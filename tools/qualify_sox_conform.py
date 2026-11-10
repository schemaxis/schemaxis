"""Native acceptance of the SoX conform operation with oracles independent of the adaptor.

The fixtures are analytic tones or integer patterns, so expected output is computed
here from the signal definition (or the exact integer rule) with `wave`/`struct` only.
Nothing in this module calls the adaptor's header parser, resampler reference or
summary code to decide whether native output is right.
"""
import copy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import random
import resource
import struct
import sys
import time
import wave

from schemaxis.adaptors.sox import adaptor as a
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis import workflow

FIXTURES = 'examples/schemaxis/sox-conform-fixtures/'
MARGIN = 150            # output frames excluded at each end of an analytic comparison
ANALYTIC_TOLERANCE = 2.5  # PCM16 LSB: three roundings plus sub-LSB resampler error


def refused(action, code):
    try: action()
    except SchemaxisError as error:
        assert error.fault.code == code, error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('invalid conform input accepted')


def read(path):
    with wave.open(str(path), 'rb') as stream:
        assert stream.getsampwidth() == 2 and stream.getcomptype() == 'NONE'
        info = (stream.getframerate(), stream.getnchannels(), stream.getnframes())
        raw = stream.readframes(stream.getnframes() + 1)
    return info, list(struct.unpack('<' + 'h' * (len(raw) // 2), raw))


def write(path, rate, channels, values):
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes(struct.pack('<' + 'h' * len(values), *values))


def rule(frames, rate):
    """Round-half-up of frames*16000/rate, by exact rational arithmetic."""
    return int(math.floor(Fraction(frames * 16000, rate) + Fraction(1, 2)))


def conform(root, source, policy, name, executable, timeout=120):
    document = {'version': a.VERSION, 'operation': 'conform', 'source': str(source), 'channelPolicy': policy}
    target = root / name
    result = a.run(document, target, executable=executable, timeout=timeout)
    assert a.verify(target)['verified']
    return result, target


def analytic(directory, name, expected, tolerance=ANALYTIC_TOLERANCE):
    """Native output against the ideal continuous-time signal sampled at 16 kHz."""
    (rate, channels, frames), output = read(directory / 'audio.wav')
    assert (rate, channels) == (16000, 1) and frames == len(output)
    worst = 0.0
    for j in range(MARGIN, frames - MARGIN):
        worst = max(worst, abs(output[j] - expected(j)))
    assert worst <= tolerance, (name, worst)
    return {'frames': frames, 'interiorFramesCompared': frames - 2 * MARGIN, 'maxErrorPCM16LSB': round(worst, 4), 'toleranceLSB': tolerance}


def tone(amplitude, frequency):
    return lambda j: amplitude * math.sin(2 * math.pi * frequency * j / 16000)


def stereo_44k(root, executable, fixture):
    result, target = conform(root, fixture / 'stereo44k.wav', 'average', 'stereo-44k-average', executable)
    left, right = tone(9000, 220), tone(3000, 1130)
    r1, r2 = tone(7000, 330), tone(2500, 2100)
    report = analytic(target, 'stereo44k', lambda j: 0.5 * (left(j) + right(j) + r1(j) + r2(j)))
    assert (result['frames'], result['rate'], result['channels']) == (3200, 16000, 1) and result['conversion']['resampled']
    return {**report, 'comparedPositions': result['fidelity']['comparedPositions'], 'warnings': result['warnings']}


def stereo_48k(root, executable, fixture):
    report = {}
    for policy, wanted, other in (('left', tone(12000, 440), tone(6000, 1250)), ('right', tone(6000, 1250), tone(12000, 440))):
        result, target = conform(root, fixture / 'stereo48k.wav', policy, f'stereo-48k-{policy}', executable)
        report[policy] = analytic(target, 'stereo48k-' + policy, wanted)
        (_, _, frames), output = read(target / 'audio.wav')
        distance = math.sqrt(sum((output[j] - other(j)) ** 2 for j in range(MARGIN, frames - MARGIN)) / (frames - 2 * MARGIN))
        assert distance > 1000, (policy, distance)       # the other channel is clearly a different signal
        report[policy]['rmsDistanceFromOtherChannelLSB'] = round(distance, 1)
        assert result['frames'] == 3200
    return report


def mono_8k(root, executable, fixture):
    expected = lambda j: tone(12000, 440)(j) + tone(3000, 1500)(j)
    reports = {}
    for policy in ('average', 'left'):
        result, target = conform(root, fixture / 'mono8k.wav', policy, f'mono-8k-{policy}', executable)
        reports[policy] = analytic(target, 'mono8k-' + policy, expected)
        assert result['frames'] == 8000 and result['conversion']['resampled']
    return reports


def exact_pairs(root, executable, fixture):
    """Same-rate conversion: every sample against the integer rule, all three policies."""
    (_, _, frames), values = read(fixture / 'stereo16k.wav')
    left, right = values[0::2], values[1::2]
    report = {}
    for policy, wanted in (('average', [(l + r + 1) >> 1 for l, r in zip(left, right)]), ('left', left), ('right', right)):
        result, target = conform(root, fixture / 'stereo16k.wav', policy, f'same-rate-{policy}', executable)
        _, output = read(target / 'audio.wav')
        assert output == wanted, policy
        assert result['fidelity']['samplesRecomputedExactly'] and result['frames'] == frames
        report[policy] = {'samplesCompared': len(output), 'exact': True}
    return report


def random_average(root, executable):
    """Native `remix -` against (L+R+1)>>1 for random and extreme pairs (not the retired remix 1,2 probe)."""
    rng = random.Random(31)
    pairs = [(rng.randint(-32768, 32767), rng.randint(-32768, 32767)) for _ in range(20000)]
    edges = (-32768, -32767, -2, -1, 0, 1, 2, 32766, 32767)
    pairs += [(x, y) for x in edges for y in edges]
    source = root / 'random-pairs.wav'
    write(source, 16000, 2, [v for pair in pairs for v in pair])
    _, target = conform(root, source, 'average', 'random-average', executable)
    _, output = read(target / 'audio.wav')
    assert output == [(x + y + 1) >> 1 for x, y in pairs]
    mono = [rng.randint(-32768, 32767) for _ in range(5000)]
    write(root / 'random-mono.wav', 16000, 1, mono)
    for policy in ('average', 'left'):
        _, target = conform(root, root / 'random-mono.wav', policy, 'random-mono-' + policy, executable)
        assert read(target / 'audio.wav')[1] == mono
    return {'stereoPairsCompared': len(pairs), 'monoSamplesCompared': len(mono) * 2, 'exact': True}


def frame_rule(root, executable):
    """Native frame counts for odd, non-integer ratios and tiny lengths against the exact rule."""
    rows = []
    for rate in (8000, 11025, 12345, 22050, 44101, 47999, 48000, 96000, 192000):
        for frames in (6, 7, 13, 101, 999, 4097):
            source = root / 'rule.wav'
            write(source, rate, 1, [(i * 977) % 20001 - 10000 for i in range(frames)])
            result, target = conform(root, source, 'left', f'rule-{rate}-{frames}', executable, 30)
            (_, _, produced), _ = read(target / 'audio.wav')
            assert produced == rule(frames, rate) == result['frames'], (rate, frames, produced)
            rows.append([rate, frames, produced])
    return {'combinations': len(rows), 'allMatchRoundHalfUp': True, 'sample': rows[:6]}


def anti_phase_and_clipping(root, executable):
    wave_ = [int(12000 * math.sin(2 * math.pi * 300 * k / 44100)) for k in range(44100)]
    source = root / 'anti.wav'
    write(source, 44100, 2, [v for x in wave_ for v in (x, -x)])
    result, target = conform(root, source, 'average', 'anti-average', executable)
    _, output = read(target / 'audio.wav')
    assert set(output) == {0} and [w['code'] for w in result['warnings']] == ['CHANNEL_CANCELLATION', 'SILENT_OUTPUT']
    left, target = conform(root, source, 'left', 'anti-left', executable)
    assert left['warnings'] == [] and left['peakPCM16'] > 11000
    square = root / 'square.wav'
    write(square, 44100, 1, [32767 if (i // 50) % 2 else -32768 for i in range(88200)])
    clipped, target = conform(root, square, 'left', 'square-left', executable)
    assert clipped['saturatedSamples'] > 0 and 'OUTPUT_SATURATION' in [w['code'] for w in clipped['warnings']]
    assert sum(clipped['nativeClippingWarnings'].values()) > 0
    _, output = read(target / 'audio.wav')
    assert sum(1 for v in output if v in (32767, -32768)) == clipped['saturatedSamples']
    return {'antiPhaseAverageOutputAllZero': True, 'antiPhaseWarnings': ['CHANNEL_CANCELLATION', 'SILENT_OUTPUT'], 'leftOfAntiPhasePeak': left['peakPCM16'],
            'squareSaturatedSamples': clipped['saturatedSamples'], 'squareNativeClippingWarnings': clipped['nativeClippingWarnings']}


def invalid_inputs(root, executable):
    report = {}
    def header(rate=16000, channels=1, bits=16, encoding=1, frames=100):
        align = channels * bits // 8
        payload = b'\0' * (frames * align)
        return (b'RIFF' + struct.pack('<I', 36 + len(payload)) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, encoding, channels, rate, rate * align, align, bits)
                + b'data' + struct.pack('<I', len(payload)) + payload)
    cases = {'24-bit': (header(bits=24), 'average', 'INVALID_AUDIO_DATA'), 'float': (header(encoding=3, bits=32), 'average', 'INVALID_AUDIO_DATA'),
             'three channels': (header(channels=3), 'average', 'INVALID_AUDIO_DATA'), 'rate 7999': (header(rate=7999), 'average', 'INVALID_AUDIO_DATA'),
             'rate 192001': (header(rate=192001), 'average', 'INVALID_AUDIO_DATA'), 'mono right': (header(), 'right', 'AUDIO_CHANNEL_POLICY'),
             'five frames at 192 kHz': (header(rate=192000, frames=5), 'left', 'AUDIO_SOURCE_BOUNDS'),
             'longer than 600 s': (header(rate=8000, frames=8000 * 600 + 1), 'left', 'AUDIO_RESOURCE_LIMIT'),
             'truncated': (header()[:-1], 'left', 'INVALID_AUDIO_DATA')}
    for name, (data, policy, code) in cases.items():
        source = root / 'invalid-source.wav'
        source.write_bytes(data)
        target = root / ('invalid-' + name.replace(' ', '-'))
        document = {'version': a.VERSION, 'operation': 'conform', 'source': str(source), 'channelPolicy': policy}
        fault = refused(lambda: a.run(document, target, executable=executable, timeout=30), code)
        assert not (target / 'version-submission.json').exists() and not (target / 'captured-0.wav').exists(), name
        report[name] = {'code': fault['code'], 'location': fault['location'], 'nativeNeverLaunched': True}
    huge = root / 'huge.wav'
    huge.write_bytes(b'0' * (32 * 1024 * 1024 + 1))
    document = {'version': a.VERSION, 'operation': 'conform', 'source': str(huge), 'channelPolicy': 'left'}
    report['over 32 MiB'] = {'code': refused(lambda: a.run(document, root / 'invalid-huge', executable=executable, timeout=30), 'INVALID_AUDIO_SOURCE')['code']}
    huge.unlink()
    for name, update, code in (('unknown policy', {'channelPolicy': 'mid'}, 'INVALID_ARGUMENT'), ('missing policy', {'channelPolicy': None}, 'MISSING_ARGUMENT'),
                               ('authored option', {'rate': 8000}, 'UNKNOWN_ARGUMENT'), ('relative source', {'source': 'a.wav'}, 'INVALID_AUDIO_SOURCE')):
        document = {'version': a.VERSION, 'operation': 'conform', 'source': str(root / 'x.wav'), 'channelPolicy': 'left', **update}
        document = {k: v for k, v in document.items() if v is not None}
        report[name] = {'code': refused(lambda: a.plan(document), code)['code']}
    return report


def transition_and_band(root, executable):
    """Correct native filtering near and above the output Nyquist must not be called corrupt.

    SoX rate -v keeps 7600 Hz at about -3 dB and removes 8000 Hz and above. The host verifies only
    the 0-0.6 Nyquist band, so these real native outputs must reopen as verified (conform() asserts
    a.verify) while the in-band chirp start still gets compared."""
    report = {}
    def sweep(rate, n, f0, f1, amplitude):
        T = n / rate
        return [round(amplitude * math.sin(2 * math.pi * (f0 * i / rate + (f1 - f0) * (i / rate) ** 2 / (2 * T)))) for i in range(n)]
    cases = {f'tone {hz} Hz at 48000': (48000, [round(10000 * math.sin(2 * math.pi * hz * i / 48000)) for i in range(9600)]) for hz in (7600, 7800, 8000, 9000)}
    cases['chirp 50-23000 Hz at 48000'] = (48000, sweep(48000, 24000, 50, 23000, 12000))
    cases['tone 5300 Hz at 11025 (upsampled transition)'] = (11025, [round(10000 * math.sin(2 * math.pi * 5300 * i / 11025)) for i in range(2205)])
    rng = random.Random(37813)
    cases['white noise at 37813'] = (37813, [rng.randint(-12000, 12000) for _ in range(7563)])
    for index, (name, (rate, values)) in enumerate(cases.items()):
        source = root / f'band-{index}.wav'
        write(source, rate, 1, values)
        result, _ = conform(root, source, 'average', f'band-{index}', executable)
        assert result['fidelity']['method'] == 'independent-band-limited-projection' and result['fidelity']['comparedPositions'] > 200, (name, result['fidelity'])
        report[name] = {'comparedPositions': result['fidelity']['comparedPositions'], 'peakPCM16': result['peakPCM16'], 'warnings': [w['code'] for w in result['warnings']]}
    return report


def forge(root, executable, fixture):
    """Tamper with real native run directories while refreshing ordinary digests."""
    from schemaxis.publication_metadata import finalise
    limit = 32 * 1024 * 1024
    def refresh(directory):
        receipt = a.read(directory, 'verification.json')
        receipt['artifacts'] = a.artifacts(directory, limit)
        receipt['evidence'] = {n: a.digest(directory, n, limit) for n in receipt['evidence']}
        atomic_json(directory / 'verification.json', receipt)
        finalise(directory)
    report = {}
    for label, source, policy in (('exact', fixture / 'stereo16k.wav', 'average'), ('resampled', fixture / 'stereo44k.wav', 'average')):
        _, directory = conform(root, source, policy, 'forge-' + label, executable)
        saved = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}
        def restore():
            for path in [p for p in directory.rglob('*') if p.is_file() and p not in saved]: path.unlink()
            for path, data in saved.items(): path.write_bytes(data)
        _, samples = read(directory / 'audio.wav')
        variants = {'silence': [0] * len(samples), 'inverted': [-v for v in samples], 'gain 0.8': [int(v * .8) for v in samples], 'gain 0.98': [round(v * .98) for v in samples], 'shifted 1 frame': samples[1:] + [0], 'shifted 5 frames': samples[5:] + [0] * 5,
                    'extra frame': samples + [samples[-1]], 'one frame short': samples[:-1]}
        if label == 'exact': variants['single sample +1'] = [v + (1 if i == 777 else 0) for i, v in enumerate(samples)]
        for name, forged in variants.items():
            try:
                write(directory / 'audio.wav', 16000, 1, forged)
                refresh(directory)
                report[f'{label}: {name}'] = refused(lambda: a.verify(directory), 'VERIFICATION_FAILED')['location']
            finally: restore()
        try:
            original = (directory / 'audio.wav').read_bytes()
            info = b'INFOICMT' + struct.pack('<I', 8) + b'injected'
            body = original[12:36] + b'LIST' + struct.pack('<I', len(info)) + info + original[36:]
            (directory / 'audio.wav').write_bytes(b'RIFF' + struct.pack('<I', 4 + len(body)) + b'WAVE' + body)
            refresh(directory)
            report[f'{label}: injected LIST'] = refused(lambda: a.verify(directory), 'VERIFICATION_FAILED')['location']
        finally: restore()
        for name, mutate in (('stderr diagnostic', lambda: (directory / 'conform.stderr').write_text('unexpected diagnostic\n')),
                             ('stdout text', lambda: (directory / 'conform.stdout').write_text('x')),
                             ('summary frames', lambda: atomic_json(directory / 'audio-summary.json', {**a.read(directory, 'audio-summary.json'), 'frames': 1})),
                             ('plan policy', lambda: atomic_json(directory / 'plan.json', {**a.read(directory, 'plan.json'), 'channelPolicy': 'left'}))):
            try:
                mutate()
                refresh(directory)
                report[f'{label}: {name}'] = refused(lambda: a.verify(directory), 'VERIFICATION_FAILED')['location']
            finally: restore()
        assert a.verify(directory)['verified']
    return report


def workflow_cases(root, executable, repository):
    """Assemble -> conform handoff, reuse invalidation and a channelPolicy parameter study."""
    locations = {'sox': executable}
    stereo = root / 'handoff-stereo.wav'
    stereo.write_bytes((repository / 'examples/schemaxis/fixtures/sox/stereo.wav').read_bytes())
    producer = {'version': a.VERSION, 'operation': 'assemble', 'clips': [{'source': str(stereo), 'startFrame': 100, 'frameCount': 4000, 'gain': 0.5, 'fadeInFrames': 10, 'fadeOutFrames': 10}]}
    consumer = {'version': a.VERSION, 'operation': 'conform', 'source': {'$artifact': 'producer', 'index': 0}, 'channelPolicy': 'average'}
    graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'producer', 'document': producer}, {'id': 'consumer', 'document': consumer}]}
    first = workflow.execute(graph, root / 'handoff', locations=locations, timeout=60)
    assert workflow.verify(root / 'handoff')['verified']
    directories = {job['operation']: Path(job['directory']) for job in first['jobs']}
    summary = json.loads((directories['consumer'] / 'audio-summary.json').read_text())
    assert summary['source']['rate'] == 48000 and summary['frames'] == rule(4000, 48000)
    produced = (directories['producer'] / 'audio.wav').read_bytes()
    assert summary['source']['sha256'] == hashlib.sha256(produced).hexdigest()
    effective = next(job for job in first['jobs'] if job['operation'] == 'consumer')['effective']
    assert effective['source'] == str(directories['producer'] / 'audio.wav')
    report = {'handoffStatus': first['status'], 'consumerFrames': summary['frames'], 'consumerSourceIsProducerOutput': True}
    assert a.verify(directories['consumer'])['verified']
    source = root / 'mutable.wav'
    source.write_bytes((repository / FIXTURES / 'stereo44k.wav').read_bytes())
    single = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'speech', 'document': {'version': a.VERSION, 'operation': 'conform', 'source': str(source), 'channelPolicy': 'average'}}]}
    workflow.execute(single, root / 'reuse', locations=locations, timeout=60)
    second = workflow.execute(single, root / 'reuse', locations=locations, timeout=60, resume=True)
    assert second['jobs'][0]['reused']
    raw = bytearray(source.read_bytes())
    offset = raw.index(b'data') + 8 + 4000
    struct.pack_into('<h', raw, offset, struct.unpack_from('<h', raw, offset)[0] + 100)
    source.write_bytes(raw)
    third = workflow.execute(single, root / 'reuse', locations=locations, timeout=60, resume=True)
    assert not third['jobs'][0]['reused'] and workflow.verify(root / 'reuse')['verified']
    report['reuse'] = {'unchangedReused': True, 'changedSourceBytesReused': False}
    study = {'version': a.VERSION, 'operation': 'conform', 'source': str(repository / FIXTURES / 'stereo48k.wav'), 'channelPolicy': {'$axis': 'policy'},
             'axes': [{'name': 'policy', 'values': ['left', 'right']}]}
    result = a.run(study, root / 'study', executable=executable, timeout=60)
    assert a.verify(root / 'study')['verified'] and len(result['states']) == 2
    report['parameterStudy'] = {'states': 2, 'verified': True}
    return report


