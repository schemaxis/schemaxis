# Copyright (C) 2026 David L F Gaden
"""Output naming is a post-verification view that never overwrites evidence.

Runs are produced by the real workflow executor and verified by the real
workflow verifier; only the native adaptor process and its own receipt check
are replaced by a host fixture, as in test_deferred_workflow_handoffs.
"""
import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis import output_naming, workflow
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.workflow_authoring import example


def fixture_receipt(directory, expected):
    directory = Path(directory)
    if json.loads((directory / 'authored.json').read_text()) != expected:
        raise AssertionError('fixture input differs')
    return json.loads((directory / 'verification.json').read_text())


def fixture_run(document, directory, *args, **kwargs):
    directory = Path(directory)
    directory.mkdir(parents=True)
    atomic_json(directory / 'authored.json', document)
    artifacts = []
    for filename in ('result.csv', 'summary.json'):
        path = directory / filename
        path.write_text('fixture publication for ' + json.dumps(document, sort_keys=True)[:40])
        artifacts.append({'file': str(path), 'kind': 'table', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    atomic_json(directory / 'verification.json', {'artifacts': artifacts})
    return {'verified': True}


class OutputNamingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for target, replacement in (('schemaxis.parallel.run_native', fixture_run),
                                    ('schemaxis.parallel.verify_native', fixture_receipt)):
            patcher = patch(target, side_effect=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch('schemaxis.parallel.reusable_inputs', return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def fault(self, code, action):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def run_workflow(self, document=None, name='run'):
        directory = self.root / name
        self.assertTrue(workflow.execute(document or example(), directory)['verified'])
        return directory

    def test_pattern_validation_and_sanitising(self):
        self.assertEqual(output_naming.validate_pattern(output_naming.DEFAULT_PATTERN),
                         ['index', 'operation', 'output', 'ext'])
        for pattern in ('', 'plain', '../{index}', '{index}/x', '{unknown}', '{param:1x}', '.{index}', 'a b{index}',
                        '{index', 'x' * 300 + '{index}', 3):
            with self.subTest(pattern=pattern):
                self.fault('INVALID_NAMING', lambda: output_naming.validate_pattern(pattern))
        for width in (0, 13, True, 2.0):
            with self.subTest(width=width):
                self.fault('INVALID_NAMING', lambda: output_naming.validate_width(width))
        cases = [(0.5, '0p5'), (-2, 'm2'), (2.0, '2'), (-0.125, 'm0p125'), (1e-7, '1em07'), (True, 'yes'),
                 (False, 'no'), ('inlet v1.2', 'inlet_v1p2'), ('a/b', 'a_b'), ([1, 2.5], '1_2p5'), (None, 'none')]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(output_naming.sanitise(value), expected)
        self.fault('INVALID_NAMING', lambda: output_naming.sanitise({'a': 1}))

    def test_preview_matches_live_ui_needs(self):
        entries = [{'operation': 'mesh', 'output': 'volume', 'ext': '.vtu', 'parameters': {'inlet': 2.5}},
                   {'operation': 'mesh', 'output': 'volume', 'ext': '.vtu', 'parameters': {'inlet': -1}}]
        result = output_naming.preview('{index}-inlet_{param:inlet}-{output}{ext}', entries, index_width=3)
        self.assertEqual(result, {'names': ['001-inlet_2p5-volume.vtu', '002-inlet_m1-volume.vtu'], 'collisions': []})
        collided = output_naming.preview('{operation}{ext}', entries)
        self.assertEqual(collided['collisions'], ['mesh.vtu'])
        self.fault('INVALID_NAMING', lambda: output_naming.preview('{param:missing}{index}', entries))

    def test_apply_links_verified_artifacts_and_records_sources(self):
        directory = self.run_workflow()
        outputs = {'scaled': {'operation': 'scaled', 'artifact': 0, 'kind': 'table'}}
        result = output_naming.apply(directory, '{index}-{operation}-{output}-f{param:factor}{ext}', index_width=2,
                                     parameters={'factor': 0.5}, outputs=outputs)
        named = directory / 'named'
        self.assertEqual(sorted(path.name for path in named.iterdir()), [
            '01-samples-result-f0p5.csv', '02-samples-summary-f0p5.json', '03-scaled-scaled-f0p5.csv',
            '04-scaled-summary-f0p5.json', 'naming.json'])
        manifest = json.loads((named / 'naming.json').read_text())
        self.assertEqual(manifest, {key: result[key] for key in manifest})
        entry = manifest['names']['03-scaled-scaled-f0p5.csv']
        self.assertEqual((entry['operation'], entry['artifact'], entry['output'], entry['method']),
                         ('scaled', 0, 'scaled', 'hardlink'))
        source = directory / entry['source']
        self.assertEqual(os.stat(source).st_ino, os.stat(named / '03-scaled-scaled-f0p5.csv').st_ino)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), entry['sha256'])
        self.assertTrue(manifest['verification']['verified'])
        self.assertTrue(workflow.verify(directory)['verified'])
        self.fault('OUTPUT_EXISTS', lambda: output_naming.apply(directory, '{index}{ext}'))

    def test_collisions_and_unverified_runs_create_nothing(self):
        directory = self.run_workflow()
        self.fault('NAMING_COLLISION', lambda: output_naming.apply(directory, '{operation}'))
        self.assertFalse((directory / 'named').exists())
        self.fault('INVALID_NAMING', lambda: output_naming.apply(directory, '{index}-{axis:stop}{ext}'))
        result = json.loads((directory / 'result.json').read_text())
        result['status'] = 'failed'
        atomic_json(directory / 'result.json', result)
        self.fault('INCOMPLETE_EXECUTION', lambda: output_naming.apply(directory, '{index}{ext}'))
        self.assertFalse((directory / 'named').exists())

    def test_cross_device_publication_copies_and_rechecks(self):
        directory = self.run_workflow()
        with patch('schemaxis.output_naming._hard_link', side_effect=OSError(errno.EXDEV, 'cross-device link')):
            result = output_naming.apply(directory, '{index}{ext}')
        self.assertEqual({entry['method'] for entry in result['names'].values()}, {'copy'})
        copied = directory / 'named' / '000001.csv'
        self.assertNotEqual(os.stat(copied).st_ino, os.stat(directory / result['names']['000001.csv']['source']).st_ino)

    def test_study_axes_name_each_state_in_deterministic_order(self):
        document = example()
        document['axes'] = [{'name': 'stop', 'values': [4, 8.5]}]
        document['settings'] = {'stop': {'$axis': 'stop'}}
        document['operations'][0]['document']['nodes'][0]['options']['stop'] = {
            '$document': '/settings/stop', 'scope': 'workflow'}
        directory = self.run_workflow(document, 'study')
        result = output_naming.apply(directory, '{index}-s{axis:stop}-{operation}-{artifact}{ext}', index_width=1)
        self.assertEqual(list(result['names']), [
            '1-s4-samples-0.csv', '2-s4-samples-1.json', '3-s4-scaled-0.csv', '4-s4-scaled-1.json',
            '5-s8p5-samples-0.csv', '6-s8p5-samples-1.json', '7-s8p5-scaled-0.csv', '8-s8p5-scaled-1.json'])
        self.assertTrue(result['names']['5-s8p5-samples-0.csv']['source'].startswith('state-00001/'))
        self.assertEqual(result['names']['5-s8p5-samples-0.csv']['axes'], {'stop': 8.5})


if __name__ == '__main__':
    unittest.main()
