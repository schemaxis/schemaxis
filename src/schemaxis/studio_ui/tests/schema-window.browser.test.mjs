// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {join} from 'node:path';
import {launch} from './harness.mjs';

const source = JSON.stringify({version: 'schemaxis.freecad/1', nodes: [
  {id: 'block', filter: 'box', options: {length: 10, width: 20, height: 30}},
], output: 'block'}, null, 2);
const editorSelector = '.schema-editor .sx-ed-input';

async function button(session, text) {
  await session.evaluate(`(() => {
    const button = [...document.querySelectorAll('.schema-editor button')]
      .find((item) => item.textContent.trim() === ${JSON.stringify(text)});
    if (!button) throw Error('Missing button: ' + ${JSON.stringify(text)});
    button.click();
  })()`);
}

async function edit(session, text) {
  await session.evaluate(`(() => {
    const input = document.querySelector(${JSON.stringify(editorSelector)});
    input.value = ${JSON.stringify(text)};
    input.dispatchEvent(new Event('input', {bubbles: true}));
  })()`);
}

async function openEditor(session, params = {}) {
  await session.wait('window.studio?.store.get().adaptors.length > 0', 'Studio ready');
  await session.evaluate(`window.studio.windows.open('schema-editor', ${JSON.stringify(params)})`);
  await session.wait(`document.querySelector('${editorSelector}')`, 'Schema Editor');
}

// Hold one real API response after the server has answered. The editor remains
// busy until release(), while every attempted document action is observable.
async function holdResponse(session, {method, path, action}) {
  await session.evaluate(`(() => {
    const api = window.studio.api;
    window.__schemaAudit?.restore();
    const originals = {get: api.get, post: api.post, click: HTMLInputElement.prototype.click};
    window.__schemaAudit = {requests: [], picked: [], release: null};
    window.__schemaAudit.restore = () => {
      api.get = originals.get;
      api.post = originals.post;
      HTMLInputElement.prototype.click = originals.click;
    };
    let held = false;
    for (const method of ['get', 'post']) {
      const original = api[method].bind(api);
      api[method] = async (path, body) => {
        window.__schemaAudit.requests.push({method, path, body});
        const result = await original(path, body);
        if (!held && method === ${JSON.stringify(method)} && path === ${JSON.stringify(path)}
            && (!${JSON.stringify(action)} || body?.action === ${JSON.stringify(action)})) {
          held = true;
          return new Promise((resolve) => { window.__schemaAudit.release = () => resolve(result); });
        }
        return result;
      };
    }
    const click = HTMLInputElement.prototype.click;
    HTMLInputElement.prototype.click = function () {
      if (this.type === 'file') window.__schemaAudit.picked.push(this);
      else click.call(this);
    };
  })()`);
}

async function assertNoEditorErrors(session, allowedWarnings = []) {
  assert.deepEqual(session.exceptions, []);
  assert.deepEqual(session.consoleErrors, []);
  const problems = await session.evaluate('window.studio.notify.store.get().problems');
  assert.deepEqual(problems.filter((item) => item.level !== 'warn' || !allowedWarnings.includes(item.title)), []);
}

