"""Thermal reactor contracts, analytic cooling and falsified energy evidence."""
import copy
import json
import math
from pathlib import Path
import unittest

from schemaxis.adaptors.cantera import adaptor, kinetics, thermo
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT/'tests/fixtures/cantera-thermal-native.json').read_text())

def document():
    return json.loads((ROOT/'examples/schemaxis/cantera-thermal-reactor.json').read_text())

class ThermalContractTests(unittest.TestCase):
    def test_plan_is_immutable_with_physical_units_and_no_wall_by_default(self):
        d=document(); original=copy.deepcopy(d); p=adaptor.plan(d)
        self.assertEqual(d,original); self.assertEqual(p,FIXTURE['plan'])
        self.assertFalse(p['reactor']['adiabatic'])
        self.assertEqual(p['reactor']['thermal']['conductance_W_K'],1000)
        for field in ('thermalConductance','bathTemperature'): d['nodes'][1]['options'].pop(field)
        p=adaptor.plan(d)
        self.assertTrue(p['reactor']['adiabatic']); self.assertNotIn('thermal',p['reactor'])
        self.assertEqual(p['nodes'][1]['options']['bathTemperature'],300)

    def test_invalid_fields_rejected_at_exact_field_before_execution(self):
        for field,values in [('thermalConductance',[-1,1000001,True,float('nan'),'1000']),
                             ('bathTemperature',[299,3501,False,float('inf'),'500'])]:
            for value in values:
                d=document(); d['nodes'][1]['options'][field]=value
                with self.subTest(field=field,value=value),self.assertRaises(SchemaxisError) as caught:
                    adaptor.plan(d)
                self.assertEqual(caught.exception.fault.code,'INVALID_ARGUMENT')
                self.assertIn(field,caught.exception.fault.location)

    def test_inert_cooling_matches_closed_form_for_both_models(self):
        for model in kinetics.MODELS:
            d=document();d['nodes'][0]['options']['composition']=[{'species':'AR','amount':1}]
            settings=d['nodes'][1]['options'];settings.update(model=model,times=[0,0.01,0.1,1])
            p=adaptor.plan(d);t0,pressure,x0,_=kinetics.initial(p)
            state=thermo.properties(t0,pressure,x0);mass=state[2]
            c=state[6 if model == 'constantPressure' else 7]
            history=kinetics.history(p)['trajectory']
            for t in settings['times']:
                y=next(y for stamp,y in history if stamp == t)
                expected=500+(t0-500)*math.exp(-1000*t/(mass*c))
                self.assertAlmostEqual(y[0],expected,delta=0.001)
                self.assertAlmostEqual(y[-1],c*(y[0]-t0),delta=0.001)
            self.assertIsNone(kinetics.history(p)['ignition'])

    def test_real_thermal_history_passes_independent_energy_and_kinetics(self):
        f=copy.deepcopy(FIXTURE)
        checks,ignition,_=kinetics.verify_history(f['plan'],f['rows'],{'reactor':f['reactor']},f['reopenedRates'])
        self.assertLess(checks[-1]['independentHeatInput_J_kg'],0)
        self.assertLess(checks[-1]['energyError_J_kg'],1)
        self.assertIsNotNone(ignition['delay_s'])

    def test_studio_thermal_template_fields_project_to_both_models(self):
        from schemaxis.studio_library import instantiate_item, load_library, plan_item
        library=load_library('cantera')
        template=next(i for i in library['templates'] if i['id'] == 'reactor-thermal')
        for model in kinetics.MODELS:
            variant=copy.deepcopy(template)
            variant['testValues']={'model':model,'temperature':900,'pressure':202650,
                                   'thermalConductance':2500,'bathTemperature':1600}
            prepared=plan_item(instantiate_item(library,variant,provider='cantera'))
            self.assertEqual(prepared['nodes'][0]['options']['pressure'],202650)
            settings=prepared['nodes'][1]['options']
            for field in ('model','temperature','thermalConductance','bathTemperature'):
                self.assertEqual(settings[field],variant['testValues'][field])

    def test_wall_heat_rate_and_energy_cannot_be_forged(self):
        attacks=[lambda f:f['reactor']['thermal'].update(conductance_W_K=999),
                 lambda f:f['reactor']['thermal'].update(emissivity=0.1),
                 lambda f:f['reactor']['thermal'].update(area_m2=True),
                 lambda f:f['reactor']['thermal'].update(emissivity=False),
                 lambda f:f['reactor']['samples'][-1].update(heatRateOut_W=0),
                 lambda f:f['reactor']['samples'][-1].update(bathTemperature_K=501),
                 lambda f:f['reactor']['samples'][-1].update(expansionRate_m3_s=1e-6),
                 lambda f:f['reactor']['samples'][-1].update(heatRateOut_W=True),
                 lambda f:f['plan']['nodes'][1]['options'].update(bathTemperature=1000)]
        for attack in attacks:
            f=copy.deepcopy(FIXTURE);attack(f)
            with self.subTest(attack=attack),self.assertRaises(SchemaxisError):
                kinetics.verify_history(f['plan'],f['rows'],{'reactor':f['reactor']},f['reopenedRates'])

if __name__ == '__main__': unittest.main()
