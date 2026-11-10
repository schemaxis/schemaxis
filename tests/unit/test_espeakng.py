"""eSpeak NG narration contract: planning, plain-text profile, canonical WAV reader, runtime identity, discovery and guidance (host only).

Nothing here starts a native process. The fake native boundary is test_espeakng_native_boundary.py (a host fake that makes no speech)
and real eSpeak NG acceptance is tools/qualify_espeakng.py.
"""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
import wave

from schemaxis.adaptors import registry
from schemaxis.adaptors.espeakng import adaptor
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_espeakng_fakes import DATA_FILES, EN_US, HEADER, VERSION_TEXT, VOICES, make_data, tone_pcm, wav_bytes   # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/espeakng'
DOC = {'version': 'schemaxis.espeakng/1', 'operation': 'narrate'}


@contextlib.contextmanager
def private_configuration(locations=None):
    """A private SCHEMAXIS_CONFIG with SCHEMAXIS_ESPEAKNG cleared, so a machine with a stored espeak-ng cannot leak into the tests."""
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
        path = Path(tmp) / 'private-config.json'
        path.write_text(json.dumps({'version': 1, 'locations': locations or {}}))
        os.environ['SCHEMAXIS_CONFIG'] = str(path)
        os.environ.pop('SCHEMAXIS_ESPEAKNG', None)
        yield


