#!/usr/bin/env python3
"""Bounded native acceptance of the FFmpeg extractAudio operation.

Runs, each in its own supervised child process with a recorded PID, timeout and exit status:

* the native cases of tests/unit/test_ffmpeg_audio.py (real AAC mono/stereo/odd-length/one-frame/H.264+AAC sources, refusals,
  coherent forgeries, planted runtimes, deadline, cancellation, strict evidence);
* a rate and geometry matrix: deterministic generated PCM encoded by the native AAC encoder (explicit ``-f mp4``), extracted by the
  adaptor, then decoded again by a separate native invocation with different arguments (no forced demuxer, no bit-exact flag,
  default stream selection) and parsed by the standard-library ``wave`` module; every PCM byte must equal the published WAV;
* optionally (--sox, --whisper-cli, --whisper-model, --whisper-sample) a workflow of extractAudio, SoX conform and whisper.cpp
  transcription of a real speech sample encoded to AAC, checked for structural consistency only (no recognition accuracy claim);
* optionally (--genuine) read-only verification of retained runs of the older operations through the unchanged paths.

It never overwrites a retained run. Fixtures are generated tones, never proprietary speech. The record carries every PID."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPOSITORY = Path(__file__).resolve().parent.parent
RATES = (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 64000, 88200, 96000)
MATRIX = '''
import json, math, struct, subprocess, sys, time, wave
from pathlib import Path
from schemaxis.adaptors.ffmpeg import adaptor
ffmpeg, root, rates = sys.argv[1], Path(sys.argv[2]), json.loads(sys.argv[3])
root.mkdir()
processes, rows = [], []
def native(label, command):
    started = time.monotonic()
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = child.communicate(timeout=60)
    processes.append({'label': label, 'pid': child.pid, 'timeoutSeconds': 60, 'exitCode': child.returncode,
                      'seconds': round(time.monotonic() - started, 2)})
    assert child.returncode == 0, (label, err[-300:])
def tone(frames, channels, rate, seed):
    data = bytearray()
    for i in range(frames):
        for c in range(channels):
            data += struct.pack('<h', int(8000 * math.sin(2 * math.pi * (190 + 70 * c + 25 * seed) * i / rate) * (0.4 + 0.6 * math.sin(i / 733 + seed))))
    return bytes(data)
cases = [('rate-%d-mono' % r, 2000 + 37 * (n + 1), 1, r, False) for n, r in enumerate(rates)]
cases += [('stereo-44100-odd', 30001, 2, 44100, False), ('stereo-48000-odd', 47999, 2, 48000, False), ('mono-16000-one-frame', 1, 1, 16000, False),
          ('mono-16000-1023', 1023, 1, 16000, False), ('mono-16000-1025', 1025, 1, 16000, False), ('mono-16000-2049', 2049, 1, 16000, False),
          ('av-mono-22050', 33333, 1, 22050, True), ('av-stereo-32000', 70000, 2, 32000, True)]
for name, frames, channels, rate, video in cases:
    source = root / (name + '.wav')
    with wave.open(str(source), 'wb') as handle:
        handle.setnchannels(channels); handle.setsampwidth(2); handle.setframerate(rate); handle.writeframes(tone(frames, channels, rate, len(name) % 5))
    mp4 = root / (name + '.mp4')
    command = [ffmpeg, '-nostdin', '-v', 'error', '-f', 'wav', '-i', str(source)]
    if video:
        raw = root / (name + '.rgb')
        raw.write_bytes(bytes((x * 7 + y * 3 + f * 11) & 255 for f in range(25) for y in range(16) for x in range(16) for _ in range(3)))
        command += ['-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', '16x16', '-framerate', '25', '-i', str(raw),
                    '-map', '1:v:0', '-map', '0:a:0', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-shortest']
    else:
        command += ['-map', '0:a:0', '-vn']
    native('encode ' + name, command + ['-c:a', 'aac', '-b:a', '64k', '-threads', '1', '-f', 'mp4', str(mp4)])
    index = 1 if video else 0
    started = time.monotonic()
    result = adaptor.run({'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'speech', 'filter': 'extractAudio',
        'options': {'file': str(mp4), 'streamIndex': index}}]}, root / ('run-' + name), executable=ffmpeg, timeout=120)
    answer = adaptor.verify(root / ('run-' + name), executable=ffmpeg)
    independent = root / (name + '.independent.wav')
    native('independent decode ' + name, [ffmpeg, '-nostdin', '-v', 'error', '-i', str(mp4), '-map', '0:%d' % index, '-c:a', 'pcm_s16le', str(independent)])
    with wave.open(str(independent), 'rb') as handle:
        other = (handle.getnchannels(), handle.getframerate(), handle.getnframes(), handle.readframes(handle.getnframes()))
    with wave.open(str(root / ('run-' + name) / 'audio.wav'), 'rb') as handle:
        mine = (handle.getnchannels(), handle.getframerate(), handle.getnframes(), handle.readframes(handle.getnframes()))
    assert mine == other, name
    published = (root / ('run-' + name) / 'audio.wav').read_bytes()
    assert len(published) == 44 + len(mine[3]) and published[36:40] == b'data'
    rows.append({'case': name, 'sourceFrames': frames, 'decodedFrames': mine[2], 'sampleRate': rate, 'channels': channels, 'streamIndex': index,
                 'independentPcmEqual': True, 'freshVerified': answer['freshNativeVerification'], 'seconds': round(time.monotonic() - started, 2)})
print(json.dumps({'cases': rows, 'processes': processes}))
'''
CHAIN = '''
import hashlib, json, subprocess, sys, wave
from pathlib import Path
from schemaxis import workflow
ffmpeg, sox, whisper, model, sample, root = sys.argv[1:7]
root = Path(root)
root.mkdir()
processes = []
def native(label, command):
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = child.communicate(timeout=120)
    processes.append({'label': label, 'pid': child.pid, 'timeoutSeconds': 120, 'exitCode': child.returncode})
    assert child.returncode == 0, (label, err[-300:])
capture = root / 'capture.m4a'
native('aac capture of the speech sample', [ffmpeg, '-nostdin', '-v', 'error', '-f', 'wav', '-i', sample, '-t', '11', '-c:a', 'aac', '-b:a', '64k', '-threads', '1', '-f', 'mp4', str(capture)])
pin = hashlib.sha256(Path(model).read_bytes()).hexdigest()
graph = {'version': 'schemaxis.workflow/1', 'operations': [
    {'id': 'extract', 'document': {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'speech', 'filter': 'extractAudio', 'options': {'file': str(capture), 'streamIndex': 0}}]}},
    {'id': 'prepare', 'document': {'version': 'schemaxis.sox/1', 'operation': 'conform', 'source': {'$artifact': 'extract', 'index': 0}, 'channelPolicy': 'average'}},
    {'id': 'draft', 'document': {'version': 'schemaxis.whispercpp/1', 'operation': 'transcribe', 'audio': {'path': {'$artifact': 'prepare', 'index': 0}},
        'model': {'path': model, 'sha256': pin}, 'language': 'en'}}]}
(root / 'workflow.json').write_text(json.dumps(graph, indent=2) + '\\n')
locations = {'ffmpeg': ffmpeg, 'sox': sox, 'whispercpp': whisper}
result = workflow.execute(graph, root / 'run', locations=locations, timeout=300)
verified = workflow.verify(root / 'run')
assert verified['verified']
audio = list((root / 'run' / 'extract').rglob('audio.wav'))
conformed = list((root / 'run' / 'prepare').rglob('audio.wav'))
segments = [p for p in (root / 'run').rglob('segments.json') if json.loads(p.read_text()).get('version') == 'schemaxis.whispercpp.segments/1']
assert len(audio) == len(conformed) == len(segments) == 1, (audio, conformed, segments)
with wave.open(str(conformed[0]), 'rb') as handle:
    assert (handle.getnchannels(), handle.getframerate()) == (1, 16000)
text = ' '.join(s['text'].strip() for s in json.loads(segments[0].read_text())['segments'])
assert text.strip(), 'the transcript is empty'
print(json.dumps({'verified': True, 'workflow': verified, 'transcriptCharacters': len(text), 'transcriptFirstWords': text.split()[:6],
                  'scope': 'structural consistency only; no recognition accuracy or human review is claimed', 'processes': processes}))
'''
VERIFY = '''
import json, sys, time
from schemaxis.adaptors.ffmpeg import adaptor
results = []
for directory in sys.argv[1:]:
    started = time.monotonic()
    try:
        answer = adaptor.verify(directory)
        results.append({'directory': directory, 'verified': answer['verified'], 'seconds': round(time.monotonic() - started, 2)})
    except Exception as error:
        fault = getattr(error, 'fault', None)
        results.append({'directory': directory, 'verified': False, 'fault': fault.to_dict() if fault else repr(error)})
print(json.dumps(results))
'''


def supervise(label, command, environment, timeout):
    """One bounded child: record its PID, limit, duration and exit status; never leave it running."""
    started = time.monotonic()
    child = subprocess.Popen(command, cwd=REPOSITORY, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    record = {'label': label, 'pid': child.pid, 'timeoutSeconds': timeout}
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
    parser.add_argument('--work', required=True, type=Path, help='new empty directory for generated fixtures and runs; must not exist')
    parser.add_argument('--sox', help='SoX executable for the conform handoff')
    parser.add_argument('--whisper-cli', help='whisper-cli executable')
    parser.add_argument('--whisper-model', help='local ggml model file (never fetched)')
    parser.add_argument('--whisper-sample', help='local speech WAV, e.g. the whisper.cpp jfk sample')
    parser.add_argument('--genuine', nargs='*', default=[], type=Path, help='retained run directories to verify read-only')
    parser.add_argument('--timeout', type=float, default=300, help='seconds for each long child')
    args = parser.parse_args()
    for path in (args.output, args.work):
        if path.exists():
            sys.exit('refusing to overwrite ' + str(path))
    executable = str(Path(args.executable).absolute())
    args.work.mkdir(parents=True)
    environment = {**os.environ, 'PYTHONPATH': str(REPOSITORY / 'src'), 'FFMPEG_EXECUTABLE': executable}
    record = {'version': 'schemaxis.ffmpeg.audio-qualification/1', 'executable': executable, 'children': []}
    version, out, _ = supervise('version', [executable, '-version'], environment, 30)
    version['identity'] = out.splitlines()[0] if out else None
    record['children'].append(version)
    suite, _, err = supervise('native-suite', [sys.executable, '-m', 'unittest', 'tests.unit.test_ffmpeg_audio', '-v'], environment, args.timeout)
    summary = [line for line in err.splitlines() if line.startswith(('Ran ', 'OK', 'FAILED'))]
    suite.update(summary=summary, verified=suite.get('exitCode') == 0 and any(line.startswith('OK') for line in summary))
    suite['cases'] = sorted(line.split(' ... ')[0].split(' (')[0] for line in err.splitlines() if line.endswith(' ... ok'))
    record['children'].append(suite)
    matrix, out, err = supervise('independent-matrix', [sys.executable, '-c', MATRIX, executable, str(args.work / 'matrix'), json.dumps(RATES)],
                                 environment, args.timeout)
    matrix['results'] = json.loads(out) if matrix.get('exitCode') == 0 and out.strip() else {'stderr': err[-600:]}
    matrix['verified'] = matrix.get('exitCode') == 0 and isinstance(matrix['results'], dict) and 'cases' in matrix['results']
    record['children'].append(matrix)
    if args.sox and args.whisper_cli and args.whisper_model and args.whisper_sample:
        chain, out, err = supervise('speech-workflow', [sys.executable, '-c', CHAIN, executable, args.sox, args.whisper_cli,
                                    args.whisper_model, args.whisper_sample, str(args.work / 'chain')], environment, args.timeout)
        chain['results'] = json.loads(out) if chain.get('exitCode') == 0 and out.strip() else {'stderr': err[-600:]}
        chain['verified'] = chain.get('exitCode') == 0 and isinstance(chain['results'], dict) and chain['results'].get('verified') is True
        record['children'].append(chain)
    if args.genuine:
        genuine, out, err = supervise('genuine-read-only', [sys.executable, '-c', VERIFY, *map(str, args.genuine)], environment, 180)
        genuine['results'] = json.loads(out) if genuine.get('exitCode') == 0 and out.strip() else []
        genuine['verified'] = bool(genuine['results']) and all(item['verified'] for item in genuine['results'])
        record['children'].append(genuine)
    record['verified'] = all(child.get('verified', True) for child in record['children'])
    record['limits'] = [
        'Verification decodes the captured compressed bytes again with a trusted FFmpeg and sibling ffprobe (explicit executable, stored '
        'configuration or FFMPEG_EXECUTABLE; never PATH or a receipt path). The capture in the run directory is an unauthenticated trust '
        'anchor: a coherent rewrite of the capture and all evidence is not detected.',
        'AAC is lossy: the WAV is a decode, not the original recording; no recognition accuracy or human review is certified, and the '
        'optional workflow checks structure only.',
        'Cases ran serially on one FFmpeg build; the independent decode uses the same FFmpeg AAC decoder through a different invocation, '
        'so it checks the recipe, the frame accounting and the canonical WAV, not the decoder itself. No exhaustive codec or MP4 coverage.',
        'The bounded probe refuses rather than truncates: ffprobe output over 4 MiB (large metadata tags), more than 17600 packets or 17500 '
        'decoded frames, and a decode larger than the counted frames are RESOURCE_LIMIT. The native suite exercises the 4 MiB output cap and '
        'the decode cap; FFmpeg encodes only 1024-sample AAC frames, so the 960-sample AAC-LC coverage of the packet bound is arithmetic and a '
        'host test, not a native source, and exhaustive AAC-LC coverage is not claimed.']
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({key: record[key] for key in ('verified', 'children')}, indent=2)[:3000])
    sys.exit(0 if record['verified'] else 1)


if __name__ == '__main__':
    main()
