// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {readdir,readFile,mkdir} from 'node:fs/promises';
import {join,relative} from 'node:path';
import {launch} from '../../src/schemaxis/studio_ui/tests/fixtures/editor/cdp.mjs';
const root=fileURLToPath(new URL('../../src/schemaxis_viewer/web/',import.meta.url));
async function choose(s,key,value){await s.evaluate(`(()=>{const n=document.querySelector('[aria-label="Filename '+${JSON.stringify(key)}+'"]');n.value=${JSON.stringify(JSON.stringify(value))};n.dispatchEvent(new Event('change'));})()`);}
const count=s=>s.evaluate('artifactViewer.groups.reduce((n,g)=>n+g.items.length,0)');
test('filename facets filter intersecting properties, decode labels and reset on replacement',async()=>{
  const s=await launch({root,path:'/index.html',width:1500,height:1000});
  try{
    await s.wait('Boolean(window.artifactViewer)','viewer ready');
    await s.evaluate(`(async()=>{
      const canvas=document.createElement('canvas');canvas.width=64;canvas.height=32;const c=canvas.getContext('2d');c.fillStyle='#49c9b7';c.fillRect(0,0,64,32);
      const url=canvas.toDataURL(),records=[];let i=0;
      for(const axis of ['X','Y'])for(const variable of ['U','p'])for(const model of ['on','off'])for(const pos of [0,.2])
        records.push({name:String(i++).padStart(6,'0')+'__kind_slice__axis_'+axis+'__pos_'+pos+'__var_'+variable+'__model_'+model+'.png',size:100,url});
      records.push({name:'000016__kind_image__var_wall.x5F.shear.png',size:100,url});
      await artifactViewer.openRecords(records);
    })()`);
    assert.equal(await count(s),17);
    assert.ok(await s.evaluate(`document.querySelector('[aria-label="Filename var"]').textContent.includes('wall_shear')`));
    await choose(s,'axis','X');await choose(s,'var','U');await choose(s,'model','on');
    assert.equal(await count(s),2);
    assert.equal(await s.evaluate('artifactViewer.groups[0].sequences.length'),1);
    assert.equal(await s.evaluate('artifactViewer.groups[0].sequences[0].inferred'),true);
    await s.evaluate(`document.querySelector('.card [data-select-file]').click()`);
    assert.match(await s.evaluate('document.querySelector("#inspector").textContent'),/Output number/);
    await s.evaluate(`[...document.querySelectorAll('button')].find(n=>n.textContent==='Clear properties').click()`);
    assert.equal(await count(s),17);
    await choose(s,'axis','X');
    await s.evaluate(`artifactViewer.openRecords([{name:'000100__kind_text__name_new.txt',size:3,url:'data:text/plain,new'}])`);
    assert.equal(await count(s),1);
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="Filename axis"]')===null`),true);
  }finally{await s.close();}
});

test('generated sample: checked metadata, intersecting groups and actual video decoding', {skip:!process.env.VIEWER_FIXTURE},async()=>{
  const folder=process.env.VIEWER_FIXTURE,records=[];
  async function visit(path){for(const row of await readdir(path,{withFileTypes:true})){if(row.name==='.output-index')continue;const file=join(path,row.name);if(row.isDirectory())await visit(file);else{const bytes=await readFile(file),mime=file.endsWith('.mp4')?'video/mp4':file.endsWith('.webm')?'video/webm':file.endsWith('.png')?'image/png':file.endsWith('.gif')?'image/gif':'application/octet-stream';records.push({name:relative(folder,file),size:bytes.length,url:`data:${mime};base64,${bytes.toString('base64')}`});}}}
  await visit(folder);
  const s=await launch({root,path:'/index.html',width:1600,height:1050});
  try{
    await s.wait('Boolean(window.artifactViewer)','viewer ready');
    await s.evaluate(`artifactViewer.openRecords(${JSON.stringify(records)})`);
    assert.equal(await s.evaluate('artifactViewer.issues.length'),0);
    assert.ok(await s.evaluate('artifactViewer.items.filter(i=>i.metadata?.spatial?.mapping==="pixel-edge-rays-to-slice-plane").length>=48'));
    await choose(s,'kind','slice');await choose(s,'axis','X');await choose(s,'var','U');await choose(s,'model','on');
    assert.equal(await count(s),4);
    if(process.env.VIEWER_SCREENSHOTS){await mkdir(process.env.VIEWER_SCREENSHOTS,{recursive:true});await s.screenshot(join(process.env.VIEWER_SCREENSHOTS,'filename-properties.png'));}
    await s.evaluate(`[...document.querySelectorAll('button')].find(n=>n.textContent==='Clear properties').click()`);
    for(const extension of ['mp4','webm']){
      await s.evaluate(`artifactViewer.openFile(artifactViewer.items.find(i=>i.name.endsWith('.${extension}')))`);
      await s.wait('document.querySelector("video")?.readyState>=2','decoded '+extension);
      assert.equal(await s.evaluate('document.querySelector("video").videoWidth'),480);
      await s.evaluate('document.querySelector("video").currentTime=.5');
      await s.wait('document.querySelector("video").currentTime>=.49','seek '+extension);
    }
  }finally{await s.close();}
});

test('native ParaView exports: checked planes and variable groups span both slice scenes', {skip:!process.env.PARAVIEW_FILENAME_FIXTURE},async()=>{
  const folder=process.env.PARAVIEW_FILENAME_FIXTURE,records=[];
  const receipt=JSON.parse(await readFile(join(folder,'verification.json'),'utf8'));
  for(const artifact of receipt.artifacts)for(const path of [artifact.file,artifact.file+'.metadata.json']){
    const bytes=await readFile(path),name=relative(folder,path),mime=path.endsWith('.png')?'image/png':'application/octet-stream';
    records.push({name,size:bytes.length,url:`data:${mime};base64,${bytes.toString('base64')}`});
  }
  const s=await launch({root,path:'/index.html',width:1600,height:1050});
  try{
    await s.wait('Boolean(window.artifactViewer)','viewer ready');
    await s.evaluate(`artifactViewer.openRecords(${JSON.stringify(records)})`);
    assert.equal(await s.evaluate('artifactViewer.issues.length'),0);
    assert.equal(await s.evaluate('artifactViewer.items.filter(i=>i.kind==="image"&&i.metadata?.spatial?.mapping==="pixel-edge-rays-to-slice-plane").length'),4);
    assert.equal(await s.evaluate('artifactViewer.groups.filter(g=>g.items.some(i=>i.kind==="image")).length'),2);
    assert.equal(await s.evaluate('artifactViewer.groups.flatMap(g=>g.sequences).filter(s=>s.axis==="x"&&s.items.length===2&&!s.inferred).length'),2);
    await choose(s,'var','U');assert.equal(await count(s),2);
    await s.wait('[...document.querySelectorAll(".card img")].filter(i=>i.complete&&i.naturalWidth===480).length===2','both native images decoded');
    if(process.env.VIEWER_SCREENSHOTS){await mkdir(process.env.VIEWER_SCREENSHOTS,{recursive:true});await s.screenshot(join(process.env.VIEWER_SCREENSHOTS,'native-filename-properties.png'));}
  }finally{await s.close();}
});
