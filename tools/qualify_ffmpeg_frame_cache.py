#!/usr/bin/env python3
"""Bounded acceptance of the per-call PNG frame reuse in the FFmpeg frame preparation.

Runs, in supervised child processes with recorded PIDs, timeouts and exit statuses: the host and native cases of
tests/unit/test_ffmpeg_frame_cache.py; a controlled before/after timing of `adaptor.frames` over one fixed repeated A/B/A
sequence (the baseline is a separate source tree given with --baseline-source, alternated with the current tree so both see the
same machine load); and a read-only standalone verification of any genuine retained runs given with --genuine, with the
baseline and current sources side by side. It never writes into a retained run. Timings are for this machine on this day and
say nothing about other hardware, other inputs or the CPU share of a whole workflow."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

REPOSITORY = Path(__file__).resolve().parent.parent
BENCHMARK = '''
import hashlib, json, resource, struct, sys, time, zlib
from schemaxis.adaptors.ffmpeg import adaptor

WIDTH, HEIGHT, FRAMES, PATTERN = 960, 320, int(sys.argv[1]), sys.argv[2]

def png(seed):
    rows = b''.join(b'\\x00' + b''.join(bytes(((x * 3 + y * 5 + seed * 40) & 255, (x * 7 + seed * 90) & 255, (y * 11 + x) & 255,
                                              (x + y * 2 + seed * 60) & 255)) for x in range(WIDTH)) for y in range(HEIGHT))
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\\x89PNG\\r\\n\\x1a\\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', WIDTH, HEIGHT, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))

held = {'A': png(1), 'B': png(2)}
sequence = (PATTERN * FRAMES)[:FRAMES]
payloads = [bytes(held[letter]) for letter in sequence]       # separate bytes objects, as separate captured files give
prepared = adaptor.plan({'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'clip', 'filter': 'encodeFrames',
    'options': {'files': ['/in/%d.png' % i for i in range(FRAMES)], 'fps': 10, 'codec': 'ffv1'}}]})
calls = [0]
real = adaptor.decode
def counted(data):
    calls[0] += 1
    return real(data)
adaptor.decode = counted
wall, cpu = time.monotonic(), time.process_time()
width, height, pixels = adaptor.frames(prepared, payloads)
wall, cpu = time.monotonic() - wall, time.process_time() - cpu
print(json.dumps({'source': adaptor.__file__, 'frames': len(pixels), 'unique': len(set(sequence)), 'decoderCalls': calls[0],
                  'dimensions': [width, height], 'wallSeconds': round(wall, 2), 'cpuSeconds': round(cpu, 2),
                  'orderedPixelsSHA256': hashlib.sha256(b''.join(pixels)).hexdigest(),
                  'peakRSSMiB': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)}))
'''
VERIFY = '''
import json, sys, time
from schemaxis.adaptors.ffmpeg import adaptor
results = []
for directory in sys.argv[1:]:
    started = time.monotonic()
    try:
        answer = adaptor.verify(directory)
        results.append({'directory': directory, 'verified': answer['verified'], 'frames': answer['frames'],
                        'fresh': answer['freshNativeVerification'], 'seconds': round(time.monotonic() - started, 2),
                        'source': adaptor.__file__})
    except Exception as error:
        fault = getattr(error, 'fault', None)
        results.append({'directory': directory, 'verified': False, 'fault': fault.to_dict() if fault else repr(error)})
print(json.dumps(results))
'''


def supervise(label, command, environment, timeout):
    """One bounded child: record its PID, limit, duration and exit status; never leave it running."""
    started = time.monotonic()
    child = subprocess.Popen(command, cwd=REPOSITORY, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    record = {'label': label, 'pid': child.pid, 'timeoutSeconds': timeout, 'loadBefore': os.getloadavg()[0]}
    try:
        out, err = child.communicate(timeout=timeout)
        record['exitCode'] = child.returncode
    except subprocess.TimeoutExpired:
        child.kill()
        out, err = child.communicate()
        record.update(exitCode=None, timedOut=True)
    record['seconds'] = round(time.monotonic() - started, 1)
    record['loadAfter'] = os.getloadavg()[0]
    return record, out, err


def last_json(out):
    for line in reversed(out.strip().splitlines()):
        try: return json.loads(line)
        except ValueError: continue
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, help='FFmpeg executable with ffprobe beside it')
    parser.add_argument('--baseline-source', required=True, type=Path, help='a src directory holding the pre-change adaptor')
    parser.add_argument('--output', required=True, type=Path, help='new JSON record; must not exist')
    parser.add_argument('--genuine', nargs='*', default=[], type=Path, help='retained run directories to verify read-only')
    parser.add_argument('--frames', type=int, default=80, help='frames in the timed repeated sequence')
    parser.add_argument('--pattern', default='ABA', help='letters (A or B) repeated to make the sequence')
    parser.add_argument('--repeats', type=int, default=3, help='alternating baseline/current timing pairs')
    parser.add_argument('--suite-timeout', type=float, default=300)
    parser.add_argument('--verify-timeout', type=float, default=180, help='per source tree, for the standalone genuine verify')
    args = parser.parse_args()
    if args.output.exists():
        sys.exit('refusing to overwrite ' + str(args.output))
    executable = str(Path(args.executable).absolute())
    current = {**os.environ, 'PYTHONPATH': str(REPOSITORY / 'src'), 'FFMPEG_EXECUTABLE': executable}
    baseline = {**current, 'PYTHONPATH': str(args.baseline_source.absolute())}
    record = {'version': 'schemaxis.ffmpeg.frame-cache-qualification/1', 'executable': executable,
              'machine': {'cpus': os.cpu_count(), 'platform': platform.platform(), 'python': platform.python_version(),
                          'loadAverageAtStart': os.getloadavg()},
              'children': []}
    version, _, _ = supervise('version', [executable, '-version'], current, 30)
    record['children'].append(version)
    suite, out, err = supervise('frame-cache-suite', [sys.executable, '-m', 'unittest', 'tests.unit.test_ffmpeg_frame_cache', '-v'],
                                current, args.suite_timeout)
    summary = [line for line in err.splitlines() if line.startswith(('Ran ', 'OK', 'FAILED'))]
    suite.update(summary=summary, verified=suite.get('exitCode') == 0 and any(line.startswith('OK') for line in summary),
                 cases=sorted(line.split(' ... ')[0].split(' (')[0] for line in err.splitlines() if line.endswith(' ... ok')))
    record['children'].append(suite)
    timings = {'baseline': [], 'current': []}
    for index in range(args.repeats):
        for label, environment in (('baseline', baseline), ('current', current)):
            child, out, err = supervise(f'frames-{label}-{index + 1}', [sys.executable, '-c', BENCHMARK, str(args.frames), args.pattern],
                                        environment, 400)
            child['result'] = last_json(out)
            child['verified'] = child.get('exitCode') == 0 and child['result'] is not None
            record['children'].append(child)
            if child['verified']: timings[label].append(child['result'])
    comparison = {}
    if timings['baseline'] and timings['current']:
        digests = {item['orderedPixelsSHA256'] for items in timings.values() for item in items}
        comparison = {'identicalOrderedPixels': len(digests) == 1,
                      'decoderCalls': {label: sorted({item['decoderCalls'] for item in items}) for label, items in timings.items()},
                      'uniqueFrames': timings['current'][0]['unique'], 'frames': timings['current'][0]['frames']}
        for label, items in timings.items():
            comparison[label] = {key: sorted(item[key] for item in items) for key in ('wallSeconds', 'cpuSeconds', 'peakRSSMiB')}
        base, new = min(comparison['baseline']['cpuSeconds']), min(comparison['current']['cpuSeconds'])
        comparison['bestCpuRatio'] = round(base / new, 1) if new else None
    record['frameBenchmark'] = comparison
    record['children'].append({'label': 'benchmark-comparison', 'verified': bool(comparison) and comparison['identicalOrderedPixels']
                               and comparison['decoderCalls']['current'] == [comparison['uniqueFrames']]
                               and comparison['decoderCalls']['baseline'] == [comparison['frames']]})
    if args.genuine:
        for label, environment in (('current', current), ('baseline', baseline)):
            genuine, out, err = supervise(f'genuine-read-only-{label}', [sys.executable, '-c', VERIFY, *map(str, args.genuine)],
                                          environment, args.verify_timeout)
            genuine['results'] = last_json(out) or [] if genuine.get('exitCode') == 0 else []
            genuine['verified'] = bool(genuine['results']) and all(item['verified'] for item in genuine['results'])
            record['children'].append(genuine)
    record['verified'] = all(child.get('verified', True) for child in record['children'])
    record['limits'] = [
        'Only frame preparation is timed. A whole workflow also spends time in encoding, native decoding, audio and caption steps '
        'that this change does not touch, so a speedup here is not a speedup of any workflow as a whole.',
        'The cache is local to one frames() call: run, its own verification, the fresh native pass and a later standalone verify '
        'each decode the distinct PNGs again. Timings come from one machine, serial, with other processes possibly sharing the CPU '
        '(load averages are recorded); they are not portable performance claims.',
        'The baseline is the previous adaptor.py in an otherwise identical source tree. The cases ran serially on one runtime build; '
        'no exhaustive native coverage is claimed.']
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({key: record[key] for key in ('verified', 'frameBenchmark')}, indent=2))
    sys.exit(0 if record['verified'] else 1)


if __name__ == '__main__':
    main()
