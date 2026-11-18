# Copyright (C) 2026 David L. F. Gaden.
"""The authoring coverage inventory reconciles discovery and detects drift."""
import contextlib
import copy
import importlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from schemaxis import studio_guidance, workflow_design, workflow_templates
from schemaxis.adaptors import registry
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.studio_catalogue import catalogue
from schemaxis.studio_guidance import SHARED, fields, shared_fields
from schemaxis.workflow_authoring import example

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'tools/inventory_adaptor_authoring.py'
GUARD = '''
import importlib.abc, runpy, sys
roots = set(sys.argv[1].split(','))
class RejectNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in roots:
            raise AssertionError('native import attempted: ' + fullname)
sys.meta_path.insert(0, RejectNative())
sys.argv = [sys.argv[2], *sys.argv[3:]]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
PRELOADED = '''
import runpy, sys
import bpy
sys.argv = [sys.argv[1], *sys.argv[2:]]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
TEMPLATE = workflow_templates.TEMPLATE_VERSION
VALUES = workflow_templates.VALUES_VERSION


def tool_module():
    spec = importlib.util.spec_from_file_location('inventory_adaptor_authoring', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inventory = tool_module()


def builtins():
    return sorted(name for name, item in registry.ADAPTORS.items() if item.get('source', 'builtin') == 'builtin')


def records(result, row):
    return {name: result['records'][row[name]] for name in inventory.DIMENSIONS}


SHOTCUT_OWNER = 'shotcut/schemaxis.shotcut~11/operation:editTimeline'
SHOTCUT_LOCAL = {
    'shotcut/schemaxis.shotcut~11/entity:~1properties~1nodes~1items~1properties~1options~1properties~1assets~1items':
        ('target', '/properties/nodes/items/properties/options/properties/assets/items/properties/name'),
    'shotcut/schemaxis.shotcut~11/entity:~1properties~1nodes~1items~1properties~1options~1properties~1clips~1items':
        ('consumer', '/properties/nodes/items/properties/options/properties/clips/items/properties/asset'),
}


def fixture_schema():
    """A small graph document with an identity pattern, a command enum and numeric settings."""
    node = {'type': 'object', 'properties': {
        'id': {'type': 'string', 'pattern': '^[A-Za-z][A-Za-z0-9_-]*$'},
        'filter': {'const': 'thing'},
        'inputs': {'type': 'object', 'properties': {'input': {'type': 'string'}}},
        'onVisit': {'type': 'array', 'items': {'enum': ['reset']}},
        'options': {'type': 'object', 'properties': {
            'size': {'type': 'number', 'minimum': 0, 'default': 1, 'description': 'Size of the thing.'},
            'mode': {'enum': ['fast', 'exact']}}}}}
    return {'type': 'object', 'properties': {'version': {'const': 'fixture/1'},
                                             'nodes': {'type': 'array', 'items': node}}}


def fixture_declarations():
    return {'thing': {'native': 'Thing', 'options': {},
                      'inputs': {'input': {'native': 'Input', 'required': True, 'multiple': False}},
                      'commands': {'reset': {'command': 'Reset', 'native': 'Reset'}}}}


def fixture(schema=None, declarations=None, ledger=None, guidance=None, identity_policy=None):
    collector = inventory.Collector('builtin')
    inventory._route(collector, 'fixture', 'fixture/1', 'primary', schema or fixture_schema(), [],
                     fixture_declarations() if declarations is None else declarations, guidance or {},
                     ['fixture:schema'])
    if identity_policy is not None:
        inventory.record_identity_policy(collector, 0, identity_policy, 'fixture:identity_policy')
    applied = inventory.apply_ledger(collector, ledger or {'version': inventory.LEDGER_VERSION, 'entries': {}}, ROOT)
    return inventory.assemble(collector, 'builtin', applied)


def unit(address):
    return 'entity:' + address


FULL = {}


def full_inventory():
    """One complete built-in build shared by the reconciliation classes."""
    if 'result' not in FULL:
        FULL['result'] = inventory.build(builtins() + list(inventory.SHARED_PROVIDERS) + [inventory.TEMPLATE_PROVIDER],
                                         ledger=inventory.load_ledger(ROOT), root=ROOT)
    return FULL['result']


def node_mutation(schema, path, key, value):
    """Set one keyword at a property path of the fixture node."""
    target = schema['properties']['nodes']['items']['properties']
    for part in path:
        target = target[part]
    target[key] = value
    return schema


class ExtendedSchema:
    """A schema binding that adds one optional top-level field."""

    def __init__(self, original):
        self.original = original

    def __call__(self):
        value = copy.deepcopy(self.original())
        value.setdefault('properties', {})['inventoryProbe'] = {'type': 'string'}
        return value


class Substitute:
    """Resolve one binding path to a replacement and every other path normally."""

    def __init__(self, path, replacement, binding):
        self.path, self.replacement, self.binding = path, replacement, binding

    def __call__(self, path):
        return self.replacement if path == self.path else self.binding(path)


class TrackedInventory(unittest.TestCase):
    def test_check_passes_without_importing_native_modules(self):
        roots = ','.join(sorted(inventory.NATIVE_ROOTS))
        result = subprocess.run([sys.executable, '-c', GUARD, roots, str(TOOL), '--check'], cwd=ROOT,
                                env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, capture_output=True,
                                text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('current:', result.stdout)

    def test_tracked_artifacts_hold_no_machine_paths(self):
        spec = importlib.util.spec_from_file_location('release_gate', ROOT / 'tools/release_gate.py')
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        names = (inventory.OUTPUT, inventory.SUMMARY, inventory.LEDGER, 'verification/adaptor-authoring/README.md')
        self.assertEqual(gate.scan_paths(ROOT, names), [])
        for name in names:
            text = (ROOT / name).read_text()
            for marker in (str(Path.home()), str(ROOT)):
                self.assertNotIn(marker, text, name)


class NativeGuard(unittest.TestCase):
    """The CLI blocks native imports before any framework or plugin module loads."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='schemaxis-inventory-guard-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.marker = self.root / 'native-executed'
        (self.root / 'bpy').mkdir()
        (self.root / 'bpy/__init__.py').write_text(
            'from pathlib import Path\nPath(' + repr(str(self.marker)) + ').write_text("imported")\n')

    def run_tool(self, *arguments, script=None):
        command = [sys.executable, '-c', script, str(TOOL), *arguments] if script else [sys.executable, str(TOOL), *arguments]
        env = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(self.root), str(ROOT / 'src')])}
        env.pop('SCHEMAXIS_ADAPTOR_PLUGINS', None)
        return subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)

    def test_plugin_loading_cannot_import_a_native_module(self):
        package = self.root / 'inventory_probe_plugin'
        package.mkdir()
        (package / '__init__.py').write_text('import bpy\n')
        (package / 'adaptor.json').write_text('{}')
        info = self.root / 'inventory_probe_plugin-1.0.dist-info'
        info.mkdir()
        (info / 'METADATA').write_text('Metadata-Version: 2.1\nName: inventory-probe-plugin\nVersion: 1.0\n')
        (info / 'entry_points.txt').write_text('[schemaxis.adaptors]\ninventoryprobe = inventory_probe_plugin\n')
        result = self.run_tool('--external', str(self.root / 'external.json'))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('native imports attempted during discovery: bpy', result.stderr)
        self.assertFalse(self.marker.exists(), 'the native module body must never run')
        self.assertFalse((self.root / 'external.json').exists())

    def test_native_modules_loaded_before_discovery_are_reported(self):
        result = self.run_tool('--check', script=PRELOADED)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('native modules were loaded before discovery started: bpy', result.stderr)

    def test_imported_module_refuses_to_run_without_the_blocker(self):
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(inventory.main(['--check']), 2)
        self.assertIn('native-import blocker', stderr.getvalue())


class CommandLine(unittest.TestCase):
    """One authoritative argparse parse precedes plugin discovery (F6)."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='schemaxis-inventory-cli-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        info = self.root / 'fixture_dist-0.1.0.dist-info'
        info.mkdir()
        (info / 'METADATA').write_text('Metadata-Version: 2.1\nName: fixture-dist\nVersion: 0.1.0\n')
        (info / 'entry_points.txt').write_text('[schemaxis.adaptors]\nfixtureplugin = schemaxis_fixture_plugin\n')
        self.tracked = {name: (ROOT / name).read_bytes() for name in (inventory.OUTPUT, inventory.SUMMARY)}

    def tearDown(self):
        for name, content in self.tracked.items():
            self.assertEqual((ROOT / name).read_bytes(), content, name + ' must not change')

    def run_tool(self, *arguments, plugins=None):
        path = os.pathsep.join([str(self.root), str(ROOT / 'tests/fixtures/plugin_adaptor'), str(ROOT / 'src')])
        env = {**os.environ, 'PYTHONPATH': path}
        env.pop('SCHEMAXIS_ADAPTOR_PLUGINS', None)
        if plugins is not None:
            env['SCHEMAXIS_ADAPTOR_PLUGINS'] = plugins
        return subprocess.run([sys.executable, str(TOOL), *arguments], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=300)

    def test_separate_and_equals_forms_inventory_the_same_admitted_plugin(self):
        separate, equals = self.root / 'separate.json', self.root / 'equals.json'
        for arguments in (('--external', str(separate)), ('--external=' + str(equals),)):
            with self.subTest(arguments=arguments):
                result = self.run_tool(*arguments)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('1 installed plugin(s) fixtureplugin', result.stdout)
        self.assertEqual(separate.read_bytes(), equals.read_bytes())
        content = json.loads(separate.read_text())
        self.assertTrue(content['items'])
        self.assertEqual({row['adaptor'] for row in content['items']}, {'fixtureplugin'})
        self.assertEqual({row['scope'] for row in content['routes']}, {'external-handoff'})

    def test_abbreviations_and_conflicting_modes_are_refused_before_discovery(self):
        target = self.root / 'refused.json'
        for arguments in (('--ext', str(target)), ('--external=' + str(target), '--check'),
                          ('--check', '--external', str(target))):
            with self.subTest(arguments=arguments):
                result = self.run_tool(*arguments)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('usage:', result.stderr)
                self.assertFalse(target.exists())

    def test_external_mode_refuses_when_the_operator_disabled_plugins(self):
        target = self.root / 'disabled.json'
        result = self.run_tool('--external=' + str(target), plugins='off')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('SCHEMAXIS_ADAPTOR_PLUGINS=off disables them', result.stderr)
        self.assertFalse(target.exists())

    def test_builtin_check_ignores_installed_plugins_and_reports_them(self):
        result = self.run_tool('--check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('current:', result.stdout)
        self.assertIn('not covered by the tracked inventory: fixtureplugin', result.stdout)


class FullInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = full_inventory()
        cls.items = {row['key']: row for row in cls.result['items']}
        cls.surfaces = {row['key']: row for row in cls.result['surfaces']}
        cls.fields = Counter((key, address) for key, address, _, _, _ in inventory.expand_fields(cls.result))
        cls.kinds = {key + address: kind for key, address, kind, _, _ in inventory.expand_fields(cls.result)}


class Reconciliation(FullInventory):
    def test_every_registered_route_declaration_and_add_entry_has_a_row(self):
        routes = {(row['adaptor'], row['route']) for row in self.result['routes']}
        for name in builtins():
            meta = registry.metadata(name)
            for version in meta['routes']:
                self.assertIn((name, version), routes)
            for operation in registry.declarations(name):
                row = self.items.get(inventory.item_key(name, meta['version'], 'operation:' + operation))
                self.assertIsNotNone(row, name + ' ' + operation)
                self.assertEqual(row['projection'], 'projected', row['key'])
            for version in meta['routes']:
                seen = Counter()
                for entry in catalogue(name, version)['items']:
                    seen[entry['id']] += 1
                    identity = entry['id'] if seen[entry['id']] == 1 else entry['id'] + '@' + str(seen[entry['id']])
                    row = self.items[inventory.item_key(name, version, identity)]
                    self.assertEqual(row['catalogue']['id'], entry['id'])
        for version in SHARED:
            self.assertIn((SHARED[version], version), routes)
        self.assertIn((inventory.TEMPLATE_PROVIDER, TEMPLATE), routes)
        self.assertIn((inventory.TEMPLATE_PROVIDER, VALUES), routes)

    def test_every_schema_address_is_owned_exactly_once(self):
        self.assertEqual(max(self.fields.values()), 1)
        addresses = Counter()
        for key, address in self.fields:
            addresses[inventory.split_key(key)[:2] + (address,)] += 1
        self.assertEqual(max(addresses.values()), 1)
        for name in builtins():
            for version, route in registry.metadata(name)['routes'].items():
                expected = {address for address, _ in fields(registry.binding(route['schema'])())}
                found = {address for key, address in self.fields if inventory.split_key(key)[:2] == (name, version)}
                self.assertEqual(found, expected, name + ' ' + version)
        for version, provider in SHARED.items():
            expected = {address for address, _ in shared_fields(version)}
            found = {address for key, address in self.fields if inventory.split_key(key)[:2] == (provider, version)}
            self.assertEqual(found, expected, version)

    def test_definitions_alternatives_nested_and_generated_items_are_present(self):
        owners = {address: key for key, address in self.fields if key.startswith('paraview/')}
        for address in ('/$defs/options-foam/properties/regions/anyOf/0',
                        '/$defs/runtime/anyOf/0/properties/path/items/anyOf/1',
                        '/properties/scenes/items/properties/visible/additionalProperties'):
            self.assertIn(address, owners)
        self.assertTrue(owners['/$defs/options-foam/properties/regions/anyOf/0'].endswith('/operation:foam'))
        self.assertEqual(owners['/$defs/runtime/anyOf/0/properties/path/items/anyOf/1'],
                         'paraview/schemaxis~11/definition:runtime')
        kinds = Counter(row['kind'] for row in self.result['items'])
        for kind in ('operation-writer', 'operation-selector', 'hook-item', 'document-collection', 'document-map',
                     'document-singleton', 'definition', 'nested-member', 'nested-entry', 'nested-variant',
                     'native-command', 'contract-unit', 'framework-entity'):
            self.assertGreater(kinds[kind], 0, kind)
        self.assertEqual(self.items['paraview/schemaxis~11/scene:camera']['anchors'],
                         ['/properties/scenes/items/properties/images/items/properties/cameras/items'])
        self.assertIn('/properties/scenes/items', self.items['paraview/schemaxis~11/document:scenes']['anchors'])

    def test_keys_are_unique_and_round_trip(self):
        keys = [row['key'] for row in self.result['items']] + [row['key'] for row in self.result['surfaces']]
        self.assertEqual(len(keys), len(set(keys)))
        for row in self.result['items']:
            self.assertEqual(inventory.split_key(row['key'])[:3], (row['adaptor'], row['route'], row['item']))
        surface = 'paraview/schemaxis~11/operation:foam/$defs/options-foam/properties/regions'
        self.assertEqual(inventory.split_key(surface),
                         ('paraview', 'schemaxis/1', 'operation:foam', '/$defs/options-foam/properties/regions'))
        timelines = [row for row in self.result['items'] if row['adaptor'] == 'shotcut'
                     and row['item'].startswith('operation:editTimeline')]
        self.assertEqual([row['key'] for row in timelines],
                         ['shotcut/schemaxis.shotcut~11/operation:editTimeline'])
        self.assertEqual((timelines[0]['operation'], timelines[0]['route']),
                         ('editTimeline', 'schemaxis.shotcut/1'))
        self.assertFalse(any(gap['code'] == 'duplicate-catalogue-id'
                             and inventory.split_key(gap['key'])[0] == 'shotcut'
                             for gap in self.result['gaps']))

    def test_intentional_duplicate_catalogue_entries_keep_distinct_keys_and_gap(self):
        schema = fixture_schema()
        entry = {'id': 'operation:thing', 'operation': 'thing', 'title': 'Thing',
                 'group': 'filters', 'at': '/nodes/-',
                 'schema': schema['properties']['nodes']['items']}
        collector = inventory.Collector('builtin')
        inventory._route(collector, 'fixture', 'fixture/1', 'primary', schema,
                         [entry, copy.deepcopy(entry)], fixture_declarations(), {}, ['fixture:schema'])
        result = inventory.assemble(collector, 'builtin', 0)
        rows = [row for row in result['items'] if row['item'].startswith('operation:thing')]
        self.assertEqual([row['key'] for row in rows],
                         ['fixture/fixture~11/operation:thing', 'fixture/fixture~11/operation:thing@2'])
        for row in rows:
            self.assertEqual(inventory.split_key(row['key'])[:3],
                             (row['adaptor'], row['route'], row['item']))
            self.assertEqual((row['operation'], row['route'], row['catalogue']['id']),
                             ('thing', 'fixture/1', 'operation:thing'))
            self.assertEqual(row['projection'], 'projected')
        gaps = [gap for gap in result['gaps'] if gap['code'] == 'duplicate-catalogue-id']
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]['key'], 'fixture/fixture~11/operation:thing')
        self.assertIn('2 Add catalogue entries share this id', gaps[0]['detail'])

    def test_statuses_stay_separate_and_unknowns_stay_unknown(self):
        assessed, reviewed = set(), {}
        entries = inventory.load_ledger(ROOT)['entries']
        for row in self.result['items'] + self.result['surfaces']:
            for name, value in records(self.result, row).items():
                for status, allowed in inventory.STATUSES.items():
                    self.assertIn(value[status], allowed)
                if value['implementation'] == 'not-applicable':
                    self.assertTrue(value.get('rationale'), row['key'])
                    self.assertIn(value['assessment'], ('derived', 'assessed'), row['key'])
                    if value['assessment'] == 'assessed':
                        self.assertTrue(entries[row['key']][name]['evidence'], row['key'])
                if value['assessment'] == 'assessed':
                    assessed.add(row['key'])
                # Review credit comes only from an explicit judged ledger record.
                judged = entries.get(row['key'], {}).get(name, {}).get('review')
                self.assertEqual(value['review'], judged or 'not-reviewed', (row['key'], name))
                if row['key'] in SHOTCUT_LOCAL and name == 'renaming':
                    self.assertIn(value['review'], ('not-reviewed', 'accepted'))
                    self.assertEqual((value['assessment'], value['implementation'], value['qualification']),
                                     ('assessed', 'partial', 'not-qualified'))
                elif value['review'] != 'not-reviewed':
                    reviewed[(row['key'], name)] = {status: value[status] for status in inventory.STATUSES}
        self.assertLessEqual(assessed, set(entries))
        # The five scoped rename reviews are separate from the singleton exclusion.
        accepted = {
            'assessment': 'assessed', 'implementation': 'partial', 'review': 'accepted',
            'qualification': 'not-qualified'}
        self.assertEqual(reviewed, {
            ('paraview/schemaxis~11/operation:extractBlock', 'renaming'): accepted,
            ('calc/schemaxis.calc~11/operation:fromRows', 'renaming'): accepted,
            ('calc/schemaxis.calc~11/operation:fromTypedRows', 'renaming'): accepted,
            ('calc/schemaxis.calc~11/operation:readCSV', 'renaming'): accepted,
            ('calc/schemaxis.calc~11/operation:readTypedCSV', 'renaming'): accepted,
            ('shotcut/schemaxis.shotcut~11/operation:editTimeline', 'multiMode'): {
                **accepted, 'implementation': 'not-applicable', 'qualification': 'not-required'}})
        timeline = records(self.result, self.items['shotcut/schemaxis.shotcut~11/operation:editTimeline'])
        self.assertEqual({status: timeline['multiMode'][status] for status in inventory.STATUSES}, {
            'assessment': 'assessed', 'implementation': 'not-applicable', 'review': 'accepted',
            'qualification': 'not-required'})
        for dimension in ('naming', 'renaming', 'subset'):
            self.assertEqual(timeline[dimension]['review'], 'not-reviewed')
            self.assertEqual(timeline[dimension]['qualification'], 'not-qualified')
        slice_ = records(self.result, self.items['paraview/schemaxis~11/operation:slice'])
        self.assertEqual((slice_['multiMode']['assessment'], slice_['multiMode']['implementation']), ('derived', 'implemented'))
        self.assertEqual(slice_['naming']['implementation'], 'implemented')
        self.assertEqual(slice_['naming']['qualification'], 'not-qualified')
        self.assertEqual(slice_['renaming']['implementation'], 'not-implemented')
        extract = records(self.result, self.items['paraview/schemaxis~11/operation:extractBlock'])
        self.assertEqual(extract['multiMode']['implementation'], 'implemented')
        self.assertEqual(extract['multiMode']['qualification'], 'recorded-prior')
        self.assertEqual(extract['renaming']['implementation'], 'partial')
        spatial = records(self.result, self.items['blender/schemaxis.blender~11/document:definitions'])
        self.assertEqual((spatial['renaming']['implementation'], spatial['renaming']['assessment']), ('generic-rule', 'unassessed'))
        implemented = {row['key'] for row in self.result['items']
                       if records(self.result, row)['multiMode']['implementation'] == 'implemented'}
        from schemaxis.studio_catalogue import catalogue
        declared = {
            inventory.item_key('workflow-design', 'schemaxis.workflow-design/2', item)
            for item in ('document:outputs', unit('/properties/outputs/additionalProperties'))
        }
        for provider in builtins():
            for version in registry.metadata(provider)['routes']:
                projection = catalogue(provider, version)
                queue, definitions_used = [], set()
                projected_ids = {entry['schema'].get('x-studio-guide', {}).get('address'): entry['id']
                                 for entry in projection['items']
                                 if entry['schema'].get('x-studio-guide', {}).get('authoring')}
                for entry in projection['items']:
                    if entry.get('authoring', {}).get('multiMode'):
                        declared.add(inventory.item_key(provider, version, entry['id']))
                    queue.append(entry['schema'])
                while queue:
                    for _, node in inventory.fields(queue.pop()):
                        guide = node.get('x-studio-guide', {})
                        address = guide.get('address', '')
                        ref = node.get('$ref', '')
                        inherited = {}
                        if ref.startswith('#/$defs/'):
                            target = ref[len('#/$defs/'):].replace('~1', '/').replace('~0', '~')
                            definition = projection['definitions'].get(target)
                            if definition is not None:
                                inherited = definition.get('x-studio-guide', {}).get('authoring', {})
                                if ref not in definitions_used:
                                    queue.append(definition)
                                    definitions_used.add(ref)
                        if guide.get('authoring', inherited).get('multiMode'):
                            if address in projected_ids or re.search(r'/items(?:/(?:oneOf|anyOf)/[0-9]+)?$', address):
                                identity = projected_ids.get(address, unit(address))
                                declared.add(inventory.item_key(provider, version, identity))
        self.assertEqual(implemented, declared)
        for key, classification in (
                ('aseprite/schemaxis.aseprite~11/operation:rect', 'sequential'),
                ('cantera/schemaxis.cantera~11/operation:equilibrate', 'singleton')):
            policy = records(self.result, self.items[key])['multiMode']
            self.assertEqual((policy['implementation'], policy['classification']), ('not-applicable', classification))


    def test_subset_controls_come_from_guidance_or_unique_enumerations(self):
        controlled = {row['key'] for row in self.result['surfaces'] if row.get('control') not in (None, 'enum-subset', 'reader-array-domain', 'input-subset', 'file-subset')}
        self.assertEqual(controlled, {
            'paraview/schemaxis~11/operation:extractBlock/$defs/options-extractBlock/properties/selectors',
            'paraview/schemaxis~11/operation:foam/$defs/options-foam/properties/cellArrays',
            'paraview/schemaxis~11/operation:foam/$defs/options-foam/properties/regions',
            'paraview/schemaxis~11/operation:cellToPoint/$defs/options-cellToPoint/properties/arrays/anyOf/0',
            'paraview/schemaxis~11/operation:pointToCell/$defs/options-pointToCell/properties/arrays/anyOf/0',
            'paraview/schemaxis~11/operation:passArrays/$defs/options-passArrays/properties/pointArrays/anyOf/0',
            'paraview/schemaxis~11/operation:passArrays/$defs/options-passArrays/properties/cellArrays/anyOf/0',
            'paraview/schemaxis~11/operation:pvPassArrays/$defs/options-pvPassArrays/properties/PointDataArrays/anyOf/0',
            'paraview/schemaxis~11/operation:pvPassArrays/$defs/options-pvPassArrays/properties/CellDataArrays/anyOf/0',
            'paraview/schemaxis~11/operation:pvCellDatatoPointData/$defs/options-pvCellDatatoPointData/properties/CellDataArraytoprocess/anyOf/0',
            'paraview/schemaxis~11/operation:pvPointDatatoCellData/$defs/options-pvPointDatatoCellData/properties/PointDataArraytoprocess/anyOf/0',
            'octave/schemaxis.octave~11/document:outputs/properties/outputs',
            'paraview/schemaxis~11/operation:pvExtractBlock/$defs/options-pvExtractBlock/properties/Selectors/anyOf/0',
            'blender/schemaxis.blender~11/document:scenes/properties/scenes/items/properties/visible',
            'blender/schemaxis.blender~11/document:scenes/properties/scenes/items/properties/meshes',
            'paraview/schemaxis~11/scene:geometry/properties/scenes/items/properties/geometry',
            'hdf5/schemaxis.hdf5~11/definition:data/$defs/data/properties/columns',
            'hdf5/schemaxis.hdf5~11/definition:extract/$defs/extract/properties/fields',
            'hdf5/schemaxis.hdf5~11/definition:tolerance/$defs/tolerance/properties/paths',
            'hdf5/schemaxis.hdf5~11/definition:dimension/$defs/dimension/properties/scales',
            'hdf5/schemaxis.hdf5~11/definition:edit/$defs/edit/properties/fields',
            'oracle/schemaxis.oracle~11/definition:window/$defs/window/properties/partitionBy',
            'oracle/schemaxis.oracle~11/definition:inspection/$defs/inspection/properties/names',
            'exiftool/schemaxis.exiftool~11/document:edits/properties/edits/properties/keywords/properties/remove',
            'exiftool/schemaxis.exiftool~11/entity:~1oneOf~14~1properties~1itemEdits~1items/oneOf/4/properties/itemEdits/items/properties/edits/properties/keywords/properties/remove',
            'exiftool/schemaxis.exiftool~11/entity:~1properties~1itemEdits~1items/properties/itemEdits/items/properties/edits/properties/keywords/properties/remove',
            'exiftool/schemaxis.exiftool~11/operation:editMetadata/oneOf/4/properties/edits/properties/keywords/properties/remove',
            *(row['key'] for row in self.result['surfaces'] if row.get('control') == 'document-entries')})
        static = {row['key'] for row in self.result['surfaces'] if row.get('control') == 'enum-subset'}
        self.assertTrue(any(key.startswith('freecad/') and key.endswith('/properties/views') for key in static), static)
        self.assertTrue(any(key.startswith('exiftool/') for key in static), static)
        reader_domains = {row['key'] for row in self.result['surfaces'] if row.get('control') == 'reader-array-domain'}
        self.assertIn('paraview/schemaxis~11/operation:pvXMLUnstructuredGridReader/'
                      '$defs/options-pvXMLUnstructuredGridReader/properties/PointArrayStatus/anyOf/0', reader_domains)
        file_lists = {row['key'] for row in self.result['surfaces'] if row.get('control') == 'file-subset'}
        self.assertIn('paraview/schemaxis~11/operation:pvXMLUnstructuredGridReader/'
                      '$defs/options-pvXMLUnstructuredGridReader/properties/FileName', file_lists)
        for row in self.result['surfaces']:
            result = inventory.record(self.result, row, 'subset')
            if row.get('control') == 'input-subset':
                self.assertTrue(row['port']['multiple'])
                self.assertEqual(result['implementation'], 'implemented')
            elif row['key'] in static | reader_domains | file_lists:
                self.assertEqual((result['assessment'], result['implementation'], result['review']),
                                 ('derived', 'implemented', 'not-reviewed'))
            elif row['key'] not in controlled:
                self.assertNotEqual(result['implementation'], 'implemented', row['key'])

    def test_summary_is_deterministic_and_matches_counts(self):
        text = inventory.summary(self.result)
        self.assertEqual(text, inventory.summary(json.loads(inventory.render(self.result))))
        self.assertIn('| fields | ' + str(self.result['counts']['fields']) + ' |', text)


class NestedUnits(FullInventory):
    """Nested collections, entries and variants are rows of their own (F2)."""

    def test_nested_collections_and_variants_have_independent_rows(self):
        production = 'blender/schemaxis.blender.production~11/'
        parent = self.items[production + 'document:production']
        self.assertEqual(records(self.result, parent)['multiMode']['implementation'], 'not-applicable')
        wanted = {'/properties/production/properties/collections/items',
                  '/properties/production/properties/materialGraphs/items',
                  '/properties/production/properties/materialGraphs/items/properties/nodes/items'}
        for address in wanted:
            row = self.items[inventory.item_key('blender', 'schemaxis.blender.production/1', unit(address))]
            self.assertEqual(row['kind'], 'nested-member')
            self.assertEqual(row['anchors'], [address])
            for name, value in records(self.result, row).items():
                if name == 'multiMode' and address.endswith('/nodes/items'):
                    self.assertEqual(value['basis'], 'discriminated collection member')
                elif name == 'naming' and address.endswith('/nodes/items'):
                    self.assertEqual(value['basis'], 'shared naming location')
                elif name == 'multiMode' and address.endswith('/materialGraphs/items'):
                    self.assertEqual(value['basis'], 'adaptor collection semantics')
                elif name == 'naming' and address.endswith('/materialGraphs/items'):
                    self.assertEqual(value['implementation'], 'implemented')
                elif address.endswith('/collections/items') and name in ('naming', 'multiMode'):
                    self.assertEqual(value['implementation'], 'implemented')
                else:
                    self.assertEqual((value['assessment'], value['implementation'], value['review'], value['qualification']),
                                     ('unassessed', 'unknown', 'not-reviewed', 'not-qualified'))
        graphs = inventory.item_key('blender', 'schemaxis.blender.production/1',
                                    unit('/properties/production/properties/materialGraphs/items'))
        self.assertEqual(self.items[graphs]['parent'], parent['key'])
        identity = graphs + '/properties/production/properties/materialGraphs/items/properties/id'
        self.assertEqual(self.kinds[identity], 'identity')
        variants = [row for row in self.result['items'] if row['kind'] == 'nested-variant'
                    and row['key'].startswith(production) and row.get('discriminator') == {'kind': 'principled'}]
        self.assertEqual(len(variants), 1)
        self.assertTrue(variants[0]['parent'].endswith('materialGraphs~1items~1properties~1nodes~1items'))

    def test_each_nested_status_has_a_declared_policy_or_explicit_disposition(self):
        nested = [row for row in self.result['items'] if row['kind'] in inventory.NESTED]
        self.assertEqual(len(nested), self.result['counts']['nestedUnits'])
        entries = inventory.load_ledger(ROOT)['entries']
        schemas = {}
        def declared_authoring(row):
            address = row['anchors'][0]
            local = row.get('guides', {}).get(address, {}).get('authoring')
            if local:
                return local
            provider, version = row['adaptor'], row['route']
            if version not in schemas:
                binding = registry.metadata(provider)['routes'][version]['schema']
                schemas[version] = dict(fields(registry.binding(binding)()))
            target = schemas[version][address].get('$ref', '').removeprefix('#')
            guide = studio_guidance.load(provider)['routes'][version]['fields'].get(target, {})
            return guide.get('authoring', {})
        for row in nested:
            self.assertIn(row['parent'], self.items)
            for name, value in records(self.result, row).items():
                if row['key'] in SHOTCUT_LOCAL and name == 'renaming':
                    self.assertEqual((value['assessment'], value['implementation'], value['qualification']),
                                     ('assessed', 'partial', 'not-qualified'))
                    continue
                if value['assessment'] == 'assessed':
                    entry = entries[row['key']][name]
                    self.assertEqual(entry['routes'], [row['route']])
                    self.assertTrue(entry.get('evidence'))
                    continue
                if value['implementation'] == 'implemented' and name in ('naming', 'multiMode'):
                    self.assertIn(name, declared_authoring(row), row['key'])
                    self.assertRegex(row['anchors'][0], r'/items(?:/(?:oneOf|anyOf)/[0-9]+)?$')
                    self.assertEqual(value['assessment'], 'derived')
                    continue
                if name == 'naming' and value['basis'] in ('declared unnamed member', 'shared naming location',
                                                           'schema has no member Name field',
                                                           'validator copy of projected member'):
                    self.assertEqual((value['assessment'], value['implementation']), ('derived', 'not-applicable'))
                    continue
                if name == 'multiMode' and value['basis'] == 'Declared member applicability':
                    self.assertEqual(value['assessment'], 'derived')
                    self.assertIn(value['implementation'], ('not-applicable', 'not-implemented'))
                    continue
                if name == 'multiMode' and value['basis'] == 'declared nested collection maxItems':
                    provider, version, _, _ = inventory.split_key(row['key'])
                    route = registry.metadata(provider)['routes'][version]
                    schema = registry.binding(route['schema'])()
                    container = dict(inventory.fields(schema))[row['anchors'][0][:-len('/items')]]
                    self.assertEqual((container['type'], container['maxItems']), ('array', 1))
                    self.assertEqual(value['implementation'], 'not-applicable')
                    continue
                if name == 'multiMode' and value['basis'] in (
                        'declared alternative for one property', 'declared document alternative'):
                    self.assertEqual(row['kind'], 'nested-variant')
                    prefix = '/properties/[^/]+' if value['basis'].endswith('one property') else '^'
                    self.assertRegex(row['anchors'][0], prefix + r'(?:/(?:oneOf|anyOf)/[0-9]+)+$')
                    self.assertEqual((value['assessment'], value['implementation']),
                                     ('derived', 'not-applicable'))
                    continue
                if name == 'multiMode' and value['basis'] in ('Blender graph requires exactly one output',
                                                             'Blender graph node has no configurable settings'):
                    self.assertEqual((row['adaptor'], row['kind'], value['implementation']),
                                     ('blender', 'nested-variant', 'not-applicable'))
                    continue
                if name == 'multiMode' and value['basis'] in ('Blender animation or constraint ownership',
                                                             'Blender member of a compound value'):
                    self.assertEqual(row['adaptor'], 'blender')
                    self.assertIn(value['classification'], ('conditional', 'collection'))
                    continue
                if name == 'multiMode' and value['basis'] in (
                        'ordered Blender mesh edit stages', 'ordered Blender channel keyframes'):
                    self.assertEqual(row['adaptor'], 'blender')
                    pattern = (r'/meshEdits/items/properties/steps/items(?:/oneOf/\d+)?$'
                               if value['classification'] == 'sequential' else r'/properties/keys/items$')
                    self.assertRegex(row['anchors'][0], pattern)
                    self.assertEqual(value['implementation'], 'not-applicable')
                    continue
                if name == 'multiMode' and value['basis'] in ('pipeline input reference', 'literal or runtime value grammar',
                                                             'FreeCAD affine binding grammar', 'FreeCAD compound geometry settings',
                                                             'duplicate operation schema member', 'closed anonymous member',
                                                             'validator copy of projected member'):
                    self.assertEqual((value['assessment'], value['implementation']), ('derived', 'not-applicable'))
                    continue
                if name == 'multiMode' and value['basis'] == 'adaptor collection semantics':
                    state = 'not-implemented' if value['classification'] == 'conditional' else 'not-applicable'
                    self.assertEqual((value['assessment'], value['implementation']), ('derived', state))
                    continue
                if name == 'multiMode' and value['basis'] == 'discriminated collection member':
                    self.assertEqual((row['kind'], value['implementation'], value['classification']),
                                     ('nested-member', 'not-applicable', 'collection'))
                    self.assertTrue(row['anchors'][0].endswith('/items'))
                    continue
                if name == 'multiMode' and value['basis'] == 'literal scalar collection member':
                    self.assertEqual(row['kind'], 'nested-member')
                    self.assertTrue(row['anchors'][0].endswith('/items'))
                    self.assertEqual((value['assessment'], value['implementation'], value['classification']),
                                     ('derived', 'not-applicable', 'collection'))
                    continue
                self.assertEqual(value['assessment'], 'unassessed', row['key'] + ' ' + name)
                self.assertEqual(value['implementation'], 'unknown', row['key'] + ' ' + name)

    def test_dynamic_scalar_collection_members_are_values(self):
        key = 'paraview/schemaxis~11/entity:' + inventory.escape(
            '/$defs/options-clip/properties/origin/anyOf/0/items')
        row = self.items[key]
        status = records(self.result, row)['multiMode']
        self.assertEqual((status['basis'], status['implementation'], status['classification']),
                         ('literal scalar collection member', 'not-applicable', 'collection'))
        self.assertEqual(records(self.result, row)['subset']['assessment'], 'unassessed')

    def test_shotcut_policy_projects_local_target_and_consumer(self):
        surfaces = {row['key']: row for row in self.result['surfaces']}
        self.assertNotIn('identityReferences', self.items[SHOTCUT_OWNER])
        for key, (role, address) in SHOTCUT_LOCAL.items():
            row = self.items[key]
            self.assertEqual(row['parent'], SHOTCUT_OWNER)
            surface = surfaces[key + address]
            self.assertEqual(surface['kind'], 'identity' if role == 'target' else 'reference')
            semantics = row['identityReferences']['asset']
            self.assertEqual(surface['identityReferences']['asset'], semantics)
            self.assertEqual((semantics['domain'], semantics['role'], semantics['owner']),
                             ('owner-local', role, SHOTCUT_OWNER))
            self.assertNotIn('ports', semantics)
            self.assertNotIn('port', surface)

    def authoring(self, key):
        return self.result['authoringSets'][self.items[key]['authoring']]

    def test_authoring_surfaces_state_projection_facts_only(self):
        surfaces = self.authoring
        extract = surfaces('paraview/schemaxis~11/operation:extractBlock')
        self.assertEqual((extract['studioAdd'], extract['quickRows'], extract['batch']), ('projected',) * 3)
        slice_ = surfaces('paraview/schemaxis~11/operation:slice')
        self.assertEqual((slice_['studioAdd'], slice_['quickRows'], slice_['batch']),
                         ('projected', 'projected', 'not-projected'))
        nested = next(row['key'] for row in self.result['items'] if row['kind'] == 'nested-member')
        self.assertEqual(surfaces(nested)['studioAdd'], 'not-projected')
        for row in self.result['items']:
            values = surfaces(row['key'])
            self.assertEqual(set(values), set(inventory.AUTHORING_SURFACES))
            nested_settings = (row['kind'] in (*inventory.NESTED, 'operation-writer', 'hook-item') and values['quickRows'] == 'projected')
            self.assertEqual(values['studioEdit'], 'projected' if nested_settings else 'unassessed', row['key'])
            for name in ('studioProperties', 'core', 'cli', 'console', 'ai'):
                self.assertEqual(values[name], 'unassessed', row['key'] + ' ' + name)


class TemplateContracts(unittest.TestCase):
    """Workflow template and values contracts are validator-backed rows (F3)."""

    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / inventory.TEMPLATE_SOURCE).read_text()
        cls.result = inventory.build([inventory.TEMPLATE_PROVIDER])

    def rows(self, result):
        return {key + address: kind for key, address, kind, _, _ in inventory.expand_fields(result)}

    def test_template_and_values_units_fields_and_gaps(self):
        units = {row['key'] for row in self.result['items']}
        for route, names in ((TEMPLATE, ('document:template', 'entity:parameters', 'entity:outputs',
                                         'document:requirements')),
                             (VALUES, ('document:case', 'entity:template-identity', 'entity:values',
                                       'document:run', 'capture:bundle'))):
            for name in names:
                self.assertIn(inventory.item_key(inventory.TEMPLATE_PROVIDER, route, name), units)
        rows = self.rows(self.result)
        template = 'workflow-template/schemaxis.workflow-template~11/'
        values = 'workflow-template/schemaxis.workflow-values~11/'
        expected = {template + 'document:template/id': 'identity',
                    template + 'entity:parameters/parameters/{parameter}': 'identity',
                    template + 'entity:parameters/parameters/{parameter}/target/pointer': 'reference',
                    template + 'entity:parameters/parameters/{parameter}/constraints/enum': 'contract-key',
                    template + 'entity:outputs/outputs/{output}': 'identity',
                    template + 'entity:outputs/outputs/{output}/operation': 'reference',
                    values + 'entity:values/values/{parameter}': 'reference',
                    values + 'entity:template-identity/template/id': 'identity',
                    values + 'document:run/run/outputDirectory': 'path'}
        for key, kind in expected.items():
            self.assertEqual(rows.get(key), kind, key)
        gaps = {(gap['key'], gap['code']) for gap in self.result['gaps']}
        for route in (TEMPLATE, VALUES):
            root = inventory.item_key(inventory.TEMPLATE_PROVIDER, route, 'route-root')
            self.assertIn((root, 'no-literal-schema'), gaps)
            self.assertIn((root, 'no-add-catalogue-projection'), gaps)
        self.assertFalse([gap for gap in self.result['gaps'] if gap['code'].startswith('contract-site')])
        for row in self.result['routes']:
            self.assertNotIn('missing', row['authoringRoutes'].values())
        for row in self.result['items']:
            for value in records(self.result, row).values():
                self.assertEqual((value['assessment'], value['implementation']), ('unassessed', 'unknown'))

    def test_contract_source_drift_is_detected(self):
        stored = json.loads(inventory.render(self.result))
        widened = self.source.replace("'default', 'units', 'target'), location)", "'default', 'units', 'target', 'probe'), location)")
        self.assertNotEqual(widened, self.source)
        problems = '\n'.join(inventory.compare(stored, inventory.build([inventory.TEMPLATE_PROVIDER], template_source=widened)))
        self.assertIn('new fields: workflow-template/schemaxis.workflow-template~11/entity:parameters/parameters/{parameter}/probe', problems)
        reworded = self.source.replace("'revision must be a positive integer'", "'revision must be one or more'")
        self.assertNotEqual(reworded, self.source)
        self.assertIn('changed routes', '\n'.join(inventory.compare(stored, inventory.build(
            [inventory.TEMPLATE_PROVIDER], template_source=reworded))))
        removed = self.source.replace("keys(output, ('operation', 'artifact', 'pointer', 'kind', 'units'), location)", 'pass')
        self.assertNotEqual(removed, self.source)
        gaps = {gap['code'] for gap in inventory.build([inventory.TEMPLATE_PROVIDER], template_source=removed)['gaps']}
        self.assertIn('contract-site-missing', gaps)
        added = self.source + textwrap.dedent('''
            def _probe(extra):
                keys(extra, ('alpha',), '$.probe')
            ''')
        gaps = {gap['code'] for gap in inventory.build([inventory.TEMPLATE_PROVIDER], template_source=added)['gaps']}
        self.assertIn('contract-site-unmapped', gaps)


