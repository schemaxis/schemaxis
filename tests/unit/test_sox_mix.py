"""Two-track `mix`: exact per-sample arithmetic, refusals before SoX, placement/duration and forgery checks.

Native SoX 14.4.2 behaviour is established by tools/qualify_sox_mix.py. Host tests stand in
for it with a stdlib stub (host plumbing only: it proves nothing about native behaviour).
Expected samples below come from integer arithmetic written here, not from the adaptor.
Every tamper probe refreshes ordinary digests, so only the semantic contract can reject it."""
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from test_sox import data, pad, riff, wav

from schemaxis.adaptors.sox import adaptor as a
from schemaxis.adaptors.sox import capabilities, mix
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise

ROOT = Path(__file__).resolve().parents[2]

FAKE_MIX = """#!%(python)s
import math,struct,sys,wave
from pathlib import Path
a=sys.argv
if a[1:]==['--version']:
    print(a[0]+':      SoX v14.4.2');raise SystemExit
here=Path(a[0]).parent
mode=(here/'mode').read_text() if (here/'mode').exists() else 'good'
(here/'launched').write_text('1')
def read(name):
    with wave.open(name,'rb') as w:
        c,r,n=w.getnchannels(),w.getframerate(),w.getnframes();return c,r,list(struct.unpack('<'+'h'*(n*c),w.readframes(n)))
def write(name,c,r,v):
    with wave.open(name,'wb') as w:
        w.setparams((c,2,r,0,'NONE','not compressed'));w.writeframes(struct.pack('<'+'h'*len(v),*v))
if a[13:14]==['pad']:
    c,r,v=read(a[5]);lead=int(a[14][:-1])*c
    if mode=='pad-short': lead-=c
    write(a[12],c,r,[0]*lead+v);raise SystemExit
assert a[3]=='-m' and a[4]=='-v' and a[7]=='-v',a
ga,gb=float(a[5]),float(a[8]);c,r,x=read(a[6]);_,_,y=read(a[9])
n=max(len(x),len(y));x+=[0]*(n-len(x));y+=[0]*(n-len(y))
if mode=='swap-gain': ga,gb=gb,ga
if mode=='ignore-gain': ga=gb=1.0
out=[int(math.floor(p*ga+q*gb+.5)) for p,q in zip(x,y)]
if a[17:18]==['trim']: out=out[:int(a[19][:-1])*c]
if mode=='off1': out[len(out)//2]+=1
if mode=='short': out=out[:-c]
if mode=='clip-sat': out=[max(-32768,min(32767,2*v)) for v in out]
if mode=='invert': out=[-v for v in out]
write(a[16],1 if mode=='mono' else c,r,out)
if mode=='noise': sys.stderr.write(a[0]+' WARN sox: mix-combining clipped 2 samples; decrease volume?\\n')
if mode=='stdout': print('hello')
"""


def tone(frames, channels=1, amplitude=9000, shift=0):
    return [int(amplitude * __import__('math').sin(0.37 * i + c + shift)) for i in range(frames) for c in range(channels)]


def oracle(narration, background, g_n, g_b, off_n, off_b, channels, policy):
    """Independent exact oracle: Fraction sums, nearest integer; returns the allowed (low, high) pair per sample."""
    from fractions import Fraction
    from math import floor
    frames_n, frames_b = len(narration) // channels, len(background) // channels
    end_n, end_b = off_n + frames_n, off_b + frames_b
    total = max(end_n, end_b) if policy == 'longest' else end_n
    result = []
    for f in range(total):
        for c in range(channels):
            n = narration[(f - off_n) * channels + c] if off_n <= f < end_n else 0
            b = background[(f - off_b) * channels + c] if off_b <= f < end_b else 0
            exact = Fraction(str(g_n)) * n + Fraction(str(g_b)) * b
            low = floor(exact + Fraction(1, 2)) if exact.denominator != 2 else floor(exact)
            result.append((low, floor(exact + Fraction(1, 2))))
    return result


