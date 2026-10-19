"""Host reactor-history contracts and independent kinetics falsification tests."""
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.cantera import adaptor, kinetics, thermo
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT/'tests/fixtures/cantera-reactor-native.json').read_text())


def document():
    return json.loads((ROOT/'examples/schemaxis/cantera-reactor.json').read_text())


def evidence():
    data = copy.deepcopy(FIXTURE)
    return data['plan'],data['rows'],{'reactor':data['reactor']},data['reopenedRates']


def fault(callable_,*args):
    with unittest.TestCase().assertRaises(SchemaxisError) as caught: callable_(*args)
    return caught.exception.fault


class ReactorPlanningTests(unittest.TestCase):
    def test_plan_is_immutable_and_declares_reactor_scope(self):
        d = document(); before = copy.deepcopy(d)
        prepared = adaptor.plan(d)
        self.assertEqual(d,before); self.assertEqual(prepared,adaptor.plan(d))
        self.assertEqual(prepared,FIXTURE['plan'])
        self.assertEqual(prepared['columns'][0],'time_s'); self.assertEqual(len(prepared['columns']),30)
        self.assertEqual(prepared['reactor']['native'],'cantera.IdealGasConstPressureReactor')
        d['nodes'][1]['options']['model'] = 'constantVolume'
        self.assertEqual(adaptor.plan(d)['reactor'],{'native':'cantera.IdealGasReactor','network':'cantera.ReactorNet',
            'closed':True,'adiabatic':True,'volume_m3':1.0,'held':'volume'})

    def test_defaults_are_explicit(self):
        d = document(); d['nodes'][1]['options'] = {}
        options = adaptor.plan(d)['nodes'][1]['options']
        self.assertEqual(options,{'model':'constantPressure','temperature':1000,'times':[0,0.0001,0.0002,0.0003,0.0004,0.0005,0.001],
                                  'relativeTolerance':1e-9,'absoluteTolerance':1e-15,'maxSteps':20000,'ignitionTemperatureRise':400})

    def test_exact_faults_for_invalid_settings(self):
        cases = [('times',[0,0.001,0.001],'INVALID_TIMES'),('times',[0.002,0.001],'INVALID_TIMES'),
                 ('times',[0],'INVALID_ARGUMENT'),('times',[0,1.5],'INVALID_ARGUMENT'),('times',[-1e-6,0.001],'INVALID_ARGUMENT'),
                 ('relativeTolerance',1e-6,'INVALID_ARGUMENT'),('absoluteTolerance',1e-10,'INVALID_ARGUMENT'),
                 ('maxSteps',50,'INVALID_ARGUMENT'),('maxSteps',2.5,'INVALID_ARGUMENT'),('temperature',250,'INVALID_ARGUMENT'),
                 ('ignitionTemperatureRise',0,'INVALID_ARGUMENT'),('model','isothermal','INVALID_ARGUMENT'),
                 ('script','import os','UNKNOWN_ARGUMENT')]
        for key,value,code in cases:
            d = document(); d['nodes'][1]['options'][key] = value
            with self.subTest(key=key,value=value):
                observed = fault(adaptor.plan,d)
                self.assertEqual(observed.code,code)
        d = document(); d['nodes'][1]['options']['times'] = [0,0.002,0.001]
        self.assertEqual(fault(adaptor.plan,d).location,'ignition.options.times')

    def test_existing_operations_keep_their_plan_contract(self):
        d = json.loads((ROOT/'examples/schemaxis/cantera-equilibrium.json').read_text())
        prepared = adaptor.plan(d)
        self.assertEqual(prepared['columns'],thermo.COLUMNS); self.assertEqual(prepared['losses'],adaptor.LOSSES)
        self.assertNotIn('reactor',prepared)


