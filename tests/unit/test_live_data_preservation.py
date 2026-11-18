# Copyright (C) 2026 David L. F. Gaden.
"""Public Data ownership, private preserving IPC and measured-only old-window requests."""
import copy
import json
import time
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from schemaxis import live_transport as transport
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.pipeline import DefinitionGraph
from schemaxis.storage import digest
from test_live_identity import Fixture, Process, CATALOGUE, binding
from test_resident_transition import Counted, EXTRA, STATE


class Preservation(Fixture):
    def setUp(self):
        super().setUp()
        self.live.load(self.request(self.old, nodes=['skin']))
        self.client = Process.instances[0]
        self.reader = self.worker().active.handles['mesh']

    def record(self):
        return next(iter(self.live.workers.values()))

    def added(self):
        new = copy.deepcopy(self.old)
        new['nodes'].extend([copy.deepcopy(EXTRA), {'id': 'leaf', 'filter': 'shrink', 'inputs': {'input': 'extra'}}])
        return new

    def assert_owner_kept(self):
        self.assertEqual(self.created, 1)
        self.assertFalse(self.client.closed)
        self.assertIs(self.worker().active.handles['mesh'], self.reader)
        self.assertEqual(self.backend.reads[self.reader['id']], 1)

    def test_old_and_new_public_windows_measure_without_executing_absent_branches(self):
        new = self.added()
        self.live.load(self.request(new, nodes=['skin', 'leaf']))
        handles = dict(self.worker().active.handles)
        calls = list(self.backend.calls)
        for _ in range(2):
            for doc in (self.old, new):
                self.live.inspect(self.request(doc), 'mesh')
                reply = self.live.refresh(self.request(doc, nodes=['mesh'], expression='extents(mesh)'))
                self.assertEqual(reply['observations']['inputDigest'], digest(doc))
                self.assertTrue(next(n for n in self.live.selection(self.request(doc))['nodes'] if n['id']=='mesh')['loaded'])
        self.assertEqual(self.backend.calls, calls)
        self.assertEqual(self.worker().active.handles, handles)
        self.assert_owner_kept()
        changed = copy.deepcopy(new); changed['nodes'][2]['options']['factor'] = .7
        self.live.load(self.request(changed, nodes=['leaf']))
        self.assertEqual(self.record()['lastLoad']['updated'], ['extra','leaf'])
        self.live.inspect(self.request(self.old), 'mesh')
        self.assert_owner_kept()

    def test_lineaged_ordinary_addition_keeps_old_bare_window_and_measurement_origins(self):
        _, renamed = self.rename(self.old)
        new = copy.deepcopy(renamed['input'])
        extra = copy.deepcopy(EXTRA); extra['inputs']['input'] = 'globe'; new['nodes'].append(extra)
        self.live.load(self.request(new, renamed['to'], nodes=['skin','extra']))
        for _ in range(2):
            self.live.inspect(self.request(self.old), 'mesh')
            self.live.inspect(self.request(new, renamed['to']), 'globe')
        self.assertEqual(self.created, 1)
        self.assertIs(self.worker().active.handles['globe'], self.reader)
        self.assertEqual(self.backend.reads[self.reader['id']], 1)

    def test_onvisit_owned_branch_does_not_execute_on_old_inspection_and_is_protected(self):
        declarations = copy.deepcopy(CATALOGUE)
        declarations['shrink']['commands'] = {'Refresh': {'command': 'Modified'}}
        new = self.added(); new['nodes'][2]['onVisit'] = ['Refresh']
        def native(value, **kwargs): return DefinitionGraph(value, declarations), self.backend
        def selected(path):
            from test_live_identity import NATIVE
            return native if path == NATIVE else binding(path)
        with patch('schemaxis.adaptors.paraview.filters.catalogue', return_value=declarations), patch('test_live_identity.binding', side_effect=selected):
            self.live.load(self.request(new, nodes=['leaf']))
            before = list(self.backend.calls)
            self.live.inspect(self.request(self.old), 'mesh')
            self.live.refresh(self.request(self.old, nodes=['mesh']))
            self.assertEqual(before, self.backend.calls)
            # A new branch of the old view would execute the retained command branch.
            other = copy.deepcopy(self.old)
            other['nodes'].append(dict(EXTRA, id='fresh'))
            with self.assertRaises(SchemaxisError) as caught:
                self.live.load(self.request(other, nodes=['fresh']))
            self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_RESIDENT_TRANSITION')
            self.assertEqual(before, self.backend.calls)
        self.assert_owner_kept()

    def test_rollback_is_retained_and_lost_reply_is_never_blindly_retried(self):
        original = self.backend.update
        def update(handle, time):
            original(handle,time)
            if self.backend.labels[id(handle)]=='extra': raise RuntimeError('update failed')
        with patch.object(self.backend,'update',side_effect=update):
            with self.assertRaises(SchemaxisError) as caught: self.live.load(self.request(self.added(),nodes=['leaf']))
        self.assertTrue(caught.exception.fault.observed['rolledBack'])
        self.assert_owner_kept()
        self.live.inspect(self.request(self.old),'mesh')
        real = self.client.request
        def lost(command, **args):
            result=real(command, **args)
            if command=='data-transition': raise OSError('lost acknowledged result')
            return result
        with patch.object(self.client,'request',side_effect=lost):
            with self.assertRaises(OSError): self.live.load(self.request(self.added(),nodes=['leaf']))
        self.assertTrue(self.record()['uncertain'])
        self.assertFalse(self.client.closed)
        calls=list(self.backend.calls)
        with self.assertRaises(SchemaxisError): self.live.inspect(self.request(self.old),'mesh')
        self.assertEqual(calls,self.backend.calls)
        self.assert_owner_kept()

    def test_unknown_create_keeps_actual_client_and_known_reader_until_unload(self):
        original=self.backend.create
        def allocated(node,*args):
            handle=original(node,*args)
            if node=='extra':raise RuntimeError('allocated before failing')
            return handle
        with patch.object(self.backend,'create',side_effect=allocated):
            with self.assertRaises(SchemaxisError) as caught:self.live.load(self.request(self.added(),nodes=['leaf']))
        self.assertEqual(caught.exception.fault.code,'UNCERTAIN_STATE')
        self.assertIn('extra',caught.exception.fault.observed['unknown'])
        self.assertTrue(self.record()['uncertain'])
        self.assert_owner_kept()
        self.live.unload();self.assertTrue(self.client.closed)

    def test_current_measured_reply_budget_rollback_and_failure_of_reversal(self):
        original = self.backend.extents
        def ports(handle):
            value = original(handle)
            return value*64 if self.backend.labels[id(handle)]=='extra' else value
        new=copy.deepcopy(self.old);new['nodes'].append(copy.deepcopy(EXTRA))
        before=copy.deepcopy(self.record()['owner']);cache=copy.deepcopy(self.live.cache)
        with patch.object(self.backend,'extents',side_effect=ports), patch.object(transport,'MAX_BYTES',4000):
            with self.assertRaises(SchemaxisError) as caught:self.live.load(self.request(new,nodes=['extra']))
        self.assertEqual(caught.exception.fault.code,'LOAD_FAILED')
        self.assertTrue(caught.exception.fault.observed['rolledBack'])
        self.assertEqual(cache,self.live.cache)
        self.assertGreater(self.record()['owner']['generation'],before['generation'])
        self.assertEqual(self.worker().document,self.record()['plan'])
        self.assert_owner_kept()
        self.live.inspect(self.request(self.old),'mesh')
        original_delete=self.backend.delete
        def no_delete(handle):
            if self.backend.labels[id(handle)]=='extra':raise RuntimeError('delete refused')
            return original_delete(handle)
        with patch.object(self.backend,'extents',side_effect=ports), patch.object(self.backend,'delete',side_effect=no_delete), patch.object(transport,'MAX_BYTES',4000):
            with self.assertRaises(SchemaxisError) as caught:self.live.load(self.request(new,nodes=['extra']))
        self.assertEqual(caught.exception.fault.code,'UNCERTAIN_STATE')
        self.assertTrue(self.record()['uncertain'])
        self.assert_owner_kept()

    def test_alignment_lost_reply_retains_client_and_rejects_legacy_transport(self):
        with patch.object(self.client,'request_retained',None):
            calls=list(self.backend.calls)
            with self.assertRaises(SchemaxisError) as caught:self.live.load(self.request(self.added(),nodes=['leaf']))
            self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_RESIDENT_CLIENT')
            self.assertEqual(calls,self.backend.calls)
        _, accepted=self.rename(self.old)
        real=self.client.request
        def lost(command,**args):
            result=real(command,**args)
            if command=='data-owned-identity':raise OSError('lost identity reply')
            return result
        with patch.object(self.client,'request',side_effect=lost):
            with self.assertRaises(OSError):self.live.inspect(self.request(accepted['input'],accepted['to']),'globe')
        self.assertTrue(self.record()['uncertain'])
        self.assertFalse(self.client.closed)
        self.assertIs(self.worker().active.handles['globe'],self.reader)
        self.assertEqual(self.backend.reads[self.reader['id']],1)
        calls=list(self.backend.calls)
        with self.assertRaises(SchemaxisError):self.live.inspect(self.request(self.old),'mesh')
        self.assertEqual(calls,self.backend.calls)
        self.assertEqual(self.created,1)

    def test_inspection_lost_reply_keeps_owner_without_hidden_retry(self):
        real=self.client.request
        def lost(command,**args):
            result=real(command,**args)
            if command=='data-inspect':raise OSError('inspection response lost')
            return result
        with patch.object(self.client,'request',side_effect=lost):
            with self.assertRaises(OSError):self.live.inspect(self.request(self.old),'mesh')
        self.assertTrue(self.record()['uncertain'])
        self.assert_owner_kept()
        calls=list(self.backend.calls)
        with self.assertRaises(SchemaxisError):self.live.inspect(self.request(self.old),'mesh')
        self.assertEqual(calls,self.backend.calls)
        self.assert_owner_kept()

    def test_inspection_wrong_owner_is_uncertain_but_checked_refusal_is_healthy(self):
        real=self.client.request
        def refused(command,**args):
            if command=='data-inspect':raise SchemaxisError(Fault('UNSUPPORTED_INSPECTION','Checked refusal','$.node','live'))
            return real(command,**args)
        with patch.object(self.client,'request',side_effect=refused):
            with self.assertRaises(SchemaxisError):self.live.inspect(self.request(self.old),'mesh')
        self.assertFalse(self.record().get('uncertain',False))
        self.live.inspect(self.request(self.old),'mesh')
        def wrong(command,**args):
            result=real(command,**args)
            if command=='data-inspect':result['owner']['generation']+=1
            return result
        with patch.object(self.client,'request',side_effect=wrong):
            with self.assertRaises(SchemaxisError) as caught:self.live.inspect(self.request(self.old),'mesh')
        self.assertEqual(caught.exception.fault.code,'RESIDENT_OWNER_MISMATCH')
        self.assertTrue(self.record()['uncertain'])
        self.assert_owner_kept()

    def assert_corrupt_ack(self, mutate, identity=False):
        before=copy.deepcopy(self.record()['owner'])
        real=self.client.request
        command='data-owned-identity' if identity else 'data-transition'
        def corrupt(name,**args):
            result=real(name,**args)
            if name==command:mutate(result['owner'])
            return result
        if identity:
            _,accepted=self.rename(self.old)
        with patch.object(self.client,'request',side_effect=corrupt):
            with self.assertRaises(SchemaxisError) as caught:
                if identity:self.live.inspect(self.request(accepted['input'],accepted['to']),'globe')
                else:self.live.load(self.request(self.added(),nodes=['leaf']))
        self.assertEqual('RESIDENT_OWNER_MISMATCH',caught.exception.fault.code)
        self.assertEqual(before,self.record()['owner'])
        self.assertTrue(self.record()['uncertain'])
        self.assertEqual(1,self.created)
        self.assertFalse(self.client.closed)
        self.assertIn(self.reader,self.worker().active.handles.values())
        self.assertEqual(1,self.backend.reads[self.reader['id']])

    def test_transition_ack_rejects_wrong_concrete_visit(self):
        self.assert_corrupt_ack(lambda owner:owner['visit'].update(timeIndex=9876))

    def test_transition_ack_rejects_wrong_roots(self):
        self.assert_corrupt_ack(lambda owner:owner.update(roots=['mesh']))

    def test_transition_ack_rejects_extra_token_member(self):
        self.assert_corrupt_ack(lambda owner:owner.update(extra=True))

    def test_transition_ack_rejects_missing_token_member(self):
        self.assert_corrupt_ack(lambda owner:owner.pop('visit'))

    def test_transition_ack_rejects_equal_but_wrong_json_type(self):
        self.assert_corrupt_ack(lambda owner:owner['visit'].update(timeIndex=False))

    def test_identity_ack_rejects_unmapped_roots(self):
        self.assert_corrupt_ack(lambda owner:owner.update(roots=['mesh']),identity=True)

    def test_identity_ack_rejects_changed_visit(self):
        self.assert_corrupt_ack(lambda owner:owner['visit'].update(timeIndex=1),identity=True)

    def test_changed_visit_never_relabels_old_measurement_or_loads_on_refresh(self):
        value=copy.deepcopy(self.old);value['times']=[0,1]
        self.live.load(self.request(value,nodes=['skin']))
        count=self.created;calls=list(self.backend.calls)
        later=self.request(value,state={'timeIndex':1},nodes=['mesh'],expression='extents(mesh)')
        result=self.live.refresh(later)
        self.assertEqual(result['records'][0]['state'],'unresolved')
        self.assertEqual(self.created,count)
        self.assertEqual(calls,self.backend.calls)
        self.assertIsNone(self.live.observations(later))

    def test_worker_rejects_equal_python_but_different_json_owner_values(self):
        original=copy.deepcopy(self.record()['owner']);calls=list(self.backend.calls)
        for field,value in (('time',False),('timeIndex',False),('time',0)):
            with self.subTest(field=field,value=value):
                expected=copy.deepcopy(original);expected['visit'][field]=value
                with self.assertRaises(SchemaxisError) as caught:
                    self.client.request('data-measure',expected=expected,nodes=['mesh'])
                self.assertEqual('STALE_RESIDENT_OWNER',caught.exception.fault.code)
                self.assertEqual(original,self.worker().owner())
                self.assertEqual(calls,self.backend.calls)
        self.live.inspect(self.request(self.old),'mesh')
        self.assert_owner_kept()

    def test_owner_preparation_rejects_foreign_and_aba_generations(self):
        worker=self.worker(); owner=copy.deepcopy(self.record()['owner'])
        args={'expected':owner,'document':worker.document,'roots':['skin'],'state':STATE,'preserve':['mesh'],'request':'a'*32}
        first=self.client.request('data-prepare-transition',**args)
        self.assertEqual(owner,self.record()['owner'])
        bad=copy.deepcopy(args);bad['expected']['nonce']='0'*32
        with self.assertRaises(SchemaxisError):self.client.request('data-prepare-transition',**bad)
        result=self.client.request('data-transition',**args,prepared=first['prepared'])
        self.assertGreater(result['owner']['generation'],owner['generation'])
        with self.assertRaises(SchemaxisError) as caught:self.client.request('data-transition',**args,prepared=first['prepared'])
        self.assertEqual(caught.exception.fault.code,'STALE_RESIDENT_OWNER')
        # Reconcile this intentionally direct worker call for cleanup, without implying host admission.
        self.record()['owner']=result['owner']
        self.assert_owner_kept()


