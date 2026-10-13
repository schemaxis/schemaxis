"""Closed physical intent, measured acceptance and trusted launch contracts."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.calculix import adaptor as app,beam
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]


def fixture():
    return json.loads((ROOT/'examples/schemaxis/calculix-beam.json').read_text())


def dat(prepared,stage='fine'):
    """Analytic contract double, never a native qualification witness."""
    mesh = beam.model(prepared,stage); L,b,h = (prepared['beam'][k] for k in ('length_m','width_m','height_m'))
    F = prepared['load']['tipForceZ_N']; nx,ny,nz = mesh['cells']; points = []
    lines = ['S T E P       1','INCREMENT     1','displacements (vx,vy,vz) for set TIP and time 1']
    lines += [f"{i} 0 0 {prepared['theory']['tipDeflection_m']:.17g}" for i in mesh['tipWeights']]
    lines += ['forces (fx,fy,fz) for set ROOT and time 1']
    sum_z2 = sum(mesh['nodes'][i][2]**2 for i in mesh['root'])
    for i in mesh['root']:
        lines.append(f"{i} {F*L*mesh['nodes'][i][2]/sum_z2:.17g} 0 {-F/len(mesh['root']):.17g}")
    lines += ['global coordinates (elem, integ.pnt.,x,y,z) for set ALL and time 1']
    for i,element in enumerate(mesh['elements'],1):
        ix,iy,iz = element['cell']
        # Explicit nested order reflects measured2.23 output: x fastest, z slowest.
        for z_sign in (-1,1):
            for y_sign in (-1,1):
                for x_sign in (-1,1):
                    j = (z_sign+1)*2+(y_sign+1)+(x_sign+1)//2+1
                    x = (ix+.5+x_sign/(2*math.sqrt(3)))*L/nx
                    y = (iy+.5+y_sign/(2*math.sqrt(3)))*b/ny-b/2
                    z = (iz+.5+z_sign/(2*math.sqrt(3)))*h/nz-h/2
                    points.append((i,j,x,y,z));lines.append(f'{i} {j} {x:.17g} {y:.17g} {z:.17g}')
    lines += ['stresses (elem, integ.pnt.,sxx,syy,szz,sxy,sxz,syz) for set ALL and time 1']
    lines += [f"{i} {j} {-F*(L-x)*z/prepared['theory']['secondMoment_m4']:.17g} 0 0 0 0 0" for i,j,x,y,z in points]
    return '\n'.join(lines)+'\n'


class CalculiXTests(unittest.TestCase):
    def error(self,function,code):
        with self.assertRaises(SchemaxisError) as caught: function()
        self.assertEqual(caught.exception.fault.code,code)
        return caught.exception.fault

    def test_schema_examples_defaults_and_independent_theory(self):
        import jsonschema
        for name in ('','-material','-load','-mesh','-unmet'):
            document = json.loads((ROOT/f'examples/schemaxis/calculix-beam{name}.json').read_text())
            jsonschema.validate(document,app.schema());self.assertEqual(app.plan(document),app.plan(copy.deepcopy(document)))
        planned = app.plan(fixture())
        self.assertAlmostEqual(planned['theory']['secondMoment_m4'],1.3333333333333334e-8)
        self.assertAlmostEqual(planned['theory']['tipDeflection_m'],-.0007619047619047619)
        self.assertAlmostEqual(planned['theory']['engineeringRootStress_Pa'],30e6)
        document = fixture();del document['mesh'];self.assertEqual(app.plan(document)['mesh'],{'lengthCells':12,'sectionCells':2})

    def test_invalid_physics_precedes_native_launch(self):
        for key,value in [('beam',{'length_m':.1,'width_m':.02,'height_m':.02}),('load',{'tipForceZ_N':0}),('load',{'tipForceZ_N':1e8})]:
            document = fixture();document[key]=value
            with patch.object(app,'execute') as native:
                self.error(lambda:app.run(document,'/unused',executable='/unused/ccx'),'INVALID_BEAM')
                native.assert_not_called()

    def test_closed_nested_schema_and_nonfinite_input(self):
        document = fixture();document['commands']=['*INCLUDE']
        self.error(lambda:app.plan(document),'UNKNOWN_ARGUMENT')
        document = fixture();document['beam']['x']=0
        self.error(lambda:app.plan(document),'UNKNOWN_ARGUMENT')
        for value in (True,float('nan'),float('inf'),[],None):
            document = fixture();document['load']['tipForceZ_N']=value
            self.error(lambda:app.plan(document),'INVALID_ARGUMENT')
        document = fixture();document['requirements'].append(copy.deepcopy(document['requirements'][0]))
        self.error(lambda:app.plan(document),'INVALID_REQUIREMENT')

    def test_consistent_face_load_integrals_and_mesh_counts(self):
        prepared = app.plan(fixture());mesh = beam.model(prepared,'fine')
        self.assertEqual((len(mesh['nodes']),len(mesh['elements'])),(2225,384))
        self.assertAlmostEqual(sum(mesh['tipWeights'].values()),1)
        self.assertAlmostEqual(sum(mesh['nodes'][i][1]*w for i,w in mesh['tipWeights'].items()),0)
        self.assertAlmostEqual(sum(mesh['nodes'][i][2]*w for i,w in mesh['tipWeights'].items()),0)
        self.assertTrue(any(w<0 for w in mesh['tipWeights'].values()))
        self.assertEqual(beam.deck(prepared,'fine'),beam.deck(prepared,'reopened'))
        self.assertIn(b'ROOT,1,3\n',beam.deck(prepared,'coarse'))
        largest = fixture();largest['mesh']={'lengthCells':24,'sectionCells':3}
        mesh = beam.model(app.plan(largest),'fine')
        self.assertEqual((len(mesh['nodes']),len(mesh['elements'])),(8869,1728))

    def test_independent_gauss_coordinates_signs_and_moments(self):
        prepared = app.plan(fixture());mesh = beam.model(prepared,'coarse')
        parsed = beam.parse_dat(dat(prepared,'coarse'),mesh)
        # Literal native2.23 first-element positions from official binary, rounded
        # at its documented text precision, independent of generator order.
        for point,xyz in [(1,[.007044162,-.007886751,-.007886751]),(2,[.02628917,-.007886751,-.007886751]),(3,[.007044162,-.002113249,-.007886751]),(5,[.007044162,-.007886751,-.002113249])]:
            for actual,expected in zip(parsed['COORD'][(1,point)],xyz):self.assertAlmostEqual(actual,expected,places=8)
        for force in (-100,50):
            document = fixture();document['load']['tipForceZ_N']=force
            planned = app.plan(document);native,rows = beam.assess(planned,'fine',dat(planned))
            self.assertAlmostEqual(native['rootReaction_N'][2],-force)
            self.assertAlmostEqual(native['rootMomentAboutClampCentre_Nm'][1],.4*force)
            self.assertAlmostEqual(native['tipAreaMeanDisplacement_m'][2],force*7.619047619047619e-6)
            self.assertLess(native['interiorStressScaledError'],1e-12)
            self.assertEqual(len(rows),1280)

    def test_parser_rejects_duplicate_missing_malformed_point_and_time(self):
        prepared = app.plan(fixture());mesh = beam.model(prepared,'fine');text = dat(prepared)
        lines = text.splitlines();point_header = next(i for i,v in enumerate(lines) if v.startswith('global coordinates'))
        stress_header = next(i for i,v in enumerate(lines) if v.startswith('stresses'))
        for changed in [text.replace('and time 1','and time 2',1), '\n'.join(lines[:point_header+2]+[lines[point_header+1]]+lines[point_header+2:]),'\n'.join(lines[:point_header+1]+lines[point_header+2:]),'\n'.join(lines[:stress_header+1]+[lines[stress_header+1]+' 0']+lines[stress_header+2:])]:
            self.error(lambda:beam.parse_dat(changed,mesh),'VERIFICATION_FAILED')
        self.error(lambda:beam.parse_dat(text.replace('and time 1','and time invalid',1),mesh),'VERIFICATION_FAILED')
        changed = lines.copy();changed[2+1]=changed[2+1].replace(' 0 ',' invalid ',1)
        self.error(lambda:beam.parse_dat('\n'.join(changed),mesh),'VERIFICATION_FAILED')

    def test_measured_geometry_stress_and_force_tamper_rejected(self):
        prepared = app.plan(fixture());lines = dat(prepared).splitlines()
        for header,column in [('global coordinates',2),('stresses',2),('forces',3)]:
            changed = list(lines);index = next(i for i,v in enumerate(changed) if v.startswith(header))+1
            if header=='stresses':
                while float(changed[index].split()[2])==0:index+=1
                # Apply all stress rows so an interior witness changes too.
                for i in range(index,len(changed)):
                    row = changed[i].split();row[2]=str(float(row[2])*2);changed[i]=' '.join(row)
            else:
                row = changed[index].split();row[column]=str(float(row[column])+1);changed[index]=' '.join(row)
            code = 'NUMERICAL_ACCEPTANCE_FAILED' if header=='stresses' else 'VERIFICATION_FAILED'
            self.error(lambda:beam.assess(prepared,'fine','\n'.join(changed)),code)

    def test_native_measurement_drives_requirement_margin(self):
        prepared = app.plan(fixture());native,_ = beam.assess(prepared,'fine',dat(prepared))
        measured = copy.deepcopy(native);measured['tipAreaMeanDisplacement_m'][2]=-.0009
        summary = app.assessment(prepared,{'fine':measured})
        self.assertFalse(summary['accepted']);self.assertAlmostEqual(summary['requirements'][0]['margin'],-.0001)
        self.assertEqual(summary['requirements'][0]['observed'],.0009)

    def test_launch_hash_blocks_changed_deck_before_owned_exec(self):
        prepared = app.plan(fixture())
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp);deck = beam.deck(prepared,'fine');(p/'beam.inp').write_bytes(deck+b'** changed\n')
            command = app.command('/does/not/exist','fine',prepared)
            result = subprocess.run(command,cwd=p,capture_output=True,timeout=3)
            self.assertNotEqual(result.returncode,0);self.assertIn(b'deck differs from trusted binding',result.stderr)
            self.assertEqual(command[-1],hashlib.sha256(deck).hexdigest())

    def test_bounded_regular_evidence_and_structured_verify_faults(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp);path = directory/'fifo'
            if hasattr(os,'mkfifo'):
                os.mkfifo(path);self.error(lambda:app.bounded(path),'VERIFICATION_FAILED')
            (directory/'result.json').write_text('null')
            self.error(lambda:app.verify(directory),'VERIFICATION_FAILED')
            (directory/'result.json').write_text('{"status":"failed","verified":false}')
            self.error(lambda:app.verify(directory),'INCOMPLETE_EXECUTION')

    def test_runtime_parameters_and_initial_write_faults_are_structured(self):
        for executable in (False,[],{},'/not/a/runtime','/invalid\x00runtime'):
            self.error(lambda:app.run(fixture(),'/unused',executable=executable),'INTERPRETER_NOT_FOUND')
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)/'regular';parent.write_text('not a directory')
            self.error(lambda:app.run(fixture(),parent/'attempt',executable=sys.executable),'OUTPUT_WRITE_FAILED')

    def test_internal_completion_mode_still_rejects_unmet_requirements(self):
        from schemaxis.artifacts import atomic_json
        document = fixture();planned = app.plan(document)
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp);atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',planned)
            atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
            atomic_json(directory/'version-submission.json',{'nativeCommand':app.command('/fixture/ccx','version')})
            expected = {'assessment':{'accepted':False,'requirements':[{'name':'tip_serviceability','margin':-.0001}]}}
            atomic_json(directory/'verification.json',expected)
            with patch.object(app,'checked_submission'),patch.object(app,'receipt',return_value=expected):
                self.error(lambda:app.verify(directory,require_result=False),'PERFORMANCE_NOT_MET')

    def test_public_query_analytic_and_resource_contract(self):
        from schemaxis.adaptors import registry
        document = fixture();document['load']['tipForceZ_N']={'$analytic':{'type':'values','values':[-100,-50]}}
        planned = app.plan(document);self.assertEqual(len(planned['visits']),2)
        self.assertEqual(registry.query(document)['adaptors'][0]['operations'],['cantileverBeam'])
        self.assertEqual(app.resources(fixture(),{},'beam'),{'threads':1})
        self.error(lambda:app.resources(fixture(),{'threads':2},'beam'),'INVALID_EXECUTION')


if __name__ == '__main__':unittest.main()
