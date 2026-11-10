"""Editorial scores stay scoped, source-aware and independent of execution."""
import copy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from schemaxis import assessments
from schemaxis.adaptors import registry
from schemaxis.capabilities import CapabilityCatalogue
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT/'verification/2026-10-25-adaptor-assessments.json'


class AdaptorAssessmentTests(unittest.TestCase):
    def record(self, provider='gmsh'):
        return json.loads(registry.adaptor_files(provider).joinpath('assessment.json').read_text())

    def test_inventory_counts_providers_and_document_routes_separately(self):
        result = assessments.report()
        self.assertEqual(result['providerCount'], len(registry.ADAPTORS))
        self.assertEqual(result['routeCount'], len(registry.routes()))
        self.assertGreater(result['routeCount'], result['providerCount'])
        self.assertEqual(sum(result['counts'].values()), result['providerCount'])
        selected = assessments.report(['whispercpp', 'blender', 'freecad', 'whispercpp'])
        self.assertEqual(selected['providerCount'], 3)
        self.assertEqual(selected['routeCount'], sum(len(registry.metadata(p)['routes']) for p in ('whispercpp', 'blender', 'freecad')))
        for entry in selected['providers']:
            self.assertEqual(entry['verification']['runtimeAvailability'], 'not checked')
            self.assertNotIn('qualified', entry['assessment'])

    def test_first_baseline_is_complete_scoped_and_portable(self):
        baseline = json.loads(BASELINE.read_text())
        self.assertEqual((baseline['providerCount'], baseline['routeCount']), (41, 47))
        self.assertEqual(len(baseline['providers']), 41)
        for item in baseline['providers']:
            record = item['assessment']['record']
            self.assertEqual(record['assessedOn'], '2026-10-25')
            self.assertEqual(record['coverage']['scope']['kind'], 'whole-application')
            self.assertEqual(record['abstraction']['scope']['kind'], 'declared-workflows')
            assessments.validate(record, item['id'])
            for reference in record['evidence']:
                self.assertTrue((ROOT/reference).is_file(), reference)
            self.assertTrue(registry.adaptor_files(item['id']).joinpath('assessment.json').is_file())
        # A useful task abstraction must not imply broad library coverage.
        narrow = next(e for e in baseline['providers'] if e['id'] == 'sympy')['assessment']['record']
        self.assertEqual(narrow['coverage']['percent'], 5)
        self.assertGreater(narrow['abstraction']['percent'], 75)
        premiere = next(e for e in baseline['providers'] if e['id'] == 'premiere')['assessment']['record']
        self.assertIn('Native qualification remains pending', premiere['limitations'][0])

    def test_validation_rejects_false_precision_bad_scope_and_missing_rationale(self):
        edits = [lambda r: r['coverage'].update(percent=True),
                 lambda r: r['coverage'].update(percent=12),
                 lambda r: r['coverage'].update(percent=100.0),
                 lambda r: r['coverage'].update(percent=105),
                 lambda r: r['coverage'].update(status='measured'),
                 lambda r: r['coverage']['scope'].update(kind='declared-workflows'),
                 lambda r: r['abstraction'].update(rationale=''),
                 lambda r: r.update(assessedOn='2026-02-30'),
                 lambda r: r.update(assessedOn='2099-12-31'),
                 lambda r: r['coverage'].update(rationale='  TODO explain this later'),
                 lambda r: r['coverage'].update(rationale='todo later'),
                 lambda r: r['coverage'].update(rationale='TBD'),
                 lambda r: r.update(routes=['same/1', 'same/1']),
                 lambda r: r.update(evidence=['/local/private/file']),
                 lambda r: r.update(evidence=['../escape']),
                 lambda r: r.update(evidence=['C:\\private\\file']),
                 lambda r: r.update(provider='other'),
                 lambda r: r.update(rubric='unregistered-rubric/9')]
        for edit in edits:
            record = self.record(); edit(record)
            with self.subTest(record=record):
                with self.assertRaises(SchemaxisError) as caught:
                    assessments.validate(record, 'gmsh')
                self.assertEqual(caught.exception.fault.code, 'INVALID_ASSESSMENT')

    def test_missing_and_invalid_editorial_metadata_do_not_remove_builtin(self):
        document = json.loads((ROOT/'examples/schemaxis/gmsh-minimal.json').read_text())
        expected = registry.plan(document)
        inventory = len(registry.ADAPTORS)
        original_files = registry.adaptor_files
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            def resources(provider):
                return folder if provider == 'gmsh' else original_files(provider)
            with patch.object(registry, 'adaptor_files', side_effect=resources):
                self.assertEqual(assessments.assessment('gmsh')['status'], 'missing')
                for text in ('{broken', '[]', '{"version": "unknown"}'):
                    (folder/'assessment.json').write_text(text)
                    result = assessments.report(['gmsh'])
                    self.assertEqual(result['providerCount'], 1)
                    self.assertEqual(result['providers'][0]['assessment']['status'], 'invalid')
                    self.assertEqual(result['providers'][0]['assessment']['fault']['code'], 'INVALID_ASSESSMENT')
                    found = registry.discover()
                    self.assertEqual(found['providerCount'], inventory)
                    gmsh = next(p for p in found['providers'] if p['id'] == 'gmsh')
                    self.assertEqual(gmsh['assessment']['status'], 'invalid')
                    catalogue = CapabilityCatalogue(['gmsh'])
                    self.assertEqual(catalogue.browse()['items'][0]['assessment']['status'], 'invalid')
                    self.assertEqual(registry.plan(document), expected)
                    self.assertIn('gmsh', registry.ADAPTORS)

    def test_corrupt_plugin_assessment_preserves_registration_and_plan(self):
        fixtures = ROOT/'tests/fixtures/plugin_adaptor'
        sys.path.insert(0, str(fixtures))
        self.addCleanup(sys.path.remove, str(fixtures))
        entry = SimpleNamespace(name='fixtureplugin', value='schemaxis_fixture_plugin',
            group=registry.GROUP, dist=SimpleNamespace(name='fixture-assessments'))
        manifest = registry.load_registry(plugins=[entry], strict=True)['fixtureplugin']
        document = {'version': 'fixtureplugin/1', 'nodes': [{'id': 'output', 'filter': 'emit'}]}
        original_files = registry.adaptor_files
        with tempfile.TemporaryDirectory() as tmp, patch.dict(registry.ADAPTORS, {'fixtureplugin': manifest}), \
                patch.object(registry, 'PLUGIN_FAULTS', []):
            folder = Path(tmp); (folder/'assessment.json').write_text('{broken')
            def resources(provider):
                return folder if provider == 'fixtureplugin' else original_files(provider)
            with patch.object(registry, 'adaptor_files', side_effect=resources):
                found = registry.discover()
                self.assertEqual(found['providerCount'], len(registry.ADAPTORS))
                self.assertIn('fixtureplugin', [e['id'] for e in found['providers']])
                self.assertEqual(assessments.report(['fixtureplugin'])['counts']['invalid'], 1)
                self.assertEqual(CapabilityCatalogue(['fixtureplugin']).browse()['items'][0]['assessment']['status'], 'invalid')
                self.assertEqual(registry.plan(document), document)
                self.assertFalse(registry.PLUGIN_FAULTS)
                self.assertIn('fixtureplugin', registry.ADAPTORS)

    def test_source_change_and_route_change_are_stale_not_reassessed(self):
        original = self.record()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); (folder/'assessment.json').write_text(json.dumps(original))
            with patch.object(registry, 'adaptor_files', return_value=folder), \
                    patch.object(assessments, 'source_fingerprint', return_value='sha256:'+'0'*64):
                result = assessments.assessment('gmsh')
                self.assertEqual(result['status'], 'stale')
                self.assertEqual(result['record'], original)
            with patch.object(registry, 'adaptor_files', return_value=folder), \
                    patch.object(assessments, 'source_fingerprint', return_value=original['sourceFingerprint']):
                manifest = copy.deepcopy(registry.metadata('gmsh'))
                manifest['routes']['new.gmsh/2'] = copy.deepcopy(next(iter(manifest['routes'].values())))
                with patch.dict(registry.ADAPTORS, {'gmsh': manifest}):
                    self.assertEqual(assessments.assessment('gmsh')['status'], 'stale')

    def test_historical_assessed_routes_are_stale_without_registering_them(self):
        record = self.record(); record['routes'].append('historical.gmsh/0')
        assessments.validate(record, 'gmsh')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); (folder/'assessment.json').write_text(json.dumps(record))
            with patch.object(registry, 'adaptor_files', return_value=folder), \
                    patch.object(assessments, 'source_fingerprint', return_value=record['sourceFingerprint']):
                self.assertEqual(assessments.assessment('gmsh')['status'], 'stale')
                self.assertNotIn('historical.gmsh/0', registry.routes())

    def test_assessment_date_respects_current_civil_day_timezone_boundary(self):
        # At UTC noon, the following date already exists in UTC+14.
        with patch.object(assessments, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
            record = self.record()
            # Exercise the boundary independently of later editorial refreshes.
            record['assessedOn'] = '2026-10-25'
            self.assertEqual(record['assessedOn'], '2026-10-25')
            assessments.validate(record, 'gmsh')
            record['assessedOn'] = '2026-10-26'
            with self.assertRaises(SchemaxisError): assessments.validate(record, 'gmsh')

    def test_fingerprint_is_portable_with_zipped_plugin_traversable(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/'fixture'; (folder/'nested').mkdir(parents=True)
            (folder/'nested/native.py').write_text('value = 1\n')
            (folder/'adaptor.json').write_text('{"fixture": true}')
            (folder/'assessment.json').write_text('ignored editorial text')
            archive = Path(tmp)/'plugin.zip'
            with zipfile.ZipFile(archive, 'w') as zipped:
                for path in folder.rglob('*'):
                    if path.is_file(): zipped.write(path, 'fixture/'+path.relative_to(folder).as_posix())
            with patch.object(registry, 'adaptor_files', return_value=folder):
                expected = assessments.source_fingerprint('gmsh')
                (folder/'assessment.json').write_text('changed editorial text')
                self.assertEqual(assessments.source_fingerprint('gmsh'), expected)
                (folder/'nested/native.py').write_text('value = 2\n')
                self.assertNotEqual(assessments.source_fingerprint('gmsh'), expected)
            with zipfile.ZipFile(archive) as zipped, \
                    patch.object(registry, 'adaptor_files', return_value=zipfile.Path(zipped, 'fixture/')):
                self.assertEqual(assessments.source_fingerprint('gmsh'), expected)

    def test_comparison_refuses_changed_denominators_and_tracks_inventory(self):
        current = assessments.report(['gmsh', 'r'])
        baseline = copy.deepcopy(current)
        baseline['providers'][0]['assessment']['record']['coverage']['percent'] -= 5
        comparison = assessments.compare(current, baseline)
        self.assertEqual(comparison['providers'][0]['coverage']['deltaPoints'], 5)
        baseline['providers'][0]['assessment']['record']['coverage']['scope']['denominator'] = 'Another functional scope.'
        comparison = assessments.compare(current, baseline)
        self.assertFalse(comparison['providers'][0]['coverage']['comparable'])
        self.assertIsNone(comparison['providers'][0]['coverage']['deltaPoints'])
        baseline['providers'].pop()
        # A full historical snapshot with one provider permits a true addition;
        # a filtered historical snapshot would mean unselected, not added.
        baseline['selection'] = {'mode': 'all', 'providers': ['gmsh']}
        self.assertEqual(assessments.compare(current, baseline)['providers'][-1]['inventoryChange'], 'added')
        baseline['providers'].append(copy.deepcopy(baseline['providers'][0]))
        with self.assertRaises(SchemaxisError) as caught:
            assessments.compare(current, baseline)
        self.assertEqual(caught.exception.fault.code, 'INVALID_ASSESSMENT_BASELINE')

    def test_filtered_comparison_does_not_report_unselected_providers_removed(self):
        full = json.loads(BASELINE.read_text())
        current = assessments.report(['gmsh'])
        self.assertEqual(current['selection'], {'mode': 'providers', 'providers': ['gmsh']})
        comparison = assessments.compare(current, full)
        self.assertEqual([entry['id'] for entry in comparison['providers']], ['gmsh'])
        self.assertEqual(comparison['providers'][0]['inventoryChange'], 'retained')
        self.assertEqual(comparison['selection']['current'], current['selection'])
        self.assertEqual(len(comparison['selection']['baselineNotSelected']), 40)
        # Full queries still distinguish a genuine removed provider.
        current = assessments.report()
        absent = copy.deepcopy(current['providers'][0]); absent['id'] = 'historical_removed'
        absent['assessment']['record']['provider'] = absent['id']
        full['providers'].append(absent)
        self.assertIn('selection', full)
        full['selection']['providers'].append(absent['id'])
        self.assertEqual(next(entry for entry in assessments.compare(current, full)['providers']
                              if entry['id'] == absent['id'])['inventoryChange'], 'removed')

        # A filtered baseline must not manufacture later provider additions.
        filtered = assessments.report(['gmsh'])
        comparison = assessments.compare(current, filtered)
        self.assertEqual([entry['id'] for entry in comparison['providers']], ['gmsh'])
        self.assertEqual(len(comparison['selection']['currentNotSelectedInBaseline']), len(registry.ADAPTORS)-1)

    def test_baseline_without_selection_cannot_establish_inventory_changes(self):
        current = assessments.report()
        for baseline in (assessments.report(), assessments.report(['gmsh'])):
            del baseline['selection']
            with self.subTest(providers=baseline['providerCount']):
                with self.assertRaises(SchemaxisError) as caught:
                    assessments.compare(current, baseline)
                self.assertEqual(caught.exception.fault.code, 'INVALID_ASSESSMENT_BASELINE')

    def test_resource_changes_in_every_native_language_mark_source_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/'adaptor.json').write_text('{"fixture": true}')
            with patch.object(registry, 'adaptor_files', return_value=folder):
                old = assessments.source_fingerprint('gmsh')
                for name in ('panel.html', 'script.jsx', 'scene.gd', 'macro.ijm', 'native.bin'):
                    with self.subTest(name=name):
                        resource = folder/name; resource.write_bytes(b'first resource bytes')
                        added = assessments.source_fingerprint('gmsh')
                        self.assertNotEqual(added, old)
                        resource.write_bytes(b'changed resource bytes')
                        self.assertNotEqual(assessments.source_fingerprint('gmsh'), added)
                        resource.unlink()
                        self.assertEqual(assessments.source_fingerprint('gmsh'), old)

    def test_plugin_package_import_failure_is_independent_invalid_state(self):
        original = registry.adaptor_files
        def resources(provider):
            if provider == 'gmsh': raise ImportError('fixture package resource failure')
            return original(provider)
        with patch.object(registry, 'adaptor_files', side_effect=resources):
            value = assessments.assessment('gmsh')
            self.assertEqual(value['status'], 'invalid')
            self.assertEqual(assessments.report(['gmsh'])['providerCount'], 1)
            self.assertEqual(registry.discover()['providerCount'], len(registry.ADAPTORS))

    def test_real_generated_index_matches_current_report(self):
        spec = importlib.util.spec_from_file_location('real_assessment_generator', ROOT/'tools/generate_adaptor_assessments.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertEqual(module.markdown(assessments.report(module.builtin_providers())), module.OUTPUT.read_text(),
                         'Run tools/generate_adaptor_assessments.py after reviewing changed assessments.')

    def test_catalogue_revision_tracks_assessment_edits_without_mutating_snapshot(self):
        old = CapabilityCatalogue(['gmsh'])
        original = assessments.assessment
        def changed(provider):
            value = original(provider)
            value['record']['abstraction']['percent'] -= 5
            return value
        with patch.object(assessments, 'assessment', side_effect=changed):
            new = CapabilityCatalogue(['gmsh'])
        self.assertNotEqual(old.revision, new.revision)
        before = old.browse()['items'][0]['assessment']['abstractionPercent']
        after = new.browse()['items'][0]['assessment']['abstractionPercent']
        self.assertEqual(before-after, 5)
        self.assertEqual(old.browse()['items'][0]['assessment']['abstractionPercent'], before)

    def test_cli_json_text_and_compare_are_host_only(self):
        script = '''
import importlib.abc, sys
class RejectNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'bpy','paraview','FreeCAD','gmsh','qgis','cantera','numpy','pyarrow','sympy','PySide6'}:
            raise AssertionError('native import: ' + fullname)
sys.meta_path.insert(0, RejectNative())
from schemaxis.__main__ import console_main
sys.exit(console_main())
'''
        for args in (['assessments', '--app', 'gmsh'], ['assessments', '--app', 'premiere', '--format', 'text'],
                     ['assessments', '--compare', str(BASELINE)]):
            result = subprocess.run([sys.executable, '-c', script, *args], cwd=ROOT,
                env={**os.environ, 'PYTHONPATH': str(ROOT/'src'), 'SCHEMAXIS_ADAPTOR_PLUGINS':'off'},
                text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            if '--format' in args:
                self.assertIn('1 registered application providers; 1 authorable routes.', result.stdout)
                self.assertIn('native qualification', result.stdout)
            else:
                value = json.loads(result.stdout)
                self.assertIn('providerCount', value)
                if '--compare' in args: self.assertIn('comparison', value)

    def test_generator_checks_drift_and_refuses_baseline_overwrite(self):
        spec = importlib.util.spec_from_file_location('assessment_generator', ROOT/'tools/generate_adaptor_assessments.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        baseline = json.loads(BASELINE.read_text())
        self.assertIn('41 registered application providers expose 47 authorable routes', module.markdown(baseline))
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'index.md'; old = Path(tmp)/'old.json'
            value = assessments.report(['gmsh'])
            output.write_text(module.markdown(value)); old.write_text('preserve\n')
            with patch.object(module, 'OUTPUT', output), patch.object(module, 'report', return_value=value):
                with patch.object(sys, 'argv', ['generate', '--check']): module.main()
                output.write_text('stale')
                with patch.object(sys, 'argv', ['generate', '--check']), self.assertRaises(SystemExit): module.main()
                with patch.object(sys, 'argv', ['generate', '--write-baseline', str(old)]), self.assertRaises(FileExistsError): module.main()
                self.assertEqual(output.read_text(), 'stale', 'existing baseline refusal must not mutate the index')
            self.assertEqual(old.read_text(), 'preserve\n')

    def test_generator_failure_removes_incomplete_baseline_and_allows_retry(self):
        spec = importlib.util.spec_from_file_location('assessment_generator_failure', ROOT/'tools/generate_adaptor_assessments.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'index.md'; baseline = Path(tmp)/'baseline.json'
            output.write_text('preserve index')
            with patch.object(module, 'OUTPUT', output), patch.object(module, 'report', side_effect=RuntimeError('fixture report failure')):
                with patch.object(sys, 'argv', ['generate', '--write-baseline', str(baseline)]):
                    with self.assertRaisesRegex(RuntimeError, 'fixture report failure'): module.main()
            self.assertFalse(baseline.exists())
            self.assertEqual(output.read_text(), 'preserve index')
            value = assessments.report(['gmsh'])
            with patch.object(module, 'OUTPUT', output), patch.object(module, 'report', return_value=value):
                with patch.object(sys, 'argv', ['generate', '--write-baseline', str(baseline)]): module.main()
            self.assertEqual(json.loads(baseline.read_text()), value)

    def test_public_generator_rejects_plugins_and_parity_selects_builtins(self):
        spec = importlib.util.spec_from_file_location('assessment_generator_plugins', ROOT/'tools/generate_adaptor_assessments.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        original = set(module.builtin_providers())
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'index.md'; baseline = Path(tmp)/'baseline.json'
            output.write_text('preserve public index')
            with patch.dict(registry.ADAPTORS, {'privatefixture': {'source': 'entry-point'}}):
                self.assertEqual(set(module.builtin_providers()), original)
                self.assertEqual(module.markdown(assessments.report(module.builtin_providers())), module.OUTPUT.read_text())
                with patch.object(module, 'OUTPUT', output), patch.object(sys, 'argv', ['generate', '--write-baseline', str(baseline)]):
                    with self.assertRaises(SchemaxisError) as caught: module.main()
                self.assertEqual(caught.exception.fault.code, 'PLUGIN_ADAPTORS_LOADED')
            self.assertFalse(baseline.exists())
            self.assertEqual(output.read_text(), 'preserve public index')


if __name__ == '__main__':
    unittest.main()
