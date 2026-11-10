// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {readdir,readFile,mkdir} from 'node:fs/promises';
import {join,relative} from 'node:path';
import {parseFilename} from '../../src/schemaxis_viewer/web/filename.mjs';
import {launch} from '../../src/schemaxis/studio_ui/tests/fixtures/editor/cdp.mjs';
const root=fileURLToPath(new URL('../../src/schemaxis_viewer/web/',import.meta.url));
const sample=fileURLToPath(new URL('../../examples/viewer-test/',import.meta.url));
const choose=(s,label,value)=>s.evaluate(`(()=>{const n=document.querySelector('[aria-label="'+${JSON.stringify(label)}+'"]');n.value=${JSON.stringify(value)};n.dispatchEvent(new Event('change'));})()`);
const click=(s,text)=>s.evaluate(`[...document.querySelectorAll('button')].find(n=>n.textContent===${JSON.stringify(text)}).click()`);
async function records({includeLegacy=false}={}){
  const result=[];
  async function visit(path){for(const row of await readdir(path,{withFileTypes:true})){if(row.name==='.output-index')continue;const file=join(path,row.name);if(row.isDirectory()){if(includeLegacy)await visit(file);}else{const bytes=await readFile(file),mime=file.endsWith('.png')?'image/png':file.endsWith('.webm')?'video/webm':'application/octet-stream';result.push({name:relative(sample,file),relativePath:relative(sample,file),scope:'sample',rootLabel:'sample',size:bytes.length,url:`data:${mime};base64,${bytes.toString('base64')}`});}}}
  await visit(sample);return result;
}
async function open(s){await s.wait('Boolean(window.artifactViewer)','ready');await s.evaluate(`artifactViewer.openRecords(${JSON.stringify(await records())})`);assert.equal(await s.evaluate('artifactViewer.issues.length'),0);}

test('flat files group and intersect by filename keys with every companion removed',async()=>{
  const s=await launch({root,path:'/index.html',width:1550,height:1050});
  try{
    await s.wait('Boolean(window.artifactViewer)','ready');
    const payloads=(await records()).filter(record=>record.name.endsWith('.png'));
    await s.evaluate(`artifactViewer.openRecords(${JSON.stringify(payloads)})`);
    assert.equal(await s.evaluate('artifactViewer.items.some(i=>i.metadata)'),false);
    await choose(s,'Filename kind','"slice"');
    await choose(s,'Grouping level 1','var');await choose(s,'Grouping level 2','axis');await choose(s,'Grouping level 3','model');
    assert.ok(await s.evaluate(`[...document.querySelectorAll('#library button')].some(n=>n.textContent==='U · 18')`));
    await choose(s,'Grouping level 1','axis');await choose(s,'Grouping level 2','var');await choose(s,'Grouping level 3','model');
    assert.ok(await s.evaluate(`[...document.querySelectorAll('#library button')].some(n=>n.textContent==='X · 12')`),'the same files also group by axis before variable');
    await choose(s,'Filename var','"U"');await choose(s,'Filename axis','"X"');await choose(s,'Filename model','"on"');
    assert.equal(await s.evaluate('artifactViewer.groups.flatMap(g=>g.items).length'),3);
    assert.equal(await s.evaluate('artifactViewer.groups[0].sequences[0].inferred'),true);
    assert.deepEqual(await s.evaluate('artifactViewer.groups[0].items.map(i=>i.filename.properties.pos)'),[.1,.4,.9]);
    assert.equal(s.exceptions.length,0,JSON.stringify(s.exceptions));
  }finally{await s.close();}
});