class MixPlan(unittest.TestCase):
    def doc(self, **update):
        document = json.loads((ROOT / 'examples/schemaxis/sox-mix-baseline.json').read_text());document.update(update);return document

    def fault(self, action, code, location=None):
        with self.assertRaises(SchemaxisError) as caught: action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        if location: self.assertEqual(caught.exception.fault.location, location)
        return caught.exception.fault

    def test_defaults_immutability_determinism_and_query(self):
        document = self.doc(narration={'source': '/n.wav'}, background={'source': '/b.wav'});before = copy.deepcopy(document)
        plan = a.plan(document);self.assertEqual(document, before);self.assertEqual(plan, a.plan(document))
        self.assertEqual(plan['narration'], {'source': '/n.wav', 'gain': 1, 'offsetFrames': 0});self.assertEqual(plan['background'], {'source': '/b.wav', 'gain': 1, 'offsetFrames': 0})
        self.assertEqual(plan['operation'], 'mix');self.assertEqual(a.query(document), (['mix'], {}));self.assertEqual(a.resources(document, {}, 'x'), {'threads': 1})
        self.fault(lambda: a.resources(document, {'threads': 2}, 'x'), 'INVALID_EXECUTION')

    def test_policy_is_required_and_closed(self):
        document = self.doc();del document['durationPolicy'];self.fault(lambda: a.plan(document), 'MISSING_ARGUMENT', '$.durationPolicy')
        for bad in ('shortest', 'LONGEST', '', None, 1): self.fault(lambda: a.plan(self.doc(durationPolicy=bad)), 'INVALID_ARGUMENT')
        for policy in mix.POLICIES: self.assertEqual(a.plan(self.doc(durationPolicy=policy))['durationPolicy'], policy)

    def test_tracks_are_required_closed_typed_and_bounded(self):
        for role in mix.ROLES:
            document = self.doc();del document[role];self.fault(lambda: a.plan(document), 'MISSING_ARGUMENT')
            self.fault(lambda: a.plan(self.doc(**{role: {'source': '/x.wav', 'volume': 1}})), 'UNKNOWN_ARGUMENT', '$.' + role)
            self.fault(lambda: a.plan(self.doc(**{role: {'gain': 1}})), 'MISSING_ARGUMENT')
            self.fault(lambda: a.plan(self.doc(**{role: {'source': 'relative.wav'}})), 'INVALID_AUDIO_SOURCE', f'$.{role}.source')
            self.fault(lambda: a.plan(self.doc(**{role: {'source': '/x.flac'}})), 'INVALID_AUDIO_SOURCE', f'$.{role}.source')
            for gain in (-0.1, 4.0001, True, '1', None, float('nan'), float('inf')): self.fault(lambda: a.plan(self.doc(**{role: {'source': '/x.wav', 'gain': gain}})), 'INVALID_ARGUMENT')
            for offset in (-1, 262145, 1.5, '3', True): self.fault(lambda: a.plan(self.doc(**{role: {'source': '/x.wav', 'offsetFrames': offset}})), 'INVALID_ARGUMENT')
            for good in (0, 4, 0.5, 0.0001, 3.9999, 1e-4): self.assertEqual(a.plan(self.doc(**{role: {'source': '/x.wav', 'gain': good}}))[role]['gain'], good)
            for good in (0, 262144): a.plan(self.doc(**{role: {'source': '/x.wav', 'offsetFrames': good}}))
        self.fault(lambda: a.plan(self.doc(clips=[])), 'UNKNOWN_ARGUMENT')
        self.fault(lambda: a.plan({'version': a.VERSION, 'operation': 'mix', 'source': '/x.wav'}), 'UNKNOWN_ARGUMENT')

    def test_gain_precision_is_exactly_four_decimals(self):
        for bad in (0.12345, 0.00001, 1.00001, 3.33333, 1e-5, 0.33333333333333331): self.fault(lambda: a.plan(self.doc(background={'source': '/x.wav', 'gain': bad})), 'INVALID_ARGUMENT', '$.background.gain')
        self.assertEqual([mix.gain_scaled(v, 'x') for v in (0, 1, 4, 0.1, 0.1235, 0.0001, 2.5e-1, 1e-4, 3)], [0, 10000, 40000, 1000, 1235, 1, 2500, 1, 30000])
        self.assertEqual(mix.native_gain(0.1), '0.10000000000000001');self.assertEqual(mix.gain_text(0.25), '1/4')

    def test_other_operations_do_not_accept_mix_fields_and_old_plans_are_unchanged(self):
        for operation, extra in (('assemble', {'clips': [{'source': '/x.wav', 'frameCount': 4}]}), ('conform', {'source': '/x.wav', 'channelPolicy': 'left'}), ('normalise', {'source': '/x.wav', 'targetPeak': 100, 'maxGain': 2})):
            self.assertEqual(a.plan({'version': a.VERSION, 'operation': operation, **extra})['operation'], operation)
            self.fault(lambda: a.plan({'version': a.VERSION, 'operation': operation, **extra, 'durationPolicy': 'longest'}), 'UNKNOWN_ARGUMENT')
        self.fault(lambda: a.plan({'version': a.VERSION, 'operation': 'duck'}), 'UNKNOWN_FILTER')

    def test_schema_has_one_closed_mix_branch(self):
        schema = a.schema();branches = [b for b in schema['oneOf'] if b['properties']['operation'].get('const') == 'mix']
        self.assertEqual(len(branches), 1);branch = branches[0]
        self.assertEqual(sorted(branch['required']), ['background', 'durationPolicy', 'narration', 'operation', 'version'])
        self.assertEqual(branch['properties']['durationPolicy']['enum'], list(mix.POLICIES));self.assertFalse(branch.get('additionalProperties', False))
        track = branch['properties']['narration'];self.assertEqual(sorted(track['properties']), ['gain', 'offsetFrames', 'source']);self.assertEqual(track['required'], ['source'])
        self.assertEqual((track['properties']['gain']['minimum'], track['properties']['gain']['maximum'], track['properties']['gain']['default']), (0, 4, 1))
        self.assertEqual(track['properties']['offsetFrames']['maximum'], mix.MAX_FRAMES);self.assertIn('mix', schema['properties']['operation']['enum'])
        self.assertEqual(set(a.DECLARATIONS), {'assemble', 'conform', 'normalise', 'mix'})

    def test_examples_and_readiness_records(self):
        readiness = json.loads((ROOT / 'src/schemaxis/adaptors/sox/readiness.json').read_text())['routes'][a.VERSION]
        examples = {e['id']: e for e in readiness['examples']}
        for name in ('baseline', 'narration-policy'):
            self.assertEqual(a.plan(json.loads((ROOT / f'examples/schemaxis/sox-mix-{name}.json').read_text()))['operation'], 'mix')
            self.assertNotIn('expect', examples['mix-' + name])
        for name, code in (('invalid-gain', 'INVALID_ARGUMENT'), ('invalid-policy', 'MISSING_ARGUMENT')):
            self.assertEqual(examples['mix-' + name]['fault'], code)
            self.fault(lambda: a.plan(json.loads((ROOT / f'examples/schemaxis/sox-mix-{name}.json').read_text())), code)
        self.assertIn('verification/2026-10-26-sox-mix.md', readiness['completion']['review'])

    def test_discovery_describes_mix_without_native_imports(self):
        catalogue = capabilities.catalogue()['operations']['mix']
        for word in ('narration', 'background', 'clipping', 'durationPolicy'): self.assertIn(word, json.dumps(catalogue))
        self.assertNotIn('ducking is', json.dumps(catalogue).lower())
        text = Path(mix.__file__).read_text();self.assertNotIn('subprocess', text);self.assertNotIn('import sox', text)

    def test_operation_examples_target_this_route_and_the_workflow_chain_stays_discoverable(self):
        """Admission requires every operation example to be a SoX document; the normalise-to-FLAC chain is a workflow document."""
        catalogue = capabilities.catalogue()
        workflow = 'examples/schemaxis/sox-normalise-flac-workflow.json'
        for name, operation in catalogue['operations'].items():
            for example in operation['examples']:
                self.assertNotEqual(example['reference'], workflow, name)
                self.assertEqual(json.loads((ROOT / example['reference']).read_text())['version'], a.VERSION, example['reference'])
        self.assertEqual(json.loads((ROOT / workflow).read_text())['version'], 'schemaxis.workflow/1')
        self.assertIn(workflow, catalogue['references'])
        self.assertIn(workflow, json.dumps(catalogue['operations']['normalise']['semantics']))
        readiness = json.loads((ROOT / 'src/schemaxis/adaptors/sox/readiness.json').read_text())['routes'][a.VERSION]
        self.assertIn(workflow, readiness['profiles']['workflow']['references'])
        self.assertIn(workflow, (ROOT / 'docs/sox.md').read_text())

    def test_commands_are_fixed_and_carry_no_authored_text(self):
        plan = a.plan(self.doc(narration={'source': '/n;rm -rf x.wav', 'gain': 0.1, 'offsetFrames': 7}, background={'source': '/b.wav', 'gain': 0.25, 'offsetFrames': 3}, durationPolicy='narration'))
        commands = a.commands('/sox', plan, 123)
        self.assertEqual(list(commands), ['version', 'pad-0', 'pad-1', 'mix'])
        self.assertEqual(commands['pad-0'], ['/sox', '-D', '--single-threaded', '-t', 'wav', 'captured-0.wav', '-t', 'wav', '-e', 'signed-integer', '-b', '16', 'pad-0.wav', 'pad', '7s', '0'])
        self.assertEqual(commands['pad-1'][-3:], ['pad', '3s', '0'])
        self.assertEqual(commands['mix'], ['/sox', '-D', '--single-threaded', '-m', '-v', '0.10000000000000001', 'pad-0.wav', '-v', '0.25', 'pad-1.wav', '-t', 'wav', '-e', 'signed-integer', '-b', '16', 'audio.wav', 'trim', '0', '123s'])
        self.assertNotIn('trim', a.commands('/sox', a.plan(self.doc()), None)['mix'])
        self.assertEqual(a.stage_inputs('mix', plan), ['pad-0.wav', 'pad-1.wav']);self.assertEqual(a.stage_inputs('pad-1', plan), ['captured-1.wav'])
        for command in commands.values(): self.assertNotIn('/n;rm -rf x.wav', command)


