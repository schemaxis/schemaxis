// Copyright (C) 2026 David L. F. Gaden.
import test from 'node:test';
import assert from 'node:assert/strict';
import {stubSpatialHost} from './fixtures/spatial-host-browser.mjs';
import {launch} from './harness.mjs';

async function input(session, label, value) {
  await session.evaluate(`(() => {
    const field = [...document.querySelectorAll('.dialog [aria-label]')].find(e => e.getAttribute('aria-label') === ${JSON.stringify(label)});
    if (!field) throw Error('Missing field '+${JSON.stringify(label)});
    field.value = ${JSON.stringify(value)}; field.dispatchEvent(new Event('input',{bubbles:true})); field.dispatchEvent(new Event('change',{bubbles:true}));
  })()`);
}
async function button(session, text) {
  await session.evaluate(`(() => {
    const control = [...document.querySelectorAll('.dialog button')].find(e => e.textContent === ${JSON.stringify(text)});
    if (!control) throw Error('Missing button '+${JSON.stringify(text)}); control.click();
  })()`);
}
async function setup(session) {
  await session.wait('window.studio?.store.get().server', 'Studio');
  await stubSpatialHost(session, {live:true, expressions: {
    'extents(body)': {type:'box',phase:'observed',value:{min:[0,0,0],max:[4,2,0]},dependsOn:{entries:[],nodes:[{node:'body',port:0}],sweeps:[],awaits:[]}},
    'missingData': {type:'box',phase:'observed',unresolved:true},
    'extents(body).inflate(0.1)': {type:'box',phase:'observed',value:{min:[-0.2,-0.1,0],max:[4.2,2.1,0]}},
    'gap / 2': {type:'scalar',value:2}, 'model.mid': {type:'vector',value:[2,1,0]},
    'model': {type:'box',phase:'observed',value:{min:[0,0,0],max:[4,2,0]}},
    'bad(': {type:'box',fault:{code:'EXPR_SYNTAX',message:'Expected closing parenthesis'}}
  }});
}

test('Spatial loads an incomplete draft once, labels observed boxes, preserves expressions and clears data after edits (stub)', {timeout: 120000}, async () => {
  const session = await launch();
  try {
    await setup(session);
    await session.evaluate(`studio.store.set({settings:{...studio.store.get().settings,values:{...studio.store.get().settings.values,'spatial.autoRefresh':false}}})`);
    await session.evaluate(`(async () => {
      const {manageSpatial} = await import('/windows/spatial/panel.mjs');
      window.spatialRoot = {version:'schemaxis/1',definitions:{floor:[0,2,0,2,0,0], model:{$expr:'extents(body)'}, missing:{$expr:'missingData'}},
        nodes:[{id:'body',filter:'sphere'},{id:'unfinished',options:{$fill:'later'}}], scenes:[{$fill:'later'}]};
      void manageSpatial(studio,{root:spatialRoot,identity:'test-document',revision:41,commit:root=>{window.committedSpatial=root;}});
    })()`);
    await session.wait(`document.querySelector('.spatial-list')?.textContent.includes('needs-data')`, 'unresolved host records');
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="Show definitions.model"]').disabled`), true);
    await button(session, 'Refresh from Live Data');
    await session.wait(`document.querySelector('[aria-label="Visible spatial overlays"]').textContent.includes('model · box · draft revision 41')`, 'live extents revision');
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="Show definitions.missing"]').disabled`), true);
    assert.equal(await session.evaluate(`hostFixture.calls.filter(c=>c.request.action==='live_data_refresh').length`), 1);
    assert.deepEqual(await session.evaluate(`hostFixture.calls.find(c=>c.request.action==='live_data_refresh').request.input`), await session.evaluate('spatialRoot'));
    await session.evaluate(`document.querySelector('[aria-label="Select definitions.model"]').click()`);
    assert.equal(await session.evaluate(`document.querySelector('.spatial-form').textContent.includes('Edit literal')`), false);
    await button(session, 'Edit expression');
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="Spatial expression"]').value`), 'extents(body)');
    await input(session, 'Spatial expression', 'bad(');
    await button(session, 'Update expression');
    await session.wait(`document.querySelector('.spatial-form').textContent.includes('Expected closing parenthesis')`, 'host syntax error');
    await input(session, 'Spatial expression', 'extents(body).inflate(0.1)');
    await button(session, 'Update expression');
    await session.wait(`document.querySelector('.spatial-list')?.textContent.includes('extents(body).inflate(0.1)')`, 'updated authored expression');
    await session.wait(`document.querySelector('[aria-label="Show definitions.model"]').disabled`, 'edited observed value unresolved');
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="Visible spatial overlays"]').textContent.includes('model ·')`), false);
    await button(session, 'Apply changes');
    await session.wait('window.committedSpatial', 'staged commit');
    assert.deepEqual(await session.evaluate('committedSpatial.definitions.model'), {$expr:'extents(body).inflate(0.1)'});
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});

