#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Native acceptance through the public local agent transport, with retained evidence.

This is a deterministic client, not an evaluation of a language model. Dimensions
are case variants beyond the M1 example. Configure FreeCAD, Octave and Calc first.
"""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time


class Client:
    def __init__(self, workspace, *, config=None):
        environment = dict(os.environ)
        if config is not None:
            environment['SCHEMAXIS_CONFIG'] = str(config)
        self.process = subprocess.Popen([sys.executable, '-m', 'schemaxis', 'agent', '--workspace', str(workspace)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        env=environment, text=True, bufsize=1)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.serial = 0
        self.records = []

    def request(self, method, **params):
        self.serial += 1
        request = {'id': self.serial, 'method': method, 'params': params}
        payload = json.dumps(request)+'\n'
        started = time.monotonic()
        self.process.stdin.write(payload)
        self.process.stdin.flush()
        if not self.selector.select(timeout=30):
            raise AssertionError('tool response exceeded thirty seconds: '+method)
        line = self.process.stdout.readline()
        if not line:
            raise AssertionError('agent transport exited: '+self.process.stderr.read())
        response = json.loads(line)
        assert response['id'] == self.serial
        self.records.append({'method': method, 'requestBytes': len(payload.encode()),
                             'responseBytes': len(line.encode()), 'ok': response['ok'],
                             'seconds': round(time.monotonic()-started, 4)})
        return response

    def call(self, method, **params):
        response = self.request(method, **params)
        if not response['ok']:
            raise AssertionError(json.dumps(response['fault']))
        return response['result']

    def wait(self, job, seconds=180):
        deadline = time.monotonic()+seconds
        while time.monotonic()<deadline:
            status = self.call('job', job_id=job['id'])
            if status['status'] not in ('running', 'cancellation-requested'):
                return status
            time.sleep(.1)
        self.call('cancel', job_id=job['id'])
        raise AssertionError('native job exceeded client wait budget')

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
            raise AssertionError('agent service did not close after EOF')
        finally:
            self.selector.close()
        if self.process.returncode:
            raise AssertionError(self.process.stderr.read())
        self.process.stdout.close()
        self.process.stderr.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    root = args.output_directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    report = {'verified': False, 'scope': 'Deterministic local client; no autonomous-model or MPI qualification.',
              'cases': [], 'negativeChecks': []}
    client = Client(root/'session')
    try:
        client.call('methods')
        client.call('capabilities.browse')
        contract = client.call('capabilities.describe', identity='operation/freecad/box')['sections']
        for length, width, height, target in [(20, 10, 5, 1500), (7, 11, 3, 693), (12, 8, 4, 960)]:
            task = client.call('create_task', objective='Construct and refine a box to '+str(target)+' mm3',
                               allowed_providers=['freecad'], budget={'maxAttempts': 2, 'maxElapsedSeconds': 180})
            document = {'version': contract['requirements']['documentVersion'], 'nodes': [
                {'id': 'body', 'filter': contract['provenance']['operationKey'],
                 'options': {'length': length, 'width': width, 'height': height}}], 'output': 'body'}
            case = {'dimensionsMM': [length, width, height], 'targetVolumeMM3': target, 'attempts': []}
            revision = 0
            for _ in range(2):
                plan = client.call('plan', task_id=task['id'], document=document, expected_revision=revision)
                revision = plan['revision']
                observed_plan = client.call('observe', plan_id=plan['id'], section='plan')
                assert observed_plan['mode'] == 'value'
                job = client.call('execute', plan_id=plan['id'], expected_revision=revision)
                status = client.wait(job)
                assert status['status'] == 'succeeded', status
                observation = client.call('observe', job_id=job['id'])['value']
                assert math.isclose(observation['volumeMM3'], length*width*document['nodes'][0]['options']['height'], rel_tol=1e-8)
                assert client.call('verify', job_id=job['id'])['value']['verified']
                case['attempts'].append({'job': job['id'], 'observed': observation})
                document['nodes'][0]['options']['height'] *= target/observation['volumeMM3']
            assert math.isclose(case['attempts'][-1]['observed']['volumeMM3'], target, rel_tol=1e-8)
            report['cases'].append(case)

        document = json.loads((Path(__file__).resolve().parents[1]/'examples/schemaxis/analysis/octave-to-calc.json').read_text())
        task = client.call('create_task', objective='Transfer a spectrum through a verified Calc workbook and read it back',
                           allowed_providers=['octave', 'calc'], budget={'maxAttempts': 1, 'maxElapsedSeconds': 180})
        plan = client.call('plan', task_id=task['id'], document=document, expected_revision=0)
        job = client.call('execute', plan_id=plan['id'], expected_revision=plan['revision'])
        status = client.wait(job)
        assert status['status'] == 'succeeded', client.call('observe', job_id=job['id'], section='fault')
        verification = client.call('verify', job_id=job['id'])['value']
        resources = client.call('observe', job_id=job['id'], section='resources')['value']
        readback = next(r for r in resources if r['operation'] == 'readback/0' and r['kind'] == 'table')
        table = client.call('inspect_resource', resource_id=readback['id'])['value']
        row = next(row for row in table['rows'] if math.isclose(float(row[0]), 8))
        assert math.isclose(float(row[1]), 2, rel_tol=1e-9)
        report['handoff'] = {'job': job['id'], 'verification': verification, 'resources': resources,
                             'peakFrequency': float(row[0]), 'peakAmplitude': float(row[1]),
                             'scope': 'Octave -> Calc -> Octave via declared $artifact references; no conversion script.'}

        task = client.call('create_task', objective='Read the retained spectrum using a service resource binding',
                           allowed_providers=['octave'], budget={'maxAttempts': 1})
        document = {'version': 'schemaxis.octave/1', 'nodes': [{'id': 'data', 'filter': 'readCSV',
                    'options': {'file': None, 'xColumn': 'x', 'yColumn': 'y'}}], 'outputs': ['data']}
        plan = client.call('plan', task_id=task['id'], document=document, expected_revision=0,
                           bindings={'/nodes/0/options/file': readback['id']})
        job = client.call('execute', plan_id=plan['id'], expected_revision=plan['revision'])
        assert client.wait(job)['status'] == 'succeeded'
        report['resourceBinding'] = {'job': job['id'], 'source': readback['id'],
                                     'verification': client.call('verify', job_id=job['id'])['value']}

        task = client.call('create_task', objective='Check incompatible resource rejection', allowed_providers=['freecad'])
        incompatible = {'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'body', 'filter': 'readSTEP', 'options': {'file': None}}], 'output': 'body'}
        rejected = client.request('plan', task_id=task['id'], document=incompatible, expected_revision=0,
                                   bindings={'/nodes/0/options/file': readback['id']})
        assert rejected['fault']['code'] == 'TYPE_MISMATCH'
        report['negativeChecks'].append('Incompatible table-to-CAD binding rejected before execution.')
        report['verified'] = True
    finally:
        client.close()
        report['transport'] = {'requests': len(client.records), 'responseBytes': sum(r['responseBytes'] for r in client.records),
                               'largestResponseBytes': max((r['responseBytes'] for r in client.records), default=0),
                               'rejectedRequests': sum(not r['ok'] for r in client.records), 'records': client.records}
        (root/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'transport'}, indent=2))


if __name__ == '__main__':
    main()
