# Copyright (C) 2026 David L F Gaden
"""Dependency-free local JSON-lines tool transport (not MCP or a model provider).

One request/response per line. Execution returns immediately with a job ID, so
observation and cancellation remain available while native processes are active.
"""
import json
import inspect
import sys
from .storage import load
from .execution_service import ExecutionService, PROTOCOL, error_fault
from .observations import fail

METHODS = {
    'schedule_create': 'Register caller-authorised pinned Schemaxis work for an independent schedule worker; no worker is launched.',
    'schedule_preview': 'Validate a schedule and preview its bounded upcoming occurrences without executing applications.',
    'schedule_list': 'List durable future-work declarations and their current lifecycle state.',
    'schedule_get': 'Read one schedule, revision and occurrence history.',
    'schedule_update': 'Revise a schedule at its expected revision with validation.',
    'schedule_pause': 'Pause future dispatch at the expected schedule revision.',
    'schedule_resume': 'Resume future dispatch at the expected schedule revision.',
    'schedule_cancel': 'Cancel a schedule at the expected revision.',
    'schedule_delete': 'Delete a schedule declaration at the expected revision without erasing execution artifacts.',
    'prepare_template': 'Bind an exact workflow-template case and optionally plan it; returns ordinary workflow and binding provenance without native execution.',
    'adaptor_context': 'Read bounded route guidance, editable examples, data/inspection contracts and scoped qualification.',
    'inspection_workspace': 'Read trusted view contracts or change presentation without editing a draft.',
    'inspection_resources': 'List immutable text/table snapshot resources with bounded pagination.',
    'capture_inspection': 'Capture at most one MiB of local UTF-8 text or CSV for historical inspection.',
    'snapshot_resource': 'Capture a digest-checked verified job publication with its provenance.',
    'inspect_snapshot': 'Read bounded text, CSV rows or explicitly mapped finite numeric series.',
    'reference_snapshot': 'Retain a typed text span, table range or series interval in the current snapshot.',
    'inspect_selection': 'Inspect retained evidence for a historical selection, with explicit staleness.',
    'selections': 'List typed evidence selections with current staleness and bounded pagination.',
    'workflow_graph': 'Inspect real workflow operations and artifact edges with bounded paging; no native execution.',
    'rewire_workflow': 'Replace one existing artifact handoff with full host validation and shared undo.',
    'create_workflow_design': 'Create a separate saved diagram design from a workflow, preserving the original draft.',
    'connect_workflow': 'Add a data arrow and identify closed feedback groups in one undoable revision.',
    'disconnect_workflow': 'Remove a design arrow and discard controller settings for changed feedback groups.',
    'configure_workflow_feedback': 'Save bounded feedback settings for an existing closed group; does not execute native coupling.',
    'compile_workflow_design': 'Create an ordinary host-planned workflow from an acyclic design; closed loops cannot execute yet.',
    'reference_workflow': 'Retain a typed historical authored-operation reference, not native result evidence.',
    'create_draft': 'Create a document in the shared console authoring workspace.',
    'list_drafts': 'List recoverable draft identities and revisions with bounded pagination.',
    'draft': 'Read an exact source slice and diagnostics at the expected document revision.',
    'locate_draft': 'Map a JSON pointer to a source range, or a source caret to a property value.',
    'edit_draft': 'Retain valid or invalid JSON/YAML source as one undo group; requires current revision; optional format selects syntax.',
    'patch_draft': 'Apply an atomic group of add/replace/remove/test JSON pointer edits.',
    'undo_draft': 'Undo one authored group, advancing the revision and invalidating native state.',
    'redo_draft': 'Redo one authored group at the current revision.',
    'draft_command': 'Apply a declared authoring command; native execution still uses task budgets.',
    'open_draft': 'Open a UTF-8 source file, retaining invalid drafts and its conflict baseline.',
    'write_draft': 'Save exact source with conflict detection, including recoverable invalid text.',
    'plan_draft': 'Capture the current valid draft; later draft edits block execution of this plan.',
    'create_task': 'Record caller-authorised providers, objective and fixed attempt/time budgets.',
    'list_tasks': 'Recover task identities and revisions with bounded pagination.',
    'task': 'Read current task revision, authorisation and budget usage.',
    'plan': 'Capture an ordinary authored document and host plan against an expected revision.',
    'execute': 'Start the current captured plan within authorisation and budgets; return a job ID.',
    'job': 'Read small job status without waiting for the native process.',
    'observe': 'Read bounded captured document, plan, result, verification, resources or fault evidence.',
    'cancel': 'Request cooperative process-tree cancellation, retaining authored input and partial evidence.',
    'verify': 'Recheck current artifacts and their receipts; invalidate success if verification fails.',
    'resource': 'Read a digest-checked bounded byte range from a verified publication.',
    'inspect_resource': 'Inspect a small JSON or CSV publication as bounded structured data.',
    'inspect_resource_metadata': 'Read verified output size and spatial placement metadata with bounded paging.',
    'capabilities.browse': 'Browse bounded application/category/operation summaries.',
    'capabilities.search': 'Search declarations with keywords and kind facets.',
    'capabilities.describe': 'Retrieve complete selected operation contract sections.',
    'capabilities.schema': 'Navigate exact document schema fragments.'}


