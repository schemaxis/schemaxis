# Copyright (C) 2026 David L. F. Gaden.
import copy
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.live_data import LiveDataSession
from schemaxis.live_data_worker import Worker
from schemaxis.spatial_rename import rename
from schemaxis.spatial_actions import spatial_check, spatial_eval
from schemaxis.pipeline import DefinitionGraph
from schemaxis.filters import catalogue
from test_spatial_actions import Backend


class FakeProcess:
    def __init__(self, provider, executable, directory, timeout):
        self.worker = Worker(provider)
        self.closed = False
        self.calls = 0
        self.backend = Backend({'ball':[{'status':'ok','bounds':[-1,1,-1,1,-1,1]}], 'other':[{'status':'ok','bounds':[0,2,0,2,0,2]}], 'skin':[{'status':'ok','bounds':[-1,1,-1,1,-1,1]}]})
    def request(self, command, **args):
        self.calls += 1
        with patch('schemaxis.live_data_worker.registry.binding', return_value=lambda d, **kw:(DefinitionGraph(d,catalogue()),self.backend)):
            return self.worker.dispatch(command, args)
    def request_retained(self, command, **args):
        # Synchronous in-process transport: exceptions never destroy the worker.
        return self.request(command, **args)

    def close(self):
        self.worker.close()
        self.closed = True


class LiveDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.live = LiveDataSession(self.temp.name, FakeProcess)
        self.addCleanup(self.live.close)
        self.doc = {'version':'schemaxis/1','nodes':[{'id':'ball','filter':'sphere'},{'id':'other','filter':'sphere'}]}
    def load(self, nodes):
        # Host planning is real. Only executable discovery and native execution are replaced.
        with patch('schemaxis.adaptors.paraview.integration.extentsSetup',
                   side_effect=lambda d,l:(DefinitionGraph(d,catalogue()),'/test/pvpython',[])):
            return self.live.load({'input':self.doc,'nodes':nodes})
    def test_retains_handles_observations_and_new_names_without_reloading(self):
        self.load(['ball'])
        client = next(iter(self.live.workers.values()))['client']
        handle = client.worker.active.handles['ball']
        self.load(['other'])
        self.assertIs(client.worker.active.handles['ball'], handle)
        self.assertEqual(set(client.worker.active.handles), {'ball','other'})
        self.doc['definitions']={'envelope':{'$expr':'inflate(extents(ball), 0.1)'}}
        record = self.live.evaluate({'input':self.doc,'expression':'envelope'})['records'][0]
        self.assertEqual(record['state'],'resolved')
        self.assertEqual(client.calls,3)  # First acquisition, then prepare + preserving transition.
        self.live.unload()
        self.assertTrue(client.closed)
        self.assertFalse(self.live.status()['enabled'])
        self.assertEqual(self.live.evaluate({'input':self.doc,'expression':'envelope'})['records'][0]['state'],'resolved')
        self.doc['nodes'][0]['options']={'radius':3}
        self.assertEqual(self.live.evaluate({'input':self.doc,'expression':'envelope'})['records'][0]['state'],'unresolved')
    def test_visit_and_upstream_changes_invalidate(self):
        self.load(['ball'])
        self.assertIsNone(self.live.observations({'input':self.doc,'state':{'timeIndex':1}}))
        changed=copy.deepcopy(self.doc);changed['nodes'][0]['options']={'radius':2}
        self.assertIsNone(self.live.observations({'input':changed}))
        self.assertIsNotNone(self.live.observations({'input':self.doc}))
    def test_distinct_sources_stay_resident_until_explicit_unload(self):
        self.load(['ball'])
        first = next(iter(self.live.workers.values()))['client']
        self.doc['nodes'][0]['options'] = {'radius': 2}
        self.load(['ball'])
        self.assertEqual(len(self.live.workers), 2)
        self.assertFalse(first.closed)
        self.live.unload()
        self.assertTrue(first.closed)
    def test_downstream_settings_reuse_upstream_native_handles(self):
        self.doc['nodes'][1] = {'id':'other','filter':'surface','inputs':{'input':'ball'}}
        self.load(['other'])
        client = next(iter(self.live.workers.values()))['client']
        ball = client.worker.active.handles['ball']
        self.doc['nodes'][1]['filter'] = 'triangulate'
        self.load(['other'])
        self.assertIs(client.worker.active.handles['ball'], ball)
        self.assertEqual(self.live.status()['sessions'][0]['lastLoad']['created'], ['other'])
    def refresh(self, **extra):
        missing_only = extra.pop('missing_only', False)
        with patch('schemaxis.adaptors.paraview.integration.extentsSetup',
                   side_effect=lambda d,l:(DefinitionGraph(d,catalogue()),'/test/pvpython',[])):
            return self.live.refresh({'input':self.doc, **extra}, missing_only=missing_only)

    def test_refresh_builds_derived_values_only_from_resident_sources(self):
        self.doc['nodes'].append({'id':'skin','filter':'surface','inputs':{'input':'ball'}})
        self.doc['definitions'] = {'region':{'$expr':'extents(skin)'}, 'unselected':{'$expr':'extents(other)'}}
        self.refresh()
        self.assertFalse(self.live.workers)  # Refresh never enables data itself.
        self.load(['ball'])
        client = next(iter(self.live.workers.values()))['client']
        ball = client.worker.active.handles['ball']
        result = self.refresh()
        self.assertEqual([r['state'] for r in result['records']], ['resolved','unresolved'])
        self.assertIs(client.worker.active.handles['ball'], ball)
        self.assertEqual(set(client.worker.active.handles), {'ball','skin'})
        self.assertEqual(self.live.status()['sessions'][0]['lastLoad']['updated'], ['skin'])
        count = client.calls
        self.refresh(missing_only=True)
        self.assertEqual(client.calls, count)
        self.doc['nodes'][0]['options'] = {'radius': 2}
        self.assertEqual(self.refresh()['records'][0]['state'], 'unresolved')
        self.assertEqual(len(self.live.workers), 1)
        self.assertIs(client.worker.active.handles['ball'], ball)

    def test_refresh_after_unload_keeps_cache_without_restarting(self):
        self.load(['ball'])
        self.live.unload()
        result = self.refresh(expression='extents(ball)')
        self.assertEqual(result['records'][0]['state'], 'resolved')
        self.assertFalse(self.live.workers)

    def test_memory_is_not_saved_across_sessions(self):
        self.load(['ball'])
        self.live.close()
        fresh = LiveDataSession(self.temp.name, FakeProcess)
        self.addCleanup(fresh.close)
        self.assertFalse(fresh.status()['enabled'])
        self.assertIsNone(fresh.observations({'input':self.doc}))
    def test_inspection_keeps_authored_recipe_for_shared_observations(self):
        from schemaxis.adaptors.paraview.studio import inspect_input
        from unittest.mock import Mock
        document = {'version':'schemaxis/1','definitions':{'radius':2},
                    'nodes':[{'id':'ball','filter':'sphere','options':{'radius':{'$document':'/definitions/radius'}}}]}
        live = Mock()
        live.inspect.return_value = {'node':'ball'}
        inspect_input(document, 'ball', '/test/pvpython', self.temp.name, live_data=live)
        self.assertEqual(live.inspect.call_args.args[0]['input'], document)

    def test_deferred_template_and_cycles_are_core_checks(self):
        self.doc['definitions']={'bounds':{'$expr':'extents(ball)'},'bigger':{'$expr':'inflate(bounds, 0.1)'}}
        result=spatial_check({'input':self.doc,'expression':'bigger'})
        self.assertTrue(result['ok']);self.assertEqual(result['type'],'box')
        self.assertEqual(result['dependsOn']['nodes'],[{'node':'ball','port':0}])
        self.doc['definitions']['bounds']={'$expr':'bigger'}
        self.assertFalse(spatial_check({'input':self.doc,'expression':'bigger'})['ok'])


