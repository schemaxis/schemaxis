// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

for (const [provider, phrase, operation] of [['gmsh','cuboid','box'], ['ngspice','Bode','acSweep']]) {
  test(`${provider} phrase reaches selection, Add and contextual Help in the browser`, {timeout:120000}, async () => {
    const session = await launch({provider});
    try {
      await session.wait('window.studio?.store.get().server', 'Studio');
      await session.evaluate(`window.studio.bus.emit('new-instance')`);
      await session.wait(`document.querySelector('[aria-label="Search adaptors"]')`, 'adaptor selection');
      await session.evaluate(`(() => {const e=document.querySelector('[aria-label="Search adaptors"]');e.value=${JSON.stringify(phrase)};e.dispatchEvent(new Event('input'));})()`);
      await session.wait(`document.querySelector('[role=listbox]')?.textContent.toLowerCase().includes(${JSON.stringify(provider)})`, 'matching adaptor');
      assert.ok(await session.evaluate(`document.querySelectorAll('[role=listbox] [role=option]').length`) > 0);
      await session.evaluate(`document.querySelector('.dialog-footer button').click()`);
      await session.evaluate(`(async () => {const ctx=window.studio;
        const r=await ctx.api.post('/api/documents',{action:'new',provider:${JSON.stringify(provider)},name:'Search example'});
        await ctx.refresh();ctx.windows.open('workbench',{document:r.id});})()`);
      await session.wait('document.querySelector("[data-add=all]")', 'Add catalogue');
      await session.clickSelector('[data-add=all]');
      await session.evaluate(`(() => {const e=document.querySelector('[aria-label="Search Add anything…"]');e.value=${JSON.stringify(phrase)};e.dispatchEvent(new Event('input'));})()`);
      await session.wait(`document.querySelector('[data-library="operation:${operation}"]')`, 'operation synonym');
      await session.clickSelector(`[data-library="operation:${operation}"]`);
      await session.wait('document.querySelector(".operation-form")', 'conceptual form');
      assert.match(await session.evaluate('document.querySelector(".operation-form").textContent'), provider === 'gmsh' ? /millimetres/ : /phasor/);
      await session.evaluate(`(() => {const d=[...document.querySelectorAll('.operation-form details')].find(d=>d.querySelector('summary')?.textContent==='? Operation reference');d.open=true;})()`);
      await session.wait(`document.querySelector('.operation-reference')?.textContent.includes(${JSON.stringify('Native binding:')})`, 'own reference');
      assert.match(await session.evaluate('document.querySelector(".operation-reference").textContent'), new RegExp(operation));
      if (provider === 'ngspice') {
        await session.evaluate(`([...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent==='Add operation')).click()`);
        await session.wait(`JSON.parse(window.studio.windows.active().window.editor.getValue()).operation==='acSweep'`, 'document operation replacement');
        const value = JSON.parse(await session.evaluate('window.studio.windows.active().window.editor.getValue()'));
        assert.ok(value.circuit); assert.equal(value.nodes, undefined);
      }
      assert.deepEqual(session.exceptions, []);
      assert.deepEqual(session.consoleErrors, []);
    } finally { await session.close(); }
  });
}
