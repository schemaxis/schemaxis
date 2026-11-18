// Copyright (C) 2026 David L. F. Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

test('native block choices follow the selected input and survive unrelated header refreshes', {timeout: 120000}, async () => {
  const session = await launch({provider: 'paraview'});
  const click = (text, scope) => session.evaluate(`[...document.querySelectorAll(${JSON.stringify(scope + ' button')})]
    .find(button => button.textContent === ${JSON.stringify(text)}).click()`);
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async () => {
      const metadata = await studio.api.get('/api/studio/adaptor', {id:'paraview',version:'schemaxis/1'});
      const item = metadata.addCatalogue.items.find(item => item.operation === 'extractBlock');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const root = {version:'schemaxis/1',nodes:[{id:'sourceA',filter:'sphere'},{id:'sourceB',filter:'sphere'}],scenes:[]};
      window.headerLoads = 0; window.sharedLiveCalls = 0;
      const shared = {get: () => ({available:true,regions:['headerOnly']}), load: async live => {
        if (live) { sharedLiveCalls++; throw Error('Shared reader metadata is not this filter input'); }
        headerLoads++; return {available:true,regions:['headerOnly']};
      }};
      const post = studio.api.post.bind(studio.api);
      studio.api.post = async (path, body) => {
        if (path !== '/api/inspect-input') return post(path, body);
        window.inspectedNode = body.node; return {job:'block-inspection-fixture'};
      };
      const wait = studio.api.waitForJob.bind(studio.api);
      studio.api.waitForJob = async id => id === 'block-inspection-fixture' ? {result:{assemblies:{Hierarchy:[
        {depth:1,label:'native_' + inspectedNode,parent:'/Root',selector:'/Root/' + inspectedNode}]}}} : wait(id);
      void configureOperation(studio, item, metadata.addCatalogue.definitions, () => root, undefined,
        {selected:'sourceA',caseData:shared});
    })()`);
    await session.wait('document.querySelector(".operation-dialog")', 'Extract Block form');
    await click('Ask the application', '.operation-form .reader-selection');
    await session.wait(`document.querySelector('.operation-form .reader-choices').textContent.includes('native_sourceA')`, 'Input A choices');
    assert.equal(await session.evaluate('sharedLiveCalls'), 0);
    await click('Load names', '.operation-case-tools');
    await session.wait('headerLoads === 1', 'Header refresh');
    assert.ok(await session.evaluate(`document.querySelector('.operation-form .reader-choices').textContent.includes('native_sourceA')`));
    await session.evaluate(`(() => {const input = document.querySelector('[aria-label="extractBlock.inputs.input"]');
      input.value='sourceB';input.dispatchEvent(new Event('change',{bubbles:true}));})()`);
    assert.ok(!await session.evaluate(`document.querySelector('.operation-form .reader-choices').textContent.includes('native_sourceA')`));
    await click('Ask the application', '.operation-form .reader-selection');
    await session.wait(`document.querySelector('.operation-form .reader-choices').textContent.includes('native_sourceB')`, 'Input B choices');
    assert.equal(await session.evaluate('inspectedNode'), 'sourceB');
    // A late native answer must not repopulate choices for an input that changed.
    await session.evaluate(`window.blockWait = studio.api.waitForJob;
      studio.api.waitForJob = id => new Promise(resolve => {window.releaseBlocks = () => resolve({result:{assemblies:{Hierarchy:[
        {depth:1,label:'stale_sourceB',parent:'/Root',selector:'/Root/B'}]}}});});`);
    await click('Ask the application', '.operation-form .reader-selection');
    await session.wait('window.releaseBlocks', 'Held native answer');
    await session.evaluate(`(() => {const input=document.querySelector('[aria-label="extractBlock.inputs.input"]');
      input.value='sourceA';input.dispatchEvent(new Event('change',{bubbles:true}));releaseBlocks();})()`);
    await session.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
    assert.ok(!await session.evaluate(`document.querySelector('.operation-form .reader-choices').textContent.includes('stale_sourceB')`));
    await session.evaluate('studio.api.waitForJob = blockWait');
    await click('Cancel', '.dialog-footer');
    assert.deepEqual(session.exceptions, []);
    assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});