for (const theme of ['light', 'dark']) {
  test(`Schema Editor drafts, schemas and revision recovery (${theme})`, {timeout: 60000}, async () => {
    const session = await launch({theme});
    try {
      await session.wait('window.studio?.store.get().adaptors.length > 0', 'Studio ready');
      await session.evaluate(`document.documentElement.dataset.theme = ${JSON.stringify(theme)};
        window.studio.windows.open('schema-editor', {id:'test'});`);
      await session.wait(`document.querySelector('${editorSelector}')`, 'Schema Editor');
      assert.ok(await session.evaluate(`document.querySelectorAll('.schema-choice').length >= 15`));
      await edit(session, source);
      await button(session, 'Save draft');
      await session.wait(`document.querySelector('.schema-editor .badge').textContent === 'Saved'`, 'draft saved');
      const id = await session.evaluate('window.studio.windows.active().params.document');
      const record = await session.evaluate(`window.studio.api.get('/api/document', {id:${JSON.stringify(id)}})`);
      assert.equal(record.source, source);
      await button(session, 'Validate');
      await session.wait(`window.studio.notify.store.get().log.some((e) => e.title === 'Document validated')`,
        'validated');
      // A schema fault is visible and is navigable in the diagnostics pane.
      const invalid = source.replace('"length": 10', '"length": "wide"');
      await edit(session, invalid);
      await session.wait(`document.querySelectorAll('.schema-problem').length > 0`, 'schema diagnostics');
      await session.clickSelector('.schema-problem');
      assert.ok(await session.evaluate(`document.querySelector('${editorSelector}').selectionEnd > 0`));
      if (process.env.STUDIO_SCREENSHOTS) {
        await session.screenshot(join(process.env.STUDIO_SCREENSHOTS, `studio-schema-${theme}.png`));
      }
      await button(session, 'Save draft');
      await session.wait(`document.querySelector('.schema-editor .badge').textContent === 'Saved'`,
        'invalid draft retained');
      const bad = await session.evaluate(`window.studio.api.get('/api/document', {id:${JSON.stringify(id)}})`);
      assert.equal(bad.valid, false);
      await button(session, 'Undo saved edit');
      await session.wait(`document.querySelector('${editorSelector}').value === ${JSON.stringify(source)}`,
        'undo saved');
      // A remote edit never silently overwrites the unsaved buffer.
      await edit(session, source.replace('"length": 10', '"length": 12'));
      await session.evaluate(`(async () => {
        const r = await window.studio.api.get('/api/document', {id:${JSON.stringify(id)}});
        await window.studio.api.post('/api/authoring', {action:'source', document:r.id, revision:r.revision,
          source: ${JSON.stringify(source.replace('"length": 10', '"length": 14'))}});
        await window.studio.refresh();
      })()`);
      await button(session, 'Save draft');
      await session.wait(`window.studio.notify.store.get().problems.some((p) => p.code === 'STALE_REVISION')`,
        'stale save is rejected');
      assert.ok(await session.evaluate(`document.querySelector('${editorSelector}').value.includes('"length": 12')`));
      assert.deepEqual(session.exceptions, []);
      assert.deepEqual(session.consoleErrors.filter((text) => !text.includes('status of 400')), []);
    } finally {
      await session.close();
    }
  });
}

test('Schema Editor keeps its binding while save and file selection are pending', {timeout: 60000}, async () => {
  const session = await launch();
  try {
    await openEditor(session, {id: 'save-lifecycle'});
    await edit(session, source);
    await button(session, 'Save draft');
    await session.wait(`document.querySelector('.schema-editor .badge').textContent === 'Saved'`, 'initial save');
    const id = await session.evaluate('window.studio.windows.active().params.document');
    const updated = source.replace('"length": 10', '"length": 12');
    await holdResponse(session, {method: 'post', path: '/api/authoring', action: 'source'});
    await edit(session, updated);
    await button(session, 'Save draft');
    await session.wait('Boolean(window.__schemaAudit.release)', 'save response held');
    assert.equal(await session.evaluate(`document.querySelector('.schema-editor .badge').textContent`), 'Saving…');
    for (const label of ['Open input', 'Save draft', 'Undo saved edit', 'Redo saved edit', 'Reload']) {
      await button(session, label);
      assert.equal(await session.evaluate('document.querySelectorAll(".dialog").length'), 0, label);
    }
    assert.equal(await session.evaluate('window.__schemaAudit.picked.length'), 0);
    assert.equal(await session.evaluate('window.studio.windows.active().params.document'), id);
    const duringSave = await session.evaluate('window.__schemaAudit.requests');
    assert.deepEqual(duringSave.map(({method, path, body}) => [method, path, body.action]),
      [['post', '/api/authoring', 'source']]);
    assert.equal(await session.evaluate(`document.querySelector('${editorSelector}').value`), updated);
    await session.evaluate('window.__schemaAudit.release()');
    await session.wait(`document.querySelector('.schema-editor .badge').textContent === 'Saved'`, 'save settled');
    const saved = await session.evaluate(`window.studio.api.get('/api/document', {id:${JSON.stringify(id)}})`);
    assert.equal(saved.source, updated);

    // A pending native file chooser must not let Save create/update a draft
    // before the user has selected a file or cancelled the chooser.
    await session.evaluate('window.__schemaAudit.requests = []');
    await button(session, 'Open input');
    await session.wait('window.__schemaAudit.picked.length === 1', 'file chooser opened');
    await button(session, 'Save draft');
    await button(session, 'Open input');
    assert.deepEqual(await session.evaluate('window.__schemaAudit.requests'), []);
    assert.equal(await session.evaluate('window.__schemaAudit.picked.length'), 1);
    assert.equal(await session.evaluate('window.studio.windows.active().params.document'), id);
    const imported = source.replace('"length": 10', '"length": 17');
    await session.evaluate(`(() => {
      const input = window.__schemaAudit.picked[0];
      const transfer = new DataTransfer();
      transfer.items.add(new File([${JSON.stringify(imported)}], 'imported.json', {type: 'application/json'}));
      input.files = transfer.files;
      input.dispatchEvent(new Event('change', {bubbles: true}));
    })()`);
    await session.wait(`document.querySelector('${editorSelector}').value === ${JSON.stringify(imported)}`,
      'file read');
    assert.equal(await session.evaluate('window.studio.windows.active().params.document'), null);
    await button(session, 'Save draft');
    await session.wait(`document.querySelector('.schema-editor .badge').textContent === 'Saved'`, 'import saved');
    const importedId = await session.evaluate('window.studio.windows.active().params.document');
    assert.notEqual(importedId, id);
    const original = await session.evaluate(`window.studio.api.get('/api/document', {id:${JSON.stringify(id)}})`);
    const opened = await session.evaluate(`window.studio.api.get('/api/document', {id:${JSON.stringify(importedId)}})`);
    assert.equal(original.source, updated);
    assert.equal(opened.source, imported);
    await assertNoEditorErrors(session);
  } finally {
    await session.close();
  }
});

