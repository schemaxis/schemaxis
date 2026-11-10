"""Exported array values and retained export evidence must be finite, complete and untampered.

Native objects are replaced by small stand-ins and no ParaView is imported. These host
tests cover the checks only; native acceptance is recorded separately in
verification/2026-10-24-paraview-export-integrity.md.
"""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.paraview import writers
from schemaxis.adaptors.paraview.export_integrity import verify_export_evidence
from schemaxis.adaptors.paraview.job import plan, schedule, identities, verify_receipt
from schemaxis.pipeline import evaluate

NAN, INF = float('nan'), float('inf')


class Array:
    def __init__(self, name, rows, kind=11):
        self.name, self.kind = name, kind
        self.rows = [tuple(r) if isinstance(r, (list, tuple)) else (r,) for r in rows]
    def GetName(self): return self.name
    def GetNumberOfComponents(self): return len(self.rows[0])
    def GetNumberOfTuples(self): return len(self.rows)
    def GetDataType(self): return self.kind
    def GetDataTypeAsString(self): return {11: 'double', 6: 'int'}[self.kind]
    def GetComponent(self, i, c): return self.rows[i][c]


class Fields:
    def __init__(self, *arrays): self.arrays = list(arrays)
    def GetNumberOfArrays(self): return len(self.arrays)
    def GetAbstractArray(self, i): return self.arrays[i]
    def GetArrayName(self, i): return self.arrays[i].name


class Points:
    def __init__(self, array): self.array = array
    def GetData(self): return self.array


class Dataset:
    def __init__(self, point=(), cell=(), points=None):
        self.point, self.cell = Fields(*point), Fields(*cell)
        self.points = None if points is None else Points(points)
    def GetPoints(self): return self.points
    def GetPointData(self): return self.point
    def GetCellData(self): return self.cell


def fault(case, action):
    with case.assertRaises(SchemaxisError) as caught:
        action()
    return caught.exception.fault


