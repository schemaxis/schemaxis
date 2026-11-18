// Copyright (C) 2026 David L. F. Gaden.
import test from 'node:test';
import assert from 'node:assert/strict';
import {launch} from './harness.mjs';

const button = (s,text) => s.evaluate(`(() => {const b=[...document.querySelectorAll('.dialog button')].find(b=>b.textContent===${JSON.stringify(text)});if(!b)throw Error('Missing button '+${JSON.stringify(text)});b.click();})()`);
const input = (s,label,value) => s.evaluate(`(() => {const e=[...document.querySelectorAll('.dialog [aria-label]')].find(e=>e.getAttribute('aria-label')===${JSON.stringify(label)});if(!e)throw Error('Missing input '+${JSON.stringify(label)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
async function setup(s,scene) {
  await s.wait('window.studio?.store.get().server','Studio');
  await s.evaluate(`(async()=>{
    const {configureOperation}=await import('/windows/workbench/operation-form.mjs');
    window.meta=await studio.api.get('/api/studio/adaptor',{id:'paraview'});
    window.root={version:'schemaxis/1',definitions:{focus:{min:[-1,-1,-1],max:[1,1,1]}},nodes:[{id:'body',filter:'sphere'},{id:'cut',filter:'slice',inputs:{input:'body'},options:{origin:[0,0,0],normal:[1,0,0]}}],scenes:[${JSON.stringify(scene)}]};
    window.openScene=()=>configureOperation(studio,meta.addCatalogue.items.find(i=>i.id==='document:scenes'),meta.addCatalogue.definitions,()=>root,undefined,{existing:{pointer:'/scenes/0',value:root.scenes[0]},operationKinds:meta.operationKinds}).then(result=>window.sceneResult={result});
    void openScene();
  })()`);
  await s.wait('document.querySelector(".scene-pipeline-map")','scene controls');
}

test('scene selection and colour UI fill existing schema; Cancel and untouched round-trip preserve values', {timeout:120000}, async()=>{
  const s=await launch({provider:'paraview'});
  try {
    const scene={id:'view',visible:{body:{colour:'tab:blue'},gone:{opacity:0.3}},images:[{id:'image',cameras:[{bounds:{$expr:'focus'}}]}]};
    await setup(s,scene);
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="Scene.visible"]')?.tagName`),undefined);
    await button(s,'Apply changes');await s.wait('window.sceneResult','scene result');
    assert.deepEqual(await s.evaluate('sceneResult.result.replace.value'),scene);
    await s.evaluate('delete window.sceneResult;void openScene()');await s.wait('document.querySelector(".scene-pipeline-map")','reopen');
    if(process.env.STUDIO_SCENE_EVIDENCE){await s.evaluate(`document.querySelector('.scene-pipeline-map').scrollIntoView({block:'start'})`);await s.screenshot(process.env.STUDIO_SCENE_EVIDENCE+'/scene-editor.png');}
    await input(s,'Filter Scene.visible','cut');await button(s,'Select shown');
    await s.evaluate(`document.querySelector('[aria-label="Edit appearance cut"]').click()`);
    await s.wait('document.querySelector(".scene-appearance-dialog")','appearance');
    await s.evaluate(`document.querySelector('[aria-label="Include Scene.visible.cut.colour"]').click()`);
    await input(s,'Scene.visible.cut.colour colour format','name');
    await s.evaluate(`document.querySelector('.scene-appearance-dialog .scene-colour-control details > summary').click()`);
    await input(s,'Scene.visible.cut.colour palette search','sky blue');
    assert.equal(await s.evaluate(`document.querySelector('.scene-appearance-dialog .scene-colour-control details').open`),true);
    await s.evaluate(`(() => {const b=[...document.querySelectorAll('.scene-appearance-dialog .scene-colour-choice')].find(b=>b.textContent==='xkcd:sky blue');if(!b?.getClientRects().length)throw Error('Palette choice is not visible');b.click();})()`);
    if(process.env.STUDIO_SCENE_EVIDENCE){await s.evaluate(`new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);await s.screenshot(process.env.STUDIO_SCENE_EVIDENCE+'/appearance-editor.png');}
    await button(s,'Apply appearance');await s.wait('!document.querySelector(".scene-appearance-dialog")','appearance applied');
    await button(s,'Apply changes');await s.wait('window.sceneResult','scene applied');
    const value=await s.evaluate('sceneResult.result.replace.value');
    assert.deepEqual(value.visible,{body:{colour:'tab:blue'},gone:{opacity:0.3},cut:{colour:'xkcd:sky blue'}});
    assert.deepEqual(value.images,scene.images);
    await s.evaluate('delete window.sceneResult;void openScene()');await s.wait('document.querySelector(".scene-pipeline-map")','reopen cancel');
    await button(s,'Deselect All');await button(s,'Cancel');await s.wait('window.sceneResult','cancelled');
    assert.equal(await s.evaluate('sceneResult.result'),null);
    assert.deepEqual(await s.evaluate('root.scenes[0]'),scene);
    assert.deepEqual(s.exceptions,[]);assert.deepEqual(s.consoleErrors,[]);
  }finally{await s.close();}
});

test('field colouring, numeric RGB and linked frame controls are usable without native loading', {timeout:120000}, async()=>{
  const s=await launch({provider:'paraview'});
  try {
    await setup(s,{id:'view',visible:{body:{}},images:[{id:'image',cameras:[{}]}]});
    await s.evaluate(`document.querySelector('[aria-label="Edit appearance body"]').click()`);await s.wait('document.querySelector(".scene-appearance-dialog")','appearance');
    await input(s,'Scene.visible.body Colour by','field');
    await input(s,'Scene.visible.body.field Array','p');
    await button(s,'Apply appearance');await s.wait('!document.querySelector(".scene-appearance-dialog")','field applied');
    await s.evaluate(`document.querySelector('[aria-label="Edit appearance body"]').click()`);await s.wait('document.querySelector(".scene-appearance-dialog")','reopen appearance');
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="Scene.visible.body.field Array"]').value`),'p');
    await input(s,'Scene.visible.body Colour by','solid');
    await s.evaluate(`document.querySelector('[aria-label="Include Scene.visible.body.colour"]').click()`);
    await input(s,'Scene.visible.body.colour colour format','rgb');
    await input(s,'Scene.visible.body.colour RGB units','255');
    for(const [channel,value] of [['Red','51'],['Green','102'],['Blue','153']])await input(s,`Scene.visible.body.colour ${channel}`,value);
    await button(s,'Apply appearance');await s.wait('!document.querySelector(".scene-appearance-dialog")','solid applied');
    await s.evaluate(`document.querySelector('[aria-label="Include Scene.images[0].cameras[0].bounds"]').click()`);
    await input(s,'Scene.images[0].cameras[0].bounds pipeline object','cut');await button(s,'Use object bounds');
    await button(s,'Apply changes');await s.wait('window.sceneResult','save');
    const value=await s.evaluate('sceneResult.result.replace.value');
    assert.deepEqual(value.visible.body,{colour:[0.2,0.4,0.6]});
    assert.deepEqual(value.images[0].cameras[0].bounds,{$expr:'extents(`cut`)'});
    assert.deepEqual(s.exceptions,[]);assert.deepEqual(s.consoleErrors,[]);
  }finally{await s.close();}
});

