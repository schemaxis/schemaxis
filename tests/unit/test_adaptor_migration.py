"""Preserved development migration and explicit gaps in the stronger completion gate."""
import tempfile
import unittest
from schemaxis.adaptors import registry
from schemaxis.adaptor_conformance import host
from schemaxis.capabilities import CapabilityCatalogue
from schemaxis.core.faults import SchemaxisError
from schemaxis.readiness import report


class AdaptorMigrationTests(unittest.TestCase):
    def test_every_installed_route_passes_development_admission_and_host_conformance(self):
        audit = report(admission=True)
        # Earlier migration qualified development materials, not the later
        # completion obligations. Keep those checks passing and new gaps visible.
        self.assertFalse(audit['structurallyComplete'])
        for row in audit['routes']:
            self.assertTrue(any(c['code'] == 'delivery.development' and c['status'] == 'pass' for c in row['checks']))
            self.assertEqual(row['runtimeAvailability'], 'unknown')
        for provider in ('gmsh', 'ngspice'):
            self.assertTrue(all(r['structural'] == 'complete' for r in audit['routes'] if r['provider'] == provider))
        self.assertTrue(any(c['code'] == 'discovery.acceptance' and c['status'] == 'unknown'
                            for row in audit['routes'] for c in row['checks']))
        for version in registry.routes():
            with self.subTest(version=version):
                self.assertTrue(host(version)['verified'])

    def test_native_catalogue_context_preserves_provenance_and_qualification_limits(self):
        catalogue = CapabilityCatalogue(['paraview'])
        metadata = catalogue._metadata['paraview']['operations']
        self.assertEqual(set(metadata), set(registry.declarations('paraview')))
        self.assertIn('sphere', metadata['pvSphere']['purpose'].lower())
        self.assertIn('installed native documentation', metadata['pvSphere']['semantics'][0])
        self.assertIn('does not establish native qualification', metadata['pvSphere']['semantics'][0])
        self.assertIn('no production', metadata['pvTest3DWidget']['purpose'])

    def test_old_verifier_entry_points_reject_missing_evidence_with_structured_faults(self):
        with tempfile.TemporaryDirectory() as directory:
            for version in ('schemaxis/1', 'schemaxis.blender/1', 'schemaxis.blender.render/1', 'schemaxis.aseprite/1'):
                with self.subTest(version=version):
                    with self.assertRaises(SchemaxisError) as error:
                        registry.verify(directory, {'version': version})
                    self.assertEqual(error.exception.fault.code, 'VERIFICATION_FAILED')


if __name__ == '__main__':
    unittest.main()
