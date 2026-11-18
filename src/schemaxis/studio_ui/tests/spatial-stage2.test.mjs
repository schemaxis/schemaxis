// Copyright (C) 2026 David L. F. Gaden.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spatialRequest, previewSpatial} from '../windows/spatial/host.mjs';
import {spatialSession} from '../windows/spatial/session.mjs';
import {entryOverlays, spatialEntries, recordRows, snapshotRows} from '../windows/spatial/model.mjs';

const box = {min: [0, 0, 0], max: [2, 2, 0]};
const root = () => ({version: 'schemaxis/1', definitions: {floor: box, model: {$expr: 'extents(body)'}},
  nodes: [{id: 'body', filter: 'sphere'}, {id: 'unfinished', options: {$fill: 'later'}}], publications: [{$fill: 'later'}]});
const record = (key, extra = {}) => ({entry: {scope: 'document', section: 'definitions', key},
  type: 'box', phase: 'observed', dependsOn: {entries: [], nodes: [{node: 'body', port: 0}], sweeps: [], awaits: []},
  state: 'unresolved', reason: 'needs-data', ...extra});
const resolved = (key, kind = 'live') => {
  const result = record(key, {state: 'resolved', value: box, valid: true, phase: kind === 'literal' || kind === 'constant' ? 'constant' : 'observed',
    source: {kind, inputDigest: 'digest', state: {timeIndex: 0, indices: {}}}});
  delete result.reason; return result;
};

// This stub implements only Appendix A responses, without parsing or native execution.
function host() {
  const calls = [];
  return {calls, async post(path, request) {
    calls.push({path, request});
    if (path === '/api/cancel') return {};
    assert.equal(path, '/api/spatial');
    const common = {inputDigest: 'digest', draft: request.draft, capabilities: {extents: true}};
    if (request.action === 'spatial_check') return {...common, ok: true, type: 'box', phase: 'observed', dependsOn: record('model').dependsOn};
    if (request.action === 'spatial_list') return {...common, entries: [resolved('floor', 'literal'), record('model')],
      sweeps: [], states: 1, functions: [{name: 'union', kind: 'builtin', parameters: [], result: 'box'}]};
    if (request.action === 'spatial_eval') return {...common, records: request.entries
      ? [resolved(request.entries[0].key, 'constant')] : [resolved('floor', 'literal'), record('model')]};
    if (request.action === 'spatial_load') { this.loaded = {...common, observations: {inputDigest: 'digest',
      state: request.state, extents: [{node: 'body', port: 0, status: 'ok', bounds: [0, 2, 0, 2, 0, 0]}]},
      records: [resolved('floor', 'literal'), resolved('model')]}; return {job: 'load-1', status: 'running'}; }
    throw Error('Unexpected action');
  }, async waitForJob(job) { assert.equal(job, 'load-1'); return {status: 'succeeded', result: this.loaded}; }};
}

test('Appendix A requests retain incomplete whole workflows and selected namespace', () => {
  const document = {version: 'schemaxis.workflow-design/2', workflow: {version: 'schemaxis.workflow/1',
    definitions: {floor: box}, operations: [{id: 'render', document: root()}]}};
  assert.deepEqual(spatialRequest(document, '/workflow/operations/0/document', {revision: 2}),
    {input: document.workflow, operation: 'render', draft: {revision: 2}});
  const rows = spatialEntries(document);
  assert.equal(rows.length, 3, 'Workbench default includes operation entries and the envelope');
  assert.equal(new Set(entryOverlays(rows).map(item => item.id)).size, 2);
  const records = [resolved('floor', 'literal'), {...resolved('floor'), operation: 'render'}];
  records[0].entry.scope = 'workflow';
  assert.equal(new Set(recordRows(document, records).map(row => row.pointer)).size, 2);
});

test('D21/D22 host list, eval, check and one job-based load keep unresolved entries undrawn', async () => {
  const api = host(), document = root();
  const session = spatialSession(api, {root: document, revision: 7});
  await session.refresh();
  assert.equal(session.functions[0].name, 'union');
  assert.equal(session.capabilities.extents, true);
  assert.equal(entryOverlays(session.rows).length, 1);
  assert.equal((await session.check('extents(body)', '/definitions/model')).ok, true);
  await session.load();
  assert.equal(entryOverlays(session.rows).length, 2);
  assert.equal(session.rows[1].draft.revision, 7);
  const load = api.calls.find(c => c.request.action === 'spatial_load').request;
  assert.deepEqual(load.input, document, 'incomplete nodes and publications pass unchanged for host pruning');
  assert.equal(load.entries, undefined, 'one action defaults to every spatial dependency');
  await session.refresh();
  assert.deepEqual(api.calls.at(-1).request.observations, api.loaded.observations, 'observations return unchanged');
  const revised = root(); revised.definitions.new = 2;
  session.edit(revised);
  assert.equal(session.rows, null);
  await session.refresh();
  assert.equal(api.calls.at(-1).request.observations, undefined);
  assert.equal(session.draft.revision, 8);
});

