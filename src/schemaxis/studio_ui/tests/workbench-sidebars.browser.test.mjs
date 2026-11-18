// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';
const active = 'studio.windows.active().window';
const node = index => `.wb-comprehension [data-pointer="/nodes/${index}"]`;

test('Overview toggles immediately on every click with bounded sticky actions; independent sidebars persist', {timeout:120000}, async () => {
  const s = await launch({provider:'paraview'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      localStorage.setItem('schemaxis.studio.workbench', JSON.stringify({sidebar:'all',shown:'all'}));
      const record=await studio.api.post('/api/documents',{action:'new',provider:'paraview',name:'Sidebar navigation',
        document:{version:'schemaxis/1',nodes:Array.from({length:80},(_,i)=>({id:'ball'+i,filter:'sphere',options:{radius:1}})),
          scenes:Array.from({length:40},(_,i)=>({id:'view'+i,geometry:['ball0']}))}});
      await studio.refresh(); studio.openDocument(record.id);
    })()`);
    await s.wait(`${active}.store?.get().schema`, 'workbench schema');
    await s.evaluate(`${active}.store.set({inspection:{available:true,node:'case',
      regions:Array.from({length:240},(_,i)=>'region_'+i).reverse(),cellArrays:Array.from({length:80},(_,i)=>'field_'+i).reverse(),
      pointArrays:['point10','point2','point1'],availableTimes:['10','2','1'],observation:{points:123,cells:456,bounds:[0,1,0,2,0,3]}}})`);
    const groups=await s.evaluate(`Object.fromEntries([...document.querySelectorAll('.wb-case-lists details')].map(group=>[
      group.dataset.section,[...group.querySelectorAll('.wb-case-name')].map(button=>button.textContent)]))`);
    assert.deepEqual(groups.regions.slice(0,3), ['region_0','region_1','region_2']);
    assert.deepEqual(groups.cellArrays.slice(0,3), ['field_0','field_1','field_2']);
    assert.deepEqual(groups.pointArrays, ['point1','point2','point10']);
    assert.deepEqual(groups.availableTimes, ['10','2','1']);
    assert.deepEqual(await s.evaluate(`[...document.querySelectorAll('[data-sidebar]')].map(b=>b.textContent)`), ['Overview','Templates']);
    assert.equal(await s.evaluate(`document.querySelector('[data-sidebar=guide]').getAttribute('aria-checked')`), 'true', 'Both migrates to Overview');
    assert.equal(await s.evaluate(`document.querySelector('.wb-sidebar-head [data-action=edit-settings]')`), null);
    assert.equal(await s.evaluate(`document.querySelector('.wb-view-state,.wb-diagnostic-state')`), null);
    const geometry=()=>s.evaluate(`(()=>{const top=s=>document.querySelector(s).getBoundingClientRect().top;
      return {left:top('.wb-sidebar-head'),right:top('.wb-case-heading'),filter:top('.wb-case-data > .input')}})()`);
    for (const mode of ['guide','library']) {
      await s.evaluate(`document.querySelector('[data-sidebar=${mode}]').click();
        document.querySelector('.wb-sidebar-content').scrollTop=0;document.querySelector('.wb-case-lists').scrollTop=0`);
      const before=await geometry();
      assert.ok(await s.evaluate(`(()=>{const left=document.querySelector('.wb-sidebar-content'),right=document.querySelector('.wb-case-lists');
        left.scrollTop=left.scrollHeight;right.scrollTop=right.scrollHeight;return left.scrollTop>100&&right.scrollTop>100})()`));
      assert.deepEqual(await geometry(), before);
    }
    await s.evaluate(`document.querySelector('[data-sidebar=guide]').click();document.querySelector(${JSON.stringify(node(35))}).scrollIntoView({block:'center'})`);
    await s.clickSelector(node(35));
    assert.deepEqual(await s.evaluate(`(()=>{const e=${active}.editor.textarea;return JSON.parse(e.value.slice(e.selectionStart,e.selectionEnd))})()`),
      {id:'ball35',filter:'sphere',options:{radius:1}});
    assert.ok(await s.evaluate(`document.querySelector('.wb-overview-node.selected > .wb-selection-guide')`));
    assert.equal(await s.evaluate(`document.querySelector('.wb-selection-guide input,.wb-selection-guide select,.wb-selection-guide textarea')`), null);
    await s.clickSelector(node(35));
    assert.equal(await s.evaluate(`${active}.store.get().selected`), '');
    assert.equal(await s.evaluate(`document.querySelector('.wb-overview-node.selected')`), null);
    assert.equal(await s.evaluate(`document.querySelector('.wb-selection-guide').hidden`), true);

    assert.doesNotMatch(await s.evaluate(`document.querySelector('.wb-comprehension > .wb-help').textContent`), /double.click/i);
    // Rapid physical clicks are two ordinary toggles, with no delayed editing action.
    const box = await s.evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(node(35))}).getBoundingClientRect();return [r.x+r.width/2,r.y+15]})()`);
    await s.click(...box); await s.click(...box, {clickCount:2});
    assert.equal(await s.evaluate(`${active}.store.get().selected`), '');
    assert.equal(await s.evaluate(`document.querySelector('.operation-dialog')`), null);
    // Deselecting must not build the enormous, hidden root schema. It is still
    // available, with the correct document context, when explicitly requested.
    assert.notEqual(await s.evaluate(`document.querySelector('.wb-schema h3')?.textContent`), 'Document schema');
    await s.clickSelector('.wb-tabs [data-tab=schema]');
    assert.equal(await s.evaluate(`document.querySelector('.wb-schema h3').textContent`), 'Document schema');
    await s.clickSelector('.wb-tabs [data-tab=input]');
    await s.clickSelector(node(35));
    await s.clickSelector('.wb-overview-node.selected [data-action=edit-settings]');
    await s.wait('document.querySelector(".operation-dialog")', 'Edit opens settings');
    assert.equal(await s.evaluate(`document.querySelector('[aria-label="sphere.id"]').value`), 'ball35');
    await s.evaluate(`(()=>{const input=document.querySelector('[aria-label="sphere.options.radius"]');input.value='2';
      input.dispatchEvent(new Event('input',{bubbles:true}));[...document.querySelectorAll('.operation-dialog > .dialog-footer button')]
      .find(b=>b.textContent==='Apply changes').click()})()`);
    await s.wait(`${active}.editor.getDocument().nodes[35].options.radius===2`, 'edit applied');
    await s.evaluate(`${active}.editor.undo()`);
    await s.wait(`${active}.editor.getDocument().nodes[35].options.radius===1`, 'undo restores node');
    await s.evaluate(`${active}.editor.revealPointer('/nodes/35/options/radius');${active}.editor.textarea.dispatchEvent(new KeyboardEvent('keyup',{key:'ArrowRight',bubbles:true}))`);
    await s.wait(`document.querySelector(${JSON.stringify(node(35))}).getAttribute('aria-current')==='true'`, 'Overview follows cursor');
    await s.evaluate(`document.querySelectorAll('.wb-overview-node.selected .wb-selection-guide details').forEach(d=>d.open=true)`);
    const pin = await s.evaluate(`(()=>{
      const scroller=document.querySelector('.wb-sidebar-content'),card=document.querySelector('.wb-overview-node.selected'),head=card.querySelector('.wb-node-head');
      const top=scroller.scrollTop+card.getBoundingClientRect().top-scroller.getBoundingClientRect().top;
      scroller.scrollTop=top+100;
      return {top:head.getBoundingClientRect().top,edge:scroller.getBoundingClientRect().top,height:head.offsetHeight,cardHeight:card.offsetHeight};
    })()`);
    assert.ok(pin.cardHeight > pin.height + 300, 'expanded properties provide real scrolling content');
    assert.ok(Math.abs(pin.top-pin.edge)<2, JSON.stringify(pin));
    assert.equal(await s.evaluate(`document.querySelector('.wb-overview-node.selected [data-action=edit-settings]').disabled`), false);
    if (process.env.SCHEMAXIS_SIDEBAR_SCREENSHOT) await s.screenshot(process.env.SCHEMAXIS_SIDEBAR_SCREENSHOT);
    await s.clickSelector('.wb-overview-node.selected [data-action=edit-settings]');
    await s.wait('document.querySelector(".operation-dialog")', 'sticky Edit remains usable');
    await s.evaluate(`[...document.querySelectorAll('.operation-dialog > .dialog-footer button')].find(b=>b.textContent==='Cancel').click()`);
    const stickyBox = await s.evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(node(35))}).getBoundingClientRect();return [r.x+r.width/2,r.y+15]})()`);
    await s.click(...stickyBox);
    assert.equal(await s.evaluate(`${active}.store.get().selected`), '', 'sticky title deselects on the first click');
    await s.click(...stickyBox, {clickCount:2});
    assert.equal(await s.evaluate(`${active}.store.get().selected`), '/nodes/35', 'the second rapid click selects again');
    assert.equal(await s.evaluate(`document.querySelector('.operation-dialog')`), null);
    await s.evaluate(`document.querySelectorAll('.wb-overview-node.selected .wb-selection-guide details').forEach(d=>d.open=true)`);
    const released = await s.evaluate(`(()=>{
      const scroller=document.querySelector('.wb-sidebar-content'),card=document.querySelector('.wb-overview-node.selected'),head=card.querySelector('.wb-node-head');
      const top=scroller.scrollTop+card.getBoundingClientRect().top-scroller.getBoundingClientRect().top;
      scroller.scrollTop=top+card.offsetHeight-head.offsetHeight+30;
      return head.getBoundingClientRect().top-scroller.getBoundingClientRect().top;
    })()`);
    assert.ok(released < -20, `Header leaves with the end of its card: ${released}`);

    await s.evaluate(`document.querySelector('.wb-overview-node.selected .wb-node-actions button:nth-child(2)').click()`);
    await s.wait(`${active}.editor.getDocument().nodes.length===81`, 'Duplicate from selected node');
    assert.equal(await s.evaluate(`${active}.editor.getDocument().nodes[36].options.radius`), 1);
    await s.evaluate(`${active}.editor.undo()`);
    await s.wait(`${active}.editor.getDocument().nodes.length===80`, 'Duplicate is one undo step');
    await s.evaluate(`${active}.editor.replaceDocument({version:'schemaxis/1',nodes:[
      {id:'source',filter:'sphere'}, {id:'dependent',filter:'shrink',inputs:{input:'source'}}],scenes:[{id:'view',geometry:['dependent']}]})`);
    await s.wait(`document.querySelector(${JSON.stringify(node(0))}).textContent.includes('source')`, 'dependent pipeline');
    await s.evaluate(`document.querySelector(${JSON.stringify(node(0))}).click();
      document.querySelector('.wb-overview-node.selected .wb-node-actions button:nth-child(3)').click()`);
    await s.wait(`document.querySelector('.dialog-header')?.textContent.includes('Delete pipeline objects')`, 'dependent deletion confirmation');
    await s.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent==='Delete').click()`);
    await s.wait(`${active}.editor.getDocument().nodes.length===0`, 'confirmed Delete removes dependents');
    await s.evaluate(`${active}.editor.undo()`);
    await s.wait(`${active}.editor.getDocument().nodes.length===2&&${active}.editor.getDocument().scenes.length===1`, 'Undo restores nodes and references');

    const widths=()=>s.evaluate(`Object.fromEntries(['left','centre','right'].map(name=>{const e=document.querySelector('.wb-'+name);return [name,e.hidden?0:e.getBoundingClientRect().width]}))`);
    const full=await widths();
    await s.clickSelector('.wb-case-data-toggle');
    const noRight=await widths(); assert.equal(noRight.right,0); assert.ok(noRight.centre>full.centre+200);
    await s.clickSelector('.wb-sidebar-toggle:not(.wb-case-data-toggle)');
    const neither=await widths(); assert.equal(neither.left,0); assert.ok(neither.centre>noRight.centre+190);
    await s.clickSelector('.wb-case-data-toggle');
    assert.equal((await widths()).left,0); assert.ok((await widths()).right>200);
    await s.clickSelector('.wb-case-data-toggle');
    await s.evaluate(`${active}.editor.setValue(${active}.store.get().record.source)`);
    await s.wait(`!${active}.store.get().dirty`, 'restore saved source before browser reload');
    await s.send('Page.reload');
    await s.wait(`window.studio?.windows.active()?.window?.store?.get().schema`, 'restored workbench');
    assert.equal(await s.evaluate(`document.querySelector('.wb-left').hidden&&document.querySelector('.wb-right').hidden`), true);
    assert.deepEqual(s.exceptions,[]); assert.deepEqual(s.consoleErrors,[]);
  } finally { await s.close(); }
});
