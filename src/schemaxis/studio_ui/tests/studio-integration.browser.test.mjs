// Shipped starter through Designer → nested Workbench → export → Case Runner.
// STUDIO_RUN_NATIVE=1 additionally executes the resulting case in configured GNU Octave.
import assert from 'node:assert/strict';
import {mkdir, readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {test} from 'node:test';
import {delay, launch} from './harness.mjs';

const example = fileURLToPath(new URL('../../../../examples/studio/sequence-study', import.meta.url));
const shots = process.env.STUDIO_SCREENSHOTS;
const active = 'window.studio.windows.active().window';
const title = 'Sample and scale integration';

async function field(session, selector, value) {
  await session.wait(`document.querySelector(${JSON.stringify(selector)})`, `field ${selector}`);
  await session.evaluate(`(() => {
    const input = document.querySelector(${JSON.stringify(selector)});
    if (input.disabled) throw Error('Field is disabled: ' + ${JSON.stringify(selector)});
    input.value = ${JSON.stringify(value)};
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  })()`);
}

async function button(session, container, label) {
  const query = `[...document.querySelectorAll(${JSON.stringify(`${container} button`)})]
    .find((item) => item.textContent.trim() === ${JSON.stringify(label)} && !item.disabled)`;
  await session.wait(query, `enabled ${label} button`);
  await session.evaluate(`${query}.click()`);
}

async function selectDesignTab(session) {
  const query = `[...document.querySelectorAll('.tab')]
    .find((item) => item.querySelector('.label')?.textContent === ${JSON.stringify(title)})`;
  await session.wait(query, 'design tab');
  await session.evaluate(`${query}.click()`);
  await session.wait(`window.studio.windows.active()?.type === 'designer'`, 'Designer active');
}

async function reload(session) {
  await session.evaluate('window.__integrationOldPage = true');
  await session.send('Page.reload');
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    try {
      if (await session.evaluate('!window.__integrationOldPage && window.studio?.store.get().server')) return;
    } catch (error) {
      if (!/navigated or closed|Execution context was destroyed|Cannot find context/.test(error.message)) throw error;
    }
    await delay(80);
  }
  throw Error('Studio did not reconnect after reload');
}

async function screenshot(session, name) {
  if (!shots) return;
  await mkdir(shots, {recursive: true});
  await session.evaluate(`document.querySelectorAll('.toast [aria-label="Dismiss"]').forEach((item) => item.click());
    window.studio.store.set({panelOpen: false});`);
  await session.screenshot(join(shots, name));
}

