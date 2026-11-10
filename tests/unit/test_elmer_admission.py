"""Host-only thermal semantics, native mappings and editable Elmer authoring."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.adaptors.elmer import adaptor,formats,physics
from schemaxis.core.faults import SchemaxisError
from schemaxis.studio_library import load_library,instantiate_item
from schemaxis.studio_catalogue import catalogue
ROOT=Path(__file__).resolve().parents[2]


class ElmerTests(unittest.TestCase):
    def document(self,name='baseline'):return json.loads((ROOT/f'examples/schemaxis/elmer-{name}.json').read_text())
    def fault(self,d,code,location=None):
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(d)
        self.assertEqual(caught.exception.fault.code,code)
        if location:self.assertEqual(caught.exception.fault.location,location)
        return caught.exception.fault
    def test_exact_baseline_immutable_and_native_free(self):
        d=self.document();before=copy.deepcopy(d)
        with patch('subprocess.Popen',side_effect=AssertionError('host planning must not launch Elmer')):
            p=adaptor._native_plan(d);t,q,ql,qr=physics.exact(p)
            self.assertEqual(p,adaptor._native_plan(d))
        self.assertEqual(before,d);self.assertAlmostEqual(t[4],350);self.assertAlmostEqual(qr,5000);self.assertAlmostEqual(ql,5000)
    def test_series_resistance_and_generation(self):
        p=adaptor._native_plan(self.document('composite'));t,q,ql,qr=physics.exact(p)
        self.assertAlmostEqual(qr,10000/11);self.assertAlmostEqual(t[10],400-100/11)
        p=adaptor._native_plan(self.document('source'));t,q,ql,qr=physics.exact(p)
        s=adaptor.summary(p,t);self.assertAlmostEqual(max(t),312.5);self.assertAlmostEqual(ql,-50);self.assertAlmostEqual(qr,50)
        self.assertAlmostEqual(s['generatedTotal'],50);self.assertAlmostEqual(s['balanceResidual'],0)
    def test_boundary_signs_and_two_films(self):
        p=adaptor._native_plan(self.document('convection'));t,*_=physics.exact(p);self.assertAlmostEqual(t[0],320);self.assertAlmostEqual(t[-1],310)
        p=adaptor._native_plan(self.document('two-convection'));t,q,*_=physics.exact(p);self.assertAlmostEqual(t[0],375);self.assertAlmostEqual(t[-1],325);self.assertAlmostEqual(q[0],2500)
        d=self.document();d['left']={'kind':'convection','coefficient':100,'ambient':400};d['right']={'kind':'flux','value':1000}
        p=adaptor._native_plan(d);t,q,_,_=physics.exact(p);self.assertAlmostEqual(t[0],390);self.assertAlmostEqual(t[-1],370)
    def test_semantic_faults_and_locations(self):
        d=self.document();d['left']=d['right']={'kind':'flux','value':0};self.assertIsNotNone(self.fault(d,'UNANCHORED_FIELD').recovery)
        d=self.document();d['left']['ambient']=300;self.fault(d,'INVALID_BOUNDARY','$.left')
        d=self.document();d['layers']*=2;self.fault(d,'INVALID_LAYERS','$.layers[1].name')
        d=self.document();d['layers'][0]['conductivity_W_mK']=True;self.fault(d,'INVALID_ARGUMENT','$.layers[0].conductivity_W_mK')
        d=self.document();del d['right'];self.fault(d,'MISSING_ARGUMENT','$.right')
        d=self.document();d['python']='exec(1)';self.fault(d,'UNKNOWN_ARGUMENT')
        d=self.document();d['limits']={'minimumField':400,'maximumField':300};self.fault(d,'INVALID_LIMITS','$.limits')
    def test_nonfinite_values_and_operation_types(self):
        for v in (float('nan'),float('inf'),-float('inf')):
            d=self.document();d['layers'][0]['heatGeneration_W_m3']=v;self.fault(d,'INVALID_ARGUMENT')
        for v in ([],{},None,True):
            d=self.document();d['operation']=v;self.fault(d,'UNKNOWN_FILTER')
    def test_between_node_kelvin_minimum_is_checked(self):
        d=self.document('source');d['layers'][0].update(cells=3,heatGeneration_W_m3=-100);d['left']['value']=d['right']['value']=12
        self.fault(d,'INVALID_TEMPERATURE')
    def test_literal_bounds_do_not_borrow_physics_tolerance(self):
        d=self.document();d['limits']={'maximumField':399.99999999};p=adaptor._native_plan(d);nodes,*_=physics.exact(p)
        s=adaptor.summary(p,nodes);self.assertFalse(s['limits']['accepted']);self.assertLess(s['limits']['margins']['maximumField'],0)
    def test_resource_stiffness_and_export_precision_guards(self):
        d=self.document('composite');d['layers'][0]['conductivity_W_mK']=1e8;d['layers'][1]['conductivity_W_mK']=1e-5;self.fault(d,'ILL_CONDITIONED_FIELD')
        d=self.document();d['layers']=[dict(d['layers'][0],name=str(i),cells=128) for i in range(5)];self.fault(d,'RESOURCE_LIMIT')
        d=self.document();d['layers']=[{'name':'large','thickness_m':1000,'conductivity_W_mK':1000,'cells':2},{'name':'thin','thickness_m':1e-5,'conductivity_W_mK':1e-5,'cells':2}]
        self.fault(d,'EXPORT_PRECISION_LOSS','$.layers')
    def test_native_mapping_outward_sign_density_and_no_solve_reopen(self):
        d=self.document('convection');p=adaptor._native_plan(d);s=formats.sources(p)
        self.assertIn('Heat Flux = 1000',s['model.sif']);self.assertIn('Density = 1',s['model.sif'])
        self.assertIn('Optimize Bandwidth = False',s['model.sif']);self.assertIn('Exec Solver = Never',s['reopen.sif'])
        self.assertIn('Restart File = "thermal.result"',s['reopen.sif']);self.assertNotIn('Output File = "thermal.result"',s['reopen.sif'])
        self.assertEqual(len(s),6)
    def test_restart_permutation_swaps_are_rejected(self):
        d=self.document();p=adaptor._native_plan(d);n=len(physics.mesh(p)[0]);t=physics.exact(p)[0]
        prefix=f' ASCII 3\n Total DOFs: 1\n Number Of Nodes: {n}\nTime: 1 1 1.0\ntemperature\nPerm: {n} {n}\n'
        pairs=[f'{i} {i}' for i in range(1,n+1)]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'thermal.result';path.write_text(prefix+'\n'.join(pairs)+'\n'+'\n'.join(str(v) for v in t)+'\n');self.assertEqual(formats.read_result(path,p),t)
            pairs[0]='1 2';pairs[1]='2 1';path.write_text(prefix+'\n'.join(pairs)+'\n'+'\n'.join(str(v) for v in t)+'\n')
            with self.assertRaises(SchemaxisError) as caught:formats.read_result(path,p)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
    def test_native_thermal_discrepancy_cannot_pass(self):
        p=adaptor._native_plan(self.document('source'));nodes,flux,*_=physics.exact(p);nodes[5]+=1
        with self.assertRaises(SchemaxisError):adaptor.summary(p,nodes)
    def test_runtime_identity_is_honest_about_patch_precision(self):
        d=adaptor.runtime('MAIN: Version: 26.2-unknown (Rev: unknown)')
        self.assertEqual(d['version'],'26.2');self.assertIn('patch',d['versionPrecision'])
        with self.assertRaises(SchemaxisError) as caught:adaptor.runtime('MAIN: Version: 26.2-devel')
        self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_RUNTIME')
    def test_runtime_unavailable_is_distinct_from_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaises(SchemaxisError) as caught:adaptor.run(self.document(),root/'missing',executable=str(root/'absent'))
            self.assertEqual(caught.exception.fault.code,'INTERPRETER_NOT_FOUND')
            script=root/'broken';script.write_text('#!/bin/sh\nexit 127\n');script.chmod(0o755)
            with self.assertRaises(SchemaxisError) as caught:adaptor.run(self.document(),root/'unavailable',executable=str(script))
            self.assertEqual(caught.exception.fault.code,'RUNTIME_UNAVAILABLE');self.assertIsNotNone(caught.exception.fault.recovery)
            self.assertEqual(json.loads((root/'unavailable/result.json').read_text())['status'],'failed')
    def test_unsupported_runtime_and_failed_solver_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);script=root/'fixture'
            script.write_text('#!/bin/sh\necho "MAIN: Version: 27.1-unknown"\n');script.chmod(0o755)
            with self.assertRaises(SchemaxisError) as caught:adaptor.run(self.document(),root/'unsupported',executable=str(script))
            self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_RUNTIME')
            script.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then echo "MAIN: Version: 26.2-unknown"; else echo "native solver rejected input" >&2; exit 17; fi\n')
            with self.assertRaises(SchemaxisError) as caught:adaptor.run(self.document(),root/'failed',executable=str(script))
            self.assertEqual(caught.exception.fault.code,'NATIVE_EXECUTION_FAILED')
            self.assertIn('rejected input',(root/'failed/solve.stderr').read_text())

    def test_studio_complete_typed_starters_and_snippets(self):
        with patch('subprocess.Popen',side_effect=AssertionError('host catalogue must not launch Elmer')):
            c=catalogue('elmer');self.assertEqual({i['operation'] for i in c['items'] if 'operation' in i},{'steadyHeat'})
            library=load_library('elmer');before=copy.deepcopy(library)
            for collection in ('templates','snippets'):
                for item in library[collection]:self.assertIsNotNone(adaptor.plan(instantiate_item(library,item,provider='elmer')))
            self.assertEqual(library,before)
    def test_discovery_cases_on_actual_cli_and_agent_protocol(self):
        import subprocess
        import sys
        from schemaxis.agent_transport import dispatch
        from schemaxis.execution_service import ExecutionService
        cases=json.loads((ROOT/'src/schemaxis/adaptors/elmer/search-cases.json').read_text())
        with tempfile.TemporaryDirectory() as tmp,ExecutionService(tmp) as service:
            for case in cases:
                request={'query':case['query'],'scope':case['scope'],'limit':100,'max_bytes':65536}
                result=dispatch(service,{'id':case['id'],'method':'capabilities.search','params':request})
                cli=subprocess.run([sys.executable,'-m','schemaxis','capabilities','search',case['query'],'--scope',case['scope'],'--limit','100','--max-bytes','65536'],cwd=ROOT,capture_output=True,text=True,timeout=30,check=True)
                self.assertEqual(json.loads(cli.stdout)['items'],result['items'])
                observed={item['id'] for item in result['items']}
                self.assertTrue(set(case['expected']['capabilities'])<=observed)
                self.assertFalse(set(case['excluded'].get('capabilities',[]))&observed)

    def test_field_guidance_covers_meaningful_units_and_defaults(self):
        d=json.loads((ROOT/'src/schemaxis/adaptors/elmer/guidance.json').read_text());fields=d['routes'][adaptor.VERSION]['fields']
        self.assertTrue(all(v['status']=='reviewed' for v in fields.values()))
        self.assertIn('W/(m K)',fields['/properties/layers/items/properties/conductivity_W_mK']['explanation'])
        self.assertIn('Omission',fields['/properties/limits']['explanation'])

if __name__=='__main__':unittest.main()
