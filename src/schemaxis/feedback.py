# Copyright (C) 2026 David L F Gaden
"""Bounded feedback execution over verified native black boxes.

An app-owned policy proposes documents from prior observations and judges them.
This module owns ordering, limits, cancellation, evidence and decision replay.
It contains no application identities, scientific thresholds or native imports.
"""
import copy
import json
import math
from pathlib import Path
import time

from .artifacts import atomic_json, file_digest
from .core.faults import Fault, SchemaxisError
from .dispatch import cancellation_requested
from .errors import fail
from .storage import digest, prepare_run_directory

PROTOCOL = 'schemaxis.feedback/1'


def transition(policy, history):
    if type(policy.limit) is not int or not 1 <= policy.limit <= 20:
        fail('INVALID_STUDY', 'feedback studies require 1 to 20 iterations')
    if history:
        decision = history[-1]['decision']
        if decision['accepted']:
            return 'accepted', None
        if decision.get('stop'):
            return decision['stop'], None
    if len(history) >= policy.limit:
        return 'iteration_limit', None
    candidate = policy.propose(copy.deepcopy(history))
    if candidate is None:
        return 'parameter_limit', None
    if not isinstance(candidate, dict):
        fail('INVALID_STUDY', 'study policy must propose a document')
    return None, candidate


def record(policy, candidate, target, history, native_verify, observe):
    if json.loads((target/'authored.json').read_text()) != candidate:
        fail('VERIFICATION_FAILED', 'feedback candidate differs from proposed input', str(target))
    native_verify(target)
    receipt = json.loads((target/'verification.json').read_text())
    observation = observe(target)
    decision = policy.judge(copy.deepcopy(candidate), copy.deepcopy(observation), copy.deepcopy(history))
    if (not isinstance(decision, dict) or type(decision.get('accepted')) is not bool
            or not isinstance(decision.get('checks'), list)
            or (decision.get('stop') is not None and not isinstance(decision['stop'], str))):
        fail('INVALID_STUDY', 'policy must return accepted, checks and an optional stop reason')
    return {'index': len(history), 'directory': target.name, 'document': candidate,
            'inputDigest': digest(candidate), 'observation': observation,
            'decision': decision, 'artifacts': receipt['artifacts']}


def report(policy, history, reason):
    accepted = reason == 'accepted'
    return {'version': 'schemaxis.feedback.report/1', 'policy': policy.describe(),
            'accepted': accepted, 'reason': reason,
            'selected': len(history)-1 if accepted else None, 'attempts': history,
            'limits': {'maxIterations': policy.limit},
            'selection': 'first tested candidate satisfying all declared requirements; no global optimum claimed'}


def publications(directory):
    return [{'file': str(directory/name), 'kind': 'text', 'sha256': file_digest(directory/name)}
            for name in ('study-summary.json', 'study.html')]


def run(document, directory, policy, native_run, native_verify, observe, *, timeout):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        fail('INVALID_TIMEOUT', 'feedback timeout must be finite and positive')
    directory = prepare_run_directory(directory, document)
    deadline = time.monotonic()+timeout
    history = []
    status = {'protocol': PROTOCOL, 'status': 'incomplete', 'verified': False, 'attempts': history}
    atomic_json(directory/'result.json', status)
    try:
        while True:
            if cancellation_requested(): fail('RUNNER_CANCELLED', 'feedback study cancelled')
            if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'feedback study exhausted its total timeout')
            reason, candidate = transition(policy, history)
            if reason: break
            target = directory/('attempt-'+str(len(history)).zfill(5))
            native_run(candidate, target, timeout=deadline-time.monotonic())
            history.append(record(policy, candidate, target, history, native_verify, observe))
            atomic_json(directory/'result.json', status)
        summary = report(policy, history, reason)
        atomic_json(directory/'study-summary.json', summary)
        from .feedback_report import render
        (directory/'study.html').write_text(render(summary, directory), encoding='utf-8')
        artifacts = (history[-1]['artifacts'] if summary['accepted'] else [])+publications(directory)
        receipt = {'protocol': PROTOCOL, 'authoredDigest': digest(document),
                   'reportDigest': digest(summary), 'artifacts': artifacts}
        atomic_json(directory/'verification.json', receipt)
        status.update(status='succeeded' if summary['accepted'] else 'requirements-unmet',
                      verified=True, accepted=summary['accepted'], reason=reason, selected=summary['selected'])
        atomic_json(directory/'result.json', status)
        result = verify(directory, document, policy, native_verify, observe)
        if cancellation_requested(): fail('RUNNER_CANCELLED', 'feedback study cancelled during verification')
        if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'feedback verification exhausted total timeout')
        return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            error = SchemaxisError(Fault('STUDY_EXECUTION_FAILED', str(error) or type(error).__name__,
                                         str(directory), 'execution'))
        status.update(status='failed', verified=False,
                      fault=error.fault.to_dict())
        atomic_json(directory/'result.json', status)
        raise error


