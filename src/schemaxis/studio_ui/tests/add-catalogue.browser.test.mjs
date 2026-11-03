// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

async function button(session, selector, label) {
  await session.evaluate(`[...document.querySelectorAll(${JSON.stringify(selector + ' button')})].find(b => b.textContent.trim() === ${JSON.stringify(label)}).click()`);
}
async function field(session, label, value) {
  await session.evaluate(`(() => {const input=document.querySelector(${JSON.stringify('[aria-label="' + label + '"]')});
    input.value=${JSON.stringify(value)}; input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
}
async function clickField(session, label) {
  const selector = `[aria-label="${label}"]`;
  await session.evaluate(`(() => {const e=document.querySelector(${JSON.stringify(selector)});
    for(let p=e.parentElement;p;p=p.parentElement) if(p.tagName==='DETAILS') p.open=true;
    e.scrollIntoView({block:'center'});})()`);
  await session.clickSelector(selector);
}
async function operation(session, group, name) {
  await session.clickSelector(`[data-add="${group}"]`);
  await field(session, `Search ${group === 'sources' ? 'Add Source' : group === 'filters' ? 'Add Filter' : 'Add anything…'}`, name);
  await session.wait(`document.querySelector('[data-library="operation:${name}"]')`, 'operation card');
  await session.clickSelector(`[data-library="operation:${name}"]`);
  await session.wait('document.querySelector(".operation-form")', 'configuration');
}

test('complete Add form configures optional fields, placeholders, targets, cancellation and undo', {timeout:120000}, async () => {
  const session = await launch({provider:'paraview'});
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async () => {
      const ctx=window.studio;
      const record=await ctx.api.post('/api/documents',{action:'new',provider:'paraview',name:'Add coverage',
        document:{version:'schemaxis/1',nodes:[{id:'source',filter:'wavelet'}],scenes:[{id:'view',geometry:['source']}]}});
      window.addTestDocument=record.id; await ctx.refresh();ctx.windows.open('workbench',{document:record.id});
    })()`);
    await session.wait('document.querySelector("[data-add=sources]")', 'Add toolbar');
    const source = () => session.evaluate('window.studio.windows.active().window.editor.getValue()');
    const initial = await source();
    await operation(session, 'sources', 'sphere');
    await button(session, '.dialog-footer', 'Cancel');
    assert.equal(await source(), initial);
    await operation(session, 'sources', 'sphere');
    await field(session, 'sphere.id', 'ball');
    await clickField(session, 'Include sphere.options');
    await clickField(session, 'Include sphere.options.radius');
    await field(session, 'sphere.options.radius', '2');
    await clickField(session, 'Help for sphere.options.radius');
    assert.match(await session.evaluate('document.querySelector(".operation-form").textContent'), /exclusiveMinimum/);
    await session.screenshot('/tmp/studio-add-dialog-light.png');
    await button(session, '.dialog-footer', 'Add operation');
    await session.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===2', 'insertion');
    assert.equal(JSON.parse(await source()).nodes[1].options.radius, 2);
    await operation(session, 'filters', 'pvClip');
    await session.evaluate(`document.querySelector('.operation-form > details').open=true`);
    await session.evaluate(`document.querySelector('.operation-reference').parentElement.open=true`);
    await session.wait('document.querySelector(".operation-reference")?.textContent.includes("ClipType")', 'inline operation help');
    await session.evaluate(`document.querySelector('.operation-form > details').open=false`);
    await clickField(session, 'Include pvClip.options');
    await clickField(session, 'Include pvClip.options.ClipType');
    assert.ok(await session.evaluate(`[...document.querySelector('[aria-label="pvClip.options.ClipType value kind"]').options].some(o=>o.textContent==='Box')`));
    await button(session, '.dialog-footer', 'Insert required placeholders');
    await session.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===3', 'required insertion');
    const cut = JSON.parse(await source()).nodes.find(node => node.filter === 'pvClip');
    assert.equal(cut.filter, 'pvClip'); assert.equal(cut.id, 'pvClip1'); assert.equal(cut.inputs.Input, 'ball');
    await session.key('Escape');
    await session.evaluate('window.studio.windows.active().window.editor.focus()');
    await session.key('z',{modifiers:2});
    await session.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===2', 'atomic undo');
    await session.clickSelector('[data-add="all"]');
    await field(session, 'Search Add anything…', 'Camera');
    await session.clickSelector('[data-library="scene:camera"]');
    await session.wait('document.querySelector(".operation-form")', 'camera form');
    await button(session, '.dialog-footer', 'Add operation');
    assert.match(await session.evaluate('document.querySelector(".operation-error").textContent'), /target scene, image or node/);
    await button(session, '.dialog-footer', 'Cancel');
    assert.equal(JSON.parse(await source()).scenes[0].images, undefined);
    await session.clickSelector('[data-add="all"]');
    await field(session, 'Search Add anything…', 'Appearance');
    await session.clickSelector('[data-library="scene:appearance"]');
    await session.wait('document.querySelector(".operation-form")', 'appearance form');
    await button(session, '.dialog-footer', 'Add operation');
    await session.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).scenes[0].visible?.source', 'visible node');
    await session.clickSelector('[data-add="all"]');
    await field(session, 'Search Add anything…', 'Image');
    await session.evaluate(`document.querySelector('[data-library="scene:image"]').scrollIntoView({block:'center'})`);
    await session.clickSelector('[data-library="scene:image"]');
    await session.wait('document.querySelector(".operation-form")', 'image form');
    await field(session, 'Image.id', 'preview');
    await button(session, '.dialog-footer', 'Add operation');
    await session.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).scenes[0].images?.length===1', 'image insertion');
    const input = await source();
    const validation = await session.evaluate(`window.studio.api.post('/api/validate',{provider:'paraview',source:${JSON.stringify(input)}})`);
    assert.deepEqual(validation.diagnostics, []);
    // The same Add catalogue is available in Schema Editor, including cancellation.
    await session.evaluate(`window.studio.windows.open('schema-editor',{document:window.addTestDocument,versions:['schemaxis/1']})`);
    await session.wait('window.studio.windows.active()?.type==="schema-editor" && document.querySelector(".schema-editor [data-add=filters]")', 'Schema Editor catalogue');
    const schemaSource = await session.evaluate('document.querySelector(".schema-editor textarea").value');
    await session.clickSelector('.schema-editor [data-add="filters"]');
    await field(session, 'Search Add Filter', 'pvClip');
    await session.clickSelector('[data-library="operation:pvClip"]');
    await session.wait('document.querySelector(".operation-form")', 'schema configuration');
    await button(session, '.dialog-footer', 'Cancel');
    assert.equal(await session.evaluate('document.querySelector(".schema-editor textarea").value'), schemaSource);
    assert.deepEqual(session.exceptions, []);
  } finally {await session.close();}
});
