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

from .service_contracts import METHODS, target_for


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
            target = target_for(service, name)
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
    target = target_for(service, method)
    # Bind arguments before invocation, so a genuine internal TypeError is not
    # misreported as a caller's parameter error.
    try:
        inspect.signature(target).bind(**params)
    except TypeError as error:
        fail('INVALID_REQUEST', str(error))
    if method == 'execute':
        # Packages are captured as ordinary documents. Recheck their immutable
        # archive identity before dispatch through either transport.
        with service.lock:
            identity = params.get('plan_id')
            captured = service.state['plans'].get(identity) if isinstance(identity, str) else None
            if captured and captured.get('package'):
                from .tool_packages import PackageStore
                provenance = captured['package']
                PackageStore(service.workspace).resolve(provenance['digest'], values=provenance['values'])
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
