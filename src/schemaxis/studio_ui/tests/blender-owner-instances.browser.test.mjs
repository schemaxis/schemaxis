// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import test from 'node:test';
import {launch} from './harness.mjs';

test('Blender Workbench checks binding ownership for compact instance rows', {timeout: 120000}, async () => {
  const s = await launch({provider: 'blender'});
  const mesh = {kind: 'mesh', vertices: [[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces: [[0, 1, 2]]};
  const draft = {version: 'schemaxis.blender.production/1', id: 'checkBindings', prepareOnly: true,
    cameras: [{direction: [1, -2, 1]}], size: [32, 32], production: {
      objects: [{...mesh, id: 'left'}, {...mesh, id: 'right', location: [1, 0, 0]}],
      materialGraphs: [{id: 'paint', nodes: [{id: 'shader', kind: 'principled'}, {id: 'out', kind: 'output'}],
        links: [{from: {node: 'shader', socket: 'shader'}, to: {node: 'out', socket: 'surface'}}]}],
      materialBindings: [{object: 'left', material: 'paint'}],
    }};
  const editor = 'studio.windows.active().window.editor';
  const click = label => s.evaluate(`[...document.querySelectorAll('.dialog-backdrop:last-child button')]
    .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const record = await studio.api.post('/api/documents', {action: 'new', provider: 'blender',
        name: 'Binding instances', document: ${JSON.stringify(draft)}});
      await studio.refresh();
      studio.windows.open('workbench', {document: record.id});
    })()`);
    await s.wait('studio.windows.active()?.window.editor?.getDocument()?.production?.objects?.length', 'production input');
    await s.evaluate(`(() => {
      ${editor}.revealPointer('/production/materialBindings/0/object');
      ${editor}.focus();
    })()`);
    const settings = '.wb-editor-tools [data-action="edit-settings"]:not(:disabled)';
    await s.wait(`document.querySelector(${JSON.stringify(settings)})`, 'production Settings action');
    await s.clickSelector(settings);
    await s.wait('document.querySelector(".operation-form")', 'production settings');
    await s.evaluate(`[...document.querySelector('[aria-label="production.materialBindings[0].object"]')
      .closest('.operation-array-item').querySelectorAll(':scope > button')]
      .find(button => button.textContent === 'Create sibling instances…').click()`);
    await s.wait('document.querySelector(".multi-mode-row")', 'binding rows');
    await click('Add instance');
    assert.equal(await s.evaluate('document.querySelector(\'[aria-label="Row 2 Name"]\')'), null);
    await click('Use instances');
    await click('Apply changes');
    await s.wait('document.querySelector(".operation-wizard > .operation-error")?.textContent.includes("duplicate binding")',
      'planner rejects a second binding for one owner');
    assert.deepEqual(await s.evaluate(`${editor}.getDocument()`), draft);
    await s.evaluate(`(() => {
      const owner = document.querySelector('[aria-label="production.materialBindings[1].object"]');
      owner.value = 'right';
      owner.dispatchEvent(new Event('input', {bubbles: true}));
    })()`);
    await click('Apply changes');
    await s.wait(`${editor}.getDocument().production.materialBindings.length === 2`, 'bindings applied');
    const expected = structuredClone(draft);
    expected.production.materialBindings.push({object: 'right', material: 'paint'});
    assert.deepEqual(await s.evaluate(`${editor}.getDocument()`), expected);
    assert.deepEqual(s.exceptions, []);
    assert.deepEqual(s.consoleErrors, []);
  } finally {
    await s.close();
  }
});