class TemplateModuleDrift(unittest.TestCase):
    """Helpers and constants outside the mapped validators still change the contract (R1)."""

    MUTATIONS = (('identity regex', '[A-Za-z][A-Za-z0-9_.-]*', '[0-9][A-Za-z0-9_.-]*'),
                 ('binding scopes', "_SCOPES = ('dimensions', 'definitions', 'settings')", "_SCOPES = ('settings',)"),
                 ('parameter kinds', "_KINDS = ('number', 'integer', 'boolean', 'string', 'enum', 'vector')",
                  "_KINDS = ('number', 'integer', 'boolean', 'string', 'enum')"))

    def test_each_helper_or_constant_mutation_drifts(self):
        source = (ROOT / inventory.TEMPLATE_SOURCE).read_text()
        base = inventory.build([inventory.TEMPLATE_PROVIDER])
        for label, old, new in self.MUTATIONS:
            with self.subTest(mutation=label):
                self.assertEqual(source.count(old), 1, label)
                current = inventory.build([inventory.TEMPLATE_PROVIDER], template_source=source.replace(old, new))
                self.assertNotEqual(base['digest'], current['digest'])
                problems = '\n'.join(inventory.compare(base, current))
                self.assertIn('changed routes', problems)
                self.assertIn('changed items', problems)
        for row in base['routes']:
            self.assertEqual(row['validators'], sorted(row['validators']))
            self.assertTrue(row['moduleContract'])


