import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from schemaxis import compatibility
from schemaxis.adaptors import registry
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = {'version': 'schemaxis/1', 'routes': {'schemaxis/1': {}},
            'executionCapabilities': {'modes': ['serial', 'mpi']}}


def identity(version='5.13.3', **extra):
    return {'application': 'paraview', 'version': version, **extra}


def policy(*profiles, absorbed='5.13.3'):
    observed = {'id': 'paraview-5.13.3', 'status': 'observed', 'versions': ['5.13.3'],
                'routes': ['schemaxis/1'], 'modes': ['serial'], 'evidence': ['verification/x.json'],
                'scope': 'serial fixture'}
    return {'absorbedVersion': absorbed, 'compatibility': {
        'protocol': compatibility.PROTOCOL, 'profiles': list(profiles) or [observed]}}


def fault(test, code, call):
    with test.assertRaises(SchemaxisError) as caught:
        call()
    test.assertEqual(caught.exception.fault.code, code)
    return caught.exception.fault


class ProfileValidation(unittest.TestCase):
    def test_paraview_declares_only_its_observed_baseline(self):
        policy_data, manifest, profiles = compatibility.load('paraview')
        self.assertEqual([p['versions'] for p in profiles], [['5.13.3']])
        self.assertEqual(policy_data['absorbedVersion'], '5.13.3')
        for evidence in profiles[0]['evidence']:
            self.assertTrue((ROOT/evidence).is_file(), evidence)
        select = lambda version, mode='serial': compatibility.select(
            profiles, identity(version), provider='paraview', route='schemaxis/1', mode=mode,
            declared=manifest['executionCapabilities']['modes'])
        self.assertEqual(select('5.13.3')['status'], 'observed')
        for version in ('5.13.4', '5.13', '6.0.0', '5.12.1'):
            self.assertEqual(select(version)['status'], 'unqualified', version)

    def test_other_adaptors_are_not_forced_to_adopt_profiles(self):
        adopted = [app for app, item in registry.ADAPTORS.items() if item['source'] == 'builtin'
                   and 'compatibility' in json.loads(registry.adaptor_files(app).joinpath('upstream.json').read_text())]
        self.assertEqual(adopted, ['paraview'])
        self.assertEqual(compatibility.assess('blender', None, route='schemaxis.blender/1',
                                              qualification=False)['profile']['status'], 'undeclared')

    def test_ambiguous_profiles_are_rejected_not_ordered(self):
        base = policy()['compatibility']['profiles'][0]
        twin = {**copy.deepcopy(base), 'id': 'twin'}
        error = fault(self, 'AMBIGUOUS_COMPATIBILITY_PROFILE',
                      lambda: compatibility.validate(policy(base, twin), MANIFEST))
        self.assertEqual(error.observed['profiles'], ['paraview-5.13.3', 'twin'])
        with self.assertRaises(SchemaxisError):
            compatibility.select([base, twin], identity(), provider='paraview', route='schemaxis/1')

    def test_absorbed_baseline_covers_every_route_independent_of_profile_order(self):
        manifest = {**MANIFEST, 'routes': {'schemaxis/1': {}, 'schemaxis/2': {}}}
        base = policy()['compatibility']['profiles'][0]
        other = {**copy.deepcopy(base), 'id': 'second-route', 'routes': ['schemaxis/2']}
        for profiles in ([base, other], [other, base]):
            self.assertEqual(len(compatibility.validate(policy(*profiles), manifest)), 2)
        unsupported = {key: value for key, value in other.items() if key not in ('modes', 'evidence')}
        unsupported.update(status='unsupported', reason='known incompatible route')
        for profiles in ([base], [base, unsupported], [unsupported, base]):
            with self.subTest(profiles=[p['id'] for p in profiles]):
                error = fault(self, 'INVALID_COMPATIBILITY_PROFILE',
                              lambda: compatibility.validate(policy(*profiles), manifest))
                self.assertEqual(error.observed['routes'], ['schemaxis/2'])

    def test_malformed_profiles_are_invalid(self):
        base = policy()['compatibility']['profiles'][0]
        cases = {
            'range': {**base, 'versions': ['5.13.*']},
            'prefix': {**base, 'versions': ['v5.13.3']},
            'route': {**base, 'routes': ['schemaxis/9']},
            'mode': {**base, 'modes': ['gpu']},
            'evidence': {k: v for k, v in base.items() if k != 'evidence'},
            'status': {**base, 'status': 'compatible'},
            'key': {**base, 'latest': True},
            'scope': {**base, 'scope': ' '},
            'unsupported-reason': {**base, 'id': 'bad', 'status': 'unsupported', 'versions': ['5.12.0']},
        }
        for name, profile in cases.items():
            with self.subTest(name):
                profiles = [profile] if profile.get('id') != 'bad' else [base, profile]
                fault(self, 'INVALID_COMPATIBILITY_PROFILE',
                      lambda: compatibility.validate(policy(*profiles), MANIFEST))
        bad_protocol = policy()
        bad_protocol['compatibility']['protocol'] = 'other/1'
        fault(self, 'INVALID_COMPATIBILITY_PROFILE', lambda: compatibility.validate(bad_protocol, MANIFEST))
        # The absorbed baseline must itself be an observed profile.
        fault(self, 'INVALID_COMPATIBILITY_PROFILE',
              lambda: compatibility.validate(policy(absorbed='5.13.4'), MANIFEST))
        refused = {'id': 'paraview-5.13.3', 'status': 'unsupported', 'versions': ['5.13.3'],
                   'routes': ['schemaxis/1'], 'scope': 'known defect', 'reason': 'crashes'}
        fault(self, 'INVALID_COMPATIBILITY_PROFILE', lambda: compatibility.validate(policy(refused), MANIFEST))
        self.assertIsNone(compatibility.validate({'absorbedVersion': '1.0.0'}, MANIFEST))


