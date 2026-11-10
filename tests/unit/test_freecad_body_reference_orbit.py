"""Whole trusted states, conservative stopping and cumulative Body budgets."""
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile,ZIP_STORED,ZIP_DEFLATED

from schemaxis.adaptors.freecad import body_reference as orbit,part_reconstruction
from schemaxis.adaptors.freecad.adaptor import _native_plan
from schemaxis.core.faults import SchemaxisError,Fault
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import execution_deadline,remaining_timeout


def archive(path,state='a',date='2026-11-06T01:00:00-05:00',**changes):
    data=('<Document><Properties Count="3"><Property name="CreationDate" type="App::PropertyString">'
          '<String value="'+date+'"/></Property><Property name="LastModifiedDate" type="App::PropertyString">'
          '<String value="'+date+'"/></Property><Property name="Notes" type="App::PropertyString">'
          '<String value="2026-11-06T01:00:00-05:00"/></Property></Properties>'
          '<Objects><Object name="N0" id="1" status="0"/></Objects></Document>').encode()
    members={'Document.xml':data,'StringHasher.Table.txt':state.encode(),'GuiDocument.xml':b'fixed view','Shape.brp':b'fixed geometry'}
    members.update(changes)
    with ZipFile(path,'w',compression=ZIP_DEFLATED) as z:
        for name,value in members.items():z.writestr(name,value)


def state(path):
    with ZipFile(path) as z:return z.read('StringHasher.Table.txt').decode()


class ExactBodyStateKey(unittest.TestCase):
    def test_only_root_date_values_and_zip_storage_are_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            a,b=Path(temporary)/'a.FCStd',Path(temporary)/'b.FCStd';archive(a);archive(b,date='2026-11-07T02:03:04-05:00')
            expected=orbit.state_key(a);self.assertEqual(expected,orbit.state_key(b))
            with ZipFile(b) as z:members={n:z.read(n) for n in z.namelist()}
            with ZipFile(b,'w',compression=ZIP_STORED) as z:
                for name,value in members.items():z.writestr(name,value)
            self.assertEqual(expected,orbit.state_key(b))
            for change in ('owner','status','whitespace','notes','unused-table','geometry','gui'):
                changed=dict(members)
                if change=='owner':changed['Document.xml']=members['Document.xml'].replace(b'id="1"',b'id="2"')
                elif change=='status':changed['Document.xml']=members['Document.xml'].replace(b'status="0"',b'status="1"')
                elif change=='whitespace':changed['Document.xml']=members['Document.xml'].replace(b'<Objects>',b' <Objects>')
                elif change=='notes':changed['Document.xml']=members['Document.xml'].replace(b'value="2026-11-06T01:00:00-05:00"',b'value="changed-note"')
                elif change=='unused-table':changed['StringHasher.Table.txt']+=b'extra unused record'
                elif change=='geometry':changed['Shape.brp']+=b'changed'
                else:changed['GuiDocument.xml']+=b'changed'
                with ZipFile(b,'w') as z:
                    for name,value in changed.items():z.writestr(name,value)
                with self.subTest(change=change):self.assertNotEqual(expected,orbit.state_key(b))

    def test_malformed_date_is_not_a_stopping_equivalence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'reference.FCStd';archive(path,date='not-a-native-date')
            with self.assertRaises(ValueError):orbit.state_key(path)


