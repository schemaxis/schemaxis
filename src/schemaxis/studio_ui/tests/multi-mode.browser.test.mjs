// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import test from 'node:test';
import {launch, delay} from './harness.mjs';
const button = (s, label, scope='.operation-dialog') => s.evaluate(`(()=>{const e=[...document.querySelectorAll(${JSON.stringify(scope+' button')})].find(b=>b.textContent===${JSON.stringify(label)});const details=e.closest('details');if(details)details.open=true;e.click();})()`);
const value = (s, label, text) => s.evaluate(`(()=>{const e=document.querySelector('[aria-label="'+${JSON.stringify(label)}+'"]');const details=e.closest('details');if(details)details.open=true;e.value=${JSON.stringify(text)};e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
const toggleRow = async (s, row) => {
 await s.evaluate(`document.querySelector('.multi-mode-batch').open=false`);
 const selector = `.multi-mode-row:nth-child(${row}) .multi-mode-row-toggle`;
 await s.evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center'})`);
 await s.clickSelector(selector);
};
const batchOpen = (s, open=true) => s.evaluate(`document.querySelector('.multi-mode-batch').open=${open}`);
const batchEntry = (s, text, action) => s.evaluate(`[...document.querySelectorAll('.multi-mode-batch-picker .reader-entry')]
  .find(row => row.querySelector('code').textContent.endsWith(${JSON.stringify(text)}))
  .querySelector('button:${action === 'Delete' ? 'last' : 'first'}-child').click()`);