test('camera list removal keeps the named Spatial box picker on the surviving destination', {timeout:120000}, async()=>{
  const s=await launch({provider:'paraview'});
  try {
    await setup(s,{id:'view',visible:{body:{}},images:[{id:'image',cameras:[{direction:[1,0,0]},{bounds:[-2,2,-2,2,-2,2]}]}]});
    await s.evaluate(`document.querySelector('.scene-camera').closest('.operation-array-item').lastElementChild.click()`);
    await s.wait(`document.querySelectorAll('.scene-camera').length===1`,'removed first camera');
    await s.evaluate(`document.querySelector('[aria-label="Value or expression for Scene.images[0].cameras[0].bounds"]').click()`);
    await s.wait(`document.querySelector('[aria-label="Choose a value or expression"]')`,'value picker');
    await s.evaluate(`(()=>{const b=[...document.querySelectorAll('.variables-list button')].find(b=>b.textContent.startsWith('focus ·'));if(!b)throw Error('No focus box offered');b.click();})()`);
    await button(s,'Use value');await s.wait(`!document.querySelector('[aria-label="Choose a value or expression"]')`,'chosen');
    await button(s,'Apply changes');await s.wait('window.sceneResult','scene');
    const value=await s.evaluate('sceneResult.result.replace.value.images[0].cameras');
    assert.equal(value.length,1);assert.equal(Array.isArray(value[0].bounds),false,'box stays linked');
    assert.ok(value[0].bounds.$document || value[0].bounds.$expr);
    assert.deepEqual(s.exceptions,[]);assert.deepEqual(s.consoleErrors,[]);
  }finally{await s.close();}
});

