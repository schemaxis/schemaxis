"""Speech conform: exact integer channel rules, frame-count rule, bounds and tamper checks.

Native SoX 14.4.2 produced the literal expectations below (see tools/qualify_sox.py).
Host tests stand in for it with an analytic stdlib stub that is host plumbing only: it
proves nothing about native behaviour. Every tamper probe refreshes ordinary digests,
so only the semantic contract can reject it."""
import copy
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import tracemalloc
import unittest
import wave

from test_sox import data, fmt, pad, riff, wav

from schemaxis.adaptors.sox import adaptor as a
from schemaxis.adaptors.sox import conform
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise

ROOT = Path(__file__).resolve().parents[2]

FAKE_CONFORM = """#!%(python)s
import math,struct,sys,wave
from pathlib import Path
a=sys.argv
if a[1:]==['--version']:
    print(a[0]+':      SoX v14.4.2');raise SystemExit
mode=(Path(a[0]).parent/'mode').read_text() if (Path(a[0]).parent/'mode').exists() else 'good'
with wave.open(a[5],'rb') as w:
    channels,rate,n=w.getnchannels(),w.getframerate(),w.getnframes();raw=struct.unpack('<'+'h'*(n*channels),w.readframes(n))
spec=a[14]
if channels==1 or spec=='1': mixed=list(raw[0::channels])
elif spec=='2': mixed=list(raw[1::2])
else: mixed=[(l+r+1)>>1 for l,r in zip(raw[0::2],raw[1::2])]
if rate==16000: out=mixed
else:
    m=(2*n*16000+rate)//(2*rate);out=[]
    for j in range(m):
        x=j*rate/16000;i=min(int(x),n-1);f=x-i;b=mixed[min(i+1,n-1)]
        out.append(int(math.floor(mixed[i]*(1-f)+b*f+.5)))
if mode=='short': out=out[:-1]
if mode=='rate':
    rate_out=8000
else: rate_out=16000
with wave.open(a[12],'wb') as w:
    w.setparams((1,2,rate_out,0,'NONE','not compressed'));w.writeframes(struct.pack('<'+'h'*len(out),*out))
if mode=='noise': sys.stderr.write(a[0]+' WARN wav: something unexpected\\n')
if mode=='clipwarn': sys.stderr.write(a[0]+' WARN rate: rate clipped 3 samples; decrease volume?\\n')
if mode=='stdout': print('hello')
"""


def tone(frames, rate, left=300.0, right=500.0, amplitude=10000, channels=2):
    values = []
    for k in range(frames):
        values.append(int(amplitude * math.sin(2 * math.pi * left * k / rate)))
        if channels == 2: values.append(int(0.7 * amplitude * math.sin(2 * math.pi * right * k / rate)))
    return values


