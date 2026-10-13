"""Sampled performance intent, signed margins and independent replay failures."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.ngspice import adaptor,circuit,performance
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.tabular import write_csv

ROOT=Path(__file__).resolve().parents[2]


def document(name='minimal'):
    return json.loads((ROOT/f'examples/schemaxis/ngspice-{name}.json').read_text())


def requirement(**changes):
    return {'name':'output_limit','probe':'out','quantity':'voltage_V',
        'axis':'sourceVoltage_V','window':[0,5],'minimum':0,'maximum':3.4,**changes}


def ideal_rows(prepared):
    rows=[]
    for axis in circuit.samples(prepared):
        values=circuit.expected(prepared,axis);row=[axis]
        for node in prepared['nodes']:
            value=values[node];row.extend([value.real,value.imag] if prepared['operation']=='acSweep' else [value.real])
        rows.append(row)
    return rows


class NgspicePerformanceTests(unittest.TestCase):
    def test_named_requirement_plan_is_host_safe_deterministic_and_immutable(self):
        doc=document();doc['requirements']=[requirement()];before=copy.deepcopy(doc)
        with patch.object(adaptor,'execute') as execute:
            prepared=adaptor.plan(doc);self.assertEqual(prepared,adaptor.plan(doc))
        execute.assert_not_called();self.assertEqual(doc,before)
        from jsonschema import Draft202012Validator
        Draft202012Validator(adaptor.schema()).validate(doc)
        report=adaptor.summary(prepared,ideal_rows(prepared))['performance']
        self.assertTrue(report['accepted']);self.assertEqual(report['requirements'][0]['units'],'V')
        self.assertEqual(report['requirements'][0]['checks'][1]['worstCondition']['coordinate'],5)

    def test_public_query_of_finite_component_study_is_host_safe(self):
        from schemaxis.adaptors import registry
        doc=json.loads((ROOT/'examples/schemaxis/ngspice-capacitance-study.json').read_text())
        with patch.object(adaptor,'execute') as execute:
            result=registry.query(doc)
        execute.assert_not_called()
        self.assertTrue(result['supported'])
        self.assertEqual(result['adaptors'][0]['operations'],['acSweep'])

    def test_invalid_units_quantities_windows_bounds_and_names_fail_before_launch(self):
        invalids=[[],None,[requirement(name='bad name')],[requirement(probe='in')],
            [requirement(quantity='gainMagnitude')],[requirement(axis='frequency_Hz')],
            [requirement(window=[-1,5])],[requirement(window=[5,0])],[requirement(window=[.1,.2])],
            [requirement(minimum=4,maximum=3)],[requirement(maximum=True)],
            [requirement(maximum=float('nan'))],[requirement(phase_deg=0)],
            [requirement(),requirement()]]
        no_bounds=requirement();del no_bounds['minimum'];del no_bounds['maximum'];invalids.append([no_bounds])
        for entries in invalids:
            doc=document();doc['requirements']=entries
            with self.subTest(requirements=entries),patch.object(adaptor,'execute') as execute,self.assertRaises(SchemaxisError):
                adaptor.run(doc,'/never-created',executable='/bin/true')
            execute.assert_not_called()

    def test_negative_voltage_lower_bound_uses_signed_margin_and_worst_sample(self):
        doc=document();doc.update(start=-5,stop=0)
        doc['requirements']=[requirement(window=[-5,0],minimum=-3,maximum=0)]
        prepared=adaptor.plan(doc);report=performance.assess(prepared,ideal_rows(prepared))
        self.assertFalse(report['accepted'])
        check=report['requirements'][0]['checks'][0]
        self.assertAlmostEqual(check['observed'],-10/3)
        self.assertAlmostEqual(check['margin'],-1/3)
        self.assertEqual(check['worstCondition']['coordinate'],-5)
        self.assertFalse(check['passed'])
        self.assertTrue(report['requirements'][0]['checks'][1]['passed'])

    def test_window_is_closed_and_roundoff_policy_does_not_hide_voltage_violation(self):
        doc=document();doc['requirements']=[requirement(window=[math.nextafter(5,math.inf),math.nextafter(5,math.inf)])]
        prepared=adaptor.plan(doc);report=performance.assess(prepared,ideal_rows(prepared))['requirements'][0]
        self.assertEqual(report['samplesChecked'],1);self.assertGreater(report['endpointTolerance'],0)
        self.assertEqual(report['maximumObserved']['sampleIndex'],5)
        doc['requirements'][0]['maximum']=math.nextafter(10/3,-math.inf)
        report=performance.assess(adaptor.plan(doc),ideal_rows(prepared))
        self.assertFalse(report['accepted'])  # Window tolerance never relaxes the bound.

    def test_ac_gain_uses_magnitude_and_absolute_source_amplitude(self):
        doc=document('rc-frequency');doc['amplitude']=-2
        doc['requirements']=[requirement(quantity='gainMagnitude',axis='frequency_Hz',
            window=[doc['start'],doc['stop']],minimum=.44,maximum=.72)]
        prepared=adaptor.plan(doc);report=performance.assess(prepared,ideal_rows(prepared))
        self.assertTrue(report['accepted']);entry=report['requirements'][0]
        self.assertEqual(entry['units'],'V/V')
        self.assertAlmostEqual(entry['maximumObserved']['value'],1/math.sqrt(2))
        self.assertAlmostEqual(entry['minimumObserved']['value'],1/math.sqrt(5))
        doc['circuit']['capacitors'][0]['capacitance']=2e-6
        prepared=adaptor.plan(doc);report=performance.assess(prepared,ideal_rows(prepared))
        self.assertFalse(report['accepted'])
        self.assertEqual(report['requirements'][0]['checks'][0]['worstCondition']['coordinate'],doc['stop'])

    def test_magnitude_bounds_and_ac_axis_are_explicit_in_schema(self):
        from jsonschema import Draft202012Validator,ValidationError
        doc=document('rc-frequency');doc['requirements']=[requirement(quantity='magnitude_V',axis='frequency_Hz',
            window=[doc['start'],doc['stop']],minimum=0,maximum=1)]
        schema=adaptor.schema();Draft202012Validator(schema).validate(doc)
        for key,value in (('minimum',-1),('quantity','voltage_V'),('axis','time_s')):
            bad=copy.deepcopy(doc);bad['requirements'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValidationError):Draft202012Validator(schema).validate(bad)
            with self.assertRaises(SchemaxisError):adaptor.plan(bad)
        # Schema generation must never alter the signed DC specification.
        doc=document();doc.update(start=-5,stop=0);doc['requirements']=[requirement(window=[-5,0],minimum=-4)]
        adaptor.plan(doc)

    def test_rc_settling_windows_and_sample_only_limits(self):
        doc=document('rc-step');doc['requirements']=[requirement(axis='time_s',window=[.003,.005],minimum=4.7,maximum=5)]
        prepared=adaptor.plan(doc);report=performance.assess(prepared,ideal_rows(prepared))
        self.assertTrue(report['accepted']);self.assertEqual(report['requirements'][0]['samplesChecked'],3)
        doc['circuit']['resistors'][0]['resistance']=2000
        prepared=adaptor.plan(doc);report=performance.assess(prepared,ideal_rows(prepared))
        self.assertFalse(report['accepted'])
        self.assertEqual(report['requirements'][0]['checks'][0]['worstCondition']['coordinate'],.003)
        self.assertIn('no continuous',report['coverage'])

    def fixture(self,root):
        """Literal divider evidence independently expected from Vout=2*Vin/3."""
        doc=document();doc['points']=2;doc['requirements']=[requirement()]
        prepared=adaptor.plan(doc);rows=[[0,0,0],[5,5,10/3]]
        output=root/'run';output.mkdir()
        for name,value in (('authored.json',doc),('plan.json',prepared),('result.json',{'status':'succeeded','verified':True}),
                           ('runtime.json',{'name':'ngspice','version':'47','executable':'/native/ngspice'})):
            atomic_json(output/name,value)
        build,reopen=adaptor.netlists(prepared);(output/'circuit.cir').write_text(build);(output/'reopen.cir').write_text(reopen)
        raw=('Title: fixture\nFlags: real\nNo. Variables: 3\nNo. Points: 2\nVariables:\n'
             '0 v(v-sweep) voltage\n1 v(in) voltage\n2 v(out) voltage\nValues:\n0 0\n0\n0\n1 5\n5\n3.3333333333333335\n')
        (output/'result.raw').write_text(raw)
        for name in ('native.dat','reopened.dat'):
            (output/name).write_text('v-sweep in out\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n')
        (output/'version.stdout').write_text('ngspice-47 : simulator\n');(output/'version.stderr').write_text('')
        write_csv(output/'results.csv',circuit.publication(prepared,rows))
        atomic_json(output/'circuit-summary.json',adaptor.summary(prepared,rows))
        self.refresh_receipt(output);self.assertTrue(adaptor.verify(output)['verified'])
        return output,rows

    def refresh_receipt(self,output):
        atomic_json(output/'verification.json',{'artifacts':adaptor.manifest(output),
            'evidence':{name:file_digest(output/name) for name in adaptor.EVIDENCE}})
        from schemaxis.publication_metadata import finalise
        finalise(output)

    def test_refreshed_hashes_cannot_forge_a_passing_performance_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            output,rows=self.fixture(Path(temp))
            authored=json.loads((output/'authored.json').read_text());authored['requirements'][0]['maximum']=3
            atomic_json(output/'authored.json',authored);prepared=adaptor.plan(authored);atomic_json(output/'plan.json',prepared)
            details=adaptor.summary(prepared,rows);details['performance']['accepted']=True
            details['performance']['requirements'][0]['accepted']=True
            details['performance']['requirements'][0]['checks'][1].update(passed=True,margin=.1)
            atomic_json(output/'circuit-summary.json',details);self.refresh_receipt(output)
            with self.assertRaises(SchemaxisError) as caught:adaptor.verify(output)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
            atomic_json(output/'circuit-summary.json',adaptor.summary(prepared,rows));self.refresh_receipt(output)
            with self.assertRaises(SchemaxisError) as caught:adaptor.verify(output)
            self.assertEqual(caught.exception.fault.code,'PERFORMANCE_NOT_MET')

    def test_physics_disagreement_is_not_an_ordinary_unmet_requirement(self):
        with tempfile.TemporaryDirectory() as temp:
            output,rows=self.fixture(Path(temp));path=output/'native.dat'
            path.write_text(path.read_text().replace('3.3333333333333335','3.1'));self.refresh_receipt(output)
            with self.assertRaises(SchemaxisError) as caught:adaptor.verify(output)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')


if __name__=='__main__':unittest.main()
