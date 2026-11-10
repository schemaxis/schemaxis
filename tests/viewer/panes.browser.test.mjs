import test from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {mkdir} from 'node:fs/promises';
import {launch} from '../../src/schemaxis/studio_ui/tests/fixtures/editor/cdp.mjs';
const root=fileURLToPath(new URL('../../src/schemaxis_viewer/web/',import.meta.url));
const click=(s,selector)=>s.evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
const bounds=(s,selector)=>s.evaluate(`(()=>{const rect=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:rect.x,y:rect.y,width:rect.width,height:rect.height};})()`);

test('Studio-style theme toggle, pane height, browser-area expansion, restore and confirmed close',async()=>{
 const s=await launch({root,path:'/index.html',width:1500,height:1000});
 try {
  await s.wait('Boolean(window.artifactViewer)','ready');
  await s.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:'dark'}]});
  await s.wait(`document.documentElement.dataset.theme==='dark'`,'initial system theme follows OS');
  assert.equal(await s.evaluate('document.querySelector("#theme").tagName'),'BUTTON');
  assert.equal(await s.evaluate('document.querySelector("#theme").dataset.icon'),'sun');
  await click(s,'#theme');assert.equal(await s.evaluate('document.documentElement.dataset.theme'),'light');
  await s.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:'light'}]});
  await s.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:'dark'}]});
  assert.equal(await s.evaluate('document.documentElement.dataset.theme'),'light','an explicit toggle takes precedence over system changes');
  await click(s,'#demo');await s.wait('artifactViewer.items.length===37','sample');await click(s,'[data-mode="xyz"]');
  await s.evaluate(`(()=>{const height=document.querySelector('[aria-label="X slices view height"]');height.value=420;height.dispatchEvent(new Event('input'));})()`);
  assert.equal(Math.round((await bounds(s,'.sequence-panel .sequence-image')).height),420);
  await s.evaluate(`document.querySelector('[aria-label="Resize X slices vertically"]').scrollIntoView({block:'center'})`);
  const drag=await bounds(s,'[aria-label="Resize X slices vertically"]');
  await s.send('Input.dispatchMouseEvent',{type:'mousePressed',x:drag.x+drag.width/2,y:drag.y+drag.height/2,button:'left',clickCount:1});
  await s.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:drag.x+drag.width/2,y:drag.y+drag.height/2+50,button:'left',buttons:1});
  await s.send('Input.dispatchMouseEvent',{type:'mouseReleased',x:drag.x+drag.width/2,y:drag.y+drag.height/2+50,button:'left',clickCount:1});
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="X slices view height"]').value`),'470');
  if(process.env.VIEWER_SCREENSHOTS){await mkdir(process.env.VIEWER_SCREENSHOTS,{recursive:true});await s.screenshot(process.env.VIEWER_SCREENSHOTS+'/xyz-resized.png');}
  const originalScroll=await s.evaluate('document.querySelector("#main").scrollTop');
  await click(s,'[aria-label="Expand X slices"]');
  const expanded=await bounds(s,'.pane-expanded');assert.deepEqual(expanded,{x:0,y:0,width:1500,height:1000});
  await s.evaluate(`(()=>{const slider=document.querySelector('[aria-label="X slice slider"]');slider.value=8;slider.dispatchEvent(new Event('input'));})()`);
  assert.equal(await s.evaluate(`document.querySelector('.pane-expanded .sequence-footer').textContent.includes('X = 1.6')`),true);
  await s.key('Escape');assert.equal(await s.evaluate('document.querySelectorAll(".pane-expanded").length'),0);
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="X slices view height"]').value`),'470');
  assert.ok(Math.abs(await s.evaluate('document.querySelector("#main").scrollTop')-originalScroll)<2,'restoring a pane preserves browsing position');
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="X slice slider"]').value`),'8');
  await click(s,'[data-mode="3d"]');await s.wait('Boolean(window.artifactScene)','3D pane');
  await click(s,'[aria-label="Expand 3D space"]');if(process.env.VIEWER_SCREENSHOTS)await s.screenshot(process.env.VIEWER_SCREENSHOTS+'/expanded-3d.png');await s.key('Escape');
  await click(s,'[data-mode="xyz"]');assert.equal(await s.evaluate(`document.querySelector('[aria-label="X slices view height"]').value`),'470','pane heights survive view changes');
  await s.evaluate('artifactViewer.openFile(artifactViewer.items.find(item=>item.name.endsWith("velocity_x_000.png")))');
  await s.wait('Boolean(document.querySelector(".detail-image"))','image viewer');
  await click(s,'[aria-label="Expand velocity_x_000.png"]');await click(s,'[aria-label="Restore velocity_x_000.png"]');
  await click(s,'#close-viewer');assert.equal(await s.evaluate('artifactViewer.items.length'),37,'opening the confirmation does not close anything');
  await s.key('Escape');await s.wait('!document.querySelector(".close-confirmation")','close confirmation cancelled');
  await click(s,'#close-viewer');await s.evaluate(`[...document.querySelectorAll('.close-confirmation button')].find(button=>button.textContent==='Close viewer').click()`);
  assert.equal(await s.evaluate('artifactViewer.items.length'),0);assert.match(await s.evaluate('document.querySelector("#content").textContent'),/Viewer closed/);
  await s.evaluate(`[...document.querySelectorAll('#content button')].find(button=>button.textContent==='Open viewer').click()`);
  assert.equal(await s.evaluate('document.body.classList.contains("viewer-closed")'),false);
  assert.equal(s.exceptions.length,0,JSON.stringify(s.exceptions));
 }finally{await s.close();}
});