test('late load responses are discarded after edits; cancellation targets the existing job', async () => {
  const api = host(); let release;
  api.waitForJob = () => new Promise(resolve => { release = () => resolve({status: 'succeeded', result: api.loaded}); });
  const session = spatialSession(api, {root: root()});
  const loading = session.load(); await Promise.resolve();
  assert.equal(session.busy, true);
  await session.load();
  assert.equal(api.calls.filter(c => c.request.action === 'spatial_load').length, 1);
  await session.cancel(); assert.deepEqual(api.calls.at(-1), {path: '/api/cancel', request: {job: 'load-1'}});
  session.edit(root()); release(); await loading;
  assert.equal(session.rows, null); assert.equal(session.busy, false);
});

test('fault, stale-data and invalid records never produce guessed boxes', () => {
  const records = [record('model', {reason: 'stale-data'}), record('floor', {state: 'fault', fault: {code: 'FAILED'}})];
  assert.deepEqual(entryOverlays(recordRows(root(), records)), []);
  assert.deepEqual(entryOverlays(recordRows(root(), [resolved('model')].map(r => ({...r, valid: false})))), []);
});

test('old Variables marker previews use host eval without a second expression evaluator', async () => {
  const api = host(), document = root(), expression = {$expr: {op: 'multiply', args: [2, 3]}};
  await previewSpatial(api, document, expression);
  const request = api.calls[0].request;
  assert.equal(request.action, 'spatial_eval');
  assert.deepEqual(request.input.definitions._studioPreview, expression);
  assert.deepEqual(request.entries, [{scope: 'document', section: 'definitions', key: '_studioPreview'}]);
  assert.equal(document.definitions._studioPreview, undefined);
});

test('a verified run record stays labelled with its captured revision and disappears on edit', async () => {
  const document = root(), api = host();
  const spatial = {root: structuredClone(document), draft: {identity: 'doc', revision: 12},
    response: {inputDigest: 'digest', records: [resolved('model', 'run')]}};
  const session = spatialSession(api, {root: document, identity: 'doc', revision: 13, spatial});
  await session.refresh();
  const model = session.rows.find(row => row.name === 'model');
  assert.equal(model.record.source.kind, 'run');
  assert.equal(model.draft.revision, 12);
  assert.equal(entryOverlays(session.rows).length, 2);
  const changed = root(); changed.nodes[0].options = {radius: 5};
  session.edit(changed); await session.refresh();
  assert.equal(entryOverlays(session.rows).length, 1);
});

test('mismatched digests and unknown entry types never become drawable records', () => {
  assert.deepEqual(entryOverlays(recordRows(root(), [resolved('model')], {revision: 9}, 'different')), []);
  assert.deepEqual(recordRows(root(), [record('model', {type: 'unknown'})]), []);
});

test('cancel requested before the load job starts is delivered when its identity arrives', async () => {
  const api = host(), original = api.post.bind(api); let release;
  api.post = async (path, request) => {
    const result = await original(path, request);
    return request.action === 'spatial_load' ? new Promise(resolve => { release = () => resolve(result); }) : result;
  };
  const session = spatialSession(api, {root: root()});
  const loading = session.load(); await Promise.resolve(); await Promise.resolve();
  await session.cancel(); release(); await loading;
  assert.deepEqual(api.calls.at(-1), {path: '/api/cancel', request: {job: 'load-1'}});
  assert.equal(session.rows, null);
});

test('an old scope reply cannot overwrite a newer scope and disposed sessions ignore replies', async () => {
  const api = host(), original = api.post.bind(api), pending = [];
  api.post = async (path, request) => {
    const response = await original(path, request);
    return request.action === 'spatial_list' ? new Promise(resolve => pending.push(() => resolve(response))) : response;
  };
  const session = spatialSession(api, {root: root()});
  const first = session.refresh(); await Promise.resolve(); await Promise.resolve();
  session.edit(root(), '/other');
  pending.shift()(); await first;
  assert.equal(session.rows, null);
  const second = session.refresh(); await Promise.resolve(); await Promise.resolve();
  session.dispose(); pending.shift()(); await second;
  assert.equal(session.rows, null);
});

