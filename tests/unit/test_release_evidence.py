# Copyright (C) 2026 David L F Gaden
"""Pure helpers of the release evidence runner: paths, summaries and checks."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('release_evidence', ROOT/'tools/release_evidence.py')
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


def summary(**changes):
    value = {'schema': evidence.SUMMARY_SCHEMA, 'workflowId': 'demo', 'title': 'Demo', 'status': 'passed',
             'apps': [{'name': 'calc', 'version': 'LibreOffice 26.8.1.1'}], 'inputs': {}, 'variant': {},
             'steps': [{'name': 'initial', 'seconds': 1.0, 'exitCode': 0, 'log': 'logs/initial.log'}],
             'artifacts': {}, 'verification': {}, 'independentChecks': {}, 'reuse': {},
             'showcase': {'files': [{'path': 'showcase/a.png', 'sha256': '0'*64, 'bytes': 1}], 'totalBytes': 1},
             'failures': [], 'startedAt': 'x', 'endedAt': 'y', 'wallSeconds': 1.0, 'machine': {}, 'code': {}}
    value.update(changes)
    return value


class ReleaseEvidenceTests(unittest.TestCase):
    def test_relativise_inside_and_outside(self):
        self.assertEqual(evidence.relativise('/a/b/run/x/y.png', '/a/b/run'), 'x/y.png')
        self.assertIsNone(evidence.relativise('/a/other/y.png', '/a/b/run'))

    def test_scrub_replaces_known_prefixes_then_any_absolute_path(self):
        text = 'wrote /work/run/out.png from /srv/someone/case/a.foam via /usr/bin/x'
        scrubbed = evidence.scrub_text(text, {'/work/run/': '', '/srv/someone/case': '<case>'})
        self.assertEqual(scrubbed, 'wrote out.png from <case>/a.foam via <absolute-path>')

    def test_absolute_path_audit_ignores_json_pointers(self):
        value = {'pointer': '/operations/0/document', 'note': 'see /tmp/x/y', 'list': ['~', 'user7 here']}
        self.assertEqual(evidence.absolute_paths(value, ['user7']), ['/note', '/list/1'])

    def test_pointer_and_patch_operations(self):
        document = {'operations': [{'document': {'nodes': [{'id': 'a'}, {'id': 'c', 'inputs': {'input': 'a'}}]}}]}
        patched = evidence.apply_patch(document, [
            {'op': 'test', 'path': '/operations/0/document/nodes/1/id', 'value': 'c'},
            {'op': 'add', 'path': '/operations/0/document/nodes/1', 'value': {'id': 'b'}},
            {'op': 'replace', 'path': '/operations/0/document/nodes/2/inputs/input', 'value': 'b'}])
        self.assertEqual([n['id'] for n in patched['operations'][0]['document']['nodes']], ['a', 'b', 'c'])
        self.assertEqual(evidence.json_pointer_get(patched, '/operations/0/document/nodes/2/inputs/input'), 'b')
        self.assertEqual(len(document['operations'][0]['document']['nodes']), 2)
        with self.assertRaises(ValueError):
            evidence.apply_patch(document, [{'op': 'test', 'path': '/operations/0/document/nodes/0/id', 'value': 'z'}])
        with self.assertRaises(KeyError):
            evidence.json_pointer_set(document, '/operations/0/missing', 1)

    def test_summary_schema(self):
        self.assertEqual(evidence.validate_summary(summary()), [])
        broken = summary(status='great')
        del broken['reuse']
        broken['showcase']['files'][0]['path'] = '/tmp/x/a.png'
        problems = evidence.validate_summary(broken)
        self.assertIn('missing reuse', problems)
        self.assertIn('status must be passed, failed or partial', problems)
        self.assertIn('showcase path is absolute', problems)
        self.assertTrue(any(p.startswith('absolute path at /showcase/files/0/path') for p in problems))
        # Every manifest workflow carries the fields the runner relies on.
        manifest = json.loads((ROOT/'tools/release_evidence_manifest.json').read_text())
        for spec in manifest['workflows']:
            self.assertTrue({'id', 'title', 'apps'} <= set(spec), spec.get('id'))
            if spec.get('kind') != 'benchmark':
                self.assertIn(spec['checks'], evidence.CHECKS)
                self.assertTrue(spec['variant']['changes'])

    def test_compare_tally_and_informational_records(self):
        checks = [evidence.compare('a', 1.0000001, 1.0, relative=1e-6),
                  evidence.compare('b', 2.0, 1.0, relative=1e-6),
                  evidence.compare('c', None, 1.0, relative=1e-6),
                  {'name': 'd', 'observed': 3, 'passed': None}]
        self.assertEqual(evidence.tally(checks), {'passed': 1, 'failed': 2, 'informational': 1})
        self.assertAlmostEqual(checks[0]['relativeDifference'], 1e-7)

    def test_householder_least_squares(self):
        rows = [[1, -2], [1, -1], [1, 1], [1, 2]]
        coefficients = evidence.householder_least_squares(rows, [6.1, 7.8, 12.2, 13.9])
        self.assertAlmostEqual(coefficients[0], 10.0, places=12)
        self.assertAlmostEqual(coefficients[1], 2.0, places=12)

    def test_tetra_volume_and_png_size(self):
        vtu = ('<VTKFile type="UnstructuredGrid" version="0.1"><UnstructuredGrid><Piece NumberOfPoints="4" '
               'NumberOfCells="1"><Points><DataArray type="Float64" Name="Points" format="ascii" '
               'NumberOfComponents="3">0 0 0 2 0 0 0 3 0 0 0 4</DataArray></Points><Cells>'
               '<DataArray type="Int64" Name="connectivity" format="ascii">0 1 2 3</DataArray>'
               '<DataArray type="Int64" Name="offsets" format="ascii">4</DataArray>'
               '<DataArray type="UInt8" Name="types" format="ascii">10</DataArray></Cells></Piece>'
               '</UnstructuredGrid></VTKFile>')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'t.vtu'
            path.write_text(vtu)
            self.assertEqual(evidence.tetra_volume_sum(path), (4.0, 1))
            png = Path(tmp)/'a.png'
            png.write_bytes(b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', 640, 480))
            self.assertEqual(evidence.png_size(png), [640, 480])

    def test_application_names_from_document_versions(self):
        self.assertEqual(evidence.application('schemaxis/1'), 'paraview')
        self.assertEqual(evidence.application('schemaxis.blender.render/1'), 'blender')
        self.assertEqual(evidence.application('schemaxis.calc/1'), 'calc')


if __name__ == '__main__':
    unittest.main()
