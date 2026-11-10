"""One shared local package format exercised through CLI helpers and MCP."""
import copy
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from schemaxis.core.faults import SchemaxisError
from schemaxis.execution_service import ExecutionService
from schemaxis.mcp import McpDispatcher
from schemaxis.mcp_admission import FileAdmission
from schemaxis.storage import encoded
from schemaxis.tool_packages import PackageStore, check_package, pack_directory, run_tool
from test_mcp import POLYNOMIAL, request


def source_package(directory):
    root = Path(directory)
    template = {'version': 'schemaxis.workflow-template/1', 'id': 'roots', 'revision': 1,
        'title': 'Exact polynomial roots', 'workflow': 'workflow.json',
        'parameters': {'constant': {'label': 'Constant coefficient', 'kind': 'string',
            'constraints': {'minLength': 1, 'maxLength': 82}, 'default': '-2',
            'target': {'scope': 'workflow', 'pointer': '/definitions/constant'}}},
        'outputs': {'roots': {'operation': 'roots', 'artifact': 0, 'kind': 'table'}}}
    workflow = {'version': 'schemaxis.workflow/1', 'definitions': {'constant': '-2'},
        'operations': [{'id': 'roots', 'document': {**POLYNOMIAL,
            'coefficients': ['1', '0', {'$document': '/definitions/constant', 'scope': 'workflow'}]}}]}
    manifest = {'version': 'schemaxis.tool/1', 'id': 'exact-roots', 'revision': 1,
        'title': 'Exact polynomial roots', 'summary': 'Isolate the real roots of a polynomial.',
        'description': 'Exact rational coefficients and independently checked intervals.',
        'tags': ['polynomial'], 'author': 'Example author', 'licence': 'Apache-2.0',
        'template': 'template.json', 'display': {},
        'execution': {'tier': 'local', 'durationClass': 'short', 'uploadedInputs': False},
        'requirements': [], 'provenance': {'files': {}}}
    for name, document in [('tool.json', manifest), ('template.json', template), ('workflow.json', workflow)]:
        (root/name).write_bytes(encoded(document))
    return manifest


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root/'source'
        self.source.mkdir()
        source_package(self.source)
        self.archive = self.root/'roots.schemaxis-tool'
        self.packed = pack_directory(self.source, self.archive)

    def test_deterministic_pack_and_exact_import(self):
        second = self.root/'second.schemaxis-tool'
        self.assertEqual(pack_directory(self.source, second), self.packed)
        self.assertEqual(self.archive.read_bytes(), second.read_bytes())
        store = PackageStore(self.root/'workspace')
        imported = store.import_package(self.archive)
        checked = store.resolve(imported['digest'], values={'constant': '-3'})
        self.assertEqual(checked['prepared']['values'], {'constant': '-3'})
        self.assertEqual(checked['providers'], ['sympy'])
        self.assertEqual(checked['manifest']['requirements'], [
            {'adaptor': 'sympy', 'application': 'sympy', 'versionRange': 'unknown'}])
        changed = store.root/(imported['digest'][7:]+'.schemaxis-tool')
        changed.write_bytes(b'changed')
        with self.assertRaises(SchemaxisError) as caught:
            store.resolve(imported['digest'])
        self.assertEqual(caught.exception.fault.code, 'TOOL_PACKAGE_CHANGED')

    def test_run_tool_captures_same_workflow_and_provenance(self):
        with ExecutionService(self.root/'service') as service:
            package = PackageStore(service.workspace).import_package(self.archive)
            task = service.create_task('Exact roots', ['sympy'])
            mcp = McpDispatcher(service)
            response = mcp.handle(request('tools/call', {'name': 'run_tool', 'arguments': {
                'task_id': task['id'], 'package_digest': package['digest'], 'values': {'constant': '-3'}, 'expected_revision': 0}}))
            carrier = response['result']['structuredContent']
            self.assertTrue(carrier['ok'], carrier)
            result = carrier['result']
            self.assertEqual(service.task(task['id'])['attempts'], 0)
            self.assertEqual(service.state['plans'][result['plan']['id']]['package']['digest'], package['digest'])
            captured = service.observe(plan_id=result['plan']['id'], section='document')['value']
            FileAdmission().check(captured)
            self.assertEqual(captured['definitions']['constant'], '-3')

    def test_scope_revision_and_attempt_budgets(self):
        with ExecutionService(self.root/'service') as service:
            package = PackageStore(service.workspace).import_package(self.archive)
            task = service.create_task('Scope refusal', ['freecad'])
            with self.assertRaises(SchemaxisError) as caught:
                run_tool(service, task['id'], package['digest'], {}, 0)
            self.assertEqual(caught.exception.fault.code, 'SCOPE_EXCEEDED')
            task = service.create_task('Budget refusal', ['sympy'], {'maxAttempts': 1})
            with patch.object(service, '_run', return_value=None):
                result = run_tool(service, task['id'], package['digest'], {}, 0, execute=True)
            self.assertEqual(service.task(task['id'])['attempts'], 1)
            self.assertIn('job', result)
            with service.lock:
                state = copy.deepcopy(service.state)
                state['jobs'][result['job']['id']]['status'] = 'failed'
                service._commit(state)
            with self.assertRaises(SchemaxisError) as caught:
                run_tool(service, task['id'], package['digest'], {}, 1, execute=True)
            self.assertEqual(caught.exception.fault.code, 'ATTEMPT_BUDGET_EXCEEDED')
            self.assertIn('plan', caught.exception.fault.observed)

    def test_hostile_template_denied_before_planner(self):
        workflow = json.loads((self.source/'workflow.json').read_text())
        workflow['operations'][0]['document']['file'] = '/outside/secret'
        (self.source/'workflow.json').write_bytes(encoded(workflow))
        with patch('schemaxis.workflow.inspect_plan', side_effect=AssertionError('planner called')):
            with self.assertRaises(SchemaxisError) as caught:
                pack_directory(self.source, self.root/'bad.schemaxis-tool')
        self.assertEqual(caught.exception.fault.code, 'MCP_POLICY_DENIED')

    def test_code_and_symlink_and_duplicate_members_refused(self):
        for name, mode in [('script.py', stat.S_IFREG | 0o644), ('link.txt', stat.S_IFLNK | 0o777),
                           ('../escape.json', stat.S_IFREG | 0o644), ('/absolute.json', stat.S_IFREG | 0o644)]:
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                info = zipfile.ZipInfo(name)
                info.external_attr = mode << 16
                archive.writestr(info, b'{}')
            with self.subTest(name=name), self.assertRaises(SchemaxisError):
                check_package(stream.getvalue())
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('data.json', b'{}')
            archive.writestr('DATA.json', b'{}')
        with self.assertRaises(SchemaxisError):
            check_package(stream.getvalue())

    def test_digest_inventory_tamper_and_zip_bomb_bound(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.archive.read_bytes())) as source, zipfile.ZipFile(stream, 'w') as target:
            for item in source.infolist():
                target.writestr(item, b'{}' if item.filename == 'workflow.json' else source.read(item))
        with self.assertRaises(SchemaxisError) as caught:
            check_package(stream.getvalue())
        self.assertEqual(caught.exception.fault.code, 'TOOL_PACKAGE_CHANGED')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('data.txt', b'x'*(8*1024*1024+1))
        with self.assertRaises(SchemaxisError) as caught:
            check_package(stream.getvalue())
        self.assertEqual(caught.exception.fault.code, 'TOOL_PACKAGE_LIMIT')

    def test_no_remote_resolver_or_parameter_code(self):
        store = PackageStore(self.root/'workspace')
        for digest in ['https://example.invalid/a', '../archive', 'sha256:'+'A'*64]:
            with self.subTest(digest=digest), self.assertRaises(SchemaxisError):
                store.resolve(digest)
        with self.assertRaises(SchemaxisError):
            check_package(self.archive.read_bytes(), values={'constant': {'python': 'bad'}})


if __name__ == '__main__':
    unittest.main()
