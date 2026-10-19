#!/usr/bin/env python3
"""Opt-in installed Premiere layout acceptance; never runs DOM doubles."""
import argparse
import copy
import json
from pathlib import Path
import sys
import threading
import time

from schemaxis.adaptors.premiere import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[1]


def observe(document, target, bridge, timeout):
    print('Activate ' + document['sequenceName'] + '; select its fresh folder when printed.', flush=True)
    stop = threading.Event()
    def show_job():
        deadline = time.monotonic() + timeout
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                job = json.loads((target / 'bridge-job.json').read_text())
                print('Select job folder: ' + job['jobDirectory'], flush=True)
                return
            except (OSError, ValueError, KeyError):
                stop.wait(.1)
    monitor = threading.Thread(target=show_job, daemon=True)
    monitor.start()
    try:
        return adaptor.run(document, target, bridge=bridge, timeout=timeout)
    finally:
        stop.set()
        monitor.join(timeout=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge', required=True, type=Path)
    parser.add_argument('--project-path', required=True)
    parser.add_argument('--source-path', required=True)
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--timeout', type=float, default=300)
    args = parser.parse_args()
    if sys.platform not in ('win32', 'darwin'):
        parser.error('Installed Premiere layout acceptance requires Windows/macOS; Linux cannot qualify this integration')
    target = args.output_directory.absolute()
    target.mkdir(parents=True, exist_ok=False)
    cases = []
    for identity, suffix, occupied, ranges, gaps in [
        ('baseline', '', 4, ('30481920000', '71124480000', '0', '40642560000'),
         [{'startFrame': 0, 'endFrame': 3}, {'startFrame': 7, 'endFrame': 10}]),
        ('held-out', '-variant', 2, ('40642560000', '60963840000', '10160640000', '30481920000'),
         [{'startFrame': 0, 'endFrame': 4}, {'startFrame': 6, 'endFrame': 10}])]:
        document = json.loads((ROOT / ('examples/schemaxis/premiere-layout' + suffix + '.json')).read_text())
        document['projectPath'] = args.project_path
        for track in document['tracks']:
            for clip in track['clips']:
                clip['sourcePath'] = args.source_path
        directory = target / identity
        observe(document, directory, args.bridge.absolute(), args.timeout)
        verification = adaptor.verify(directory)
        observation = json.loads((directory / 'observation.json').read_text())
        report = json.loads((directory / 'layout.json').read_text())
        literal_base = [('0', '40642560000', '0', '40642560000'),
                        ('60963840000', '101606400000', '20321280000', '60963840000')]
        actual = [tuple(clip[key] for key in ('startTicks', 'endTicks', 'inTicks', 'outTicks'))
                  for clip in observation['tracks'][0]['clips']]
        if actual != literal_base:
            raise AssertionError('Base native intervals differ from independent literal ticks')
        clip = observation['tracks'][1]['clips'][0]
        if tuple(clip[key] for key in ('startTicks', 'endTicks', 'inTicks', 'outTicks')) != ranges:
            raise AssertionError('Overlay native intervals differ from independent literal ticks')
        if [track['name'] for track in observation['tracks']] != ['Base', 'Overlay', 'Reserved']:
            raise AssertionError('Native track identities differ')
        expected = [
            {'name': 'Base', 'occupiedFrames': 8, 'gaps': [{'startFrame': 4, 'endFrame': 6}]},
            {'name': 'Overlay', 'occupiedFrames': occupied, 'gaps': gaps},
            {'name': 'Reserved', 'occupiedFrames': 0, 'gaps': [{'startFrame': 0, 'endFrame': 10}]}]
        if report['tracks'] != expected or any(row['uncoveredFrames'] for row in report['requirements']):
            raise AssertionError('Native editorial layout differs from independent occupancy expectations')
        mutations = []
        for filename in ('layout.json', 'request.json', 'response.json', 'observation.json', 'verification.json'):
            path = directory / filename
            original = path.read_bytes()
            try:
                path.write_text('{}')
                try:
                    adaptor.verify(directory)
                except SchemaxisError as error:
                    mutations.append({'file': filename, 'fault': error.fault.code})
                else:
                    raise AssertionError('Changed evidence was accepted')
            finally:
                path.write_bytes(original)
        adaptor.verify(directory)
        cases.append({'id': identity, 'runtime': verification['runtime'], 'literalOverlayTicks': ranges,
                      'literalTracks': expected, 'mutations': mutations})
        if identity == 'baseline':
            failed = copy.deepcopy(document)
            failed['requirements'][0]['tracks'] = ['Base']
            try:
                observe(failed, target / 'failed-gate', args.bridge.absolute(), args.timeout)
            except SchemaxisError as error:
                if error.fault.code != 'REQUIREMENT_FAILED':
                    raise
            else:
                raise AssertionError('Native Base-only gap coverage incorrectly passed')
            failure = json.loads((target / 'failed-gate/layout.json').read_text())
            if failure['requirements'][0]['uncoveredFrames'] != [4, 5]:
                raise AssertionError('Native uncovered frames differ')
    report = {'nativeExecution': True, 'verified': True, 'provider': 'premiere', 'cases': cases,
              'scope': 'Read-only complete named-track editorial occupancy; no rendered pixels, native editing or exhaustive lifecycle qualification.'}
    atomic_json(target / 'acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
