import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

async function field(s,label,value) {
  await s.evaluate(`(() => {const e=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});if(!e)throw Error('missing '+${JSON.stringify(label)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
}
async function button(s,label) {
  await s.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent.trim()===${JSON.stringify(label)}).click()`);
}
async function add(s,name) {
  await s.clickSelector('[data-add="all"]');
  await field(s,'Search Add anything…',name);
  await s.wait(`document.querySelector('[data-library="document:${name}"]')`,'document control');
  await s.clickSelector(`[data-library="document:${name}"]`);
  await s.wait('document.querySelector(".operation-form")','typed form');
}

test('OpenSCAD actual Studio forms, guidance, cancellation, placeholder insertion and atomic undo',{timeout:120000},async()=>{
  const s=await launch({provider:'openscad'});
  try {
    await s.wait('window.studio?.store.get().server','Studio ready');
    await s.evaluate(`window.studio.bus.emit('new-instance')`);
    await s.wait(`document.querySelector('[aria-label="Search adaptors"]')`,'adaptor search');
    await field(s,'Search adaptors','mounting plate');
    await s.wait(`document.querySelector('[role=listbox]')?.textContent.includes('OpenSCAD')`,'matching adaptor');
    await s.evaluate(`document.querySelector('.dialog-footer button').click()`);
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',{action:'new',provider:'openscad',name:'OpenSCAD authoring',document:{version:'schemaxis.openscad/1',operation:'plate',units:'mm',plate:{width:40,depth:30,height:3,holes:[{centre:[10,10],diameter:6}]}}});window.cadDoc=r.id;await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")','Add toolbar');
    const source=()=>s.evaluate('window.studio.windows.active().window.editor.getValue()');
    const initial=await source();
    await s.clickSelector('[data-add="all"]');await field(s,'Search Add anything…','mounting plate');
    await s.wait(`document.querySelector('[data-library="operation:plate"]')`,'operation search');
    await s.clickSelector('[data-library="operation:plate"]');await s.wait('document.querySelector(".operation-form")','operation form');
    await s.evaluate(`(() => {const d=[...document.querySelectorAll('.operation-form details')].find(d=>d.querySelector('summary')?.textContent==='? Operation reference');d.open=true;})()`);
    await s.wait(`document.querySelector('.operation-reference')?.textContent.includes('Native binding:')`,'packaged context Help');
    assert.match(await s.evaluate('document.querySelector(".operation-reference").textContent'),/plate|cube/);
    await button(s,'Cancel');
    await add(s,'plate');
    assert.match(await s.evaluate('document.querySelector(".operation-form").textContent'),/millimetre|mm|plate/i);
    await button(s,'Cancel');assert.equal(await source(),initial);
    await add(s,'plate');
    await field(s,'plate.width','50');await field(s,'plate.depth','35');await field(s,'plate.height','4');
    await s.evaluate(`(() => {const b=document.querySelector('[aria-label="Help for plate.width"]');for(let p=b.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;b.click();})()`);
    assert.match(await s.evaluate('document.querySelector(".operation-form").textContent'),/local X length|0.5.*200/);
    await button(s,'Add operation');
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).plate.width===50','edited plate');
    const changed=await source();
    const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'openscad',source:${JSON.stringify(changed)}})`);assert.deepEqual(checked.diagnostics,[]);
    await s.evaluate('window.studio.windows.active().window.editor.focus()');await s.key('z',{modifiers:2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).plate.width===40','atomic undo');
    assert.equal(await source(),initial);
    await add(s,'plate');await button(s,'Insert required placeholders');
    await s.wait('window.studio.windows.active().window.editor.getValue().includes("$fill")','persistent required fill markers');
    const filled=JSON.parse(await source());assert.ok(filled.plate.width.$fill);assert.ok(filled.plate.depth.$fill);assert.ok(filled.plate.height.$fill);
    await s.evaluate('window.studio.windows.active().window.editor.focus()');await s.key('z',{modifiers:2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).plate.width===40','placeholder atomic undo');
    assert.deepEqual(s.exceptions,[]);
  } finally {await s.close();}
});
