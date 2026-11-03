// Copyright (C) 2026 David L F Gaden
// Designer acceptance: real authoring API, pointer wiring, controller round-trip and template export.

import assert from 'node:assert/strict';
import {mkdir, readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {test} from 'node:test';
import {delay, launch} from './harness.mjs';

const shots = process.env.STUDIO_SCREENSHOTS;
const operation = {version: 'schemaxis.octave/1', nodes: [
  {id: 'data', filter: 'sequence', options: {start: 0, stop: 4, count: 5}},
], outputs: ['data']};
const designer = `[...window.studio.designers.values()][0]`;
const state = `${designer}.model.store.get()`;

async function waitForReload(session) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    try {
      if (await session.evaluate(`!window.__designerOldPage && window.studio?.store.get().server`)) return;
    } catch (error) {
      if (!/navigated or closed|Execution context was destroyed|Cannot find context/.test(error.message)) throw error;
    }
    await delay(80);
  }
  throw Error('Reloaded Studio did not become ready');
}

async function field(session, selector, value) {
  await session.wait(`document.querySelector(${JSON.stringify(selector)})`, `field ${selector}`);
  await session.evaluate(`(() => {
    const input = document.querySelector(${JSON.stringify(selector)});
    if (!input) throw Error('Missing field: ' + ${JSON.stringify(selector)});
    input.value = ${JSON.stringify(value)};
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  })()`);
}

async function button(session, container, label) {
  const selector = `${container} button`;
  await session.wait(`[...document.querySelectorAll(${JSON.stringify(selector)})]
    .some((item) => item.textContent.trim() === ${JSON.stringify(label)} && !item.disabled)`, `button ${label}`);
  await session.evaluate(`(() => {
    const button = [...document.querySelectorAll(${JSON.stringify(selector)})]
      .find((item) => item.textContent.trim() === ${JSON.stringify(label)});
    if (!button || button.disabled) throw Error('Missing enabled button: ' + ${JSON.stringify(label)});
    button.click();
  })()`);
}

async function addOperation(session, id) {
  await session.evaluate(`document.querySelector('.dz-palette-item[data-adaptor="octave"]').focus()`);
  await session.key('Enter');
  await session.wait(`document.querySelector('.dialog input[name="id"]')`, 'operation dialog');
  await field(session, '.dialog input[name="id"]', id);
  await field(session, '.dialog textarea', JSON.stringify(operation));
  await button(session, '.dialog', 'Add operation');
  await session.wait(`${state}.projection.nodes.some((node) => node.id === '${id}')`, `operation ${id}`);
  await session.wait(`!document.querySelector('.dialog')`, 'operation dialog closed');
}

async function addPorts(session, id) {
  await session.evaluate(`${designer}.model.select({kind: 'nodes', ids: ['${id}']})`);
  await button(session, '.dz-inspector', 'Add input');
  await session.wait(`document.querySelector('.dialog .dz-choice')`, 'input suggestions');
  await session.evaluate(`(() => {
    const choice = [...document.querySelectorAll('.dialog .dz-choice')]
      .find((item) => item.textContent.includes('/nodes/0/options/stop'));
    if (!choice) throw Error('Missing stop input');
    choice.click();
  })()`);
  await field(session, '.dialog input[name="portName"]', 'stop');
  await field(session, '.dialog select[name="dataKind"]', 'number');
  await button(session, '.dialog', 'Add port');
  await session.wait(`${state}.projection.ports['${id}']?.inputs?.stop`, 'input port persisted');
  await button(session, '.dz-inspector', 'Add output');
  await session.wait(`document.querySelector('.dialog select[name="outputKind"]')`, 'output dialog');
  await field(session, '.dialog input[name="portName"]', 'first');
  await field(session, '.dialog select[name="outputKind"]', 'value');
  await field(session, '.dialog input[name="valuePath"]', '/rows/0/0');
  await field(session, '.dialog select[name="dataKind"]', 'number');
  await button(session, '.dialog', 'Add port');
  await session.wait(`${state}.projection.ports['${id}']?.outputs?.first`, 'output port persisted');
}

async function portPoint(session, id, side, name) {
  return session.evaluate(`(() => {
    const port = document.querySelector('.dz-port[data-node="${id}"][data-side="${side}"][data-port="${name}"]');
    const r = port.getBoundingClientRect();
    return [${side === 'outputs' ? 'r.right - 1' : 'r.left + 1'}, r.y + r.height / 2];
  })()`);
}

