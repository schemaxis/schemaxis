"""Release monitoring must distinguish unknown state from successful absorption."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from schemaxis import updates


class UpstreamUpdateTests(unittest.TestCase):
    def test_stable_version_order_and_prerelease_rejection(self):
        self.assertEqual(updates.version('47'), updates.version('47.0.0'))
        self.assertGreater(updates.version('47'), updates.version('46.2'))
        self.assertGreater(updates.version('v1.3.18.6'), updates.version('1.3.17.2'))
        self.assertEqual(updates.version('4.7.2-stable'), updates.version('4.7.2'))
        for bad in ('6.2.0-RC2', '6.1-final', '5.3-alpha', 'weekly-builds', 'n8.0'):
            with self.assertRaises(ValueError): updates.version(bad)

    def test_gitlab_excludes_release_candidates_and_final_branch_tags(self):
        source = {'kind': 'gitlab-tags', 'url': 'unused'}
        payload = json.dumps([{'name': v} for v in ['v6.2.0-RC2', 'v6.1-final', 'v6.1.1', 'v5.13.3']])
        self.assertEqual(updates.latest(source, lambda _: payload), '6.1.1')

    def test_github_draft_and_prerelease_are_not_accepted(self):
        for flag in ('draft', 'prerelease'):
            with self.assertRaises(ValueError):
                updates.latest({'kind': 'github-release', 'url': 'unused'},
                               lambda _: json.dumps({'tag_name': '1.2.3', flag: True}))

    def test_blender_download_parser_excludes_prerelease_filenames(self):
        policy = json.loads((Path(updates.__file__).parent/'adaptors/blender/upstream.json').read_text())
        payload = 'blender-5.3.0-alpha-linux-x64.tar.xz blender-5.2.2-linux-x64.tar.xz'
        self.assertEqual(updates.latest(policy['source'], lambda _: payload), '5.2.2')

    def test_octave_download_parser_handles_native_html_markup(self):
        policy = json.loads((Path(updates.__file__).parent/'adaptors/octave/upstream.json').read_text())
        for payload in ('<strong>GNU Octave 11.3.0</strong> is the latest stable release.',
                        'GNU Octave 11.3.0 is the latest stable release.'):
            self.assertEqual(updates.latest(policy['source'], lambda _: payload), '11.3.0')

    def test_pattern_does_not_treat_empty_page_as_current(self):
        with self.assertRaises(ValueError):
            updates.latest({'kind': 'pattern', 'url': 'unused', 'pattern': r'blender-(\d+\.\d+\.\d+)-'}, lambda _: 'blocked')

    def test_report_separates_updates_current_stale_failed_and_manual(self):
        def reader(url):
            if 'aseprite' in url: return json.dumps({'tag_name': 'v1.3.18.6'})
            if 'FreeCAD' in url: return json.dumps({'tag_name': '1.1.3'})
            if 'godot' in url: return json.dumps({'tag_name': '4.6.0-stable'})
            raise OSError('offline')
        # A licensed runtime without a public release feed is a manual check.
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(updates.ADAPTORS, {'manualapp': {'id': 'manualapp', 'source': 'builtin'}}), \
                patch('schemaxis.updates.adaptor_files',
                      side_effect=lambda app: Path(tmp)/app):
            for app, absorbed in [('aseprite', '1.3.17.2'), ('freecad', '1.1.3'),
                                  ('godot', '4.7.2'), ('blender', '5.2.0')]:
                target = Path(tmp)/app
                target.mkdir()
                target.joinpath('upstream.json').write_text(json.dumps({
                    'policy': 'latest-stable', 'absorbedVersion': absorbed,
                    'source': {'kind': 'github-release', 'url': 'FreeCAD' if app == 'freecad' else app},
                    'evidence': []}))
            (Path(tmp)/'manualapp').mkdir()
            (Path(tmp)/'manualapp/upstream.json').write_text(json.dumps(
                {'policy': 'latest-stable', 'absorbedVersion': None, 'source': None,
                 'manualReason': 'licensed runtime; no public release feed', 'evidence': []}))
            result = updates.report(['aseprite', 'freecad', 'godot', 'blender', 'manualapp'], reader)
        self.assertEqual([x['app'] for x in result['updates']], ['aseprite'])
        self.assertEqual(result['current'], ['freecad'])
        self.assertEqual({x['app']: x['status'] for x in result['attention']},
                         {'blender': 'check-failed', 'manualapp': 'manual-check', 'godot': 'source-behind'})
        self.assertEqual(result['updates'][0]['estimate']['change'], 'patch')

    def test_estimates_are_labelled_heuristics_and_scale_for_catalogues(self):
        small = updates.estimate('5.13.3', '6.1.1', 10)
        large = updates.estimate('5.13.3', '6.1.1', 600)
        self.assertEqual(small['confidence'], 'low')
        self.assertEqual(large['personDays'], [2*x for x in small['personDays']])

    def test_manual_letter_version_keeps_qualification_but_never_reports_current(self):
        def unexpected_fetch(_):
            self.fail('manual release policy must not fetch or compare numeric versions')
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.updates.adaptor_files', return_value=Path(tmp)):
            (Path(tmp)/'upstream.json').write_text(json.dumps({
                'policy': 'latest-stable', 'source': None, 'absorbedVersion': '1.54t',
                'manualReason': 'letter-suffixed releases need manual review', 'evidence': []}))
            result = updates.check('manualapp', unexpected_fetch)
        self.assertEqual(result['status'], 'manual-check')
        self.assertEqual(result['absorbedVersion'], '1.54t')
        self.assertTrue(result['reason'])
        self.assertNotIn('latestVersion', result)

    def test_prepare_writes_reviewable_tasks_without_changing_baselines(self):
        root = Path(updates.__file__).parent/'adaptors'
        before = {p: p.read_bytes() for p in root.glob('*/upstream.json')}
        result = updates.report(['freecad'], lambda _: json.dumps({'tag_name': '2.0.0'}))
        with tempfile.TemporaryDirectory() as tmp:
            updates.prepare(result, tmp)
            prompt = (Path(tmp)/'freecad.md').read_text()
            self.assertIn('src/schemaxis/adaptors/freecad/', prompt)
            self.assertIn('retain the old baseline', prompt)
            self.assertIn('qualify_freecad_assembly.py', prompt)
            self.assertEqual(json.loads((Path(tmp)/'report.json').read_text()), result)
            self.assertIn('freecad', (Path(tmp)/'report.md').read_text())
            with self.assertRaises(FileExistsError): updates.prepare(result, tmp)
        self.assertTrue(all(p.read_bytes() == data for p, data in before.items()))

    def test_every_registered_app_has_portable_update_policy(self):
        root = Path(updates.__file__).parent/'adaptors'
        # External adaptor packages keep their evidence in their own repositories.
        for app in [a for a, item in updates.ADAPTORS.items() if item['source'] == 'builtin']:
            policy = json.loads((root/app/'upstream.json').read_text())
            self.assertEqual(policy['policy'], 'latest-stable')
            self.assertTrue(policy['acceptance'])
            if policy['source']:
                if policy['absorbedVersion']: updates.version(policy['absorbedVersion'])
            else:
                # Manual policies retain native release labels (e.g. ImageJ
                # 1.54t); they never claim numeric comparison or current status.
                self.assertTrue(policy['manualReason'].strip())
                if policy['absorbedVersion'] is not None:
                    self.assertIsInstance(policy['absorbedVersion'], str)
                    self.assertTrue(policy['absorbedVersion'].strip())
            for evidence in policy['evidence']:
                self.assertFalse(Path(evidence).is_absolute())
                self.assertTrue((root.parents[2]/evidence).is_file(), evidence)
