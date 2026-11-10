# Copyright (C) 2026 David L F Gaden
"""Host contract and independent parser checks; no meshio/NumPy import."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis.adaptors.meshio import adaptor, reference
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]


class MeshioTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((ROOT/'examples/schemaxis/meshio-convert.json').read_text())
        self.document['source'] = str(ROOT/'examples/schemaxis/fixtures/meshio/mixed.vtu')

    def test_plan_is_immutable_and_units_explicit(self):
        original = copy.deepcopy(self.document)
        self.assertEqual(adaptor._native_plan(self.document)['factor'], .001)
        self.assertEqual(self.document, original)
        for change in ({'sourceUnits': 'guess'}, {'lossPolicy': 'discard'}, {'source': 'relative.vtu'}, {'sourceFormat': 'vtk'}, {'targetUnits': True}, {'extra': 1}):
            with self.subTest(change=change), self.assertRaises(SchemaxisError):
                adaptor._native_plan({**self.document, **change})
        for key in adaptor.OPTIONS:
            with self.subTest(missing=key), self.assertRaises(SchemaxisError):
                adaptor._native_plan({k:v for k,v in self.document.items() if k != key})

    def test_literal_independent_formats_and_orientation(self):
        a = reference.vtu(Path(self.document['source']).read_bytes())
        b = reference.vtk((ROOT/'examples/schemaxis/fixtures/meshio/mixed.vtk').read_bytes())
        reference.compare(reference.scaled(a, .001), b)
        self.assertEqual(a['cells'], [['triangle', [0,1,2]], ['tetra', [0,1,2,3]], ['triangle', [1,4,2]]])
        self.assertEqual(reference.summary(a)['tetraVolumes'], [4])
        self.assertEqual(a['pointData']['node_id'], [[101],[203],[307],[409],[503]])
        self.assertEqual(a['cellData']['direction'], [[1,0,0],[0,1,0],[0,0,-1]])
        for factor in (1e-6, 1, 1e6):
            self.assertEqual(len(reference.validate(reference.scaled(a, factor))['cells']), 3)
        for ids in ([1,0,2,3], [0,1,2,2]):
            invalid=copy.deepcopy(a);invalid['cells'][1][1]=ids
            with self.assertRaises(ValueError):reference.validate(invalid)

    def test_hostile_source_and_exact_order(self):
        source=Path(self.document['source']).read_bytes()
        with self.assertRaises((ValueError, UnicodeError)):
            reference.vtu(source.decode().encode('utf-16'))
        for raw in (source.replace(b'format="ascii"',b'format="binary"'),source.replace(b'<VTKFile',b'<!DOCTYPE evil><VTKFile'),source.replace(b'5 10 5',b'5 13 5'),source.replace(b'3 7 10',b'3 8 10'),source.replace(b'101 203',b'9007199254740993 203'),source.replace(b'10 20 30',b'nan 20 30'),source.replace(b'</Piece>',b'<FieldData/></Piece>')):
            with self.assertRaises(ValueError):reference.vtu(raw)
        valid=reference.vtu(source);altered=copy.deepcopy(valid);altered['cells'].reverse()
        with self.assertRaisesRegex(ValueError,'topology'):reference.compare(valid,altered)
        altered=copy.deepcopy(valid);altered['pointData']['node_id'][0][0]+=1
        with self.assertRaises(ValueError):reference.compare(valid,altered)

    def test_regular_file_bounds_and_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'a.vtu';path.write_bytes(Path(self.document['source']).read_bytes())
            first=adaptor.bounded(path)
            link=Path(folder)/'link.vtu';link.symlink_to(path)
            with self.assertRaises(SchemaxisError):adaptor.bounded(link)
            with self.assertRaises(SchemaxisError):adaptor.bounded(path,limit=4)
            self.assertGreater(len(first),4)

    def test_declared_precision_ranges_and_xml_text(self):
        self.assertEqual(reference.numbers('0.1', 'Float32'), [0.10000000149011612])
        for text, dtype in [('300', 'Int8'), ('-1', 'UInt8'), ('65536', 'UInt16'), ('2147483648', 'int'), ('inf', 'Float32')]:
            with self.subTest(dtype=dtype), self.assertRaises(ValueError):
                reference.numbers(text, dtype)
        source=Path(self.document['source']).read_bytes()
        for data in (source.replace(b'<Cells>',b'<Cells>discard me'),source.replace(b'</Cells>',b'</Cells>discard me'),source.replace(b'</PointData>',b'</PointData><PointData/>')):
            with self.assertRaises(ValueError):reference.vtu(data)

    def test_schema_and_declarations_cover_every_option(self):
        literal=adaptor.schema()
        self.assertEqual(set(literal['properties']),{'version','operation',*adaptor.OPTIONS})
        self.assertEqual(set(literal['required']),set(literal['properties']))
        self.assertFalse(literal['additionalProperties'])
        self.assertEqual(set(adaptor.DECLARATIONS['convert']['options']),set(adaptor.OPTIONS))

    def test_small_cells_at_large_origin_need_area_preservation(self):
        mesh=reference.vtu(Path(self.document['source']).read_bytes())
        for point in mesh['points']:point[0]+=1e8
        changed=copy.deepcopy(mesh);changed['points'][1][0]+=.0001
        with self.assertRaisesRegex(ValueError,'area/volume'):
            reference.compare(mesh,changed)

    def test_studio_source_placeholder_edit_and_undo(self):
        from schemaxis.adaptors import registry
        from schemaxis.console_session import AdaptorConsoleSession
        from schemaxis.studio_library import instantiate_item, load_library, apply_inserts
        library=load_library('meshio');original=copy.deepcopy(library)
        for item in library['templates']:
            filled=instantiate_item(library,item,provider='meshio')
            self.assertEqual(registry.plan(filled)['operation'],'convert')
            with self.assertRaises(SchemaxisError):
                registry.plan(instantiate_item(library,item,provider='meshio',filled=False))
            altered=apply_inserts(filled,[{'at':'','merge':{'targetUnits':'cm'}}])
            self.assertEqual(registry.plan(altered)['targetUnits'],'cm')
        self.assertEqual(library,original)
        with tempfile.TemporaryDirectory() as folder:
            session=AdaptorConsoleSession(folder,provider='meshio')
            try:
                before=session.document;draft=session.draft()
                result=session.edit_source(json.dumps({**before,'targetUnits':'cm'}),session.active_document,draft['revision'])
                self.assertFalse(result.get('diagnostics'))
                self.assertEqual(session.document['targetUnits'],'cm')
                session.undo();self.assertEqual(session.document,before)
            finally:session.close()


if __name__ == '__main__': unittest.main()
