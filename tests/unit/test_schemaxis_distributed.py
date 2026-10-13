"""Distributed execution policy and complete, streaming artifact verification."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.paraview.execution import validate_mpi
from schemaxis.adaptors.paraview.parallel_files import manifest, members, verify_manifest
from schemaxis.parallel import work_items


class PolicyTests(unittest.TestCase):
    def test_real_cfd_time_selector_plans_without_native_imports(self):
        document = json.loads(Path('examples/schemaxis/foam.json').read_text())
        capability = validate_mpi(document)
        self.assertIn('foam', capability['mpiOperations'])
        self.assertEqual(capability['mpiDriver'], 'normal pvbatch (one Python driver)')

    def test_full_table_and_index_sampling_require_a_reduction(self):
        document = {'version': 'schemaxis/1', 'nodes': [{'id': 'sphere', 'filter': 'sphere'}],
                    'scenes': [{'id': 'view', 'geometry': ['sphere'], 'measurements': [{'node': 'sphere'}]}]}
        with self.assertRaises(SchemaxisError) as error:
            validate_mpi(document)
        self.assertEqual(error.exception.fault.code, 'UNSUPPORTED_MPI_MEASUREMENT')
        document['nodes'].append({'id': 'total', 'filter': 'integrate', 'inputs': {'input': 'sphere'}})
        document['scenes'][0]['measurements'][0]['node'] = 'total'
        validate_mpi(document)

    def test_unqualified_operation_remains_explicit(self):
        document = {'version': 'schemaxis/1', 'nodes': [{'id': 'box', 'filter': 'cone'}],
                    'scenes': [{'id': 'view', 'geometry': ['box']}]}
        with self.assertRaises(SchemaxisError) as error:
            validate_mpi(document)
        self.assertEqual(error.exception.fault.code, 'UNSUPPORTED_MPI_PIPELINE')

    def test_parallel_readers_are_discoverable(self):
        from schemaxis.adaptors.paraview.filters import catalogue
        for name, native in [('readParallelPolyData', 'XMLPartitionedPolydataReader'),
                             ('readParallelUnstructuredGrid', 'XMLPartitionedUnstructuredGridReader')]:
            self.assertEqual(catalogue()[name]['native'], native)


class ManifestTests(unittest.TestCase):
    def fixture(self, root):
        (root/'pieces').mkdir()
        (root/'pieces/part.vtu').write_bytes(b'native piece bytes')
        (root/'data.pvtu').write_text('<VTKFile><PUnstructuredGrid><Piece Source="pieces/part.vtu"/></PUnstructuredGrid></VTKFile>')
        return root/'data.pvtu'

    def test_missing_changed_and_omitted_pieces_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.fixture(Path(tmp))
            artifact = {'file': str(path), 'files': manifest(path)}
            verify_manifest(artifact)
            incomplete = copy.deepcopy(artifact)
            incomplete['files'] = incomplete['files'][:1]
            with self.assertRaises(SchemaxisError):
                verify_manifest(incomplete)
            (path.parent/'pieces/part.vtu').write_bytes(b'corrupted')
            with self.assertRaises(SchemaxisError):
                verify_manifest(artifact)
            (path.parent/'pieces/part.vtu').unlink()
            with self.assertRaises(SchemaxisError):
                verify_manifest(artifact)

    def test_nested_references_are_closed_and_cannot_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = self.fixture(root)
            outer = root/'outer.vtm'
            outer.write_text('<VTKFile><DataSet file="data.pvtu"/></VTKFile>')
            self.assertEqual(len(members(outer)), 3)
            data.write_text('<VTKFile><Piece Source="../outside.vtu"/></VTKFile>')
            with self.assertRaises(SchemaxisError):
                members(outer)

    def test_symlink_escape_and_invalid_xml_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root/'output'
            out.mkdir()
            path = self.fixture(out)
            outside = root/'outside'
            outside.write_bytes(b'data')
            (out/'pieces/part.vtu').unlink()
            (out/'pieces/part.vtu').symlink_to(outside)
            with self.assertRaises(SchemaxisError):
                members(path)
            path.write_text('not XML')
            with self.assertRaises(SchemaxisError):
                members(path)


class EvidenceTests(unittest.TestCase):
    def piece(self):
        import hashlib
        from schemaxis.adaptors.paraview.parallel_files import canonical
        records = [{'rank': 0, 'size': 2, 'data': {'points': 3, 'cells': 1, 'coordinates': {'sha256': 'a'}}},
                   {'rank': 1, 'size': 2, 'empty': True}]
        return {'verification': {'method': 'exact-per-piece-v1', 'gatheredGeometry': False,
                                 'before': records, 'after': copy.deepcopy(records)},
                'dataDigest': hashlib.sha256(json.dumps(canonical(records)).encode()).hexdigest()}

    def test_every_rank_is_required_and_geometry_change_is_rejected(self):
        from schemaxis.adaptors.paraview.parallel_files import verify_piece_evidence
        original = self.piece()
        verify_piece_evidence(original, 2)
        changed = copy.deepcopy(original)
        changed['verification']['after'][0]['data']['coordinates']['sha256'] = 'b'
        with self.assertRaises(SchemaxisError):
            verify_piece_evidence(changed, 2)
        changed = copy.deepcopy(original)
        changed['verification']['after'].pop()
        with self.assertRaises(SchemaxisError):
            verify_piece_evidence(changed, 2)

    def test_whole_piece_migration_preserves_exact_identity(self):
        from schemaxis.adaptors.paraview.parallel_files import verify_piece_evidence
        changed = self.piece()
        data = changed['verification']['after'][0].pop('data')
        changed['verification']['after'][0]['empty'] = True
        changed['verification']['after'][1] = {'rank': 1, 'size': 2, 'data': data}
        verify_piece_evidence(changed, 2)

    def test_reduction_csv_is_bound_to_rank_evidence(self):
        from schemaxis.adaptors.paraview.parallel_files import verify_reduction_evidence
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'total.csv'
            path.write_text('index,Volume[0]\n0,8.0\n')
            artifact = {'file': str(path), 'gatheredGeometry': False, 'columns': ['index', 'Volume[0]'],
                        'values': [[0, 8.0]], 'rows': 1, 'reductionEvidence': [
                            {'rank': 0, 'size': 2, 'headers': ['Volume[0]'], 'values': [8.0]},
                            {'rank': 1, 'size': 2, 'empty': True}]}
            verify_reduction_evidence(artifact, 2)
            path.write_text('index,Volume[0]\n0,9.0\n')
            with self.assertRaises(SchemaxisError):
                verify_reduction_evidence(artifact, 2)
