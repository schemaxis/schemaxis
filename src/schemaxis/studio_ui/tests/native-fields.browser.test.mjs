// Real Workbench observation wiring with a mocked geometry response; no native process runs.
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {join} from 'node:path';
import {test} from 'node:test';
import {launch} from './harness.mjs';

const active = 'window.studio.windows.active().window';
const fill = '.sx-fill-popover:not([hidden])';
const shots = process.env.STUDIO_SCREENSHOTS;

async function screenshot(session, name, theme) {
  if (!shots) return;
  await mkdir(shots, {recursive: true});
  await session.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
  await session.screenshot(join(shots, `studio-native-fields-${name}-${theme}.png`));
}

for (const theme of ['light', 'dark']) {
  test(`Workbench geometry observations supply scientific field choices (${theme})`, {timeout: 60000}, async () => {
    const session = await launch({theme, provider: 'paraview'});
    try {
      await session.wait('window.studio?.store.get().adaptors.length', 'adaptor catalogue');
      await session.evaluate(`document.documentElement.dataset.theme = '${theme}'`);
      await session.evaluate(`(async () => {
        const record = await studio.api.post('/api/documents', {action: 'new', provider: 'paraview',
          name: 'Observed scientific fields', document: {
            version: 'schemaxis/1', nodes: [{id: 'source', filter: 'wavelet'}],
            scenes: [{id: 'overview', geometry: ['source'], visible: {source: {}}, images: []}],
          }});
        await studio.refresh();
        studio.windows.open('workbench', {document: record.id});
      })()`);
      await session.wait(`${active}.store?.get().schema`, 'ParaView Workbench loaded');
      assert.deepEqual(await session.evaluate(`${active}.editor.getOption('fillObservations') || []`), []);
      await session.evaluate(`(() => {
        const get = studio.api.get.bind(studio.api);
        window.geometryRequests = [];
        studio.api.get = (route, params) => {
          if (route !== '/api/geometry') return get(route, params);
          geometryRequests.push(structuredClone(params));
          return Promise.resolve({document: params.document, revision: params.revision,
            objects: [{id: 'source', label: 'Observed source', faces: [{id: 'Face1',
              vertices: [[0, 0, 0], [1, 0, 0], [0, 1, 0]], triangles: [[0, 1, 2]]}]}],
            observations: {source: {pointCount: 3, bounds: [0, 1, 0, 1, 0, 0], fields: {
              POINTS: {pressure: {components: 1, range: [0, 1]}},
              CELLS: {velocity: {components: 3}},
            }}}});
        };
        ${active}.store.set({native: 'live'});
      })()`);
      await session.clickSelector('[data-tab="3d"]');
      const load = '[data-viewer-panel="3d"] .wb-viewer-tools button:nth-child(2)';
      await session.wait(`!document.querySelector('${load}').disabled`, 'native preview action enabled');
      await session.clickSelector(load);
      await session.wait(`document.querySelector('[data-viewer-panel="3d"] .vw').dataset.state === 'ready'
        && ${active}.editor.getOption('fillObservations')?.length === 2`, 'observation callback completed');
      assert.deepEqual(await session.evaluate(`${active}.editor.getOption('fillObservations')`),
        ['pressure', 'velocity']);
      assert.deepEqual(await session.evaluate('geometryRequests'), [await session.evaluate(`(() => {
        const {id, revision} = ${active}.store.get().record;
        return {document: id, revision};
      })()`)]);
      await screenshot(session, 'geometry', theme);

      await session.clickSelector('[data-tab="input"]');
      await session.evaluate(`(() => {
        const editor = ${active}.editor;
        const value = JSON.parse(editor.getValue());
        value.nodes.push({id: 'isosurface', filter: 'contour', inputs: {input: 'source'}, options: {
          field: ['POINTS', {$fill: 'array', type: 'field', label: 'Scientific array', required: true}],
          values: [0.5],
        }});
        editor.setValue(JSON.stringify(value, null, 2), {preserveUndo: true});
        editor.startFill();
      })()`);
      const choices = `${fill} [aria-label="Choose a value"]`;
      await session.wait(`document.querySelector('${choices}')`, 'scientific field picker');
      assert.deepEqual(await session.evaluate(`[...document.querySelector('${choices}').options]
        .slice(1).map(option => option.textContent)`), ['pressure', 'velocity']);
      await session.evaluate(`(() => {
        const select = document.querySelector('${choices}');
        select.value = [...select.options].find(option => option.textContent === 'pressure').value;
        select.dispatchEvent(new Event('change', {bubbles: true}));
      })()`);
      await screenshot(session, 'picker', theme);
      await session.key('Enter');
      await session.wait(`!document.querySelector('${fill}')`, 'observed field accepted');
      assert.equal(await session.evaluate(`JSON.parse(${active}.editor.getValue()).nodes[1].options.field[1]`),
        'pressure');
      assert.equal(await session.evaluate('studio.notify.store.get().problems.length'), 0);
      assert.deepEqual(session.exceptions, []);
      assert.deepEqual(session.consoleErrors.filter(text => !text.includes('favicon')), []);
    } finally {
      await session.close();
    }
  });
}