class RenameTests(unittest.TestCase):
    def test_bindings_and_references_not_strings(self):
        doc={'version':'schemaxis/1','nodes':[],'definitions':{'old':[0,1,0,1,0,1],
             'use':{'$expr':'old.mid + definitions.old.size'},'ref':{'$document':'/definitions/old'},'label':'old'}}
        result=rename({'input':doc,'section':'definitions','name':'old','newName':'new-box'})['input']
        self.assertEqual(result['definitions']['label'],'old')
        self.assertEqual(result['definitions']['ref']['$document'],'/definitions/new-box')
        self.assertEqual(spatial_eval({'input':result,'expression':'use'})['records'][0]['value'],[1.5,1.5,1.5])
        self.assertIn('old',doc['definitions'])
    def test_workflow_shadowing(self):
        doc={'version':'schemaxis.workflow/1','definitions':{'old':1},'operations':[
            {'id':'a','document':{'version':'schemaxis/1','nodes':[],'definitions':{'old':2,
              'local':{'$expr':'old'},'shared':{'$expr':'workflow.definitions.old'}}}}]}
        result=rename({'input':doc,'section':'definitions','name':'old','newName':'shared'})['input']
        values=result['operations'][0]['document']['definitions']
        self.assertEqual(values['local']['$expr'],'old')
        self.assertEqual(values['shared']['$expr'],'workflow.definitions.`shared`')

class ServiceTests(unittest.TestCase):
    def test_agent_session_routes_and_strict_admission(self):
        from schemaxis.execution_service import ExecutionService
        from schemaxis.mcp import McpDispatcher
        from schemaxis.core.faults import SchemaxisError
        with tempfile.TemporaryDirectory() as directory, ExecutionService(directory) as service:
            document={'version':'schemaxis/1','nodes':[]}
            self.assertFalse(service.spatial('live_data_status', document)['enabled'])
            self.assertEqual(service.spatial('live_data_list', document)['nodes'], [])
            with patch.object(service.live_data, 'load', return_value={'loaded':True}) as load:
                self.assertEqual(service.spatial('live_data_load',document,nodes=['mesh']), {'loaded':True})
                self.assertEqual(load.call_args.args[0]['nodes'], ['mesh'])
            with patch.object(service.live_data, 'refresh', return_value={'refreshed':True}) as refresh:
                self.assertEqual(service.spatial('live_data_refresh',document,nodes=['mesh']), {'refreshed':True})
                self.assertEqual(refresh.call_args.args[0]['nodes'], ['mesh'])
            dispatcher=McpDispatcher(service)
            for action in ('spatial_load','live_data_load','live_data_refresh','live_data_list','live_data_status','live_data_unload'):
                with self.assertRaises(SchemaxisError) as error:
                    dispatcher._admit('spatial',{'action':action,'input':document})
                self.assertEqual(error.exception.fault.code,'MCP_POLICY_DENIED')
            self.assertFalse(service.spatial('live_data_unload',document)['enabled'])

class ConsoleRefreshTests(unittest.TestCase):
    def test_console_refresh_and_cached_evaluation(self):
        from schemaxis.console_session import AdaptorConsoleSession
        with tempfile.TemporaryDirectory() as directory, AdaptorConsoleSession(directory, provider='paraview') as session:
            with patch.object(session.live_data, 'refresh', return_value={'refreshed':True}) as refresh:
                self.assertEqual(session.execute('data refresh'), {'refreshed':True})
                self.assertNotIn('nodes', refresh.call_args.args[0])
                session.execute('data refresh mesh')
                self.assertEqual(refresh.call_args.args[0]['nodes'], ['mesh'])
                session.execute('data eval "extents(mesh)"')
                self.assertTrue(refresh.call_args.kwargs['missing_only'])
            with patch.object(session.live_data, 'evaluate', return_value={'cached':True}) as evaluate:
                self.assertEqual(session.execute('data eval "extents(mesh)" --cached'), {'cached':True})
                self.assertEqual(evaluate.call_args.args[0]['expression'], 'extents(mesh)')
