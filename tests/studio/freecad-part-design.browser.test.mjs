// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

async function field(s, label, value) {
  await s.evaluate(`(() => {const e=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});
    if (!e || e.disabled) throw Error('Missing or disabled field '+${JSON.stringify(label)});
    e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));
    e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}
async function button(s,label) {
  await s.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent.trim()===${JSON.stringify(label)}).click()`);
}
async function add(s,operation) {
  await s.clickSelector('[data-add="all"]');
  await field(s,'Search Add anything…',operation);
  await s.wait(`document.querySelector('[data-library="operation:${operation}"]')`,'operation search');
  await s.clickSelector(`[data-library="operation:${operation}"]`);
  await s.wait('document.querySelector(".operation-form")','typed operation form');
}

test('FreeCAD Studio preserves persistent history and exposes optional sketch ownership', {timeout:120000},async()=>{
  const document=JSON.parse(await readFile(new URL('../../examples/schemaxis/freecad-part-design.json',import.meta.url),'utf8'));
  const s=await launch({provider:'freecad'});
  try {
    await s.wait('window.studio?.store.get().server','Studio ready');
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',
      {action:'new',provider:'freecad',name:'Editable mechanical part',document:${JSON.stringify(document)}});
      await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")','Workbench ready');
    const source=()=>s.evaluate('window.studio.windows.active().window.editor.getValue()');
    const original=await source();
    await add(s,'pad');
    assert.equal(await s.evaluate(`!!document.querySelector('[aria-label="pad.inputs.body"]')`),true);
    assert.equal(await s.evaluate(`!!document.querySelector('[aria-label="pad.inputs.profile"]')`),true);
    await button(s,'Cancel');
    assert.equal(await source(),original);
    await add(s,'circle');
    await field(s,'circle.id','spare');
    // Both the inputs object and its Body port are optional for legacy Part profiles.
    await s.evaluate(`(() => {for(const label of ['Include circle.inputs','Include circle.inputs.body']) {
      const e=document.querySelector('[aria-label="'+label+'"]');
      if(!e)throw Error('Missing optional ownership control '+label);
      if(!e.checked){e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));}
    }})()`);
    await field(s,'circle.inputs.body','part');
    await button(s,'Add operation');
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===6','owned profile inserted');
    const changed=JSON.parse(await source());
    assert.deepEqual(changed.nodes.at(-1).inputs,{body:'part'});
    assert.deepEqual(changed.parameters,document.parameters);
    assert.deepEqual(changed.nodes.slice(0,5),document.nodes);
    assert.equal(changed.output,'finished');
    const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(changed))}})`);
    assert.deepEqual(checked.diagnostics,[]);
    await s.evaluate('window.studio.windows.active().window.editor.focus()');await s.key('z',{modifiers:2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===5','atomic undo');
    assert.deepEqual(JSON.parse(await source()),JSON.parse(original));
    assert.deepEqual(s.exceptions,[]);
  } finally {await s.close();}
});