const source='window.studio.windows.active().window.editor.getDocument()';
test('extractBlock multi-mode applies four ordinary elements atomically, preserves references, cancels and undoes', {timeout:120000}, async()=>{
 const s=await launch({provider:'paraview'});
 try {
  await s.wait('window.studio?.store.get().server','Studio');
  await s.evaluate(`(async()=>{const record=await studio.api.post('/api/documents',{action:'new',provider:'paraview',name:'multi',document:{version:'schemaxis/1',nodes:[{id:'ball',filter:'sphere'},{id:'source',filter:'group',inputs:{input:['ball']}},{id:'custom',filter:'extractBlock',inputs:{input:'source'},options:{selectors:['//internalMesh']}},{id:'downstream',filter:'surface',inputs:{input:'custom'}}],scenes:[]}});window.batchRecordId=record.id;await studio.refresh();studio.windows.open('workbench',{document:record.id});})()`);
  await s.wait(`[...document.querySelectorAll('.wb-comprehension button')].some(b=>b.textContent.includes('custom'))`,'workbench');
  await s.evaluate(`[...document.querySelectorAll('.wb-comprehension button')].find(b=>b.textContent.includes('custom')).click()`);
  await s.wait('document.querySelector(".wb-overview-node.selected [data-action=edit-settings]:not(:disabled)")','settings action');
  await s.clickSelector('.wb-overview-node.selected [data-action=edit-settings]');
  await s.wait('document.querySelector(".operation-dialog")','settings');
  await button(s,'Switch to multi-mode');
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="Row 1 Name"]').readOnly`),true);
  await batchOpen(s);
  await button(s,'Delete','.multi-mode-batch-picker .reader-entry');
  await value(s,'Batch.Blocks entry','internalMesh, WT_wall_XP, WT_wall_XM, Inlet');
  await button(s,'Add entry','.multi-mode-batch-picker .reader-add');
  await button(s,'One instance per selected item');
  assert.match(await s.evaluate('document.querySelector(".multi-mode [role=alert]").textContent'),/already uses .*internalMesh/);
  assert.equal(await s.evaluate('document.querySelectorAll(".multi-mode-row").length'),1);
  await batchEntry(s,'internalMesh','Delete');
  await button(s,'One instance per selected item');
  assert.equal(await s.evaluate('document.querySelectorAll(".multi-mode-row").length'),4);
  assert.deepEqual(await s.evaluate(`[...document.querySelectorAll('.multi-mode-row input[aria-label$=" Name"]')].map(e=>e.value)`),
    ['custom','extractBlock_WT_wall_XP','extractBlock_WT_wall_XM','extractBlock_Inlet']);
  if (process.env.SCHEMAXIS_MULTI_SCREENSHOT) {
    await batchOpen(s,false);
    await s.evaluate(`document.querySelector('.multi-mode').scrollIntoView({block:'start'})`);
    await s.screenshot(process.env.SCHEMAXIS_MULTI_SCREENSHOT);
  }
  await button(s,'Group selected rows');
  assert.match(await s.evaluate('document.querySelector(".multi-mode [role=alert]").textContent'),/original/);
  await button(s,'Apply instances');
  await s.wait(`${source}.nodes.length===7`,'atomic rows');
  const saved=await s.evaluate(source);
  assert.equal(saved.nodes[3].inputs.input,'custom');
  assert.deepEqual(saved.nodes.slice(4).map(n=>n.options.selectors),[['//WT_wall_XP'],['//WT_wall_XM'],['//Inlet']]);
  assert.deepEqual(saved.nodes[2].options.selectors,['//internalMesh']);
  // One text editor history item owns all rows.
  await s.evaluate('studio.windows.active().window.editor.focus()');
  await s.key('z',{modifiers:2});
  await s.wait(`${source}.nodes.length===4`,'undo batch');
  await s.evaluate('studio.windows.active().window.editor.focus()');
  await s.key('z',{modifiers:10});
  await s.wait(`${source}.nodes.length===7`,'redo batch');
  await s.wait(`document.querySelector('.wb-comprehension [data-pointer="/nodes/4"]')`,'batch member after redo');
  await s.clickSelector('.wb-comprehension [data-pointer="/nodes/4"]');
  await s.wait(`document.querySelector('.wb-editor-tools [data-action=edit-settings]:not(:disabled)')`,'enabled edit action');
  await s.clickSelector('.wb-editor-tools [data-action=edit-settings]');
  await s.wait('document.querySelector(".operation-dialog")','reopen');
  await s.wait('document.querySelector(".operation-dialog.multi-mode-active")','known batch reopens automatically');
  assert.equal(await s.evaluate('document.querySelectorAll(".multi-mode-row").length'),4);
  assert.ok(await s.evaluate(`[...document.querySelectorAll('.multi-mode-row input[aria-label$=" Name"]')].every(e=>e.readOnly)`));
  // Editing a different member replaces that exact original, not the clicked
  // node or the entire batch appended a second time.
  await toggleRow(s,2);
  await button(s,'Properties…','.multi-mode-row:nth-child(2)');
  await s.wait('document.querySelectorAll(".operation-dialog").length===2','saved member properties');
  assert.equal(await s.evaluate(`[...document.querySelectorAll('[aria-label="extractBlock.id"]')].at(-1).readOnly`),true);
  await button(s,'Delete','.dialog-backdrop:last-child .reader-entry');
  await s.evaluate(`(()=>{const e=[...document.querySelectorAll('[aria-label="extractBlock.options.selectors entry"]')].at(-1);e.value='changedWall';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await button(s,'Apply changes','.dialog-backdrop:last-child .dialog-footer');
  await s.wait('document.querySelectorAll(".operation-dialog").length===1','return to saved batch');
  await button(s,'Apply instances');
  await s.wait(`${source}.nodes[4].options.selectors[0]==='//changedWall'`,'member updated in place');
  assert.equal(await s.evaluate(`${source}.nodes.length`),7);
  assert.equal(await s.evaluate(`${source}.nodes[3].inputs.input`),'custom');
  assert.deepEqual(await s.evaluate(`${source}.nodes[2].options.selectors`),['//internalMesh']);
  await s.evaluate('studio.windows.active().window.editor.focus()');
  await s.key('z',{modifiers:2});
  await s.wait(`${source}.nodes[4].options.selectors[0]==='//WT_wall_XP'`,'one undo restores edited batch');
  await s.clickSelector('.wb-comprehension [data-pointer="/nodes/4"]');
  await s.clickSelector('.wb-overview-node.selected [data-action=edit-settings]');
  await s.wait('document.querySelector(".operation-dialog.multi-mode-active")','batch membership survives undo');
  await button(s,'Add instance');
  await button(s,'Cancel','.dialog-footer');
  assert.deepEqual(await s.evaluate(source),saved);
  const documentId=await s.evaluate('batchRecordId');
  await s.clickSelector('[data-action="save"]');
  await s.wait(`document.querySelector('[aria-label="Source file path"]')`,'save batch file');
  await s.evaluate(`document.querySelector('[aria-label="Source file path"]').value=${JSON.stringify(s.workspace+'/batch.json')}`);
  await button(s,'Save','.dialog-backdrop:last-child');
  await s.wait(`[...studio.windows.instances.values()].every(instance=>!instance.window.isDirty?.())`,'batch saved before reload');
  await s.evaluate('window.batchOldPage=true');
  await s.send('Page.reload');
  const reloadDeadline=Date.now()+20000;
  let reloaded=false;
  while(Date.now()<reloadDeadline){
    try { if(await s.evaluate('!window.batchOldPage && window.studio?.store.get().server')) {reloaded=true;break;} }
    catch(error){if(!/navigated or closed|Execution context was destroyed|Cannot find context/.test(error.message))throw error;}
    await delay(80);
  }
  assert.equal(reloaded,true,'Studio reloads its saved batch');
  await s.evaluate(`studio.openDocument(${JSON.stringify(documentId)})`);
  await s.wait(`document.querySelector('.wb-comprehension [data-pointer="/nodes/4"]')`,'saved batch after reload');
  await s.clickSelector('.wb-comprehension [data-pointer="/nodes/4"]');
  await s.wait('document.querySelector(".wb-overview-node.selected [data-action=edit-settings]:not(:disabled)")','saved batch settings available');
  await s.clickSelector('.wb-overview-node.selected [data-action=edit-settings]');
  await s.wait('document.querySelector(".operation-dialog.multi-mode-active")','batch survives browser reload');
  assert.equal(await s.evaluate('document.querySelectorAll(".multi-mode-row").length'),4);
  await button(s,'Cancel','.dialog-footer');
  // A removed member must not discard the original batch or absorb an
  // unrelated extract with matching settings. Applying must not revive it.
  await s.evaluate(`(()=>{const editor=studio.windows.active().window.editor,doc=editor.getDocument();
    editor.replaceDocument({...doc,nodes:[...doc.nodes.filter(node=>node.id!=='extractBlock_WT_wall_XM'),
      {...doc.nodes[4],id:'unrelatedExtract'}]});})()`);
  await s.evaluate(`(()=>{const button=document.querySelector('.wb-comprehension [data-pointer="/nodes/4"]');
    if(button.getAttribute('aria-current')!=='true')button.click();})()`);
  await s.wait('document.querySelector(".wb-editor-tools [data-action=edit-settings]:not(:disabled)")','surviving member selected');
  await s.clickSelector('.wb-editor-tools [data-action=edit-settings]');
  await s.wait('document.querySelector(".operation-dialog.multi-mode-active")','surviving batch reopens');
  const memberNames=()=>s.evaluate(`[...document.querySelectorAll('.multi-mode-row input[aria-label$=" Name"]')].map(e=>e.value)`);
  assert.deepEqual(await memberNames(),['custom','extractBlock_WT_wall_XP','extractBlock_Inlet']);
  await toggleRow(s,2);
  await value(s,'Row 2.Blocks entry','extraWall');
  await button(s,'Add entry','.multi-mode-row:nth-child(2) .reader-add');
  await button(s,'Apply instances');
  await s.wait(`${source}.nodes[4].options.selectors.includes('//extraWall')`,'surviving member edited in place');
  assert.deepEqual(await s.evaluate(`${source}.nodes.map(n=>n.id)`),
    ['ball','source','custom','downstream','extractBlock_WT_wall_XP','extractBlock_Inlet','unrelatedExtract']);
  assert.deepEqual(await s.evaluate(`${source}.nodes.at(-1).options.selectors`),['//WT_wall_XP']);
  // The batch's provenance remembers omitted members across Apply, so Undo of
  // the edit followed by Undo of the deletion restores the full table.
  await s.evaluate('studio.windows.active().window.editor.undo();studio.windows.active().window.editor.undo()');
  await s.wait(`${source}.nodes[5].id==='extractBlock_WT_wall_XM'`,'deleted member restored by Undo');
  await s.evaluate(`(()=>{const button=document.querySelector('.wb-comprehension [data-pointer="/nodes/4"]');
    if(button.getAttribute('aria-current')!=='true')button.click();})()`);
  await s.clickSelector('.wb-editor-tools [data-action=edit-settings]');
  await s.wait('document.querySelector(".operation-dialog.multi-mode-active")','restored batch');
  assert.deepEqual(await memberNames(),['custom','extractBlock_WT_wall_XP','extractBlock_WT_wall_XM','extractBlock_Inlet']);
  await button(s,'Cancel','.dialog-footer');
  assert.deepEqual(s.exceptions,[]);
 } finally { await s.close(); }
});

test('single-mode naming follows configuration until the user explicitly edits Name', {timeout:120000}, async()=>{
 const s=await launch({provider:'paraview'});
 try {
  await s.wait('window.studio?.store.get().server','Studio');
  await s.evaluate(`(async()=>{const meta=await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});const item=meta.addCatalogue.items.find(i=>i.operation==='extractBlock');const {configureOperation}=await import('/windows/workbench/operation-form.mjs');window.root={version:'schemaxis/1',nodes:[{id:'source',filter:'group',inputs:{input:[]}}],scenes:[]};void configureOperation(studio,item,meta.addCatalogue.definitions,()=>root).then(r=>window.result=r);})()`);
  await s.wait('document.querySelector(".operation-dialog")','add form');
  await value(s,'extractBlock.options.selectors entry','internalMesh');
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="extractBlock.id"]').value`),'extractBlock_internalMesh');
  await value(s,'extractBlock.id','extractBlock_internalMesh');
  await value(s,'extractBlock.options.selectors entry','Inlet');
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="extractBlock.id"]').value`),'extractBlock_internalMesh');
  await button(s,'Add operation');
  await s.wait('window.result','saved');
  assert.deepEqual(await s.evaluate('result.inserts.at(-1).values[0].options.selectors'),['//Inlet']);
  assert.deepEqual(s.exceptions,[]);
 } finally {await s.close();}
});