class ContractDrift(unittest.TestCase):
    """Same-address semantic changes invalidate the inventory (F1)."""

    MUTATIONS = (('identity pattern', ('id',), 'pattern', '^[0-9]+$'),
                 ('command enum', ('onVisit', 'items'), 'enum', ['deleteEverything']),
                 ('bound', ('options', 'properties', 'size'), 'minimum', 5),
                 ('default', ('options', 'properties', 'size'), 'default', 2),
                 ('enum choices', ('options', 'properties', 'mode'), 'enum', ['fast', 'exact', 'rough']))

    def test_same_address_schema_mutations_drift_independently(self):
        base = fixture()
        for label, path, key, value in self.MUTATIONS:
            with self.subTest(mutation=label):
                current = fixture(node_mutation(fixture_schema(), path, key, value))
                self.assertNotEqual(base['digest'], current['digest'])
                self.assertTrue(any('changed fields' in problem for problem in inventory.compare(base, current)))
        prose = fixture(node_mutation(fixture_schema(), ('options', 'properties', 'size'), 'description', 'Reworded.'))
        self.assertEqual(inventory.compare(base, prose), [])

    def test_declaration_port_and_command_mutations_drift(self):
        base = fixture()
        declarations = fixture_declarations()
        declarations['thing']['inputs']['input']['multiple'] = True
        self.assertIn('changed items', '\n'.join(inventory.compare(base, fixture(declarations=declarations))))
        declarations = fixture_declarations()
        declarations['thing']['commands'] = {'deleteEverything': {'command': 'Delete', 'native': 'Delete'}}
        problems = '\n'.join(inventory.compare(base, fixture(declarations=declarations)))
        self.assertIn('dropped items: fixture/fixture~11/command:thing:reset', problems)
        self.assertIn('new items: fixture/fixture~11/command:thing:deleteEverything', problems)

    def test_identity_constraints_and_port_multiplicity_are_readable(self):
        result = fixture()
        surfaces = {row['key']: row for row in result['surfaces']}
        identity = surfaces['fixture/fixture~11/operation:thing/properties/nodes/items/properties/id']
        self.assertEqual(identity['constraints'], {'type': 'string', 'pattern': '^[A-Za-z][A-Za-z0-9_-]*$'})
        port = surfaces['fixture/fixture~11/operation:thing/properties/nodes/items/properties/inputs/properties/input']
        self.assertEqual(port['port'], {'native': 'Input', 'required': True, 'multiple': False})
        row = next(row for row in result['items'] if row['item'] == 'operation:thing')
        self.assertEqual(row['ports'], {'input': {'native': 'Input', 'required': True, 'multiple': False}})
        self.assertEqual(row['commands'], ['reset'])


