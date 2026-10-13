import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from schemaxis.core.documents import load_document, resolve_document
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.catalogue import Catalogue
from schemaxis.core.planner import Planner, PlanningError

ROOT = Path(__file__).resolve().parents[2]


class DocumentTests(unittest.TestCase):
    def test_types_chains_escapes_and_independent_copies(self):
        document = {'dimensions': {'a/b': [1, 2, 3], '~': False},
                    'normal': {'$document': '/dimensions/a~1b'},
                    'arguments': {'normal': {'$document': '/normal'},
                                  'flag': {'$document': '/dimensions/~0'},
                                  'number': {'$document': '/dimensions/a~1b/1'}}}
        original = copy.deepcopy(document)
        resolved, evidence = resolve_document(document)
        self.assertEqual(resolved['arguments'], {'normal': [1, 2, 3], 'flag': False, 'number': 2})
        resolved['normal'][0] = 90
        self.assertEqual(resolved['arguments']['normal'], [1, 2, 3])
        self.assertEqual(document, original)
        self.assertTrue(evidence)

    def test_cycles_missing_malformed_and_expansion_limits(self):
        cases = [({'x': {'$document': '/x'}}, 'DOCUMENT_CYCLE'),
                 ({'x': {'$document': '/y'}, 'y': {'$document': '/x'}}, 'DOCUMENT_CYCLE'),
                 ({'x': {'$document': '/missing'}}, 'UNKNOWN_DOCUMENT_REFERENCE'),
                 ({'x': {'$document': '/a~2'}}, 'INVALID_DOCUMENT_REFERENCE'),
                 ({'x': {'$document': '/x', 'other': 1}}, 'INVALID_DOCUMENT_REFERENCE'),
                 ({'x': float('inf')}, 'INVALID_JSON')]
        for document, code in cases:
            with self.subTest(code=code), self.assertRaises(SchemaxisError) as caught:
                resolve_document(document)
            self.assertEqual(caught.exception.fault.code, code)
        with self.assertRaises(SchemaxisError) as caught:
            resolve_document({'a': [1, 2], 'b': {'$document': '/a'}}, max_values=6)
        self.assertEqual(caught.exception.fault.code, 'DOCUMENT_LIMIT')

    def test_strict_json(self):
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{'):
            with self.subTest(text=text), self.assertRaises(SchemaxisError):
                load_document(text)
        with self.assertRaises(SchemaxisError):
            resolve_document(load_document('{"x":1e999}'))

    def test_runtime_references_and_strings_are_not_interpreted(self):
        doc = {'ref': 'steps.source.outputs.dataset', 'text': '$[x]', 'x': '__import__("os")'}
        self.assertEqual(resolve_document(doc), (doc, []))

    def test_file_stdin_and_python_have_identical_plans(self):
        path = ROOT / 'examples/paraview-slice/references.json'
        doc = load_document(path.read_text())
        catalogue = Catalogue.from_roots([ROOT / 'src/schemaxis/adaptors/paraview/mvp'])
        expected = Planner(catalogue).resolve(doc).to_dict()
        environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        for source in (str(path), '-'):
            result = subprocess.run([sys.executable, '-m', 'schemaxis.adaptors.paraview.mvp', 'plan', source],
                                    input=path.read_text(), capture_output=True, text=True,
                                    env=environment, cwd=ROOT)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            actual = json.loads(result.stdout)
            self.assertEqual(actual['plan'], expected)
            self.assertEqual(actual['resolvedDocument']['steps'][0]['arguments']['normal'], [1, 0, 0])
            self.assertTrue(actual['documentReferences'])
            self.assertIn('triangulate', actual['plan']['nodes'][0]['arguments'])

    def test_invalid_cli_input_is_structured_and_does_not_execute(self):
        result = subprocess.run([sys.executable, '-m', 'schemaxis.adaptors.paraview.mvp', 'run', '-'],
                                input='{"steps": [], "x": {"$document": "/absent"}}',
                                text=True, capture_output=True,
                                env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, cwd=ROOT)
        self.assertEqual(result.returncode, 1)
        fault = json.loads(result.stdout)['fault']
        self.assertEqual(fault['code'], 'UNKNOWN_DOCUMENT_REFERENCE')
        self.assertEqual(fault['location'], '$/x')
        self.assertEqual(result.stderr, '')

    def test_reference_and_inline_plans_match_and_types_are_validated(self):
        document = load_document((ROOT / 'examples/paraview-slice/references.json').read_text())
        planner = Planner(Catalogue.from_roots([ROOT / 'src/schemaxis/adaptors/paraview/mvp']))
        inline, _ = resolve_document(document)
        self.assertEqual(planner.resolve(document).digest, planner.resolve(inline).digest)
        document['directions']['crossStream'] = 'x'
        with self.assertRaises(PlanningError):
            planner.resolve(document)

    def test_invalid_override_is_json_fault(self):
        result = subprocess.run([sys.executable, '-m', 'schemaxis.adaptors.paraview.mvp', 'plan', '-',
                                 '--output-directory', '/tmp/unused'],
                                input='{"documentVersion":"schemaxis.workflow/0.1", "steps":[]}',
                                text=True, capture_output=True,
                                env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, cwd=ROOT)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['fault']['code'], 'INVALID_OVERRIDE')
        self.assertEqual(result.stderr, '')

    def test_relative_sibling_parent_and_array_component(self):
        doc = {'size': 12, 'dimensions': {'min': [1, 2, 3],
               'y': {'$document': './min/1'},
               'size': {'$document': '../size'}}}
        resolved, evidence = resolve_document(doc)
        self.assertEqual(resolved['dimensions']['y'], 2)
        self.assertEqual(resolved['dimensions']['size'], 12)
        self.assertIn({'location': '$/dimensions/y', 'reference': './min/1',
                       'pointer': '/dimensions/min/1'}, evidence)

    def test_relative_templates_keep_definition_scope(self):
        doc = {'template': {'value': 3, 'copy': {'$document': './value'}},
               'consumer': {'value': 99, 'settings': {'$document': '/template'}}}
        resolved, _ = resolve_document(doc)
        self.assertEqual(resolved['consumer']['settings']['copy'], 3)

    def test_relative_escape_and_cycle_faults(self):
        for doc, code in [({'x': {'$document': '../x'}}, 'INVALID_DOCUMENT_REFERENCE'),
                          ({'x': {'$document': './x'}}, 'DOCUMENT_CYCLE'),
                          ({'a': {'x': {'$document': '../a'}}}, 'DOCUMENT_CYCLE')]:
            with self.subTest(doc=doc), self.assertRaises(SchemaxisError) as caught:
                resolve_document(doc)
            self.assertEqual(caught.exception.fault.code, code)