class IndependentKineticsTests(unittest.TestCase):
    def test_rate_data_is_the_pinned_upstream_mechanism(self):
        self.assertEqual(kinetics.DATA['mechanismSHA256'],thermo.DATA['mechanismSHA256'])
        self.assertEqual(len(kinetics.REACTIONS),29)
        self.assertEqual(kinetics.DATA['units'],{'length':'cm','time':'s','quantity':'mol','activation-energy':'cal/mol'})
        for record in kinetics.DATA['reactions']:
            left,right = record['equation'].replace('(+M)','+ (M)').split('<=>')
            parse = lambda text:{(p.split()[-1]):(float(p.split()[0]) if len(p.split()) == 2 else 1.0)
                                 for p in (t.strip() for t in text.split(' + ')) if p not in ('M','(M)')}
            with self.subTest(equation=record['equation']):
                self.assertEqual(parse(left),record['reactants']); self.assertEqual(parse(right),record['products'])

    def test_every_reaction_conserves_atoms_and_inert_gas_is_unreactive(self):
        state = [0.01*(i+1) for i in range(10)]
        rates,scale = kinetics.production(1500,state)
        self.assertGreater(scale,0)
        for element in thermo.DATA['elements']:
            total = math.fsum(r*s['atoms'].get(element,0) for r,s in zip(rates,thermo.DATA['species']))
            self.assertLess(abs(total),1e-12*scale)
        self.assertEqual(kinetics.production(1500,[0]*8+[0.02,0.01]),([0.0]*10,0.0))

    def test_detailed_balance_at_closed_form_hydrogen_dissociation(self):
        # Independent analytic H2 <=> 2H equilibrium from NASA7 Kp (also used by the TP tests).
        t,p = 2000,101325
        _,h,s = thermo.nasa(t)
        kp = math.exp(-2*(h[1]-s[1])+h[0]-s[0]); alpha = math.sqrt(kp/(4+kp))
        x = [(1-alpha)/(1+alpha),2*alpha/(1+alpha)]+[0.0]*8
        rates,scale = kinetics.production(t,[v*p/(thermo.R*t) for v in x])
        self.assertLess(max(map(abs,rates)),1e-12*scale)
        x[0] -= 0.01; x[1] += 0.01
        rates,_ = kinetics.production(t,[v*p/(thermo.R*t) for v in x])
        self.assertLess(rates[1],0)  # Excess atoms recombine.

    def test_rosenbrock_is_fourth_order(self):
        def f(y): return [-y[0],-1e4*y[1]+y[0]]
        errors = []
        for n in (10,20,40):
            y = [1.0,0.0]
            for _ in range(n): y,_ = kinetics._step(f,y,1/n,f(y),[[-1.0,0.0],[1.0,-1e4]])
            errors.append(abs(y[0]-math.exp(-1)))
        self.assertGreater(errors[0]/errors[1],12); self.assertGreater(errors[1]/errors[2],12)

    def test_independent_history_conserves_energy_and_elements(self):
        prepared = adaptor.plan(document())
        result = kinetics.history(prepared)
        t0,p0,x0,_ = kinetics.initial(prepared)
        start = thermo.properties(t0,p0,x0); elements = thermo.elements(x0)
        final_t,final = result['trajectory'][-1]
        x = kinetics._moles(final[1:]); end = thermo.properties(final[0],p0,x)
        self.assertGreater(final[0],2600)
        self.assertLess(abs(end[3]-start[3]),start[6]*t0*1e-6+kinetics._jump(t0,final[0]))
        self.assertLess(max(abs(thermo.elements(x)[e]-v) for e,v in elements.items()),1e-12)
        self.assertAlmostEqual(result['ignition'],3.1114e-4,delta=3e-7)

    def test_inert_reactor_is_unchanged(self):
        d = document()
        d['nodes'][0]['options']['composition'] = [{'species':'AR','amount':1},{'species':'N2','amount':1}]
        d['nodes'][1]['options'].update(model='constantVolume',temperature=1500)
        result = kinetics.history(adaptor.plan(d))
        self.assertIsNone(result['ignition'])
        self.assertTrue(all(y[0] == 1500 for _,y in result['trajectory']))

    def test_nasa_range_jump_is_bounded_and_only_counted_when_crossed(self):
        self.assertAlmostEqual(kinetics._jump(900,1100),0.18555729,6)
        self.assertEqual(kinetics._jump(1100,2500),0.0)

    def test_crossing_is_linear_and_bounded_by_the_history(self):
        points = [(0.0,1000.0),(1.0,1200.0),(2.0,1600.0)]
        self.assertEqual(kinetics.crossing(points,1400.0,2.0),1.5)
        self.assertIsNone(kinetics.crossing(points,1400.0,1.4))
        self.assertIsNone(kinetics.crossing(points,1700.0,2.0))