class ConformPlanAndBounds(unittest.TestCase):
    def doc(self, **update):
        return {'version': a.VERSION, 'operation': 'conform', 'source': '/recording.wav', 'channelPolicy': 'average', **update}

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught: action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def test_plan_is_immutable_deterministic_and_states_the_target(self):
        d = self.doc();before = copy.deepcopy(d);p = a.plan(d)
        self.assertEqual(d, before);self.assertEqual(p, a.plan(d));self.assertEqual(a.query(d), (['conform'], {}))
        self.assertEqual(p['target'], {'rate': 16000, 'channels': 1, 'encoding': 'signed-integer', 'bits': 16})
        self.assertEqual(p['losses'], conform.LOSSES);self.assertEqual(a.resources(d, {}, 'id'), {'threads': 1})

    def test_policy_is_explicit_and_closed_with_actionable_faults(self):
        d = self.doc();del d['channelPolicy']
        fault = self.fault(lambda: a.plan(d), 'MISSING_ARGUMENT');self.assertEqual(fault.location, '$.channelPolicy');self.assertIn('average, left, right', fault.message)
        for value in ('mid', 'Average', '', 1, None, ['left']):
            fault = self.fault(lambda: a.plan(self.doc(channelPolicy=value)), 'INVALID_ARGUMENT');self.assertEqual(fault.location, '$.channelPolicy')
        for name in ('left', 'right', 'average'): self.assertEqual(a.plan(self.doc(channelPolicy=name))['channelPolicy'], name)

    def test_source_and_closed_keys(self):
        for source in ('relative.wav', 'https://example.org/a.wav', '/recording.mp3', '/recording'):
            self.assertEqual(self.fault(lambda: a.plan(self.doc(source=source)), 'INVALID_AUDIO_SOURCE').location, '$.source')
        for extra in ({'clips': []}, {'targetRate': 8000}, {'command': 'x'}, {'dither': True}, {'gain': 1}):
            self.fault(lambda: a.plan(self.doc(**extra)), 'UNKNOWN_ARGUMENT')
        assemble = {'version': a.VERSION, 'operation': 'assemble', 'source': '/a.wav', 'clips': [{'source': '/a.wav', 'frameCount': 1}]}
        self.fault(lambda: a.plan(assemble), 'UNKNOWN_ARGUMENT')
        self.fault(lambda: a.plan({'version': a.VERSION, 'operation': 'duck'}), 'UNKNOWN_FILTER')
        self.fault(lambda: a.plan({'version': 'schemaxis.sox/2', 'operation': 'conform'}), 'UNSUPPORTED_VERSION')

    def test_schema_has_one_closed_branch_per_operation(self):
        schema = a.schema();assemble, speech, headroom, _overlay = schema['oneOf']
        self.assertEqual(speech['required'], ['version', 'operation', 'source', 'channelPolicy']);self.assertFalse(speech['additionalProperties'])
        self.assertEqual(speech['properties']['channelPolicy'], {'enum': ['average', 'left', 'right']})
        self.assertEqual(speech['properties']['operation'], {'const': 'conform'});self.assertEqual(assemble['properties']['operation'], {'const': 'assemble'})
        self.assertEqual(schema['required'], ['version', 'operation']);self.assertEqual(schema['properties']['operation'], {'enum': ['assemble', 'conform', 'normalise', 'mix']})
        self.assertEqual(headroom['properties']['operation'], {'const': 'normalise'})

    def source_fault(self, data_bytes, code, policy='average', at=None):
        p = a.plan(self.doc(channelPolicy=policy))
        fault = self.fault(lambda: a.conform_source(p, data_bytes), code)
        if at: self.assertEqual(fault.location, at)
        return fault

    def test_channel_policy_against_source_channels(self):
        stereo, mono = wav([1, 2] * 100, 2, 16000), wav([1] * 100, 1, 16000)
        for policy in conform.POLICIES: self.assertEqual(a.conform_source(a.plan(self.doc(channelPolicy=policy)), stereo)['channels'], 2)
        for policy in ('average', 'left'): self.assertEqual(a.conform_source(a.plan(self.doc(channelPolicy=policy)), mono)['channels'], 1)
        fault = self.source_fault(mono, 'AUDIO_CHANNEL_POLICY', 'right', '$.channelPolicy');self.assertIn("'average' or 'left'", fault.message)

    def test_unsupported_formats_are_refused_before_native_use(self):
        good = [100, -100, 200, -200]
        cases = {'24-bit': riff(fmt(bits=24, align=3), data(good)), 'float': riff(fmt(encoding=3), data(good)), 'extensible': riff(fmt(encoding=0xFFFE), data(good)),
                 'three channels': riff(fmt(channels=3, align=6), data(good * 3)), 'rate low': riff(fmt(rate=7999), data(good)), 'rate high': riff(fmt(rate=192001), data(good)),
                 'truncated': wav(good)[:-1], 'trailing': wav(good) + b'\0', 'empty': riff(fmt(), data([])), 'RF64': b'RF64' + wav(good)[4:], 'extra chunk': riff(fmt(), b'fact' + struct.pack('<II', 4, 4), data(good)),
                 'duplicate data': riff(fmt(), data(good), data(good))}
        for name, value in cases.items():
            with self.subTest(name):
                self.source_fault(value, 'INVALID_AUDIO_DATA', at='$.source')
                self.fault(lambda: a.pcm(value), 'INVALID_AUDIO_DATA')   # assemble's parser agrees

    def test_header_parser_agrees_with_the_assemble_parser_on_accepted_layouts(self):
        for layout in ([fmt(), data([1, 2])], [pad(b'JUNK' + struct.pack('<I', 3) + b'abc'), fmt(), pad(b'LIST' + struct.pack('<I', 3) + b'abc'), data([1, 2])], [fmt(), data([1, 2]), pad(b'LIST' + struct.pack('<I', 1) + b'x')]):
            value = riff(*layout);info, start, size, _ = conform.info_of(value);self.assertEqual(info, a.pcm(value)[0]);self.assertEqual(value[start:start + size], struct.pack('<hh', 1, 2))
        self.fault(lambda: conform.info_of(riff(fmt(), pad(b'LIST' + struct.pack('<I', 3) + b'abc')[:-1] + b'\1', data([1]))), 'INVALID_AUDIO_DATA')

    def test_duration_and_minimum_length_bounds(self):
        header = lambda rate, frames: riff(fmt(rate=rate), b'data' + struct.pack('<I', 2 * frames) + b'\0' * (2 * frames))
        p = a.plan(self.doc())
        self.assertEqual(a.conform_source(p, header(8000, 600 * 8000))['frames'], 4800000)
        self.fault(lambda: a.conform_source(p, header(8000, 600 * 8000 + 1)), 'AUDIO_RESOURCE_LIMIT')
        self.assertEqual(a.conform_source(p, header(192000, 6))['frames'], 6)
        self.fault(lambda: a.conform_source(p, header(192000, 5)), 'AUDIO_SOURCE_BOUNDS')
        self.fault(lambda: conform.info_of(b'\0' * (conform.SOURCE_LIMIT + 1)), 'INVALID_AUDIO_DATA')
        with tempfile.TemporaryDirectory() as name:
            big = Path(name) / 'big.wav';big.write_bytes(b'0' * (conform.SOURCE_LIMIT + 1));d = self.doc(source=str(big))
            self.fault(lambda: a.reusableInputs(d), 'INVALID_AUDIO_SOURCE')

    def test_literal_frame_rule_and_channel_mixing_observed_natively(self):
        """Values observed with SoX 14.4.2: round-half-up frame count, (L+R+1)>>1 average."""
        for rate, frames, expected in [(44100, 66150, 24000), (48000, 101, 34), (48000, 1000, 333), (88200, 3, 1), (96000, 3, 1), (96000, 255, 43), (192000, 5, 0),
                                       (192000, 6, 1), (192000, 12345, 1029), (8000, 1, 2), (11025, 1, 1), (12345, 100, 130)]:
            self.assertEqual(conform.expected_frames(frames, rate), expected, (rate, frames))
        pairs = [(1, 0, 1), (-1, 0, 0), (-3, 0, -1), (3, 0, 2), (1, -2, 0), (-5, -6, -5), (32767, 32766, 32767), (-32768, -32767, -32767), (32767, -32768, 0), (-32768, 32767, 0), (100, -101, 0), (32767, 0, 16384), (-32768, 0, -16384)]
        from array import array
        block = array('h', [v for l, r, _ in pairs for v in (l, r)])
        self.assertEqual(list(conform.mix(block, 2, 'average')), [e for _, _, e in pairs])
        self.assertEqual(list(conform.mix(block, 2, 'left')), [l for l, _, _ in pairs]);self.assertEqual(list(conform.mix(block, 2, 'right')), [r for _, r, _ in pairs])

    def test_commands_are_fixed_and_carry_no_authored_text(self):
        for policy, spec in (('average', '-'), ('left', '1'), ('right', '2')):
            p = a.plan(self.doc(channelPolicy=policy));command = a.commands('/native/sox', p)['conform']
            self.assertEqual(command, ['/native/sox', '-D', '--single-threaded', '-t', 'wav', 'captured-0.wav', '-t', 'wav', '-e', 'signed-integer', '-b', '16', 'audio.wav', 'remix', spec, 'rate', '-v', '16000'])
            self.assertEqual(a.stage_inputs('conform', p), ['captured-0.wav']);self.assertEqual(a.stage_inputs('version', p), [])
        text = a.launcher(Path('/run'), 'conform', command, p)
        self.assertIn('RLIMIT_FSIZE,(25165824,25165824)', text);self.assertIn(str(conform.SOURCE_LIMIT), text)


