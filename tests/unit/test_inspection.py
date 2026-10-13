import copy
import json
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.resource_inspection import InspectionStore, BUDGET
from schemaxis.console_references import ReferenceStore
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.console_server import ConsoleApplication
from schemaxis.execution_service import ExecutionService
from schemaxis.core.faults import SchemaxisError
from schemaxis.storage import encoded, atomic, AtomicPublicationError
from schemaxis.agent_transport import dispatch


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=InspectionStore(self.root)

    def fault(self, code, action):
        with self.assertRaises(SchemaxisError) as caught: action()
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def capture(self, data='x,y\n0,1\n1,2\n2,4\n3,8\n', kind='table'):
        return self.store.capture_bytes(data.encode(),kind,'Test',{'kind':'test-fixture'})

    def test_exact_text_paging_and_utf8_selection_survive_restart(self):
        source='heading\r\né 😀\nlast'
        resource=self.capture(source,'text')
        result=self.store.inspect(resource['id'],resource['revision'],'text',offset=9,limit=3)
        self.assertEqual(result['text'],source[9:12])
        self.assertEqual(result['byteStart'],len(source[:9].encode()))
        self.assertEqual(result['line'],2)
        ref=self.store.reference(resource['id'],resource['revision'],'text-span',{'start':9,'end':12})
        self.assertEqual(ref['payload']['byteEnd'],len(source[:12].encode()))
        restored=InspectionStore(self.root)
        evidence=restored.inspect_reference(ref['id'])['value']
        self.assertEqual(evidence['evidence'],source[9:12])
        self.assertFalse(evidence['stale'])
        self.assertFalse(ref['replayable'])

    def test_replacement_marks_history_stale_but_preserves_old_evidence(self):
        r=self.capture('old text','text')
        ref=self.store.reference(r['id'],r['revision'],'text-span',{'start':0,'end':3})
        new=self.store.capture_bytes(b'new text','text','Changed',{'kind':'test-fixture'},r['id'],r['revision'])
        self.assertNotEqual(new['revision'],r['revision'])
        self.assertTrue(self.store.references.list(None,None,self.store.revisions())[0]['stale'])
        self.assertEqual(self.store.inspect_reference(ref['id'])['value']['evidence'],'old')
        self.assertTrue(self.store.inspect_reference(ref['id'])['value']['stale'])
        self.fault('STALE_REFERENCE',lambda:self.store.reference(r['id'],r['revision'],'text-span',{'start':0,'end':3}))
        self.fault('STALE_RESOURCE',lambda:self.store.capture_bytes(b'other','text','Changed',{},r['id'],r['revision']))
        self.fault('STALE_REFERENCE',lambda:self.store.check_references({ref['id']}))
        self.fault('STALE_REFERENCE',lambda:self.store.references.message([{'reference':ref['id']}],'doc',1,resource_revisions=self.store.revisions()))

    def test_text_table_and_native_references_have_distinct_common_envelopes(self):
        r=self.capture('text','text')
        text=self.store.reference(r['id'],r['revision'],'text-span',{'start':0,'end':4})
        geometry={'revision':2,'units':'mm','objects':[{'id':'body','faces':[],
            'vertices':[{'id':'Vertex1','point':[0,0,0]}]}]}
        native=self.store.references.register({'revision':2,'object':'body','subelement':'Vertex1','point':[0,0,0]},'doc',geometry)
        for ref in (text,native):
            self.assertEqual(ref['version'],'schemaxis.reference/1')
            self.assertIn('target',ref)
            self.assertIn('payload',ref)
            self.assertIn('provenance',ref)
            self.assertFalse(ref['replayable'])
        self.assertNotIn('point',text['payload'])
        self.assertEqual(native['kind'],'native-subelement')
        message=self.store.references.message([{'reference':text['id']},{'reference':native['id']}],'doc',2,resource_revisions=self.store.revisions())
        self.assertEqual(len(message['segments']),2)
        self.assertFalse(message['executed'])
        refs=self.store.references.list('doc',3,self.store.revisions())
        self.assertFalse(refs[0]['stale'])
        self.assertTrue(refs[1]['stale'])

    def test_csv_preserves_strings_empty_cells_and_quoted_newlines(self):
        r=self.capture('x,note,missing\r\n01,"a\nb",\r\n')
        view=self.store.inspect(r['id'],r['revision'],'table')
        self.assertEqual(view['rows'][0]['values'],['01','a\nb',''])
        self.assertEqual(view['valueType'],'string')
        ref=self.store.reference(r['id'],r['revision'],'table-range',{'rowStart':0,'rowEnd':1,'columnStart':1,'columnEnd':3})
        observed=self.store.inspect_reference(ref['id'])['value']['evidence']
        self.assertEqual(observed['columns'],['note','missing'])
        self.assertEqual(observed['rows'],[['a\nb','']])

    def test_series_explicit_mapping_domain_and_interval(self):
        r=self.capture()
        self.fault('INVALID_COLUMNS',lambda:self.store.inspect(r['id'],r['revision'],'series'))
        view=self.store.inspect(r['id'],r['revision'],'series',1,2,x_column=0,y_column=1)
        self.assertEqual(view['points'],[{'row':1,'x':1.0,'y':2.0},{'row':2,'x':2.0,'y':4.0}])
        self.assertEqual(view['nextOffset'],3)
        ref=self.store.reference(r['id'],r['revision'],'series-interval',{'rowStart':1,'rowEnd':3,'xColumn':0,'yColumn':1})
        self.assertEqual(ref['payload']['domain'],[1.0,2.0])
        self.assertEqual(ref['payload']['axisUnits'],{'x':'unknown','y':'unknown'})
        self.assertEqual(self.store.inspect_reference(ref['id'])['value']['evidence']['points'],[[1.0,2.0],[2.0,4.0]])

    def test_bad_numeric_values_and_unordered_domains_do_not_get_silently_fixed(self):
        for token in ('','NaN','inf','1e999','12px','1,234'):
            r=self.capture('x,y\n0,"'+token+'"\n')
            self.fault('NON_NUMERIC_SERIES',lambda:self.store.inspect(r['id'],r['revision'],'series',x_column=0,y_column=1))
        for data in ('x,y\n1,2\n0,3\n','x,y\n0,2\n0,3\n'):
            r=self.capture(data)
            self.fault('UNSUPPORTED_DOMAIN',lambda:self.store.inspect(r['id'],r['revision'],'series',x_column=0,y_column=1))

    def test_malformed_csv_and_invalid_utf8_are_explicit(self):
        for data in ('','a,a\n1,2\n','a,b\n1\n','a,\n1,2\n','a,b\n1,"unfinished'):
            self.fault('INVALID_TABLE',lambda:self.capture(data))
        self.fault('INVALID_ENCODING',lambda:self.store.capture_bytes(b'\xff','text','bad',{}))
        self.fault('INSPECTION_LIMIT',lambda:self.capture('x'*(1024*1024+1),'text'))
        self.assertEqual(self.store.resources()['value'],[])

    def test_selection_bounds_and_kind_mismatch(self):
        text=self.capture('abc','text');table=self.capture()
        for payload in ({'start':-1,'end':2},{'start':1,'end':1},{'start':0,'end':4},{'start':True,'end':2}):
            self.fault('INVALID_SELECTION',lambda:self.store.reference(text['id'],text['revision'],'text-span',payload))
        self.fault('TYPE_MISMATCH',lambda:self.store.reference(table['id'],table['revision'],'text-span',{'start':0,'end':1}))
        self.fault('TYPE_MISMATCH',lambda:self.store.inspect(text['id'],text['revision'],'table'))
        self.fault('UNSUPPORTED_SELECTION',lambda:self.store.reference(text['id'],text['revision'],'native-subelement',{}))
        self.fault('INVALID_SELECTION',lambda:self.store.reference(table['id'],table['revision'],'table-range',{'rowStart':0,'rowEnd':9,'columnStart':0,'columnEnd':1}))
        self.assertEqual(self.store.references.data['references'],[])

    def test_snapshot_tampering_blocks_inspection_and_message_validation(self):
        r=self.capture('sample','text');ref=self.store.reference(r['id'],r['revision'],'text-span',{'start':0,'end':3})
        meta=self.store.state['resources'][r['id']]['snapshots'][r['revision']]
        (self.store.root/'blobs'/meta['sha256']).write_text('changed')
        self.fault('RESOURCE_CHANGED',lambda:self.store.inspect(r['id'],r['revision'],'text'))
        self.fault('RESOURCE_CHANGED',lambda:self.store.inspect_reference(ref['id']))
        self.fault('RESOURCE_CHANGED',lambda:self.store.check_references({ref['id']}))

    def test_bounded_text_and_table_pages_reconstruct_without_truncation(self):
        text='😀'*40000;r=self.capture(text,'text');offset=0;parts=[]
        while offset is not None:
            view=self.store.inspect(r['id'],r['revision'],'text',offset,16384)
            self.assertLessEqual(len(encoded(view)),BUDGET)
            parts.append(view['text']);offset=view['nextOffset']
        self.assertEqual(''.join(parts),text)
        r=self.capture('x,y\n'+''.join(f'{i},'+('a'*1500)+'\n' for i in range(80)))
        view=self.store.inspect(r['id'],r['revision'],'table',limit=100)
        self.assertLessEqual(len(encoded(view)),BUDGET)
        self.assertLess(len(view['rows']),80)
        self.assertEqual(view['nextOffset'],len(view['rows']))

    def test_complete_headers_are_never_silently_truncated(self):
        header=','.join(str(i)+'😀'*240 for i in range(128))
        r=self.capture(header+'\n'+','.join('1' for _ in range(128))+'\n')
        self.fault('OBSERVATION_TOO_LARGE',lambda:self.store.inspect(r['id'],r['revision'],'table'))
        self.fault('OBSERVATION_TOO_LARGE',lambda:self.store.inspect(r['id'],r['revision'],'series',x_column=0,y_column=1))

    def test_workspace_changes_preserve_invalid_source_history_jobs_and_references(self):
        with patch('schemaxis.configuration.load',return_value={'version':1,'locations':{}}):
            with ExecutionService(self.root/'agent') as service:
                draft=service.create_draft('freecad')
                draft=service.edit_draft(draft['document'],draft['revision'],'{unfinished')
                task=service.create_task('No native work',['freecad'])
                plan=service.plan(task['id'],{'version':'schemaxis.freecad/1','nodes':[{'id':'body','filter':'box'}],'output':'body'},0)
                state=copy.deepcopy(service.state);authored=copy.deepcopy(service.authoring._state)
                path=self.root/'fixture.txt';path.write_text('fixture')
                resource=service.capture_inspection(str(path),'text')
                ref=service.reference_snapshot(resource['id'],resource['revision'],'text-span',{'start':0,'end':4})
                for preset in ('text-inspection','table-analysis','geometry-study'):
                    service.inspection_workspace(preset,resource['id'])
                    self.assertEqual(service.state,state)
                    self.assertEqual(service.authoring._state,authored)
                    self.assertFalse(service.selections()['value'][0]['stale'])
                self.fault('UNKNOWN_WORKSPACE',lambda:service.inspection_workspace('https://untrusted/panel.js'))
                result=dispatch(service,{'id':1,'method':'inspect_selection','params':{'reference_id':ref['id']}})
                self.assertEqual(result['value']['evidence'],'fixt')

    def test_agent_console_share_inspection_state_on_reopen(self):
        path=self.root/'fixture.csv';path.write_text('x,y\n0,2\n1,4\n')
        with ExecutionService(self.root/'agent') as service:
            r=service.capture_inspection(str(path),'table')
            service.inspection_workspace('table-analysis',r['id'])
        with AdaptorConsoleSession(self.root/'agent'/'authoring') as session:
            app=ConsoleApplication(session)
            try:
                view=app.inspect_evidence({'action':'inspect','params':{'resource_id':r['id'],'revision':r['revision'],'view':'table'}})
                self.assertEqual(view['rows'][1]['values'],['1','4'])
                self.assertEqual(app.state()['presentation']['preset'],'table-analysis')
            finally:app.close()

    def test_demo_is_labelled_and_idempotent(self):
        first=self.store.demo();second=self.store.demo()
        self.assertEqual([r['id'] for r in first],[r['id'] for r in second])
        self.assertTrue(all(r['provenance']['kind']=='synthetic' for r in first))
        self.assertIn('not extraction output',self.store.inspect(first[0]['id'],first[0]['revision'],'text',limit=100)['text'])

    def test_capture_does_not_watch_external_changes(self):
        path=self.root/'log.txt';path.write_text('before')
        r=self.store.capture(path,'text');path.write_text('after')
        self.assertEqual(self.store.inspect(r['id'],r['revision'],'text')['text'],'before')
        changed=self.store.capture(path,'text',r['id'],r['revision'])
        self.assertNotEqual(changed['revision'],r['revision'])

    def test_uncertain_publication_reconciles_and_unpublished_failure_leaves_state(self):
        initial=copy.deepcopy(self.store.state)
        with patch('schemaxis.resource_inspection.atomic',side_effect=OSError('full disk')):
            with self.assertRaises(OSError):self.capture('test','text')
        self.assertEqual(self.store.state,initial)
        def uncertain(path,payload,**kwargs):
            atomic(path,payload,**kwargs)
            if path.name=='state.json':raise AtomicPublicationError(path,OSError('sync failed'))
        with patch('schemaxis.resource_inspection.atomic',side_effect=uncertain):
            with self.assertRaises(AtomicPublicationError):self.capture('published','text')
        self.assertEqual(len(self.store.state['resources']),1)
        self.assertEqual(InspectionStore(self.root).state,self.store.state)

    def test_existing_native_inspection_dispatch_remains_available(self):
        from schemaxis.inspection import inspect, execute_native
        self.assertTrue(callable(execute_native))
        document={'version':'example/1'}
        def native_observation(*args, **kwargs):
            directory = Path(args[2])
            directory.mkdir()
            (directory/'inspection.json').write_text('{"scope":"native observation"}')
            return {'scope':'native observation'}
        with patch('schemaxis.inspection.resolve'), patch('schemaxis.inspection.route_hook') as route:
            route.return_value.side_effect=native_observation
            self.assertEqual(inspect(document,'body',self.root/'native',locations={}),{'scope':'native observation'})
            self.assertTrue((self.root/'native'/'inspection.json.metadata.json').is_file())
            route.assert_called_once_with(document,'inspect')
            self.assertEqual(route.return_value.call_args.args,(document,'body',self.root/'native'))

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for browser offset mapping')
    def test_browser_normalised_offsets_resolve_exact_snapshot_spans(self):
        module=Path(__file__).resolve().parents[2]/'src/schemaxis/studio_ui/viewers/text-offsets.mjs'
        script=r"""
import {snapshotOffset,domOffset} from %s;
import assert from 'node:assert/strict';
const source='heading\\r\\né 😀\\r\\nlast'.replaceAll('\\r','\r').replaceAll('\\n','\n');
const dom=source.replaceAll('\r\n','\n').replaceAll('\r','\n');
for(const pick of ['heading','é 😀','😀','last',dom]){
  const start=dom.indexOf(pick),end=start+pick.length;
  assert.equal(domOffset(source,snapshotOffset(source,start)),start);
  assert.equal(domOffset(source,snapshotOffset(source,end)),end);
  const span=Array.from(source).slice(snapshotOffset(source,start),snapshotOffset(source,end)).join('');
  assert.equal(span.replaceAll('\r\n','\n').replaceAll('\r','\n'),pick);
}
assert.equal(snapshotOffset('a\rb',2),2);
""" % json.dumps(module.as_uri())
        # Keep JavaScript escapes intact in the Python string passed to Node.
        subprocess.run(['node','--input-type=module','-e',script],check=True,capture_output=True,text=True)
