// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

test('both authoring surfaces compact, expand and navigate a draft comprehension reference', {timeout:120000}, async () => {
  const session = await launch({provider: 'paraview'});
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async () => {
      const ctx = window.studio;
      const record = await ctx.api.post('/api/documents', {action:'new', provider:'paraview', name:'Readable draft',
        document:{version:'schemaxis/1', nodes:[{id:'flow',filter:'wavelet'},
          {id:'speed',filter:'calculator',inputs:{input:'flow'},options:{expression:'mag(U)',result:'speed',association:'Point Data'}}],
          scenes:[{id:'view',geometry:['speed']}],settings:{args:[{$observe:'speed',path:['bounds',1]},{$observe:'speed',path:['bounds',0]}]}}});
      window.readableDocument = record.id; await ctx.refresh(); ctx.windows.open('workbench',{document:record.id});
    })()`);
    await session.wait('window.studio.windows.active().window.store?.get().schema', 'workbench schema');
    const click = async (selector, text) => session.evaluate(`[...document.querySelectorAll(${JSON.stringify(selector)} + ' button')].find(b => b.textContent.trim() === ${JSON.stringify(text)}).click()`);
    const source = () => session.evaluate('window.studio.windows.active().window.editor.getValue()');
    const original = await source();
    await click('.wb-editor-tools', 'Compact');
    const compact = await source();
    assert.deepEqual(JSON.parse(compact), JSON.parse(original));
    assert.ok(compact.split('\n').length < original.split('\n').length);
    assert.match(compact, /\["bounds", 1\]/);
    await click('.wb-editor-tools', 'Expand');
    assert.deepEqual(JSON.parse(await source()), JSON.parse(original));
    await session.evaluate(`document.querySelector('.wb-comprehension').open=true`);
    await session.wait(`document.querySelector('.wb-comprehension').textContent.includes('mag(U)')`, 'node description');
    await session.evaluate(`document.querySelector('.wb-comprehension [data-pointer="/nodes/1"]').click()`);
    assert.equal(await session.evaluate('window.studio.windows.active().window.store.get().selected'), '/nodes/1');
    await session.screenshot('/tmp/schemaxis-comprehension.png');
    assert.ok(await session.evaluate(`[...document.querySelectorAll('.wb-editor-tools button')].some(b=>b.textContent==='Preview with live data')`));
    await session.evaluate(`window.studio.windows.open('schema-editor',{document:window.readableDocument})`);
    await session.wait(`document.querySelector('.schema-editor .wb-comprehension')?.textContent.includes('mag(U)')`, 'schema reference');
    await click('.schema-toolbar', 'Compact');
    assert.match(await session.evaluate(`document.querySelector('.schema-source textarea').value`), /\["bounds", 1\]/);
    await click('.schema-toolbar', 'Expand');
    assert.deepEqual(JSON.parse(await session.evaluate(`document.querySelector('.schema-source textarea').value`)), JSON.parse(original));
    assert.deepEqual(session.exceptions, []);
  } finally { await session.close(); }
});
