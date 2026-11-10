#!/usr/bin/env python3
"""Native acceptance of the SoX normalise (peak headroom) operation with oracles independent of the adaptor.

Fixtures are analytic or integer patterns written with `wave`/`struct`. The expected output
of every sample is computed here by integer arithmetic from the stated rule (nearest PCM16
integer to sample*targetPeak/peak, ties either way). Nothing in this module calls the
adaptor's header parser, gain decision or summary code to decide whether native output is
right; the adaptor is only driven (run/verify) and its refusals are checked. A native exit
status alone is never acceptance.
"""
import argparse
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

from schemaxis import workflow
from schemaxis.adaptors.sox import adaptor as a
from schemaxis.artifacts import atomic_json
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise

ROOT = Path(__file__).resolve().parents[1]
RATES = (8000, 16000, 22050, 44100, 48000, 192000)


def read(path):
    """(rate, channels, frames), scalar samples and the file size; wave plus the canonical 44-byte size rule."""
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
    raise AssertionError('invalid normalise input accepted')


def document(source, target, ceiling):
    return {'version': a.VERSION, 'operation': 'normalise', 'source': str(source), 'targetPeak': target, 'maxGain': ceiling}


def check(directory, values, rate, channels, target, label):
    """Every output sample against the independent integer rule; returns facts for the report."""
    info, output = read(directory / 'audio.wav')
    assert info == (rate, channels, len(values) // channels), (label, info)
    peak = max(abs(v) for v in values)
    assert peak > 0 and len(output) == len(values)
    worst = 0
    for s, n in zip(values, output):
        error = abs(2 * n * peak - 2 * s * target)       # twice |n - s*target/peak| times peak: at most one half LSB means <= peak
        assert error <= peak, (label, s, n, peak, target)
        worst = max(worst, error)
    assert max(abs(v) for v in output) == target, (label, 'output peak is not targetPeak')
    assert -32768 <= min(output) and max(output) <= 32767
    return {'samples': len(values), 'sourcePeak': peak, 'gain': f'{target // math.gcd(target, peak)}/{peak // math.gcd(target, peak)}',
            'worstErrorLSB': f'{worst // math.gcd(worst, 2 * peak)}/{2 * peak // math.gcd(worst, 2 * peak)}' if worst else '0', 'outputPeak': target}


def normalise(root, name, rate, channels, values, target, ceiling, executable, timeout=60):
    source = root / f'{name}.wav'
    write(source, rate, channels, values)
    directory = root / name
    result = a.run(document(source, target, ceiling), directory, executable=executable, timeout=timeout)
    assert a.verify(directory)['verified']
    assert result['claims']['everySampleCompared'] and result['claims']['clippedSamples'] == 0 and not result['claims']['loudnessNormalised']
    assert (directory / 'normalise-submission.json').exists() and json.loads((directory / 'normalise-submission.json').read_text())['exitCode'] == 0
    return result, directory


def signal(rate, channels, seconds, amplitude, seed):
    """Two integer-rounded tones per channel plus bounded noise; one frame forced to the exact amplitude."""
    rng = random.Random(seed)
    frames = int(rate * seconds)
    values = []
    for i in range(frames):
        for c in range(channels):
            tone = amplitude * math.sin(2 * math.pi * (440 * (c + 1)) * i / rate) * 0.7 + amplitude * 0.3 * math.sin(2 * math.pi * 1250 * i / rate)
            values.append(max(-amplitude, min(amplitude, int(math.floor(tone + 0.5)) + rng.randint(-40, 40))))
    values[(frames // 3) * channels] = amplitude
    values[(frames // 2) * channels + channels - 1] = -amplitude
    return values


def rate_matrix(root, executable):
    report = {}
    for index, rate in enumerate(RATES):
        channels = 1 + index % 2
        values = signal(rate, channels, 0.05, 2400 + 100 * index, index)
        result, directory = normalise(root, f'rate-{rate}', rate, channels, values, 24000, 16, executable)
        report[str(rate)] = {'channels': channels, 'frames': result['frames'], **check(directory, values, rate, channels, 24000, f'rate-{rate}'),
                             'summaryGain': result['gain'], 'summaryMaxErrorLSB': result['maxErrorLSB']}
    return report


def edge_cases(root, executable):
    report = {}
    # exactly the boost ceiling, and the exact decimal ceiling that a binary float comparison refused
    values = [2000, -1000, 7, 1999, -2000, 0, 3] * 5
    result, directory = normalise(root, 'gain-16', 8000, 1, values, 32000, 16, executable)
    assert result['gain'] == {'numerator': 16, 'denominator': 1, 'direction': 'boost', 'withinMaxGain': True}
    report['maximumBoostGain16'] = check(directory, values, 8000, 1, 32000, 'gain-16')
    values = [5, -3, 2, 1, -5, 4, 0, 5]
    result, directory = normalise(root, 'decimal-ceiling-6.6', 8000, 1, values, 33, 6.6, executable)
    assert result['gain']['numerator'] == 33 and result['gain']['denominator'] == 5 and result['maxGain'] == 6.6
    assert read(directory / 'audio.wav')[1] == [33, -20, 13, 7, -33, 26, 0, 33]
    report['decimalCeiling6_6'] = check(directory, values, 8000, 1, 33, 'decimal-6.6')
    source = root / 'decimal-ceiling-6.6.wav'
    for label, target, ceiling in (('belowCeilingByOneFloat', 33, math.nextafter(6.6, 0)), ('targetAboveCeiling', 34, 6.6)):
        run = root / ('refused-' + label)
        fault = refused(lambda: a.run(document(source, target, ceiling), run, executable=executable, timeout=60), 'AUDIO_GAIN_LIMIT')
        assert not (run / 'version-submission.json').exists() and not (run / 'normalise-submission.json').exists()
        report[label] = {'fault': fault['code'], 'requiredGain': fault['observed']['requiredGain'], 'nativeProcessStarted': False}
    # signed extrema: -32768 is the only possible negative-only peak
    values = [-32768, 32767, 1000, -1000, 0, 1]
    for label, target in (('negativeFullScale32767', 32767), ('negativeFullScale1000', 1000), ('negativeFullScaleMinimum1', 1)):
        result, directory = normalise(root, label, 8000, 1, values, target, 1, executable)
        assert result['source']['peakPCM16'] == 32768 and result['gain']['direction'] == 'attenuation'
        report[label] = check(directory, values, 8000, 1, target, label)
    values = [-32768, 17, -5, 0, 32767, -32767, 3, 4]
    result, directory = normalise(root, 'negative-only-stereo', 22050, 2, values, 32767, 1, executable)
    assert result['source']['peakPolarity'] == ['negative'] and result['headroom']['positiveHeadroomPCM16'] == 0
    report['negativePeakStereo'] = check(directory, values, 22050, 2, 32767, 'negative-stereo')
    # unity: every sample unchanged
    values = [32767, -32767, 5, 0, -1, 12000]
    result, directory = normalise(root, 'unity', 8000, 1, values, 32767, 1, executable)
    assert read(directory / 'audio.wav')[1] == values and result['gain']['direction'] == 'unity'
    report['unityUnchanged'] = check(directory, values, 8000, 1, 32767, 'unity')
    # ties: peak 10, target 5 halves every odd value; either neighbour is an accepted nearest integer
    values = [10, 1, 3, -1, -3, -10, 7, -7, 9]
    result, directory = normalise(root, 'ties', 8000, 1, values, 5, 1, executable)
    report['halfTies'] = {**check(directory, values, 8000, 1, 5, 'ties'), 'nativeOutput': read(directory / 'audio.wav')[1]}
    # small odd frame counts, mono and stereo
    for label, channels, values, target, ceiling in (('one-frame-mono', 1, [-1234], 5000, 5), ('one-frame-stereo', 2, [1, -2], 32, 16), ('three-frames-stereo', 2, [5, 1000, -7, 3, 0, -999], 15000, 16)):
        _, directory = normalise(root, label, 8000, channels, values, target, ceiling, executable)
        report[label] = check(directory, values, 8000, channels, target, label)
    return report


def sweeps(root, executable):
    """Every PCM16 value the rule can reach: native rounding is compared sample by sample for each."""
    report = {}
    cases = (('sweep-all-65536-values', list(range(-32768, 32768)), 32767, 1), ('sweep-boost-4096-values', list(range(-2048, 2048)), 32767, 16),
             ('sweep-middle-gain-3.001', list(range(-1000, 1001)), 3001, 4), ('sweep-heavy-attenuation', list(range(-20000, 20001, 7)), 7, 1))
    for label, values, target, ceiling in cases:
        result, directory = normalise(root, label, 8000, 1, values, target, ceiling, executable, timeout=120)
        report[label] = {**check(directory, values, 8000, 1, target, label), 'distinctSourceValues': len(set(values)), 'summaryMaxErrorLSB': result['maxErrorLSB']}
    return report


def invalid_inputs(root, executable):
    report = {}
    silent = root / 'silent.wav'
    write(silent, 8000, 1, [0] * 200)
    loud = root / 'loud-source.wav'
    write(loud, 8000, 1, [1000, -500])
    cases = {'silence': (document(silent, 20000, 16), 'AUDIO_SILENT_SOURCE'), 'overGain': (document(loud, 32000, 16), 'AUDIO_GAIN_LIMIT'),
             'unknownControl': ({**document(loud, 2000, 4), 'gainDb': 6}, 'UNKNOWN_ARGUMENT'), 'targetZero': (document(loud, 0, 4), 'INVALID_ARGUMENT'),
             'target32768': (document(loud, 32768, 4), 'INVALID_ARGUMENT'), 'targetBoolean': (document(loud, True, 4), 'INVALID_ARGUMENT'), 'targetFloat': (document(loud, 2000.0, 4), 'INVALID_ARGUMENT'),
             'maxGainBelowOne': (document(loud, 2000, 0.9), 'INVALID_ARGUMENT'), 'maxGainAbove16': (document(loud, 2000, 16.5), 'INVALID_ARGUMENT'),
             'maxGainNaN': (document(loud, 2000, float('nan')), 'INVALID_ARGUMENT'), 'maxGainInfinite': (document(loud, 2000, float('inf')), 'INVALID_ARGUMENT'),
             'maxGainString': (document(loud, 2000, '4'), 'INVALID_ARGUMENT')}
    for label, (doc, code) in cases.items():
        run = root / ('invalid-' + label)
        fault = refused(lambda: a.run(doc, run, executable=executable, timeout=60), code)
        assert not (run / 'version-submission.json').exists() and not (run / 'normalise-submission.json').exists()
        report[label] = {'fault': fault['code'], 'location': fault['location'], 'nativeProcessStarted': False}
    # unsupported source formats are refused by the existing bounded reader before SoX starts
    bad = root / 'float-source.wav'
    bad.write_bytes(b'RIFF' + struct.pack('<I', 36 + 8) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 3, 1, 8000, 32000, 4, 32) + b'data' + struct.pack('<I', 8) + bytes(8))
    run = root / 'invalid-float'
    fault = refused(lambda: a.run(document(bad, 100, 4), run, executable=executable, timeout=60), 'INVALID_AUDIO_DATA')
    assert not (run / 'version-submission.json').exists()
    report['floatSource'] = {'fault': fault['code'], 'nativeProcessStarted': False}
    return report


def refresh(directory):
    receipt = a.read(directory, 'verification.json')
    receipt['artifacts'] = a.artifacts(directory, a.normalise.SOURCE_LIMIT)
    receipt['evidence'] = {n: a.digest(directory, n, a.normalise.SOURCE_LIMIT) for n in receipt['evidence']}
    atomic_json(directory / 'verification.json', receipt)
    finalise(directory)


def forgeries(root, executable):
    """Real native run directory; each forged output has refreshed digests, so only the numerical contract can refuse it."""
    values = signal(16000, 2, 0.05, 3000, 99)
    _, directory = normalise(root, 'forge-base', 16000, 2, values, 20000, 8, executable)
    audio = directory / 'audio.wav'
    good = audio.read_bytes()
    _, samples = read(audio)
    report = {}
    forged = {'oneSamplePlusOne': [v + (1 if i == 77 else 0) for i, v in enumerate(samples)], 'quieterByOnePercent': [round(v * .99) for v in samples],
              'unscaledSource': values, 'invertedPolarity': [-v for v in samples], 'channelsSwapped': [v for pair in zip(samples[1::2], samples[0::2]) for v in pair],
              'silence': [0] * len(samples), 'oneFrameShort': samples[:-2]}
    for label, output in forged.items():
        write(audio, 16000, 2, output); refresh(directory)
        report[label] = refused(lambda: a.verify(directory), 'VERIFICATION_FAILED')['location']
        audio.write_bytes(good); refresh(directory)
        assert a.verify(directory)['verified']
    summary = a.read(directory, 'audio-summary.json')
    summary['gain']['numerator'] = 21
    atomic_json(directory / 'audio-summary.json', summary); refresh(directory)
    report['summaryGainForged'] = refused(lambda: a.verify(directory), 'VERIFICATION_FAILED')['code']
    summary['gain']['numerator'] = 20
    atomic_json(directory / 'audio-summary.json', summary); refresh(directory)
    assert a.verify(directory)['verified']
    return report


def determinism(root, executable):
    values = signal(8000, 1, 0.1, 5000, 3)
    hashes = []
    for i in range(2):
        _, directory = normalise(root, f'determinism-{i}', 8000, 1, values, 30000, 8, executable)
        hashes.append(hashlib.sha256((directory / 'audio.wav').read_bytes()).hexdigest())
    assert hashes[0] == hashes[1]
    return {'audioSha256': hashes[0], 'identicalAcrossRuns': True}


def flac_workflow(root, sox, flac, repository):
    """normalise -> FLAC encodeLossless -> decodePCM16: the archived and restored PCM equal the normalised WAV exactly."""
    locations = {'sox': sox, 'flac': flac}
    source = root / 'workflow-quiet.wav'
    source.write_bytes((repository / 'examples/schemaxis/sox-normalise-fixtures/quiet-stereo16k.wav').read_bytes())
    graph = {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'headroom', 'document': document(source, 20000, 8)},
        {'id': 'archive', 'document': {'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': {'$artifact': 'headroom', 'index': 0}}},
        {'id': 'restore', 'document': {'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': {'$artifact': 'archive', 'index': 0}}}]}
    first = workflow.execute(graph, root / 'flac-workflow', locations=locations, timeout=240)
    assert first['status'] == 'succeeded', first['status']
    with location_context(locations):
        assert workflow.verify(root / 'flac-workflow')['verified']
    base = root / 'flac-workflow'
    wavs = {p.relative_to(base).parts[0]: p for p in base.rglob('audio.wav')}
    flacs = list(base.rglob('audio.flac'))
    assert set(wavs) >= {'headroom', 'restore'} and len(flacs) == 1, (sorted(wavs), flacs)
    normalised, restored = wavs['headroom'].read_bytes(), wavs['restore'].read_bytes()
    assert normalised == restored, 'restored PCM differs from the normalised WAV'
    original = read(source)[1]
    (rate, channels, frames), output = read(wavs['headroom'])
    facts = check(wavs['headroom'].parent, original, rate, channels, 20000, 'flac-workflow')
    second = workflow.execute(graph, root / 'flac-workflow', locations=locations, timeout=240, resume=True)
    assert all(job['reused'] for job in second['jobs'])
    source.write_bytes(source.read_bytes()[:44] + struct.pack('<h', 1500) + source.read_bytes()[46:])
    third = workflow.execute(graph, root / 'flac-workflow', locations=locations, timeout=240, resume=True)
    assert not third['jobs'][0]['reused']
    return {'status': first['status'], 'jobs': [job['operation'] for job in first['jobs']], 'flacBytes': flacs[0].stat().st_size, 'normalisedWavSha256': hashlib.sha256(normalised).hexdigest(),
            'restoredEqualsNormalisedWav': True, 'normalise': facts, 'unchangedResumeReused': True, 'changedSourceReused': False}


def accept(root, sox, flac, repository):
    root.mkdir(parents=True)
    started = time.monotonic()
    report = {'rateMatrix': rate_matrix(root, sox), 'edgeCases': edge_cases(root, sox), 'sweeps': sweeps(root, sox), 'invalidInputsRefusedBeforeNative': invalid_inputs(root, sox),
              'forgedNativeRunsWithRefreshedHashes': forgeries(root, sox), 'determinism': determinism(root, sox)}
    if flac: report['flacWorkflow'] = flac_workflow(root, sox, flac, repository)
    report['elapsedSeconds'] = round(time.monotonic() - started, 1)
    report['hostPeakRssMB'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sox', type=Path, required=True, help='absolute SoX 14.4.2 executable')
    parser.add_argument('--flac', type=Path, help='absolute flac executable (enables the normalise -> FLAC workflow)')
    parser.add_argument('--root', type=Path, required=True, help='new empty evidence directory')
    arguments = parser.parse_args()
    root = arguments.root.absolute()
    report = {'sox': str(arguments.sox), 'flac': str(arguments.flac) if arguments.flac else None, 'started': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    try: report.update(accept(root, str(arguments.sox), str(arguments.flac) if arguments.flac else None, ROOT)); report['status'] = 'passed'
    except BaseException as error:
        report['status'] = 'failed'; report['error'] = repr(error)
        atomic_json(root / 'acceptance.json', report); print(json.dumps(report, indent=2)); raise
    atomic_json(root / 'acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
