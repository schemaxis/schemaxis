# Copyright (C) 2026 David L F Gaden
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.console_server import ConsoleApplication
from schemaxis.execution_service import ExecutionService
from schemaxis.core.faults import SchemaxisError
from schemaxis.workflow_authoring import example, graph, observe, rewire, reference
from schemaxis.console_references import ReferenceStore
from schemaxis.storage import encoded


class WorkflowAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.session=AdaptorConsoleSession(self.root/'console','workflow');self.addCleanup(self.session.close)
        self.session._edit(example())

    def identity(self):return self.session.active_document,self.session._record['revision']

    def fault(self,code,action):
        with self.assertRaises(SchemaxisError) as caught:action()
        self.assertEqual(caught.exception.fault.code,code)

    def test_graph_is_exact_projection_with_source_pointers(self):
        before=copy.deepcopy(self.session._state)
        view=graph(self.session,*self.identity())
        self.assertEqual([n['id'] for n in view['nodes']],['samples','scaled'])
        self.assertEqual(view['edges'],[{'source':'samples','target':'scaled','artifactIndex':0,
            'pointer':'/operations/1/document/nodes/0/options/file','kind':'artifact-handoff'}])
        location=self.session.locate_source(*self.identity(),pointer=view['edges'][0]['pointer'])
        self.assertEqual(location['value'],{'$artifact':'samples','index':0})
        self.assertEqual(self.session._state,before)
        self.assertEqual(view['executionMode'],'scheduled')

    def test_independent_operations_do_not_invent_data_edges(self):
        doc=example();doc['operations'][1]['document']=copy.deepcopy(doc['operations'][0]['document'])
        self.session._edit(doc);view=graph(self.session,*self.identity())
        self.assertEqual(view['edges'],[])
        self.assertEqual([n['order'] for n in view['nodes']],[0,1])

    def test_serial_order_is_separate_from_artifact_edges(self):
        doc={'version':'schemaxis.workflow/1','operations':[
            {'id':name,'document':{'version':'schemaxis/1','nodes':[{'id':'body','filter':'sphere'}],'scenes':[{'id':'shape','visible':{'body':{'colour':'steelblue'}},'gltf':True}]}} for name in ('a','b')]}
        self.session._edit(doc);view=graph(self.session,*self.identity())
        self.assertEqual(view['executionMode'],'serial');self.assertEqual(view['edges'],[])
        self.assertIn('declared order',view['orderMeaning'])

    def test_rewire_validates_and_undo_restores_one_group(self):
        doc=example();alternate=copy.deepcopy(doc['operations'][0]);alternate['id']='alternate';doc['operations'].insert(1,alternate)
        self.session._edit(doc);before=self.session.document;undo=len(self.session.history)
        edge=graph(self.session,*self.identity())['edges'][0]
        result=rewire(self.session,*self.identity(),edge['pointer'],'alternate',0)
        self.assertEqual(len(self.session.history),undo+1)
        self.assertEqual(graph(self.session,*self.identity())['edges'][0]['source'],'alternate')
        self.session.undo();self.assertEqual(self.session.document,before)
        self.fault('STALE_REVISION',lambda:rewire(self.session,self.session.active_document,result['revision'],edge['pointer'],'samples',0))

    def test_forward_cycle_unknown_producer_and_invalid_indices_are_atomic(self):
        edge=graph(self.session,*self.identity())['edges'][0]
        for source,index,code in [('scaled',0,'UNAVAILABLE_OPERATION'),('missing',0,'UNAVAILABLE_OPERATION'),('samples',-1,'INVALID_SELECTION'),('samples',True,'INVALID_SELECTION')]:
            before=copy.deepcopy(self.session._state)
            self.fault(code,lambda:rewire(self.session,*self.identity(),edge['pointer'],source,index))
            self.assertEqual(self.session._state,before)
        self.fault('INVALID_HANDOFF',lambda:rewire(self.session,*self.identity(),'/operations/0/id','samples',0))

    def test_missing_runtime_artifact_index_is_not_claimed_verified(self):
        edge=graph(self.session,*self.identity())['edges'][0]
        rewire(self.session,*self.identity(),edge['pointer'],'samples',999)
        view=graph(self.session,*self.identity())
        self.assertEqual(view['edges'][0]['artifactIndex'],999)
        self.assertIn('rechecked',view['verification'])

    def test_invalid_source_and_history_survive_reopen_without_old_graph(self):
        identity,revision=self.identity();self.session.edit_source('{unfinished',identity,revision)
        self.fault('INVALID_DRAFT',lambda:graph(self.session,*self.identity()))
        self.session.close();self.session=AdaptorConsoleSession(self.root/'console','workflow');self.addCleanup(self.session.close)
        self.assertEqual(self.session.draft()['source'],'{unfinished')
        self.session.undo();self.assertEqual(len(graph(self.session,*self.identity())['nodes']),2)

    def test_typed_operation_reference_is_historical_and_stales_on_edit(self):
        store=ReferenceStore(self.session.workspace);identity,revision=self.identity()
        ref=reference(self.session,store,identity,revision,'scaled')
        self.assertEqual(ref['kind'],'workflow-operation');self.assertFalse(ref['replayable'])
        self.assertEqual(ref['payload']['operation'],example()['operations'][1])
        self.assertFalse(store.list(identity,revision)[0]['stale'])
        self.session.patch([{'op':'replace','path':'/operations/1/document/nodes/1/options/factor','value':3}],identity,revision)
        self.assertTrue(store.list(*self.identity())[0]['stale'])
        self.assertEqual(store.data['references'][0]['payload']['operation']['document']['nodes'][1]['options']['factor'],2)
        self.fault('STALE_REFERENCE',lambda:store.message([{'reference':ref['id']}],*self.identity()))

    def test_workflow_is_host_document_not_native_adaptor(self):
        from schemaxis.adaptors.registry import ADAPTORS
        self.assertNotIn('workflow',ADAPTORS)
        for line,code in [('add body box','UNSUPPORTED_COMMAND'),('preview','UNSUPPORTED_COMMAND'),('connect','UNSUPPORTED_COMMAND'),('live /missing','UNSUPPORTED_LIVE')]:
            self.fault(code,lambda:self.session.execute(line))
        self.assertEqual(len(self.session.execute('list')),2)
        self.assertEqual(self.session.execute('inspect samples')['id'],'samples')
        self.fault('UNSUPPORTED_COMMAND',lambda:self.session.configure('workflow','/missing'))

    def test_agent_graph_edit_and_plan_share_current_document(self):
        with ExecutionService(self.root/'agent') as service:
            draft=service.create_draft('workflow');draft=service.edit_draft(draft['document'],draft['revision'],json.dumps(example()))
            target=draft['document'];revision=draft['revision']
            task=service.create_task('Authorised workflow',['octave'])
            plan=service.plan_draft(task['id'],0,target,revision)
            view=service.workflow_graph(target,revision)['value']
            ref=service.reference_workflow(target,revision,'samples')
            self.assertEqual(service.inspect_selection(ref['id'])['value']['payload']['operation'],example()['operations'][0])
            service.rewire_workflow(target,revision,view['edges'][0]['pointer'],'samples',0)
            self.fault('STALE_REVISION',lambda:service.execute(plan['id'],plan['revision']))
            with self.assertRaises(SchemaxisError):service.plan_draft(service.create_task('Wrong scope',['freecad'])['id'],0,target,service.authoring._record['revision'])

    def test_graph_bounds_are_progressive_without_truncation(self):
        doc=example();doc['operations']=[{**copy.deepcopy(doc['operations'][0]),'id':f'op{i}'} for i in range(80)]
        self.session._edit(doc)
        result=observe(self.session,*self.identity(),pointer='/nodes',max_bytes=2048,limit=5)
        self.assertEqual(result['mode'],'members');self.assertEqual(result['page']['nextOffset'],5)
        self.assertLessEqual(len(encoded(result)),2048)
        selected=observe(self.session,*self.identity(),pointer='/nodes/79',max_bytes=2048)
        self.assertEqual(selected['value']['id'],'op79')

    def test_console_actions_preserve_existing_document_and_busy_guard(self):
        app=ConsoleApplication(self.session)
        try:
            identity,revision=self.identity()
            app.author({'action':'workflow_example','document':identity,'revision':revision})
            self.assertIn(identity,self.session._state['documents'])
            self.assertNotEqual(self.session.active_document,identity)
            app.busy=True
            self.fault('SESSION_BUSY',lambda:app.author({'action':'workflow_rewire','document':self.session.active_document,'revision':self.session._record['revision']}))
        finally:app.close()

    def test_empty_workflow_can_be_saved_but_not_executed(self):
        self.session.new('Empty','workflow');self.assertEqual(graph(self.session,*self.identity())['nodes'],[])
        self.session.write_source(*self.identity(),str(self.root/'empty.json'))
        with ExecutionService(self.root/'agent') as service:
            draft=service.create_draft('workflow');task=service.create_task('Empty',['octave'])
            self.fault('EMPTY_WORKFLOW',lambda:service.plan_draft(task['id'],0,draft['document'],draft['revision']))
