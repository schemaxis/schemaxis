import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {launch} from './harness.mjs';

test('Studio embeds the shared local collection viewer, synchronises theme and opens all selected files',async()=>{
 const s=await launch({provider:'workflow-design'});
 try {
  await s.wait('Boolean(window.studio?.store.get().server)','Studio ready');
  const directory=join(s.workspace,'output');await mkdir(join(directory,'slices'),{recursive:true});
  await writeFile(join(directory,'slices','velocity_x_0.svg'),'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><rect width="100" height="50" fill="#66a"/></svg>');
  await writeFile(join(directory,'run.log'),'test result log');
  const collection=await s.evaluate(`(async()=>{const result=await studio.api.post('/artifact-viewer/api/open',{paths:[${JSON.stringify(directory)}]});studio.openResults({collection:result.id});return result.id;})()`);
  const viewer=`document.querySelector('.results-frame').contentWindow.artifactExplorer`;
  const doc=`document.querySelector('.results-frame').contentDocument`;
  await s.wait(`${viewer}?.collection?.items.length===2`,'all outputs loaded in embedded viewer');
  assert.equal(await s.evaluate('studio.windows.active().type'),'results');
  await s.evaluate(`(()=>{const app=${viewer};app.state.view='files';app.state.recursive=true;app.render();})()`);
  assert.equal(await s.evaluate(`${doc}.querySelectorAll('#main .tile[data-id]').length`),2);
  assert.ok(await s.evaluate('document.querySelector(".results-frame").src.includes('+JSON.stringify(collection)+')'));
  await s.evaluate(`(async()=>{const {setSetting}=await import('/shell/preferences.mjs');await setSetting(studio,{theme:'dark'});})()`);
  await s.wait(`${doc}.documentElement.dataset.theme==='dark'`,'Studio dark theme propagated');
  await s.evaluate(`(async()=>{const {setSetting}=await import('/shell/preferences.mjs');await setSetting(studio,{theme:'light'});})()`);
  await s.wait(`${doc}.documentElement.dataset.theme==='light'`,'Studio light theme propagated');
  await s.evaluate(`${viewer}.toggleFilter('type','"Images"')`);
  assert.equal(await s.evaluate(`${doc}.querySelectorAll('#main .tile[data-id]').length`),1);
  await s.evaluate(`${doc}.querySelector('[data-role=theme]').click()`);
  await s.wait(`studio.setting('theme')==='dark'&&document.documentElement.dataset.theme==='dark'`,'viewer theme preference updates Studio');
  await s.evaluate(`(()=>{const app=${viewer};const image=app.collection.items.find(item=>item.kind==='image');app.activate(image.id,[image.id]);})()`);
  await s.wait(`${doc}.querySelector('#viewer:not([hidden]) .zoom-image img')?.complete`,'individual image viewer');
  await s.evaluate(`${doc}.querySelector('[data-role=expand]').click()`);
  await s.wait(`document.querySelector('.results-frame').classList.contains('results-frame-expanded')`,'expanded iframe bridge');
  assert.ok(await s.evaluate(`(()=>{const rect=document.querySelector('.results-frame').getBoundingClientRect();return rect.x===0&&rect.y===0&&Math.abs(rect.width-innerWidth)<2&&Math.abs(rect.height-innerHeight)<2;})()`),'expanded viewer covers the browser area, including Studio chrome');
  await s.evaluate(`${doc}.querySelector('[data-role=expand]').click()`);
  await s.wait(`!document.querySelector('.results-frame').classList.contains('results-frame-expanded')`,'restore embedded frame');
  await s.evaluate(`studio.windows.close('results');true`);
  await s.wait(`document.querySelector('.dialog[aria-label="Close results?"]')`,'Studio tab close confirms');
  await s.key('Escape');assert.equal(await s.evaluate(`studio.windows.instances.has('results')`),true);
  await s.evaluate(`${doc}.querySelector('[data-role=close]').click()`);
  await s.wait(`${doc}.querySelector('.dialog')`,'viewer close confirms');
  await s.evaluate(`[...${doc}.querySelectorAll('.dialog button')].find(button=>button.textContent==='Close').click()`);
  await s.wait(`!studio.windows.instances.has('results')`,'confirmed viewer close closes Results without a second prompt');
  assert.equal(await s.evaluate(`document.querySelectorAll('.dialog').length`),0);
  assert.equal(s.exceptions.length,0,JSON.stringify(s.exceptions));
  assert.deepEqual(s.consoleErrors.filter(line=>/violates.*Content Security|Refused to (execute|load|frame)/i.test(line)),[]);
 }finally{await s.close();}
});
