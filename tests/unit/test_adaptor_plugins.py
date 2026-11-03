# Copyright (C) 2026 David L F Gaden
"""External adaptor packages register through the schemaxis.adaptors entry-point group."""
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings
import zipfile

from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors import registry
from schemaxis.adaptors.registry import load_registry

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT/'tests/fixtures/plugin_adaptor'
PACKAGE = 'schemaxis_fixture_plugin'


def entry(name, value=PACKAGE, dist='schemaxis-fixture-plugin'):
    return SimpleNamespace(name=name, value=value, group=registry.GROUP, dist=SimpleNamespace(name=dist))


def install(site, name, package, dist='schemaxis-fixture-plugin'):
    """A minimal dist-info entry point, as pip would leave it."""
    info = site/(dist.replace('-', '_') + '-0.1.0.dist-info')
    info.mkdir(parents=True)
    (info/'METADATA').write_text('Metadata-Version: 2.1\nName: ' + dist + '\nVersion: 0.1.0\n')
    (info/'entry_points.txt').write_text('[schemaxis.adaptors]\n' + name + ' = ' + package + '\n')


def fresh(script, *args, path=(), isolated=False):
    """Run ``script`` in a new interpreter; ``isolated`` drops site-packages and PYTHONPATH."""
    environment = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(ROOT/'src'), *map(str, path)])}
    environment.pop('SCHEMAXIS_ADAPTOR_PLUGINS', None)
    command = [sys.executable, *(['-I', '-S'] if isolated else []), '-c', script, *map(str, args)]
    return subprocess.run(command, env=environment, cwd=args[0] if args else None,
                          capture_output=True, text=True, timeout=180)


class AdaptorPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.packages = Path(cls._tmp.name)
        sys.path.insert(0, str(FIXTURES))
        sys.path.insert(0, str(cls.packages))
        cls.builtins = load_registry(plugins=[])
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        for path in (str(FIXTURES), str(cls.packages)):
            if path in sys.path: sys.path.remove(path)
        cls._tmp.cleanup()

    def variant(self, change=None, init=None):
        """A uniquely named copy of the fixture package, optionally edited."""
        type(self).counter += 1
        name = PACKAGE + '_v' + str(self.counter)
        target = self.packages/name
        shutil.copytree(FIXTURES/PACKAGE, target, ignore=shutil.ignore_patterns('__pycache__'))
        manifest = json.loads((target/'adaptor.json').read_text())
        if change: change(manifest)
        (target/'adaptor.json').write_text(json.dumps(manifest).replace(PACKAGE + '.', name + '.'))
        if init is not None: (target/'__init__.py').write_text(init)
        return name

    @contextmanager
    def registered(self, **items):
        """Plugins admitted into the live registry, restored with its faults afterwards."""
        with patch.dict(registry.ADAPTORS, items), patch.object(registry, 'PLUGIN_FAULTS', []), \
                patch.object(registry, '_EXCLUDED', {}), warnings.catch_warnings():
            warnings.simplefilter('ignore', registry.AdaptorPluginWarning)
            yield

    def admitted(self, change=None, identity='fixtureplugin'):
        name = self.variant(change)
        return load_registry(plugins=[entry(identity, name)], strict=True)[identity]

    def fault(self, plugins):
        with self.assertRaises(SchemaxisError) as caught:
            load_registry(plugins=plugins, strict=True)
        self.assertEqual(caught.exception.fault.code, 'INVALID_ADAPTOR')
        found = []
        result = load_registry(plugins=plugins, faults=found)
        self.assertEqual(set(result), set(self.builtins), 'built-ins remain usable and the plugin is excluded')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].code, 'INVALID_ADAPTOR')
        return found[0]

    def test_registry_loads_plugin_from_entry_point_lookup(self):
        with patch.object(registry, 'plugin_entry_points', return_value=[entry('fixtureplugin')]):
            result = load_registry(strict=True)
        item = result['fixtureplugin']
        self.assertEqual((item['package'], item['source']), (PACKAGE, 'plugin:schemaxis-fixture-plugin'))
        self.assertEqual(item['adaptor'], PACKAGE + '.adaptor')
        self.assertEqual(item['declarations'], PACKAGE + '.adaptor:DECLARATIONS')
        self.assertEqual(registry.binding(item['declarations'])['emit']['id'], 'emit')
        for name, builtin in self.builtins.items():
            self.assertEqual(result[name], builtin)
            self.assertEqual(builtin['source'], 'builtin')
            self.assertEqual(builtin['package'], 'schemaxis.adaptors.' + name)

    def test_plugins_can_be_disabled_and_are_off_for_explicit_empty_lists(self):
        with patch.dict(os.environ, {'SCHEMAXIS_ADAPTOR_PLUGINS': 'off'}), \
                patch.object(registry, 'plugin_entry_points', side_effect=AssertionError('lookup must be skipped')):
            self.assertEqual(set(load_registry()), set(self.builtins))
        self.assertEqual(set(load_registry(plugins=[])), set(self.builtins))

    def test_resource_helpers_resolve_plugin_and_builtin_packages(self):
        item = load_registry(plugins=[entry('fixtureplugin')], strict=True)['fixtureplugin']
        with patch.dict(registry.ADAPTORS, {'fixtureplugin': item}):
            self.assertEqual(registry.adaptor_package('fixtureplugin'), PACKAGE)
            self.assertTrue(registry.adaptor_files('fixtureplugin').joinpath('adaptor.json').is_file())
            self.assertEqual(registry.adaptor_source('fixtureplugin', 'readiness.json'), PACKAGE + '/readiness.json')
            self.assertEqual(list(registry.routes())[-1], 'fixtureplugin/1', 'plugin routes follow built-ins')
        self.assertEqual(registry.adaptor_package('gmsh'), 'schemaxis.adaptors.gmsh')
        self.assertTrue(registry.adaptor_files('gmsh').joinpath('adaptor.json').is_file())
        self.assertTrue(registry.adaptor_files('workflow').joinpath('guidance.json').is_file())
        self.assertEqual(registry.adaptor_source('gmsh', 'guidance.json'), 'src/schemaxis/adaptors/gmsh/guidance.json')
        with self.assertRaises(SchemaxisError):
            registry.adaptor_files('../schemaxis')

    def test_delivery_links_resolve_in_the_plugin_checkout(self):
        from schemaxis.readiness import repository_root
        checkout = self.packages/'checkout'
        (checkout/'docs').mkdir(parents=True)
        (checkout/'pyproject.toml').write_text('[project]\nname = "fixture"\n')
        name = self.variant()
        (checkout/'src').mkdir()
        shutil.move(str(self.packages/name), str(checkout/'src'/name))
        sys.path.insert(0, str(checkout/'src'))
        self.addCleanup(sys.path.remove, str(checkout/'src'))
        item = load_registry(plugins=[entry('fixtureplugin', name)], strict=True)['fixtureplugin']
        installed = load_registry(plugins=[entry('fixtureplugin')], strict=True)['fixtureplugin']
        with patch.dict(registry.ADAPTORS, {'fixtureplugin': item}):
            self.assertEqual(repository_root('fixtureplugin'), checkout.resolve())
        with patch.dict(registry.ADAPTORS, {'fixtureplugin': installed}):
            self.assertIsNone(repository_root('fixtureplugin'), 'no source checkout, as for an installed wheel')
        self.assertEqual(repository_root('gmsh'), repository_root())

    def test_id_collision_with_builtin_names_both_sources(self):
        name = self.variant(lambda m: m.update(id='gmsh'))
        fault = self.fault([entry('gmsh', name)])
        self.assertIn('builtin', fault.message)
        self.assertEqual(list(fault.observed['sources']), ['builtin', 'plugin:schemaxis-fixture-plugin'])

    def test_id_collision_between_plugins_excludes_both(self):
        plugins = [entry('fixtureplugin', dist='first-dist'), entry('fixtureplugin', self.variant(), dist='second-dist')]
        fault = self.fault(plugins)
        self.assertEqual(list(fault.observed['sources']), ['plugin:first-dist', 'plugin:second-dist'])

    def test_entry_point_name_must_match_manifest_id(self):
        fault = self.fault([entry('otherplugin')])
        self.assertIn('does not match manifest id', fault.message)

    def test_bindings_may_not_escape_the_plugin_package(self):
        def builtin(manifest): manifest['routes']['fixtureplugin/1']['module'] = 'schemaxis.adaptors.gmsh.adaptor'
        def sibling(manifest): manifest['capabilities'] = PACKAGE + 'x.capabilities:catalogue'
        def validation(manifest): manifest['documentValidation'] = 'schemaxis.workflow_authoring:validate'
        for change in (builtin, sibling, validation):
            with self.subTest(change=change.__name__):
                fault = self.fault([entry('fixtureplugin', self.variant(change))])
                self.assertIn('bindings must belong', fault.message)

    def test_versions_defaults_namespace_and_display_are_checked(self):
        def version(manifest):
            manifest['version'] = 'schemaxis.gmsh/1'
            manifest['routes'] = {'schemaxis.gmsh/1': manifest['routes']['fixtureplugin/1']}
        def default(manifest): manifest['default'] = True
        def display(manifest): manifest['display'] = {'name': 'Fixture', 'colour': 'blue'}
        for change in (version, default, display):
            with self.subTest(change=change.__name__):
                self.fault([entry('fixtureplugin', self.variant(change))])
        self.fault([entry('gmsh', 'schemaxis.adaptors.gmsh')])
        self.fault([entry('fixtureplugin', 'schemaxis_fixture_plugin:attribute')])

    def test_framework_identities_are_reserved(self):
        def route(version):
            def change(manifest):
                manifest['version'] = version
                manifest['routes'] = {version: manifest['routes']['fixtureplugin/1']}
            change.__name__ = version
            return change
        def schema_name(manifest): manifest['routes']['fixtureplugin/1']['schemaName'] = 'workflow'
        def section(manifest): manifest['sections'] = {'camera': PACKAGE + '.adaptor:schema'}
        def shared_name(manifest): manifest['routes']['fixtureplugin/1']['schemaName'] = 'assembly'
        def packages(manifest): manifest['runtimePackages'] = ['../outside']
        changes = [route(v) for v in ('schemaxis.workflow/1', 'schemaxis.workflow-design/3', 'schemaxis.study/1',
                                      'schemaxis.plan/9', 'schemaxis.gmsh/2', 'schemaxis/2', 'schemaxis.fixturepluginx/1')]
        for change in changes + [schema_name, section, shared_name, packages]:
            with self.subTest(change=change.__name__):
                self.fault([entry('fixtureplugin', self.variant(change))])
        for identity in ('workflow', 'fixture_geo'):
            with self.subTest(identity=identity):
                fault = self.fault([entry(identity, self.variant(lambda m: m.update(id=identity)))])
                self.assertIn('reserved', fault.message)
        for version in ('schemaxis.fixtureplugin/2', 'schemaxis.fixtureplugin.extra/1', 'acme.fixture/1'):
            with self.subTest(allowed=version):
                self.assertIn(version, self.admitted(route(version))['routes'])

    def test_stale_cache_folder_does_not_reserve_an_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'fixtureplugin' / '__pycache__').mkdir(parents=True)
            (root / 'occupied').mkdir()
            (root / 'occupied' / '__init__.py').write_text('')
            name = self.variant()
            result = load_registry(root=root, plugins=[entry('fixtureplugin', name)], strict=True)
            self.assertEqual(result['fixtureplugin']['source'], 'plugin:schemaxis-fixture-plugin')
            occupied = self.variant(lambda m: m.update(id='occupied'))
            with self.assertRaises(SchemaxisError) as caught:
                load_registry(root=root, plugins=[entry('occupied', occupied)], strict=True)
            self.assertIn('reserved', caught.exception.fault.message)

    def test_cli_options_may_not_collide(self):
        def option(**fields):
            def change(manifest): manifest['cliOptions'] = [{'flag': '--fixture', 'dest': 'fixtureplugin',
                                                              'help': 'Fixture launcher', **fields}]
            change.__name__ = repr(fields)
            return change
        cases = [option(flag='--executable'), option(flag='--gmsh', dest='fixture'), option(flag='--help'),
                 option(dest='roots'), option(dest='gmsh'), option(dest='command'), option(dest='output_directory'),
                 option(type='int'), option(action='help'), option(flag='-f'), option(dest='not-an-identifier')]
        for change in cases:
            with self.subTest(change=change.__name__):
                self.fault([entry('fixtureplugin', self.variant(change))])
        self.assertEqual(self.admitted(option())['cliOptions'][0]['flag'], '--fixture')
        def other(manifest):
            manifest.update(id='otherplugin', version='otherplugin/1')
            manifest['routes'] = {'otherplugin/1': manifest['routes']['fixtureplugin/1']}
            option()(manifest)
        found = []
        result = load_registry(plugins=[entry('fixtureplugin', self.variant(option())),
                                        entry('otherplugin', self.variant(other), dist='other-dist')], faults=found)
        self.assertIn('fixtureplugin', result, 'the first plugin in ID order keeps its flag')
        self.assertNotIn('otherplugin', result)
        self.assertIn("collides with adaptor 'fixtureplugin'", found[0].message)
        found = []
        result = load_registry(plugins=[entry('roots', self.variant(lambda m: m.update(id='roots')))], faults=found)
        self.assertNotIn('roots', result, 'an adaptor ID is a location key shared with cliOptions dests')

    def test_reserved_cli_names_cover_the_framework_parsers(self):
        from schemaxis.__main__ import build_parser
        adaptor = {o['flag'] for item in registry.ADAPTORS.values() for o in item.get('cliOptions', [])}
        dests = {o['dest'] for item in registry.ADAPTORS.values() for o in item.get('cliOptions', [])}
        commands = next(a for a in build_parser()._actions if a.dest == 'command')
        for name in ('run', 'inspect', 'console'):
            for action in commands.choices[name]._actions:
                flags = set(action.option_strings) - adaptor
                if flags:
                    self.assertLessEqual(flags, registry.FRAMEWORK_FLAGS, name)
                    self.assertIn(action.dest, registry.FRAMEWORK_DESTS | dests, name)
                elif not action.option_strings:
                    self.assertIn(action.dest, registry.FRAMEWORK_DESTS, name)

    def test_reserved_documents_cover_framework_versions(self):
        import re
        source, found = ROOT/'src/schemaxis', set()
        for path in source.rglob('*'):
            parts = path.relative_to(source).parts
            if path.suffix not in ('.py', '.json', '.mjs') or 'tests' in parts or parts[0] == 'adaptors' and len(parts) > 2:
                continue
            found.update(re.findall(r'[\'"](schemaxis\.[a-z][a-z0-9-]*)/[0-9]+[\'"]', path.read_text(errors='ignore')))
        routed = {version.partition('/')[0] for version in registry.routes()}
        self.assertEqual(found - routed - registry.FRAMEWORK_DOCUMENTS, set(), 'reserve new framework documents')

    def test_failing_declarations_binding_is_excluded_at_first_use(self):
        from schemaxis.capabilities import CapabilityCatalogue
        broken = {'module': lambda m: m.update(declarations=PACKAGE + '.missing:DECLARATIONS'),
                  'attribute': lambda m: m.update(declarations=PACKAGE + '.adaptor:MISSING')}
        for label, edit in broken.items():
            with self.subTest(binding=label):
                item = self.admitted(edit)
                with self.registered(fixtureplugin=item):
                    found = registry.discover()
                    self.assertEqual({p['id'] for p in found['providers']}, set(self.builtins))
                    self.assertEqual([(f['code'], f['observed']['id']) for f in found['pluginFaults']],
                                     [('INVALID_ADAPTOR', 'fixtureplugin')])
                    self.assertNotIn('fixtureplugin', registry.ADAPTORS)
                    with self.assertRaises(SchemaxisError) as caught:
                        registry.metadata('fixtureplugin')
                    self.assertEqual(caught.exception.fault.code, 'UNKNOWN_PROVIDER')
                    self.assertEqual(registry.declarations('gmsh'), registry.declarations('gmsh'))
                with self.registered(fixtureplugin=self.admitted(edit)):
                    with self.assertRaises(SchemaxisError) as caught:
                        registry.declarations('fixtureplugin')
                    self.assertEqual(caught.exception.fault.code, 'INVALID_ADAPTOR')
                    self.assertEqual(len(registry.PLUGIN_FAULTS), 1)
                with self.registered(fixtureplugin=self.admitted(edit)):
                    self.assertNotIn('fixtureplugin', CapabilityCatalogue()._manifests)
                    self.assertTrue(registry.query(operations=['emit']) is not None)
                    self.assertEqual(len(registry.PLUGIN_FAULTS), 1)

    def test_failing_route_schema_is_excluded_from_aggregate_schemas(self):
        from schemaxis import schema_authoring
        item = self.admitted(lambda m: m['routes']['fixtureplugin/1'].update(schema=PACKAGE + '.adaptor:missing'))
        with self.registered(fixtureplugin=item), patch.dict(schema_authoring.VERSIONS, {'fixtureplugin/1': 'fixtureplugin'}), \
                patch.object(schema_authoring, 'WORKFLOW_VERSIONS', schema_authoring.WORKFLOW_VERSIONS + ('fixtureplugin/1',)):
            workflow = schema_authoring.workflow_schema(authored=False)
            umbrella = schema_authoring.umbrella_schema(authored=False)
            self.assertEqual([f.observed['id'] for f in registry.PLUGIN_FAULTS], ['fixtureplugin'])
        self.assertEqual(len(workflow['properties']['operations']['items']['properties']['document']['oneOf']),
                         len(schema_authoring.WORKFLOW_VERSIONS))
        self.assertEqual(len(umbrella['oneOf']), len(schema_authoring.VERSIONS))
        self.assertEqual(umbrella, schema_authoring.umbrella_schema(authored=False))

    def test_installed_faulty_plugins_leave_every_command_usable(self):
        """Broken bindings and colliding flags, installed exactly as after pip install."""
        def broken(manifest): manifest['declarations'] = PACKAGE + '.adaptor:MISSING'
        def flags(manifest):
            manifest.update(id='flagplugin', version='flagplugin/1')
            manifest['routes'] = {'flagplugin/1': manifest['routes']['fixtureplugin/1']}
            manifest['cliOptions'] = [{'flag': '--executable', 'dest': 'flagplugin', 'help': 'Collides'}]
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)/'site'
            install(site, 'fixtureplugin', self.variant(broken))
            install(site, 'flagplugin', self.variant(flags), dist='flag-plugin')
            script = r'''
import contextlib, io, sys, warnings
warnings.simplefilter('ignore')
from schemaxis.adaptors import registry
from schemaxis.__main__ import main
def cli(*args):
    sys.argv = ['schemaxis', *args]
    return main()
assert [f.observed['id'] for f in registry.PLUGIN_FAULTS] == ['flagplugin'], registry.PLUGIN_FAULTS
assert 'collides with the framework' in registry.PLUGIN_FAULTS[0].message
found = cli('discover')
assert 'gmsh' in {p['id'] for p in found['providers']}
assert 'fixtureplugin' not in {p['id'] for p in found['providers']}
assert sorted(f['observed']['id'] for f in found['pluginFaults']) == ['fixtureplugin', 'flagplugin']
assert cli('describe', '--provider', 'gmsh')
with contextlib.redirect_stdout(io.StringIO()), contextlib.suppress(SystemExit):
    cli('run', '--help')
print('ok')
'''
            result = fresh(script, tmp, path=(self.packages, site))
            self.assertEqual(result.returncode, 0, result.stderr[-4000:])
            self.assertEqual(result.stdout.strip().splitlines()[-1], 'ok')

    def test_runtime_archive_registers_bundled_plugins_in_a_bare_interpreter(self):
        """A native interpreter without the host's site-packages, as in pvbatch or an embedded Python."""
        from importlib.metadata import PathDistribution
        from schemaxis import artifacts
        item = load_registry(plugins=[entry('fixtureplugin')], strict=True)['fixtureplugin']
        metadata = tempfile.TemporaryDirectory()
        self.addCleanup(metadata.cleanup)
        info = Path(metadata.name)/'schemaxis_fixture_plugin-0.1.0.dist-info'
        (info/'licenses').mkdir(parents=True)
        (info/'METADATA').write_text('Metadata-Version: 2.4\nName: schemaxis-fixture-plugin\nVersion: 0.1.0\n'
                                     'License-File: LICENCE\n')
        (info/'licenses/LICENCE').write_text('fixture licence\n')
        plugin = {'schemaxis-fixture-plugin': PathDistribution(info)}
        with self.registered(fixtureplugin=item), patch.object(artifacts, '_distribution', plugin.get):
            data = artifacts.runtime_archive()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            self.assertEqual(archive.read(artifacts.LICENCES + '/plugins/schemaxis-fixture-plugin/LICENCE'),
                             b'fixture licence\n')
            self.assertIn(artifacts.LICENCES + '/NOTICE', names)
            self.assertLessEqual({PACKAGE + '/__init__.py', PACKAGE + '/adaptor.py', PACKAGE + '/adaptor.json',
                                  'schemaxis/adaptors/' + registry.RUNTIME_PLUGINS}, names)
            self.assertEqual(json.loads(archive.read('schemaxis/adaptors/' + registry.RUNTIME_PLUGINS))['plugins'],
                             [{'id': 'fixtureplugin', 'package': PACKAGE, 'distribution': 'schemaxis-fixture-plugin'}])
        self.assertIsNone(registry.bundled_entry_points(), 'outside an archive installed metadata decides')
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'runtime.zip').write_bytes(data)
            # A plugin installed only in the application's own environment is not admitted.
            install(Path(tmp)/'site', 'otherplugin', self.variant(lambda m: m.update(id='otherplugin')), dist='other')
            script = r'''
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path[:0] = [str(root/'runtime.zip'), str(root/'site'), sys.argv[2]]
from schemaxis.adaptors import registry
assert registry.__file__.startswith(str(root/'runtime.zip')), registry.__file__
assert not registry.PLUGIN_FAULTS, registry.PLUGIN_FAULTS
assert registry.ADAPTORS['fixtureplugin']['source'] == 'plugin:schemaxis-fixture-plugin'
assert 'otherplugin' not in registry.ADAPTORS
doc = {'version': 'fixtureplugin/1', 'nodes': [{'id': 'hello', 'filter': 'emit', 'options': {'text': 'hi'}}]}
assert registry.resolve(doc)[0] == 'fixtureplugin'
assert registry.plan(doc) == doc
assert registry.route_hook(doc, 'reusableInputs')(doc) == {}
assert sys.modules['schemaxis_fixture_plugin'].__file__.startswith(str(root/'runtime.zip'))
print('ok')
'''
            result = fresh(script, tmp, self.packages, isolated=True)
            self.assertEqual(result.returncode, 0, result.stderr[-4000:])
            self.assertEqual(result.stdout.strip().splitlines()[-1], 'ok')

    def test_package_that_fails_to_import_is_excluded_with_a_fault(self):
        name = self.variant(init='raise RuntimeError("broken plugin")\n')
        fault = self.fault([entry('fixtureplugin', name)])
        self.assertIn('broken plugin', fault.message)
        self.fault([entry('fixtureplugin', 'schemaxis_missing_plugin_package')])

    def test_installed_distribution_routes_through_public_commands(self):
        """A real dist-info entry point, in a fresh process exactly as after pip install."""
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)/'site'
            install(site, 'fixtureplugin', PACKAGE)
            script = r'''
import importlib.abc, json, sys
from pathlib import Path
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'bpy', 'paraview', 'vtk', 'vtkmodules', 'FreeCAD', 'FreeCADGui'}:
            raise AssertionError('host tried importing native app: ' + fullname)
sys.meta_path.insert(0, NoNative())
from schemaxis.adaptors import registry
from schemaxis.__main__ import main
root = Path(sys.argv[1])
def cli(*args):
    sys.argv = ['schemaxis', *args]
    return main()
assert not registry.PLUGIN_FAULTS, registry.PLUGIN_FAULTS
assert 'schemaxis_fixture_plugin.adaptor' not in sys.modules, 'discovery imported plugin runtime modules'
found = {p['id']: p for p in cli('discover')['providers']}
assert found['fixtureplugin']['source'] == 'plugin:schemaxis-fixture-plugin', found['fixtureplugin']
assert found['gmsh']['source'] == 'builtin'
assert cli('describe', '--provider', 'fixtureplugin')['emit']['id'] == 'emit'
assert cli('schema', '--provider', 'fixtureplugin')['properties']['version']['const'] == 'fixtureplugin/1'
doc = {'version': 'fixtureplugin/1', 'nodes': [{'id': 'hello', 'filter': 'emit', 'options': {'text': 'hi'}}]}
source = root/'input.json'; source.write_text(json.dumps(doc))
assert cli('plan', str(source)) == doc
assert cli('run', str(source), '--output-directory', str(root/'out'), '--executable', 'launcher')['executable'] == 'launcher'
assert cli('verify', str(root/'out'))['verified']
assert list(registry.routes())[-1] == 'fixtureplugin/1'
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.studio_server import StudioApplication
session = AdaptorConsoleSession(root/'console', provider='workflow-design')
app = StudioApplication(session)
try:
    listed = {a['id']: a for a in app.adaptors()['adaptors']}
    assert listed['fixtureplugin']['display'] == {'name': 'Fixture Plugin', 'mark': 'FP', 'colour': '#336699'}
    assert 'display' not in listed['gmsh']
finally:
    app.close(); session.close()
print('ok')
'''
            result = fresh(script, tmp, path=(FIXTURES, site))
            self.assertEqual(result.returncode, 0, result.stderr[-4000:])
            self.assertEqual(result.stdout.strip().splitlines()[-1], 'ok')


if __name__ == '__main__':
    unittest.main()
