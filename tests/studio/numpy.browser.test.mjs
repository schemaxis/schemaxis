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
async function add(s, id, query) {
  await s.clickSelector('[data-add="all"]');
  await field(s, 'Search Add anything…', query);
  await s.wait(`document.querySelector('[data-library="${id}"]')`, 'matching Add control');
  await s.clickSelector(`[data-library="${id}"]`);
  await s.wait('document.querySelector(".operation-form")', 'typed authoring form');
}

test('NumPy Studio discovers PCA by intent, explains it and validates located scaling faults with cancellation and undo', {timeout:120000}, async()=>{
  const document=JSON.parse(await readFile(new URL('../../examples/schemaxis/numpy-sensors.json',import.meta.url),'utf8'));
  document.source=fileURLToPath(new URL('../../examples/schemaxis/numpy-sensors.csv',import.meta.url));
  const s=await launch({provider:'numpy'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio ready');
    await s.evaluate(`window.studio.bus.emit('new-instance')`);
    await s.wait(`document.querySelector('[aria-label="Search adaptors"]')`, 'adaptor discovery');
    await field(s, 'Search adaptors', 'principal component analysis');
    await s.wait(`document.querySelector('[role=listbox]')?.textContent.includes('NumPy')`, 'NumPy discovered by user intent');
    await button(s, 'Cancel');
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',
      {action:'new',provider:'numpy',name:'Analytic sensors',document:${JSON.stringify(document)}});
      await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")', 'Workbench ready');
    const source=()=>s.evaluate('window.studio.windows.active().window.editor.getValue()');
    const initial=await source();

    await add(s, 'operation:principalComponents', 'explained variance');
    await s.evaluate(`(() => {const d=[...document.querySelectorAll('.operation-form details')]
      .find(d=>d.querySelector('summary')?.textContent==='? Operation reference');
      if(!d)throw Error('Missing operation Help');for(let p=d;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;})()`);
    await s.wait(`document.querySelector('.operation-reference')?.textContent.includes('Native binding:')`, 'packaged NumPy operation Help');
    const help=await s.evaluate('document.querySelector(".operation-reference").textContent');
    assert.match(help, /numpy\.linalg\.svd/);
    assert.match(help, /repeated or near-repeated eigenvalues/i);
    await button(s, 'Cancel');
    assert.equal(await source(), initial);

    // A valid typed edit changes only scaling, passes host validation and undoes atomically.
    await add(s, 'document:scaling', 'scaling');
    await field(s, 'scaling', '1');
    await button(s, 'Add operation');
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).scaling==="standardise"', 'typed scaling edit');
    const edited=JSON.parse(await source());
    assert.deepEqual(edited, {...JSON.parse(initial), scaling:'standardise'});
    const standardised=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'numpy',source:${JSON.stringify(JSON.stringify(edited))}})`);
    assert.equal(standardised.valid, true);
    assert.deepEqual(standardised.diagnostics, []);
    await s.evaluate('window.studio.windows.active().window.editor.focus()');
    await s.key('z', {modifiers:2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).scaling==="none"', 'atomic scaling undo');
    assert.equal(await source(), initial);

    const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'numpy',source:${JSON.stringify(JSON.stringify(document))}})`);
    assert.equal(checked.valid, true);
    assert.deepEqual(checked.diagnostics, []);
    const mixed=structuredClone(document);
    mixed.channels[1].unit='V';
    const rejected=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'numpy',source:${JSON.stringify(JSON.stringify(mixed))}})`);
    assert.equal(rejected.valid, false);
    assert.equal(rejected.diagnostics.length, 1);
    assert.equal(rejected.diagnostics[0].pointer, '/scaling');
    assert.match(rejected.diagnostics[0].message, /shared channel unit/);
    const missing=structuredClone(document);
    missing.scaling='declared';
    const located=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'numpy',source:${JSON.stringify(JSON.stringify(missing))}})`);
    assert.equal(located.valid, false);
    assert.equal(located.diagnostics[0].pointer, '/channels/0/scale');

    await s.evaluate('window.studio.windows.active().window.editor.focus()');
    assert.equal(await source(), initial);
    assert.deepEqual(s.exceptions, []);
  } finally {await s.close();}
});