test('acceptance folder: hierarchy, matching selection, photo series, spatial planes and mixed media',async()=>{
  const s=await launch({root,path:'/index.html',width:1550,height:1050});
  try{
    await open(s);
    assert.ok((await records()).every(r=>!r.name.includes('/')),'all artifacts share one folder');
    assert.ok((await records()).filter(r=>r.name!=='README.txt'&&!r.name.endsWith('.metadata.json')).every(r=>parseFilename(r.name)),'every payload uses the real key-value pattern');
    assert.equal(await s.evaluate('artifactViewer.items.some(i=>i.metadata?.group||i.metadata?.properties||i.metadata?.sequence)'),false,'group labels come from filenames');
    await choose(s,'Filename kind','"slice"');
    await choose(s,'Grouping level 1','var');await choose(s,'Grouping level 2','axis');await choose(s,'Grouping level 3','model');
    assert.ok(await s.evaluate('document.querySelectorAll(".hierarchy-branch").length>=8'));
    await s.evaluate(`window.uBranch=()=>[...document.querySelectorAll('.hierarchy-branch')].find(n=>n.querySelector('button').textContent==='U · 18');uBranch().open=false;document.querySelector('#deselect-all').click();`);
    assert.equal(await s.evaluate('uBranch().open'),false,'collapsed branches survive selection changes');
    await s.evaluate('uBranch().open=true');
    if(process.env.VIEWER_SCREENSHOTS){await mkdir(process.env.VIEWER_SCREENSHOTS,{recursive:true});await s.screenshot(join(process.env.VIEWER_SCREENSHOTS,'acceptance-hierarchy.png'));}
    await s.evaluate(`[...document.querySelectorAll('#library button')].find(n=>n.textContent==='U · 18').click()`);
    assert.equal(await s.evaluate('artifactViewer.groups.flatMap(g=>g.items).length'),18);
    await s.evaluate('document.querySelector("#deselect-all").click()');
    await choose(s,'Filename axis','"X"');
    assert.equal(await s.evaluate('artifactViewer.groups.flatMap(g=>g.items).length'),6);
    await choose(s,'Filename model','"on"');
    await s.evaluate('document.querySelector("#select-matching").click()');
    assert.equal(await s.evaluate('[...document.querySelectorAll("[aria-label^=\\"Show preview\\"]")].filter(n=>n.checked).length'),3);
    await s.evaluate(`document.querySelector('#filter').value='pos_0.1';document.querySelector('#filter').dispatchEvent(new Event('input'));document.querySelector('#deselect-matching').click();document.querySelector('#filter').value='';document.querySelector('#filter').dispatchEvent(new Event('input'));`);
    assert.equal(await s.evaluate('[...document.querySelectorAll("[aria-label^=\\"Show preview\\"]")].filter(n=>n.checked).length'),2,'matching selection honours the name filter');
    await click(s,'Clear properties');await click(s,'All groups');await choose(s,'Grouping level 1','');
    await s.evaluate('document.querySelector("#select-all").click()');
    // Intersect independent filename keys while every payload is in one folder.
    await choose(s,'Filename var','"U"');await choose(s,'Filename axis','"X"');await choose(s,'Filename model','"on"');
    assert.equal(await s.evaluate('artifactViewer.groups.flatMap(g=>g.items).length'),3);
    await click(s,'Clear properties');
    await s.evaluate('document.querySelector(".all-outputs").click()');
    await s.evaluate('document.querySelector("[data-mode=\\"3d\\"]").click()');
    await s.wait(`Boolean(document.querySelector('[aria-label="Show all selected image planes"]'))`,'3D scene controls');
    await s.evaluate('window.planeCount=0;window.originalSetData=artifactScene.setData;artifactScene.setData=(planes,...args)=>{window.planeCount=planes.length;return originalSetData(planes,...args);};');
    await s.evaluate('document.querySelector("[aria-label=\\"Show all selected image planes\\"]").click()');
    await s.wait('window.planeCount===36','all registered planes');
    if(process.env.VIEWER_SCREENSHOTS){await s.wait('document.querySelectorAll(".compact-axis").length>0','slice controls');await s.screenshot(join(process.env.VIEWER_SCREENSHOTS,'acceptance-spatial.png'));}
    await choose(s,'Filename series','"photos"');
    await s.evaluate('document.querySelector("[data-mode=sequences]").click()');
    assert.match(await s.evaluate('document.querySelector(".sequence-panel").textContent'),/Photo series/);
    await s.evaluate('document.querySelector("[aria-label=\\"INDEX next frame\\"]").click()');
    assert.match(await s.evaluate('document.querySelector(".sequence-footer").textContent'),/2 \/ 4/);
    await click(s,'Clear properties');await s.evaluate('document.querySelector(".all-outputs").click()');
    for(const extension of ['csv','tsv']){
      await s.evaluate(`artifactViewer.openFile(artifactViewer.items.find(i=>i.name.endsWith('.${extension}')))`);
      await s.wait('document.querySelectorAll("tbody tr").length===100','paged table');
      assert.ok(await s.evaluate('Boolean(document.querySelector(".chart"))'));
    }
    await s.evaluate('artifactViewer.openFile(artifactViewer.items.find(i=>i.name.endsWith(".webm")))');
    await s.wait('document.querySelector("video")?.readyState>=2','video decode');
    if(process.env.VIEWER_SCREENSHOTS){await mkdir(process.env.VIEWER_SCREENSHOTS,{recursive:true});await s.screenshot(join(process.env.VIEWER_SCREENSHOTS,'acceptance-video.png'));}
    assert.equal(s.exceptions.length,0,JSON.stringify(s.exceptions));
  }finally{await s.close();}
});