class ReactorVerificationTests(unittest.TestCase):
    def test_recorded_native_history_is_independently_verified(self):
        prepared,rows,native,reopened = evidence()
        checks,ignition,independent = kinetics.verify_history(prepared,rows,native,reopened)
        self.assertEqual(len(checks),11)
        self.assertLess(abs(ignition['delay_s']/independent['independentIgnitionDelay_s']-1),1e-4)
        self.assertLess(independent['finalEquilibriumResidual_RT'],1e-9)
        self.assertEqual(ignition['threshold_K'],1400)

    def test_summary_is_reproducible_with_tolerant_integrator_values(self):
        prepared,rows,native,reopened = evidence()
        saved = adaptor.summary(prepared,rows,native,reopened)
        self.assertTrue(adaptor.same_summary(saved,adaptor.summary(prepared,rows,native)))
        drift = copy.deepcopy(saved); drift['independent']['independentIgnitionDelay_s'] *= 1+1e-9
        self.assertTrue(adaptor.same_summary(drift,saved))
        drift['independent']['independentIgnitionDelay_s'] *= 1.001
        self.assertFalse(adaptor.same_summary(drift,saved))
        drift = copy.deepcopy(saved); drift['ignition']['delay_s'] *= 1+1e-12
        self.assertFalse(adaptor.same_summary(drift,saved))

    def test_every_published_column_is_checked(self):
        prepared,rows,native,reopened = evidence()
        for column in range(30):
            bad = copy.deepcopy(rows); bad[7][column] += 1e-3*max(abs(bad[7][column]),1)
            with self.subTest(column=column),self.assertRaises(SchemaxisError):
                kinetics.verify_history(prepared,bad,native,reopened)

    def test_consistent_time_shifted_state_is_rejected_by_kinetics(self):
        # Row 4 (0.31 ms) replaced by the real, thermodynamically consistent state at 0.32 ms.
        prepared,rows,native,reopened = evidence()
        rows[4] = rows[5][:]; rows[4][0] = 0.00031
        native['reactor']['samples'][4] = dict(native['reactor']['samples'][5],time=0.00031)
        reopened[4] = reopened[5]
        observed = fault(kinetics.verify_history,prepared,rows,native,reopened)
        self.assertIn('independent kinetics',observed.message)

    def test_wrong_kinetics_or_ignition_record_is_rejected(self):
        prepared,rows,native,reopened = evidence()
        steps = native['reactor']['steps']
        native['reactor']['steps'] = [[t*1.02,temperature] for t,temperature in steps]
        self.assertIn('ignition delay',fault(kinetics.verify_history,prepared,rows,native,reopened).message)
        prepared,rows,native,reopened = evidence()
        changed = copy.deepcopy(kinetics.REACTIONS)
        index = next(i for i,r in enumerate(kinetics.DATA['reactions']) if r['equation'] == 'H + O2 <=> O + OH')
        a,b,ea = changed[index]['rate']; changed[index]['rate'] = (a*1.05,b,ea)
        with patch.object(kinetics,'REACTIONS',changed),patch.object(kinetics,'_HISTORIES',{}):
            self.assertRaises(SchemaxisError,kinetics.verify_history,prepared,rows,native,reopened)
            shifted = kinetics.history(prepared)['ignition']
        self.assertGreater(abs(shifted/kinetics.history(prepared)['ignition']-1),kinetics.SHIFT)

    def test_native_readback_conservation_and_rate_evidence_are_required(self):
        mutations = [
            ('solver',lambda n,r:n['reactor']['solver'].update(rtol=1e-8)),
            ('initial mass',lambda n,r:n['reactor']['initial'].update(mass=n['reactor']['initial']['mass']*(1+1e-6))),
            ('sample mass',lambda n,r:n['reactor']['samples'][6].update(mass=n['reactor']['samples'][6]['mass']*(1+1e-6))),
            ('volume',lambda n,r:n['reactor']['initial'].update(volume=2.0)),
            ('native rates',lambda n,r:n['reactor']['samples'][3]['rates'].__setitem__(1,n['reactor']['samples'][3]['rates'][1]*1.001+1e-9)),
            ('reopened rates',lambda n,r:r[3].__setitem__(1,r[3][1]*1.001+1e-9)),
            ('missing reopened rates',lambda n,r:r.pop()),
            ('sample time',lambda n,r:n['reactor']['samples'][2].update(time=0.000201)),
            ('steps',lambda n,r:n['reactor']['steps'].reverse()),
            ('boolean sample rate',lambda n,r:n['reactor']['samples'][0]['rates'].__setitem__(8,False)),
            ('boolean volume',lambda n,r:n['reactor']['initial'].update(volume=True)),
            ('boolean step',lambda n,r:n['reactor']['steps'][1].__setitem__(0,True)),
            ('short rate vector',lambda n,r:r[0].pop())]
        for name,mutate in mutations:
            prepared,rows,native,reopened = evidence(); mutate(native,reopened)
            with self.subTest(name=name),self.assertRaises(SchemaxisError):
                kinetics.verify_history(prepared,rows,native,reopened)

    def test_out_of_range_state_is_rejected(self):
        prepared,rows,native,reopened = evidence()
        rows[-1][1] = 3600.0
        self.assertIn('outside',fault(kinetics.verify_history,prepared,rows,native,reopened).message)


