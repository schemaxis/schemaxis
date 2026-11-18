// Copyright (C) 2026 David L. F. Gaden.
// Real Studio transport and host expressions; supplied extents are not native evidence.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile, mkdir, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {launch} from './harness.mjs';

const car = JSON.parse(await readFile(new URL('../../../../examples/paraview-car/input.json', import.meta.url), 'utf8'));
const active = 'studio.windows.active().window';
const fill = 'document.querySelector(".sx-fill-popover:not([hidden])")';
const shots = process.env.STUDIO_SCREENSHOTS;
function hostRunRecords() {
  const root=fileURLToPath(new URL('../../../../',import.meta.url));
  return JSON.parse(execFileSync(process.env.STUDIO_PYTHON || 'python3',['-c',`
import json, tempfile
from pathlib import Path
from test_spatial_results import document, run, receipt
from schemaxis import spatial_results
value = document()
value['scenes'] = [{'id': 'view', 'geometry': ['cut', 'wheels']}]
master, states = run(value)
saved = receipt(master, states)
spatial_results.verify(master, saved, 'browser-host-fixture')
with tempfile.TemporaryDirectory() as folder:
    (Path(folder) / 'verification.json').write_text(json.dumps(saved))
    print(json.dumps({'root': value, 'response': spatial_results.run_records(value, folder),
                      'draft': {'identity': 'host-run', 'revision': 11}}))
`],{cwd:root,env:{...process.env,PYTHONPATH:join(root,'src')+':'+join(root,'tests/unit')},encoding:'utf8',timeout:30000}));
}
async function button(s, label, container = '.dialog') {
  const q = `[...document.querySelectorAll(${JSON.stringify(container + ' button')})].find(b=>b.textContent.trim()===${JSON.stringify(label)}&&!b.disabled)`;
  await s.wait(q, label); await s.evaluate(`${q}.click()`);
}
async function field(s, label, value) {
  const q = `document.querySelector('[aria-label="${label}"]')`;
  await s.wait(q, label);
  await s.evaluate(`(()=>{const e=${q};e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}
async function open(s, document = {version:'schemaxis/1',nodes:[],scenes:[]}) {
  await s.wait('window.studio?.store.get().server', 'Studio');
  await s.evaluate(`(async()=>{
    const record=await studio.api.post('/api/documents',{action:'new',provider:'paraview',name:'Stage 3',document:${JSON.stringify(document)}});
    await studio.refresh();studio.openDocument(record.id);
    // Fail before dispatch if this authoring test accidentally requests native work.
    const post=studio.api.post.bind(studio.api);
    studio.api.post=(path,body)=>{
      if(['/api/inspect-input','/api/command','/api/preview'].includes(path)||body?.action==='spatial_load'||['run','preview-live'].includes(body?.command))throw Error('Native execution forbidden in Stage 3 browser test');
      return post(path,body);
    };
  })()`);
  await s.wait(`${active}.store?.get().schema && ${active}.store.get().metadata.addCatalogue`, 'Workbench');
}
async function screenshot(s, name) { if (shots) await s.screenshot(join(shots,name+'.png')); }

for (const theme of ['light','dark']) {
  test(`Stage 3 templates fill and retain expressions through the real host (${theme})`, {timeout:180000}, async()=>{
    const s=await launch({provider:'paraview',theme});
    try {
      await open(s);
      for(const id of ['slice-sweep','cfd-overview','synchronised-geometry-study']) {
        await s.evaluate(`document.querySelector('[data-library="${id}"]').click()`);
        await s.wait(`document.querySelector('.library-replace-review')?.textContent.includes('replaces the entire input')`, 'replacement review');
        await button(s, 'Replace input', '.library-replace-review');
        await s.wait(fill,'template fill');
        for(let n=0;n<5 && await s.evaluate(`Boolean(${fill})`);n++) {
          const heading=await s.evaluate(`${fill}.querySelector('.sx-fill-heading strong').textContent`);
          assert.deepEqual(await s.evaluate(`[...${fill}.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent)`),[]);
          const value=heading==='OpenFOAM case file'?'data/case.foam':heading==='Initial radius'?'1':heading==='Final radius'?'3':'4';
          await s.evaluate(`(()=>{const e=${fill}.querySelector('.sx-fill-value');e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
          await screenshot(s,`${id}-fill-${theme}`);
          await s.evaluate(`${fill}.querySelector('.primary').click()`);
          await s.wait(`!${fill} || ${fill}.querySelector('.sx-fill-heading strong').textContent!==${JSON.stringify(heading)}`, 'next filled value');
        }
        assert.equal(await s.evaluate(`Boolean(${fill})`),false);
        const doc=await s.evaluate(`${active}.editor.getDocument()`);
        if(id==='cfd-overview')assert.deepEqual(doc.times,{source:'case',select:{latest:1}});
        assert.doesNotMatch(JSON.stringify(doc),/\$fill|\$calc|\$observe/);
        const origins=doc.nodes.filter(n=>n.filter==='slice').map(n=>n.options.origin.$expr);
        assert.equal(origins.length,id==='cfd-overview'?3:1);
        assert.ok(origins.every(e=>typeof e==='string'));
        if(id==='synchronised-geometry-study') {
          assert.equal(origins[0],'extents(sphere).mid');
          assert.equal(doc.nodes[0].options.radius.$analytic.count,4);
          assert.equal(doc.nodes[0].options.centre.$analytic.count,4);
        } else assert.equal(doc.sweeps[0].series.count,4);
        const checked=await s.evaluate(`studio.api.post('/api/validate',{provider:'paraview',source:${active}.editor.getValue()})`);
        assert.equal(checked.valid,true,JSON.stringify(checked));
        // The transformed expressions must check at their actual destinations.
        const checks=await s.evaluate(`Promise.all(${active}.editor.getDocument().nodes.flatMap((n,i)=>n.filter==='slice'?[studio.api.post('/api/spatial',{action:'spatial_check',input:${active}.editor.getDocument(),expression:n.options.origin.$expr,destination:'/nodes/'+i+'/options/origin'})]:[]))`);
        assert.ok(checks.every(c=>c.ok && c.type==='vector'),JSON.stringify(checks));
        await s.evaluate(`${active}.editor.revealPointer('/nodes/'+${doc.nodes.findIndex(n=>n.filter==='slice')}+'/options/origin')`);
        await screenshot(s,`${id}-filled-${theme}`);
      }
      assert.deepEqual(s.exceptions,[]);
    } finally {await s.close();}
  });

  test(`Stage 3 Run reaches dispatch after real source-time validation (${theme})`, {timeout:120000}, async()=>{
    const s=await launch({provider:'paraview',theme});
    try {
      await open(s,car);
      await s.evaluate(`(()=>{
        window.runRequests=[];
        const post=studio.api.post.bind(studio.api);
        studio.api.post=(path,body)=>{
          if(path==='/api/command') {runRequests.push(body);return Promise.resolve({job:'host-boundary'});}
          return post(path,body);
        };
        studio.api.waitForJob=async()=>({result:{native:false}});
        const refresh=studio.refresh.bind(studio);
        studio.refresh=async()=>{await refresh();studio.store.set({server:{...studio.store.get().server,configured:['paraview']}});};
        studio.store.set({server:{...studio.store.get().server,configured:['paraview']}});
      })()`);
      await s.clickSelector('[data-action="run"]');
      await s.wait('runRequests.length===1','Run dispatch');
      assert.equal(await s.evaluate('runRequests[0].line'),'preview');
      const checked=await s.evaluate(`studio.api.post('/api/validate',{provider:'paraview',source:${active}.editor.getValue()})`);
      assert.equal(checked.valid,true);
      assert.equal(checked.validation.code,'TIME_INSPECTION_REQUIRED');
      assert.deepEqual(await s.evaluate(`${active}.editor.getDocument().times`),car.times);
      // Real validation must stop both structural and expression errors before dispatch.
      for(const broken of [
        {...car,nodes:car.nodes.map((n,i)=>i? n:{...n,filter:'missingFilter'})},
        {...car,definitions:{...car.definitions,wake:{$expr:'missingName + 1'}}},
      ]) {
        await s.evaluate(`${active}.editor.setValue(${JSON.stringify(JSON.stringify(broken,null,2))})`);
        await s.clickSelector('[data-action="run"]');
        await s.wait(`${active}.editor.getDiagnostics().some(d=>d.severity==='error')`,'invalid draft blocked');
        assert.equal(await s.evaluate('runRequests.length'),1);
      }
      assert.deepEqual(s.exceptions,[]);
    } finally {await s.close();}
  });

  test(`Stage 3 camera forms and relocated help (${theme})`, {timeout:120000}, async()=>{
    const s=await launch({provider:'paraview',theme});
    try {
      await open(s,{version:'schemaxis/1',nodes:[{id:'body',filter:'sphere'}],scenes:[{id:'view',visible:{body:{}},images:[{id:'image',cameras:[{direction:'z+',up:'y+'}]}]}]});
      const guides=await s.evaluate(`(()=>{const c=${active}.store.get().metadata.addCatalogue.items.find(i=>i.id==='scene:camera');return Object.fromEntries(Object.entries(c.schema.properties).map(([k,v])=>[k,v['x-studio-guide']]));})()`);
      for(const key of ['direction','focalPoint','bounds','scale','up']) {
        assert.ok(['reviewed','reference'].includes(guides[key].status),key);
        assert.ok(guides[key].explanation && guides[key].sources.length,key);
        assert.match(guides[key].address,/cameras\/items\/anyOf\/0\/properties\//);
      }
      const addresses=await s.evaluate(`(()=>{const found=new Set();function walk(v){if(!v||typeof v!=='object')return;
        if(v['x-studio-guide']?.address.includes('/cameras/items/anyOf/0/'))found.add(v['x-studio-guide'].address);
        for(const [k,w] of Object.entries(v))if(k!=='x-studio-guide')walk(w);}
        walk(${active}.store.get().schema);return [...found];})()`);
      assert.equal(addresses.length,108);
      await s.evaluate(`(async()=>{const {configureOperation}=await import('/windows/workbench/operation-form.mjs');const m=${active}.store.get().metadata.addCatalogue;
        void configureOperation(studio,m.items.find(i=>i.id==='scene:camera'),m.definitions,()=>${active}.editor.getDocument()).then(r=>window.cameraAdded=r);})()`);
      await s.wait('document.querySelector(".operation-dialog")','camera form');
      await s.evaluate(`document.querySelector('[aria-label="Include Camera.focalPoint"]').closest('details').open=true;
        document.querySelector('[aria-label="Include Camera.focalPoint"]').click()`);
      await field(s,'Camera.focalPoint','[1,2,3]');
      await s.evaluate(`document.querySelector('[aria-label="Help for Camera.focalPoint"]').click()`);
      assert.match(await s.evaluate(`document.querySelector('.operation-dialog').textContent`),/World point \[x, y, z\]/);
      assert.doesNotMatch(await s.evaluate(`document.querySelector('.operation-dialog').textContent`),/Conceptual explanation needed/);
      await screenshot(s,`camera-help-${theme}`);
      await button(s,'Add operation');await s.wait('window.cameraAdded','camera form result');
      assert.deepEqual(await s.evaluate('cameraAdded.inserts.at(-1).values[0]'),{focalPoint:[1,2,3]});
      // A whole expression camera is admitted by the real authored-schema validator.
      const result=await s.evaluate(`(async()=>{const root=${active}.editor.getDocument();root.scenes[0].images[0].cameras=[{$expr:"fitCamera(bounds = box(0, 4, -1, 1, 0, 2), direction = 'z+', up = 'y+')"}];
        return studio.api.post('/api/validate',{provider:'paraview',source:JSON.stringify(root)});})()`);
      assert.equal(result.valid,true,JSON.stringify(result));
      assert.deepEqual(s.exceptions,[]);
    } finally {await s.close();}
  });

  test(`Stage 3 car extents and Spatial use real host records (${theme})`, {timeout:120000}, async()=>{
    const s=await launch({provider:'paraview',theme});
    try {
      await open(s);
      const filename=join(s.workspace,'car.json');await writeFile(filename,JSON.stringify(car));
      await s.evaluate(`(async()=>{const r=await studio.api.post('/api/documents',{action:'open',file:${JSON.stringify(filename)}});await studio.refresh();studio.openDocument(r.id);})()`);
      await s.wait(`${active}.editor?.getDocument()?.definitions?.model`, 'car file open');
      await s.evaluate(`(async()=>{window.carDraft=${active}.editor.getDocument();const {manageSpatial}=await import('/windows/spatial/panel.mjs');void manageSpatial(studio,{root:carDraft,identity:'car',revision:7,commit:()=>{}});})()`);
      await s.wait(`document.querySelector('.spatial-list')?.textContent.includes('needs-data')`,'car unresolved');
      assert.equal(await s.evaluate(`document.querySelector('[aria-label="Show definitions.model"]').disabled`),true);
      await screenshot(s,`car-unresolved-${theme}`); await button(s,'Cancel');
      const values=await s.evaluate(`(async()=>{
        const listed=await studio.api.post('/api/spatial',{action:'spatial_list',input:carDraft});
        const results=[];for(let i=0;i<5;i++){
          const state={timeIndex:0,indices:{'sweep:/definitions/seedY/$expr#0':i}};
          const observations={inputDigest:listed.inputDigest,state,extents:[{node:'body',port:0,status:'ok',bounds:[0,4.5,-0.9,0.9,0.2,1.4]},{node:'wheels',port:0,status:'ok',bounds:[0.5,3.6,-1,1,0,0.7]}]};
          const response=await studio.api.post('/api/spatial',{action:'spatial_eval',input:carDraft,state,observations});
          if(i===0)window.carSpatial={root:carDraft,response,draft:{identity:'car',revision:7}};
          results.push(Object.fromEntries(response.records.filter(r=>r.entry.section==='definitions').map(r=>[r.entry.key,r.value])));
        }return results;
      })()`);
      assert.deepEqual(values.map(v=>v.seedY),[-1,-0.5,0,0.5,1]);
      assert.deepEqual(values[0].model,{min:[0,-1,0],max:[4.5,1,1.4]});
      assert.equal(values[0].seedX,-0.45);
      assert.ok(Math.abs(values[0].wake.max[2]-2.1)<1e-12);
      await s.evaluate(`(async()=>{const {manageSpatial}=await import('/windows/spatial/panel.mjs');void manageSpatial(studio,{root:carDraft,identity:'car',revision:7,spatial:carSpatial,commit:()=>{}});})()`);
      await s.wait(`document.querySelector('[aria-label="Visible spatial overlays"]')?.textContent.includes('model · box · draft revision 7')`,'host box overlay');
      assert.equal(await s.evaluate(`document.querySelector('[aria-label="Show definitions.wake"]').disabled`),false);
      await screenshot(s,`car-resolved-${theme}`);
      await s.evaluate(`document.querySelector('[aria-label="Select definitions.wake"]').click()`);await button(s,'Edit expression');
      await field(s,'Spatial expression',"model.inflate(0.1)");await button(s,'Update expression');
      await s.wait(`document.querySelector('[aria-label="Show definitions.model"]').disabled`,'edit drops observed extents');
      assert.doesNotMatch(await s.evaluate(`document.querySelector('[aria-label="Visible spatial overlays"]').textContent`),/model ·|wake ·/);
      assert.deepEqual(s.exceptions,[]);
    } finally {await s.close();}
  });

  test(`Stage 3 OpenFOAM browser and reader default skip zero (${theme})`, {timeout:120000}, async()=>{
    const s=await launch({provider:'paraview',theme});
    try {
      const path=join(s.workspace,'case');
      for(const sub of ['constant/polyMesh','0','0.5','1'])await mkdir(join(path,sub),{recursive:true});
      await writeFile(join(path,'case.foam'),'');
      await writeFile(join(path,'constant/polyMesh/boundary'),'FoamFile {class polyBoundaryMesh;}\n1\n(\nwall {type wall; nFaces 1; startFace 0;}\n)');
      await writeFile(join(path,'1/U'),'FoamFile {class volVectorField; object U;}');
      await open(s);
      for(const setting of [null,true,false]) {
        const result=await s.evaluate(`studio.api.post('/api/peek-input',{provider:'paraview',node:'case',input:{version:'schemaxis/1',nodes:[{id:'case',filter:'foam',options:{file:${JSON.stringify(join(path,'case.foam'))},...${JSON.stringify(setting===null?{}:{skipZero:setting})}}}]}})`);
        assert.deepEqual(result.availableTimes,setting===false?[0,0.5,1]:[0.5,1]);
      }
      await s.clickSelector('[data-add=inputs]');await field(s,'Search Add Input','foam');
      await s.wait(`document.querySelector('[data-library="operation:foam"]')`,'foam');await s.clickSelector('[data-library="operation:foam"]');
      await s.wait('document.querySelector(".operation-dialog")','reader form');
      assert.equal(await s.evaluate(`${active}.store.get().metadata.addCatalogue.definitions['options-foam'].properties.skipZero.default`),true);
      await field(s,'foam.options.file',join(path,'case.foam'));
      await s.evaluate(`document.querySelector('[aria-label="Browse for foam.options.file"]').click()`);
      await s.wait(`document.querySelector('.operation-file-list')?.textContent.includes('File: case.foam')`,'case browser');
      await s.evaluate(`[...document.querySelectorAll('.operation-file-list button')].find(b=>b.textContent==='File: case.foam').click()`);
      await button(s,'Open','.file-dialog');await s.wait('!document.querySelector(".file-dialog")','selected');
      await screenshot(s,`reader-default-${theme}`);
      await button(s,'Add operation');
      await s.wait(`${active}.editor.getDocument().nodes.length===1`,'reader inserted');
      const doc=await s.evaluate(`${active}.editor.getDocument()`);
      assert.deepEqual(doc.times,[0.5]);assert.notEqual(doc.nodes[0].options.skipZero,false);
      assert.equal(doc.nodes[0].options.caseType,'Reconstructed Case');
      assert.deepEqual(s.exceptions,[]);
    } finally {await s.close();}
  });

  test(`Stage 3 host receipt records reach Spatial unchanged (${theme})`, {timeout:120000}, async()=>{
    // The real graph, recorder, spatial verifier and run_records adapter are used.
    // test_spatial_results.Backend supplies extents; no native receipt is claimed.
    const saved=hostRunRecords();
    const s=await launch({provider:'paraview',theme});
    try {
      await open(s,saved.root);
      await s.evaluate(`(async()=>{const {manageSpatial}=await import('/windows/spatial/panel.mjs');window.savedRun=${JSON.stringify(saved)};
        void manageSpatial(studio,{root:savedRun.root,identity:'host-run',revision:12,spatial:savedRun,commit:()=>{}});})()`);
      await s.wait(`document.querySelector('.spatial-list')?.textContent.includes('run · box · draft revision 11')`,'host receipt provenance');
      assert.match(await s.evaluate(`document.querySelector('[aria-label="Visible spatial overlays"]').textContent`),/model · box · draft revision 11/);
      await screenshot(s,`host-run-records-${theme}`);await button(s,'Cancel');
      await s.evaluate(`(async()=>{const {manageSpatial}=await import('/windows/spatial/panel.mjs');const edited=structuredClone(savedRun.root);edited.nodes[0].options={maximum:42};
        void manageSpatial(studio,{root:edited,identity:'host-run',revision:13,spatial:savedRun,commit:()=>{}});})()`);
      await s.wait(`document.querySelector('.spatial-list')?.textContent.includes('needs-data')`,'changed input rejects receipt');
      assert.equal(await s.evaluate(`document.querySelector('[aria-label="Show definitions.model"]').disabled`),true);
      assert.deepEqual(s.exceptions,[]);
    } finally {await s.close();}
  });
}
