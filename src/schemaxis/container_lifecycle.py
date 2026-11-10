"""Durable engine ownership intents, reconciled under the service owner lock."""
import copy
from pathlib import Path
import re
import time

from .storage import atomic, encoded, load, digest
from .core.faults import Fault, SchemaxisError


def refused(message):
    raise SchemaxisError(Fault('ISOLATION_RECOVERY_FAILED', message, '$', 'isolation'))


class LifecycleJournal:
    def __init__(self, workspace):
        self.workspace = Path(workspace)
        self.root = self.workspace/'container-lifecycle'
        if self.root.is_symlink():
            refused('container lifecycle directory is a symlink')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, nonce):
        if not isinstance(nonce, str) or not re.fullmatch('[0-9a-f]{32}', nonce):
            refused('invalid container lifecycle nonce')
        path = self.root/(nonce+'.json')
        if path.is_symlink():
            refused('container lifecycle record is a symlink')
        return path

    def _write(self, record, *, exclusive=False):
        atomic(self._path(record['nonce']), encoded({'version': 1,
            'record': record, 'sha256': digest(record)}), exclusive=exclusive)

    def begin(self, *, name, nonce, request, action, image, deadline):
        record = {'name': name, 'nonce': nonce, 'jobId': request.job_id,
            'planId': request.plan_id, 'action': action, 'image': image,
            'deadlineMonotonic': deadline,
            'deadlineUnix': time.time()+max(0, deadline-time.monotonic()),
            'createdAt': time.time(), 'containerId': None, 'state': 'intent'}
        if request.operation_id is not None:
            record['operationId'] = request.operation_id
        if action == 'plan':
            record['planningPhase'] = request.planning_phase
        self._write(record, exclusive=True)
        return record

    def update(self, record, **changes):
        updated = {**copy.deepcopy(record), **copy.deepcopy(changes), 'updatedAt': time.time()}
        self._write(updated)
        record.clear()
        record.update(updated)

    def pending(self, *, include_cleaned_plans=False):
        result = []
        for index, path in enumerate(self.root.iterdir()):
            if index >= 10000:
                refused('container lifecycle recovery inventory exceeds its bound')
            if not path.name.endswith('.json'):
                # Atomic storage scratch is not an ownership record.
                continue
            nonce = path.stem
            if path != self._path(nonce) or not path.is_file() or path.stat().st_size > 65536:
                refused('container lifecycle record is not a bounded regular file')
            value = load(path.read_text())
            record = value.get('record')
            if (value.get('version') != 1 or not isinstance(record, dict)
                    or value.get('sha256') != digest(record) or record.get('nonce') != nonce
                    or record.get('name') != 'schemaxis-'+nonce
                    or record.get('action') not in ('plan', 'run', 'verify')
                    or (record.get('action') == 'plan' and (
                        not isinstance(record.get('operationId'), str) or not record['operationId']
                        or len(record['operationId']) > 256
                        or record.get('planningPhase') not in ('capture', 'stale-check')))
                    or record.get('state') not in ('intent', 'created', 'cleaned', 'cleanup-unknown')
                    or not isinstance(record.get('jobId'), str)
                    or not isinstance(record.get('planId'), str)
                    or (record.get('containerId') is not None and not re.fullmatch(
                        '[0-9a-f]{64}', str(record.get('containerId'))))):
                refused('container lifecycle record failed its integrity checks')
            if record['state'] != 'cleaned':
                result.append(record)
            elif record.get('containerId') is None:
                refused('a cleaned intent without an observed container ID cannot exclude delayed creation')
            elif include_cleaned_plans and record['action'] == 'plan' and isinstance(record.get('isolation'), dict):
                # This preserves attributable observations across the gap before
                # the service commits its operation; it never restores success.
                result.append(record)
        return result