test('new rows retain explicit names, split and group deliberately, and validate selected-only settings and collisions', {timeout:120000}, async()=>{
 const s=await launch({provider:'paraview'});
 try {
  await s.wait('window.studio?.store.get().server','Studio');
  await s.evaluate(`(async()=>{const meta=await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});const item=meta.addCatalogue.items.find(i=>i.operation==='extractBlock');const {configureOperation}=await import('/windows/workbench/operation-form.mjs');window.root={version:'schemaxis/1',nodes:[{id:'sourceA',filter:'group',inputs:{input:[]}},{id:'sourceB',filter:'group',inputs:{input:[]}}],scenes:[]};void configureOperation(studio,item,meta.addCatalogue.definitions,()=>root).then(r=>window.result=r);})()`);
  await s.wait('document.querySelector(".operation-dialog")','add form');
  await value(s,'extractBlock.id','myChoice');
  await value(s,'extractBlock.options.selectors entry','WT_wall_XP, Inlet');
  await s.evaluate(`(()=>{const e=document.querySelector('[aria-label="extractBlock.inputs.input"]');e.value='sourceA';e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await button(s,'Switch to multi-mode');
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="Row 1 Name"]').value`),'myChoice');
  await button(s,'Split selected rows');
  assert.deepEqual(await s.evaluate(`[...document.querySelectorAll('.multi-mode-row input[aria-label$=" Name"]')].map(e=>e.value)`),['myChoice','extractBlock_Inlet']);
  await batchOpen(s,false);
  await toggleRow(s,1);
  await button(s,'Properties…','.multi-mode-row:nth-child(1)');
  await s.wait(`document.querySelectorAll('.operation-dialog').length===2`,'first row properties');
  await s.evaluate(`(()=>{const e=[...document.querySelectorAll('[aria-label="extractBlock.inputs.input"]')].at(-1);e.value='sourceB';e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await button(s,'Apply changes','.dialog-backdrop:last-child .dialog-footer');
  await s.wait(`document.querySelectorAll('.operation-dialog').length===1`,'row properties applied');
  // Other rows keep their own input after one instance changes Properties.
  await s.evaluate(`window.realPost=studio.api.post;studio.api.post=async(path,body)=>{if(path==='/api/inspect-input'){window.lastInspection=body;return {job:'fixture'}}return realPost(path,body)};studio.api.waitForJob=async()=>({result:{assemblies:{Hierarchy:[{depth:1,label:'Inlet',parent:'/Root',selector:'/Root/Inlet'}]}}});`);
  await toggleRow(s,2);
  await button(s,'Ask the application','.multi-mode-row:nth-child(2)');
  await s.wait('window.lastInspection','row input inspection');
  assert.equal(await s.evaluate('lastInspection.node'),'sourceA');
  await s.wait(`document.querySelector('.multi-mode-row:nth-child(2) .wb-case-name')?.textContent==='Inlet'`,'row choices');
  await toggleRow(s,2);
  await toggleRow(s,2);
  assert.equal(await s.evaluate(`document.querySelector('.multi-mode-row:nth-child(2) .wb-case-name').textContent`),'Inlet');
  await batchOpen(s);
  await button(s,'Group selected rows');
  assert.match(await s.evaluate(`document.querySelector('.multi-mode [role=alert]').textContent`),/different settings/);
  await s.evaluate(`document.querySelector('[aria-label="Select row 2"]').click()`);
  await button(s,'Use starting settings for selected instances');
  await s.evaluate(`document.querySelector('[aria-label="Select row 2"]').click()`);
  await button(s,'Group selected rows');
  assert.equal(await s.evaluate('document.querySelectorAll(".multi-mode-row").length'),1);
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="Row 1 Name"]').value`),'myChoice');
  await button(s,'Add instance');
  await value(s,'Row 2.Blocks entry','internalMesh');
  await value(s,'Row 2 Name','sourceA');
  await button(s,'Apply instances');
  assert.match(await s.evaluate(`document.querySelector('.operation-wizard > .operation-error').textContent`),/already in use/);
  assert.equal(await s.evaluate('root.nodes.length'),2);
  await value(s,'Row 2 Name','secondChoice');
  await s.evaluate(`const kind=document.querySelector('[aria-label="Row 2.Blocks entry kind"]');kind.value='regex';kind.dispatchEvent(new Event('change',{bubbles:true}));`);
  await value(s,'Row 2.Blocks entry','[');
  await button(s,'Apply instances');
  assert.match(await s.evaluate(`document.querySelector('.operation-wizard > .operation-error').textContent`),/regular expression/);
  await value(s,'Row 2.Blocks entry','');
  await s.evaluate(`root.nodes.push({id:'changed',filter:'sphere'})`);
  await button(s,'Apply instances');
  assert.match(await s.evaluate(`document.querySelector('.operation-wizard > .operation-error').textContent`),/input changed/);
  await button(s,'Cancel','.dialog-footer');
  assert.equal(await s.evaluate('window.result'),null);
  assert.deepEqual(s.exceptions,[]);
 } finally {await s.close();}
});

