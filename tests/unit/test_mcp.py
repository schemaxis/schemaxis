"""Fake clients and host-only service checks; no native runtime or live model."""
import copy
import inspect
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import create_autospec, patch

from schemaxis.agent_transport import dispatch
from schemaxis.core.faults import SchemaxisError
from schemaxis.execution_service import ExecutionService
from schemaxis.mcp import LEGACY, MODERN, MAX_RESPONSE, McpDispatcher, ProtocolError, RequestContext, parse_message, serve
from schemaxis.mcp_admission import FileAdmission
from schemaxis.mcp_http import HttpRequest, McpHttpBinding
from schemaxis.mcp_resources import ResponseStore
from schemaxis.service_contracts import METHODS, target_for
from schemaxis.storage import encoded

POLYNOMIAL = {'version': 'schemaxis.sympy/1', 'operation': 'isolateRealRoots',
              'coefficients': ['1', '0', '-2']}


def request(method, params=None, identity=1):
    return {'jsonrpc': '2.0', 'id': identity, 'method': method, 'params': {
        **(params or {}), '_meta': {'io.modelcontextprotocol/protocolVersion': MODERN,
                                  'io.modelcontextprotocol/clientCapabilities': {}}}}


class McpTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = ExecutionService(self.directory.name)
        self.addCleanup(self.service.close)
        self.mcp = McpDispatcher(self.service)

    def call(self, name, arguments=None, dispatcher=None):
        result = (dispatcher or self.mcp).handle(request('tools/call', {'name': name, 'arguments': arguments or {}}))
        self.assertNotIn('error', result, result)
        return result['result']['structuredContent']

    def test_shared_inventory_and_all_method_parity(self):
        trusted = McpDispatcher(self.service, profile='trusted-local', store=self.mcp.store)
        self.assertEqual(len(METHODS), 56)  # 55 inherited methods plus unavailable run_tool.
        self.assertEqual(set(trusted.catalogue.specs), {'methods', *METHODS})
        for method in METHODS:
            if method == 'run_tool':
                continue
            target = target_for(self.service, method)
            arguments = {p.name: None for p in inspect.signature(target).parameters.values()
                         if p.default is inspect.Parameter.empty and p.kind != inspect.Parameter.VAR_KEYWORD}
            owner = self.service.catalogue if method.startswith('capabilities.') else self.service
            name = method.split('.')[-1]
            fake = create_autospec(target, return_value={'method': method, 'complete': True})
            with self.subTest(method=method), patch.object(owner, name, fake):
                expected = dispatch(self.service, {'id': 1, 'method': method, 'params': arguments})
                actual = self.call(method.replace('.', '_'), arguments, trusted)
                self.assertEqual(actual, {'ok': True, 'result': expected})
        expected = dispatch(self.service, {'id': 1, 'method': 'methods'})
        self.assertEqual(self.call('methods', dispatcher=trusted), {'ok': True, 'result': expected})

    def test_fault_parity_and_unknown_tool_protocol_error(self):
        trusted = McpDispatcher(self.service, profile='trusted-local', store=self.mcp.store)
        for method, arguments in [('plan', {}), ('create_task', {'objective': '', 'allowed_providers': []}),
                                  ('job', {'job_id': 'missing'}), ('capabilities.search', {'query': 4})]:
            with self.subTest(method=method), self.assertRaises(SchemaxisError) as caught:
                dispatch(self.service, {'id': 1, 'method': method, 'params': arguments})
            actual = self.call(method.replace('.', '_'), arguments, trusted)
            self.assertEqual(actual, {'ok': False, 'fault': caught.exception.fault.to_dict()})
        result = self.mcp.handle(request('tools/call', {'name': 'python', 'arguments': {}}))
        self.assertEqual(result['error']['code'], -32602)

    def test_default_root_plan_and_unknown_routes_before_hooks(self):
        task = self.call('create_task', {'objective': 'Isolate roots', 'allowed_providers': ['sympy']})['result']
        result = self.call('plan', {'task_id': task['id'], 'document': POLYNOMIAL, 'expected_revision': 0})
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['result']['revision'], 1)
        for document in [{**POLYNOMIAL, 'file': '/outside/input'},
                         {**POLYNOMIAL, 'coefficients': {'python': 'bad'}},
                         {'version': 'unknown'}, {**POLYNOMIAL, 'executable': 'bad'}]:
            with patch('schemaxis.execution_service.registry.plan', side_effect=AssertionError('planner ran')):
                result = self.call('plan', {'task_id': task['id'], 'document': document, 'expected_revision': 1})
            self.assertEqual(result['fault']['code'], 'MCP_POLICY_DENIED')

    def test_admission_contract_change_and_no_native_import(self):
        admission = FileAdmission()
        admission.check(POLYNOMIAL)
        policy = copy.deepcopy(admission.policies)
        first = next(iter(policy[POLYNOMIAL['version']]['files']))
        policy[POLYNOMIAL['version']]['files'][first] = '0'*64
        with self.assertRaises(SchemaxisError):
            FileAdmission(policy).check(POLYNOMIAL)
        from schemaxis.adaptors import registry
        with patch.dict(registry.ADAPTORS['sympy']['routes']['schemaxis.sympy/1'], {'schema': 'bad:bad'}):
            with self.assertRaises(SchemaxisError):
                admission.check(POLYNOMIAL)

    def test_default_path_authoring_schedule_refusals(self):
        for name, arguments in [('open_draft', {'filename': '/outside'}),
                                ('write_draft', {}), ('capture_inspection', {}),
                                ('prepare_template', {}), ('schedule_create', {}), ('draft_command', {})]:
            self.assertEqual(self.call(name, arguments)['fault']['code'], 'MCP_POLICY_DENIED')

    def test_literal_code_is_rejected_without_process_launch(self):
        task = self.service.create_task('Refuse code literal', ['sympy'])
        document = {**POLYNOMIAL, 'coefficients': ['1', '__import__("os").system("false")']}
        with patch('subprocess.Popen', side_effect=AssertionError('native process launched')):
            result = self.call('plan', {'task_id': task['id'], 'expected_revision': 0, 'document': document})
        self.assertFalse(result['ok'])
        self.assertEqual(result['fault']['code'], 'SYMPY_INVALID_COEFFICIENT')

    def test_bounded_listing_and_revision_cursors(self):
        names, cursor = [], None
        while True:
            result = self.mcp.handle(request('tools/list', {'cursor': cursor} if cursor else {}))['result']
            self.assertLessEqual(len(result['tools']), 12)
            names.extend(tool['name'] for tool in result['tools'])
            cursor = result.get('nextCursor')
            if not cursor:
                break
        self.assertEqual(names, sorted(names))
        self.assertEqual(set(names), set(self.mcp.catalogue.by_name))
        result = self.mcp.handle(request('resources/list', {'cursor': 'forged'}))
        self.assertEqual(result['error']['code'], -32602)

    def test_modern_and_legacy_are_separate(self):
        result = self.mcp.handle(request('server/discover'))
        self.assertEqual(result['result']['supportedVersions'], [MODERN, LEGACY])
        self.assertIn('resultType', result['result'])
        legacy = McpDispatcher(self.service, store=self.mcp.store)
        result = legacy.handle({'jsonrpc': '2.0', 'id': 'init', 'method': 'initialize',
            'params': {'protocolVersion': LEGACY, 'capabilities': {}, 'clientInfo': {'name': 'fake', 'version': '1'}}})
        self.assertNotIn('error', result)
        legacy.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        result = legacy.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        self.assertNotIn('resultType', result['result'])
        self.assertEqual(legacy.handle(request('tools/list'))['error']['code'], -32602)
        self.assertEqual(self.mcp.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'})['error']['code'], -32602)

    def test_modern_cacheable_results_include_required_private_hints(self):
        reference = self.mcp.store.capture({'value': 1})
        for method, params in [('server/discover', {}), ('tools/list', {}), ('resources/list', {}),
                               ('resources/templates/list', {}), ('resources/read', {'uri': reference['uri']})]:
            with self.subTest(method=method):
                result = self.mcp.handle(request(method, params))['result']
                self.assertEqual(result['cacheScope'], 'private')
                self.assertEqual(result['ttlMs'], 0)

    def test_modern_client_info_is_optional_but_validated_when_present(self):
        self.assertIn('result', self.mcp.handle(request('tools/list')))
        valid = request('tools/list')
        valid['params']['_meta']['io.modelcontextprotocol/clientInfo'] = {'name': 'fake', 'version': '1'}
        self.assertIn('result', self.mcp.handle(valid))
        for info in (None, [], {}, {'name': 'fake'}, {'name': 1, 'version': '1'}):
            malformed = request('tools/call', {'name': 'create_task',
                'arguments': {'objective': 'Never dispatched', 'allowed_providers': ['sympy']}})
            malformed['params']['_meta']['io.modelcontextprotocol/clientInfo'] = info
            with self.subTest(info=info), patch.object(self.service, 'create_task', side_effect=AssertionError('mutation ran')):
                self.assertEqual(self.mcp.handle(malformed)['error']['code'], -32602)

    def test_protocol_and_stdio_recovery(self):
        for value in [b'{', b'[]', b'{"a":1,"a":2}', b'{"value":NaN}']:
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                parse_message(value)
        with self.assertRaises(ProtocolError):
            parse_message(('['*70+'0'+']'*70).encode())
        self.assertIsNone(self.mcp.handle({'jsonrpc': '2.0', 'method': 'tools/call', 'params': {'name': 'create_task'}}))
        self.service.close()
        output = io.StringIO()
        stream = io.BytesIO(b'bad\n'+encoded(request('server/discover'))+b'\n')
        serve(self.directory.name, stdin=stream, stdout=output)
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]['error']['code'], -32700)
        self.assertIn('result', lines[1])

    def test_large_result_recovery_and_tampering(self):
        value = {'large': 'x'*200000, 'numbers': list(range(200))}
        with patch.object(self.service, 'task', create_autospec(self.service.task, return_value=value)):
            carrier = self.call('task', {'task_id': 'fake'})
        self.assertIn('resultResource', carrier)
        uri = carrier['resultResource']['uri']
        page = self.mcp.store.resource(self.service, uri)
        self.assertEqual(page['mode'], 'members')
        scalar = self.mcp.store.resource(self.service, uri+'/scalars?pointer=%2Flarge&length=16')
        self.assertEqual(scalar['returnedBytes'], 16)
        key = uri.rsplit('/', 1)[-1]
        (self.mcp.store.root/(key+'.json')).write_text('{}')
        with self.assertRaises(SchemaxisError):
            self.mcp.store.read(key)

    def test_cancel_and_status_not_blocked_by_response_quota(self):
        self.mcp.store.quota = 0
        with patch.object(self.service, 'cancel', create_autospec(self.service.cancel, return_value={'id': 'job-x', 'status': 'cancellation-requested'})) as cancel:
            result = self.call('cancel', {'job_id': 'job-x'})
        self.assertTrue(result['ok'])
        cancel.assert_called_once_with(job_id='job-x')
        with patch.object(self.service, 'job', create_autospec(self.service.job, return_value={'id': 'job-x', 'status': 'running'})):
            self.assertTrue(self.call('job', {'job_id': 'job-x'})['ok'])

    def test_uri_escapes_and_changed_namespace(self):
        for uri in ['file:///etc/passwd', 'schemaxis://workspace/other/responses/a',
                    self.mcp.store.uri('responses', '..'), self.mcp.store.uri('responses', '%2e%2e'),
                    self.mcp.store.uri('resources', 'x', 'bytes')+'?offset=1&offset=2']:
            with self.subTest(uri=uri), self.assertRaises(SchemaxisError):
                self.mcp.store.resource(self.service, uri)

    def test_resource_method_policy_checked_on_every_read(self):
        reference = self.mcp.store.capture({'value': 1})
        context = RequestContext('narrow', self.mcp.store.namespace, self.service,
                                 frozenset({'capabilities.search'}))
        response = self.mcp.handle(request('resources/read', {'uri': reference['uri']}), context=context)
        self.assertEqual(response['error']['data']['fault']['code'], 'MCP_POLICY_DENIED')

    def test_http_headers_origin_context_and_no_sessions(self):
        binding = McpHttpBinding(self.mcp, allowed_origins=('https://client.example',))
        message = request('tools/list')
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                   'MCP-Protocol-Version': MODERN, 'Mcp-Method': 'tools/list'}
        def send(headers=headers, method='POST', context=self.mcp.local_context, message=message):
            return binding.handle(HttpRequest(method, headers, encoded(message)), context)
        self.assertEqual(send().status, 200)
        self.assertEqual(send(context=None).status, 401)
        self.assertEqual(send(headers={**headers, 'Origin': 'https://evil.example'}).status, 403)
        self.assertEqual(send(headers={**headers, 'Mcp-Method': 'tools/call'}).status, 400)
        self.assertEqual(send(method='GET').status, 405)
        self.assertNotIn('Mcp-Session-Id', send().headers)
        unknown = request('does/not/exist')
        self.assertEqual(send(headers={**headers, 'Mcp-Method': 'does/not/exist'}, message=unknown).status, 404)

    def test_absent_package_is_explicit(self):
        result = self.call('run_tool', {'task_id': 'none', 'package_digest': 'sha256:'+'0'*64,
            'values': {}, 'expected_revision': 0})
        self.assertEqual(result['fault']['code'], 'UNKNOWN_TOOL_PACKAGE')


if __name__ == '__main__':
    unittest.main()
