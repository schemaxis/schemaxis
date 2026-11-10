"""Typed STL plans and exact retained captures stay native-free."""
import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from schemaxis.adaptors.freecad import adaptor,saved_checks,step_source
from schemaxis.core.faults import SchemaxisError
from test_freecad_mesh_source import binary,box


class MeshImport(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'sample.stl';self.source.write_bytes(binary(box(1,2,3)))
        self.document={'version':'schemaxis.freecad/1','nodes':[{'id':'mesh','filter':'importMesh',
                        'options':{'file':str(self.source),'units':'inch','orientation':{'z':'+Y','x':'-X'},
                                   'placement':{'position':[4,5,6],'clocking':90}}}],'output':'mesh'}
    def tearDown(self):self.temp.cleanup()

    def test_planning_is_native_free_and_maps_explicit_units_and_frames(self):
        with patch('subprocess.Popen',side_effect=AssertionError('native process forbidden')):
            result=adaptor.plan(self.document)
        node=result['nodes'][0];self.assertAlmostEqual(node['source']['volume'],6*25.4**3)
        self.assertEqual(node['source']['facets'],12);self.assertFalse(node['options']['reverseWinding'])
        self.assertEqual(node['frame']['translation'],[4,5,6]);self.assertEqual(node['frame']['worldFromFile'],[[0.,0.,-1.],[-1.,0.,0.],[0.,1.,0.]])
        choices=list(adaptor.DECLARATIONS)
        self.assertEqual(choices[42:44],['bodyDraft','importMesh'])
        unknown=copy.deepcopy(self.document);unknown['nodes'][0]['options']['repair']=True
        with self.assertRaises(SchemaxisError):adaptor.plan(unknown)

    def test_capture_and_replay_use_owned_retained_stl_after_original_removal(self):
        from schemaxis.adaptors.freecad.integration import reusableInputs,retainedInputs
        first=adaptor.plan(self.document);directory=self.root/'run';directory.mkdir()
        self.assertEqual(reusableInputs(self.document),{str(self.source):first['nodes'][0]['source']['sha256']})
        records=adaptor.capture(first,directory);self.source.unlink()
        with patch('subprocess.Popen',side_effect=AssertionError('native process forbidden')):
            replay=adaptor.plan(self.document,source=step_source.CapturedSources(directory,records))
            saved_checks.verify_sources(directory,replay,records)
        from schemaxis.artifacts import atomic_json
        atomic_json(directory/'plan.json',first);atomic_json(directory/'sources.json',records)
        self.assertEqual(retainedInputs(directory,self.document),{str(self.source):first['nodes'][0]['source']['sha256']})
        self.assertEqual(first,replay);self.assertEqual(records['mesh']['route'],'importMesh')
        target=directory/'mesh-import-0.stl';target.write_bytes(binary(box(1,2,4)))
        with self.assertRaises(SchemaxisError):adaptor.plan(self.document,source=step_source.CapturedSources(directory,records))

    def test_invalid_topology_winding_and_aggregate_limits_refuse_before_native(self):
        self.source.write_bytes(binary(box()[:-1]))
        with patch('subprocess.Popen',side_effect=AssertionError('native process forbidden')):
            with self.assertRaises(SchemaxisError):adaptor.plan(self.document)
        self.source.write_bytes(binary(box()))
        second=copy.deepcopy(self.document);second['nodes'].append({'id':'second','filter':'importMesh',
            'options':{'file':str(self.source),'units':'mm'}})
        with patch('schemaxis.adaptors.freecad.mesh_source.MAX_FACETS',20):
            with self.assertRaises(SchemaxisError) as caught:adaptor.plan(second)
        self.assertEqual(caught.exception.fault.code,'RESOURCE_LIMIT')
        self.source.write_bytes(binary([(a,c,b) for a,b,c in box()]))
        with self.assertRaises(SchemaxisError):adaptor.plan(self.document)
        self.document['nodes'][0]['options']['reverseWinding']=True
        self.assertGreater(adaptor.plan(self.document)['nodes'][0]['source']['volume'],0)

    def test_body_import_combination_remains_an_explicit_unimplemented_bridge(self):
        self.document['nodes'].append({'id':'body','filter':'body'})
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(self.document)
        self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_SOURCE')
