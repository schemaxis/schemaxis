#!/usr/bin/env python3
"""Qualify diagram-to-video handoffs, reordered frames, reuse and rejection.

Uses three independently configured native providers. This checks technical
publication and timing, not editorial quality or general project compatibility.
"""
import argparse
import copy
import json
from pathlib import Path

from schemaxis import workflow
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    locations = json.loads(args.config.read_text())['locations']
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=False)
    example = ROOT/'examples/schemaxis/diagram-to-edited-video.json'
    document = json.loads(example.read_text())
    report = {'version': 'schemaxis.diagram-video-qualification/1',
              'verified': False, 'scope': __doc__, 'checks': {},
              'recipeSHA256': file_digest(__file__), 'documentSHA256': file_digest(example),
              'sourceDigests': {app: source_digest(app) for app in ('inkscape', 'ffmpeg', 'shotcut')}}
    try:
        target = output/'workflow'
        result = workflow.execute(document, target, locations=locations, timeout=240)
        report['checks']['workflow'] = workflow.verify(target)
        assert len(result['jobs']) == 4
        jobs = {job['operation']: job for job in result['jobs']}
        assert set(jobs) == {'baseline', 'variant', 'animation', 'edit'}
        assert all(job['status'] == 'succeeded' for job in jobs.values())

        def native_receipt(operation):
            directory = Path(jobs[operation]['directory'])
            return json.loads((directory/'verification.json').read_text())

        def publications(operation):
            return native_receipt(operation)['artifacts']

        report['runtimes'] = {provider: native_receipt(operation)['runtime']
                              for provider, operation in (('inkscape', 'baseline'),
                                  ('ffmpeg', 'animation'), ('shotcut', 'edit'))}
        for operation, frames in (('animation', 6), ('edit', 5)):
            receipt = native_receipt(operation)
            assert {key: receipt[key] for key in ('frames', 'fps', 'width', 'height')} == {
                'frames': frames, 'fps': 12, 'width': 400, 'height': 200}, operation

        # Fixed authored expectations: six frames at 12 fps become five after
        # selecting [1, 2] then [0, 1, 2]. The Shotcut verifier independently
        # constructs and checks that exact RGB frame ordering from its source.
        edited = publications('edit')
        assert [item['kind'] for item in edited] == ['video', 'videoProject', 'videoProjectBundle']
        project = Path(edited[1]['file'])
        from xml.etree import ElementTree as ET
        tree = ET.parse(project)
        playlists = [playlist for playlist in tree.getroot().iter('playlist')
                     if playlist.get('id') == 'timeline']
        assert len(playlists) == 1, 'expected one named timeline'
        entries = [entry.attrib for entry in playlists[0].findall('entry')]
        assert entries == [
            {'producer': 'asset-process', 'in': '1', 'out': '2'},
            {'producer': 'asset-process', 'in': '0', 'out': '2'}], entries
        report['checks']['timeline'] = {'sourceFrames': 6, 'outputFrames': 5,
                                        'fps': 12, 'rangesInclusive': [[1, 2], [0, 2]]}

        resumed = workflow.execute(document, target, locations=locations, timeout=240, resume=True)
        assert len(resumed['jobs']) == 4
        assert {job['operation'] for job in resumed['jobs']} == set(jobs)
        assert all(job['status'] == 'succeeded' and job['reused'] for job in resumed['jobs'])
        workflow.verify(target)
        report['checks']['reusedJobs'] = len(resumed['jobs'])

        publication = Path(publications('baseline')[1]['file'])
        original = publication.read_bytes()
        try:
            publication.write_bytes(b'altered PNG publication')
            try:
                workflow.verify(target)
            except SchemaxisError as error:
                report['checks']['changedProducerRejected'] = error.fault.code
            else:
                raise AssertionError('changed producer publication was accepted')
        finally:
            publication.write_bytes(original)
        workflow.verify(target)

        bad = copy.deepcopy(document)
        # The source has six frames; demand seven. Native publication must be
        # withheld, and the downstream timeline must never report success.
        bad['operations'][2]['document']['deliverable']['frames'] = 7
        rejected = output/'unmet-deliverable'
        try:
            workflow.execute(bad, rejected, locations=locations, timeout=240)
        except SchemaxisError as error:
            assert error.fault.code == 'DELIVERABLE_NOT_MET', error.fault.to_dict()
            report['checks']['unmetProducerFault'] = error.fault.to_dict()
            assessment = error.fault.to_dict()['observed']['assessment']
            assert assessment['observed']['frames'] == 6
            assert [check['requirement'] for check in assessment['checks']
                    if not check['passed']] == ['frames'], assessment
        else:
            raise AssertionError('unmet producer deliverable was accepted')
        failed = json.loads((rejected/'result.json').read_text())
        failed_jobs = {job['operation']: job for job in failed['jobs']}
        assert failed['status'] == 'failed' and not failed['verified']
        assert failed_jobs['animation']['status'] == 'failed'
        assert 'edit' not in failed_jobs, 'downstream edit was launched after producer rejection'
        assert not (rejected/'edit').exists(), 'downstream edit created an execution directory'
        report['checks']['unmetProducerBlocksEdit'] = True
        report['verified'] = True
    finally:
        atomic_json(output/'qualification.json', report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
