// Copyright (C) 2026 David L F Gaden
// Full-shell guided authoring acceptance against packaged libraries and real host routes.
// No native application is invoked: validation and template export are host-only.
import assert from 'node:assert/strict';
import {mkdir, readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {test} from 'node:test';
import {launch, delay} from './harness.mjs';

const active = 'window.studio.windows.active().window';
const editor = `${active}.editor`;
const designer = '[...window.studio.designers.values()][0]';
const visible = '.window:not([hidden])';
const popover = `${visible} .sx-fill-popover:not([hidden])`;
const shots = process.env.STUDIO_SCREENSHOTS;

async function field(session, selector, value) {
  await session.wait(`document.querySelector(${JSON.stringify(selector)})`, selector);
  await session.evaluate(`(() => {
    const input = document.querySelector(${JSON.stringify(selector)});
    input.focus();
    input.value = ${JSON.stringify(value)};
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  })()`);
}

async function button(session, container, label) {
  const expression = `[...document.querySelectorAll(${JSON.stringify(container + ' button')})]
    .find(item => item.textContent.trim() === ${JSON.stringify(label)} && !item.disabled && !item.hidden)`;
  await session.wait(expression, label);
  await session.evaluate(`${expression}.click()`);
}

async function screenshot(session, name, theme) {
  if (!shots) return;
  await session.evaluate(`new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
  await mkdir(shots, {recursive: true});
  await session.screenshot(join(shots, `studio-guided-${name}-${theme}.png`));
}

async function ready(session, theme) {
  await session.wait('window.studio?.store.get().adaptors.length', 'adaptor catalogue');
  await session.evaluate(`document.documentElement.dataset.theme = '${theme}'`);
  await delay(180);
}

async function dismissNotifications(session) {
  await session.evaluate(`(() => {
    studio.notify.clearProblems();
    document.querySelectorAll('.toast [aria-label="Dismiss"]').forEach(button => button.click());
    studio.store.set({panelOpen: false});
  })()`);
}

async function visitFill(session, label) {
  for (let count = 0; count < 100; count += 1) {
    const current = await session.evaluate(`document.querySelector('${popover} .sx-fill-heading strong')?.textContent`);
    if (current === label) return;
    await session.evaluate(`document.querySelector('${popover} [aria-label="Value"]').focus()`);
    await session.key('Tab');
  }
  throw Error(`Could not reach fill field ${label}`);
}

async function markerSnapshot(session) {
  return session.evaluate(`(async () => {
    const {markers} = await import('/editor/insert-fields.mjs');
    return markers(JSON.parse(${editor}.getValue()));
  })()`);
}

for (const theme of ['light', 'dark']) {
  test(`Guided library, templates and XYZ fill through the full shell (${theme})`,
    {timeout: 120000}, async () => {
      const session = await launch({theme});
      try {
        await ready(session, theme);
        await session.evaluate(`studio.bus.emit('new-instance', {provider:'paraview'})`);
        await session.wait(`document.querySelector('.template-card[data-template="slice-sweep"]')`, 'template gallery');
        await field(session, '.dialog input[placeholder="e.g. geometry, mesher, slices"]', `guided-${theme}`);
        await session.clickSelector('.template-card[data-template="slice-sweep"]');
        assert.match(await session.evaluate(`document.querySelector('[data-template="slice-sweep"]').textContent`),
          /Fill:.*Slice positions/);
        assert.ok(await session.evaluate(`(() => {
          const gallery = document.querySelector('.template-gallery');
          const dialog = gallery.closest('.dialog');
          return gallery.scrollWidth <= gallery.clientWidth + 1 && dialog.scrollWidth <= dialog.clientWidth + 1;
        })()`), 'Template gallery should fit its dialog');
        await screenshot(session, 'template-gallery', theme);
        await button(session, '.dialog', 'Create instance');
        await session.wait(`${active}.store?.get().schema && document.querySelector('${popover}')`,
          'template enters fill mode');
        assert.equal((await markerSnapshot(session)).length, 1);
        assert.equal(await session.evaluate(`document.querySelector('${popover} .sx-fill-heading strong').textContent`),
          'Slice positions');
        await screenshot(session, 'template-fill', theme);
        await field(session, `${popover} [aria-label="Value"]`, '3');
        await session.key('Enter');
        await session.wait(`!document.querySelector('${popover}')`, 'template field accepted');
        assert.equal((await markerSnapshot(session)).length, 0);
        await session.clickSelector(`${visible} [data-action="validate"]`);
        await session.wait(`!${active}.store.get().busy && document.querySelector('.toast.ok')`, 'template host-plans');
        assert.equal(await session.evaluate('studio.notify.store.get().problems.length'), 0);
        await dismissNotifications(session);

        const before = await session.evaluate(`${editor}.getValue()`);
        await session.evaluate(`[...document.querySelectorAll('${visible} .library-section button')]
          .find(button => button.textContent.includes('X, Y and Z slice arrays')).focus()`);
        await session.wait(`(() => {
          const viewport = document.querySelector('${visible} .sx-editor').getBoundingClientRect();
          return [...document.querySelectorAll('${visible} .sx-ghost')].some(ghost => {
            const rect = ghost.getBoundingClientRect();
            return rect.bottom > viewport.top && rect.top < viewport.bottom;
          });
        })()`, 'visible section ghost');
        assert.equal(await session.evaluate(`${editor}.getValue()`), before);
        await screenshot(session, 'section-ghost', theme);
        await session.clickSelector(`${visible} .library-category[data-category="slicing"]`);
        await session.wait(`document.querySelector('.library-popover [data-library="xyz-slice-arrays"]')`,
          'slice category popover');
        await screenshot(session, 'snippet-popover', theme);
        await session.evaluate(`document.querySelector('.library-popover [data-library="xyz-slice-arrays"]').focus()`);
        await session.wait(`document.querySelector('${visible} .sx-ed-previewing .sx-ghost')`, 'multi-insert ghost');
        assert.equal(await session.evaluate(`${editor}.getValue()`), before);
        assert.match(await session.evaluate(`document.querySelector('.library-popover .library-summary').textContent`),
          /axes.*scenes|scenes.*axes/);
        await screenshot(session, 'multi-insert-ghost', theme);
        await session.key('Enter');
        await session.wait(`document.querySelector('${popover}') && !document.querySelector('.library-popover')`,
          'snippet enters fill mode');
        assert.ok(await session.evaluate(`document.querySelectorAll('${visible} .sx-fill-marker').length > 0`));
        assert.ok(await session.evaluate(`!document.querySelector('${visible}').textContent
          .includes('[object Object]')`), 'Unfinished identifiers should have readable labels');
        assert.equal(await session.evaluate(`document.querySelector('${visible} .sx-fill-badge').textContent`),
          '2 values to fill'); // ID prefix is assigned automatically; only source/count need answers.
        assert.equal(await session.evaluate(`document.querySelector('${popover} .sx-fill-heading strong').textContent`),
          'Data source');
        await screenshot(session, 'xyz-fill', theme);

        await visitFill(session, 'Data source');
        await session.evaluate(`(() => {
          const choices = document.querySelector('${popover} [aria-label="Choose a value"]');
          const option = [...choices.options].find(option => option.textContent === 'source');
          if (!option) throw Error('Existing source was not offered');
          choices.value = option.value;
          choices.dispatchEvent(new Event('change', {bubbles: true}));
        })()`);
        await session.key('Tab');
        await visitFill(session, 'Slices per axis');
        // Leave the real numeric field unfinished; identities are assigned automatically.
        await button(session, popover, 'Leave for later');
        await session.key('Escape');
        const remaining = await markerSnapshot(session);
        assert.ok(remaining.length > 0);
        assert.ok(remaining.every(item => item.marker.$fill === 'count'));
        const result = await session.evaluate(`studio.api.post('/api/validate',
          {provider:'paraview', source:${editor}.getValue()})`);
        assert.equal(result.valid, false);
        const fault = result.diagnostics.find(item => item.code === 'UNFILLED_VALUES');
        assert.ok(fault, JSON.stringify(result));
        assert.deepEqual(fault.observed.pointers, remaining.map(item => item.pointer));
        assert.equal(await session.evaluate(`document.querySelector('${visible} .sx-fill-badge').textContent`),
          '1 value to fill');
        await screenshot(session, 'values-left-for-later', theme);
        await session.clickSelector(`${visible} .sx-fill-badge`);
        await field(session, `${popover} [aria-label="Value"]`, '3');
        await session.key('Enter');
        await session.wait(`!document.querySelector('${popover}')`, 'all linked fields accepted');
        assert.equal((await markerSnapshot(session)).length, 0);
        const accepted = await session.evaluate(`studio.api.post('/api/validate',
          {provider:'paraview', source:${editor}.getValue()})`);
        assert.equal(accepted.valid, true, JSON.stringify(accepted.diagnostics));
        const value = JSON.parse(await session.evaluate(`${editor}.getValue()`));
        assert.ok(value.nodes.some(node => node.id === 'sliceX'));
        assert.equal(value.axes.find(axis => axis.name === 'sliceFraction').series.count, 3);
        await dismissNotifications(session);
        await screenshot(session, 'xyz-complete', theme);

        const documentId = await session.evaluate(`${active}.store.get().record.id`);
        await session.evaluate(`studio.windows.open('schema-editor', {document:${JSON.stringify(documentId)}})`);
        const schemaCategory = `${visible} .schema-main .library-category[data-category="slicing"]`;
        await session.wait(`document.querySelector('${schemaCategory}')`, 'Schema Editor snippet bar');
        await session.clickSelector(schemaCategory);
        await session.wait(`document.querySelector('.library-popover [data-library="xyz-slice-arrays"]')`,
          'Schema Editor category content');
        await dismissNotifications(session);
        await screenshot(session, 'schema-library', theme);
        assert.deepEqual(session.exceptions, []);
        assert.deepEqual(session.consoleErrors.filter(text => !text.includes('favicon')), []);
      } finally { await session.close(); }
    });
}

for (const theme of ['light', 'dark']) {
  test(`Designer exposes unfilled runtime values and exports a draft case (${theme})`,
    {timeout: 90000}, async () => {
      const session = await launch({theme});
      try {
        await ready(session, theme);
        const design = {version: 'schemaxis.workflow-design/2', workflow: {
          version: 'schemaxis.workflow/1', operations: [{id: 'series', document: {
            version: 'schemaxis.octave/1', nodes: [{id: 'data', filter: 'sequence', options: {
              start: 0, stop: 4, count: {$fill: 'count', type: 'integer', label: 'Sample count', minimum: 1},
            }}], outputs: ['data'],
          }}]}, ports: {}, connections: [], controllers: {}, parameters: {}, outputs: {}, naming: {}, layout: {}};
        await session.evaluate(`(async () => {
          const record = await studio.api.post('/api/documents', {action:'new', provider:'workflow-design',
            name:'Exposed study', source:${JSON.stringify(JSON.stringify(design))}});
          await studio.refresh();
          studio.windows.open('designer', {document:record.id});
        })()`);
        await session.wait(`${designer}.model?.store.get().projection?.status === 'unfilled'`, 'unfinished design');
        await button(session, `${visible} .dz-header`, 'Expose unfilled values as parameters');
        await session.wait(`${designer}.model.store.get().projection.templateExportAvailable`, 'export enabled');
        assert.equal(await session.evaluate(`${designer}.model.store.get().projection.compilationAvailable`), false);
        assert.ok(await session.evaluate(`[...document.querySelectorAll('${visible} .dz-inspector button')]
          .some(button => button.textContent.includes('Export template') && !button.disabled)`));
        await dismissNotifications(session);
        await screenshot(session, 'designer-exposed', theme);
        await button(session, `${visible} .dz-header`, 'Export template');
        const destination = join(session.workspace, `guided-export-${theme}`);
        await field(session, '.dialog input[name="directory"]', destination);
        await field(session, '.dialog input[name="templateId"]', 'guided-study');
        await button(session, '.dialog', 'Export');
        await session.wait(`document.querySelector('.dz-export-ok')?.textContent.includes('fill the example case')`,
          'unfilled example case exported');
        const manifest = JSON.parse(await readFile(join(destination, 'template.json'), 'utf8'));
        const values = JSON.parse(await readFile(join(destination, 'cases/example.json'), 'utf8'));
        assert.equal(manifest.parameters['series-count'].kind, 'integer');
        assert.equal(values.values['series-count'].$fill, 'count');
        await screenshot(session, 'designer-export', theme);
        assert.deepEqual(session.exceptions, []);
      } finally { await session.close(); }
    });
}
