// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import test from 'node:test';
import {launch} from './harness.mjs';

test('Workbench Body seed rows check the whole ownership edit before applying', {timeout: 120000}, async () => {
  const s = await launch({provider: 'freecad'});
  const draft = {version: 'schemaxis.freecad/1', output: 'stock', nodes: [
    {id: 'stock', filter: 'box'}, {id: 'leftBody', filter: 'body'},
    {id: 'rightBody', filter: 'body'}, {id: 'occupied', filter: 'body'},
    {id: 'existingSeed', filter: 'bodySeed', inputs: {body: 'occupied', source: 'stock'}},
  ]};
  const editor = 'studio.windows.active().window.editor';
  const click = label => s.evaluate(`[...document.querySelectorAll('.operation-dialog button')]
    .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
  const field = (label, value) => s.evaluate(`(() => {
    const input = document.querySelector(${JSON.stringify(`[aria-label="${label}"]`)});
    input.value = ${JSON.stringify(value)};
    input.dispatchEvent(new Event(input.tagName === 'SELECT' ? 'change' : 'input', {bubbles: true}));
  })()`);
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const record = await studio.api.post('/api/documents', {action: 'new', provider: 'freecad',
        name: 'Body seeds', document: ${JSON.stringify(draft)}});
      await studio.refresh();
      studio.windows.open('workbench', {document: record.id});
    })()`);
    await s.wait('document.querySelector("[data-add=filters]")', 'Workbench Add');
    const start = await s.evaluate(`${editor}.getValue()`);
    await s.clickSelector('[data-add="filters"]');
    await s.wait('document.querySelector(\'[data-library="operation:bodySeed"]\')', 'Body seed catalogue card');
    await s.evaluate('document.querySelector(\'[data-library="operation:bodySeed"]\').click()');
    await s.wait('document.querySelector(".operation-form")', 'Body seed settings');
    await field('bodySeed.inputs.body', 'leftBody');
    await field('bodySeed.inputs.source', 'stock');
    assert.equal(await s.evaluate('document.querySelector(\'[aria-label="bodySeed.id"]\').value'),
      'bodySeed_leftBody_stock');
    await click('Switch to multi-mode');
    await click('Add instance');
    await click('Apply instances');
    const fault = 'document.querySelector(".operation-wizard > .operation-error")?.textContent';
    await s.wait(`${fault}.includes("first member of an empty Body")`, 'repeated Body refused by planner');
    assert.equal(await s.evaluate(`${editor}.getValue()`), start);
    await field('Row 2.Empty Body', 'occupied');
    await click('Apply instances');
    await s.wait(`${fault}.includes("bodySeed_occupied_stock") && ${fault}.includes("first member of an empty Body")`,
      'occupied Body refused by planner');
    assert.equal(await s.evaluate(`${editor}.getValue()`), start);
    await field('Row 2.Empty Body', 'rightBody');
    await field('Row 2.External solid', 'existingSeed');
    await click('Apply instances');
    await s.wait(`${fault}.includes("refer to an external solid")`, 'Body-owned source refused by planner');
    assert.equal(await s.evaluate(`${editor}.getValue()`), start);
    await field('Row 2.External solid', 'stock');
    await field('Row 2 Name', 'seedTheRightBody');
    await click('Apply instances');
    await s.wait(`JSON.parse(${editor}.getValue()).nodes.length === 7`, 'both seeds applied');
    const result = JSON.parse(await s.evaluate(`${editor}.getValue()`));
    assert.deepEqual(result.nodes.slice(5).map(node => [node.id, node.inputs]), [
      ['bodySeed_leftBody_stock', {body: 'leftBody', source: 'stock'}],
      ['seedTheRightBody', {body: 'rightBody', source: 'stock'}],
    ]);
    await s.evaluate(`${editor}.undo()`);
    assert.deepEqual(JSON.parse(await s.evaluate(`${editor}.getValue()`)), draft);
    assert.deepEqual(s.exceptions, []);
    assert.deepEqual(s.consoleErrors, []);
  } finally {
    await s.close();
  }
});
