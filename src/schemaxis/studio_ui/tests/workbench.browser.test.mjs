// Real-server coverage for authoring, snippets, samples, reference chips and parent design edits.
import assert from 'node:assert/strict';
import {mkdir, readFile, readdir, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {test} from 'node:test';
import {launch} from './harness.mjs';

const shots = process.env.STUDIO_SCREENSHOTS;
const active = 'window.studio.windows.active().window';

async function start(session, theme) {
  await session.wait('window.studio?.store.get().adaptors.length', 'adaptor catalogue');
  await session.evaluate(`document.documentElement.dataset.theme = '${theme}'`);
  await session.evaluate(`new Promise((resolve) => setTimeout(resolve, 180))`);
  await session.evaluate(`(async () => {
    const ctx = window.studio;
    const library = await ctx.api.get('/api/studio/adaptor', {id: 'freecad'});
    const record = await ctx.api.post('/api/documents', {action: 'new', provider: 'freecad',
      name: 'Parametric enclosure', document: library.templates[0].document});
    await ctx.refresh();
    ctx.windows.open('workbench', {document: record.id});
  })()`);
  await session.wait(`${active}.store?.get().schema && document.querySelector('.wb-library-card')`, 'workbench loaded');
}

for (const theme of ['light', 'dark']) {
  test(`Workbench edits, previews snippets, saves and picks samples (${theme})`, {timeout: 90000}, async () => {
    const session = await launch({theme});
    try {
      await start(session, theme);
      await session.clickSelector('.wb-outline-item[data-pointer="/nodes/0"]');
      assert.equal(await session.evaluate(`document.querySelector('[aria-label="/nodes/0/options/length"]').value`),
        '30');
      await session.evaluate(`(() => {
        const input = document.querySelector('[aria-label="/nodes/0/options/length"]');
        input.value = '42';
        input.dispatchEvent(new Event('change', {bubbles: true}));
      })()`);
      await session.wait(`JSON.parse(${active}.editor.getValue()).nodes[0].options.length === 42`, 'property changed');
      await session.evaluate(`document.querySelector('[data-library="add-box"]')
        .dispatchEvent(new MouseEvent('mouseenter'))`);
      await session.wait(`document.querySelector('.sx-ed-previewing')`, 'ghost shown');
      assert.equal(await session.evaluate(`JSON.parse(${active}.editor.getValue()).nodes.length`), 1);
      if (shots) {
        await mkdir(shots, {recursive: true});
        await session.screenshot(join(shots, `studio-workbench-ghost-${theme}.png`));
      }
      await session.evaluate(`document.querySelector('[data-library="add-box"]').scrollIntoView({block: 'center'})`);
      await session.evaluate(`new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
      await session.clickSelector('[data-library="add-box"]');
      await session.wait(`document.querySelector('.sx-fill-popover:not([hidden])')`, 'snippet fill mode');
      for (let remaining = 0; remaining < 12; remaining += 1) {
        if (!await session.evaluate(`${active}.editor.getValue().includes('"$fill"')`)) break;
        await session.wait(`document.querySelector('.sx-fill-popover:not([hidden]) .button.primary:not(:disabled)')`,
          'suggested field value ready');
        await session.clickSelector('.sx-fill-popover .button.primary');
        await session.evaluate(`new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
      }
      assert.equal(await session.evaluate(`${active}.editor.getValue().includes('"$fill"')`), false);
      await session.wait(`JSON.parse(${active}.editor.getValue()).nodes.length === 2`, 'snippet inserted');
      await session.clickSelector('[data-action="validate"]');
      await session.wait(`document.querySelector('.toast.ok')?.textContent.includes('validated')`, 'host validation');
      await session.clickSelector('[data-action="save"]');
      await session.wait(`document.querySelector('[aria-label="Source file path"]')`, 'save dialog');
      await session.clickSelector('.dialog .button.primary');
      await session.wait(`${active}.store.get().record.file && !${active}.store.get().busy`, 'saved to disk');
      assert.equal(await session.evaluate(`${active}.store.get().dirty`), false);
      await session.clickSelector('[data-tab="schema"]');
      await session.wait(`document.querySelector('.wb-schema-row') && !document.querySelector('.wb-schema').hidden`,
        'schema visible');
      assert.match(await session.evaluate(`document.querySelector('.wb-schema').textContent`), /length/);
      await session.clickSelector('[data-tab="text"]');
      const sample = fileURLToPath(new URL('./fixtures/viewers/sample.csv', import.meta.url));
      const dom = await session.send('DOM.getDocument');
      const input = await session.send('DOM.querySelector', {nodeId: dom.root.nodeId,
        selector: '[data-viewer-panel="text"] input[type="file"]'});
      await session.send('DOM.setFileInputFiles', {nodeId: input.nodeId, files: [sample]});
      await session.wait(`document.querySelector('.vw-text-row')`, 'sample text loaded');
      // A gutter pick creates a file reference; Delete removes it in one keystroke.
      await session.clickSelector('.vw-text-gutter');
      await session.wait(`document.querySelector('.wb-chips .vw-chip')`, 'reference chip created');
      assert.equal(await session.evaluate(`${active}.store.get().references[0].name`), 'sample.csv');
      await session.evaluate(`document.querySelector('.wb-chips .vw-chip').focus()`);
      await session.key('Delete');
      await session.wait(`!document.querySelector('.wb-chips .vw-chip')`, 'reference chip deleted');
      await session.clickSelector('.vw-text-gutter');
      assert.equal(await session.evaluate(`getComputedStyle(document.querySelector('.wb-editor-host')).display`),
        'none');
      await session.clickSelector('[data-tab="input"]');
      await session.clickSelector('.wb-outline-item[data-pointer="/nodes/0"]');
      await session.evaluate(`document.querySelectorAll('.toast [aria-label="Dismiss"]').forEach((b) => b.click())`);
      assert.equal(await session.evaluate(`getComputedStyle(document.querySelector('[data-viewer-panel="text"]'))
        .display`), 'none');
      if (shots) {
        await session.screenshot(join(shots, `studio-workbench-${theme}.png`));
      }
      assert.deepEqual(session.exceptions, []);
      assert.deepEqual(session.consoleErrors.filter((text) => !text.includes('favicon')), []);
    } finally {
      await session.close();
    }
  });
}

test('Workbench saves a nested operation to its parent design', {timeout: 90000}, async () => {
  const session = await launch();
  try {
    await session.wait('window.studio?.store.get().adaptors.length', 'adaptor catalogue');
    await session.evaluate(`(async () => {
      const ctx = window.studio;
      const library = await ctx.api.get('/api/studio/adaptor', {id: 'freecad'});
      const record = await ctx.api.post('/api/documents', {action: 'new', provider: 'workflow-design',
        name: 'Enclosure workflow', document: {version: 'schemaxis.workflow-design/2',
          workflow: {version: 'schemaxis.workflow/1',
            operations: [{id: 'cad', document: library.templates[0].document}]},
          ports: {}, connections: [], controllers: {}, parameters: {}, outputs: {}, naming: {}, layout: {}}});
      await ctx.refresh();
      ctx.windows.open('workbench', {document: record.id, operation: 'cad'});
    })()`);
    await session.wait(`${active}.store?.get().schema`, 'nested workbench loaded');
    await session.evaluate(`(() => {
      const editor = ${active}.editor;
      const value = JSON.parse(editor.getValue());
      value.nodes[0].options.length = 55;
      editor.setValue(JSON.stringify(value, null, 2), {preserveUndo: true});
    })()`);
    await session.clickSelector('[data-action="save"]');
    await session.wait(`${active}.store.get().record.document.workflow.operations[0].document
      .nodes[0].options.length === 55`,
      'parent document saved');
    assert.equal(await session.evaluate(`${active}.store.get().provider`), 'freecad');
    assert.deepEqual(session.exceptions, []);
  } finally {
    await session.close();
  }
});

test('Workbench native Preview renders live FreeCAD topology',
  {timeout: 90000, skip: process.env.STUDIO_NATIVE !== '1'}, async () => {
    const session = await launch();
    try {
      await start(session, 'light');
      await session.clickSelector('[data-action="preview"]');
      await session.wait(`(${active}.store.get().tab === '3d' && !${active}.store.get().busy)
        || window.studio.notify.store.get().problems.length`, 'native 3D preview', 60000);
      const problems = await session.evaluate(`window.studio.notify.store.get().problems`);
      if (problems.length) {
        const paths = await readdir(session.workspace, {recursive: true});
        for (const path of paths.filter((name) => name.endsWith('.log'))) {
          console.error(path, (await readFile(join(session.workspace, path), 'utf8')).slice(-3000));
        }
      }
      assert.deepEqual(problems, []);
      assert.equal(await session.evaluate(`window.studio.notify.store.get().problems.length`), 0);
      await session.clickSelector('.vw-canvas');
      await session.key(']');
      await session.key('Enter');
      await session.wait(`document.querySelector('.wb-chips .vw-chip')`, 'native topology pick');
      const pick = await session.evaluate(`${active}.store.get().references[0]`);
      assert.ok(['face', 'edge', 'vertex'].includes(pick.type));
      assert.ok(pick.object);
      assert.ok(pick.subelement);
      await session.evaluate(`document.querySelectorAll('.toast [aria-label="Dismiss"]').forEach((b) => b.click())`);
      await session.evaluate(`window.studio.store.set({panelOpen: false})`);
      for (const theme of ['light', 'dark']) {
        await session.evaluate(`document.documentElement.dataset.theme = '${theme}'`);
        await session.evaluate(`new Promise((resolve) => setTimeout(resolve, 180))`);
        if (shots) {
          await mkdir(shots, {recursive: true});
          await session.screenshot(join(shots, `studio-workbench-native-${theme}.png`));
        }
      }
      await session.clickSelector('[data-tab="image"]');
      await session.clickSelector('[data-viewer-panel="image"] .wb-viewer-tools button:nth-child(2)');
      await session.wait(`document.querySelector('.vw-image').dataset.state === 'ready'`, 'native image ready');
      await session.clickSelector('.vw-image-canvas');
      await session.wait(`${active}.store.get().references.some((item) => item.type === 'pixel')`, 'native pixel pick');
      assert.equal(await session.evaluate(`window.studio.notify.store.get().problems.length`), 0);
      assert.deepEqual(session.exceptions, []);
    } finally {
      await session.close();
    }
  });

async function loadSample(session, kind, filename) {
  await session.clickSelector(`[data-tab="${kind}"]`);
  const dom = await session.send('DOM.getDocument');
  const input = await session.send('DOM.querySelector', {nodeId: dom.root.nodeId,
    selector: `[data-viewer-panel="${kind}"] input[type="file"]`});
  const path = fileURLToPath(new URL(`./fixtures/viewers/${filename}`, import.meta.url));
  await session.send('DOM.setFileInputFiles', {nodeId: input.nodeId, files: [path]});
  await session.wait(`document.querySelector('[data-viewer-panel="${kind}"] .vw').dataset.state === 'ready'`,
    `${kind} sample ready`);
}

test('Workbench loads image, table and 3D samples with typed reference chips', {timeout: 90000}, async () => {
  const session = await launch();
  try {
    await start(session, 'light');
    for (const [kind, file, canvas, type] of [
      ['table', 'sample.csv', '[role="gridcell"]', 'cell'],
      ['image', 'sample.png', '.vw-image-canvas', 'pixel'],
      ['3d', 'mesh.json', '.vw-canvas', 'face'],
    ]) {
      await loadSample(session, kind, file);
      await session.wait(`document.querySelector('${canvas}')`, `${kind} viewer drawn`);
      await session.clickSelector(canvas);
      if (kind === '3d') {
        await session.key(']');
        await session.key('Enter');
      }
      await session.wait(`${active}.store.get().references.some((item) => item.type === '${type}')`, `${type} pick`);
      if (shots) {
        for (const theme of ['light', 'dark']) {
          await session.evaluate(`document.documentElement.dataset.theme = '${theme}'`);
        await session.evaluate(`new Promise((resolve) => setTimeout(resolve, 180))`);
          await mkdir(shots, {recursive: true});
          await session.screenshot(join(shots, `studio-workbench-${kind}-${theme}.png`));
        }
      }
    }
    assert.equal(await session.evaluate(`window.studio.notify.store.get().problems.length`), 0);
    assert.deepEqual(session.exceptions, []);
  } finally {
    await session.close();
  }
});

test('Workbench retains unsaved text when another window changes the same revision', {timeout: 90000}, async () => {
  const session = await launch();
  try {
    await start(session, 'light');
    await session.evaluate(`(async () => {
      const workbench = ${active};
      const record = workbench.store.get().record;
      const local = JSON.parse(workbench.editor.getValue());
      local.nodes[0].options.length = 99;
      workbench.editor.setValue(JSON.stringify(local, null, 2), {preserveUndo: true});
      const remote = structuredClone(record.document);
      remote.nodes[0].options.length = 77;
      await globalThis.studio.api.post('/api/authoring', {action: 'source', document: record.id,
        revision: record.revision, source: JSON.stringify(remote, null, 2)});
      await globalThis.studio.refresh();
    })()`);
    await session.wait(`!document.querySelector('.wb-conflict').hidden`, 'remote revision warning');
    assert.equal(await session.evaluate(`JSON.parse(${active}.editor.getValue()).nodes[0].options.length`), 99);
    await session.clickSelector('[data-action="save"]');
    await session.wait(`window.studio.notify.store.get().problems.some((item) => item.code === 'STALE_REVISION')`,
      'stale save rejected');
    assert.equal(await session.evaluate(`JSON.parse(${active}.editor.getValue()).nodes[0].options.length`), 99);
    assert.deepEqual(session.exceptions, []);
  } finally {
    await session.close();
  }
});

test('Workbench output references retain their revision and reject modified artifact bytes',
  {timeout: 90000}, async () => {
    const session = await launch();
    try {
      await start(session, 'light');
      const bytes = 'First verified line\nSecond verified line\n';
      const artifact = {file: join(session.workspace, 'verified.txt'),
        sha256: createHash('sha256').update(bytes).digest('hex')};
      await writeFile(artifact.file, bytes);
      const original = await session.evaluate(`${active}.store.get().record`);
      await session.evaluate(`(async () => {
        const {createViewers} = await import('/windows/workbench/viewers.mjs');
        window.reviewViewers = createViewers({ctx: window.studio, store: ${active}.store, onTab: (kind) => {
          document.querySelector('.wb-editor-tools').hidden = true;
          document.querySelectorAll('.wb-tabs button').forEach((button) =>
            button.setAttribute('aria-selected', String(button.dataset.tab === kind)));
        }});
        const item = reviewViewers.get('text');
        document.querySelector('.wb-panels').replaceChildren(item.panel);
        item.panel.hidden = false;
        document.querySelector('.wb-references').replaceWith(reviewViewers.references);
        document.querySelector('.wb-artifacts').replaceWith(reviewViewers.artifacts);
        await reviewViewers.showArtifacts(${JSON.stringify([artifact])});
      })()`);
      await session.wait(`document.querySelector('.vw-text-gutter')`, 'verified output rendered');
      await session.clickSelector('.vw-text-gutter');
      assert.equal(await session.evaluate(`${active}.store.get().references[0].revision`), original.revision);
      assert.equal(await session.evaluate(`${active}.store.get().references[0].digest`), artifact.sha256);
      await session.evaluate(`(async () => {
        const record = ${active}.store.get().record;
        const value = structuredClone(record.document);
        value.nodes[0].options.length += 1;
        await window.studio.api.post('/api/authoring', {action:'source', document:record.id,
          revision:record.revision, source:JSON.stringify(value, null, 2)});
        await window.studio.refresh();
      })()`);
      await session.wait(`document.querySelector('.wb-chips .wb-stale')`, 'old reference marked stale');
      await session.clickSelector('.vw-text-row:nth-child(2) .vw-text-gutter');
      assert.equal(await session.evaluate(`${active}.store.get().references.at(-1).revision`), original.revision);
      assert.ok(await session.evaluate(`${active}.store.get().record.revision > ${original.revision}`));
      if (shots) {
        for (const theme of ['light', 'dark']) {
          await session.evaluate(`document.documentElement.dataset.theme = '${theme}'`);
          await session.screenshot(join(shots, `studio-workbench-stale-${theme}.png`));
        }
      }
      await writeFile(artifact.file, 'Modified after verification\n');
      await session.evaluate(`document.querySelector('.wb-artifact button').scrollIntoView({block: 'center'})`);
      await session.evaluate(`new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
      await session.clickSelector('.wb-artifact button');
      await session.wait(`window.studio.notify.store.get().problems.some((item) =>
        item.code === 'VERIFICATION_FAILED')`, 'changed output rejected');
      assert.equal(await session.evaluate(`document.querySelector('.vw-text').textContent
        .includes('Modified after verification')`), false);
      await session.evaluate('reviewViewers.destroy()');
      assert.deepEqual(session.exceptions, []);
    } finally {
      await session.close();
    }
  });
