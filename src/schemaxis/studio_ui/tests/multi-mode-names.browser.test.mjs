// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import test from 'node:test';
import {launch} from './harness.mjs';

test('saved Names explain the identity lock without claiming that references were found', {timeout:120000}, async()=>{
  const s=await launch({provider:'paraview'});
  const click=(text,scope='.dialog-backdrop:last-child .dialog-footer')=>s.evaluate(`[...document.querySelectorAll(${JSON.stringify(scope+' button')})]
    .find(button=>button.textContent===${JSON.stringify(text)}).click()`);
  try {
    await s.wait('window.studio?.store.get().server','Studio');
    await s.evaluate(`(async()=>{
      const metadata=await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});
      const item=metadata.addCatalogue.items.find(item=>item.operation==='extractBlock');
      const {configureOperation}=await import('/windows/workbench/operation-form.mjs');
      window.nameRoot={version:'schemaxis/1',nodes:[{id:'source',filter:'sphere'},
        {id:'walls',filter:'extractBlock',inputs:{input:'source'},options:{selectors:['//wall']}},
        {id:'tyres',filter:'extractBlock',inputs:{input:'source'},options:{selectors:[{pattern:'^.*_T[yi]re$'}]}}],scenes:[]};
      window.openNameForm=group=>configureOperation(studio,item,metadata.addCatalogue.definitions,()=>nameRoot,undefined,
        {existing:{pointer:'/nodes/2',value:nameRoot.nodes[2]},...(group?{
          existingGroup:nameRoot.nodes.slice(1).map((value,index)=>({pointer:'/nodes/'+(index+1),value})),
          groupStartingValue:nameRoot.nodes[1]}:{})}).then(result=>window.nameResult=result);
      void openNameForm(false);
    })()`);
    await s.wait('document.querySelector(".operation-dialog")','ordinary instance settings');
    const single=await s.evaluate(`(()=>{const input=document.querySelector('[aria-label="extractBlock.id"]');
      return {readOnly:input.readOnly,disabled:input.disabled,description:input.closest('.operation-field').querySelector('.operation-field-description').textContent};})()`);
    assert.equal(single.readOnly,true);
    assert.equal(single.disabled,false);
    assert.match(single.description,/other items may refer/);
    await s.evaluate(`(()=>{const input=document.querySelector('[aria-label="extractBlock.id"]');input.value='renamedTyres';
      input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    await click('Apply changes');
    await s.wait('document.querySelector(".operation-wizard > .operation-error")?.textContent.includes("cannot be changed in Settings")',
      'saved Name substitution refused');
    assert.equal(await s.evaluate('window.nameResult'),undefined);
    await s.evaluate(`document.querySelector('[aria-label="extractBlock.id"]').value='tyres'`);
    await click('Apply changes');
    await s.wait('window.nameResult','single-instance settings applied');
    assert.equal(await s.evaluate('nameResult.replace.value.id'),'tyres');
    assert.deepEqual(await s.evaluate('nameResult.replace.value.options.selectors'),[{pattern:'^.*_T[yi]re$'}]);

    await s.evaluate('window.nameResult=undefined;void openNameForm(true)');
    await s.wait('document.querySelector(".operation-dialog.multi-mode-active")','saved batch settings');
    await s.evaluate(`document.querySelector('.multi-mode-row:nth-child(2) .multi-mode-row-toggle').click()`);
    const saved=await s.evaluate(`(()=>{const input=document.querySelector('[aria-label="Row 2 Name"]');
      return {readOnly:input.readOnly,title:input.title};})()`);
    assert.equal(saved.readOnly,true,'saved multi-mode names are locked even without references');
    assert.equal(saved.title,single.description);
    await click('Properties…','.multi-mode-row:nth-child(2)');
    await s.wait('document.querySelectorAll(".operation-dialog").length===2','saved instance Properties');
    const nested=await s.evaluate(`(()=>{const input=document.querySelector('.dialog-backdrop:last-child [aria-label="extractBlock.id"]');
      return {readOnly:input.readOnly,description:input.closest('.operation-field').querySelector('.operation-field-description').textContent};})()`);
    assert.equal(nested.readOnly,true);
    assert.equal(nested.description,saved.title);
    assert.doesNotMatch(nested.description,/Other nodes refer/);
    await click('Cancel');
    await click('Cancel');
    await s.wait('window.nameResult===null','batch cancellation');
    assert.equal(await s.evaluate('nameRoot.nodes[2].id'),'tyres');
    assert.deepEqual(s.exceptions,[]);
    assert.deepEqual(s.consoleErrors,[]);
  } finally {await s.close();}
});