class AssembleIsUnchanged(unittest.TestCase):
    """Fail-before pins of the pre-conform assemble contract (hashes of the retained structures)."""
    def h(self, value): return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def test_effective_plan_commands_launchers_schema_and_declaration_bytes(self):
        d = json.loads((ROOT / 'examples/schemaxis/sox-assembly.json').read_text());p = a._native_plan(d)
        self.assertEqual(self.h(p), 'afe21c72106e9c7379e661da0bc0448c31dc045cc958e79b53eb8c7cfe11fefc')
        commands = a.commands('/native/sox', p);self.assertEqual(self.h(commands), 'd1685663ecc648e1414ba057ec443391e92ccf8305935800db317ea4fa11d744')
        for stage, expected in (('clip-0', 'ff6c3bcaf464442285679a99691896b97d903710cf69b8c92226a55b488e5f70'), ('assemble', 'bb94e0f2aeae02d2089fafa2e3cb7c771056998c1943eb6ea4af15059d23c2fd'),
                                ('version', '5134d8b19d3de83cce7f96c2fa853b5054552281c7d65c2188664c196a33bb28')):
            self.assertEqual(hashlib.sha256(a.launcher(Path('/run'), stage, commands[stage], p).encode()).hexdigest(), expected, stage)
        self.assertEqual(self.h(sorted(a.evidence_names(p))), '12ab75f4a271a8331d0c6df8db496eeb2b9d7fc0223845e736f743059b11361b')
        from schemaxis.schema import DRAFT
        self.assertEqual(self.h({'$schema': DRAFT, **a.schema()['oneOf'][0]}), 'e1e2d351bf05d5f2700fccc095d198cbb30e6334fb6d97c68fce52e340ffe770')
        self.assertEqual(self.h(a.DECLARATIONS['assemble']), 'a224d43708b6c6e304e2bc81a9d00bacf1de0730f80264c0a350c34205731c23')
        self.assertEqual(self.h(a.LOSSES), '158f8cb0930fa1d30bb1a6cefb17278741bcb04764bdfde638a510605ef66848')
        self.assertIn('no resampling/channel conversion', a.LOSSES[0]);self.assertNotIn('conform', ' '.join(a.LOSSES))

    def test_assemble_still_refuses_rate_or_channel_change(self):
        d = json.loads((ROOT / 'examples/schemaxis/sox-assembly.json').read_text());p = a.plan(d)
        with self.assertRaises(SchemaxisError) as caught: a.inputs(p, lambda i, c: wav([0] * 4096, rate=8000 if i == 0 else 16000))
        self.assertEqual(caught.exception.fault.code, 'AUDIO_FORMAT_MISMATCH')


class ConformRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory();cls.root = Path(cls.temporary.name)
        exe = cls.root / 'bin' / 'sox';exe.parent.mkdir();exe.write_text(FAKE_CONFORM % {'python': sys.executable});exe.chmod(0o700);cls.exe = exe
        cls.counter = 0

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def mode(self, name): (self.exe.parent / 'mode').write_text(name)

    def tearDown(self): self.mode('good')

    def run_conform(self, frames=22050, rate=44100, policy='average', channels=2, values=None, mode='good', sub='run'):
        type(self).counter += 1;work = self.root / f'case-{self.counter}';work.mkdir()
        source = work / 'source.wav';source.write_bytes(wav(values if values is not None else tone(frames, rate, channels=channels), channels, rate))
        self.mode(mode)
        document = {'version': a.VERSION, 'operation': 'conform', 'source': str(source), 'channelPolicy': policy}
        return a.run(document, work / sub, executable=str(self.exe), timeout=120), work / sub, source

    def fault(self, action, code='VERIFICATION_FAILED'):
        with self.assertRaises(SchemaxisError) as caught: action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict());return caught.exception.fault

    def test_resampled_run_reopens_with_declared_fidelity_and_time_axis(self):
        result, directory, source = self.run_conform()
        self.assertTrue(a.verify(directory)['verified'])
        self.assertEqual((result['rate'], result['channels'], result['frames']), (16000, 1, 8000));self.assertEqual(result['durationExact'], {'numerator': 1, 'denominator': 2})
        self.assertEqual(result['source']['sha256'], hashlib.sha256(source.read_bytes()).hexdigest());self.assertEqual((result['source']['rate'], result['source']['frames']), (44100, 22050))
        self.assertTrue(result['conversion']['resampled']);self.assertFalse(result['fidelity']['samplesRecomputedExactly']);self.assertGreater(result['fidelity']['comparedPositions'], 100)
        self.assertEqual(result['fidelity']['method'], 'independent-band-limited-projection');self.assertIn('individual samples are not certified', result['fidelity']['limit'])
        self.assertEqual(result['fidelity']['verifiedBand'], {'upperFractionOfLowerNyquist': 0.6, 'upperHz': {'numerator': 4800, 'denominator': 1}});self.assertEqual(result['fidelity']['excludedForNativeClipping'], 0)
        self.assertTrue(result['timeline']['originalTimestampsPreserved']);self.assertEqual(result['warnings'], [])
        self.assertEqual(json.loads((directory / 'result.json').read_text())['frames'], 8000)
        names = {p.name for p in directory.iterdir()};self.assertTrue({'captured-0.wav', 'conform-launcher.py', 'conform-submission.json', 'audio.wav', 'audio-summary.json'} <= names)
        self.assertFalse(any(n.startswith('clip-') for n in names))

    def test_same_rate_conversion_is_exact_for_each_policy(self):
        values = [(i * 7919) % 60001 - 30000 for i in range(4000)]
        for policy in conform.POLICIES:
            result, directory, _ = self.run_conform(rate=16000, policy=policy, values=values)
            self.assertTrue(result['fidelity']['samplesRecomputedExactly']);self.assertEqual(result['fidelity']['comparedPositions'], 0);self.assertIsNone(result['fidelity']['verifiedBand']);self.assertFalse(result['conversion']['resampled'])
            output = a.pcm((directory / 'audio.wav').read_bytes())[1];left, right = values[0::2], values[1::2]
            self.assertEqual(output, {'average': [(l + r + 1) >> 1 for l, r in zip(left, right)], 'left': left, 'right': right}[policy])

    def test_extreme_integer_averages_never_clip_or_overflow(self):
        pairs = [(32767, 32767), (-32768, -32768), (32767, -32768), (-32768, 32767), (32767, 0), (-32768, 0), (-32768, -32767), (32767, 32766)] * 8
        result, directory, _ = self.run_conform(rate=16000, values=[v for p in pairs for v in p])
        self.assertEqual(a.pcm((directory / 'audio.wav').read_bytes())[1][:8], [32767, -32768, 0, 0, 16384, -16384, -32767, 32767]);self.assertEqual(result['saturatedSamples'], 24)

    def test_anti_phase_cancellation_and_silent_output_are_flagged_not_hidden(self):
        wave_ = [int(12000 * math.sin(2 * math.pi * 300 * k / 16000)) for k in range(4000)]
        result, _, _ = self.run_conform(rate=16000, values=[v for x in wave_ for v in (x, -x)])
        self.assertEqual([w['code'] for w in result['warnings']], ['CHANNEL_CANCELLATION', 'SILENT_OUTPUT']);self.assertEqual(result['peakPCM16'], 0)
        result, _, _ = self.run_conform(rate=16000, policy='left', values=[v for x in wave_ for v in (x, -x)])
        self.assertEqual(result['warnings'], []);self.assertEqual(result['peakPCM16'], max(wave_))

    def test_mono_sources_and_upsampling_are_not_mistaken_for_gain(self):
        """Native smoke testing found an energy-sum loudness bound that rejected 8 kHz mono."""
        for rate, frames in ((8000, 4000), (11025, 5001), (12345, 6000), (16000, 3000)):
            result, directory, _ = self.run_conform(frames=frames, rate=rate, policy='left', channels=1)
            self.assertEqual(result['frames'], conform.expected_frames(frames, rate));self.assertEqual(result['conversion']['resampled'], rate != 16000);self.assertTrue(a.verify(directory)['verified'])
        result, _, _ = self.run_conform(frames=4001, rate=8000, policy='average', channels=1);self.assertEqual(result['frames'], 8002)

    def test_short_sources_are_warned_unsampled_but_keep_header_and_frame_count_checks(self):
        result, directory, _ = self.run_conform(frames=120, rate=44100)
        self.assertEqual(result['fidelity']['comparedPositions'], 0);self.assertEqual([w['code'] for w in result['warnings']], ['FIDELITY_NOT_SAMPLED']);self.assertEqual(result['frames'], conform.expected_frames(120, 44100));self.assertTrue(a.verify(directory)['verified'])
        result, directory, _ = self.run_conform(frames=300, rate=44100)
        self.assertGreater(result['fidelity']['comparedPositions'], 0);self.assertEqual(result['warnings'], []);self.assertEqual(result['frames'], conform.expected_frames(300, 44100));self.assertTrue(a.verify(directory)['verified'])

    def test_runtime_failures_are_located_and_refused(self):
        for mode, fragment in (('short', 'frames'), ('rate', 'mono 16000 Hz')):
            with self.subTest(mode):
                fault = self.fault(lambda: self.run_conform(mode=mode));self.assertEqual(fault.location, 'audio.wav');self.assertIn(fragment, fault.message)
        self.assertEqual(self.fault(lambda: self.run_conform(mode='noise')).location, 'conform.stderr')
        self.assertEqual(self.fault(lambda: self.run_conform(mode='stdout')).location, 'conform.stdout')
        self.fault(lambda: self.run_conform(mode='clipwarn'))  # claims clipping while nothing is saturated
        directory = [d for d in self.root.glob('case-*/run') if (d / 'result.json').exists() and json.loads((d / 'result.json').read_text()).get('status') == 'failed'][-1]
        self.assertFalse(json.loads((directory / 'result.json').read_text())['verified'])

    def test_native_clipping_diagnostics_are_counted_when_samples_saturate(self):
        values = [32767 if (i // 40) % 2 else -32768 for i in range(8000)]
        result, _, _ = self.run_conform(rate=16000, policy='left', values=values, mode='clipwarn')
        self.assertEqual(result['nativeClippingWarnings'], {'rateEffectSamples': 3, 'outputSamples': 0});self.assertEqual([w['code'] for w in result['warnings']], ['OUTPUT_SATURATION'])


class ConformTamper(unittest.TestCase):
    """Forgeries with every ordinary digest refreshed must still fail semantic verification."""
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory();root = Path(cls.temporary.name);cls.root = root
        exe = root / 'bin' / 'sox';exe.parent.mkdir();exe.write_text(FAKE_CONFORM % {'python': sys.executable});exe.chmod(0o700)
        source = root / 'source.wav';source.write_bytes(wav(tone(22050, 44100), 2, 44100));cls.source = source
        cls.resampled = a.run({'version': a.VERSION, 'operation': 'conform', 'source': str(source), 'channelPolicy': 'average'}, root / 'resampled', executable=str(exe), timeout=120)
        exact = root / 'exact.wav';cls.values = [(i * 7919) % 60001 - 30000 for i in range(4000)];exact.write_bytes(wav(cls.values, 2, 16000))
        a.run({'version': a.VERSION, 'operation': 'conform', 'source': str(exact), 'channelPolicy': 'average'}, root / 'exact-run', executable=str(exe), timeout=120)

    baselines = {}

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def use(self, name):
        baselines = ConformTamper.baselines
        self.directory = self.root / name
        if name not in baselines: baselines[name] = {p: p.read_bytes() for p in self.directory.rglob('*') if p.is_file()}
        self.saved = baselines[name];self.restore()

    def restore(self):
        for path in list(self.directory.rglob('*')):
            if path.is_file() and path not in self.saved: path.unlink()
        for path, content in self.saved.items(): path.write_bytes(content)

    def refresh(self):
        d = self.directory;receipt = a.read(d, 'verification.json');limit = conform.SOURCE_LIMIT
        receipt['artifacts'] = a.artifacts(d, limit);receipt['evidence'] = {n: a.digest(d, n, limit) for n in receipt['evidence']};a.atomic_json(d / 'verification.json', receipt);finalise(d)

    def rebind(self, stage, name):
        d = self.directory;bindings = a.read(d, stage + '-inputs.json');bindings[str(d / name)] = a.digest(d, name, conform.SOURCE_LIMIT);a.atomic_json(d / (stage + '-inputs.json'), bindings)

    def refused(self, action=None, code='VERIFICATION_FAILED'):
        with self.assertRaises(SchemaxisError) as caught: (action or (lambda: a.verify(self.directory)))()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict());return caught.exception.fault

    def rewrite_output(self, samples, rate=16000):
        (self.directory / 'audio.wav').write_bytes(wav(samples, 1, rate));self.refresh()

    def reseal(self):
        """Model a forger who rewrites summary, result and every digest consistently."""
        d = self.directory;p = a.plan(a.read(d, 'authored.json'));receipt = a.read(d, 'verification.json')
        summary = a.inspect(d, p, receipt['executable']);a.atomic_json(d / 'audio-summary.json', summary)
        a.atomic_json(d / 'result.json', {'verified': True, 'artifacts': 2, 'runtime': receipt['runtime'], **summary, 'status': 'succeeded'});self.refresh()

    def output(self): return a.pcm((self.directory / 'audio.wav').read_bytes())[1]

    def test_baselines_reopen(self):
        for name in ('resampled', 'exact-run'):
            self.use(name);self.assertTrue(a.verify(self.directory)['verified'])

    def test_exact_conversion_rejects_a_single_changed_sample_even_with_refreshed_hashes(self):
        self.use('exact-run');samples = self.output()
        for index in (0, 999, 1999):
            forged = list(samples);forged[index] += 1;self.rewrite_output(forged)
            fault = self.refused();self.assertIn(f'output frame {index}', fault.message);self.restore()
        self.rewrite_output(samples[:-1]);self.refused();self.restore()
        self.rewrite_output(samples + [0]);self.refused();self.restore()
        self.assertTrue(a.verify(self.directory)['verified'])

    def test_exact_conversion_rejects_the_wrong_channel_and_an_inverted_signal(self):
        self.use('exact-run');left = self.values[0::2];right = self.values[1::2]
        for name, forged in (('left', left), ('right', right), ('inverted', [-v for v in self.output()]), ('floor average', [(l + r) >> 1 for l, r in zip(left, right)]), ('truncated average', [int((l + r) / 2) for l, r in zip(left, right)])):
            with self.subTest(name): self.rewrite_output(forged);self.refused();self.restore()

    def test_resampled_forgeries_beyond_the_declared_limit_are_rejected(self):
        self.use('resampled');samples = self.output()
        for name, forged in (('silence', [0] * len(samples)), ('inverted', [-v for v in samples]), ('gain 0.8', [int(v * .8) for v in samples]), ('gain 2', [max(-32768, min(32767, v * 2)) for v in samples]),
                             ('gain 0.98', [round(v * .98) for v in samples]), ('shifted 1 frame', samples[1:] + [0]), ('shifted 5 frames', samples[5:] + [0] * 5), ('delayed 5 frames', [0] * 5 + samples[:-5]), ('noise', [(i * 7919) % 20001 - 10000 for i in range(len(samples))]), ('other channel', [int(10000 * .7 * math.sin(2 * math.pi * 500 * k / 16000)) for k in range(len(samples))])):
            with self.subTest(name): self.rewrite_output(forged);self.refused();self.restore()
        self.assertTrue(a.verify(self.directory)['verified'])

    def test_declared_fidelity_limit_is_a_real_limit_not_an_oracle_claim(self):
        """Small departures pass: this check is bounded, which the summary says in so many words."""
        self.use('resampled');samples = self.output()
        self.rewrite_output([round(v * .999) for v in samples]);self.refused()   # stale summary: caught by exact reopening
        self.reseal();result = a.verify(self.directory)       # a forger who also rebuilds summary and result
        self.assertTrue(result['verified']);self.assertFalse(result['fidelity']['samplesRecomputedExactly']);self.assertIn('individual samples are not certified', result['fidelity']['limit']);self.restore()
        # Content above 0.6 x Nyquist is outside the verified band: added 7900 Hz energy is not detected by the band check.
        self.rewrite_output([max(-32768, min(32767, v + round(1500 * math.sin(2 * math.pi * 7900 * k / 16000)))) for k, v in enumerate(samples)]);self.reseal()
        self.assertTrue(a.verify(self.directory)['verified']);self.restore()

    def test_output_structure_frame_count_and_rate(self):
        self.use('resampled');samples = self.output()
        self.rewrite_output(samples[:-1]);self.refused();self.restore()
        self.rewrite_output(samples + [samples[-1]]);self.refused();self.restore()
        self.rewrite_output(samples, rate=8000);self.refused();self.restore()
        original = (self.directory / 'audio.wav').read_bytes();info = b'INFOICMT' + struct.pack('<I', 8) + b'injected'
        (self.directory / 'audio.wav').write_bytes(riff(original[12:36], pad(b'LIST' + struct.pack('<I', len(info)) + info), original[36:]));self.refresh();self.refused();self.restore()
        stereo = bytearray(original);stereo[22:24] = struct.pack('<H', 2);(self.directory / 'audio.wav').write_bytes(bytes(stereo));self.refresh();self.refused();self.restore()

    def test_capture_plan_and_evidence_binding(self):
        self.use('resampled');captured = (self.directory / 'captured-0.wav').read_bytes()
        forged = captured[:44] + struct.pack('<h', 5) + captured[46:]
        (self.directory / 'captured-0.wav').write_bytes(forged);captures = a.read(self.directory, 'captures.json');captures[0]['sha256'] = hashlib.sha256(forged).hexdigest();a.atomic_json(self.directory / 'captures.json', captures)
        self.rebind('conform', 'captured-0.wav');self.refresh();self.refused();self.restore()
        plan = a.read(self.directory, 'plan.json');plan['channelPolicy'] = 'left';a.atomic_json(self.directory / 'plan.json', plan);self.refresh();self.refused();self.restore()
        authored = a.read(self.directory, 'authored.json');authored['channelPolicy'] = 'left';a.atomic_json(self.directory / 'authored.json', authored);self.refresh();self.refused();self.restore()
        plan = a.read(self.directory, 'plan.json');plan['target']['rate'] = 8000;a.atomic_json(self.directory / 'plan.json', plan);self.refresh();self.refused();self.restore()
        captures = a.read(self.directory, 'captures.json');captures[0]['info']['rate'] = 48000;a.atomic_json(self.directory / 'captures.json', captures);self.refresh();self.refused();self.restore()
        captures = a.read(self.directory, 'captures.json');captures[0]['bytes'] = float(captures[0]['bytes']);a.atomic_json(self.directory / 'captures.json', captures);self.refresh();self.refused();self.restore()

    def test_summary_result_receipt_and_membership_cannot_be_forged(self):
        self.use('resampled')
        for key, value in (('frames', 8001), ('rate', 8000), ('channelPolicy', 'left'), ('warnings', [{'code': 'x'}]), ('saturatedSamples', 3), ('timeline', {'originalTimestampsPreserved': False}),
                           ('fidelity', {'method': 'exact-integer-channel-conversion'}), ('source', {}), ('peakPCM16', 1), ('operation', 'assemble'), ('conversion', {'resampled': False})):
            summary = a.read(self.directory, 'audio-summary.json');summary[key] = value;a.atomic_json(self.directory / 'audio-summary.json', summary);self.refresh();self.refused();self.restore()
        for key, value in (('verified', 1), ('frames', 8000.0), ('claimed', 'x')):
            result = a.read(self.directory, 'result.json');result[key] = value;a.atomic_json(self.directory / 'result.json', result);self.refused();self.restore()
        for name in ('clip-0.wav', 'audio-copy.wav', 'conform-launcher.py.bak', 'captured-1.wav', 'audio.WAV', 'notes.json'):
            (self.directory / name).write_bytes(b'x');self.refresh();self.refused();(self.directory / name).unlink();self.restore()
        receipt = a.read(self.directory, 'verification.json')
        for mutation in (lambda r: r.update(qualified=True), lambda r: r['evidence'].pop('conform.stderr'), lambda r: r['evidence'].update({'extra': '0' * 64}), lambda r: r['artifacts'].pop(), lambda r: r.update(runtime='SoX v9')):
            forged = copy.deepcopy(receipt);mutation(forged);a.atomic_json(self.directory / 'verification.json', forged);self.refused();self.restore()

    def test_native_command_launcher_and_diagnostics(self):
        self.use('resampled')
        submission = a.read(self.directory, 'conform-submission.json');submission['exitCode'] = 1;a.atomic_json(self.directory / 'conform-submission.json', submission);self.refresh();self.refused();self.restore()
        launcher = (self.directory / 'conform-launcher.py').read_text().replace("'remix', '-'", "'remix', '1'");(self.directory / 'conform-launcher.py').write_text(launcher);self.refresh();self.refused();self.restore()
        (self.directory / 'conform.stderr').write_text('/x/sox WARN rate: rate clipped 1 samples; decrease volume?\n');self.refresh();self.refused();self.restore()
        (self.directory / 'conform.stderr').write_text('anything unexpected\n');self.refresh();self.refused();self.restore()
        (self.directory / 'conform.stdout').write_text('x');self.refresh();self.refused();self.restore()
        self.assertTrue(a.verify(self.directory)['verified'])


class ConformStreaming(unittest.TestCase):
    def test_memory_does_not_scale_with_python_int_lists(self):
        """A 6M-frame source decoded to a list would need >48 MB; streaming adds only chunk arrays."""
        frames = 6_000_000;payload = struct.pack('<h', 1234) * frames
        source = riff(fmt(rate=16000), b'data' + struct.pack('<I', len(payload)) + payload)
        info, start, size, _ = conform.info_of(source)
        tracemalloc.start()
        try:
            stats = conform.measure(source, start, size, info, 'left')
            current, peak = tracemalloc.get_traced_memory()
        finally: tracemalloc.stop()
        self.assertEqual(stats['mixedSumSquares'], 1234 * 1234 * frames);self.assertLess(peak, 8 * 1024 * 1024, peak)

    def test_projection_is_one_physical_time_kernel_at_both_rates(self):
        """Source and output kernels must be the same continuous filter, or their transitions would differ."""
        for rate in (8000, 11025, 22050, 37813, 44100, 48000, 192000):
            src, out = conform.Projection(rate, rate), conform.Projection(rate, 16000)
            self.assertAlmostEqual(src.span / rate, out.span / 16000, places=12);self.assertAlmostEqual(src.cutoff * rate, out.cutoff * 16000, places=6)
            self.assertAlmostEqual(src.cutoff * rate, 0.35 * min(rate, 16000), places=6)
            for t in (0.0, 0.3e-3, 1.1e-3):
                self.assertAlmostEqual(src.kernel(t * rate) * rate, out.kernel(t * 16000) * 16000, delta=1e-9 * rate)

    def test_projection_passes_the_band_and_stops_the_transition(self):
        """Measured on the analytic kernel: unit gain below 0.6 N, below 1e-4 from 0.8 N (design 100 dB)."""
        for rate in (16000, 48000, 11025):
            filt = conform.Projection(rate, 16000);nyquist = min(rate, 16000) / 2;taps = filt.weights(0.0)
            def gain(hz): return abs(sum(w * math.cos(2 * math.pi * hz / 16000 * (k - filt.half + 1)) for k, w in enumerate(taps)))
            for fraction in (0.0, 0.3, 0.6): self.assertAlmostEqual(gain(fraction * nyquist), 1.0, delta=1e-4)
            for fraction in (0.8, 0.9, 0.95, 1.0): self.assertLess(gain(fraction * nyquist), 1e-4)

    def test_transition_and_out_of_band_tones_are_not_called_corrupt(self):
        """Regression for the master finding: a correct resampler that removes 7600-9000 Hz differently is accepted.

        The 'native' output here is SoX 14.4.2 behaviour modelled by an ideal band-limited resample of the
        in-band part only (out-of-band removed entirely), which differs from any reference near Nyquist."""
        rate = 48000
        for hz in (7600, 7800, 8000, 9000, 12000):
            values = [round(10000 * math.sin(2 * math.pi * hz * k / rate)) for k in range(9600)]
            for kept in (0.0, 0.5, 1.0) if hz < 8000 else (0.0,):
                out = [round(kept * 10000 * math.sin(2 * math.pi * hz * j / 16000)) for j in range(3200)]
                with self.subTest(hz=hz, kept=kept): self.assertEqual(self.band(values, rate, out)[0], 'ok')
        values = [round(10000 * math.sin(2 * math.pi * 1000 * k / rate)) for k in range(9600)]
        out = [round(10000 * math.sin(2 * math.pi * 1000 * j / 16000)) for j in range(3200)]
        self.assertEqual(self.band(values, rate, out)[0], 'ok')
        self.assertEqual(self.band(values, rate, out[1:] + [0])[0], 'refused');self.assertEqual(self.band(values, rate, [round(v * .98) for v in out])[0], 'refused')

    def test_clipping_exclusion_only_applies_when_native_reported_clipping(self):
        rate = 48000;values = [round(30000 * math.sin(2 * math.pi * 1000 * k / rate)) for k in range(9600)]
        out = [max(-32768, min(32767, round(33000 * math.sin(2 * math.pi * 1000 * j / 16000)))) for j in range(3200)]   # gain + saturation
        self.assertEqual(self.band(values, rate, out, clipped=False)[0], 'refused')
        # Declared limit: when SoX reported clipping, instants touching saturation are excluded, not compared. Saturation on
        # every cycle therefore leaves nothing to compare; summarise warns FIDELITY_NOT_SAMPLED rather than claiming a check.
        verdict, compared, excluded = self.band(values, rate, out, clipped=True);self.assertEqual((verdict, compared), ('ok', 0));self.assertGreater(excluded, 0)
        out = [max(-32768, min(32767, round(30000 * math.sin(2 * math.pi * 1000 * j / 16000) * (1.2 if j % 16 in (3, 4, 5) else 1)))) for j in range(3200)]
        verdict, compared, excluded = self.band(values, rate, out, clipped=True);self.assertEqual(verdict, 'ok');self.assertGreater(excluded, 0)

    def band(self, values, rate, out, clipped=False):
        source = wav(values, 1, rate);output = wav(out, 1, 16000);info, start, _, _ = conform.info_of(source)
        blocks = [sum(v * v for v in values[i:i + conform.BLOCK]) for i in range(0, len(values), conform.BLOCK)]
        try: compared, excluded = conform.band_check(source, start, info, 'average', output, 44, len(out), blocks, max(map(abs, values)), clipped)
        except SchemaxisError: return 'refused', None, None
        return 'ok', compared, excluded

    def test_spot_selection_is_deterministic_and_interior(self):
        src, out = conform.Projection(48000, 48000), conform.Projection(48000, 16000);blocks = [0] * 200 + [5, 9, 7] + [0] * 50
        low, high = conform.instants(src.half, out.half, 48000 * 6, 16000 * 6, 48000)
        first = conform.spots(low, high, 48000, blocks);second = conform.spots(low, high, 48000, blocks)
        self.assertEqual(first, second);self.assertTrue(all(low <= j <= high for j in first));self.assertEqual(first, sorted(set(first)));self.assertLessEqual(len(first), 512)
        self.assertEqual(conform.spots(*conform.instants(src.half, out.half, 100, 34, 48000), 48000, [1]), [])
        self.assertGreaterEqual(low, out.half - 1);self.assertLessEqual(high, 16000 * 6 - 1 - out.half);self.assertLessEqual((high * 48000) // 16000 + src.half, 48000 * 6 - 1)

if __name__ == '__main__': unittest.main()
