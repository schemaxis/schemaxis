# Copyright (C) 2026 David L F Gaden
"""Closed circuit contracts and independent linear-circuit falsification tests."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.adaptor_conformance import host
from schemaxis.adaptors.ngspice import adaptor,circuit
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[2]


def document(name='minimal'):
    return json.loads((ROOT/f'examples/schemaxis/ngspice-{name}.json').read_text())


class NgspiceAdmissionTests(unittest.TestCase):
    def test_host_conformance(self):
        self.assertTrue(host(adaptor.VERSION)['verified'])

    def test_immutable_plans_reject_scripts_and_floating_circuits(self):
        d=document();before=copy.deepcopy(d)
        self.assertEqual(adaptor.plan(d),adaptor.plan(d));self.assertEqual(d,before)
        variants=[]
        bad=copy.deepcopy(d);bad['script']='quit';variants.append(bad)
        bad=copy.deepcopy(d);bad['circuit']['resistors'][0]['a']='in\n.control';variants.append(bad)
        bad=copy.deepcopy(d);bad['circuit']['resistors'][0]['resistance']=float('nan');variants.append(bad)
        bad=copy.deepcopy(d);bad['circuit']['resistors'][0]['name']='r2';variants.append(bad)
        bad=copy.deepcopy(d);bad['circuit']['resistors'].append({'name':'r3','a':'island','b':'other','resistance':100});variants.append(bad)
        bad=copy.deepcopy(d);bad['circuit']['probes']=['missing'];variants.append(bad)
        for bad in variants:
            with self.subTest(document=bad),self.assertRaises(SchemaxisError):adaptor.plan(bad)

    def test_sweep_and_transient_bounds(self):
        for name,key,value in [('minimal','stop',0),('rc-frequency','points',2),
                               ('rc-frequency','start',0),('rc-frequency','amplitude',0),
                               ('rc-step','stop',1),('rc-step','amplitude',0),('minimal','points',513)]:
            d=document(name);d[key]=value
            with self.subTest(name=name,key=key),self.assertRaises(SchemaxisError):adaptor.plan(d)
        d=document('rc-step');d['circuit']['capacitors'][0]['a']='in'
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(d)
        self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_CIRCUIT')

    def test_ac_table_width_and_unrepresentable_spacing_rejected_before_execution(self):
        d=document('rc-frequency')
        nodes=['in']+['n'+str(i) for i in range(15)]
        d['circuit'].update(probes=nodes,capacitors=[],resistors=[
            {'name':'r'+str(i),'a':'in','b':n,'resistance':1000} for i,n in enumerate(nodes[1:])])
        with self.assertRaises(SchemaxisError):adaptor.plan(d)
        d['circuit']['probes']=nodes[:15]
        self.assertEqual(len(adaptor.plan(d)['nodes']),16)
        d=document();d.update(start=1,stop=math.nextafter(1,math.inf),points=3)
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(d)
        self.assertEqual(caught.exception.fault.code,'INVALID_SWEEP')

    def test_divider_and_symmetric_bridge(self):
        p=adaptor.plan(document());v=circuit.voltages(p,6)
        self.assertAlmostEqual(v['out'].real,4)
        d=document();d['circuit']['resistors']=[{'name':'r'+str(i),'a':a,'b':b,'resistance':1000}
            for i,(a,b) in enumerate([('in','left'),('left','0'),('in','right'),('right','0'),('left','right')])]
        d['circuit']['probes']=['left','right'];v=circuit.voltages(adaptor.plan(d),6)
        self.assertAlmostEqual(v['left'].real,3);self.assertAlmostEqual(v['right'].real,3)
        with self.assertRaises(SchemaxisError):circuit.solve([[1,1],[2,2]],[1,2])

    def test_rc_complex_response_and_analytic_step(self):
        p=adaptor.plan(document('rc-frequency'));v=circuit.voltages(p,p['start'])['out']
        self.assertAlmostEqual(v.real,.5);self.assertAlmostEqual(v.imag,-.5)
        p=adaptor.plan(document('rc-step'))
        self.assertEqual(circuit.expected(p,0)['out'],0)
        self.assertAlmostEqual(circuit.expected(p,.001)['out'].real,5*(1-math.exp(-1)))

    def test_rl_and_rlc_transfer_functions(self):
        # Closed-form impedances are independent of the nodal stamping solver.
        for name in ('rl-frequency','rlc-resonance','rlc-parallel'):
            d=document(name);before=copy.deepcopy(d);p=adaptor.plan(d)
            self.assertEqual(d,before)
            for f in circuit.samples(p):
                x=2*math.pi*f/1000
                reference={'rl-frequency':1/(1+1j*x),
                           'rlc-resonance':1/(1-x*x+1j*x),
                           'rlc-parallel':1/(1+1j*(x-1/x))}[name]
                self.assertAlmostEqual(abs(circuit.voltages(p,f)['out']-reference),0,places=12)
        d=document('rlc-resonance');d['amplitude']=-2
        # Reversing an uncoupled ideal inductor leaves voltages unchanged.
        d['circuit']['inductors'][0].update(a='out',b='mid')
        p=adaptor.plan(d)
        self.assertAlmostEqual(abs(circuit.voltages(p,p['start'])['out']-2j),0,places=12)
        d['circuit']['inductors']=[
            {'name':'one','a':'mid','b':'tap','inductance':.25},
            {'name':'two','a':'tap','b':'out','inductance':.75}]
        p=adaptor.plan(d)
        for f in circuit.samples(p):
            x=2*math.pi*f/1000
            self.assertAlmostEqual(abs(circuit.voltages(p,f)['out']+2/(1-x*x+1j*x)),0,places=12)

    def test_inductor_schema_bounds_and_analysis_scope(self):
        import jsonschema
        jsonschema.validate(document('rl-frequency'),adaptor.schema())
        for operation in ('dcSweep','rcStep'):
            d=document('minimal' if operation=='dcSweep' else 'rc-step')
            d['circuit']['inductors']=[]
            with self.subTest(operation=operation):
                with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(d,adaptor.schema())
                with self.assertRaises(SchemaxisError):adaptor.plan(d)
        for field,value in [('inductance',0),('inductance',1e-10),('inductance',1001),
                            ('inductance',True),('inductance',float('inf')),
                            ('name','load'),('a','in\n.control'),('a','out')]:
            d=document('rl-frequency');d['circuit']['inductors'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(SchemaxisError):adaptor.plan(d)
        d=document('rl-frequency');d['circuit']['inductors']*=65
        with self.assertRaises(SchemaxisError):adaptor.plan(d)
        d=document('rl-frequency');p=adaptor.plan(d)
        self.assertIn('L_coil in out 1\n',adaptor.netlists(p)[0])

    def test_inductor_operating_point_loops_rejected(self):
        for extra in ([{'name':'other','a':'out','b':'in','inductance':1}],
                      [{'name':'other','a':'out','b':'0','inductance':1}],
                      [{'name':'other','a':'out','b':'tap','inductance':1},
                       {'name':'last','a':'tap','b':'in','inductance':1}]):
            d=document('rl-frequency');d['circuit']['inductors']+=extra
            with self.subTest(extra=extra),self.assertRaises(SchemaxisError) as caught:adaptor.plan(d)
            self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_CIRCUIT')

    def test_undamped_resonance_inside_sweep_rejected(self):
        d=document('rlc-parallel')
        # This unforced LC tank has a DC path through L, but loses its unique
        # AC solution at the middle sample. Endpoint-only checking misses it.
        d['circuit']['resistors'][0].update(a='in',b='0')
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(d)
        self.assertEqual(caught.exception.fault.code,'ILL_CONDITIONED_CIRCUIT')
        d['circuit']['resistors'].append({'name':'damping','a':'out','b':'0','resistance':1000})
        p=adaptor.plan(d)
        self.assertEqual(circuit.voltages(p,circuit.samples(p)[2])['out'],0)

    def test_rlc_complex_sign_and_internal_voltage_corruption_fail(self):
        p=adaptor.plan(document('rlc-resonance'));rows=[]
        for f in circuit.samples(p):
            values=circuit.expected(p,f);row=[f]
            for n in p['nodes']:row.extend([values[n].real,values[n].imag])
            rows.append(row)
        circuit.inspect(p,rows)
        for node in ('mid','out'):
            bad=copy.deepcopy(rows);bad[0][1+2*p['nodes'].index(node)]+=0.1
            with self.subTest(node=node),self.assertRaises(SchemaxisError):circuit.inspect(p,bad)
        bad=copy.deepcopy(rows);bad[0][2+2*p['nodes'].index('out')]*=-1
        with self.assertRaises(SchemaxisError):circuit.inspect(p,bad)

    def test_mismatched_phases_sample_coordinates_and_voltages_fail(self):
        p=adaptor.plan(document('rc-frequency'));rows=[]
        for f in circuit.samples(p):
            values=circuit.expected(p,f);row=[f]
            for n in p['nodes']:row.extend([values[n].real,values[n].imag])
            rows.append(row)
        circuit.inspect(p,rows)
        for column in range(len(rows[0])):
            bad=copy.deepcopy(rows);bad[0][column]+=1
            with self.subTest(column=column),self.assertRaises(SchemaxisError):circuit.inspect(p,bad)
        table=circuit.publication(p,rows)
        self.assertAlmostEqual(table['rows'][0][-1],-45)
        d=document();d.update(start=-5,stop=0,points=101);p=adaptor.plan(d)
        rows=[[axis]+[circuit.expected(p,axis)[n].real for n in p['nodes']] for axis in circuit.samples(p)]
        rows[-1][0]=-1e-14  # Typical accumulated native roundoff at zero.
        circuit.inspect(p,rows)
        rows[-1][0]=-1e-5
        with self.assertRaises(SchemaxisError):circuit.inspect(p,rows)

    def test_ascii_raw_parser_checks_indices_names_and_finite_values(self):
        d=document();d.update(points=2,stop=1);p=adaptor.plan(d)
        raw='Title: fixture\nFlags: real\nNo. Variables: 3\nNo. Points: 2\nVariables:\n0 v(v-sweep) voltage\n1 v(in) voltage\n2 v(out) voltage\nValues:\n0 0\n0\n0\n1 1\n1\n0.6666666666666667\n'
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'data.raw';path.write_text(raw)
            rows=circuit.read_raw(path,p);circuit.inspect(p,rows)
            for old,new in [('2 v(out)','2 v(wrong)'),('Values:\n0','Values:\n9'),('0.6666666666666667','nan')]:
                path.write_text(raw.replace(old,new))
                with self.subTest(old=old),self.assertRaises(SchemaxisError):circuit.read_raw(path,p)

    def test_netlist_is_deterministic_and_unsupported_runtime_fails(self):
        p=adaptor.plan(document('rc-step'));a,b=adaptor.netlists(p)
        self.assertIn('.ic v(out)=0',a);self.assertIn('load result.raw',b)
        self.assertEqual((a,b),adaptor.netlists(p))
        with self.assertRaises(SchemaxisError):adaptor.runtime('ngspice-46 : simulator')

    def test_missing_runtime_and_false_success(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SchemaxisError) as caught:adaptor.run(document(),Path(temp)/'missing',executable='/missing-ngspice')
            self.assertEqual(caught.exception.fault.code,'INTERPRETER_NOT_FOUND')
            directory=Path(temp)/'false'
            with patch.object(adaptor,'execute'),self.assertRaises(SchemaxisError):adaptor.run(document(),directory,executable='/bin/true')
            self.assertEqual(json.loads((directory/'result.json').read_text())['status'],'failed')


if __name__=='__main__':unittest.main()
