"""Host and native qualification for list CAD ports, curves and scene transforms."""
import copy
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.core.faults import SchemaxisError
from schemaxis.tabular import close
from schemaxis.adaptors.freecad import adaptor as cad
from schemaxis.adaptors.blender import adaptor as blender
from schemaxis.adaptors.blender.table_curve import points_from_csv
from schemaxis.adaptors.godot import adaptor as godot

ROOT=Path(__file__).resolve().parents[2]


def example(name):return json.loads((ROOT/'examples/schemaxis'/(name+'.json')).read_text())


class CADListPorts(unittest.TestCase):
    def test_loft_and_union_schema_and_kind_contracts(self):
        for name,op,port in [('freecad-loft','loft','sections'),('freecad-multi-fuse','multiFuse','shapes')]:
            doc=example(name);prepared=cad.plan(doc)
            self.assertEqual(prepared['nodes'][-1]['filter'],op)
            variants=cad.schema()['properties']['nodes']['items']['oneOf']
            variant=next(v for v in variants if v['properties']['filter']['const']==op)
            spec=variant['properties']['inputs']['properties'][port]
            self.assertEqual(spec['type'],'array');self.assertEqual(spec['minItems'],2);self.assertTrue(spec['uniqueItems'])
            for value in ('base',[],['base'],[None,'missing'],['missing','other'],['base','base'],True):
                changed=copy.deepcopy(doc);changed['nodes'][-1]['inputs'][port]=value
                with self.subTest(name=name,value=value),self.assertRaises(SchemaxisError):cad.plan(changed)
        doc=example('freecad-loft');doc['nodes'][0]={'id':doc['nodes'][0]['id'],'filter':'box'}
        with self.assertRaises(SchemaxisError) as caught:cad.plan(doc)
        self.assertEqual(caught.exception.fault.code,'TYPE_MISMATCH')

    def test_inspection_collects_list_dependencies(self):
        from schemaxis.adaptors.freecad.inspection import inspect
        doc=example('freecad-loft')
        class Captured(Exception):pass
        def captured(document,*args,**kwargs):
            self.assertEqual([n['id'] for n in document['nodes']],[n['id'] for n in doc['nodes']]);raise Captured()
        with patch('schemaxis.adaptors.freecad.inspection.run',side_effect=captured),self.assertRaises(Captured):
            inspect(doc,doc['output'],'/unused')

    @unittest.skipUnless(os.environ.get('SCHEMAXIS_TEST_FREECAD'),'set SCHEMAXIS_TEST_FREECAD for native CAD list ports')
    def test_native_loft_union_and_inspection(self):
        from schemaxis.adaptors.freecad.inspection import inspect
        runtime=os.environ['SCHEMAXIS_TEST_FREECAD']
        with tempfile.TemporaryDirectory() as temp:
            for name,expected in [('freecad-loft',7000*math.pi),('freecad-multi-fuse',2000)]:
                target=Path(temp)/name
                result=cad.run(example(name),target,executable=runtime)
                self.assertAlmostEqual(result['volumeMM3'],expected,places=6)
                self.assertTrue(cad.verify(target)['verified'])
            doc=example('freecad-loft');result=inspect(doc,doc['output'],Path(temp)/'inspect',executable=runtime)
            self.assertGreater(len(result['edges']),0);self.assertEqual(len(result['faces']),3)

    @unittest.skipUnless(os.environ.get('SCHEMAXIS_TEST_FREECAD_GUI'),'set SCHEMAXIS_TEST_FREECAD_GUI for native list-feature edits')
    def test_live_loft_profile_edit_reuses_objects_and_union_failure_rolls_back(self):
        from schemaxis.adaptors.freecad.live import LiveSession
        with tempfile.TemporaryDirectory() as temp:
            with LiveSession(os.environ['SCHEMAXIS_TEST_FREECAD_GUI'],Path(temp)/'session') as session:
                doc=example('freecad-loft');first=session.request('apply',document=doc)
                self.assertAlmostEqual(session.request('geometry')['volume'],7000*math.pi,places=6)
                doc['nodes'][0]['options']['radius']=15
                second=session.request('apply',document=doc)
                self.assertEqual(first['objects'],second['objects']);self.assertEqual(first['pid'],second['pid'])
                self.assertAlmostEqual(session.request('geometry')['volume'],4750*math.pi,places=6)
                doc=example('freecad-multi-fuse');session.request('apply',document=doc)
                previous=session.request('geometry');status=session.request('status')
                doc['nodes'][2]['options']['origin']=[1000,0,0]
                with self.assertRaises(SchemaxisError):session.request('apply',document=doc)
                self.assertEqual(session.request('geometry'),previous)
                self.assertEqual(session.request('status')['revision'],status['revision'])


