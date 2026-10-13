"""YAML profile parity and durable authoring; optional-extra checks skip without it."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis import authoring
from schemaxis.core.documents import document_format, load_document, load_document_file
from schemaxis.core.faults import SchemaxisError
from schemaxis.source_formats import dump_document

HAS_YAML = importlib.util.find_spec('ruamel') is not None
BOX = {'version': 'schemaxis.freecad/1', 'nodes': [
    {'id': 'body', 'filter': 'box', 'options': {'length': 20, 'width': 10, 'height': 5}}], 'output': 'body'}


class FormatTests(unittest.TestCase):
    def test_format_detection_never_falls_back_from_broken_json(self):
        self.assertEqual(document_format('case.YML'), 'yaml')
        self.assertEqual(document_format('case.txt'), 'json')
        self.assertEqual(document_format('case.yaml', 'json'), 'json')
        with self.assertRaises(SchemaxisError): load_document('version: value')

    def test_missing_extra_is_a_structured_fault(self):
        if HAS_YAML: self.skipTest('extra installed')
        with self.assertRaises(SchemaxisError) as caught: load_document('a: 1', 'yaml')
        self.assertEqual(caught.exception.fault.code, 'YAML_UNAVAILABLE')


@unittest.skipUnless(HAS_YAML, 'install schemaxis[yaml] for YAML qualification')
class YamlTests(unittest.TestCase):
    def test_profile_and_conversion_preserve_finite_json_types(self):
        value = load_document('text: yes\nflag: true\nnumber: 012\nscientific: 1e3\ndate: 2026-10-09\nempty: null\nvector: [1, 2, 3]\n', 'yaml')
        self.assertEqual(value, {'text': 'yes', 'flag': True, 'number': 12, 'scientific': 1000.0,
                                'date': '2026-10-09', 'empty': None, 'vector': [1, 2, 3]})
        self.assertEqual(load_document(dump_document(value, 'yaml'), 'yaml'), value)
        self.assertEqual(json.loads(dump_document(value)), value)

    def test_unsafe_or_ambiguous_input_is_rejected(self):
        for source in ('a: 1\na: 2\n', 'a: .nan', 'a: .inf', 'a: !!str 2',
                       'a: &anchor [1]\nb: *anchor', '<<: {a: 1}', '1: value',
                       'a: 1\n---\nb: 2', '%YAML 1.1\n---\na: yes', '%TAG !e! tag:example.com,2026:\n---\na: 1'):
            with self.subTest(source=source), self.assertRaises(SchemaxisError):
                load_document(source, 'yaml')

    def test_schema_diagnostics_have_yaml_locations(self):
        def validate(value):
            from schemaxis.errors import fail
            fail('BAD_FIELD', 'repair a', '$.a')
        value, diagnostics = authoring.analyse('# heading\na: 3\n', validate, 'yaml')
        self.assertEqual(value, {'a': 3})
        self.assertEqual(diagnostics[0]['line'], 2)
        self.assertEqual(diagnostics[0]['column'], 4)
        _, diagnostics = authoring.analyse('a: [\n', lambda value: None, 'yaml')
        self.assertEqual(diagnostics[0]['code'], 'INVALID_YAML')
        self.assertIn('line', diagnostics[0])

    def test_property_edits_comments_invalid_drafts_and_recovery(self):
        from schemaxis.console_session import AdaptorConsoleSession
        with tempfile.TemporaryDirectory() as temporary, patch('schemaxis.configuration.load', return_value={'version': 1, 'locations': {}}):
            root = Path(temporary)
            source = '# project comment\n' + dump_document(BOX, 'yaml').replace('height: 5', 'height: 5 # thickness')
            path = root/'box.yaml'
            path.write_text(source)
            self.assertEqual(load_document_file(path), BOX)
            with AdaptorConsoleSession(root/'session', 'freecad') as session:
                session.open(path)
                identity = session.active_document
                session.patch([{'op': 'replace', 'path': '/nodes/0/options/height', 'value': 7}], identity, session._record['revision'])
                draft = session.draft(length=16384)
                self.assertEqual(draft['sourceFormat'], 'yaml')
                self.assertIn('# project comment', draft['source'])
                self.assertIn('# thickness', draft['source'])
                self.assertEqual(session.document['nodes'][0]['options']['height'], 7)
                span = session.locate_source(identity, session._record['revision'], '/nodes/0/options/height')
                self.assertEqual(span['value'], 7)
                session.edit_source('nodes: [\n', identity, session._record['revision'])
                self.assertFalse(session.draft()['valid'])
            with AdaptorConsoleSession(root/'session', 'freecad') as session:
                self.assertEqual(session.draft()['sourceFormat'], 'yaml')
                self.assertFalse(session.draft()['valid'])
                session.undo()
                self.assertIn('# thickness', session.draft(length=16384)['source'])
                self.assertEqual(session.document['nodes'][0]['options']['height'], 7)
                with self.assertRaises(SchemaxisError) as caught:
                    session.write_source(identity, session._record['revision'], root/'edited.json')
                self.assertEqual(caught.exception.fault.code, 'FORMAT_MISMATCH')
                self.assertFalse((root/'edited.json').exists())
                session.write_source(identity, session._record['revision'], root/'edited.yml')
                self.assertEqual(load_document_file(root/'edited.yml'), session.document)

    def test_reorder_preserves_comments_with_identifiable_objects(self):
        from schemaxis.core.yaml_documents import reconcile
        source = 'nodes:\n- id: first # first note\n  x: 1\n- id: second # second note\n  x: 2\n'
        value = load_document(source, 'yaml')
        value['nodes'].reverse()
        revised = reconcile(source, value)
        self.assertEqual(load_document(revised, 'yaml'), value)
        self.assertIn('second # second note', revised)
        self.assertIn('first # first note', revised)


if __name__ == '__main__': unittest.main()
