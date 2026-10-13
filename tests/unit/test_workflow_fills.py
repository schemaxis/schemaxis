"""Unfinished designs expose real case parameters without inventing values."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis import workflow_design as design, workflow_templates as templates
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.core.faults import SchemaxisError
from schemaxis.workflow_authoring import design_action
from schemaxis.workflow_fills import expose_unfilled


def example():
    body = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'series', 'document': {
        'version': 'schemaxis.octave/1', 'nodes': [
            {'id': 'data', 'filter': 'sequence', 'options': {'start': 0, 'stop': 4, 'count': 5}}],
        'outputs': ['data']}}]}
    result = design.create(body)
    result['workflow']['operations'][0]['document']['nodes'][0]['options']['count'] = {
        '$fill': 'count', 'type': 'integer', 'label': 'Sample count', 'minimum': 1}
    return result


class WorkflowFillTests(unittest.TestCase):
    def fault(self, code, action):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def test_draft_projects_but_compile_and_unexposed_export_refuse(self):
        value = example()
        projection = design.project(value)
        self.assertEqual(projection['status'], 'unfilled')
        self.assertFalse(projection['compilationAvailable'])
        self.assertFalse(projection['templateExportAvailable'])
        self.fault('UNFILLED_VALUES', lambda: design.compile(value))
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'bundle'
            self.fault('UNFILLED_VALUES', lambda: design.export_template(
                value, target, template_id='fill-test', title='Fill test'))
            self.assertFalse(target.exists())

    def test_expose_export_then_bind_requires_real_case_values(self):
        value = example()
        before = copy.deepcopy(value)
        exposed = expose_unfilled(value)
        self.assertEqual(value, before)
        self.assertTrue(design.project(exposed)['templateExportAvailable'])
        self.fault('UNFILLED_VALUES', lambda: design.compile(exposed))
        with tempfile.TemporaryDirectory() as root:
            result = design.export_template(exposed, Path(root) / 'bundle', template_id='fill-test', title='Fill test')
            self.assertIsNone(result['boundDigest'])
            self.assertEqual(result['requiresValues'], ['/values/series-count'])
            bundle = templates.load_template(result['template'])
            case = json.loads(Path(result['case']).read_text())
            self.fault('UNFILLED_VALUES', lambda: templates.bind_values(bundle, case))
            case['values']['series-count'] = 6
            bound = templates.bind_values(bundle, case)
            self.assertEqual(bound['document']['settings']['series-count'], 6)
            case['values']['series-count'] = 0
            self.fault('INVALID_PARAMETER', lambda: templates.bind_values(bundle, case))

    def test_shared_fields_are_one_parameter_and_exposure_is_idempotent(self):
        value = example()
        options = value['workflow']['operations'][0]['document']['nodes'][0]['options']
        options['stop'] = copy.deepcopy(options['count'])
        exposed = expose_unfilled(value)
        self.assertEqual(len(exposed['parameters']), 1)
        self.assertEqual(expose_unfilled(exposed), exposed)
        options = exposed['workflow']['operations'][0]['document']['nodes'][0]['options']
        self.assertEqual(options['stop'], options['count'])

    def test_unknown_field_type_fails_atomically(self):
        value = example()
        value['workflow']['operations'][0]['document']['nodes'][0]['options']['count']['type'] = 'json'
        before = copy.deepcopy(value)
        self.fault('UNSUPPORTED_PARAMETER_KIND', lambda: expose_unfilled(value))
        self.assertEqual(value, before)

    def test_operation_id_from_workflow_settings_uses_resolved_identity(self):
        value = example()
        value['workflow']['settings'] = {'operation': 'series'}
        value['workflow']['operations'][0]['id'] = {'$document': '/settings/operation', 'scope': 'workflow'}
        exposed = expose_unfilled(value)
        self.assertIn('series-count', exposed['parameters'])
        self.assertTrue(design.project(exposed)['templateExportAvailable'])

    def test_structural_markers_cannot_be_exposed(self):
        value = example()
        value['workflow']['operations'][0]['document']['nodes'][0]['id'] = {
            '$fill': 'node', 'type': 'id', 'label': 'Node ID'}
        self.fault('INVALID_PARAMETER', lambda: expose_unfilled(value))

    def test_expression_over_marker_stays_deferred_until_binding(self):
        value = example()
        options = value['workflow']['operations'][0]['document']['nodes'][0]['options']
        options['count'] = {'$expr': {'op': 'add', 'args': [options['count'], 1]}}
        exposed = expose_unfilled(value)
        self.assertEqual(design.project(exposed)['status'], 'unfilled')
        with tempfile.TemporaryDirectory() as root:
            result = design.export_template(exposed, Path(root) / 'bundle', template_id='fill-test', title='Fill test')
            bundle = templates.load_template(result['template'])
            case = json.loads(Path(result['case']).read_text())
            case['values']['series-count'] = 5
            bound = templates.bind_values(bundle, case)
            self.assertEqual(bound['document']['settings']['series-count'], 5)

    def test_revision_checked_action_retains_markers_and_undo(self):
        with tempfile.TemporaryDirectory() as root:
            session = AdaptorConsoleSession(root, provider='workflow-design')
            try:
                identity = session.active_document
                session.edit_source(json.dumps(example()), identity, session._record['revision'])
                revision = session._record['revision']
                result = design_action(session, identity, revision, 'expose_unfilled')
                self.assertTrue(result['projection']['templateExportAvailable'])
                self.assertEqual(session._record['diagnostics'][0]['code'], 'UNFILLED_VALUES')
                self.fault('STALE_REVISION', lambda: design_action(session, identity, revision, 'expose_unfilled'))
                session.undo()
                self.assertFalse(session._record['document']['parameters'])
            finally:
                session.close()
