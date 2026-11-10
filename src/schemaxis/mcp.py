"""Dependency-free MCP stdio dispatcher over the shared declared service tools.

Supports modern 2026-07-28 and legacy 2025-11-25 stdio profiles. Application
execution remains in ExecutionService; this module never imports native apps.
"""
import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import sys
import threading
import uuid

from .agent_transport import dispatch as agent_dispatch
from .capabilities import digest
from .execution_service import ExecutionService, error_fault
from .mcp_admission import FileAdmission
from .mcp_resources import PAGE, ResponseStore
from .observations import fail
from .service_contracts import CONTROL, ToolCatalogue
from .storage import encoded, load

MODERN = '2026-07-28'
LEGACY = '2025-11-25'
MAX_REQUEST = 1024 * 1024
MAX_RESPONSE = 256 * 1024
STRICT_METHODS = frozenset({'methods', 'create_task', 'list_tasks', 'task', 'plan',
    'execute', 'job', 'observe', 'cancel', 'verify', 'resource', 'inspect_resource',
    'inspect_resource_metadata', 'run_tool', 'adaptor_context',
    'capabilities.browse', 'capabilities.search', 'capabilities.describe', 'capabilities.schema'})


class ProtocolError(Exception):
    def __init__(self, code, message, data=None):
        self.code, self.message, self.data = code, message, data
        super().__init__(message)


@dataclass(frozen=True)
class RequestContext:
    """Trusted host-provided ownership; never constructed from request JSON."""
    principal: str
    namespace: str
    service: object
    allowed_methods: object = None


def _depth(value):
    pending = [(value, 0)]
    while pending:
        current, level = pending.pop()
        if level > 64:
            raise ProtocolError(-32600, 'JSON nesting exceeds 64 levels')
        if isinstance(current, dict):
            pending.extend((child, level+1) for child in current.values())
        elif isinstance(current, list):
            pending.extend((child, level+1) for child in current)


