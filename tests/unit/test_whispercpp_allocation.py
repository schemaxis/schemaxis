"""Blank-looking native cues: a cue with no visible character is refused, never published.

Host-only checks with the deterministic native test double from test_whispercpp. They
are not native acceptance.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from schemaxis.adaptors.whispercpp import adaptor as a
from schemaxis.core.faults import SchemaxisError

try: import test_whispercpp as base
except ModuleNotFoundError: from tests.unit import test_whispercpp as base

INVISIBLE_ONLY = {
    'zero width space': '\u200b', 'zero width spaces and space': '\u200b \u200b', 'word joiner': '\u2060', 'byte order mark': '\ufeff',
    'soft hyphen': '\u00ad', 'combining mark alone': '\u0301', 'hangul filler': '\u3164', 'halfwidth hangul filler': '\uffa0',
    'braille blank': '\u2800', 'tag character alone': '\U000e0041', 'left to right mark alone': '\u200e', 'variation selector alone': '\ufe0f',
    'mongolian vowel separator': '\u180e'}
NOT_TEXT = {'noncharacter': '\ufffe', 'arabic presentation noncharacter': '\ufdd0', 'private use': '\ue000'}
VISIBLE = {'ascii': 'Hello.', 'emoji joined sequence': '\U0001f469\u200d\U0001f4bb', 'zero width space inside': 'a\u200bb', 'accented': 'Cafe\u0301',
           'arabic with mark': '\u0645\u0631\u062d\u0628\u0627\u064b', 'han': '\u65e5\u672c\u8a9e', 'punctuation only': '...', 'digits': '42', 'symbol': '\u2022',
           'non-speech annotation': '[BLANK_AUDIO]', 'invisible then word': '\u200bhi', 'flag with tags': '\U0001f3f4\U000e0067\U000e0062\U000e007f'}
VISIBLE.update({'noncharacter inside text': 'a\uffffb', 'private use inside text': 'ok \U000f0000', 'supplementary noncharacter inside text': 'ok \U0001fffe'})


class BlankCues(unittest.TestCase):
    def parse(self, text, frames=176000):
        return a.native_segments(base.native([(0, 1000, text)]), {'language': 'en'}, frames)

    def refuse(self, action, code):
        with self.assertRaises(SchemaxisError) as caught: action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def test_cue_without_a_visible_character_is_refused_with_location_and_recovery(self):
        for name, text in INVISIBLE_ONLY.items():
            with self.subTest(name):
                fault = self.refuse(lambda: self.parse(text), 'TRANSCRIPT_INVALID')
                self.assertEqual(fault.location, '$.transcription[0].text')
                self.assertIn('visible', fault.message)

    def test_invisible_cue_is_located_among_valid_cues(self):
        raw = base.native([(0, 1000, 'First.'), (1000, 2000, 'Second.'), (2000, 3000, '\u200b\u2060')])
        self.assertEqual(self.refuse(lambda: a.native_segments(raw, {'language': 'en'}, 176000), 'TRANSCRIPT_INVALID').location, '$.transcription[2].text')

    def test_noncharacter_or_private_use_only_cues_are_refused(self):
        for name, text in NOT_TEXT.items():
            with self.subTest(name):
                self.assertEqual(self.refuse(lambda: self.parse(text), 'TRANSCRIPT_INVALID').location, '$.transcription[0].text')

    def test_genuine_visible_text_is_unchanged(self):
        for name, text in VISIBLE.items():
            with self.subTest(name):
                self.assertEqual(self.parse(text)[0]['text'], text)

    def test_fault_is_structured_with_observed_code_points_and_recovery(self):
        fault = self.refuse(lambda: self.parse('\u200b\u2060'), 'TRANSCRIPT_INVALID').to_dict()
        self.assertEqual(fault['observed'], {'cue': 0, 'codePoints': ['U+200B', 'U+2060']})
        self.assertIn('native.json', fault['recovery'])
        self.assertEqual(self.refuse(lambda: self.parse('\ue000'), 'TRANSCRIPT_INVALID').to_dict()['observed']['codePoints'], ['U+E000'])

    def test_plan_and_segment_policy_bytes_stay_those_of_genuine_receipts(self):
        # Retained receipts embed these strings; changing them would turn genuine runs into VERIFICATION_FAILED.
        p = a.plan(json.loads((base.ROOT / 'examples/schemaxis/whispercpp-jfk.json').read_text()))
        self.assertEqual(len(p['losses']), 5)
        document = a.segment_document({'language': 'en'}, self.parse('Hello.'), '0' * 64, {'bytes': 1, 'frames': 16000, 'rate': 16000, 'channels': 1}, '1' * 64, 1, '2' * 64)
        self.assertEqual(document['review']['policy']['text'], 'UTF-8; surrounding spaces removed; no control, line-separator, replacement or subtitle markup, bidirectional overrides/isolates or caption-marker characters')


class BlankCueRuns(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.dir = Path(self.temporary.name)
        self.audio = self.dir / 'speech.wav';self.audio.write_bytes(base.wav(176000))
        self.model = self.dir / 'tiny.bin';self.model.write_bytes(os.urandom(5000))
        self.config = self.dir / 'fake.json';self.exe = self.dir / 'whisper-cli'
        self.exe.write_text(base.FAKE.format(python=sys.executable, config=str(self.config)));self.exe.chmod(0o700)
        self.document = {'version': a.VERSION, 'operation': 'transcribe', 'audio': {'path': str(self.audio), 'sha256': hashlib.sha256(self.audio.read_bytes()).hexdigest()},
                         'model': {'path': str(self.model), 'sha256': hashlib.sha256(self.model.read_bytes()).hexdigest()}, 'language': 'en'}

    def configure(self, segments):
        self.config.write_text(json.dumps({'version': 'whisper.cpp version: 1.9.5', 'model_path': str(self.model), 'native': base.native(segments)}))

    def run_job(self, name, **document):
        return a.run({**self.document, **document}, self.dir / name, executable=str(self.exe), timeout=30)

    def test_blank_cue_run_fails_and_publishes_nothing(self):
        for review in (False, True):
            name = f'blank-{review}'
            self.configure([(0, 2500, base.SPEECH), (2600, 3000, '\u200b')])
            with self.assertRaises(SchemaxisError) as caught: self.run_job(name, captionReview=review)
            self.assertEqual(caught.exception.fault.code, 'TRANSCRIPT_INVALID')
            self.assertEqual(caught.exception.fault.location, '$.transcription[1].text')
            for published in ('segments.json', 'transcript.txt', 'captions.srt', 'captions.vtt', 'caption-review.json'):
                self.assertFalse((self.dir / name / published).exists(), published)
            self.assertEqual(json.loads((self.dir / name / 'result.json').read_text())['status'], 'failed')

    def test_verifier_rejects_a_blank_cue_forged_into_retained_native_evidence(self):
        self.configure([(0, 2500, base.SPEECH), (2600, 3000, 'Ask.')])
        self.run_job('run');directory = self.dir / 'run'
        self.assertTrue(a.verify(directory)['verified'])
        native = json.loads((directory / 'native.json').read_text(encoding='utf-8'))
        native['transcription'][1]['text'] = ' \u200b'
        (directory / 'native.json').write_text(json.dumps(native, ensure_ascii=False, indent=1), encoding='utf-8')
        (directory / 'native.srt').write_text(a.native_srt([{'index': i, 'startMs': c['offsets']['from'], 'endMs': c['offsets']['to'], '_raw': c['text']}
                                                            for i, c in enumerate(native['transcription'])]), encoding='utf-8')
        receipt = a.read(directory, 'verification.json')
        receipt['evidence'] = {n: a.digest(directory, n) for n in receipt['evidence']};a.atomic_json(directory / 'verification.json', receipt)
        from schemaxis.publication_metadata import finalise
        finalise(directory)
        with self.assertRaises(SchemaxisError) as caught: a.verify(directory)
        fault = caught.exception.fault
        self.assertEqual(fault.code, 'VERIFICATION_FAILED')
        self.assertEqual(fault.to_dict()['observed']['cause']['code'], 'TRANSCRIPT_INVALID')
        self.assertNotIn('observed', fault.to_dict()['observed'])
        self.assertEqual(fault.to_dict()['observed']['cause']['observed'], {'cue': 1, 'codePoints': ['U+200B']})
        self.assertIn('native.json', fault.to_dict()['observed']['cause']['recovery'])
        self.assertEqual(fault.location, '$.transcription[1].text')


if __name__ == '__main__':
    unittest.main()
