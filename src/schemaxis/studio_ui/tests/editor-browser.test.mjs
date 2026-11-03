// Copyright (C) 2026 David L F Gaden
// Browser smoke test of the JSON editor in headless Chromium (no dependencies).
// Set EDITOR_SCREENSHOTS=<dir> to keep light/dark screenshots.
import assert from 'node:assert/strict';
import {join} from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';

import {launch, findChromium} from './fixtures/editor/cdp.mjs';
import {decodePng, bestShift, meanDifference} from './fixtures/editor/png.mjs';

const ROOT = fileURLToPath(new URL('../../../../', import.meta.url));
const PAGE = '/src/schemaxis/studio_ui/tests/fixtures/editor/demo.html';
const SHOTS = process.env.EDITOR_SCREENSHOTS || '';
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const frames = 'new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))';

async function ready(session, query) {
  await session.open(`${PAGE}?${query}`);
  await session.wait('window.demo && window.demo.ready', 'demo ready');
  await session.evaluate(frames);
}

const value = (session) => session.evaluate('window.demo.editor.getValue()');
const popupLabels = (session) => session.evaluate(`[...document.querySelectorAll(
  '.sx-ed-popup:not([hidden]) .sx-ed-item-label')].map((e) => e.firstChild.textContent)`);

async function setText(session, text, caretMarker = '|') {
  const offset = text.indexOf(caretMarker);
  const clean = text.replace(caretMarker, '');
  await session.evaluate(`(() => {
    const editor = window.demo.editor;
    editor.setValue(${JSON.stringify(clean)});
    editor.focus();
    editor.textarea.setSelectionRange(${offset}, ${offset});
  })()`);
  await session.evaluate(frames);
}

async function shoot(session, name) {
  if (SHOTS) {
    await session.screenshot(join(SHOTS, name));
  }
}

/** Compare the textarea's own glyphs with the highlight layer's glyphs. */
async function alignment(session) {
  const clip = await session.evaluate(`(() => {
    const sheet = document.styleSheets[document.styleSheets.length - 1];
    const rules = ['.align-a .sx-ed-lines { visibility: hidden; }', '.align-a .sx-ed-input { color: #000 !important; }',
      '.align-b .sx-ed-lines, .align-b .sx-ed-lines * { color: #000 !important; text-decoration: none !important; '
        + 'background: none !important; outline: none !important; }',
      '.align-a .sx-ed-current-line, .align-b .sx-ed-current-line { display: none; }'];
    if (!window.alignRules) {
      rules.forEach((rule) => sheet.insertRule(rule, sheet.cssRules.length));
      window.alignRules = true;
    }
    window.demo.editor.textarea.blur();
    const rect = document.querySelector('.sx-ed-main').getBoundingClientRect();
    return {x: rect.x, y: rect.y, width: rect.width - 16, height: rect.height - 16};
  })()`);
  await session.evaluate(`document.body.className = 'align-a'; ${frames}`);
  const a = decodePng(Buffer.from(await session.screenshot(null, clip), 'base64'));
  await session.evaluate(`document.body.className = 'align-b'; ${frames}`);
  const b = decodePng(Buffer.from(await session.screenshot(null, clip), 'base64'));
  await session.evaluate(`document.body.className = ''; ${frames}`);
  return {shift: bestShift(a, b, 3), difference: meanDifference(a, b)};
}