def verify(directory, document, policy, native_verify, observe):
    """Reconstruct proposals and decisions from independently verified attempts."""
    directory = Path(directory).absolute()
    try:
        for name in ('authored.json', 'result.json', 'verification.json', 'study-summary.json', 'study.html'):
            if not (directory/name).is_file() or (directory/name).is_symlink():
                fail('VERIFICATION_FAILED', 'missing regular feedback evidence', name)
        saved = json.loads((directory/'result.json').read_text())
        receipt = json.loads((directory/'verification.json').read_text())
        if json.loads((directory/'authored.json').read_text()) != document:
            fail('VERIFICATION_FAILED', 'feedback authored input differs')
        retained = saved.get('attempts')
        if (saved.get('protocol') != PROTOCOL or saved.get('verified') is not True
                or not isinstance(retained, list) or len(retained) > policy.limit):
            fail('VERIFICATION_FAILED', 'feedback execution is incomplete or over its bound')
        history = []
        for item in retained:
            reason, candidate = transition(policy, history)
            if reason: fail('VERIFICATION_FAILED', 'feedback evidence continued after stopping')
            target = directory/('attempt-'+str(len(history)).zfill(5))
            if target.is_symlink(): fail('VERIFICATION_FAILED', 'feedback attempt must not be a symlink')
            actual = record(policy, candidate, target, history, native_verify, observe)
            if actual != item: fail('VERIFICATION_FAILED', 'feedback observation, proposal or decision differs')
            history.append(actual)
        reason, _ = transition(policy, history)
        if reason is None: fail('VERIFICATION_FAILED', 'feedback execution stopped before its decision')
        summary = report(policy, history, reason)
        if json.loads((directory/'study-summary.json').read_text()) != summary:
            fail('VERIFICATION_FAILED', 'feedback summary differs from decision replay')
        from .feedback_report import render
        if (directory/'study.html').read_text(encoding='utf-8') != render(summary, directory):
            fail('VERIFICATION_FAILED', 'human study report differs from decision replay')
        expected_status = 'succeeded' if summary['accepted'] else 'requirements-unmet'
        expected = {'protocol': PROTOCOL, 'status': expected_status, 'verified': True,
                    'attempts': history, 'accepted': summary['accepted'], 'reason': reason,
                    'selected': summary['selected']}
        if saved != expected: fail('VERIFICATION_FAILED', 'feedback outcome differs from decision replay')
        artifacts = (history[-1]['artifacts'] if summary['accepted'] else [])+publications(directory)
        if receipt != {'protocol': PROTOCOL, 'authoredDigest': digest(document),
                       'reportDigest': digest(summary), 'artifacts': artifacts}:
            fail('VERIFICATION_FAILED', 'feedback publication membership or digest differs')
        return {'verified': True, 'accepted': summary['accepted'], 'reason': reason,
                'attempts': len(history), 'selected': summary['selected'], 'artifacts': len(artifacts)}
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        fail('VERIFICATION_FAILED', 'invalid feedback evidence: '+str(error))
