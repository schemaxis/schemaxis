// Studio shell smoke test against a real server and headless Chromium.
// Set STUDIO_SCREENSHOTS=/some/dir to keep screenshots.

import assert from 'node:assert/strict';
import {test} from 'node:test';
import {join} from 'node:path';
import {launch} from './harness.mjs';

const shots = process.env.STUDIO_SCREENSHOTS;

for (const theme of ['light', 'dark']) {
  test(`shell renders and navigates (${theme})`, {timeout: 90000}, async () => {
    const session = await launch({theme});
    try {
      await session.wait(`document.querySelector('.studio') && window.studio && window.studio.store.get().server`,
        'shell and first state');
      if (theme === 'dark') {
        await session.evaluate(`window.studio.api.post('/api/settings', {action: 'write', values: {theme: 'dark'},
          role: 'dev'}).then((r) => window.studio.store.set({settings: r}))`);
        await session.evaluate(`document.documentElement.dataset.theme = 'dark'`);
      }
      await session.wait(`document.querySelector('.start-action')`, 'start actions');
      assert.equal(await session.evaluate(`document.querySelectorAll('.adaptor-card').length`),
        await session.evaluate(`window.studio.store.get().adaptors.filter(a=>!a.hostOnly).length`));
      if (shots) {
        await session.screenshot(join(shots, `studio-start-${theme}.png`));
      }

      // New adaptor instance from the dialog opens a Workbench tab.
      await session.clickSelector('.start-action:nth-child(2)');
      await session.wait(`document.querySelector('.dialog input[placeholder^="Search"]')`, 'instance dialog');
      await session.type('freecad');
      await session.wait(`document.querySelectorAll('.dialog .list-item').length === 1`, 'filtered list');
      await session.clickSelector('.dialog .list-item');
      if (shots) {
        await session.screenshot(join(shots, `studio-new-instance-${theme}.png`));
      }
      await session.clickSelector('.dialog .button.primary');
      await session.wait(`document.querySelector('.tab[aria-selected="true"] .label')?.textContent === 'freecad'`,
        'workbench tab opened');

      // Command palette opens with Ctrl+K and lists documents.
      await session.key('k', {modifiers: 2});
      await session.wait(`document.querySelector('.palette')`, 'palette');
      await session.type('settings');
      await session.key('Enter');
      await session.wait(`document.querySelector('.settings-group')`, 'settings window');
      if (shots) {
        await session.screenshot(join(shots, `studio-settings-${theme}.png`));
      }

      // A server fault surfaces as a toast and a Problems entry.
      const previousProblems = await session.evaluate(`window.studio.notify.store.get().problems.length`);
      await session.evaluate(`window.studio.call(() => window.studio.api.post('/api/documents',
        {action: 'new', provider: 'nonsense'}), {title: 'Expected failure'})`);
      await session.wait(`document.querySelector('.toast.error')`, 'error toast');
      assert.equal(await session.evaluate(`window.studio.notify.store.get().problems.length`), previousProblems + 1);
      assert.equal(await session.evaluate(`window.studio.notify.store.get().problems.at(-1).title`), 'Expected failure');

      // User mode offers case execution; the installed-adaptor list cannot create drafts.
      await session.evaluate(`window.studio.api.post('/api/settings', {action: 'write', values: {role: 'user'},
        role: 'dev'}).then((settings) => window.studio.store.set({settings}))`);
      await session.evaluate(`window.studio.windows.open('start')`);
      await session.wait(`document.querySelectorAll('.start-action').length === 1`, 'user actions');
      assert.equal(await session.evaluate(`document.querySelectorAll('.adaptor-card:not(:disabled)').length`), 0);
      assert.equal(await session.evaluate(`document.querySelector('.start-action .title').textContent`),
        'Run a template');

      assert.deepEqual(session.exceptions, []);
      assert.deepEqual(session.consoleErrors.filter((text) => !text.includes('status of 400') && !text.includes('favicon')), []);
    } finally {
      await session.close();
    }
  });
}