class Selection(unittest.TestCase):
    profiles = compatibility.validate(policy(
        policy()['compatibility']['profiles'][0],
        {'id': 'paraview-5.12.0', 'status': 'unsupported', 'versions': ['5.12.0'], 'routes': ['schemaxis/1'],
         'scope': 'regression fixture', 'reason': 'known incompatible reader behaviour'}), MANIFEST)

    def pick(self, value, mode='serial', probed=None):
        return compatibility.select(self.profiles, value, provider='paraview', route='schemaxis/1',
                                    mode=mode, probed=probed, declared=['serial', 'mpi'])

    def test_unknown_and_malformed_runtime_versions_stay_distinct(self):
        self.assertEqual(self.pick(None)['status'], 'absent')
        self.assertEqual(self.pick({'application': 'paraview', 'fault': 'ImportError: x'})['status'], 'unavailable')
        for value in (identity('x.y'), identity('5'), identity('5.13.3-rc1'), identity(''), identity(None),
                      'paraview 5.13.3', identity(nested=1), {**identity(), 'application': 'blender'}):
            self.assertEqual(self.pick(value)['status'], 'invalid', value)
        self.assertEqual(self.pick(identity('5.13.4'))['status'], 'unqualified')
        self.assertEqual(self.pick(identity('5.12.0'))['status'], 'unsupported')
        self.assertEqual(self.pick(identity())['status'], 'observed')
        # The launcher's --version and the in-process report must agree.
        mismatch = self.pick(identity(), probed='5.13.4')
        self.assertEqual(mismatch['status'], 'invalid')
        self.assertIn('differs', mismatch['reason'])
        other_route = compatibility.select(self.profiles, identity(), provider='paraview', route='schemaxis/9')
        self.assertEqual(other_route['status'], 'unqualified')

    def test_optional_identity_fields_are_typed_when_present(self):
        native = identity(build='paraview version 5.13.3', source='paraview.servermanager.vtkSMProxyManager',
                          platform={'system': 'Linux', 'machine': 'x86_64', 'python': '3.10.13'})
        self.assertEqual(self.pick(native)['status'], 'observed')
        # Each optional field may be omitted, including a partial platform.
        for missing in ('build', 'source', 'platform'):
            value = {k: v for k, v in native.items() if k != missing}
            self.assertEqual(self.pick(value)['status'], 'observed', missing)
        self.assertEqual(self.pick(identity(platform={'system': 'Linux'}))['status'], 'observed')
        malformed = {'build-int': {'build': 42}, 'build-empty': {'build': ' '}, 'platform-list': {'platform': []},
                     'platform-str': {'platform': 'Linux'}, 'source-dict': {'source': {}},
                     'source-none': {'source': None}, 'platform-key': {'platform': {'os': 'Linux'}},
                     'platform-int': {'platform': {'system': 'Linux', 'machine': 64}},
                     'platform-nested': {'platform': {'system': {'name': 'Linux'}}},
                     'platform-empty': {'platform': {'python': ''}}}
        for name, fields in malformed.items():
            with self.subTest(name):
                self.assertEqual(self.pick({**native, **fields})['status'], 'invalid')
        # A malformed fault is invalid, not unavailable, as are malformed fields beside a fault.
        for value in ({'application': 'paraview', 'fault': {}}, {'application': 'paraview', 'fault': 7},
                      {'application': 'paraview', 'fault': ''},
                      {'application': 'paraview', 'fault': 'ImportError: x', 'platform': []}):
            self.assertEqual(self.pick(value)['status'], 'invalid', value)

    def test_supplied_candidates_stay_distinct_from_native_reports(self):
        candidate = identity(source='supplied')
        supplied = compatibility.select(self.profiles, candidate, provider='paraview', route='schemaxis/1',
                                        supplied=True)
        self.assertEqual(supplied['status'], 'observed')
        self.assertIn('no runtime was started or observed', supplied['reason'])
        self.assertNotIn('no runtime', self.pick(identity())['reason'])
        # Neither kind can pass as the other.
        self.assertEqual(self.pick(candidate)['status'], 'invalid')
        self.assertEqual(compatibility.select(self.profiles, identity(), provider='paraview', route='schemaxis/1',
                                              supplied=True)['status'], 'invalid')

    def test_capabilities_follow_the_profile_not_the_manifest(self):
        self.assertEqual(self.pick(identity())['capability'], {'mode': 'serial', 'status': 'observed'})
        self.assertEqual(self.pick(identity(), 'mpi')['capability']['status'], 'unqualified')
        self.assertEqual(self.pick(identity(), 'gpu')['capability']['status'], 'undeclared')
        self.assertEqual(self.pick(identity('5.13.4'), 'serial')['capability']['status'], 'unknown')
        self.assertEqual(self.pick(identity('5.12.0'))['capability']['status'], 'unsupported')


