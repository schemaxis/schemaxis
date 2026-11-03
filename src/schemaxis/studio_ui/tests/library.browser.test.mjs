// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {join} from 'node:path';
import test from 'node:test';
import {launch} from './fixtures/editor/cdp.mjs';
import {fileURLToPath} from 'node:url';

for (const theme of ['light', 'dark']) {
  test(`Library keyboard search, composite ghost, atomic insertion and undo (${theme})`, {timeout: 90000}, async () => {
    const session = await launch({root: fileURLToPath(new URL('../', import.meta.url)), width: 1440, height: 960});
    try {
      await session.open('/tests/fixtures/library/demo.html');
      await session.wait('window.libraryDemo', 'library fixture');
      await session.evaluate(`document.documentElement.dataset.theme = '${theme}';
        new Promise((resolve) => setTimeout(resolve, 180))`);
      await session.evaluate(`document.querySelector('[data-category="slicing"]').click()`);
      await session.wait('document.querySelector(".library-popover")', 'category popover');
      await session.evaluate(`(() => {
        const input = document.querySelector('.library-popover input');
        input.value = 'unmatched';
        input.dispatchEvent(new Event('input', {bubbles: true}));
      })()`);
      assert.match(await session.evaluate('document.querySelector(".library-grid").textContent'), /No matching/);
      await session.evaluate(`(() => {
        const input = document.querySelector('.library-popover input');
        input.value = 'slice';
        input.dispatchEvent(new Event('input', {bubbles: true}));
      })()`);
      await session.key('ArrowDown');
      await session.wait('document.querySelector(".sx-ed-previewing")', 'multi-insert ghost');
      assert.deepEqual(await session.evaluate('JSON.parse(window.libraryDemo.editor.getValue())'),
        await session.evaluate('window.libraryDemo.initial'));
      assert.match(await session.evaluate('document.querySelector(".library-popover .library-summary").textContent'),
        /\/axes\/.*\/scenes\/0\/visible/);
      const shots = process.env.STUDIO_SCREENSHOTS;
      if (shots) {
        await mkdir(shots, {recursive: true});
        await session.screenshot(join(shots, `studio-library-${theme}.png`));
      }
      await session.key('Enter');
      await session.wait('JSON.parse(window.libraryDemo.editor.getValue()).nodes.length === 4', 'snippet inserted');
      assert.equal(await session.evaluate('JSON.parse(window.libraryDemo.editor.getValue()).axes.length'), 1);
      assert.ok(await session.evaluate('window.libraryDemo.editor.getValue().includes("$fill")'));
      await session.key('Escape');
      await session.evaluate('window.libraryDemo.editor.focus()');
      await session.key('z', 2);
      await session.wait('JSON.parse(window.libraryDemo.editor.getValue()).nodes.length === 1', 'one undo group');
      await session.key('k', 2);
      await session.wait('document.querySelector(".palette-results")', 'command palette');
      assert.match(await session.evaluate('document.querySelector(".palette-results").textContent'),
        /Insert snippet: X, Y and Z slice arrays/);
      assert.deepEqual(await session.evaluate('window.libraryDemo.errors'), []);
      assert.deepEqual(session.exceptions, []);
    } finally {
      await session.close();
    }
  });
}
