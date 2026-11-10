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

test('FreeCAD finite Pocket exposes explicit depth and preserves atomic history edits', {timeout:120000},async()=>{
  const document=JSON.parse(await readFile(new URL('../../examples/schemaxis/freecad-counterbore.json',import.meta.url),'utf8'));
  const s=await launch({provider:'freecad'});
  try {
    await s.wait('window.studio?.store.get().server','Studio ready');
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',
      {action:'new',provider:'freecad',name:'Editable counterbore',document:${JSON.stringify(document)}});
      await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")','Workbench ready');
    const source=()=>s.evaluate('window.studio.windows.active().window.editor.getValue()');
    const original=await source();
    await add(s,'pocket');
    await field(s,'pocket.id','recess');
    await field(s,'pocket.inputs.base','finished');
    await field(s,'pocket.inputs.profile','counterbore');
    await s.evaluate(`(() => {const e=document.querySelector('[aria-label="Include pocket.options"]');
      if(!e)throw Error('Missing optional options object');
      if(!e.checked){e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));}})()`);
    await s.evaluate(`(() => {const e=document.querySelector('[aria-label="Include pocket.options.extent"]');
      if(e && !e.checked){e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));}})()`);
    await field(s,'pocket.options.extent','1');
    await s.evaluate(`(() => {const e=document.querySelector('[aria-label="Include pocket.options.length"]');
      if(!e)throw Error('Missing optional finite depth');
      if(!e.checked){e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));}})()`);
    await field(s,'pocket.options.length','2');
    await button(s,'Add operation');
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===8','finite depth inserted');
    const changed=JSON.parse(await source());
    assert.equal(changed.nodes.at(-1).options.extent,'length');
    assert.equal(changed.nodes.at(-1).options.length,2);
    assert.deepEqual(changed.parameters,document.parameters);
    assert.deepEqual(changed.nodes.slice(0,7),document.nodes);
    // Reusing an owned profile remains a semantic error; typed insertion does not
    // discard the user's existing history or silently choose another profile.
    const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(changed))}})`);
    assert.ok(checked.diagnostics.some(d=>d.code==='INVALID_BODY_OWNERSHIP'));
    await s.evaluate('window.studio.windows.active().window.editor.focus()');await s.key('z',{modifiers:2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===7','atomic undo');
    assert.deepEqual(JSON.parse(await source()),JSON.parse(original));
    assert.deepEqual(s.exceptions,[]);
  } finally {await s.close();}
});
