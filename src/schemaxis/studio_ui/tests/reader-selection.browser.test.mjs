// Copyright (C) 2026 David L. F. Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

test('available names toggle selection rows, including keyboard, patterns and reader All mode', {timeout:120000}, async () => {
  const session = await launch({provider:'paraview'});
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async () => {
      window.toggleWidgets = await import('/windows/workbench/reader-selection.mjs');
      window.toggleDialogs = await import('/shell/dialog.mjs');
    })()`);
    const open = async (options, available) => {
      await session.evaluate(`(() => {
        const data = {available:true,regions:${JSON.stringify(available)}};
        window.togglePicker = toggleWidgets.readerSelection({...${JSON.stringify(options)},field:'regions',label:'Test selection',
          names:{get:()=>data,subscribe:()=>()=>{},load:async()=>data},inspect:async()=>data});
        void toggleDialogs.openDialog({title:'Select names',enterSubmits:false,content:togglePicker.element,
          actions:[{label:'Close',run:()=>null}]});
      })()`);
    };
    const click = name => session.evaluate(`[...document.querySelectorAll('.dialog .reader-choices button')]
      .find(button=>button.textContent===${JSON.stringify(name)}).click()`);
    const enter = async () => {
      await session.send('Input.dispatchKeyEvent', {type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});
      await session.send('Input.dispatchKeyEvent', {type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
    };
    const pressed = name => session.evaluate(`[...document.querySelectorAll('.dialog .reader-choices button')]
      .find(button=>button.textContent===${JSON.stringify(name)}).getAttribute('aria-pressed')`);
    const close = () => session.evaluate(`document.querySelector('.dialog-footer button').click()`);
    const rowCount = () => session.evaluate(`document.querySelectorAll('.dialog .reader-entry').length`);

    await open({blocks:true,initial:[]}, ['internalMesh','WT_wall_XP','Inlet']);
    assert.deepEqual(await session.evaluate(`[...document.querySelectorAll('.dialog .reader-choices button')].map(button=>button.textContent)`),
      ['Inlet','internalMesh','WT_wall_XP']);
    assert.equal(await pressed('internalMesh'), 'false');
    await session.evaluate(`[...document.querySelectorAll('.dialog .reader-choices button')].find(button=>button.textContent==='internalMesh').focus()`);
    await enter();
    assert.deepEqual(await session.evaluate('togglePicker.read()'), ['//internalMesh']);
    assert.equal(await rowCount(), 1);
    assert.equal(await session.evaluate('document.activeElement.textContent'), 'internalMesh');
    await enter();
    assert.equal(await rowCount(), 0);
    assert.equal(await pressed('internalMesh'), 'false');
    await click('Inlet'); await click('WT_wall_XP'); await click('Inlet');
    assert.deepEqual(await session.evaluate('togglePicker.read()'), ['//WT_wall_XP']);
    await close();

    await open({blocks:true,initial:[{pattern:'^WT_'}]}, ['WT_wall_XP','WT_wall_XM','Inlet']);
    await click('WT_wall_XP');
    assert.equal(await pressed('WT_wall_XP'), 'false');
    assert.equal(await pressed('WT_wall_XM'), 'true');
    assert.deepEqual(await session.evaluate('togglePicker.read()'), [{pattern:'^WT_'},{exclude:'^WT_wall_XP$'}]);
    await click('WT_wall_XP');
    assert.deepEqual(await session.evaluate('togglePicker.read()'), [{pattern:'^WT_'}]);
    await close();

    await open({initial:{select:'all'}}, ['U','UMean','p']);
    await click('U');
    assert.equal(await pressed('U'), 'false');
    assert.equal(await pressed('UMean'), 'true');
    assert.deepEqual(await session.evaluate('togglePicker.read()'), ['p','UMean']);
    assert.equal(await session.evaluate(`document.querySelector('.dialog [data-mode=names]').getAttribute('aria-checked')`), 'true');
    assert.equal(await session.evaluate(`document.querySelector('.dialog .reader-selection-note').hidden`), false);
    await click('U');
    assert.deepEqual(await session.evaluate('togglePicker.read()'), ['p','UMean','U']);
    await close();
    assert.deepEqual(session.exceptions, []);
    assert.deepEqual(session.consoleErrors, []);
  } finally {await session.close();}
});
