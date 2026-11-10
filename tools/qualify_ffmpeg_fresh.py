#!/usr/bin/env python3
"""Bounded native acceptance of fresh verification for encodeFrames, encodeSheet and encodeVideo.

Runs the native cases of tests/unit/test_ffmpeg_fresh.py (genuine runs, coherent forgeries of the published bytes and of the
captured-source readbacks, strict evidence, wrong and planted runtimes, deadline, cancellation, byte budget and cleanup) in one
supervised child process, then verifies any genuine retained runs given with --genuine read-only. It never overwrites a
retained run. The record carries actual PIDs, the timeout and exit status of every child."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPOSITORY = Path(__file__).resolve().parent.parent
VERIFY = '''
import json, sys, time
from schemaxis.adaptors.ffmpeg import adaptor
results = []
for directory in sys.argv[1:]:
    started = time.monotonic()
    try:
        answer = adaptor.verify(directory)
        results.append({'directory': directory, 'verified': answer['verified'], 'frames': answer['frames'],
                        'fresh': answer['freshNativeVerification'], 'colourTagged': answer['colourTagged'],
                        'seconds': round(time.monotonic() - started, 2)})
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
    parser.add_argument('--genuine', nargs='*', default=[], type=Path, help='retained run directories to verify read-only')
    parser.add_argument('--timeout', type=float, default=180, help='seconds for the native case suite')
    args = parser.parse_args()
    if args.output.exists():
        sys.exit('refusing to overwrite ' + str(args.output))
    executable = str(Path(args.executable).absolute())
    environment = {**os.environ, 'PYTHONPATH': str(REPOSITORY / 'src'), 'FFMPEG_EXECUTABLE': executable}
    record = {'version': 'schemaxis.ffmpeg.fresh-qualification/1', 'executable': executable, 'children': []}
    version, _, _ = supervise('version', [executable, '-version'], environment, 30)
    record['children'].append(version)
    suite, out, err = supervise('native-suite', [sys.executable, '-m', 'unittest', 'tests.unit.test_ffmpeg_fresh', '-v'], environment, args.timeout)
    summary = [line for line in err.splitlines() if line.startswith(('Ran ', 'OK', 'FAILED'))]
    suite.update(summary=summary, verified=suite.get('exitCode') == 0 and any(line.startswith('OK') for line in summary))
    suite['cases'] = sorted(line.split(' ... ')[0].split(' (')[0] for line in err.splitlines() if line.endswith(' ... ok'))
    record['children'].append(suite)
    if args.genuine:
        genuine, out, err = supervise('genuine-read-only', [sys.executable, '-c', VERIFY, *map(str, args.genuine)], environment, 120)
        genuine['results'] = json.loads(out) if genuine.get('exitCode') == 0 and out.strip() else []
        genuine['verified'] = bool(genuine['results']) and all(item['verified'] for item in genuine['results'])
        record['children'].append(genuine)
    record['verified'] = all(child.get('verified', True) for child in record['children'])
    record['limits'] = [
        'Verification decodes the published bytes again with a trusted FFmpeg and sibling ffprobe (explicit executable, stored '
        'configuration or FFMPEG_EXECUTABLE; never PATH or a receipt path). The captured sources in the run directory remain the '
        'trust anchor: a coherent rewrite of captures and evidence is not authenticated, and an equivalent in-budget re-encode can verify.',
        'The cases ran serially on one runtime build; no exhaustive native coverage, no signed-source authenticity and no host-offline decode claim.']
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({key: record[key] for key in ('verified', 'children')}, indent=2))
    sys.exit(0 if record['verified'] else 1)


if __name__ == '__main__':
    main()