for (const theme of ['light', 'dark']) {
  test(`designer connects, configures, reloads and exports (${theme})`, {timeout: 120000}, async () => {
    const session = await launch({provider: 'workflow-design', theme, width: 1680, height: 1100});
    try {
      await session.wait(`window.studio?.store.get().server`, 'server state');
      await session.evaluate(`window.studio.openDocument(window.studio.store.get().server.documents[0].id)`);
      await session.wait(`window.studio.designers?.size && ${state}.projection`, 'designer loaded');
      await session.evaluate(`document.documentElement.dataset.theme = '${theme}'`);
      await addOperation(session, 'source');
      await addPorts(session, 'source');
      await addOperation(session, 'response');
      await addPorts(session, 'response');
      await session.evaluate(`${designer}.model.action('move', {
        positions: {source: {x: 70, y: 130}, response: {x: 490, y: 220}}
      })`);
      await session.evaluate(`${designer}.canvas.fit()`);
      await session.wait(`${state}.projection.layout.viewport`, 'saved viewport');
      const nodePoint = await session.evaluate(`(() => {
        const r = document.querySelector('.dz-node[data-node="source"] .dz-node-header').getBoundingClientRect();
        return [r.x + 50, r.y + 20];
      })()`);
      await session.drag(nodePoint, [nodePoint[0] + 24, nodePoint[1] + 16]);
      await session.wait(`${state}.projection.layout.nodes.source.x !== 70`, 'drag position saved');
      const savedPosition = await session.evaluate(`${state}.projection.layout.nodes.source`);
      await session.drag(await portPoint(session, 'source', 'outputs', 'first'),
        await portPoint(session, 'response', 'inputs', 'stop'));
      await session.wait(`${state}.projection.connections.length === 1`, 'pointer connection');
      await session.drag(await portPoint(session, 'response', 'outputs', 'first'),
        await portPoint(session, 'source', 'inputs', 'stop'));
      await session.wait(`${state}.projection.loops.length === 1`, 'feedback loop');
      await session.wait(`document.querySelector('.dz-loop-fields')`, 'controller inspector');
      assert.equal(await session.evaluate(`document.querySelector('.dz-header .button.primary').disabled`), true);
      if (theme === 'dark') {
        await field(session, '.dz-inspector select[name="algorithm"]', 'constant-relaxation');
        await field(session, '.dz-loop-fields input[name="relaxation"]', '0.65');
      }
      await field(session, '.dz-loop-fields input[name="maxIterations"]', '37');
      await field(session, '.dz-loop-fields input[name="absoluteTolerance"]', '0.0002');
      await button(session, '.dz-inspector', 'Save loop settings');
      await session.wait(`${state}.projection.loops[0]?.controller?.maxIterations === 37`, 'saved controller');
      const docId = await session.evaluate(`${designer}.model.documentId`);
      await session.wait(`!${state}.busy && !${designer}.canvas.isDirty()`, 'all design edits saved');
      await session.evaluate(`window.__designerOldPage = true`);
      await session.send('Page.reload', {});
      await waitForReload(session);
      await session.evaluate(`window.studio.openDocument(${JSON.stringify(docId)})`);
      await session.wait(`window.studio.designers?.size && ${state}.projection?.loops.length === 1`, 'reloaded loop');
      await session.wait(`!${state}.busy && document.querySelector('.dz-loop-marker')`, 'reloaded canvas');
      await session.evaluate(`document.documentElement.dataset.theme = '${theme}'`);
      await session.evaluate(`new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
      assert.deepEqual(await session.evaluate(`${state}.projection.layout.nodes.source`), savedPosition);
      await session.clickSelector('.dz-loop-marker');
      await session.wait(`document.querySelector('input[name="maxIterations"]')`, 'selected loop inspector');
      assert.equal(await session.evaluate(`document.querySelector('input[name="maxIterations"]').value`), '37');
      assert.equal(await session.evaluate(`document.querySelectorAll('.dz-edge.loop').length`), 2);
      if (theme === 'dark') {
        assert.equal(await session.evaluate(`document.querySelector('select[name="algorithm"]').value`),
          'constant-relaxation');
        assert.equal(await session.evaluate(`document.querySelector('input[name="relaxation"]').value`), '0.65');
      }
      if (shots) {
        await mkdir(shots, {recursive: true});
        await session.screenshot(join(shots, `studio-designer-loop-${theme}.png`));
      }
      await session.clickSelector('.dz-header button[aria-label="Undo"]');
      await session.wait(`${state}.projection.loops[0]?.status === 'unconfigured'`, 'undo settings');
      await session.clickSelector('.dz-header button[aria-label="Undo"]');
      await session.wait(`${state}.projection.loops.length === 0`, 'undo closing connection');
      await session.evaluate(`${designer}.model.select({kind: 'edge', id: ${state}.projection.connections[0].id})`);
      await button(session, '.dz-inspector', 'Remove connection');
      await session.wait(`${state}.projection.connections.length === 0`, 'disconnect');
      // Keyboard wiring is available without pointer gestures.
      await session.evaluate(`document.querySelector('.dz-port.out[data-node="source"]').focus()`);
      await session.key('Enter');
      await session.evaluate(`document.querySelector('.dz-port.in[data-node="response"]').focus()`);
      await session.key('Enter');
      await session.wait(`${state}.projection.connections.length === 1`, 'keyboard connection');
      await session.evaluate(`${designer}.model.select({kind: 'nodes', ids: ['source']})`);
      await session.wait(`document.querySelector('.dz-runtime-item')`, 'runtime inputs');
      await session.evaluate(`(() => {
        const row = [...document.querySelectorAll('.dz-runtime-item')]
          .find((item) => item.textContent.includes('/nodes/0/options/count'));
        if (!row) throw Error('Count runtime input missing');
        row.querySelector('button').click();
      })()`);
      await session.wait(`document.querySelector('.dialog input[name="parameterId"]')`, 'parameter dialog');
      await field(session, '.dialog input[name="parameterId"]', 'samples');
      await button(session, '.dialog', 'Expose');
      await session.wait(`${state}.projection.parameters.samples`, 'exposed parameter');
      await field(session, '.dz-bottom input[aria-label="Label of samples"]', 'Samples per run');
      await session.evaluate(`${designer}.model.action('move', {positions: {response: {x: 500, y: 220}}})`);
      assert.equal(await session.evaluate(`document.querySelector('input[aria-label="Label of samples"]').value`),
        'Samples per run', 'layout edits preserve table drafts');
      assert.equal(await session.evaluate(`[...window.studio.windows.instances.values()]
        .find((item) => item.type === 'designer').window.isDirty()`), true);
      await button(session, '.dz-bottom', 'Save');
      await session.wait(`${state}.projection.parameters.samples.label === 'Samples per run'`, 'parameter table saved');
      await session.clickSelector('.dz-bottom-tab[data-tab="outputs"]');
      await button(session, '.dz-bottom', 'Add output');
      await field(session, '.dz-bottom input[aria-label="Alias"]', 'result');
      await field(session, '.dz-bottom select[aria-label="Operation"]', 'response');
      await button(session, '.dz-bottom', 'Save');
      await session.wait(`${state}.projection.outputs.result`, 'named output');
      await session.clickSelector('.dz-bottom-tab[data-tab="naming"]');
      await field(session, '.dz-naming-input', '{index}-{output}-n{param:samples}{ext}');
      await button(session, '.dz-bottom', 'Save naming');
      await session.wait(`${state}.projection.naming.pattern?.includes('samples')`, 'naming pattern');
      // Editing complete source remains available for recovery, and applies as one undo step.
      await session.clickSelector('.dz-bottom-tab[data-tab="source"]');
      await session.wait(`document.querySelector('.dz-source-editor textarea')?.value.includes('workflow-design')`,
        'design source');
      // Hold a canvas-triggered source fetch while the user starts typing in the source editor.
      await session.evaluate(`(() => {
        const model = ${designer}.model;
        const record = model.record;
        window.__sourceRecordOriginal = record;
        window.__sourceRecordWaiters = [];
        model.record = async () => {
          const result = await record();
          await new Promise((resolve) => { window.__sourceRecordWaiters.push(resolve); });
          return result;
        };
      })()`);
      await session.evaluate(`${designer}.model.action('move', {positions: {response: {x: 540, y: 220}}})`);
      await session.wait('window.__sourceRecordWaiters.length > 0', 'source refresh is in flight');
      const duringRefresh = await session.evaluate(`(() => {
        const doc = JSON.parse(document.querySelector('.dz-source-editor textarea').value);
        doc.workflow.settings.samples = 99;
        return JSON.stringify(doc, null, 2);
      })()`);
      await field(session, '.dz-source-editor textarea', duringRefresh);
      await session.evaluate(`(() => {
        ${designer}.model.record = window.__sourceRecordOriginal;
        window.__sourceRecordWaiters.forEach((resolve) => resolve());
        return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      })()`);
      assert.equal(await session.evaluate(`document.querySelector('.dz-source-editor textarea').value`),
        duringRefresh, 'typing during source fetch survives the late response');
      assert.match(await session.evaluate(`document.querySelector('.dz-source-toolbar').textContent`),
        /Your source edits are kept/);
      await button(session, '.dz-source-panel', 'Discard');
      await session.wait(`JSON.parse(document.querySelector('.dz-source-editor textarea').value)
        .layout.nodes.response.x === 540`, 'discard explicitly loads the refreshed source');
      const edited = await session.evaluate(`(() => {
        const doc = JSON.parse(document.querySelector('.dz-source-editor textarea').value);
        doc.workflow.settings.samples = 7;
        return JSON.stringify(doc, null, 2);
      })()`);
      await field(session, '.dz-source-editor textarea', edited);
      await button(session, '.dz-source-panel', 'Apply source');
      await session.wait(`(${designer}.model.record()).then((r) => r.document.workflow.settings.samples === 7)`,
        'source applied');
      const persistedSamples = await session.evaluate(`(${designer}.model.record())
        .then((r) => r.document.workflow.settings.samples)`);
      assert.equal(persistedSamples, 7);
      // Attach a local sample, inspect a table, then grep named captures into another table.
      await session.clickSelector('.dz-bottom-tab[data-tab="samples"]');
      await session.wait(`document.querySelector('.dz-samples input[type="file"]')`, 'sample attachment input');
      const dom = await session.send('DOM.getDocument');
      const input = await session.send('DOM.querySelector', {nodeId: dom.root.nodeId,
        selector: '.dz-samples input[type="file"]'});
      await session.send('DOM.setFileInputFiles', {nodeId: input.nodeId,
        files: [fileURLToPath(new URL('./fixtures/designer/sample.csv', import.meta.url))]});
      await session.wait(`document.querySelector('.dz-samples .vw-table')?.dataset.state === 'ready'`, 'sample table');
      assert.match(await session.evaluate(`document.querySelector('.dz-sample-status').textContent`), /response.stop/);
      await field(session, '.dz-samples select[aria-label="Sample view"]', 'text');
      await button(session, '.dz-samples', 'Grep extract');
      await field(session, '.dz-samples input[aria-label="Row pattern"]',
        '^(?<time>[0-9]+),(?<velocity>[0-9.]+),(?<pressure>[0-9]+)$');
      await button(session, '.dz-samples', 'Extract');
      await session.wait(`document.querySelector('.dz-samples select[aria-label="Sample view"]').value === 'table'`,
        'grep extracted table');
      const sampleStatus = await session.evaluate(
        `document.querySelector('.dz-samples .vw-table .vw-status-meta').textContent`);
      assert.match(sampleStatus, /4 rows × 4 columns/);
      await session.evaluate(`document.querySelectorAll('.toast [aria-label="Dismiss"]')
        .forEach((item) => item.click())`);
      const divider = await session.evaluate(`(() => {
        const r = document.querySelector('.dz-bottom-resize').getBoundingClientRect();
        return [r.x + 100, r.y + r.height / 2];
      })()`);
      await session.drag(divider, [divider[0], divider[1] - 120]);
      if (shots) await session.screenshot(join(shots, `studio-designer-sample-${theme}.png`));
      await button(session, '.dz-header', 'Export template');
      await session.wait(`document.querySelector('.dialog input[name="directory"]')`, 'export dialog');
      const output = join(session.workspace, 'exported-study');
      await field(session, '.dialog input[name="directory"]', output);
      await field(session, '.dialog input[name="templateId"]', 'sequence.study');
      await button(session, '.dialog', 'Export');
      await session.wait(`document.querySelector('.dz-export-ok')`, 'export result');
      const manifest = JSON.parse(await readFile(join(output, 'template.json'), 'utf8'));
      const workflow = JSON.parse(await readFile(join(output, 'workflow.json'), 'utf8'));
      const example = JSON.parse(await readFile(join(output, 'cases/example.json'), 'utf8'));
      assert.equal(manifest.id, 'sequence.study');
      assert.equal(example.values.samples, 7);
      assert.equal(workflow.operations[1].document.nodes[0].options.stop.$value, 'source');
      if (shots) await session.screenshot(join(shots, `studio-designer-export-${theme}.png`));
      assert.deepEqual(session.exceptions, []);
      assert.deepEqual(session.consoleErrors.filter((text) => !text.includes('favicon')), []);
    } catch (error) {
      console.error(error);
      throw error;
    } finally {
      await session.close();
    }
  });
}
