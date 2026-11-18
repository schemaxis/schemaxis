// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import test from 'node:test';
import {launch} from './harness.mjs';

test('ParaView Workbench authors and reopens separately named scene publications', {timeout: 120000}, async () => {
  const s = await launch({provider: 'paraview'});
  const draft = {version: 'schemaxis/1', nodes: [{id: 'left', filter: 'sphere'}, {id: 'right', filter: 'sphere'}],
    scenes: [{id: 'leftScene', geometry: ['left'], stateBundle: false}]};
  const editor = 'studio.windows.active().window.editor';
  const dialogButton = label => s.evaluate(`[...document.querySelectorAll('.operation-dialog button')]
    .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
  const edit = async index => {
    await s.evaluate(`(() => {
      ${editor}.revealPointer('/scenes/${index}/id');
      ${editor}.focus();
    })()`);
    const settings = '.wb-editor-tools [data-action=edit-settings]:not(:disabled)';
    await s.wait(`document.querySelector(${JSON.stringify(settings)})`, 'scene Settings action');
    await s.clickSelector(settings);
    await s.wait('document.querySelector(".operation-dialog")', 'scene settings');
  };
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const record = await studio.api.post('/api/documents', {action: 'new', provider: 'paraview',
        name: 'Scene instances', document: ${JSON.stringify(draft)}});
      await studio.refresh();
      studio.windows.open('workbench', {document: record.id});
    })()`);
    await s.wait(`studio.windows.active()?.window.editor?.getDocument()?.scenes?.length`, 'scene input');
    await edit(0);
    await dialogButton('Switch to multi-mode');
    await dialogButton('Add instance');
    await s.evaluate(`(() => {
      const row = document.querySelector('.multi-mode-row:nth-child(2)');
      row.querySelector('[data-name=left]').click();
      row.querySelector('[data-name=right]').click();
    })()`);
    assert.equal(await s.evaluate('document.querySelector(\'[aria-label="Row 2 Name"]\').value'), 'scene_right');
    await dialogButton('Apply instances');
    await s.wait(`${editor}.getDocument().scenes.length === 2`, 'both scenes applied');
    const saved = await s.evaluate(`${editor}.getDocument()`);
    assert.deepEqual(saved, {...draft, scenes: [draft.scenes[0], {id: 'scene_right', geometry: ['right'], stateBundle: false}]});
    await edit(1);
    assert.equal(await s.evaluate('document.querySelectorAll(".multi-mode-row").length'), 2);
    await dialogButton('Cancel');
    await s.evaluate(`${editor}.undo()`);
    assert.deepEqual(await s.evaluate(`${editor}.getDocument()`), draft);
    assert.deepEqual(s.exceptions, []);
    assert.deepEqual(s.consoleErrors, []);
  } finally {
    await s.close();
  }
});