class LiteralPayloads(unittest.TestCase):
    """Literal values keep every member, whatever its name; only schema annotations are prose (R2)."""

    PAYLOAD = {'label': 'A', 'units': 'm', 'title': 'T', 'description': 'D'}

    def with_caption(self, keyword, value):
        caption = {'type': 'object', 'description': 'Caption shown beside the output.'}
        caption[keyword] = value
        return fixture(node_mutation(fixture_schema(), ('options', 'properties'), 'caption', caption))

    def test_default_const_and_enum_members_named_like_prose_drift(self):
        for keyword in ('default', 'const', 'enum'):
            base = self.with_caption(keyword, [dict(self.PAYLOAD)] if keyword == 'enum' else dict(self.PAYLOAD))
            for member in self.PAYLOAD:
                changed = dict(self.PAYLOAD, **{member: self.PAYLOAD[member] + '2'})
                with self.subTest(keyword=keyword, member=member):
                    current = self.with_caption(keyword, [changed] if keyword == 'enum' else changed)
                    self.assertNotEqual(base['digest'], current['digest'])
                    self.assertTrue(any('changed fields' in problem for problem in inventory.compare(base, current)))

    def test_properties_named_like_prose_are_contract(self):
        schema = node_mutation(fixture_schema(), ('options', 'properties'), 'title', {'type': 'string'})
        base = fixture(schema)
        changed = fixture(node_mutation(fixture_schema(), ('options', 'properties'), 'title', {'type': 'number'}))
        self.assertTrue(any('changed fields' in problem for problem in inventory.compare(base, changed)))
        self.assertTrue(any('changed routes' in problem for problem in inventory.compare(base, changed)))

    def test_declaration_names_matching_prose_keys_are_contract(self):
        base_declarations = fixture_declarations()
        base_declarations['thing']['options'] = {'label': {'path': ['Label']}}
        base_declarations['thing']['inputs']['units'] = {'native': 'Units', 'required': False, 'multiple': False}
        base = fixture(declarations=base_declarations)
        option = copy.deepcopy(base_declarations)
        option['thing']['options']['label']['path'] = ['Caption']
        port = copy.deepcopy(base_declarations)
        port['thing']['inputs']['units']['multiple'] = True
        for label, declarations in (('option named label', option), ('input named units', port)):
            with self.subTest(change=label):
                current = fixture(declarations=declarations)
                self.assertNotEqual(base['digest'], current['digest'])
                self.assertIn('changed items', '\n'.join(inventory.compare(base, current)))

    def test_schema_annotations_alone_do_not_drift(self):
        base = self.with_caption('default', dict(self.PAYLOAD))
        for keyword, text in (('description', 'Reworded caption explanation.'), ('title', 'Caption'),
                              ('$comment', 'maintainer note')):
            with self.subTest(annotation=keyword):
                schema = node_mutation(fixture_schema(), ('options', 'properties'), 'caption',
                                       {'type': 'object', 'description': 'Caption shown beside the output.',
                                        'default': dict(self.PAYLOAD), keyword: text})
                self.assertEqual(inventory.compare(base, fixture(schema)), [])

    def test_catalogue_entries_keep_literal_schema_values(self):
        entry = {'id': 'operation:thing', 'title': 'Thing', 'description': 'Explained.', 'at': '/nodes/-',
                 'schema': {'properties': {'caption': {'default': dict(self.PAYLOAD), 'description': 'Caption.'}}}}
        reworded = copy.deepcopy(entry)
        reworded['description'] = 'Explained differently.'
        reworded['schema']['properties']['caption']['description'] = 'Another caption.'
        self.assertEqual(inventory.fingerprint(inventory.entry_semantic(entry)),
                         inventory.fingerprint(inventory.entry_semantic(reworded)))
        relabelled = copy.deepcopy(entry)
        relabelled['schema']['properties']['caption']['default']['label'] = 'B'
        self.assertNotEqual(inventory.fingerprint(inventory.entry_semantic(entry)),
                            inventory.fingerprint(inventory.entry_semantic(relabelled)))