test('Schema Editor preserves local typing when an incoming document read finishes', {timeout: 60000}, async () => {
  const session = await launch();
  try {
    await session.wait('window.studio?.store.get().adaptors.length > 0', 'Studio ready');
    const record = await session.evaluate(`window.studio.api.post('/api/documents', {
      action: 'new', provider: 'freecad', name: 'Saved box', source: ${JSON.stringify(source)},
    })`);
    await holdResponse(session, {method: 'get', path: '/api/document'});
    await openEditor(session, {document: record.id});
    await session.wait('Boolean(window.__schemaAudit.release)', 'document response held');
    const typed = source.replace('"length": 10', '"length": 19');
    await edit(session, typed);
    await session.evaluate(`(() => {
      const name = document.querySelector('.schema-name');
      name.value = 'Locally typed title';
      name.dispatchEvent(new Event('input', {bubbles: true}));
    })()`);
    await button(session, 'Open input');
    await button(session, 'Save draft');
    assert.equal(await session.evaluate('document.querySelectorAll(".dialog").length'), 0);
    assert.equal(await session.evaluate('window.__schemaAudit.picked.length'), 0);
    assert.equal(await session.evaluate('window.__schemaAudit.requests.filter((r) => r.method === "post").length'), 0);
    await session.evaluate('window.__schemaAudit.release()');
    await session.wait(`window.studio.notify.store.get().log.some((e) => e.title === 'Draft changed while refreshing')`,
      'incoming document yielded to local changes');
    assert.equal(await session.evaluate(`document.querySelector('${editorSelector}').value`), typed);
    assert.equal(await session.evaluate('document.querySelector(".schema-name").value'), 'Locally typed title');
    assert.equal(await session.evaluate('window.studio.windows.active().params.document'), record.id);
    assert.equal(await session.evaluate('window.studio.windows.active().window.isDirty()'), true);

    // An explicit reload still offers recovery after preserving the local draft.
    await button(session, 'Reload');
    await session.wait('document.querySelector(".dialog")', 'reload discard confirmation');
    await session.evaluate(`[...document.querySelectorAll('.dialog button')]
      .find((item) => item.textContent.trim() === 'Discard changes').click()`);
    await session.wait(`document.querySelector('${editorSelector}').value === ${JSON.stringify(source)}`, 'reload');
    assert.equal(await session.evaluate('document.querySelector(".schema-name").value'), 'Saved box');
    const original = await session.evaluate(
      `window.studio.api.get('/api/document', {id:${JSON.stringify(record.id)}})`);
    assert.equal(original.source, source);
    assert.equal(original.revision, record.revision);
    await assertNoEditorErrors(session, ['Draft changed while refreshing']);
  } finally {
    await session.close();
  }
});

