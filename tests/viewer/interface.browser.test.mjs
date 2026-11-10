import test from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {mkdir} from 'node:fs/promises';
import {launch} from '../../src/schemaxis/studio_ui/tests/fixtures/editor/cdp.mjs';
const root=fileURLToPath(new URL('../../src/schemaxis_viewer/web/',import.meta.url));
const shots=process.env.VIEWER_SCREENSHOTS;
const choose=(s,selector)=>s.evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
const rect=(s,selector)=>s.evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right};})()`);

test('interface audit: discover sequences, pin location, select explicitly and restore browsing context',async()=>{
  const s=await launch({root,path:'/index.html',width:1500,height:1000});
  try {
    await s.wait('Boolean(window.artifactViewer)','viewer startup');
    await choose(s,'#demo');await s.wait('artifactViewer.items.length===37','demo');
    assert.equal(await s.evaluate('document.querySelectorAll("[data-mode]").length'),4);
    assert.equal(await s.evaluate('document.querySelectorAll("[data-jump-section]").length'),4);
    assert.match(await s.evaluate('document.querySelector("[data-mode=sequences]").textContent'),/3 image sequences/);
    assert.ok(await s.evaluate(`[...document.querySelectorAll('input[aria-label^="Show preview"]')].every(input=>input.getClientRects().length>0)`),'preview checkboxes are directly available');
    await choose(s,'[aria-label="Select velocity_x_004.png"]');
    const selected=await s.evaluate('document.querySelector("#location").textContent');
    assert.match(selected,/X = 0.8/);
    await s.evaluate(`document.querySelector('[aria-label="Select velocity_x_001.png"]').dispatchEvent(new MouseEvent('mouseenter'))`);
    assert.equal(await s.evaluate('document.querySelector("#location").textContent'),selected,'hover must not replace selection');
    const before=await rect(s,'#location');
    await s.evaluate('document.querySelector("#main").scrollTop=document.querySelector("#main").scrollHeight');
    const after=await rect(s,'#location');assert.equal(after.top,before.top);assert.ok(after.bottom<1000);
    await choose(s,'[data-jump-section="2"]');
    await s.wait(`(()=>{const section=document.querySelector('[data-section-index="2"]').getBoundingClientRect(),nav=document.querySelector('#workspace-controls').getBoundingClientRect();return section.top>=nav.bottom-3&&section.top<nav.bottom+50;})()`,'Z section reached without scanning X/Y');
    await s.evaluate(`document.querySelector('[aria-label="Select velocity_z_009.png"]').focus()`);await s.key(' ',0,'Space');
    await s.wait(`document.querySelector('#location').textContent.includes('Z = 0.9')`,'keyboard selects a thumbnail');
    assert.match(await s.evaluate('document.querySelector("#location").textContent'),/Z = 0.9/);
    await choose(s,'[aria-label="Animate Z slices"]');
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="Z slice slider"]').value`),'9','Animate starts at the selected gallery slice');
    await choose(s,'[data-mode=gallery]');
    if(shots){await mkdir(shots,{recursive:true});await s.screenshot(shots+'/gallery-scrolled.png');}
    await s.evaluate(`(()=>{const n=document.querySelector('[aria-label="Gallery image size"]');n.value=300;n.dispatchEvent(new Event('input'));})()`);
    const saved=await s.evaluate('document.querySelector("#main").scrollTop');
    await choose(s,'.location-open');await s.wait('Boolean(document.querySelector(".detail-image"))','individual image');
    assert.equal(await s.evaluate(`document.querySelectorAll('[aria-label="Select next gallery slice"]').length`),0,'detail selection cannot diverge from its enlarged image');
    await s.evaluate(`[...document.querySelectorAll('button')].find(b=>b.textContent==='← Collection').click()`);
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="Gallery image size"]').value`),'300');
    assert.ok(Math.abs(await s.evaluate('document.querySelector("#main").scrollTop')-saved)<3,'gallery scroll is restored');
    assert.equal(await s.evaluate('document.querySelector(".card.selected").dataset.fileId'),await s.evaluate('artifactViewer.items.find(i=>i.name.endsWith("velocity_z_009.png")).id'));
    for(const width of [1100,900,600]) {
      await s.send('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});
      await s.wait(`document.querySelector('#location').parentElement.id===${JSON.stringify(width<=1050?'compact-location':'')}`,'responsive locator moves to pinned area');
      await s.evaluate('document.querySelector("#main").scrollTop=document.querySelector("#main").scrollHeight');
      const location=await rect(s,'#location');assert.ok(location.top>=0&&location.bottom<1000,`locator stays visible at ${width}px`);
      assert.ok(await s.evaluate(`document.documentElement.scrollWidth<=${width}`));
      if(shots)await s.screenshot(shots+`/gallery-${width}.png`);
    }
    await s.send('Emulation.setDeviceMetricsOverride',{width:1500,height:1000,deviceScaleFactor:1,mobile:false});
    await choose(s,'[aria-label="Animate Y slices"]');await s.wait('Boolean(document.querySelector(".sequence-panel"))','direct animation');
    assert.equal(await s.evaluate('artifactViewer.mode'),'sequences');
    assert.equal(await s.evaluate('document.querySelector(".sequence-panel h2").textContent'),'Y slices');
    await choose(s,'[data-mode="3d"]');await s.wait('document.querySelectorAll(".compact-axis").length===3','compact 3D controls');
    assert.equal(await s.evaluate(`document.querySelector('.compact-axis').textContent.includes('null')`),false,'compact controls must not render placeholder text');
    assert.equal(await s.evaluate(`document.querySelector('.location-open').textContent`),'Open X image');
    assert.equal(await s.evaluate('document.querySelectorAll("#content .sequence-image").length'),0,'3D does not repeat the image triptych');
    assert.equal(await s.evaluate('document.querySelector("[data-mesh-option]").hidden'),true,'mesh controls hidden for bounds-only data');
    assert.equal(await s.evaluate(`document.querySelectorAll('[aria-label="Spatial coordinate frame"]').length`),0,'single-frame selector omitted');
    await choose(s,'[data-mode=gallery]');
    await choose(s,'[aria-label="Show sequence Z slices"]');
    await choose(s,'[data-mode=xyz]');
    assert.ok(await s.evaluate('Boolean(document.querySelector(".restore-previews"))'),'hidden data can be restored without going back to Gallery');
    await choose(s,'.restore-previews');
    assert.equal(await s.evaluate('document.querySelectorAll(".sequence-image").length'),3);
    assert.equal(await s.evaluate('[...document.querySelectorAll(".transport button")].filter(n=>n.getClientRects().length).length'),12,'one compact transport per scope');
    await choose(s,'.sequence-panel .playback-options summary');
    assert.ok(await s.evaluate(`document.querySelector('[aria-label="X play backward"]').getClientRects().length>0`));
    await s.evaluate(`[...document.querySelectorAll('#library button')].find(b=>b.textContent==='Run records').click()`);
    assert.equal(await s.evaluate('document.querySelector("[data-mode=sequences]").disabled'),true);
    assert.match(await s.evaluate('document.querySelector("[data-mode=sequences]").textContent'),/Needs an image sequence/);
    assert.equal(s.exceptions.length,0,JSON.stringify(s.exceptions));
  } finally {await s.close();}
});