test('ad-hoc and legacy numeric previews forward destination checks to the host', async () => {
  const calls = [], api = {post: async (path, request) => {
    calls.push(request); return {records: [resolved('preview', 'constant')]};
  }};
  const document = root();
  await previewSpatial(api, document, {$expr: 'model'}, '', {destination: '/nodes/0/options/bounds'});
  assert.equal(calls[0].expression, 'model'); assert.equal(calls[0].destination, '/nodes/0/options/bounds');
  await previewSpatial(api, document, {$value: 'boundsFromExtents', args: {extents: [0,2,0,2,0,0]}}, '', {destination: '/nodes/0/options/bounds'});
  assert.equal(calls[1].expression, 'definitions._studioPreview');
  assert.deepEqual(calls[1].input.definitions._studioPreview, {$value: 'boundsFromExtents', args: {extents: [0,2,0,2,0,0]}});
  assert.equal(document.definitions._studioPreview, undefined);
});

test('operation observations retain other workflow literals and unresolved records override literals', () => {
  const document = {version: 'schemaxis.workflow/1', definitions: {floor: box},
    operations: [{id: 'first', document: root()}, {id: 'second', document: root()}]};
  const snapshot = {root: structuredClone(document), draft: {revision: 3}, response: {inputDigest: 'digest', records: [
    {...resolved('model'), operation: 'first'}, {...record('floor'), operation: 'first'},
  ]}};
  const rows = snapshotRows(document, snapshot), overlays = entryOverlays(rows);
  assert.equal(overlays.length, 3, 'envelope floor, first model and second floor');
  assert.equal(rows.find(row => row.operation === 'first' && row.name === 'floor').literal.state, 'unresolved');
  assert.equal(rows.find(row => row.operation === 'second' && row.name === 'model').literal.state, 'unresolved');
  document.definitions.extra = 4;
  assert.equal(snapshotRows(document, snapshot), null);
});

test('failed live jobs cannot publish even if a partial result is attached', async () => {
  const api = host(); api.waitForJob = async () => ({status: 'failed', result: api.loaded, fault: {message: 'Cancelled'}});
  const session = spatialSession(api, {root: root()});
  await assert.rejects(session.load(), /Cancelled/);
  assert.equal(session.rows, null); assert.equal(session.busy, false);
});

test('Workbench captures the input and draft at run dispatch, not when the run finishes', async () => {
  const {createActions} = await import('../windows/workbench/actions.mjs');
  const original = root(); let document = structuredClone(original), revision = 6, finish;
  const state = {record: {id: 'doc', revision: 3, document: original, source: JSON.stringify(original)},
    value: original, provider: 'fixture', metadata: {viewers: []}};
  const store = {get: () => state, set: patch => Object.assign(state, patch)};
  const editor = {flushDiagnostics: () => [], setDiagnostics: () => {}, getTextVersion: () => revision,
    getDocument: () => document, getValue: () => JSON.stringify(document), getOption: () => 'json'};
  const requests = [], ctx = {store: {get: () => ({server: {configured: ['fixture']}}), set: () => {}},
    refresh: async () => {}, notify: {ok: () => {}, group: () => assert.fail('Unexpected diagnostics')}, api: {
      post: async (path, request) => { requests.push({path, request});
        if (path === '/api/validate') return {valid: true, diagnostics: []};
        if (path === '/api/command') return {job: 'run-1'};
        throw Error('Unexpected request '+path);
      }, waitForJob: () => new Promise(resolve => { finish = resolve; }),
    }};
  const actions = createActions({ctx, store, editor, params: {document: 'doc'}, viewers: {}});
  const running = actions.run();
  for (let attempt = 0; !finish && attempt < 20; attempt++) await new Promise(resolve => setImmediate(resolve));
  assert.ok(finish, 'run reached the job wait');
  document.definitions.changed = 8; revision++;
  finish({status: 'succeeded', result: {spatial: {inputDigest: 'digest', records: [resolved('model', 'run')]}}});
  await running;
  assert.deepEqual(state.spatial.root, original);
  assert.deepEqual(state.spatial.draft, {identity: 'doc', revision: 6});
  assert.equal(snapshotRows(document, state.spatial), null, 'run results are not applied to edited input');
  assert.deepEqual(requests.at(-1), {path: '/api/command', request: {line: 'preview', document: 'doc', revision: 3}});
});


test('A-S2-02 untyped host faults remain repairable rows and are never drawn', () => {
  const document = root(); document.definitions.text = 'not spatial';
  const records = ['EXPR_SYNTAX', 'EXPR_UNKNOWN_NAME', 'EXPR_CYCLE', 'EXPR_ARGUMENTS'].map((code, i) => {
    const key = `bad${i}`; document.definitions[key] = {$expr: 'broken('};
    return {entry: {scope: 'document', section: 'definitions', key}, state: 'fault', fault: {code, message: code}};
  });
  records.push({entry: {scope: 'document', section: 'definitions', key: 'text'}, type: 'text', state: 'resolved', value: 'not spatial'});
  const rows = recordRows(document, records);
  assert.equal(rows.length, 4);
  assert.ok(rows.every(row => row.literal.type === 'unknown' && row.literal.reason.startsWith('EXPR_')));
  assert.deepEqual(entryOverlays(rows), []);
});

