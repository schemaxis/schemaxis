// Copyright (C) 2026 David L. F. Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {launch} from './harness.mjs';

const active='studio.windows.active().window';
test('golden path keeps drafts while inspecting headers, inserting section recipes and navigating panels', {timeout:120000}, async()=>{
  const s=await launch({provider:'paraview'});
  try {
    const casePath=join(s.workspace,'case');
    await mkdir(join(casePath,'constant/polyMesh'),{recursive:true}); await mkdir(join(casePath,'1'));
    await writeFile(join(casePath,'case.foam'),'');
    await writeFile(join(casePath,'constant/polyMesh/boundary'),'FoamFile {class polyBoundaryMesh;}\n1\n(\nwalls { nFaces 6; startFace 0;}\n)');
    await writeFile(join(casePath,'1/U'),'FoamFile {class volVectorField; object U;}');
    await writeFile(join(casePath,'1/p'),'FoamFile {class volScalarField; object p;}');
    await s.wait('window.studio?.store.get().server','Studio');
    await s.evaluate(`(async()=>{const r=await studio.api.post('/api/documents',{action:'new',provider:'paraview',name:'Audit golden path',source:JSON.stringify({version:'schemaxis/1',nodes:[
      {id:'case',filter:'foam',options:{file:${JSON.stringify(join(casePath,'case.foam'))},cellArrays:['U','p']}},
      {id:'unfinished',filter:'slice',options:{$document:'/notReady'}}],scenes:[]})});await studio.refresh();studio.openDocument(r.id);})()`);
    await s.wait(`${active}.store?.get().schema`,'schema');
    const original=await s.evaluate(`${active}.editor.getValue()`);
    await s.evaluate(`${active}.editor.revealPointer('/nodes/0/options/file');${active}.editor.focus()`);
    await s.wait(`document.querySelector('.wb-comprehension [data-pointer="/nodes/0"]').getAttribute('aria-current')==='true'`,'cursor guide');
    await s.evaluate(`document.querySelector('[data-action=case-names]').click()`);
    await s.wait(`${active}.store.get().inspection?.cellArrays?.length===2`,'header preview despite invalid downstream');
    assert.equal(await s.evaluate(`${active}.editor.getValue()`),original);
    assert.deepEqual(await s.evaluate(`${active}.store.get().inspection.regions`),['internalMesh','patch/walls']);
    await s.evaluate(`document.querySelector('[data-tab=schema]').click()`);
    await s.wait(`document.querySelector('.wb-schema-row .tree-subtree')`,'schema tree');
    await s.evaluate(`(()=>{const e=document.querySelector('[aria-label="Search schema"]');e.value='cellArrays';e.dispatchEvent(new Event('input'));})()`);
    assert.ok(await s.evaluate(`document.querySelector('.wb-schema').textContent.includes('Copy schema')`));
    await s.evaluate(`document.querySelector('.wb-sidebar-toggle').click()`);
    assert.equal(await s.evaluate(`document.querySelector('.wb-left').hidden`),true);
    await s.evaluate(`document.querySelector('.wb-sidebar-toggle').click();document.querySelector('[data-sidebar=guide]').click();document.querySelector('[data-tab=input]').click()`);
    assert.equal(await s.evaluate(`document.querySelector('.wb-left').hidden`),false);
    assert.equal(await s.evaluate(`document.querySelector('.wb-sections').hidden`),true);
    await s.evaluate(`document.querySelector('.wb-controls-toggle').click()`);
    assert.equal(await s.evaluate(`document.querySelector('.wb-authoring-tools').hidden`),true);
    await s.evaluate(`document.querySelector('.wb-controls-toggle').click()`);
    assert.equal(await s.evaluate(`document.querySelector('.wb-authoring-tools').hidden`),false);
    assert.equal(await s.evaluate(`document.querySelectorAll('.window:not([hidden]) > .window-body > .tree-tools').length`),0);
    await s.evaluate(`document.querySelector('[data-right=case]').click();${active}.editor.revealPointer('/nodes/0/options/cellArrays');${active}.editor.focus()`);
    await s.evaluate(`document.querySelector('.wb-case-data').querySelector('summary').parentElement.open=true`);
    assert.deepEqual(await s.evaluate(`[...document.querySelectorAll('.wb-case-data .wb-case-name')].map(b=>b.textContent)`),['internalMesh','patch/walls','U','p','1']);
    await s.evaluate(`[...document.querySelectorAll('.wb-case-data .wb-case-name')].find(b=>b.textContent==='patch/walls').click()`);
    assert.deepEqual(await s.evaluate(`${active}.editor.getDocument().nodes[0].options.cellArrays`),['U','p','patch/walls']);
    await s.evaluate(`${active}.editor.undo();document.querySelector('[data-right=properties]').click()`);
    assert.equal(await s.evaluate(`${active}.editor.getValue()`),original);
    // A section button must survive focus and commit its preview in one undo step.
    await s.evaluate(`${active}.editor.revealPointer('/scenes');${active}.editor.focus()`);
    await s.evaluate(`${active}.editor.textarea.dispatchEvent(new KeyboardEvent('keyup',{key:'ArrowDown',bubbles:true}))`);
    await s.wait(`document.querySelector('.library-section button')`,'section recipe');
    const before=await s.evaluate(`${active}.editor.getValue()`);
    await s.clickSelector('.library-section button');
    await s.wait(`${active}.editor.getValue()!==${JSON.stringify(before)}`,'section recipe persisted');
    await s.evaluate(`document.querySelector('.wb-comprehension').dispatchEvent(new MouseEvent('mouseenter'))`);
    assert.notEqual(await s.evaluate(`${active}.editor.getValue()`),before);
    await s.evaluate(`${active}.editor.stopFill();${active}.editor.undo()`);
    assert.equal(await s.evaluate(`${active}.editor.getValue()`),before);
    await s.evaluate(`studio.notify.group([{message:'Audit diagnostic',pointer:'/nodes/1'}])`);
    await s.evaluate(`[...document.querySelectorAll('.toast button')].find(b=>b.textContent==='Show Problems').click()`);
    assert.equal(await s.evaluate(`studio.store.get().panelTab`),'problems');
    assert.equal(await s.evaluate(`studio.store.get().panelOpen`),true);
    await s.evaluate(`studio.notify.suppressed=true;studio.notify.info('Retained silently')`);
    assert.ok(await s.evaluate(`studio.notify.store.get().log.some(e=>e.title==='Retained silently')`));
    assert.ok(!await s.evaluate(`[...document.querySelectorAll('.toast')].some(e=>e.textContent.includes('Retained silently'))`));
    await s.screenshot('/tmp/schemaxis-gui-audit.png');
    assert.deepEqual(s.exceptions,[]); assert.deepEqual(s.consoleErrors,[]);
  } finally { await s.close(); }
});