test('read-only text: highlighted Find, wrap navigation, capture fields and invalid regex recovery',async()=>{
  const s=await launch({root,path:'/index.html',width:1550,height:1050});
  try{
    await open(s);await s.evaluate('artifactViewer.openFile(artifactViewer.items.find(i=>i.filename?.properties.name==="solver"))');
    await s.wait('Boolean(document.querySelector("[aria-label=\\"Search text\\"]"))','text pane');
    await s.evaluate(`(()=>{const n=document.querySelector('[aria-label="Search text"]');n.value='U=';n.dispatchEvent(new Event('input'));})()`);
    await s.wait('document.querySelector(".text-tools").textContent.includes("450 matches")','find results');
    await click(s,'Previous match');
    assert.match(await s.evaluate('document.querySelector(".current-match").parentElement.parentElement.textContent'),/451Time=44.9/);
    await click(s,'Next match');assert.match(await s.evaluate('document.querySelector(".current-match").parentElement.parentElement.textContent'),/2Time=0.0/);
    await choose(s,'Text search mode','grep');
    await s.evaluate(`document.querySelector('[aria-label="Use regular expression"]').click()`);
    await s.evaluate(`(()=>{const n=document.querySelector('[aria-label="Search text"]');n.value=${JSON.stringify(String.raw`Time=(?<time>[\d.]+) U=(?<velocity>[\d.]+) residual=([\d.]+)`)};n.dispatchEvent(new Event('input'));})()`);
    await s.wait('document.querySelectorAll(".capture-fields input").length===3','capture columns');
    assert.deepEqual(await s.evaluate('[...document.querySelectorAll(".grep-table th")].map(n=>n.textContent)'),['Line','Column','Match','time','velocity','Group 3','Text']);
    assert.match(await s.evaluate('document.querySelector(".grep-table tbody tr").textContent'),/0.02.001.00000/);
    await s.evaluate('document.querySelector("[aria-label=\\"Capture velocity\\"]").click()');
    assert.equal(await s.evaluate('document.querySelectorAll(".grep-table th").length'),6);
    await s.evaluate(`window.createOriginalURL=URL.createObjectURL;URL.createObjectURL=blob=>{window.exportedCSV=blob.text();return createOriginalURL(blob);};`);
    await click(s,'Export matches CSV');
    const exported=await s.evaluate('window.exportedCSV');
    assert.ok(exported.startsWith('"Line","Column","Match","time","Group 3","Text"'));
    assert.equal(exported.split('\r\n').length,451);
    await s.evaluate('URL.createObjectURL=window.createOriginalURL');
    if(process.env.VIEWER_SCREENSHOTS){await mkdir(process.env.VIEWER_SCREENSHOTS,{recursive:true});await s.screenshot(join(process.env.VIEWER_SCREENSHOTS,'acceptance-grep.png'));}
    await s.evaluate(`(()=>{const n=document.querySelector('[aria-label="Search text"]');n.value='(';n.dispatchEvent(new Event('input'));})()`);
    await s.wait('Boolean(document.querySelector(".warning"))','invalid regex');
    await s.evaluate(`(()=>{const n=document.querySelector('[aria-label="Search text"]');n.value='^WARNING';n.dispatchEvent(new Event('input'));})()`);
    await s.wait('document.querySelector(".text-tools").textContent.includes("1 matches")','valid search recovers');
    assert.equal(await s.evaluate('document.querySelectorAll(".warning").length'),0);
    assert.equal(await s.evaluate('document.querySelectorAll("textarea,[contenteditable=true]").length'),0);
    assert.equal(s.exceptions.length,0,JSON.stringify(s.exceptions));
  }finally{await s.close();}
});
