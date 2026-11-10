#!/usr/bin/env python3
"""Native acceptance of the SoX two-track `mix` operation with an oracle independent of the adaptor.

Fixtures are analytic or integer patterns written with `wave`/`struct`. Every expected
output sample is computed here with `fractions.Fraction` from the stated rule: the exact
sum of gain*sample for each track present, rounded to the nearest PCM16 integer (an exact
tie accepts either neighbour; the observed tie direction is reported). Nothing in this
module calls the adaptor's header parser, gain arithmetic, layout or summary code to decide
whether native output is right; the adaptor is only driven (run/verify) and its refusals are
checked. A native exit status alone is never acceptance. Fixtures stay tiny: at most a few
thousand frames, apart from one 65536-frame value sweep.
"""
import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import random
import resource
import shutil
import struct
import sys
import threading
import time
import wave

from schemaxis import workflow
from schemaxis.adaptors.sox import adaptor as a
from schemaxis.artifacts import atomic_json
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis.publication_metadata import finalise

ROOT = Path(__file__).resolve().parents[1]
LOW, HIGH = -32768, 32767


def read(path):
    """((rate, channels, frames), samples); wave plus the canonical 44-byte size rule."""
    path = Path(path)
    with wave.open(str(path), 'rb') as stream:
        assert stream.getsampwidth() == 2 and stream.getcomptype() == 'NONE'
        info = (stream.getframerate(), stream.getnchannels(), stream.getnframes())
        raw = stream.readframes(stream.getnframes() + 1)
    values = list(struct.unpack('<' + 'h' * (len(raw) // 2), raw))
    assert len(values) == info[1] * info[2]
    assert path.stat().st_size == 44 + 2 * len(values), 'output is not a canonical 44-byte-header WAV'
    return info, values


def write(path, rate, channels, values):
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes(struct.pack('<' + 'h' * len(values), *values))


def refused(action, code):
    try: action()
    except SchemaxisError as error:
        assert error.fault.code == code, error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('invalid mix input accepted')


def tone(frames, channels, amplitude, shift=0):
    return [int(amplitude * math.sin(0.0371 * i + c * 1.3 + shift)) for i in range(frames) for c in range(channels)]


def expected(narration, background, g_n, g_b, off_n, off_b, channels, policy):
    """Exact mixed values (Fractions) for every output scalar sample."""
    n_frames, b_frames = len(narration) // channels, len(background) // channels
    end_n, end_b = off_n + n_frames, off_b + b_frames
    total = max(end_n, end_b) if policy == 'longest' else end_n
    gn, gb = Fraction(str(g_n)), Fraction(str(g_b))
    out = []
    for frame in range(total):
        for c in range(channels):
            n = narration[(frame - off_n) * channels + c] if off_n <= frame < end_n else 0
            b = background[(frame - off_b) * channels + c] if off_b <= frame < end_b else 0
            out.append(gn * n + gb * b)
    return out


def compare(actual, exact):
    """Every sample nearest to its exact value; returns tie directions counted ('up' = half toward +infinity)."""
    assert len(actual) == len(exact), (len(actual), len(exact))
    ties = {'up': 0, 'down': 0}
    for index, (got, want) in enumerate(zip(actual, exact)):
        assert LOW <= want <= HIGH, 'oracle value out of range'
        distance = abs(got - want)
        assert distance <= Fraction(1, 2), (index, got, str(want))
        if distance == Fraction(1, 2): ties['up' if got > want else 'down'] += 1
    return ties


def document(directory, narration, background, g_n, g_b, off_n, off_b, policy, name):
    paths = {}
    for role, (rate, channels, values) in (('narration', narration), ('background', background)):
        paths[role] = directory / f'{name}-{role}.wav'
        write(paths[role], rate, channels, values)
    return {'version': a.VERSION, 'operation': 'mix', 'narration': {'source': str(paths['narration']), 'gain': g_n, 'offsetFrames': off_n},
            'background': {'source': str(paths['background']), 'gain': g_b, 'offsetFrames': off_b}, 'durationPolicy': policy}


def check(root, sox, name, rate, channels, narration, background, g_n=1, g_b=1, off_n=0, off_b=0, policy='longest'):
    """Run natively, reopen with this module's own reader and compare every output sample."""
    doc = document(root, (rate, channels, narration), (rate, channels, background), g_n, g_b, off_n, off_b, policy, name)
    directory = root / ('run-' + name)
    result = a.run(doc, directory, executable=sox, timeout=60)
    exact = expected(narration, background, g_n, g_b, off_n, off_b, channels, policy)
    info, actual = read(directory / 'audio.wav')
    assert info == (rate, channels, len(exact) // channels), info
    ties = compare(actual, exact)
    assert result['samplesCompared'] == len(exact) and a.verify(directory)['verified']
    # Padded intermediates are exact copies with leading silence.
    for role, off, values in (('0', off_n, narration), ('1', off_b, background)):
        _, padded = read(directory / f'pad-{role}.wav')
        assert padded == [0] * (off * channels) + values, 'pad stage is not exact placement'
    return {'case': name, 'rate': rate, 'channels': channels, 'policy': policy, 'offsets': [off_n, off_b], 'gains': [g_n, g_b], 'frames': info[2], 'samples': len(actual), 'ties': ties}, directory, actual


def kit_case(directory, doc):
    """Independent oracle for a retained development-kit mix run (used by tools/qualify_sox.py).

    The captured tracks are bound to the case document's source bytes, then every output
    scalar sample is compared with the exact gained sum computed here, as in `check`.
    """
    directory = Path(directory)
    assert doc['operation'] == 'mix', doc['operation']
    for index, role in enumerate(('narration', 'background')):
        assert (directory / f'captured-{index}.wav').read_bytes() == Path(doc[role]['source']).read_bytes(), role + ' capture is not the declared source'
    (rate, channels, _), narration = read(directory / 'captured-0.wav')
    (b_rate, b_channels, _), background = read(directory / 'captured-1.wav')
    assert (rate, channels) == (b_rate, b_channels), 'kit case mixes different formats'
    off_n, off_b = doc['narration'].get('offsetFrames', 0), doc['background'].get('offsetFrames', 0)
    exact = expected(narration, background, doc['narration'].get('gain', 1), doc['background'].get('gain', 1), off_n, off_b, channels, doc['durationPolicy'])
    info, actual = read(directory / 'audio.wav')
    assert info == (rate, channels, len(exact) // channels), info
    ties = compare(actual, exact)
    for role, off, values in (('0', off_n, narration), ('1', off_b, background)):
        _, padded = read(directory / f'pad-{role}.wav')
        assert padded == [0] * (off * channels) + values, 'pad stage is not exact placement'
    return {'rate': rate, 'channels': channels, 'frames': info[2], 'samples': len(actual), 'policy': doc['durationPolicy'], 'offsets': [off_n, off_b], 'ties': ties}


def matrix(root, sox):
    """Mono/stereo, four rates, both policies, offsets (none, small, past the end, equal), gains with ties and fractions."""
    cases = []
    for rate, channels in ((8000, 1), (22050, 2), (44100, 1), (192000, 2)):
        narration, background = tone(300, channels, 11000), tone(480, channels, 7000, 1)
        for policy in ('longest', 'narration'):
            for off_n, off_b in ((0, 0), (40, 0), (0, 120), (500, 3), (200, 0)):
                for g_n, g_b in ((1, 0.25), (0.5, 0.5), (0.7, 0.3), (1.2345, 0.0001), (0, 1)):
                    if policy == 'narration' and off_b >= off_n + 300: continue
                    cases.append(check(root, sox, f'm{len(cases)}-{rate}-{channels}-{policy}', rate, channels, narration, background, g_n, g_b, off_n, off_b, policy)[0])
    return {'cases': len(cases), 'samples': sum(c['samples'] for c in cases), 'ties': {k: sum(c['ties'][k] for c in cases) for k in ('up', 'down')}}


def extremes(root, sox):
    """PCM16 extrema, sign and tie handling with gains that keep every term and sum representable."""
    report = []
    values = [LOW, HIGH, 0, 1, -1, 2, -2, 3, -3, 5, -5, 32766, -32767, 16383, -16384, 16384]
    for index, (g_n, g_b) in enumerate(((1, 0), (0, 1), (0.5, 0), (0.5, 0.5), (0.25, 0.75), (0.0001, 1), (1, 0.0001), (0.3333, 0.6667))):
        report.append(check(root, sox, f'extreme-{index}', 8000, 1, values, list(reversed(values)), g_n, g_b)[0])
    ties = check(root, sox, 'ties', 8000, 1, [5, -5, 3, -3, 1, -1, 7, -7, 9, -9], [0] * 10, 0.5, 1)[0]
    assert ties['ties']['up'] == 10 and ties['ties']['down'] == 0, ties
    report.append(ties)
    # Boundary sums exactly at full scale are accepted.
    report.append(check(root, sox, 'full-scale-sum-positive', 8000, 1, [20000], [12767], 1, 1)[0])
    report.append(check(root, sox, 'full-scale-sum-negative', 8000, 1, [-20000], [-12768], 1, 1)[0])
    report.append(check(root, sox, 'gain-four-boundary', 8000, 1, [8191, -8192], [0, 0], 4, 1)[0])
    return report


def sweeps(root, sox):
    """Every PCM16 value at several gains, then random value pairs whose gained sum is in range."""
    full = list(range(LOW, HIGH + 1))
    report = []
    for g_n, g_b in ((1, 0), (0.5, 0), (0.0001, 0), (0.3333, 0), (0.9999, 0)):
        entry, directory, _ = check(root, sox, f'sweep-{g_n}', 8000, 1, full, [0], g_n, g_b)
        report.append(entry); shutil.rmtree(directory)
    rng = random.Random(61)
    for g_n, g_b in ((0.5, 0.5), (0.3333, 0.6667), (0.1, 0.9)):
        n, b = [rng.randint(LOW, HIGH) for _ in range(40000)], [rng.randint(LOW, HIGH) for _ in range(40000)]
        entry, directory, _ = check(root, sox, f'pairs-{g_n}', 16000, 1, n, b, g_n, g_b)
        report.append(entry); shutil.rmtree(directory)
    return report


def refusals(root, sox):
    """Each refusal happens before any native stage: no stage launcher exists in the run directory."""
    seven = [1000, -1000, 7, 9]
    cases = {
        'term clips at gain 4': (document(root, (8000, 1, [8192]), (8000, 1, [0]), 4, 1, 0, 0, 'longest', 'r1'), 'AUDIO_CLIPPING'),
        'sum clips positive': (document(root, (8000, 1, [20000]), (8000, 1, [12768]), 1, 1, 0, 0, 'longest', 'r2'), 'AUDIO_CLIPPING'),
        'sum clips negative': (document(root, (8000, 1, [-20000]), (8000, 1, [-12769]), 1, 1, 0, 0, 'longest', 'r3'), 'AUDIO_CLIPPING'),
        'cut background tail would clip': (document(root, (8000, 1, [5, 5]), (8000, 1, [0, 0, 20000]), 1, 2, 0, 0, 'narration', 'r4'), 'AUDIO_CLIPPING'),
        'rate mismatch': (document(root, (8000, 1, seven), (16000, 1, seven), 1, 1, 0, 0, 'longest', 'r5'), 'AUDIO_FORMAT_MISMATCH'),
        'channel mismatch': (document(root, (8000, 2, seven), (8000, 1, seven), 1, 1, 0, 0, 'longest', 'r6'), 'AUDIO_FORMAT_MISMATCH'),
        'background after narration end': (document(root, (8000, 1, seven), (8000, 1, seven), 1, 1, 0, 4, 'narration', 'r7'), 'AUDIO_SOURCE_BOUNDS'),
        'span beyond limit': (document(root, (8000, 1, seven), (8000, 1, seven), 1, 1, 262144, 0, 'longest', 'r8'), 'AUDIO_RESOURCE_LIMIT'),
        'gain precision': (document(root, (8000, 1, seven), (8000, 1, seven), 1, 0.12345, 0, 0, 'longest', 'r9'), 'INVALID_ARGUMENT'),
        'gain above four': (document(root, (8000, 1, seven), (8000, 1, seven), 4.0001, 1, 0, 0, 'longest', 'r10'), 'INVALID_ARGUMENT'),
        'negative offset': (document(root, (8000, 1, seven), (8000, 1, seven), 1, 1, -1, 0, 'longest', 'r11'), 'INVALID_ARGUMENT'),
        'unknown policy': (document(root, (8000, 1, seven), (8000, 1, seven), 1, 1, 0, 0, 'shortest', 'r12'), 'INVALID_ARGUMENT')}
    missing = document(root, (8000, 1, seven), (8000, 1, seven), 1, 1, 0, 0, 'longest', 'r13'); del missing['durationPolicy']
    cases['missing policy'] = (missing, 'MISSING_ARGUMENT')
    (root / 'garbage.wav').write_bytes(b'RIFF0000WAVE')
    garbage = document(root, (8000, 1, seven), (8000, 1, seven), 1, 1, 0, 0, 'longest', 'r14'); garbage['background']['source'] = str(root / 'garbage.wav')
    cases['malformed source'] = (garbage, 'INVALID_AUDIO_DATA')
    absent = document(root, (8000, 1, seven), (8000, 1, seven), 1, 1, 0, 0, 'longest', 'r15'); absent['narration']['source'] = str(root / 'absent.wav')
    cases['absent source'] = (absent, 'INVALID_AUDIO_SOURCE')
    outcome = {}
    for index, (name, (doc, code)) in enumerate(cases.items()):
        directory = root / f'refused-{index}'
        outcome[name] = refused(lambda: a.run(doc, directory, executable=sox, timeout=30), code)['code']
        assert not any(directory.glob('*-launcher.py')), 'native stage launched for a refused mix: ' + name
        # Declaration/plan faults precede any run directory; later refusals leave an unverified result.
        if directory.exists(): assert json.loads((directory / 'result.json').read_text())['verified'] is False
    return outcome


def forgeries(root, sox):
    """Tamper with a genuine native run, refreshing digests so only the semantic contract can reject it."""
    n, b = tone(120, 2, 9000), tone(200, 2, 5000, 2)
    entry, directory, good = check(root, sox, 'forge', 16000, 2, n, b, 0.8, 0.25, 5, 0)
    other = check(root, sox, 'forge-other', 16000, 2, n, b, 0.8, 0.25, 5, 0, 'narration')[1]
    saved = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}

    def restore():
        for path in list(directory.rglob('*')):
            if path.is_file() and path not in saved: path.unlink()
        for path, content in saved.items(): path.write_bytes(content)

    def refresh():
        receipt = a.read(directory, 'verification.json'); receipt['artifacts'] = a.artifacts(directory)
        receipt['evidence'] = {name: a.digest(directory, name) for name in receipt['evidence']}
        atomic_json(directory / 'verification.json', receipt); finalise(directory)

    def rebind(stage, name):
        bindings = a.read(directory, stage + '-inputs.json'); bindings[str(directory / name)] = a.digest(directory, name); atomic_json(directory / (stage + '-inputs.json'), bindings)

    rejected = {}
    def probe(name):
        refused(lambda: a.verify(directory), 'VERIFICATION_FAILED'); rejected[name] = True; restore()
    for name, forged in {'silence': [0] * len(good), 'inverted': [-v for v in good], 'one sample': [v + (1 if i == 99 else 0) for i, v in enumerate(good)],
                         'shifted by one frame': good[2:] + [0, 0], 'swapped channels': [v for pair in zip(good[1::2], good[0::2]) for v in pair],
                         'gains ignored': [min(HIGH, max(LOW, x + y)) for x, y in zip([0] * 10 + n + [0] * 150, b)],
                         'wrong length': good[:-2], 'long': good + good[-2:]}.items():
        write(directory / 'audio.wav', 16000, 2, forged); refresh(); probe('output ' + name)
    for name in ('pad-0.wav', 'pad-1.wav'):
        _, padded = read(directory / name)
        write(directory / name, 16000, 2, padded[2:] + [0, 0]); rebind('mix', name); refresh(); probe('placement ' + name)
    summary = a.read(directory, 'audio-summary.json')
    for name, edit in {'frames': lambda s: s.update(frames=s['frames'] + 1), 'gain': lambda s: s['tracks'][0].update(gainExact='1/1'), 'offset': lambda s: s['tracks'][0].update(offsetFrames=0),
                       'policy': lambda s: s.update(durationPolicy='narration'), 'overlap': lambda s: s.update(overlapFrames=0), 'extra claim': lambda s: s.update(loudness='-23 LUFS')}.items():
        forged = json.loads(json.dumps(summary)); edit(forged); atomic_json(directory / 'audio-summary.json', forged); refresh(); probe('summary ' + name)
    atomic_json(directory / 'verification.json', a.read(other, 'verification.json')); probe('foreign receipt')
    (directory / 'captured-0.wav').write_bytes((directory / 'captured-0.wav').read_bytes()[:50] + b'\x07\x00' + (directory / 'captured-0.wav').read_bytes()[52:])
    rebind('pad-0', 'captured-0.wav'); refresh(); probe('changed captured narration')
    (directory / 'mix.stderr').write_text('sox WARN: mix-combining clipped 2 samples'); refresh(); probe('native warning')
    (directory / 'stray.wav').write_bytes(b'x'); refresh(); probe('unreferenced member')
    assert a.verify(directory)['verified']
    return rejected


def changed_sources_and_workflow(root, sox):
    """Source bytes invalidate reuse; a verified workflow resumes only while both captured sources are unchanged."""
    locations = {'sox': sox}
    n, b = tone(200, 1, 9000), tone(300, 1, 5000, 1)
    doc = document(root, (8000, 1, n), (8000, 1, b), 1, 0.25, 20, 0, 'longest', 'wf')
    before = a.reusableInputs(doc)
    graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'overlay', 'document': doc}]}
    first = workflow.execute(graph, root / 'workflow', locations=locations, timeout=60)
    assert first['status'] == 'succeeded', first['status']
    with location_context(locations): assert workflow.verify(root / 'workflow')['verified']
    second = workflow.execute(graph, root / 'workflow', locations=locations, timeout=60, resume=True)
    assert all(job['reused'] for job in second['jobs'])
    out = sorted((root / 'workflow').rglob('audio.wav'))[-1]
    _, actual = read(out); compare(actual, expected(n, b, 1, 0.25, 20, 0, 1, 'longest'))
    report = {'status': first['status'], 'unchangedResumeReused': True}
    for role in ('background', 'narration'):
        source = Path(doc[role]['source']); data = bytearray(source.read_bytes()); data[60] ^= 0x10; source.write_bytes(bytes(data))
        changed = a.reusableInputs(doc)
        assert changed != before and changed[str(('narration', 'background').index(role))] != before[str(('narration', 'background').index(role))]
        third = workflow.execute(graph, root / 'workflow', locations=locations, timeout=60, resume=True)
        assert not third['jobs'][0]['reused'], role
        report[role + 'ChangeReused'] = False
        before = changed
    new_out = sorted((root / 'workflow').rglob('audio.wav'))[-1]  # latest retained attempt
    n2, b2 = read(Path(doc['narration']['source']))[1], read(Path(doc['background']['source']))[1]
    compare(read(new_out)[1], expected(n2, b2, 1, 0.25, 20, 0, 1, 'longest'))
    handoff = {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'tidy', 'document': {'version': 'schemaxis.sox/1', 'operation': 'normalise', 'source': doc['narration']['source'], 'targetPeak': 20000, 'maxGain': 8}},
        {'id': 'overlay', 'document': {**doc, 'narration': {**doc['narration'], 'source': {'$artifact': 'tidy', 'index': 0}}}}]}
    passed = workflow.execute(handoff, root / 'handoff', locations=locations, timeout=90)
    assert passed['status'] == 'succeeded', passed['status']
    with location_context(locations): assert workflow.verify(root / 'handoff')['verified']
    report['handoff'] = {'status': passed['status'], 'verified': True}
    return report


