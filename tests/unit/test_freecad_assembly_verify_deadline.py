"""Public standalone verification shares source and copy-worker budgets.

The graph verifier and native process are stand-ins here. The real process
wrapper and public verification entry point enforce the clock/cancel boundary;
actual native source admission is qualified separately.
"""
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from schemaxis.adaptors.freecad import assembly_sources
from schemaxis.adaptors.freecad.process import SubprocessRunner
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import allocation,execution_deadline


class VerificationDeadline(unittest.TestCase):
    def invoke(self,timeout,*,parent=None,cancel_after=None):
        now=[100.0];budgets=[];cancel=threading.Event()
        class Native:
            def __init__(self,interpreter,workspace,arguments,budget,environment):
                budgets.append(budget)
            def __call__(self,source):
                now[0]+=4
                if len(budgets)==cancel_after:cancel.set()
                return 'native-result'
        def stages(*args,**kwargs):
            for label,limit in (('source-one',240),('source-two',240),('copy-history',120)):
                SubprocessRunner(Interpreter('freecad','/qualified/freecadcmd'),Path('/unused'),timeout=limit)(label)
            return {'verified':True}
        from contextlib import nullcontext
        with patch('schemaxis.dispatch._clock',side_effect=lambda:now[0]),\
                patch('schemaxis.adaptors.freecad.process.Runner',Native),\
                patch.object(assembly_sources,'_verify',side_effect=stages),allocation({},cancel):
            try:
                with execution_deadline(parent) if parent is not None else nullcontext():
                    result=assembly_sources.verify('/unused',verification_timeout=timeout)
            except SchemaxisError as error:return budgets,error.fault.code
        return budgets,result

    def test_two_source_workers_and_copy_share_one_budget(self):
        budgets,result=self.invoke(10)
        self.assertEqual(budgets,[10,6,2]);self.assertEqual(result,'RUNNER_TIMED_OUT')
        budgets,result=self.invoke(13)
        self.assertEqual(budgets,[13,9,5]);self.assertEqual(result,{'verified':True})

    def test_tighter_parent_is_not_extended(self):
        budgets,result=self.invoke(13,parent=9)
        self.assertEqual(budgets,[9,5,1]);self.assertEqual(result,'RUNNER_TIMED_OUT')

    def test_cancellation_after_a_source_never_starts_the_next_worker(self):
        budgets,result=self.invoke(120,cancel_after=1)
        self.assertEqual(budgets,[120]);self.assertEqual(result,'RUNNER_CANCELLED')

    def test_cancellation_after_copy_cannot_return_success(self):
        budgets,result=self.invoke(120,cancel_after=3)
        self.assertEqual(budgets,[120,116,112]);self.assertEqual(result,'RUNNER_CANCELLED')

    def test_invalid_budgets_never_enter_graph_verification(self):
        with patch.object(assembly_sources,'_verify') as graph:
            for value in (True,0,-1,None,float('inf'),float('nan')):
                with self.subTest(value=value),self.assertRaises(SchemaxisError) as error:
                    assembly_sources.verify('/unused',verification_timeout=value)
                self.assertEqual(error.exception.fault.code,'INVALID_TIMEOUT')
        graph.assert_not_called()


if __name__=='__main__':unittest.main()
