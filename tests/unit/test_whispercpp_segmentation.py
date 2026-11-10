"""Optional maxSegmentLength: a native word-aware segmentation target with honest limits.

Host-only checks with the deterministic native test double from test_whispercpp; the test double
records its argv and replays cues, so nothing here is native acceptance. The real whisper.cpp
proof is tools/qualify_whispercpp.py (cases jfk-short-cues and jfk-short-cues-review).
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from schemaxis.adaptors.whispercpp import adaptor as a
from schemaxis.adaptors.whispercpp import segmentation as sg
from schemaxis.core.faults import SchemaxisError

try: import test_whispercpp as base
except ModuleNotFoundError: from tests.unit import test_whispercpp as base

ROOT = base.ROOT
# Taken from the unmodified adaptor before this option existed, with this exact deterministic audio, model bytes and cues.
PRE_OPTION = {
    'basePlan': '5d0a7a96af232568b818d642b49109449eff4b566d0b77df5ff160b9028d32e1',
    'planJson': '3394d336ba943dee6eb606f266aeb400971558fe5bf9563e44fc70ed05f03e2a',
    'segments': 'f1cfa8f42e0e72641e7bfa8ea41e9d0f73af8dd3ea814c265a3048055da121e4',
    'transcript': '02c88cecbe42e931c4f0ed3aed2a670d6d1179e76db834c3c3cad3e2bdd79a5c',
    'srt': 'f3bb18606bac78727fc0e2dad24a6f6ba878f9b86e18a14319f95597789e8fad',
    'vtt': 'd4ce03547057d17ae95e2a8702f0c3408f8a537a419d709b2d37c3383369b4d0',
    'result': {'verified': True, 'artifacts': 4, 'runtime': 'whisper.cpp 1.9.5', 'segments': 2, 'audioDurationMs': 11000,
               'audioSha256': 'e236b039d02d0e904fc7a09e132f32916e9b7570e63b93c752b82c68b6bf8a52',
               'modelSha256': '34398b85297bf7d9dfb59b8d511d8bbb44ab23e891570e4395e7871475fc8afb',
               'accuracyCertified': False, 'humanReviewRequired': True, 'status': 'succeeded'}}
# The cue boundaries the real whisper.cpp 1.9.5 run produced for the public sample with -ml 42 -sow.
JFK_42 = [(0, 5410, 'And so my fellow Americans, ask not what'), (5410, 9040, 'your country can do for you, ask what you'), (9040, 11000, 'can do for your country.')]
# Every call records its argv beyond the base test double, outside the run directory (a stray file there is a membership fault).
FAKE = base.FAKE + "Path(cfg['argv_log']).write_text(json.dumps(args))\n"


def sha(data): return hashlib.sha256(data).hexdigest()


class Option(unittest.TestCase):
    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught: action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def doc(self, **extra): return {**json.loads((ROOT / 'examples/schemaxis/whispercpp-jfk.json').read_text()), **extra}

    def test_declared_as_an_optional_bounded_integer_without_a_default(self):
        declared = a.schema()['properties']['maxSegmentLength']
        self.assertEqual((declared['type'], declared['minimum'], declared['maximum']), ('integer', 16, 200))
        self.assertNotIn('default', declared)
        self.assertNotIn('maxSegmentLength', a.schema()['required'])
        self.assertEqual((sg.MINIMUM, sg.MAXIMUM, sg.OPTION), (16, 200, 'maxSegmentLength'))

    def test_boundary_values_are_accepted_and_kept_as_authored(self):
        for value in (16, 17, 42, 199, 200):
            p = a.plan(self.doc(maxSegmentLength=value))
            self.assertEqual(p['maxSegmentLength'], value);self.assertIs(type(p['maxSegmentLength']), int)

    def test_every_other_value_is_refused_with_a_stable_code_and_location(self):
        for bad in (15, 201, 0, -1, 10 ** 9, True, False, 42.0, 42.5, '42', '', None, [], [42], {}, {'n': 42}):
            fault = self.fault(lambda: a.plan(self.doc(maxSegmentLength=bad)), 'INVALID_ARGUMENT')
            self.assertEqual(fault.location, '$.arguments.maxSegmentLength', repr(bad))
            self.assertTrue(fault.recovery or fault.observed, repr(bad))
        fault = self.fault(lambda: a.plan(self.doc(maxSegmentLength=15)), 'INVALID_ARGUMENT')
        self.assertEqual(fault.observed, {'value': 15, 'minimum': 16, 'exclusive': False})
        self.assertEqual(self.fault(lambda: a.plan(self.doc(maxSegmentLength=201)), 'INVALID_ARGUMENT').observed['maximum'], 200)

    def test_only_the_one_option_exists_no_native_flag_or_sibling_spelling(self):
        for name in ('maxLen', 'max-len', 'ml', 'splitOnWord', 'sow', 'maxSegmentChars', 'maxSegmentBytes', 'maxSegmentLenght', 'segmentation', 'wordTimestamps', 'nativeArguments'):
            with self.assertRaises(SchemaxisError, msg=name): a.plan(self.doc(**{name: 42}))

    def test_unauthored_plans_losses_and_command_keep_their_exact_bytes(self):
        plain = a.plan(self.doc())
        self.assertEqual(set(plain), {'version', 'operation', 'audio', 'model', 'language', 'losses'})
        self.assertEqual(plain['losses'], a.LOSSES);self.assertEqual(len(plain['losses']), 5)
        self.assertEqual(sha(json.dumps(plain, sort_keys=True).encode()), PRE_OPTION['basePlan'])
        self.assertEqual(a.commands('/x/whisper-cli', plain)['transcribe'][-6:], ['1', '-ng', '-oj', '-osrt', '-of', 'native'])
        for stage, command in a.commands('/x/whisper-cli', plain).items():
            self.assertNotIn('-ml', command);self.assertNotIn('-sow', command)
        # Each existing option keeps its own exact effect, with and without the new one.
        review = a.plan(self.doc(captionReview=True))
        self.assertEqual(review['losses'], [*a.LOSSES, base.cr.LOSS])
        both = a.plan(self.doc(captionReview=True, maxSegmentLength=42))
        self.assertEqual(both['losses'], [*a.LOSSES, base.cr.LOSS, sg.LOSS])
        only = a.plan(self.doc(maxSegmentLength=42))
        self.assertEqual(only['losses'], [*a.LOSSES, sg.LOSS])
        self.assertEqual({k: v for k, v in only.items() if k not in ('maxSegmentLength', 'losses')}, {k: v for k, v in plain.items() if k != 'losses'})

    def test_authored_option_adds_exactly_the_two_native_arguments_before_the_output_name(self):
        p = a.plan(self.doc(maxSegmentLength=42))
        command = a.commands('/x/whisper-cli', p)['transcribe']
        self.assertEqual(command[-9:], ['1', '-ng', '-oj', '-osrt', '-ml', '42', '-sow', '-of', 'native'])
        plain = a.commands('/x/whisper-cli', a.plan(self.doc()))['transcribe']
        self.assertEqual([x for x in command if x not in ('-ml', '42', '-sow')], plain)
        for stage in ('version', 'libraries'): self.assertEqual(a.commands('/x/y', p)[stage], ['/x/y', '--version'])

    def test_example_is_the_baseline_plus_the_option_and_the_losses_state_the_limits(self):
        example = json.loads((ROOT / 'examples/schemaxis/whispercpp-short-cues.json').read_text())
        self.assertEqual({k: v for k, v in example.items() if k != 'maxSegmentLength'}, self.doc())
        self.assertEqual(a.plan(example)['maxSegmentLength'], 42)
        for needle in ('target', 'not a guaranteed maximum', 'code points', 'bytes', 'leading space', 'space', 'experimental', 'never refused', 'not certified'):
            self.assertIn(needle, sg.LOSS)
        for claim in ('accuracy', 'confidence', 'speaker'): self.assertNotIn(claim + ' is certified', sg.STATEMENT)
        self.assertIn('machine draft', sg.STATEMENT);self.assertIn('review', sg.STATEMENT)

    def test_discovery_guidance_and_readiness_describe_the_option(self):
        from schemaxis.adaptors import registry
        guide = json.loads((ROOT / 'src/schemaxis/adaptors/whispercpp/guidance.json').read_text())
        record = guide['routes'][a.VERSION]['fields']['/properties/maxSegmentLength']
        self.assertEqual(record['status'], 'reviewed')
        for needle in ('target', 'code points', 'word', 'experimental', 'not certified'): self.assertIn(needle, record['explanation'])
        self.assertTrue(any('guarantee' in text for text in record['pitfalls']))
        self.assertTrue(any('Unspaced' in text for text in record['pitfalls']))
        self.assertEqual(record['examples'], [42])
        capabilities = registry.binding(registry.metadata('whispercpp')['capabilities'])()
        operation = capabilities['operations']['transcribe']
        text = json.dumps(capabilities)
        for needle in ('maxSegmentLength', 'not a guaranteed maximum', 'experimental', 'whispercpp-short-cues.json'): self.assertIn(needle, text)
        self.assertIn('shorter caption cues', operation['keywords'])
        readiness = json.loads((ROOT / 'src/schemaxis/adaptors/whispercpp/readiness.json').read_text())['routes'][a.VERSION]
        self.assertIn('short-cues', [e['id'] for e in readiness['examples']])
        cases = {c['id']: c for c in readiness['development']['cases']}
        self.assertEqual(set(cases) & {'jfk-short-cues', 'jfk-short-cues-review'}, {'jfk-short-cues', 'jfk-short-cues-review'})
        self.assertEqual(cases['jfk-short-cues-review']['edits'], [{'op': 'add', 'path': '/captionReview', 'value': True}])
        expected = {c['pointer']: c['expected'] for c in cases['jfk-short-cues']['checks']}
        self.assertEqual([expected[f'/segments/{i}/{k}'] for i in range(3) for k in ('startMs', 'endMs', 'text')], [v for cue in JFK_42 for v in cue])
        self.assertEqual((expected['/segmentation/enforced'], expected['/segmentation/cuesOverTarget']), (False, 0))
        cases_text = json.dumps(readiness)
        self.assertIn('INVALID_ARGUMENT at $.arguments.maxSegmentLength', cases_text)
        self.assertTrue((ROOT / 'verification/2026-10-25-whispercpp-32.md').is_file())
        self.assertIn('verification/2026-10-25-whispercpp-32.md', readiness['completion']['review'])


class Counting(unittest.TestCase):
    """The host's observation: published code points above the target; never a check."""

    def over(self, target, *texts):
        segments = [{'index': i, 'startMs': i * 1000, 'endMs': i * 1000 + 900, 'text': t} for i, t in enumerate(texts)]
        return sg.observe({'maxSegmentLength': target}, segments)['cuesOverTarget']

    def test_exactly_the_target_is_not_over_and_one_more_is(self):
        self.assertEqual((self.over(16, 'a' * 16), self.over(16, 'a' * 17), self.over(16, 'a' * 15, 'b' * 16, 'c' * 17, 'd' * 40)), (0, 1, 2))

    def test_utf8_is_counted_in_code_points_not_bytes_graphemes_or_width(self):
        han = '日本語の' * 4        # 16 code points, 48 UTF-8 bytes
        self.assertEqual((len(han), len(han.encode())), (16, 48))
        self.assertEqual(self.over(16, han), 0)               # a byte count would call this three times over
        self.assertEqual(self.over(16, han + '。'), 1)
        accented = 'Café ' * 3 + 'Café'            # decomposed accents count as separate code points
        self.assertEqual((len(accented), accented.count('́')), (23, 4))
        self.assertEqual(self.over(16, accented), 1)
        family = '\U0001f469‍\U0001f4bb' * 6               # 6 emoji sequences = 18 code points, 6 graphemes
        self.assertEqual((len(family), self.over(16, family)), (18, 1))
        self.assertEqual(self.over(18, family), 0)

    def test_member_is_exact_and_states_that_nothing_is_enforced(self):
        member = sg.observe({'maxSegmentLength': 20}, [{'index': 0, 'startMs': 0, 'endMs': 900, 'text': 'x' * 30}, {'index': 1, 'startMs': 900, 'endMs': 1800, 'text': 'short'}])
        self.assertEqual(set(member), {'maxSegmentLength', 'nativeOptions', 'enforced', 'unit', 'cueCount', 'cuesOverTarget', 'statement'})
        self.assertEqual((member['maxSegmentLength'], member['nativeOptions'], member['enforced'], member['cueCount'], member['cuesOverTarget']), (20, ['-ml', '20', '-sow'], False, 2, 1))
        self.assertEqual(sg.summary(member), {'maxSegmentLength': 20, 'cues': 2, 'cuesOverTarget': 1, 'enforced': False})
        self.assertIsNone(sg.observe({}, []))
        self.assertEqual((sg.native_arguments({}), sg.losses({})), ([], []))
        self.assertEqual(sg.native_arguments({'maxSegmentLength': 99}), ['-ml', '99', '-sow'])

    def test_cues_over_the_target_are_valid_native_text_for_the_host(self):
        # A word longer than the target and unspaced script both stay whole in whisper.cpp; the strict native contract still accepts them.
        long_word = 'Pneumonoultramicroscopicsilicovolcanoconiosis'
        han = '日本語の文字' * 12        # 72 code points, no space-led token to split at
        segments = a.native_segments(base.native([(0, 2000, long_word), (2000, 4000, han), (4000, 6000, 'ok')]), {'language': 'en'}, 176000)
        self.assertEqual([len(s['text']) for s in segments], [45, 72, 2])
        document = a.segment_document({'language': 'en', 'maxSegmentLength': 16}, segments, '0' * 64, {'bytes': 1, 'frames': 176000, 'rate': 16000, 'channels': 1}, '1' * 64, 1, '2' * 64)
        self.assertEqual(document['segmentation']['cuesOverTarget'], 2)


