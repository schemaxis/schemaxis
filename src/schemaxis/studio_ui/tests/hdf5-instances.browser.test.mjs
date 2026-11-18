// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import test from 'node:test';
import {launch} from './harness.mjs';

test('HDF5 Workbench checks compact object paths and suggests Names for extracts', {timeout: 120000}, async () => {
  const s = await launch({provider: 'hdf5'});
  const draft = {version: 'schemaxis.hdf5/1', operation: 'createFile',
    objects: [{path: '/run/left', kind: 'dataset', type: {class: 'float', bits: 64},
      shape: [2], data: {source: 'values', values: [2, 4]}}],
    links: [{path: '/run/reserved', kind: 'hard', target: '/run/left'}],
    extracts: [{id: 'leftcsv', dataset: '/run/left', format: 'csv'}]};
  const editor = 'studio.windows.active().window.editor';
  const click = (label, scope = '.dialog-backdrop:last-child') => s.evaluate(`[...document.querySelectorAll(${JSON.stringify(scope + ' button')})]
    .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
  const field = (label, value) => s.evaluate(`(() => {
    const input = document.querySelector(${JSON.stringify(`[aria-label="${label}"]`)});
    input.value = ${JSON.stringify(value)};
    input.dispatchEvent(new Event('input', {bubbles: true}));
  })()`);
  const value = label => s.evaluate(`document.querySelector(${JSON.stringify(`[aria-label="${label}"]`)}).value`);
  const edit = async section => {
    await s.wait(`studio.windows.active()?.window.editor?.getDocument()?.${section}?.length`, `${section} in input`);
    await s.evaluate(`(() => {
      ${editor}.revealPointer('/${section}/0');
      ${editor}.focus();
    })()`);
    const settings = '.wb-editor-tools [data-action=edit-settings]:not(:disabled)';
    await s.wait(`document.querySelector(${JSON.stringify(settings)})`, 'enabled Edit settings');
    await s.evaluate(`document.querySelector(${JSON.stringify(settings)}).click()`);
    await s.wait('document.querySelector(".operation-form")', 'section settings');
  };
  const siblings = async (label) => {
    await s.evaluate(`[...document.querySelector(${JSON.stringify(`[aria-label="${label}"]`)})
      .closest('.operation-array-item').querySelectorAll(':scope > button')]
      .find(button => button.textContent === 'Create sibling instances…').click()`);
    await s.wait('document.querySelector(".multi-mode-row,.multi-mode .operation-error,.toast.error")', 'nested compact rows or fault');
    const issue = await s.evaluate(`([...document.querySelectorAll('.operation-error,.toast')].map(el=>el.textContent).filter(Boolean))`);
    assert.equal(await s.evaluate('document.querySelectorAll(".multi-mode-row").length'), 1, JSON.stringify(issue));
    await click('Add instance');
  };
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const record = await studio.api.post('/api/documents', {action: 'new', provider: 'hdf5',
        name: 'HDF5 instances', document: ${JSON.stringify(draft)}});
      await studio.refresh();
      studio.windows.open('workbench', {document: record.id});
    })()`);
    await edit('objects');
    const start = await s.evaluate(`${editor}.getValue()`);
    await siblings('objects[0].path');
    assert.equal(await s.evaluate('document.querySelector(\'[aria-label="Row 2 Name"]\')'), null);
    await field('Row 2.HDF5 path', '/run/reserved');
    await click('Use instances');
    await click('Apply changes');
    await s.wait('document.querySelector(".operation-wizard > .operation-error")?.textContent.includes("link path collides")',
      'link and object collision refused by planner');
    assert.equal(await s.evaluate(`${editor}.getValue()`), start);
    await field('objects[1].path', '/run/right');
    await click('Apply changes');
    await s.wait(`${editor}.getDocument().objects.length === 2`, 'two objects applied');
    const withObjects = await s.evaluate(`${editor}.getDocument()`);
    assert.deepEqual(withObjects.objects[1], {...draft.objects[0], path: '/run/right'});
    assert.deepEqual(withObjects.links, draft.links);

    await edit('extracts');
    await siblings('extracts[0].dataset');
    await field('Row 2.Dataset', '/run/right');
    assert.equal(await value('Row 2 Name'), 'extract_right_csv');
    await field('Row 2 Name', 'right_values');
    await click('Use instances');
    await click('Apply changes');
    await s.wait(`${editor}.getDocument().extracts.length === 2`, 'independent extracts applied');
    const result = await s.evaluate(`${editor}.getDocument()`);
    assert.deepEqual(result.extracts, [draft.extracts[0], {id: 'right_values', dataset: '/run/right', format: 'csv'}]);
    await s.evaluate(`${editor}.undo()`);
    assert.deepEqual(await s.evaluate(`${editor}.getDocument()`), withObjects);
    assert.deepEqual(s.exceptions, []);
    assert.deepEqual(s.consoleErrors, []);
  } finally {
    await s.close();
  }
});
