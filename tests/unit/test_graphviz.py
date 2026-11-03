# Copyright (C) 2026 David L F Gaden
"""Declared topology, closed geometry inspection and host authoring contracts."""
import copy
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.adaptors.graphviz import adaptor as a
from schemaxis.adaptors.graphviz import inspection as i
from schemaxis.core.faults import SchemaxisError
ROOT=Path(__file__).resolve().parents[2]


class GraphvizContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pending=ROOT/'src/schemaxis/adaptors/graphviz/adaptor.json.pending'
        cls.registration=patch.dict(registry.ADAPTORS,{'graphviz':json.loads(pending.read_text())}) if pending.exists() else patch.dict(registry.ADAPTORS,{})
        cls.registration.start()
    @classmethod
    def tearDownClass(cls):cls.registration.stop()
    def document(self,name='baseline'):return json.loads((ROOT/f'examples/schemaxis/graphviz-{name}.json').read_text())
    def fault(self,action,code):
        with self.assertRaises(SchemaxisError) as caught:action()
        self.assertEqual(caught.exception.fault.code,code,caught.exception.fault.to_dict());return caught.exception.fault
    def test_immutable_defaults_schema_and_declarations(self):
        d=self.document();before=copy.deepcopy(d);p=a.plan(d)
        self.assertEqual(d,before);self.assertEqual(p,a.plan(d));self.assertEqual((p['rankDirection'],p['graphPolicy']),('TB','dag'))
        from schemaxis.core.declarations import validate_specification
        for k,v in a.OPTIONS.items():validate_specification(v,k)
        self.assertEqual(set(a.schema()['properties']),{'version','operation',*a.OPTIONS})
        self.assertEqual(a.schema()['properties']['rankDirection']['default'],'TB')
        self.assertIn('"extract" -> "build";',a.dot(p));self.assertIn('rankdir=TB',a.dot(p))
    def test_literal_topology_policy_and_multiplicity(self):
        p=a.plan(self.document());t=a.topology(p)
        self.assertEqual(t['nodeIds'],['extract','build','check','publish'])
        self.assertEqual(t['edgePairs'],[['extract','build'],['extract','check'],['build','publish'],['check','publish']])
        self.assertTrue(t['acyclic']);self.assertEqual(t['topologicalOrder'],['extract','build','check','publish'])
        self.assertFalse(a.topology(a.plan(self.document('cycle')))['acyclic'])
        self.assertEqual(self.fault(lambda:a.plan(self.document('cycle-invalid')),'GRAPH_CYCLE').location,'$.graphPolicy')
        self.assertEqual(self.fault(lambda:a.plan(self.document('edge-invalid')),'INVALID_GRAPH_EDGE').location,'$.edges[0]')
        for edge in ({'source':'extract','target':'extract'},self.document()['edges'][0]):
            d=self.document();d['edges'].append(edge);self.fault(lambda:a.plan(d),'INVALID_GRAPH_EDGE')
    def test_closed_authored_surface_and_actionable_locations(self):
        for value in ['a"; URL="file:///bad','a\\N','<b>Hi</b>',"can’t",'hi\nthere',"can't"]:
            d=self.document();d['nodes'][0]['label']=value
            self.assertEqual(self.fault(lambda:a.plan(d),'INVALID_GRAPH_LABEL').location,'$.nodes[0].label')
        for value in ['A','1a','a-b']:
            d=self.document();d['nodes'][0]['id']=value;self.fault(lambda:a.plan(d),'INVALID_GRAPH_NODE')
        d=self.document();d['nodes'].append(d['nodes'][0]);self.fault(lambda:a.plan(d),'INVALID_GRAPH_NODE')
        for key in ['dot','url','image','flags','cluster','script']:
            d=self.document();d[key]='untrusted';self.fault(lambda:a.plan(d),'UNKNOWN_ARGUMENT')
        for label in ['0','Task 2','Input/Output (03)','v1.2+3:OK']:
            d=self.document();d['nodes'][0]['label']=label;self.assertEqual(a.plan(d)['nodes'][0]['label'],label)
        d=self.document();d['nodes'][0]['id']='graph';d['edges'][0]['source']='graph';d['edges'][1]['source']='graph'
        self.assertIn('"graph" [label=',a.dot(a.plan(d)))
    def test_plain_fixture_literal_geometry_and_membership(self):
        p=a.plan(self.document());raw=(ROOT/'tests/fixtures/graphviz-baseline.plain').read_bytes();w,h,nodes,edges=i.plain(raw,p)
        self.assertEqual((w,h),(5.25,2.5));self.assertEqual(nodes['extract']['centre'],[2.625,2.25]);self.assertEqual(nodes['publish']['centre'],[2.625,.25]);self.assertEqual(len(edges),4)
        for changed in [raw.replace(b'graph 1 ',b'graph 0 '),raw.replace(b'5.25',b'NaN'),raw.replace(b'Extract 01',b'Extract 02'),raw.replace(b'edge extract build',b'edge check build'),raw.replace(b'node build 1.25 1.25',b'node build 2.625 2.25'),raw+b'node extra 0 0\n']:
            self.fault(lambda:i.plain(changed,p),'VERIFICATION_FAILED')
    def test_svg_fixture_closed_grammar_and_hidden_numeric_text(self):
        p=a.plan(self.document());w,h,nodes,edges=i.plain((ROOT/'tests/fixtures/graphviz-baseline.plain').read_bytes(),p);raw=(ROOT/'tests/fixtures/graphviz-baseline.svg').read_bytes()
        i.svg(raw,p,w,h,nodes,edges)
        mutations=[lambda b:b.replace(b'class="node"',b'class="node" opacity="0"',1),lambda b:b.replace(b'>Extract 01</text>',b'></text>'),lambda b:b.replace(b'font-size="10.00"',b'font-size="0.00"',1),lambda b:b.replace(b'fill="none" stroke="black"',b'fill="white" stroke="black"',1),lambda b:b.replace(b'</svg>',b'<rect width="999" height="999" fill="white"/></svg>'),lambda b:b.replace(b'</svg>',b'<script>bad()</script></svg>'),lambda b:b.replace(b'<text ',b'<a href="file:///bad"><text ',1),lambda b:b.replace(b'x="189"',b'x="0"',1),lambda b:b.replace(b'M164.27',b'M164.99',1),lambda b:b.replace(b'white',b'transparent',1),lambda b:b.replace(b'scale(1 1)',b'scale(0 0)',1)]
        for mutation in mutations:
            changed=mutation(raw);self.assertNotEqual(changed,raw);self.fault(lambda:i.svg(changed,p,w,h,nodes,edges),'VERIFICATION_FAILED')
    def test_cubic_extrema_are_not_control_bounds(self):
        pts=[[0,0],[2,0],[2,1],[0,1]];observed=i.curve_points(pts)
        self.assertAlmostEqual(max(p[0] for p in observed),1.5)
        self.assertTrue(any(p==[0.,0.] for p in observed))
    def test_file_caps_regular_nofollow_and_no_native_import_for_planning(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);p=d/'source';p.write_bytes(b'OK');self.assertEqual(a.bounded(p),b'OK')
            link=d/'link';link.symlink_to(p);self.fault(lambda:a.bounded(link),'VERIFICATION_FAILED')
            if hasattr(os,'mkfifo'):
                fifo=d/'fifo';os.mkfifo(fifo);self.fault(lambda:a.bounded(fifo),'VERIFICATION_FAILED')
            self.fault(lambda:a.bounded(p,limit=1),'VERIFICATION_FAILED')
        with patch.object(a,'execute',side_effect=AssertionError('native called')):a.plan(self.document())
    def test_studio_starters_and_guidance(self):
        from schemaxis.studio_library import load_library,instantiate_item,plan_item
        from schemaxis.studio_guidance import audit
        library=load_library('graphviz')
        for item in library['templates']:plan_item(instantiate_item(library,item,provider='graphviz'))
        self.assertTrue(audit('graphviz')['complete'])
    def test_actual_capability_search(self):
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        c=CapabilityCatalogue(providers=['graphviz']);result=check_cases(c,'graphviz');self.assertTrue(result['complete'],result)
        from schemaxis.agent_transport import dispatch
        from schemaxis.execution_service import ExecutionService
        with tempfile.TemporaryDirectory() as temp,ExecutionService(temp) as service:
            for case in c._metadata['graphviz']['searchCases']:
                request={'query':case['query'],'scope':case['scope'],'limit':100,'max_bytes':65536}
                agent=dispatch(service,{'id':case['id'],'method':'capabilities.search','params':request})
                cli=subprocess.run([sys.executable,'-m','schemaxis','capabilities','search',case['query'],'--scope',case['scope'],'--limit','100','--max-bytes','65536'],cwd=ROOT,capture_output=True,text=True,timeout=30)
                self.assertEqual(cli.returncode,0,cli.stderr);self.assertEqual(json.loads(cli.stdout)['items'],agent['items'])
                observed={item['id'] for item in agent['items']};self.assertLessEqual(set(case['expected']['capabilities']),observed)
                self.assertFalse(set(case.get('excluded',{}).get('capabilities',[])) & observed)

if __name__=='__main__':unittest.main()