class ReactorStudioTests(unittest.TestCase):
    def test_every_studio_item_instantiates_and_plans(self):
        from schemaxis.studio_library import instantiate_item, load_library, plan_item
        library = load_library('cantera')
        items = library['snippets']+library['templates']
        self.assertIn('reactor-history',[i['id'] for i in items]); self.assertIn('reactor-ignition',[i['id'] for i in items])
        for item in items:
            with self.subTest(item=item['id']):
                prepared = plan_item(instantiate_item(library,item,provider='cantera'))
                if item['id'].startswith('reactor'):
                    self.assertEqual(prepared['nodes'][1]['filter'],'reactorHistory')
                    self.assertEqual(prepared['columns'][0],'time_s')
        template = next(i for i in library['templates'] if i['id'] == 'reactor-ignition')
        for model in template['fields']['model']['values']:
            variant = copy.deepcopy(template); variant['testValues'] = {'model':model,'temperature':1100,'pressure':202650}
            prepared = plan_item(instantiate_item(library,variant,provider='cantera'))
            self.assertEqual(prepared['nodes'][1]['options']['model'],model)
            self.assertEqual(prepared['nodes'][0]['options']['pressure'],202650)


class ReactorReceiptTests(unittest.TestCase):
    """Complete offline receipts built from recorded native evidence.

The pinned mechanism bytes are not redistributed in tests, so a stand-in file and
its digest replace them; every other check runs unchanged.
"""
    MECHANISM = b'stand-in mechanism bytes for offline receipt tests\n'

    def receipt(self,directory):
        d = document(); prepared = adaptor.plan(d); recorded = copy.deepcopy(FIXTURE)
        directory.mkdir()
        (directory/'mechanism.yaml').write_bytes(self.MECHANISM)
        (directory/'worker.py').write_text('# retained worker copy\n')
        common = {'plan':prepared,'species':list(thermo.SPECIES),'phase':'ohmech',
                  'mechanismSHA256':prepared['mechanism']['sha256'],'runtime':FIXTURE['runtime']}
        built = {'stage':'build','pid':1,'rows':recorded['rows'],'reactor':recorded['reactor'],**common}
        reopened = {'stage':'reopen','pid':2,'rows':copy.deepcopy(recorded['rows']),'rates':recorded['reopenedRates'],**common}
        atomic_json(directory/'authored.json',d); atomic_json(directory/'plan.json',prepared)
        atomic_json(directory/'built.json',built); atomic_json(directory/'reopened.json',reopened)
        with (directory/'results.csv').open('w',newline='') as stream:
            writer = csv.writer(stream); writer.writerow(prepared['columns']); writer.writerows(recorded['rows'])
        atomic_json(directory/'chemistry-summary.json',adaptor.summary(prepared,recorded['rows'],built))
        self.seal(directory)
        atomic_json(directory/'result.json',{'status':'succeeded','verified':True})
        return reopened

    def seal(self,directory):
        atomic_json(directory/'verification.json',{'artifacts':adaptor.manifest(directory),
            'evidence':{n:file_digest(directory/n) for n in adaptor.EVIDENCE}})

    def test_reopened_rows_must_have_planned_shape_and_finite_values(self):
        attacks = {'empty rows':lambda r:r.update(rows=[[] for _ in r['rows']]),
                   'short rows':lambda r:r.update(rows=[row[:-1] for row in r['rows']]),
                   'extra row':lambda r:r['rows'].append(r['rows'][-1]),
                   'boolean cell':lambda r:r['rows'][2].__setitem__(0,False),
                   'non-finite cell':lambda r:r['rows'][2].__setitem__(3,float('inf')),
                   'boolean rate':lambda r:r['rates'][0].__setitem__(8,False),
                   'non-finite rate':lambda r:r['rates'][0].__setitem__(8,float('nan')),
                   'empty rates':lambda r:r.update(rates=[]),
                   'missing rates':lambda r:r.pop('rates')}
        with patch.dict(thermo.DATA,{'mechanismSHA256':hashlib.sha256(self.MECHANISM).hexdigest()}),tempfile.TemporaryDirectory() as temp:
            intact = Path(temp)/'intact'; self.receipt(intact)
            self.assertTrue(adaptor._native_verify(intact)['verified'])
            for name,attack in attacks.items():
                directory = Path(temp)/name.replace(' ','-'); reopened = self.receipt(directory)
                attack(reopened); (directory/'reopened.json').write_text(json.dumps(reopened))
                self.seal(directory)  # A forged digest refresh must not rescue the receipt.
                with self.subTest(attack=name),self.assertRaises(SchemaxisError) as caught:
                    adaptor._native_verify(directory)
                self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')


if __name__ == '__main__': unittest.main()
