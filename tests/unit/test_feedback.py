# Copyright (C) 2026 David L F Gaden
"""Decision replay, failure bounds and publication selection without native apps."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis import feedback
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail


class Target:
    limit = 4
    def describe(self): return {'target': 3}
    def propose(self, history):
        return {'input': history[-1]['observation']['measured']+1 if history else 1}
    def judge(self, candidate, observation, history):
        return {'accepted': observation['measured'] >= 3, 'checks': [{'observed': observation['measured'], 'minimum': 3}]}


def native(document, directory, **options):
    directory.mkdir()
    atomic_json(directory/'authored.json', document)
    atomic_json(directory/'measurement.json', {'measured': document['input']})
    atomic_json(directory/'verification.json', {'artifacts': [
        {'file': str(directory/'measurement.json'), 'kind': 'text', 'sha256': file_digest(directory/'measurement.json')}]})


def observe(directory): return json.loads((directory/'measurement.json').read_text())


def verify_native(directory):
    doc = json.loads((directory/'authored.json').read_text())
    receipt = json.loads((directory/'verification.json').read_text())
    if (observe(directory)['measured'] != doc['input']
            or file_digest(directory/'measurement.json') != receipt['artifacts'][0]['sha256']):
        fail('VERIFICATION_FAILED', 'native double changed')


class FeedbackTests(unittest.TestCase):
    def test_observation_drives_next_proposal_and_first_acceptance_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'study'
            result = feedback.run({'request': 'fixture'}, target, Target(), native, verify_native, observe, timeout=5)
            self.assertEqual((result['accepted'], result['attempts'], result['selected']), (True, 3, 2))
            self.assertFalse((target/'attempt-00003').exists())
            receipt = json.loads((target/'verification.json').read_text())
            self.assertEqual(len(receipt['artifacts']), 3)
            self.assertIn('attempt-00002', receipt['artifacts'][0]['file'])
            # Changing rejected evidence is also detected; it justified continuing.
            atomic_json(target/'attempt-00000'/'measurement.json', {'measured': 99})
            with self.assertRaises(SchemaxisError): feedback.verify(target, {'request': 'fixture'}, Target(), verify_native, observe)

    def test_exhaustion_is_verified_but_never_publishes_a_selected_candidate(self):
        policy = Target(); policy.limit = 2
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'study'
            result = feedback.run({}, target, policy, native, verify_native, observe, timeout=5)
            self.assertFalse(result['accepted'])
            self.assertEqual(result['reason'], 'iteration_limit')
            receipt = json.loads((target/'verification.json').read_text())
            self.assertEqual(len(receipt['artifacts']), 2)
            self.assertTrue(receipt['artifacts'][0]['file'].endswith('study-summary.json'))

    def test_forged_decisions_truncation_and_extra_attempts_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'study'
            feedback.run({}, target, Target(), native, verify_native, observe, timeout=5)
            original = json.loads((target/'result.json').read_text())
            for change in ('decision', 'truncate', 'extra', 'selected'):
                saved = copy.deepcopy(original)
                if change == 'decision': saved['attempts'][0]['decision']['accepted'] = True
                elif change == 'truncate': saved['attempts'].pop()
                elif change == 'extra': saved['attempts'].append(saved['attempts'][-1])
                else: saved['selected'] = 0
                atomic_json(target/'result.json', saved)
                with self.subTest(change=change), self.assertRaises(SchemaxisError):
                    feedback.verify(target, {}, Target(), verify_native, observe)

    def test_native_failure_and_cancellation_do_not_become_rejected_candidates(self):
        def broken(*args, **kwargs): fail('NATIVE_EXECUTION_FAILED', 'fixture')
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'failed'
            with self.assertRaises(SchemaxisError): feedback.run({}, target, Target(), broken, verify_native, observe, timeout=5)
            self.assertEqual(json.loads((target/'result.json').read_text())['status'], 'failed')
            with patch('schemaxis.feedback.cancellation_requested', return_value=True), self.assertRaises(SchemaxisError) as caught:
                feedback.run({}, Path(temp)/'cancelled', Target(), native, verify_native, observe, timeout=5)
            self.assertEqual(caught.exception.fault.code, 'RUNNER_CANCELLED')

    def test_total_timeout_includes_observation_and_verification(self):
        with tempfile.TemporaryDirectory() as temp, patch('schemaxis.feedback.time.monotonic', side_effect=[0, 0, 0, 6]):
            with self.assertRaises(SchemaxisError) as caught:
                feedback.run({}, Path(temp)/'study', Target(), native, verify_native, observe, timeout=5)
            self.assertEqual(caught.exception.fault.code, 'RUNNER_TIMED_OUT')

    def test_callback_fault_is_structured_and_preserves_earlier_evidence(self):
        def broken_observation(directory):
            if directory.name == 'attempt-00001': raise ValueError('measurement unavailable')
            return observe(directory)
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'study'
            with self.assertRaises(SchemaxisError) as caught:
                feedback.run({}, target, Target(), native, verify_native, broken_observation, timeout=5)
            self.assertEqual(caught.exception.fault.code, 'STUDY_EXECUTION_FAILED')
            saved = json.loads((target/'result.json').read_text())
            self.assertEqual(saved['fault']['code'], 'STUDY_EXECUTION_FAILED')
            self.assertEqual(len(saved['attempts']), 1)
            self.assertEqual(saved['status'], 'failed')
            self.assertFalse((target/'verification.json').exists())
            verify_native(target/'attempt-00000')