class Acquisition(Fixture):
    def test_initial_reply_must_establish_a_closed_exact_owner(self):
        real=Process.request
        mutations=[lambda owner:owner.update(extra=True), lambda owner:owner.pop('nonce'),
                   lambda owner:owner.update(generation=True),lambda owner:owner.update(nonce='x'*32),
                   lambda owner:owner.update(roots=['foreign']),
                   lambda owner:owner['visit'].update(timeIndex=9)]
        for index,mutate in enumerate(mutations):
            with self.subTest(index=index):
                def corrupt(client,command,**args):
                    result=real(client,command,**args)
                    if command=='data-load':mutate(result['owner'])
                    return result
                with patch.object(Process,'request',corrupt):
                    with self.assertRaises(SchemaxisError) as caught:self.live.load(self.request(self.old,nodes=['skin']))
                self.assertEqual('RESIDENT_OWNER_MISMATCH',caught.exception.fault.code)
                self.assertFalse(self.live.workers)
                self.assertTrue(Process.instances[-1].closed)


class RetainedTransport(unittest.TestCase):
    def test_timeout_keeps_owner_and_blocks_single_slot_until_explicit_close(self):
        with tempfile.TemporaryDirectory() as directory:
            client=transport.ProcessSession.__new__(transport.ProcessSession)
            client._lock=threading.RLock();client._closed=False;client._retained_uncertain=False
            client.directory=Path(directory);client.provider='paraview';client.timeout=.01
            killed=[];client._terminate=lambda *a,**kw:killed.append(True)
            client._await=lambda *a,**kw:transport.fault('LIVE_TIMEOUT','lost reply',uncertain=True)
            with self.assertRaises(SchemaxisError):client.request_retained('status')
            first=(Path(directory)/'request.json').read_bytes()
            self.assertEqual(killed,[])
            with self.assertRaises(SchemaxisError) as caught:client.request('status')
            self.assertEqual(caught.exception.fault.code,'UNCERTAIN_STATE')
            self.assertEqual((Path(directory)/'request.json').read_bytes(),first)
            client.process=None;client.close()
            self.assertEqual(killed,[True])

    def test_actual_oversized_fault_wire_keeps_critical_mutation_outcome(self):
        from schemaxis.artifacts import atomic_json
        class Worker:
            provider='paraview'
            def dispatch(self,command,args):
                if command=='shutdown':return {'closed':True}
                outcome={'rolledBack':True} if args['request']=='b'*32 else {'uncertain':True}
                raise SchemaxisError(Fault('LOAD_FAILED','x'*8000,'$','live',observed=outcome))
            def close(self):pass
        with tempfile.TemporaryDirectory() as directory, patch.object(transport,'MAX_BYTES',1800):
            root=Path(directory);thread=threading.Thread(target=transport.serve,args=(root,Worker()),daemon=True);thread.start()
            try:
                for char,outcome in [('a','uncertain'),('b','rolledBack')]:
                    owner={'nonce':'a'*32,'generation':1,'documentDigest':'b'*64,'roots':['x'],'visit':{}}
                    args={'expected':owner,'document':{},'roots':['x'],'state':{},'preserve':[],
                          'request':char*32,'prepared':'c'*64}
                    atomic_json(root/'request.json',{'id':char*32,'command':'data-transition','args':args})
                    path=root/(char*32+'.json');deadline=time.monotonic()+3
                    while not path.exists() and time.monotonic()<deadline:time.sleep(.01)
                    reply=json.loads(path.read_text())
                    self.assertLessEqual(path.stat().st_size,1800)
                    self.assertEqual(reply['fault']['code'],'LIVE_LIMIT')
                    self.assertEqual(reply['fault']['observed'],{outcome:True})
            finally:
                atomic_json(root/'request.json',{'id':'d'*32,'command':'shutdown','args':{}})
                thread.join(3)
            self.assertFalse(thread.is_alive())

    def test_closed_wire_rejects_unknown_fields_and_invalid_owner(self):
        args={'expected':{'nonce':'a'*32,'generation':1,'documentDigest':'b'*64,'roots':['x'],'visit':{}},'nodes':['x']}
        transport.validate('data-measure',args)
        for bad in ({**args,'extra':True},{**args,'nodes':['x','x']},{**args,'expected':{}}):
            with self.assertRaises(SchemaxisError):transport.validate('data-measure',bad)

