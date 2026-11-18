// Copyright (C) 2026 David L. F. Gaden.
import test from 'node:test';
import assert from 'node:assert/strict';
import {launch} from './harness.mjs';

const click = (s, text) => s.evaluate(`(()=>{const d=[...document.querySelectorAll('.dialog')].at(-1);const b=[...d.querySelectorAll('button')].find(b=>b.textContent===${JSON.stringify(text)});if(!b||b.disabled)throw Error('Unavailable '+${JSON.stringify(text)});b.click();})()`);
const field = (s, label, value) => s.evaluate(`(()=>{const d=[...document.querySelectorAll('.dialog')].at(-1);const e=d.querySelector('[aria-label="'+${JSON.stringify(label)}+'"]');e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);

test('deferred volumes suggest names, respect user names, rename consumers and remain cancellable', {timeout:120000}, async()=>{
 const s=await launch({provider:'paraview'});
 try{
  await s.wait('window.studio?.store.get().server','Studio');
  await s.evaluate(`(async()=>{const {editVolume}=await import('/windows/spatial/volume-editor.mjs');
   window.doc={version:'schemaxis/1',nodes:[{id:'tires',filter:'sphere'}]};
   void editVolume(studio,{root:doc,source:{kind:'node',node:'tires'}}).then(value=>window.saved=value);})()`);
  await s.wait(`document.querySelector('.volume-actions .primary')?.disabled===false`,'deferred save');
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="Volume name"]').value`),'tires_extents');
  await click(s,'Inflate %');
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="Volume name"]').value`),'tires_extents_inflate');
  await field(s,'Volume name','clearance');await click(s,'Translate');
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="Volume name"]').value`),'clearance');
  await s.wait(`document.querySelector('.volume-actions .primary')?.disabled===false`,'save linked');
  await click(s,'Add volume');await s.wait('window.saved','saved expression');
  assert.match(await s.evaluate('saved.root.definitions.clearance.$expr'),/translate\(inflate\(extents\(`tires`\)/);
  assert.equal(await s.evaluate('studio.store.get().server.liveData.enabled'),false);
  await s.evaluate(`(async()=>{const {editVolume}=await import('/windows/spatial/volume-editor.mjs');const {entries}=await import('/windows/variables/model.mjs');
    saved.root.definitions.consumer={$expr:'clearance.mid'};saved.root.definitions.label='clearance';
    void editVolume(studio,{root:saved.root,previous:entries(saved.root).find(e=>e.name==='clearance')}).then(value=>window.renamed=value);})()`);
  await s.wait(`document.querySelector('.volume-actions .primary')?.disabled===false`,'editable existing');
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="Volume name"]').readOnly`),false);
  await field(s,'Volume name','tire-clearance');
  await s.wait(`document.querySelector('.volume-actions .primary')?.disabled===false`,'rename ready');
  await click(s,'Update volume');await s.wait('window.renamed','renamed');
  assert.equal(await s.evaluate('renamed.root.definitions.consumer.$expr'),'definitions.`tire-clearance`.mid');
  assert.equal(await s.evaluate('renamed.root.definitions.label'),'clearance');
  assert.equal(await s.evaluate('renamed.root.definitions.clearance'),undefined);
  assert.deepEqual(s.exceptions,[]);assert.deepEqual(s.consoleErrors,[]);
 }finally{await s.close();}
});

