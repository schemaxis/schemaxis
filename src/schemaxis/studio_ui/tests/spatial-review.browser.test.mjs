// Copyright (C) 2026 David L. F. Gaden.
import test from 'node:test';
import assert from 'node:assert/strict';
import {launch} from './harness.mjs';

test('A-S2-01/02 real host refusals retain diagnostics and untyped entries remain editable', {timeout: 120000}, async () => {
  const session = await launch({provider: 'paraview'});
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    const result = await session.evaluate(`(async () => {
      const {reportSpatialCheck} = await import('/editor/spatial-input.mjs');
      const {spatialAction} = await import('/windows/spatial/host.mjs');
      const root = {version:'schemaxis/1',settings:{r:2},definitions:{bad:{$expr:'union('},unknown:{$expr:'nothere + 1'}},nodes:[]};
      const text = 'r * 2 + ) + 1';
      const response = await spatialAction(studio.api, 'spatial_check', {input:root,expression:text});
      const field = document.createElement('input'); field.value=text; document.body.append(field);
      reportSpatialCheck(field,response);
      const refusal = {ok:response.ok, code:response.fault.code, invalid:field.getAttribute('aria-invalid'),
        focused:document.activeElement===field, range:[field.selectionStart,field.selectionEnd]};
      let transport;
      try { await studio.api.post('/api/spatial', {action:'spatial_check'}); }
      catch (error) { transport={code:error.code, structured:Boolean(error.fault)}; }
      const {manageSpatial} = await import('/windows/spatial/panel.mjs');
      void manageSpatial(studio,{root,commit:()=>{}});
      return {refusal,transport};
    })()`);
    assert.deepEqual(result.refusal, {ok:false,code:'EXPR_SYNTAX',invalid:'true',focused:true,range:[8,9]});
    assert.ok(result.transport.code); assert.equal(result.transport.structured,true);
    await session.wait(`document.querySelector('.spatial-list')?.textContent.includes('nothere')`, 'fault rows');
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="Show definitions.bad"]').disabled`), true);
    await session.evaluate(`document.querySelector('[aria-label="Select definitions.bad"]').click();
      [...document.querySelectorAll('.spatial-form button')].find(e=>e.textContent==='Edit expression').click();`);
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="Spatial expression"]').value`), 'union(');
    assert.deepEqual(session.exceptions, []);
  } finally { await session.close(); }
});


test('A-S2-05/06 unchanged Variables and operation forms retain authored values', {timeout:120000}, async () => {
  const session = await launch({provider:'paraview'});
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    const values = await session.evaluate(`(async () => {
      const {literalEditor} = await import('/windows/variables/forms.mjs');
      const {spatialInput} = await import('/editor/spatial-input.mjs');
      const originals = [[10,8,6,4,2,0], {min:[10,6,2],max:[8,4,0]}];
      return {boxes: originals.map(value=>literalEditor(value).read()),
        expressions: [{$expr:'2'},{$expr:'true'}].map(value=>spatialInput({label:'Value',value}).read())};
    })()`);
    assert.deepEqual(values.boxes, [[10,8,6,4,2,0], {min:[10,6,2],max:[8,4,0]}]);
    assert.deepEqual(values.expressions, [{$expr:'2'},{$expr:'true'}]);
    await session.evaluate(`(async () => {
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const root={version:'schemaxis/1',nodes:[{id:'body',filter:'sphere',options:{radius:{$expr:'2'}}}]};
      const schema={type:'object',required:['id','filter','options'],properties:{id:{type:'string'},filter:{const:'sphere'},
        options:{type:'object',required:['radius'],properties:{radius:{type:'number'}}}}};
      void configureOperation(studio,{id:'sphere',title:'Sphere',operation:'sphere',at:'/nodes/-',schema}, {},()=>root,
        undefined,{existing:{pointer:'/nodes/0',value:root.nodes[0]}}).then(value=>window.reviewOperation=value);
    })()`);
    await session.wait('document.querySelector(".operation-dialog")', 'operation');
    await session.evaluate(`[...document.querySelectorAll('.operation-dialog button')].find(e=>e.textContent==='Apply changes').click()`);
    await session.wait('window.reviewOperation', 'unchanged save');
    assert.deepEqual(await session.evaluate('reviewOperation.replace.value.options.radius'), {$expr:'2'});
    assert.deepEqual(session.exceptions, []);
  } finally { await session.close(); }
});