def parse_message(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    if len(data) > MAX_REQUEST:
        raise ProtocolError(-32600, 'request exceeds one MiB')
    try:
        message = load(data.decode('utf-8'))
    except Exception:
        raise ProtocolError(-32700, 'invalid UTF-8 JSON') from None
    _depth(message)
    if not isinstance(message, dict):
        raise ProtocolError(-32600, 'one JSON-RPC object is required; batches are unsupported')
    return message


class McpDispatcher:
    def __init__(self, service, *, profile='declared-documents', admission=None,
                 store=None, server_info=None, input_store=None):
        if profile not in {'declared-documents', 'trusted-local'}:
            raise ValueError('unknown MCP admission profile')
        self.service, self.profile = service, profile
        self.admission = admission or FileAdmission()
        self.store = store or ResponseStore(service.workspace)
        self.catalogue = ToolCatalogue(service)
        self.input_store = input_store
        self.input_methods = frozenset()
        if input_store is not None:
            from .mcp_inputs import LocalInputs
            from .service_contracts import ToolSpec
            if (type(input_store) is not LocalInputs or not getattr(service.executor, 'isolated', False)
                    or service.executor.capture_policy is not input_store.policy):
                raise ValueError('Local inputs require the same explicitly isolated capture policy')
            definitions = {
                'inputs_list': ('List operator-provided immutable input identities for this local task; no source paths or bytes.', ['task_id'], 'read'),
                'input_from_resource': ('Explicitly capture a freshly verified publication as an immutable input for another local task; no paths accepted.', ['task_id', 'resource_id'], 'mutate')}
            self.input_methods = frozenset(definitions)
            for name, (summary, names, effect) in definitions.items():
                spec = ToolSpec(name, summary, {'type': 'object', 'properties': {n: {'type': 'string'} for n in names},
                    'required': names, 'additionalProperties': False}, effect)
                self.catalogue.specs[name] = spec
                self.catalogue.by_name[name] = spec
        if server_info is None:
            from .__main__ import project_version
            server_info = {'name': 'schemaxis', 'version': project_version()}
        self.server_info = server_info
        self.era = None
        self.initialized = False
        self.state_lock = threading.RLock()
        self.active = set()
        self.cancelled = set()
        self.local_context = RequestContext('local', self.store.namespace, service)

    @staticmethod
    def _error(identity, error):
        value = {'code': error.code, 'message': error.message}
        if error.data is not None:
            value['data'] = error.data
        return {'jsonrpc': '2.0', 'id': identity, 'error': value}

    def _metadata(self, params, binding):
        metadata = params.get('_meta', {})
        if not isinstance(metadata, dict):
            raise ProtocolError(-32602, '_meta must be an object')
        version = metadata.get('io.modelcontextprotocol/protocolVersion')
        if version is not None:
            if version != MODERN:
                raise ProtocolError(-32022, 'Unsupported protocol version',
                    {'supported': [MODERN] if binding == 'http' else [MODERN, LEGACY], 'requested': version})
            if not isinstance(metadata.get('io.modelcontextprotocol/clientCapabilities'), dict):
                raise ProtocolError(-32602, 'modern clientCapabilities metadata is required')
            if 'io.modelcontextprotocol/clientInfo' in metadata:
                info = metadata['io.modelcontextprotocol/clientInfo']
                if not isinstance(info, dict) or any(not isinstance(info.get(key), str) for key in ('name', 'version')):
                    raise ProtocolError(-32602, 'clientInfo metadata needs string name and version')
            if binding == 'stdio' and self.era == LEGACY:
                raise ProtocolError(-32602, 'this stdio process uses the legacy profile')
            if binding == 'stdio':
                self.era = MODERN
            return MODERN
        if binding == 'http' or self.era != LEGACY or not self.initialized:
            raise ProtocolError(-32602, 'modern protocolVersion and clientCapabilities metadata are required')
        return LEGACY

    def _check_context(self, context):
        if (context is None or not isinstance(context, RequestContext) or not context.principal
                or context.service is not self.service or context.namespace != self.store.namespace):
            raise ProtocolError(-32602, 'request has no authorised service ownership')

    def _permitted(self, method, context):
        return ((self.profile == 'trusted-local' or method in STRICT_METHODS or method in self.input_methods)
                and (context.allowed_methods is None or method in context.allowed_methods))

    def _admit(self, method, arguments):
        if self.profile == 'trusted-local':
            return
        if method == 'plan':
            if arguments.get('bindings'):
                fail('MCP_POLICY_DENIED', 'use opaque immutable input identities, not authored filesystem bindings')
            if self.input_store is not None:
                return self.input_store.resolve(self.service, arguments.get('task_id'),
                    arguments.get('document'), self.admission)
            self.admission.check(arguments.get('document'))
        elif method in {'execute', 'verify'}:
            if not getattr(self.service.executor, 'isolated', False):
                fail('ISOLATION_UNAVAILABLE', 'strict MCP execution requires explicitly configured qualified worker images')
            with self.service.lock:
                if method == 'execute':
                    plan = self.service._get('plans', arguments.get('plan_id'))
                else:
                    job = self.service._get('jobs', arguments.get('job_id'))
                    plan = self.service._get('plans', job['plan'])
                document = self.service._read(plan['document'])
                inputs = self.service._input_bindings(plan)
                if inputs is None:
                    self.admission.check(document)
                else:
                    self.admission.check(document, context=inputs, bound=True)
                if plan.get('resources') or plan.get('bindings') or inputs is not None and self.input_store is None:
                    fail('MCP_POLICY_DENIED', 'strict file-free admission has no external input bindings')
        elif method == 'run_tool':
            if arguments.get('execute') and not getattr(self.service.executor, 'isolated', False):
                fail('ISOLATION_UNAVAILABLE', 'strict MCP package execution requires qualified worker images')
            from .tool_packages import PackageStore
            package = PackageStore(self.service.workspace).resolve(arguments.get('package_digest'),
                values=arguments.get('values'))
            self.admission.check(package['prepared']['document'])

    def _complete(self, result, version, *, cacheable=False):
        if version == MODERN:
            result = {**result, 'resultType': 'complete',
                      '_meta': {'io.modelcontextprotocol/serverInfo': self.server_info}}
            if cacheable:
                result.update(cacheScope='private', ttlMs=0)
        return result

    def _tool_result(self, carrier, version, *, reserved=False, control=False):
        def inline(value):
            return self._complete({'content': [{'type': 'text', 'text': encoded(value).decode()}],
                'structuredContent': value, 'isError': not value['ok']}, version)
        result = inline(carrier)
        if len(encoded(result)) + 512 <= MAX_RESPONSE:
            return result
        if not carrier['ok']:
            # Full large fault is retained just like a large successful value.
            value = carrier
        else:
            value = carrier['result']
        try:
            reference = self.store.capture(value, reserved=reserved)
        except Exception as error:
            details = {'outcome': 'committed-result-unavailable' if control or reserved else 'result-unavailable'}
            original = carrier.get('result')
            if isinstance(original, dict):
                details['control'] = {key: original[key] for key in
                    ('id', 'task', 'plan', 'revision', 'status', 'verified', 'nativeState')
                    if key in original and len(encoded(original[key])) <= 2048}
            fault = error_fault(error)
            fault['observed'] = {**fault.get('observed', {}), **details}
            return inline({'ok': False, 'fault': fault})
        deferred = {'ok': carrier['ok'], 'resultResource': reference}
        if not carrier['ok']:
            deferred['fault'] = {'code': carrier['fault'].get('code', 'EXECUTION_ERROR'),
                'message': 'Complete fault retained in resultResource'}
        result = inline(deferred)
        result['content'].append({'type': 'resource_link', 'uri': reference['uri'],
            'name': 'Complete service result', 'mimeType': 'application/json'})
        return result

    def _call(self, params, version, context):
        if set(params) - {'name', 'arguments', '_meta'} or not isinstance(params.get('name'), str):
            raise ProtocolError(-32602, 'tools/call requires a name and optional arguments object')
        arguments = params.get('arguments', {})
        if not isinstance(arguments, dict):
            raise ProtocolError(-32602, 'tool arguments must be an object')
        spec = self.catalogue.by_name.get(params['name'])
        if spec is None:
            raise ProtocolError(-32602, 'Unknown tool: '+params['name'])
        reserved = False
        try:
            if not self._permitted(spec.method, context):
                fail('MCP_POLICY_DENIED', 'method is unavailable in the current admission profile', method=spec.method)
            inputs = self._admit(spec.method, arguments)
            if spec.effect == 'mutate' and spec.method not in CONTROL:
                self.store.reserve()
                reserved = True
            # ExecutionService owns revision locks. Avoid a wrapper lock around
            # native verification: cancel/status must remain independently callable.
            if spec.method in self.input_methods:
                expected = set(spec.input_schema['required'])
                if set(arguments) != expected or any(type(v) is not str for v in arguments.values()):
                    fail('INVALID_REQUEST', 'use the declared input tool arguments')
                value = (self.input_store.list(self.service, arguments['task_id']) if spec.method == 'inputs_list'
                    else self.input_store.promote(self.service, **arguments))
            elif spec.method == 'plan' and self.input_store is not None and self.profile == 'declared-documents':
                if set(arguments)-{'task_id', 'document', 'expected_revision', 'bindings'}:
                    fail('INVALID_REQUEST', 'use the declared planning arguments')
                value = self.service.plan_with_inputs(arguments.get('task_id'), arguments.get('document'),
                    arguments.get('expected_revision'), inputs=inputs,
                    operation_id='capture-'+uuid.uuid4().hex, plan_id='plan-'+uuid.uuid4().hex)
            else:
                value = agent_dispatch(self.service, {'id': 'mcp', 'method': spec.method, 'params': arguments})
            return self._tool_result({'ok': True, 'result': value}, version,
                reserved=reserved, control=spec.method in CONTROL)
        except Exception as error:
            return self._tool_result({'ok': False, 'fault': error_fault(error)}, version)
        finally:
            if reserved:
                self.store.release()

    def _list_page(self, items, params, key, stamp):
        if set(params) - {'cursor', '_meta'}:
            raise ProtocolError(-32602, 'list accepts only an opaque cursor')
        offset = 0
        if params.get('cursor') is not None:
            try:
                payload, signature = params['cursor'].split('.')
                expected = hmac.new(self.store.namespace.encode(), payload.encode(), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(signature, expected):
                    raise ValueError()
                value = json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
                if value['stamp'] != stamp or value['key'] != key or type(value['offset']) is not int:
                    raise ValueError()
                offset = value['offset']
                if not 0 <= offset < len(items):
                    raise ValueError()
            except Exception:
                raise ProtocolError(-32602, 'invalid or stale list cursor') from None
        end = min(len(items), offset+12)
        result = {key: items[offset:end]}
        while len(encoded(result)) > MAX_RESPONSE-512 and end > offset:
            end -= 1
            result = {key: items[offset:end]}
        if end == offset and offset < len(items):
            raise ProtocolError(-32603, 'one complete catalogue entry exceeds the response limit')
        if end < len(items):
            payload = base64.urlsafe_b64encode(encoded({'stamp': stamp, 'key': key, 'offset': end})).decode().rstrip('=')
            result['nextCursor'] = payload+'.'+hmac.new(self.store.namespace.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return result

    def _resources(self):
        result = []
        with self.store.lock:
            self.store._expire()
            for key in sorted(self.store.index['responses']):
                result.append({'uri': self.store.uri('responses', key), 'name': key, 'mimeType': 'application/json'})
        with self.service.lock:
            for key in sorted(self.service.state['jobs']):
                result.append({'uri': self.store.uri('jobs', key, 'receipt'), 'name': key+' captured verification', 'mimeType': 'application/json'})
            for key in sorted(self.service.state['resources']):
                result.append({'uri': self.store.uri('resources', key, 'bytes'), 'name': key+' bounded bytes', 'mimeType': 'application/json'})
        return result

    def _templates(self):
        base = 'schemaxis://workspace/'+self.store.namespace
        suffixes = [('/jobs/{job_id}/observations/{section}{?pointer,offset,limit,max_bytes,revision}', 'Captured job observation'),
            ('/plans/{plan_id}/observations/{section}{?pointer,offset,limit,max_bytes,revision}', 'Captured plan document or plan'),
            ('/jobs/{job_id}/receipt{?pointer,offset,limit,max_bytes,revision}', 'Captured verification; call verify for fresh checks'),
            ('/resources/{resource_id}/bytes{?offset,length}', 'Verified byte range; maximum 16384 bytes'),
            ('/resources/{resource_id}/metadata{?pointer,offset,limit,max_bytes,revision}', 'Verified publication metadata'),
            ('/responses/{digest}{?pointer,offset,limit,max_bytes,revision}', 'Immutable result page; maximum 65536 payload bytes'),
            ('/responses/{digest}/scalars{?pointer,offset,length}', 'Encoded string-token byte range; maximum 16384 bytes')]
        return [{'uriTemplate': base+suffix, 'name': name, 'mimeType': 'application/json'} for suffix, name in suffixes]

    def handle(self, message, *, binding='stdio', context=None):
        identity = None
        notification = False
        claimed = False
        try:
            if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or 'result' in message or 'error' in message:
                raise ProtocolError(-32600, 'expected a JSON-RPC request or notification')
            notification = 'id' not in message
            identity = message.get('id')
            if not notification and (type(identity) not in (str, int) or len(str(identity)) > 128):
                identity = None
                raise ProtocolError(-32600, 'id must be a bounded string or integer')
            if set(message) - {'jsonrpc', 'id', 'method', 'params'} or not isinstance(message.get('method'), str):
                raise ProtocolError(-32600, 'invalid JSON-RPC request fields')
            params = message.get('params', {})
            if not isinstance(params, dict):
                raise ProtocolError(-32602, 'params must be an object')
            _depth(message)
            if len(encoded(message)) > MAX_REQUEST:
                raise ProtocolError(-32600, 'request exceeds one MiB')
            context = self.local_context if binding == 'stdio' and context is None else context
            self._check_context(context)
            method = message['method']
            if notification:
                if method == 'notifications/initialized' and self.era == LEGACY:
                    self.initialized = True
                elif method == 'notifications/cancelled' and binding == 'stdio':
                    with self.state_lock:
                        if params.get('requestId') in self.active:
                            self.cancelled.add(params['requestId'])
                return None
            with self.state_lock:
                if identity in self.active:
                    raise ProtocolError(-32600, 'request id is already active')
                self.active.add(identity)
                claimed = True
            if method == 'initialize':
                if binding != 'stdio' or self.era is not None:
                    raise ProtocolError(-32602, 'legacy initialization is unavailable on this profile')
                if params.get('protocolVersion') != LEGACY:
                    raise ProtocolError(-32022, 'Unsupported protocol version', {'supported': [MODERN, LEGACY], 'requested': params.get('protocolVersion')})
                if not isinstance(params.get('capabilities'), dict) or not isinstance(params.get('clientInfo'), dict):
                    raise ProtocolError(-32602, 'legacy initialization needs clientInfo and capabilities')
                self.era = LEGACY
                result = {'protocolVersion': LEGACY, 'serverInfo': self.server_info,
                          'capabilities': {'tools': {}, 'resources': {}}}
            else:
                version = self._metadata(params, binding)
                if method == 'server/discover' and version == MODERN:
                    result = self._complete({'supportedVersions': [MODERN] if binding == 'http' else [MODERN, LEGACY],
                        'capabilities': {'tools': {}, 'resources': {}}}, version, cacheable=True)
                elif method == 'ping' and version == LEGACY:
                    result = {}
                elif method == 'tools/call':
                    result = self._call(params, version, context)
                elif method == 'tools/list':
                    items = []
                    for spec in sorted(self.catalogue.specs.values(), key=lambda spec: spec.mcp_name):
                        item = spec.definition(self.profile)
                        if not self._permitted(spec.method, context):
                            item['description'] += ' Current admission profile refuses this method.'
                        items.append(item)
                    stamp = digest({'items': items, 'profile': self.profile, 'principal': context.principal})
                    result = self._complete(self._list_page(items, params, 'tools', stamp), version, cacheable=True)
                elif method in {'resources/list', 'resources/templates/list'}:
                    items = self._resources() if method == 'resources/list' else self._templates()
                    if method == 'resources/list':
                        items = [item for item in items if self._permitted(
                            'resource' if '/resources/' in item['uri'] else 'observe', context)]
                    key = 'resources' if method == 'resources/list' else 'resourceTemplates'
                    result = self._complete(self._list_page(items, params, key,
                        digest({'items': items, 'principal': context.principal, 'profile': self.profile})), version, cacheable=True)
                elif method == 'resources/read':
                    if set(params) - {'uri', '_meta'} or 'uri' not in params:
                        raise ProtocolError(-32602, 'resources/read needs one uri')
                    try:
                        parts, _ = self.store.parse(params['uri'])
                        needed = ('resource' if parts and parts[0] == 'resources' and parts[-1] == 'bytes'
                            else 'inspect_resource_metadata' if parts and parts[0] == 'resources'
                            else 'observe')
                        if not self._permitted(needed, context):
                            fail('MCP_POLICY_DENIED', 'resource read is unavailable in the current method policy')
                        value = self.store.resource(self.service, params['uri'])
                    except Exception as error:
                        raise ProtocolError(-32602, 'resource read failed', {'fault': error_fault(error)}) from None
                    result = self._complete({'contents': [{'uri': params['uri'], 'mimeType': 'application/json',
                                                         'text': encoded(value).decode()}]}, version, cacheable=True)
                else:
                    raise ProtocolError(-32601, 'Method not found')
            response = {'jsonrpc': '2.0', 'id': identity, 'result': result}
            if len(encoded(response)) > MAX_RESPONSE:
                raise ProtocolError(-32603, 'complete response exceeds the byte limit')
            with self.state_lock:
                return None if identity in self.cancelled else response
        except ProtocolError as error:
            return None if notification else self._error(identity, error)
        except Exception as error:
            return None if notification else self._error(identity,
                ProtocolError(-32603, 'MCP dispatch failed', {'fault': error_fault(error)}))
        finally:
            if claimed:
                with self.state_lock:
                    self.active.discard(identity)
                    self.cancelled.discard(identity)


def serve(workspace, *, profile='declared-documents', stdin=None, stdout=None, isolation_config=None):
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout
    executor, inputs = None, None
    if isolation_config is not None:
        if profile != 'declared-documents':
            raise ValueError('Isolation configuration requires the declared-documents profile')
        from .mcp_isolation import configured_executor
        executor, inputs = configured_executor(isolation_config)
    with ExecutionService(workspace, executor=executor) as service:
        dispatcher = McpDispatcher(service, profile=profile, input_store=inputs)
        while True:
            line = stdin.readline(MAX_REQUEST+1)
            if not line:
                break
            try:
                if len(line) > MAX_REQUEST:
                    while line and not line.endswith(b'\n'):
                        line = stdin.readline(MAX_REQUEST+1)
                    raise ProtocolError(-32600, 'request exceeds one MiB')
                response = dispatcher.handle(parse_message(line))
            except ProtocolError as error:
                response = dispatcher._error(None, error)
            if response is not None:
                stdout.write(encoded(response).decode()+'\n')
                stdout.flush()