def dispatch(service, request):
    if not isinstance(request, dict) or set(request)-{'id', 'method', 'params'}:
        fail('INVALID_REQUEST', 'request needs id, method and optional params')
    if type(request.get('id')) not in (str, int) or len(str(request['id'])) > 128:
        fail('INVALID_REQUEST', 'id must be a string or integer of at most 128 characters')
    method, params = request.get('method'), request.get('params', {})
    if not isinstance(params, dict):
        fail('INVALID_REQUEST', 'params must be an object')
    if method == 'methods':
        if params:
            fail('INVALID_REQUEST', 'methods accepts no parameters')
        specs = {}
        for name, description in METHODS.items():
            target = getattr(service.catalogue, name.split('.')[1]) if name.startswith('capabilities.') else getattr(service, name)
            parameters = []
            for arg in inspect.signature(target).parameters.values():
                if arg.kind == inspect.Parameter.VAR_KEYWORD:
                    parameters.append({'name': arg.name, 'paging': ['pointer', 'offset', 'limit', 'max_bytes', 'revision']})
                else:
                    info = {'name': arg.name, 'required': arg.default is inspect.Parameter.empty}
                    if arg.default is not inspect.Parameter.empty:
                        info['default'] = arg.default
                    parameters.append(info)
            specs[name] = {'description': description, 'parameters': parameters}
        return {'protocol': PROTOCOL, 'methods': specs, 'guide': 'docs/agent-service.md',
                'requestLimitBytes': 1024*1024, 'transport': 'local JSON lines; no network listener'}
    if not isinstance(method, str) or method not in METHODS:
        fail('UNKNOWN_METHOD', 'choose a declared method or request methods')
    target = getattr(service.catalogue, method.split('.')[1]) if method.startswith('capabilities.') else getattr(service, method)
    # Bind arguments before invocation, so a genuine internal TypeError is not
    # misreported as a caller's parameter error.
    try:
        inspect.signature(target).bind(**params)
    except TypeError as error:
        fail('INVALID_REQUEST', str(error))
    return target(**params)


def serve(workspace, stdin=None, stdout=None):
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout
    with ExecutionService(workspace) as service:
        while True:
            line = stdin.readline(1024*1024+1)
            if not line:
                break
            identity = None
            try:
                if len(line) > 1024*1024:
                    while line and not line.endswith(b'\n'):
                        line = stdin.readline(1024*1024+1)
                    fail('REQUEST_TOO_LARGE', 'one request must be at most one MiB')
                request = load(line.decode('utf-8'))
                if isinstance(request, dict) and type(request.get('id')) in (str, int) and len(str(request['id'])) <= 128:
                    identity = request['id']
                result = dispatch(service, request)
                response = {'id': identity, 'ok': True, 'result': result}
            except Exception as error:
                response = {'id': identity, 'ok': False, 'fault': error_fault(error)}
            stdout.write(json.dumps(response, allow_nan=False) + '\n')
            stdout.flush()