OPTIONS = '/properties/nodes/items/properties/options'


def guided(records):
    """Fixture guidance holding field records for the fixture route."""
    return {'operations': {}, 'routes': {'fixture/1': {'fields': copy.deepcopy(records)}}}


def edited(records, address, key, value):
    """A copy of the field records with one record member replaced."""
    result = copy.deepcopy(records)
    result[address][key] = value
    return result


class GuidanceRecords(unittest.TestCase):
    """Field control, authoring and file records are contract, not prose (R3)."""

    RECORDS = {
        OPTIONS: {'status': 'reviewed', 'explanation': 'Settings of the thing.',
                  'control': {'kind': 'line', 'start': 'start', 'end': 'end'}},
        OPTIONS + '/properties/size': {'status': 'reviewed', 'explanation': 'Size of the thing.',
                                       'control': {'kind': 'blocks', 'input': 'input'},
                                       'fileExtensions': ['.foam'],
                                       'authoring': {'naming': {'path': '/options/size', 'style': 'literal'}}},
        OPTIONS + '/properties/mode': {'status': 'reviewed', 'explanation': 'Mode of the thing.',
                                       'control': {'kind': 'reader-selection', 'field': 'regions'}},
    }

    def test_control_targets_authoring_and_files_drift_with_the_same_kind(self):
        base = fixture(guidance=guided(self.RECORDS))
        size = OPTIONS + '/properties/size'
        changes = (('line endpoints', OPTIONS, 'control', {'kind': 'line', 'start': 'end', 'end': 'start'}),
                   ('blocks input', size, 'control', {'kind': 'blocks', 'input': 'seeds'}),
                   ('reader field', OPTIONS + '/properties/mode', 'control',
                    {'kind': 'reader-selection', 'field': 'cellArrays'}),
                   ('field authoring', size, 'authoring', {'naming': {'path': '/options/size', 'style': 'lastSegment'}}),
                   ('file extensions', size, 'fileExtensions', ['.foam', '.OpenFOAM']))
        for label, address, key, value in changes:
            with self.subTest(change=label):
                current = fixture(guidance=guided(edited(self.RECORDS, address, key, value)))
                self.assertNotEqual(base['digest'], current['digest'])
                problems = '\n'.join(inventory.compare(base, current))
                self.assertIn('changed fields: fixture/fixture~11/operation:thing' + address, problems)
                self.assertIn('changed routes', problems)

    def test_explanation_only_guidance_does_not_drift(self):
        base = fixture(guidance=guided(self.RECORDS))
        reworded = edited(self.RECORDS, OPTIONS + '/properties/mode', 'explanation', 'How the thing runs.')
        reworded = edited(reworded, OPTIONS, 'pitfalls', ['Choose endpoints inside the domain.'])
        self.assertEqual(inventory.compare(base, fixture(guidance=guided(reworded))), [])

    def test_item_rows_show_verbatim_controls_and_authoring(self):
        row = next(row for row in fixture(guidance=guided(self.RECORDS))['items'] if row['item'] == 'operation:thing')
        self.assertEqual(row['guides'][OPTIONS + '/properties/mode'],
                         {'control': {'kind': 'reader-selection', 'field': 'regions'}})
        self.assertEqual(row['guides'][OPTIONS + '/properties/size']['authoring'],
                         {'naming': {'path': '/options/size', 'style': 'literal'}})

    def test_real_foam_reader_control_target_switch_drifts(self):
        guidance = studio_guidance.load('paraview')
        switched = copy.deepcopy(guidance)
        address = '/$defs/options-foam/properties/regions'
        record = switched['routes']['schemaxis/1']['fields'][address]
        self.assertEqual(record['control'], {'kind': 'reader-selection', 'field': 'regions'})
        record['control'] = {'kind': 'reader-selection', 'field': 'cellArrays'}
        studio_guidance.validate_record(record)
        results = []
        for value in (guidance, switched):
            with patch.object(studio_guidance, 'load', return_value=value), \
                    patch.object(inventory, 'load', return_value=value):
                results.append(inventory.build(['paraview']))
        problems = '\n'.join(inventory.compare(*results))
        self.assertNotEqual(results[0]['digest'], results[1]['digest'])
        self.assertIn('changed fields: paraview/schemaxis~11/operation:foam' + address, problems)
        self.assertIn('changed items: paraview/schemaxis~11/operation:foam', problems)
        foam = next(row for row in results[1]['items'] if row['key'] == 'paraview/schemaxis~11/operation:foam')
        self.assertEqual(foam['guides'][address]['control']['field'], 'cellArrays')