test('four selected items become four compact instances; clickable headers preserve grouped selections and owned Names', {timeout:120000}, async()=>{
 const s=await launch({provider:'paraview'});
 try {
  await s.wait('window.studio?.store.get().server','Studio');
  await s.evaluate(`(async()=>{const meta=await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});const item=meta.addCatalogue.items.find(i=>i.operation==='extractBlock');const {configureOperation}=await import('/windows/workbench/operation-form.mjs');window.root={version:'schemaxis/1',nodes:[{id:'source',filter:'group',inputs:{input:[]}}],scenes:[]};void configureOperation(studio,item,meta.addCatalogue.definitions,()=>root).then(r=>window.result=r);})()`);
  await s.wait('document.querySelector(".operation-dialog")','add form');
  await value(s,'extractBlock.options.selectors entry','internalMesh, WT_wall_XP, WT_wall_XM, Inlet');
  await value(s,'extractBlock.id','myInternal');
  await button(s,'Switch to multi-mode');
  await button(s,'One instance per selected item');
  assert.equal(await s.evaluate('document.querySelectorAll(".multi-mode-row").length'),4);
  assert.match(await s.evaluate('document.querySelector(".multi-mode-status").textContent'),/Replaced the draft starter/);
  assert.deepEqual(await s.evaluate(`[...document.querySelectorAll('.multi-mode-summary-name')].map(e=>e.textContent)`),
    ['myInternal','extractBlock_WT_wall_XP','extractBlock_WT_wall_XM','extractBlock_Inlet']);
  assert.ok(await s.evaluate(`[...document.querySelectorAll('.multi-mode-row-editor')].every(e=>getComputedStyle(e).display==='none')`));
  assert.ok(await s.evaluate(`[...document.querySelectorAll('.multi-mode-row')].every(e=>e.getBoundingClientRect().height<100)`));
  await button(s,'One instance per selected item');
  assert.equal(await s.evaluate('document.querySelectorAll(".multi-mode-row").length'),4,'repeating selected-item split adds no duplicate instances');
  assert.match(await s.evaluate('document.querySelector(".multi-mode [role=alert]").textContent'),/already uses .*internalMesh/);
  if(process.env.SCHEMAXIS_MULTI_FRESH_SCREENSHOT){
   await batchOpen(s,false);
   await s.evaluate(`document.querySelector('.multi-mode').scrollIntoView({block:'start'})`);
   await s.screenshot(process.env.SCHEMAXIS_MULTI_FRESH_SCREENSHOT);
  }
  await toggleRow(s,1);
  await value(s,'Row 1.Blocks entry','secondary');
  await button(s,'Add entry','.multi-mode-row:nth-child(1) .reader-add');
  await value(s,'Row 1.Blocks entry','third');
  await button(s,'Add entry','.multi-mode-row:nth-child(1) .reader-add');
  assert.equal(await s.evaluate('document.querySelector(".multi-mode-row-editor").hidden'),false,'multi-select editing stays expanded');
  await toggleRow(s,1);
  assert.equal(await s.evaluate('document.querySelector(".multi-mode-row-editor").hidden'),true);
  assert.match(await s.evaluate('document.querySelector(".multi-mode-summary-items").textContent'),/internalMesh.*secondary.*third/);
  assert.equal(await s.evaluate('document.querySelector(".multi-mode-summary-name").textContent'),'myInternal');
  await batchOpen(s);
  for (const entry of ['WT_wall_XP','WT_wall_XM','Inlet']) await batchEntry(s,entry,'Delete');
  await button(s,'One instance per selected item');
  assert.equal(await s.evaluate('document.querySelectorAll(".multi-mode-row").length'),5,'edited group is retained when batch selection still asks for a separate internalMesh');
  await toggleRow(s,2);
  await value(s,'Row 2 Name','myWall');
  await toggleRow(s,2);
  await button(s,'One instance per selected item');
  assert.equal(await s.evaluate('document.querySelectorAll(".multi-mode-row").length'),5);
  assert.equal(await s.evaluate('document.querySelectorAll(".multi-mode-summary-name")[1].textContent'),'myWall');
  if(process.env.SCHEMAXIS_MULTI_GROUP_SCREENSHOT){
   await batchOpen(s,false);
   await s.evaluate(`document.querySelector('.multi-mode').scrollIntoView({block:'start'})`);
   await s.screenshot(process.env.SCHEMAXIS_MULTI_GROUP_SCREENSHOT);
  }
  await button(s,'Apply instances');
  await s.wait('window.result','saved instances');
  const saved=await s.evaluate('result.inserts.at(-1).values');
  assert.equal(saved.length,5);
  assert.equal(saved[0].id,'myInternal');
  assert.deepEqual(saved[0].options.selectors,['//internalMesh','//secondary','//third']);
  assert.equal(saved[1].id,'myWall');
  assert.ok(saved.every(node=>node.inputs.input==='source'));
  assert.deepEqual(s.exceptions,[]);
 }finally{await s.close();}
});

