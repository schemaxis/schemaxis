// Copyright (C) 2026 David L. F. Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

test('structured document replacement preserves source boundaries and one undo/redo in JSON and YAML',
  {timeout: 120000}, async () => {
    const session = await launch({provider: 'paraview'});
    try {
      await session.wait('window.studio?.store.get().server', 'Studio');
      await session.evaluate(`(async () => {
        const record = await studio.api.post('/api/documents', {action:'new',provider:'paraview',name:'Document history',
          document:{version:'schemaxis/1',nodes:[{id:'ball',filter:'sphere'}],scenes:[]}});
        await studio.refresh(); studio.windows.open('workbench', {document:record.id});
      })()`);
      await session.wait('document.querySelector("[data-add=filters]")', 'Workbench');
      for (const format of ['json', 'yaml']) {
        await session.evaluate(`(() => {
          window.historyEditor = studio.windows.active().window.editor;
          if (${JSON.stringify(format)} === 'yaml') historyEditor.convertFormat('yaml');
          else historyEditor.setValue(${JSON.stringify(' \n')} + historyEditor.getValue().trim() + ${JSON.stringify('\n\n')});
          window.historyBefore = historyEditor.getValue();
          const value = historyEditor.getDocument();
          value.nodes.push({id:${JSON.stringify('extra_' + format)},filter:'sphere'});
          historyEditor.replaceDocument(value);
          historyEditor.revealPointer('/nodes/0');
          window.historyAfter = historyEditor.getValue();
        })()`);
        if (format === 'json') {
          assert.equal(await session.evaluate(`historyAfter.startsWith(${JSON.stringify(' \n')}) && historyAfter.endsWith(${JSON.stringify('\n\n')})`), true);
        }
        await session.evaluate('historyEditor.undo()');
        await session.wait('historyEditor.getValue() === historyBefore', `${format} undo`);
        await session.evaluate('historyEditor.redo()');
        await session.wait('historyEditor.getValue() === historyAfter', `${format} redo`);
        assert.equal((await session.evaluate('historyEditor.getDocument()')).nodes.at(-1).id, 'extra_' + format);
      }
      assert.deepEqual(session.exceptions, []);
      assert.deepEqual(session.consoleErrors, []);
    } finally { await session.close(); }
  });
