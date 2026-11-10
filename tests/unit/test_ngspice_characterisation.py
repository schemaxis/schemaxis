"""Engineering frequency grids, electrical sign conventions and adverse inputs."""
import copy
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from schemaxis.adaptors.ngspice import adaptor,circuit,performance
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[2]


def document():
    value=json.loads((ROOT/'examples/schemaxis/ngspice-rc-frequency.json').read_text())
    value.update(portMetrics=True,amplitudeConvention='peak')
    value['circuit']['branchProbes']=['r1','c1']
    return value


def rows(prepared):
    result=[]
    for f in circuit.samples(prepared):
        values=circuit.expected(prepared,f);row=[f]
        for node in prepared['nodes']:row.extend([values[node].real,values[node].imag])
        if prepared.get('portMetrics'):
            current=-circuit.input_current(prepared,f,values);row.extend([current.real,current.imag])
        result.append(row)
    return result


class NgspiceCharacterisationTests(unittest.TestCase):
    def test_frequency_grids_follow_ngspice47_density_semantics(self):
        doc=document();doc.update(start=10,stop=10000,points=4,spacing='decade')
        before=copy.deepcopy(doc);p=adaptor.plan(doc);self.assertEqual(doc,before)
        axis=circuit.samples(p);self.assertEqual(len(axis),13)
        for i,f in enumerate(axis):self.assertAlmostEqual(f,10*10**(i/4))
        self.assertIn('ac dec 4 10 10000',adaptor.netlists(p)[0])
        doc.update(start=100,stop=350,points=3,spacing='octave')
        axis=circuit.samples(adaptor.plan(doc));self.assertEqual(len(axis),6)
        self.assertAlmostEqual(axis[-1],100*2**(5/3));self.assertLess(axis[-1],350)
        doc.update(start=10,stop=3700,points=5,spacing='decade')
        axis=circuit.samples(adaptor.plan(doc));self.assertEqual(len(axis),13)
        self.assertAlmostEqual(axis[-1],3700)
        doc.update(start=10,stop=23,points=10)
        self.assertEqual(len(circuit.samples(adaptor.plan(doc))),4)

    def test_frequency_and_output_resource_limits_before_launch(self):
        cases=[]
        doc=document();doc.update(start=.001,stop=1e9,spacing='decade',points=512);cases.append((doc,'RESOURCE_LIMIT'))
        doc=document();doc.update(start=10,stop=10.1,spacing='octave',points=3);cases.append((doc,'RESOURCE_LIMIT'))
        doc=document();doc['circuit']['branchProbes']=['absent'];cases.append((doc,'INVALID_SELECTION'))
        doc=document();doc['circuit']['branchProbes']=['r1','r1'];cases.append((doc,'INVALID_ARGUMENT'))
        doc=document();doc['spacing']='log';cases.append((doc,'INVALID_ARGUMENT'))
        doc=document();doc['portMetrics']='true';cases.append((doc,'INVALID_ARGUMENT'))
        for doc,code in cases:
            with self.subTest(code=code),patch.object(adaptor,'execute') as execute,self.assertRaises(SchemaxisError) as caught:
                adaptor.run(doc,'/never-created',executable='/bin/true')
            execute.assert_not_called();self.assertEqual(caught.exception.fault.code,code)

    def test_selected_metrics_share_output_column_budget(self):
        doc=document();nodes=['out']+['n'+str(i) for i in range(13)]
        doc['circuit']['resistors'] += [{'name':'load'+str(i),'a':'in','b':node,'resistance':1000}
                                      for i,node in enumerate(nodes[1:])]
        doc['circuit']['probes']=nodes
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(doc)
        self.assertEqual((caught.exception.fault.code,caught.exception.fault.location),('RESOURCE_LIMIT','$.circuit'))

    def test_editable_studio_characterisation_template_preserves_library(self):
        from schemaxis.studio_library import load_library,instantiate_item
        metadata=load_library('ngspice');before=copy.deepcopy(metadata)
        item=next(t for t in metadata['templates'] if t['id']=='filter-characterisation')
        doc=instantiate_item(metadata,item,provider='ngspice')
        p=adaptor.plan(doc);self.assertEqual(p['spacing'],'decade');self.assertTrue(p['portMetrics'])
        self.assertEqual(metadata,before)
        self.assertEqual(len(p['requirements']),6)

    def test_closed_form_rc_current_impedance_and_peak_power(self):
        p=adaptor.plan(document());row=rows(p)[0];circuit.inspect(p,[*rows(p)])
        table=circuit.publication(p,[row]);data=dict(zip(table['columns'],table['rows'][0]))
        # At cutoff Z=1000-j1000; I=(1+j)/2000, S=(1-j)/4000.
        self.assertAlmostEqual(data['$input_current_real_A'],.0005)
        self.assertAlmostEqual(data['$input_current_imag_A'],.0005)
        self.assertAlmostEqual(data['$input_impedance_real_Ohm'],1000)
        self.assertAlmostEqual(data['$input_impedance_imag_Ohm'],-1000)
        self.assertAlmostEqual(data['$input_activePower_W'],.00025)
        self.assertAlmostEqual(data['$input_reactivePower_var'],-.00025)
        self.assertAlmostEqual(data['r1_activePower_W'],.00025)
        self.assertAlmostEqual(data['c1_reactivePower_var'],-.00025)
        self.assertAlmostEqual(data['c1_activePower_W'],0)

    def test_reversing_branch_changes_current_but_preserves_passive_power(self):
        original=document();p=adaptor.plan(original);reference=circuit.publication(p,rows(p))
        original['circuit']['capacitors'][0].update(a='0',b='out')
        p=adaptor.plan(original);table=circuit.publication(p,rows(p))
        for old,new in zip(reference['rows'],table['rows']):
            a=dict(zip(reference['columns'],old));b=dict(zip(table['columns'],new))
            self.assertAlmostEqual(a['c1_current_imag_A'],-b['c1_current_imag_A'])
            self.assertAlmostEqual(a['c1_reactivePower_var'],b['c1_reactivePower_var'])
            self.assertAlmostEqual(a['$input_current_imag_A'],b['$input_current_imag_A'])

    def test_rms_and_negative_excitation_power_scaling(self):
        p=adaptor.plan(document());a=circuit.publication(p,rows(p))['rows'][0]
        doc=document();doc.update(amplitudeConvention='rms',amplitude=-2)
        p=adaptor.plan(doc);table=circuit.publication(p,rows(p));b=table['rows'][0]
        for name in ('r1_activePower_W','c1_reactivePower_var','$input_activePower_W'):
            index=table['columns'].index(name);self.assertAlmostEqual(b[index],8*a[index])
        self.assertAlmostEqual(circuit.observables(p,rows(p)[0])['out']['phase_deg'],-45)
        self.assertAlmostEqual(circuit.observables(p,rows(p)[0])['out']['gain_dB'],-10*math.log10(2))

    def test_source_current_sign_and_unselected_voltage_corruption_rejected(self):
        p=adaptor.plan(document());good=rows(p);circuit.inspect(p,good)
        for column in (-1,-2,1):
            bad=copy.deepcopy(good);bad[0][column]*=-1
            with self.subTest(column=column),self.assertRaises(SchemaxisError):circuit.inspect(p,bad)

    def test_tiny_excitation_cannot_hide_relative_current_or_transfer_error(self):
        doc=document();doc['amplitude']=1e-15
        doc['circuit']['resistors'][0]['resistance']=1e9
        doc['circuit']['capacitors'][0]['capacitance']=1e-12
        p=adaptor.plan(doc);good=rows(p);circuit.inspect(p,good)
        for scale in (0,2,-1):
            bad=copy.deepcopy(good)
            for row in bad:row[-2:]=[v*scale for v in row[-2:]]
            with self.subTest(scale=scale),self.assertRaises(SchemaxisError):circuit.inspect(p,bad)
        bad=copy.deepcopy(good);bad[0][3]*=2
        with self.assertRaises(SchemaxisError):circuit.inspect(p,bad)

    def test_current_power_phase_and_decibel_requirements(self):
        doc=document();window=[doc['start'],doc['stop']]
        doc['requirements']=[{'name':'check_'+str(i),'probe':probe,'quantity':quantity,'axis':'frequency_Hz','window':window,
                             'minimum':lower,'maximum':upper} for i,(probe,quantity,lower,upper) in enumerate([
            ('out','phase_deg',-64,-44),('out','gain_dB',-7.1,-3),('$input','currentMagnitude_A',.0007,.0009),
            ('r1','activePower_W',.00024,.00041),('c1','reactivePower_var',-.00026,-.00019),
            ('$input','impedanceMagnitude_Ohm',1100,1500)])]
        p=adaptor.plan(doc);report=performance.assess(p,rows(p));self.assertTrue(report['accepted'])
        self.assertEqual([r['units'] for r in report['requirements']],['deg','dB','A','W','var','ohm'])
        doc['requirements'][0]['minimum']=-60;p=adaptor.plan(doc)
        report=performance.assess(p,rows(p));self.assertFalse(report['accepted'])
        self.assertLess(report['requirements'][0]['checks'][0]['margin'],0)

    def test_undefined_phase_gain_and_input_impedance_refused(self):
        doc=document();doc['circuit']['resistors'] += [{'name':'load','a':'silent','b':'0','resistance':1000}]
        doc['circuit']['probes']=['silent']
        for quantity in ('phase_deg','gain_dB'):
            doc['requirements']=[{'name':'silent','probe':'silent','quantity':quantity,'axis':'frequency_Hz',
                                  'window':[doc['start'],doc['stop']],'minimum':-1}]
            with self.subTest(quantity=quantity),self.assertRaises(SchemaxisError) as caught:adaptor.plan(doc)
            self.assertEqual(caught.exception.fault.code,'UNDEFINED_OBSERVABLE')
        doc=document();doc['circuit']['resistors'][0].update(a='out',b='0')
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(doc)
        self.assertEqual(caught.exception.fault.code,'UNDEFINED_OBSERVABLE')
        doc['portMetrics']=False;adaptor.plan(doc)

    def test_requirement_schema_preserves_signed_quantities_and_selection(self):
        from jsonschema import Draft202012Validator,ValidationError
        doc=document();entry={'name':'phase','probe':'out','quantity':'phase_deg','axis':'frequency_Hz',
                            'window':[doc['start'],doc['stop']],'minimum':-90,'maximum':0}
        doc['requirements']=[entry];validator=Draft202012Validator(adaptor.schema());validator.validate(doc)
        for changes in ({'minimum':-181},{'quantity':'currentMagnitude_A','minimum':-1}):
            bad=copy.deepcopy(doc);bad['requirements'][0].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValidationError):validator.validate(bad)
            with self.assertRaises(SchemaxisError):adaptor.plan(bad)
        for quantity,probe in [('activePower_W','out'),('impedanceMagnitude_Ohm','r1')]:
            bad=copy.deepcopy(doc);bad['requirements'][0].update(quantity=quantity,probe=probe)
            with self.assertRaises(SchemaxisError):adaptor.plan(bad)
        bad=copy.deepcopy(doc);bad['portMetrics']=False;bad['requirements'][0].update(probe='$input',quantity='activePower_W')
        with self.assertRaises(SchemaxisError):adaptor.plan(bad)


if __name__=='__main__':unittest.main()