test('empty activation keeps loaded choices, clickable quick edits, confirmed deletion and transactional Properties', {timeout:120000}, async()=>{
 const s=await launch({provider:'paraview'});
 try {
  await s.wait('window.studio?.store.get().server','Studio');
  await s.evaluate(`(async()=>{const meta=await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});const item=meta.addCatalogue.items.find(i=>i.operation==='extractBlock');const {configureOperation}=await import('/windows/workbench/operation-form.mjs');window.root={version:'schemaxis/1',nodes:[{id:'source',filter:'group',inputs:{input:[]}}],scenes:[]};const post=studio.api.post;studio.api.post=async(path,body)=>path==='/api/inspect-input'?{job:'fixture'}:post(path,body);studio.api.waitForJob=async()=>({result:{assemblies:{Hierarchy:[{depth:1,label:'internalMesh',parent:'/Root',selector:'/Root/internalMesh'},{depth:1,label:'Inlet',parent:'/Root',selector:'/Root/Inlet'}]}}});void configureOperation(studio,item,meta.addCatalogue.definitions,()=>root).then(r=>window.result=r);})()`);
  await s.wait('document.querySelector(".operation-dialog")','add form');
  await button(s,'Ask the application','.operation-form');
  await s.wait(`document.querySelectorAll('.operation-form .wb-case-name').length===2`,'starting available names');
  await button(s,'Switch to multi-mode');
  await s.wait(`document.querySelector('.multi-mode-row-toggle')?.getAttribute('aria-expanded')==='true'`,'expanded empty draft');
  assert.match(await s.evaluate(`document.querySelector('.multi-mode-summary-items').textContent`),/No blocks selected/);
  assert.equal(await s.evaluate(`document.querySelectorAll('.multi-mode-row .wb-case-name').length`),2,'starting choices carried to empty instance');
  assert.equal(await s.evaluate(`document.querySelector('.multi-mode [role=alert]').textContent`),'');
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="Select row 1"]').hidden`),true);
  await batchOpen(s);
  await s.wait(`!document.querySelector('[aria-label="Select row 1"]').hidden`,'batch checkbox');
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="Select row 1"]').checked`),true);
  await batchOpen(s,false);
  await s.wait(`document.querySelector('[aria-label="Select row 1"]').hidden`,'hidden batch checkbox');
  // Native keyboard activation of the header folds and reopens the entire quick editor.
  await s.evaluate(`document.querySelector('.multi-mode-row-toggle').focus()`);
  await s.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});
  await s.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
  assert.equal(await s.evaluate(`document.querySelector('.multi-mode-row-editor').hidden`),true);
  await toggleRow(s,1);
  assert.equal(await s.evaluate(`document.querySelector('.multi-mode-row').classList.contains('expanded')`),true);
  await button(s,'internalMesh','.multi-mode-row .reader-choices');
  assert.match(await s.evaluate(`document.querySelector('.multi-mode-summary-items').textContent`),/internalMesh/);
  assert.equal(await s.evaluate(`document.querySelector('.multi-mode-row-editor').hidden`),false);
  await value(s,'Row 1 Name','myMesh');
  assert.equal(await s.evaluate(`document.querySelector('.multi-mode-summary-name').textContent`),'myMesh');
  await button(s,'Add instance');
  assert.equal(await s.evaluate(`document.querySelectorAll('.multi-mode-row').length`),2);
  assert.equal(await s.evaluate(`document.querySelectorAll('.multi-mode-row:nth-child(1) .wb-case-name').length`),2);
  assert.equal(await s.evaluate(`document.querySelectorAll('.multi-mode-row:nth-child(2) .wb-case-name').length`),2);
  await button(s,'Delete','.multi-mode-row:nth-child(2) .multi-mode-row-editor > .wb-button-row');
  await s.wait(`document.querySelector('[aria-label="Delete instance?"]')`,'delete confirmation');
  await button(s,'Cancel','[aria-label="Delete instance?"]');
  assert.equal(await s.evaluate(`document.querySelectorAll('.multi-mode-row').length`),2);
  await button(s,'Delete','.multi-mode-row:nth-child(2) .multi-mode-row-editor > .wb-button-row');
  await button(s,'Delete','[aria-label="Delete instance?"]');
  await s.wait(`document.querySelectorAll('.multi-mode-row').length===1`,'confirmed deletion');
  await button(s,'Properties…','.multi-mode-row');
  await s.wait(`document.querySelectorAll('.operation-dialog').length===2`,'instance properties');
  await s.evaluate(`(()=>{const e=[...document.querySelectorAll('[aria-label="extractBlock.id"]')].at(-1);e.value='cancelledName';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await button(s,'Cancel','.dialog-backdrop:last-child .dialog-footer');
  await s.wait(`document.querySelectorAll('.operation-dialog').length===1`,'cancel properties');
  assert.equal(await s.evaluate(`document.querySelector('.multi-mode-summary-name').textContent`),'myMesh');
  assert.equal(await s.evaluate(`document.querySelectorAll('.multi-mode-row .wb-case-name').length`),2);
  await s.wait(`document.querySelector('.operation-steps [data-step="final"]').textContent.includes('(0)')`,'completed instance has no pending final values');
  if(process.env.SCHEMAXIS_MULTI_QUICK_SCREENSHOT){
   await batchOpen(s,false);
   await s.evaluate(`document.querySelector('.multi-mode').scrollIntoView({block:'start'})`);
   await s.screenshot(process.env.SCHEMAXIS_MULTI_QUICK_SCREENSHOT);
  }
  await button(s,'Apply instances');
  await s.wait('window.result','saved formerly empty draft');
  const saved=await s.evaluate('result.inserts.at(-1).values');
  assert.equal(saved.length,1); assert.equal(saved[0].id,'myMesh');
  assert.deepEqual(saved[0].options.selectors,['//internalMesh']);
  assert.deepEqual(s.exceptions,[]); assert.deepEqual(s.consoleErrors,[]);
 }finally{await s.close();}
});

test('multi-mode isolates starting defaults and keeps toolbar/footer fixed while twelve instances scroll', {timeout:120000}, async()=>{
 const s=await launch({provider:'paraview'});
 try {
  await s.wait('window.studio?.store.get().server','Studio');
  await s.evaluate(`(async()=>{const meta=await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});const item=meta.addCatalogue.items.find(i=>i.operation==='extractBlock');const {configureOperation}=await import('/windows/workbench/operation-form.mjs');window.root={version:'schemaxis/1',nodes:[{id:'sourceA',filter:'group',inputs:{input:[]}},{id:'sourceB',filter:'group',inputs:{input:[]}},{id:'saved',filter:'extractBlock',inputs:{input:'sourceA'},options:{selectors:['//internalMesh']}}],scenes:[]};void configureOperation(studio,item,meta.addCatalogue.definitions,()=>root,null,{existing:{pointer:'/nodes/2',value:root.nodes[2]}}).then(r=>window.result=r);})()`);
  await s.wait('document.querySelector(".operation-dialog")','edit form');
  await button(s,'Switch to multi-mode');
  assert.equal(await s.evaluate(`document.querySelector('.operation-form > .operation-field').getBoundingClientRect().height`),0,'single-instance form is absent from multi-mode layout');
  assert.equal(await s.evaluate(`document.querySelector('.operation-reference').getBoundingClientRect().height`),0,'ordinary operation reference is hidden');
  assert.equal(await s.evaluate(`document.querySelector('.operation-dialog').innerText.includes('master')`),false);
  await toggleRow(s,1);
  await button(s,'Properties…','.multi-mode-row:nth-child(1)');
  await s.wait(`document.querySelectorAll('.operation-dialog').length===2`,'original properties');
  await s.evaluate(`(()=>{const e=[...document.querySelectorAll('[aria-label="extractBlock.inputs.input"]')].at(-1);e.value='sourceB';e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await button(s,'Apply changes','.dialog-backdrop:last-child .dialog-footer');
  await s.wait(`document.querySelectorAll('.operation-dialog').length===1`,'return from properties');
  for(let index=0;index<11;index++) await button(s,'Add instance');
  assert.equal(await s.evaluate(`document.querySelectorAll('.multi-mode-row').length`),12);
  await button(s,'Properties…','.multi-mode-row:nth-child(12)');
  await s.wait(`document.querySelectorAll('.operation-dialog').length===2`,'new instance properties');
  assert.equal(await s.evaluate(`[...document.querySelectorAll('[aria-label="extractBlock.inputs.input"]')].at(-1).value`),'sourceA','later instances inherit starting input, never edited row Properties');
  await button(s,'Cancel','.dialog-backdrop:last-child .dialog-footer');
  await s.wait(`document.querySelectorAll('.operation-dialog').length===1`,'return after cancel');
  await s.evaluate(`document.querySelectorAll('.multi-mode-row-toggle[aria-expanded="true"]').forEach(e=>e.click());document.querySelector('.multi-mode-rows').scrollTop=0`);
  const geometry=()=>s.evaluate(`(()=>{const rect=e=>{const r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height}};const rows=document.querySelector('.multi-mode-rows');return {toolbar:rect(document.querySelector('.multi-mode-toolbar')),footer:rect(document.querySelector('.operation-dialog > .dialog-footer')),rows:rect(rows),scrollHeight:rows.scrollHeight,scrollTop:rows.scrollTop,viewport:innerHeight}})()`);
  const before=await geometry();
  assert.ok(before.toolbar.height<55,'toolbar remains a single compact row');
  assert.ok(before.rows.height>200 && before.scrollHeight>before.rows.height,'instances have an independent scroll viewport');
  await s.evaluate(`const list=document.querySelector('.multi-mode-rows');list.scrollTop=list.scrollHeight`);
  const after=await geometry();
  assert.ok(after.scrollTop>100);
  assert.equal(after.toolbar.top,before.toolbar.top); assert.equal(after.footer.top,before.footer.top);
  assert.ok(after.toolbar.top>=0 && after.footer.bottom<=after.viewport);
  assert.ok(after.rows.bottom<=after.footer.top);
  if(process.env.SCHEMAXIS_MULTI_SCROLL_SCREENSHOT) await s.screenshot(process.env.SCHEMAXIS_MULTI_SCROLL_SCREENSHOT);
  await button(s,'Cancel','.operation-dialog > .dialog-footer');
  assert.equal(await s.evaluate('window.result'),null);
  assert.equal(await s.evaluate('root.nodes[2].inputs.input'),'sourceA','outer cancellation leaves saved original unchanged');
  assert.deepEqual(s.exceptions,[]);
 }finally{await s.close();}
});
