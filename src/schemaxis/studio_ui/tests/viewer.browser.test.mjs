// Copyright (C) 2026 David L F Gaden
// Acceptance checks for the four shared viewers under the fixture's strict CSP.
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import {findChromium, launch} from './fixtures/editor/cdp.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const shots = process.env.STUDIO_SCREENSHOTS;
const view3d = `demo.viewers['3d']`;
const image = 'demo.viewers.image';
const table = 'demo.viewers.table';
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function point(session, selector) {
  return session.evaluate(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) throw Error('Missing element: ' + ${JSON.stringify(selector)});
    const rect = element.getBoundingClientRect();
    return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
  })()`);
}

async function click(session, at) {
  await session.send('Input.dispatchMouseEvent', {type: 'mouseMoved', ...at});
  await session.send('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, ...at});
  await session.send('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...at});
}

async function drag(session, from, to) {
  await session.send('Input.dispatchMouseEvent', {type: 'mouseMoved', ...from});
  await session.send('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', buttons: 1,
    clickCount: 1, ...from});
  for (let i = 1; i <= 8; i++) {
    await session.send('Input.dispatchMouseEvent', {type: 'mouseMoved', button: 'left', buttons: 1,
      x: from.x + (to.x - from.x) * i / 8, y: from.y + (to.y - from.y) * i / 8});
  }
  await session.send('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...to});
}

async function field(session, selector, value) {
  await session.evaluate(`(() => {
    const input = document.querySelector(${JSON.stringify(selector)});
    input.value = ${JSON.stringify(value)};
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  })()`);
}

async function button(session, selector, label) {
  await session.evaluate(`(() => {
    const item = [...document.querySelectorAll(${JSON.stringify(selector)} + ' button')]
      .find((item) => item.textContent.trim() === ${JSON.stringify(label)});
    if (!item || item.disabled) throw Error('Missing enabled button: ' + ${JSON.stringify(label)});
    item.click();
  })()`);
}

async function capture(session, name, theme) {
  if (shots) {
    await mkdir(shots, {recursive: true});
    await session.screenshot(join(shots, `studio-viewers-${name}-${theme}.png`));
  }
}

async function geometry(session) {
  assert.ok(await session.evaluate(`${view3d}.coveredPixels()`) > 10000, 'actual WebGL geometry is drawn');
  const before = await session.evaluate(`${view3d}.getCamera()`);
  const centre = await point(session, '#slot-3d canvas');
  await drag(session, centre, {x: centre.x + 65, y: centre.y + 35});
  await session.wait(`${view3d}.getCamera().yaw !== ${before.yaw}`, 'orbit changes camera');
  await session.evaluate(`${view3d}.setView('+z')`);
  await session.wait(`Math.abs(${view3d}.getCamera().pitch - Math.PI / 2) < 0.001`, 'top view animation');
  const face = await session.evaluate(`${view3d}.projectToClient([-45, 0, 40])`);
  await click(session, face);
  const picked = await session.evaluate('demo.picks.at(-1)');
  assert.equal(picked.object, 'Box');
  assert.equal(picked.subelement, 'Face6');
  assert.equal(picked.document, 'demo');
  assert.equal(picked.revision, 3);
  assert.ok(picked.point.every((value, i) => Math.abs(value - [-45, 0, 40][i]) < 0.5));
  const fullPixels = await session.evaluate(`${view3d}.coveredPixels()`);
  await field(session, '[aria-label="Section plane"]', '0');
  assert.equal(await session.evaluate(`${view3d}.getSection().axis`), 0);
  const cutPixels = await session.evaluate(`${view3d}.coveredPixels()`);
  assert.ok(cutPixels > 0 && cutPixels < fullPixels, 'section removes visible geometry');
  await click(session, await point(session, '[aria-label="Flip kept side"]'));
  assert.equal(await session.evaluate(`${view3d}.getSection().side`), -1);
  assert.equal(await session.evaluate(`${view3d}.pickAt(${face.x}, ${face.y})`), null,
    'clipped native element cannot be picked');
  await field(session, '[aria-label="Section plane"]', 'off');
  await field(session, '[aria-label="Navigation"]', 'walk');
  const eye = await session.evaluate(`${view3d}.getCamera().eye`);
  await session.send('Input.dispatchKeyEvent', {type: 'rawKeyDown', key: 'w', code: 'KeyW'});
  await delay(160);
  await session.send('Input.dispatchKeyEvent', {type: 'keyUp', key: 'w', code: 'KeyW'});
  assert.notDeepEqual(await session.evaluate(`${view3d}.getCamera().eye`), eye, 'walk moves eye');
  await field(session, '[aria-label="Navigation"]', 'orbit');
  await session.evaluate(`${view3d}.setView('iso')`);
}

async function pixels(session) {
  const at = await session.evaluate(`(() => {
    const rect = document.querySelector('#slot-image canvas').getBoundingClientRect();
    const transform = ${image}.getTransform();
    return {x: rect.left + transform.x + 71.5 * transform.scale,
      y: rect.top + transform.y + 41.5 * transform.scale};
  })()`);
  const original = await session.evaluate(`${image}.getTransform()`);
  const pixel = await session.evaluate(`${image}.pixelAtClient(${at.x}, ${at.y})`);
  await session.send('Input.dispatchMouseEvent', {type: 'mouseWheel', ...at, deltaX: 0, deltaY: -180});
  await session.wait(`${image}.getTransform().scale > ${original.scale}`, 'image wheel zoom');
  assert.deepEqual(await session.evaluate(`${image}.pixelAtClient(${at.x}, ${at.y})`), pixel,
    'zoom keeps the pixel under the cursor');
  const zoomed = await session.evaluate(`${image}.getTransform()`);
  await drag(session, at, {x: at.x + 36, y: at.y + 25});
  const panned = await session.evaluate(`${image}.getTransform()`);
  assert.ok(Math.abs(panned.x - zoomed.x - 36) < 1 && Math.abs(panned.y - zoomed.y - 25) < 1);
  const expected = await session.evaluate(`${image}.pixelAtClient(${at.x + 36}, ${at.y + 25})`);
  await click(session, {x: at.x + 36, y: at.y + 25});
  assert.deepEqual(await session.evaluate('demo.picks.at(-1)'), expected);
  assert.equal(expected.width, 160);
  assert.equal(expected.height, 100);
  assert.match(expected.digest, /^[a-f0-9]{64}$/);
  await session.wait(`document.querySelector('#slot-image .vw-status-main').textContent.includes('RGBA')`,
    'actual decoded pixel readout');
}

async function rows(session) {
  await session.evaluate(`${table}.load({
    columns:Array.from({length:50},(_,i)=>({name:'column '+i,type:'integer'})),
    rows:Array.from({length:100000},(_,r)=>Array.from({length:50},(_,c)=>r*50+c))})`);
  await session.evaluate(`${table}.select({rows:[99999],columns:[49]},true)`);
  await session.wait(`document.querySelector('#slot-table .vw-tr[data-row="99999"]')`, 'last virtualised row');
  assert.equal(await session.evaluate(`${table}.getSelection().value`), 4999999);
  assert.ok(await session.evaluate(`${table}.renderedCells`) < 2000, 'large table virtualises rows and columns');
  await session.evaluate(`${table}.load({columns:['id','label','value'], rows:[
    [1,'Alpha [1]',4],[2,'beta',9],[3,'ALPHA [1]',7],[4,'gamma',2]], name:'row identities', revision:6})`);
  await session.wait(`document.querySelectorAll('#slot-table .vw-th-name').length === 3`, 'table headers');
  // Click the numeric column header twice: descending values 9, 7, 4, 2.
  await session.evaluate(`document.querySelectorAll('#slot-table .vw-th-cells .vw-th')[2].click()`);
  await session.evaluate(`document.querySelectorAll('#slot-table .vw-th-cells .vw-th')[2].click()`);
  await field(session, '#slot-table [aria-label="Filter rows"]', 'aLpHa [1]');
  await session.wait(`document.querySelector('#slot-table [role="grid"]').getAttribute('aria-rowcount') === '3'`,
    'two filtered rows');
  await click(session, await point(session, '#slot-table .vw-tr[data-row="0"] .vw-td[data-col="0"]'));
  await session.key('ArrowDown', 8);
  await session.key('ArrowRight', 8);
  await session.key('ArrowRight', 8);
  await session.key('Enter');
  const selection = await session.evaluate(`${table}.getSelection()`);
  assert.deepEqual(selection.sourceRows, [2, 0]);
  assert.deepEqual(selection.rows, [0, 1]);
  assert.deepEqual(selection.columns, [0, 2]);
  assert.equal(selection.revision, 6);
  assert.equal(selection.filter, 'aLpHa [1]');
  assert.equal(selection.sort.direction, 'desc');
  const copied = await session.evaluate(`(() => {
    const data = new DataTransfer();
    document.querySelector('#slot-table [role="grid"]').dispatchEvent(new ClipboardEvent('copy',
      {bubbles:true, cancelable:true, clipboardData:data}));
    return data.getData('text/plain');
  })()`);
  assert.equal(copied, '3\tALPHA [1]\t7\n1\tAlpha [1]\t4');
  assert.equal(await session.evaluate(`${table}.selectionText(true)`), `id\tlabel\tvalue\n${copied}`);
  await button(session, '#slot-table', 'Stats');
  assert.match(await session.evaluate(`document.querySelector('.vw-table-stats').textContent`), /Count2/);
  await field(session, '#slot-table [aria-label="Filter rows"]', 'missing');
  await session.wait(`${table}.renderedCells === 0`, 'empty filter hides rows');
  await session.evaluate(`${table}.select({rows:[0,99],columns:[0,99]},true)`);
  await session.key('ArrowDown');
  assert.equal(await session.evaluate(`${table}.getSelection()`), null);
  assert.equal(await session.evaluate(`${table}.selectionText()`), '');
  await field(session, '#slot-table [aria-label="Filter rows"]', 'ALPHA');
  await session.evaluate(`${table}.select({rows:[0,99],columns:[0,99]},true)`);
  assert.deepEqual(await session.evaluate(`${table}.getSelection().sourceRows`), [2, 0], 'selection bounds clamp');
}

async function textExtraction(session) {
  assert.equal(await session.evaluate('demo.viewers.text.lineCount'), 200000);
  assert.ok(await session.evaluate('demo.viewers.text.renderedRows') < 100, 'large text remains virtualised');
  await session.evaluate(`demo.viewers.text.scrollToLine(199990)`);
  await session.wait(`[...document.querySelectorAll('#slot-text .vw-text-gutter')]
    .some((item) => Number(item.textContent) >= 199990)`, 'virtual scroll');
  await field(session, '#slot-text [aria-label="Find in text"]', 'Solving for Ux');
  await session.wait(`document.querySelector('.vw-find-status').textContent.includes('22,222')`, 'large text search');
  await button(session, '#slot-text', 'Grep extract');
  await field(session, '#slot-text [aria-label="Row pattern"]',
    '^smoothSolver:  Solving for (?<field>Ux), Initial residual = (?<initial>\\S+),');
  await field(session, '#slot-text [aria-label="Context pattern"]', '^Time = (?<Time>\\S+)');
  await button(session, '#slot-text', 'Extract');
  await session.wait('demo.extracts.length === 1', 'named capture extraction');
  assert.deepEqual(await session.evaluate('demo.extracts[0].columns.map((column)=>column.name)'),
    ['line', 'Time', 'field', 'initial']);
  assert.equal(await session.evaluate('demo.extracts[0].rows.length'), 22222);
  await button(session, '#slot-text', 'Open in Table');
  await session.wait(`${table}.getTable().rows.length === 22222`, 'extraction in table viewer');
  await session.evaluate(`${table}.select({rows:[0,2],columns:[0,3]},true)`);
  assert.match(await session.evaluate(`${table}.selectionText(true)`), /^line\tTime\tfield\tinitial\n10\t0.005\tUx\t/);
  await session.evaluate(`${table}.showStats(false); ${table}.showPlot(true,{x:1,y:3,logY:true})`);
}

for (const theme of ['light', 'dark']) {
  test(`shared viewers orbit, clip, sample pixels, filter and extract (${theme})`,
    {skip: !findChromium(), timeout: 120000}, async () => {
      const session = await launch({root, path: `/tests/fixtures/viewers/demo.html?theme=${theme}&lines=200000`,
        width: 1680, height: 1120});
      try {
        await session.wait('window.demo?.ready', 'all four viewers ready');
        assert.deepEqual(await session.evaluate('demo.errors'), []);
        await geometry(session);
        await pixels(session);
        await rows(session);
        await capture(session, 'filter', theme);
        await textExtraction(session);
        await capture(session, 'extract', theme);
        assert.deepEqual(session.exceptions, []);
        assert.deepEqual(await session.evaluate('demo.errors'), []);
        assert.ok(!session.logs.some((message) => /content security policy|refused to (?:load|execute)/i.test(message)),
          session.logs.join('\n'));
      } finally {
        await session.close();
      }
    });
}
