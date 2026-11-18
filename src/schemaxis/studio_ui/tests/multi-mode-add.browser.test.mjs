// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import test from 'node:test';
import {launch} from './harness.mjs';

for (const height of [700,1100]) test(`adding an instance keeps the preceding summary above the new editor (${height}px screen)`, {timeout:120000}, async () => {
  const s = await launch({provider:'paraview', height});
  const click = (text, scope='.operation-dialog') => text==='Add instance' && scope==='.operation-dialog'
    ? s.clickSelector('.multi-mode-toolbar > button') : s.evaluate(`[...document.querySelectorAll(${JSON.stringify(scope+' button')})]
    .find(button=>button.textContent===${JSON.stringify(text)}).click()`);
  const expanded = () => s.evaluate(`[...document.querySelectorAll('.multi-mode-row-toggle')].map(button=>button.getAttribute('aria-expanded'))`);
  const visiblePair = async () => {
    await s.evaluate('new Promise(requestAnimationFrame)');
    const view=await s.evaluate(`(() => {
      const list=document.querySelector('.multi-mode-rows'),row=list.lastElementChild,previous=row.previousElementSibling;
      const a=list.getBoundingClientRect(),b=row.getBoundingClientRect(),p=previous.getBoundingClientRect();
      return {scroll:list.scrollTop,previousTop:p.top-a.top,previousBottom:p.bottom-a.top,
        top:b.top-a.top,headerBottom:row.querySelector('.multi-mode-row-summary').getBoundingClientRect().bottom-a.top,
        height:list.clientHeight,previousCollapsed:previous.classList.contains('compact'),
        footer:document.querySelector('.operation-dialog > .dialog-footer').getBoundingClientRect().bottom,viewport:innerHeight};
    })()`);
    assert.ok(view.previousCollapsed && view.previousTop>=0 && view.previousTop<=3,
      `the second-last instance is collapsed at the top of the list: ${JSON.stringify(view)}`);
    assert.ok(view.top>view.previousBottom && view.headerBottom<view.height,
      `the expanded new instance is visible directly below: ${JSON.stringify(view)}`);
    assert.ok(view.footer<=view.viewport,'Apply/Cancel remain inside the screen');
    return view;
  };
  try {
    await s.wait('window.studio?.store.get().server','Studio');
    await s.evaluate(`(async () => {
      const meta=await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});
      const item=meta.addCatalogue.items.find(item=>item.operation==='extractBlock');
      const {configureOperation}=await import('/windows/workbench/operation-form.mjs');
      window.addRoot={version:'schemaxis/1',nodes:[{id:'source',filter:'sphere'}],scenes:[]};
      const headers={available:true,regions:['wall10','wall2','Inlet']};
      const shared={get:()=>headers,subscribe:()=>()=>{},load:async()=>headers};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>addRoot,undefined,
        {selected:'source',caseData:shared}).then(result=>window.addResult=result);
    })()`);
    await s.wait('document.querySelector(".operation-dialog")','settings');
    await click('Switch to multi-mode');
    await click('wall10','.multi-mode-row');
    await s.evaluate(`(() => {const name=document.querySelector('[aria-label="Row 1 Name"]');name.value='outerWall';
      name.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    await click('Add instance');
    assert.deepEqual(await expanded(),['false','true']);
    await visiblePair();
    assert.equal(await s.evaluate('document.querySelector(".multi-mode-summary-name").textContent'),'outerWall');
    assert.equal(await s.evaluate('document.activeElement.closest(".multi-mode-row").getAttribute("aria-label")'),'Instance 2');
    assert.equal(await s.evaluate('document.activeElement.textContent'),'Inlet','focus uses the first sorted choice');
    // A pending invalid pattern refuses Add without collapsing the editable row.
    await s.evaluate(`(() => {const row=document.querySelector('.multi-mode-row:nth-child(2)');
      row.querySelector('details.reader-selectors').open=true;
      row.querySelector('[aria-label="Row 2.Blocks entry kind"]').value='regex';
      const input=row.querySelector('[aria-label="Row 2.Blocks entry"]');input.value='[';
      input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    await click('Add instance');
    assert.deepEqual(await expanded(),['false','true']);
    assert.match(await s.evaluate('document.querySelector(".multi-mode > .operation-error").textContent'),/valid regular expression/);
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="Row 2.Blocks entry"]').value`),'[');
    // A valid pending pattern is captured before the row minimises.
    await s.evaluate(`(() => {const input=document.querySelector('[aria-label="Row 2.Blocks entry"]');input.value='^wall';
      input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    await click('Add instance');
    assert.deepEqual(await expanded(),['false','false','true']);
    await visiblePair();
    assert.match(await s.evaluate('document.querySelectorAll(".multi-mode-summary-items")[1].textContent'),/pattern: \^wall/);
    await click('Inlet','.multi-mode-row:nth-child(3)');
    // Each addition leaves the previous summary visible, including after many rows.
    for (let row=4;row<=14;row++) {
      await click('Add instance');
      await visiblePair();
      assert.equal(await s.evaluate('document.activeElement.closest(".multi-mode-row").getAttribute("aria-label")'),`Instance ${row}`);
      await click('wall2',`.multi-mode-row:nth-child(${row})`);
    }
    assert.deepEqual(await expanded(),[...Array(13).fill('false'),'true']);
    assert.ok((await visiblePair()).scroll>0,'older instances remain available above the visible pair');
    if(process.env.SCHEMAXIS_ADD_ORIENTATION_SCREENSHOT) await s.screenshot(process.env.SCHEMAXIS_ADD_ORIENTATION_SCREENSHOT);
    // Reopening an older editor does not change which summary orients the next addition.
    await s.evaluate(`document.querySelector('.multi-mode-row:first-child .multi-mode-row-toggle').click()`);
    await click('Add instance');
    await visiblePair();
    assert.deepEqual(await expanded(),[...Array(14).fill('false'),'true']);
    await click('wall2','.multi-mode-row:last-child');
    await click('Apply instances');
    await s.wait('window.addResult','saved instances');
    const values=await s.evaluate('addResult.inserts.at(-1).values');
    assert.equal(values.length,15);
    assert.equal(values[0].id,'outerWall');
    assert.deepEqual(values.slice(0,3).map(value=>value.options.selectors),[['//wall10'],[{pattern:'^wall'}],['//Inlet']]);
    assert.deepEqual(s.exceptions,[]);
    assert.deepEqual(s.consoleErrors,[]);
  } finally {await s.close();}
});
