// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {mkdir, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {launch} from './harness.mjs';

test('foam form explains concepts, browses a case marker, and pipeline reference is visible', {timeout: 120000}, async () => {
  const session = await launch({provider: 'paraview'});
  try {
    const caseFolder = join(session.workspace, 'coupe');
    await mkdir(caseFolder); await writeFile(join(caseFolder, 'coupe.foam'), '');
    await writeFile(join(caseFolder, 'unrelated.txt'), '');
    await writeFile(join(caseFolder, '.hidden.foam'), '');
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async () => {
      const ctx = window.studio;
      const record = await ctx.api.post('/api/documents', {action:'new',provider:'paraview', name:'Foam guidance',
        document:{version:'schemaxis/1',nodes:[],scenes:[]}});
      await ctx.refresh();ctx.windows.open('workbench',{document:record.id});
      // This test uses an empty marker to exercise browsing/help, not native IO.
      const post=ctx.api.post.bind(ctx.api);ctx.api.post=(path,body)=>path==='/api/inspect-input' && body.prepare
        ? Promise.resolve({job:'fixture-reader-setup'}):post(path,body);
      const wait=ctx.api.waitForJob.bind(ctx.api);ctx.api.waitForJob=id=>id==='fixture-reader-setup'
        ? Promise.resolve({result:{value:{id:'case',filter:'foam',options:{file:${JSON.stringify(join(caseFolder,'coupe.foam'))}}},summary:'Browser fixture'}}):wait(id);
    })()`);
    await session.wait('document.querySelector("[data-add=inputs]")', 'Add input');
    assert.equal(await session.evaluate(`document.querySelector('.wb-comprehension').open`), true);
    assert.ok(await session.evaluate(`document.querySelector('.wb-left > .wb-comprehension') && !document.querySelector('.wb-left').hidden`));
    await session.clickSelector('[data-add=inputs]');
    await session.evaluate(`(() => {const e=document.querySelector('[aria-label="Search Add Input"]');e.value='foam';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    await session.wait(`document.querySelector('[data-library="operation:foam"]')`, 'foam card');
    await session.clickSelector('[data-library="operation:foam"]');
    await session.wait('document.querySelector(".operation-form")', 'foam form');
    const text = await session.evaluate(`document.querySelector('.operation-form').textContent`);
    assert.match(text, /Assigned automatically/); assert.match(text, /marker can be empty/); assert.match(text, /not from the JSON file/);
    await session.evaluate(`document.querySelector('[aria-label="foam.id"]').value='case'`);
    await session.evaluate(`document.querySelector('[aria-label="Browse for foam.options.file"]').scrollIntoView({block:'center'})`);
    await session.clickSelector('[aria-label="Browse for foam.options.file"]');
    try { await session.wait(`document.querySelector('.operation-file-list')?.textContent.includes('Folder: coupe')`, 'folder listing'); }
    catch (error) { throw new Error(await session.evaluate(`document.querySelector('.operation-file-browser').textContent + ' / ' + document.querySelector('[aria-label=\"Browse folder for foam.options.file\"]').value`)); }
    await session.evaluate(`[...document.querySelectorAll('.operation-file-list button')].find(b=>b.textContent==='Folder: coupe').click()`);
    await session.wait(`document.querySelector('.operation-file-list')?.textContent.includes('File: coupe.foam')`, 'case marker');
    assert.ok(!await session.evaluate(`document.querySelector('.operation-file-list').textContent.includes('unrelated.txt')`));
    assert.ok(!await session.evaluate(`document.querySelector('.operation-file-list').textContent.includes('.hidden.foam')`));
    await session.evaluate(`(() => {const e=[...document.querySelectorAll('.operation-file-browser label')].find(e=>e.textContent.includes('Hidden files')).querySelector('input');e.checked=true;e.dispatchEvent(new Event('change'));})()`);
    assert.ok(await session.evaluate(`document.querySelector('.operation-file-list').textContent.includes('.hidden.foam')`));
    await session.evaluate(`(() => {const e=[...document.querySelectorAll('.operation-file-browser label')].find(e=>e.textContent.includes('All file types')).querySelector('input');e.checked=true;e.dispatchEvent(new Event('change'));})()`);
    await session.wait(`document.querySelector('.operation-file-list')?.textContent.includes('unrelated.txt')`, 'all file types');
    await session.evaluate(`(() => {const e=document.querySelector('[aria-label="Filter files"]');e.value='coupe';e.dispatchEvent(new Event('input'));})()`);
    assert.equal(await session.evaluate(`document.querySelectorAll('.operation-file-list button').length`), 1);
    await session.evaluate(`[...document.querySelectorAll('.operation-file-browser button')].find(e=>e.textContent==='Back').click()`);
    await session.wait(`document.querySelector('.operation-file-list')?.textContent.includes('Folder: coupe')`, 'back to workspace');
    await session.evaluate(`[...document.querySelectorAll('.operation-file-browser button')].find(e=>e.textContent==='Forward').click()`);
    await session.wait(`document.querySelector('.operation-file-list')?.textContent.includes('File: coupe.foam')`, 'forward to case');
    await session.evaluate(`document.querySelector('[aria-label="Filter files"]').focus()`);
    await session.key('Escape');
    assert.equal(await session.evaluate(`document.querySelector('.operation-file-browser')`), null);
    assert.ok(await session.evaluate(`document.querySelector('.operation-form')!==null`));
    await session.evaluate(`document.querySelector('[aria-label="foam.options.file"]').value=${JSON.stringify(join(caseFolder,'coupe.foam'))}`);
    await session.evaluate(`document.querySelector('[aria-label="Browse for foam.options.file"]').click()`);
    await session.wait(`document.querySelector('.operation-file-list')?.textContent.includes('File: coupe.foam')`, 'reopened case');
    await session.evaluate(`[...document.querySelectorAll('.operation-file-list button')].find(b=>b.textContent==='File: coupe.foam').click()`);
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="File name"]').value`), 'coupe.foam');
    await session.evaluate(`[...document.querySelectorAll('.file-dialog .dialog-footer button')].find(b=>b.textContent==='Open').click()`);
    await session.wait(`!document.querySelector('.file-dialog')`, 'file chosen');
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="foam.options.file"]').value`), join(caseFolder, 'coupe.foam'));
    await session.evaluate(`(()=>{const e=document.querySelector('[aria-label="foam.options.cellArrays entry"]');e.value='U, p';
      e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));})()`);
    assert.ok(await session.evaluate(`document.querySelector('.operation-form')!==null`), 'Enter adds an entry and keeps the window open');
    assert.equal(await session.evaluate(`document.querySelectorAll('[aria-label="foam.options.cellArrays entries"] .reader-entry').length`), 2);
    await session.screenshot('/tmp/schemaxis-foam-guidance.png');
    await session.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent==='Add operation').click()`);
    await session.wait(`JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===1`, 'foam inserted');
    await session.wait(`document.querySelector('.wb-comprehension').textContent.includes('foam → case')`, 'updated pipeline reference');
    assert.deepEqual(await session.evaluate(`window.studio.windows.active().window.editor.getDocument().nodes[0].options.cellArrays`), ['U','p']);
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});
