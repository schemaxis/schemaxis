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
  await s.wait(`document.querySelector('.results-frame')?.contentWindow?.artifactViewer?.items.length===2`,'all outputs loaded in embedded viewer');
  assert.equal(await s.evaluate('studio.windows.active().type'),'results');
  assert.equal(await s.evaluate('document.querySelector(".results-frame").contentDocument.querySelectorAll(".card").length'),2);
  assert.ok(await s.evaluate('document.querySelector(".results-frame").src.includes('+JSON.stringify(collection)+')'));
  await s.evaluate(`(async()=>{const {setSetting}=await import('/shell/preferences.mjs');await setSetting(studio,{theme:'dark'});})()`);
  await s.wait(`document.querySelector('.results-frame').contentDocument.documentElement.dataset.theme==='dark'`,'Studio dark theme propagated');
  await s.evaluate(`(async()=>{const {setSetting}=await import('/shell/preferences.mjs');await setSetting(studio,{theme:'light'});})()`);
  await s.wait(`document.querySelector('.results-frame').contentDocument.documentElement.dataset.theme==='light'`,'Studio light theme propagated');
  await s.evaluate(`(()=>{const doc=document.querySelector('.results-frame').contentDocument;const filter=doc.querySelector('#type-filter');filter.value='image';filter.dispatchEvent(new Event('change'));})()`);
  assert.equal(await s.evaluate('document.querySelector(".results-frame").contentDocument.querySelectorAll(".card").length'),1);
  await s.evaluate(`(()=>{document.querySelector('.results-frame').contentDocument.querySelector('#theme').click();})()`);
  await s.wait(`studio.setting('theme')==='dark'&&document.documentElement.dataset.theme==='dark'`,'viewer theme preference updates Studio');
  await s.evaluate(`(()=>{const viewer=document.querySelector('.results-frame').contentWindow;viewer.artifactViewer.openFile(viewer.artifactViewer.items.find(item=>item.kind==='image'));})()`);
  await s.wait(`document.querySelector('.results-frame').contentDocument.querySelector('.detail-image')`,'individual image pane');
  await s.evaluate(`document.querySelector('.results-frame').contentDocument.querySelector('.pane-expand').click()`);
  await s.wait(`document.querySelector('.results-frame').classList.contains('results-frame-expanded')`,'expanded iframe bridge');
  assert.ok(await s.evaluate(`(()=>{const rect=document.querySelector('.results-frame').getBoundingClientRect();return rect.x===0&&rect.y===0&&Math.abs(rect.width-innerWidth)<2&&Math.abs(rect.height-innerHeight)<2;})()`),'expanded pane covers the browser area, including Studio chrome');
  await s.evaluate(`document.querySelector('.results-frame').contentDocument.querySelector('.pane-expand').click()`);
  await s.wait(`!document.querySelector('.results-frame').classList.contains('results-frame-expanded')`,'restore embedded frame');
  await s.evaluate(`studio.windows.close('results');true`);
  await s.wait(`document.querySelector('.dialog[aria-label="Close results?"]')`,'Studio tab close confirms');
  await s.key('Escape');assert.equal(await s.evaluate(`studio.windows.instances.has('results')`),true);
  await s.evaluate(`document.querySelector('.results-frame').contentDocument.querySelector('#close-viewer').click()`);
  await s.evaluate(`(()=>{const doc=document.querySelector('.results-frame').contentDocument;[...doc.querySelectorAll('.close-confirmation button')].find(button=>button.textContent==='Close viewer').click();})()`);
  await s.wait(`!studio.windows.instances.has('results')`,'confirmed viewer close closes Results without a second prompt');
  assert.equal(await s.evaluate(`document.querySelectorAll('.dialog').length`),0);
  assert.equal(s.exceptions.length,0,JSON.stringify(s.exceptions));
  assert.deepEqual(s.consoleErrors.filter(line=>/violates.*Content Security|Refused to (execute|load|frame)/i.test(line)),[]);
 }finally{await s.close();}
});
