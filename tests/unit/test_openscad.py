"""Host CAD semantics and independent geometry adversaries, without native imports."""
import copy
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.adaptors import registry
from schemaxis.adaptors.openscad import adaptor as a, geometry as g
from schemaxis.core.faults import SchemaxisError
ROOT=Path(__file__).resolve().parents[2]


def binary(triangles):
    data=bytearray(b'independent test solid'.ljust(80,b'\0')+struct.pack('<I',len(triangles)))
    for triangle in triangles:
        normal=g.cross(g.sub(triangle[1],triangle[0]),g.sub(triangle[2],triangle[0]));length=math.sqrt(g.dot(normal,normal));normal=tuple(x/length for x in normal) if length else (0,0,0)
        data.extend(struct.pack('<12fH',*normal,*(x for v in triangle for x in v),0))
    return bytes(data)


def box():
    vertices=[(0,0,0),(2,0,0),(2,3,0),(0,3,0),(0,0,4),(2,0,4),(2,3,4),(0,3,4)]
    quads=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    return [[vertices[q[i]] for i in indices] for q in quads for indices in [(0,1,2),(0,2,3)]]


class OpenSCADContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pending=ROOT/'src/schemaxis/adaptors/openscad/adaptor.json.pending'
        cls.registration=patch.dict(registry.ADAPTORS,{'openscad':json.loads(pending.read_text())}) if pending.exists() else patch.dict(registry.ADAPTORS,{})
        cls.registration.start()
    @classmethod
    def tearDownClass(cls):cls.registration.stop()
    def document(self,name='plate'):return json.loads((ROOT/f'examples/schemaxis/openscad-{name}.json').read_text())
    def fault(self,action,code):
        with self.assertRaises(SchemaxisError) as caught:action()
        self.assertEqual(caught.exception.fault.code,code,caught.exception.fault.to_dict());return caught.exception.fault
    def test_defaults_immutable_and_declarations(self):
        from schemaxis.core.declarations import validate_specification
        for name in a.OPTIONS:
            for key,value in a.OPTIONS[name].items():validate_specification(value,key)
        d=self.document();before=copy.deepcopy(d)
        with patch.object(a,'execute',side_effect=AssertionError('native called')):p=a.plan(d)
        self.assertEqual(d,before);self.assertEqual(p,a.plan(d));self.assertEqual(p['segments'],64);self.assertEqual(p['translation'],[0,0,0]);self.assertEqual(g.expected(p)['euler'],-2)
        self.assertNotIn('spacer',p);self.assertEqual(set(a.DECLARATIONS),{'plate','spacer'})
        self.assertIn('cube([40,30,3]);',a.scad(p));self.assertIn('cylinder(h=5,d=6,$fn=64)',a.scad(p))
    def test_precise_clearance_faults(self):
        self.assertEqual(self.fault(lambda:a.plan(self.document('clearance-invalid')),'INVALID_CAD_CLEARANCE').location,'$.plate.holes[0]')
        d=self.document();d['plate']['holes'].append(d['plate']['holes'][0]);self.assertEqual(self.fault(lambda:a.plan(d),'INVALID_CAD_CLEARANCE').location,'$.plate.holes[2]')
        d=self.document('spacer');d['spacer']['boreDiameter']=d['spacer']['outerDiameter'];self.assertEqual(self.fault(lambda:a.plan(d),'INVALID_CAD_CLEARANCE').location,'$.spacer.boreDiameter')
        d=self.document();d['segments']=17;self.assertEqual(self.fault(lambda:a.plan(d),'INVALID_CAD_RESOLUTION').location,'$.segments')
    def test_closed_inputs_and_conditioning(self):
        for key in ['scad','script','flags','source','module','spacer']:
            d=self.document();d[key]='bad';self.fault(lambda:a.plan(d),'UNKNOWN_ARGUMENT')
        for key,value in [('units','cm'),('segments',True),('segments',512),('translation',[101,0,0]),('translation',[float('nan'),0,0])]:
            d=self.document();d[key]=value;self.fault(lambda:a.plan(d),'INVALID_ARGUMENT')
        d=self.document();d['plate']['width']=.1;self.fault(lambda:a.plan(d),'INVALID_ARGUMENT')
        d=self.document();d['plate']['holes'][0]['centre']='[0,0];bad()';self.fault(lambda:a.plan(d),'INVALID_ARGUMENT')
    def test_nested_booleans_refused_before_native_launch(self):
        cases=[('plate',('plate','width')),('plate',('plate','height')),
               ('plate',('plate','holes',0,'diameter')),
               ('plate',('plate','holes',0,'centre',0)),
               ('plate',('translation',0)),('spacer',('spacer','boreDiameter'))]
        with patch.object(a,'execute',side_effect=AssertionError('native launched')):
            for name,path in cases:
                d=self.document(name);d['translation']=[0,0,0];target=d
                for key in path[:-1]:target=target[key]
                target[path[-1]]=True
                fault=self.fault(lambda:a.plan(d),'INVALID_ARGUMENT')
                self.assertIn(str(path[-1]),fault.location)
    def test_reopen_reordering_keeps_exact_oriented_surface(self):
        p=a.plan({'version':a.VERSION,'operation':'plate','units':'mm',
                  'translation':[.123,-.234,.345],
                  'plate':{'width':2.3,'depth':3.7,'height':4.1}})
        faces=[[(v[0]*2.3/2+.123,v[1]*3.7/3-.234,v[2]*4.1/4+.345) for v in tri] for tri in box()]
        order=[1,9,8,5,10,2,3,7,4,0,11,6];raw=binary(faces)
        reordered=binary([faces[i] for i in order])
        # Python 3.12 improved built-in sum. Exercise ordinary accumulation used
        # by supported older hosts so this regression fails with exact equality.
        def ordinary_sum(values,start=0):
            for value in values:start+=value
            return start
        with tempfile.TemporaryDirectory() as temp,patch.object(g,'sum',ordinary_sum,create=True):
            d=Path(temp);(d/'part.stl').write_bytes(raw);(d/'reopened.stl').write_bytes(reordered)
            for stage in ('construct','reopen'):
                (d/(stage+'.stdout')).write_bytes(b'');(d/(stage+'.stderr')).write_bytes(b'')
            source=g.inspect(raw,p);other=g.inspect(reordered,p)
            self.assertNotEqual(source['volume'],other['volume'])
            self.assertTrue(math.isclose(source['volume'],other['volume'],rel_tol=1e-12,abs_tol=1e-12))
            self.assertEqual(a.inspect(d,p)['volume'],source['volume'])
            rotated=binary([faces[i][1:]+faces[i][:1] for i in order]);(d/'reopened.stl').write_bytes(rotated)
            self.assertEqual(g.canonical_triangles(raw),g.canonical_triangles(rotated));a.inspect(d,p)
            # A different top-face diagonal is the same analytic solid but not
            # the qualified facet-preserving native reopen representation.
            altered=copy.deepcopy(faces);first,second=faces[2],faces[3]
            altered[2]=[first[0],first[1],second[2]]
            altered[3]=[first[1],first[2],second[2]]
            data=binary(altered);g.inspect(data,p);(d/'reopened.stl').write_bytes(data)
            self.assertIn('oriented triangle surface',self.fault(lambda:a.inspect(d,p),'VERIFICATION_FAILED').message)
    def test_runtime_banner_is_intentionally_strict(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);(d/'version.stdout').write_bytes(b'')
            for text in ['OpenSCAD version 2021.01', 'OpenSCAD version 2021.01\n']:
                (d/'version.stderr').write_text(text);self.assertEqual(a.runtime_identity(d),'OpenSCAD 2021.01')
            for text in ['OpenSCAD version 2021.01 (distribution build)\n','Fontconfig warning\nOpenSCAD version 2021.01\n','OpenSCAD version 2026.01\n']:
                (d/'version.stderr').write_text(text);self.fault(lambda:a.runtime_identity(d),'UNSUPPORTED_NATIVE_VERSION')
    def test_literal_analytic_oracles(self):
        p=a.plan(self.document());e=g.expected(p)
        self.assertEqual(e['bounds'],[[0,0,0],[40,30,3]])
        self.assertAlmostEqual(e['volume'],3600-39*32*math.sin(math.pi/32),10)
        self.assertAlmostEqual(e['idealVolume'],3600-39*math.pi,10)
        self.assertGreater(e['volume'],e['idealVolume'])
        s=g.expected(a.plan(self.document('spacer')));self.assertAlmostEqual(s['idealVolume'],840*math.pi,10);self.assertLess(s['volume'],s['idealVolume']);self.assertEqual(s['euler'],0)
    def test_independent_box_topology_shape_and_normals(self):
        p=a.plan({'version':a.VERSION,'operation':'plate','units':'mm','plate':{'width':2,'depth':3,'height':4}});tri=box();raw=binary(tri);result=g.inspect(raw,p)
        self.assertEqual((result['volume'],result['vertices'],result['eulerCharacteristic']),(24,8,2))
        hostile=[raw[:-1],raw+b'x',binary(tri[:-1]),binary(tri+[tri[0]]),binary([[tuple(v[k]+(.1 if k==0 else 0) for k in range(3)) for v in f] for f in tri]),binary([list(reversed(f)) for f in tri]),binary([[tuple(v[k]*(1.5 if k==0 else 2/3 if k==1 else 1) for k in range(3)) for v in f] for f in tri])]
        damaged=bytearray(raw);struct.pack_into('<f',damaged,84+8,1);hostile.append(damaged)
        for data in hostile:self.fault(lambda:g.inspect(data,p),'VERIFICATION_FAILED')
    def test_regular_bounded_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);p=d/'solid';p.write_bytes(b'ok');link=d/'link';link.symlink_to(p)
            self.assertEqual(a.bounded(p),b'ok');self.fault(lambda:a.bounded(link),'VERIFICATION_FAILED');self.fault(lambda:a.bounded(p,1),'VERIFICATION_FAILED')
            if hasattr(os,'mkfifo'):
                os.mkfifo(d/'fifo');self.fault(lambda:a.bounded(d/'fifo'),'VERIFICATION_FAILED')
    def test_guidance_and_studio_templates(self):
        from schemaxis.studio_guidance import audit
        from schemaxis.studio_library import load_library,instantiate_item,plan_item
        report=audit('openscad')
        if (ROOT/'docs/openscad.md.pending').exists():
            self.assertEqual(report['counts']['pending'],0);self.assertEqual(report['stale'],[])
            self.assertEqual([x['citation'] for x in report['linkIssues']],['docs/openscad.md'])
        else:self.assertTrue(report['complete'],report)
        library=load_library('openscad')
        for item in library['templates']:plan_item(instantiate_item(library,item,provider='openscad'))
        from schemaxis.studio_catalogue import catalogue
        cat=catalogue('openscad');self.assertEqual({i['operation'] for i in cat['items'] if 'operation' in i},{'plate','spacer'})
    def test_search_cases(self):
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        catalogue=CapabilityCatalogue(providers=['openscad']);report=check_cases(catalogue,'openscad');self.assertTrue(report['complete'],report)
        if (ROOT/'src/schemaxis/adaptors/openscad/adaptor.json.pending').exists():return
        from schemaxis.agent_transport import dispatch
        from schemaxis.execution_service import ExecutionService
        with tempfile.TemporaryDirectory() as temp,ExecutionService(temp) as service:
            for case in catalogue._metadata['openscad']['searchCases']:
                request={'query':case['query'],'scope':case['scope'],'limit':100,'max_bytes':65536}
                agent=dispatch(service,{'id':case['id'],'method':'capabilities.search','params':request})
                cli=subprocess.run([sys.executable,'-m','schemaxis','capabilities','search',case['query'],'--scope',case['scope'],'--limit','100','--max-bytes','65536'],cwd=ROOT,capture_output=True,text=True,timeout=30)
                self.assertEqual(cli.returncode,0,cli.stderr);self.assertEqual(json.loads(cli.stdout)['items'],agent['items'])
                observed={i['id'] for i in agent['items']};self.assertLessEqual(set(case['expected']['capabilities']),observed)
                self.assertFalse(set(case.get('excluded',{}).get('capabilities',[])) & observed)

if __name__=='__main__':unittest.main()
