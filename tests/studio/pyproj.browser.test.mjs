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
async function validate(s, document) {
  return s.evaluate(`window.studio.api.post('/api/validate',{provider:'pyproj',source:${JSON.stringify(JSON.stringify(document))}})`);
}

test('pyproj Studio discovers route chainage by intent, explains it and validates located faults with cancellation and undo', {timeout:120000}, async()=>{
  const document=JSON.parse(await readFile(new URL('../../examples/schemaxis/pyproj-winnipeg-route.json',import.meta.url),'utf8'));
  document.source=fileURLToPath(new URL('../../examples/schemaxis/pyproj-winnipeg-route.csv',import.meta.url));
  const s=await launch({provider:'pyproj'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio ready');
    await s.evaluate(`window.studio.bus.emit('new-instance')`);
    await s.wait(`document.querySelector('[aria-label="Search adaptors"]')`, 'adaptor discovery');
    await field(s, 'Search adaptors', 'chainage');
    await s.wait(`document.querySelector('[role=listbox]')?.textContent.includes('pyproj')`, 'pyproj discovered by user intent');
    await button(s, 'Cancel');
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',
      {action:'new',provider:'pyproj',name:'Winnipeg route',document:${JSON.stringify(document)}});
      await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")', 'Workbench ready');
    const source=()=>s.evaluate('window.studio.windows.active().window.editor.getValue()');
    const initial=await source();

    await add(s, 'operation:routeStations', 'geodesic distance');
    await s.evaluate(`(() => {const d=[...document.querySelectorAll('.operation-form details')]
      .find(d=>d.querySelector('summary')?.textContent==='? Operation reference');
      if(!d)throw Error('Missing operation Help');for(let p=d;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;})()`);
    await s.wait(`document.querySelector('.operation-reference')?.textContent.includes('Native binding:')`, 'packaged pyproj operation Help');
    const help=await s.evaluate('document.querySelector(".operation-reference").textContent');
    assert.match(help, /Geod/);
    assert.match(help, /not geodesic|numerical agreement/i);
    await button(s, 'Cancel');
    assert.equal(await source(), initial);

    // A valid typed edit changes only the spacing, passes host validation and undoes atomically.
    await add(s, 'document:spacing_m', 'spacing');
    await field(s, 'spacing_m', '2000');
    await button(s, 'Add operation');
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).spacing_m===2000', 'typed spacing edit');
    const edited=JSON.parse(await source());
    assert.deepEqual(edited, {...JSON.parse(initial), spacing_m:2000});
    const spaced=await validate(s, edited);
    assert.equal(spaced.valid, true);
    assert.deepEqual(spaced.diagnostics, []);
    await s.evaluate('window.studio.windows.active().window.editor.focus()');
    await s.key('z', {modifiers:2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).spacing_m===1000', 'atomic spacing undo');
    assert.equal(await source(), initial);

    const checked=await validate(s, document);
    assert.equal(checked.valid, true);
    assert.deepEqual(checked.diagnostics, []);
    const closedGap={...structuredClone(document), closed:true, requirements:{endpointGap_m:{maximum:100}}};
    const rejected=await validate(s, closedGap);
    assert.equal(rejected.valid, false);
    assert.equal(rejected.diagnostics[0].pointer, '/requirements/endpointGap_m');
    assert.match(rejected.diagnostics[0].message, /closed route/);
    const sphere=await validate(s, {...structuredClone(document), ellipsoid:'sphere'});
    assert.equal(sphere.valid, false);
    assert.equal(sphere.diagnostics[0].pointer, '/ellipsoid');

    assert.equal(await source(), initial);
    assert.deepEqual(s.exceptions, []);
  } finally {await s.close();}
});
