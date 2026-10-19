"""FreeCAD contracts stay host-safe and reject false or altered CAD evidence."""
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.freecad.adaptor import FILES, plan, verify
from schemaxis.adaptors.paraview.parallel_files import file_digest
from schemaxis.artifacts import atomic_json
from schemaxis.parallel import work_items, reusable_inputs
from schemaxis.schema import export_schema
from schemaxis.workflow import inspect_plan


def box():
    return {'version':'schemaxis.freecad/1', 'nodes':[{'id':'block','filter':'box'}], 'output':'block'}


class FreeCADTests(unittest.TestCase):
    def test_discovery_and_planning_never_import_native_modules(self):
        script = '''
import sys
from schemaxis.adaptors.registry import discover, query
from schemaxis.adaptors.freecad.adaptor import plan
assert 'freecad' in [p['id'] for p in discover()['providers']]
assert query({'version':'schemaxis.freecad/1','nodes':[{'id':'b','filter':'box'}],'output':'b'})['supported']
assert not any(m in sys.modules for m in ('FreeCAD','Part','Mesh','bpy','paraview'))
'''
        subprocess.run([sys.executable,'-c',script],check=True)

    def test_literal_dimensions_and_dependencies_reject_invalid_data(self):
        for options in ({'length':0},{'length':-1},{'length':True},{'length':float('nan')},{'length':100001},{'origin':[1,2]}, {'width':{'$eval':'1+1'}}, {'surprise':1}):
            doc=box();doc['nodes'][0]['options']=options
            with self.subTest(options=options),self.assertRaises(SchemaxisError): plan(doc)
        for node in ({'id':'b','filter':'cylinder','options':{'axis':[0,0,0]}},
                     {'id':'b','filter':'cut','inputs':{'base':'missing','tool':'missing'}},
                     {'id':'b','filter':'cut'}, {'id':'b','filter':'eval'}, {'id':'b','filter':[]}):
            with self.subTest(node=node),self.assertRaises(SchemaxisError): plan({**box(),'nodes':[node]})
        for change in ({'units':'m'},{'output':'absent'},{'script':'print(1)'},{'nodes':[]}, {'nodes':box()['nodes']*2}):
            with self.assertRaises(SchemaxisError):plan({**box(),**change})

    def test_schema_and_examples_share_literal_contract(self):
        schema=export_schema('freecad')
        length=schema['properties']['nodes']['items']['oneOf'][0]['properties']['options']['properties']['length']
        self.assertEqual(length['exclusiveMinimum'],0)
        for example in ('bracket','flange'):
            prepared=plan(json.loads(Path(f'examples/schemaxis/freecad-{example}.json').read_text()))
            self.assertEqual(prepared['units'],'mm')
            self.assertEqual(prepared['expectedPublications'],3)
        report=inspect_plan(json.loads(Path('examples/schemaxis/freecad-to-blender.json').read_text()))
        self.assertEqual(len(report['jobs']),6)

    def test_scheduler_uses_processes_without_mpi_or_time_batches(self):
        workflow={'version':'schemaxis.workflow/1','operations':[{'id':'cad','document':box()}]}
        self.assertEqual(work_items(workflow)[2][0]['resources']['ranks'],1)
        self.assertEqual(reusable_inputs(box()),{})
        for execution in ({'ranks':2,'mpiexec':'/tmp/mpi'}, {'timeChunkSize':2}):
            workflow['operations'][0]['execution']=execution
            with self.assertRaises(SchemaxisError):work_items(workflow)

    def fixture(self,directory):
        # Host-authored geometry exercises receipt verification; it is not native qualification.
        from tests.unit.test_freecad_step_import import Q, box_triangles, native, write_stl
        from schemaxis.adaptors.freecad.saved_checks import EXPORT_EVIDENCE
        doc=box();prepared=plan(doc)
        shape=native((0,0,0),(10,10,10))
        atomic_json(directory/'authored.json',doc);atomic_json(directory/'plan.json',prepared)
        atomic_json(directory/'built.json',{'definition':prepared,'shape':shape,'importObservations':{},
            'exportEvidence':{'version':EXPORT_EVIDENCE,'shape':shape,
                'meshing':{'linearDeflection':prepared['linearDeflection']/2,'angularDeflection':0.1,'relative':False}}})
        atomic_json(directory/'result.json',{'verified':True})
        Q.write_planar(directory/'model.step',Q.prism([(0,0),(10,0),(10,10),(0,10)],[],0,10))
        write_stl(directory/'model.stl',box_triangles((0,0,0),(10,10,10)))
        with ZipFile(directory/'model.FCStd','w') as archive:
            archive.writestr('Document.xml','<Document><Objects><Object name="N0" type="Part::Box"/></Objects>'
                '<ObjectData><Object name="N0"><Properties/></Object></ObjectData></Document>')
        artifacts=[]
        for filename,kind in FILES:
            p=directory/filename
            artifacts.append({'file':str(p),'kind':kind,'units':'mm','sha256':file_digest(p)})
        receipt={'status':'succeeded','freshProcess':True,'units':'mm','definition':prepared,'runtime':['1','1','3'],
                 'importObservations':{},'exportEvidence':{'version':EXPORT_EVIDENCE,'native':copy.deepcopy(shape),'step':copy.deepcopy(shape)},
                 'native':copy.deepcopy(shape),'step':copy.deepcopy(shape),'mesh':{'solid':True,'volume':1000.,'facets':12,'bounds':shape['bounds']},'artifacts':artifacts}
        atomic_json(directory/'verification.json',receipt)
        from schemaxis.publication_metadata import finalise
        finalise(directory)
        return receipt

    def test_receipt_checks_scientific_evidence_and_complete_membership(self):
        mutations=[lambda r:r['step'].update(volume=900),lambda r:r['native'].update(solids=2),
                   lambda r:r['mesh'].update(solid=False),lambda r:r['mesh'].update(facets=10),
                   lambda r:r['mesh'].update(bounds=[0,11,0,10,0,10]),lambda r:r.update(freshProcess=False),
                   lambda r:r['artifacts'].pop(),lambda r:r['artifacts'][0].update(units='m'),
                   lambda r:r['definition'].update(output='absent')]
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp);original=self.fixture(target)
            self.assertTrue(verify(target)['verified'])
            for mutate in mutations:
                receipt=copy.deepcopy(original);mutate(receipt);atomic_json(target/'verification.json',receipt)
                with self.assertRaises(SchemaxisError):verify(target)

    def test_legacy_evidence_requires_rerun_and_host_mesh_volume_is_authoritative(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp);receipt=self.fixture(target)
            receipt['mesh']['volume']=0.0  # Known far-placement native accumulator failure.
            atomic_json(target/'verification.json',receipt)
            self.assertTrue(verify(target)['verified'])
            receipt.pop('exportEvidence')
            atomic_json(target/'verification.json',receipt)
            with self.assertRaises(SchemaxisError) as caught:verify(target)
            self.assertEqual(caught.exception.fault.code,'RERUN_REQUIRED')

    def test_modified_and_escaped_artifacts_fail_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp);self.fixture(target)
            (target/'model.step').write_text('changed')
            with self.assertRaises(SchemaxisError):verify(target)
            receipt=self.fixture(target);receipt['artifacts'][0]['file']='/tmp/outside.step'
            atomic_json(target/'verification.json',receipt)
            with self.assertRaises(SchemaxisError):verify(target)