test('Live Data selection retains native objects across windows and frees them explicitly', {timeout:120000,skip:!process.env.SCHEMAXIS_PARAVIEW_ROOTS},async()=>{
 const s=await launch({provider:'paraview'});
 try{
  await s.wait('window.studio?.store.get().server','Studio');
  await s.evaluate(`studio.api.post('/api/setup',{action:'configure',provider:'paraview',role:'admin',location:${JSON.stringify(process.env.SCHEMAXIS_PARAVIEW_ROOTS?.split(':')[0])}})`);
  await s.evaluate(`(async()=>{const {openLiveData}=await import('/windows/spatial/live-data.mjs');
    window.doc={version:'schemaxis/1',nodes:[{id:'mesh',filter:'wavelet'},{id:'skin',filter:'surface',inputs:{input:'mesh'}}]};
    void openLiveData(studio,{root:doc});})()`);
  await s.wait(`document.querySelector('[aria-label="Load mesh"]')`,'source checklist');
  await s.evaluate(`document.querySelector('[aria-label="Load mesh"]').click()`);
  await click(s,'Enable selected Live Data');
  await s.wait(`document.querySelector('[aria-label="Live Data selection"]').textContent.includes('● Live Data')&&!document.querySelector('[aria-label="Live Data selection"]').textContent.includes('loading')`,'resident indicator').catch(async error=>{throw Error(error.message+' '+await s.evaluate(`document.querySelector('.dialog')?.textContent`));});
  await s.wait(`document.querySelector('.live-data-nodes')?.textContent.includes('loaded')`,'loaded source');
  assert.equal(await s.evaluate(`[...document.querySelectorAll('.dialog button')].find(b=>b.textContent==='Enable selected Live Data').disabled`),true);
  await s.evaluate(`(async()=>{window.first=await studio.api.post('/api/spatial',{action:'live_data_status'});})()`);
  await click(s,'Close');
  await s.evaluate(`(async()=>{const {editVolume}=await import('/windows/spatial/volume-editor.mjs');void editVolume(studio,{root:doc,source:{kind:'node',node:'mesh'}});})()`);
  await s.wait(`document.querySelector('[aria-label="Volume result"]')?.textContent.includes('(-10, -10, -10)')`,'cross-window cached bounds');
  await click(s,'Cancel volume');
  await s.evaluate(`(async()=>{const {openLiveData}=await import('/windows/spatial/live-data.mjs');void openLiveData(studio,{root:doc});})()`);
  await s.wait(`document.querySelector('[aria-label="Load skin"]')`,'reopen selection');
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="Load mesh"]').checked`),true);
  await s.evaluate(`document.querySelector('[aria-label="Load skin"]').click()`);await click(s,'Enable selected Live Data');
  await s.wait(`document.querySelector('.live-data-nodes')?.textContent.includes('skin · surface · loaded')`,'derived bounds');
  const details=await s.evaluate(`studio.api.post('/api/spatial',{action:'live_data_status'})`);
  assert.equal(details.sessions[0].pid,await s.evaluate('first.sessions[0].pid'));
  assert.deepEqual(details.sessions[0].lastLoad.created,['skin']);
  assert.deepEqual(details.sessions[0].lastLoad.updated,['skin']);
  if(process.env.SPATIAL_EVIDENCE)await s.screenshot(process.env.SPATIAL_EVIDENCE+'/live-data-selection.png');
  await click(s,'Disable all Live Data');
  await s.wait(`document.querySelector('[aria-label="Live Data selection"]').textContent==='○ Live Data off'`,'unloaded indicator');
  assert.equal((await s.evaluate(`studio.api.post('/api/spatial',{action:'spatial_eval',input:doc,expression:'extents(skin)'})`)).records[0].state,'resolved');
  await click(s,'Close');
  assert.deepEqual(s.exceptions,[]);assert.deepEqual(s.consoleErrors,[]);
 }finally{await s.close();}
});

test('Workbench Live Data opens a checklist even with one source', {timeout:90000}, async()=>{
 const s=await launch({provider:'paraview'});
 try{
  await s.wait('window.studio?.store.get().server','Studio');
  await s.evaluate(`(async()=>{const r=await studio.api.post('/api/documents',{action:'new',provider:'paraview',name:'Selection',document:{version:'schemaxis/1',nodes:[{id:'mesh',filter:'wavelet'}],scenes:[]}});await studio.refresh();studio.openDocument(r.id);})()`);
  await s.wait('studio.windows.active().window.store?.get().schema','Workbench');
  await s.clickSelector('[data-action="live"]');
  await s.wait(`document.querySelector('[aria-label="Load mesh"]')`,'checklist');
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="Load mesh"]').checked`),false);
  assert.equal(await s.evaluate('studio.store.get().server.liveData.enabled'),false);
  await click(s,'Close');
  assert.deepEqual(s.exceptions,[]);assert.deepEqual(s.consoleErrors,[]);
 }finally{await s.close();}
});

