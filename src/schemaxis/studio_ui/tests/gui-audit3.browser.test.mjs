// Copyright (C) 2026 David L. F. Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {launch, delay} from './harness.mjs';

const PATCHES = ['body_upper', 'procBoundary0to2', 'underfloor_floor', 'wheels_FL_movingPatch', 'wheels_FL_Tyre',
  'wheels_FR_Tyre', 'WT_floor', 'WT_inlet'];

async function makeCase(folder) {
  await mkdir(join(folder, 'constant/polyMesh'), {recursive: true});
  await mkdir(join(folder, '1'));
  await writeFile(join(folder, 'coupe.foam'), '');
  await writeFile(join(folder, 'constant/polyMesh/boundary'), `FoamFile {class polyBoundaryMesh;}\n${PATCHES.length}\n(\n`
    + PATCHES.map((name) => `${name} {type patch; nFaces 4; startFace 0;}`).join('\n') + '\n)');
  await writeFile(join(folder, '1', 'U'), 'FoamFile { class volVectorField; }');
}

const setValue = (selector, value, type = 'input') => `(() => {const e=document.querySelector(${JSON.stringify(selector)});
  e.value=${JSON.stringify(value)};e.dispatchEvent(new Event(${JSON.stringify(type)},{bubbles:true}));})()`;
const press = (scope, label) => `[...document.querySelectorAll(${JSON.stringify(scope + ' button')})].find(b=>b.textContent===${JSON.stringify(label)}).click()`;
const source = 'window.studio.windows.active().window.editor.getDocument()';

test('blocks are chosen by name, expression and exclusion with the case names in view; nothing is added while typing',
  {timeout: 120000}, async () => {
    const session = await launch({provider: 'paraview'});
    try {
      const folder = join(session.workspace, 'coupe');
      await makeCase(folder);
      await session.wait('window.studio?.store.get().server', 'Studio');
      await session.evaluate(`(async () => {const ctx=window.studio;
        const record=await ctx.api.post('/api/documents',{action:'new',provider:'paraview',name:'blocks',
          document:{version:'schemaxis/1',nodes:[{id:'coupe',filter:'foam',options:{file:${JSON.stringify(join(folder, 'coupe.foam'))}}}],scenes:[]}});
        await ctx.refresh();ctx.windows.open('workbench',{document:record.id});})()`);
      await session.wait('document.querySelector("[data-add=filters]")', 'workbench');
      await session.wait('window.studio.windows.active().window.store.get().inspection?.available', 'case names loaded with the document');
      await session.clickSelector('[data-add=filters]');
      await session.evaluate(setValue('[aria-label="Search Add Filter"]', 'extractBlock'));
      await session.wait(`document.querySelector('[data-library="operation:extractBlock"]')`, 'extractBlock card');
      await session.clickSelector('[data-library="operation:extractBlock"]');
      await session.wait('document.querySelector(".operation-form .reader-selection")', 'block entries');
      assert.equal(await session.evaluate(`document.querySelector('.operation-top [data-action="load-case"]').textContent`), 'Load names');
      assert.equal(await session.evaluate(`document.querySelector('.reader-available-title').textContent`),
        `Names in the case (${PATCHES.length + 1})`);
      assert.equal(await session.evaluate(`document.querySelector('.reader-selection [role=radiogroup]').hidden`), true);

      const kind = '[aria-label="extractBlock.options.selectors entry kind"]', entry = '[aria-label="extractBlock.options.selectors entry"]';
      await session.evaluate(setValue(kind, 'regex', 'change'));
      await session.evaluate(`document.querySelector(${JSON.stringify(entry)}).focus()`);
      for (const character of '^wheels_') {
        await session.type(character);
      }
      await delay(700);
      assert.equal(await session.evaluate(`document.querySelectorAll('.reader-entry').length`), 0, 'typing a matching expression adds nothing');
      assert.equal(await session.evaluate(`document.querySelector(${JSON.stringify(entry)}).value`), '^wheels_');
      assert.match(await session.evaluate(`document.querySelector('.reader-named [role=status]').textContent`), /Not added yet\. Would match 3 of 9/);
      assert.match(await session.evaluate(`[...document.querySelectorAll('.operation-steps button')].at(-1).textContent`), /Final values \(0\)/);
      await session.evaluate(press('.reader-add', 'Add entry'));
      assert.equal(await session.evaluate(`document.querySelectorAll('.reader-entry').length`), 1);
      await session.evaluate(setValue(kind, 'exclude', 'change'));
      await session.evaluate(setValue(entry, 'movingPatch$'));
      await session.evaluate(press('.reader-add', 'Add entry'));
      await session.evaluate(`[...document.querySelectorAll('.reader-choices .wb-case-name')].find(b=>b.textContent==='internalMesh').click()`);
      assert.equal(await session.evaluate(`document.querySelector('.reader-summary').textContent`),
        'Selects 3 of 9 in this case: wheels_FL_Tyre, wheels_FR_Tyre, internalMesh');
      await session.evaluate(press('.dialog-footer', 'Add operation'));
      await session.wait(`${source}.nodes.length===2`, 'extractBlock added');
      assert.deepEqual(await session.evaluate(`${source}.nodes[1].options.selectors`),
        [{pattern: '^wheels_'}, {exclude: 'movingPatch$'}, '//internalMesh']);
      const validation = await session.evaluate(`window.studio.api.post('/api/validate',{provider:'paraview',source:window.studio.windows.active().window.editor.getValue()})`);
      assert.deepEqual(validation.diagnostics, []);

      // The settings window reopens from Properties with the entries it was added with.
      await session.evaluate(`[...document.querySelectorAll('.wb-comprehension button')].find(b=>b.textContent.includes('extractBlock1')).click()`);
      await session.wait(`document.querySelector('.wb-properties [data-action="edit-settings"]')`, 'Edit settings in Properties');
      assert.ok(await session.evaluate(`document.querySelector('.wb-editor-tools [data-action="edit-settings"]') !== null`));
      await session.evaluate(`document.querySelector('.wb-properties [data-action="edit-settings"]').click()`);
      await session.wait(`document.querySelector('.operation-dialog')`, 'settings window reopened');
      assert.equal(await session.evaluate(`document.querySelectorAll('.operation-form .reader-entry').length`), 3);
      await session.evaluate(press('.dialog-footer', 'Cancel'));

      // Expert mode folds help text behind the ? buttons.
      await session.evaluate(`window.studio.api.post('/api/settings',{action:'write',values:{'help.expert':true},role:'dev'}).then(r=>window.studio.store.set({settings:r}))`);
      await session.evaluate(`document.querySelector('.wb-editor-tools [data-action="edit-settings"]').click()`);
      await session.wait(`document.querySelector('.operation-wizard.expert')`, 'expert settings window');
      const shown = `getComputedStyle(document.querySelector('.operation-form .operation-field-description')).display`;
      assert.equal(await session.evaluate(shown), 'none');
      await session.evaluate(`document.querySelector('.operation-form .operation-field-description').parentElement.querySelector('[aria-label^="Help for"]').click()`);
      assert.notEqual(await session.evaluate(shown), 'none');
      await session.evaluate(press('.dialog-footer', 'Cancel'));
      assert.deepEqual(session.exceptions, []);
      assert.deepEqual(session.consoleErrors, []);
    } finally {
      await session.close();
    }
  });

