import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

test('Application Setup reviews cache removal and preserves files by default', {timeout: 90000}, async () => {
  const session = await launch();
  try {
    await session.wait('window.studio?.store.get().server', 'Studio ready');
    await session.evaluate(`window.studio.api.post('/api/settings', {action:'write', values:{role:'admin'}, role:'admin'})
      .then(r => window.studio.store.set({settings:r}))`);
    await session.evaluate(`(() => {
      const original = window.studio.api.post.bind(window.studio.api);
      window.moduleCalls = [];
      window.studio.api.post = async (url, request) => {
        if (url !== '/api/setup' || !['modules','cachePlan','cacheClear','fetchModule','moduleSettings'].includes(request.action))
          return original(url, request);
        window.moduleCalls.push(request);
        if (request.action === 'modules') return {settings:{backend:'container',allowDownloads:true},
          sizeScope:'Sizes include shared layers.', modules:[{id:'blender',provider:'blender',applicationVersion:'test',
            installed:true,imageBytes:1048576,downloadBytes:2048,owned:true}]};
        if (request.action === 'cachePlan') return {confirmation:'reviewed-plan', modules:[{
          removeImage:true, removeDownload:request.downloads, blockedByContainers:[]}]};
        return {ok:true};
      };
      window.studio.windows.open('setup');
    })()`);
    await session.wait(`document.querySelector('[aria-label="Workflow execution backend"]')`, 'module preferences');
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="Workflow execution backend"]').value`), 'container');
    await session.evaluate(`Array.from(document.querySelectorAll('.setup-modules button')).find(b=>b.textContent==='Review cache cleanup').click()`);
    await session.wait(`Array.from(document.querySelectorAll('h3')).some(e=>e.textContent==='Clear Blender cache?')`, 'cleanup review');
    assert.equal(await session.evaluate(`window.moduleCalls.find(r=>r.action==='cachePlan').downloads`), false);
    assert.equal(await session.evaluate(`window.moduleCalls.some(r=>r.action==='cacheClear')`), false);
    assert.equal(await session.evaluate(`document.querySelector('.setup-modules').textContent.includes('Keep application preferences, module registration, projects, input files and results.')`), true);
    await session.evaluate(`Array.from(document.querySelectorAll('.setup-modules button')).find(b=>b.textContent==='Clear selected cache').click()`);
    await session.wait(`window.moduleCalls.some(r=>r.action==='cacheClear')`, 'explicit cache removal');
    assert.equal(await session.evaluate(`window.moduleCalls.find(r=>r.action==='cacheClear').confirmation`), 'reviewed-plan');
    assert.equal(await session.evaluate(`window.moduleCalls.find(r=>r.action==='cacheClear').role`), 'admin');
    assert.deepEqual(session.exceptions, []);
  } finally {
    await session.close();
  }
});
