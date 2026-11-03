# Copyright (C) 2026 David L F Gaden
"""Bounded durable triggers over the existing verified execution service.

Control clients lock only the state transaction. A separate foreground owner runs
occurrences; transport disconnection therefore has no effect on scheduled work.
"""
import copy
from datetime import datetime, timedelta, timezone
import fcntl
import math
from pathlib import Path
import threading
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .storage import atomic, encoded, load, digest
from .observations import fail
from .execution_service import ExecutionService, DEFAULT_BUDGET, TERMINAL, error_fault

UTC = timezone.utc


def required_providers(document):
    return ExecutionService._providers(document)


def instant(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError('offset required')
        return dt.timestamp()
    except (ValueError, TypeError, AttributeError, OverflowError):
        fail('INVALID_SCHEDULE', 'time must be ISO 8601 with an explicit UTC offset')


def iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat().replace('+00:00', 'Z')


def next_due(trigger, after, inclusive=False):
    """Calendar gaps are skipped; repeated wall times use their first occurrence."""
    start = instant(trigger['at'] if trigger['kind'] == 'once' else trigger['start'])
    minimum = max(start, after if inclusive else after + 0.000001)
    if trigger['kind'] == 'once':
        return start if start >= minimum else None
    if trigger['kind'] == 'interval':
        steps = max(0, math.ceil((minimum-start)/trigger['seconds']))
        candidate = start + steps*trigger['seconds']
        return candidate if candidate <= 253402300799 else None
    zone = ZoneInfo(trigger['timezone'])
    day = datetime.fromtimestamp(minimum, zone).date()
    for offset in range(370):
        try:
            date = day + timedelta(days=offset)
        except OverflowError:
            return None
        if date.weekday() not in trigger['weekdays']:
            continue
        local = datetime(date.year, date.month, date.day, trigger['hour'], trigger['minute'], tzinfo=zone)
        candidate = local.timestamp()
        roundtrip = datetime.fromtimestamp(candidate, zone)
        if (roundtrip.hour, roundtrip.minute, roundtrip.date()) != (local.hour, local.minute, local.date()):
            continue
        if candidate >= minimum:
            return candidate
    fail('INVALID_SCHEDULE', 'calendar trigger has no upcoming occurrence')


def validate(spec):
    if not isinstance(spec, dict):
        fail('INVALID_SCHEDULE', 'schedule must be an object')
    spec = copy.deepcopy(spec)
    allowed = {'document', 'objective', 'allowedProviders', 'budget', 'trigger', 'overlap', 'misfire',
               'maxOccurrences', 'expiresAt', 'maxCatchUp', 'graceSeconds', 'maxRetries'}
    if set(spec)-allowed:
        fail('INVALID_SCHEDULE', 'unknown schedule fields', fields=sorted(set(spec)-allowed))
    if not isinstance(spec.get('document'), dict) or len(encoded(spec['document'])) > 1024*1024:
        fail('INVALID_SCHEDULE', 'pin a document object no larger than one MiB')
    objective = spec.get('objective')
    if not isinstance(objective, str) or not objective.strip() or len(objective) > 2000:
        fail('INVALID_SCHEDULE', 'provide a nonempty objective of at most 2000 characters')
    from .adaptors import registry
    providers = spec.get('allowedProviders')
    if not isinstance(providers, list) or not providers or any(not isinstance(p, str) or p not in registry.ADAPTORS for p in providers):
        fail('INVALID_AUTHORISATION', 'supply registered providers authorised by the caller')
    used = ExecutionService._providers(spec['document'])
    if set(used)-set(providers):
        fail('SCOPE_EXCEEDED', 'document exceeds scheduled provider authorisation')
    # Planning is host-only; reject invalid executable documents before registration.
    from . import workflow
    if spec['document'].get('version') == 'schemaxis.workflow/1':
        workflow.inspect_plan(spec['document'])
    else:
        registry.plan(spec['document'])
    budget = spec.get('budget', {})
    if not isinstance(budget, dict) or set(budget)-set(DEFAULT_BUDGET):
        fail('INVALID_BUDGET', 'unknown task budget fields')
    spec['budget'] = {**DEFAULT_BUDGET, **budget}
    for key, value in spec['budget'].items():
        if key in ('maxAttempts', 'maxRepeatedFailures'):
            valid = type(value) is int and 1 <= value <= 100
        else:
            valid = type(value) in (int, float) and math.isfinite(value) and 0 < value <= 86400
        if not valid:
            fail('INVALID_BUDGET', 'invalid occurrence budget', field=key)
    trigger = spec.get('trigger')
    if not isinstance(trigger, dict):
        fail('INVALID_SCHEDULE', 'provide a trigger object')
    kind = trigger.get('kind')
    fields = {'once': {'kind', 'at'}, 'interval': {'kind', 'start', 'seconds'},
              'calendar': {'kind', 'start', 'timezone', 'hour', 'minute', 'weekdays'}}
    if not isinstance(kind, str) or kind not in fields or set(trigger) != fields[kind]:
        fail('INVALID_SCHEDULE', 'trigger fields do not match once, interval or calendar contract')
    instant(trigger['at'] if kind == 'once' else trigger['start'])
    if kind == 'interval' and (type(trigger['seconds']) not in (int, float) or not math.isfinite(trigger['seconds']) or not 1 <= trigger['seconds'] <= 3155760000):
        fail('INVALID_SCHEDULE', 'interval seconds must be finite and at least one')
    if kind == 'calendar':
        try:
            ZoneInfo(trigger['timezone'])
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            fail('INVALID_SCHEDULE', 'calendar timezone must be a known IANA zone')
        if (type(trigger['hour']) is not int or not 0 <= trigger['hour'] <= 23
                or type(trigger['minute']) is not int or not 0 <= trigger['minute'] <= 59
                or not isinstance(trigger['weekdays'], list) or not trigger['weekdays']
                or any(type(day) is not int or not 0 <= day <= 6 for day in trigger['weekdays'])):
            fail('INVALID_SCHEDULE', 'invalid calendar clock or weekdays (Monday=0)')
    for field, default, choices in [('overlap', 'queue', {'queue', 'skip', 'coalesce'}),
                                   ('misfire', 'runOnce', {'skip', 'runOnce', 'catchUp'})]:
        spec.setdefault(field, default)
        if not isinstance(spec[field], str) or spec[field] not in choices:
            fail('INVALID_SCHEDULE', 'invalid '+field+' policy')
    for field, default, maximum in [('maxOccurrences', 100, 100000), ('maxCatchUp', 10, 100)]:
        spec.setdefault(field, default)
        if type(spec[field]) is not int or not 1 <= spec[field] <= maximum:
            fail('INVALID_SCHEDULE', field+' is outside its bounded range')
    spec.setdefault('maxRetries', 0)
    if type(spec['maxRetries']) is not int or not 0 <= spec['maxRetries'] < spec['budget']['maxAttempts']:
        fail('INVALID_SCHEDULE', 'maxRetries must be nonnegative and below occurrence maxAttempts')
    spec.setdefault('graceSeconds', 60)
    if type(spec['graceSeconds']) not in (int, float) or not math.isfinite(spec['graceSeconds']) or not 0 <= spec['graceSeconds'] <= 86400:
        fail('INVALID_SCHEDULE', 'graceSeconds must be finite and between zero and 86400')
    if spec.get('expiresAt') is not None:
        instant(spec['expiresAt'])
    return spec


class SchedulerStore:
    """Short-lived control client, safe while the runner owns its separate lock."""
    def __init__(self, workspace):
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.RLock()

    def _transaction(self, function, write=False):
        with self._thread_lock, (self.workspace/'scheduler-state.lock').open('a+b') as owner:
            fcntl.flock(owner, fcntl.LOCK_EX)
            path = self.workspace/'scheduler.json'
            if path.exists():
                try:
                    envelope = load(path.read_text())
                    state = envelope['state']
                    if envelope['version'] != 1 or envelope['digest'] != digest(state) or set(state) != {'schedules', 'occurrences'}:
                        raise ValueError('invalid state')
                    for identity, record in state['schedules'].items():
                        if (identity != record['id'] or type(record['revision']) is not int or record['revision'] < 1
                                or record['status'] not in {'active', 'paused', 'cancelled', 'completed'}
                                or type(record['generated']) is not int or record['generated'] < 0
                                or not isinstance(record['spec'], dict)
                                or digest(record['spec']['document']) != record['documentDigest']
                                or (record['nextDue'] is not None and (type(record['nextDue']) not in (int, float)
                                    or not math.isfinite(record['nextDue'])))):
                            raise ValueError('invalid schedule')
                    for identity, record in state['occurrences'].items():
                        if (identity != record['id'] or record['schedule'] not in state['schedules']
                                or record['status'] not in TERMINAL | {'queued', 'running', 'skipped'}
                                or type(record['dueAt']) not in (int, float) or not math.isfinite(record['dueAt'])
                                or not isinstance(record['spec'], dict)
                                or digest(record['spec']['document']) != record['documentDigest']):
                            raise ValueError('invalid occurrence')
                except Exception as error:
                    fail('SCHEDULER_RECOVERY_FAILED', 'scheduler state is corrupt; preserve it for recovery', detail=str(error))
            else:
                state = {'schedules': {}, 'occurrences': {}}
            result = function(state)
            if write:
                atomic(path, encoded({'version': 1, 'state': state, 'digest': digest(state)}))
            return copy.deepcopy(result)

    def preview(self, spec, count=5, now=None):
        spec = validate(spec)
        if type(count) is not int or not 1 <= count <= 100:
            fail('INVALID_SCHEDULE', 'preview count must be 1..100')
        due = next_due(spec['trigger'], time.time() if now is None else now, True)
        result = []
        for _ in range(min(count, spec['maxOccurrences'])):
            if due is None or (spec.get('expiresAt') and due > instant(spec['expiresAt'])):
                break
            result.append(iso(due))
            due = next_due(spec['trigger'], due)
        return {'documentDigest': digest(spec['document']), 'upcoming': result, 'spec': spec}

    def create(self, spec):
        spec = validate(spec)
        identity = 'schedule-'+uuid.uuid4().hex
        first = next_due(spec['trigger'], instant(spec['trigger'].get('at', spec['trigger'].get('start'))), True)
        record = {'id': identity, 'revision': 1, 'status': 'active', 'spec': spec,
                  'documentDigest': digest(spec['document']), 'nextDue': first, 'generated': 0, 'createdAt': time.time()}
        def operation(state):
            state['schedules'][identity] = record
            return record
        return self._transaction(operation, True)

    def list(self):
        return self._transaction(lambda state: list(state['schedules'].values()))

    def get(self, identity):
        if not isinstance(identity, str):
            fail('INVALID_SCHEDULE', 'schedule id must be a string')
        def operation(state):
            if identity not in state['schedules']:
                fail('UNKNOWN_SCHEDULE', 'schedule is absent')
            return {**state['schedules'][identity], 'occurrences': [o for o in state['occurrences'].values() if o['schedule'] == identity]}
        return self._transaction(operation)

    def update(self, identity, expected_revision, changes):
        if not isinstance(changes, dict):
            fail('INVALID_SCHEDULE', 'changes must be an object')
        def operation(state):
            record = self._checked(state, identity, expected_revision)
            if any(o['schedule'] == identity and o['status'] in {'queued', 'running'} for o in state['occurrences'].values()):
                fail('SCHEDULE_BUSY', 'finish or cancel pending occurrences before revising')
            spec = validate({**record['spec'], **changes})
            record.update(spec=spec, documentDigest=digest(spec['document']), revision=record['revision']+1,
                          generated=0, nextDue=next_due(spec['trigger'], time.time(), True), status='active')
            return record
        return self._transaction(operation, True)

    @staticmethod
    def _checked(state, identity, revision):
        if not isinstance(identity, str):
            fail('INVALID_SCHEDULE', 'schedule id must be a string')
        if identity not in state['schedules']:
            fail('UNKNOWN_SCHEDULE', 'schedule is absent')
        record = state['schedules'][identity]
        if type(revision) is not int or revision != record['revision']:
            fail('STALE_REVISION', 'schedule revision changed', currentRevision=record['revision'])
        return record

    def _status(self, identity, expected_revision, status):
        def operation(state):
            record = self._checked(state, identity, expected_revision)
            if record['status'] == 'cancelled' or (record['status'] == 'completed' and status != 'cancelled'):
                fail('SCHEDULE_TERMINAL', 'create a new schedule or revise its specification')
            record.update(status=status, revision=record['revision']+1)
            if status == 'cancelled':
                for occurrence in state['occurrences'].values():
                    if occurrence['schedule'] == identity and occurrence['status'] == 'queued':
                        occurrence['status'] = 'cancelled'
            return record
        return self._transaction(operation, True)

    def pause(self, identity, expected_revision):
        return self._status(identity, expected_revision, 'paused')

    def resume(self, identity, expected_revision):
        return self._status(identity, expected_revision, 'active')

    def cancel(self, identity, expected_revision):
        return self._status(identity, expected_revision, 'cancelled')

    def delete(self, identity, expected_revision):
        def operation(state):
            self._checked(state, identity, expected_revision)
            if any(o['schedule'] == identity and o['status'] in {'running', 'queued'} for o in state['occurrences'].values()):
                fail('SCHEDULE_BUSY', 'cancel and finish pending occurrences before deletion')
            del state['schedules'][identity]
            state['occurrences'] = {k: v for k, v in state['occurrences'].items() if v['schedule'] != identity}
            return {'deleted': identity, 'executionEvidenceRetained': True}
        return self._transaction(operation, True)


class SchedulerRunner:
    """Single independent owner with serial verified occurrences and durable claims."""
    def __init__(self, workspace, *, locations=None, service_factory=ExecutionService):
        self.store = SchedulerStore(workspace)
        self.locations = locations
        self.service_factory = service_factory
        self._owner = (self.store.workspace/'scheduler-owner.lock').open('a+b')
        try:
            fcntl.flock(self._owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._owner.close()
            fail('SCHEDULER_LOCKED', 'another scheduler runner owns this workspace')
        self.active = None
        self.closed = False
        def recover(state):
            for occurrence in state['occurrences'].values():
                if occurrence['status'] == 'running':
                    occurrence.update(status='interrupted', verified=False, nativeState='unknown',
                                      fault={'code': 'INTERRUPTED', 'message': 'previous scheduler owner exited; execution was not repeated'})
        try:
            self.store._transaction(recover, True)
        except Exception:
            self._owner.close()
            self.closed = True
            raise

    def tick(self, now=None):
        if self.closed:
            fail('SCHEDULER_CLOSED', 'open a new scheduler owner')
        now = time.time() if now is None else now
        if type(now) not in (int, float) or not math.isfinite(now):
            fail('INVALID_SCHEDULE', 'clock instant must be finite')
        if self.active:
            identity, service, job = self.active
            record = service.job(job)
            cancelled = self.store.get(identity.split(':')[0])['status'] == 'cancelled'
            if cancelled and record['status'] not in TERMINAL:
                service.cancel(job)
            if record['status'] == 'failed' and not cancelled:
                occurrence = self.store._transaction(lambda state: state['occurrences'][identity])
                if occurrence.get('retries', 0) < occurrence['spec']['maxRetries']:
                    def retry_claim(state):
                        state['occurrences'][identity]['retries'] = occurrence.get('retries', 0)+1
                    self.store._transaction(retry_claim, True)
                    try:
                        retried = service.execute(occurrence['plan'], service.task(occurrence['task'])['revision'])
                        self.store._transaction(lambda state: state['occurrences'][identity].update(job=retried['id']), True)
                        self.active = identity, service, retried['id']
                        record = service.job(retried['id'])
                    except Exception as error:
                        record = {**record, 'fault': error_fault(error)}
            if record['status'] in TERMINAL:
                def finish(state):
                    state['occurrences'][identity].update(status=record['status'], verified=record.get('verified', False),
                                                         finishedAt=now, fault=record.get('fault') or ({'code': record['faultCode']} if record.get('faultCode') else None))
                self.store._transaction(finish, True)
                service.close()
                self.active = None
        def collect(state):
            for schedule in state['schedules'].values():
                if schedule['status'] != 'active':
                    continue
                spec = schedule['spec']
                due = schedule['nextDue']
                expiry = instant(spec['expiresAt']) if spec.get('expiresAt') else None
                if expiry is not None and now > expiry:
                    schedule['status'] = 'completed'
                    for queued in state['occurrences'].values():
                        if queued['schedule'] == schedule['id'] and queued['status'] == 'queued':
                            queued['status'] = 'skipped'
                    continue
                pending = [o for o in state['occurrences'].values() if o['schedule'] == schedule['id'] and o['status'] in {'queued', 'running'}]
                generated = 0
                while due is not None and due <= now and schedule['generated'] < spec['maxOccurrences'] and generated < spec['maxCatchUp']:
                    stale = now-due > spec['graceSeconds']
                    identity = schedule['id']+':'+str(schedule['revision'])+':'+str(round(due*1000000))
                    skip = (stale and spec['misfire'] == 'skip') or (bool(pending) and spec['overlap'] == 'skip')
                    if pending and spec['overlap'] == 'coalesce':
                        skip = any(o['status'] == 'queued' for o in pending)
                    occurrence = {'id': identity, 'schedule': schedule['id'], 'revision': schedule['revision'],
                                  'dueAt': due, 'status': 'skipped' if skip else 'queued', 'spec': copy.deepcopy(spec),
                                  'documentDigest': schedule['documentDigest']}
                    state['occurrences'][identity] = occurrence
                    if not skip:
                        pending.append(occurrence)
                    schedule['generated'] += 1
                    generated += 1
                    if stale and spec['misfire'] in {'skip', 'runOnce'}:
                        due = next_due(spec['trigger'], now)
                    else:
                        due = next_due(spec['trigger'], due)
                schedule['nextDue'] = due
                if due is None or schedule['generated'] >= spec['maxOccurrences']:
                    schedule['status'] = 'completed'
            if self.active:
                return None
            for queued in state['occurrences'].values():
                expiry = queued['spec'].get('expiresAt')
                if queued['status'] == 'queued' and expiry and now > instant(expiry):
                    queued['status'] = 'skipped'
            queued = sorted((o for o in state['occurrences'].values() if o['status'] == 'queued'
                             and state['schedules'][o['schedule']]['status'] in {'active', 'completed'}), key=lambda o: o['dueAt'])
            if not queued:
                return None
            occurrence = queued[0]
            occurrence.update(status='running', claimedAt=now, verified=False)
            return occurrence
        occurrence = self.store._transaction(collect, True)
        if occurrence:
            service = None
            try:
                workspace = self.store.workspace/'occurrences'/occurrence['id'].replace(':', '_')
                service = self.service_factory(workspace, locations=self.locations)
                spec = occurrence['spec']
                task = service.create_task(spec['objective'], spec['allowedProviders'], spec['budget'])
                plan = service.plan(task['id'], spec['document'], task['revision'])
                def started(state):
                    current = state['schedules'][occurrence['schedule']]
                    captured = state['occurrences'][occurrence['id']]
                    if current['status'] in {'cancelled', 'paused'}:
                        captured['status'] = 'cancelled' if current['status'] == 'cancelled' else 'queued'
                        return None
                    job = service.execute(plan['id'], plan['revision'])
                    captured.update(task=task['id'], plan=plan['id'], job=job['id'], workspace=str(workspace))
                    return job
                job = self.store._transaction(started, True)
                if job is None:
                    service.close()
                else:
                    self.active = occurrence['id'], service, job['id']
            except Exception as error:
                def failed(state):
                    state['occurrences'][occurrence['id']].update(status='failed', verified=False, fault=error_fault(error), finishedAt=now)
                self.store._transaction(failed, True)
                if service:
                    service.close()
        return {'activeOccurrence': self.active[0] if self.active else None}

    def serve(self, stop_event=None, poll_seconds=1):
        if not 0.05 <= poll_seconds <= 60:
            fail('INVALID_SCHEDULE', 'poll_seconds must be 0.05..60')
        stop_event = stop_event or threading.Event()
        try:
            while not stop_event.is_set():
                self.tick()
                stop_event.wait(poll_seconds)
        finally:
            self.close()

    def close(self):
        if self.closed:
            return
        if self.active:
            identity, service, job = self.active
            service.close()
            def interrupted(state):
                state['occurrences'][identity].update(status='interrupted', verified=False, nativeState='unknown')
            self.store._transaction(interrupted, True)
            self.active = None
        self._owner.close()
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