test('Schema Editor accepts an empty saved design with its structural schema', {timeout: 60000}, async () => {
  const session = await launch();
  try {
    await session.wait('window.studio?.store.get().adaptors.length > 0', 'Studio ready');
    for (const version of ['schemaxis.workflow-design/1', 'schemaxis.workflow-design/2']) {
      const schema = await session.evaluate(
        `window.studio.api.get('/api/schema', {version:${JSON.stringify(version)}})`);
      assert.equal(schema.properties.version.const, version);
      assert.equal(schema.properties.workflow.properties.operations.minItems, 0);
      assert.deepEqual(schema['x-schemaxis-inlineDocuments'], ['/workflow']);
    }
    const record = await session.evaluate(`window.studio.api.post('/api/documents', {
      action: 'new', provider: 'workflow-design', name: 'Empty design',
    })`);
    assert.equal(record.document.version, 'schemaxis.workflow-design/2');
    assert.deepEqual(record.document.workflow.operations, []);
    await session.evaluate(`(() => {
      const original = window.studio.api.get.bind(window.studio.api);
      window.__loadedSchemas = [];
      window.studio.api.get = async (path, body) => {
        const result = await original(path, body);
        if (path === '/api/schema') window.__loadedSchemas.push(body.version);
        return result;
      };
    })()`);
    await openEditor(session, {document: record.id});
    await session.wait(`document.querySelector('.schema-editor .badge').textContent === 'Saved'`, 'design loaded');
    await session.wait(`['schemaxis.workflow-design/2', 'schemaxis.workflow/1']
      .every((version) => window.__loadedSchemas.includes(version))`, 'design and workflow schemas loaded');
    await button(session, 'Validate');
    await session.wait(`window.studio.notify.store.get().log.some((e) => e.title === 'Document validated')`,
      'validated');
    await session.wait('document.querySelector(".schema-problems-heading").textContent === "0 diagnostics"',
      'empty design has no standalone-workflow minimum-items fault');
    assert.equal(await session.evaluate('document.querySelectorAll(".schema-problem").length'), 0);
    await button(session, 'Save draft');
    await session.wait(`document.querySelector('.schema-editor .badge').textContent === 'Saved'`, 'design saved');
    const saved = await session.evaluate(`window.studio.api.get('/api/document', {id:${JSON.stringify(record.id)}})`);
    assert.equal(saved.valid, true);
    assert.deepEqual(saved.document, record.document);
    await assertNoEditorErrors(session);
  } finally {
    await session.close();
  }
});

test('Schema Editor preserves text and title typed during save and saved history', {timeout: 60000}, async () => {
  const session = await launch();
  const rename = async (name) => session.evaluate(`(() => {
    const input = document.querySelector('.schema-name');
    input.value = ${JSON.stringify(name)};
    input.dispatchEvent(new Event('input', {bubbles: true}));
  })()`);
  try {
    await openEditor(session, {id: 'history-lifecycle'});
    await edit(session, source);
    await button(session, 'Save draft');
    await session.wait(`document.querySelector('.schema-editor .badge').textContent === 'Saved'`, 'initial save');
    const id = await session.evaluate('window.studio.windows.active().params.document');
    const submitted = source.replace('"length": 10', '"length": 12');
    const typed = source.replace('"length": 10', '"length": 16');
    await edit(session, submitted);
    await rename('Submitted title');
    await holdResponse(session, {method: 'post', path: '/api/authoring', action: 'source'});
    await button(session, 'Save draft');
    await session.wait('Boolean(window.__schemaAudit.release)', 'save response held');
    await edit(session, typed);
    await rename('Typed during save');
    await session.evaluate('window.__schemaAudit.release()');
    await session.wait(`document.querySelector('.schema-editor .badge').textContent === 'Unsaved changes'`,
      'save settled');
    const submittedRecord = await session.evaluate(
      `window.studio.api.get('/api/document', {id:${JSON.stringify(id)}})`);
    assert.equal(submittedRecord.name, 'Submitted title');
    assert.equal(submittedRecord.source, submitted);
    assert.equal(await session.evaluate(`document.querySelector('${editorSelector}').value`), typed);
    assert.equal(await session.evaluate('document.querySelector(".schema-name").value'), 'Typed during save');
    await button(session, 'Save draft');
    await session.wait(`document.querySelector('.schema-editor .badge').textContent === 'Saved'`,
      'local changes saved');

    await holdResponse(session, {method: 'post', path: '/api/authoring', action: 'undo'});
    await button(session, 'Undo saved edit');
    await session.wait('Boolean(window.__schemaAudit.release)', 'undo response held');
    const duringUndo = source.replace('"length": 10', '"length": 21');
    await edit(session, duringUndo);
    await rename('Typed during undo');
    await session.evaluate('window.__schemaAudit.release()');
    await session.wait(`window.studio.notify.store.get().log.some((e) =>
      e.title === 'Draft changed during saved history')`,
      'undo response yielded to local changes');
    assert.equal(await session.evaluate(`document.querySelector('${editorSelector}').value`), duringUndo);
    assert.equal(await session.evaluate('document.querySelector(".schema-name").value'), 'Typed during undo');
    assert.equal(await session.evaluate('window.studio.windows.active().params.document'), id);
    assert.equal(await session.evaluate('window.studio.windows.active().window.isDirty()'), true);
    const saved = await session.evaluate(`window.studio.api.get('/api/document', {id:${JSON.stringify(id)}})`);
    assert.notEqual(saved.source, duringUndo);
    assert.notEqual(saved.name, 'Typed during undo');
    await assertNoEditorErrors(session, ['Draft changed during saved history', 'Document changed elsewhere']);
  } finally {
    await session.close();
  }
});
