// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

test('a non-graph adaptor shows existing concepts and exports a scoped missing-field request', {timeout: 120000}, async () => {
  const session = await launch({provider: 'octave'});
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async () => {
      const ctx = window.studio;
      const record = await ctx.api.post('/api/documents', {action:'new', provider:'octave',name:'Numerical help'});
      await ctx.refresh();ctx.windows.open('workbench',{document:record.id});
      Object.defineProperty(navigator, 'clipboard', {value:{writeText:async text=>{window.guidanceCopy=text}}});
    })()`);
    await session.wait(`document.querySelector('[data-add=all]')`, 'complete Add menu');
    await session.clickSelector('[data-add=all]');
    await session.evaluate(`(() => {const e=document.querySelector('[aria-label="Search Add anything…"]');e.value='integral';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    await session.wait(`document.querySelector('[data-library="operation:integral"]')`, 'integral');
    await session.clickSelector('[data-library="operation:integral"]');
    await session.wait(`document.querySelector('.operation-form')`, 'form');
    assert.match(await session.evaluate(`document.querySelector('.operation-form').textContent`), /trapezoidal integral/);
    assert.match(await session.evaluate(`document.querySelector('.operation-form').textContent`), /strictly increasing/);
    await session.evaluate(`(() => {
      const d=[...document.querySelectorAll('.operation-form > details')].find(d=>d.querySelector('summary')?.textContent==='Suggest a correction');d.open=true;
      d.querySelector('button').click();})()`);
    await session.wait('window.guidanceCopy', 'copied record');
    const record = JSON.parse(await session.evaluate('window.guidanceCopy'));
    assert.equal(record.provider, 'octave'); assert.equal(record.operation, 'integral');
    assert.equal(record.version, 'schemaxis.octave/1'); assert.ok(record.examples.length);
    await session.evaluate(`document.querySelector('[aria-label="Help for integral.options.initial"]').click()`);
    const help = await session.evaluate(`document.querySelector('.operation-form').textContent`);
    assert.match(help, /Value of the running integral at the first x/);
    assert.doesNotMatch(help, /Conceptual explanation needed/);
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});