test('A-S2-07 operation and library fill checks select real host fault spans', {timeout:120000}, async () => {
  const session = await launch({provider:'paraview'});
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async () => {
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const root={version:'schemaxis/1',settings:{r:2},nodes:[]};
      const schema={type:'object',required:['id','filter','options'],properties:{id:{type:'string'},filter:{const:'sphere'},
        options:{type:'object',required:['radius'],properties:{radius:{type:'number'}}}}};
      void configureOperation(studio,{id:'sphere',title:'Sphere',operation:'sphere',at:'/nodes/-',schema}, {},()=>root);
    })()`);
    await session.wait('document.querySelector(".operation-dialog")', 'operation');
    await session.evaluate(`document.querySelector('[aria-label="sphere.options.radius"]').value='r * 2 + ) + 1';
      [...document.querySelectorAll('.operation-dialog button')].find(e=>e.textContent==='Add operation').click()`);
    await session.wait(`document.querySelector('[aria-label="sphere.options.radius"]').getAttribute('aria-invalid')==='true'`, 'operation refusal');
    assert.deepEqual(await session.evaluate(`(() => {const f=document.querySelector('[aria-label="sphere.options.radius"]');
      return [document.activeElement===f,f.selectionStart,f.selectionEnd];})()`), [true,8,9]);
    await session.evaluate(`[...document.querySelectorAll('.operation-dialog button')].find(e=>e.textContent==='Cancel').click()`);
    await session.evaluate(`(async () => {
      const {createJsonEditor} = await import('/editor/editor.mjs');
      const {bindVariables} = await import('/windows/variables/editor.mjs');
      const {libraryRequest} = await import('/editor/insert-fields.mjs');
      const host=document.createElement('div'); host.style.height='500px'; document.body.append(host);
      const root={version:'schemaxis/1',settings:{r:2},nodes:[]};
      window.reviewEditor=createJsonEditor(host,{value:JSON.stringify(root)});
      bindVariables(studio,reviewEditor);
      const item={fields:{radius:{type:'number',label:'Radius',required:true}},
        inserts:[{at:'/nodes/-',values:[{id:'body',filter:'sphere',options:{radius:{$fill:'radius'}}}]}]};
      const request=libraryRequest(item,root), preview=reviewEditor.preview(request);
      reviewEditor.commitPreview(); reviewEditor.startFill({pointers:preview.pointers,fields:request.fields});
      const field=document.querySelector('.sx-fill-value'); field.value='r * 2 + ) + 1';
      field.dispatchEvent(new Event('input',{bubbles:true}));
      [...document.querySelectorAll('.sx-fill-popover button')].find(e=>e.textContent==='Accept').click();
    })()`);
    await session.wait(`document.querySelector('.sx-fill-value').getAttribute('aria-invalid')==='true'`, 'fill refusal');
    assert.deepEqual(await session.evaluate(`(() => {const f=document.querySelector('.sx-fill-value');
      return [document.activeElement===f,f.selectionStart,f.selectionEnd];})()`), [true,8,9]);
    assert.ok(await session.evaluate('reviewEditor.getDocument().nodes[0].options.radius.$fill'));
    // Hold an actual host reply while the author changes the field. Neither its
    // error nor a commit may be installed against the newer text.
    await session.evaluate(`window.reviewPost=studio.api.post.bind(studio.api);
      studio.api.post=async (...args)=>{const response=await reviewPost(...args);
        return args[1]?.action==='spatial_check' ? new Promise(resolve=>window.releaseReview=()=>resolve(response)) : response;};
      [...document.querySelectorAll('.sx-fill-popover button')].find(e=>e.textContent==='Accept').click()`);
    await session.wait('window.releaseReview', 'held host check');
    await session.evaluate(`const field=document.querySelector('.sx-fill-value'); field.value='r * 2';
      field.dispatchEvent(new Event('input',{bubbles:true})); studio.api.post=reviewPost; releaseReview();`);
    await session.evaluate('new Promise(resolve=>setTimeout(resolve,50))');
    assert.equal(await session.evaluate(`document.querySelector('.sx-fill-value').getAttribute('aria-invalid')`), null);
    assert.ok(await session.evaluate('reviewEditor.getDocument().nodes[0].options.radius.$fill'));

    await session.evaluate(`const f=document.querySelector('.sx-fill-value'); f.value='r * 2'; f.dispatchEvent(new Event('input',{bubbles:true}));
      [...document.querySelectorAll('.sx-fill-popover button')].find(e=>e.textContent==='Accept').click()`);
    await session.wait(`reviewEditor.getDocument().nodes[0].options.radius.$expr==='r * 2'`, 'checked expression accepted');
    assert.deepEqual(session.exceptions, []);
  } finally { await session.close(); }
});

test('A-S2-07 Case Runner selects the parameter fault returned by real binding', {timeout:120000}, async () => {
  const {fileURLToPath} = await import('node:url');
  const fixture = fileURLToPath(new URL('./runner-fixtures', import.meta.url));
  const session = await launch();
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate('studio.windows.open("runner")');
    await session.wait(`document.querySelector('.runner-template-bar input')`, 'Case Runner');
    await session.evaluate(`document.querySelector('.runner-template-bar input').value=${JSON.stringify(fixture)};
      document.querySelector('.runner-template-bar button').click()`);
    await session.wait(`document.querySelector('[data-parameter="stop"]')`, 'parameters');
    await session.evaluate(`const f=document.querySelector('[data-parameter="stop"]'); f.value='2 + )';
      f.dispatchEvent(new Event('input',{bubbles:true})); document.querySelector('.runner .actions button:first-child').click()`);
    await session.wait(`document.querySelector('[data-parameter="stop"]').getAttribute('aria-invalid')==='true'`, 'binding fault');
    assert.deepEqual(await session.evaluate(`(() => {const f=document.querySelector('[data-parameter="stop"]');
      return [document.activeElement===f,f.selectionStart,f.selectionEnd];})()`), [true,4,5]);
    assert.deepEqual(session.exceptions, []);
  } finally { await session.close(); }
});
