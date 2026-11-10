import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from schemaxis.adaptors.blender.adaptor import plan,_verify
from schemaxis.adaptors.blender.verification_input import lowered
from schemaxis.errors import SchemaxisError


class AuthoredReplayAuthority(unittest.TestCase):
    def packet(self,root):
        authored={'version':'schemaxis.blender/1','nodes':[{'id':'paint','filter':'material'},
            {'id':'box','filter':'cube','inputs':{'material':'paint'}}],
            'scenes':[{'id':'view','visible':['box'],'images':[{'id':'preview','size':[32,32],
                'cameras':[{'direction':[1,-2,1]}]}]}]}
        master,_,prepared=plan(authored)
        values={'authored.json':authored,'input.json':lowered(master),'plan.json':prepared,
                'sources.json':{},'result.json':{'status':'incomplete','verified':False}}
        for name,value in values.items():(root/name).write_text(json.dumps(value))
        return values

    def test_unchanged_input_reaches_the_separate_execution_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);self.packet(root)
            with self.assertRaises(SchemaxisError) as caught:_verify(root)
            self.assertEqual(caught.exception.fault.code,'INCOMPLETE_EXECUTION')

    def test_lowered_material_cannot_replace_authored_defaults_or_launch_native(self):
        for forge_declarations in (False,True):
            with self.subTest(forge_declarations=forge_declarations),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);values=self.packet(root)
                values['input.json']['nodes'][0].setdefault('options',{})['colour']=[0,1,0,1]
                if forge_declarations:
                    values['plan.json']['pipeline']['declarations']['material']['options']['colour']['value']['default']=[0,1,0,1]
                for name in ('input.json','plan.json'):(root/name).write_text(json.dumps(values[name]))
                before={p:p.read_bytes() for p in root.iterdir()}
                with patch('schemaxis.core.runners.Interpreter.probe',side_effect=AssertionError('untrusted lowering launched native')):
                    with self.assertRaises(SchemaxisError) as caught:_verify(root)
                self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
                self.assertEqual(caught.exception.fault.location,'input.json')
                self.assertIn('trusted authored intent',caught.exception.fault.message)
                self.assertEqual(before,{p:p.read_bytes() for p in root.iterdir()})


class FreshReaderBudget(unittest.TestCase):
    def test_native_replay_uses_the_parent_budget_without_extending_it(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from schemaxis.dispatch import execution_deadline
        from schemaxis.configuration import location_context
        from schemaxis.adaptors.blender.production_verify import fresh_reopen
        for budget in (900,20,None):
            observed={}
            class Runner:
                def __init__(self,runtime,directory,**kwargs):
                    observed['native']=kwargs['timeout'];self.directory=directory
                def __call__(self,source):
                    (self.directory/'observed.json').write_text('{}')
            def probe(_self,**kwargs):
                observed['probe']=kwargs['timeout'];return SimpleNamespace(version='5.2.3')
            with self.subTest(parent=budget),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);(root/'verification.json').write_text('{"states":[]}')
                scope=execution_deadline(budget) if budget is not None else nullcontext()
                with scope,location_context({'blender':'/fixed/blender'}),patch(
                        'schemaxis.core.runners.Interpreter.probe',probe),patch(
                        'schemaxis.adaptors.blender.production_verify.SubprocessRunner',Runner):
                    self.assertEqual(fresh_reopen(root,trusted_input={},trusted_digest='test-only'),{})
                maximum=300 if budget is None else budget
                self.assertGreater(observed['native'],maximum-2)
                self.assertLessEqual(observed['native'],maximum)
                self.assertGreater(observed['probe'],0)
                self.assertLessEqual(observed['probe'],min(120,maximum))

    def test_runtime_probe_is_clamped_to_the_enclosing_budget(self):
        from schemaxis.dispatch import execution_deadline
        from schemaxis.configuration import location_context
        from schemaxis.adaptors.blender.production_verify import fresh_reopen
        observed=[]
        def probe(_self,**kw):
            observed.append(kw['timeout']);raise RuntimeError('probe boundary only')
        with tempfile.TemporaryDirectory() as temporary,location_context({'blender':'/fixed/blender'}):
            with execution_deadline(.25),patch('schemaxis.core.runners.Interpreter.probe',probe):
                with self.assertRaisesRegex(RuntimeError,'probe boundary only'):fresh_reopen(temporary)
        self.assertEqual(len(observed),1)
        self.assertGreater(observed[0],0);self.assertLessEqual(observed[0],.25)

    def test_probe_failure_cannot_replace_an_expired_parent_fault(self):
        from schemaxis.errors import Fault
        from schemaxis.configuration import location_context
        from schemaxis.adaptors.blender.production_verify import fresh_reopen
        expired=SchemaxisError(Fault('RUNNER_TIMED_OUT','parent exhausted','$','pipeline'))
        with tempfile.TemporaryDirectory() as temporary,location_context({'blender':'/fixed/blender'}):
            with patch('schemaxis.adaptors.blender.production_verify.remaining_timeout',side_effect=[10,10,expired]):
                with patch('schemaxis.core.runners.Interpreter.probe',side_effect=RuntimeError('late probe')):
                    with self.assertRaises(SchemaxisError) as caught:fresh_reopen(temporary)
        self.assertEqual(caught.exception.fault.code,'RUNNER_TIMED_OUT')


if __name__=='__main__':unittest.main()
