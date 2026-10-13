"""Markers survive drafts but are refused at execution and binding boundaries."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis import authoring, storage, workflow
from schemaxis.adaptors import registry
from schemaxis.console_session import ConsoleSession
from schemaxis.core.faults import SchemaxisError
from schemaxis.unfilled import find_unfilled, reject_unfilled
from schemaxis.workflow_templates import bind_values, load_template


class UnfilledTests(unittest.TestCase):
    def fault(self, action, pointers):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        fault = caught.exception.fault
        self.assertEqual(fault.code, 'UNFILLED_VALUES')
        self.assertEqual(fault.to_dict()['observed']['pointers'], pointers)

    def document(self):
        return {'version': 'schemaxis.freecad/1', 'units': 'mm', 'nodes': [
            {'id': 'body', 'filter': 'box', 'options': {'height': {'$fill': 'height', 'label': 'Height',
                                                                    'type': 'number'}}}], 'output': 'body'}

    def test_scan_reports_exact_escaped_paths_and_all_markers(self):
        value = {'a/b': [{'~x': {'$fill': 'one'}}, {'$fill': 'two', 'label': 'Two', 'type': 'integer'}]}
        self.assertEqual([item['pointer'] for item in find_unfilled(value)], ['/a~1b/0/~0x', '/a~1b/1'])
        self.fault(lambda: reject_unfilled(value), ['/a~1b/0/~0x', '/a~1b/1'])
        self.fault(lambda: reject_unfilled(value, allowed=['/a~1b/0']), ['/a~1b/0/~0x', '/a~1b/1'])

    def test_malformed_host_objects_fail_structurally_without_recursion_leaks(self):
        cycle = {}
        cycle['self'] = cycle
        deep = {}
        cursor = deep
        for _ in range(70):
            cursor['child'] = {}
            cursor = cursor['child']
        for document in (cycle, deep, {1: 'bad key'}):
            with self.subTest(document_type=type(document)):
                with self.assertRaises(SchemaxisError) as caught:
                    registry.plan(document)
                self.assertEqual(caught.exception.fault.code, 'INVALID_DOCUMENT')

    def test_registry_and_workflow_fail_before_native_or_expression_validation(self):
        document = self.document()
        pointer = '/nodes/0/options/height'
        self.fault(lambda: registry.plan(document), [pointer])
        self.fault(lambda: registry.run(document, '/unused'), [pointer])
        body = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'cad', 'document': document}]}
        self.fault(lambda: workflow.inspect_plan(body), ['/operations/0/document' + pointer])
        self.fault(lambda: workflow.execute(body, '/unused'), ['/operations/0/document' + pointer])

    def test_source_retention_and_session_validate(self):
        document = self.document()
        source = json.dumps(document)
        parsed, diagnostics = authoring.analyse(source, registry.plan)
        self.assertEqual(parsed, document)
        self.assertEqual(diagnostics[0]['code'], 'UNFILLED_VALUES')
        with tempfile.TemporaryDirectory() as directory:
            session = ConsoleSession(workspace=directory)
            session.new(provider='freecad')
            try:
                self.fault(lambda: session._validate(document), ['/nodes/0/options/height'])
                session.edit_source(source, session.active_document, session._record['revision'])
                path = Path(directory) / 'draft.json'
                session.write_source(session.active_document, session._record['revision'], str(path))
                self.assertEqual(path.read_text(), source)
                self.fault(lambda: session.document, ['/nodes/0/options/height'])
            finally:
                session.close()

    def test_exposed_exact_marker_binds_before_check_and_other_markers_fail(self):
        body = {'version': 'schemaxis.workflow/1', 'settings': {'height': {'$fill': 'height'}},
                'operations': [{'id': 'cad', 'document': self.document()}]}
        body['operations'][0]['document']['nodes'][0]['options']['height'] = {
            '$document': '/settings/height', 'scope': 'workflow'}
        manifest = {'version': 'schemaxis.workflow-template/1', 'id': 'box', 'revision': 1,
                    'title': 'Box', 'workflow': 'workflow.json', 'outputs': {}, 'parameters': {
                        'height': {'label': 'Height', 'kind': 'number',
                                   'target': {'scope': 'workflow', 'pointer': '/settings/height'}}}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'template.json').write_text(json.dumps(manifest))
            (root / 'workflow.json').write_text(json.dumps(body))
            bundle = load_template(root / 'template.json')
            values = {'version': 'schemaxis.workflow-values/1', 'template': {
                'id': 'box', 'revision': 1, 'digest': bundle['digest']}, 'values': {'height': 4}}
            self.assertEqual(bind_values(bundle, values)['document']['settings']['height'], 4)
            bad = copy.deepcopy(body)
            bad['settings']['other'] = {'$fill': 'other'}
            (root / 'workflow.json').write_text(json.dumps(bad))
            self.fault(lambda: load_template(root / 'template.json'), ['/settings/other'])
