"""Peak headroom `normalise`: exact gain, refusals before SoX, every-sample verification and forgery checks.

Native SoX 14.4.2 behaviour is established by tools/qualify_sox_normalise.py. Host tests
stand in for it with an analytic stdlib stub (host plumbing only: it proves nothing about
native behaviour). The expected samples below come from integer arithmetic written here,
not from the adaptor. Every tamper probe refreshes ordinary digests, so only the semantic
contract can reject it."""
import copy
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from fractions import Fraction

from test_sox import data, fmt, pad, riff, wav

from schemaxis.adaptors.sox import adaptor as a
from schemaxis.adaptors.sox import capabilities, conform, normalise
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise

ROOT = Path(__file__).resolve().parents[2]

FAKE_NORMALISE = """#!%(python)s
import math,struct,sys,wave
from pathlib import Path
a=sys.argv
if a[1:]==['--version']:
    print(a[0]+':      SoX v14.4.2');raise SystemExit
here=Path(a[0]).parent
mode=(here/'mode').read_text() if (here/'mode').exists() else 'good'
(here/'launched').write_text('1')
assert a[13]=='vol' and len(a)==15,a
with wave.open(a[5],'rb') as w:
    channels,rate,n=w.getnchannels(),w.getframerate(),w.getnframes();raw=list(struct.unpack('<'+'h'*(n*channels),w.readframes(n)))
g=float(a[14])
if mode=='ignoretarget': g=1.0
if mode=='slightly-wrong': g*=1.001
out=[max(-32768,min(32767,int(math.floor(v*g+.5)))) for v in raw]
if mode=='off1': out[len(out)//2]+=1 if out[len(out)//2]<32767 else -1
if mode=='short': out=out[:-channels]
if mode=='long': out=out+out[-channels:]
if mode=='invert': out=[-v for v in out]
if mode=='swap' and channels==2: out[0::2],out[1::2]=out[1::2],out[0::2]
if mode=='clip': out=[max(-32768,min(32767,v*2)) for v in out]
rate_out=2*rate if mode=='rate' else rate
with wave.open(a[12],'wb') as w:
    w.setparams((1 if mode=='mono' else channels,2,rate_out,0,'NONE','not compressed'));w.writeframes(struct.pack('<'+'h'*len(out),*out))
if mode=='noise': sys.stderr.write(a[0]+' WARN vol: vol clipped 3 samples; decrease volume?\\n')
if mode=='stdout': print('hello')
"""


def nearest(sample, target, peak):
    """Independent integer oracle: round-half-up of sample*target/peak."""
    return (2 * sample * target + peak) // (2 * peak)


def tone(frames, channels=1, amplitude=9000, extras=()):
    values = [int(amplitude * math.sin(0.37 * i + c)) for i in range(frames) for c in range(channels)]
    for index, value in extras: values[index] = value
    return values


class NormalisePlan(unittest.TestCase):
    def doc(self, **update):
        return {'version': a.VERSION, 'operation': 'normalise', 'source': '/recording.wav', 'targetPeak': 20000, 'maxGain': 4, **update}

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught: action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def test_plan_is_immutable_deterministic_and_does_no_file_io(self):
        d = self.doc();before = copy.deepcopy(d);p = a.plan(d)
        self.assertEqual(d, before);self.assertEqual(p, a.plan(d));self.assertEqual(a.query(d), (['normalise'], {}))
        self.assertEqual(p['target'], {'peakPCM16': 20000, 'encoding': 'signed-integer', 'bits': 16});self.assertEqual(p['losses'], normalise.LOSSES)
        self.assertEqual((p['targetPeak'], p['maxGain'], p['source']), (20000, 4, '/recording.wav'));self.assertEqual(a.resources(d, {}, 'id'), {'threads': 1})
        self.assertEqual(a.plan(self.doc(maxGain=4.0))['maxGain'], 4.0)    # the authored number is kept as written

    def test_old_code_would_refuse_the_operation_and_losses_state_the_limits(self):
        text = ' '.join(normalise.LOSSES)
        for phrase in ('not decibels', 'before SoX starts', 'never capped', 'noise floor', 'one common gain', '-32768', 'not RMS or loudness normalisation', 'authenticity'):
            self.assertIn(phrase.lower(), text.lower().replace('one common gain', 'one common gain'))
        self.assertIn('select assemble, conform, normalise or mix', self.fault(lambda: a.plan({'version': a.VERSION, 'operation': 'duck'}), 'UNKNOWN_FILTER').message)

    def test_target_and_ceiling_are_required_typed_and_bounded(self):
        for name in ('targetPeak', 'maxGain'):
            d = self.doc();del d[name];fault = self.fault(lambda: a.plan(d), 'MISSING_ARGUMENT');self.assertEqual(fault.location, '$.arguments.' + name)
        for value in (0, -1, 32768, 40000, 2 ** 40, 1.0, 20000.0, 0.9, True, False, '20000', None, [20000], {'peak': 1}, -3.0):
            with self.subTest(targetPeak=value):self.assertEqual(self.fault(lambda: a.plan(self.doc(targetPeak=value)), 'INVALID_ARGUMENT').location, '$.arguments.targetPeak')
        for value in (0, 0.999, -1, 16.0001, 17, 100, float('inf'), float('-inf'), float('nan'), True, False, '4', None, [4], 0.0):
            with self.subTest(maxGain=value):self.assertEqual(self.fault(lambda: a.plan(self.doc(maxGain=value)), 'INVALID_ARGUMENT').location, '$.arguments.maxGain')
        for target in (1, 2, 32766, 32767):self.assertEqual(a.plan(self.doc(targetPeak=target))['targetPeak'], target)
        for ceiling in (1, 1.0, 1.5, 15.999999, 16, 16.0):self.assertEqual(a.plan(self.doc(maxGain=ceiling))['maxGain'], ceiling)

    def test_source_and_closed_keys(self):
        for source in ('relative.wav', 'https://example.org/a.wav', '/recording.mp3', '/recording'):
            self.assertEqual(self.fault(lambda: a.plan(self.doc(source=source)), 'INVALID_AUDIO_SOURCE').location, '$.source')
        for extra in ({'clips': []}, {'channelPolicy': 'left'}, {'gain': 1}, {'decibels': -3}, {'limiter': True}, {'dither': True}, {'targetRate': 8000}, {'command': 'x'}, {'loudness': -16}, {'lufs': -16}):
            self.fault(lambda: a.plan(self.doc(**extra)), 'UNKNOWN_ARGUMENT')
        for operation in ('conform', 'assemble'):
            d = {'version': a.VERSION, 'operation': operation, 'source': '/a.wav', 'targetPeak': 100, 'maxGain': 2, 'channelPolicy': 'left', 'clips': [{'source': '/a.wav', 'frameCount': 1}]}
            d = {k: v for k, v in d.items() if not (operation == 'conform' and k in ('targetPeak', 'maxGain', 'clips')) and not (operation == 'assemble' and k != 'clips' and k not in ('version', 'operation'))}
            self.assertEqual(a.plan(d)['operation'], operation)
        self.fault(lambda: a.plan({'version': a.VERSION, 'operation': 'conform', 'source': '/a.wav', 'channelPolicy': 'left', 'targetPeak': 100}), 'UNKNOWN_ARGUMENT')
        self.fault(lambda: a.plan({'version': a.VERSION, 'operation': 'assemble', 'clips': [{'source': '/a.wav', 'frameCount': 1}], 'maxGain': 2}), 'UNKNOWN_ARGUMENT')
        self.fault(lambda: a.plan({'version': 'schemaxis.sox/2', 'operation': 'normalise'}), 'UNSUPPORTED_VERSION')

    def test_schema_has_one_closed_branch_for_the_operation(self):
        schema = a.schema();assemble, speech, headroom, _overlay = schema['oneOf']
        self.assertEqual(headroom['required'], ['version', 'operation', 'source', 'targetPeak', 'maxGain']);self.assertFalse(headroom['additionalProperties'])
        self.assertEqual(headroom['properties']['operation'], {'const': 'normalise'})
        self.assertEqual(headroom['properties']['targetPeak'], {'type': 'integer', 'minimum': 1, 'maximum': 32767})
        self.assertEqual(headroom['properties']['maxGain'], {'type': 'number', 'minimum': 1, 'maximum': 16})
        self.assertEqual(set(headroom['properties']), {'version', 'operation', 'source', 'targetPeak', 'maxGain'})
        self.assertEqual(schema['properties']['operation'], {'enum': ['assemble', 'conform', 'normalise', 'mix']})
        self.assertEqual(speech['properties']['operation'], {'const': 'conform'});self.assertEqual(assemble['properties']['operation'], {'const': 'assemble'})

    def test_examples_are_valid_and_the_invalid_one_is_refused_at_the_field(self):
        for name in ('boost', 'attenuate', 'negative-fullscale'):
            d = json.loads((ROOT / f'examples/schemaxis/sox-normalise-{name}.json').read_text());self.assertEqual(a.plan(d)['operation'], 'normalise')
        d = json.loads((ROOT / 'examples/schemaxis/sox-normalise-invalid-target.json').read_text())
        self.assertEqual(self.fault(lambda: a.plan(d), 'INVALID_ARGUMENT').location, '$.arguments.targetPeak')
        workflow = json.loads((ROOT / 'examples/schemaxis/sox-normalise-flac-workflow.json').read_text())
        self.assertEqual([o['document']['operation'] for o in workflow['operations']], ['normalise', 'encodeLossless'])

    def test_discovery_boost_example_matches_the_example_and_is_feasible_on_its_fixture(self):
        boost = json.loads((ROOT / 'examples/schemaxis/sox-normalise-boost.json').read_text())
        peak = max(map(abs, a.pcm((ROOT / 'examples/schemaxis/sox-normalise-fixtures/quiet-stereo16k.wav').read_bytes())[1]))
        gain = Fraction(boost['targetPeak'], peak);self.assertEqual((boost['targetPeak'], boost['maxGain'], peak, gain), (20000, 8, 3000, Fraction(20, 3)))
        self.assertLessEqual(gain, normalise.ceiling(boost['maxGain']))
        entry = {x['reference']: x['purpose'] for x in capabilities.catalogue()['operations']['normalise']['examples']}['examples/schemaxis/sox-normalise-boost.json']
        self.assertIn(f"peak of {boost['targetPeak']}", entry);self.assertIn(f"maxGain of {boost['maxGain']}", entry);self.assertIn(f'exact gain {gain.numerator}/{gain.denominator}', entry)


