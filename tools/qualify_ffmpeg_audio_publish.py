#!/usr/bin/env python3
"""Bounded native acceptance of the FFmpeg encodeAudio operation (verified AAC-LC/M4A publishing from a prepared PCM16 WAV).

Runs, each in its own supervised child process with a recorded PID, timeout and exit status:

* the native cases of tests/unit/test_ffmpeg_audio_publish.py;
* a geometry matrix of deterministic generated tones: mono and stereo at 16000, 22050, 44100 and 48000 Hz with tiny and odd frame
  counts, each published, verified twice by the same trusted runtime, and decoded again by a separate native invocation with different
  arguments; the actual native children (PID, argv, exit status and the executable observed under /proc) are recorded, not only the
  Python supervisors;
* extended acceptance (own supervised child per case): 60 s of 48 kHz stereo at 192 kbit/s whose output exceeds 1 MiB and 600 s of 16 kHz mono
  (the 600 s limit, a 19.2 MB source) whose output spans several chunks, each with the container chunk tables read back, every PCM sample counted,
  verified twice and decoded again by a separate native invocation; they supersede the earlier short-clip proof, which stays valid only for its own
  points (this is bounded named fixtures, not every length or quality);
* the legacy read-only control: plans and fixed argv of the five older operations from the committed baseline tree (--baseline-src,
  ``git archive HEAD src``) against the current tree must be identical;
* optionally (--espeak) a real eSpeak NG utterance, and an extractAudio WAV handed to encodeAudio.

It never overwrites a retained run. Fixtures are generated tones and a synthetic voice, never proprietary speech; the results are
numeric waveform measurements of a machine publication with no human review, listening test or recognition accuracy."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPOSITORY = Path(__file__).resolve().parent.parent
CASES = [(16000, 1, 1), (16000, 2, 4097), (22050, 1, 2049), (22050, 2, 17), (44100, 1, 1025), (44100, 2, 30001), (48000, 1, 12345), (48000, 2, 999),
         (16000, 1, 24001), (48000, 2, 48001)]
# label, rate, channels, seconds, bitrate, maxMeanPCMError: bounded named fixtures, not every length or quality
EXTENDED_CASES = [('extended-60s-48k-stereo-192k', 48000, 2, 60, 192, 65535), ('extended-600s-16k-mono-64k', 16000, 1, 600, 64, 3000)]
RECORD = '''
import json, os, subprocess, sys, threading, time
RECORDED = []
class Recording(subprocess.Popen):
    """Record every native child the adaptor starts: PID, argv, and the executable seen under /proc while it ran."""
    def __init__(self, args, *a, **k):
        super().__init__(args, *a, **k)
        entry = {'pid': self.pid, 'argv': [str(x) for x in args], 'stageTimeoutSeconds': 120, 'exe': None}
        RECORDED.append((entry, self))
        def watch():
            end = time.monotonic() + 3
            while time.monotonic() < end and self.poll() is None:
                try:
                    exe = os.readlink('/proc/%d/exe' % self.pid)
                except OSError:
                    break
                entry['exe'] = exe
                if os.path.basename(exe).startswith(('ffmpeg', 'ffprobe')):
                    break
                time.sleep(0.001)
        threading.Thread(target=watch, daemon=True).start()
subprocess.Popen = Recording
def children():
    out = []
    for entry, process in RECORDED:
        process.poll()
        out.append({**entry, 'exitCode': process.returncode})
    return out
'''
MATRIX = RECORD + '''
import math, struct, wave, hashlib
from pathlib import Path
from schemaxis.adaptors.ffmpeg import adaptor
ffmpeg, root, cases = sys.argv[1], Path(sys.argv[2]), json.loads(sys.argv[3])
root.mkdir()
def tone(frames, channels, rate, seed):
    data = bytearray()
    for i in range(frames):
        for c in range(channels):
            data += struct.pack('<h', int(9000 * math.sin(2 * math.pi * (190 + 70 * c + 25 * seed) * i / rate) * (0.4 + 0.6 * math.sin(i / 733 + seed))))
    return bytes(data)
rows = []
for n, (rate, channels, frames) in enumerate(cases):
    name = '%d-%d-%d' % (rate, channels, frames)
    source = root / (name + '.wav')
    with wave.open(str(source), 'wb') as handle:
        handle.setnchannels(channels); handle.setsampwidth(2); handle.setframerate(rate); handle.writeframes(tone(frames, channels, rate, n % 5))
    started = time.monotonic()
    document = {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'pub', 'filter': 'encodeAudio', 'options': {
        'file': str(source), 'bitrateKbps': (64, 96, 128, 192)[n % 4], 'maxBytes': 8 << 20, 'maxMeanPCMError': 20000}}]}
    first_child = len(RECORDED)
    result = adaptor.run(document, root / ('run-' + name), executable=ffmpeg, timeout=120)
    first = adaptor.verify(root / ('run-' + name), executable=ffmpeg)
    second = adaptor.verify(root / ('run-' + name), executable=ffmpeg)
    assert first == second and first['freshNativeVerification'] is True
    independent = root / (name + '.independent.wav')
    child = subprocess.Popen([ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(root / ('run-' + name) / 'audio.m4a'), '-map', '0:a:0', '-c:a', 'pcm_s16le', str(independent)])
    child.wait(timeout=60)
    assert child.returncode == 0
    with wave.open(str(independent)) as handle:
        got = (handle.getnchannels(), handle.getframerate(), handle.getnframes(), handle.readframes(handle.getnframes()))
    with wave.open(str(root / ('run-' + name) / 'decoded.wav')) as handle:
        mine = (handle.getnchannels(), handle.getframerate(), handle.getnframes(), handle.readframes(handle.getnframes()))
    assert got == mine and got[2] == frames, name
    summary = json.loads((root / ('run-' + name) / 'audio-publish-summary.json').read_text())
    rows.append({'case': name, 'sampleRate': rate, 'channels': channels, 'frames': frames, 'bitrateKbps': document['nodes'][0]['options']['bitrateKbps'],
                 'bytes': result['bytes'], 'meanAbsPCMError': summary['comparison']['meanAbsPCMError'], 'meanAbsPCMErrorApprox': summary['comparison']['meanAbsPCMErrorApprox'],
                 'maxAbsPCMError': summary['comparison']['maxAbsPCMError'], 'primingFrames': summary['geometry']['primingFrames'],
                 'decodedFrames': got[2], 'independentDecodeEqual': True, 'freshVerifiedTwice': True, 'seconds': round(time.monotonic() - started, 2),
                 'nativeChildren': len(RECORDED) - first_child})
print(json.dumps({'cases': rows, 'nativeChildren': children()}))
'''
EXTENDED = RECORD + '''
import math, struct, wave, hashlib
from array import array
from pathlib import Path
from schemaxis.adaptors.ffmpeg import adaptor, audio
ffmpeg, root = sys.argv[1], Path(sys.argv[2])
rate, channels, seconds, bitrate, max_error = int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6]), float(sys.argv[7])
root.mkdir()
frames = rate * seconds
def signal(frames, channels, rate):
    """Deterministic generated amplitude-modulated partials plus low-level LCG noise (never speech)."""
    state, out = 12345, array('h')
    partials = [(180, 5200), (437, 3100), (1093, 1800), (2711, 900), (5303, 450)]
    w = [2 * math.pi * f / rate for f, _ in partials]
    for i in range(frames):
        env = 0.55 + 0.45 * math.sin(i / (0.37 * rate))
        base = sum(a * math.sin(w[k] * i + k * 0.7) for k, (_, a) in enumerate(partials)) * env
        for c in range(channels):
            state = (state * 1103515245 + 12345) & 0x7fffffff
            out.append(max(-32768, min(32767, int(base * (1.0 - 0.18 * c) + ((state >> 8) % 601) - 300))))
    return out
started = time.monotonic()
source = root / 'source.wav'
with wave.open(str(source), 'wb') as handle:
    handle.setnchannels(channels); handle.setsampwidth(2); handle.setframerate(rate); handle.writeframes(signal(frames, channels, rate).tobytes())
generated = round(time.monotonic() - started, 2)
document = {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'pub', 'filter': 'encodeAudio', 'options': {
    'file': str(source), 'bitrateKbps': bitrate, 'maxBytes': 32 << 20, 'maxMeanPCMError': int(max_error) if max_error == int(max_error) else max_error}}]}
started = time.monotonic()
result = adaptor.run(document, root / 'run', executable=ffmpeg, timeout=300)
ran = round(time.monotonic() - started, 2)
started = time.monotonic()
first = adaptor.verify(root / 'run', executable=ffmpeg)
second = adaptor.verify(root / 'run', executable=ffmpeg)
verified = round(time.monotonic() - started, 2)
assert first == second and first['freshNativeVerification'] is True
data = (root / 'run' / 'audio.m4a').read_bytes()
found = {}
def walk(start, end):
    for kind, payload, stop in audio.boxes(data, start, end):
        found.setdefault(kind, (payload, stop))
        if kind in (b'moov', b'trak', b'mdia', b'minf', b'stbl'):
            walk(payload, stop)
walk(0, len(data))
chunks = struct.unpack('>I', data[found[b'stco'][0] + 4:found[b'stco'][0] + 8])[0]
runs = struct.unpack('>I', data[found[b'stsc'][0] + 4:found[b'stsc'][0] + 8])[0]
offsets = struct.unpack('>%dI' % chunks, data[found[b'stco'][0] + 8:found[b'stco'][1]])
deltas = [b - a for a, b in zip(offsets, offsets[1:])]
independent = root / 'independent.wav'
child = subprocess.Popen([ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(root / 'run' / 'audio.m4a'), '-map', '0:a:0', '-c:a', 'pcm_s16le', str(independent)])
child.wait(timeout=120)
assert child.returncode == 0
with wave.open(str(independent)) as left, wave.open(str(root / 'run' / 'decoded.wav')) as right:
    equal = (left.getnchannels(), left.getframerate(), left.getnframes()) == (right.getnchannels(), right.getframerate(), right.getnframes()) == (channels, rate, frames)
    equal = equal and left.readframes(left.getnframes()) == right.readframes(right.getnframes())
assert equal
summary = json.loads((root / 'run' / 'audio-publish-summary.json').read_text())
comparison = summary['comparison']
print(json.dumps({'sourceRate': rate, 'channels': channels, 'seconds': seconds, 'frames': frames, 'sourceWavBytes': source.stat().st_size, 'bitrateKbps': bitrate,
                  'maxBytes': 32 << 20, 'maxMeanPCMError': document['nodes'][0]['options']['maxMeanPCMError'], 'publishedBytes': len(data),
                  'overOneMebibyte': len(data) > 1 << 20, 'chunks': chunks, 'sampleToChunkRuns': runs, 'chunkPayloadBytesFirst': deltas[:3], 'multiChunk': chunks > 1,
                  'packets': summary['geometry']['packets'], 'samplesCounted': comparison['samples'], 'expectedSamples': frames * channels,
                  'absoluteErrorSum': comparison['absoluteErrorSum'], 'meanAbsPCMError': comparison['meanAbsPCMError'],
                  'meanAbsPCMErrorApprox': comparison['meanAbsPCMErrorApprox'], 'maxAbsPCMError': comparison['maxAbsPCMError'],
                  'sourceFullScaleSamples': comparison['sourceFullScaleSamples'], 'decodedFullScaleSamples': comparison['decodedFullScaleSamples'],
                  'independentDecodeEqual': True, 'freshVerifiedTwice': True, 'generateSeconds': generated, 'runSeconds': ran, 'verifySeconds': verified,
                  'nativeChildren': children()}))
'''
LEGACY = '''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from schemaxis.adaptors.ffmpeg import adaptor, audio, review, video
docs = {
    'encodeFrames': {'files': ['/in/a.png', '/in/b.png'], 'fps': 12, 'codec': 'ffv1'},
    'encodeSheet': {'file': '/in/s.png', 'metadata': '/in/s.json'},
    'encodeVideo': {'file': '/in/v.mp4', 'startFrame': 1, 'endFrame': 9, 'fps': 24},
    'muxReview': {'video': '/in/v.mkv', 'audio': '/in/a.wav', 'captions': '/in/c.srt'},
    'extractAudio': {'file': '/in/a.m4a', 'streamIndex': 1, 'threads': 2}}
plans = {name: adaptor.plan({'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'x', 'filter': name, 'options': options}]}) for name, options in docs.items()}
prepared = plans['encodeFrames']
argv = {'native_commands': adaptor.native_commands('/t/ffmpeg', Path('/run'), prepared, 4, 2),
        'extractAudio': audio.commands('/t/ffmpeg', Path('/run'), plans['extractAudio']['nodes'][0]['options']),
        'review': review.commands('/t/ffmpeg', Path('/run'), plans['muxReview']['nodes'][0]['options']),
        'declarations': {k: v for k, v in adaptor.DECLARATIONS.items() if k != 'encodeAudio'}}
print(json.dumps({'plans': plans, 'argv': argv}, sort_keys=True, default=str))
'''
WORKFLOW = RECORD + '''
from pathlib import Path
from schemaxis import configuration, workflow
ffmpeg, espeak, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
document = json.loads((Path(sys.argv[4]) / 'examples' / 'schemaxis' / 'ffmpeg-audio-publish-workflow.json').read_text())
locations = {'ffmpeg': ffmpeg, 'espeakng': espeak}
result = workflow.execute(document, out, locations=locations, timeout=120)
with configuration.location_context(locations):
    answer = workflow.verify(out)
summary = json.loads(next(out.rglob('audio-publish-summary.json')).read_text())
print(json.dumps({'status': result['status'], 'jobs': [{k: job.get(k) for k in ('id', 'status')} for job in result['jobs']], 'workflowVerified': answer['verified'],
                  'source': {k: summary['source'][k] for k in ('sampleRate', 'channels', 'frames')}, 'publishedBytes': summary['published']['bytes'],
                  'meanAbsPCMError': summary['comparison']['meanAbsPCMError'], 'meanAbsPCMErrorApprox': summary['comparison']['meanAbsPCMErrorApprox'],
                  'maxAbsPCMError': summary['comparison']['maxAbsPCMError'], 'budgetsAccepted': summary['budgets']['accepted'], 'nativeChildren': children()}))
'''
HANDOFF = RECORD + '''
import wave, math, struct
from pathlib import Path
from schemaxis.adaptors.ffmpeg import adaptor
ffmpeg, espeak, root = sys.argv[1], sys.argv[2], Path(sys.argv[3])
root.mkdir()
processes = []
def native(label, command):
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = child.communicate(timeout=60)
    processes.append({'label': label, 'pid': child.pid, 'argv': command, 'timeoutSeconds': 60, 'exitCode': child.returncode})
    assert child.returncode == 0, (label, err[-300:])
cases = []
if espeak != '-':
    voice = root / 'espeak.wav'
    native('espeak-ng synthetic voice', [espeak, '-w', str(voice), 'Schemaxis publishes a shareable audio file after checking every sample.'])
    with wave.open(str(voice)) as handle:
        rate, channels, frames = handle.getframerate(), handle.getnchannels(), handle.getnframes()
    document = {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'voice', 'filter': 'encodeAudio', 'options': {'file': str(voice), 'bitrateKbps': 64, 'maxBytes': 1 << 20, 'maxMeanPCMError': 3000}}]}
    result = adaptor.run(document, root / 'run-espeak', executable=ffmpeg, timeout=120)
    answer = adaptor.verify(root / 'run-espeak', executable=ffmpeg)
    cases.append({'case': 'espeak-ng synthetic voice (draft; no human listening)', 'sampleRate': rate, 'channels': channels, 'frames': frames,
                  'bytes': result['bytes'], 'meanAbsPCMError': result['meanAbsPCMError'], 'freshVerified': answer['freshNativeVerification']})
source = root / 'capture.wav'
with wave.open(str(source), 'wb') as handle:
    handle.setnchannels(2); handle.setsampwidth(2); handle.setframerate(48000)
    handle.writeframes(b''.join(struct.pack('<h', int(8000 * math.sin(2 * math.pi * (230 + 60 * c) * i / 48000))) for i in range(40001) for c in range(2)))
capture = root / 'capture.m4a'
native('native AAC capture for extractAudio', [ffmpeg, '-nostdin', '-v', 'error', '-f', 'wav', '-i', str(source), '-c:a', 'aac', '-b:a', '128k', '-threads', '1', '-f', 'mp4', str(capture)])
extracted = adaptor.run({'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'e', 'filter': 'extractAudio', 'options': {'file': str(capture), 'streamIndex': 0}}]},
                        root / 'run-extract', executable=ffmpeg, timeout=120)
document = {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'p', 'filter': 'encodeAudio', 'options': {'file': extracted['audio'], 'bitrateKbps': 128, 'maxBytes': 1 << 20, 'maxMeanPCMError': 20000}}]}
result = adaptor.run(document, root / 'run-reuse', executable=ffmpeg, timeout=120)
answer = adaptor.verify(root / 'run-reuse', executable=ffmpeg)
cases.append({'case': 'extractAudio WAV (48000 Hz stereo, 40001 frames) re-published', 'frames': result['frames'], 'bytes': result['bytes'],
              'meanAbsPCMError': result['meanAbsPCMError'], 'freshVerified': answer['freshNativeVerification']})
print(json.dumps({'cases': cases, 'processes': processes, 'nativeChildren': children()}))
'''


def supervise(label, command, environment, timeout):
    """One bounded child: record its PID, limit, duration and exit status; never leave it running."""
    started = time.monotonic()
    child = subprocess.Popen(command, cwd=REPOSITORY, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    record = {'label': label, 'pid': child.pid, 'argv': command[:3] if command[1:2] == ['-c'] else command, 'timeoutSeconds': timeout}
    try:
        out, err = child.communicate(timeout=timeout)
        record['exitCode'] = child.returncode
    except subprocess.TimeoutExpired:
        child.kill()
        out, err = child.communicate()
        record.update(exitCode=None, timedOut=True)
    record['seconds'] = round(time.monotonic() - started, 1)
    return record, out, err


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, help='FFmpeg executable with ffprobe beside it')
    parser.add_argument('--output', required=True, type=Path, help='new JSON record; must not exist')
    parser.add_argument('--work', required=True, type=Path, help='new directory for generated fixtures and runs; must not exist')
    parser.add_argument('--baseline-src', type=Path, help='committed baseline src tree (git archive HEAD src) for the legacy control')
    parser.add_argument('--espeak', help='eSpeak NG executable for a real synthetic-voice publication')
    parser.add_argument('--timeout', type=float, default=400, help='seconds for each long child')
    args = parser.parse_args()
    for path in (args.output, args.work):
        if path.exists():
            sys.exit('refusing to overwrite ' + str(path))
    executable = str(Path(args.executable).absolute())
    args.work.mkdir(parents=True)
    environment = {**os.environ, 'PYTHONPATH': str(REPOSITORY / 'src'), 'FFMPEG_EXECUTABLE': executable}
    record = {'version': 'schemaxis.ffmpeg.audio-publish-qualification/1', 'executable': executable, 'children': []}
    version, out, _ = supervise('version', [executable, '-version'], environment, 30)
    version['identity'] = out.splitlines()[0] if out else None
    record['children'].append(version)
    suite, _, err = supervise('native-suite', [sys.executable, '-m', 'unittest', 'tests.unit.test_ffmpeg_audio_publish', '-v'], environment, args.timeout)
    summary = [line for line in err.splitlines() if line.startswith(('Ran ', 'OK', 'FAILED'))]
    suite.update(summary=summary, verified=suite.get('exitCode') == 0 and any(line.startswith('OK') for line in summary),
                 cases=sorted(line.split(' ... ')[0].split(' (')[0] for line in err.splitlines() if line.endswith(' ... ok')))
    record['children'].append(suite)
    matrix, out, err = supervise('geometry-matrix', [sys.executable, '-c', MATRIX, executable, str(args.work / 'matrix'), json.dumps(CASES)], environment, args.timeout)
    matrix['results'] = json.loads(out) if matrix.get('exitCode') == 0 and out.strip() else {'stderr': err[-800:]}
    matrix['verified'] = matrix.get('exitCode') == 0 and 'cases' in matrix['results']
    record['children'].append(matrix)
    for label, rate, channels, seconds, bitrate, error in EXTENDED_CASES:
        extended, out, err = supervise(label, [sys.executable, '-c', EXTENDED, executable, str(args.work / label), str(rate), str(channels), str(seconds), str(bitrate), str(error)],
                                       environment, args.timeout)
        extended['results'] = json.loads(out) if extended.get('exitCode') == 0 and out.strip() else {'stderr': err[-800:]}
        results = extended['results']
        extended['verified'] = extended.get('exitCode') == 0 and results.get('multiChunk') is True and results.get('samplesCounted') == results.get('expectedSamples')
        record['children'].append(extended)
    if args.baseline_src:
        old, out_old, err_old = supervise('legacy-baseline', [sys.executable, '-I', '-c', LEGACY, str(args.baseline_src)], {**environment, 'PYTHONPATH': ''}, 60)
        new, out_new, err_new = supervise('legacy-current', [sys.executable, '-I', '-c', LEGACY, str(REPOSITORY / 'src')], {**environment, 'PYTHONPATH': ''}, 60)
        same = old.get('exitCode') == 0 == new.get('exitCode') and out_old == out_new and bool(out_old.strip())
        record['children'] += [old, {**new, 'identicalToBaseline': same, 'verified': same, 'stderr': (err_old + err_new)[-300:]}]
    handoff, out, err = supervise('handoffs', [sys.executable, '-c', HANDOFF, executable, args.espeak or '-', str(args.work / 'handoff')], environment, args.timeout)
    handoff['results'] = json.loads(out) if handoff.get('exitCode') == 0 and out.strip() else {'stderr': err[-800:]}
    handoff['verified'] = handoff.get('exitCode') == 0 and 'cases' in handoff['results']
    record['children'].append(handoff)
    if args.espeak:
        flow, out, err = supervise('workflow-espeakng-encodeAudio', [sys.executable, '-c', WORKFLOW, executable, args.espeak, str(args.work / 'workflow'), str(REPOSITORY)],
                                   environment, args.timeout)
        flow['results'] = json.loads(out) if flow.get('exitCode') == 0 and out.strip() else {'stderr': err[-800:]}
        flow['verified'] = flow.get('exitCode') == 0 and flow['results'].get('workflowVerified') is True and flow['results'].get('budgetsAccepted') is True
        record['children'].append(flow)
    record['verified'] = all(child.get('verified', True) for child in record['children'])
    record['limits'] = [
        'Serial native cases on one FFmpeg 9.0.2 build and one CPU architecture; the geometry matrix is a bounded grid of rates, channel counts and '
        'lengths, not proof for every length or rate. No MPI or exhaustive codec coverage is claimed.',
        'maxMeanPCMError is a numeric waveform error in signed PCM16 units; nothing here measures or certifies listening quality, audibility, '
        'recognition accuracy or identity, no human listened to any output, and the eSpeak NG voice and tones are synthetic.',
        'Verification decodes the published M4A with a trusted FFmpeg and sibling ffprobe and compares every sample with the captured WAV. It does '
        'not re-encode, so it accepts any encoding meeting the declared criteria and does not authenticate the encoder; a coherent rewrite of source, '
        'output and summary is not detected. The independent decode uses the same FFmpeg AAC decoder through a different invocation.',
        'Observed MAE and byte figures are specific to this recipe and runtime; the encoder clamps by sample rate and size is not monotonic in bitrate.']
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'verified': record['verified'], 'children': [{k: c.get(k) for k in ('label', 'pid', 'exitCode', 'seconds', 'verified')} for c in record['children']]}, indent=2))
    sys.exit(0 if record['verified'] else 1)


if __name__ == '__main__':
    main()