class EspeakngContract(unittest.TestCase):
    def document(self, name='baseline'):
        return json.loads((ROOT / f'examples/schemaxis/espeakng-{name}.json').read_text())

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def literal(self, text, **extra):
        return {**DOC, 'text': text, **extra}

    # ------------------------------------------------------------ registration, planning
    def test_registered_with_one_native_option_and_no_framework_branch(self):
        item = registry.ADAPTORS['espeakng']
        self.assertEqual([o['dest'] for o in item['cliOptions']], ['espeakng'])
        self.assertEqual(item['executables'], ['espeak-ng'])
        self.assertNotIn('runOptions', item['routes']['schemaxis.espeakng/1'])
        self.assertEqual(item['routes']['schemaxis.espeakng/1']['acceptedArtifacts'], ['file', 'text'])
        self.assertEqual(registry.query(self.document())['adaptors'][0]['operations'], ['narrate'])
        self.assertEqual(registry.query(self.document('variant'))['adaptors'][0]['operations'], ['narrate'])
        self.assertEqual(item['version'], adaptor.VERSION)

    def test_host_contract_guidance_and_curated_search(self):
        from schemaxis.adaptor_conformance import host
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        from schemaxis.studio_guidance import audit
        self.assertTrue(host(adaptor.VERSION)['verified'])
        self.assertTrue(audit('espeakng')['complete'])
        self.assertTrue(check_cases(CapabilityCatalogue(providers=['espeakng']), 'espeakng')['complete'])

    def test_planning_is_immutable_deterministic_and_closed(self):
        for name in ('baseline', 'variant', 'fast'):
            document = self.document(name)
            if 'source' in document:
                document['source'] = '/tmp/script.txt'
            before = copy.deepcopy(document)
            prepared = adaptor.plan(document)
            self.assertEqual(before, document)
            self.assertEqual(prepared, adaptor.plan(document))
            self.assertEqual(prepared['native']['arguments'], ['-ven-us', '-s%d' % prepared['rateWpm'], '-p50', '-a100', '-b1', '-w', 'native.wav', '-f', 'captured.txt'])
            self.assertEqual((prepared['native']['voice'], prepared['native']['pitch'], prepared['native']['amplitude']), ('en-us', 50, 100))
            self.assertEqual(prepared['budget'], {'maxCodePoints': 1024, 'maxTextBytes': 8192, 'maxSeconds': 120, 'maxWavBytes': 8 * 1024 * 1024,
                                                  'rateWpm': [120, 240], 'sampleRate': 22050, 'channels': 1, 'bitsPerSample': 16})
            for key in ('voiceName', 'voiceFile', 'variant', 'language', 'pitch', 'amplitude', 'wordGap', 'ssml', 'markup', 'phonemes', 'flags', 'arguments', 'command', 'encoding',
                        'device', 'output', 'path', 'stdout', 'playback', 'translate', 'detect', 'url', 'speed', 'rate', 'rateWPM'):
                bad = copy.deepcopy(document)
                bad[key] = 1
                self.fault(lambda: adaptor.plan(bad), 'UNKNOWN_ARGUMENT')
        self.assertEqual(adaptor.plan(self.document())['rateWpm'], 175)
        for bad_operation in ('speak', 'Narrate', '', None, 7, ['narrate'], {'a': 1}):
            bad = self.document()
            bad['operation'] = bad_operation
            self.assertEqual(self.fault(lambda: adaptor.plan(bad), 'UNKNOWN_FILTER').location, '$.operation')
        bad = self.document()
        bad['version'] = 'schemaxis.espeakng/2'
        self.fault(lambda: adaptor.plan(bad), 'UNSUPPORTED_VERSION')
        self.fault(lambda: adaptor.plan([]), 'INVALID_DOCUMENT')
        self.fault(lambda: adaptor.resources(self.document(), {'threads': 2}, 'op'), 'INVALID_EXECUTION')
        self.assertEqual(adaptor.resources(self.document(), {}, 'op'), {'threads': 1})
        self.assertEqual(adaptor.query(self.document()), (['narrate'], {}))

    def test_exactly_one_of_text_and_source(self):
        for document in ({**DOC}, {**DOC, 'text': 'Hello there.', 'source': '/tmp/a.txt'}):
            fault = self.fault(lambda: adaptor.plan(document), 'INVALID_ESPEAKNG_SOURCE')
            self.assertEqual(fault.location, '$')
            self.assertIn('exactly one', fault.message)
        self.assertEqual(adaptor.plan({**DOC, 'text': 'Hello there.'})['text'], 'Hello there.')
        self.assertEqual(adaptor.plan({**DOC, 'source': '/tmp/a.txt'})['source'], '/tmp/a.txt')
        for value in (1, True, None, ['x'], {'a': 1}):
            with self.assertRaises(SchemaxisError):
                adaptor.plan({**DOC, 'text': value})
            with self.assertRaises(SchemaxisError):
                adaptor.plan({**DOC, 'source': value})

    def test_rate_is_a_typed_integer_in_bounds(self):
        for rate in (120, 121, 175, 239, 240):
            self.assertEqual(adaptor.plan(self.literal('Hello there.', rateWpm=rate))['native']['arguments'][1], '-s%d' % rate)
        for bad in (119, 241, 0, -175, 1000, True, False, 175.0, 120.5, '175', None, [175], float('inf'), float('nan'), 10 ** 20):
            fault = self.fault(lambda: adaptor.plan(self.literal('Hello there.', rateWpm=bad)), 'INVALID_ARGUMENT')
            self.assertIn('rateWpm', fault.location, repr(bad))

    def test_source_names_must_be_absolute_text_files(self):
        document = {**DOC, 'source': '/tmp/a.TXT'}
        self.assertEqual(adaptor.plan(document)['source'], '/tmp/a.TXT')
        for source in ('relative.txt', './a.txt', 'https://example.org/a.txt', 'file:///tmp/a.txt', 'TXT:/tmp/a.txt', '/tmp/a.text', '/tmp/a.wav', '/tmp/a.txt.wav',
                       '/tmp/a', '/tmp/a\0.txt', '/tmp/.txt'):
            self.assertEqual(self.fault(lambda: adaptor.plan({**DOC, 'source': source}), 'INVALID_ESPEAKNG_SOURCE').location, '$.source', source)
        self.assertEqual(self.fault(lambda: adaptor.plan(self.document('invalid-source')), 'INVALID_ESPEAKNG_SOURCE').location, '$.source')
        with self.assertRaises(SchemaxisError):
            adaptor.plan({**DOC, 'source': ''})

    def test_planning_reads_no_file_and_starts_no_native_process(self):
        with mock.patch.object(adaptor, 'read_source', side_effect=AssertionError('file read')), mock.patch.object(adaptor, 'execute', side_effect=AssertionError('native')):
            self.assertEqual(adaptor.plan({**DOC, 'source': '/nonexistent/never-read.txt'})['source'], '/nonexistent/never-read.txt')
            adaptor.plan(self.literal('Hello there.'))

    # ------------------------------------------------------------ the plain-text profile
    def test_profile_accepts_plain_speakable_text_and_counts_it(self):
        for text, points, lines in (('Hello there.', 12, 1), ('Hello there.\n', 13, 1), ('One.\nTwo.\nThree.', 16, 3), ('One.\n\nTwo.\n', 11, 3), ('café résumé naïve', 17, 1),
                                    ('日本語のテキスト', 8, 1), ('hello 😀', 7, 1), ('1 < 2 and 3 > 2', 15, 1), ('Fish & chips cost $5 (50%).', 27, 1), ('a', 1, 1),
                                    ('Dr. Smith said: "Yes -- 100%!"', 30, 1), ('x' * 1024, 1024, 1), ('😀a' * 512, 1024, 1), ('[one] and ]two[', 15, 1)):
            with self.subTest(text=text[:20]):
                self.assertEqual(adaptor.check_text(text, '$.text'), {'codePoints': points, 'lines': lines})
                self.assertEqual(adaptor.plan(self.literal(text))['text'], text)    # never normalised

    def test_profile_refusals_name_the_code_point_and_its_index(self):
        for label, text, index in (('tab', 'a\tb', 1), ('carriage return', 'a\rb', 1), ('crlf', 'one\r\ntwo', 3), ('form feed', 'page\x0c', 4), ('nul', 'a\0b', 1), ('escape', 'a\x1bb', 1),
                                   ('delete', 'a\x7fb', 1), ('next line', 'a\x85b', 1), ('vertical tab', 'a\x0bb', 1), ('bell', 'ab\x07', 2), ('byte-order mark', '﻿Hello', 0),
                                   ('soft hyphen', 'in­side', 2), ('zero-width space', 'a​b', 1), ('zero-width joiner', 'a‍b', 1), ('right-to-left override', 'a‮b', 1),
                                   ('line separator', 'a b', 1), ('paragraph separator', 'a b', 1), ('private use', 'ab', 1), ('private use end', 'ab', 1),
                                   ('lone surrogate', 'a\ud800b', 1), ('emphasis code', 'a԰b', 1), ('comma break code', 'a՗b', 1), ('tag character', 'a\U000e0041b', 1)):
            with self.subTest(label):
                fault = self.fault(lambda: adaptor.check_text(text, '$.text'), 'INVALID_ESPEAKNG_TEXT')
                self.assertEqual((fault.location, fault.observed['index']), ('$.text', index))
                self.assertIn('U+%04X' % ord(text[index]), fault.message)
                self.assertIn('recovery', fault.observed)
                self.assertEqual(self.fault(lambda: adaptor.plan(self.literal(text)), 'INVALID_ESPEAKNG_TEXT').location, '$.text')

    def test_phoneme_escapes_and_markup_are_refused_not_stripped(self):
        for label, text, index in (('phoneme open', "Say [[h@'loU]] now", 4), ('phoneme close only', 'ab ]] cd', 3), ('phoneme at start', '[[a]]', 0),
                                   ('ssml', '<speak>hello</speak>', 0), ('closing tag', 'hello</s>', 5), ('comment', 'a <!-- x --> b', 2), ('processing', '<?xml version="1.0"?>', 0),
                                   ('numeric reference', 'a &#65; b', 2), ('named reference', 'fish &amp; chips', 5), ('html', 'x <b>bold</b>', 2), ('upper tag', 'a <P>', 2)):
            with self.subTest(label):
                fault = self.fault(lambda: adaptor.check_text(text, '$.source'), 'INVALID_ESPEAKNG_TEXT')
                self.assertEqual(fault.observed['index'], index)
                self.assertTrue('phoneme' in fault.message or 'markup' in fault.message, fault.message)
        self.assertEqual(self.fault(lambda: adaptor.plan(self.document('invalid-phoneme')), 'INVALID_ESPEAKNG_TEXT').location, '$.text')

    def test_text_without_a_letter_or_digit_is_refused(self):
        for text in ('', ' ', '\n', '\n\n', '...', '!!! ???', '---', '. . .', '😀😀', '()', '_ _', '́'):
            with self.subTest(text=text):
                self.fault(lambda: adaptor.check_text(text, '$.text'), 'INVALID_ESPEAKNG_TEXT')
        self.assertEqual(adaptor.check_text('7', '$.text')['codePoints'], 1)
        self.assertEqual(adaptor.check_text('!!! ok', '$.text')['codePoints'], 6)

    def test_budgets_are_judged_before_any_native_work(self):
        self.assertEqual(adaptor.check_text('x' * 1024, '$.text')['codePoints'], 1024)
        fault = self.fault(lambda: adaptor.plan(self.literal('x' * 1025)), 'ESPEAKNG_BUDGET')
        self.assertEqual(fault.location, '$.text')
        self.assertIn('1025', fault.message)
        self.fault(lambda: adaptor.check_text('😀' * 1025, '$.text'), 'ESPEAKNG_BUDGET')
        self.fault(lambda: adaptor.decode_text(b'x' * 8193, '$.source'), 'ESPEAKNG_BUDGET')
        self.fault(lambda: adaptor.text_facts(b'x' * 8192, '$.source'), 'ESPEAKNG_BUDGET')    # within the byte bound, over the code point bound
        self.assertEqual(adaptor.text_facts(b'x' * 1024, '$.source'), {'bytes': 1024, 'codePoints': 1024, 'lines': 1})
        self.assertEqual(adaptor.text_facts('😀a'.encode() * 100, '$.source'), {'bytes': 500, 'codePoints': 200, 'lines': 1})

    def test_script_files_must_be_valid_utf8(self):
        for label, data in (('latin-1', 'café'.encode('latin-1')), ('truncated sequence', b'abc\xc3'), ('overlong', b'a\xc0\xafb'), ('surrogate bytes', b'a\xed\xa0\x80b'),
                            ('utf-16', 'hello'.encode('utf-16')), ('lone continuation', b'a\x80b')):
            with self.subTest(label):
                fault = self.fault(lambda: adaptor.text_facts(data, '$.source'), 'INVALID_ESPEAKNG_TEXT')
                self.assertIn('UTF-8', fault.message)
        self.fault(lambda: adaptor.text_facts(b'\xef\xbb\xbfHello', '$.source'), 'INVALID_ESPEAKNG_TEXT')    # a decoded BOM is an invisible format character
        self.assertEqual(adaptor.text_facts('café'.encode(), '$.source'), {'bytes': 5, 'codePoints': 4, 'lines': 1})
        self.assertEqual(adaptor.text_facts((FIXTURES / 'script-numbered.txt').read_bytes(), '$.source'), {'bytes': 173, 'codePoints': 169, 'lines': 3})

    def test_sources_are_regular_bounded_and_byte_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / 'a.txt'
            good.write_bytes(b'Hello there.\n')
            self.assertEqual(adaptor.read_source(str(good)), b'Hello there.\n')
            document = {**DOC, 'source': str(good)}
            first = adaptor.reusableInputs(document)
            self.assertEqual(first, {str(good): hashlib.sha256(b'Hello there.\n').hexdigest()})
            good.write_bytes(b'Hello there!\n')
            self.assertNotEqual(adaptor.reusableInputs(document), first)          # same path, different bytes
            self.assertEqual(adaptor.reusableInputs(self.literal('Hello there.')), {})   # a literal has no external input
            link = Path(tmp) / 'link.txt'
            link.symlink_to(good)
            self.assertEqual(self.fault(lambda: adaptor.read_source(str(link)), 'INVALID_ESPEAKNG_SOURCE').location, '$.source')
            directory = Path(tmp) / 'dir.txt'
            directory.mkdir()
            self.fault(lambda: adaptor.read_source(str(directory)), 'INVALID_ESPEAKNG_SOURCE')
            fifo = Path(tmp) / 'pipe.txt'
            os.mkfifo(fifo)
            self.fault(lambda: adaptor.read_source(str(fifo)), 'INVALID_ESPEAKNG_SOURCE')
            self.fault(lambda: adaptor.read_source(str(Path(tmp) / 'missing.txt')), 'INVALID_ESPEAKNG_SOURCE')
            big = Path(tmp) / 'big.txt'
            big.write_bytes(b'x' * 8193)
            self.fault(lambda: adaptor.read_source(str(big)), 'ESPEAKNG_BUDGET')
            big.write_bytes(b'x' * 8192)
            self.assertEqual(len(adaptor.read_source(str(big))), 8192)
            self.fault(lambda: adaptor.reusableInputs({**DOC, 'source': str(big)}), 'ESPEAKNG_BUDGET')       # 8192 code points
            bad = Path(tmp) / 'bad.txt'
            bad.write_bytes(b'one\r\ntwo\r\n')
            self.fault(lambda: adaptor.reusableInputs({**DOC, 'source': str(bad)}), 'INVALID_ESPEAKNG_TEXT')

    # ------------------------------------------------------------ WAV reader and writer
    def test_canonical_wav_is_exactly_the_44_byte_pcm16_layout_and_readable_back(self):
        pcm = struct.pack('<4h', 0, 1, -1, 32767)
        data = adaptor.canonical_wav(pcm)
        self.assertEqual(data, wav_bytes(pcm))     # the test's independent writer
        self.assertEqual(data[:4] + data[8:16], b'RIFFWAVEfmt ')
        self.assertEqual(len(data), 44 + len(pcm))
        self.assertEqual(struct.unpack_from('<IHHIIHH', data, 16), (16, 1, 1, 22050, 44100, 2, 16))
        with wave.open(io.BytesIO(data), 'rb') as stream:
            self.assertEqual((stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getnframes(), stream.readframes(4)), (1, 2, 22050, 4, pcm))
        parsed = adaptor.parse_wav(data)
        self.assertEqual((parsed['frames'], parsed['pcm']), (4, pcm))

    def test_wav_refusals_are_distinct_and_located(self):
        pcm = tone_pcm(b'hello there friend', 175)
        good = wav_bytes(pcm)
        self.assertEqual(adaptor.parse_wav(good)['frames'], len(pcm) // 2)
        rejected = {'rate': wav_bytes(pcm, rate=44100), 'stereo': wav_bytes(pcm, channels=2), 'eight-bit': wav_bytes(pcm, bits=8), 'float': wav_bytes(pcm, encoding=3),
                    'extra chunk': wav_bytes(pcm, extra=b'LIST' + struct.pack('<I', 4) + b'INFO'), 'riff size': wav_bytes(pcm, riff_delta=2), 'data size': wav_bytes(pcm, data_delta=-2),
                    'odd data': wav_bytes(pcm + b'\0'), 'trailing byte': good + b'\0', 'truncated': good[:-3], 'short header': good[:30], 'empty': b'', 'not riff': b'RIFX' + good[4:],
                    'not wave': good[:8] + b'AVI ' + good[12:], 'fmt size': good[:16] + struct.pack('<I', 18) + good[20:], 'no data': wav_bytes(b'')}
        for label, data in rejected.items():
            with self.subTest(label):
                fault = self.fault(lambda: adaptor.parse_wav(data, 'x.wav'), 'ESPEAKNG_OUTPUT_REJECTED')
                self.assertEqual(fault.location, 'x.wav')

    def test_silent_and_over_budget_audio_are_distinct_refusals(self):
        self.assertEqual(self.fault(lambda: adaptor.parse_wav(wav_bytes(bytes(4000))), 'ESPEAKNG_SILENT_OUTPUT').location, 'native.wav')
        self.assertEqual(adaptor.parse_wav(wav_bytes(bytes(3998) + b'\x01\x00'))['frames'], 2000)       # one nonzero sample is signal
        limit = 120 * 22050
        self.assertEqual(adaptor.parse_wav(wav_bytes(b'\x01\x00' * limit))['frames'], limit)
        fault = self.fault(lambda: adaptor.parse_wav(wav_bytes(b'\x01\x00' * (limit + 1))), 'ESPEAKNG_BUDGET')
        self.assertIn('120', fault.message)
        self.fault(lambda: adaptor.parse_wav(b'\0' * (8 * 1024 * 1024 + 1)), 'ESPEAKNG_BUDGET')

    def test_pcm_record_and_first_difference_use_samples(self):
        pcm = struct.pack('<5h', 0, 5, -300, 299, 0)
        self.assertEqual(adaptor.pcm_record(pcm), {'bytes': 10, 'sha256': hashlib.sha256(pcm).hexdigest(), 'peakAbs': 300, 'nonzeroSamples': 3})
        self.assertEqual(adaptor.pcm_record(struct.pack('<2h', -32768, 32767))['peakAbs'], 32768)
        other = struct.pack('<5h', 0, 5, -300, 298, 0)
        self.assertEqual(adaptor.first_difference(pcm, other), 'first difference at sample 3')
        self.assertIn('lengths differ (5 and 3 samples)', adaptor.first_difference(pcm, pcm[:6]))

    # ------------------------------------------------------------ trusted runtime and native identity
    def test_runtime_never_comes_from_receipts_path_or_relative_names(self):
        with private_configuration():
            fault = self.fault(lambda: adaptor.runtime(), 'INTERPRETER_NOT_FOUND')
            self.assertIn('no host speech synthesizer', fault.message)
            self.assertEqual(fault.location, '$.runtime.espeakng')
            with mock.patch.dict(os.environ, {'PATH': '/bin:/usr/bin'}):
                self.fault(lambda: adaptor.runtime(), 'INTERPRETER_NOT_FOUND')          # PATH is never searched
            for bad in ('espeak-ng', '/nonexistent/espeak-ng', str(FIXTURES), str(FIXTURES / 'script-numbered.txt'), 3, ['/bin/true']):
                self.fault(lambda: adaptor.runtime(bad), 'INTERPRETER_NOT_FOUND')

    def test_explicit_stored_and_environment_routes_are_ordered(self):
        with private_configuration({'espeakng': '/bin/true'}):
            self.assertEqual(adaptor.runtime(), {'espeakng': '/bin/true'})
            self.assertEqual(adaptor.runtime('/bin/false'), {'espeakng': '/bin/false'})
        with private_configuration():
            with mock.patch.dict(os.environ, {'SCHEMAXIS_ESPEAKNG': '/bin/true'}):
                self.assertEqual(adaptor.runtime(), {'espeakng': '/bin/true'})
        with private_configuration():
            recovery = self.fault(lambda: adaptor.runtime(), 'INTERPRETER_NOT_FOUND').observed['recovery']
            self.assertIn('SCHEMAXIS_ESPEAKNG', recovery)
            self.assertIn('no --espeakng flag', recovery)

    def test_help_readiness_and_docs_do_not_claim_the_run_flag_reaches_bare_verify_or_leak_paths(self):
        help_text = registry.ADAPTORS['espeakng']['cliOptions'][0]['help']
        self.assertIn('schemaxis verify has no such flag', help_text)
        self.assertIn('SCHEMAXIS_ESPEAKNG', help_text)
        docs = (ROOT / 'docs/espeakng.md').read_text()
        flat = ' '.join(docs.split())
        for phrase in ('SCHEMAXIS_ESPEAKNG=/path/to/espeak-ng schemaxis verify output/narrate', 'no host speech synthesizer', 'does not claim host-independent', 'nothing here certifies',
                       'The result is a **draft**', 'unauthenticated trust anchor', 'matching runtime and data', 'not demonstrated customer demand'):
            self.assertIn(phrase, flat, phrase)
        package = ROOT / 'src/schemaxis/adaptors/espeakng'
        public = [ROOT / 'docs/espeakng.md', *package.glob('*.json'), *package.glob('*.py'), *(ROOT / 'examples/schemaxis').glob('espeakng-*.json'), *FIXTURES.glob('*')]
        for path in public:
            text = path.read_text(errors='replace')
            self.assertNotIn('/'.join(('', 'home', '')), text, path.name)
            self.assertNotIn('adaptor-100-2026', text, path.name)
        readiness = (package / 'readiness.json').read_text()
        self.assertIn('SCHEMAXIS_ESPEAKNG', readiness)
        self.assertNotIn('also for verify', readiness + docs)

    def test_runtime_identity_is_exactly_eSpeak_NG_1_52_0_with_an_absolute_data_directory(self):
        self.assertEqual(adaptor.check_identity(VERSION_TEXT % '/opt/espeak/share/espeak-ng-data'), ('eSpeak NG 1.52.0', '/opt/espeak/share/espeak-ng-data'))
        self.assertEqual(adaptor.check_identity((VERSION_TEXT % '/d').rstrip('\n'))[1], '/d')
        for bad in ('eSpeak NG text-to-speech: 1.51.0  Data at: /d\n', 'eSpeak NG text-to-speech: 1.52.1  Data at: /d\n', 'eSpeak NG text-to-speech: 1.53.0  Data at: /d\n',
                    'eSpeak NG text-to-speech: 1.52  Data at: /d\n', 'eSpeak NG text-to-speech: 1.52.0 Data at: /d\n', 'eSpeak NG text-to-speech: 1.52.0  Data at: relative\n',
                    'eSpeak NG text-to-speech: 1.52.0  Data at: \n', 'espeak 1.52.0\n', '', 'eSpeak NG text-to-speech: 1.52.0  Data at: /d\nextra\n', 'x' + VERSION_TEXT % '/d'):
            self.assertEqual(self.fault(lambda: adaptor.check_identity(bad), 'UNSUPPORTED_RUNTIME').location, 'version', bad)

    def test_the_requested_voice_must_be_listed_not_silently_replaced(self):
        self.assertEqual(adaptor.check_voice(VOICES), {'language': 'en-us', 'name': 'English_(America)', 'file': 'gmw/en-US'})
        for label, table in (('no en-us', HEADER + ' 2  en-gb           --/M      English_(Great_Britain) gmw/en               (en 2)\n'),
                             ('only variants', HEADER + ' 5  en-us-nyc       --/M      English_(America,_New_York_City) gmw/en-US-nyc        \n'),
                             ('different name', HEADER + ' 2  en-us           --/M      English_(Canada)   gmw/en-US            (en 3)\n'),
                             ('different file', HEADER + ' 2  en-us           --/M      English_(America)  gmw/en-GB            (en 3)\n'), ('empty', ''), ('header only', HEADER)):
            with self.subTest(label):
                self.assertEqual(self.fault(lambda: adaptor.check_voice(table), 'UNSUPPORTED_RUNTIME').location, 'voices')
        self.assertIn('2 times', self.fault(lambda: adaptor.check_voice(HEADER + EN_US + EN_US), 'UNSUPPORTED_RUNTIME').message)    # an identical repeat is ambiguous too
        self.assertEqual(adaptor.check_voice(HEADER + EN_US)['file'], 'gmw/en-US')

    def test_data_fingerprint_covers_only_the_six_chosen_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_data(Path(tmp) / 'data')
            first = adaptor.data_fingerprint(root)
            self.assertRegex(first, '^[0-9a-f]{64}$')
            self.assertEqual(first, adaptor.data_fingerprint(root))
            self.assertEqual(tuple(adaptor.DATA_FILES), DATA_FILES)
            (Path(root) / 'unrelated_dict').write_bytes(b'x')                            # a file outside the six chosen ones
            self.assertEqual(first, adaptor.data_fingerprint(root))
            for name in DATA_FILES:
                path = Path(root) / name
                saved = path.read_bytes()
                path.write_bytes(saved + b'!')
                self.assertNotEqual(first, adaptor.data_fingerprint(root), name)
                path.unlink()
                self.assertEqual(self.fault(lambda: adaptor.data_fingerprint(root), 'UNSUPPORTED_RUNTIME').location, 'version', name)
                path.write_bytes(saved)
            self.assertEqual(first, adaptor.data_fingerprint(root))
            self.fault(lambda: adaptor.data_fingerprint(Path(tmp) / 'missing'), 'UNSUPPORTED_RUNTIME')
            self.fault(lambda: adaptor.data_fingerprint('relative'), 'UNSUPPORTED_RUNTIME')

    # ------------------------------------------------------------ strict JSON and typed comparison
    def test_retained_json_is_read_strictly(self):
        good = b'{"a": [1, 2.5, true, null, "x"]}'
        self.assertEqual(adaptor.strict_json(good, 'x.json'), {'a': [1, 2.5, True, None, 'x']})
        for label, data in (('duplicate', b'{"a": 1, "a": 2}'), ('nested duplicate', b'{"a": {"b": 1, "b": 2}}'), ('NaN', b'{"a": NaN}'), ('Infinity', b'{"a": Infinity}'),
                            ('-Infinity', b'{"a": -Infinity}'), ('overflow', b'{"a": 1e400}'), ('bom', b'\xef\xbb\xbf{"a": 1}'), ('bad utf-8', b'{"a": "\xff"}'), ('deep', b'[' * 100000 + b']' * 100000),
                            ('trailing', b'{"a": 1} x')):
            with self.subTest(label):
                self.fault(lambda: adaptor.strict_json(data, 'x.json'), 'VERIFICATION_FAILED')

    def test_typed_comparison_does_not_collapse_booleans_numbers_or_member_order(self):
        self.assertTrue(adaptor.same_json({'a': 1, 'b': [True, None]}, {'b': [True, None], 'a': 1}))
        for left, right in ((True, 1), (1, True), (66, 66.0), ({'a': 0}, {'a': False}), ([1], [1.0]), ({'a': 1}, {'a': 1, 'b': 2}), (float('nan'), float('nan'))):
            self.assertFalse(adaptor.same_json(left, right), (left, right))

    def test_result_claims_are_closed_and_exclude_only_the_status(self):
        claims = adaptor.result_claims({'status': 'succeeded', 'verified': True, 'runtime': {'espeakng': 'eSpeak NG 1.52.0', 'dataFingerprint': 'a' * 64}})
        self.assertEqual(set(claims), {'verified', 'runtime'})
        self.assertEqual(claims['runtime'], {'espeakng': 'eSpeak NG 1.52.0', 'dataFingerprint': 'a' * 64})
        self.assertEqual(adaptor.result_claims({'status': 'failed'}), {})

    def test_launcher_is_fixed_bounded_and_clean_environment(self):
        launcher = adaptor.launcher('narrate', ['captured.txt'], ['/x/espeak-ng', *adaptor.narrate_arguments(175)], adaptor.WAV_FILE_CAP)
        compile(launcher, 'launcher', 'exec')
        self.assertIn('{"LANG":"C.UTF-8","LC_ALL":"C.UTF-8"}', launcher)
        for forbidden in ('HOME', 'ESPEAK_DATA_PATH', 'PATH', 'environ'):
            self.assertNotIn(forbidden, launcher)
        self.assertIn('RLIMIT_AS,(2147483648,2147483648)', launcher)
        self.assertIn('RLIMIT_FSIZE,(%d,%d)' % (adaptor.WAV_FILE_CAP, adaptor.WAV_FILE_CAP), launcher)
        self.assertIn("'-ven-us', '-s175', '-p50', '-a100', '-b1', '-w', 'native.wav', '-f', 'captured.txt']", launcher)
        commands = adaptor.stage_commands(140, '/x/espeak-ng')
        self.assertEqual(list(commands), ['version', 'voices', 'narrate'])
        self.assertEqual(commands['version'][0], ['/x/espeak-ng', '--version'])
        self.assertEqual(commands['voices'][0], ['/x/espeak-ng', '--voices=en'])
        self.assertEqual(commands['narrate'], (['/x/espeak-ng', '-ven-us', '-s140', '-p50', '-a100', '-b1', '-w', 'native.wav', '-f', 'captured.txt'], ['captured.txt'], adaptor.WAV_FILE_CAP))
        for banned in ('-m', '-x', '-X', '--ipa', '--stdout', '--stdin', '-d', '--path', '--punct', '-k', '-g', '-l', '-q', '-z', '--split'):
            self.assertNotIn(banned, [a for command, _, _ in commands.values() for a in command])

    def test_schema_is_closed_with_two_alternatives_and_matching_defaults(self):
        schema = adaptor.schema()
        self.assertEqual(schema['required'], ['version', 'operation'])
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(set(schema['properties']), {'version', 'operation', 'text', 'source', 'rateWpm', 'voice'})
        literal, file = schema['oneOf']
        self.assertEqual((literal['required'], file['required']), (['version', 'operation', 'text'], ['version', 'operation', 'source']))
        self.assertEqual((set(literal['properties']), set(file['properties'])), ({'version', 'operation', 'text', 'rateWpm', 'voice'}, {'version', 'operation', 'source', 'rateWpm', 'voice'}))
        self.assertEqual({k: schema['properties']['rateWpm'][k] for k in ('type', 'minimum', 'maximum', 'default')}, {'type': 'integer', 'minimum': 120, 'maximum': 240, 'default': 175})
        self.assertEqual({k: schema['properties']['text'][k] for k in ('type', 'minLength', 'maxLength')}, {'type': 'string', 'minLength': 1, 'maxLength': 1024})
        for item in (schema, literal, file):
            json.dumps(item, allow_nan=False)

    def test_example_documents_plan_and_the_workflows_defer_their_artifacts(self):
        from schemaxis import workflow
        for name, fault in (('invalid-phoneme', 'INVALID_ESPEAKNG_TEXT'), ('invalid-source', 'INVALID_ESPEAKNG_SOURCE')):
            self.fault(lambda: adaptor.plan(self.document(name)), fault)
        for name in ('speech-workflow', 'archive-workflow', 'transcript-workflow'):
            planned = workflow.inspect_plan(self.document(name))
            self.assertEqual([entry['id'] for entry in planned['operations']][0], 'narration' if name != 'transcript-workflow' else 'transcribe', name)
            consumer = planned['operations'][1]['provisionalPlan']
            self.assertEqual(consumer['status'], 'deferred', name)
            self.assertEqual(consumer['references'][0]['$artifact'], planned['operations'][0]['id'], name)
        self.assertEqual(self.document('transcript-workflow')['operations'][1]['document']['source'], {'$artifact': 'transcribe', 'index': 1})


if __name__ == '__main__':
    unittest.main()
