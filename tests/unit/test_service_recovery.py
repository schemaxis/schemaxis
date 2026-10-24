"""Persisted relationships must be checked even when Python removes assertions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

RECOVER = r'''
import copy, json, sys
from pathlib import Path
from schemaxis.execution_service import ExecutionService
from schemaxis.resource_inspection import InspectionStore
from schemaxis.core.faults import SchemaxisError
from schemaxis.storage import digest, encoded
from schemaxis.capabilities import digest as service_digest

root = Path(sys.argv[1])
service_root = root / 'service'
with ExecutionService(service_root) as service:
    task = service.create_task('Recovery test', ['freecad'])
    plan = service.plan(task['id'], {'version': 'schemaxis.freecad/1',
        'nodes': [{'id': 'body', 'filter': 'box'}], 'output': 'body'}, task['revision'])
service_path = service_root / 'agent.json'
original = service_path.read_bytes()
seed = json.loads(original)['state']
results = {'optimize': sys.flags.optimize, 'service': {}, 'inspection': {}}

def service_change(case, state):
    task_record = state['tasks'][task['id']]
    plan_record = state['plans'][plan['id']]
    if case == 'tasks-array': state['tasks'] = []
    elif case == 'task-array': state['tasks'][task['id']] = []
    elif case == 'task-identity': task_record['id'] = 'other'
    elif case == 'revision-boolean': task_record['revision'] = True
    elif case == 'attempts-negative': task_record['attempts'] = -1
    elif case == 'budget-array': task_record['budget'] = list(task_record['budget'])
    elif case == 'budget-incomplete': task_record['budget'] = {}
    elif case == 'authorisation-array': task_record['authorisation'] = []
    elif case == 'providers-text': task_record['authorisation']['allowedProviders'] = 'freecad'
    elif case == 'plan-array': state['plans'][plan['id']] = []
    elif case == 'plan-task': plan_record['task'] = 'missing'
    elif case == 'plan-revision': plan_record['revision'] = task_record['revision'] + 1
    elif case == 'plan-reference': plan_record['document']['sha256'] = []
    elif case == 'job-array': state['jobs']['job'] = []
    elif case == 'job-plan':
        state['jobs']['job'] = {'id': 'job', 'plan': 'missing', 'task': task['id'], 'status': 'failed'}
    elif case == 'job-status':
        state['jobs']['job'] = {'id': 'job', 'plan': plan['id'], 'task': task['id'], 'status': 'invented'}
    elif case == 'resource-array': state['resources']['resource'] = []
    elif case == 'resource-job': state['resources']['resource'] = {'id': 'resource', 'job': 'missing'}
    elif case != 'valid': raise ValueError(case)

for case in ('valid', 'tasks-array', 'task-array', 'task-identity', 'revision-boolean',
             'attempts-negative', 'budget-array', 'budget-incomplete', 'authorisation-array',
             'providers-text', 'plan-array', 'plan-task', 'plan-revision', 'plan-reference',
             'job-array', 'job-plan', 'job-status', 'resource-array', 'resource-job'):
    changed = copy.deepcopy(seed)
    service_change(case, changed)
    service_path.write_bytes(encoded({'version': 1, 'state': changed, 'digest': service_digest(changed)}))
    try:
        with ExecutionService(service_root) as service: result = {'accepted': True}
    except SchemaxisError as error: result = {'code': error.fault.code}
    service_path.write_bytes(original)
    # A failed recovery must release its ownership lock, permitting repair/reopen.
    with ExecutionService(service_root) as service:
        result['retry'] = service.task(task['id'])['revision'] == seed['tasks'][task['id']]['revision']
    results['service'][case] = result

inspection_root = root / 'inspection-owner'
store = InspectionStore(inspection_root)
first = store.capture_bytes(b'old text', 'text', 'Sample', {'kind': 'test'})
latest = store.capture_bytes(b'new text', 'text', 'Sample', {'kind': 'test'}, first['id'], first['revision'])
store.workspace('text-inspection', latest['id'])
inspection_path = inspection_root / 'inspection' / 'state.json'
original = inspection_path.read_bytes()
seed = json.loads(original)['state']

for case in ('valid', 'state-array', 'resources-array', 'record-array', 'identity',
             'snapshots-array', 'revision-missing', 'presentation-array', 'preset',
             'selected-missing', 'selected-array'):
    changed = copy.deepcopy(seed)
    record = changed['resources'][first['id']]
    if case == 'state-array': changed = []
    elif case == 'resources-array': changed['resources'] = []
    elif case == 'record-array': changed['resources'][first['id']] = []
    elif case == 'identity': record['id'] = 'other'
    elif case == 'snapshots-array': record['snapshots'] = list(record['snapshots'])
    elif case == 'revision-missing': record['revision'] = 'missing'
    elif case == 'presentation-array': changed['presentation'] = []
    elif case == 'preset': changed['presentation']['preset'] = 'untrusted'
    elif case == 'selected-missing': changed['presentation']['resource'] = 'missing'
    elif case == 'selected-array': changed['presentation']['resource'] = []
    inspection_path.write_bytes(encoded({'version': 1, 'state': changed, 'digest': digest(changed)}))
    try:
        InspectionStore(inspection_root)
        result = {'accepted': True}
    except SchemaxisError as error: result = {'code': error.fault.code}
    inspection_path.write_bytes(original)
    restored = InspectionStore(inspection_root)
    result['retry'] = (restored.inspect(first['id'], first['revision'], 'text')['text'] == 'old text'
        and restored.inspect(latest['id'], latest['revision'], 'text')['text'] == 'new text')
    results['inspection'][case] = result
print(json.dumps(results))
'''


class ServiceRecoveryTests(unittest.TestCase):
    def check_recovery(self, *flags):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, *flags, '-c', RECOVER, directory],
                cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        outcomes = json.loads(result.stdout)
        self.assertEqual(outcomes.pop('optimize'), 1 if flags else 0)
        for owner, cases in outcomes.items():
            for case, outcome in cases.items():
                with self.subTest(owner=owner, case=case, flags=flags):
                    if case == 'valid': self.assertTrue(outcome.get('accepted'), outcome)
                    else: self.assertEqual(outcome.get('code'), 'RECOVERY_FAILED', outcome)
                    self.assertTrue(outcome['retry'])

    def test_recovery_relationships(self):
        self.check_recovery()

    def test_optimised_recovery_relationships(self):
        self.check_recovery('-O')


if __name__ == '__main__':
    unittest.main()
