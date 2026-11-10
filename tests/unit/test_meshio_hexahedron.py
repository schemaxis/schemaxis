"""Independent first-order hexahedron admission and preservation controls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis.adaptors.meshio import adaptor, reference
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT/'examples/schemaxis/fixtures/meshio'


class MeshioHexahedronTests(unittest.TestCase):
    def setUp(self):
        self.mesh = reference.vtu((FIXTURES/'hex-affine.vtu').read_bytes())

    def test_literal_affine_and_warped_volumes(self):
        self.assertEqual(self.mesh['cells'], [['hexahedron',list(range(8))],['triangle',[0,1,2]],['tetra',[8,9,10,11]]])
        self.assertAlmostEqual(reference.summary(self.mesh)['hexahedronVolumes'][0],24)
        warped = reference.vtk((FIXTURES/'hex-warped.vtk').read_bytes())
        self.assertAlmostEqual(reference.summary(warped)['hexahedronVolumes'][0],.0255)
        self.assertEqual(warped['cellData']['region'],[[7],[9],[11]])
        for factor in (1e-6,1,1e6):
            scaled = reference.scaled(self.mesh,factor)
            self.assertAlmostEqual(reference.summary(scaled)['hexahedronVolumes'][0]/factor**3,24)

    def test_invalid_inverted_twisted_and_near_degenerate_hexes(self):
        inverted=copy.deepcopy(self.mesh);inverted['cells'][0][1]=[1,0,3,2,5,4,7,6]
        twisted=copy.deepcopy(self.mesh);twisted['cells'][0][1]=[0,1,2,3,4,6,5,7]
        flat=copy.deepcopy(self.mesh)
        for p in flat['points'][4:8]:p[2]=30+1e-13
        folded=copy.deepcopy(self.mesh);folded['points'][6][2]=29
        repeated=copy.deepcopy(self.mesh);repeated['cells'][0][1][-1]=6
        for label,mesh in [('inverted',inverted),('twisted',twisted),('thin',flat),('folded',folded),('repeated',repeated)]:
            with self.subTest(label=label),self.assertRaises(ValueError):reference.validate(mesh)

    def test_exact_node_order_and_sampled_jacobian_preservation(self):
        rotated=copy.deepcopy(self.mesh);rotated['cells'][0][1]=[1,2,3,0,5,6,7,4]
        reference.validate(rotated)
        with self.assertRaisesRegex(ValueError,'topology'):reference.compare(self.mesh,rotated)
        for p in self.mesh['points']:p[0]+=1e8
        changed=copy.deepcopy(self.mesh);changed['points'][6][0]+=.0001
        with self.assertRaisesRegex(ValueError,'Jacobian'):reference.compare(self.mesh,changed)

    def test_unsupported_high_order_and_voxel_are_explicit(self):
        source=(FIXTURES/'hex-affine.vtu').read_bytes()
        for code in (11,13,14,25):
            with self.subTest(code=code),self.assertRaisesRegex(ValueError,'only triangle/tetra/hexahedron'):
                reference.vtu(source.replace(b'>12 5 10<',('>'+str(code)+' 5 10<').encode()))

    def test_preflight_fault_before_native_assignment(self):
        source=(FIXTURES/'hex-affine.vtu').read_bytes().replace(b'>0 1 2 3 4 5 6 7 ',b'>0 1 2 3 4 6 5 7 ')
        document=json.loads((ROOT/'examples/schemaxis/meshio-hex-convert.json').read_text())
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);path=folder/'bad.vtu';path.write_bytes(source)
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.run({**document,'source':str(path)},folder/'run',executable='/usr/bin/python3')
            self.assertEqual(caught.exception.fault.code,'INVALID_MESH_CONTENT')
            self.assertFalse((folder/'run/native-worker.py').exists())


if __name__=='__main__':unittest.main()