class Qualification(unittest.TestCase):
    def test_profile_match_does_not_change_source_current_qualification(self):
        receipt = {'cases': [{'runtime': {'version': '5.13.3'}}, {'runtime': {'version': '5.13.3'}}]}
        for status in ('source-current', 'stale'):
            with self.subTest(status), mock.patch('schemaxis.adaptor_delivery.qualification_status',
                                                  return_value={'status': status, 'receipt': receipt}):
                report = compatibility.assess('paraview', identity(), route='schemaxis/1')
                self.assertEqual(report['profile']['status'], 'observed')
                self.assertEqual(report['qualification']['status'], status)
                self.assertTrue(report['qualification']['coversObservedVersion'])
        with mock.patch('schemaxis.adaptor_delivery.qualification_status',
                        return_value={'status': 'source-current', 'receipt': receipt}):
            other = compatibility.assess('paraview', identity('6.0.0'), route='schemaxis/1')
        self.assertEqual(other['profile']['status'], 'unqualified')
        # A source-current receipt recorded on another release does not cover this runtime.
        self.assertFalse(other['qualification']['coversObservedVersion'])
        with mock.patch('schemaxis.adaptor_delivery.qualification_status',
                        return_value={'status': 'unknown', 'reason': 'no receipt'}):
            report = compatibility.assess('paraview', identity(), route='schemaxis/1')
        self.assertEqual((report['profile']['status'], report['qualification']['status']), ('observed', 'unknown'))

    def test_qualification_keeps_its_receipt_scope_and_checks_version_equality_only(self):
        receipt = {'cases': [{'runtime': {'version': '5.13.3'}}]}
        scope = 'Only cited cases and recorded runtimes; installation availability and untested profiles remain unknown.'
        with mock.patch('schemaxis.adaptor_delivery.qualification_status',
                        return_value={'status': 'stale', 'receipt': receipt, 'scope': scope}):
            report = compatibility.assess('paraview', identity(), route='schemaxis/1')['qualification']
        self.assertEqual((report['status'], report['scope']), ('stale', scope))
        self.assertIn('release numbers only', report['versionCheck'])
        self.assertIn('platform, build or plugin', report['versionCheck'])
        with mock.patch('schemaxis.adaptor_delivery.qualification_status',
                        return_value={'status': 'unknown', 'reason': 'No scoped development-kit receipt is registered.'}):
            report = compatibility.assess('paraview', identity(), route='schemaxis/1')['qualification']
        self.assertEqual(report['reason'], 'No scoped development-kit receipt is registered.')
        self.assertNotIn('scope', report)

    def test_legacy_free_text_and_malformed_runtimes_report_no_structured_version(self):
        scope = 'Only cited cases and recorded runtimes.'
        legacy = {'cases': [{'runtime': 'pandoc 3.12.1'}, {'runtime': 'pandoc 3.12.1'}]}
        malformed = [None, 7, [], 'x', {}, {'runtime': None}, {'runtime': 5}, {'runtime': []},
                     {'runtime': {}}, {'runtime': {'version': None}}, {'runtime': {'version': 5}},
                     {'runtime': {'version': ['5.13.3']}}, {'runtime': {'version': {}}},
                     {'runtime': {'version': ' '}}]
        for name, receipt in (('legacy', legacy), ('malformed', {'cases': malformed}),
                              ('cases-text', {'cases': 'pandoc 3.12.1'}), ('cases-object', {'cases': {}}),
                              ('cases-null', {'cases': None}), ('no-cases', {})):
            for status in ('stale', 'source-current'):
                with self.subTest(name, status=status), mock.patch(
                        'schemaxis.adaptor_delivery.qualification_status',
                        return_value={'status': status, 'receipt': receipt, 'scope': scope}):
                    report = compatibility.assess('pandoc', identity(application='pandoc', version='3.12.1'),
                                                  route='schemaxis.pandoc/1')
                    candidate = compatibility.assess('pandoc', None, route='schemaxis.pandoc/1')
                for value in (report, candidate):
                    qualification = value['qualification']
                    self.assertEqual((qualification['status'], qualification['scope']), (status, scope))
                    self.assertEqual(qualification['runtimeVersions'], [])
                    self.assertIsNone(qualification['coversObservedVersion'])
                    self.assertIn('release numbers only', qualification['versionCheck'])
                self.assertEqual(candidate['profile']['status'], 'undeclared')

    def test_mixed_legacy_and_structured_runtimes_keep_only_structured_versions(self):
        receipt = {'cases': [{'runtime': 'paraview 5.13.3'}, {'runtime': {'version': '5.13.3'}},
                             {'runtime': {'version': 5}}, {'runtime': {'version': '5.12.0'}}, None]}
        for version, covered in (('5.13.3', True), ('5.12.0', True), ('6.0.0', False)):
            with self.subTest(version), mock.patch('schemaxis.adaptor_delivery.qualification_status',
                                                   return_value={'status': 'stale', 'receipt': receipt}):
                report = compatibility.assess('paraview', identity(version), route='schemaxis/1')['qualification']
            self.assertEqual(report['status'], 'stale')
            self.assertEqual(report['runtimeVersions'], ['5.12.0', '5.13.3'])
            self.assertIs(report['coversObservedVersion'], covered)

    def test_cli_reports_pandoc_with_legacy_free_text_receipts(self):
        completed = subprocess.run([sys.executable, '-m', 'schemaxis', 'adaptor', 'compatibility', 'pandoc'],
                                   cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT/'src')},
                                   capture_output=True, text=True, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr[-3000:])
        self.assertNotIn('Traceback', completed.stderr)
        report = json.loads(completed.stdout)
        report = report.get('result', report)
        self.assertEqual(report['profile']['status'], 'undeclared')
        self.assertIn(report['qualification']['status'], ('stale', 'source-current', 'unknown'))
        self.assertEqual(report['qualification'].get('runtimeVersions', []), [])
        self.assertIsNone(report['qualification']['coversObservedVersion'])

    def test_supplied_candidate_report_does_not_claim_an_observation(self):
        with mock.patch('schemaxis.adaptor_delivery.qualification_status',
                        return_value={'status': 'source-current', 'receipt': {'cases': [{'runtime': {'version': '5.13.3'}}]}}):
            report = compatibility.assess('paraview', identity(source='supplied'), route='schemaxis/1', supplied=True)
        self.assertEqual(report['identitySource'], 'supplied')
        self.assertIsNone(report['observed'])
        self.assertEqual(report['candidate']['version'], '5.13.3')
        self.assertEqual(report['profile']['status'], 'observed')
        self.assertIn('no runtime was started or observed', report['scope'])
        self.assertEqual(report['qualification']['status'], 'source-current')
        native = compatibility.assess('paraview', identity(), route='schemaxis/1', qualification=False)
        self.assertEqual(native['identitySource'], 'native-self-report')
        self.assertNotIn('candidate', native)

    def test_cli_marks_app_version_as_a_supplied_candidate(self):
        completed = subprocess.run([sys.executable, '-m', 'schemaxis', 'adaptor', 'compatibility', 'paraview',
                                    '--app-version', '5.13.3'], cwd=ROOT,
                                   env={**os.environ, 'PYTHONPATH': str(ROOT/'src')},
                                   capture_output=True, text=True, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr[-3000:])
        report = json.loads(completed.stdout)
        report = report.get('result', report)
        self.assertEqual((report['identitySource'], report['observed']), ('supplied', None))
        self.assertEqual(report['candidate']['source'], 'supplied')
        self.assertIn('no runtime was started or observed', report['profile']['reason'])

    def test_report_separates_identity_layers(self):
        report = compatibility.assess('paraview', identity(build='paraview version 5.13.3'),
                                      route='schemaxis/1', qualification=False)
        self.assertEqual(set(report) - {'scope'},
                         {'protocol', 'core', 'adaptor', 'route', 'identitySource', 'observed', 'profile'})
        self.assertEqual(report['adaptor']['absorbedVersion'], '5.13.3')
        self.assertTrue(report['adaptor']['revision'].startswith('sha256:'))
        self.assertEqual(report['route'], 'schemaxis/1')
        self.assertNotEqual(report['core']['package'], report['observed']['version'])


