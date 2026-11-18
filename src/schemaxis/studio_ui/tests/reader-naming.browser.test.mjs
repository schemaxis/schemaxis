// Copyright (C) 2026 David L. F. Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

const source = 'window.studio.windows.active().window.editor.getDocument()';
const nameSelector = '[aria-label="foam.id"]';
const fileSelector = '[aria-label="foam.options.file"]';
async function set(session, selector, value, event = 'change') {
  await session.evaluate(`(() => { const input = document.querySelector(${JSON.stringify(selector)});
    input.value = ${JSON.stringify(value)}; input.dispatchEvent(new Event(${JSON.stringify(event)}, {bubbles:true})); })()`);
}

test('reader instance Name follows parent_fileStem until the user names it', {timeout: 120000}, async () => {
  const session = await launch({provider: 'paraview'});
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async () => {
      const ctx = window.studio;
      const record = await ctx.api.post('/api/documents', {action:'new',provider:'paraview',name:'Reader names',
        document:{version:'schemaxis/1',nodes:[],scenes:[]}});
      await ctx.refresh(); ctx.windows.open('workbench', {document:record.id});
    })()`);
    await session.wait('document.querySelector("[data-add=inputs]")', 'Add input');
    const add = async () => {
      await session.clickSelector('[data-add=inputs]');
      await set(session, '[aria-label="Search Add Input"]', 'foam', 'input');
      await session.clickSelector('[data-library="operation:foam"]');
      await session.wait(`document.querySelector(${JSON.stringify(fileSelector)})`, 'Reader form');
    };
    await add();
    await set(session, fileSelector, '/cases/004_031_9d/case.foam');
    assert.equal(await session.evaluate(`document.querySelector(${JSON.stringify(nameSelector)}).value`), '004_031_9d_case');
    await set(session, fileSelector, '/cases/004_031_9d/004_031_9d.foam');
    assert.equal(await session.evaluate(`document.querySelector(${JSON.stringify(nameSelector)}).value`), '004_031_9d');
    // Even explicitly entering the current suggestion makes it the user's name.
    await set(session, nameSelector, '004_031_9d', 'input');
    await set(session, fileSelector, '/cases/other/case.foam');
    assert.equal(await session.evaluate(`document.querySelector(${JSON.stringify(nameSelector)}).value`), '004_031_9d');
    await session.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b => b.textContent === 'Cancel').click()`);
    assert.equal((await session.evaluate(source)).nodes.length, 0);

    await add();
    await set(session, fileSelector, '/cases/004_031_9d/case.foam');
    // This test covers authoring and planning; the empty case is not native IO.
    await session.evaluate(`window.studio.api.post = ((post) => (path, body) => path === '/api/inspect-input' && body.prepare
      ? Promise.resolve({job:'reader-name-fixture'}) : post(path, body))(window.studio.api.post.bind(window.studio.api));
      window.studio.api.waitForJob = ((wait) => id => id === 'reader-name-fixture'
      ? Promise.resolve({result:{value:{id:'004_031_9d_case',filter:'foam',options:{file:'/cases/004_031_9d/case.foam'}}}})
      : wait(id))(window.studio.api.waitForJob.bind(window.studio.api));`);
    await session.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b => b.textContent === 'Add operation').click()`);
    await session.wait(`${source}.nodes.length === 1`, 'Reader added');
    assert.equal((await session.evaluate(source)).nodes[0].id, '004_031_9d_case');
    assert.deepEqual(session.exceptions, []);
    assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});