test('variants restrict choices to visible objects, preserve overrides, and text overlays offer text controls', {timeout:120000}, async()=>{
  const s=await launch({provider:'paraview'});
  try {
    const scene={id:'view',visible:{body:{colour:'steelblue'}},appearances:[{}, {body:{opacity:0.4}}],images:[{id:'image',cameras:[{}]}]};
    await setup(s,scene);
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="Scene.appearances[1]: cut"]')`),null);
    assert.ok(await s.evaluate(`Boolean(document.querySelector('[aria-label="Scene.appearances[1]: body"]'))`));
    await s.evaluate(`document.querySelector('[aria-label="Scene.visible: cut"]').click()`);
    assert.ok(await s.evaluate(`Boolean(document.querySelector('[aria-label="Scene.appearances[1]: cut"]'))`),'variant offers newly visible object');
    await s.evaluate(`document.querySelector('[aria-label="Scene.visible: cut"]').click()`);
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="Scene.appearances[1]: cut"]')`),null);
    await button(s,'Apply changes');await s.wait('window.sceneResult','scene');
    assert.deepEqual(await s.evaluate('sceneResult.result.replace.value'),scene);
    await s.evaluate(`delete window.sceneResult;root.nodes.push({id:'timeText',filter:'pvAnnotateTimeFilter',inputs:{Input:'body'}});root.scenes[0].visible.timeText={fontSize:24,colour:'black'};void openScene()`);
    await s.wait('document.querySelector(".scene-pipeline-map")','reopen');
    await s.evaluate(`document.querySelector('[aria-label="Edit appearance timeText"]').click()`);await s.wait('document.querySelector(".scene-appearance-dialog")','text');
    assert.equal(await s.evaluate(`Boolean(document.querySelector('[aria-label="Include Scene.visible.timeText.representation"]'))`),false);
    assert.ok(await s.evaluate(`Boolean(document.querySelector('[aria-label="Scene.visible.timeText.fontSize"]'))`));
    await button(s,'Apply appearance');await s.wait('!document.querySelector(".scene-appearance-dialog")','applied');
    await button(s,'Apply changes');await s.wait('window.sceneResult','scene');
    assert.deepEqual(await s.evaluate('sceneResult.result.replace.value.visible.timeText'),{fontSize:24,colour:'black'});
    assert.deepEqual(s.exceptions,[]);assert.deepEqual(s.consoleErrors,[]);
  }finally{await s.close();}
});

test('inspection is explicit and fills current-object cell arrays and a fixed range', {timeout:120000}, async()=>{
  const s=await launch({provider:'paraview'});
  try {
    await setup(s,{id:'view',visible:{body:{}},images:[{id:'image',cameras:[{}]}]});
    await s.evaluate(`(()=>{
      const post=studio.api.post.bind(studio.api),wait=studio.api.waitForJob.bind(studio.api);window.inspections=[];
      studio.api.post=async(path,body)=>{if(path==='/api/inspect-input'){inspections.push(body);return {job:'scene-test-inspection'};}return post(path,body);};
      studio.api.waitForJob=async(job,...args)=>job==='scene-test-inspection'?{result:{observation:{fields:{CELLS:{p:{components:1,range:[-3,8],numeric:true}},POINTS:{U:{components:3,range:[0,4],numeric:true}}}}}}:wait(job,...args);
    })()`);
    await s.evaluate(`document.querySelector('[aria-label="Edit appearance body"]').click()`);await s.wait('document.querySelector(".scene-appearance-dialog")','appearance');
    await input(s,'Scene.visible.body Colour by','field');
    assert.equal(await s.evaluate('inspections.length'),0);
    await button(s,'Ask the application');
    await s.wait(`document.querySelector('.scene-data-field datalist option[value="p"]')`,'native fields');
    await input(s,'Scene.visible.body.field Array','p');
    // Reinspection establishes the current selection's reported range.
    await button(s,'Ask the application');await s.wait(`![...document.querySelectorAll('button')].find(b=>b.textContent==='Use inspected range').disabled`,'range available');
    await button(s,'Use inspected range');
    await button(s,'Apply appearance');await s.wait('!document.querySelector(".scene-appearance-dialog")','applied');
    await button(s,'Apply changes');await s.wait('window.sceneResult','scene');
    assert.deepEqual(await s.evaluate('sceneResult.result.replace.value.visible.body'),{field:['CELLS','p'],range:[-3,8]});
    assert.deepEqual(await s.evaluate('inspections.map(i=>i.node)'),['body','body']);
    assert.deepEqual(s.exceptions,[]);assert.deepEqual(s.consoleErrors,[]);
  }finally{await s.close();}
});

