// Copyright (C) 2026 David L F Gaden
// YAML authoring acceptance uses the optional host extra, without native execution.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {test} from 'node:test';
import {launch} from './harness.mjs';
let available = true;
try { execFileSync(process.env.STUDIO_PYTHON || 'python3', ['-c', 'import ruamel.yaml'], {stdio: 'ignore'}); }
catch { available = false; }
const active = 'studio.windows.active().window';
const source = '# project note\nversion: schemaxis.freecad/1\nnodes:\n- id: body\n  filter: box\n  options:\n    length: 20\n    width: 10\n    height: 5 # thickness\noutput: body\n';

test('YAML workbench uses shared schema, comments, validation and saved revisions',
  {skip: !available, timeout: 60000}, async () => {
    const session = await launch();
    try {
      await session.wait('window.studio?.store.get().adaptors.length', 'adaptor catalogue');
      const id = await session.evaluate(`(async () => {
        const record = await studio.api.post('/api/documents', {action:'new', name:'YAML box',
          provider:'freecad', format:'yaml', source:${JSON.stringify(source)}});
        await studio.refresh(); studio.openDocument(record.id); return record.id;
      })()`);
      await session.wait(`${active}.store?.get().schema && ${active}.editor?.getOption('format') === 'yaml'`, 'YAML workbench');
      assert.equal(await session.evaluate(`${active}.editor.getDocument().nodes[0].options.height`), 5);
      await session.evaluate(`${active}.editor.insertAtPointer('/nodes/0/options/height', 7)`);
      assert.match(await session.evaluate(`${active}.editor.getValue()`), /height: 7 # thickness/);
      await session.clickSelector('.window:not([hidden]) [data-action="validate"]');
      await session.wait(`!${active}.store.get().busy && document.querySelector('.toast.ok')`, 'host validation');
      await session.clickSelector('.window:not([hidden]) [data-action="save"]');
      await session.wait(`document.querySelector('.dialog input[aria-label="Source file path"]')`, 'source destination');
      assert.match(await session.evaluate(`document.querySelector('.dialog input[aria-label="Source file path"]').value`), /\.yaml$/);
      await session.evaluate(`[...document.querySelectorAll('.dialog button')].find(button => button.textContent === 'Cancel').click()`);
      const saved = await session.evaluate(`studio.api.get('/api/document', {id:${JSON.stringify(id)}})`);
      assert.equal(saved.sourceFormat, 'yaml');
      assert.equal(saved.document.nodes[0].options.height, 7);
      assert.match(saved.source, /# project note/);
      assert.match(saved.source, /# thickness/);
      await session.evaluate(`${active}.editor.setValue('nodes: [\\n')`);
      const invalid = await session.evaluate(`studio.api.post('/api/validate', {provider:'freecad',format:'yaml',source:${active}.editor.getValue()})`);
      assert.equal(invalid.valid, false);
      assert.equal(invalid.diagnostics[0].code, 'INVALID_YAML');
      await session.evaluate(`${active}.editor.setValue(${JSON.stringify(saved.source)})`);
      await session.evaluate(`studio.windows.open('schema-editor', {document:${JSON.stringify(id)}})`);
      await session.wait(`${active}.editor?.getOption('format') === 'yaml' && document.querySelector('.window:not([hidden]) .schema-editor')`, 'YAML Schema Editor');
      assert.equal(await session.evaluate(`${active}.editor.getDocument().nodes[0].options.height`), 7);
      await session.evaluate(`${active}.editor.insertAtPointer('/nodes/0/options/height', 8)`);
      await session.evaluate(`[...document.querySelectorAll('.window:not([hidden]) button')].find(button => button.textContent.trim() === 'Save draft').click()`);
      await session.wait(`document.querySelector('.window:not([hidden]) .schema-editor .badge').textContent === 'Saved'`, 'YAML schema draft saved');
      const updated = await session.evaluate(`studio.api.get('/api/document', {id:${JSON.stringify(id)}})`);
      assert.equal(updated.sourceFormat, 'yaml');
      assert.equal(updated.document.nodes[0].options.height, 8);
      assert.match(updated.source, /# thickness/);
      assert.deepEqual(session.exceptions, []);
    } finally { await session.close(); }
  });
