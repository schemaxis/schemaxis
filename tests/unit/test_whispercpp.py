"""Transcription contract: strict native evidence, deterministic captions and hostile receipts.

A small deterministic test double stands in for the native executable so that every
check here is host-only. It is never counted as native acceptance; the real
whisper.cpp runs are in tools/qualify_whispercpp.py.
"""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
import wave

from schemaxis.adaptors import registry
from schemaxis.adaptors.whispercpp import adaptor as a
from schemaxis.adaptors.whispercpp import caption_review as cr
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation

ROOT = Path(__file__).resolve().parents[2]
SPEECH = "And so my fellow Americans, ask not what your country can do for you."


def wav(frames=32000, rate=16000, channels=1, bits=16, extra=b''):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as w:
        w.setparams((channels, bits // 8, rate, 0, 'NONE', 'not compressed'))
        w.writeframes(struct.pack('<' + 'h' * (frames * channels), *[(i * 37) % 2000 - 1000 for i in range(frames * channels)]))
    return stream.getvalue() + extra


def clock(ms, sep=','): return '%02d:%02d:%02d%s%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, sep, ms % 1000)


def native(segments, language='en', model='/proc/self/fd/3'):
    return {'systeminfo': 'CPU : test = 1 | ', 'model': {'type': 'base', 'multilingual': False, 'vocab': 51864,
            'audio': {'ctx': 1500, 'state': 512, 'head': 8, 'layer': 6}, 'text': {'ctx': 448, 'state': 512, 'head': 8, 'layer': 6}, 'mels': 80, 'ftype': 1},
        'params': {'model': model, 'language': language, 'translate': False}, 'result': {'language': language},
        'transcription': [{'timestamps': {'from': clock(s), 'to': clock(e)}, 'offsets': {'from': s, 'to': e}, 'text': ' ' + t} for s, e, t in segments]}


class Contract(unittest.TestCase):
    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught: action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def doc(self, name='jfk'): return json.loads((ROOT / f'examples/schemaxis/whispercpp-{name}.json').read_text())

    def test_common_host_conformance_discovery_and_guidance(self):
        from schemaxis.adaptor_conformance import host
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        from schemaxis.studio_guidance import audit
        self.assertTrue(host(a.VERSION)['verified'])
        self.assertTrue(check_cases(CapabilityCatalogue(providers=['whispercpp']), 'whispercpp')['complete'])
        self.assertTrue(audit('whispercpp')['complete'])

    def test_manifest_is_native_free_and_registered(self):
        self.assertIn('whispercpp', registry.ADAPTORS)
        self.assertEqual(registry.ADAPTORS['whispercpp']['executables'], ['whisper-cli'])
        self.assertNotIn('whisper', ' '.join(m for m in sys.modules if m.startswith('whisper')))

    def test_immutable_deterministic_defaults(self):
        d = self.doc();del d['language'];del d['audio']['sha256'];before = copy.deepcopy(d)
        p = a.plan(d);self.assertEqual(d, before);self.assertEqual(p, a.plan(d))
        self.assertEqual((p['language'], p['audio']), ('en', {'path': d['audio']['path']}))
        self.assertEqual(a.query(d)[0], ['transcribe'])
        self.assertEqual(a.resources(d, {}, 'x'), {'threads': 1})
        self.fault(lambda: a.resources(d, {'threads': 2}, 'x'), 'INVALID_EXECUTION')

    def test_exact_semantic_faults_and_locations(self):
        def change(f):
            d = self.doc();f(d);return d
        cases = [('INVALID_AUDIO_SOURCE', '$.audio.path', lambda d: d['audio'].update(path='speech.wav')),
            ('INVALID_AUDIO_SOURCE', '$.audio.path', lambda d: d['audio'].update(path='/a/../b/speech.wav')),
            ('INVALID_AUDIO_SOURCE', '$.audio.path', lambda d: d['audio'].update(path='/a/speech.mp3')),
            ('INVALID_MODEL', '$.model.path', lambda d: d['model'].update(path='/m/model.gguf')),
            ('INVALID_MODEL', '$.model.path', lambda d: d['model'].update(path='relative/model.bin')),
            ('INVALID_SHA256', '$.model.sha256', lambda d: d['model'].update(sha256=d['model']['sha256'].upper())),
            ('INVALID_SHA256', '$.audio.sha256', lambda d: d['audio'].update(sha256='g' * 64)),
            ('INVALID_LANGUAGE', '$.language', lambda d: d.update(language='EN')),
            ('INVALID_LANGUAGE', '$.language', lambda d: d.update(language='e1'))]
        for code, location, mutate in cases:
            self.assertEqual(self.fault(lambda: a.plan(change(mutate)), code).location, location)
        for mutate in (lambda d: d.update(operation='translate'), lambda d: d.update(version='schemaxis.whispercpp/2'),
                       lambda d: d.update(prompt='hello'), lambda d: d['model'].update(url='https://example.invalid/m.bin'),
                       lambda d: d['audio'].update(path=3), lambda d: d.pop('model'), lambda d: d['model'].pop('sha256'), lambda d: d.update(language='')):
            with self.assertRaises(SchemaxisError): a.plan(change(mutate))
        for name in ('relative-invalid', 'hash-invalid'):
            example = self.doc(name)
            self.assertTrue(example)
            self.fault(lambda: a.plan(example), 'INVALID_AUDIO_SOURCE' if name == 'relative-invalid' else 'INVALID_SHA256')

    def test_audio_boundary_rejections(self):
        self.assertEqual(a.audio_info(wav(32000))['frames'], 32000)
        for data in (wav(rate=44100), wav(channels=2), wav(bits=8), b'RIFF', wav(extra=b'x'), wav()[:-3], wav()[:40],
                     wav().replace(b'data', b'dat2', 1), bytes(44)):
            self.fault(lambda: a.audio_info(data), 'INVALID_AUDIO_DATA')
        raw = wav(100);doubled = raw[:4] + struct.pack('<I', len(raw) + len(raw[raw.index(b'data'):]) - 8) + raw[8:] + raw[raw.index(b'data'):]
        self.fault(lambda: a.audio_info(doubled), 'INVALID_AUDIO_DATA')
        self.fault(lambda: a.audio_info(wav(a.MAX_SECONDS * a.RATE + 1)), 'AUDIO_RESOURCE_LIMIT')
        self.assertEqual(a.audio_info(wav(a.MAX_SECONDS * a.RATE))['frames'], 9600000)

    def parse(self, raw, frames=176000, language='en'):
        p = a.plan(self.doc());p['language'] = language
        return a.native_segments(raw, p, frames)

    def test_strict_native_json_contract(self):
        good = native([(0, 2500, SPEECH), (2500, 11000, 'Second.')])
        self.assertEqual([(s['startMs'], s['endMs'], s['text']) for s in self.parse(good)], [(0, 2500, SPEECH), (2500, 11000, 'Second.')])
        for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '﻿{}', '{"a":'):
            self.fault(lambda: a.strict_json(text.encode(), 'native.json'), 'TRANSCRIPT_INVALID')
        self.fault(lambda: a.strict_json(b'\xff\xfe', 'native.json'), 'TRANSCRIPT_INVALID')
        # Real whisper.cpp escapes only quotes/backslashes, so raw control bytes are invalid JSON too.
        self.fault(lambda: a.strict_json(b'{"text": " a\nb"}', 'native.json'), 'TRANSCRIPT_INVALID')
        def mutated(f):
            doc = copy.deepcopy(good);f(doc);return doc
        invalid = {
            'extraRoot': lambda d: d.update(extra=1), 'missingRoot': lambda d: d.pop('model'), 'extraModel': lambda d: d['model'].update(x=1),
            'badDimension': lambda d: d['model']['audio'].update(ctx=0), 'boolDimension': lambda d: d['model']['text'].update(head=True),
            'paramsPath': lambda d: d['params'].update(model='/tmp/model.bin'), 'translate': lambda d: d['params'].update(translate=True),
            'paramsLanguage': lambda d: d['params'].update(language='de'), 'resultLanguage': lambda d: d['result'].update(language='de'),
            'notList': lambda d: d.update(transcription={}), 'extraSegment': lambda d: d['transcription'][0].update(tokens=[]),
            'textType': lambda d: d['transcription'][0].update(text=3), 'blank': lambda d: d['transcription'][0].update(text='   '),
            'newline': lambda d: d['transcription'][0].update(text=' a\nb'), 'nul': lambda d: d['transcription'][0].update(text=' a\x00b'),
            'lineSeparator': lambda d: d['transcription'][0].update(text=' a b'), 'marker': lambda d: d['transcription'][0].update(text=' a --> b'),
            'replacement': lambda d: d['transcription'][0].update(text=' a�b'), 'surrogate': lambda d: d['transcription'][0].update(text=' a\ud800b'),
            'tooLong': lambda d: d['transcription'][0].update(text=' ' + 'x' * (a.MAX_SEGMENT_CHARACTERS + 1)),
            'stampText': lambda d: d['transcription'][0]['timestamps'].update(to='00:00:02,501'), 'stampShape': lambda d: d['transcription'][0]['timestamps'].update(to='2.5'),
            'dotSeparator': lambda d: d['transcription'][0]['timestamps'].update(to='00:00:02.500'),
        }
        for name, f in invalid.items():
            with self.subTest(name):
                with self.assertRaises(SchemaxisError) as caught: self.parse(mutated(f))
                self.assertEqual(caught.exception.fault.code, 'TRANSCRIPT_INVALID' if name not in ('stampText', 'stampShape', 'dotSeparator') else 'TRANSCRIPT_TIMING', caught.exception.fault.to_dict())
        self.fault(lambda: self.parse(mutated(lambda d: d.update(transcription=[]))), 'TRANSCRIPT_EMPTY')
        many = native([(i, i + 1, 'x') for i in range(a.MAX_SEGMENTS + 1)])
        self.fault(lambda: self.parse(many, frames=a.MAX_SECONDS * a.RATE), 'TRANSCRIPT_RESOURCE_LIMIT')

    def test_timing_policy(self):
        def timing(segments, frames=176000): return self.parse(native(segments), frames)
        self.assertEqual(len(timing([(0, 11000, 'edge')])), 1)          # exact audio boundary
        for segments in ([(0, 11001, 'late')], [(0, 0, 'empty')], [(5, 4, 'backwards')], [(0, 5000, 'a'), (4999, 6000, 'b')], [(5000, 6000, 'a'), (0, 1000, 'b')], [(-1, 5, 'neg')]):
            with self.assertRaises(SchemaxisError) as caught: timing(segments)
            self.assertEqual(caught.exception.fault.code, 'TRANSCRIPT_TIMING', segments)
        d = native([(0, 1000, 'a')]);d['transcription'][0]['offsets']['from'] = 0.0
        self.fault(lambda: self.parse(d), 'TRANSCRIPT_TIMING')
        d['transcription'][0]['offsets']['from'] = True
        self.fault(lambda: self.parse(d), 'TRANSCRIPT_TIMING')
        d['transcription'][0]['offsets']['from'] = 10 ** 15
        self.fault(lambda: self.parse(d), 'TRANSCRIPT_TIMING')
        self.assertEqual(len(timing([(0, 1000, 'a'), (1000, 2000, 'b')], frames=32000)), 2)   # touching is allowed
        self.fault(lambda: timing([(0, 2101, 'a')], frames=32000), 'TRANSCRIPT_TIMING')

    def test_deterministic_text_srt_and_webvtt(self):
        segments = [{'index': 0, 'startMs': 0, 'endMs': 1500, 'text': 'Café & 日本語', '_raw': ' Café & 日本語'},
                    {'index': 1, 'startMs': 3723004, 'endMs': 3723999, 'text': 'Done.', '_raw': ' Done.'}]
        self.assertEqual(a.srt(segments), '1\n00:00:00,000 --> 00:00:01,500\nCafé & 日本語\n\n2\n01:02:03,004 --> 01:02:03,999\nDone.\n\n')
        self.assertEqual(a.vtt(segments), 'WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nCafé &amp; 日本語\n\n01:02:03.004 --> 01:02:03.999\nDone.\n\n')
        self.assertEqual(a.transcript(segments), 'Café & 日本語\nDone.\n')
        self.assertEqual(a.native_srt(segments), '1\n00:00:00,000 --> 00:00:01,500\n Café & 日本語\n\n2\n01:02:03,004 --> 01:02:03,999\n Done.\n\n')

    def test_subtitle_markup_is_refused_in_native_cue_text(self):
        for text in ('<b>bold</b>', 'A < B', 'A > B', '<font color="white">hidden</font>', '{\\an8}Above', '\u202ehidden'):
            self.fault(lambda: self.parse(native([(0,1000,text)])), 'TRANSCRIPT_INVALID')

    def test_launcher_is_trusted_text_without_authored_values(self):
        p = a.plan(self.doc());p['language'] = 'en'
        for stage, command in a.commands('/x/whisper-cli', p).items():
            text = a.launcher(Path('/run'), stage, command, p)
            compile(text, stage, 'exec')
            self.assertEqual(text, a.launcher(Path('/run'), stage, command, p))
        command = a.commands('/x/whisper-cli', p)['transcribe']
        self.assertEqual(command[:4], ['/x/whisper-cli', '-m', '@MODEL@', '-f'])
        self.assertTrue({'-ng', '-oj', '-osrt'} <= set(command))
        self.assertNotIn(p['model']['path'], command)
        self.assertNotIn(p['audio']['path'], command)
        self.assertIn('LD_TRACE_LOADED_OBJECTS', a.launcher(Path('/run'), 'libraries', ['x'], p))


def doc_of(*cues):
    """Minimal checked-segment document for the pure review heuristics."""
    return {'segments': [{'index': i, 'startMs': s, 'endMs': e, 'text': t} for i, (s, e, t) in enumerate(cues)]}


class CaptionReview(unittest.TestCase):
    """Fixed editorial heuristics, independent of any native run."""

    def flags(self, duration, text): return cr.build(doc_of((0, duration, text)), '0' * 64)['cues'][0]['flags']

    def test_option_is_optional_closed_boolean_and_leaves_plans_unchanged(self):
        base = json.loads((ROOT / 'examples/schemaxis/whispercpp-jfk.json').read_text())
        plain = a.plan(base)
        self.assertEqual(set(plain), {'version', 'operation', 'audio', 'model', 'language', 'losses'})
        self.assertEqual(plain['losses'], a.LOSSES)
        explicit = a.plan({**base, 'captionReview': False})
        self.assertIs(explicit['captionReview'], False);self.assertEqual(explicit['losses'], a.LOSSES)
        on = a.plan({**base, 'captionReview': True})
        self.assertIs(on['captionReview'], True);self.assertEqual(on['losses'], [*a.LOSSES, cr.LOSS])
        for bad in (1, 0, 'true', 'yes', None, [], {}, 1.0):
            with self.assertRaises(SchemaxisError, msg=repr(bad)): a.plan({**base, 'captionReview': bad})
        with self.assertRaises(SchemaxisError): a.plan({**base, 'captionReviewThresholds': {'longMs': 1}})
        example = json.loads((ROOT / 'examples/schemaxis/whispercpp-caption-review.json').read_text())
        self.assertIs(a.plan(example)['captionReview'], True)
        self.assertEqual({k: v for k, v in example.items() if k != 'captionReview'}, base)
        # The native command line does not depend on the option.
        self.assertEqual(a.commands('/x/whisper-cli', plain), a.commands('/x/whisper-cli', on))
        declared = a.schema()['properties']['captionReview']
        self.assertEqual((declared['type'], declared['default']), ('boolean', False))
        self.assertNotIn('captionReview', a.schema()['required'])

    def test_duration_boundaries(self):
        for duration, expected in ((1, ['short-duration', 'dense-text']), (49, ['short-duration', 'dense-text']), (50, ['short-duration']), (999, ['short-duration']), (1000, []), (1001, []), (7000, []), (7001, ['long-duration']), (60000, ['long-duration'])):
            self.assertEqual(self.flags(duration, 'a'), expected, duration)

    def test_density_boundary_is_exact_integer_arithmetic(self):
        self.assertEqual(self.flags(2000, 'x' * 40), [])                      # exactly 20 code points per second
        self.assertEqual(self.flags(2000, 'x' * 41), ['dense-text'])
        self.assertEqual(self.flags(3000, 'x' * 60), [])
        self.assertEqual(self.flags(3000, 'x' * 61), ['dense-text'])
        self.assertEqual(self.flags(1000, 'x' * 20), []);self.assertEqual(self.flags(1000, 'x' * 21), ['dense-text'])
        self.assertEqual(self.flags(999, 'x' * 20), ['short-duration', 'dense-text'])   # flags are ordered and independent
        self.assertEqual(cr.build(doc_of((0, 3000, 'x' * 10)), '0' * 64)['cues'][0]['codePointsPerSecondMilli'], 3333)   # floor
        self.assertEqual(cr.build(doc_of((0, 3000, 'x' * 20)), '0' * 64)['cues'][0]['codePointsPerSecondMilli'], 6666)

    def test_length_is_unicode_code_points_not_graphemes_or_display_width(self):
        def points(text): return cr.build(doc_of((0, 2000, text)), '0' * 64)['cues'][0]['codePoints']
        self.assertEqual(points('é'), 1);self.assertEqual(points('e\u0301'), 2)         # same grapheme, different code points
        self.assertEqual(points('👨‍👩‍👧'), 5)                                          # one family emoji grapheme, five scalars
        self.assertEqual(points('日本語'), 3);self.assertEqual(points('abc'), 3)         # no display-width weighting
        self.assertEqual(points('A & B'), 5)                                             # WebVTT escaping is not counted
        self.assertEqual(points('a b'), 3)                                               # spaces and punctuation count once each

    def test_report_is_deterministic_bounded_pure_and_has_no_floats_or_verdicts(self):
        document = doc_of((0, 500, 'Hi.'), (500, 9000, 'Long quiet cue.'), (9000, 10000, 'x' * 30), (10000, 12000, 'Fine.'))
        before = copy.deepcopy(document)
        report = cr.build(document, 'a' * 64)
        self.assertEqual(document, before);self.assertEqual(report, cr.build(document, 'a' * 64))
        self.assertEqual([c['flags'] for c in report['cues']], [['short-duration'], ['long-duration'], ['dense-text'], []])
        self.assertEqual((report['cueCount'], report['flaggedCueCount']), (4, 3))
        self.assertEqual(report['flagCounts'], {'short-duration': 1, 'long-duration': 1, 'dense-text': 1})
        self.assertEqual(cr.summary(report), {'cues': 4, 'flaggedCues': 3, 'flagCounts': report['flagCounts']})
        self.assertNotIn('"text"', json.dumps(report))                                    # words stay in segments.json only
        def walk(value):
            if isinstance(value, dict):
                for v in value.values(): yield from walk(v)
            elif isinstance(value, list):
                for v in value: yield from walk(v)
            else: yield value
        self.assertFalse(any(isinstance(v, float) for v in walk(report)))
        claims = report['review']
        self.assertEqual([claims[k] for k in ('accuracyCertified', 'accessibilityCertified', 'readabilityCertified', 'passCertified')], [False] * 4)
        self.assertIs(claims['humanReviewRequired'], True);self.assertIn('regardless', claims['statement'])
        self.assertEqual((report['policy']['shortDurationBelowMs'], report['policy']['longDurationAboveMs'], report['policy']['denseTextAboveCodePointsPerSecond']), (1000, 7000, 20))
        self.assertIn('not grapheme', report['policy']['textLength']);self.assertIn('not a standard', report['policy']['kind'])
        # A review of zero flags still demands human review.
        quiet = cr.build(doc_of((0, 3000, 'Fine.')), 'b' * 64)
        self.assertEqual((quiet['flaggedCueCount'], quiet['flagCounts']), (0, {'short-duration': 0, 'long-duration': 0, 'dense-text': 0}))
        self.assertIs(quiet['review']['humanReviewRequired'], True);self.assertIs(quiet['review']['passCertified'], False)
        many = doc_of(*[(i * 10, i * 10 + 9, 'x') for i in range(a.MAX_SEGMENTS)])
        self.assertLess(len(a.encode_json(cr.build(many, 'c' * 64))), a.JSON_LIMIT // 4)

    def test_strict_check_rejects_every_structural_and_type_forgery(self):
        document = doc_of((0, 500, 'Hi.'), (500, 9000, 'Long quiet cue.'))
        good = cr.build(document, 'a' * 64);cr.check(copy.deepcopy(good), good)
        def mutated(f):
            value = copy.deepcopy(good);f(value);return value
        forgeries = {
            'rootExtra': lambda r: r.update(extra=1), 'rootMissing': lambda r: r.pop('policy'), 'cueExtra': lambda r: r['cues'][0].update(text='Hi.'), 'cueMissing': lambda r: r['cues'][1].pop('flags'),
            'policyExtra': lambda r: r['policy'].update(strict=True), 'reviewExtra': lambda r: r['review'].update(approved=True), 'countsExtra': lambda r: r['flagCounts'].update(other=0),
            'durationMetric': lambda r: r['cues'][1].update(durationMs=8499), 'codePointMetric': lambda r: r['cues'][0].update(codePoints=4), 'rateMetric': lambda r: r['cues'][0].update(codePointsPerSecondMilli=1),
            'flagRemoved': lambda r: r['cues'][1].update(flags=[]), 'flagAdded': lambda r: r['cues'][1].update(flags=['long-duration', 'dense-text']), 'flagDuplicated': lambda r: r['cues'][1].update(flags=['long-duration'] * 2),
            'flagUnknown': lambda r: r['cues'][1].update(flags=['readable']), 'flagType': lambda r: r['cues'][1].update(flags=[1]), 'flagsString': lambda r: r['cues'][1].update(flags='long-duration'),
            'flagOrder': lambda r: r['cues'][0].update(flags=['dense-text', 'short-duration']),
            'cueCount': lambda r: r.update(cueCount=3), 'flaggedCount': lambda r: r.update(flaggedCueCount=0), 'flagCount': lambda r: r['flagCounts'].update(**{'long-duration': 0}),
            'cueRemoved': lambda r: r['cues'].pop(), 'cueDuplicated': lambda r: r['cues'].append(copy.deepcopy(r['cues'][0])), 'cueReordered': lambda r: r['cues'].reverse(), 'cuesNotList': lambda r: r.update(cues={}),
            'segmentsHash': lambda r: r.update(segmentsSha256='b' * 64), 'version': lambda r: r.update(version='schemaxis.whispercpp.caption-review/2'),
            'policyThreshold': lambda r: r['policy'].update(longDurationAboveMs=30000), 'policyText': lambda r: r['policy'].update(textLength='grapheme clusters'),
            'passClaimed': lambda r: r['review'].update(passCertified=True), 'humanReviewDropped': lambda r: r['review'].update(humanReviewRequired=False), 'accessibilityClaimed': lambda r: r['review'].update(accessibilityCertified=True),
            'statementEdited': lambda r: r['review'].update(statement='All good.'),
            'boolAsInt': lambda r: r['review'].update(passCertified=0), 'intAsBool': lambda r: r['cues'][0].update(startMs=False), 'intAsFloat': lambda r: r['cues'][0].update(durationMs=500.0),
            'floatPolicy': lambda r: r['policy'].update(shortDurationBelowMs=1000.0), 'intAsString': lambda r: r['cues'][0].update(codePoints='3'), 'countAsFloat': lambda r: r.update(cueCount=2.0),
            'hashAsInt': lambda r: r.update(segmentsSha256=0), 'rootNotObject': lambda r: None}
        for name, f in forgeries.items():
            with self.subTest(name):
                with self.assertRaises(SchemaxisError) as caught: cr.check([] if name == 'rootNotObject' else mutated(f), good)
                self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED', caught.exception.fault.to_dict())
        # A forged metric is located at the offending cue member.
        with self.assertRaises(SchemaxisError) as caught: cr.check(mutated(lambda r: r['cues'][1].update(durationMs=8499)), good)
        self.assertEqual(caught.exception.fault.location, 'caption-review.json $.cues[1].durationMs')


FAKE = '''#!{python}
import json,os,sys
from pathlib import Path
cfg=json.loads(Path({config!r}).read_text());args=sys.argv[1:]
if args==['--version']:
    sys.stdout.write(cfg['version']+'\\n')
    sys.exit(0)
if cfg.get('sleep'):
    Path(cfg['marker']).write_text(str(os.getpid()));import time;time.sleep(cfg['sleep'])
model=args[args.index('-m')+1];assert model.startswith('/proc/self/fd/'),model
audio=Path(args[args.index('-f')+1]).read_bytes()
loaded=Path(model).read_bytes()
if cfg.get('mutate_model'): open(cfg['model_path'],'ab').write(b'x')
if cfg.get('replace_executable'): open(sys.argv[0],'a').write('# changed during the run\\n')
native=cfg['native'];native['params']['model']=model
Path('native.json').write_text(json.dumps(native,ensure_ascii=False,indent=1),encoding='utf-8')
def ts(ms): return '%02d:%02d:%02d,%03d'%(ms//3600000,ms//60000%60,ms//1000%60,ms%1000)
srt=''.join(f"{{i+1}}\\n{{ts(s['offsets']['from'])}} --> {{ts(s['offsets']['to'])}}\\n{{s['text']}}\\n\\n" for i,s in enumerate(native['transcription']))
Path('native.srt').write_text(cfg.get('native_srt',srt),encoding='utf-8')
'''


class FakeNativeRuns(unittest.TestCase):
    """End to end through the real launcher, runner, verifier and publication metadata."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.dir = Path(self.temporary.name)
        self.audio = self.dir / 'speech.wav';self.audio.write_bytes(wav(176000))
        self.model = self.dir / 'tiny.bin';self.model.write_bytes(os.urandom(5000))
        self.config = self.dir / 'fake.json'
        self.exe = self.dir / 'whisper-cli'
        self.exe.write_text(FAKE.format(python=sys.executable, config=str(self.config)));self.exe.chmod(0o700)
        self.setup_config()
        self.document = {'version': a.VERSION, 'operation': 'transcribe', 'audio': {'path': str(self.audio), 'sha256': hashlib.sha256(self.audio.read_bytes()).hexdigest()},
                         'model': {'path': str(self.model), 'sha256': hashlib.sha256(self.model.read_bytes()).hexdigest()}, 'language': 'en'}

    def setup_config(self, **change):
        config = {'version': 'whisper.cpp version: 1.9.5', 'model_path': str(self.model),
                  'native': native([(0, 2500, SPEECH), (2600, 11000, 'Ask what you can do.')])}
        config.update(change);self.config.write_text(json.dumps(config))

    def run_job(self, name='run', **options):
        return a.run(self.document, self.dir / name, executable=str(self.exe), timeout=options.pop('timeout', 30), **options)

    def refuse(self, action, code=None):
        with self.assertRaises(SchemaxisError) as caught: action()
        if code: self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def refresh(self, directory):
        receipt = a.read(directory, 'verification.json');receipt['artifacts'] = a.artifacts(directory)
        receipt['evidence'] = {n: a.digest(directory, n) for n in receipt['evidence']};a.atomic_json(directory / 'verification.json', receipt)
        from schemaxis.publication_metadata import finalise
        finalise(directory)

    def test_successful_run_verifies_every_publication(self):
        result = self.run_job()
        self.assertEqual((result['status'], result['runtime'], result['segments'], result['audioDurationMs']), ('succeeded', 'whisper.cpp 1.9.5', 2, 11000))
        self.assertFalse(result['accuracyCertified']);self.assertTrue(result['humanReviewRequired'])
        directory = self.dir / 'run'
        self.assertTrue(a.verify(directory)['verified'])
        self.assertEqual((directory / 'transcript.txt').read_text(), SPEECH + '\nAsk what you can do.\n')
        self.assertEqual((directory / 'captions.srt').read_text(), f'1\n00:00:00,000 --> 00:00:02,500\n{SPEECH}\n\n2\n00:00:02,600 --> 00:00:11,000\nAsk what you can do.\n\n')
        self.assertTrue((directory / 'captions.vtt').read_text().startswith('WEBVTT\n\n00:00:00.000 --> 00:00:02.500\n'))
        segments = json.loads((directory / 'segments.json').read_text())
        self.assertFalse(segments['review']['accuracyCertified']);self.assertIn('not certified', segments['review']['statement'])
        self.assertEqual(a.reusableInputs(self.document), {'audio': self.document['audio']['sha256'], 'model': self.document['model']['sha256']})
        # The model is bound through a descriptor, never copied into the run.
        self.assertFalse(any(path.stat().st_size >= 5000 and path.name == 'tiny.bin' for path in directory.iterdir()))
        # Verification does not need the original files.
        self.audio.unlink();self.model.unlink()
        self.assertTrue(a.verify(directory)['verified'])

    def test_pre_native_input_refusals(self):
        self.audio.write_bytes(wav(176000, rate=8000))
        self.refuse(lambda: self.run_job('rate'), 'INVALID_AUDIO_DATA')
        self.audio.write_bytes(wav(176000))
        self.document['audio']['sha256'] = '0' * 64
        self.refuse(lambda: self.run_job('pin'), 'AUDIO_HASH_MISMATCH')
        self.document['audio']['sha256'] = hashlib.sha256(self.audio.read_bytes()).hexdigest()
        self.model.write_bytes(b'different model')
        self.refuse(lambda: self.run_job('model'), 'MODEL_HASH_MISMATCH')
        self.assertFalse((self.dir / 'model' / 'version-launcher.py').exists())
        self.document['model']['path'] = str(self.dir / 'absent.bin')
        self.refuse(lambda: self.run_job('absent'), 'INVALID_MODEL')
        self.document['model']['path'] = str(self.dir / 'dir.bin');(self.dir / 'dir.bin').mkdir()
        self.refuse(lambda: self.run_job('directory'), 'INVALID_MODEL')
        self.refuse(lambda: a.run(self.document, self.dir / 'noexe', executable='relative'), 'INTERPRETER_NOT_FOUND')
        self.refuse(lambda: self.run_job('timeout', timeout=0), 'INVALID_ARGUMENT')
        (self.dir / 'exists').mkdir()
        self.refuse(lambda: self.run_job('exists'), 'OUTPUT_EXISTS')

    def test_native_contract_violations_publish_nothing(self):
        late = native([(0, 12000, 'beyond the 11 second recording')])
        wrong = native([(0, 1000, 'x')], language='de')
        for code, value in (('TRANSCRIPT_EMPTY', native([])), ('TRANSCRIPT_TIMING', late), ('TRANSCRIPT_INVALID', wrong)):
            self.setup_config(native=value)
            name = code.lower()
            self.refuse(lambda: self.run_job(name), code)
            self.assertFalse((self.dir / name / 'captions.srt').exists())
            self.assertEqual(json.loads((self.dir / name / 'result.json').read_text())['status'], 'failed')
        self.setup_config(native_srt='1\n00:00:00,000 --> 00:00:02,500\nA different native caption\n\n')
        self.refuse(lambda: self.run_job('nativesrt'), 'VERIFICATION_FAILED')
        self.setup_config(version='whisper.cpp version: 1.9.4-dev')
        self.refuse(lambda: self.run_job('old'), 'UNSUPPORTED_NATIVE_VERSION')
        self.assertFalse((self.dir / 'old' / 'transcribe-launcher.py').exists())

    def test_model_or_runtime_change_during_run(self):
        self.setup_config(mutate_model=True)
        self.refuse(lambda: self.run_job('model-changed'), 'MODEL_CHANGED')
        self.model.write_bytes(os.urandom(5000));self.document['model']['sha256'] = hashlib.sha256(self.model.read_bytes()).hexdigest()
        self.setup_config(replace_executable=True)
        self.refuse(lambda: self.run_job('runtime-changed'), 'RUNTIME_CHANGED')

    def test_runtime_version_accepts_release_and_development_strings_only(self):
        self.assertEqual(self.run_job('release')['runtime'], 'whisper.cpp 1.9.5')
        self.setup_config(version='whisper.cpp version: 1.9.5-dev')
        self.assertEqual(self.run_job('dev')['runtime'], 'whisper.cpp 1.9.5-dev')
        for bad in ('whisper.cpp version: 1.9.5-rc1', 'whisper.cpp version: 1.9.50', 'whisper.cpp version: 1.9.5\nextra', 'version 1.9.5', ''):
            self.setup_config(version=bad)
            self.refuse(lambda: self.run_job('bad' + str(abs(hash(bad)))), 'UNSUPPORTED_NATIVE_VERSION')

    def test_rehashed_tampering_is_rejected_semantically(self):
        self.run_job();directory = self.dir / 'run';saved = {p: p.read_bytes() for p in directory.iterdir() if p.is_file()}
        def restore():
            for path in [p for p in directory.iterdir() if p.is_file() and p not in saved]: path.unlink()
            for path, data in saved.items(): path.write_bytes(data)
        def tamper(name, mutate, codes=('VERIFICATION_FAILED',)):
            try:
                path = directory / name;path.write_bytes(mutate(path.read_bytes()));self.refresh(directory)
                self.assertIn(self.refuse(lambda: a.verify(directory)).code, codes)
            finally: restore()
        for key,value in [('accuracyCertified',True),('humanReviewRequired',False),('verified',1),('segments',2.0),('invented','claim')]:
            tamper('result.json', lambda b,k=key,v=value: json.dumps({**json.loads(b),k:v}).encode())
        tamper('captions.srt', lambda b: b.replace(b'country', b'county'))
        tamper('captions.vtt', lambda b: b.replace(b'00:00:02.500', b'00:00:02.501'))
        tamper('transcript.txt', lambda b: b + b'extra line\n')
        tamper('segments.json', lambda b: b.replace(b'"endMs": 2500', b'"endMs": 2501'))
        tamper('segments.json', lambda b: b.replace(b'"accuracyCertified": false', b'"accuracyCertified": true'))
        tamper('segments.json', lambda b: json.dumps(json.loads(b)).encode())          # non-canonical bytes
        tamper('native.json', lambda b: b.replace(b'2500', b'2400'), ('VERIFICATION_FAILED',))
        tamper('native.json', lambda b: b.replace(b'"language": "en"', b'"language": "fr"', 1), ('VERIFICATION_FAILED',))
        tamper('native.srt', lambda b: b.replace(b'country', b'county'))
        tamper('captured-audio.wav', lambda b: b[:100] + bytes([b[100] ^ 1]) + b[101:])
        tamper('model.json', lambda b: b.replace(b'"sha256"', b'"sha257"'))
        tamper('runtime.json', lambda b: b.replace(b'libm.so.6', b'libother.so.6'))
        tamper('runtime.json', lambda b: b.replace(b'"sha256": "', b'"sha256": "0', 1))
        tamper('libraries.stdout', lambda b: b.replace(b'libz.so.1', b'libq.so.1'))
        tamper('version.stdout', lambda b: b'whisper.cpp version: 1.9.4\n')
        tamper('transcribe-launcher.py', lambda b: b.replace(b'-ng', b'-xx'))
        tamper('transcribe-inputs.json', lambda b: b.replace(b'"bytes": 5000', b'"bytes": 4999'))
        tamper('transcribe-submission.json', lambda b: b.replace(b'"exitCode": 0', b'"exitCode": 1'))
        # Receipt-level forgeries with every ordinary hash refreshed.
        for name, mutation in (('extra claim', lambda r:r.update(accuracyCertified=True)), ('missing evidence', lambda r: r['evidence'].pop('native.json')), ('extra evidence', lambda r: r['evidence'].update({'extra.json': '0' * 64})),
                               ('publication membership', lambda r: r['artifacts'].pop()), ('runtime identity', lambda r: r.update(runtime='whisper.cpp 1.9.4')),
                               ('executable identity', lambda r: r.update(executable='relative/whisper-cli'))):
            try:
                receipt = a.read(directory, 'verification.json');mutation(receipt);a.atomic_json(directory / 'verification.json', receipt)
                self.refuse(lambda: a.verify(directory), 'VERIFICATION_FAILED')
            finally: restore()
        try:
            for name in ('stray.txt','orphan.metadata.json'):
                (directory / name).write_text('unexpected');self.refuse(lambda: a.verify(directory), 'VERIFICATION_FAILED');(directory / name).unlink()
        finally: restore()
        try:
            (directory / 'captions.srt').unlink();self.refuse(lambda: a.verify(directory), 'VERIFICATION_FAILED')
        finally: restore()
        self.assertTrue(a.verify(directory)['verified'])

    def test_audio_binding_is_a_pin_not_the_path(self):
        self.run_job('first');self.audio.write_bytes(wav(176000, rate=16000)[:-2] + b'\x01\x00')
        # The retained capture is authoritative; a changed original does not alter prior verification.
        self.assertTrue(a.verify(self.dir / 'first')['verified'])
        self.assertNotEqual(a.reusableInputs({**self.document, 'audio': {'path': str(self.audio)}})['audio'], self.document['audio']['sha256'])

    def test_cancellation_and_deadline_precede_native_work(self):
        cancelled = threading.Event();cancelled.set()
        with allocation({'threads': 1, 'ranks': 1}, cancelled):
            self.refuse(lambda: self.run_job('cancelled'), 'RUNNER_CANCELLED')
        self.assertFalse((self.dir / 'cancelled' / 'captured-audio.wav').exists())
        self.refuse(lambda: a.run(self.document, self.dir / 'late', executable=str(self.exe), timeout=1e-9), 'RUNNER_TIMED_OUT')

    def test_inflight_timeout_terminates_the_native_process(self):
        marker = self.dir / 'native.pid';self.setup_config(sleep=30, marker=str(marker))
        self.refuse(lambda: self.run_job('slow', timeout=2), 'RUNNER_TIMED_OUT')
        pid = int(marker.read_text())
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)


    # ---- optional caption review -------------------------------------------------

    def review_job(self, name='review', **options):
        self.document['captionReview'] = True
        try: return self.run_job(name, **options)
        finally: del self.document['captionReview']

    def refresh_review(self, directory):
        """Refresh every ordinary hash for whatever publications the retained plan names."""
        plan = a.read(directory, 'plan.json');names = [n for n in ('segments.json', 'transcript.txt', 'captions.srt', 'captions.vtt', *(['caption-review.json'] if plan.get('captionReview') is True else [])) if (directory / n).exists()]
        receipt = a.read(directory, 'verification.json');receipt['artifacts'] = [{'file': str(directory / n), 'kind': 'file' if n.startswith('captions.') else 'text', 'sha256': a.digest(directory, n)} for n in names]
        receipt['evidence'] = {n: a.digest(directory, n) for n in receipt['evidence']};a.atomic_json(directory / 'verification.json', receipt)
        from schemaxis.publication_metadata import finalise
        finalise(directory)

    def test_option_absent_or_false_keeps_the_exact_four_publication_run(self):
        for name, setting in (('absent', None), ('false', False)):
            if setting is not None: self.document['captionReview'] = setting
            result = self.run_job(name);directory = self.dir / name
            self.assertEqual(set(result), {'verified', 'artifacts', 'runtime', 'segments', 'audioDurationMs', 'audioSha256', 'modelSha256', 'accuracyCertified', 'humanReviewRequired', 'status'})
            self.assertEqual(result['artifacts'], 4);self.assertFalse((directory / 'caption-review.json').exists())
            self.assertEqual([Path(x['file']).name for x in a.read(directory, 'verification.json')['artifacts']], ['segments.json', 'transcript.txt', 'captions.srt', 'captions.vtt'])
            self.assertEqual(('captionReview' in a.read(directory, 'plan.json')), setting is not None)
            self.assertEqual(a.read(directory, 'plan.json')['losses'], a.LOSSES)
            self.assertEqual(a.verify(directory), {k: v for k, v in result.items() if k != 'status'})
        self.assertEqual(a.read(self.dir / 'absent', 'authored.json').get('captionReview'), None)

    def test_effective_plan_boolean_cannot_be_forged_as_an_integer(self):
        self.review_job();directory = self.dir / 'review'
        plan = a.read(directory, 'plan.json');plan['captionReview'] = 1
        a.atomic_json(directory / 'plan.json', plan)
        receipt = a.read(directory, 'verification.json')
        receipt['evidence'] = {n: a.digest(directory, n) for n in receipt['evidence']}
        a.atomic_json(directory / 'verification.json', receipt)
        from schemaxis.publication_metadata import finalise
        finalise(directory)
        fault = self.refuse(lambda: a.verify(directory), 'VERIFICATION_FAILED')
        self.assertEqual(fault.message, 'effective transcription plan differs')

    def test_review_run_adds_only_the_report_and_never_alters_words_or_timing(self):
        plain = self.run_job('plain');reviewed = self.review_job('review')
        base, directory = self.dir / 'plain', self.dir / 'review'
        for name in ('segments.json', 'transcript.txt', 'captions.srt', 'captions.vtt', 'native.json', 'native.srt', 'captured-audio.wav', 'model.json'):
            self.assertEqual((base / name).read_bytes(), (directory / name).read_bytes(), name)
        self.assertEqual(a.commands('/x/whisper-cli', a.read(base, 'plan.json')), a.commands('/x/whisper-cli', a.read(directory, 'plan.json')))
        self.assertEqual(reviewed['artifacts'], 5);self.assertTrue(a.verify(directory)['verified'])
        self.assertEqual({k: v for k, v in reviewed.items() if k not in ('artifacts', 'captionReview')}, {k: v for k, v in plain.items() if k != 'artifacts'})
        self.assertEqual(reviewed['captionReview'], {'cues': 2, 'flaggedCues': 2, 'flagCounts': {'short-duration': 0, 'long-duration': 1, 'dense-text': 1}})
        self.assertEqual([Path(x['file']).name for x in a.read(directory, 'verification.json')['artifacts']], ['segments.json', 'transcript.txt', 'captions.srt', 'captions.vtt', 'caption-review.json'])
        self.assertTrue((directory / 'caption-review.json.metadata.json').is_file())
        report = json.loads((directory / 'caption-review.json').read_text())
        self.assertEqual(report['segmentsSha256'], hashlib.sha256((directory / 'segments.json').read_bytes()).hexdigest())
        self.assertEqual([{k: c[k] for k in ('index', 'startMs', 'endMs', 'durationMs', 'codePoints', 'codePointsPerSecondMilli', 'flags')} for c in report['cues']],
                         [{'index': 0, 'startMs': 0, 'endMs': 2500, 'durationMs': 2500, 'codePoints': 69, 'codePointsPerSecondMilli': 27600, 'flags': ['dense-text']},
                          {'index': 1, 'startMs': 2600, 'endMs': 11000, 'durationMs': 8400, 'codePoints': 20, 'codePointsPerSecondMilli': 2380, 'flags': ['long-duration']}])
        self.assertEqual(len(SPEECH), 69)
        self.assertFalse(report['review']['passCertified']);self.assertTrue(report['review']['humanReviewRequired'])
        self.assertEqual((directory / 'caption-review.json').read_bytes(), a.encode_json(report))
        self.audio.unlink();self.model.unlink()
        self.assertTrue(a.verify(directory)['verified'])        # reopening needs neither original

    def test_review_with_no_flags_still_demands_human_review(self):
        self.setup_config(native=native([(0, 3000, 'Fine words.'), (3000, 6000, 'More words.')]))
        result = self.review_job('quiet')
        self.assertEqual(result['captionReview']['flaggedCues'], 0);self.assertTrue(result['humanReviewRequired']);self.assertFalse(result['accuracyCertified'])
        report = json.loads((self.dir / 'quiet' / 'caption-review.json').read_text())
        self.assertEqual([c['flags'] for c in report['cues']], [[], []]);self.assertFalse(report['review']['passCertified']);self.assertTrue(report['review']['humanReviewRequired'])
        self.assertNotIn('pass', {k for k in result if result[k] is True})

    def test_review_report_tampering_with_refreshed_hashes_is_rejected(self):
        self.review_job();directory = self.dir / 'review';saved = {p: p.read_bytes() for p in directory.iterdir() if p.is_file()}
        def restore():
            for path in [p for p in directory.iterdir() if p.is_file() and p not in saved]: path.unlink()
            for path, data in saved.items(): path.write_bytes(data)
        def edit(f):
            def mutate(b):
                value = json.loads(b);f(value);return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b'\n'
            return mutate
        raw = {'durationMs': lambda r: r['cues'][1].update(durationMs=8399), 'codePoints': lambda r: r['cues'][0].update(codePoints=20), 'rate': lambda r: r['cues'][0].update(codePointsPerSecondMilli=1),
               'flagRemoved': lambda r: r['cues'][0].update(flags=[]), 'flagAdded': lambda r: r['cues'][1].update(flags=['short-duration', 'long-duration']), 'flagCounts': lambda r: r['flagCounts'].update(**{'dense-text': 0}),
               'cueCount': lambda r: r.update(cueCount=1), 'cueRemoved': lambda r: r['cues'].pop(), 'cuesReordered': lambda r: r['cues'].reverse(), 'segmentsHash': lambda r: r.update(segmentsSha256='0' * 64),
               'threshold': lambda r: r['policy'].update(longDurationAboveMs=9000), 'passClaim': lambda r: r['review'].update(passCertified=True), 'humanReviewDropped': lambda r: r['review'].update(humanReviewRequired=False),
               'accessibilityClaim': lambda r: r['review'].update(accessibilityCertified=True), 'unknownRoot': lambda r: r.update(verdict='good'), 'unknownCue': lambda r: r['cues'][0].update(severity=3),
               'unknownReview': lambda r: r['review'].update(approvedBy='me'), 'missingMember': lambda r: r.pop('flagCounts'), 'boolAsInt': lambda r: r['review'].update(passCertified=0),
               'floatMetric': lambda r: r['cues'][0].update(endMs=2500.0), 'stringMetric': lambda r: r['cues'][0].update(codePoints='69'), 'trueAsMetric': lambda r: r['cues'][0].update(startMs=False)}
        for name, f in raw.items():
            with self.subTest(name):
                path = directory / 'caption-review.json'
                try:
                    path.write_bytes(edit(f)(path.read_bytes()));self.refresh_review(directory)
                    self.assertEqual(self.refuse(lambda: a.verify(directory)).code, 'VERIFICATION_FAILED')
                finally: restore()
        byte_level = {'nonCanonicalSpacing': lambda b: json.dumps(json.loads(b)).encode(), 'trailingNewlineRemoved': lambda b: b.rstrip(b'\n'), 'emptyFile': lambda b: b'', 'notJson': lambda b: b'not json',
                      'duplicateKey': lambda b: b.replace(b'{\n', b'{\n  "cueCount": 2,\n', 1), 'byteOrderMark': lambda b: b'\xef\xbb\xbf' + b, 'nan': lambda b: b.replace(b'"cueCount": 2', b'"cueCount": NaN'),
                      'oversize': lambda b: b + b' ' * (a.JSON_LIMIT + 1), 'array': lambda b: b'[]'}
        for name, mutate in byte_level.items():
            with self.subTest(name):
                path = directory / 'caption-review.json'
                try:
                    path.write_bytes(mutate(path.read_bytes()));self.refresh_review(directory) if name != 'oversize' else None
                    self.assertEqual(self.refuse(lambda: a.verify(directory)).code, 'VERIFICATION_FAILED')
                except SchemaxisError as error:
                    self.assertEqual(error.fault.code, 'VERIFICATION_FAILED')    # refreshing may itself refuse a malformed publication
                finally: restore()
        # Unrefreshed edits and result/receipt forgeries.
        path = directory / 'caption-review.json'
        try:
            path.write_bytes(path.read_bytes().replace(b'"long-duration"', b'"short-duration"', 1));self.refuse(lambda: a.verify(directory), 'VERIFICATION_FAILED')
        finally: restore()
        for name, mutate in (('summary', lambda r: r['captionReview'].update(flaggedCues=0)), ('summaryDropped', lambda r: r.pop('captionReview')), ('artifactCount', lambda r: r.update(artifacts=4)),
                             ('summaryVerdict', lambda r: r['captionReview'].update(passed=True)), ('summaryFloat', lambda r: r['captionReview'].update(cues=2.0))):
            try:
                result = a.read(directory, 'result.json');mutate(result);a.atomic_json(directory / 'result.json', result)
                self.refuse(lambda: a.verify(directory), 'VERIFICATION_FAILED')
            finally: restore()
        for name, mutate in (('artifactDropped', lambda r: r['artifacts'].pop()), ('artifactDigest', lambda r: r['artifacts'][-1].update(sha256='0' * 64)), ('artifactKind', lambda r: r['artifacts'][-1].update(kind='file'))):
            try:
                receipt = a.read(directory, 'verification.json');mutate(receipt);a.atomic_json(directory / 'verification.json', receipt)
                self.refuse(lambda: a.verify(directory), 'VERIFICATION_FAILED')
            finally: restore()
        self.assertTrue(a.verify(directory)['verified'])

    def test_report_membership_must_match_the_authored_option_exactly(self):
        self.review_job('review');self.run_job('plain')
        review, plain = self.dir / 'review', self.dir / 'plain'
        # A stray report in a run without the option, with and without refreshed hashes and metadata.
        (plain / 'caption-review.json').write_bytes((review / 'caption-review.json').read_bytes())
        self.refuse(lambda: a.verify(plain), 'VERIFICATION_FAILED');self.refresh_review(plain)
        self.refuse(lambda: a.verify(plain), 'VERIFICATION_FAILED')
        (plain / 'caption-review.json').unlink();(plain / 'caption-review.json.metadata.json').unlink(missing_ok=True)
        self.refresh_review(plain)
        self.assertTrue(a.verify(plain)['verified'])
        # Missing report in a run that asked for it.
        saved = (review / 'caption-review.json').read_bytes()
        (review / 'caption-review.json').unlink();self.refuse(lambda: a.verify(review), 'VERIFICATION_FAILED')
        self.refresh_review(review);self.refuse(lambda: a.verify(review), 'VERIFICATION_FAILED')
        (review / 'caption-review.json').write_bytes(saved);self.refresh_review(review)
        self.assertTrue(a.verify(review)['verified'])
        # The authored and effective plans cannot silently drop or add the option, even with every digest refreshed.
        for directory, change in ((review, False), (plain, True)):
            files = {n: (directory / n).read_bytes() for n in ('authored.json', 'plan.json')}
            try:
                authored = json.loads(files['authored.json']);authored['captionReview'] = change
                a.atomic_json(directory / 'authored.json', authored);a.atomic_json(directory / 'plan.json', a.plan(authored))   # internally consistent forgery
                self.refresh_review(directory)
                fault = self.refuse(lambda: a.verify(directory), 'VERIFICATION_FAILED')
                self.assertNotEqual(fault.message, 'effective transcription plan differs')
            finally:
                for n, data in files.items(): (directory / n).write_bytes(data)
                self.refresh_review(directory)
        self.assertTrue(a.verify(review)['verified']);self.assertTrue(a.verify(plain)['verified'])

    def test_review_skips_work_after_a_native_contract_violation(self):
        self.setup_config(native=native([(0, 12000, 'beyond the recording')]))
        self.refuse(lambda: self.review_job('late'), 'TRANSCRIPT_TIMING')
        self.assertFalse((self.dir / 'late' / 'caption-review.json').exists())
        self.assertEqual(json.loads((self.dir / 'late' / 'result.json').read_text())['status'], 'failed')


class WhisperQualifierOwnership(unittest.TestCase):
    def test_existing_staging_and_model_are_never_replaced_or_deleted(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('whisper_qualifier',ROOT/'tools/qualify_whispercpp.py')
        q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);q.STAGING=root/'existing';q.STAGING.mkdir(mode=0o700)
            sample=root/'source.wav';sample.write_bytes(b'sample')
            model=q.STAGING/'ggml-base.en.bin';model.write_bytes(b'owned-model')
            q.SAMPLE_SHA256=hashlib.sha256(sample.read_bytes()).hexdigest()
            q.MODEL_SHA256=hashlib.sha256(model.read_bytes()).hexdigest()
            link=q.STAGING/'jfk.wav';link.symlink_to(sample)
            with self.assertRaises(SystemExit):q.stage(sample,model)
            q.unstage()
            self.assertTrue(link.is_symlink());self.assertEqual(sample.read_bytes(),b'sample')
            self.assertEqual(model.read_bytes(),b'owned-model')


if __name__ == '__main__':
    unittest.main()
