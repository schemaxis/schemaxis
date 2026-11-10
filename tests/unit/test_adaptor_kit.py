# Copyright (C) 2026 David L F Gaden
"""Reusable development contracts, conformance and scoped receipt semantics."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptor_delivery import (context, route_materials, validate_development,
                                       source_digest, case_document, case_document_digest, qualification_status)
from schemaxis.adaptor_conformance import host, assertions, integrity, register
from schemaxis.artifacts import file_digest
from schemaxis.capabilities import response_bytes, digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'schemaxis.octave/1'


class AdaptorKitTests(unittest.TestCase):
    def setUp(self):
        self.provider, self.route, self.entry = route_materials(VERSION)

    def test_bounded_context_keeps_exact_materials_and_revision_checks(self):
        result = context(VERSION, pointer='/materials/development/data', max_bytes=2048)
        self.assertLessEqual(response_bytes(result), 2048)
        exact = context(VERSION, pointer='/materials/development/data/0', max_bytes=8192)
        self.assertEqual(exact['value'], self.entry['development']['data'][0])
        self.assertEqual(exact['revision'], result['revision'])
        with self.assertRaises(SchemaxisError) as caught:
            context(VERSION, revision='stale')
        self.assertEqual(caught.exception.fault.code, 'STALE_OBSERVATION')

    def test_optional_decisions_cannot_contradict_authoritative_flags(self):
        for feature in ('workflow', 'composition', 'mpi'):
            entry = copy.deepcopy(self.entry)
            decision = entry['development']['features'][feature]
            decision['status'] = 'unsupported' if decision['status'] == 'supported' else 'supported'
            with self.subTest(feature=feature), self.assertRaises(SchemaxisError):
                validate_development(VERSION, entry)

    def test_missing_materials_duplicate_cases_and_unsafe_assertions_fail(self):
        edits = [lambda d: d.pop('data'),
                 lambda d: d['features'].pop('conversion'),
                 lambda d: d['cases'][1].update(id=d['cases'][0]['id']),
                 lambda d: d['cases'][1].update(edits=[]),
                 lambda d: d['cases'][0]['checks'][0].update(file='../escape.csv'),
                 lambda d: d['cases'][0]['checks'][0].update(relative=float('nan')),
                 lambda d: d['authoring'].update(model='document'),
                 lambda d: d['inspection'][0].update(panel='remote-code')]
        for change in edits:
            entry = copy.deepcopy(self.entry)
            change(entry['development'])
            with self.assertRaises(SchemaxisError):
                validate_development(VERSION, entry)

    def test_cases_reuse_the_shared_patch_semantics_without_mutating_examples(self):
        before = copy.deepcopy(self.entry)
        baseline, variant = [case_document(self.entry, c, ROOT) for c in self.entry['development']['cases']]
        self.assertNotEqual(baseline, variant)
        self.assertEqual(self.entry, before)
        self.assertEqual(variant['nodes'][0]['options']['y'], [2, 5, 8])

    def test_host_conformance_works_for_numerical_geometry_and_non_node_routes(self):
        for version in (VERSION, 'schemaxis.freecad/1', 'schemaxis.freecad.assembly/1', 'schemaxis.ffmpeg/1'):
            with self.subTest(version=version):
                self.assertTrue(host(version)['verified'])

    def test_host_conformance_detects_a_schema_accepting_an_undeclared_field(self):
        from schemaxis.adaptor_conformance import export_schema
        schema = export_schema(version=VERSION, authored=True)
        schema['additionalProperties'] = True
        with patch('schemaxis.adaptor_conformance.export_schema', return_value=schema):
            with self.assertRaises(SchemaxisError) as caught:
                host(VERSION)
        self.assertEqual(caught.exception.fault.code, 'CONFORMANCE_FAILED')

    def test_independent_expectations_reject_a_success_flag_with_wrong_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'output.json').write_text('{"verified":true,"value":12}')
            checks = [{'file': 'output.json', 'format': 'json', 'pointer': '/value', 'expected': 13}]
            with self.assertRaises(SchemaxisError):
                assertions(root, checks)
            checks[0]['expected'] = 12
            self.assertEqual(assertions(root, checks)[0]['observed'], 12)
            (root/'outside.json').symlink_to('/etc/passwd')
            checks[0]['file'] = 'outside.json'
            with self.assertRaises(SchemaxisError):
                assertions(root, checks)

    def test_integrity_uses_real_publications_and_restores_on_verifier_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('output.txt', 'authored.json', 'plan.json'):
                (root/name).write_text('original')
            (root/'verification.json').write_text(json.dumps({'artifacts': [
                {'file': str(root/'output.txt'), 'kind': 'text', 'sha256': file_digest(root/'output.txt')}]}))
            originals = {n: (root/n).read_text() for n in ('output.txt', 'authored.json', 'plan.json', 'verification.json')}
            def verify(*args):
                if any(not (root/n).is_file() or (root/n).read_text() != payload for n, payload in originals.items()):
                    fail('VERIFICATION_FAILED', 'mutation caught')
                return {'verified': True}
            with patch('schemaxis.adaptor_conformance.registry.verify', side_effect=verify):
                self.assertEqual(len(integrity(root, {})), 8)
            with patch('schemaxis.adaptor_conformance.registry.verify', return_value={'verified': True}):
                with self.assertRaises(SchemaxisError):
                    integrity(root, {})
            self.assertEqual((root/'output.txt').read_text(), 'original')
            self.assertFalse(list(root.glob('*.qualification-original')))

    def test_cad_missing_evidence_is_structured_for_both_route_models(self):
        from schemaxis.adaptors.freecad import adaptor, assembly
        with tempfile.TemporaryDirectory() as tmp:
            for module in (adaptor, assembly):
                with self.assertRaises(SchemaxisError) as caught:
                    module.verify(tmp)
                self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')

    def test_source_identity_is_stable_and_host_only_receipts_cannot_register(self):
        self.assertEqual(source_digest('octave'), source_digest('octave'))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'receipt.json'
            path.write_text(json.dumps({'protocol': 'schemaxis.adaptor-qualification/1',
                'documentVersion': VERSION, 'provider': 'octave', 'mode': 'host',
                'verified': True, 'sourceDigest': source_digest('octave')}))
            with self.assertRaises(SchemaxisError) as caught:
                register(path)
            self.assertEqual(caught.exception.fault.code, 'INVALID_QUALIFICATION')

    def test_registered_qualification_requires_current_complete_matching_evidence(self):
        receipt = {'protocol': 'schemaxis.adaptor-qualification/1', 'provider': 'octave',
                   'documentVersion': VERSION, 'mode': 'native', 'verified': True, 'sourceDigest': 'current',
                   'host': {'verified': True, 'checks': ['fixture conformance']},
                   'lifecycle': [{'check': name, 'verified': True, 'fault': fault} for name, fault in
                                 [('native runner timeout', 'RUNNER_TIMED_OUT'), ('pre-launch cancellation', 'RUNNER_CANCELLED')]],
                   'cases': []}
        for case in self.entry['development']['cases']:
            receipt['cases'].append({'id': case['id'], 'verified': True, 'runtime': 'test-runtime',
                'caseDigest': digest(case), 'documentDigest': digest(case_document(self.entry, case, ROOT)),
                'checks': [{**c, 'observed': copy.deepcopy(c['expected'])} for c in case['checks']],
                'integrity': [{'check': action+' '+name, 'verified': True} for action in ('missing','tampered')
                              for name in ('authored.json','plan.json','verification.json','result.csv')]})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'octave').mkdir()
            (root/'octave/readiness.json').write_text(json.dumps({'routes': {VERSION: self.entry}}))
            file = root/'octave/qualification.json'
            def write(value):
                file.write_text(json.dumps({'protocol': receipt['protocol'], 'routes': {VERSION: value}}))
            with patch('schemaxis.adaptors.registry.adaptor_files', side_effect=lambda provider: root/provider), \
                 patch('schemaxis.adaptor_delivery.source_digest', return_value='current'):
                write(receipt)
                self.assertEqual(qualification_status(VERSION)['status'], 'source-current')
                broken = copy.deepcopy(receipt)
                broken['cases'][0]['checks'][0]['observed'] = [[0, 99], [1, 99], [2, 99]]
                write(broken)
                self.assertEqual(qualification_status(VERSION)['status'], 'unknown')
                broken = copy.deepcopy(receipt)
                broken['cases'][0]['integrity'] = [{'check': 'anything', 'verified': True}]
                write(broken)
                self.assertEqual(qualification_status(VERSION)['status'], 'unknown')
                stale = copy.deepcopy(receipt)
                stale['sourceDigest'] = 'old'
                write(stale)
                self.assertEqual(qualification_status(VERSION)['status'], 'stale')

    def test_referenced_fixture_changes_invalidate_source_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root/'examples/schemaxis/freecad-assembly.json'
            path.parent.mkdir(parents=True)
            path.write_text('{}')
            with patch('schemaxis.readiness.repository_root', return_value=root):
                first = source_digest('freecad')
                path.write_text('{"changed": true}')
                self.assertNotEqual(source_digest('freecad'), first)

    def test_resource_fixtures_are_portable_contained_and_bound_to_bytes(self):
        _, _, entry = route_materials('schemaxis.ffmpeg/1')
        case = entry['development']['cases'][0]
        reference = case['resources']['/nodes/0/options/files/0']
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for location in (first, second):
                path = Path(location)/reference
                path.parent.mkdir(parents=True)
                path.write_bytes(b'fixture bytes')
            document = case_document(entry, case, first)
            self.assertEqual(document['nodes'][0]['options']['files'], [str(Path(first)/reference)])
            self.assertEqual(case_document_digest(entry, case, first), case_document_digest(entry, case, second))
            with patch('schemaxis.readiness.repository_root', return_value=Path(first)):
                initial = source_digest('ffmpeg')
                (Path(first)/reference).write_bytes(b'changed fixture')
                self.assertNotEqual(source_digest('ffmpeg'), initial)
            self.assertNotEqual(case_document_digest(entry, case, first), case_document_digest(entry, case, second))
            (Path(first)/reference).unlink()
            (Path(first)/reference).symlink_to(Path(second)/reference)
            with self.assertRaises(SchemaxisError):
                case_document(entry, case, first)
        for resources in ({'/nodes/0/options/files/0': '../escape.png'},
                          {'not-a-pointer': reference}, {'/input': '/tmp/input.png'}, ['bad']):
            bad = copy.deepcopy(entry)
            bad['development']['cases'][0]['resources'] = resources
            with self.assertRaises(SchemaxisError):
                validate_development('schemaxis.ffmpeg/1', bad)

    def test_public_context_does_not_import_probe_or_execute_native_apps(self):
        script = r'''
import importlib.abc, json, sys
attempts = []
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'bpy', 'paraview', 'FreeCAD', 'Part', 'vtk', 'qgis'}:
            attempts.append(fullname)
            raise AssertionError(fullname)
sys.meta_path.insert(0, NoNative())
def audit(event, args):
    if event in {'subprocess.Popen','os.system','os.posix_spawn','os.fork','os.exec','socket.connect'}:
        attempts.append(event)
        raise AssertionError(event)
sys.addaudithook(audit)
from schemaxis.__main__ import main
sys.argv = ['schemaxis', 'adaptor', 'context', 'schemaxis.freecad.assembly/1', '--pointer', '/materials/development/authoring']
r = main()
assert r['value']['model'] == 'document'
assert not attempts, attempts
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


class NativeRuntimeContextTests(unittest.TestCase):
    def test_caller_runtime_reaches_verification_and_integrity_without_leaking(self):
        from schemaxis.adaptor_conformance import _native_worker
        from schemaxis.configuration import locations
        trusted = {'ffmpeg': '/trusted/operator/ffmpeg'}
        request = {'action': 'case', 'document': {'version': 'schemaxis.ffmpeg/1'},
                   'run': '/unused/run', 'locations': trusted, 'timeout': 5,
                   'documentDigest': 'fixture', 'case': {'id': 'case', 'scope': 'fixture', 'checks': []}}
        observations = []
        def verify(*args):
            observations.append(locations()['ffmpeg'])
            return {'verified': True, 'runtime': 'trusted native fixture'}
        def integrity_check(*args):
            observations.append(locations()['ffmpeg'])
            return []
        with patch('schemaxis.configuration.load', return_value={'locations': {}}), \
                patch('schemaxis.adaptor_conformance.registry.run'), \
                patch('schemaxis.adaptor_conformance.registry.verify', side_effect=verify), \
                patch('schemaxis.adaptor_conformance.assertions', return_value=[]), \
                patch('schemaxis.adaptor_conformance.integrity', side_effect=integrity_check):
            self.assertTrue(_native_worker(request)['verified'])
            self.assertEqual(observations, [trusted['ffmpeg'], trusted['ffmpeg']])
            self.assertNotEqual(locations().get('ffmpeg'), trusted['ffmpeg'])
            with patch('schemaxis.adaptor_conformance.registry.verify', side_effect=RuntimeError('failed native check')):
                with self.assertRaisesRegex(RuntimeError, 'failed native check'):
                    _native_worker(request)
            self.assertNotEqual(locations().get('ffmpeg'), trusted['ffmpeg'])


if __name__ == '__main__':
    unittest.main()
