import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
import zipfile
from schemaxis.core.faults import SchemaxisError
from schemaxis.documents import resolve_document
from schemaxis.functions import FUNCTIONS
from schemaxis.camera import camera_values
from schemaxis.adaptors.registry import query
from schemaxis.job import plan, runtime_archive
from schemaxis.schema import expand_input

ROOT = Path(__file__).resolve().parents[2]


class HumanInputTests(unittest.TestCase):
    def call(self, name, **args):
        return FUNCTIONS.invoke(name, args, 'test')

    def test_dimensions_drive_wake_and_endpoint_positions(self):
        doc=json.loads((ROOT/'examples/paraview-vehicle-demo/humanInput.json').read_text())
        doc['dimensions']={'model':{'min':[10,-1,0], 'max':[13.5,1,1]},'ground':-0.5}
        result,_=resolve_document(doc)
        bounds=result['views']['modelAndWake']
        self.assertEqual(bounds['min'],[6.5,-3,-0.5])
        self.assertEqual(bounds['max'],[22.25,3,2.875])
        origins=next(n for n in result['nodes'] if n['id']=='sliceX')['options']['origin']['$analytic']['values']
        self.assertEqual(origins[0][0],6.5)
        self.assertEqual(origins[-1][0],22.25)
        step=origins[1][0]-origins[0][0]
        self.assertTrue(all(abs(b[0]-a[0]-step)<1e-12 for a,b in zip(origins,origins[1:])))
        self.assertFalse(any(n['filter']=='clip' for n in result['nodes']))
        result['times']=[1]
        self.assertEqual(sum(s['publications'] for s in plan(result)[1]),93)

    def test_bounds_union_shrink_and_invalid_extent(self):
        box={'min':[0,0,0],'max':[4,2,1]}
        shrunk=self.call('boundsExtend',bounds=box,before=[-.1,0,0],after=[-.1,0,0])
        self.assertEqual(shrunk,{'min':[.4,0,0],'max':[3.6,2,1]})
        self.assertEqual(self.call('boundsUnion',bounds=[box,{'min':[-1,0,0],'max':[2,3,4]}]),
                         {'min':[-1,0,0],'max':[4,3,4]})
        with self.assertRaises(SchemaxisError):self.call('boundsExtend',bounds=box,before=[-2,0,0])
        with self.assertRaises(SchemaxisError):self.call('boundsFrame',bounds=box,floor=1)

    def test_direction_vector_and_camera_share_azel(self):
        vector=self.call('directionVector',direction={'azimuth':90,'elevation':0},length=3)
        self.assertAlmostEqual(vector[0],0)
        self.assertAlmostEqual(vector[1],3)
        camera=camera_values({'direction':{'azimuth':90,'elevation':30},'up':'z+'},'camera')
        self.assertAlmostEqual(camera['direction'][2],.5)
        self.assertEqual(camera_values({'direction':'x-'},'camera')['direction'],[-1,0,0])
        with self.assertRaises(SchemaxisError):camera_values({'direction':'z+','up':'z+'},'camera')

    def test_fitted_camera_projects_all_box_corners(self):
        box={'min':[-9,-2,-1],'max':[9,2,3]}
        camera=self.call('fitCamera',bounds=box,direction='y+',aspect=[16,9],padding=0)
        self.assertAlmostEqual(camera['scale'],18/2*9/16)
        self.assertEqual(camera['focalPoint'],[0,0,1])
        self.assertTrue(camera['parallel'])
        cameras=self.call('orbitCameras',bounds=box,count=12,elevation=25)
        self.assertEqual(len(cameras),12)
        self.assertNotEqual(cameras[0]['direction'],cameras[-1]['direction'])

    def test_one_slice_uses_centre_and_invalid_count_rejected(self):
        box={'min':[0,0,0],'max':[2,4,6]}
        self.assertEqual(self.call('slicePositions',bounds=box,axis='z',count=1),[[1,2,3]])
        with self.assertRaises(SchemaxisError):self.call('slicePositions',bounds=box,axis='z',count=10001)

    def test_authoring_reports_reference_and_value_provenance(self):
        doc={'dimensions':{'box':{'min':[0,0,0],'max':[2,4,6]}},
             'centre':{'$value':'boundsCentre3D','args':{'bounds':{'$document':'/dimensions/box'}}}}
        resolved,evidence=resolve_document(doc)
        self.assertEqual(resolved['centre'],[1,2,3])
        self.assertTrue(any(e.get('function')=='boundsCentre3D' for e in evidence))
        with self.assertRaises(SchemaxisError):resolve_document({'x':{'$value':'eval','args':{}}})
        with self.assertRaises(SchemaxisError):resolve_document({'x':{'$document':'/x'}})
        with self.assertRaises(SchemaxisError):resolve_document({'x':{'$value':'boundsSize','args':{'bounds':{'$document':'/x'}}}})

    def test_query_finds_adaptor_and_reports_unknown_operations(self):
        doc=json.loads((ROOT/'examples/paraview-vehicle-demo/humanInput.json').read_text())
        result=query(doc)
        self.assertTrue(result['supported'])
        self.assertEqual(result['adaptors'][0]['adaptor'],'paraview')
        self.assertEqual(result['adaptors'][0]['availability'],'not checked')
        doc['nodes'][0]['filter']='imaginary'
        self.assertFalse(query(doc)['supported'])
        self.assertEqual(query(operations=['foam'])['adaptors'][0]['adaptor'],'paraview')
        self.assertFalse(query(operations=['imaginary'])['supported'])

    def test_host_discovery_does_not_import_native_applications(self):
        script="from schemaxis.adaptors.registry import discover; discover(); import sys; assert not {'bpy','paraview'} & set(sys.modules)"
        subprocess.run([sys.executable,'-c',script],check=True)

    def test_archive_contains_adaptor_packages_and_compatibility_imports(self):
        with zipfile.ZipFile(io.BytesIO(runtime_archive())) as archive:
            for path in ['schemaxis/adaptors/__init__.py','schemaxis/adaptors/paraview/native.py',
                         'schemaxis/adaptors/blender/native.py','schemaxis/spatial.py','schemaxis/native.py']:
                self.assertIn(path,archive.namelist())
            self.assertFalse(any('__pycache__' in p for p in archive.namelist()))
        from schemaxis import native
        from schemaxis.adaptors.paraview import native as canonical
        self.assertIs(native,canonical)

    def test_human_input_expands_and_is_strictly_schema_valid(self):
        import jsonschema
        from schemaxis.schema import export_schema
        doc=json.loads((ROOT/'examples/paraview-vehicle-demo/humanInput.json').read_text())
        jsonschema.validate(expand_input(doc),export_schema())
        doc['nodes'][0]['options']['garbage']=True
        with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(expand_input(doc),export_schema())
