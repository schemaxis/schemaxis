# Copyright (C) 2026 David L F Gaden
"""Host-only contracts and independent mesh corruption tests for Gmsh."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.gmsh import adaptor, mesh
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptor_conformance import host

ROOT = Path(__file__).resolve().parents[2]
TETRA = '''$MeshFormat
2.2 0 8
$EndMeshFormat
$PhysicalNames
2
2 2 "boundary"
3 1 "domain"
$EndPhysicalNames
$Nodes
4
1 0 0 0
2 1 0 0
3 0 1 0
4 0 0 1
$EndNodes
$Elements
5
1 2 2 2 1 1 2 3
2 2 2 2 1 1 2 4
3 2 2 2 1 1 3 4
4 2 2 2 1 2 3 4
5 4 2 1 1 1 2 3 4
$EndElements
'''


def document():
    return json.loads((ROOT/'examples/schemaxis/gmsh-minimal.json').read_text())


class GmshAdmissionTests(unittest.TestCase):
    def test_host_conformance(self):
        self.assertTrue(host(adaptor.VERSION)['verified'])

    def test_planning_rejects_execution_units_names_and_excessive_work(self):
        d = document(); before = copy.deepcopy(d)
        self.assertEqual(adaptor.plan(d), adaptor.plan(d)); self.assertEqual(d, before)
        edits = [('units','m'), ('script','print(1)'), ('output','solid')]
        for key, value in edits:
            bad = copy.deepcopy(d); bad[key] = value
            with self.subTest(key=key), self.assertRaises(SchemaxisError): adaptor.plan(bad)
        for key, value in [('size',0.001), ('volumeName','boundary'), ('boundaryName','bad\nname'), ('volumeTolerance',0.5), ('threads',8)]:
            bad = copy.deepcopy(d); bad['nodes'][1]['options'][key] = value
            with self.subTest(key=key), self.assertRaises(SchemaxisError): adaptor.plan(bad)
        bad = copy.deepcopy(d); bad['nodes'][0] = {'id':'solid','filter':'readSTEP','options':{'file':'relative.step'}}
        with self.assertRaises(SchemaxisError): adaptor.plan(bad)

    def test_independent_tetrahedron_volume_and_vtu_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'mesh.msh'; path.write_text(TETRA)
            data = mesh.read(path); observed = mesh.inspect(data)
            self.assertAlmostEqual(observed['volume'], 1/6)
            self.assertEqual(observed['bounds'], [0,0,0,1,1,1])
            for dim in (2,3):
                vtu = Path(temp)/f'{dim}.vtu'; mesh.write_vtu(vtu,data,dim); mesh.verify_vtu(vtu,data,dim)
                if dim == 3:
                    original = vtu.read_text()
                    vtu.write_text(original.replace('Name="meanRatio"', 'Name="wrongQuality"'))
                    with self.assertRaises(SchemaxisError): mesh.verify_vtu(vtu,data,dim)
                    vtu.write_text(original)
                vtu.write_text(vtu.read_text().replace('Name="physicalTag"','Name="wrong"'))
                with self.assertRaises(SchemaxisError): mesh.verify_vtu(vtu,data,dim)

    def test_reject_inverted_missing_boundary_and_unknown_physical_group(self):
        for text in [TETRA.replace('5 4 2 1 1 1 2 3 4','5 4 2 1 1 2 1 3 4'),
                     TETRA.replace('$Elements\n5', '$Elements\n4').replace('1 2 2 2 1 1 2 3\n',''),
                     TETRA.replace('5 4 2 1 1', '5 4 2 99 1'),
                     TETRA.replace('4 0 0 1', '4 0 0 nan'),
                     TETRA.replace('$EndNodes', '$EndWrong')]:
            with self.subTest(mesh=text), tempfile.TemporaryDirectory() as temp:
                path = Path(temp)/'mesh.msh'; path.write_text(text)
                with self.assertRaises(SchemaxisError): mesh.inspect(mesh.read(path))

    def test_missing_runtime_and_missing_evidence_are_structured(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.run(document(), Path(temp)/'absent', executable='/no-gmsh-python')
            self.assertEqual(caught.exception.fault.code,'INTERPRETER_NOT_FOUND')
            with self.assertRaises(SchemaxisError) as caught: adaptor.verify(temp)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')

    def test_absent_step_is_distinct_from_excessive_work(self):
        d = document(); d['nodes'][0] = {'id':'solid','filter':'readSTEP','options':{'file':'/missing-schemaxis-fixture.step'}}
        with self.assertRaises(SchemaxisError) as caught: adaptor.reusableInputs(d)
        self.assertEqual(caught.exception.fault.code,'RESOURCE_NOT_FOUND')

    def test_empty_native_exit_cannot_publish_success(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)/'run'
            with patch.object(adaptor, 'execute'), self.assertRaises(SchemaxisError):
                adaptor.run(document(), directory, executable='/bin/true')
            self.assertEqual(json.loads((directory/'result.json').read_text())['status'],'failed')

    def test_face_selection_contract_and_defaults(self):
        d = document()
        groups = [{'name':'fixed','axis':'x','coordinate':0}]
        d['nodes'][1]['options']['faceGroups'] = groups
        before = copy.deepcopy(d)
        effective = adaptor.plan(d)['nodes'][1]['options']['faceGroups']
        self.assertEqual(effective[0]['tolerance'],1e-6)
        self.assertEqual(d,before)
        for member, value in [('axis','normal'),('coordinate',float('nan')),
                              ('tolerance',0),('name','boundary'),('unexpected',1)]:
            bad = copy.deepcopy(d); bad['nodes'][1]['options']['faceGroups'][0][member] = value
            with self.subTest(member=member), self.assertRaises(SchemaxisError): adaptor.plan(bad)
        d['nodes'][1]['options']['faceGroups'].append({'name':'other','axis':'x','coordinate':1e-7})
        with self.assertRaises(SchemaxisError) as caught: adaptor.plan(d)
        self.assertEqual(caught.exception.fault.code,'INVALID_SELECTION')

    def test_independent_surface_area_and_wrong_face_assignment(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'mesh.msh'
            text = TETRA.replace('$PhysicalNames\n2','$PhysicalNames\n3').replace('3 1 "domain"','2 3 "fixed"\n3 1 "domain"')
            text = text.replace('1 2 2 2 1 1 2 3','1 2 2 3 1 1 2 3')
            path.write_text(text)
            data = mesh.read(path); result = mesh.inspect(data)
            self.assertAlmostEqual(result['boundaryGroups'][1]['area'],0.5)
            self.assertEqual(result['boundaryGroups'][1]['bounds'],[0,0,0,1,1,0])
            selectors = [{'name':'fixed','axis':'z','coordinate':0,'tolerance':1e-6}]
            mesh.verify_face_groups(data,selectors)
            # A valid mesh with valid physical IDs can still put a face in the wrong group.
            data['cells'][0] = (2,2,data['cells'][0][2])
            with self.assertRaises(SchemaxisError): mesh.verify_face_groups(data,selectors)


if __name__ == '__main__': unittest.main()