test('Spatial auto-resolves derived volumes from resident sources, with manual refresh preference', {timeout:120000,skip:!process.env.SCHEMAXIS_PARAVIEW_ROOTS},async()=>{
 const s=await launch({provider:'paraview'});
 try{
  await s.wait('window.studio?.store.get().server','Studio');
  await s.evaluate(`studio.api.post('/api/setup',{action:'configure',provider:'paraview',role:'admin',location:${JSON.stringify(process.env.SCHEMAXIS_PARAVIEW_ROOTS?.split(':')[0])}})`);
  await s.evaluate(`(async()=>{
    window.doc={version:'schemaxis/1',nodes:[{id:'mesh',filter:'wavelet'},{id:'skin',filter:'surface',inputs:{input:'mesh'}},{id:'other',filter:'wavelet'}],definitions:{region:{$expr:'extents(skin)'}}};
    const started=await studio.api.post('/api/spatial',{action:'live_data_load',input:doc,nodes:['mesh']});
    const done=await studio.api.waitForJob(started.job);if(done.status!=='succeeded')throw Error(JSON.stringify(done));
    window.originalPid=done.result.liveData.sessions[0].pid;
    const {manageSpatial}=await import('/windows/spatial/panel.mjs');window.openSpatial=()=>manageSpatial(studio,{root:doc,commit:()=>{}});void openSpatial();
  })()`);
  await s.wait(`document.querySelector('[aria-label="Show definitions.region"]')?.disabled===false`,'automatic derived volume');
  let status=await s.evaluate(`studio.api.post('/api/spatial',{action:'live_data_status'})`);
  assert.equal(status.sessions[0].pid,await s.evaluate('originalPid'));
  assert.deepEqual(status.sessions[0].lastLoad.created,['skin']);
  assert.deepEqual(status.sessions[0].lastLoad.updated,['skin']);
  assert.ok(!status.sessions[0].nodes.includes('other'));
  await click(s,'Cancel');
  await s.evaluate(`void openSpatial()`);
  await s.wait(`document.querySelector('[aria-label="Show definitions.region"]')?.disabled===false`,'reopened resolved volume');
  assert.equal(await s.evaluate(`[...document.querySelectorAll('.dialog button')].some(b=>b.textContent==='Enable Live Data for extents')`),false);
  await click(s,'Cancel');
  await s.evaluate(`(async()=>{doc.nodes.push({id:'preview',filter:'surface',inputs:{input:'skin'}});const {editVolume}=await import('/windows/spatial/volume-editor.mjs');void editVolume(studio,{root:doc,source:{kind:'node',node:'preview'}});})()`);
  await s.wait(`document.querySelector('[aria-label="Volume result"]')?.textContent.includes('(-10, -10, -10)')`,'automatic new-volume preview');
  assert.equal((await s.evaluate(`studio.api.post('/api/spatial',{action:'live_data_status'})`)).sessions[0].pid,await s.evaluate('originalPid'));
  await click(s,'Cancel volume');
  await s.evaluate(`(async()=>{await studio.api.post('/api/settings',{action:'write',role:'user',values:{'spatial.autoRefresh':false}});await studio.refresh();doc.nodes.push({id:'triangles',filter:'triangulate',inputs:{input:'skin'}});doc.definitions.region={$expr:'extents(triangles)'};void openSpatial();})()`);
  await s.wait(`document.querySelector('.spatial-list')?.textContent.includes('needs-data')`,'manual mode unresolved');
  status=await s.evaluate(`studio.api.post('/api/spatial',{action:'live_data_status'})`);
  assert.ok(!status.sessions[0].nodes.includes('triangles'));
  await click(s,'Refresh from Live Data');
  await s.wait(`document.querySelector('[aria-label="Show definitions.region"]')?.disabled===false`,'manual refresh volume');
  status=await s.evaluate(`studio.api.post('/api/spatial',{action:'live_data_status'})`);
  assert.equal(status.sessions[0].pid,await s.evaluate('originalPid'));
  assert.deepEqual(status.sessions[0].lastLoad.updated,['triangles']);
  await click(s,'Cancel');
  await s.evaluate(`studio.api.post('/api/spatial',{action:'live_data_unload'})`);
  await s.evaluate(`void openSpatial()`);
  await s.wait(`document.querySelector('[aria-label="Show definitions.region"]')?.disabled===false`,'cached after unload');
  assert.equal(await s.evaluate(`[...document.querySelectorAll('.dialog button')].find(b=>b.textContent==='Refresh from Live Data').disabled`),true);
  await click(s,'Cancel');
  assert.deepEqual(s.exceptions,[]);assert.deepEqual(s.consoleErrors,[]);
 }finally{await s.close();}
});