class AlignedPreflight(Fixture):
    def setUp(self):
        super().setUp()
        self.live.load(self.request(self.old, nodes=['skin']))
        self.client = Process.instances[0]

    def record(self):
        return next(iter(self.live.workers.values()))

    def snapshot(self):
        worker = self.worker(); active = worker.active
        return copy.deepcopy({'record': {k: v for k, v in self.record().items() if k != 'client'},
            'owner': worker.owner(), 'document': worker.document, 'calls': self.backend.calls,
            'labels': self.backend.labels, 'handles': {k: id(v) for k, v in active.handles.items()},
            'values': active.values, 'observations': active.observations, 'visit': active.visit,
            'events': active.events, 'generation': active.generation,
            'cache': self.live.cache, 'cacheOwners': self.live.cache_owners, 'visits': self.live.visits,
            'views': self.live.views, 'edges': {k: {f: x for f, x in v.items() if f != 'sides'}
                                               for k, v in self.live.edges.items()}})

    def candidate(self):
        _, accepted = self.rename(self.old)
        new = copy.deepcopy(accepted['input'])
        new['nodes'].append({**copy.deepcopy(EXTRA), 'inputs': {'input': 'globe'}})
        return accepted, new

    def test_pending_identity_then_new_work_is_prepared_without_any_native_ownership(self):
        from contextlib import ExitStack
        from schemaxis.pipeline import RuntimeClosure
        from schemaxis.context import ObjectRegistry
        accepted, new = self.candidate()
        new['nodes'][1]['options']['factor'] = .7
        real = self.client.request
        seen = []
        def checked(command, **args):
            if command != 'data-prepare-aligned-transition': return real(command, **args)
            before = self.snapshot()
            with ExitStack() as spies:
                for name in ('create','configure','command','update','observe','extents','delete','relabel','output_port'):
                    spies.enter_context(patch.object(self.backend,name,side_effect=AssertionError('native '+name)))
                for name in ('publish','retire','close'):
                    spies.enter_context(patch.object(ObjectRegistry,name,side_effect=AssertionError('registry '+name)))
                for name in ('__init__','activate','apply','transition','reidentify','close'):
                    spies.enter_context(patch.object(RuntimeClosure,name,side_effect=AssertionError('lifecycle '+name)))
                result = real(command, **args)
            self.assertEqual(before, self.snapshot())
            seen.append(copy.deepcopy(result))
            return result
        with patch.object(self.client,'request',side_effect=checked):
            self.live.load(self.request(new,accepted['to'],nodes=['skin','extra']))
        self.assertEqual(1,len(seen))
        commands=self.client.requests
        self.assertLess(commands.index('data-prepare-aligned-transition'),commands.index('data-owned-identity'))
        self.assertLess(commands.index('data-owned-identity'),commands.index('data-transition'))
        self.assertEqual(['extra'],self.record()['lastLoad']['created'])
        reader=self.worker().active.handles['globe'];self.assertEqual(1,self.backend.reads[reader['id']])
        # The original owner remains usable and owns cleanup exactly once.
        self.live.inspect(self.request(self.old),'mesh')
        self.live.unload()
        self.assertEqual(3,self.backend.count('delete'))
        self.assertFalse(self.backend.labels)

    def test_refused_onvisit_after_identity_keeps_every_owned_and_cached_fact(self):
        declarations=copy.deepcopy(CATALOGUE)
        declarations['shrink']['commands']={'Refresh':{'command':'Modified'}}
        from test_live_identity import NATIVE
        def native(value,**kwargs):return DefinitionGraph(value,declarations),self.backend
        def selected(path):return native if path==NATIVE else binding(path)
        with patch('schemaxis.adaptors.paraview.filters.catalogue',return_value=declarations), patch('test_live_identity.binding',side_effect=selected):
            self.live.unload();Process.instances=[]
            self.live.load(self.request(self.old,nodes=['skin']));self.client=Process.instances[0]
            accepted,new=self.candidate();new['nodes'][-1]['onVisit']=['Refresh']
            self.live.load(self.request(new,accepted['to'],nodes=['extra']))
            other=copy.deepcopy(self.old);other['nodes'].append(dict(EXTRA,id='fresh'))
            before=self.snapshot()
            with self.assertRaises(SchemaxisError) as caught:self.live.load(self.request(other,nodes=['fresh']))
            self.assertEqual('UNSUPPORTED_RESIDENT_TRANSITION',caught.exception.fault.code)
            self.assertEqual(before,self.snapshot())

    def test_carry_conflict_bad_visit_and_future_envelope_refuse_before_alignment(self):
        accepted,new=self.candidate()
        self.live.load(self.request(new,accepted['to'],nodes=['extra']))
        other=copy.deepcopy(self.old);other['nodes'].append(dict(EXTRA,id='fresh'))
        from schemaxis import spatial_load
        cases=[('carry',patch.object(self.live,'carried',return_value=None),'LIVE_DATA_CONFLICT'),
               ('visit',patch.object(spatial_load,'visit_of',side_effect=SchemaxisError(Fault('INVALID_SELECTION','bad visit','$','live'))),'INVALID_SELECTION')]
        for label,guard,code in cases:
            with self.subTest(label=label):
                before=self.snapshot()
                with guard,self.assertRaises(SchemaxisError) as caught:self.live.load(self.request(other,nodes=['fresh']))
                self.assertEqual(code,caught.exception.fault.code);self.assertEqual(before,self.snapshot())
        original=transport.request_budget
        def budget(command,args):
            if command=='data-transition':transport.fault('LIVE_LIMIT','future complete request exceeds limit')
            return original(command,args)
        before=self.snapshot()
        with patch.object(transport,'request_budget',side_effect=budget),self.assertRaises(SchemaxisError) as caught:
            self.live.load(self.request(other,nodes=['fresh']))
        self.assertEqual('LIVE_LIMIT',caught.exception.fault.code);self.assertEqual(before,self.snapshot())
        with patch.object(transport,'MAX_BYTES',1000),self.assertRaises(SchemaxisError) as caught:
            self.live.load(self.request(other,nodes=['fresh']))
        self.assertEqual('LIVE_LIMIT',caught.exception.fault.code);self.assertEqual(before,self.snapshot())

    def test_prepared_prediction_and_digest_are_not_trusted(self):
        mutations=[lambda r:r['predictedOwner'].update(nonce='0'*32),
            lambda r:r['predictedOwner'].update(generation=r['predictedOwner']['generation']+1),
            lambda r:r['predictedOwner'].update(roots=['foreign']),
            lambda r:r['predictedOwner']['visit'].update(timeIndex=9),
            lambda r:r['predictedOwner'].update(extra=True),lambda r:r.update(prepared='0'*64)]
        for mutate in mutations:
            fixture=AlignedPreflight();fixture.setUp()
            try:
                accepted,new=fixture.candidate();before=fixture.snapshot();real=fixture.client.request
                def corrupt(command,**args):
                    reply=real(command,**args)
                    if command=='data-prepare-aligned-transition':mutate(reply)
                    return reply
                with patch.object(fixture.client,'request',side_effect=corrupt),self.assertRaises(SchemaxisError) as caught:
                    fixture.live.load(fixture.request(new,accepted['to'],nodes=['extra']))
                self.assertEqual('RESIDENT_OWNER_MISMATCH',caught.exception.fault.code)
                self.assertTrue(fixture.record()['uncertain']);self.assertFalse(fixture.client.closed)
                self.assertEqual(before['calls'],fixture.backend.calls)
                self.assertEqual(before['owner'],fixture.worker().owner())
                self.assertEqual(before['record']['evidence'],fixture.record()['evidence'])
            finally:fixture.doCleanups()

    def test_lost_aligned_preflight_retains_owner_and_never_aligns(self):
        accepted,new=self.candidate();before=self.snapshot();real=self.client.request
        def lost(command,**args):
            reply=real(command,**args)
            if command=='data-prepare-aligned-transition':raise OSError('preflight reply lost')
            return reply
        with patch.object(self.client,'request',side_effect=lost),self.assertRaises(OSError):
            self.live.load(self.request(new,accepted['to'],nodes=['extra']))
        self.assertTrue(self.record()['uncertain']);self.assertFalse(self.client.closed)
        self.assertEqual(before['owner'],self.worker().owner());self.assertEqual(before['calls'],self.backend.calls)
        with self.assertRaises(SchemaxisError):self.live.load(self.request(new,accepted['to'],nodes=['extra']))
        self.assertEqual(before['calls'],self.backend.calls)

    def test_worker_wrong_prepared_digest_and_interleaved_epoch_refuse_before_mutation(self):
        worker=self.worker();owner=worker.owner();calls=list(self.backend.calls)
        args={'expected':owner,'document':worker.document,'roots':['skin'],'state':STATE,'preserve':['mesh'],'request':'a'*32}
        prepared=self.client.request('data-prepare-transition',**args)
        with self.assertRaises(SchemaxisError) as caught:self.client.request('data-transition',**args,prepared='0'*64)
        self.assertEqual('STALE_RESIDENT_TRANSITION',caught.exception.fault.code)
        self.assertEqual(calls,self.backend.calls);self.assertEqual(owner,worker.owner())
        worker.generation+=1  # Another acknowledged operation, even with identical content.
        with self.assertRaises(SchemaxisError) as caught:self.client.request('data-transition',**args,prepared=prepared['prepared'])
        self.assertEqual('STALE_RESIDENT_OWNER',caught.exception.fault.code);self.assertEqual(calls,self.backend.calls)

    def test_rollback_status_requires_exact_advanced_owner_and_no_uncertainty(self):
        mutations=[lambda r:r['owner'].update(generation=r['owner']['generation']+1),
            lambda r:r['owner'].update(documentDigest='0'*64),lambda r:r.update(uncertain=True),
            lambda r:r['owner']['visit'].update(timeIndex=9),lambda r:r['owner'].update(nonce='0'*32)]
        for mutate in mutations:
            fixture=AlignedPreflight();fixture.setUp()
            try:
                new=copy.deepcopy(fixture.old);new['nodes'].append(copy.deepcopy(EXTRA))
                before=copy.deepcopy(fixture.record()['owner']);real=fixture.client.request;update=fixture.backend.update
                def failing(handle,time):
                    update(handle,time)
                    if fixture.backend.labels[id(handle)]=='extra':raise RuntimeError('update failed')
                def corrupt(command,**args):
                    reply=real(command,**args)
                    if command=='status':mutate(reply)
                    return reply
                with patch.object(fixture.backend,'update',side_effect=failing),patch.object(fixture.client,'request',side_effect=corrupt):
                    with self.assertRaises(SchemaxisError):fixture.live.load(fixture.request(new,nodes=['extra']))
                self.assertTrue(fixture.record()['uncertain']);self.assertFalse(fixture.client.closed)
                self.assertEqual(before,fixture.record()['owner'])
                reader=fixture.worker().active.handles['mesh'];self.assertEqual(1,fixture.backend.reads[reader['id']])
            finally:fixture.doCleanups()

    def test_successful_derived_sweep_addition_changes_visit_without_rereading_source(self):
        self.live.unload();Process.instances=[]
        self.old['sweeps']=[{'name':'size','values':[.2,.4]}]
        self.live.load(self.request(self.old,nodes=['skin']));self.client=Process.instances[0]
        new=copy.deepcopy(self.old)
        new['nodes'].append({**copy.deepcopy(EXTRA),'options':{'factor':{'$sweep':'size'}}})
        before=copy.deepcopy(self.record()['owner']['visit'])
        self.live.load(self.request(new,nodes=['extra']))
        after=self.record()['owner']['visit']
        self.assertNotEqual(before,after)
        self.assertEqual({'size':.2},after['sweeps'])
        reader=self.worker().active.handles['mesh'];self.assertEqual(1,self.backend.reads[reader['id']])
        self.assertEqual(after,self.worker().owner()['visit'])


    def test_stale_native_transition_fault_quarantines_without_replacement(self):
        new=copy.deepcopy(self.old);new['nodes'].append(copy.deepcopy(EXTRA))
        calls=list(self.backend.calls);real=self.client.request
        def stale(command,**args):
            if command=='data-transition':transport.fault('STALE_RESIDENT_OWNER','epoch changed')
            return real(command,**args)
        with patch.object(self.client,'request',side_effect=stale),self.assertRaises(SchemaxisError):
            self.live.load(self.request(new,nodes=['extra']))
        self.assertTrue(self.record()['uncertain']);self.assertFalse(self.client.closed)
        self.assertEqual(calls,self.backend.calls)
        with self.assertRaises(SchemaxisError):self.live.load(self.request(new,nodes=['extra']))
        self.assertEqual(1,self.created)

    def test_aligned_worker_rejects_foreign_prediction_and_closed_command_fields(self):
        accepted,new=self.candidate();real=self.client.request;captured=[]
        def stopped(command,**args):
            if command=='data-prepare-aligned-transition':
                captured.append(copy.deepcopy(args))
                transport.fault('INVALID_ARGUMENT','stop before admission')
            return real(command,**args)
        with patch.object(self.client,'request',side_effect=stopped),self.assertRaises(SchemaxisError):
            self.live.load(self.request(new,accepted['to'],nodes=['extra']))
        before=self.snapshot()
        mutations=[lambda a:a['identity']['owner'].update(nonce='0'*32),
                   lambda a:a['identity']['owner'].update(generation=999),
                   lambda a:a['transition']['expected'].update(roots=['foreign']),
                   lambda a:a['transition']['expected']['visit'].update(timeIndex=9),
                   lambda a:a['transition']['expected'].update(extra=True),
                   lambda a:a.update(extra=True)]
        for mutate in mutations:
            args=copy.deepcopy(captured[0]);mutate(args)
            with self.assertRaises(SchemaxisError):real('data-prepare-aligned-transition',**args)
            self.assertEqual(before,self.snapshot())

    def test_changed_concrete_sweep_visit_cannot_be_acknowledged_as_old_visit(self):
        self.live.unload();Process.instances=[]
        self.old['sweeps']=[{'name':'size','values':[.2,.4]}]
        self.live.load(self.request(self.old,nodes=['skin']));self.client=Process.instances[0]
        new=copy.deepcopy(self.old)
        new['nodes'].append({**copy.deepcopy(EXTRA),'options':{'factor':{'$sweep':'size'}}})
        before=copy.deepcopy(self.record()['owner']);real=self.client.request
        def corrupt(command,**args):
            reply=real(command,**args)
            if command=='data-transition':reply['owner']['visit']=copy.deepcopy(before['visit'])
            return reply
        with patch.object(self.client,'request',side_effect=corrupt),self.assertRaises(SchemaxisError) as caught:
            self.live.load(self.request(new,nodes=['extra']))
        self.assertEqual('RESIDENT_OWNER_MISMATCH',caught.exception.fault.code)
        self.assertTrue(self.record()['uncertain']);self.assertEqual(before,self.record()['owner'])
        self.assertEqual({'size':.2},self.worker().owner()['visit']['sweeps'])
        reader=self.worker().active.handles['mesh'];self.assertEqual(1,self.backend.reads[reader['id']])


