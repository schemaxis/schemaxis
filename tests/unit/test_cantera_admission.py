"""Host contracts and independent thermodynamic/equilibrium falsification tests."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptor_conformance import host
from schemaxis.adaptors.cantera import adaptor, thermo
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]


def document(name='minimal'):
    return json.loads((ROOT/f'examples/schemaxis/cantera-{name}.json').read_text())


def rows_for(prepared):
    x = thermo.fractions(prepared['nodes'][0]['options'])
    p = prepared['nodes'][0]['options']['pressure']
    weight = math.fsum(a*b for a,b in zip(x,thermo.WEIGHTS))
    y = [a*b/weight for a,b in zip(x,thermo.WEIGHTS)]
    return [[t]+thermo.properties(t,p,x)+x+y for t in prepared['nodes'][1]['options']['temperatures']]


class CanteraAdmissionTests(unittest.TestCase):
    def test_host_conformance(self):
        self.assertTrue(host(adaptor.VERSION)['verified'])

    def test_planning_is_immutable_and_rejects_invalid_composition(self):
        d = document(); before = copy.deepcopy(d)
        self.assertEqual(adaptor.plan(d),adaptor.plan(d)); self.assertEqual(d,before)
        for value in [[{'species':'AR','amount':0}],[{'species':'AR','amount':1}]*2,
                      [{'species':'CH4','amount':1}],[{'species':'H2','amount':-1}],
                      [{'species':'H2','amount':float('inf')}]]:
            bad = copy.deepcopy(d); bad['nodes'][0]['options']['composition'] = value
            with self.subTest(value=value),self.assertRaises(SchemaxisError): adaptor.plan(bad)
        for key,value in [('script','print(1)'),('output','gas')]:
            bad = copy.deepcopy(d); bad[key] = value
            with self.assertRaises(SchemaxisError): adaptor.plan(bad)

    def test_closed_bounds_and_dependencies(self):
        for node,key,value in [(0,'pressure',0),(0,'basis','moles'),(1,'temperatures',[299,500]),
                               (1,'temperatures',[300]*101),(1,'temperatures',[300]),(1,'mode','UV')]:
            bad = document('equilibrium'); bad['nodes'][node]['options'][key] = value
            with self.subTest(key=key,value=value),self.assertRaises(SchemaxisError): adaptor.plan(bad)
        bad = document(); bad['nodes'][1]['inputs']['input'] = 'missing'
        with self.assertRaises(SchemaxisError): adaptor.plan(bad)

    def test_analytic_monatomic_argon(self):
        x = [0]*10; x[8] = 1
        values = thermo.properties(600,202650,x)
        self.assertAlmostEqual(values[2],202650*39.95/(thermo.R*600),12)
        self.assertAlmostEqual(values[3],2.5*thermo.R*(600-298.15)/39.95,8)
        self.assertAlmostEqual(values[6],2.5*thermo.R/39.95,10)
        self.assertAlmostEqual(values[7],1.5*thermo.R/39.95,10)

    def test_mass_basis_conversion_and_scaling(self):
        options={'composition':[{'species':'H2','amount':2.016},{'species':'O2','amount':31.998}],'basis':'mass'}
        x = thermo.fractions(options)
        self.assertAlmostEqual(x[0],0.5); self.assertAlmostEqual(x[3],0.5)
        for c in options['composition']: c['amount'] *= 3
        self.assertEqual(x,thermo.fractions(options))
        options['composition']=[{'species':'H2','amount':5e-324}]
        self.assertEqual(thermo.fractions(options),[1]+[0]*9)

    def test_all_property_columns_and_species_are_checked(self):
        prepared = adaptor.plan(document()); rows = rows_for(prepared)
        self.assertEqual(len(thermo.verify_rows(prepared,rows)),3)
        for column in range(30):
            bad = copy.deepcopy(rows); bad[0][column] += 1
            with self.subTest(column=column),self.assertRaises(SchemaxisError): thermo.verify_rows(prepared,bad)

    def test_frozen_reactants_are_not_equilibrium(self):
        prepared = adaptor.plan(document('equilibrium'))
        with self.assertRaises(SchemaxisError): thermo.verify_rows(prepared,rows_for(prepared))

    def test_closed_form_hydrogen_equilibrium_and_wrong_extent(self):
        initial=[1.0]+[0.0]*9
        _,h,s=thermo.nasa(2000)
        kp=math.exp(-2*(h[1]-s[1])+h[0]-s[0]); alpha=math.sqrt(kp/(4+kp))
        x=[(1-alpha)/(1+alpha),2*alpha/(1+alpha)]+[0.0]*8
        self.assertLess(thermo.equilibrium_error(2000,101325,x,initial),1e-12)
        x[0]-=0.01; x[1]+=0.01
        self.assertGreater(thermo.equilibrium_error(2000,101325,x,initial),0.1)

    def test_missing_runtime_and_false_native_success(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.run(document(),Path(temp)/'missing',executable='/missing-cantera')
            self.assertEqual(caught.exception.fault.code,'INTERPRETER_NOT_FOUND')
            directory=Path(temp)/'false'
            with patch.object(adaptor,'execute'),self.assertRaises(SchemaxisError):
                adaptor.run(document(),directory,executable='/bin/true')
            self.assertEqual(json.loads((directory/'result.json').read_text())['status'],'failed')
            with self.assertRaises(SchemaxisError): adaptor.verify(temp)


if __name__ == '__main__': unittest.main()
