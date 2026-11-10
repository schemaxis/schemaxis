"""Physics, closed declared inputs and source-bound evidence for GetDP."""
import copy
import json
from pathlib import Path
import unittest
from schemaxis.adaptors.getdp import adaptor,physics
from schemaxis.core.faults import SchemaxisError
ROOT=Path(__file__).resolve().parents[2]


class GetDPTests(unittest.TestCase):
    def document(self,name='baseline'):return json.loads((ROOT/f'examples/schemaxis/getdp-{name}.json').read_text())
    def fault(self,doc,code):
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(doc)
        self.assertEqual(code,caught.exception.fault.code)
    def test_exact_baseline_and_immutable_plan(self):
        d=self.document();original=copy.deepcopy(d);p=adaptor._native_plan(d);t,q,ql,qr=physics.exact(p)
        self.assertEqual(d,original);self.assertEqual(p,adaptor._native_plan(d));self.assertAlmostEqual(t[5],350);self.assertAlmostEqual(qr,10000)
    def test_composite_resistance_and_source(self):
        p=adaptor._native_plan(self.document('composite'));t,q,_,qr=physics.exact(p);self.assertAlmostEqual(qr,10000/11);self.assertAlmostEqual(t[10],400-100/11)
        p=adaptor._native_plan(self.document('source'));t,q,ql,qr=physics.exact(p);self.assertAlmostEqual(max(t),312.5);self.assertAlmostEqual(ql,-50);self.assertAlmostEqual(qr,50)
        summary=adaptor.summary(p,t,q);self.assertAlmostEqual(summary['balanceResidual'],0);self.assertAlmostEqual(summary['generatedTotal'],50)
    def test_convection_and_current(self):
        p=adaptor._native_plan(self.document('convection'));t,q,_,_=physics.exact(p);self.assertAlmostEqual(t[0],320);self.assertAlmostEqual(t[-1],310)
        p=adaptor._native_plan(self.document('current'));t,q,_,_=physics.exact(p);self.assertAlmostEqual(t[5],5);self.assertAlmostEqual(q[-1],10000)
    def test_boundary_and_semantic_faults(self):
        d=self.document();d['left']=d['right']={'kind':'flux','value':0};self.fault(d,'UNANCHORED_FIELD')
        d=self.document();d['left']['ambient']=300;self.fault(d,'INVALID_BOUNDARY')
        d=self.document('current');d['right']={'kind':'convection','coefficient':1,'ambient':300};self.fault(d,'UNSUPPORTED_BOUNDARY')
        d=self.document();d['layers']*=2;self.fault(d,'INVALID_LAYERS')
        d=self.document();d['arbitraryPro']='Include "attack.pro";';self.fault(d,'UNKNOWN_ARGUMENT')
        d=self.document();d['layers'][0]['conductivity']=True;self.fault(d,'INVALID_ARGUMENT')
    def test_continuum_kelvin_extremum_between_nodes(self):
        d=self.document('source');d['layers'][0].update(cells=3,source=-100);d['left']['value']=d['right']['value']=12
        # Minimum is -0.5 K at x=.5; all four mesh nodes remain positive.
        self.fault(d,'INVALID_TEMPERATURE')
    def test_literal_requirement_margin(self):
        d=self.document();d['limits']={'maximumField':399.99999999};p=adaptor._native_plan(d);t,q,_,_=physics.exact(p)
        s=adaptor.summary(p,t,q);self.assertFalse(s['limits']['accepted']);self.assertLess(s['limits']['margins']['maximumField'],0)
    def test_resource_and_conditioning_bounds(self):
        d=self.document('composite');d['layers'][0]['conductivity']=1e8;d['layers'][1]['conductivity']=1e-5;self.fault(d,'ILL_CONDITIONED_FIELD')
        d=self.document();d['layers']=[dict(d['layers'][0],name=str(i),cells=128) for i in range(5)];self.fault(d,'RESOURCE_LIMIT')
    def test_boundaries_source_and_interface_conservation(self):
        d=self.document('composite');d['layers'][0]['source']=1000;d['layers'][1]['source']=-100;d['left']={'kind':'flux','value':-1000};p=adaptor._native_plan(d);t,q,_,_=physics.exact(p)
        s=adaptor.summary(p,t,q);self.assertAlmostEqual(s['rightOutwardFlux'],1090);self.assertAlmostEqual(s['balanceResidual'],0)
        q[9]+=1
        with self.assertRaises(SchemaxisError):physics.inspect(p,t,q)
    def test_runtime_identity(self):
        self.assertEqual(adaptor.runtime('3.5.0\n')['version'],'3.5.0')
        with self.assertRaises(SchemaxisError):adaptor.runtime('4.0.0')

    def test_unhashable_operation_fault(self):
        for value in ([],{},1,None):
            d=self.document();d['operation']=value;self.fault(d,'UNKNOWN_FILTER')

    def test_missing_raw_sections_are_structured(self):
        import tempfile
        with tempfile.TemporaryDirectory() as name:
            directory=Path(name);(directory/'model.pre').write_text('$EndDofData\n');(directory/'model.res').write_text('$EndSolution\n')
            with self.assertRaises(SchemaxisError) as caught:physics.read_solution(directory,adaptor._native_plan(self.document()))
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
