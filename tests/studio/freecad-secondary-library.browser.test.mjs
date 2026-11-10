import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

test('CAM, assembly and drawing workbenches show their packaged templates', {timeout: 120000}, async () => {
  const s = await launch({provider: 'freecad'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio ready');
    for (const id of ['named-drilling', 'fixed-assembly', 'technical-drawing']) {
      await s.evaluate(`(async () => {
        const c = window.studio;
        const library = await c.api.get('/api/studio/adaptor', {id: 'freecad'});
        const item = library.templates.find(t => t.id === ${JSON.stringify(id)});
        const document = JSON.parse(JSON.stringify(item.document, (k, v) =>
          v && typeof v.$fill === 'string' ? item.fields[v.$fill].default : v));
        const record = await c.api.post('/api/documents', {action: 'new', provider: 'freecad',
          name: ${JSON.stringify(id)}, document});
        await c.refresh();
        c.windows.open('workbench', {document: record.id});
      })()`);
      await s.wait(`document.querySelector('[data-library="${id}"]')`, 'route template visible');
      assert.equal(await s.evaluate('document.querySelector(".wb-library").textContent.includes("no packaged library")'), false);
      assert.equal(await s.evaluate('Boolean(document.querySelector("[data-library=add-box]"))'), false);
    }
    assert.deepEqual(s.exceptions, []);
  } finally {
    await s.close();
  }
});