class BoundedPrivateReference(unittest.TestCase):
    def test_paths_refuse_symlinks_outside_types_and_filesystems(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);root=base/'root';root.mkdir();native=root/'model.FCStd';native.write_bytes(b'original')
            outside=base/'outside';outside.mkdir();target=outside/'model.FCStd';target.write_bytes(b'outside')
            self.assertEqual(orbit.private_path(root,native),native)
            for link_target in (outside,root):
                link=root/'slot';link.symlink_to(link_target,target_is_directory=True)
                with self.assertRaisesRegex(ValueError,'symlink'):orbit.private_path(root,link/'model.FCStd')
                link.unlink()
            with self.assertRaises(ValueError):orbit.private_path(root,target)
            with self.assertRaises(ValueError):orbit.private_path(root,root)
            with self.assertRaises(ValueError):orbit.private_path(root,native,directory=True)
            real_stat=Path.stat
            def different_device(path,*args,**kwargs):
                result=real_stat(path,*args,**kwargs)
                if path==native:
                    values=list(result);values[2]+=1;return os.stat_result(values)
                return result
            with patch.object(Path,'stat',different_device):
                with self.assertRaisesRegex(ValueError,'filesystem'):orbit.private_path(root,native)
            self.assertEqual(native.read_bytes(),b'original');self.assertEqual(target.read_bytes(),b'outside')

    def test_streaming_key_and_all_resource_bounds(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'reference.FCStd';archive(path)
            # Whole ZIP read is forbidden: only bounded streaming member reads.
            with patch.object(ZipFile,'read',side_effect=AssertionError('nonstreaming read')):
                self.assertEqual(len(orbit.state_key(path)),32)
            for module,name,limit in (
                    ('assembly_sources','SOURCE_BYTES',path.stat().st_size-1),
                    ('assembly_sources','ZIP_MEMBERS',3),
                    ('assembly_sources','ZIP_EXPANDED',10),
                    ('source_envelope','MEMBER_BYTES',10)):
                with self.subTest(bound=name),patch('schemaxis.adaptors.freecad.'+module+'.'+name,limit):
                    with self.assertRaises(SchemaxisError) as error:orbit.state_key(path)
                    self.assertEqual(error.exception.fault.code,'RESOURCE_LIMIT')



class TrustedBodyOrbit(unittest.TestCase):
    def run_orbit(self,states,*,accepted=None,clock=None,cancel=False,fault=None,sabotage=None,gate=None):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);generated=root/'generated';generated.mkdir();archive(generated/'model.FCStd')
            submitted=root/'submitted.FCStd';submitted.write_bytes(b'never passed to native');launches=[];binds=[];cost=[0];cancelled=[False]
            class Native:
                def __init__(self,interpreter,workspace,timeout):
                    self.workspace=workspace;launches.append(timeout)
                def __call__(self,source):
                    self_source=source
                    if str(submitted) in source:raise AssertionError('submitted native path launched')
                    if fault:raise SchemaxisError(Fault(fault,'native control','$','native'))
                    target=self.workspace/'resaved';target.mkdir();archive(target/'model.FCStd',states[cost[0]])
                    (target/'reference-lifecycle.json').write_text('{}')
                    if sabotage:sabotage(root,target)
                    cost[0]+=1
                    if clock is not None:clock[0]+=4
                    if cancel:cancelled[0]=True
            def bind(path,xml,candidate,source_names):
                self.assertEqual(path,submitted);actual=state(candidate/'model.FCStd');binds.append(actual)
                # Rolling storage has only current+next in addition to original.
                self.assertEqual(len(list(generated.rglob('*.FCStd'))),3)
                if actual!=accepted:raise ValueError('whole state differs')
            with ExitStack() as stack:
                stack.enter_context(patch.object(orbit,'SubprocessRunner',Native))
                stack.enter_context(patch.object(part_reconstruction,'bind_payloads',side_effect=bind))
                stack.enter_context(patch.object(part_reconstruction,'body_reference_lifecycle',side_effect=gate or (lambda p,b:b or {'first':'complete'})))
                stack.enter_context(patch('schemaxis.dispatch.cancellation_requested',side_effect=lambda:cancelled[0]))
                if clock is not None:stack.enter_context(patch('schemaxis.dispatch._clock',side_effect=lambda:clock[0]))
                try:orbit.bind_lifecycle(submitted,None,generated,root/'runtime.zip',Interpreter('freecad','/installed'),{}, {},set())
                finally:self.launches=launches;self.binds=binds

    def test_first_matching_whole_state_accepts_and_storage_does_not_accumulate(self):
        self.run_orbit(['b','c','d'],accepted='c');self.assertEqual(self.binds,['b','c']);self.assertEqual(len(self.launches),2)

    def test_first_whole_match_wins_even_when_state_key_repeats(self):
        self.run_orbit(['a'],accepted='a');self.assertEqual(self.binds,['a']);self.assertEqual(len(self.launches),1)

    def test_candidate_resource_preflight_precedes_receipt_xml_and_key_decode(self):
        gates=[]
        def gate(path,baseline):gates.append(path);raise AssertionError('oversized archive reached geometry')
        def oversized(root,target):
            with ZipFile(target/'model.FCStd') as z:members={n:z.read(n) for n in z.namelist()}
            members['Document.xml']=b'invalid XML but first oversized'+b'x'*2048
            with ZipFile(target/'model.FCStd','w',ZIP_DEFLATED) as z:
                for n,data in members.items():z.writestr(n,data)
        with patch('schemaxis.adaptors.freecad.source_envelope.MEMBER_BYTES',1024):
            with self.assertRaises(SchemaxisError) as error:self.run_orbit(['b'],sabotage=oversized,gate=gate)
        self.assertEqual(error.exception.fault.code,'RESOURCE_LIMIT');self.assertEqual(gates,[]);self.assertEqual(self.binds,[])
        def malformed(root,target):(target/'model.FCStd').write_bytes(b'not a ZIP archive')
        with self.assertRaises(SchemaxisError) as error:self.run_orbit(['b'],sabotage=malformed,gate=gate)
        self.assertEqual(error.exception.fault.code,'VERIFICATION_FAILED');self.assertEqual(gates,[])

    def test_repeated_mismatching_state_is_structured_unresolved(self):
        with self.assertRaises(SchemaxisError) as error:self.run_orbit(['b','b'])
        self.assertEqual(error.exception.fault.code,'VERIFICATION_FAILED')
        self.assertEqual(error.exception.fault.observed['reason'],'trusted-state-repeated');self.assertEqual(self.binds,['b','b'])

    def test_serial_transitions_share_the_parent_budget(self):
        clock=[100.]
        with patch('schemaxis.dispatch._clock',side_effect=lambda:clock[0]),execution_deadline(10):
            with self.assertRaises(SchemaxisError) as error:self.run_orbit(['b','c','d'],clock=clock)
        self.assertEqual(error.exception.fault.code,'RUNNER_TIMED_OUT');self.assertEqual(self.launches,[10,6,2]);self.assertEqual(self.binds,['b','c'])

    def test_native_cancel_and_timeout_keep_their_identity(self):
        for fault in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT'):
            with self.subTest(fault=fault),self.assertRaises(SchemaxisError) as error:self.run_orbit([],fault=fault)
            self.assertEqual(error.exception.fault.code,fault)
        with self.assertRaises(SchemaxisError) as error:self.run_orbit(['b'],cancel=True)
        self.assertEqual(error.exception.fault.code,'RUNNER_CANCELLED');self.assertEqual(self.binds,[])

    def test_worker_symlink_candidate_refuses_before_geometry_bind_or_key(self):
        def sabotage(root,target):
            (target/'model.FCStd').unlink();(target/'model.FCStd').symlink_to(root/'submitted.FCStd')
        with self.assertRaisesRegex(ValueError,'symlink'):self.run_orbit(['b'],sabotage=sabotage)
        self.assertEqual(self.binds,[]);self.assertEqual(len(self.launches),1)

    def test_geometry_failure_is_terminal_before_bind_or_next_key(self):
        def gate(path,baseline):raise ValueError('complete geometry changed')
        with patch.object(orbit,'state_key',wraps=orbit.state_key) as key:
            with self.assertRaisesRegex(ValueError,'geometry changed'):self.run_orbit(['b','c'],gate=gate)
        self.assertEqual(key.call_count,1,'Only initial fresh-build key may precede geometry')
        self.assertEqual(self.binds,[]);self.assertEqual(len(self.launches),1)

    def test_body_local_budget_starts_before_build_and_keeps_tighter_parent(self):
        prepared=_native_plan({'version':'schemaxis.freecad/1','nodes':[{'id':'body','filter':'body'},
            {'id':'profile','filter':'rectangle','inputs':{'body':'body'}},
            {'id':'pad','filter':'pad','inputs':{'body':'body','profile':'profile'}}],'output':'pad'})
        for parent,cost,expected in ((None,121,120),(9,10,9)):
            clock=[100.];budgets=[]
            def build(*args,**kwargs):budgets.append(remaining_timeout(240));clock[0]+=cost;return {'trusted':'local'}
            with ExitStack() as stack:
                stack.enter_context(patch('schemaxis.dispatch._clock',side_effect=lambda:clock[0]));stack.enter_context(patch.object(part_reconstruction,'_verify',side_effect=build))
                if parent:stack.enter_context(execution_deadline(parent))
                with self.subTest(parent=parent),self.assertRaises(SchemaxisError) as error:part_reconstruction.verify('submitted',prepared,{},body_local=True)
                self.assertEqual(error.exception.fault.code,'RUNNER_TIMED_OUT');self.assertEqual(budgets,[expected])