test('shared input reaches scalar, vector and both box forms in the operation form with host destination checks (stub)', {timeout: 120000}, async () => {
  const session = await launch();
  try {
    await setup(session);
    await session.evaluate(`(async () => {
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const vector={type:'array',items:{type:'number'},minItems:3,maxItems:3};
      const root={version:'schemaxis/1',definitions:{gap:4,model:{$expr:'extents(body)'}},nodes:[{id:'body',filter:'sphere'}]};
      const schema={type:'object',required:['id','filter','options'],properties:{id:{type:'string'},filter:{const:'fixture'},options:{type:'object',
        required:['radius','origin','bounds','box'],properties:{radius:{type:'number'},origin:vector,bounds:{type:'array',items:{type:'number'},minItems:6,maxItems:6},box:{type:'object',required:['min','max'],properties:{min:vector,max:vector}}}}}};
      void configureOperation(studio,{id:'fixture',title:'Fixture',operation:'fixture',at:'/nodes/-',schema}, {},()=>root)
        .then(value=>{window.operationResult=value;});
    })()`);
    await session.wait('document.querySelector(".operation-dialog")', 'operation form');
    const labels = await session.evaluate(`[...document.querySelectorAll('.operation-dialog input[aria-label]')].map(e=>e.getAttribute('aria-label'))`);
    for (const [suffix,value] of [['radius','gap / 2'],['origin','model.mid'],['bounds','model'],['box','model']]) {
      const label = labels.find(label=>label.endsWith('.options.'+suffix));
      assert.ok(label, `shared control for ${suffix}`); await input(session,label,value);
    }
    await button(session,'Add operation');
    await session.wait('window.operationResult', 'authored operation');
    assert.deepEqual(await session.evaluate('operationResult.inserts.at(-1).values[0].options'),
      {radius:{$expr:'gap / 2'},origin:{$expr:'model.mid'},bounds:{$expr:'model'},box:{$expr:'model'}});
    const checks = await session.evaluate(`hostFixture.calls.filter(c=>c.request.action==='spatial_check').map(c=>c.request)`);
    assert.deepEqual(checks.map(c=>c.destination).sort(), ['/nodes/1/options/bounds','/nodes/1/options/box','/nodes/1/options/origin','/nodes/1/options/radius']);
    assert.equal(checks[0].input.nodes.length, 2);
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});

test('Variables classifies six numbers as a box, keeps its representation, and uses shared coordinate and runner controls', {timeout: 120000}, async () => {
  const session = await launch();
  try {
    await setup(session);
    const result = await session.evaluate(`(async () => {
      const {literalEditor} = await import('/windows/variables/forms.mjs');
      const {parameterField,parseParameter} = await import('/windows/runner/parameters.mjs');
      const box=literalEditor([0,2,0,4,0,0]); document.body.append(box.element);
      const initial=box.read(), type=box.element.querySelector('[aria-label="Value type"]').value;
      box.element.querySelector('[aria-label="Minimum X"]').value='gap / 2';
      const computed=box.read();
      const text=literalEditor('steel'); document.body.append(text.element);
      const runner=parameterField('radius',{kind:'number',label:'Radius'},{$expr:'gap / 2'}); document.body.append(runner);
      return {type,initial,computed,text:text.read(),runner:runner.querySelector('input').value,
        value:parseParameter({kind:'number'},runner.querySelector('input').value)};
    })()`);
    assert.deepEqual(result, {type:'box',initial:[0,2,0,4,0,0],computed:[{$expr:'gap / 2'},2,0,4,0,0],text:'steel',runner:'gap / 2',value:{$expr:'gap / 2'}});
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});

test('Spatial displays captured run records at their original revision and hides unsupported Live data (stub)', {timeout: 120000}, async () => {
  const session = await launch();
  try {
    await setup(session);
    await session.evaluate(`(async () => {
      const {manageSpatial} = await import('/windows/spatial/panel.mjs');
      const root={version:'schemaxis/1',definitions:{model:{$expr:'extents(body)'}},nodes:[{id:'body',filter:'sphere'}]};
      const started=await studio.api.post('/api/spatial',{action:'spatial_load',input:root,draft:{identity:'run-document',revision:5},state:{timeIndex:0,indices:{}}});
      const response=(await studio.api.waitForJob(started.job)).result;
      response.records.forEach(record=>{record.source.kind='run';});
      delete response.observations;
      void manageSpatial(studio,{root,identity:'run-document',revision:9,spatial:{root,response,draft:{identity:'run-document',revision:5}},commit:()=>{}});
    })()`);
    await session.wait(`document.querySelector('[aria-label="Visible spatial overlays"]')?.textContent.includes('draft revision 5')`, 'captured run revision');
    assert.match(await session.evaluate(`document.querySelector('.spatial-list').textContent`), /run · box/);
    await button(session,'Cancel');
    await stubSpatialHost(session, {extents:false});
    await session.evaluate(`(async()=>{const {manageSpatial}=await import('/windows/spatial/panel.mjs');
      void manageSpatial(studio,{root:{version:'schemaxis.freecad/1',definitions:{floor:[0,1,0,1,0,0]}},commit:()=>{}});})()`);
    await session.wait(`hostFixture.calls.some(c=>c.request.action==='spatial_eval')`, 'unsupported capability response');
    assert.equal(await session.evaluate(`[...document.querySelectorAll('.spatial-dialog button')].find(b=>b.textContent==='Live Data selection…').hidden`),true);
    await button(session,'Cancel');
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});
