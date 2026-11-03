# Copyright (C) 2026 David L F Gaden
"""Studio controls for the independently owned durable scheduler."""
from pathlib import Path

from .errors import fail, keys
from .scheduler import SchedulerStore


def request(app, value):
    keys(value, ('action', 'spec', 'count', 'id', 'revision', 'changes', 'document', 'documentRevision'), 'schedules')
    store = SchedulerStore(app.session.workspace/'schedules')
    action = value.get('action')
    if action == 'list':
        return {'schedules': store.list(), 'workspace': str(Path(app.session.workspace/'schedules').absolute()),
                'workerRequired': True}
    if action == 'get': return store.get(value.get('id'))
    if action in ('create', 'preview'):
        spec = value.get('spec')
        if value.get('document') is not None:
            import copy
            if not isinstance(spec, dict): fail('INVALID_SCHEDULE', 'provide a schedule declaration')
            if not isinstance(value['document'], str): fail('INVALID_SCHEDULE', 'document id must be a string')
            with app.lock:
                record = app.session._state['documents'].get(value['document'])
                if record is None: fail('UNKNOWN_DOCUMENT', 'select a saved document')
                if type(value.get('documentRevision')) is not int or record['revision'] != value.get('documentRevision'):
                    fail('STALE_REVISION', 'document changed; refresh before scheduling')
                if record.get('diagnostics'): fail('INVALID_DRAFT', 'repair the draft before scheduling')
                spec = copy.deepcopy(spec)
                spec['document'] = copy.deepcopy(record['document'])
                # The UI explicitly schedules this exact draft. The normal host
                # scope check still rejects any provider missing from this list.
                from .scheduler import required_providers
                spec['allowedProviders'] = required_providers(spec['document'])
        return store.create(spec) if action == 'create' else store.preview(spec, count=value.get('count', 5))
    if action == 'update': return store.update(value.get('id'), value.get('revision'), value.get('changes'))
    if action in ('pause', 'resume', 'cancel', 'delete'):
        return getattr(store, action)(value.get('id'), value.get('revision'))
    fail('INVALID_REQUEST', 'choose create, preview, list, get, update, pause, resume, cancel or delete')
