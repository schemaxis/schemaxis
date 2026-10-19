"""Nested drafts validate in their real workflow, without opening future artifacts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.core.faults import SchemaxisError
from schemaxis.studio_server import StudioApplication
from schemaxis.workflow_authoring import example


class StudioWorkflowValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.session = AdaptorConsoleSession(temporary.name, provider='workflow')
        self.addCleanup(self.session.close)
        self.session._edit(example())
        self.identity = self.session.active_document
        self.app = StudioApplication(self.session)
        self.addCleanup(self.app.close)

    def request(self, operation='scaled', candidate=None, provider='octave'):
        record = self.session._state['documents'][self.identity]
        body = record['document'].get('workflow', record['document'])
        candidate = candidate or next(op['document'] for op in body['operations'] if op['id'] == operation)
        return {'provider': provider, 'source': json.dumps(candidate), 'document': self.identity,
                'revision': record['revision'], 'operation': operation}

    def validate(self, request):
        with patch('subprocess.Popen', side_effect=AssertionError('validation must not launch a native process')):
            return self.app.validate_source(request)

    def test_artifact_draft_uses_parent_without_saving_or_activating_it(self):
        request = self.request()
        self.session.new('another document', 'freecad')
        before = copy.deepcopy(self.session._state)
        result = self.validate(request)
        self.assertTrue(result['valid'], result)
        self.assertEqual(result['diagnostics'], [])
        self.assertEqual(result['validation']['scope'], 'workflow-operation')
        self.assertTrue(result['validation']['deferred'])
        self.assertEqual(self.session._state, before)

    def test_source_assembly_is_deferred_without_opening_a_fake_part(self):
        root = Path(__file__).resolve().parents[2]
        document = json.loads((root/'examples/schemaxis/freecad-assembly-parts-workflow.json').read_text())
        self.session._edit(document)
        result = self.validate(self.request('assembly', provider='freecad'))
        self.assertTrue(result['valid'], result)
        self.assertTrue(result['validation']['deferred'])

    def test_qpdf_artifact_draft_uses_the_same_generic_boundary(self):
        root = Path(__file__).resolve().parents[2]
        document = json.loads((root/'examples/schemaxis/qpdf-chain.json').read_text())
        for source in document['operations'][0]['document']['sources']:
            source['path'] = str(root/'examples/schemaxis/fixtures/qpdf'/(source['name']+'.pdf'))
        self.session._edit(document)
        result = self.validate(self.request('second', provider='qpdf'))
        self.assertTrue(result['valid'], result)
        self.assertTrue(result['validation']['deferred'])

    def test_reference_order_shape_and_index_are_still_checked(self):
        original = json.loads(self.request()['source'])
        for reference, code in (({'$artifact': 'missing', 'index': 0}, 'UNAVAILABLE_OPERATION'),
                                ({'$artifact': 'samples', 'index': -1}, 'INVALID_SELECTION'),
                                ({'$artifact': 'samples', 'index': True}, 'INVALID_SELECTION'),
                                ({'$artifact': 'samples', 'index': 0, 'file': '/fake'}, 'UNKNOWN_ARGUMENT')):
            candidate = copy.deepcopy(original)
            candidate['nodes'][0]['options']['file'] = reference
            with self.subTest(reference=reference):
                result = self.validate(self.request(candidate=candidate))
                self.assertFalse(result['valid'], result)
                self.assertEqual(result['diagnostics'][0]['code'], code)

    def test_concrete_operation_is_not_blanket_deferred(self):
        request = self.request('samples')
        result = self.validate(request)
        self.assertTrue(result['valid'], result)
        self.assertFalse(result['validation']['deferred'])
        self.assertFalse(result['validation']['requiresWorkflow'])
        candidate = json.loads(request['source'])
        candidate['nodes'][0]['options']['count'] = 0
        result = self.validate(self.request('samples', candidate))
        self.assertFalse(result['valid'], result)
        standalone = self.validate({'provider': 'octave', 'source': json.dumps(candidate)})
        for key in ('code', 'location', 'pointer', 'sourcePointer', 'line', 'column', 'offset'):
            self.assertEqual(result['diagnostics'][0][key], standalone['diagnostics'][0][key], key)

    def test_design_field_fault_keeps_the_draft_address(self):
        from schemaxis.workflow_design import create
        document = create(example())
        self.session.new('design', 'workflow-design')
        self.identity = self.session.active_document
        self.session._edit(document)
        candidate = json.loads(self.request('samples')['source'])
        candidate['nodes'][0]['options']['count'] = 0
        diagnostic = self.validate(self.request('samples', candidate))['diagnostics'][0]
        self.assertEqual(diagnostic['pointer'], '/nodes/0/options/count')
        self.assertEqual(diagnostic['sourcePointer'], '/nodes/0/options/count')

    def test_workflow_reference_fault_strips_only_the_draft_prefix(self):
        candidate = json.loads(self.request('samples')['source'])
        candidate['nodes'][0]['options']['count'] = {'$document': '/definitions/missing', 'scope': 'workflow'}
        diagnostic = self.validate(self.request('samples', candidate))['diagnostics'][0]
        self.assertEqual(diagnostic['code'], 'UNKNOWN_REFERENCE')
        self.assertEqual(diagnostic['pointer'], '/nodes/0/options/count')
        self.assertEqual(diagnostic['sourcePointer'], '/nodes/0/options/count')

    def test_sibling_fault_is_not_attached_to_a_same_named_draft_node(self):
        document = example()
        sibling = copy.deepcopy(document['operations'][0]['document'])
        sibling['nodes'][0]['options']['count'] = {
            '$document': '/nodes/0/options/stop', 'operation': 'samples'}
        document['operations'][1]['document'] = sibling
        self.session._edit(document)
        candidate = copy.deepcopy(document['operations'][0]['document'])
        candidate['nodes'][0]['options']['stop'] = 0
        self.assertTrue(self.validate({'provider': 'octave', 'source': json.dumps(candidate)})['valid'])
        diagnostic = self.validate(self.request('samples', candidate))['diagnostics'][0]
        self.assertEqual(diagnostic['code'], 'INVALID_ARGUMENT')
        self.assertEqual(diagnostic['pointer'], '')
        self.assertEqual(diagnostic['observed']['workflowLocation'], 'data.count')

    def test_indirect_artifact_reference_is_still_deferred(self):
        document = example()
        document['definitions'] = {'future': {'$artifact': 'samples', 'index': 0}}
        document['operations'][1]['document']['nodes'][0]['options']['file'] = {
            '$document': '/definitions/future', 'scope': 'workflow'}
        self.session._edit(document)
        result = self.validate(self.request())
        self.assertTrue(result['valid'], result)
        self.assertTrue(result['validation']['deferred'])
        self.assertTrue(result['validation']['requiresWorkflow'])

    def test_concrete_workflow_definition_keeps_execution_in_its_context(self):
        document = example()
        document['definitions'] = {'count': 5}
        document['operations'][0]['document']['nodes'][0]['options']['count'] = {
            '$document': '/definitions/count', 'scope': 'workflow'}
        self.session._edit(document)
        result = self.validate(self.request('samples'))
        self.assertTrue(result['valid'], result)
        self.assertFalse(result['validation']['deferred'])
        self.assertTrue(result['validation']['requiresWorkflow'])

    def test_workflow_design_uses_the_same_reference_validation(self):
        from schemaxis.workflow_design import create
        document = create(example())
        self.session.new('design', 'workflow-design')
        self.session._edit(document)
        self.identity = self.session.active_document
        self.assertTrue(self.validate(self.request())['validation']['deferred'])
        candidate = json.loads(self.request()['source'])
        candidate['nodes'][0]['options']['file']['$artifact'] = 'missing'
        self.assertFalse(self.validate(self.request(candidate=candidate))['valid'])

    def test_design_connections_defer_an_otherwise_concrete_operation(self):
        from schemaxis import workflow_design as design
        from tests.unit.test_workflow_design_v2 import arrow, body, link, value_ports, v1
        first = v1(body('a', 'b'), arrow('a', 'b', 'ab'))
        second = design.create(body('a', 'b'))
        second['ports'] = value_ports('a', 'b')
        second = design.connect(second, link('ab', 'a', 'b'))
        self.session.new('connected design', 'workflow-design')
        self.identity = self.session.active_document
        for document in (first, second):
            with self.subTest(version=document['version']):
                self.session._edit(document)
                result = self.validate(self.request('b'))
                self.assertTrue(result['valid'], result)
                self.assertTrue(result['validation']['deferred'])
                self.assertFalse(self.validate(self.request('a'))['validation']['deferred'])

    def test_context_is_complete_current_and_names_an_existing_operation(self):
        for mutate, code in ((lambda r: r.pop('revision'), 'INVALID_REQUEST'),
                             (lambda r: r.update(revision=True), 'STALE_REVISION'),
                             (lambda r: r.update(revision=r['revision']+1), 'STALE_REVISION'),
                             (lambda r: r.update(document='missing'), 'UNKNOWN_DOCUMENT'),
                             (lambda r: r.update(operation='missing'), 'UNKNOWN_OPERATION')):
            request = self.request()
            mutate(request)
            with self.subTest(code=code), self.assertRaises(SchemaxisError) as caught:
                self.validate(request)
            self.assertEqual(caught.exception.fault.code, code)

    def test_provider_mismatch_and_json_syntax_still_report_diagnostics(self):
        request = self.request()
        request['source'] = json.dumps({'version': 'schemaxis.freecad/1', 'nodes': []})
        result = self.validate(request)
        self.assertFalse(result['valid'])
        self.assertEqual(result['diagnostics'][0]['code'], 'UNSUPPORTED_VERSION')
        request['source'] = '{"version": '
        result = self.validate(request)
        self.assertEqual(result['diagnostics'][0]['code'], 'INVALID_JSON')

    def test_no_context_keeps_standalone_validation(self):
        request = self.request()
        request = {key: request[key] for key in ('provider', 'source')}
        result = self.validate(request)
        self.assertFalse(result['valid'], result)
        self.assertNotIn('validation', result)
