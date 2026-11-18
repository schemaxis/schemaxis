import {stubSpatialHost} from './fixtures/spatial-host-browser.mjs';
// Copyright (C) 2026 David L. F. Gaden.
import test from 'node:test';
import assert from 'node:assert/strict';
import {launch} from './harness.mjs';
import {mkdir} from 'node:fs/promises';

const active = 'studio.windows.active().window';
async function button(session, label) {
  await session.evaluate(`(() => {const dialog=[...document.querySelectorAll('.dialog')].at(-1);
    const control=[...dialog.querySelectorAll('button')].find(b=>b.textContent===${JSON.stringify(label)});
    if (!control) throw Error('Missing button: '+${JSON.stringify(label)});control.click();})()`);
}
async function field(session, label, value) {
  await session.evaluate(`(() => {const dialog=[...document.querySelectorAll('.dialog')].at(-1);
    const control=[...dialog.querySelectorAll('[aria-label]')].find(e=>e.getAttribute('aria-label')===${JSON.stringify(label)});
    if (!control) throw Error('Missing field: '+${JSON.stringify(label)});
    control.value=${JSON.stringify(value)};control.dispatchEvent(new Event('input',{bubbles:true}));control.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}

test('spatial overlays render without native geometry and never manufacture native picks', {timeout: 120000}, async () => {
  const session = await launch();
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await stubSpatialHost(session, {expressions: {'union(floor, extents(body))': {type: 'box', phase: 'observed', unresolved: true}}});
    await session.evaluate(`(async () => {
      const {createViewer3d} = await import('/viewers/viewer3d.mjs');
      const host = document.createElement('div');
      host.style.cssText = 'position:fixed;inset:90px 60px 70px 100px;z-index:1000';
      document.body.append(host); window.spatialViewer = createViewer3d(host);
      spatialViewer.setOverlays([
        {id:'ground',kind:'box',min:[-2,-2,0],max:[2,2,0]},
        {id:'point',kind:'point',point:[0,0,1]},
        {id:'line',kind:'line',start:[0,0,0],end:[0,0,2]}]);
    })()`);
    await session.wait('spatialViewer.coveredPixels() > 50', 'literal overlay pixels');
    assert.equal(await session.evaluate('spatialViewer.mesh'), null);
    assert.equal(await session.evaluate(`(() => {const p=spatialViewer.projectToClient([0,0,1]);return spatialViewer.pickAt(p.x,p.y);})()`), null);
    await session.evaluate(`spatialViewer.setSection({axis:'z', position:0.5})`);
    assert.equal(await session.evaluate('spatialViewer.getSection().position'), 0.5);
    const beforeSelection = await session.evaluate('spatialViewer.getCamera()');
    await session.evaluate(`spatialViewer.setOverlays([
      {id:'ground',kind:'box',min:[-2,-2,0],max:[2,2,0]},
      {id:'point',kind:'point',point:[0,0,1]},
      {id:'line',kind:'line',start:[0,0,0],end:[0,0,2]}],{selected:'point'})`);
    assert.deepEqual(await session.evaluate('spatialViewer.getCamera()'), beforeSelection, 'selection keeps the camera');
    assert.equal(await session.evaluate('spatialViewer.getSection().position'), 0.5, 'selection keeps the section');
    await session.evaluate(`spatialViewer.setOverlays([])`);
    assert.equal(await session.evaluate('spatialViewer.coveredPixels()'), 0);
    await session.evaluate(`spatialViewer.load({revision:1,objects:[{id:'body',faces:[{id:'face',vertices:[[-1,-1,0],[1,-1,0],[0,1,0]],triangles:[[0,1,2]]}]}]})`);
    await session.evaluate(`spatialViewer.setView('+z'); spatialViewer.setOverlays([{id:'box',kind:'box',min:[-1,-1,0],max:[1,1,1]}])`);
    await session.wait(`(() => {const p=spatialViewer.projectToClient([0,0,0]);return p && spatialViewer.pickAt(p.x,p.y)?.object==='body';})()`, 'native pick survives overlays');
    await session.evaluate('spatialViewer.clear()');
    assert.equal(await session.evaluate('spatialViewer.coveredPixels()'), 0);
    await session.evaluate('spatialViewer.destroy()');
    assert.deepEqual(session.exceptions, []);
    assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});

test('spatial literal edits are cancellable, preserve expressions and apply as one undo', {timeout: 120000}, async () => {
  const session = await launch();
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await stubSpatialHost(session, {expressions: {'union(floor, extents(body))': {type: 'box', phase: 'observed', unresolved: true}}});
    await session.evaluate(`(async()=>{const record=await studio.api.post('/api/documents',{action:'new',provider:'freecad',name:'Spatial literals',document:{
      version:'schemaxis.freecad/1',nodes:[{id:'body',filter:'box',options:{length:10,width:2,height:3}}],output:'body'}});
      await studio.refresh();studio.openDocument(record.id);})()`);
    await session.wait(`${active}.store?.get().schema`, 'Workbench');
    await session.evaluate(`${active}.editor.insertAtPointer('/definitions',{
      floor:[-2,2,-2,2,0,0], centre:[0,0,1], height:2,
      invalid:{min:[1,1,1],max:[-1,-1,-1]}, computed:{$expr:'union(floor, extents(body))'}})`);
    const original = await session.evaluate(`${active}.editor.getValue()`);
    for (const cancel of [true, false]) {
      await session.evaluate('void studio.openSpatial()');
      await session.wait('document.querySelector(".spatial-dialog")', 'Spatial window');
      assert.equal(await session.evaluate('document.querySelectorAll(".spatial-row").length'), 5);
      assert.match(await session.evaluate('document.querySelector(".spatial-list").textContent'), /Invalid box · not drawn/);
      assert.equal(await session.evaluate('document.querySelector(\'[aria-label="Show definitions.computed"]\').disabled'), true);
      await session.evaluate('document.querySelector(\'[aria-label="Select definitions.computed"]\').click()');
      assert.match(await session.evaluate('document.querySelector(".spatial-form").textContent'), /unresolved/);
      assert.equal(await session.evaluate('document.querySelector(".spatial-form input")'), null);
      await button(session, 'Quick literal');
      await field(session, 'Spatial name', 'floor');
      await button(session, 'Add literal');
      assert.match(await session.evaluate('document.querySelector(".spatial-dialog [role=alert]").textContent'), /already exists/);
      await field(session, 'Spatial name', 'wake');
      await field(session, 'Maximum Z', '0');
      await field(session, 'Minimum X', '');
      await button(session, 'Add literal');
      assert.match(await session.evaluate('document.querySelector(".spatial-dialog [role=alert]").textContent'), /finite number/);
      await field(session, 'Minimum X', '0');
      await button(session, 'Add literal');
      await session.wait('document.querySelectorAll(".spatial-row").length===6', 'staged flat box');
      assert.equal(await session.evaluate(`${active}.editor.getValue()`), original, 'adding a literal is still staged');
      await session.evaluate('document.querySelector(\'[aria-label="Vectors as lines from origin"]\').click()');
      if (!cancel) {
        assert.equal(await session.evaluate(`(() => {const r=document.querySelector('.spatial-dialog .dialog-footer').getBoundingClientRect();return r.bottom<=innerHeight && r.top>=0;})()`), true, 'Apply and Cancel stay in the viewport');
        await mkdir('evidence/spatial-stage1', {recursive: true});
        await session.screenshot('evidence/spatial-stage1/literal-window.png');
      }
      await button(session, cancel ? 'Cancel' : 'Apply changes');
      await session.wait('!document.querySelector(".dialog")', 'Spatial closed');
      if (cancel) assert.equal(await session.evaluate(`${active}.editor.getValue()`), original);
    }
    const value = await session.evaluate(`${active}.editor.getDocument()`);
    assert.deepEqual(value.definitions.wake, {min:[0,0,0],max:[1,1,0]});
    assert.deepEqual(value.definitions.computed, {$expr:'union(floor, extents(body))'});
    assert.deepEqual(value.definitions.floor, [-2,2,-2,2,0,0], 'untouched six-number form survives');
    await session.evaluate(`${active}.editor.focus()`); await session.key('z', {modifiers: 2});
    assert.equal(await session.evaluate(`${active}.editor.getValue()`), original);
    await session.evaluate('document.querySelector(\'[role="tab"][data-tab="3d"]\').click()');
    await session.wait('document.querySelector(\'[aria-label="Spatial overlays"]\')', 'Workbench overlay control');
    await session.evaluate('document.querySelector(\'[aria-label="Spatial overlays"]\').click()');
    await session.wait('document.querySelector(\'[data-viewer-panel="3d"] .vw\').dataset.state==="ready"', 'Workbench literals without native data');
    assert.equal(await session.evaluate(`${active}.store.get().references.length`), 0);
    await session.evaluate('document.querySelector(\'[aria-label="Spatial overlays"]\').click()');
    await session.wait('document.querySelector(\'[data-viewer-panel="3d"] .vw\').dataset.state==="empty"', 'Workbench overlays hidden');
    await session.evaluate('void studio.openSpatial()');
    await session.wait('document.querySelector(".spatial-dialog")', 'Spatial reopened');
    await session.evaluate('document.querySelector(\'[aria-label="Select definitions.height"]\').click()');
    await field(session, 'Scalar value', '3');
    await button(session, 'Update literal');
    await session.evaluate(`${active}.editor.insertAtPointer('/definitions/height',7)`);
    await button(session, 'Apply changes');
    await session.wait('document.querySelector(".spatial-dialog [role=alert]").textContent.includes("input changed")', 'actual draft guard');
    assert.equal(await session.evaluate(`${active}.editor.getDocument().definitions.height`), 7);
    await button(session, 'Cancel');
    await session.evaluate('void studio.openVariables()');
    await session.wait('document.querySelector(\'[aria-label="Variables & expressions"]\')', 'Variables');
    await button(session, 'Spatial…');
    await session.wait('document.querySelector(".spatial-dialog")', 'nested Spatial');
    await field(session, 'Spatial name', 'stagedOnly');
    await button(session, 'Add literal');
    await button(session, 'Apply changes');
    await session.wait('!document.querySelector(".spatial-dialog")', 'nested changes staged');
    assert.equal(await session.evaluate(`${active}.editor.getDocument().definitions.stagedOnly`), undefined);
    await button(session, 'Cancel');
    assert.equal(await session.evaluate(`${active}.editor.getDocument().definitions.stagedOnly`), undefined);
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});

test('spatial scopes isolate entries and commit failures keep edits open for recovery', {timeout: 120000}, async () => {
  const session = await launch();
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await stubSpatialHost(session, {expressions: {'union(floor, extents(body))': {type: 'box', phase: 'observed', unresolved: true}}});
    await session.evaluate(`(async()=>{const {manageSpatial}=await import('/windows/spatial/panel.mjs');
      window.spatialCommit=null;
      void manageSpatial(studio,{root:{version:'schemaxis.workflow/1',definitions:{shared:[0,0,0]},operations:[
        {id:'part',document:{version:'schemaxis.freecad/1',definitions:{local:{min:[0,0,0],max:[1,1,1]},region:[0,1,0,1,0,1]},settings:{labels:['x+','y+','z+']}}}]},
        commit:root=>{window.spatialCommit=root;throw Error('The input changed while Spatial was open.');}});
    })()`);
    await session.wait('document.querySelector(".spatial-dialog")', 'Spatial');
    assert.match(await session.evaluate('document.querySelector(".spatial-list").textContent'), /shared/);
    assert.doesNotMatch(await session.evaluate('document.querySelector(".spatial-list").textContent'), /local/);
    await field(session, 'Spatial scope', '/operations/0/document');
    assert.match(await session.evaluate('document.querySelector(".spatial-list").textContent'), /local/);
    assert.doesNotMatch(await session.evaluate('document.querySelector(".spatial-list").textContent'), /shared/);
    await session.evaluate('document.querySelector(\'[aria-label="Select definitions.local"]\').click()');
    await field(session, 'Maximum X', '4');
    await button(session, 'Update literal');
    assert.doesNotMatch(await session.evaluate('document.querySelector(".spatial-list").textContent'), /labels/, 'a list of strings is not spatial');
    await session.evaluate('document.querySelector(\'[aria-label="Select definitions.region"]\').click()');
    await field(session, 'Maximum Z', '0');
    await button(session, 'Update literal');
    await button(session, 'Apply changes');
    await session.wait('document.querySelector(".spatial-dialog [role=alert]").textContent.includes("input changed")', 'stale edit warning');
    assert.deepEqual(await session.evaluate('spatialCommit.operations[0].document.definitions.region'), [0,1,0,1,0,0], 'an edited six-number box keeps its form');
    assert.deepEqual(await session.evaluate('spatialCommit.operations[0].document.settings.labels'), ['x+','y+','z+']);
    assert.deepEqual(await session.evaluate('spatialCommit.definitions.shared'), [0,0,0]);
    assert.deepEqual(await session.evaluate('spatialCommit.operations[0].document.definitions.local.max'), [4,1,1]);
    await button(session, 'Cancel');
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});