def determinism(root, executable, fixture):
    hashes = []
    for i in range(2):
        _, target = conform(root, fixture / 'stereo44k.wav', 'average', f'determinism-{i}', executable)
        hashes.append(hashlib.sha256((target / 'audio.wav').read_bytes()).hexdigest())
    assert hashes[0] == hashes[1]
    return {'audioSha256': hashes[0], 'identicalAcrossRuns': True}


def maximum_size(root, executable):
    """The documented budget at its limit: 32 MiB / 190 s of 44.1 kHz stereo."""
    frames = (32 * 1024 * 1024 - 44) // 4
    source = root / 'maximum.wav'
    rng = random.Random(5)
    with open(source, 'wb') as stream:
        n = frames * 4
        stream.write(b'RIFF' + struct.pack('<I', 36 + n) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, 2, 44100, 44100 * 4, 4, 16) + b'data' + struct.pack('<I', n))
        done = 0
        while done < frames:
            count = min(65536, frames - done)
            block = []
            for k in range(done, done + count):
                block += [int(9000 * math.sin(2 * math.pi * 440 * k / 44100)) + rng.randint(-1500, 1500), int(7000 * math.sin(2 * math.pi * 1100 * k / 44100))]
            stream.write(struct.pack('<' + 'h' * len(block), *block))
            done += count
    size = source.stat().st_size
    assert size <= 32 * 1024 * 1024 and frames <= 600 * 44100
    start = time.monotonic()
    result, target = conform(root, source, 'average', 'maximum', executable, 300)
    elapsed = time.monotonic() - start
    source.unlink()
    return {'sourceBytes': size, 'sourceFrames': frames, 'sourceSeconds': round(frames / 44100, 1), 'outputFrames': result['frames'], 'comparedPositions': result['fidelity']['comparedPositions'],
            'runAndVerifySeconds': round(elapsed, 1), 'hostPeakRssMB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024}


def accept(root, executable, repository, large=True):
    root.mkdir(parents=True)
    fixture = repository / FIXTURES
    report = {'stereo44kAverageAnalytic': stereo_44k(root, executable, fixture), 'stereo48kLeftRightAsymmetry': stereo_48k(root, executable, fixture),
              'mono8kUpsample': mono_8k(root, executable, fixture), 'sameRateExactIntegerRule': exact_pairs(root, executable, fixture),
              'randomAndExtremePairs': random_average(root, executable), 'frameCountRule': frame_rule(root, executable),
              'antiPhaseAndClipping': anti_phase_and_clipping(root, executable), 'transitionAndOutOfBandNotCorrupt': transition_and_band(root, executable), 'invalidFormatAndPolicy': invalid_inputs(root, executable),
              'forgedNativeRunsWithRefreshedHashes': forge(root, executable, fixture), 'workflow': workflow_cases(root, executable, repository),
              'determinism': determinism(root, executable, fixture)}
    if large: report['maximumSize'] = maximum_size(root, executable)
    return report