class IdentityPolicyDrift(unittest.TestCase):
    """The inventory records projected policy data in addition to schema/declarations."""

    def test_selector_name_constraint_and_shape_changes_invalidate_item_and_route(self):
        policy = {'version': 'schemaxis.authoring-references/1',
                  'identities': [{'nameSchema': {'type': 'string', 'pattern': '^[A-Z]+$'}}],
                  'references': [{'path': ['members'], 'shape': 'list'}],
                  'projection': {'node': {'operations': {'thing': {'input': {'multiple': False, 'kind': 'data'}}},
                                          'writers': {}}}}
        base = fixture(identity_policy=policy)
        changes = (lambda p: p['references'][0].update(path=['otherMembers']),
                   lambda p: p['references'][0].update(shape='scalar'),
                   lambda p: p['identities'][0]['nameSchema'].update(pattern='^[a-z]+$'))
        for change in changes:
            modified = copy.deepcopy(policy); change(modified)
            current = fixture(identity_policy=modified)
            self.assertNotEqual(base['digest'], current['digest'])
            differences = '\n'.join(inventory.compare(base, current))
            self.assertIn('changed routes', differences)
            self.assertIn('changed items: fixture/fixture~11/operation:thing', differences)
        row = next(row for row in base['items'] if row['item'] == 'operation:thing')
        self.assertTrue(row['identityReferences']['node']['target'])
        self.assertEqual(records(base, row)['renaming']['implementation'], 'unknown')


