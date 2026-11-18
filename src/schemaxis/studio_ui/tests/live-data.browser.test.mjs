// Copyright (C) 2026 David L. F. Gaden.
// Browser regressions; native inspection is replaced at the job boundary here.
import assert from 'node:assert/strict';
import test from 'node:test';
import {launch} from './harness.mjs';

for (const theme of ['light', 'dark']) {
  test(`panel text selection survives background refresh (${theme})`, {timeout: 90000}, async () => {
    const s = await launch({theme});
    try {
      await s.wait('window.studio?.store.get().server', 'Studio');
      await s.evaluate(`studio.notify.error({code:'NATIVE_EXIT',message:'Native worker exited'});
        studio.store.set({panelOpen:true,panelTab:'problems'});`);
      for (const tab of ['problems', 'log']) {
        await s.evaluate(`studio.store.set({panelTab:${JSON.stringify(tab)}});
          window.selectedRow=document.querySelector('.panel-body .panel-row');
          var range=document.createRange();range.selectNodeContents(selectedRow);
          getSelection().removeAllRanges();getSelection().addRange(range);
          window.selectedText=getSelection().toString();`);
        assert.match(await s.evaluate('selectedText'), /Native worker exited/);
        await s.evaluate('(async()=>{for(let i=0;i<4;i++)await studio.refresh();})()');
        assert.equal(await s.evaluate('getSelection().toString() === selectedText && selectedRow.isConnected'), true);
      }
      await s.evaluate(`studio.store.set({panelTab:'problems'});studio.notify.error({message:'Another problem'});`);
      assert.equal(await s.evaluate(`document.querySelectorAll('.panel-body .panel-row').length`), 2);
      await s.evaluate('studio.notify.clearProblems()');
      assert.match(await s.evaluate(`document.querySelector('.panel-body').textContent`), /No problems/);
      assert.deepEqual(s.exceptions, []);
    } finally { await s.close(); }
  });

  test(`Live Data reports its own fault and retains metadata without a display mesh (${theme})`, {timeout: 90000}, async () => {
    const s = await launch({provider: 'paraview', theme});
    try {
      await s.wait('window.studio?.store.get().server', 'Studio');
      await s.evaluate(`(async()=>{
        const record=await studio.api.post('/api/documents',{action:'new',provider:'paraview',name:'Live reader',
          document:{version:'schemaxis/1',nodes:[{id:'ball',filter:'sphere'}],scenes:[]}});
        await studio.refresh();studio.openDocument(record.id);
      })()`);
      const active = 'studio.windows.active().window';
      await s.wait(`${active}.store?.get().schema`, 'Workbench');
      await s.evaluate(`window.wb=${active};window.failLive=true;
        const post=studio.api.post.bind(studio.api);
        studio.api.post=(path,body)=>path==='/api/inspect-input'?Promise.resolve({job:'inspection-fixture'}):post(path,body);
        studio.api.waitForJob=async()=>{
          if(failLive)throw Object.assign(Error('Native worker exited'),{code:'NATIVE_EXIT',location:'$'});
          return {result:{available:true,node:'ball',port:0,geometry:null,observation:{points:530,cells:1056,bounds:[-1,1,-1,1,-1,1]},
            assemblies:{Hierarchy:[],Assembly:[]},geometryUnavailable:{code:'LIVE_LIMIT',message:'Native surface exceeds live tessellation budget'}}};
        };studio.notify.clearProblems();`);
      await s.clickSelector('[data-action="inspect-live"]');
      await s.wait('studio.notify.store.get().problems.length', 'inspection error');
      assert.deepEqual(await s.evaluate('studio.notify.store.get().problems.map(p=>p.code)'), ['NATIVE_EXIT']);
      await s.evaluate('window.failLive=false;studio.notify.clearProblems()');
      await s.clickSelector('[data-action="inspect-live"]');
      await s.wait(`wb.store.get().dataMode==='live'`, 'live metadata');
      assert.equal(await s.evaluate('wb.store.get().inspection.observation.cells'), 1056);
      assert.match(await s.evaluate(`document.querySelector('.wb-case-data').textContent`), /530 points · 1056 cells/);
      assert.equal(await s.evaluate('studio.notify.store.get().problems.length'), 0);
      assert.match(await s.evaluate('studio.notify.store.get().log.at(-1).title'), /mesh display unavailable/);
      assert.deepEqual(s.exceptions, []);
    } finally { await s.close(); }
  });
}