def lifecycle(root, sox):
    """Deterministic wrappers prove timeout and cancellation of an owned stage; they are not native audio evidence."""
    n, b = tone(50, 1, 9000), tone(70, 1, 5000)
    doc = document(root, (8000, 1, n), (8000, 1, b), 1, 1, 0, 0, 'longest', 'life')
    wrapper = root / 'slow-runtime.py'; marker = root / 'slow.pid'
    wrapper.write_text('#!' + sys.executable + '\nimport os,time\nfrom pathlib import Path\nPath(' + repr(str(marker)) + ').write_text(str(os.getpid()))\ntime.sleep(30)\n'); wrapper.chmod(0o700)
    outcomes = {}
    for action in ('timeout', 'cancel'):
        if marker.exists(): marker.unlink()
        cancel = threading.Event()
        def trigger():
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline: time.sleep(.01)
            if marker.exists(): cancel.set()
        thread = threading.Thread(target=trigger, daemon=True) if action == 'cancel' else None
        if thread: thread.start()
        try:
            with allocation({'threads': 1, 'ranks': 1}, cancel):
                outcomes[action] = refused(lambda: a.run(doc, root / ('inflight-' + action), executable=str(wrapper), timeout=8 if thread else .4), 'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')['code']
        finally:
            if thread: thread.join(6)
        assert marker.exists(), 'lifecycle probe did not launch an owned child'
        try: os.kill(int(marker.read_text()), 0)
        except ProcessLookupError: pass
        else: raise AssertionError('owned process survived ' + action)
        assert json.loads((root / ('inflight-' + action) / 'result.json').read_text())['verified'] is False
    return outcomes