class Receipts(unittest.TestCase):
    def directory(self, tmp, receipt):
        path = Path(tmp)
        (path/'authored.json').write_text(json.dumps({'version': 'schemaxis/1'}))
        (path/'submission.json').write_text(json.dumps({'interpreter': {'kind': 'paraview', 'version': '5.13.3'}}))
        return path, receipt

    def test_old_receipts_without_identity_report_absent(self):
        from schemaxis.adaptors.paraview.integration import compatibility as receipt_compatibility
        with tempfile.TemporaryDirectory() as tmp:
            report = receipt_compatibility(*self.directory(tmp, {'status': 'succeeded', 'artifacts': []}))
        self.assertNotIn('fault', report)
        self.assertEqual(report['profile']['status'], 'absent')
        self.assertIsNone(report['observed'])
        self.assertIsNone(report['qualification']['coversObservedVersion'])

    def test_native_identity_and_mpi_mode_are_assessed(self):
        from schemaxis.adaptors.paraview.integration import compatibility as receipt_compatibility
        with tempfile.TemporaryDirectory() as tmp:
            report = receipt_compatibility(*self.directory(tmp, {'ranks': 2, 'runtimeIdentity': identity()}))
        self.assertEqual(report['profile']['status'], 'observed')
        self.assertEqual(report['profile']['capability'], {'mode': 'mpi', 'status': 'unqualified'})
        self.assertEqual(report['launcherVersion'], '5.13.3')

    def test_profile_data_faults_do_not_change_receipt_verification(self):
        from schemaxis.adaptors.paraview.integration import compatibility as receipt_compatibility
        from schemaxis.core.faults import Fault
        invalid = SchemaxisError(Fault('INVALID_COMPATIBILITY_PROFILE', 'bad', '$', 'pipeline'))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(compatibility, 'load', side_effect=invalid):
            report = receipt_compatibility(*self.directory(tmp, {'runtimeIdentity': identity()}))
        self.assertEqual(report['fault']['code'], 'INVALID_COMPATIBILITY_PROFILE')



