// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFile, rm} from 'node:fs/promises';
import {join} from 'node:path';
import {launch, delay} from './harness.mjs';
import {createBrowserProfile} from './browser-profile.mjs';
const active='studio.windows.active().window';

async function downloaded(path) {
  for (let i=0;i<50;i++) {
    try { return await readFile(path,'utf8'); } catch(error) { if(error.code!=='ENOENT') throw error; }
    await delay(100);
  }
  throw Error(`Download did not finish: ${path}`);
}

test('Case data copies full sections, appends atomically in JSON/YAML and downloads CSV', {timeout:120000}, async()=>{
  const s=await launch({provider:'paraview'});
  // Snap Chromium has a private /tmp; use a directory both processes can see.
  const downloads=await createBrowserProfile('schemaxis-csv-download-');
  try {
    await s.wait('window.studio?.store.get().server','Studio');
    await s.send('Browser.grantPermissions',{origin:new URL(s.url).origin,permissions:['clipboardReadWrite','clipboardSanitizedWrite']});
    await s.send('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:downloads});
    await s.evaluate(`(async()=>{const record=await studio.api.post('/api/documents',{action:'new',provider:'paraview',name:'Case copy',
      document:{version:'schemaxis/1',nodes:[{id:'case',filter:'foam',options:{file:'case.foam',regions:['wall1']}}],scenes:[{id:'view',geometry:['case']}]}});
      await studio.refresh();studio.openDocument(record.id)})()`);
    await s.wait(`${active}.store?.get().schema`,'workbench');
    await s.evaluate(`${active}.store.set({inspection:{available:true,node:'case',regions:['wall10','wall1','wall2','a,"b'],cellArrays:['U','p'],availableTimes:[0.6,0.8,1]}})`);
    for(const format of ['json','yaml']) {
      await s.evaluate(`${active}.editor.convertFormat('${format}');${active}.editor.revealPointer('/nodes/0/options/regions/0')`);
      await s.clickSelector('[aria-label="Copy Regions"]');
      try { await s.wait(`${active}.editor.getDocument().nodes[0].options.regions.length===4`,'section appended'); }
      catch(error) {
        console.error('Case copy failure',format,await s.evaluate(`({cursor:${active}.editor.getCursor(),
          value:${active}.editor.getDocument(),cached:${active}.store.get().value,inspection:${active}.store.get().inspection,
          status:document.querySelector('.wb-case-data > [role=status]').textContent})`)); throw error;
      }
      assert.deepEqual(await s.evaluate(`${active}.editor.getDocument().nodes[0].options.regions`),['wall1','a,"b','wall2','wall10']);
      await s.evaluate(`${active}.editor.undo()`);
      await s.wait(`${active}.editor.getDocument().nodes[0].options.regions.length===1`,'one undo restores entire section');
    }
    await s.evaluate(`${active}.editor.revealPointer('/nodes/0/id');document.querySelector('[aria-label="Filter case names"]').value='wall2';
      document.querySelector('[aria-label="Filter case names"]').dispatchEvent(new Event('input',{bubbles:true}))`);
    await s.clickSelector('[aria-label="Copy Regions"]');
    await s.wait(`document.querySelector('.wb-case-data > [role=status]').textContent.startsWith('Copied')`,'copy complete');
    assert.deepEqual(JSON.parse(await s.evaluate('navigator.clipboard.readText()')),['a,"b','wall1','wall2','wall10'],'copy includes filtered-out values');
    await s.clickSelector('[data-action=copy-case-data]');
    await s.wait(`navigator.clipboard.readText().then(t=>t.startsWith('{'))`,'copy all complete');
    assert.deepEqual(JSON.parse(await s.evaluate('navigator.clipboard.readText()')).availableTimes,[0.6,0.8,1]);
    await s.clickSelector('[aria-label="Export Regions CSV"]');
    const section=await downloaded(join(downloads,'case-data-regions.csv'));
    assert.ok(section.includes('"Regions","a,""b"'));assert.ok(!section.includes('"Times"'));
    await s.clickSelector('[data-action=export-case-data]');
    const all=await downloaded(join(downloads,'case-data.csv'));
    assert.ok(all.includes('"Cell arrays","U"'));assert.ok(all.includes('"Times","0.6"'));
    assert.equal(await s.evaluate(`${active}.editor.getDocument().nodes[0].options.regions.length`),1,'copy and download do not edit scalar cursor targets');
    await s.evaluate(`Object.defineProperty(navigator.clipboard,'writeText',{configurable:true,value:async()=>{throw Error('Permission denied')}})`);
    await s.clickSelector('[aria-label="Copy Regions"]');
    await s.wait(`document.querySelector('.wb-case-data > [role=status]').textContent.includes('Could not copy or insert: Permission denied')`,'clipboard failure reported truthfully');
    assert.deepEqual(s.exceptions,[]); assert.deepEqual(s.consoleErrors,[]);
  } finally {await s.close();await rm(downloads,{recursive:true,force:true});}
});

test('block subset controls support all, filtered groups, shift ranges, patterns, box drag and keyboard', {timeout:120000},async()=>{
  const s=await launch({provider:'paraview'});
  try {
    await s.wait('window.studio?.store.get().server','Studio');
    await s.evaluate(`(async()=>{
      const {readerSelection}=await import('/windows/workbench/reader-selection.mjs');
      const {openDialog}=await import('/shell/dialog.mjs');
      const data={available:true,regions:['patch/body_diffuser','patch/body_upper','internalMesh','patch/wheel1','patch/wheel2','patch/wheel10']};
      window.picker=readerSelection({initial:[{pattern:'^wheel'},'/Root/hidden'],blocks:true,compact:true,label:'extractBlock.options.selectors',field:'regions',
        names:{get:()=>data,subscribe:()=>()=>{},load:async()=>data},inspect:async()=>data});
      void openDialog({title:'Blocks',enterSubmits:false,content:picker.element,actions:[{label:'Close',run:()=>null}]});
    })()`);
    const filter=async text=>s.evaluate(`(()=>{const e=document.querySelector('[aria-label="Filter available blocks"]');e.value=${JSON.stringify(text)};e.dispatchEvent(new Event('input',{bubbles:true}))})()`);
    const chip=name=>`.reader-choices [data-name="${name}"]`;
    const values=()=>s.evaluate('picker.read()');
    await filter('wheel'); await s.clickSelector('[data-action=deselect-shown]');
    assert.equal((await values())[0].pattern,'^wheel');
    assert.ok((await values()).includes('/Root/hidden'));
    assert.equal(await s.evaluate(`document.querySelectorAll('.reader-choices [aria-pressed=true]').length`),0);
    await s.clickSelector('[data-action=select-shown]');
    assert.deepEqual(await values(),[{pattern:'^wheel'},'/Root/hidden']);
    await s.clickSelector('[data-action=select-all]');
    assert.ok((await values()).includes('//internalMesh'),'Select All includes filtered-out names');
    await s.clickSelector('[data-action=deselect-all]'); assert.equal(await values(),undefined);
    await filter('body'); await s.clickSelector('[data-action=select-shown]');
    assert.deepEqual(await values(),['//body_diffuser','//body_upper']);
    await s.clickSelector('[data-action=deselect-all]'); await filter('');
    await s.clickSelector(chip('body_upper'));
    await s.evaluate(`document.querySelector(${JSON.stringify(chip('wheel2'))}).dispatchEvent(new MouseEvent('click',{bubbles:true,shiftKey:true}))`);
    assert.deepEqual(await values(),['//body_upper','//internalMesh','//wheel1','//wheel2']);
    await s.evaluate(`document.querySelector(${JSON.stringify(chip('wheel1'))}).dispatchEvent(new MouseEvent('click',{bubbles:true,ctrlKey:true}))`);
    assert.ok(!(await values()).includes('//wheel1'));
    await s.clickSelector('[data-action=deselect-all]');
    await s.evaluate(`document.querySelector(${JSON.stringify(chip('internalMesh'))}).focus()`);
    await s.key(' '); assert.deepEqual(await values(),['//internalMesh']);
    await s.key(' '); assert.equal(await values(),undefined);
    const box=await s.evaluate(`(()=>{const r=document.querySelector('.reader-choices').getBoundingClientRect();return {from:[r.left+1,r.top+1],to:[r.right-2,r.bottom-2]}})()`);
    await s.drag(box.from,box.to);
    assert.equal((await values()).length,6,'real pointer box selects all intersected chips');
    assert.equal(await s.evaluate(`document.querySelector('.reader-selection-box')`),null);
    await filter('no matches');
    assert.equal(await s.evaluate(`document.querySelector('[data-action=select-shown]').disabled`),true);
    assert.equal((await values()).length,6);
    if(process.env.SCHEMAXIS_SELECTION_SCREENSHOT) {await filter('');await s.screenshot(process.env.SCHEMAXIS_SELECTION_SCREENSHOT);}
    assert.deepEqual(s.exceptions,[]);assert.deepEqual(s.consoleErrors,[]);
  } finally {await s.close();}
});