def examples(root, sox, repository):
    """The shipped baseline and variant examples on their tiny fixtures, with every sample compared."""
    report = {}
    for name, nf, bf in (('baseline', 'narration-mono8k.wav', 'background-mono8k.wav'), ('narration-policy', 'narration-stereo16k.wav', 'background-stereo16k.wav')):
        doc = json.loads((repository / f'examples/schemaxis/sox-mix-{name}.json').read_text())
        doc['narration']['source'] = str(repository / 'examples/schemaxis/sox-mix-fixtures' / nf)
        doc['background']['source'] = str(repository / 'examples/schemaxis/sox-mix-fixtures' / bf)
        directory = root / ('example-' + name); a.run(doc, directory, executable=sox, timeout=60)
        (rate, channels, _), n = read(doc['narration']['source']); _, b = read(doc['background']['source'])
        info, actual = read(directory / 'audio.wav')
        ties = compare(actual, expected(n, b, doc['narration']['gain'], doc['background']['gain'], doc['narration']['offsetFrames'], doc['background']['offsetFrames'], channels, doc['durationPolicy']))
        assert a.verify(directory)['verified']
        report[name] = {'frames': info[2], 'channels': info[1], 'rate': info[0], 'samples': len(actual), 'ties': ties}
    return report


def accept(root, sox, repository, only=None):
    root.mkdir(parents=True)
    started = time.monotonic()
    report = {'runtime': os.popen(f'{sox} --version').read().strip().split(':')[-1].strip()}
    for name, action in (('matrix', matrix), ('extremes', extremes), ('sweeps', sweeps), ('refusalsBeforeNative', refusals), ('forgedNativeRuns', forgeries),
                         ('changedSourcesAndWorkflow', changed_sources_and_workflow), ('lifecycle', lifecycle)):
        if only and name not in only: continue
        scratch = root / name; scratch.mkdir()
        report[name] = action(scratch, sox)
    if not only or 'examples' in only:
        scratch = root / 'examples-run'; scratch.mkdir()
        report['examples'] = examples(scratch, sox, repository)
    report['elapsedSeconds'] = round(time.monotonic() - started, 1)
    report['hostPeakRssMB'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sox', type=Path, required=True, help='absolute SoX 14.4.2 executable')
    parser.add_argument('--root', type=Path, required=True, help='new empty evidence directory')
    parser.add_argument('--only', help='comma-separated stage names to run (matrix, extremes, sweeps, refusalsBeforeNative, forgedNativeRuns, changedSourcesAndWorkflow, lifecycle, examples); default all')
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    report = {'sox': str(arguments.sox), 'started': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    try: report.update(accept(root, str(arguments.sox), ROOT, set(arguments.only.split(',')) if arguments.only else None)); report['status'] = 'passed'
    except BaseException as error:
        report['status'] = 'failed'; report['error'] = repr(error)
        atomic_json(root / 'acceptance.json', report); print(json.dumps(report, indent=2)); raise
    atomic_json(root / 'acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
