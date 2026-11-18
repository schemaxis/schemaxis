"""The extents contract: a declared, optional adaptor capability the framework knows nothing else about."""
import unittest

from schemaxis.adaptors import registry
from schemaxis.core.faults import SchemaxisError
from schemaxis.expressions import recorded_extents


class ExtentsContract(unittest.TestCase):
    def test_paraview_and_blender_declare_a_provider_and_discovery_reports_the_capability(self):
        providers = {item['id']: item for item in registry.discover()['providers']}
        for name in ('paraview', 'blender'):
            declared = registry.metadata(name)['extents']
            self.assertEqual(set(declared), {'setup', 'native'})
            for path in declared.values():
                self.assertTrue(path.startswith('schemaxis.adaptors.' + name + '.'))
                self.assertTrue(callable(registry.binding(path)))
            self.assertIs(providers[name]['authoring']['extents'], True)
        self.assertIs(providers['gmsh']['authoring']['extents'], False)
        self.assertNotIn('extents', registry.metadata('gmsh'))

    def test_a_manifest_names_both_bindings_inside_its_own_package(self):
        manifest = {'id': 'sample', 'version': 'schemaxis.sample/1',
                    'routes': {'schemaxis.sample/1': {'module': 'pkg.sample.adaptor', 'schema': 'pkg.sample.adaptor:schema'}}}
        claims = {'versions': set(), 'sections': set(), 'flags': set(), 'names': set()}
        for extents in ({'setup': 'pkg.sample.integration:extentsSetup'}, 'pkg.sample.integration:extents',
                        {'setup': 'pkg.sample.integration:extentsSetup', 'native': 'other.package:nativeExtents'}):
            with self.assertRaises(ValueError):
                registry._admit({**manifest, 'extents': extents}, 'sample', 'pkg.sample.', dict(claims))
        registry._admit({**manifest, 'extents': {'setup': 'pkg.sample.integration:extentsSetup',
                                                 'native': 'pkg.sample.integration:nativeExtents'}},
                        'sample', 'pkg.sample.', dict(claims))

    def test_readers_declare_that_they_load_data(self):
        paraview = registry.declarations('paraview')
        for name in ('foam', 'readSurface', 'pvLegacyVTKReader', 'pvXMLUnstructuredGridReader'):
            self.assertIs(paraview[name].get('loadsData'), True, name)
        for name in ('sphere', 'wavelet', 'slice', 'pvSphere', 'pvWriteCSVWriter'):
            self.assertNotIn('loadsData', paraview[name], name)
        blender = registry.declarations('blender')
        self.assertEqual(sorted(name for name, declaration in blender.items() if declaration.get('loadsData')),
                         ['readGltf', 'readPLY', 'readSTL'])

    def test_blender_refuses_an_unqualified_release_before_starting_it(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from schemaxis.adaptors.blender import integration
        from schemaxis.core.runners import Interpreter
        document = {'version': 'schemaxis.blender/1', 'nodes': [{'id': 'paint', 'filter': 'material'}]}
        with patch.object(Interpreter, 'probe', return_value=SimpleNamespace(version='4.5.14')):
            with self.assertRaises(SchemaxisError) as caught:
                integration.extentsSetup(document, {'blender': 'blender'})
        self.assertEqual((caught.exception.fault.code, caught.exception.fault.observed),
                         ('UNSUPPORTED_RUNTIME', {'version': '4.5.14'}))
        qualified = SimpleNamespace(version='5.2.3')
        with patch.object(Interpreter, 'probe', return_value=qualified):
            self.assertIs(integration.extentsSetup(document, {'blender': 'blender'})[1], qualified)

    def test_a_provider_reports_six_numbers_empty_or_not_spatial_for_each_port(self):
        self.assertEqual(recorded_extents([{'status': 'ok', 'bounds': [0, 1, 0, 2, 0, 3]}, {'status': 'empty'},
                                           {'status': 'notSpatial'}]),
                         [[0, 1, 0, 2, 0, 3], [1, -1, 1, -1, 1, -1], None])
        for result in ({'status': 'ok', 'bounds': [0, 1, 0, 2, 0]}, {'status': 'ok', 'bounds': [0, 1, 0, 2, 0, float('inf')]},
                       {'status': 'unknown'}, [0, 1, 0, 2, 0, 3]):
            with self.assertRaises(SchemaxisError) as caught:
                recorded_extents([result])
            self.assertEqual(caught.exception.fault.code, 'INVALID_EXTENTS')


if __name__ == '__main__':
    unittest.main()