class MixRun(unittest.TestCase):
    counter = 0

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory();cls.root = Path(cls.temporary.name)
        cls.exe = cls.root / 'bin' / 'sox';cls.exe.parent.mkdir();cls.exe.write_text(FAKE_MIX % {'python': sys.executable});cls.exe.chmod(0o700)

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def setUp(self): self.mode('good')

    def mode(self, name):
        (self.exe.parent / 'mode').write_text(name);launched = self.exe.parent / 'launched'
        if launched.exists(): launched.unlink()

    def fault(self, action, code, location=None):
        with self.assertRaises(SchemaxisError) as caught: action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        if location: self.assertEqual(caught.exception.fault.location, location)
        return caught.exception.fault

    def run_case(self, narration, background, g_n=1, g_b=1, off_n=0, off_b=0, channels=1, policy='longest', rate=8000, rate_b=None, channels_b=None):
        type(self).counter += 1
        n = self.root / f'n-{self.counter}.wav';b = self.root / f'b-{self.counter}.wav'
        n.write_bytes(wav(narration, channels, rate));b.write_bytes(wav(background, channels_b or channels, rate_b or rate))
        document = {'version': a.VERSION, 'operation': 'mix', 'narration': {'source': str(n), 'gain': g_n, 'offsetFrames': off_n},
                    'background': {'source': str(b), 'gain': g_b, 'offsetFrames': off_b}, 'durationPolicy': policy}
        directory = self.root / f'run-{self.counter}'
        return document, directory

    def check_exact(self, narration, background, g_n=1, g_b=1, off_n=0, off_b=0, channels=1, policy='longest', rate=8000):
        document, directory = self.run_case(narration, background, g_n, g_b, off_n, off_b, channels, policy, rate)
        result = a.run(document, directory, executable=str(self.exe), timeout=60)
        expected = oracle(narration, background, g_n, g_b, off_n, off_b, channels, policy)
        info, actual = a.pcm((directory / 'audio.wav').read_bytes(), canonical=True)
        self.assertEqual(info, {'rate': rate, 'channels': channels, 'frames': len(expected) // channels});self.assertEqual(len(actual), len(expected))
        for index, (value, (low, high)) in enumerate(zip(actual, expected)): self.assertTrue(low <= value <= high, (index, value, low, high))
        self.assertEqual(result['samplesCompared'], len(expected));self.assertTrue(a.verify(directory)['verified'])
        return result, directory, actual

    def test_primary_qualifier_dispatches_mix_cases_to_an_independent_sample_oracle(self):
        """tools/qualify_sox.py must not feed a mix run to the assemble oracle; the standalone oracle rejects forged runs."""
        sys.path.insert(0, str(ROOT / 'tools'))
        try:
            import qualify_sox
            import qualify_sox_mix
        finally: sys.path.remove(str(ROOT / 'tools'))
        self.assertIs(qualify_sox.mix_kit_case, qualify_sox_mix.kit_case)
        narration, background = tone(40, 2), tone(70, 2, 7000, 1)
        document, directory = self.run_case(narration, background, 0.5, 0.25, 6, 2, 2, 'narration')
        a.run(document, directory, executable=str(self.exe), timeout=60)
        facts = qualify_sox_mix.kit_case(directory, document)
        self.assertEqual((facts['rate'], facts['channels'], facts['frames'], facts['samples']), (8000, 2, 46, 92))
        output = directory / 'audio.wav';good = output.read_bytes()
        forged = bytearray(good);offset = good.index(b'data') + 8 + 2 * 30
        struct.pack_into('<h', forged, offset, struct.unpack_from('<h', forged, offset)[0] + 1);output.write_bytes(forged)
        with self.assertRaises(AssertionError): qualify_sox_mix.kit_case(directory, document)
        output.write_bytes(good)
        other = self.root / f'other-{self.counter}.wav';other.write_bytes(wav(tone(40, 2, 8000), 2, 8000))
        with self.assertRaises(AssertionError): qualify_sox_mix.kit_case(directory, {**document, 'narration': {**document['narration'], 'source': str(other)}})
        with self.assertRaises(AssertionError): qualify_sox_mix.kit_case(directory, {**document, 'narration': {**document['narration'], 'gain': 0.75}})
        self.assertEqual(qualify_sox_mix.kit_case(directory, document), facts)

    def test_literal_hand_computed_samples_with_offsets_gains_and_rounding(self):
        """n=[5,-5,7,-7] at 1/2 from frame 1, b=[5,5,-5,-5,9,9] at 1/4: 1.25->1, 2.5+1.25->4, -2.5-1.25->-4, 3.5-1.25->2, -3.5+2.25->-1, 2.25->2."""
        result, directory, actual = self.check_exact([5, -5, 7, -7], [5, 5, -5, -5, 9, 9], 0.5, 0.25, 1, 0)
        self.assertEqual(actual, [1, 4, -4, 2, -1, 2])

    def test_every_matrix_cell_is_exact_for_mono_stereo_offsets_policies_and_gains(self):
        narration, background = tone(40, 1, 9000), tone(70, 1, 5000, 1)
        for policy in mix.POLICIES:
            for off_n, off_b in ((0, 0), (5, 0), (0, 5), (45, 0), (100, 3)):
                if policy == 'narration' and off_b >= off_n + 40: continue
                for g_n, g_b in ((1, 1), (0.5, 0.25), (0, 1), (0.7, 0.3), (1.2345, 0.0001)):
                    with self.subTest(policy=policy, off=(off_n, off_b), gains=(g_n, g_b)): self.check_exact(narration, background, g_n, g_b, off_n, off_b, 1, policy)
        stereo_n, stereo_b = tone(25, 2, 9000), tone(33, 2, 5000, 2)
        for policy in mix.POLICIES:
            with self.subTest(stereo=policy): self.check_exact(stereo_n, stereo_b, 0.8, 0.3333, 4, 2, 2, policy, 16000)

    def test_silence_padding_gap_and_trailing_frames_are_exact(self):
        result, directory, actual = self.check_exact([100, 200], [50, 60], 1, 1, 0, 5)
        self.assertEqual(actual, [100, 200, 0, 0, 0, 50, 60]);self.assertEqual(result['uncoveredFrames'], 3);self.assertEqual(result['overlapFrames'], 0)
        self.assertEqual([t['trailingSilenceFrames'] for t in result['tracks']], [5, 0]);self.assertEqual([t['leadingSilenceFrames'] for t in result['tracks']], [0, 5])
        result, directory, actual = self.check_exact([100, 200, 300], [50, 60, 70, 80, 90], 1, 1, 1, 0, 1, 'narration')
        self.assertEqual(actual, [50, 160, 270, 380]);self.assertEqual(result['tracks'][1]['truncatedSourceFrames'], 1);self.assertEqual(result['tracks'][1]['outputEndFrame'], 4)

    def test_signed_rounding_and_ties_follow_nearest_with_either_neighbour_at_a_tie(self):
        values = [5, -5, 3, -3, 1, -1, 0, 32767, -32768, 2, -2]
        result, directory, actual = self.check_exact(values, [0] * len(values), 0.5, 1)
        self.assertEqual([actual[7], actual[8]], [16384, -16384])
        for exact, got in zip([2.5, -2.5, 1.5, -1.5, .5, -.5, 0, 16383.5, -16384, 1, -1], actual): self.assertLessEqual(abs(got - exact), 0.5)
        self.assertEqual(result['maxMixErrorExact'], '1/2')

    def test_extremes_that_fit_are_accepted_and_overrange_is_refused_before_native(self):
        document, directory = self.run_case([32767, -32768, 100], [0, 0, 0], 1, 1)
        self.assertEqual(a.run(document, directory, executable=str(self.exe), timeout=60)['peakPCM16'], 32768)
        document, directory = self.run_case([20000, -20000], [12767, -12768], 1, 1);self.assertTrue(a.run(document, directory, executable=str(self.exe), timeout=60)['verified'])
        cases = {'sum': ([20000, 0], [12768, 0], 1, 1, '$'), 'negative sum': ([-20000, 0], [-12769, 0], 1, 1, '$'), 'term at gain 4': ([8192, 0], [0, 0], 4, 1, '$.narration.gain'),
                 'term cancels in sum': ([30000, 0], [-30000, 0], 4, 4, '$.narration.gain'), 'background term': ([0, 0], [-8193, 0], 1, 4, '$.background.gain')}
        for name, (n, b, g_n, g_b, location) in cases.items():
            with self.subTest(name):
                self.mode('good');document, directory = self.run_case(n, b, g_n, g_b)
                self.fault(lambda: a.run(document, directory, executable=str(self.exe), timeout=60), 'AUDIO_CLIPPING', location)
                self.assertFalse((self.exe.parent / 'launched').exists());self.assertFalse((directory / 'pad-0-launcher.py').exists())
        document, directory = self.run_case([1, 2], [0, 0, 0, 0] + [32767], 1, 1, 0, 0, policy='narration')
        self.assertTrue(a.run(document, directory, executable=str(self.exe), timeout=60)['verified'])
        document, directory = self.run_case([10, 0, 0], [0, 0, 0, 0, 30000], 1, 1, 0, 0, policy='narration');document['background']['gain'] = 2
        self.fault(lambda: a.run(document, directory, executable=str(self.exe), timeout=60), 'AUDIO_CLIPPING', '$.background.gain')

    def test_format_bounds_and_resource_refusals_happen_before_any_native_process(self):
        cases = [('rate', dict(rate_b=16000), 'AUDIO_FORMAT_MISMATCH', '$.background.source'), ('channels', dict(channels_b=2), 'AUDIO_FORMAT_MISMATCH', '$.background.source'),
                 ('background after narration end', dict(off_b=3, policy='narration'), 'AUDIO_SOURCE_BOUNDS', '$.background.offsetFrames'),
                 ('span', dict(off_b=262144), 'AUDIO_RESOURCE_LIMIT', '$')]
        for name, extra, code, location in cases:
            with self.subTest(name):
                self.mode('good');document, directory = self.run_case([1, 2, 3], [4, 5, 6, 7], **extra)
                if name == 'channels':
                    document, directory = self.run_case([1, 2, 3, 4], [4, 5, 6, 7], channels=2, channels_b=1)
                self.fault(lambda: a.run(document, directory, executable=str(self.exe), timeout=60), code, location)
                self.assertFalse((self.exe.parent / 'launched').exists())
        document, directory = self.run_case([1, 2, 3], [4, 5, 6, 7], off_b=3, policy='longest');self.assertTrue(a.run(document, directory, executable=str(self.exe), timeout=60)['verified'])
        self.mode('good');document, directory = self.run_case([1, 2, 3], [4, 5, 6, 7], off_n=0, off_b=2, policy='narration');self.assertTrue(a.run(document, directory, executable=str(self.exe), timeout=60)['verified'])

    def test_unsupported_sources_are_refused_with_distinct_faults(self):
        document, directory = self.run_case([1, 2], [3, 4]);Path(document['narration']['source']).write_bytes(b'RIFF')
        self.fault(lambda: a.run(document, directory, executable=str(self.exe), timeout=60), 'INVALID_AUDIO_DATA')
        document, directory = self.run_case([1, 2], [3, 4]);Path(document['background']['source']).unlink()
        self.fault(lambda: a.run(document, directory, executable=str(self.exe), timeout=60), 'INVALID_AUDIO_SOURCE', str(Path(document['background']['source'])))
        document, directory = self.run_case([1, 2], [3, 4]);self.fault(lambda: a.run(document, directory, executable='/no/such/sox', timeout=60), 'INTERPRETER_NOT_FOUND')
        self.fault(lambda: a.run(document, self.root / 'x', executable=str(self.exe), timeout=0), 'INVALID_ARGUMENT')

    def test_native_misbehaviour_is_rejected_even_when_the_native_exit_is_zero(self):
        for mode in ('off1', 'swap-gain', 'ignore-gain', 'short', 'mono', 'noise', 'stdout', 'pad-short', 'invert'):
            with self.subTest(mode):
                self.mode(mode);document, directory = self.run_case(tone(30, 2, 9000), tone(44, 2, 5000, 1), 0.5, 0.25, 3, 1, 2, 'longest')
                self.fault(lambda: a.run(document, directory, executable=str(self.exe), timeout=60), 'VERIFICATION_FAILED')
                self.assertEqual(json.loads((directory / 'result.json').read_text())['status'], 'failed')

    def test_unsuitable_runtime_is_rejected_before_any_stage(self):
        wrong = self.root / 'wrong-sox.py';marker = self.root / 'processed'
        wrong.write_text('#!' + sys.executable + '\nimport sys\nfrom pathlib import Path\nif sys.argv[1:]==["--version"]: print(sys.argv[0]+": SoX v14.4.1")\nelse: Path(' + repr(str(marker)) + ').touch()\n');wrong.chmod(0o700)
        document, directory = self.run_case([1, 2], [3, 4])
        self.fault(lambda: a.run(document, directory, executable=str(wrong), timeout=10), 'UNSUPPORTED_NATIVE_VERSION');self.assertFalse(marker.exists());self.assertFalse((directory / 'pad-0-submission.json').exists())

    def test_reusable_inputs_track_both_source_bytes(self):
        document, directory = self.run_case([1, 2], [3, 4]);before = a.reusableInputs(document);self.assertEqual(sorted(before), ['0', '1']);self.assertEqual(before, a.reusableInputs(document))
        Path(document['background']['source']).write_bytes(wav([3, 5], 1, 8000));after = a.reusableInputs(document)
        self.assertEqual((after['0'], after['1'] == before['1']), (before['0'], False))
        Path(document['narration']['source']).write_bytes(wav([9, 2], 1, 8000));self.assertNotEqual(a.reusableInputs(document)['0'], before['0'])
        Path(document['narration']['source']).write_bytes(wav([30000, 2], 1, 8000));document['narration']['gain'] = 4
        self.fault(lambda: a.reusableInputs(document), 'AUDIO_CLIPPING')


class MixForgeries(unittest.TestCase):
    """Stub-native run directory; every probe refreshes digests so only the contract can reject it."""
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory();root = Path(cls.temporary.name);cls.root = root
        exe = root / 'sox';exe.write_text(FAKE_MIX % {'python': sys.executable});exe.chmod(0o700)
        cls.narration = tone(40, 2, 9000);cls.background = tone(60, 2, 5000, 1)
        (root / 'n.wav').write_bytes(wav(cls.narration, 2, 16000));(root / 'b.wav').write_bytes(wav(cls.background, 2, 16000))
        cls.document = {'version': a.VERSION, 'operation': 'mix', 'narration': {'source': str(root / 'n.wav'), 'gain': 0.8, 'offsetFrames': 5},
                        'background': {'source': str(root / 'b.wav'), 'gain': 0.25, 'offsetFrames': 0}, 'durationPolicy': 'longest'}
        cls.directory = root / 'run';cls.result = a.run(cls.document, cls.directory, executable=str(exe), timeout=60)
        cls.other = root / 'other';a.run({**cls.document, 'durationPolicy': 'narration'}, cls.other, executable=str(exe), timeout=60)

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
        d = self.directory;receipt = a.read(d, 'verification.json');receipt['artifacts'] = a.artifacts(d)
        receipt['evidence'] = {n: a.digest(d, n) for n in receipt['evidence']};a.atomic_json(d / 'verification.json', receipt);finalise(d)

    def rebind(self, stage, name):
        d = self.directory;bindings = a.read(d, stage + '-inputs.json');bindings[str(d / name)] = a.digest(d, name);a.atomic_json(d / (stage + '-inputs.json'), bindings)

    def put(self, name, value): (self.directory / name).write_bytes(value)

    def test_baseline_reopens_and_states_the_timeline(self):
        result = a.verify(self.directory);self.assertTrue(result['verified']);self.assertEqual(result['frames'], 60);self.assertEqual(result['durationPolicy'], 'longest')
        self.assertEqual([(t['role'], t['gainExact'], t['offsetFrames'], t['outputStartFrame'], t['outputEndFrame']) for t in result['tracks']], [('narration', '4/5', 5, 5, 45), ('background', '1/4', 0, 0, 60)])
        self.assertEqual((result['overlapFrames'], result['overlapStartFrame'], result['uncoveredFrames'], result['samplesCompared']), (40, 5, 0, 120))
        self.assertFalse(result['timeline']['originalTimestampsPreserved']);self.assertEqual(result['durationExact'], {'numerator': 3, 'denominator': 800})
        self.assertEqual(self.result['status'] if 'status' in self.result else 'succeeded', 'succeeded')

    def test_forged_output_samples_with_refreshed_hashes(self):
        d = self.directory;good = a.pcm((d / 'audio.wav').read_bytes())[1]
        variants = {'silence': [0] * len(good), 'inverted': [-v for v in good], 'shifted': good[2:] + [0, 0], 'one sample +1': [v + (1 if i == 77 else 0) for i, v in enumerate(good)],
                    'single zeroed': [0 if i == 5 else v for i, v in enumerate(good)], 'all +1': [v + 1 for v in good],
                    'swapped channels': [v for pair in zip(good[1::2], good[0::2]) for v in pair], 'narration only': ([0] * 10 + [round(v * 0.8) for v in self.narration] + [0] * 20)[:len(good)]}
        for name, forged in variants.items():
            with self.subTest(name):
                self.put('audio.wav', wav(forged, 2, 16000));self.refresh();self.assertEqual(self.fault().location, 'audio.wav');self.put('audio.wav', self.saved[d / 'audio.wav'])
        for name, forged in {'extra frame': wav(good + good[-2:], 2, 16000), 'one frame short': wav(good[:-2], 2, 16000), 'wrong rate': wav(good, 2, 8000), 'mono': wav(good, 1, 16000)}.items():
            with self.subTest(name): self.put('audio.wav', forged);self.refresh();self.fault();self.put('audio.wav', self.saved[d / 'audio.wav'])
        original = self.saved[d / 'audio.wav'];info = b'INFOICMT' + struct.pack('<I', 8) + b'injected'
        self.put('audio.wav', riff(original[12:36], pad(b'LIST' + struct.pack('<I', len(info)) + info), original[36:]));self.refresh();self.fault()

    def test_forged_padded_intermediates_with_refreshed_hashes(self):
        d = self.directory
        for name in ('pad-0.wav', 'pad-1.wav'):
            good = a.pcm((d / name).read_bytes())[1]
            for label, forged in {'zeroed': [0] * len(good), 'shifted': good[2:] + [0, 0], 'lead removed': good[2 * 5:] + [0] * 10, 'one sample': [v + (1 if i == 40 else 0) for i, v in enumerate(good)]}.items():
                with self.subTest(name + label):
                    self.put(name, wav(forged, 2, 16000));self.rebind('mix', name);self.refresh();self.fault();self.put(name, self.saved[d / name]);self.rebind('mix', name)

    def test_forged_summary_result_plan_capture_and_receipt_fields(self):
        d = self.directory;summary = a.read(d, 'audio-summary.json')
        edits = {'frames': lambda s: s.update(frames=s['frames'] + 1), 'gain type': lambda s: s['tracks'][0].update(gain=0.8000001), 'exact gain': lambda s: s['tracks'][1].update(gainExact='1/3'),
                 'offset': lambda s: s['tracks'][0].update(offsetFrames=6), 'policy': lambda s: s.update(durationPolicy='narration'), 'sha': lambda s: s['tracks'][0].update(sourceSha256='0' * 64),
                 'overlap': lambda s: s.update(overlapFrames=41), 'peak': lambda s: s.update(peakPCM16=1), 'compared': lambda s: s.update(samplesCompared=121), 'error': lambda s: s.update(maxMixErrorExact='0/1'),
                 'claim removed': lambda s: s.pop('limits'), 'extra claim': lambda s: s.update(loudness='measured'), 'timeline': lambda s: s['timeline'].update(originalTimestampsPreserved=True),
                 'int as bool': lambda s: s['tracks'][1].update(offsetFrames=False), 'float as int': lambda s: s.update(frames=60.0)}
        for name, edit in edits.items():
            with self.subTest(name):
                forged = copy.deepcopy(summary);edit(forged);a.atomic_json(d / 'audio-summary.json', forged);self.refresh();self.fault();a.atomic_json(d / 'audio-summary.json', summary)
        result = a.read(d, 'result.json');a.atomic_json(d / 'result.json', {**result, 'frames': 61});finalise(d);self.fault();a.atomic_json(d / 'result.json', result)
        plan = a.read(d, 'plan.json');plan['narration']['gain'] = 1;a.atomic_json(d / 'plan.json', plan);self.refresh();self.fault();a.atomic_json(d / 'plan.json', json.loads(self.saved[d / 'plan.json']))
        authored = a.read(d, 'authored.json');authored['durationPolicy'] = 'narration';a.atomic_json(d / 'authored.json', authored);self.refresh();self.fault();a.atomic_json(d / 'authored.json', json.loads(self.saved[d / 'authored.json']))
        captures = a.read(d, 'captures.json');captures[1]['sha256'] = '1' * 64;a.atomic_json(d / 'captures.json', captures);self.refresh();self.fault();a.atomic_json(d / 'captures.json', json.loads(self.saved[d / 'captures.json']))
        receipt = a.read(d, 'verification.json');a.atomic_json(d / 'verification.json', {**receipt, 'extra': 1});self.fault();a.atomic_json(d / 'verification.json', receipt)

    def test_stale_or_foreign_receipt_and_changed_captured_source_are_rejected(self):
        d = self.directory;foreign = a.read(self.other, 'verification.json');a.atomic_json(d / 'verification.json', foreign);self.fault()
        a.atomic_json(d / 'verification.json', json.loads(self.saved[d / 'verification.json']))
        forged = wav([v // 2 for v in self.narration], 2, 16000);self.put('captured-0.wav', forged);self.rebind('pad-0', 'captured-0.wav');self.refresh();self.fault()
        self.put('captured-0.wav', self.saved[d / 'captured-0.wav']);self.rebind('pad-0', 'captured-0.wav')
        bg = wav([min(v + 1, 20000) for v in self.background], 2, 16000);self.put('captured-1.wav', bg);self.rebind('pad-1', 'captured-1.wav');self.refresh();self.fault()
        self.put('captured-1.wav', self.saved[d / 'captured-1.wav']);self.rebind('pad-1', 'captured-1.wav')
        loud = wav([32767] * len(self.narration), 2, 16000);self.put('captured-0.wav', loud);self.rebind('pad-0', 'captured-0.wav');self.refresh();self.fault()

    def test_forged_launcher_command_submission_and_native_output(self):
        d = self.directory
        launcher = (d / 'mix-launcher.py').read_text();(d / 'mix-launcher.py').write_text(launcher.replace('0.25', '0.5'));self.refresh();self.fault();(d / 'mix-launcher.py').write_text(launcher)
        submission = a.read(d, 'pad-0-submission.json');a.atomic_json(d / 'pad-0-submission.json', {**submission, 'exitCode': 1});self.refresh();self.fault();a.atomic_json(d / 'pad-0-submission.json', submission)
        for stage in ('pad-0', 'pad-1', 'mix'):
            for stream in ('stdout', 'stderr'):
                with self.subTest(stage + stream):
                    (d / f'{stage}.{stream}').write_text('x');self.refresh();self.fault();(d / f'{stage}.{stream}').write_bytes(self.saved[d / f'{stage}.{stream}'])

    def test_membership_is_exact(self):
        d = self.directory
        for name in ('extra.wav', 'pad-2.wav', 'clip-0.wav', 'normalise-launcher.py', 'conform.stdout'):
            with self.subTest(name): (d / name).write_bytes(b'x');self.refresh();self.assertIn(name, self.fault().message);(d / name).unlink()
        (d / 'pad-0.wav').unlink();self.fault();
        link = d / 'link.wav';link.symlink_to(d / 'audio.wav');self.fault();link.unlink()


if __name__ == '__main__': unittest.main()
