"""Language admission: the static whisper.cpp 1.9.5 code set is checked at $.language before any file is read.

Before this contract the pattern [a-z]{2,3} accepted zz and zzz, which the native whisper_lang_id refuses only
after the audio and model are hashed and the process is launched (and then exits 0 without results).
All checks here are host-only; the native refusal is recorded in verification/2026-10-25-whispercpp-42.md.
"""
import copy
import json
import os
from pathlib import Path
import re
import unittest
from unittest import mock

from schemaxis.adaptors.whispercpp import adaptor as a
from schemaxis.adaptors.whispercpp import languages
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
SOURCE = os.environ.get('SCHEMAXIS_WHISPERCPP_SOURCE')
UPSTREAM = Path(SOURCE) / 'src' / 'whisper.cpp' if SOURCE else None
# Reviewed literal anchors from whisper.cpp v1.9.5 g_lang (id order), not derived from the module under test.
ANCHORS = {0: 'en', 1: 'zh', 20: 'he', 29: 'no', 83: 'nn', 93: 'haw', 97: 'jw', 99: 'yue'}


class Languages(unittest.TestCase):
    def doc(self, **changes):
        d = json.loads((ROOT / 'examples/schemaxis/whispercpp-jfk.json').read_text())
        d.update(changes)
        return d

    def refusal(self, action):
        with self.assertRaises(SchemaxisError) as caught: action()
        return caught.exception.fault

    def test_control_and_invisible_values_are_not_echoed_into_diagnostics(self):
        for value in ('e\u202en', 'e\x00n', 'e\u200bn'):
            fault = self.refusal(lambda: a.plan(self.doc(language=value)))
            self.assertEqual(fault.observed, {'type': 'str', 'length': len(value)})

    def test_unknown_three_and_two_letter_codes_are_refused_at_the_authored_location(self):
        # Failed before: both planned successfully and only the native process refused them later.
        for code in ('zz', 'zzz', 'qq', 'xx', 'abc', 'iw'):
            for entry in (a.plan, a.query):
                fault = self.refusal(lambda: entry(self.doc(language=code)))
                self.assertEqual((fault.code, fault.location), ('INVALID_LANGUAGE', '$.language'), code)
                self.assertEqual(fault.observed['value'], code)
                self.assertIn('schema enum', fault.recovery)
                self.assertIn('iw', fault.recovery)

    def test_wrong_types_null_bool_names_case_padding_and_auto_are_one_located_fault(self):
        bad = ['EN', 'En', 'english', 'English', 'german', 'auto', 'e1', '', ' en', 'en ', 'en\n', 'en\0', 'é', 'éé', 'en-US', 'en_us', 'zh-cn',
               None, True, False, 0, 1, 2.0, ['en'], {'code': 'en'}, 'x' * 10000]
        for value in bad:
            fault = self.refusal(lambda: a.plan(self.doc(language=value)))
            self.assertEqual((fault.code, fault.location), ('INVALID_LANGUAGE', '$.language'), repr(value)[:40])
            self.assertTrue(fault.recovery)
            self.assertLessEqual(len(json.dumps(fault.to_dict())), 2000)
        self.assertEqual(self.refusal(lambda: a.plan(self.doc(language=None))).observed['type'], 'NoneType')
        self.assertEqual(self.refusal(lambda: a.plan(self.doc(language=True))).observed['type'], 'bool')

    def test_language_is_refused_before_any_other_argument_or_file_access(self):
        d = self.doc(language='zz')
        d['audio']['path'] = 'relative.wav'
        d['model']['sha256'] = 'NOT-A-DIGEST'
        with mock.patch('os.open', side_effect=AssertionError('file access')), mock.patch('builtins.open', side_effect=AssertionError('file access')), \
                mock.patch('subprocess.Popen', side_effect=AssertionError('process')), mock.patch('socket.socket', side_effect=AssertionError('network')):
            self.assertEqual(self.refusal(lambda: a.plan(d)).location, '$.language')
            self.assertEqual(self.refusal(lambda: a.query(d)).location, '$.language')

    def test_every_supported_code_plans_and_reaches_the_native_command_unchanged(self):
        self.assertEqual(len(languages.CODES), 100)
        self.assertEqual(len(set(languages.CODES)), 100)
        for code in languages.CODES:
            plan = a.plan(self.doc(language=code))
            self.assertEqual(plan['language'], code)
            command = a.commands('/bin/whisper-cli', plan)['transcribe']
            self.assertEqual(command[command.index('-l') + 1], code)
            self.assertEqual(a.query(self.doc(language=code)), (['transcribe'], {}))
        for code in ('yue', 'jw', 'haw', 'he', 'nn', 'no'):
            a.plan(self.doc(language=code))

    def test_release_bound_set_matches_reviewed_anchors_and_upstream_policy(self):
        self.assertEqual(languages.RELEASE, '1.9.5')
        for index, code in ANCHORS.items(): self.assertEqual(languages.CODES[index], code)
        self.assertNotIn('iw', languages.SUPPORTED)
        self.assertNotIn('auto', languages.SUPPORTED)
        self.assertTrue(all(re.fullmatch('[a-z]{2,3}', c) for c in languages.CODES))
        self.assertEqual(languages.DEFAULT, 'en')

    @unittest.skipUnless(UPSTREAM and UPSTREAM.is_file(), 'set SCHEMAXIS_WHISPERCPP_SOURCE to a whisper.cpp v1.9.5 checkout to compare the table')
    def test_set_equals_the_v1_9_5_upstream_table_in_id_order(self):
        text = UPSTREAM.read_text(encoding='utf-8')
        block = text[text.index('g_lang = {'):]
        rows = re.findall(r'\{\s*"([a-z]+)",\s*\{\s*(\d+),', block[:block.index('};')])
        self.assertEqual([int(i) for _, i in rows], list(range(len(rows))))
        self.assertEqual(tuple(c for c, _ in rows), languages.CODES)

    def test_default_and_absent_language_preserve_the_exact_plan(self):
        d = self.doc();del d['language']
        plan = a.plan(d)
        self.assertEqual(plan['language'], 'en')
        self.assertEqual(plan, a.plan(self.doc(language='en')))
        self.assertEqual(plan['losses'], a.plan_losses(plan))
        self.assertNotIn('captionReview', plan)

    def test_schema_enum_default_and_discovery_agree_with_the_admission_set(self):
        member = a.schema()['properties']['language']
        self.assertEqual(member['enum'], list(languages.CODES))
        self.assertEqual(member['default'], 'en')
        self.assertNotIn('minLength', member)
        guidance = json.loads((ROOT / 'src/schemaxis/adaptors/whispercpp/guidance.json').read_text())
        text = json.dumps(guidance)
        self.assertIn('100 canonical codes of whisper.cpp 1.9.5', text)
        self.assertNotIn('two or three letter', text)
        self.assertIn('does not certify that the chosen model is multilingual', text)
        docs = (ROOT / 'docs/whispercpp.md').read_text()
        self.assertIn('INVALID_LANGUAGE', docs)
        self.assertNotIn('two or three letter', docs)

    def test_readiness_example_is_schema_invalid_and_plans_to_invalid_language(self):
        readiness = json.loads((ROOT / 'src/schemaxis/adaptors/whispercpp/readiness.json').read_text())
        examples = json.dumps(readiness)
        self.assertIn('examples/schemaxis/whispercpp-invalid-language.json', examples)
        document = json.loads((ROOT / 'examples/schemaxis/whispercpp-invalid-language.json').read_text())
        self.assertEqual(document['language'], 'zz')
        self.assertNotIn(document['language'], a.schema()['properties']['language']['enum'])
        self.assertEqual(self.refusal(lambda: a.plan(document)).code, 'INVALID_LANGUAGE')
        from schemaxis.adaptor_conformance import host
        self.assertTrue(host(a.VERSION)['verified'])

    def test_supported_language_receipt_still_requires_exact_native_agreement(self):
        raw = {'systeminfo': 'CPU', 'model': {'type': 'base', 'multilingual': True, 'vocab': 51865, 'audio': {'ctx': 1500, 'state': 512, 'head': 8, 'layer': 6},
                'text': {'ctx': 448, 'state': 512, 'head': 8, 'layer': 6}, 'mels': 80, 'ftype': 1},
            'params': {'model': '/proc/self/fd/3', 'language': 'de', 'translate': False}, 'result': {'language': 'de'},
            'transcription': [{'timestamps': {'from': '00:00:00,000', 'to': '00:00:01,000'}, 'offsets': {'from': 0, 'to': 1000}, 'text': ' Guten Tag.'}]}
        plan = a.plan(self.doc(language='de'))
        self.assertEqual(a.native_segments(raw, plan, 32000)[0]['text'], 'Guten Tag.')
        changed = copy.deepcopy(raw);changed['result']['language'] = 'en'
        self.assertEqual(self.refusal(lambda: a.native_segments(changed, plan, 32000)).code, 'TRANSCRIPT_INVALID')
        # A real English-only receipt keeps its meaning: language en, nothing about multilingual capability is added.
        self.assertEqual(a.plan(self.doc())['language'], 'en')


if __name__ == '__main__': unittest.main()
