# Copyright (C) 2026 David L F Gaden
"""Bracket semantics, target units, refusal and CAD execution lifecycle bounds."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from schemaxis import feedback
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.freecad import adaptor
from schemaxis.adaptors.freecad.design_study import Policy
ROOT=Path(__file__).resolve().parents[2]


def document():return json.loads((ROOT/'examples/schemaxis/freecad-design-target.json').read_text())


def advance(policy,history,function):
    reason,candidate=feedback.transition(policy,history)
    if reason:return reason
    observation={'value':function(policy.coordinate(candidate)),'units':policy.settings['target']['units'],'sources':{}}
    decision=policy.judge(candidate,observation,history)
    history.append({'document':candidate,'observation':observation,'decision':decision})
    return None


class DesignStudyTests(unittest.TestCase):
    def test_nonlinear_increasing_target_converges_without_derivative_or_linear_assumption(self):
        doc=document();doc['designStudy']['parameter'].update(minimum=.5,maximum=2)
        doc['designStudy']['target'].update(value=2,tolerance=1e-5);doc['designStudy']['maxIterations']=20
        policy=Policy(doc);history=[]
        for _ in range(21):
            reason=advance(policy,history,lambda x:x*x)
            if reason:break
        self.assertEqual(reason,'accepted')
        self.assertAlmostEqual(policy.coordinate(history[-1]['document']),math.sqrt(2),delta=1e-5)
        self.assertEqual(policy.coordinate(history[0]['document']),.5)
        self.assertEqual(policy.coordinate(history[1]['document']),2)

    def test_decreasing_response_and_first_endpoint_acceptance(self):
        doc=document();doc['designStudy'].update(response='decreasing')
        doc['designStudy']['parameter'].update(minimum=2,maximum=8);doc['designStudy']['target'].update(value=20,tolerance=.001)
        policy=Policy(doc);history=[]
        for _ in range(4):
            reason=advance(policy,history,lambda x:100/x)
            if reason:break
        self.assertEqual(reason,'accepted');self.assertEqual(len(history),3)
        self.assertEqual(policy.coordinate(history[-1]['document']),5)
        history=[];advance(policy,history,lambda x:20)
        self.assertEqual(feedback.transition(policy,history)[0],'accepted')

    def test_unbracketed_response_violation_iteration_and_parameter_limits(self):
        for label,fn,target,limit,step,expected in [
            ('unbracketed',lambda x:x,200,12,1e-6,'target_not_bracketed'),
            ('direction',lambda x:100-x,95,12,1e-6,'response_assumption_violated'),
            ('iterations',lambda x:x,5.1,2,1e-6,'iteration_limit'),
            ('resolution',lambda x:x,5.1,12,20,'parameter_limit')]:
            doc=document();doc['designStudy']['parameter'].update(minimum=1,maximum=10)
            doc['designStudy']['target'].update(value=target,tolerance=.001)
            doc['designStudy'].update(maxIterations=limit,minimumStep=step)
            policy=Policy(doc);history=[]
            for _ in range(21):
                reason=advance(policy,history,fn)
                if reason:break
            with self.subTest(label=label):self.assertEqual(reason,expected)

    def test_invalid_control_units_bounds_and_target_are_rejected(self):
        paths=[(('parameter','node'),'missing'),(('parameter','option'),'axis'),(('parameter','minimum'),0),
               (('parameter','maximum'),3),(('target','units'),'mm'),(('target','measurement'),'centre'),
               (('target','tolerance'),0),(('maxIterations',),1)]
        for path,value in paths:
            doc=document();owner=doc['designStudy']
            for key in path[:-1]:owner=owner[key]
            owner[path[-1]]=value
            with self.subTest(path=path),self.assertRaises(SchemaxisError):adaptor.plan(doc)
        from schemaxis.adaptors.freecad.live import prepare
        with self.assertRaises(SchemaxisError):prepare(document())

    def test_changed_source_and_wrong_observation_units_are_not_search_samples(self):
        policy=Policy(document());history=[];advance(policy,history,lambda x:x)
        candidate=policy.propose(history)
        for changed in ({'value':6,'units':'mm','sources':{}},{'value':6,'units':'mm^3','sources':{'step':{'sha256':'changed'}}}):
            with self.assertRaises(SchemaxisError):policy.judge(candidate,changed,history)

    def test_native_stages_share_one_deadline_and_final_checks_cannot_publish_late(self):
        doc={'version':'schemaxis.freecad/1','nodes':[{'id':'box','filter':'box'}],'output':'box'}
        timeouts=[]
        class Report:
            def to_dict(self):return {}
        class Runner:
            def __call__(self,source):timeouts.append(self.timeout);return Report()
        with tempfile.TemporaryDirectory() as temp, patch.object(adaptor,'runtime_archive',return_value=b''), \
             patch.object(adaptor,'SubprocessRunner',return_value=Runner()), \
             patch.object(adaptor,'verify',return_value={'verified':True}), \
             patch.object(adaptor,'cancellation_requested',return_value=False), \
             patch('schemaxis.adaptors.freecad.adaptor.time.monotonic',side_effect=[0,1,4,11]):
            target=Path(temp)/'late'
            with self.assertRaises(SchemaxisError) as error:adaptor._native_run(doc,target,executable=sys.executable,timeout=10)
            self.assertEqual(error.exception.fault.code,'RUNNER_TIMED_OUT')
            self.assertEqual(timeouts,[9,6])
            self.assertFalse(json.loads((target/'result.json').read_text())['verified'])