class Runs(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.dir = Path(self.temporary.name)
        self.audio = self.dir / 'speech.wav';self.audio.write_bytes(base.wav(176000))
        self.model = self.dir / 'tiny.bin';self.model.write_bytes(bytes((i * 7 + 3) % 256 for i in range(5000)))
        self.config = self.dir / 'fake.json';self.argv = self.dir / 'argv.json';self.exe = self.dir / 'whisper-cli'
        self.exe.write_text(FAKE.format(python=sys.executable, config=str(self.config)));self.exe.chmod(0o700)
        self.document = {'version': a.VERSION, 'operation': 'transcribe', 'audio': {'path': str(self.audio), 'sha256': sha(self.audio.read_bytes())},
                         'model': {'path': str(self.model), 'sha256': sha(self.model.read_bytes())}, 'language': 'en'}
        self.cues(JFK_42)

    def cues(self, cues, **change):
        config = {'version': 'whisper.cpp version: 1.9.5-dev', 'model_path': str(self.model), 'argv_log': str(self.argv), 'native': base.native(cues)};config.update(change)
        self.config.write_text(json.dumps(config))

    def job(self, name='run', **options):
        document = {**self.document, **options}
        return a.run(document, self.dir / name, executable=str(self.exe), timeout=60)

    def refuse(self, action, code=None):
        with self.assertRaises(SchemaxisError) as caught: action()
        if code: self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def refresh(self, directory):
        plan = a.read(directory, 'plan.json');review = plan.get('captionReview') is True
        receipt = a.read(directory, 'verification.json');receipt['artifacts'] = a.artifacts(directory, review)
        receipt['evidence'] = {n: a.digest(directory, n) for n in receipt['evidence']};a.atomic_json(directory / 'verification.json', receipt)
        from schemaxis.publication_metadata import finalise
        finalise(directory)

    def tamper_cases(self, directory, cases, code='VERIFICATION_FAILED'):
        saved = {p: p.read_bytes() for p in directory.iterdir() if p.is_file()}
        for name, target, mutate in cases:
            try:
                path = directory / target;before = path.read_bytes();after = mutate(before);self.assertNotEqual(after, before, name)
                path.write_bytes(after);self.refresh(directory)
                self.assertEqual(self.refuse(lambda: a.verify(directory)).code, code, name)
            finally:
                for path in [p for p in directory.iterdir() if p.is_file() and p not in saved]: path.unlink()
                for path, data in saved.items(): path.write_bytes(data)
        self.assertTrue(a.verify(directory)['verified'])

    def edited(self, change):
        def mutate(data):
            value = json.loads(data);change(value);return a.encode_json(value)
        return mutate

    def test_an_unauthored_run_is_byte_identical_to_the_one_made_before_the_option_existed(self):
        self.cues([(0, 2500, base.SPEECH), (2600, 11000, 'Ask what you can do.')], version='whisper.cpp version: 1.9.5')
        result = self.job('plain');directory = self.dir / 'plain'
        self.assertEqual(result, PRE_OPTION['result'])
        plan_bytes = (directory / 'plan.json').read_bytes().replace(str(self.audio).encode(), b'AUDIO').replace(str(self.model).encode(), b'MODEL')
        self.assertEqual(sha(plan_bytes), PRE_OPTION['planJson'])
        for name, key in (('segments.json', 'segments'), ('transcript.txt', 'transcript'), ('captions.srt', 'srt'), ('captions.vtt', 'vtt')):
            self.assertEqual(sha((directory / name).read_bytes()), PRE_OPTION[key], name)
        self.assertNotIn('segmentation', json.loads((directory / 'segments.json').read_text()))
        self.assertNotIn('segmentation', result)
        self.assertEqual(json.loads(self.argv.read_text())[-6:], ['1', '-ng', '-oj', '-osrt', '-of', 'native'])
        self.assertEqual(a.read(directory, 'plan.json')['losses'], a.LOSSES)

    def test_plain_run_matches_pre_option_result_pin_and_reopens_without_sources(self):
        # PRE_OPTION pins the old result; this new plain run must match it and reopen without external sources.
        self.cues([(0, 2500, base.SPEECH), (2600, 11000, 'Ask what you can do.')], version='whisper.cpp version: 1.9.5')
        self.job('genuine')
        self.assertEqual(a.verify(self.dir / 'genuine'), {k: v for k, v in PRE_OPTION['result'].items() if k != 'status'})
        self.audio.unlink();self.model.unlink()
        self.assertTrue(a.verify(self.dir / 'genuine')['verified'])

    def test_authored_run_passes_the_exact_arguments_and_publishes_the_native_cues(self):
        result = self.job('short', maxSegmentLength=42);directory = self.dir / 'short'
        argv = json.loads(self.argv.read_text())
        self.assertEqual(argv[argv.index('-osrt'):], ['-osrt', '-ml', '42', '-sow', '-of', 'native'])
        self.assertEqual((argv.count('-ml'), argv.count('-sow')), (1, 1))
        self.assertEqual(result['segments'], 3);self.assertEqual(result['artifacts'], 4)
        self.assertEqual(result['segmentation'], {'maxSegmentLength': 42, 'cues': 3, 'cuesOverTarget': 0, 'enforced': False})
        self.assertFalse(result['accuracyCertified']);self.assertTrue(result['humanReviewRequired'])
        self.assertEqual((directory / 'captions.srt').read_text(), ''.join(f'{i + 1}\n{base.clock(s)} --> {base.clock(e)}\n{t}\n\n' for i, (s, e, t) in enumerate(JFK_42)))
        self.assertEqual((directory / 'transcript.txt').read_text(), ''.join(t + '\n' for _, _, t in JFK_42))
        self.assertTrue((directory / 'captions.vtt').read_text().startswith('WEBVTT\n\n00:00:00.000 --> 00:00:05.410\n'))
        document = json.loads((directory / 'segments.json').read_text())
        self.assertEqual([(s['startMs'], s['endMs'], s['text']) for s in document['segments']], JFK_42)
        member = document['segmentation']
        self.assertEqual((member['maxSegmentLength'], member['nativeOptions'], member['enforced'], member['cueCount'], member['cuesOverTarget']), (42, ['-ml', '42', '-sow'], False, 3, 0))
        self.assertIn('draft', member['statement']);self.assertFalse(document['review']['accuracyCertified']);self.assertTrue(document['review']['humanReviewRequired'])
        plan = a.read(directory, 'plan.json')
        self.assertEqual((plan['maxSegmentLength'], plan['losses']), (42, [*a.LOSSES, sg.LOSS]))
        self.assertEqual(a.read(directory, 'authored.json')['maxSegmentLength'], 42)
        self.assertEqual(a.verify(directory), {k: v for k, v in result.items() if k != 'status'})
        self.assertEqual([Path(x['file']).name for x in a.read(directory, 'verification.json')['artifacts']], ['segments.json', 'transcript.txt', 'captions.srt', 'captions.vtt'])
        self.audio.unlink();self.model.unlink()
        self.assertTrue(a.verify(directory)['verified'])           # reopening needs neither original

    def test_the_option_changes_only_the_segmentation_member_not_the_words_or_other_policy(self):
        self.cues([(0, 11000, ' '.join(t for _, _, t in JFK_42))])
        self.job('whole');self.cues(JFK_42);self.job('split', maxSegmentLength=42)
        whole = json.loads((self.dir / 'whole/segments.json').read_text());split = json.loads((self.dir / 'split/segments.json').read_text())
        self.assertEqual(' '.join(s['text'] for s in whole['segments']), ' '.join(s['text'] for s in split['segments']))
        self.assertEqual({k: v for k, v in split.items() if k not in ('segmentation', 'segments', 'segmentCount', 'nativeJsonSha256')}, {k: v for k, v in whole.items() if k not in ('segments', 'segmentCount', 'nativeJsonSha256')})

    def test_cues_over_the_target_are_published_and_counted_never_refused(self):
        long_word = 'Pneumonoultramicroscopicsilicovolcanoconiosis'
        han = '日本語の文字' * 12
        self.cues([(0, 3000, 'short cue'), (3000, 6000, long_word), (6000, 9000, han), (9000, 11000, 'x' * 16), (11000, 12000, 'y' * 17)])
        self.audio.write_bytes(base.wav(200000));self.document['audio'] = {'path': str(self.audio), 'sha256': sha(self.audio.read_bytes())}
        result = self.job('over', maxSegmentLength=16);directory = self.dir / 'over'
        self.assertEqual(result['segmentation'], {'maxSegmentLength': 16, 'cues': 5, 'cuesOverTarget': 3, 'enforced': False})
        self.assertEqual(result['segments'], 5)
        self.assertIn(han, (directory / 'captions.srt').read_text(encoding='utf-8'))
        self.assertEqual(json.loads((directory / 'segments.json').read_text(encoding='utf-8'))['segmentation']['cuesOverTarget'], 3)
        self.assertTrue(a.verify(directory)['verified'])

    def test_strict_native_timing_and_text_checks_stay_in_force_with_the_option(self):
        bad = {'overlap': [(0, 3000, 'one'), (2000, 5000, 'two')], 'zero length': [(0, 1000, 'one'), (1000, 1000, 'two')], 'reversed': [(2000, 1000, 'one')],
               'beyond audio': [(0, 3000, 'one'), (3000, 11001, 'two')], 'blank': [(0, 1000, 'one'), (1000, 2000, '​')], 'markup': [(0, 1000, '<b>one</b>')], 'invalid order': [(5000, 6000, 'late'), (0, 1000, 'early')]}
        for name, cues in bad.items():
            self.cues(cues)
            fault = self.refuse(lambda: self.job('bad-' + name.replace(' ', '-'), maxSegmentLength=42))
            self.assertIn(fault.code, ('TRANSCRIPT_TIMING', 'TRANSCRIPT_INVALID'), name)
            directory = self.dir / ('bad-' + name.replace(' ', '-'))
            self.assertFalse((directory / 'segments.json').exists());self.assertFalse((directory / 'captions.srt').exists())
            self.assertEqual(a.read(directory, 'result.json')['status'], 'failed')
        self.cues([])
        self.refuse(lambda: self.job('empty', maxSegmentLength=42), 'TRANSCRIPT_EMPTY')
        self.cues(JFK_42, native_srt='1\n00:00:00,000 --> 00:00:05,410\n different text\n\n')
        self.refuse(lambda: self.job('native-srt', maxSegmentLength=42), 'VERIFICATION_FAILED')

    def test_rehashed_forgeries_of_the_segmentation_evidence_are_rejected(self):
        self.job('short', maxSegmentLength=42);directory = self.dir / 'short'
        S = 'segments.json'
        self.tamper_cases(directory, [
            ('cuesOverTarget lowered claim raised', S, self.edited(lambda d: d['segmentation'].update(cuesOverTarget=1))),
            ('enforced claimed', S, self.edited(lambda d: d['segmentation'].update(enforced=True))),
            ('enforced as integer', S, self.edited(lambda d: d['segmentation'].update(enforced=0))),
            ('target rewritten', S, self.edited(lambda d: d['segmentation'].update(maxSegmentLength=200))),
            ('target as float', S, self.edited(lambda d: d['segmentation'].update(maxSegmentLength=42.0))),
            ('native options rewritten', S, self.edited(lambda d: d['segmentation'].update(nativeOptions=['-ml', '42']))),
            ('cue count forged', S, self.edited(lambda d: d['segmentation'].update(cueCount=2))),
            ('statement softened', S, self.edited(lambda d: d['segmentation'].update(statement='guaranteed maximum'))),
            ('counting rule rewritten', S, self.edited(lambda d: d['segmentation'].update(unit='bytes'))),
            ('extra member', S, self.edited(lambda d: d['segmentation'].update(readable=True))),
            ('member removed', S, self.edited(lambda d: d.pop('segmentation'))),
            ('human review dropped', S, self.edited(lambda d: d['review'].update(humanReviewRequired=False))),
            ('cue boundary moved', S, lambda b: b.replace(b'"endMs": 5410', b'"endMs": 5400')),
            ('cue text moved between cues', S, lambda b: b.replace(b'ask not what', b'ask not', 1)),
            ('result summary forged', 'result.json', self.edited(lambda d: d['segmentation'].update(cuesOverTarget=2))),
            ('result summary dropped', 'result.json', self.edited(lambda d: d.pop('segmentation'))),
            ('result enforcement claimed', 'result.json', self.edited(lambda d: d['segmentation'].update(enforced=True))),
            ('result verdict added', 'result.json', self.edited(lambda d: d['segmentation'].update(passed=True))),
            ('argv without the option', 'transcribe-launcher.py', lambda b: b.replace(b"'-ml', '42', '-sow', ", b'')),
            ('argv with another target', 'transcribe-launcher.py', lambda b: b.replace(b"'-ml', '42'", b"'-ml', '43'")),
            ('argv without word splitting', 'transcribe-launcher.py', lambda b: b.replace(b"'-sow', ", b'')),
            ('authored target dropped', 'authored.json', self.edited(lambda d: d.pop('maxSegmentLength'))),
            ('authored target changed', 'authored.json', self.edited(lambda d: d.update(maxSegmentLength=43))),
            ('effective plan target changed', 'plan.json', self.edited(lambda d: d.update(maxSegmentLength=43))),
            ('effective plan target as boolean', 'plan.json', self.edited(lambda d: d.update(maxSegmentLength=True))),
            ('effective plan limit statement removed', 'plan.json', self.edited(lambda d: d.update(losses=d['losses'][:-1])))])

    def test_a_segmentation_member_without_the_authored_option_is_refused(self):
        self.job('plain');directory = self.dir / 'plain'
        member = {'maxSegmentLength': 42, 'nativeOptions': ['-ml', '42', '-sow'], 'enforced': False, 'unit': sg.COUNTING, 'cueCount': 3, 'cuesOverTarget': 0, 'statement': sg.STATEMENT}
        self.tamper_cases(directory, [('member added', 'segments.json', self.edited(lambda d: d.update(segmentation=member))),
            ('result summary added', 'result.json', self.edited(lambda d: d.update(segmentation={'maxSegmentLength': 42, 'cues': 3, 'cuesOverTarget': 0, 'enforced': False}))),
            ('option added to the plan only', 'plan.json', self.edited(lambda d: d.update(maxSegmentLength=42)))])

    def test_caption_review_describes_the_shorter_cues_and_binds_the_segments_bytes(self):
        result = self.job('both', maxSegmentLength=42, captionReview=True);directory = self.dir / 'both'
        self.assertEqual(result['artifacts'], 5)
        self.assertEqual(result['captionReview'], {'cues': 3, 'flaggedCues': 0, 'flagCounts': {'short-duration': 0, 'long-duration': 0, 'dense-text': 0}})
        self.assertEqual(result['segmentation']['cuesOverTarget'], 0)
        report = json.loads((directory / 'caption-review.json').read_text())
        self.assertEqual([(c['durationMs'], c['codePoints'], c['codePointsPerSecondMilli']) for c in report['cues']], [(5410, 40, 7393), (3630, 41, 11294), (1960, 24, 12244)])
        self.assertEqual(report['segmentsSha256'], sha((directory / 'segments.json').read_bytes()))
        self.assertTrue(report['review']['humanReviewRequired']);self.assertFalse(report['review']['passCertified'])
        self.assertEqual(a.read(directory, 'plan.json')['losses'], [*a.LOSSES, base.cr.LOSS, sg.LOSS])
        self.tamper_cases(directory, [('review cue forged', 'caption-review.json', self.edited(lambda d: d['cues'][0].update(codePoints=39))),
            ('review hash unbound', 'caption-review.json', self.edited(lambda d: d.update(segmentsSha256='0' * 64))),
            ('target dropped while the review stays', 'authored.json', self.edited(lambda d: d.pop('maxSegmentLength')))])

    def test_one_long_cue_still_flags_long_duration_without_the_option(self):
        self.cues([(0, 11000, ' '.join(t for _, _, t in JFK_42))])
        result = self.job('plain-review', captionReview=True)
        self.assertEqual(result['captionReview']['flagCounts']['long-duration'], 1)
        self.assertNotIn('segmentation', result)

    def test_reuse_identity_does_not_depend_on_the_option_and_the_pins_still_apply(self):
        plain = a.reusableInputs(self.document);short = a.reusableInputs({**self.document, 'maxSegmentLength': 42})
        self.assertEqual(plain, short)
        self.refuse(lambda: self.job('pin', maxSegmentLength=42, audio={'path': str(self.audio), 'sha256': '0' * 64}), 'AUDIO_HASH_MISMATCH')
        self.assertFalse((self.dir / 'pin' / 'version-launcher.py').exists())

    def test_query_and_resources_are_unchanged(self):
        document = {**self.document, 'maxSegmentLength': 42}
        self.assertEqual(a.query(document), (['transcribe'], {}))
        self.assertEqual(a.resources(document, {}, 'x'), {'threads': 1})
        self.refuse(lambda: a.resources(document, {'threads': 2}, 'x'), 'INVALID_EXECUTION')


if __name__ == '__main__': unittest.main()