class ReconstructionAuthorityModes(unittest.TestCase):
    def test_local_and_whole_export_authority_cannot_be_combined(self):
        # Reject a confused admission request before touching even an absent
        # submitted path, selecting a Body or starting trusted reconstruction.
        with patch.object(part_reconstruction,'_verify') as reconstruct:
            with self.assertRaisesRegex(ValueError,'distinct requests'):
                part_reconstruction.verify('absent.FCStd',{}, {},
                    body_local=True,exports={'step':'absent.step','stl':'absent.stl'})
            reconstruct.assert_not_called()

    def test_whole_export_result_is_not_unwrapped_to_local_scalar_evidence(self):
        exports={'step':'accepted.step','stl':'accepted.stl'}
        authority={'built':{'definition':{'output':'coil'}},
                   'reopened':{'freshProcess':True},
                   'exportEvidence':{'precision':{'method':'independent'}},
                   'bodyLocalExportEvidence':{'frame':'bodyLocal','body':'B0'}}
        with patch.object(part_reconstruction,'_verify',return_value=authority) as reconstruct:
            result=part_reconstruction.verify('submitted.FCStd',{}, {},exports=exports)
        self.assertIs(result,authority)
        self.assertIs(reconstruct.call_args.kwargs['exports'],exports)
        self.assertIs(reconstruct.call_args.kwargs['body_local'],False)

    def test_truthy_non_boolean_local_requests_refuse_before_reconstruction(self):
        with patch.object(part_reconstruction,'_verify') as reconstruct:
            for value in (0,1,None,'false',{}):
                with self.subTest(value=value),self.assertRaises(ValueError):
                    part_reconstruction.verify('absent.FCStd',{}, {},body_local=value)
            reconstruct.assert_not_called()


if __name__=='__main__':unittest.main()
