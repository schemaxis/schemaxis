import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

# Runs in a child interpreter so recovery validation is exercised with and
# without python -O. Each case tampers with a saved session, recomputes its
# checksum, recovers, then restores the original bytes and recovers again in
# the same process: flock conflicts there unless the failed owner released it.
RECOVERY = r'''
import json, sys, uuid
from pathlib import Path
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.core.faults import SchemaxisError
from schemaxis.storage import digest, encoded

root = Path(sys.argv[1])

def record(state): return state['documents'][state['activeDocument']]

def tamper(case, state):
    if case == 'empty-documents': state.update(documents={}, activeDocument=None)
    elif case == 'missing-active': del state['activeDocument']
    elif case == 'unknown-active': state['activeDocument'] = str(uuid.uuid4())
    elif case == 'unhashable-active': state['activeDocument'] = []
    elif case == 'state-array': return []
    elif case == 'documents-array': state['documents'] = list(state['documents'].values())
    elif case == 'references-array': state['references'] = []
    elif case == 'file-baselines-array': state['fileBaselines'] = []
    elif case == 'next-revision-text': state['nextRevision'] = str(state['nextRevision'])
    elif case == 'revision-zero': record(state)['revision'] = 0
    elif case == 'revision-ahead': record(state)['revision'] = state['nextRevision'] + 1
    elif case == 'revision-boolean': record(state)['revision'] = True
    elif case == 'noncanonical-identity':
        identity = state['activeDocument']
        state['documents'] = {identity.upper(): state['documents'][identity]}
        state['activeDocument'] = identity.upper()
    elif case == 'record-array': state['documents'][state['activeDocument']] = []
    elif case == 'undo-object': record(state)['undo'] = {}
    elif case == 'undo-without-document': del record(state)['undo'][0]['document']
    elif case == 'attempt-text': record(state)['attempts'] = ['running']
    elif case == 'source-document-differs': record(state)['document'] = {'tampered': True}
    elif case == 'source-diagnostics-differ': record(state)['diagnostics'] = [{'code': 'INVALID_JSON'}]
    elif case == 'undo-source-differs': record(state)['undo'][0].update(source='{', diagnostics=[])
    elif case == 'document-array-without-source':
        del record(state)['source']
        record(state)['document'] = []
    elif case == 'provider-array': record(state)['provider'] = []
    elif case == 'provider-unknown': record(state)['provider'] = 'unregistered'
    elif case == 'invalid-draft-provider-array':
        record(state).update(source='{', document=None, diagnostics=[{'code': 'INVALID_JSON'}], provider=[])
    elif case == 'source-array': record(state)['source'] = []
    elif case == 'invalid-draft-diagnostics-text':
        record(state).update(source='{', document=None, diagnostics='a non-list')
    elif not case.startswith('valid'): raise SystemExit('unknown case ' + case)
    return state

def recover(workspace):
    with AdaptorConsoleSession(workspace, provider='workflow') as session:
        return {'activeDocument': session.active_document,
                'attempts': session.status()['documents'][session.active_document]['attempts'],
                'invalidDraft': bool(record(session._state).get('diagnostics'))}

DRAFTS = {'valid-invalid-json-draft': '{',
          'valid-invalid-document-draft': json.dumps({'version': 'schemaxis.workflow/1', 'operations': 3})}
results = {'optimize': sys.flags.optimize}
for case in sys.argv[2:]:
    workspace = root / case
    with AdaptorConsoleSession(workspace, provider='workflow') as session:
        source = json.dumps({'version': 'schemaxis.workflow/1', 'operations': []}, indent=2)
        session.edit_source(source, session.active_document, session.draft()['revision'])
        # Legitimate invalid drafts are retained: unparsed, or parsed but schema-invalid.
        if case in DRAFTS: session.edit_source(DRAFTS[case], session.active_document, session.draft()['revision'])
        state = json.loads(json.dumps(session._state))
        state['documents'][session.active_document]['attempts'].append(
            {'id': 'interrupted', 'revision': state['nextRevision'], 'status': 'running'})
        session._commit(state)
        expected = session.active_document
    path = workspace / 'session.json'
    original = path.read_bytes()
    state = tamper(case, json.loads(original)['state'])
    path.write_bytes(encoded({'version': 1, 'state': state, 'sha256': digest(state)}))
    try: outcome = {'recovered': recover(workspace)}
    except SchemaxisError as error: outcome = {'code': error.fault.code}
    path.write_bytes(original)
    retry = recover(workspace)
    outcome['retry'] = retry['activeDocument'] == expected and retry['attempts'][-1]['status'] == 'interrupted'
    results[case] = outcome
print(json.dumps(results))
'''

INVALID = ['empty-documents', 'missing-active', 'unknown-active', 'unhashable-active',
    'state-array', 'documents-array', 'references-array', 'file-baselines-array',
    'next-revision-text', 'revision-zero', 'revision-ahead', 'revision-boolean',
    'noncanonical-identity', 'record-array', 'undo-object', 'undo-without-document',
    'attempt-text', 'source-document-differs', 'source-diagnostics-differ', 'undo-source-differs',
    'document-array-without-source', 'provider-array', 'provider-unknown', 'invalid-draft-provider-array',
    'source-array', 'invalid-draft-diagnostics-text']
VALID = ['valid', 'valid-invalid-json-draft', 'valid-invalid-document-draft']


class SessionRecoveryValidationTests(unittest.TestCase):
    def recover(self, *flags):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, *flags, '-c', RECOVERY, directory, *VALID, *INVALID],
                                    capture_output=True, text=True, timeout=120,
                                    env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def check(self, results, optimize):
        self.assertEqual(results.pop('optimize'), optimize)
        for case in VALID:
            with self.subTest(case=case):
                valid = results.pop(case)
                self.assertNotIn('code', valid)
                # Recovery marks the owner's unfinished attempt as interrupted.
                self.assertEqual(valid['recovered']['attempts'][-1]['status'], 'interrupted')
                self.assertTrue(valid['retry'])
                self.assertEqual(valid['recovered']['invalidDraft'], case != 'valid')
        self.assertEqual(sorted(results), sorted(INVALID))
        for case, outcome in results.items():
            with self.subTest(case=case):
                self.assertEqual(outcome.get('code'), 'RECOVERY_FAILED', outcome)
                self.assertTrue(outcome['retry'], 'lock was not released for a retry')

    def test_malformed_sessions_fail_recovery_and_release_lock(self):
        self.check(self.recover(), 0)

    def test_malformed_sessions_fail_recovery_under_optimized_python(self):
        self.check(self.recover('-O'), 1)


if __name__ == '__main__':
    unittest.main()
