// Copyright (C) 2026 David L. F. Gaden.
// Real Studio server; no spatial stubs and no native applications.
import test from 'node:test';
import assert from 'node:assert/strict';
import {launch} from './harness.mjs';
const active='studio.windows.active().window';
async function field(s, label, value) {
  await s.wait(`document.querySelector('[aria-label="${label}"]')`, label);
  await s.evaluate(`(() => {
    const e = document.querySelector('[aria-label="${label}"]');
    e.value = ${JSON.stringify(value)};
    e.dispatchEvent(new Event('input', {bubbles: true}));
    e.dispatchEvent(new Event('change', {bubbles: true}));
  })()`);
}
async function button(s, label) {
  const q = `[...document.querySelectorAll('.dialog button')]
    .find(b => b.textContent.trim() === ${JSON.stringify(label)} && !b.disabled)`;
  await s.wait(q, label);
  await s.evaluate(`${q}.click()`);
}
for(const theme of ['light','dark']) test(`rename real host Variables, fill, Spatial and naming (${theme})`,{timeout:120000},async()=>{
 const s=await launch({provider:'paraview',theme});
 try{
 await s.wait('window.studio?.store.get().server','Studio');
 await s.evaluate(`(async()=>{const r=await studio.api.post('/api/documents',{action:'new',provider:'paraview',name:'Rename review',document:{version:'schemaxis/1',nodes:[{id:'ball',filter:'sphere',options:{radius:2}}],scenes:[{id:'v',geometry:['ball']}]}});window.reviewId=r.id;await studio.refresh();studio.openDocument(r.id);})()`);
 await s.wait(`${active}.store?.get().schema`,'Workbench');
 await s.evaluate(`void studio.openVariables()`);
 await button(s,'Create new value…');await field(s,'Variable name','t');await field(s,'Value group','sweeps');await field(s,'Sweep values (JSON)','[1,2,3]');await button(s,'Create value');
 await s.wait(`document.querySelector('.variable-row')?.parentElement.textContent.includes('t')`,'sweep staged');
 await button(s,'Apply changes');await s.wait(`!document.querySelector('.dialog')`,'Variables saved');
 assert.deepEqual(await s.evaluate(`${active}.editor.getDocument().sweeps`),[{name:'t',values:[1,2,3]}]);
 await s.evaluate(`(()=>{const root=${active}.editor.getDocument();root.definitions={position:{$expr:'vector(sweeps.t,0,0)'}};root.nodes[0].options.radius={$fill:'radius',type:'number'};${active}.editor.setValue(JSON.stringify(root));${active}.editor.startFill({pointers:['/nodes/0/options/radius']});})()`);
 await field(s,'Value or expression','$sweep');
 // There is an existing sweep, so explicitly select creation.
 await field(s,'Sweep','Create a sweep…');
 await field(s,'New sweep name','radius');await field(s,'New sweep values (JSON)','[2,4]');
 await s.evaluate(`document.querySelector('.sx-fill-popover:not([hidden]) .primary').click()`);
 await s.wait(`!document.querySelector('.sx-fill-popover:not([hidden])')`,'fill committed');
 assert.deepEqual(await s.evaluate(`${active}.editor.getDocument().nodes[0].options.radius`),{$sweep:'radius'});
 const checked=await s.evaluate(`studio.api.post('/api/validate',{provider:'paraview',source:${active}.editor.getValue()})`);assert.equal(checked.valid,true,JSON.stringify(checked));
 await s.evaluate(`(async()=>{window.reviewCalls=[];const post=studio.api.post.bind(studio.api);studio.api.post=async(...args)=>{const result=await post(...args);if(args[1]?.action==='spatial_list')reviewCalls.push(result);return result;};const {manageSpatial}=await import('/windows/spatial/panel.mjs');void manageSpatial(studio,{root:${active}.editor.getDocument(),commit:()=>{}});})()`);
 await s.wait(`reviewCalls.length && document.querySelector('.spatial-list')?.textContent.includes('position')`,'real spatial list');
 const listing=await s.evaluate('reviewCalls.at(-1)');assert.ok(listing.sweeps);assert.equal(Object.hasOwn(listing,'axes'),false);
 assert.ok(listing.sweeps.some(x=>x.id==='radius'));
 await button(s,'Cancel');
 // Full Designer naming control saves through the actual server.
 await s.evaluate(`(async()=>{const r=await studio.api.post('/api/documents',{action:'new',provider:'workflow-design',name:'Sweep naming'});window.namingId=r.id;await studio.refresh();studio.openDocument(r.id);})()`);
 await s.wait('studio.designers.get(namingId)?.model.store.get().projection','Designer');
 await s.evaluate(`(async()=>{const model=studio.designers.get(namingId).model;const r=await studio.api.get('/api/document',{id:namingId});r.document.workflow.sweeps=[{name:'t',values:[2,4]}];r.document.workflow.operations=[{id:'data',document:{version:'schemaxis.octave/1',nodes:[{id:'data',filter:'sequence',options:{start:0,stop:4,count:5}}],outputs:['data']}}];r.document.outputs={table:{operation:'data',artifact:0,kind:'table'}};await model.saveDocument(r.document,model.store.get().revision);})()`);
 await s.clickSelector('.dz-bottom-tab[data-tab="naming"]');await field(s,'Naming pattern','{index}-{sweep:t}{ext}');
 await s.wait(`[...document.querySelectorAll('.dz-naming button')].some(b=>b.textContent.trim()==='Save naming'&&!b.disabled)`,'naming preview accepts sweep');
 await s.evaluate(`[...document.querySelectorAll('.dz-naming button')].find(b=>b.textContent.trim()==='Save naming').click()`);
 await s.wait(`studio.designers.get(namingId).model.store.get().projection.naming.pattern==='{index}-{sweep:t}{ext}'`,'naming saved');
 const record=await s.evaluate('studio.api.get("/api/document",{id:namingId})');assert.equal(record.document.naming.pattern,'{index}-{sweep:t}{ext}');
 assert.match(await s.evaluate(`document.querySelector('.dz-naming-preview').textContent`),/000001-2/);
 const preview=await s.evaluate(`(async()=>{const {preview}=await import('/windows/designer/naming.mjs');return {good:preview('{index}-{sweep:t}{ext}',[{sweeps:{t:2},ext:'.png'}]),old:preview('{index}-{axis:t}{ext}',[{sweeps:{t:2},ext:'.png'}])};})()`);
 assert.deepEqual(preview.good.names,['000001-2.png']);assert.ok(preview.old.error);
 assert.deepEqual(s.exceptions,[]);
 }finally{await s.close();}
});
