// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

async function field(s, label, value) {
  await s.evaluate(`(() => {const e=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});
    if(!e || e.disabled)throw Error('Missing or disabled field '+${JSON.stringify(label)});
    e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));
    e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}
async function button(s, label, selector = '.dialog-footer') {
  await s.evaluate(`(() => {const b=[...document.querySelectorAll(${JSON.stringify(selector+' button')})]
    .find(b=>b.textContent.trim()===${JSON.stringify(label)});
    if(!b)throw Error('Missing button '+${JSON.stringify(label)});b.click();})()`);
}
async function revealAndClick(s, label) {
  await s.evaluate(`(() => {const e=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});
    if(!e)throw Error('Missing control '+${JSON.stringify(label)});
    for(let p=e.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;
    e.click();})()`);
}
async function add(s, id, query) {
  await s.clickSelector('[data-add="all"]');
  await field(s, 'Search Add anything…', query);
  await s.wait(`document.querySelector('[data-library="${id}"]')`, 'matching Add control');
  await s.clickSelector(`[data-library="${id}"]`);
  await s.wait('document.querySelector(".operation-form")', 'typed authoring form');
}

test('Arrow Studio discovers nullable tables and authors typed selection with validation, cancellation and undo', {timeout:120000}, async()=>{
  const document=JSON.parse(await readFile(new URL('../../examples/schemaxis/apachearrow-measurements.json',import.meta.url),'utf8'));
  document.source=fileURLToPath(new URL('../../examples/schemaxis/fixtures/apachearrow/measurements.csv',import.meta.url));
  const s=await launch({provider:'apachearrow'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio ready');
    await s.evaluate(`window.studio.bus.emit('new-instance')`);
    await s.wait(`document.querySelector('[aria-label="Search adaptors"]')`, 'adaptor discovery');
    await field(s, 'Search adaptors', 'nullable table');
    await s.wait(`document.querySelector('[role=listbox]')?.textContent.includes('Apache Arrow')`, 'Arrow discovered by user intent');
    await button(s, 'Cancel');
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',
      {action:'new',provider:'apachearrow',name:'Nullable measurements',document:${JSON.stringify(document)}});
      await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")', 'Workbench ready');
    const source=()=>s.evaluate('window.studio.windows.active().window.editor.getValue()');
    const initial=await source();

    await add(s, 'operation:prepareTable', 'nullable table');
    await s.evaluate(`(() => {const d=[...document.querySelectorAll('.operation-form details')]
      .find(d=>d.querySelector('summary')?.textContent==='? Operation reference');
      if(!d)throw Error('Missing operation Help');for(let p=d;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;})()`);
    await s.wait(`document.querySelector('.operation-reference')?.textContent.includes('Native binding:')`, 'packaged Arrow operation Help');
    const help=await s.evaluate('document.querySelector(".operation-reference").textContent');
    assert.match(help, /pyarrow\.csv\.read_csv/);
    assert.match(help, /int32.to.int64 widening/);
    await button(s, 'Cancel');
    assert.equal(await source(), initial);

    await add(s, 'document:select', 'select');
    await button(s, 'Remove', '.operation-form');
    await button(s, 'Add operation');
    await s.wait(`document.querySelector('.operation-error')?.textContent.includes('Expected at least 1 item')`, 'required selection validation');
    assert.equal(await s.evaluate('!!document.querySelector(".operation-form")'), true);
    assert.equal(await source(), initial);
    await button(s, 'Add select item', '.operation-form');
    await field(s, 'select[0].column', 'label');
    await field(s, 'select[0].name', 'x'.repeat(41));
    await button(s, 'Add operation');
    await s.wait(`document.querySelector('.operation-error')?.textContent.includes('Expected at most 40 characters')`, 'output name length validation');
    assert.equal(await s.evaluate('!!document.querySelector(".operation-form")'), true);
    assert.equal(await source(), initial);
    await field(s, 'select[0].name', 'label_text');
    await revealAndClick(s, 'Include select[0].fillNull');
    await field(s, 'select[0].fillNull', 'unlabelled');
    await revealAndClick(s, 'Help for select[0].fillNull');
    const fieldHelp=await s.evaluate(`document.querySelector('[aria-label="Help for select[0].fillNull"]')
      .closest('.operation-field').querySelector('.operation-field-help').textContent`);
    assert.match(fieldHelp, /nullable source/);
    assert.match(fieldHelp, /Omit to preserve nulls/);
    await button(s, 'Add select item', '.operation-form');
    await field(s, 'select[1].column', 'small');
    await field(s, 'select[1].name', 'batch');
    await revealAndClick(s, 'Include select[1].cast');
    await button(s, 'Add select item', '.operation-form');
    await field(s, 'select[2].column', 'observed');
    await field(s, 'select[2].name', 'observed');
    await button(s, 'Add operation');
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).select.length===3', 'typed selection inserted');
    const changed=JSON.parse(await source());
    assert.deepEqual(changed.select, [
      {column:'label',name:'label_text',fillNull:'unlabelled'},
      {column:'small',name:'batch',cast:'int64'},
      {column:'observed',name:'observed'},
    ]);
    assert.deepEqual(changed, {...document, select:changed.select});
    const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'apachearrow',source:${JSON.stringify(JSON.stringify(changed))}})`);
    assert.equal(checked.valid, true);
    assert.deepEqual(checked.diagnostics, []);
    // Host validation independently rejects the same limit after form feedback.
    const invalid=structuredClone(changed);
    invalid.select[0].name='x'.repeat(41);
    const rejected=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'apachearrow',source:${JSON.stringify(JSON.stringify(invalid))}})`);
    assert.equal(rejected.valid, false);
    assert.equal(rejected.diagnostics.length, 1);
    assert.equal(rejected.diagnostics[0].pointer, '/select/0/name');
    assert.match(rejected.diagnostics[0].message, /40/);

    const edited=await source();
    assert.deepEqual(JSON.parse(edited), changed);
    await add(s, 'document:select', 'select');
    await field(s, 'select[0].column', 'id');
    await field(s, 'select[0].name', 'abandoned');
    await button(s, 'Cancel');
    assert.equal(await source(), edited);
    await s.evaluate('window.studio.windows.active().window.editor.focus()');
    await s.key('z', {modifiers:2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).select.length===6', 'atomic selection undo');
    assert.equal(await source(), initial);
    assert.deepEqual(s.exceptions, []);
  } finally {await s.close();}
});

test('Arrow Studio opts in to typed CSV publication with field Help, host validation and undo', {timeout:120000}, async()=>{
  const document=JSON.parse(await readFile(new URL('../../examples/schemaxis/apachearrow-measurements.json',import.meta.url),'utf8'));
  document.source=fileURLToPath(new URL('../../examples/schemaxis/fixtures/apachearrow/measurements.csv',import.meta.url));
  const s=await launch({provider:'apachearrow'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio ready');
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',
      {action:'new',provider:'apachearrow',name:'Typed CSV',document:${JSON.stringify(document)}});
      await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")', 'Workbench ready');
    const source=()=>s.evaluate('window.studio.windows.active().window.editor.getValue()');
    const initial=await source();
    assert.equal(JSON.parse(initial).publishCSV, undefined);

    await add(s, 'document:publishCSV', 'publishCSV');
    await revealAndClick(s, 'Help for publishCSV');
    const help=await s.evaluate(`document.querySelector('[aria-label="Help for publishCSV"]')
      .closest('.operation-field').querySelector('.operation-field-help').textContent`);
    assert.match(help, /declare the identical column types/);
    assert.match(help, /not sanitised/);
    assert.match(help, /no workbook is created/);
    await button(s, 'Cancel');
    assert.equal(await source(), initial);

    await add(s, 'document:publishCSV', 'publishCSV');
    await field(s, 'publishCSV', '0'); // choice index 0 is true; '' would leave a Fill later placeholder
    await button(s, 'Add operation');
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).publishCSV===true', 'publishCSV inserted');
    const changed=JSON.parse(await source());
    assert.deepEqual(changed, {...document, publishCSV:true});
    const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'apachearrow',source:${JSON.stringify(JSON.stringify(changed))}})`);
    assert.equal(checked.valid, true);
    assert.deepEqual(checked.diagnostics, []);
    const rejected=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'apachearrow',source:${JSON.stringify(JSON.stringify({...changed,publishCSV:'yes'}))}})`);
    assert.equal(rejected.valid, false);
    assert.equal(rejected.diagnostics[0].pointer, '/publishCSV');
    await s.evaluate('window.studio.windows.active().window.editor.focus()');
    await s.key('z', {modifiers:2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).publishCSV===undefined', 'publishCSV undo');
    assert.equal(await source(), initial);
    assert.deepEqual(s.exceptions, []);
  } finally {await s.close();}
});
