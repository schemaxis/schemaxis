"""Captured inputs are structurally admitted only at workflow reader positions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional test dependency
    jsonschema = None

from schemaxis import captured_inputs
from schemaxis.adaptors import registry
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.core.faults import SchemaxisError
from schemaxis.schema_authoring import version_schema, workflow_schema
from schemaxis.studio_schemas import design_schema
from schemaxis.studio_server import StudioApplication
from schemaxis.workflow import inspect_plan

from test_captured_inputs import TRIANGLE

DIGEST = 'a' * 64
REFERENCE = {'$resource': '/snapshots/surface', 'digest': DIGEST, 'member': 'surface.vtp'}


def pipeline(filter_name, options):
    return {'version': 'schemaxis/1', 'nodes': [{'id': 'data', 'filter': filter_name, 'options': options}],
            'scenes': [{'id': 'view', 'geometry': ['data']}]}


def workflow(filter_name, options):
    return {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'read', 'document': pipeline(filter_name, options)}]}


@unittest.skipIf(jsonschema is None, 'jsonschema is not installed')
class CapturedInputSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = jsonschema.Draft202012Validator(workflow_schema())
        cls.design = jsonschema.Draft202012Validator(design_schema('schemaxis.workflow-design/2'))
        cls.standalone = jsonschema.Draft202012Validator(version_schema('schemaxis/1', authored=True))

    def valid(self, document):
        design = {'version': 'schemaxis.workflow-design/2', 'workflow': document, 'connections': [],
                  'controllers': {}, 'ports': {}}
        workflow_valid = not list(self.workflow.iter_errors(document))
        self.assertEqual(workflow_valid, not list(self.design.iter_errors(design)), 'workflow and design differ')
        return workflow_valid

    def test_supported_reader_positions_accept_file_and_directory_references(self):
        directory = {'$resource': '/snapshots/case', 'digest': DIGEST, 'member': 'case.foam',
                     'origin': 'saved checkpoint', 'maxFiles': 20, 'maxBytes': 0}
        for filter_name, options in (('readSurface', {'files': [REFERENCE]}),
                                     ('readMultiBlock', {'files': [{**directory, 'member': 'blocks.vtm'}]}),
                                     ('foam', {'file': directory}),
                                     ('foam', {'file': {'$resource': '/snapshots/case', 'digest': DIGEST}})):
            with self.subTest(filter=filter_name, options=options):
                self.assertTrue(self.valid(workflow(filter_name, options)))

    def test_literal_paths_and_artifacts_are_unchanged(self):
        for value in ('/data/surface.vtp', {'$artifact': 'produce', 'index': 0}):
            with self.subTest(value=value):
                self.assertTrue(self.valid(workflow('readSurface', {'files': [value]})))
        self.assertFalse(self.valid(workflow('readSurface', {'files': [{'$artifact': 'produce'}]})))

    def test_malformed_references_are_refused(self):
        for bad in ({'$resource': '/snapshots/surface'}, {**REFERENCE, 'digest': 'A' * 64},
                    {**REFERENCE, 'digest': 'a' * 63}, {**REFERENCE, '$resource': 'relative'},
                    {**REFERENCE, 'member': '../escape'}, {**REFERENCE, 'member': 'a/./b'},
                    {**REFERENCE, 'member': '/absolute'}, {**REFERENCE, 'member': 'a//b'},
                    {**REFERENCE, 'member': 'C:/x'}, {**REFERENCE, 'member': ''},
                    {**REFERENCE, 'origin': ''}, {**REFERENCE, 'origin': 'x' * 1025},
                    {**REFERENCE, 'maxFiles': 0}, {**REFERENCE, 'maxBytes': -1},
                    {**REFERENCE, 'maxFiles': True}, {**REFERENCE, 'file': '/fake'},
                    {**REFERENCE, 'digest': DIGEST + '\n'}, {**REFERENCE, 'digest': DIGEST + 'a'}):
            with self.subTest(reference=bad):
                self.assertFalse(self.valid(workflow('readSurface', {'files': [bad]})))
                # The host shape check agrees with the schema.
                with self.assertRaises(SchemaxisError):
                    captured_inputs.check_reference(bad, 'reference')
        self.assertIs(captured_inputs.check_reference(REFERENCE, 'reference'), REFERENCE)

    def test_unsupported_positions_and_standalone_scope_are_refused(self):
        for filter_name, options in (('foam', {'file': '/case/case.foam', 'regions': [REFERENCE]}),
                                     ('readCSV', {'file': REFERENCE}),
                                     ('readSurface', {'files': REFERENCE})):
            with self.subTest(filter=filter_name, options=options):
                self.assertFalse(self.valid(workflow(filter_name, options)))
        self.assertTrue(list(self.standalone.iter_errors(pipeline('readSurface', {'files': [REFERENCE]}))))
        self.assertFalse(list(self.standalone.iter_errors(pipeline('readSurface', {'files': ['/data/a.vtp']}))))

    def test_captured_inputs_require_explicit_schema_and_consumer_hooks(self):
        for version, (provider, route) in registry.routes().items():
            if route.get('workflow'):
                with self.subTest(version=version):
                    hooks = route.get('hooks', {})
                    enabled = 'capturedInputSchema' in hooks
                    self.assertEqual(enabled, 'acceptResource' in hooks)
                    schema = version_schema(version, authored=True, artifact=True)
                    self.assertEqual('capturedInput' in schema.get('$defs', {}), enabled)
                    self.assertEqual('"#/$defs/capturedInput"' in json.dumps(schema), enabled)

    def test_schema_matches_accept_resource_positions(self):
        from schemaxis.adaptors.paraview import integration
        defs = version_schema('schemaxis/1', authored=True, artifact=True)['$defs']
        admitting = {name[len('options-'):] for name, value in defs.items()
                     if name.startswith('options-') and 'capturedInput"}' in json.dumps(value)}
        self.assertEqual(admitting, integration._SELF_CONTAINED | integration._REFERENCING | {'foam'})


class CapturedInputStudioTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'saved').mkdir()
        (self.root / 'saved' / 'surface.vtp').write_text(TRIANGLE)
        self.adopted = captured_inputs.adopt(self.root / 'saved' / 'surface.vtp', self.root / 'snapshot')
        self.session = AdaptorConsoleSession(str(self.root / 'workspace'), provider='workflow')
        self.addCleanup(self.session.close)
        self.session._edit(workflow('readSurface', {'files': [self.adopted['reference']]}))
        self.identity = self.session.active_document
        self.app = StudioApplication(self.session)
        self.addCleanup(self.app.close)

    def validate(self, candidate=None):
        record = self.session._state['documents'][self.identity]
        candidate = candidate or record['document']['operations'][0]['document']
        request = {'provider': 'paraview', 'source': json.dumps(candidate), 'document': self.identity,
                   'revision': record['revision'], 'operation': 'read'}
        with patch('subprocess.Popen', side_effect=AssertionError('validation must not launch a native process')):
            return self.app.validate_source(request)

    def test_nested_validation_requires_workflow_without_deferring(self):
        before = copy.deepcopy(self.session._state)
        result = self.validate()
        self.assertTrue(result['valid'], result)
        self.assertTrue(result['validation']['requiresWorkflow'])
        self.assertFalse(result['validation']['deferred'])
        self.assertIn('pinned snapshots', result['validation']['message'])
        self.assertIn('workflow', result['validation']['message'])
        self.assertEqual(self.session._state, before)

    def test_digest_with_trailing_newline_is_refused_by_closed_schema(self):
        # Python's ``$`` also matches before a final newline; exact length closes that gap.
        schema = jsonschema.Draft202012Validator(captured_inputs.reference_schema())
        self.assertTrue(schema.is_valid({'$resource': '/snapshot', 'digest': DIGEST}))
        self.assertFalse(schema.is_valid({'$resource': '/snapshot', 'digest': DIGEST + '\n'}))

    def test_nested_validation_follows_composed_consumers_only(self):
        reference = self.adopted['reference']
        draft = copy.deepcopy(self.session._state['documents'][self.identity]['document']['operations'][0]['document'])
        composed = {**draft, 'settings': {'surface': reference}}
        composed['nodes'][0]['options']['files'] = [{'$document': '/settings/surface'}]
        result = self.validate(composed)
        self.assertTrue(result['valid'], result)
        self.assertTrue(result['validation']['requiresWorkflow'])
        self.assertIn('pinned snapshots', result['validation']['message'])
        (self.root / 'snapshot' / 'data' / 'surface.vtp').write_text(TRIANGLE.replace('1 0 0', '3 0 0'))
        result = self.validate(composed)
        self.assertFalse(result['valid'], result)
        self.assertEqual(result['diagnostics'][0]['code'], 'RESOURCE_MISMATCH')
        # An unused definition is not consumed, so it neither opens a snapshot nor
        # forces workflow-only execution.
        literal = {**draft, 'settings': {'unused': {'$resource': str(self.root / 'absent'), 'digest': DIGEST}}}
        literal['nodes'][0]['options']['files'] = [str(self.root / 'saved' / 'surface.vtp')]
        result = self.validate(literal)
        self.assertTrue(result['valid'], result)
        self.assertFalse(result['validation']['requiresWorkflow'])
        self.assertNotIn('message', result['validation'])

    def test_nested_validation_checks_snapshot_now(self):
        pinned = copy.deepcopy(self.session._state['documents'][self.identity]['document']['operations'][0]['document'])
        pinned['nodes'][0]['options']['files'][0]['digest'] = '0' * 64
        result = self.validate(pinned)
        self.assertFalse(result['valid'], result)
        self.assertEqual(result['diagnostics'][0]['code'], 'INPUT_CHANGED')
        (self.root / 'snapshot' / 'data' / 'surface.vtp').write_text(TRIANGLE.replace('1 0 0', '3 0 0'))
        result = self.validate()
        self.assertFalse(result['valid'], result)
        # Byte changes fail manifest verification before the digest comparison.
        self.assertEqual(result['diagnostics'][0]['code'], 'RESOURCE_MISMATCH')

    def test_nested_validation_reports_missing_member_in_the_draft(self):
        candidate = copy.deepcopy(self.session._state['documents'][self.identity]['document']['operations'][0]['document'])
        candidate['nodes'][0]['options']['files'][0]['member'] = 'absent.vtp'
        result = self.validate(candidate)
        self.assertFalse(result['valid'], result)
        diagnostic = result['diagnostics'][0]
        self.assertEqual(diagnostic['code'], 'RESOURCE_MISMATCH')
        self.assertIn('/nodes/0/options/files/0', diagnostic['location'])

    def test_schema_scope_is_closed_and_workflow_only(self):
        scoped = json.loads(self.app.schema('schemaxis/1', 'workflow'))
        standalone = json.loads(self.app.schema('schemaxis/1'))
        self.assertIn('capturedInput', scoped['$defs'])
        self.assertNotIn('capturedInput', standalone['$defs'])
        guide = scoped['$defs']['capturedInput']['x-studio-guide']
        self.assertEqual(guide['provider'], 'workflow')
        self.assertEqual(guide['address'], '/$defs/capturedInput')
        self.assertNotEqual(guide['status'], 'pending')
        self.assertIn('digest', scoped['$defs']['capturedInput']['description'])
        for scope, code in (('standalone', 'INVALID_REQUEST'), ('workflow', 'UNKNOWN_VERSION')):
            with self.subTest(scope=scope):
                with self.assertRaises(SchemaxisError) as caught:
                    self.app.schema('schemaxis.workflow/1' if scope == 'workflow' else 'schemaxis/1', scope)
                self.assertEqual(caught.exception.fault.code, code)

    def test_shared_workflow_schema_projects_guidance(self):
        shared = json.loads(self.app.schema('schemaxis.workflow/1'))
        self.assertNotEqual(shared['$defs']['capturedInput']['x-studio-guide']['status'], 'pending')
        embedded = next(value for key, value in shared['$defs'].items()
                        if key.startswith('pipeline') and 'capturedInput' in value.get('$defs', {}))
        self.assertEqual(embedded['$defs']['capturedInput']['x-studio-guide']['address'], '/$defs/capturedInput')

    def test_host_plan_rejects_tampered_and_missing_members(self):
        document = self.session._state['documents'][self.identity]['document']
        plan = inspect_plan(copy.deepcopy(document))
        self.assertIn('read', json.dumps(plan))
        missing = copy.deepcopy(document)
        missing['operations'][0]['document']['nodes'][0]['options']['files'][0]['member'] = 'absent.vtp'
        with self.assertRaises(SchemaxisError) as caught:
            inspect_plan(missing)
        self.assertEqual(caught.exception.fault.code, 'RESOURCE_MISMATCH')
        repinned = copy.deepcopy(document)
        repinned['operations'][0]['document']['nodes'][0]['options']['files'][0]['digest'] = '0' * 64
        with self.assertRaises(SchemaxisError) as caught:
            inspect_plan(repinned)
        self.assertEqual(caught.exception.fault.code, 'INPUT_CHANGED')
        (self.root / 'snapshot' / 'data' / 'surface.vtp').write_text('changed')
        with self.assertRaises(SchemaxisError) as caught:
            inspect_plan(copy.deepcopy(document))
        self.assertEqual(caught.exception.fault.code, 'RESOURCE_MISMATCH')


if __name__ == '__main__':
    unittest.main()
