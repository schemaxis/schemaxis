// Copyright (C) 2026 David L. F. Gaden.
import test from 'node:test';
import assert from 'node:assert/strict';
import {launch} from './harness.mjs';
import {mkdir} from 'node:fs/promises';
const evidence = process.env.SPATIAL_EVIDENCE;
async function click(s,label) {
  await s.evaluate(`(()=>{const d=[...document.querySelectorAll('.dialog')].at(-1);const b=[...d.querySelectorAll('button')].find(b=>b.textContent===${JSON.stringify(label)});if(!b||b.disabled)throw Error('Unavailable button '+${JSON.stringify(label)});b.click();})()`);
}
async function field(s,label,value) {
  await s.evaluate(`(()=>{const d=[...document.querySelectorAll('.dialog')].at(-1);const e=d.querySelector('[aria-label="'+${JSON.stringify(label)}+'"]');if(!e)throw Error('Missing field');e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}
async function ready(s) {await s.wait(`document.querySelector('.volume-dialog .volume-actions .primary')?.disabled===false`,'valid host preview');}

test('guided volumes use the real host, preserve linked recipes, support fixed snapshots and cancel staging', {timeout:120000}, async()=>{
  const s=await launch({provider:'paraview'});
  try {
    await s.wait('window.studio?.store.get().server','Studio');
    await s.evaluate(`(async()=>{const {manageSpatial}=await import('/windows/spatial/panel.mjs');
      window.before={version:'schemaxis/1',nodes:[{id:'ball-node',filter:'sphere'}],definitions:{seed:[0,10,0,20,0,30]}};
      void manageSpatial(studio,{root:before,commit:root=>window.result=root});})()`);
    await s.wait(`document.querySelector('[aria-label="Data extents"]')?.textContent.includes('no data readers')`,'no-reader explanation');
    await click(s,'Add literal / volume…'); await ready(s);
    await field(s,'Volume source','value'); await ready(s);
    await click(s,'Inflate %'); await ready(s);
    await field(s,'1. Change Y (%)','20'); await ready(s);
    await field(s,'1. Change Z (%)','-100'); await ready(s);
    assert.match(await s.evaluate(`document.querySelector('[aria-label="Volume result"]').textContent`),/\(-0.5, -2, 15\), \(10.5, 22, 15\)/);
    await click(s,'Translate'); await ready(s);
    await field(s,'2. Move by X','1'); await ready(s);
    await click(s,'Undo step'); await ready(s);
    assert.match(await s.evaluate(`document.querySelector('[aria-label="Volume result"]').textContent`),/\(-0.5, -2, 15\)/);
    await click(s,'Redo step'); await ready(s);
    await field(s,'Volume name','envelope'); await ready(s);
    if(evidence){await mkdir(evidence,{recursive:true});await s.screenshot(evidence+'/volume-builder-light.png');}
    await click(s,'Add volume');
    await s.wait(`document.querySelector('.spatial-list')?.textContent.includes('envelope')`,'staged volume');
    assert.equal(await s.evaluate('window.result'),undefined);
    await s.evaluate(`document.querySelector('[aria-label="Select definitions.envelope"]').click()`);
    await s.wait(`document.querySelector('.spatial-form')?.textContent.includes('Adjust volume…')`,'typed selected volume');
    await click(s,'Adjust volume…');await ready(s);
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="Volume source"]').value`),'current');
    await click(s,'Resize');await ready(s);
    await field(s,'1. New size Z','0');await ready(s);
    await s.evaluate(`document.querySelector('[aria-label="Save as fixed numbers"]').click()`);await ready(s);
    await click(s,'Update volume');
    await s.wait(`!document.querySelector('.volume-dialog')`,'fixed result staged');
    await click(s,'Add literal / volume…');await ready(s);
    await field(s,'Volume name','discarded');await ready(s);
    await click(s,'Cancel volume');
    await click(s,'Apply changes');await s.wait('window.result','committed');
    assert.deepEqual(await s.evaluate('result.definitions.envelope'),{min:[5.5,9.5,15],max:[6.5,10.5,15]});
    assert.equal(await s.evaluate('result.definitions.discarded'),undefined);
    assert.deepEqual(await s.evaluate('before.definitions'),{seed:[0,10,0,20,0,30]});
    assert.deepEqual(s.exceptions,[]);assert.deepEqual(s.consoleErrors,[]);
  }finally{await s.close();}
});

test('invalid numbers and empty intersections cannot be saved; linked node sources save without loading data', {timeout:120000},async()=>{
  const s=await launch({provider:'paraview',width:700,height:900,theme:'dark'});
  try{
    await s.wait('window.studio?.store.get().server','Studio');
    await s.evaluate(`(async()=>{const {editVolume}=await import('/windows/spatial/volume-editor.mjs');void editVolume(studio,{root:{version:'schemaxis/1',nodes:[{id:'ball-node',filter:'sphere'}]}});})()`);
    await ready(s);
    await field(s,'Volume source Min X','');
    await s.wait(`document.querySelector('.volume-dialog [role="alert"]').textContent.includes('finite number')`,'invalid numeric explanation');
    assert.equal(await s.evaluate(`document.querySelector('.volume-actions .primary').disabled`),true);
    await field(s,'Volume source Min X','0');await ready(s);
    await click(s,'Intersect');await ready(s);
    await field(s,'1. Other volume Max X','3');await ready(s);
    await field(s,'1. Other volume Min X','2');
    await s.wait(`document.querySelector('[aria-label="Volume result"]').textContent.includes('Empty or invalid')`,'empty intersection');
    assert.equal(await s.evaluate(`document.querySelector('.volume-actions .primary').disabled`),true);
    await click(s,'Remove');await ready(s);
    await field(s,'Volume source','node');
    await s.wait(`document.querySelector('[aria-label="Volume result"]').textContent.includes('Unavailable until data loads')`,'unloaded node');
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="Volume source node"]').value`),'ball-node');
    assert.equal(await s.evaluate(`document.querySelector('.volume-actions .primary').disabled`),false);
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="Volume name"]').value`),'ball-node_extents');
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="Save as fixed numbers"]').disabled`),true);
    assert.equal(await s.evaluate(`(()=>{const e=document.querySelector('.volume-dialog .dialog-body');return e.scrollWidth<=e.clientWidth;})()`),true,'no horizontal overflow');
    await field(s,'Volume source','coordinates');await ready(s);
    if(evidence){await mkdir(evidence,{recursive:true});await s.screenshot(evidence+'/volume-builder-dark-narrow.png');}
    await click(s,'Cancel volume');
    assert.deepEqual(s.exceptions,[]);assert.deepEqual(s.consoleErrors,[]);
  }finally{await s.close();}
});