class InspectionBudget(Fixture):
    def test_actual_file_reply_budgets_owner_inside_optional_geometry_fallback(self):
        from schemaxis.artifacts import atomic_json
        from schemaxis.wire_json import size
        from test_live_identity import INSPECT
        self.live.load(self.request(self.old,nodes=['skin']))
        worker=self.worker();client=Process.instances[0];Process.current=client
        original_owner=worker.owner();calls=list(self.backend.calls)
        payload={'node':'mesh','geometry':{'points':'x'*3000},'observation':{'points':4}}
        def inspected(*args,**kwargs):return transport.inspection_reply(copy.deepcopy(payload))
        def selected(path):return inspected if path==INSPECT else binding(path)
        alone=size({'id':'0'*32,'result':payload},100000)
        with tempfile.TemporaryDirectory() as directory,patch('schemaxis.live_data_worker.registry.binding',side_effect=selected):
            root=Path(directory);thread=threading.Thread(target=transport.serve,args=(root,worker),daemon=True);thread.start()
            try:
                for index,extra in enumerate((0,40,400)):
                    with patch.object(transport,'MAX_BYTES',alone+extra):
                        ident=f'{index+1:032x}'
                        atomic_json(root/'request.json',{'id':ident,'command':'data-inspect','args':{'node':'mesh','port':0,'geometry':True}})
                        path=root/(ident+'.json');deadline=time.monotonic()+3
                        while not path.exists() and time.monotonic()<deadline:time.sleep(.01)
                        reply=json.loads(path.read_text());self.assertLessEqual(path.stat().st_size,alone+extra)
                        self.assertNotIn('fault',reply);result=reply['result']
                        self.assertEqual(original_owner,result['owner']);self.assertEqual({'points':4},result['observation'])
                        if extra<400:
                            self.assertIsNone(result['geometry']);self.assertEqual('LIVE_LIMIT',result['geometryUnavailable']['code'])
                        else:self.assertEqual(payload['geometry'],result['geometry'])
                payload['observation']['large']='x'*6000
                with patch.object(transport,'MAX_BYTES',alone):
                    atomic_json(root/'request.json',{'id':'e'*32,'command':'data-inspect','args':{'node':'mesh','port':0,'geometry':True}})
                    path=root/('e'*32+'.json');deadline=time.monotonic()+3
                    while not path.exists() and time.monotonic()<deadline:time.sleep(.01)
                    reply=json.loads(path.read_text());self.assertLessEqual(path.stat().st_size,alone)
                    self.assertEqual('LIVE_LIMIT',reply['fault']['code'])
                self.assertEqual(original_owner,worker.owner());self.assertEqual(calls,self.backend.calls)
            finally:
                atomic_json(root/'request.json',{'id':'f'*32,'command':'shutdown','args':{}});thread.join(3)
            self.assertFalse(thread.is_alive())