class RouteOwnership(unittest.TestCase):
    def lookups(self):
        return (mock.patch('schemaxis.adaptor_delivery.qualification_status'),
                mock.patch('schemaxis.adaptor_delivery.source_digest'))

    def test_routes_the_provider_does_not_declare_are_rejected_before_any_lookup(self):
        wrong = (('blender', 'schemaxis/1'), ('paraview', 'schemaxis.pandoc/1'), ('paraview', 'schemaxis/9'),
                 ('paraview', ''), ('paraview', None), ('paraview', 5), ('paraview', ['schemaxis/1']),
                 ('blender', {}))
        for provider, route in wrong:
            for supplied in (False, True):
                with self.subTest(provider=provider, route=route, supplied=supplied):
                    candidate = identity(application=provider, source='supplied') if supplied else None
                    status, digest = self.lookups()
                    with status as qualification, digest as source, mock.patch.object(
                            compatibility, 'load', wraps=compatibility.load) as load:
                        error = fault(self, 'UNSUPPORTED_VERSION', lambda: compatibility.assess(
                            provider, candidate, route=route, supplied=supplied))
                    qualification.assert_not_called()
                    source.assert_not_called()
                    load.assert_not_called()
                    self.assertEqual(error.location, '$.route')
                    self.assertEqual(error.observed['provider'], provider)
                    self.assertEqual(error.observed['route'], route if isinstance(route, str) else repr(route))
                    self.assertNotIn('schemaxis.pandoc/1', error.observed['routes'])

    def test_declared_routes_keep_working_including_legacy_version_fallback(self):
        for provider in ('paraview', 'blender'):
            manifest = registry.metadata(provider)
            for route in set(manifest.get('routes', {})) or {manifest['version']}:
                with self.subTest(provider=provider, route=route):
                    report = compatibility.assess(provider, None, route=route, qualification=False)
                    self.assertEqual((report['route'], report['adaptor']['id']), (route, provider))
        legacy = {'version': 'legacy/1'}
        with mock.patch.object(registry, 'metadata', return_value=legacy):
            compatibility.check_route('any', 'legacy/1')
            fault(self, 'UNSUPPORTED_VERSION', lambda: compatibility.check_route('any', 'schemaxis/1'))

    def test_cli_rejects_a_route_owned_by_another_adaptor(self):
        for provider, route in (('blender', 'schemaxis/1'), ('paraview', 'schemaxis.pandoc/1'),
                                ('paraview', 'nonsense')):
            with self.subTest(provider=provider, route=route):
                completed = subprocess.run([sys.executable, '-m', 'schemaxis', 'adaptor', 'compatibility', provider,
                                            '--route', route], cwd=ROOT,
                                           env={**os.environ, 'PYTHONPATH': str(ROOT/'src')},
                                           capture_output=True, text=True, timeout=60)
                self.assertEqual(completed.returncode, 1, completed.stdout[-2000:] + completed.stderr[-2000:])
                self.assertNotIn('Traceback', completed.stderr)
                output = json.loads(completed.stdout)
                self.assertEqual(output['fault']['code'], 'UNSUPPORTED_VERSION')
                for key in ('qualification', 'adaptor', 'profile'):
                    self.assertNotIn(key, output)

    def test_cli_default_and_explicit_declared_routes_still_report(self):
        for arguments in (['blender'], ['blender', '--route', 'schemaxis.blender/1'],
                          ['paraview', '--route', 'schemaxis/1', '--app-version', '5.13.3']):
            with self.subTest(arguments):
                completed = subprocess.run([sys.executable, '-m', 'schemaxis', 'adaptor', 'compatibility', *arguments],
                                           cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT/'src')},
                                           capture_output=True, text=True, timeout=60)
                self.assertEqual(completed.returncode, 0, completed.stderr[-3000:])
                report = json.loads(completed.stdout)
                report = report.get('result', report)
                self.assertEqual(report['adaptor']['id'], arguments[0])
                self.assertIn('qualification', report)

    def test_receipt_hook_reports_an_undeclared_route_as_an_informational_fault(self):
        from schemaxis.adaptors.paraview.integration import compatibility as receipt_compatibility
        for authored in ({'version': 'schemaxis.pandoc/1'}, {'version': 'unknown/9'}, {}):
            with self.subTest(authored), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)
                (path/'authored.json').write_text(json.dumps(authored))
                (path/'submission.json').write_text(json.dumps({'interpreter': {'kind': 'paraview', 'version': '5.13.3'}}))
                with mock.patch('schemaxis.adaptor_delivery.qualification_status') as qualification:
                    report = receipt_compatibility(path, {'runtimeIdentity': identity()})
                qualification.assert_not_called()
                self.assertEqual(set(report), {'fault'})
                self.assertEqual(report['fault']['code'], 'UNSUPPORTED_VERSION')