class CurvesAndMaterials(unittest.TestCase):
    def test_procedural_declarations_and_bounds(self):
        doc=example('blender-procedural');master,selection,_=blender.plan(doc)
        self.assertIn('tube',selection.order)
        for op,opts in [('grid',{'xSegments':257}),('disk',{'segments':2}),('polylineTube',{'points':[[0,0,0]]}),
                        ('material',{'coat':1.1}),('material',{'transmission':-1}),('material',{'emissionStrength':-1}),
                        ('material',{'emissionColour':[True,0,0]})]:
            changed=copy.deepcopy(doc);node=next(n for n in changed['nodes'] if n['filter']==op)
            node['options'].update(opts)
            with self.subTest(op=op,opts=opts),self.assertRaises(SchemaxisError):blender.plan(changed)

    def test_lathe_topology_and_invalid_profiles(self):
        from schemaxis.adaptors.blender.profiles import lathe_mesh
        points,faces=lathe_mesh([[1,0],[2,3]],4,True)
        self.assertEqual(len(points),8);self.assertEqual(len(faces),6)
        self.assertEqual(points[0],(1,0,0));self.assertEqual(points[4],(2,0,3))
        self.assertEqual(faces[-2],(3,2,1,0));self.assertEqual(faces[-1],(4,5,6,7))
        self.assertEqual(len(lathe_mesh([[1,0],[2,3]],4,False)[1]),4)
        for profile in ([[1,0]],[[0,0],[1,2]],[[1,0],[1,0]],[[1,2],[1,0]],[[True,0],[1,2]]):
            with self.assertRaises(SchemaxisError):lathe_mesh(profile,32,True)

    def test_lathe_profile_is_checked_at_planning(self):
        blender.plan(example('blender-lathe'))
        index=[n['id'] for n in example('blender-lathe')['nodes']].index('vessel')
        for profile in ([[0.8,0],[-1,0.3],[1,0.2]],[[0.8,0],[1,0.3],[1,0.2]],[[0,0],[1,1]]):
            doc=example('blender-lathe');doc['nodes'][index]['options']['profile']=profile
            with self.subTest(profile=profile),self.assertRaises(SchemaxisError) as caught:blender.plan(doc)
            fault=caught.exception.fault
            self.assertEqual(fault.code,'INVALID_PROFILE')
            self.assertEqual(fault.location,'$.nodes[%d].options.profile'%index)
        doc=example('blender-lathe');doc['axes']=[{'name':'r','values':[1,-2]}]
        doc['nodes'][index]['options']['profile']=[[{'$axis':'r'},0],[1,1]]
        with self.assertRaises(SchemaxisError) as caught:blender.plan(doc)
        self.assertEqual(caught.exception.fault.code,'INVALID_PROFILE')

    def test_inline_lathe_fault_does_not_claim_an_authored_node_index(self):
        doc=example('blender-lathe')
        count=len(doc['nodes'])
        doc['nodes'].append({'id':'rim','filter':'bevel','inputs':{'input':{'$create':{
            'id':'inlineVessel','filter':'lathe','inputs':{'material':'paint'},
            'options':{'profile':[[1,1],[2,0]]}}}}})
        doc['scenes'][0]['visible']=['rim']
        with self.assertRaises(SchemaxisError) as caught:blender.plan(doc)
        fault=caught.exception.fault
        self.assertEqual(fault.code,'INVALID_PROFILE')
        self.assertEqual(fault.location,'$.nodes')
        self.assertEqual(fault.observed['node'],'inlineVessel')
        self.assertEqual(len(doc['nodes']),count+1)

    def test_table_curve_coordinates_missing_columns_and_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'data.csv';path.write_text('x,y,z\n0,1,2\n3,4,5\n')
            opts={'file':str(path),'xColumn':'x','yColumn':'y','zColumn':''}
            self.assertEqual(points_from_csv(opts),[[0,1,0],[3,4,0]])
            self.assertEqual(points_from_csv({**opts,'zColumn':'z'}),[[0,1,2],[3,4,5]])
            with self.assertRaises(SchemaxisError):points_from_csv({**opts,'yColumn':'missing'})
            path.write_text('x,y\n0,1\n3,1e10\n')
            with self.assertRaises(SchemaxisError):points_from_csv(opts)
            path.write_text('x,y\n'+'0,1\n'*1025)
            with self.assertRaises(SchemaxisError):points_from_csv(opts)

    @unittest.skipUnless(os.environ.get('SCHEMAXIS_TEST_BLENDER'),'set SCHEMAXIS_TEST_BLENDER for native procedural geometry')
    def test_native_mesh_counts_volume_materials_and_rejected_segments(self):
        runtime=os.environ['SCHEMAXIS_TEST_BLENDER']
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'geometry';blender.run(example('blender-procedural'),target,executable=runtime)
            receipt=json.loads((target/'verification.json').read_text());obs=receipt['states'][0]['observations']
            self.assertEqual(obs['grid']['points'],45);self.assertEqual(obs['grid']['cells'],32)
            self.assertEqual(obs['disk']['points'],32);self.assertEqual(obs['disk']['cells'],1)
            # A capped straight native bevel approximates a cylinder by a regular polygon.
            tube=obs['tube'];sides=12  # bevel_resolution 4 has 12 sides, with separate cap vertices
            expected=sides/2*.25**2*math.sin(2*math.pi/sides)*2
            self.assertAlmostEqual(tube['signedVolume'],expected,places=6)
            self.assertAlmostEqual(obs['paint']['coat'],.5);self.assertAlmostEqual(obs['paint']['emissionStrength'],.2)
            bad=example('blender-procedural');next(n for n in bad['nodes'] if n['id']=='tube')['options']['points']=[[0,0,0],[0,0,0]]
            with self.assertRaises(SchemaxisError):blender.run(bad,Path(temp)/'bad',executable=runtime)

    @unittest.skipUnless(os.environ.get('SCHEMAXIS_TEST_BLENDER'),'set SCHEMAXIS_TEST_BLENDER for native rotational profile')
    def test_native_lathe_volume(self):
        doc=example('blender-lathe');doc['scenes'][0]['prepareOnly']=True
        options=doc['nodes'][1]['options'];profile=options['profile'];n=options['segments']
        expected=n*math.sin(2*math.pi/n)/6*sum((b[1]-a[1])*(a[0]**2+a[0]*b[0]+b[0]**2) for a,b in zip(profile,profile[1:]))
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'lathe';blender.run(doc,target,executable=os.environ['SCHEMAXIS_TEST_BLENDER'])
            observation=json.loads((target/'verification.json').read_text())['states'][0]['observations']['vessel']
            self.assertAlmostEqual(observation['signedVolume'],expected,places=5)
            self.assertEqual(observation['points'],n*len(profile));self.assertEqual(observation['cells'],n*(len(profile)-1)+2)

    @unittest.skipUnless(os.environ.get('SCHEMAXIS_TEST_BLENDER') and os.environ.get('SCHEMAXIS_TEST_OCTAVE'),'set Blender and Octave for native data-curve handoff')
    def test_native_csv_curve_handoff(self):
        from schemaxis.workflow import execute,verify
        doc=json.loads((ROOT/'examples/schemaxis/analysis/octave-to-blender.json').read_text())
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'curve'
            execute(doc,target,locations={'blender':os.environ['SCHEMAXIS_TEST_BLENDER'],'octave':os.environ['SCHEMAXIS_TEST_OCTAVE']})
            self.assertTrue(verify(target)['verified'])
            jobs=json.loads((target/'result.json').read_text())['jobs']
            curve=next(j for j in jobs if j['operation']=='curve')
            record=json.loads((Path(curve['directory'])/'verification.json').read_text())['states'][0]['observations']['curve']
            self.assertGreater(record['points'],128);self.assertGreater(record['signedVolume'],0)

    @unittest.skipUnless(os.environ.get('SCHEMAXIS_TEST_BLENDER'),'set SCHEMAXIS_TEST_BLENDER for live profile edits')
    def test_live_lathe_edit_reuses_handles_and_invalid_profile_rolls_back(self):
        from schemaxis.adaptors.blender.live import LiveSession
        doc=example('blender-lathe')
        with tempfile.TemporaryDirectory() as temp:
            with LiveSession(os.environ['SCHEMAXIS_TEST_BLENDER'],Path(temp)/'session',timeout=120) as session:
                first=session.request('apply',document=doc)
                old=session.request('geometry')
                doc['nodes'][1]['options']['profile']=[[2*r,z] for r,z in doc['nodes'][1]['options']['profile']]
                second=session.request('apply',document=doc)
                self.assertEqual(first['objects'],second['objects']);self.assertEqual(first['pid'],second['pid'])
                current=session.request('geometry');self.assertNotEqual(old,current)
                doc['nodes'][1]['options']['profile']=[[1,1],[2,0]]
                with self.assertRaises(SchemaxisError) as caught:session.request('apply',document=doc)
                # Rejected at planning, before any native mutation, so there is nothing to roll back.
                self.assertEqual(caught.exception.fault.code,'INVALID_PROFILE')
                self.assertNotIn('rolledBack',caught.exception.fault.observed)
                self.assertEqual(session.request('geometry'),current)


