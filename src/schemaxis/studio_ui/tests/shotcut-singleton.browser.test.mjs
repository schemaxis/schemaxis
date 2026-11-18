// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

async function action(s,label) {
  await s.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent.trim()===${JSON.stringify(label)}).click()`);
}
async function field(s,label,value) {
  await s.evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(`[aria-label="${label}"]`)});e.value=${JSON.stringify(String(value))};e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
}
async function add(s) {
  await s.clickSelector('[data-add="sources"]');
  await s.wait('document.querySelector(\'[data-library="operation:editTimeline"]\')','timeline card');
  assert.equal(await s.evaluate('document.querySelectorAll(\'[data-library="operation:editTimeline"]\').length'),1);
  await s.clickSelector('[data-library="operation:editTimeline"]');
}
const active='window.studio.windows.active().window';
async function openSettings(s) {
  const row='.wb-comprehension button[data-pointer="/nodes/0"]';
  await s.wait(`document.querySelector(${JSON.stringify(row)})`,'Overview timeline');
  await s.evaluate(`document.querySelector(${JSON.stringify(row)}).scrollIntoView({block:'center'})`);
  // Select through the actual Overview gesture; it retains focus on its button,
  // rather than racing a store-only selection against textarea selectionchange.
  if (await s.evaluate(`document.querySelector(${JSON.stringify(row)}).getAttribute('aria-current')==='true'`))
    await s.clickSelector(row);
  await s.clickSelector(row);
  const button='.wb-comprehension .wb-node-actions [data-action="edit-settings"]';
  await s.evaluate(`document.querySelector(${JSON.stringify(button)}).scrollIntoView({block:'center'})`);
  await s.wait(`(()=>{const b=document.querySelector(${JSON.stringify(button)});if(!b||b.disabled)return false;
    const r=b.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
    return ${active}.store.get().selected==='/nodes/0' && r.width>0 && r.height>0 && (hit===b||b.contains(hit));})()`,
    'enabled unobstructed Overview Edit');
  await s.clickSelector(button);
  await s.wait('document.querySelector(".operation-form")','existing form');
}
async function diagnostics(s) {
  return s.evaluate(`(()=>{return {selected:${active}.store.get().selected,
    focused:document.activeElement?.outerHTML?.slice(0,500),
    buttons:[...document.querySelectorAll('[data-action="edit-settings"]')].map(b=>{const r=b.getBoundingClientRect();
      const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
      return {text:b.textContent,disabled:b.disabled,rect:[r.x,r.y,r.width,r.height],hit:hit?.outerHTML?.slice(0,500)};}),
    notifications:window.studio.notify.store.get().log,
    alerts:[...document.querySelectorAll('.operation-error')].map(e=>e.textContent)};})()`);
}
const fixture={version:'schemaxis.shotcut/1',nodes:[{id:'MyOrderedTimeline',filter:'editTimeline',options:{
  assets:[{name:'second',file:'/clips/second.mkv'},{name:'first',file:'/clips/first.mkv'}],
  clips:[{asset:'first',startFrame:3,frameCount:3},{asset:'second',startFrame:0,frameCount:2},{asset:'first',startFrame:3,frameCount:3}],
  fps:25,width:32,height:24,threads:1}}]};

test('real Shotcut Add is singleton, transactional, cancellable and retains existing ordered settings', {timeout:120000},async()=>{
  const s=await launch({provider:'shotcut'});
  try {
    await s.wait('window.studio?.store.get().server','Studio');
    await s.evaluate(`(async()=>{const ctx=window.studio;const r=await ctx.api.post('/api/documents',{action:'new',provider:'shotcut',name:'Singleton check',document:{version:'schemaxis.shotcut/1',nodes:[]}});await ctx.refresh();ctx.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=sources]")','Add toolbar');
    const source=()=>s.evaluate(`${active}.editor.getValue()`);
    const empty=await source();
    await add(s);await s.wait('document.querySelector(".operation-form")','empty form');
    await action(s,'Cancel');assert.equal(await source(),empty);
    await add(s);await s.wait('document.querySelector(".operation-form")','new form');
    await field(s,'editTimeline.options.assets[0].file','/clips/camera.mkv');
    assert.equal(await s.evaluate('document.querySelector(\'[aria-label="editTimeline.options.assets[0].name"]\').value'),
      'asset_camera_mkv');
    await field(s,'editTimeline.id','MyTimeline');
    await field(s,'editTimeline.options.assets[0].name','camera');
    await field(s,'editTimeline.options.assets[0].file','/clips/camera.mkv');
    await field(s,'editTimeline.options.clips[0].asset','camera');
    await field(s,'editTimeline.options.clips[0].frameCount',2);
    await action(s,'Add operation');
    await s.wait(`JSON.parse(${active}.editor.getValue()).nodes.length===1`,'single insertion');
    const inserted=await source();assert.equal(JSON.parse(inserted).nodes[0].id,'MyTimeline');
    const version=await s.evaluate(`${active}.editor.getTextVersion()`);
    await add(s);
    await s.wait('document.querySelector(".toast-body")?.textContent.includes("Edit settings")','populated refusal');
    assert.equal(await s.evaluate('Boolean(document.querySelector(".operation-form"))'),false);
    assert.equal(await source(),inserted);assert.equal(await s.evaluate(`${active}.editor.getTextVersion()`),version);
    await s.evaluate(`${active}.editor.undo()`);
    await s.wait(`JSON.parse(${active}.editor.getValue()).nodes.length===0`,'one Undo removes only insertion');
    // Stale-capacity check: a different action fills the collection while Add is open.
    await add(s);await s.wait('document.querySelector(".operation-form")','stale form');
    await s.evaluate(`${active}.editor.replaceDocument(${JSON.stringify(fixture)})`);
    const stale=await source(),staleVersion=await s.evaluate(`${active}.editor.getTextVersion()`);
    await action(s,'Insert required placeholders');
    await s.wait('document.querySelector(".operation-wizard > .operation-error")?.textContent.includes("at most 1")','stale refusal');
    assert.equal(await source(),stale);assert.equal(await s.evaluate(`${active}.editor.getTextVersion()`),staleVersion);
    await action(s,'Cancel');
    await openSettings(s);
    assert.equal(await s.evaluate('document.querySelector(\'[aria-label="editTimeline.id"]\').value'),'MyOrderedTimeline');
    assert.equal(await s.evaluate('document.querySelector(\'[aria-label="editTimeline.id"]\').readOnly'),true);
    assert.match(await s.evaluate('document.querySelector(\'[aria-label="editTimeline.id"]\').title'),/cannot be changed in Settings/);
    await field(s,'editTimeline.options.threads',2);
    await action(s,'Apply changes');
    await s.wait(`JSON.parse(${active}.editor.getValue()).nodes[0].options.threads===2`,'settings apply');
    const expected=structuredClone(fixture);expected.nodes[0].options.threads=2;
    assert.deepEqual(JSON.parse(await source()),expected);
    await s.evaluate(`${active}.editor.undo()`);
    await s.wait(`JSON.parse(${active}.editor.getValue()).nodes[0].options.threads===1`,'settings Undo');
    assert.deepEqual(JSON.parse(await source()),fixture);
    // Existing invalid drafts remain editable as text; Settings never silently
    // deletes the extra timeline or loops back to its own recovery instruction.
    const invalid=structuredClone(fixture);invalid.nodes.push({...structuredClone(fixture.nodes[0]),id:'ExtraTimeline'});
    await s.evaluate(`${active}.editor.replaceDocument(${JSON.stringify(invalid)})`);
    const invalidSource=await source(),invalidVersion=await s.evaluate(`${active}.editor.getTextVersion()`);
    await openSettings(s);
    await field(s,'editTimeline.options.threads',2);
    await action(s,'Apply changes');
    await s.wait('document.querySelector(".operation-wizard > .operation-error")?.textContent.includes("already contains 2")','invalid count refusal');
    const message=await s.evaluate('document.querySelector(".operation-wizard > .operation-error").textContent');
    assert.match(message,/before applying settings/);assert.doesNotMatch(message,/Open the existing/);
    assert.equal(await source(),invalidSource);assert.equal(await s.evaluate(`${active}.editor.getTextVersion()`),invalidVersion);
    await action(s,'Cancel');
    assert.deepEqual(s.exceptions,[]);
    assert.deepEqual(s.consoleErrors,[]);
  } catch (error) {
    console.error(JSON.stringify({settingsDiagnostic:await diagnostics(s),exceptions:s.exceptions,consoleErrors:s.consoleErrors}));
    throw error;
  } finally {await s.close();}
});
