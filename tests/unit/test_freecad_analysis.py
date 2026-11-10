"""Independent elastic-element controls and typed physical-policy admission."""
import copy
import math
import tempfile
from pathlib import Path
import unittest
from schemaxis.adaptors.freecad import analysis
from schemaxis.adaptors.freecad.analysis_mesh import EDGES,volume_and_energy,face_weights,connectivity_key,verify_stress_field
from schemaxis.core.faults import SchemaxisError


def intent():
    return {'version':analysis.VERSION,'source':{'file':'bar.step','units':'mm','expect':{'volume':1/6,'bounds':[0,1,0,1,0,1],'centreOfMass':[.25]*3}},
        'material':{'youngModulusMPa':1000,'poissonRatio':0,'densityKgPerM3':2700},'mesh':{'sizeMM':1},
        'supports':[{'id':'clamp','face':{'face':'left'}}],'loads':[{'id':'pull','kind':'force','face':{'face':'right'},'forceN':[1,0,0]}]}


def tetra(order):
    nodes={1:[0.,0.,0.],2:[1.,0.,0.],3:[0.,1.,0.],4:[0.,0.,1.]}
    if order==2:
        for i,(a,b) in enumerate(EDGES,5):nodes[i]=[(x+y)/2 for x,y in zip(nodes[a+1],nodes[b+1])]
    return nodes,{1:list(nodes)}


class PhysicalPolicy(unittest.TestCase):
    def test_default_units_and_immutable_typed_intent(self):
        d=intent();before=copy.deepcopy(d);p=analysis.plan(d,unread=True)
        self.assertEqual(d,before);self.assertEqual(p['mesh']['order'],2)
        self.assertEqual(p['supports'][0]['displacementMM'],[0,0,0]);self.assertEqual(p['units']['stress'],'MPa')

    def test_impossible_or_undeclared_physics_refused(self):
        mutations=[lambda d:d['material'].update(poissonRatio=.5),lambda d:d['material'].update(youngModulusMPa=0),
            lambda d:d['mesh'].update(order=3),lambda d:d['mesh'].update(sizeMM=.001),lambda d:d.update(rawPython='x'),
            lambda d:d['supports'][0].update(displacementMM=[None]*3),lambda d:d['loads'][0].update(forceN=[0,0,0]),
            lambda d:d['loads'][0]['face'].update(offset=1),lambda d:d['loads'][0].update(id='clamp'),lambda d:d['source'].update(units='furlong')]
        for mutation in mutations:
            d=intent();mutation(d)
            with self.subTest(d=d),self.assertRaises(SchemaxisError):analysis.plan(d,unread=True)

    def test_nonzero_displacement_and_signed_pressure_are_intent(self):
        d=intent();d['supports'][0]['displacementMM']=[.1,None,0]
        d['loads']=[{'id':'pressure','kind':'pressure','face':{'face':'top'},'pressureMPa':-2}]
        p=analysis.plan(d,unread=True);self.assertEqual(p['loads'][0]['pressureMPa'],-2)


