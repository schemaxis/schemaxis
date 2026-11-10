// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {join} from 'node:path';
import {launch} from './harness.mjs';

for (const theme of ['light', 'dark']) {
  test(`help navigation, search, context and examples (${theme})`, {timeout: 90000}, async () => {
    const session = await launch({provider: 'paraview', theme});
    try {
      await session.wait('window.studio?.store.get().server', 'Studio');
      await session.clickSelector('.rail-button[aria-label="Help"]');
      await session.wait('document.querySelector(".help-source")?.textContent.startsWith("Schemaxis Studio guide")', 'Studio guide');
      await session.clickSelector('.help-shortcuts button:nth-child(3)');
      await session.wait('document.querySelector(".help-article")?.textContent.includes("Code snapshot")', 'guide');
      assert.ok(await session.evaluate('document.querySelectorAll(".help-diagram").length >= 3'));
      assert.ok(await session.evaluate('document.querySelectorAll(".help-article table").length > 5'));
      // Search the complete inventory, not only the currently loaded guide.
      await session.evaluate(`document.querySelector('[aria-label="Search help"]').value = 'pvClip'; document.querySelector('[aria-label="Search help"]').dispatchEvent(new Event('input'))`);
      await session.wait('document.querySelector(".help-topic strong")?.textContent === "pvClip"', 'search');
      await session.clickSelector('.help-topic');
      await session.wait('document.querySelector(".help-source")?.textContent.startsWith("pvClip ·")', 'operation');
      assert.ok(await session.evaluate('document.querySelector(".help-article").textContent.includes("ClipType")'));
      await session.clickSelector('[aria-label="Previous help topic"]');
      await session.wait('document.querySelector(".help-source")?.textContent.startsWith("ParaView adaptor documentation guide")', 'back');
      await session.clickSelector('[aria-label="Next help topic"]');
      await session.wait('document.querySelector(".help-source")?.textContent.startsWith("pvClip ·")', 'forward');
      // Existing singleton window accepts new context and shows the right operation.
      await session.evaluate('window.studio.openHelp({provider:"paraview", operation:"slice"})');
      await session.wait('document.querySelector(".help-source")?.textContent.startsWith("slice ·")', 'context');
      await session.clickSelector('.help-shortcuts button:nth-child(2)');
      await session.wait('document.querySelector(".help-source")?.textContent.startsWith("Shared `$` authoring reference")', '$ reference');
      await session.evaluate(`document.querySelectorAll('.help-toc button')[4].click()`);
      assert.ok(await session.evaluate('document.activeElement.id.startsWith("help-")'));
      // Copy is literal authored JSON, no transformation.
      await session.send('Browser.grantPermissions', {origin: new URL(session.url).origin, permissions: ['clipboardReadWrite', 'clipboardSanitizedWrite']});
      await session.evaluate('document.querySelector(".help-code button").scrollIntoView({block:"center"})');
      await session.clickSelector('.help-code button');
      await session.wait('document.querySelector(".help-code button")?.textContent === "Copied"', 'copied example');
      assert.ok(await session.evaluate('navigator.clipboard.readText().then(text => text.includes("$document"))'));
      if (process.env.STUDIO_SCREENSHOTS) await session.screenshot(join(process.env.STUDIO_SCREENSHOTS, `studio-help-${theme}.png`));
      // Workbench Help uses the selected node and preserves unsaved editor text.
      await session.evaluate(`(async () => {
        const ctx = window.studio;
        const record = await ctx.api.post('/api/documents', {action:'new', provider:'paraview', name:'Help context',
          document:{version:'schemaxis/1', nodes:[{id:'data',filter:'wavelet'},
            {id:'cut',filter:'slice',inputs:{input:'data'}}], scenes:[{id:'out',geometry:['cut']}]}});
        await ctx.refresh(); ctx.windows.open('workbench',{document:record.id});
      })()`);
      await session.wait('window.studio.windows.active().window.store?.get().schema', 'Workbench');
      await session.clickSelector('.wb-outline-item[data-pointer="/nodes/1"]');
      const authored = await session.evaluate(`(() => {
        const editor = window.studio.windows.active().window.editor;
        editor.setValue(editor.getValue() + ' '); return editor.getValue();
      })()`);
      await session.clickSelector('.wb-workbench [data-action="help"]');
      await session.wait('document.querySelector(".help-source")?.textContent.startsWith("slice ·")', 'selected operation help');
      assert.equal(await session.evaluate('[...window.studio.windows.instances.values()].find(item => item.type === "workbench").window.editor.getValue()'), authored);
      await session.clickSelector('.help-shortcuts button:nth-child(2)');
      await session.wait('document.querySelector(".help-source")?.textContent.startsWith("Shared `$` authoring reference")', 'shared reference');
      // End the unsaved-input check before reloading (which correctly guards dirty editors).
      await session.evaluate(`(() => {
        const workbench = [...window.studio.windows.instances.values()].find(item => item.type === 'workbench').window;
        workbench.editor.setValue(workbench.store.get().record.source);
      })()`);
      // Help is available in user mode and restores its selected topic after reload.
      await session.evaluate(`window.studio.api.post('/api/settings', {action:'write', values:{role:'user'}, role:'dev'}).then(settings => window.studio.store.set({settings}))`);
      await session.send('Page.reload');
      await session.wait('window.studio?.windows.active()?.type === "help" && document.querySelector(".help-article")?.textContent.includes("$fill")', 'restored help');
      assert.deepEqual(session.exceptions, []);
      assert.deepEqual(session.consoleErrors.filter((message) => !message.includes('favicon')), []);
    } finally { await session.close(); }
  });
}

test('browser wait retries navigation transitions within its bound and preserves other errors', {timeout: 90000}, async () => {
  const session = await launch({provider: 'paraview'});
  const evaluate = session.evaluate.bind(session);
  const navigation = new Error(JSON.stringify({code: -32000, message: 'Inspected target navigated or closed'}));
  try {
    let calls = 0;
    session.evaluate = async (expression) => {
      calls += 1;
      if (calls === 1) throw navigation;
      return evaluate(expression);
    };
    await session.wait('document.readyState === "complete"', 'document after navigation');
    assert.ok(calls >= 2, 'the successful predicate must be observed after the protocol interruption');
    const application = new Error('application predicate failed');
    session.evaluate = async () => { throw application; };
    await assert.rejects(session.wait('true', 'application failure'), (error) => error === application);
    const unrelated = new Error(JSON.stringify({code: -32000, message: 'No such target id'}));
    session.evaluate = async () => { throw unrelated; };
    await assert.rejects(session.wait('true', 'unrelated protocol failure'), (error) => error === unrelated);
    session.evaluate = async () => { throw navigation; };
    await assert.rejects(session.wait('true', 'closed target stays unavailable', 1), /Timed out: closed target stays unavailable/);
  } finally {
    session.evaluate = evaluate;
    await session.close();
  }
});