class NormaliseDecision(unittest.TestCase):
    """Peak, exact gain and the refusals that happen before any native process."""
    def plan(self, **update):
        return a.plan({'version': a.VERSION, 'operation': 'normalise', 'source': '/recording.wav', 'targetPeak': 20000, 'maxGain': 4, **update})

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught: action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def decide(self, values, channels=1, **update):
        p = self.plan(**update)
        info, start, size, _ = conform.info_of(wav(values, channels, 8000))
        return normalise.decide(p, normalise.scan(wav(values, channels, 8000), start, size, channels))

    def test_peak_is_the_largest_magnitude_over_every_channel(self):
        self.assertEqual(self.decide([100, 200, -50, 300, 10, -400], 2, targetPeak=800), (400, Fraction(2)))
        self.assertEqual(self.decide([100, -9000, 50, 7000], 2, targetPeak=18000), (9000, Fraction(2)))
        self.assertEqual(self.decide([5, -5, 5], 1, targetPeak=5, maxGain=1), (5, Fraction(1)))

    def test_exact_gain_is_a_reduced_fraction_of_integers(self):
        peak, gain = self.decide([3000, -1500, 7], 1, targetPeak=20000, maxGain=8)
        self.assertEqual((peak, gain, (gain.numerator, gain.denominator)), (3000, Fraction(20, 3), (20, 3)))
        peak, gain = self.decide([30000, 1], 1, targetPeak=16384, maxGain=1)
        self.assertEqual((gain.numerator, gain.denominator), (1024, 1875))
        self.assertEqual(normalise.native_gain(Fraction(20, 3)), '6.666666666666667');self.assertEqual(normalise.native_gain(Fraction(1)), '1')
        self.assertEqual(float(normalise.native_gain(Fraction(32767, 32768))), 32767 / 32768)

    def test_negative_full_scale_has_peak_32768_and_is_always_attenuated(self):
        peak, gain = self.decide([-32768, 100, 32767], 1, targetPeak=32767, maxGain=1)
        self.assertEqual((peak, gain), (32768, Fraction(32767, 32768)))
        for target in (1, 1000, 32766, 32767): self.assertLess(self.decide([-32768, 0], 1, targetPeak=target, maxGain=1)[1], 1)
        self.assertEqual(self.decide([32767, -32767], 1, targetPeak=32767, maxGain=1), (32767, Fraction(1)))

    def test_silence_is_refused(self):
        fault = self.fault(lambda: self.decide([0] * 40, 2), 'AUDIO_SILENT_SOURCE');self.assertEqual(fault.location, '$.source')

    def test_boost_above_maxgain_is_refused_and_the_boundary_is_accepted(self):
        self.assertEqual(self.decide([2000, -3], 1, targetPeak=32000, maxGain=16)[1], Fraction(16))      # exactly at the ceiling
        fault = self.fault(lambda: self.decide([1999, -3], 1, targetPeak=32000, maxGain=16), 'AUDIO_GAIN_LIMIT')
        self.assertEqual(fault.location, '$.maxGain');self.assertEqual(fault.observed['measuredPeak'], 1999);self.assertEqual(fault.observed['requiredGain'], '32000/1999')
        self.assertIn('lower targetPeak', fault.message)
        self.fault(lambda: self.decide([999], 1, targetPeak=1000, maxGain=1), 'AUDIO_GAIN_LIMIT')
        self.assertEqual(self.decide([1000], 1, targetPeak=1000, maxGain=1)[1], 1);self.assertEqual(self.decide([2000], 1, targetPeak=1000, maxGain=1)[1], Fraction(1, 2))
        self.assertEqual(self.decide([1000], 1, targetPeak=1500, maxGain=1.5)[1], Fraction(3, 2))       # 1.5 is exact in binary and decimal
        self.fault(lambda: self.decide([1000], 1, targetPeak=1501, maxGain=1.5), 'AUDIO_GAIN_LIMIT')
        # maxGain is the exact fraction of the parsed number's shortest round-trip decimal (Fraction(str(value))), not of the binary float
        self.assertEqual(self.decide([10], 1, targetPeak=11, maxGain=1.1)[1], Fraction(11, 10))
        self.fault(lambda: self.decide([10], 1, targetPeak=11, maxGain=1.0999999999999999), 'AUDIO_GAIN_LIMIT')

    def test_decimal_ceiling_is_the_declared_decimal_not_its_binary_float(self):
        # Fraction(6.6) is the binary float just below 33/5, so a binary comparison refused this ordinary inclusive case.
        self.assertLess(Fraction(6.6), Fraction(33, 5))
        self.assertEqual(self.decide([5, -3], 1, targetPeak=33, maxGain=6.6), (5, Fraction(33, 5)))
        self.assertEqual(self.decide([5, -3], 1, targetPeak=33, maxGain=6.6000000000000005)[1], Fraction(33, 5))
        # just below the ceiling, whether by a larger target or by a ceiling one float step under 6.6, is still refused
        fault = self.fault(lambda: self.decide([5], 1, targetPeak=34, maxGain=6.6), 'AUDIO_GAIN_LIMIT');self.assertEqual(fault.observed['requiredGain'], '34/5')
        below = math.nextafter(6.6, 0);self.assertEqual(repr(below), '6.599999999999999')
        self.fault(lambda: self.decide([5], 1, targetPeak=33, maxGain=below), 'AUDIO_GAIN_LIMIT')
        # the same declared value as an integer or a trailing-zero float is the same number
        self.assertEqual(self.decide([10], 1, targetPeak=160, maxGain=16)[1], 16);self.assertEqual(self.decide([10], 1, targetPeak=160, maxGain=16.0)[1], 16)
        for text, peak, target in (('2.2', 10, 22), ('3.3', 10, 33), ('4.35', 20, 87), ('7.7', 10, 77), ('12.1', 10, 121), ('1.15', 20, 23), ('9.9', 10, 99)):
            with self.subTest(maxGain=text):
                ceiling = float(text);self.assertEqual(normalise.decide(self.plan(targetPeak=target, maxGain=ceiling), {peak})[1], Fraction(target, peak))
                self.fault(lambda: normalise.decide(self.plan(targetPeak=target, maxGain=math.nextafter(ceiling, 0)), {peak}), 'AUDIO_GAIN_LIMIT')
                self.assertEqual(normalise.ceiling(ceiling), Fraction(text))

    def test_json_literal_is_rounded_to_a_double_before_the_decimal_comparison(self):
        # JSON parsing rounds the written literal to a double first, so extra digits beyond a double are not preserved:
        # the literal below 6.6 by 1e-23 parses to the double 6.6 and is compared as 33/5, while the next smaller double is refused.
        parsed = json.loads('{"maxGain":6.59999999999999999999999}')['maxGain']
        self.assertEqual(parsed, 6.6);self.assertEqual(repr(parsed), '6.6');self.assertEqual(normalise.ceiling(parsed), Fraction(33, 5))
        self.assertGreater(Fraction('6.6'), Fraction('6.59999999999999999999999'))   # the written literal is exactly below 33/5
        self.assertEqual(self.decide([5, -3], 1, targetPeak=33, maxGain=parsed), (5, Fraction(33, 5)))
        below = json.loads('{"maxGain":6.599999999999999}')['maxGain'];self.assertEqual(below, math.nextafter(6.6, 0))
        fault = self.fault(lambda: self.decide([5], 1, targetPeak=33, maxGain=below), 'AUDIO_GAIN_LIMIT');self.assertEqual(fault.observed['requiredGain'], '33/5')
        self.assertIn('JSON parsing first rounds a literal with more digits than a double holds', ' '.join(normalise.LOSSES))   # the plan discloses the parse-time rounding

    def test_source_rules_use_the_conform_reader_before_decisions(self):
        p = self.plan();header = lambda rate, frames: riff(fmt(rate=rate), b'data' + struct.pack('<I', 2 * frames) + b'\0' * (2 * frames))
        loud = lambda rate, frames: riff(fmt(rate=rate), b'data' + struct.pack('<I', 2 * frames) + struct.pack('<h', 9000) * frames)
        self.assertEqual(a.normalise_source(p, loud(8000, 600 * 8000))['frames'], 4800000)
        self.fault(lambda: a.normalise_source(p, loud(8000, 600 * 8000 + 1)), 'AUDIO_RESOURCE_LIMIT')
        self.assertEqual(a.normalise_source(p, loud(192000, 1))['frames'], 1)                       # no minimum length: one frame is a recording
        self.fault(lambda: a.normalise_source(p, header(8000, 100)), 'AUDIO_SILENT_SOURCE')
        good = [100, -100, 200, -200]
        cases = {'24-bit': riff(fmt(bits=24, align=3), data(good)), 'float': riff(fmt(encoding=3), data(good)), 'extensible': riff(fmt(encoding=0xFFFE), data(good)),
                 'three channels': riff(fmt(channels=3, align=6), data(good * 3)), 'rate low': riff(fmt(rate=7999), data(good)), 'rate high': riff(fmt(rate=192001), data(good)),
                 'truncated': wav(good)[:-1], 'trailing': wav(good) + b'\0', 'empty': riff(fmt(), data([])), 'RF64': b'RF64' + wav(good)[4:], 'extra chunk': riff(fmt(), b'fact' + struct.pack('<II', 4, 4), data(good)),
                 'duplicate data': riff(fmt(), data(good), data(good)), 'nonzero pad': riff(fmt(), pad(b'LIST' + struct.pack('<I', 3) + b'abc')[:-1] + b'\1', data(good)), 'big endian': b'RIFX' + wav(good)[4:]}
        for name, value in cases.items():
            with self.subTest(name):self.assertEqual(self.fault(lambda: a.normalise_source(p, value), 'INVALID_AUDIO_DATA').location, '$.source')
        self.fault(lambda: conform.info_of(b'\0' * (conform.SOURCE_LIMIT + 1)), 'INVALID_AUDIO_DATA')
        self.assertEqual(a.normalise_source(self.plan(targetPeak=400), riff(pad(b'JUNK' + struct.pack('<I', 3) + b'abc'), fmt(), pad(b'LIST' + struct.pack('<I', 3) + b'abc'), data(good)))['frames'], 4)

    def test_regular_file_bounds_and_byte_reuse(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'clip.wav';path.write_bytes(wav([100, -100] * 4))
            d = {'version': a.VERSION, 'operation': 'normalise', 'source': str(path), 'targetPeak': 200, 'maxGain': 2}
            before = a.reusableInputs(d);path.write_bytes(wav([100, -101] * 4));self.assertNotEqual(before, a.reusableInputs(d));self.assertEqual(list(before), ['0'])
            path.write_bytes(wav([0] * 8));self.assertEqual(self.fault(lambda: a.reusableInputs(d), 'AUDIO_SILENT_SOURCE').location, '$.source')
            path.write_bytes(wav([1, -1] * 4));self.fault(lambda: a.reusableInputs(d), 'AUDIO_GAIN_LIMIT')
            link = Path(name) / 'link.wav';link.symlink_to(path);self.fault(lambda: a.bounded(link, 'INVALID_AUDIO_SOURCE'), 'INVALID_AUDIO_SOURCE')
            path.write_bytes(b'0' * (conform.SOURCE_LIMIT + 1));self.fault(lambda: a.reusableInputs(d), 'INVALID_AUDIO_SOURCE')

    def test_commands_are_fixed_and_carry_no_authored_text(self):
        p = self.plan(targetPeak=20000, maxGain=8)
        c = a.commands('/native/sox', p, '6.666666666666667')
        self.assertEqual(c['normalise'], ['/native/sox', '-D', '--single-threaded', '-t', 'wav', 'captured-0.wav', '-t', 'wav', '-e', 'signed-integer', '-b', '16', 'audio.wav', 'vol', '6.666666666666667'])
        self.assertEqual(c['version'], ['/native/sox', '--version']);self.assertEqual(list(c), ['version', 'normalise'])
        self.assertEqual(a.stage_inputs('normalise', p), ['captured-0.wav']);self.assertEqual(a.stage_inputs('version', p), [])
        text = a.launcher(Path('/run'), 'normalise', c['normalise'], p)
        self.assertIn(f'RLIMIT_FSIZE,({normalise.OUTPUT_LIMIT},{normalise.OUTPUT_LIMIT})', text);self.assertIn(str(normalise.SOURCE_LIMIT), text)
        self.assertIn('RLIMIT_CPU,(30,30)', text);self.assertIn('RLIMIT_AS,(536870912,536870912)', text)
        self.assertEqual(sorted(a.evidence_names(p)), sorted(['authored.json', 'plan.json', 'captures.json', 'captured-0.wav', *[s + x for s in ('version', 'normalise') for x in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr')]]))


class AssembleAndConformAreUnchanged(unittest.TestCase):
    """Fail-before pins of the earlier contracts, taken from the repository HEAD before normalise existed."""
    def h(self, value): return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def test_conform_plan_losses_commands_launchers_schema_and_declaration(self):
        d = {'version': a.VERSION, 'operation': 'conform', 'source': '/recording.wav', 'channelPolicy': 'average'};p = a.plan(d)
        self.assertEqual(self.h(p), 'ec740babe916887f8ec21982f431e5ccd00092c492bab5a0191f7d131935ec33')
        self.assertEqual(self.h(conform.LOSSES), 'f10be8bef2a5d6212b493896fe41d1518b2dc0c7f46af2a8345ac5d324b31f93');self.assertEqual(self.h(p['losses']), self.h(conform.LOSSES))
        c = a.commands('/native/sox', p);self.assertEqual(self.h(c), '7ed20c724ebcca80c11356c4b9ccc050acd4041ac9de263b5b29d0f76b9b0d9b')
        for stage, expected in (('version', 'a123f2c15d60d2eec62b45f25ad5daaeb6a8d1d20769412aff2d04e1556d8b40'), ('conform', 'a485858037bd585a56af7a14d471be007a6de9cce408beaba572467077af47c4')):
            self.assertEqual(hashlib.sha256(a.launcher(Path('/run'), stage, c[stage], p).encode()).hexdigest(), expected, stage)
        self.assertEqual(self.h(sorted(a.evidence_names(p))), '09b2c9d28731efb6aeace440ae855662af7464be0399508070896a96cfb95acd')
        self.assertEqual(self.h(a.DECLARATIONS['conform']), '91b562b1b9bfd6d1c1cd00a175b8d0aea18f5ac0c74955e9ff3f20e175fc72ed')
        for policy, expected in (('left', 'bf5e61eff6a70b8478b5d730f7a9e843e8cb874c2b1ff38b8f7f000d3e41c3cd'), ('right', 'd72a0c1f35f65011670339e9af2d2108728c7dbf0994c727ccd40a42c90fc691')):
            self.assertEqual(self.h(a.commands('/native/sox', a.plan({**d, 'channelPolicy': policy}))), expected)
        from schemaxis.schema import DRAFT
        self.assertEqual(self.h({'$schema': DRAFT, **a.schema()['oneOf'][1]}), '3011959cb0400fe0a4cf25e5a20ec2f0225e61855b175951e0aac80ae175269b')
        self.assertEqual(self.h({'$schema': DRAFT, **a.schema()['oneOf'][0]}), 'e1e2d351bf05d5f2700fccc095d198cbb30e6334fb6d97c68fce52e340ffe770')

    def test_assemble_and_conform_stage_names_membership_and_limits_are_not_shared_with_normalise(self):
        d = {'version': a.VERSION, 'operation': 'conform', 'source': '/recording.wav', 'channelPolicy': 'left'};p = a.plan(d)
        self.assertEqual(list(a.commands('/native/sox', p)), ['version', 'conform']);self.assertEqual(a.stage_inputs('normalise', p), [])
        self.assertIn('RLIMIT_FSIZE,(25165824,25165824)', a.launcher(Path('/run'), 'conform', a.commands('/native/sox', p)['conform'], p))
        e = json.loads((ROOT / 'examples/schemaxis/sox-assembly.json').read_text());q = a.plan(e)
        self.assertIn('RLIMIT_FSIZE,(8388608,8388608)', a.launcher(Path('/run'), 'clip-0', a.commands('/native/sox', q)['clip-0'], q))


class NormaliseRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory();cls.root = Path(cls.temporary.name)
        exe = cls.root / 'bin' / 'sox';exe.parent.mkdir();exe.write_text(FAKE_NORMALISE % {'python': sys.executable});exe.chmod(0o700);cls.exe = exe
        cls.counter = 0

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def setUp(self): self.mode('good')

    def mode(self, name):
        (self.exe.parent / 'mode').write_text(name);launched = self.exe.parent / 'launched'
        if launched.exists(): launched.unlink()

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught: action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def run_case(self, values, channels, target, ceiling, rate=8000, name=None):
        type(self).counter += 1
        source = self.root / f'source-{self.counter}.wav';source.write_bytes(wav(values, channels, rate))
        document = {'version': a.VERSION, 'operation': 'normalise', 'source': str(source), 'targetPeak': target, 'maxGain': ceiling}
        directory = self.root / (name or f'run-{self.counter}')
        return a.run(document, directory, executable=str(self.exe), timeout=60), directory

    def oracle(self, values, target):
        peak = max(abs(v) for v in values);return [nearest(v, target, peak) for v in values], peak

    def check_exact(self, values, channels, target, ceiling, rate=8000):
        result, directory = self.run_case(values, channels, target, ceiling, rate)
        expected, peak = self.oracle(values, target)
        info, actual = a.pcm((directory / 'audio.wav').read_bytes(), canonical=True)
        self.assertEqual(info, {'rate': rate, 'channels': channels, 'frames': len(values) // channels})
        self.assertEqual(actual, expected);self.assertEqual(max(abs(v) for v in actual), target)
        gain = Fraction(target, peak)
        self.assertEqual((result['gain']['numerator'], result['gain']['denominator']), (gain.numerator, gain.denominator))
        self.assertEqual((result['source']['peakPCM16'], result['peakPCM16'], result['samplesCompared']), (peak, target, len(values)))
        self.assertEqual(result['headroom'], {'inputPeakPCM16': peak, 'outputPeakPCM16': target, 'positiveHeadroomPCM16': 32767 - target, 'negativeHeadroomPCM16': 32768 - target})
        self.assertTrue(a.verify(directory)['verified'])
        return result, directory

    def test_literal_hand_computed_samples(self):
        """Gain 3/10: 1000->300, -1000->-300, 500->150, 1->0.3->0, -1->0, 333->99.9->100, -334->-100.2->-100, 17->5.1->5."""
        values = [1000, -1000, 500, 1, -1, 333, -334, 17]
        result, directory = self.run_case(values, 1, 300, 1)
        self.assertEqual(a.pcm((directory / 'audio.wav').read_bytes())[1], [300, -300, 150, 0, 0, 100, -100, 5])
        self.assertEqual(result['gain'], {'numerator': 3, 'denominator': 10, 'direction': 'attenuation', 'withinMaxGain': True})
        self.assertEqual((result['rate'], result['channels'], result['frames']), (8000, 1, 8))

    def test_mono_stereo_signed_extrema_small_odd_frames_and_directions(self):
        cases = {'stereo boost': (tone(500, 2, 3000, [(100, 3000), (301, -3000)]), 2, 20000, 8, 16000),
                 'mono attenuation': (tone(700, 1, 30000, [(5, 30000)]), 1, 16384, 1, 8000),
                 'positive peak unity': (tone(300, 1, 20000, [(7, 32767), (8, -20000)]), 1, 32767, 1, 44100),
                 'negative peak only': (tone(300, 1, 20000, [(9, -32768)]), 1, 32767, 1, 48000),
                 'negative peak stereo': (tone(300, 2, 10000, [(11, -32768), (12, 32767)]), 2, 32767, 1, 22050),
                 'both polarities at peak': ([700, -700, 3, -3, 0, 699], 1, 1400, 2, 192000),
                 'one frame mono': ([-1234], 1, 5000, 5, 8000), 'one frame stereo': ([1, -2], 2, 32, 16, 8000), 'three frames stereo': ([5, 1000, -7, 3, 0, -999], 2, 15000, 16, 11025),
                 'five frames mono': ([9, -8, 7, -6, 5], 1, 100, 16, 8000), 'unity small': ([4, -4, 1, 0], 1, 4, 1, 8000),
                 'maximum boost 16': ([2000, -1000, 7, 1999, -2000], 1, 32000, 16, 8000), 'tiny target 1': (tone(64, 1, 5000, [(3, 5000)]), 1, 1, 1, 8000),
                 'minimum gain edge': ([32767, -32768, 1, 0, -1] * 3, 1, 1, 1, 8000)}
        for name, (values, channels, target, ceiling, rate) in cases.items():
            with self.subTest(name): self.check_exact(values, channels, target, ceiling, rate)

    def test_decimal_ceiling_runs_end_to_end_and_reopens(self):
        """maxGain 6.6 with peak 5 and target 33 is the inclusive ceiling 33/5: planned, run, verified and reopened with the same decimal."""
        result, directory = self.check_exact([5, -3, 2, 1, -5, 4], 1, 33, 6.6)
        self.assertEqual((result['gain'], result['maxGain']), ({'numerator': 33, 'denominator': 5, 'direction': 'boost', 'withinMaxGain': True}, 6.6))
        self.assertEqual(a.pcm((directory / 'audio.wav').read_bytes())[1], [33, -20, 13, 7, -33, 26])
        self.assertEqual(json.loads((directory / 'authored.json').read_text())['maxGain'], 6.6)
        self.mode('good');below = math.nextafter(6.6, 0)
        with self.assertRaises(SchemaxisError) as caught: self.run_case([5, -3], 1, 33, below, name='below-decimal-ceiling')
        self.assertEqual(caught.exception.fault.code, 'AUDIO_GAIN_LIMIT');self.assertFalse((self.exe.parent / 'launched').exists())

    def test_directions_and_polarity_in_the_summary(self):
        boost, _ = self.check_exact([3000, -1500, 7, 0], 1, 20000, 8);self.assertEqual(boost['gain']['direction'], 'boost')
        self.assertEqual([w['code'] for w in boost['warnings']], ['NOISE_FLOOR_AMPLIFIED']);self.assertIn('20/3', boost['warnings'][0]['message'])
        attenuation, _ = self.check_exact([30000, -1500, 7, 0], 1, 16384, 1);self.assertEqual((attenuation['gain']['direction'], attenuation['warnings']), ('attenuation', []))
        unity, directory = self.check_exact([32767, -1500, 7, 0], 1, 32767, 1)
        self.assertEqual((unity['gain']['direction'], unity['warnings'], unity['maxErrorLSB']['numerator']), ('unity', [], 0))
        self.assertEqual(a.pcm((directory / 'audio.wav').read_bytes())[1], [32767, -1500, 7, 0])
        self.assertEqual(boost['source']['peakPolarity'], ['positive']);self.assertEqual(self.check_exact([-3000, 100], 1, 20000, 8)[0]['source']['peakPolarity'], ['negative'])
        both, _ = self.check_exact([700, -700, 5], 1, 1400, 2);self.assertEqual(both['source']['peakPolarity'], ['negative', 'positive'])
        negative, _ = self.check_exact([-32768, 7, 300], 1, 32767, 1);self.assertEqual((negative['source']['peakPCM16'], negative['source']['peakPolarity'], negative['headroom']['positiveHeadroomPCM16']), (32768, ['negative'], 0))
        self.assertEqual(negative['headroom']['negativeHeadroomPCM16'], 1)

    def test_summary_fields_types_claims_and_description(self):
        result, directory = self.check_exact(tone(400, 2, 3000, [(10, 3000)]), 2, 20000, 8, 16000)
        expected = {'operation', 'rate', 'channels', 'frames', 'durationSeconds', 'durationExact', 'source', 'targetPeakPCM16', 'maxGain', 'gain', 'headroom', 'peakPCM16', 'samplesCompared',
                    'distinctSampleValuesCompared', 'maxErrorLSB', 'toleranceLSB', 'claims', 'description', 'limits', 'warnings', 'timeline', 'verified', 'artifacts', 'runtime', 'status'}
        self.assertEqual(set(result), expected)
        self.assertEqual((result['targetPeakPCM16'], result['maxGain'], result['toleranceLSB']), (20000, 8, {'numerator': 1, 'denominator': 2}))
        self.assertEqual(result['durationExact'], {'numerator': 1, 'denominator': 40});self.assertIs(result['timeline']['originalTimestampsPreserved'], True)
        self.assertEqual(result['claims'], {'oneCommonGain': True, 'everySampleCompared': True, 'outputPeakIsTargetPeak': True, 'clippedSamples': 0, 'loudnessNormalised': False, 'truePeakControlled': False, 'authenticityCertified': False})
        self.assertLessEqual(Fraction(result['maxErrorLSB']['numerator'], result['maxErrorLSB']['denominator']), Fraction(1, 2))
        description = result['description'];self.assertEqual(set(description), {'gainRatio', 'gainDecibels', 'outputHeadroomDecibels'})
        self.assertAlmostEqual(description['gainRatio'], result['gain']['numerator'] / result['gain']['denominator']);self.assertAlmostEqual(description['gainDecibels'], 20 * math.log10(result['gain']['numerator'] / result['gain']['denominator']), places=3)
        self.assertAlmostEqual(description['outputHeadroomDecibels'], 20 * math.log10(32768 / 20000), places=3)
        self.assertEqual(json.loads((directory / 'audio-summary.json').read_text())['gain'], result['gain'])
        self.assertEqual([x['kind'] for x in a.artifacts(directory, normalise.SOURCE_LIMIT)], ['file', 'text'])
        saved = json.loads((directory / 'result.json').read_text());self.assertEqual(saved['status'], 'succeeded');self.assertEqual(saved, result)
        self.assertEqual({p.name for p in directory.iterdir() if p.is_file() and p.suffix == '.wav'}, {'audio.wav', 'captured-0.wav'})

    def test_channel_balance_is_one_common_gain(self):
        values = [3000, 1500, -3000, -1500, 600, 300]
        _, directory = self.check_exact(values, 2, 20000, 8)
        out = a.pcm((directory / 'audio.wav').read_bytes())[1]
        self.assertEqual(out[0::2], [20000, -20000, 4000]);self.assertEqual(out[1::2], [10000, -10000, 2000])

    def test_refusals_happen_before_any_native_process(self):
        for values, code, target, ceiling in (([0] * 64, 'AUDIO_SILENT_SOURCE', 1000, 4), ([1] * 64, 'AUDIO_GAIN_LIMIT', 1000, 4), ([-3, 3] * 32, 'AUDIO_GAIN_LIMIT', 32767, 16)):
            self.mode('good');type(self).counter += 1
            source = self.root / f'refused-{self.counter}.wav';source.write_bytes(wav(values, 1, 8000));directory = self.root / f'refused-run-{self.counter}'
            document = {'version': a.VERSION, 'operation': 'normalise', 'source': str(source), 'targetPeak': target, 'maxGain': ceiling}
            fault = self.fault(lambda: a.run(document, directory, executable=str(self.exe), timeout=30), code)
            self.assertEqual(fault.location, '$.maxGain' if code == 'AUDIO_GAIN_LIMIT' else '$.source')
            self.assertFalse((self.exe.parent / 'launched').exists());self.assertFalse((directory / 'version-submission.json').exists());self.assertFalse((directory / 'captured-0.wav').exists())
            self.assertFalse((directory / 'audio.wav').exists());self.assertEqual(json.loads((directory / 'result.json').read_text())['status'], 'failed')
            self.assertEqual(json.loads((directory / 'result.json').read_text())['fault']['code'], code)

    def test_unsupported_source_is_refused_before_native_use(self):
        type(self).counter += 1;source = self.root / f'bad-{self.counter}.wav';source.write_bytes(riff(fmt(bits=24, align=3), data([1, 2, 3])))
        document = {'version': a.VERSION, 'operation': 'normalise', 'source': str(source), 'targetPeak': 100, 'maxGain': 2}
        self.fault(lambda: a.run(document, self.root / f'bad-run-{self.counter}', executable=str(self.exe), timeout=30), 'INVALID_AUDIO_DATA')
        self.assertFalse((self.exe.parent / 'launched').exists())

    def test_native_misbehaviour_is_rejected_even_when_the_native_exit_is_zero(self):
        values = tone(200, 2, 3000, [(3, 3000)])
        for mode in ('off1', 'short', 'long', 'rate', 'mono', 'invert', 'swap', 'clip', 'ignoretarget', 'slightly-wrong', 'noise', 'stdout'):
            with self.subTest(mode):
                self.mode(mode);result = None
                with self.assertRaises(SchemaxisError) as caught: self.run_case(values, 2, 20000, 8, name=f'mis-{mode}-{self.counter + 1}')
                self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED', caught.exception.fault.to_dict())
                self.assertIn(caught.exception.fault.location, ('audio.wav', 'normalise.stderr', 'normalise.stdout'))

    def test_one_off_sample_at_a_non_tie_value_is_rejected_but_a_tie_may_go_either_way(self):
        self.mode('off1')
        with self.assertRaises(SchemaxisError) as caught: self.run_case([1000, -1000, 500, 1, 333], 1, 300, 1)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        # peak 10, target 5: every odd sample is an exact half; both neighbours are nearest integers
        source = bytes(wav([10, 1, 3, -1, -3, -10], 1, 8000));info, start, size, _ = conform.info_of(source)
        for variant in ([5, 0, 1, -1, -2, -5], [5, 1, 2, 0, -1, -5], [5, 1, 1, 0, -2, -5]):
            output = bytes(wav(variant, 1, 8000));out_info, out_start, out_size = conform.canonical_info(output, 'X', 'audio.wav', normalise.OUTPUT_LIMIT)
            result = normalise.summarise(a.plan({'version': a.VERSION, 'operation': 'normalise', 'source': '/x.wav', 'targetPeak': 5, 'maxGain': 1}), source, info, start, size, output, out_info, out_start, out_size, b'', b'')
            self.assertEqual(result['maxErrorLSB'], {'numerator': 1, 'denominator': 2})
        for variant in ([5, 2, 1, 0, -1, -5], [5, 0, 1, -1, -3, -5]):
            output = bytes(wav(variant, 1, 8000));out_info, out_start, out_size = conform.canonical_info(output, 'X', 'audio.wav', normalise.OUTPUT_LIMIT)
            with self.assertRaises(SchemaxisError) as caught:
                normalise.summarise(a.plan({'version': a.VERSION, 'operation': 'normalise', 'source': '/x.wav', 'targetPeak': 5, 'maxGain': 1}), source, info, start, size, output, out_info, out_start, out_size, b'', b'')
            self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')

    def test_memory_guard_for_an_output_that_is_not_a_function_of_the_source_value(self):
        n = 4000;source = bytes(wav([1000] * n, 1, 8000));info, start, size, _ = conform.info_of(source)
        output = bytes(wav([300 + (i % 9) for i in range(n)], 1, 8000));out_info, out_start, out_size = conform.canonical_info(output, 'X', 'audio.wav', normalise.OUTPUT_LIMIT)
        with self.assertRaises(SchemaxisError) as caught:
            normalise.summarise(a.plan({'version': a.VERSION, 'operation': 'normalise', 'source': '/x.wav', 'targetPeak': 300, 'maxGain': 1}), source, info, start, size, output, out_info, out_start, out_size, b'', b'')
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED');self.assertIn('not a function', caught.exception.fault.message)

    def test_unsuitable_runtime_is_rejected_before_normalise_processing(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name);executable = directory / 'wrong-sox.py';marker = directory / 'processed'
            executable.write_text('#!' + sys.executable + '\nimport sys\nfrom pathlib import Path\nif sys.argv[1:]==["--version"]: print(sys.argv[0]+": SoX v14.4.1")\nelse: Path(' + repr(str(marker)) + ').touch()\n')
            executable.chmod(0o700);source = directory / 'in.wav';source.write_bytes(wav([100, -200, 50], 1, 8000))
            document = {'version': a.VERSION, 'operation': 'normalise', 'source': str(source), 'targetPeak': 400, 'maxGain': 4}
            self.fault(lambda: a.run(document, directory / 'result', executable=str(executable), timeout=10), 'UNSUPPORTED_NATIVE_VERSION')
            self.assertFalse(marker.exists());self.assertFalse((directory / 'result/normalise-submission.json').exists())


class NormaliseForgeries(unittest.TestCase):
    """Real (stub-native) run directory; every probe refreshes digests so only the contract can reject it."""
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory();root = Path(cls.temporary.name);cls.root = root
        exe = root / 'sox';exe.write_text(FAKE_NORMALISE % {'python': sys.executable});exe.chmod(0o700)
        source = root / 'source.wav';cls.values = tone(300, 2, 3000, [(40, 3000), (41, -1500)]);source.write_bytes(wav(cls.values, 2, 16000))
        cls.document = {'version': a.VERSION, 'operation': 'normalise', 'source': str(source), 'targetPeak': 20000, 'maxGain': 8}
        cls.directory = root / 'run';cls.result = a.run(cls.document, cls.directory, executable=str(exe), timeout=60)

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def setUp(self): self.saved = {p: p.read_bytes() for p in self.directory.rglob('*') if p.is_file()}

    def tearDown(self):
        for path in list(self.directory.rglob('*')):
            if path.is_file() and path not in self.saved: path.unlink()
        for path, content in self.saved.items(): path.write_bytes(content)

    def fault(self, action=None, code='VERIFICATION_FAILED'):
        with self.assertRaises(SchemaxisError) as caught: (action or (lambda: a.verify(self.directory)))()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict());return caught.exception.fault

    def refresh(self):
        d = self.directory;limit = normalise.SOURCE_LIMIT;receipt = a.read(d, 'verification.json');receipt['artifacts'] = a.artifacts(d, limit)
        receipt['evidence'] = {n: a.digest(d, n, limit) for n in receipt['evidence']};a.atomic_json(d / 'verification.json', receipt);finalise(d)

    def rebind(self, stage, name):
        d = self.directory;bindings = a.read(d, stage + '-inputs.json');bindings[str(d / name)] = a.digest(d, name);a.atomic_json(d / (stage + '-inputs.json'), bindings)

    def put(self, name, value): (self.directory / name).write_bytes(value)

    def test_baseline_reopens(self):
        self.assertTrue(a.verify(self.directory)['verified']);self.assertEqual(a.verify(self.directory)['gain'], {'numerator': 20, 'denominator': 3, 'direction': 'boost', 'withinMaxGain': True})

    def test_forged_output_samples_with_refreshed_hashes(self):
        d = self.directory;good = a.pcm((d / 'audio.wav').read_bytes())[1]
        variants = {'silence': [0] * len(good), 'inverted': [-v for v in good], 'shifted': good[2:] + [0, 0], 'one sample +1': [v + (1 if i == 77 else 0) for i, v in enumerate(good)],
                    'single sample zeroed': [0 if i == 5 else v for i, v in enumerate(good)], 'quieter by 1 percent': [round(v * .99) for v in good], 'swapped channels': [v for pair in zip(good[1::2], good[0::2]) for v in pair],
                    'unscaled source': list(self.values), 'peak short': [min(v, 19999) if v > 0 else v for v in good]}
        for name, forged in variants.items():
            with self.subTest(name):
                self.put('audio.wav', wav(forged, 2, 16000));self.refresh();fault = self.fault();self.assertIn(fault.location, ('audio.wav',))
                self.put('audio.wav', self.saved[d / 'audio.wav'])
        for name, forged in {'extra frame': wav(good + good[-2:], 2, 16000), 'one frame short': wav(good[:-2], 2, 16000), 'wrong rate': wav(good, 2, 8000), 'mono': wav(good, 1, 16000)}.items():
            with self.subTest(name):
                self.put('audio.wav', forged);self.refresh();self.fault();self.put('audio.wav', self.saved[d / 'audio.wav'])
        original = self.saved[d / 'audio.wav'];info = b'INFOICMT' + struct.pack('<I', 8) + b'injected'
        self.put('audio.wav', riff(original[12:36], pad(b'LIST' + struct.pack('<I', len(info)) + info), original[36:]));self.refresh();self.fault()

    def test_forged_summary_and_result_fields_with_refreshed_hashes(self):
        d = self.directory
        mutations = {'gain numerator': lambda s: s['gain'].update(numerator=21), 'gain denominator': lambda s: s['gain'].update(denominator=4), 'gain direction': lambda s: s['gain'].update(direction='attenuation'),
                     'gain unreduced': lambda s: s['gain'].update(numerator=40, denominator=6), 'withinMaxGain': lambda s: s['gain'].update(withinMaxGain=False), 'source peak': lambda s: s['source'].update(peakPCM16=2999),
                     'source sha': lambda s: s['source'].update(sha256='0' * 64), 'polarity': lambda s: s['source'].update(peakPolarity=['negative']), 'output peak': lambda s: s.update(peakPCM16=19999),
                     'target': lambda s: s.update(targetPeakPCM16=20001), 'maxGain': lambda s: s.update(maxGain=9), 'maxGain type': lambda s: s.update(maxGain=8.0), 'frames': lambda s: s.update(frames=s['frames'] + 1),
                     'rate': lambda s: s.update(rate=8000), 'samples compared': lambda s: s.update(samplesCompared=1), 'distinct': lambda s: s.update(distinctSampleValuesCompared=1),
                     'max error': lambda s: s.update(maxErrorLSB={'numerator': 0, 'denominator': 1}), 'tolerance': lambda s: s.update(toleranceLSB={'numerator': 1, 'denominator': 1}),
                     'headroom': lambda s: s['headroom'].update(positiveHeadroomPCM16=0), 'claim loudness': lambda s: s['claims'].update(loudnessNormalised=True), 'claim authenticity': lambda s: s['claims'].update(authenticityCertified=True),
                     'claim clipped': lambda s: s['claims'].update(clippedSamples=1), 'claim bool as int': lambda s: s['claims'].update(oneCommonGain=1), 'claim clipped float': lambda s: s['claims'].update(clippedSamples=0.0),
                     'extra claim': lambda s: s['claims'].update(identityVerified=True), 'limits removed': lambda s: s.update(limits=[]), 'warnings removed': lambda s: s.update(warnings=[]),
                     'timeline': lambda s: s['timeline'].update(originalTimestampsPreserved=False), 'description missing': lambda s: s.pop('description'), 'description int': lambda s: s['description'].update(gainRatio=7),
                     'description far': lambda s: s['description'].update(gainDecibels=0.0), 'description nan': lambda s: s['description'].update(gainRatio=float('nan')), 'description extra': lambda s: s['description'].update(lufs=-16.0),
                     'operation': lambda s: s.update(operation='conform'), 'invented field': lambda s: s.update(transcript='x'), 'duration exact': lambda s: s['durationExact'].update(numerator=2)}
        for name, mutate in mutations.items():
            with self.subTest('summary ' + name):
                summary = a.read(d, 'audio-summary.json')
                try: mutate(summary);a.atomic_json(d / 'audio-summary.json', summary)
                except ValueError: (d / 'audio-summary.json').write_text(json.dumps(summary))   # NaN is not valid JSON for the strict writer
                self.refresh();self.fault();(d / 'audio-summary.json').write_bytes(self.saved[d / 'audio-summary.json'])
        for name, mutate in mutations.items():
            with self.subTest('result ' + name):
                result = a.read(d, 'result.json')
                try: mutate(result);a.atomic_json(d / 'result.json', result)
                except (ValueError, KeyError): continue
                self.fault();(d / 'result.json').write_bytes(self.saved[d / 'result.json'])
        for key, value in (('verified', 1), ('status', 'failed'), ('artifacts', 3), ('runtime', 'SoX v14.4.1'), ('claimedQuality', 'broadcast')):
            forged = a.read(d, 'result.json');forged[key] = value;a.atomic_json(d / 'result.json', forged);self.fault(code='INCOMPLETE_EXECUTION' if key == 'status' else 'VERIFICATION_FAILED');(d / 'result.json').write_bytes(self.saved[d / 'result.json'])
        for path, content in self.saved.items(): path.write_bytes(content)       # the probes refreshed receipts; restore the untouched run
        self.assertTrue(a.verify(d)['verified'])

    def test_description_is_a_diagnostic_compared_with_a_small_tolerance_not_authority(self):
        d = self.directory;summary = a.read(d, 'audio-summary.json');summary['description']['gainRatio'] += 5e-5;a.atomic_json(d / 'audio-summary.json', summary)
        result = a.read(d, 'result.json');result['description']['gainRatio'] += 5e-5;a.atomic_json(d / 'result.json', result);self.refresh()
        self.assertTrue(a.verify(d)['verified'])          # last-digit differences between hosts must not break reopening
        summary['description']['gainRatio'] += 1e-3;a.atomic_json(d / 'audio-summary.json', summary);self.refresh();self.fault()

    def test_forged_plan_capture_and_receipt_with_refreshed_hashes(self):
        d = self.directory
        plan = a.read(d, 'plan.json');plan['targetPeak'] = 20001;a.atomic_json(d / 'plan.json', plan);self.refresh();self.fault();(d / 'plan.json').write_bytes(self.saved[d / 'plan.json'])
        authored = a.read(d, 'authored.json');authored['targetPeak'] = 19999;a.atomic_json(d / 'authored.json', authored);self.refresh();self.fault();(d / 'authored.json').write_bytes(self.saved[d / 'authored.json'])
        authored = a.read(d, 'authored.json');authored['maxGain'] = 8.0;a.atomic_json(d / 'authored.json', authored);self.refresh();self.fault();(d / 'authored.json').write_bytes(self.saved[d / 'authored.json'])
        captures = a.read(d, 'captures.json');captures[0]['info']['frames'] += 1;a.atomic_json(d / 'captures.json', captures);self.refresh();self.fault();(d / 'captures.json').write_bytes(self.saved[d / 'captures.json'])
        receipt = a.read(d, 'verification.json')
        for name, mutation in (('extra', lambda r: r.update(claimed='qualified')), ('evidence type', lambda r: r.update(evidence=[])), ('missing', lambda r: r.pop('runtime')), ('runtime', lambda r: r.update(runtime='SoX v14.4.1'))):
            forged = copy.deepcopy(receipt);mutation(forged);a.atomic_json(d / 'verification.json', forged);self.fault();(d / 'verification.json').write_bytes(self.saved[d / 'verification.json'])

    def test_retained_captured_source_forgeries_with_refreshed_bindings(self):
        d = self.directory;bits = {}
        def forge(values, rate=16000, channels=2):
            data = wav(values, channels, rate);self.put('captured-0.wav', data);captures = a.read(d, 'captures.json')
            captures[0]['sha256'] = hashlib.sha256(data).hexdigest();captures[0]['bytes'] = len(data);captures[0]['info'] = {'rate': rate, 'channels': channels, 'frames': len(values) // channels};a.atomic_json(d / 'captures.json', captures)
            self.rebind('normalise', 'captured-0.wav');self.refresh()
        forge([0] * len(self.values));self.fault();self.put('captured-0.wav', self.saved[d / 'captured-0.wav']);(d / 'captures.json').write_bytes(self.saved[d / 'captures.json']);(d / 'normalise-inputs.json').write_bytes(self.saved[d / 'normalise-inputs.json'])
        louder = [v * 2 for v in self.values];forge(louder);self.fault();self.put('captured-0.wav', self.saved[d / 'captured-0.wav']);(d / 'captures.json').write_bytes(self.saved[d / 'captures.json']);(d / 'normalise-inputs.json').write_bytes(self.saved[d / 'normalise-inputs.json'])
        forge([1, -1] * 100)     # needs gain 20000 > maxGain 8: the retained source no longer satisfies the plan
        fault = self.fault();self.assertIn('AUDIO_GAIN_LIMIT', fault.message)

    def test_forged_launcher_gain_command_and_submission(self):
        d = self.directory
        launcher = (d / 'normalise-launcher.py').read_text();self.assertIn('6.666666666666667', launcher)
        for forged in (launcher.replace('6.666666666666667', '6.7'), launcher.replace("'vol'", "'gain'"), launcher.replace('-D', '-G'), launcher.replace('RLIMIT_CPU,(30,30)', 'RLIMIT_CPU,(300,300)')):
            (d / 'normalise-launcher.py').write_text(forged);self.refresh();self.fault();(d / 'normalise-launcher.py').write_text(launcher)
        submission = a.read(d, 'normalise-submission.json');submission['exitCode'] = 1;a.atomic_json(d / 'normalise-submission.json', submission);self.refresh();self.fault()
        (d / 'normalise-submission.json').write_bytes(self.saved[d / 'normalise-submission.json'])
        bindings = a.read(d, 'normalise-inputs.json');bindings[next(iter(bindings))] = '0' * 64;a.atomic_json(d / 'normalise-inputs.json', bindings);self.refresh();self.fault()

    def test_native_output_streams_must_be_empty(self):
        d = self.directory
        for name in ('normalise.stdout', 'normalise.stderr'):
            (d / name).write_text('WARN vol: vol clipped 1 samples; decrease volume?\n');self.refresh();fault = self.fault();self.assertEqual(fault.location, name)
            (d / name).write_bytes(self.saved[d / name])

    def test_unreferenced_members_and_other_operation_stages_are_membership_failures(self):
        d = self.directory
        for name in ('clip-0.wav', 'audio-copy.wav', 'conform.stderr', 'conform-launcher.py', 'normalise-extra.json', 'audio.WAV', 'audio.flac', 'notes.json', 'orphan.metadata.json', 'captured-1.wav'):
            (d / name).write_bytes(b'x');self.refresh();self.fault();(d / name).unlink()
        link = d / 'linked.wav';link.symlink_to(d / 'audio.wav');self.refresh();self.fault();link.unlink()
        self.assertTrue(a.verify(d)['verified'])


if __name__ == '__main__': unittest.main()