test('A-S2-03 captured first visits match omitted zero coordinates, never other visits', async () => {
  for (const [state, expected] of [[{timeIndex: 0, indices: {t: 0, sweep: 0}}, 'resolved'],
    [{timeIndex: 0, indices: {t: 1}}, 'unresolved'], [{timeIndex: 1, indices: {}}, 'unresolved'],
    [undefined, 'unresolved']]) {
    const document = root(), observed = resolved('model', 'run'); observed.source.state = state;
    const spatial = {root: document, draft: {revision: 12}, response: {inputDigest: 'digest', records: [observed]}};
    const session = spatialSession(host(), {root: document, revision: 13, spatial});
    await session.refresh();
    const row = session.rows.find(row => row.name === 'model');
    assert.equal(row.literal.state, expected);
    if (expected === 'resolved') assert.equal(row.draft.revision, 12);
  }
});

test('A-S2-07 grouped fill checks retain workflow scope, tentative sweeps and the unchanged original draft', async () => {
  const {bindVariables} = await import('../windows/variables/editor.mjs');
  const document = {version:'schemaxis.workflow-design/2', workflow:{version:'schemaxis.workflow/1', settings:{r:2},
    operations:[{id:'render',document:{version:'schemaxis/1',nodes:[{id:'a',filter:'sphere',options:{radius:{$fill:'r'}}},
      {id:'b',filter:'sphere',options:{radius:{$fill:'r'}}}]}}]}};
  const original = structuredClone(document), options = {}, calls = [];
  const editor = {setOption:(name,value)=>{options[name]=value;}};
  const fault = {ok:false,fault:{code:'EXPR_TYPE',message:'Wrong type'}};
  bindVariables({api:{post:async (path,request)=>{calls.push(request); return calls.length === 2 ? fault : {ok:true};}}},
    editor,{snapshot:async()=>({root:document,base:'/workflow/operations/0/document'})});
  const result = await options.checkSpatialValue({value:{$expr:'workflow.settings.r'},
    pointers:['/nodes/0/options/radius','/nodes/1/options/radius'],axis:{name:'t',values:[0,1]}});
  assert.equal(result,fault);
  assert.deepEqual(calls.map(request=>request.destination), ['/nodes/0/options/radius','/nodes/1/options/radius']);
  assert.ok(calls.every(request=>request.operation==='render' && request.input.version==='schemaxis.workflow/1'));
  assert.deepEqual(calls[0].input.operations[0].document.nodes.map(node=>node.options.radius),
    [{$expr:'workflow.settings.r'},{$expr:'workflow.settings.r'}]);
  assert.deepEqual(calls[0].input.operations[0].document.sweeps,[{name:'t',values:[0,1]}]);
  assert.deepEqual(document,original);
});

test('one-click data extents needs no authored entries and retains provenance for follow-up previews', async () => {
  const document={version:'schemaxis/1',nodes:[{id:'reader',filter:'foam',options:{file:'case.foam'}}]};
  const calls=[];
  const observation={inputDigest:'same',state:{timeIndex:0,indices:{}},extents:[{node:'reader',port:0,status:'ok',bounds:[0,10,0,20,0,30]}]};
  const value={expression:'dataExtents',type:'box',state:'resolved',valid:true,value:{min:[0,0,0],max:[10,20,30]}};
  const api={
    async post(path, request){calls.push({path,request});
      if(request.action==='spatial_load')return {job:'load'};
      if(request.action==='spatial_list')return {capabilities:{extents:true},entries:[]};
      if(request.action==='spatial_eval')return {records:request.expression
        ? [request.observations ? value : {expression:request.expression,type:'box',state:'unresolved',reason:'needs-data'}] : []};
      throw Error('unexpected '+path);
    },
    async waitForJob(){return {status:'succeeded',result:{inputDigest:'same',observations:observation,records:[value]}};}
  };
  const session=spatialSession(api,{root:document,includeDataExtents:true});
  await session.refresh();assert.equal(session.dataExtents.reason,'needs-data');
  await session.load('dataExtents');
  assert.deepEqual(session.dataExtents.value,value.value);
  const request=calls.find(c=>c.request.action==='spatial_load').request;
  assert.equal(request.expression,'dataExtents');assert.equal(request.input.definitions,undefined);
  assert.deepEqual(session.rows,[]);
  const retained=spatialSession(api,{root:document,spatial:session.snapshot,includeDataExtents:true});
  await retained.refresh();assert.deepEqual(retained.dataExtents.value,value.value);
  session.edit({...document,settings:{edited:1}});assert.equal(session.dataExtents,undefined);
  await session.refresh();assert.equal(session.dataExtents.reason,'needs-data');
});
