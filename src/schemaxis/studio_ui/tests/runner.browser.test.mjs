// Copyright (C) 2026 David L F Gaden
// Real HTTP bind/plan/save/load flow. Optional bounded native Octave acceptance:
// STUDIO_RUN_NATIVE=1 runs the same case through the actual configured application.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {mkdir, readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {launch} from './harness.mjs';

const fixture = fileURLToPath(new URL('./runner-fixtures', import.meta.url));
const shots = process.env.STUDIO_SCREENSHOTS;

for (const theme of ['light', 'dark']) {
  test(`case runner binds, plans and preserves a typed case (${theme})`, {timeout: 120000}, async () => {
    const session = await launch({theme});
    try {
      await session.wait(`window.studio?.store.get().server`, 'Studio connection');
      await session.evaluate(`document.documentElement.dataset.theme = ${JSON.stringify(theme)};
        window.studio.windows.open('runner');`);
      await session.wait(`document.querySelector('.runner-template-bar input')`, 'Case Runner');
      await session.clickSelector('.runner-template-bar input');
      await session.type(fixture);
      await session.clickSelector('.runner-template-bar button');
      await session.wait(`document.querySelector('[data-parameter="stop"]')`, 'template parameters');
      assert.equal(await session.evaluate(`document.querySelectorAll('[data-parameter]').length`), 7);
      assert.equal(await session.evaluate(`document.querySelector('[data-parameter="enabled"]').value`), 'true');
      await session.evaluate(`(() => { const field = document.querySelector('[data-parameter="stop"]');
        field.value = '6.5'; field.dispatchEvent(new Event('input', {bubbles: true})); })()`);
      await session.clickSelector('.runner .actions button:first-child');
      await session.wait(`document.querySelector('.runner-flow .badge').textContent === 'Plan ready'`, 'plan');
      assert.equal(await session.evaluate(`document.querySelectorAll('.runner-operation').length`), 2);
      assert.match(await session.evaluate(`document.querySelector('.runner-plan-details pre').textContent`), /6.5/);
      await session.wait(`!document.querySelector('.runner-case-actions button:last-child').disabled`, 'save enabled');
      await session.clickSelector('.runner-case-actions button:last-child');
      await session.wait(`window.studio.notify.store.get().log.some(e => e.title === 'Case saved')`, 'saved case');
      const saved = JSON.parse(await readFile(join(session.workspace, 'cases/studio.sequence.json'), 'utf8'));
      assert.equal(saved.values.stop, 6.5);
      assert.equal(saved.values.enabled, true);
      assert.deepEqual(saved.values.direction, [1, 0, 0]);
      await session.evaluate(`document.querySelector('[data-parameter="stop"]').value = '3'`);
      await session.clickSelector('.runner-case-actions button:first-child');
      await session.wait(`document.querySelector('[data-parameter="stop"]').value === '6.5'`, 'loaded values');
      if (shots) {
        await mkdir(shots, {recursive: true});
        await session.evaluate(`document.querySelectorAll('.toast').forEach(element => element.remove())`);
        await session.screenshot(join(shots, `studio-runner-plan-${theme}.png`));
      }
      if (process.env.STUDIO_RUN_NATIVE === '1') {
        await session.wait(`!document.querySelector('.runner .actions .primary').disabled`, 'run enabled');
        await session.clickSelector('.runner .actions .primary');
        await session.wait(`document.querySelector('.runner .window-header > .badge')?.textContent === 'Verified'
          || document.querySelector('.runner-fault')`, 'native case completed', 80000);
        assert.equal(await session.evaluate(`document.querySelector('.runner-fault')?.textContent || ''`), '');
        await session.wait(`document.querySelector('.runner-viewer .vw-table-scroll')
          || document.querySelector('.runner-viewer .vw[data-state="ready"]')
          || document.querySelector('.runner-viewer canvas')`, 'output viewer');
        assert.equal(await session.evaluate(`document.querySelectorAll('.runner-output').length`), 4);
        if (shots) {
          await session.evaluate(`window.studio.store.set({panelOpen: false});
            document.querySelectorAll('.toast').forEach(element => element.remove());
            document.querySelector('.runner-results').scrollTop = 150;`);
          await session.screenshot(join(shots, `studio-runner-outputs-${theme}.png`));
        }
      }
      await session.evaluate(`(() => { const field = document.querySelector('[data-parameter="stop"]');
        field.value = '7'; field.dispatchEvent(new Event('input', {bubbles: true})); })()`);
      assert.equal(await session.evaluate(`window.studio.windows.instances.get('runner').window.isDirty()`), true);
      await session.clickSelector('.tab[aria-selected="true"] .tab-close');
      await session.wait(`document.querySelector('.dialog[aria-label="Discard unsaved case?"]')`, 'unsaved case guard');
      await session.key('Escape');
      assert.equal(await session.evaluate(`!!document.querySelector('.runner')`), true);
      assert.deepEqual(session.exceptions, []);
      assert.deepEqual(await session.evaluate(`window.studio.notify.store.get().problems`), []);
      assert.deepEqual(session.consoleErrors.filter((text) => !text.includes('favicon')), []);
    } finally {
      await session.close();
    }
  });
}
