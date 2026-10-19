import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {join} from 'node:path';
import {test} from 'node:test';
import {launch, delay} from './harness.mjs';

const active = 'window.studio.windows.active().window';
const editor = `${active}.editor`;
const shots = process.env.STUDIO_SCREENSHOTS;

async function start(session) {
  await session.wait('window.studio?.store.get().adaptors.length', 'adaptor catalogue');
  await session.evaluate(`(async () => {
    const ctx = window.studio;
    const record = await ctx.api.post('/api/documents', {action: 'new', provider: 'freecad', name: 'Calm input'});
    await ctx.refresh();
    ctx.windows.open('workbench', {document: record.id});
  })()`);
  await session.wait(`${active}.store?.get().schema`, 'workbench loaded');
  await session.evaluate(`(() => {
    const e = ${editor};
    e.setOption('suggestions', false);
    e.setValue('');
    e.focus();
    window.validationRequests = [];
    const post = studio.api.post.bind(studio.api);
    studio.api.post = (path, body) => {
      if (path === '/api/validate') validationRequests.push({source:body.source, time:Date.now()});
      return post(path, body);
    };
  })()`);
}

async function assertQuiet(session) {
  assert.equal(await session.evaluate(`${editor}.getDiagnostics().length`), 0);
  // Diagnostic state updates synchronously; its decorations render on the next
  // animation frame. Check that frame's DOM instead of racing a pending render.
  assert.equal(await session.evaluate(`new Promise(resolve => requestAnimationFrame(() =>
    resolve(document.querySelectorAll('.wb-editor-host .sx-diag').length)))`), 0);
  assert.equal(await session.evaluate('studio.notify.store.get().problems.length'), 0);
  assert.equal(await session.evaluate(`document.querySelectorAll('.toast').length`), 0);
}

for (const theme of ['light', 'dark']) {
  test(`Workbench character typing, settled errors and one grouped action (${theme})`, {timeout: 90000}, async () => {
    const session = await launch({theme});
    try {
      await start(session);
      await session.evaluate(`document.documentElement.dataset.theme = '${theme}'`);
      for (const char of '{"nodes') {
        await session.type(char);
        await delay(170);
        await assertQuiet(session);
      }
      await delay(1700);
      await assertQuiet(session);
      assert.equal(await session.evaluate(`document.querySelector('.wb-diagnostic-state').textContent`), 'Editing…');
      assert.equal(await session.evaluate('validationRequests.length'), 0);
      if (shots) {
        await mkdir(shots, {recursive: true});
        await session.screenshot(join(shots, `studio-settle-editing-${theme}.png`));
      }
      for (const char of '": [') {
        await session.type(char);
        await delay(170);
        await assertQuiet(session);
      }
      // Supply a complete document through normal character input, including nested options.
      await session.evaluate(`${editor}.setValue(''); ${editor}.focus(); validationRequests.length = 0`);
      const source = '{"version":"schemaxis.freecad/1","nodes":[{"id":"body","filter":"box",'
        + '"options":{"length":30,"width":20,"height":10}}],"output":"body"}';
      for (const char of source) {
        await session.type(char);
        await delay(12);
        await assertQuiet(session);
      }
      await delay(1700);
      await assertQuiet(session);
      assert.equal(await session.evaluate('validationRequests.length'), 1);
      // A genuinely invalid token is stable, and appears after 600 ms without global notifications.
      await session.type('!');
      await delay(250);
      await assertQuiet(session);
      await session.wait(`${editor}.getDiagnostics().some(d => d.settle === 'stable')`, 'settled syntax error');
      assert.equal(await session.evaluate('studio.notify.store.get().problems.length'), 0);
      assert.equal(await session.evaluate(`document.querySelectorAll('.toast').length`), 0);
      if (shots) await session.screenshot(join(shots, `studio-settle-stable-${theme}.png`));
      await session.clickSelector('[data-action="validate"]');
      await session.wait('studio.notify.store.get().problems.length > 0', 'grouped validation');
      assert.equal(await session.evaluate(`document.querySelectorAll('.toast').length`), 1);
      assert.match(await session.evaluate(`document.querySelector('.toast').textContent`), /problems? — see Problems/);
      assert.equal(await session.evaluate(`studio.notify.store.get().problems.every(p => p.actions.length)`), true);
      assert.equal(await session.evaluate(`new Set(studio.notify.store.get().problems.map(p => p.group)).size`), 1);
      assert.deepEqual(session.exceptions, []);
    } finally { await session.close(); }
  });
}

test('editor discards stale diagnostics and flushes transient text', {timeout: 90000}, async () => {
  const session = await launch();
  try {
    await start(session);
    await session.type('{"origin');
    await delay(200);
    const version = await session.evaluate(`${editor}.getTextVersion()`);
    await session.type('X');
    assert.equal(await session.evaluate(`${editor}.setDiagnostics([{message:'stale'}], {version:${version}})`), false);
    assert.equal(await session.evaluate(`${editor}.getDiagnostics().length`), 0);
    assert.ok(await session.evaluate(`${editor}.flushDiagnostics().length > 0`));
    assert.equal(await session.evaluate('studio.notify.store.get().problems.length'), 0);
    await session.evaluate(`${editor}.setValue(''); ${editor}.focus()`);
    await session.type('{"x":');
    await delay(200);
    await assertQuiet(session);
    await session.clickSelector('[data-tab="schema"]');
    await session.wait('studio.notify.store.get().problems.length > 0', 'tab departure diagnostics');
    assert.equal(await session.evaluate(`document.querySelectorAll('.toast').length`), 1);
    await session.evaluate(`studio.notify.store.get().problems[0].actions[0].run()`);
    assert.equal(await session.evaluate(`${active}.store.get().tab`), 'input');
  } finally { await session.close(); }
});