class NativeCommands(unittest.TestCase):
    """Every declared native command has its own row (F4)."""

    @classmethod
    def setUpClass(cls):
        cls.result = inventory.build(builtins())

    def test_commands_reconcile_with_every_provider_declaration(self):
        expected = set()
        for name in builtins():
            meta = registry.metadata(name)
            for operation, declaration in registry.declarations(name).items():
                for command in declaration.get('commands') or {}:
                    expected.add(inventory.item_key(name, meta['version'], 'command:' + operation + ':' + command))
        rows = {row['key']: row for row in self.result['items'] if row['kind'] == 'native-command'}
        self.assertTrue(expected)
        self.assertEqual(set(rows), expected)
        self.assertEqual(self.result['counts']['commands'], len(expected))
        items = {row['key'] for row in self.result['items']}
        for key, row in rows.items():
            self.assertIn(row['parent'], items)
            self.assertEqual(row['projection'], 'schema-enumerated')
            self.assertTrue(row['command']['native'])
            self.assertTrue(row['evidence'])
            for name, value in records(self.result, row).items():
                if name == 'multiMode':
                    self.assertEqual((value['implementation'], value['classification']),
                                     ('not-applicable', 'sequential'))
                else:
                    self.assertEqual((value['assessment'], value['implementation'], value['review'], value['qualification']),
                                     ('unassessed', 'unknown', 'not-reviewed', 'not-qualified'))
        self.assertIn('paraview/schemaxis~11/command:pvFidesReader:PrepareNextStep', rows)
        self.assertFalse([gap for gap in self.result['gaps'] if gap['code'].startswith('command-')])


class Drift(unittest.TestCase):
    def build(self, providers=('sympy',)):
        return inventory.build(list(providers))

    def test_regeneration_is_byte_identical(self):
        self.assertEqual(inventory.render(self.build()), inventory.render(self.build()))

    def test_dropped_and_new_operations_routes_and_fields_are_reported(self):
        stored = json.loads(inventory.render(self.build()))
        declarations = registry.declarations('sympy')
        added = {**declarations, 'inventoryPhantom': next(iter(declarations.values()))}
        with patch.object(registry, 'declarations', return_value=added):
            current = self.build()
        problems = '\n'.join(inventory.compare(stored, current))
        self.assertIn('new items: sympy/schemaxis.sympy~11/operation:inventoryPhantom', problems)
        phantom = next(row for row in current['items'] if row['item'] == 'operation:inventoryPhantom')
        self.assertEqual(phantom['projection'], 'missing')
        self.assertIn('declaration-not-projected', phantom['gaps'])
        self.assertIn('dropped items', '\n'.join(inventory.compare(current, stored)))
        route = registry.metadata('sympy')['routes']['schemaxis.sympy/1']['schema']
        original = registry.binding(route)
        binding = registry.binding
        with patch.object(registry, 'binding', side_effect=Substitute(route, ExtendedSchema(original), binding)):
            widened = self.build()
        problems = '\n'.join(inventory.compare(stored, widened))
        self.assertIn('new fields: sympy/schemaxis.sympy~11/document:inventoryProbe/properties/inventoryProbe', problems)
        self.assertIn('counts differ', problems)
        meta = copy.deepcopy(registry.ADAPTORS['sympy'])
        meta['routes']['schemaxis.sympy/9'] = copy.deepcopy(meta['routes']['schemaxis.sympy/1'])
        with patch.dict(registry.ADAPTORS, {'sympy': meta}):
            rerouted = self.build()
        self.assertIn('new routes: sympy/schemaxis.sympy~19', '\n'.join(inventory.compare(stored, rerouted)))

    def test_changed_rows_are_reported(self):
        stored = json.loads(inventory.render(self.build()))
        current = copy.deepcopy(stored)
        current['items'][0]['projection'] = 'missing'
        self.assertTrue(any(problem.startswith('1 changed items') for problem in inventory.compare(stored, current)))