test('JSON editor in headless Chromium', {skip: findChromium() ? false : 'Chromium not available'}, async () => {
  const session = await launch({root: ROOT, width: 1100, height: 640});
  try {
    await ready(session, 'doc=paraview&theme=light');

    // Overlay text is pixel-aligned with the textarea, also when scrolled both ways.
    let result = await alignment(session);
    assert.deepEqual([result.shift.dx, result.shift.dy], [0, 0]);
    assert.ok(result.difference < 0.002, `difference ${result.difference}`);
    await session.evaluate(`(() => {
      const editor = window.demo.editor;
      editor.setValue(editor.getValue().replace('"contour"', '"contour", "long": "${'x'.repeat(220)} [ok]"'));
      editor.textarea.scrollTop = 137;
      editor.textarea.scrollLeft = 333;
    })()`);
    await session.evaluate(frames);
    result = await alignment(session);
    assert.deepEqual([result.shift.dx, result.shift.dy], [0, 0]);
    assert.ok(result.difference < 0.002, `scrolled difference ${result.difference}`);

    // Schema diagnostics appear as squiggles and gutter marks; hover shows the message.
    await ready(session, 'doc=paraview&theme=light');
    await session.wait(`window.demo.editor.getDiagnostics()
      .some((d) => d.message.includes('"crinkle" is not allowed'))`, 'validation');
    assert.ok(await session.evaluate(`document.querySelectorAll('.sx-diag-warning').length > 0`));
    assert.ok(await session.evaluate(`document.querySelectorAll('.sx-ed-gutter-mark').length > 0`));
    await session.evaluate(`window.demo.editor.revealPointer('/nodes/2/options/crinkle'); ${frames}`);
    const point = await session.evaluate(`(() => {
      const span = [...document.querySelectorAll('.sx-diag')].find((e) => e.textContent.includes('crinkle'));
      const rect = span.getBoundingClientRect();
      return {x: rect.x + 4, y: rect.y + rect.height / 2};
    })()`);
    await session.send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: point.x, y: point.y});
    await session.wait(`!document.querySelector('.sx-ed-tooltip').hidden`, 'hover tooltip');
    assert.match(await session.evaluate(`document.querySelector('.sx-ed-tooltip').textContent`), /not allowed/);
    await shoot(session, 'editor-light-hover.png');
    await session.send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: 5, y: 5});
    await session.wait(`document.querySelector('.sx-ed-tooltip').hidden`, 'tooltip hides');

    // Hovering a key shows its schema documentation.
    await session.evaluate(`window.demo.editor.revealPointer('/nodes/1/options/normal'); ${frames}`);
    const normal = await session.evaluate(`(() => {
      const span = [...document.querySelectorAll('.sx-tk-key')].find((e) => e.textContent === '"normal"');
      const rect = span.getBoundingClientRect();
      return {x: rect.x + 12, y: rect.y + rect.height / 2};
    })()`);
    await session.send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: normal.x, y: normal.y});
    await session.wait(`!document.querySelector('.sx-ed-tooltip').hidden`, 'schema hover');
    assert.match(await session.evaluate(`document.querySelector('.sx-ed-tooltip').textContent`), /azimuth/);
    await shoot(session, 'editor-light-schema-hover.png');
    await session.send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: 5, y: 5});

    // External (server) diagnostics map pointers to ranges; getCursor reports the pointer.
    await session.evaluate(`window.demo.editor.setDiagnostics([{pointer: '/nodes/1/filter', message: 'Native fault',
      severity: 'error'}])`);
    const external = await session.evaluate(`window.demo.editor.getDiagnostics().find((d) => d.source === 'server')`);
    assert.equal(external.message, 'Native fault');
    assert.equal((await value(session)).slice(external.from, external.to), '"slice"');
    assert.ok(await session.evaluate(`${frames}.then(() => document.querySelectorAll('.sx-diag-error').length > 0)`));
    await session.evaluate(`window.demo.editor.revealPointer('/nodes/1/filter')`);
    assert.equal((await session.evaluate(`window.demo.editor.getCursor()`)).pointer, '/nodes/1/filter');
    await session.evaluate(`window.demo.editor.setDiagnostics([])`);

    // Read-only editors ignore typing.
    await session.evaluate(`window.demo.editor.setReadOnly(true); window.demo.editor.focus()`);
    const frozen = await value(session);
    await session.type('{');
    assert.equal(await value(session), frozen);
    await session.evaluate(`window.demo.editor.setReadOnly(false)`);

    // Typing '"' in key position auto-closes and opens property completion; Enter accepts.
    await setText(session,
      '{\n  "version": "schemaxis/1",\n  "nodes": [\n    {\n      "id": "cut",\n      |\n    }\n  ]\n}');
    await session.type('"');
    await session.wait(`!document.querySelector('.sx-ed-popup').hidden`, 'key completion');
    assert.equal((await popupLabels(session))[0], 'filter');
    await session.key('Enter');
    await session.wait(`window.demo.editor.getValue().includes('"$fill":"filter"')`, 'property marker accepted');
    await session.wait(`!document.querySelector('.sx-fill-popover').hidden`, 'property fill popover');
    await session.evaluate(`(() => {
      const input = document.querySelector('.sx-fill-value');
      input.value = JSON.stringify('slice');
      input.dispatchEvent(new Event('input', {bubbles: true}));
    })()`);
    await session.evaluate(`document.querySelector('.sx-fill-actions .primary').click()`);
    await session.wait(`JSON.parse(window.demo.editor.getValue()).nodes[0].filter === 'slice'`, 'value accepted');
    await session.key('Escape');
    await shoot(session, 'editor-light-completion.png');

    // Option completion resolves the chosen discriminator in a new options object.
    await setText(session,
      '{"version":"schemaxis/1","nodes":[{"id":"cut","filter":"slice","options":{|}}]}');
    let text = await value(session);
    await session.key(' ', 2, 'Space');
    await session.wait(`!document.querySelector('.sx-ed-popup').hidden`, 'manual completion');
    assert.deepEqual(await popupLabels(session), ['origin', 'normal', 'crinkle', 'triangulate']);
    await session.key('Escape');
    assert.equal(await session.evaluate(`document.querySelector('.sx-ed-popup').hidden`), true);

    // The suggestions setting disables automatic popups but not Ctrl+Space.
    await session.evaluate(`window.demo.editor.setOption('suggestions', false)`);
    await session.type('"');
    await delay(150);
    assert.equal(await session.evaluate(`document.querySelector('.sx-ed-popup').hidden`), true);
    await session.key(' ', 2, 'Space');
    await session.wait(`!document.querySelector('.sx-ed-popup').hidden`, 'manual completion with suggestions off');
    await session.key('Escape');
    await session.evaluate(`window.demo.editor.setOption('suggestions', true)`);

    // Programmatic edits are undoable with Ctrl+Z.
    await ready(session, 'doc=paraview&theme=light');
    const original = await value(session);
    await session.evaluate(`window.demo.editor.insertAtPointer('/nodes/-', {id: 'extra', filter: 'wavelet'})`);
    assert.ok((await value(session)).includes('"extra"'));
    await session.evaluate(`window.demo.editor.focus()`);
    await session.key('z', 2, 'KeyZ');
    assert.equal(await value(session), original, 'Ctrl+Z undoes insertAtPointer');
    await session.key('y', 2, 'KeyY');
    assert.ok((await value(session)).includes('"extra"'), 'Ctrl+Y redoes');
    await session.key('z', 2, 'KeyZ');

    // Ghost preview renders without changing the value; commit is one undo step.
    await session.evaluate(`document.getElementById('demo-preview').click(); ${frames}`);
    assert.equal(await value(session), original);
    assert.ok(await session.evaluate(`document.querySelectorAll('.sx-ghost').length > 0`));
    const ghost = await session.evaluate(`[...document.querySelectorAll('.sx-ghost')]
      .map((e) => e.textContent).join('')`);
    assert.match(ghost, /"sliceX"/);
    await shoot(session, 'editor-light-preview.png');
    await session.evaluate(`document.getElementById('demo-commit').click(); ${frames}`);
    assert.ok((await value(session)).includes('"sliceX"'));
    assert.equal(await session.evaluate(`document.querySelectorAll('.sx-ghost').length`), 0);
    JSON.parse(await value(session));
    await session.key('z', 2, 'KeyZ');
    assert.equal(await value(session), original, 'commitPreview undoes in one step');

    // Format pretty-prints valid JSON (undoable); invalid JSON is left alone.
    await session.evaluate(`window.demo.editor.setValue('{"a":[1,2],"b":{"c":true}}')`);
    assert.equal(await session.evaluate(`window.demo.editor.format()`), true);
    assert.equal(await value(session), JSON.stringify({a: [1, 2], b: {c: true}}, null, 2));
    await session.evaluate(`window.demo.editor.setValue('{"a": }')`);
    assert.equal(await session.evaluate(`window.demo.editor.format()`), false);
    assert.ok(await session.evaluate(`window.demo.editor.getDiagnostics()[0].message === 'Expected a value'`));

    // Workflow: the nested gmsh document completes against the gmsh schema.
    await ready(session, 'doc=workflow&theme=dark');
    await session.evaluate(`(() => {
      const editor = window.demo.editor;
      const nodes = '"nodes": [\\n          {"id": "m", "filter": }\\n        ]';
      const text = editor.getValue().replace('"nodes": []', nodes);
      editor.setValue(text);
      editor.focus();
      const at = text.indexOf('"filter": ') + 10;
      editor.textarea.setSelectionRange(at, at);
    })()`);
    await session.key(' ', 2, 'Space');
    await session.wait(`!document.querySelector('.sx-ed-popup').hidden`, 'gmsh filters');
    const gmsh = await popupLabels(session);
    assert.ok(gmsh.includes('tetrahedral') && !gmsh.includes('slice'), gmsh.join(','));
    await shoot(session, 'editor-dark-workflow.png');
    await session.key('Escape');

    // Dark theme screenshots of completion with documentation and of diagnostics.
    await ready(session, 'doc=paraview&theme=dark');
    await session.evaluate(`(() => {
      const editor = window.demo.editor;
      const text = editor.getValue();
      const at = text.indexOf('"filter": "slice"') + 11;
      editor.focus();
      editor.textarea.setSelectionRange(at, at + 5);
    })()`);
    await session.type('sl');
    await session.key(' ', 2, 'Space');
    await session.wait(`!document.querySelector('.sx-ed-popup').hidden`, 'dark completion');
    await shoot(session, 'editor-dark-completion.png');
    await session.key('Escape');
    await session.evaluate(`document.getElementById('demo-preview').click(); ${frames}`);
    await shoot(session, 'editor-dark-preview.png');
    await session.evaluate(`window.demo.editor.clearPreview()`);

    // Large documents stay responsive: only visible lines are rendered, and a keystroke costs
    // little more than in a bare textarea holding the same text.
    const size = await session.evaluate(`(() => {
      const nodes = [];
      for (let index = 0; index < 6000; index += 1) {
        nodes.push({id: 'n' + index, filter: 'slice', inputs: {input: 'source'}, options: {normal: [0, 0, 1]}});
      }
      window.big = JSON.stringify({version: 'schemaxis/1', nodes}, null, 2);
      const bare = document.createElement('textarea');
      bare.id = 'bare';
      document.body.prepend(bare);
      bare.value = window.big;
      bare.focus();
      bare.setSelectionRange(window.big.length / 2, window.big.length / 2);
      return window.big.length;
    })()`);
    assert.ok(size > 1000000, `${size} characters`);
    const keystroke = async () => {
      const start = Date.now();
      const params = {key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65};
      await session.send('Input.dispatchKeyEvent', {type: 'keyDown', text: 'a', ...params});
      await session.send('Input.dispatchKeyEvent', {type: 'keyUp', ...params});
      await session.evaluate(frames);
      return Date.now() - start;
    };
    await keystroke();
    const bare = Math.min(await keystroke(), await keystroke());
    await session.evaluate(`(() => {
      document.getElementById('bare').remove();
      const editor = window.demo.editor;
      editor.setValue(window.big);
      editor.focus();
      editor.textarea.setSelectionRange(window.big.length / 2, window.big.length / 2);
      editor.textarea.scrollTop = editor.textarea.scrollHeight / 2;
    })()`);
    await session.evaluate(frames);
    await keystroke();
    const edited = Math.min(await keystroke(), await keystroke());
    assert.ok(await session.evaluate(`document.querySelectorAll('.sx-ed-line').length < 200`));
    assert.ok(edited < bare * 1.5 + 40, `editor ${edited} ms vs bare textarea ${bare} ms per keystroke`);
    console.log(`keystroke on ${size} characters: editor ${edited} ms, bare textarea ${bare} ms`);

    assert.deepEqual(session.exceptions, []);
    assert.deepEqual(session.logs.filter((line) => /Content Security Policy|Refused/.test(line)), []);
  } finally {
    await session.close();
  }
});
