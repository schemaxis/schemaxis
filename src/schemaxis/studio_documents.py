"""Revision-checked Studio document lifecycle, independent of HTTP transport."""
import copy
import uuid

from . import authoring
from .console_session import CONSOLE_TYPES
from .errors import fail, keys


def document_request(app, request):
    keys(request, ('action', 'id', 'name', 'provider', 'document', 'revision', 'source', 'format'), 'documents')
    session = app.session
    action = request.get('action')
    with app.job_lock:
        if app.busy:
            fail('SESSION_BUSY', 'wait for the current native operation to finish')
        with app.lock:
            if action == 'new':
                provider = request.get('provider')
                if provider not in CONSOLE_TYPES:
                    fail('UNKNOWN_PROVIDER', 'choose a registered adaptor or workflow type', 'provider',
                         providers=sorted(CONSOLE_TYPES))
                initial = request.get('document')
                source = request.get('source')
                # Validate before creating, so a failed request leaves no orphan document.
                if source is not None:
                    authoring.analyse(source, lambda value: session._validate(value, provider), request.get("format", "json"))
                elif initial is not None:
                    session._validate(initial, provider)
                session.new(request.get('name') or provider.title(), provider)
                if source is not None:
                    session.edit_source(source, session.active_document, session._record['revision'], request.get('format', 'json'))
                elif initial is not None:
                    session._edit(initial)
            elif action == 'activate':
                app.focus(request.get('id'))
            elif action in ('rename', 'duplicate', 'close'):
                identity = request.get('id')
                if identity not in session._state['documents']:
                    fail('UNKNOWN_DOCUMENT', 'document is not in this workspace', 'id')
                record = session._state['documents'][identity]
                authoring.check(record, identity, identity, request.get('revision'))
                state = copy.deepcopy(session._state)
                if action == 'close':
                    if len(state['documents']) == 1:
                        fail('LAST_DOCUMENT', 'create another document before closing the last one')
                    # Close only this document's native client; do not delete files or run evidence.
                    runtime = session._runtimes.get(identity, {})
                    if runtime.get('client'):
                        runtime['client'].close()
                    session._runtimes.pop(identity, None)
                    del state['documents'][identity]
                    if state['activeDocument'] == identity:
                        state['activeDocument'] = next(iter(state['documents']))
                else:
                    name = request.get('name') or (record['name'] + ' copy' if action == 'duplicate' else '')
                    if not isinstance(name, str) or not name.strip():
                        fail('INVALID_DOCUMENT', 'provide a document name', 'name')
                    state['nextRevision'] += 1
                    if action == 'duplicate':
                        identity = str(uuid.uuid4())
                        state['documents'][identity] = copy.deepcopy(record)
                        state['documents'][identity].update(file=None, undo=[], redo=[], checkpoints=[], attempts=[])
                        state['activeDocument'] = identity
                    state['documents'][identity].update(name=name.strip(), revision=state['nextRevision'])
                session._commit(state)
                app.refresh_snapshot()
                if action == 'close':
                    return {'closed': identity, 'activeDocument': session.active_document}
                return app.document(identity)
            else:
                fail('INVALID_REQUEST', 'choose new, activate, rename, duplicate or close', 'action')
            app.refresh_snapshot()
            return app.document(session.active_document)
