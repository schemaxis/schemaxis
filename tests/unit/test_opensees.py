"""Host contracts and independent literal mechanics for planar structural networks."""
import copy
import json
from pathlib import Path
import sys
import unittest
from schemaxis.adaptors.opensees import adaptor as a,mechanics
from schemaxis.core.faults import SchemaxisError
ROOT=Path(__file__).resolve().parents[2]
def example(name='triangle'):return json.loads((ROOT/f'examples/schemaxis/opensees-{name}.json').read_text())


class OpenSeesTest(unittest.TestCase):
    def test_plan_immutable_deterministic_native_free(self):
        doc=example(); saved=copy.deepcopy(doc);p=a.plan(doc)
        self.assertEqual(p,a.plan(doc));self.assertEqual(doc,saved);self.assertNotIn('openseespy.opensees',sys.modules)
        self.assertEqual(p['nodes'][2]['fixed'],[False,False]);self.assertEqual(a.query(doc),(['trussStatic'],{}))
    def test_literal_triangle_and_area_scaling(self):
        p=a.plan(example());v=mechanics.solve(p);w=mechanics.solve(a.plan(example('stiffness')))
        self.assertAlmostEqual(v['nodes'][2]['displacement_m'][0],2.5e-6,places=14)
        self.assertAlmostEqual(v['nodes'][2]['displacement_m'][1],-9.571067811865475e-6,places=14)
        self.assertAlmostEqual(v['members'][1]['force_N'],-707.1067811865476,places=9)
        self.assertAlmostEqual(v['nodes'][1]['reaction_N'][1],500,places=9)
        self.assertAlmostEqual(v['nodes'][2]['displacement_m'][1],2*w['nodes'][2]['displacement_m'][1],places=14)
        self.assertAlmostEqual(v['members'][1]['force_N'],w['members'][1]['force_N'],places=10)
    def test_negative_semantics(self):
        for name,code in [('invalid','INVALID_TRUSS'),('unstable','UNSTABLE_TRUSS')]:
            with self.subTest(name=name),self.assertRaises(SchemaxisError) as caught:a.plan(example(name))
            self.assertEqual(caught.exception.fault.code,code)
        for mutate,code in [(lambda d:d['nodes'].append({'id':'orphan','x_m':3,'y_m':0,'fixed':[True,True]}),'INVALID_TRUSS'),(lambda d:d['members'][0].update(b='a'),'INVALID_TRUSS'),(lambda d:d['loads'].append(copy.deepcopy(d['loads'][0])),'INVALID_TRUSS'),(lambda d:d['requirements'][0].update(target='ab'),'INVALID_REQUIREMENT')]:
            doc=example();mutate(doc)
            with self.assertRaises(SchemaxisError) as caught:a.plan(doc)
            self.assertEqual(caught.exception.fault.code,code)
    def test_redundancy_signed_loads_and_unmet(self):
        for name in ('redundant','reverse'):
            p=a.plan(example(name));result=mechanics.solve(p);self.assertTrue(a.assessment(p,result)['accepted'])
        p=a.plan(example('unmet'));self.assertFalse(a.assessment(p,mechanics.solve(p))['accepted'])
    def test_independent_result_mutations(self):
        p=a.plan(example());result=mechanics.solve(p)
        for group,key,value in [('nodes','reaction_N',[0,0]),('members','force_N',0),('members','strain',float('nan'))]:
            mutated=copy.deepcopy(result);mutated[group][0][key]=value
            with self.assertRaises(SchemaxisError) as caught:mechanics.check(p,mutated)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
    def test_schema_valid_cases(self):
        import jsonschema
        for name in ('triangle','stiffness','reverse','redundant','unmet'):
            doc=example(name);jsonschema.Draft202012Validator(a.schema()).validate(doc);a.plan(doc)
    def test_execution_options(self):
        self.assertEqual(a.resources(example(),{},'$'),{'threads':1})
        with self.assertRaises(SchemaxisError):a.resources(example(),{'threads':2},'$')