class FiniteValueTests(unittest.TestCase):
    def test_nonfinite_input_array_is_named_with_its_first_location(self):
        array = Array('pressure', [(1.5,), (NAN,), (INF,)])
        found = fault(self, lambda: writers.require_finite(array, 'Point Data', 'out'))
        self.assertEqual((found.code, found.location), ('NONFINITE_DATA', 'out'))
        self.assertEqual({k: found.observed[k] for k in ('array', 'association', 'tuple', 'component', 'nonfiniteValuesFromFirst')},
                         {'array': 'pressure', 'association': 'Point Data', 'tuple': 1, 'component': 0,
                          'nonfiniteValuesFromFirst': 2})

    def test_vector_component_is_located(self):
        array = Array('velocity', [(0.0, 1.0, 2.0), (0.0, -INF, 2.0)])
        found = fault(self, lambda: writers.require_finite(array, 'Cell Data'))
        self.assertEqual((found.observed['tuple'], found.observed['component']), (1, 1))

    def test_finite_and_integer_arrays_pass(self):
        writers.require_finite(Array('p', [(0.0,), (1e308,)]), 'Point Data')
        writers.require_finite(Array('ids', [(1,), (2,)], kind=6), 'Cell Data')
        writers.require_finite(None, 'Cell Data')

    def test_readback_nonfinite_values_are_an_artifact_fault_not_an_input_fault(self):
        found = fault(self, lambda: writers.require_finite(Array('p', [(NAN,)]), 'Point Data', readback=True))
        self.assertEqual(found.code, 'NONFINITE_ARTIFACT_DATA')

    def test_nonfinite_coordinates_are_refused(self):
        data = Dataset(points=Array('Points', [(0.0, 0.0, 0.0), (1.0, NAN, 0.0)]))
        found = fault(self, lambda: writers.require_finite_points(data))
        self.assertEqual((found.code, found.observed['association']), ('NONFINITE_DATA', 'Points'))

    def test_text_cells_that_parse_as_nonfinite_are_refused(self):
        for text in ('nan', 'NaN', 'inf', '-inf', 'Infinity'):
            with self.subTest(text=text):
                found = fault(self, lambda: writers.require_finite_text(text, 3, 'pressure'))
                self.assertEqual((found.code, found.observed['row'], found.observed['column']),
                                 ('NONFINITE_ARTIFACT_DATA', 3, 'pressure'))
        for text in ('1.5', '-2', '', 'label', '1e-3'):
            writers.require_finite_text(text, 0, 'x')

    def test_csv_with_nonfinite_input_has_a_precise_fault_not_a_cell_mismatch(self):
        class Table:
            def __init__(self, arrays): self.row = Fields(*arrays)
            def IsA(self, name): return name == 'vtkTable'
            def GetRowData(self): return self.row
        class Rows(Fields):
            def GetNumberOfTuples(self): return self.arrays[0].GetNumberOfTuples()
        data = Table([]); data.row = Rows(Array('pressure', [(1.5,), (NAN,)]))
        effective = {'FieldAssociation': 'Row Data', 'FieldDelimiter': ',', 'StringDelimiter': '"', 'UseStringDelimiter': True}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'data.csv'
            path.write_text('"pressure"\n1.5\nnan\n')
            found = fault(self, lambda: writers.verify_csv(data, path, effective, 0.0))
        self.assertEqual((found.code, found.observed['array'], found.observed['tuple']), ('NONFINITE_DATA', 'pressure', 1))

    def test_csv_file_that_gained_a_nonfinite_cell_is_an_artifact_fault(self):
        class Table:
            def IsA(self, name): return name == 'vtkTable'
            def GetRowData(self): return rows
        class Rows(Fields):
            def GetNumberOfTuples(self): return 2
        rows = Rows(Array('pressure', [(1.5,), (2.5,)]))
        effective = {'FieldAssociation': 'Row Data', 'FieldDelimiter': ',', 'StringDelimiter': '"', 'UseStringDelimiter': True}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'data.csv'
            path.write_text('"pressure"\n1.5\ninf\n')
            found = fault(self, lambda: writers.verify_csv(Table(), path, effective, 0.0))
        self.assertEqual((found.code, found.observed['row']), ('NONFINITE_ARTIFACT_DATA', 1))


# ------------------------------------------------------------------ retained evidence
def sha(data): return hashlib.sha256(data).hexdigest()


def document():
    return {'version': 'schemaxis/1', 'nodes': [{'id': 's', 'filter': 'sphere'}],
            'scenes': [{'id': 'out', 'exports': [{
                'id': 'table', 'node': 's', 'writer': 'pvWriteCSVWriter', 'comparison': 'table', 'tolerance': 0.5,
                'acceptLosses': ['topology', 'coordinates', 'structure']}]}]}


class RetainedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.master, self.scenes, _ = plan(document())
        scene, visit = next(schedule(self.master, self.scenes))
        self.scene, self.visit = scene, visit
        self.identity = next(i for i in identities(scene, visit) if i['kind'] == 'export')
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.export = self.directory / '000000-out-export-0'
        self.export.mkdir()
        self.path = self.export / 'data.csv'
        self.path.write_bytes(b'"p"\n1\n2\n')
        self.expected = scene['exports'][0]

    def artifact(self):
        effective = self.master.declarations['pvWriteCSVWriter']
        from schemaxis.adaptors.paraview.filters import validate_options
        options = validate_options(effective, evaluate(self.expected['options'], {}, {'s': {}}, 0.0, 'table'), 'table')
        digest = sha(self.path.read_bytes())
        return {'file': str(self.path), 'sha256': digest, 'verified': True,
                'files': [{'file': str(self.path), 'sha256': digest}], 'writer': 'pvWriteCSVWriter',
                'effectiveOptions': options, 'comparison': 'table', 'acceptedLosses': self.expected['acceptLosses'],
                'tolerance': 0.5, 'readback': None, 'resources': {}, 'resourceProxyIds': {},
                'verification': {'comparison': 'table', 'rows': 2, 'verifiedColumns': ['p'], 'additionalColumns': [],
                                 'association': 'Row Data', 'delimiter': ','},
                'identity': self.identity}

    def receipt(self, artifact):
        digest = self.master.to_dict()
        receipt = {'status': 'succeeded', 'verified': True, 'planDigest': digest['digest'], 'planVersion': digest['version'],
                   'states': [{'scene': 'out', 'visit': self.visit, 'proxyIds': {'s': '1'},
                               'effective': {'s': self.master.nodes['s']['options']},
                               'observations': {'s': {}}, 'updated': ['s'], 'samples': []}],
                   'events': [{'event': 'create', 'node': 's'}, {'event': 'update', 'node': 's', 'time': 0.0},
                              {'event': 'delete', 'node': 's'}], 'artifacts': [artifact]}
        (self.directory / 'verification.json').write_text(json.dumps(receipt, allow_nan=True))

    def check(self, artifact):
        return verify_export_evidence(self.directory, artifact, self.expected, 'CSVWriter', 'out.exports[0]')

    def assertRejected(self, artifact, code, text=None):
        found = fault(self, lambda: self.check(artifact))
        self.assertEqual(found.code, code)
        if text is not None:
            self.assertIn(text, json.dumps(found.to_dict()))
        return found

    def test_complete_record_passes_and_the_receipt_verifies_end_to_end(self):
        artifact = self.artifact()
        self.check(artifact)
        self.receipt(artifact)
        self.assertTrue(verify_receipt(self.directory, self.master, self.scenes)['verified'])

    def test_indexed_export_names_are_bound_to_the_authored_scene_and_export(self):
        from schemaxis.artifact_names import VERSION, stem
        target = self.directory / '000007'
        self.export.rename(target)
        self.export, self.path = target, target / self.path.name
        basename = stem(7, {'kind': 'export', 'scene': 'out', 'name': self.expected['id'], 'time': self.visit['time']})
        self.path = self.path.rename(target / (basename + '.csv'))
        artifact = self.artifact()
        self.receipt(artifact)
        receipt_path = self.directory / 'verification.json'
        receipt = json.loads(receipt_path.read_text())
        receipt['artifactNamingVersion'] = VERSION
        receipt_path.write_text(json.dumps(receipt))
        self.assertTrue(verify_receipt(self.directory, self.master, self.scenes)['verified'])
        wrong = self.path.rename(target / (basename.replace('__name_', '__wrong_') + '.csv'))
        artifact['file'] = artifact['files'][0]['file'] = str(wrong)
        receipt['artifacts'][0] = artifact
        receipt_path.write_text(json.dumps(receipt))
        self.assertEqual(fault(self, lambda: verify_receipt(self.directory, self.master, self.scenes)).code,
                         'VERIFICATION_FAILED')

    def test_receipt_verification_refuses_each_tamper_through_the_shared_entry_point(self):
        for label, tamper, code in (
                ('unlisted file', lambda a: (self.export / 'extra.csv').write_text('x'), 'VERIFICATION_FAILED'),
                ('wrong comparison', lambda a: a['verification'].update(comparison='exact'), 'MALFORMED_EXPORT_EVIDENCE'),
                ('NaN evidence', lambda a: a['verification'].update(rows=NAN), 'NONFINITE_EVIDENCE')):
            with self.subTest(label):
                artifact = self.artifact()
                tamper(artifact)
                self.receipt(artifact)
                self.assertEqual(fault(self, lambda: verify_receipt(self.directory, self.master, self.scenes)).code, code)
                (self.export / 'extra.csv').unlink(missing_ok=True)

    def test_unlisted_extra_file_is_refused_with_its_name(self):
        artifact = self.artifact()
        (self.export / 'notes.txt').write_text('added after the run')
        found = self.assertRejected(artifact, 'VERIFICATION_FAILED', 'notes.txt')
        self.assertEqual(found.message, 'export directory membership differs from the retained record')

    def test_publication_sidecar_beside_a_listed_member_is_allowed_but_no_other_name(self):
        artifact = self.artifact()
        (self.export / 'data.csv.metadata.json').write_text('{}')
        self.check(artifact)
        (self.export / 'other.csv.metadata.json').write_text('{}')
        self.assertRejected(artifact, 'VERIFICATION_FAILED', 'other.csv.metadata.json')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX special file required')
    def test_unlisted_special_file_is_refused_without_reading_it(self):
        artifact = self.artifact()
        os.mkfifo(self.export / 'unexpected.pipe')
        self.assertRejected(artifact, 'VERIFICATION_FAILED', 'special file')

    def test_removed_member_is_a_structured_fault_not_a_file_error(self):
        artifact = self.artifact()
        self.path.unlink()
        self.assertRejected(artifact, 'VERIFICATION_FAILED', 'data.csv')

    def test_changed_file_content_is_refused(self):
        artifact = self.artifact()
        self.path.write_bytes(b'"p"\n1\n999\n')
        self.assertRejected(artifact, 'VERIFICATION_FAILED')

    def test_recorded_file_digest_must_equal_its_member_record(self):
        artifact = self.artifact()
        artifact['files'][0]['sha256'] = sha(b'other')
        self.assertRejected(artifact, 'VERIFICATION_FAILED')

    def test_member_records_must_be_wellformed_unique_and_include_the_export(self):
        for label, change in (('empty', lambda a: a.update(files=[])),
                              ('missing key', lambda a: a['files'][0].pop('sha256')),
                              ('short digest', lambda a: a['files'][0].update(sha256='abc')),
                              ('uppercase digest', lambda a: a['files'][0].update(sha256='A' * 64)),
                              ('duplicate', lambda a: a['files'].append(dict(a['files'][0]))),
                              ('not a list', lambda a: a.update(files='data.csv'))):
            with self.subTest(label):
                artifact = self.artifact()
                change(artifact)
                self.assertRejected(artifact, 'MALFORMED_EXPORT_EVIDENCE')

    def test_member_outside_the_export_directory_is_refused(self):
        artifact = self.artifact()
        other = self.directory / 'elsewhere.csv'
        other.write_bytes(b'x')
        artifact['files'].append({'file': str(other), 'sha256': sha(b'x')})
        self.assertRejected(artifact, 'VERIFICATION_FAILED', 'outside the export directory')

    def test_export_file_must_have_the_managed_name(self):
        artifact = self.artifact()
        renamed = self.export / 'other.csv'
        self.path.rename(renamed)
        artifact['file'] = str(renamed)
        artifact['files'][0]['file'] = str(renamed)
        self.assertRejected(artifact, 'VERIFICATION_FAILED', 'managed name')

    def test_export_file_outside_its_own_output_directory_is_refused(self):
        artifact = self.artifact()
        artifact['file'] = artifact['files'][0]['file'] = str(self.directory / 'data.csv')
        (self.directory / 'data.csv').write_bytes(self.path.read_bytes())
        self.assertRejected(artifact, 'VERIFICATION_FAILED', 'own output directory')

    def test_symbolic_link_in_the_export_directory_is_refused(self):
        artifact = self.artifact()
        (self.export / 'link.csv').symlink_to(self.path)
        self.assertRejected(artifact, 'VERIFICATION_FAILED', 'symbolic link')

    def test_verification_evidence_shape_for_each_comparison(self):
        base = {'tolerance': 0.5, 'comparison': 'table'}
        cases = [
            ('table', {'comparison': 'table', 'rows': -1, 'verifiedColumns': ['p'], 'additionalColumns': [], 'association': 'Row Data', 'delimiter': ','}),
            ('table', {'comparison': 'table', 'rows': 2, 'verifiedColumns': [], 'additionalColumns': [], 'association': 'Row Data', 'delimiter': ','}),
            ('table', {'comparison': 'table', 'rows': 2, 'verifiedColumns': ['p'], 'additionalColumns': ['p'], 'association': 'Row Data', 'delimiter': ','}),
            ('table', {'comparison': 'table', 'rows': 2, 'verifiedColumns': ['p'], 'additionalColumns': [], 'association': 'Field Data', 'delimiter': ','}),
            ('table', {'comparison': 'table', 'rows': True, 'verifiedColumns': ['p'], 'additionalColumns': [], 'association': 'Row Data', 'delimiter': ','}),
            ('table', None), ('table', []),
            ('exact', {'comparison': 'exact'}),
            ('exact', {'comparison': 'exact', 'data': {}}),
            ('semantic', {'comparison': 'semantic', 'tolerance': 0.5, 'associations': {'point': {'records': 1, 'fields': []}}}),
            ('semantic', {'comparison': 'semantic', 'tolerance': 0.25, 'associations': {'point': {'records': 1, 'fields': []}, 'cell': {'records': 1, 'fields': []}}}),
            ('geometry', {'comparison': 'geometry', 'tolerance': 0.5, 'surfaceCells': 0}),
            ('geometry', {'comparison': 'geometry', 'tolerance': 0.0, 'surfaceCells': 4}),
            ('pixels', {'comparison': 'pixels', 'dimensions': [2, 2, 1], 'maximumError': 0.75}),
            ('pixels', {'comparison': 'pixels', 'dimensions': [2, 2, 1], 'maximumError': -0.1}),
            ('pixels', {'comparison': 'pixels', 'dimensions': [2, 2], 'maximumError': 0.1}),
            ('pixels', {'comparison': 'pixels', 'format': 'vtk-json-image', 'fields': [], 'tolerance': 0.5}),
        ]
        for comparison, evidence in cases:
            with self.subTest(comparison=comparison, evidence=evidence):
                self.expected = {**self.expected, 'comparison': comparison}
                artifact = self.artifact()
                artifact['verification'] = evidence
                self.assertRejected(artifact, 'MALFORMED_EXPORT_EVIDENCE')

    def test_valid_evidence_for_the_other_comparisons_passes(self):
        good = {
            'exact': {'comparison': 'exact', 'data': {'type': 'vtkPolyData'}},
            'semantic': {'comparison': 'semantic', 'tolerance': 0.5,
                         'associations': {'point': {'records': 3, 'fields': ['p']}, 'cell': {'records': 1, 'fields': []}}},
            'geometry': {'comparison': 'geometry', 'tolerance': 0.5, 'surfaceCells': 2},
            'pixels': {'comparison': 'pixels', 'dimensions': [2, 2, 1], 'maximumError': 0.5},
        }
        for comparison, evidence in good.items():
            with self.subTest(comparison):
                self.expected = {**self.expected, 'comparison': comparison}
                artifact = self.artifact()
                artifact['verification'] = evidence
                self.check(artifact)

    def test_nonfinite_numbers_in_retained_json_are_refused_wherever_they_appear(self):
        artifact = self.artifact()
        artifact['effectiveOptions'] = {'Precision': INF}
        found = self.assertRejected(artifact, 'NONFINITE_EVIDENCE')
        self.assertEqual(found.observed['at'], ['artifact.effectiveOptions.Precision'])
        # Python's JSON reader accepts these literals, so a hand-edited receipt would otherwise pass.
        text = json.dumps(self.artifact()).replace('"rows": 2', '"rows": NaN')
        self.assertTrue(json.loads(text)['verification']['rows'] != json.loads(text)['verification']['rows'])
        self.assertRejected(json.loads(text), 'NONFINITE_EVIDENCE')


if __name__ == '__main__':
    unittest.main()