class Ledger(unittest.TestCase):
    def build(self, entries):
        return inventory.build(['gmsh'], ledger={'version': inventory.LEDGER_VERSION, 'entries': entries}, root=ROOT)

    def test_invalid_or_stale_entries_are_refused(self):
        key = 'gmsh/schemaxis.gmsh~11/operation:' + next(iter(registry.declarations('gmsh')))
        for entries in ({'gmsh/schemaxis.gmsh~11/operation:absent': {'naming': {'assessment': 'assessed'}}},
                        {key: {'naming': {'assessment': 'complete'}}},
                        {key: {'naming': {'implementation': 'not-applicable', 'rationale': None}}},
                        {key: {'multiMode': {'implementation': 'not-applicable'}}},
                        {key: {'naming': {'tests': ['tests/unit/test_absent_inventory_case.py']}}},
                        {key: {'naming': {'unexpected': 'value'}}},
                        {key: {'naming': {'entryPoint': 'not a binding'}}},
                        {key: {'everything': {}}}):
            with self.subTest(entries=entries), self.assertRaises((ValueError, TypeError)):
                self.build(entries)

    def test_credit_must_name_the_exact_route(self):
        key = 'gmsh/schemaxis.gmsh~11/operation:' + next(iter(registry.declarations('gmsh')))
        for record in ({'implementation': 'implemented'}, {'qualification': 'recorded-prior'},
                       {'implementation': 'partial', 'routes': ['schemaxis.workflow-design/2']}):
            with self.subTest(record=record), self.assertRaises(ValueError):
                self.build({key: {'renaming': record}})
        result = self.build({key: {'renaming': {'implementation': 'partial', 'routes': ['schemaxis.gmsh/1']}}})
        row = next(row for row in result['items'] if row['key'] == key)
        self.assertEqual(inventory.record(result, row, 'renaming')['implementation'], 'partial')

    def test_surfaces_accept_all_four_dimensions_independently(self):
        result = self.build({})
        surface = next(row for row in result['surfaces'] if row['kind'] == 'identity')
        entry = {'naming': {'assessment': 'assessed', 'rationale': 'Fixture naming judgement.'},
                 'renaming': {'assessment': 'insufficient-evidence'},
                 'multiMode': {'classification': 'collection'},
                 'subset': {'assessment': 'blocked'}}
        updated = self.build({surface['key']: entry})
        row = next(row for row in updated['surfaces'] if row['key'] == surface['key'])
        values = records(updated, row)
        self.assertEqual(values['naming']['assessment'], 'assessed')
        self.assertEqual(values['renaming']['assessment'], 'insufficient-evidence')
        self.assertEqual(values['multiMode']['classification'], 'collection')
        self.assertEqual(values['subset']['assessment'], 'blocked')
        for value in values.values():
            self.assertEqual((value['implementation'], value['review'], value['qualification']),
                             ('unknown', 'not-reviewed', 'not-qualified'))

    def test_nested_units_accept_independent_dimension_records(self):
        result = self.build({})
        nested = next(row for row in result['items'] if row['kind'] in inventory.NESTED)
        parent = nested['parent']
        updated = self.build({nested['key']: {'naming': {'assessment': 'assessed', 'rationale': 'Fixture.'}}})
        rows = {row['key']: row for row in updated['items']}
        self.assertEqual(inventory.record(updated, rows[nested['key']], 'naming')['assessment'], 'assessed')
        self.assertEqual(inventory.record(updated, rows[nested['key']], 'renaming')['assessment'], 'unassessed')
        self.assertNotEqual(inventory.record(updated, rows[parent], 'naming').get('rationale'), 'Fixture.')

    def test_workflow_rename_credit_belongs_only_to_design_version_two(self):
        ledger = inventory.load_ledger(ROOT)['entries']
        workflow = ledger['workflow/schemaxis.workflow~11/document:operations']['renaming']
        self.assertEqual(workflow['implementation'], 'not-implemented')
        self.assertNotIn('routes', workflow)
        design = ledger['workflow-design/schemaxis.workflow-design~12/entity:workflow-operations']['renaming']
        self.assertEqual((design['implementation'], design['routes']), ('partial', [workflow_design.VERSION_2]))
        older = ledger['workflow-design/schemaxis.workflow-design~11/entity:workflow-operations']['renaming']
        self.assertEqual(older['implementation'], 'not-implemented')

    def test_entry_points_accept_only_their_credited_routes(self):
        """Each credited record's route is its evidence scope, exercised on its own operation.

        The mapping is closed: a new rename credit needs its own fixture. It does not
        claim the generic preview cannot serve another record's route.
        """
        from schemaxis.storage import digest
        missing_csv = '/nonexistent-schemaxis-ledger/data.csv'
        typed = [{'name': 'Label', 'kind': 'text'}, {'name': 'Mass', 'kind': 'number'}]
        rename_fixtures = {
            'paraview/schemaxis~11/operation:extractBlock': ('schemaxis/1', {}, False),
            'calc/schemaxis.calc~11/operation:fromRows': (
                'schemaxis.calc/1', {'options': {'columns': ['x'], 'rows': [[1], [2]]}}, True),
            'calc/schemaxis.calc~11/operation:readCSV': ('schemaxis.calc/1', {'options': {'file': missing_csv}}, True),
            'calc/schemaxis.calc~11/operation:fromTypedRows': (
                'schemaxis.calc/1', {'options': {'columns': typed, 'rows': [['a', 1], ['b', 2]]}}, True),
            'calc/schemaxis.calc~11/operation:readTypedCSV': (
                'schemaxis.calc/1', {'options': {'file': missing_csv, 'columns': typed}}, True)}
        documents = {workflow_design.VERSION_2: workflow_design.create(example()),
                     workflow_design.VERSION: {'version': workflow_design.VERSION, 'workflow': example(),
                                               'connections': [], 'controllers': {}},
                     'schemaxis.workflow/1': example()}
        renamed_keys, design_credited = set(), 0
        for key, entry in inventory.load_ledger(ROOT)['entries'].items():
            for value in entry.values():
                if not isinstance(value, dict) or 'entryPoint' not in value:
                    continue
                module, _, name = value['entryPoint'].partition(':')
                function = getattr(importlib.import_module(module), name)
                if value['entryPoint'] == 'schemaxis.identity_rename:rename_identity':
                    if key in SHOTCUT_LOCAL:
                        from test_shotcut_local_identity import ROUTE, TARGET, timeline
                        candidate = timeline()
                        result = function(candidate, TARGET, 'Opening-1', digest(candidate))
                        self.assertEqual(candidate, timeline())
                        self.assertEqual(result['input'], timeline('Opening-1'))
                        self.assertEqual(value['routes'], [ROUTE])
                        self.assertEqual(value['implementation'], 'partial')
                        self.assertEqual(value['qualification'], 'not-qualified')
                        self.assertEqual(result['identityChanges'][0]['route'], ROUTE)
                        renamed_keys.add(key)
                        continue
                    self.assertIn(key, rename_fixtures)
                    route, node, plans = rename_fixtures[key]
                    self.assertEqual(value['routes'], [route])
                    self.assertEqual(value['implementation'], 'partial')
                    self.assertEqual(value['qualification'], 'not-qualified')
                    operation = key.rsplit('operation:', 1)[1]
                    document = {'version': route, 'nodes': [{'id': 'A', 'filter': operation, **copy.deepcopy(node)}]}
                    before = copy.deepcopy(document)
                    with self.subTest(key=key):
                        result = function(document, '/nodes/0/id', 'B', digest(document))
                        self.assertEqual(before, document)
                        expected = copy.deepcopy(document)
                        expected['nodes'][0]['id'] = 'B'
                        self.assertEqual(expected, result['input'])
                        self.assertEqual(['/nodes/0/id'], result['changedPointers'])
                        self.assertEqual(route, result['identityChanges'][0]['route'])
                        if plans:
                            with patch('schemaxis.adaptors.calc.adaptor.source_bytes',
                                       side_effect=AssertionError('CSV source was read')):
                                original, renamed = registry.plan(document), registry.plan(result['input'])
                            self.assertEqual(('B', operation), (renamed['nodes'][0]['id'], renamed['nodes'][0]['filter']))
                            renamed['nodes'][0]['id'] = 'A'
                            self.assertEqual(original, renamed)
                    renamed_keys.add(key)
                    continue
                self.assertEqual(value['entryPoint'], 'schemaxis.workflow_design:rename_operation')
                for route, document in documents.items():
                    with self.subTest(key=key, route=route):
                        if route in value['routes']:
                            renamed = function(document, 'samples', 'source')
                            self.assertEqual(renamed['workflow']['operations'][0]['id'], 'source')
                            design_credited += 1
                        else:
                            with self.assertRaises(SchemaxisError) as caught:
                                function(document, 'samples', 'source')
                            self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_VERSION')
        self.assertEqual(set(rename_fixtures) | set(SHOTCUT_LOCAL), renamed_keys)
        self.assertEqual(1, design_credited)
        unsupported = {'version': 'schemaxis.gmsh/1', 'nodes': [{'id': 'A', 'operation': 'point'}]}
        before = copy.deepcopy(unsupported)
        from schemaxis.identity_rename import rename_identity
        with self.assertRaises(SchemaxisError) as caught:
            rename_identity(unsupported, '/nodes/0/id', 'B', digest(unsupported))
        self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_IDENTITY')
        self.assertEqual(before, unsupported)


class ExternalPlugins(unittest.TestCase):
    def test_absent_and_faulty_plugins_never_qualify(self):
        fault = Fault('INVALID_ADAPTOR', 'fixture plugin failed', 'entry point schemaxis.adaptors:fixture',
                      'discovery', observed={'id': 'fixture'})
        with patch.object(registry, 'PLUGIN_FAULTS', [fault]):
            result = inventory.build(scope='external')
        self.assertEqual(result['items'], [])
        self.assertEqual([(gap['key'], gap['code']) for gap in result['gaps']],
                         [('fixture/unregistered/route-root', 'plugin-excluded')])
        self.assertEqual(result['ledgerEntries'], 0)

    def test_installed_plugins_are_owner_handoffs_outside_builtin_scope(self):
        meta = {**copy.deepcopy(registry.ADAPTORS['sympy']), 'source': 'plugin:fixture-dist'}
        with patch.dict(registry.ADAPTORS, {'fixtureplugin': meta}):
            builtin = inventory.build(['fixtureplugin', 'sympy'])
            external = inventory.build(['fixtureplugin', 'sympy'], scope='external')
        self.assertEqual({row['adaptor'] for row in builtin['items']}, {'sympy'})
        self.assertEqual({row['adaptor'] for row in external['items']}, {'fixtureplugin'})
        self.assertEqual({row['scope'] for row in external['routes']}, {'external-handoff'})
        for row in external['items']:
            for value in records(external, row).values():
                self.assertIn(value['qualification'], ('not-qualified', 'not-required'))
                self.assertNotEqual(value['assessment'], 'assessed')


if __name__ == '__main__':
    unittest.main()