class ElasticControls(unittest.TestCase):
    def test_uniform_strain_in_rotated_skewed_tetrahedra(self):
        for order in (1,2):
            nodes,cells=tetra(order)
            # Affine geometry with nontrivial off-diagonal Jacobian exercises the
            # inverse-transpose gradient, independently of an axis-aligned bar.
            nodes={n:[2*x+y+4,y+z-3,z+7] for n,(x,y,z) in nodes.items()}
            u={n:[.01*x,0.,0.] for n,(x,y,z) in nodes.items()}
            result=volume_and_energy(nodes,cells,u,{'youngModulusMPa':1000,'poissonRatio':0})
            self.assertAlmostEqual(result['meshVolumeMM3'],1/3)
            self.assertAlmostEqual(result['maxVonMisesMPa'],10)
            self.assertAlmostEqual(result['strainEnergyNMM'],.5*1000*.01**2/3)

    def test_quadratic_displacement_has_exact_quadratic_energy_integral(self):
        nodes,cells=tetra(2);u={n:[x*x,0.,0.] for n,(x,y,z) in nodes.items()}
        result=volume_and_energy(nodes,cells,u,{'youngModulusMPa':1000,'poissonRatio':0})
        # epsilon_xx=2x; integral_tetra(x²)=1/60.
        self.assertAlmostEqual(result['strainEnergyNMM'],2000/60)

    def test_quadratic_constant_traction_uses_midsides_and_zero_corner_weights(self):
        for order in (1,2):
            nodes,cells=tetra(order);weights,area,sides=face_weights(nodes,cells,{'normal':[0,0,-1],'centre':[1/3,1/3,0],'area':.5})
            self.assertAlmostEqual(area,.5);self.assertEqual(sides,[(1,1)]);self.assertAlmostEqual(sum(weights.values()),.5)
            for n in (1,2,3):self.assertAlmostEqual(weights[n],0 if order==2 else 1/6)
            resultant=[sum(nodes[n][j]*w for n,w in weights.items()) for j in range(3)]
            self.assertEqual(resultant,[1/6,1/6,0])

    def test_poisson_coupling_under_uniaxial_stress(self):
        nodes,cells=tetra(2);u={n:[.01*x,-.003*y,-.003*z] for n,(x,y,z) in nodes.items()}
        result=volume_and_energy(nodes,cells,u,{'youngModulusMPa':1000,'poissonRatio':.3})
        self.assertAlmostEqual(result['maxVonMisesMPa'],10);self.assertAlmostEqual(result['strainEnergyNMM'],.5*10*.01/6)

    def test_orientation_permutation_preserves_edge_midside_ownership(self):
        original=[1,2,3,4,5,6,7,8,9,10]
        reversed_orientation=[2,1,3,4,5,7,6,9,8,10]
        self.assertEqual(connectivity_key(original),connectivity_key(reversed_orientation))
        reversed_orientation[4],reversed_orientation[5]=reversed_orientation[5],reversed_orientation[4]
        self.assertNotEqual(connectivity_key(original),connectivity_key(reversed_orientation))

    def test_constitutive_stress_field_rejects_consistently_zeroed_cache(self):
        nodes,cells=tetra(2);u={n:[.01*x,0,0] for n,(x,y,z) in nodes.items()};material={'youngModulusMPa':1000,'poissonRatio':0}
        verify_stress_field(nodes,cells,u,material,{n:[10,0,0,0,0,0] for n in nodes})
        with self.assertRaises(SchemaxisError):verify_stress_field(nodes,cells,u,material,{n:[0]*6 for n in nodes})

    def test_inverted_cells_and_curved_midsides_refused(self):
        for kind in ('inverted','curved'):
            nodes,cells=tetra(2)
            if kind=='inverted':nodes={n:[-x,y,z] for n,(x,y,z) in nodes.items()}
            else:nodes[5][2]=.01
            with self.subTest(kind=kind),self.assertRaises(SchemaxisError):volume_and_energy(nodes,cells,{n:[0,0,0] for n in nodes},{'youngModulusMPa':1000,'poissonRatio':0})



class VerificationBudget(unittest.TestCase):
    def test_long_mesh_and_solver_reads_poll_the_shared_deadline(self):
        from unittest.mock import patch
        from schemaxis.adaptors.freecad.analysis_mesh import boundary_faces
        from schemaxis.adaptors.freecad.analysis_results import read_text
        from schemaxis.errors import fail
        nodes,cells=tetra(2);u={n:[0,0,0] for n in nodes};material={'youngModulusMPa':1000,'poissonRatio':0}
        operations=[lambda:volume_and_energy(nodes,cells,u,material),lambda:verify_stress_field(nodes,cells,u,material,{n:[0]*6 for n in nodes}),lambda:boundary_faces(cells)]
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'solver.dat';p.write_text('0')
            operations.append(lambda:read_text(p))
            for operation in operations:
                with self.subTest(operation=operation),patch('schemaxis.dispatch.remaining_timeout',side_effect=lambda:fail('RUNNER_TIMED_OUT','expired verification budget')):
                    with self.assertRaises(SchemaxisError) as error:operation()
                    self.assertEqual(error.exception.fault.code,'RUNNER_TIMED_OUT')


class SolverDeckPolicy(unittest.TestCase):
    def test_dof_foreign_nodes_and_physical_modifiers_are_closed(self):
        from schemaxis.adaptors.freecad.analysis_results import deck
        text='*NODE,NSET=Nall\n1,0,0,0\n2,1,0,0\n3,0,1,0\n4,0,0,1\n*ELEMENT,TYPE=C3D4,ELSET=allcells\n1,1,2,3,4\n*MATERIAL,NAME=solid\n*ELASTIC\n1000,0\n*SOLID SECTION,ELSET=allcells,MATERIAL=solid\n*BOUNDARY\n1,1,3,0\n*STEP\n*STATIC\n*CLOAD\n2,3,1\n*END STEP\n'
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'mesh.inp';p.write_text(text);self.assertEqual(deck(p)['forces'][2],[0,0,1])
            for old,new in [('2,3,1','2,0,1'),('2,3,1','2,4,1'),('2,3,1','99,3,1'),('*ELASTIC','*ELASTIC,TYPE=ORTHO'),('*CLOAD','*CLOAD,OP=NEW')]:
                p.write_text(text.replace(old,new))
                with self.subTest(new=new),self.assertRaises(SchemaxisError):deck(p)


if __name__=='__main__':unittest.main()