class GodotShapesAndLights(unittest.TestCase):
    def test_bounds_and_rotation_have_analytic_answers(self):
        node={'filter':'box','options':{'size':[2,4,6],'scale':[2,1,1],'rotation':[0,0,90],'position':[1,2,3]}}
        self.assertTrue(close(godot.expected_bounds(node,{}),[-1,0,0,3,4,6]))
        self.assertTrue(close(godot.expected_basis(node['options']),[[0,2,0],[-1,0,0],[0,0,1]]))
        prepared=godot.plan(example('godot-lighting'));self.assertEqual(len(prepared['nodes']),7)

    def test_invalid_shape_light_and_transform_values(self):
        for op,options in [('capsule',{'radius':2,'height':1}),('torus',{'innerRadius':2,'outerRadius':1}),
                           ('omniLight',{'range':0}),('spotLight',{'angle':90}),('capsule',{'scale':[1,0,1]}),
                           ('torus',{'rotation':[0,float('inf'),0]})]:
            doc=example('godot-lighting');next(n for n in doc['nodes'] if n['filter']==op).setdefault('options',{}).update(options)
            with self.subTest(op=op,options=options),self.assertRaises(SchemaxisError):godot.plan(doc)

    @unittest.skipUnless(os.environ.get('GODOT_EXECUTABLE'),'set GODOT_EXECUTABLE for native transforms and lights')
    def test_native_reopen_and_tampered_transform(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'scene';doc=example('godot-lighting')
            self.assertTrue(godot.run(doc,target,os.environ['GODOT_EXECUTABLE'])['verified'])
            originals={name:(target/name).read_bytes() for name in ('built.json','reopened.json')}
            for name,raw in originals.items():
                record=json.loads(raw);record['scene']['nodes']['capsule']['basis'][0][0]+=1
                (target/name).write_text(json.dumps(record))
            with self.assertRaises(SchemaxisError):godot.verify(target)
            for name,raw in originals.items():(target/name).write_bytes(raw)
            self.assertTrue(godot.verify(target)['verified'])


if __name__=='__main__':unittest.main()