test('New volume from a camera stages its definition with the scene; cancelling discards both', {timeout:120000}, async()=>{
  const s=await launch({provider:'paraview',width:700,height:900,theme:'dark'});
  try {
    await setup(s,{id:'view',visible:{body:{}},images:[{id:'image',cameras:[{}]}]});
    await s.evaluate(`document.querySelector('[aria-label="Include Scene.images[0].cameras[0].bounds"]').click()`);
    await button(s,'New volume…');await s.wait(`document.querySelector('.volume-actions .primary')?.disabled===false`,'volume preview');
    await input(s,'Volume name','cameraFocus');
    await s.wait(`document.querySelector('.volume-actions .primary')?.disabled===false`,'valid volume name');
    await button(s,'Add volume');await s.wait('!document.querySelector(".volume-dialog")','volume staged');
    assert.equal(await s.evaluate('root.definitions.cameraFocus'),undefined);
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="Scene.images[0].cameras[0].bounds"]').value`),'definitions.`cameraFocus`');
    assert.equal(await s.evaluate(`(()=>{const d=document.querySelector('.operation-dialog .dialog-body');return d.scrollWidth<=d.clientWidth;})()`),true);
    if(process.env.STUDIO_SCENE_EVIDENCE)await s.screenshot(process.env.STUDIO_SCENE_EVIDENCE+'/scene-dark-narrow.png');
    await button(s,'Apply changes');await s.wait('window.sceneResult','result');
    assert.ok(await s.evaluate(`sceneResult.result.inserts.find(i=>i.at==='/definitions').values[0].cameraFocus`));
    assert.deepEqual(await s.evaluate('sceneResult.result.replace.value.images[0].cameras[0].bounds'),{$expr:'definitions.`cameraFocus`'});
    assert.equal(await s.evaluate('root.definitions.cameraFocus'),undefined);
    await s.evaluate('delete window.sceneResult;void openScene()');await s.wait('document.querySelector(".scene-pipeline-map")','reopen');
    await s.evaluate(`document.querySelector('[aria-label="Include Scene.images[0].cameras[0].bounds"]').click()`);
    await button(s,'New volume…');await s.wait(`document.querySelector('.volume-actions .primary')?.disabled===false`,'new volume');
    await input(s,'Volume name','discardMe');await s.wait(`document.querySelector('.volume-actions .primary')?.disabled===false`,'valid');
    await button(s,'Add volume');await s.wait('!document.querySelector(".volume-dialog")','staged');
    await button(s,'Cancel');await s.wait('window.sceneResult','cancelled');
    assert.equal(await s.evaluate('sceneResult.result'),null);assert.equal(await s.evaluate('root.definitions.discardMe'),undefined);
    assert.deepEqual(s.exceptions,[]);assert.deepEqual(s.consoleErrors,[]);
  }finally{await s.close();}
});


test('a new scene opens pipeline choices, and deselecting an appearance override restores defaults', {timeout:120000}, async()=>{
  const s=await launch({provider:'paraview'});
  try {
    await setup(s,{id:'view',visible:{body:{colour:'gold',opacity:0.5}},images:[{id:'image',cameras:[{}]}]});
    await s.evaluate(`document.querySelector('[aria-label="Edit appearance body"]').click()`);await s.wait('document.querySelector(".scene-appearance-dialog")','appearance');
    await s.evaluate(`document.querySelector('[aria-label="Include Scene.visible.body.colour"]').click();document.querySelector('[aria-label="Include Scene.visible.body.opacity"]').click()`);
    await button(s,'Apply appearance');await s.wait('!document.querySelector(".scene-appearance-dialog")','applied');
    await button(s,'Apply changes');await s.wait('window.sceneResult','scene');
    assert.deepEqual(await s.evaluate('sceneResult.result.replace.value.visible.body'),{});
    await s.evaluate(`(async()=>{
      const {configureOperation}=await import('/windows/workbench/operation-form.mjs');delete window.sceneResult;
      void configureOperation(studio,meta.addCatalogue.items.find(i=>i.id==='document:scenes'),meta.addCatalogue.definitions,()=>root,undefined,{operationKinds:meta.operationKinds}).then(result=>window.sceneResult={result});
    })()`);
    await s.wait('document.querySelector(".scene-pipeline-map")','new scene');
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="Scene.visible: body"]').checkVisibility()`),true);
    await s.evaluate(`document.querySelector('[aria-label="Scene.visible: body"]').click()`);
    await button(s,'Add image');await s.wait('document.querySelector(".scene-camera")','new image camera');
    await button(s,'Add operation');await s.wait('window.sceneResult','created');
    const created=await s.evaluate(`sceneResult.result.inserts.find(i=>i.at==='/scenes/-').values[0]`);
    assert.deepEqual(created.visible,{body:{}});assert.equal(created.images.length,1);assert.deepEqual(created.images[0].cameras,[{}]);
    assert.deepEqual(s.exceptions,[]);assert.deepEqual(s.consoleErrors,[]);
  }finally{await s.close();}
});