class UpstreamMetadata(unittest.TestCase):
    def tree(self, text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        Path(tmp.name, 'upstream.json').write_text(text)
        return mock.patch.object(registry, 'adaptor_files', return_value=Path(tmp.name))

    def test_malformed_upstream_metadata_is_a_structured_profile_fault(self):
        for name, text in (('array', '[]'), ('string', '"x"'), ('number', '3'), ('null', 'null'),
                           ('truncated', '{"absorbedVersion": '), ('empty', ''), ('not-json', 'nope')):
            with self.subTest(name), self.tree(text):
                for call in (lambda: compatibility.load('paraview'),
                             lambda: compatibility.assess('paraview', None, route='schemaxis/1', qualification=False)):
                    error = fault(self, 'INVALID_COMPATIBILITY_PROFILE', call)
                    self.assertEqual(error.location, 'upstream.json')

    def test_receipt_hook_reports_malformed_upstream_metadata_without_raising(self):
        from schemaxis.adaptors.paraview.integration import compatibility as receipt_compatibility
        with self.tree('[]'), tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path/'authored.json').write_text(json.dumps({'version': 'schemaxis/1'}))
            (path/'submission.json').write_text(json.dumps({'interpreter': {'kind': 'paraview', 'version': '5.13.3'}}))
            report = receipt_compatibility(path, {'runtimeIdentity': identity()})
        self.assertEqual(report['fault']['code'], 'INVALID_COMPATIBILITY_PROFILE')

    def test_missing_metadata_still_means_no_profiles_and_other_errors_are_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(registry, 'adaptor_files',
                                                                     return_value=Path(tmp)):
            self.assertEqual(compatibility.load('paraview')[::2], ({}, None))
        with self.tree('{}'), mock.patch.object(Path, 'read_text', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                compatibility.load('paraview')


class NativeFree(unittest.TestCase):
    def test_discovery_planning_and_selection_neither_import_nor_launch_native_apps(self):
        script = r"""
import importlib.abc, json, sys
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'paraview', 'vtk', 'vtkmodules'}:
            raise AssertionError('native import: ' + fullname)
sys.meta_path.insert(0, NoNative())
def audit(event, args):
    if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.fork', 'os.exec'}:
        raise AssertionError('native process: ' + event)
sys.addaudithook(audit)
from schemaxis.adaptors import registry
from schemaxis.compatibility import assess
assert 'paraview' in json.dumps(registry.discover())
registry.plan(json.load(open('examples/schemaxis/paraview-admission.json')), legacy=True)
report = assess('paraview', {'application': 'paraview', 'version': '5.13.3'}, route='schemaxis/1')
assert report['profile']['status'] == 'observed', report
"""
        completed = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                                   env={**os.environ, 'PYTHONPATH': str(ROOT/'src')},
                                   capture_output=True, text=True, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr[-3000:])


if __name__ == '__main__':
    unittest.main()