test('Studio starter connects Designer, Workbench, template export and Case Runner',
  {timeout: 120000}, async () => {
    const session = await launch();
    try {
      const design = JSON.parse(await readFile(join(example, 'design.json'), 'utf8'));
      const original = JSON.parse(await readFile(join(example, 'template.json'), 'utf8'));
      await session.wait('window.studio?.store.get().adaptors.length', 'Studio catalogue');
      // Only initial document setup uses the API. All authoring/run transitions below use UI controls.
      const documentId = await session.evaluate(`(async () => {
        const record = await window.studio.api.post('/api/documents', {action: 'new', provider: 'workflow-design',
          name: ${JSON.stringify(title)}, document: ${JSON.stringify(design)}});
        await window.studio.refresh();
        return record.id;
      })()`);
      await session.wait(`[...document.querySelectorAll('.start .list-item')]
        .some((item) => item.querySelector('.title')?.textContent === ${JSON.stringify(title)})`, 'recent design');
      await session.evaluate(`[...document.querySelectorAll('.start .list-item')]
        .find((item) => item.querySelector('.title')?.textContent === ${JSON.stringify(title)}).click()`);
      await session.wait(`document.querySelector('.dz-node[data-node="samples"]')`, 'shipped design canvas');
      assert.equal(await session.evaluate(`document.querySelectorAll('.dz-edge').length`), 1);
      await session.clickSelector('.dz-node[data-node="samples"] .dz-node-header');
      await button(session, '.dz-inspector', 'Open in Workbench');
      await session.wait(`${active}.store?.get().schema && document.querySelector('.wb-outline-item')`,
        'nested Workbench');
      assert.equal(await session.evaluate(`${active}.store.get().provider`), 'octave');
      await session.clickSelector('.wb-outline-item[data-pointer="/nodes/0"]');
      await field(session, '.wb-property [aria-label="/nodes/0/options/start"]', '1');
      await session.wait(`JSON.parse(${active}.editor.getValue()).nodes[0].options.start === 1`, 'nested input edited');
      await button(session, '.wb-workbench .actions', 'Save');
      await session.wait(`!${active}.store.get().busy && !${active}.isDirty()
        && ${active}.store.get().record.document.workflow.operations[0].document.nodes[0].options.start === 1`,
      'nested operation saved to its parent');
      await selectDesignTab(session);
      await reload(session);
      await selectDesignTab(session);
      await session.wait(`document.querySelector('.dz-bottom-tab[data-tab="source"]')`, 'restored Designer');
      await session.clickSelector('.dz-bottom-tab[data-tab="source"]');
      await session.wait(`(() => {
        try { return JSON.parse(document.querySelector('.dz-source-editor textarea')?.value)
          .workflow.operations[0].document.nodes[0].options.start === 1; }
        catch { return false; }
      })()`, 'Designer reload contains the nested edit');
      assert.equal(await session.evaluate(`window.studio.windows.active().params.document`), documentId);
      await screenshot(session, 'studio-integration-designer.png');

      await button(session, '.dz-header', 'Export template');
      const output = join(session.workspace, 'integration-export');
      await field(session, '.dialog input[name="directory"]', output);
      await field(session, '.dialog input[name="templateId"]', 'studio.integration');
      await button(session, '.dialog', 'Export');
      await session.wait(`document.querySelector('.dz-export-ok')`, 'template exported');
      const manifest = JSON.parse(await readFile(join(output, 'template.json'), 'utf8'));
      const workflow = JSON.parse(await readFile(join(output, 'workflow.json'), 'utf8'));
      const exportedCase = JSON.parse(await readFile(join(output, 'cases/example.json'), 'utf8'));
      assert.equal(manifest.id, 'studio.integration');
      assert.deepEqual(manifest.parameters, original.parameters);
      assert.deepEqual(manifest.outputs, original.outputs);
      assert.equal(workflow.operations[0].document.nodes[0].options.start, 1);
      assert.equal(workflow.operations[1].document.nodes[0].options.file.$artifact, 'samples');
      assert.deepEqual(exportedCase.run.naming, design.naming);
      await button(session, '.dialog', 'Close');
      await session.clickSelector('.rail-button[aria-label="Case Runner"]');
      await field(session, '.runner-template-bar input', output);
      await button(session, '.runner-template-bar', 'Inspect template');
      await session.wait(`document.querySelectorAll('[data-parameter]').length === 3`, 'exported parameter form');
      await field(session, '.runner-case-file input', join(output, 'cases/example.json'));
      await button(session, '.runner-case-actions', 'Load case');
      await session.wait(`window.studio.notify.store.get().log.some((entry) => entry.title === 'Case loaded')`,
        'exported case bound');
      await session.wait(`!document.querySelector('[data-parameter="stop"]').disabled`, 'case form enabled');
      await field(session, '[data-parameter="stop"]', '6');
      await field(session, '[data-parameter="count"]', '6');
      await field(session, '[data-parameter="factor"]', '3');
      await field(session, '.runner-case-file input', 'cases/integration.json');
      await button(session, '.runner-case-actions', 'Save case');
      await session.wait(`window.studio.notify.store.get().log.some((entry) => entry.title === 'Case saved')`,
        'edited case saved');
      const savedCase = JSON.parse(await readFile(join(session.workspace, 'cases/integration.json'), 'utf8'));
      assert.deepEqual(savedCase.template, exportedCase.template);
      assert.deepEqual(savedCase.values, {count: 6, factor: 3, stop: 6});
      await button(session, '.runner .actions', 'Plan');
      await session.wait(`document.querySelector('.runner-flow .badge').textContent === 'Plan ready'`, 'case planned');
      const plan = JSON.parse(await session.evaluate(`document.querySelector('.runner-plan-details pre').textContent`));
      const plannedSequence = plan.operations[0].provisionalPlan.nodes[0].options;
      assert.deepEqual([plannedSequence.start, plannedSequence.stop, plannedSequence.count], [1, 6, 6]);
      assert.equal(plan.operations[1].provisionalPlan.status, 'deferred');
      await screenshot(session, 'studio-integration-planned.png');

      if (process.env.STUDIO_RUN_NATIVE === '1') {
        await button(session, '.runner .actions', 'Run');
        await session.wait(`document.querySelector('.runner .window-header > .badge')?.textContent === 'Verified'
          || document.querySelector('.runner-fault')`, 'native case completion', 80000);
        assert.equal(await session.evaluate(`document.querySelector('.runner-fault')?.textContent || ''`), '');
        await session.wait(`document.querySelector('.runner-viewer .vw-table')?.dataset.state === 'ready'`,
          'first verified table rendered');
        const snapshot = await session.evaluate(`(async () => {
          const state = await window.studio.api.get('/api/state');
          const job = state.jobs.find((item) => item.label === 'Case: studio.integration');
          return window.studio.api.get('/api/jobs/' + job.id);
        })()`);
        assert.equal(snapshot.verified, true);
        assert.deepEqual(snapshot.result.outputs.map((item) => item.name), [
          '0001-samples-samples-gain_3.csv', '0002-samples-sampleStatistics-gain_3.json',
          '0003-scaled-scaled-gain_3.csv', '0004-scaled-scaledStatistics-gain_3.json']);
        const scaled = snapshot.result.outputs.find((item) => item.output === 'scaled');
        await button(session, '.runner-output-list', scaled.name);
        await session.wait(`document.querySelector('.runner-output-heading strong').textContent
          === ${JSON.stringify(scaled.name)}
          && document.querySelector('.runner-viewer .vw-table')?.dataset.state === 'ready'`,
        'scaled verified table rendered');
        const rows = (await readFile(scaled.path, 'utf8')).trim().split(/\r?\n/).slice(1)
          .map((line) => line.split(',').map(Number));
        assert.equal(rows.length, 6);
        assert.deepEqual(rows[0], [1, 3]);
        assert.deepEqual(rows.at(-1), [6, 18]);
        assert.match(await session.evaluate(`document.querySelector('.runner-viewer .vw-status-meta').textContent`),
          /6 rows × 2 columns/);
        assert.deepEqual(JSON.parse(await readFile(join(snapshot.directory, 'case.json'), 'utf8')), savedCase);
        for (const theme of ['light', 'dark']) {
          await session.evaluate(`document.documentElement.dataset.theme = '${theme}';
            document.querySelector('.runner-results').scrollTop = 150;`);
          await delay(180);
          await screenshot(session, `studio-integration-verified-${theme}.png`);
        }
      }
      assert.deepEqual(await session.evaluate('window.studio.notify.store.get().problems'), []);
      assert.deepEqual(session.exceptions, []);
      assert.deepEqual(session.consoleErrors.filter((message) => !message.includes('favicon')), []);
    } finally {
      await session.close();
    }
  });