test('Start lists each application with New, Open and recent work; a saved file opens, and Save as asks before replacing',
  {timeout: 120000}, async () => {
    const session = await launch({provider: 'paraview'});
    try {
      const folder = join(session.workspace, 'elsewhere');
      await mkdir(folder);
      const saved = join(folder, 'wing.json'), taken = join(folder, 'taken.json');
      await writeFile(saved, JSON.stringify({version: 'schemaxis/1', nodes: [], scenes: []}));
      await writeFile(taken, '{}');
      await session.wait('document.querySelector(".start-app")', 'Start');
      await session.clickSelector('.start-app[data-app="workbench"] [data-action="open-file"]');
      await session.wait(`document.querySelector('.file-dialog [aria-label="File name"]')`, 'Open window');
      await session.evaluate(setValue('.file-dialog [aria-label="File name"]', saved));
      await session.evaluate(press('.file-dialog .dialog-footer', 'Open'));
      await session.wait(`document.querySelector('.tab[aria-selected="true"] .label')?.textContent === 'wing'`, 'opened in the Workbench');
      await session.wait(`document.querySelector('.wb-view-state [role=status]')?.textContent.includes('wing.json')`, 'file shown beside the revision');
      await session.evaluate(`window.studio.windows.open('start')`);
      await session.wait(`[...document.querySelectorAll('.start-app[data-app="workbench"] .list-item')].some(i=>i.textContent.includes(${JSON.stringify(saved)}))`,
        'recent item names its file');

      await session.evaluate(`window.studio.openDocument(window.studio.store.get().server.documents.find(d=>d.name==='wing').id)`);
      await session.wait('document.querySelector(".window:not([hidden]) [data-action=save-menu]:not(:disabled)")', 'file menu');
      await session.evaluate(`document.querySelector('.window:not([hidden]) [data-action=save-menu]').click()`);
      await session.evaluate(`[...document.querySelectorAll('.menu-item')].find(b=>b.textContent==='Save as…').click()`);
      await session.wait(`document.querySelector('[aria-label="Source file path"]')`, 'Save as');
      assert.equal(await session.evaluate(`document.querySelector('[aria-label="Source file path"]').value`), saved);
      await session.evaluate(setValue('[aria-label="Source file path"]', taken));
      await session.evaluate(press('.dialog-footer', 'Save'));
      await session.wait(`document.querySelector('.dialog h3')?.textContent === 'Replace the existing file?'`, 'replace question');
      assert.equal(await readFile(taken, 'utf8'), '{}');
      await session.evaluate(press('.dialog-footer', 'Replace'));
      await session.wait(`document.querySelector('.wb-view-state [role=status]')?.textContent.includes('taken.json')`, 'saved under the new name');
      assert.match(await readFile(taken, 'utf8'), /schemaxis\/1/);
      assert.deepEqual(session.exceptions, []);
      assert.deepEqual(session.consoleErrors.filter((text) => !text.includes('status of 400')), []);
    } finally {
      await session.close();
    }
  });
