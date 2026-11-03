# Copyright (C) 2026 David L F Gaden
"""Reusable host admission contract, including incomplete third-party adaptors."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.core.faults import SchemaxisError
from schemaxis.readiness import Audit, PROTOCOL, enforce, report

ROOT = Path(__file__).resolve().parents[2]


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root/'fixtureapp'
        self.folder.mkdir()
        self.manifest = json.loads((ROOT/'tests/fixtures/adaptor_plugin/adaptor.json').read_text())
        self.manifest['capabilities'] = 'schemaxis.adaptors.fixtureapp.adaptor:catalogue'
        self.manifest['executionCapabilities'] = {'mpi': False}
        self.manifest['routes']['fixtureapp/1']['compose'] = False
        self.module_name = 'schemaxis.adaptors.fixtureapp.adaptor'
        spec = importlib.util.spec_from_file_location(self.module_name, ROOT/'tests/fixtures/adaptor_plugin/adaptor.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module.catalogue = lambda: {'operations': {'emit': {'purpose': 'Write declared text for host extension checks.'}}}
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, {self.module_name: self.module}).start()
        patch.object(registry, 'ADAPTORS', {'fixtureapp': self.manifest}).start()
        patch('schemaxis.readiness.files', return_value=self.root).start()
        patch.object(registry, 'adaptor_files', side_effect=lambda provider: self.root/provider).start()
        for name in ('guide.md', 'conformance.py', 'acceptance.py'):
            (self.root/name).write_text('# Fixture\n')
        self.document = {'version': 'fixtureapp/1', 'nodes': [{'id': 'hello', 'filter': 'emit'}]}
        self.invalid = copy.deepcopy(self.document)
        self.invalid['nodes'][0]['filter'] = 'unsupported'
        self.bundle = {'version': PROTOCOL, 'routes': {'fixtureapp/1': {
            'guide': 'guide.md#fixture',
            'context': {key: 'Fixture ' + key for key in ('purpose', 'assumptions', 'constraints', 'inspection', 'recovery')},
            'examples': [
                {'id': 'valid', 'document': self.document, 'expect': 'valid'},
                {'id': 'invalid', 'document': self.invalid, 'expect': 'invalid', 'fault': 'UNKNOWN_FILTER'}],
            'conformance': ['conformance.py'], 'acceptance': ['acceptance.py'],
            'profiles': {'workflow': {'scope': 'Test-only text receipts.', 'references': ['conformance.py']}}
        }}}
        self.write_bundle()

    def write_bundle(self):
        (self.folder/'readiness.json').write_text(json.dumps(self.bundle))

    def audit(self):
        return report(root=self.root)

    def checks(self):
        return {c['code']: c for c in self.audit()['routes'][0]['checks']}

    def test_complete_structure_is_never_native_qualification(self):
        result = enforce(self.audit())
        row = result['routes'][0]
        self.assertEqual(row['structural'], 'complete')
        self.assertEqual(row['implementation'], {'entryPoints': 'present', 'behaviour': 'unreviewed'})
        self.assertEqual(row['nativeQualification'], 'unknown')
        self.assertEqual(row['runtimeAvailability'], 'unknown')
        self.assertGreater(row['counts']['unknown'], 0)
        self.assertEqual(row['counts']['requiredUnknown'], 0)
        self.assertEqual(row['profiles']['mpi']['declaration'], 'unsupported')
        self.assertEqual(len({c['id'] for c in row['checks']}), len(row['checks']))

    def test_missing_and_malformed_bundles_preserve_routing(self):
        (self.folder/'readiness.json').unlink()
        self.assertEqual(self.checks()['delivery.bundle']['status'], 'fail')
        self.assertEqual(registry.plan(self.document), self.document)
        with self.assertRaises(SchemaxisError) as caught:
            enforce(self.audit())
        self.assertEqual(caught.exception.fault.code, 'ADAPTOR_NOT_READY')
        self.assertIn('report', caught.exception.fault.observed)
        for value in ('{broken', '[]', '{"version": "future", "routes": {}}'):
            (self.folder/'readiness.json').write_text(value)
            self.assertEqual(self.checks()['delivery.bundle']['status'], 'fail')

    def test_semantically_invalid_examples_and_exact_faults(self):
        examples = self.bundle['routes']['fixtureapp/1']['examples']
        examples[0]['document'] = self.invalid
        examples[1]['fault'] = 'INVALID_DOCUMENT'
        self.write_bundle()
        checks = self.checks()
        self.assertEqual(checks['examples.valid']['status'], 'fail')
        self.assertEqual(checks['examples.invalid']['status'], 'fail')
        examples[1]['document'] = self.document
        self.write_bundle()
        self.assertEqual(self.checks()['examples.invalid']['status'], 'fail')

    def test_example_route_and_parse_failures_cannot_count_as_expected_faults(self):
        example = self.bundle['routes']['fixtureapp/1']['examples'][1]
        example.update(document={'version': 'other/1'}, fault='UNSUPPORTED_VERSION')
        self.write_bundle()
        self.assertEqual(self.checks()['examples.invalid']['status'], 'fail')
        (self.root/'invalid.json').write_text('{broken')
        del example['document']
        example.update(reference='invalid.json', fault='INVALID_JSON')
        self.write_bundle()
        self.assertEqual(self.checks()['examples.invalid']['status'], 'fail')

    def test_missing_contract_and_profile_inconsistency(self):
        self.module.verify = None
        self.manifest['executionCapabilities']['mpi'] = True
        entry = self.bundle['routes']['fixtureapp/1']
        entry['profiles']['composition'] = {'scope': 'not actually supported', 'references': ['guide.md']}
        self.write_bundle()
        checks = self.checks()
        for code in ('contracts.verify', 'profile.mpi.binding', 'profile.mpi', 'profile.composition'):
            self.assertEqual(checks[code]['status'], 'fail', code)
        self.manifest['routes']['fixtureapp/1']['workflow'] = False
        self.assertEqual(self.checks()['profiles.artifacts']['status'], 'fail')

    def test_broken_context_and_example_links_and_unknown_operation_metadata(self):
        self.module.catalogue = lambda: {'references': ['missing.md'], 'operations': {'emit': {
            'purpose': 'Write text', 'examples': [{'purpose': 'Missing example', 'reference': 'missing.json'}]}}}
        checks = self.checks()
        self.assertEqual(checks['context.reference.0']['status'], 'fail')
        self.assertEqual(checks['context.example.emit.0.reference']['status'], 'fail')
        self.module.catalogue = lambda: {'operations': {'invented': {'purpose': 'Not declared'}}}
        self.assertEqual(self.checks()['context.metadata']['status'], 'fail')

    def test_no_native_execution_and_no_probes(self):
        with patch('schemaxis.native_command.execute', side_effect=AssertionError('native execution')), \
             patch('subprocess.Popen', side_effect=AssertionError('process probe')), \
             patch('urllib.request.urlopen', side_effect=AssertionError('network')):
            enforce(self.audit())

    def test_links_are_bounded_and_external_references_are_not_fetched(self):
        audit = Audit(self.root)
        self.assertEqual(audit.link('../escape', 'escape'), 'fail')
        self.assertEqual(audit.link('/etc/passwd', 'absolute'), 'fail')
        (self.root/'escape').symlink_to('/etc/passwd')
        self.assertEqual(audit.link('escape', 'symlink'), 'fail')
        self.assertEqual(audit.link('guide.md#missing', 'anchor'), 'fail')
        self.assertEqual(audit.link('https://example.org/manual', 'external'), 'unknown')
        self.assertFalse(audit.checks[-1]['required'])
        self.assertEqual(audit.link('https://example.org/example.json', 'fixture', local=True), 'fail')
        (self.root/'source.py').write_text('def plan():\n    pass\n')
        self.assertEqual(audit.link('source.py:plan', 'symbol'), 'pass')
        self.assertEqual(audit.link('source.py:missing', 'missing-symbol'), 'fail')
        self.assertEqual(audit.link('https://[broken', 'malformed-url'), 'fail')

    def test_installed_wheel_does_not_pass_unresolved_required_delivery(self):
        with patch('schemaxis.readiness.repository_root', return_value=None):
            result = report()
        self.assertFalse(result['structurallyComplete'])
        self.assertGreater(result['routes'][0]['counts']['requiredUnknown'], 0)

    def test_unknown_route_and_duplicate_fixture_ids_fail(self):
        self.bundle['routes']['other/1'] = {}
        self.write_bundle()
        self.assertEqual(self.checks()['delivery.bundle']['status'], 'fail')
        del self.bundle['routes']['other/1']
        self.bundle['routes']['fixtureapp/1']['examples'][1]['id'] = 'valid'
        self.write_bundle()
        self.assertEqual(self.checks()['examples.identity.1']['status'], 'fail')

    def test_malformed_nested_metadata_is_reported_without_aborting(self):
        entry = self.bundle['routes']['fixtureapp/1']
        entry['profiles']['mpi'] = None
        self.manifest['executionCapabilities']['mpi'] = 'yes'
        entry['examples'] = [None, {'id': 'null-reference', 'reference': None},
                             {'id': 'missing-document', 'document': None}]
        self.write_bundle()
        checks = self.checks()
        for code in ('profiles.flags', 'profile.mpi', 'examples.null-reference', 'examples.missing-document'):
            self.assertEqual(checks[code]['status'], 'fail', code)

    def test_mpi_modes_are_claims_and_conflicting_false_flags_fail(self):
        self.manifest['executionCapabilities'] = {'modes': ['serial', 'mpi']}
        result = self.audit()
        self.assertEqual(result['routes'][0]['profiles']['mpi']['declaration'], 'declared')
        self.assertEqual(self.checks()['profile.mpi.binding']['status'], 'fail')
        self.manifest['executionCapabilities']['mpi'] = False
        self.assertEqual(self.checks()['profiles.mpi-conflict']['status'], 'fail')


class InstalledReadinessTests(unittest.TestCase):
    def test_public_cli_gate_and_provider_selection(self):
        from schemaxis.__main__ import main
        with patch.object(sys, 'argv', ['schemaxis', 'readiness', '--app', 'octave', '--app', 'ffmpeg', '--check']):
            result = main()
        self.assertEqual({row['provider'] for row in result['routes']}, {'octave', 'ffmpeg'})
        self.assertTrue(result['structurallyComplete'])
        with patch.object(sys, 'argv', ['schemaxis', 'readiness', '--app', 'calc', '--check']), \
             patch('schemaxis.adaptors.calc.capabilities.catalogue', return_value={}):
            with self.assertRaises(SchemaxisError) as caught:
                main()
        self.assertEqual(caught.exception.fault.code, 'ADAPTOR_NOT_READY')

    def test_bad_provider_context_does_not_hide_other_routes(self):
        from importlib import import_module
        module = import_module('schemaxis.adaptors.octave.capabilities')
        with patch.object(module, 'catalogue', return_value={'operations': {'invented': {}}}):
            result = report(['octave', 'ffmpeg'])
        rows = {row['provider']: row for row in result['routes']}
        self.assertEqual(rows['octave']['structural'], 'incomplete')
        self.assertEqual(rows['ffmpeg']['structural'], 'complete')

    def test_every_route_is_reported_with_stable_identifiers_and_no_native_imports(self):
        script = '''
import importlib.abc, json, sys
attempts = []
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'bpy', 'paraview', 'vtk', 'vtkmodules', 'FreeCAD', 'FreeCADGui', 'Part', 'qgis', 'gmsh', 'cantera'}:
            attempts.append(fullname)
            raise AssertionError('Native import: ' + fullname)
sys.meta_path.insert(0, NoNative())
def no_process(event, args):
    if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.fork', 'os.exec', 'socket.connect'}:
        attempts.append(event)
        raise AssertionError('Readiness attempted external work: ' + event)
sys.addaudithook(no_process)
from schemaxis.readiness import report
from schemaxis.adaptors.registry import routes
r = report()
assert {row['documentVersion'] for row in r['routes']} == set(routes())
ids = [c['id'] for row in r['routes'] for c in row['checks']]
assert len(ids) == len(set(ids))
assert all(c['message'] and c['sources'] and (c['status'] != 'fail' or c['recovery']) for row in r['routes'] for c in row['checks'])
assert all(row['nativeQualification'] == 'unknown' for row in r['routes'])
expected_non_node = {version for version, (_, route) in routes().items() if route.get('graphEditing', True) is False}
assert {row['documentVersion'] for row in r['routes'] if row['documentModel'] == 'non-node'} == expected_non_node
assert r == report()
assert not attempts, attempts
print(len(r['routes']))
'''
        completed = subprocess.run([sys.executable, '-c', script], cwd=ROOT, text=True, capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        from schemaxis.adaptors.registry import routes
        self.assertEqual(completed.stdout.strip(), str(len(routes())))


if __name__ == '__main__':
    unittest.main()
