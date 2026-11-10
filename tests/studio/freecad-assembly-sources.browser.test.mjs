// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

// Editing-only fixtures: sourced parts name `$artifact` publications of producers in the same workflow, so nothing
// here plans, runs or verifies a real FreeCAD part; source integrity stays the backend's gate.
const WORKFLOW = new URL('../../examples/schemaxis/freecad-assembly-parts-workflow.json', import.meta.url);
const ROUTE = 'schemaxis.freecad.assembly/1';

async function field(s, label, value) {
  await s.evaluate(`(() => {const e=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});
    if(!e || e.disabled)throw Error('Missing or disabled field '+${JSON.stringify(label)});
    e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));
    e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}
async function button(s, label, selector = '.dialog-footer') {
  await s.evaluate(`(() => {const b=[...document.querySelectorAll(${JSON.stringify(selector+' button')})]
    .find(b=>b.textContent.trim()===${JSON.stringify(label)});
    if(!b)throw Error('Missing button '+${JSON.stringify(label)});b.click();})()`);
}
async function revealAndClick(s, label) {
  await s.evaluate(`(() => {const e=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});
    if(!e)throw Error('Missing control '+${JSON.stringify(label)});
    for(let p=e.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;
    e.click();})()`);
}
async function setIncluded(s, label, included) {
  await s.evaluate(`(() => {const e=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});
    if(!e)throw Error('Missing include control '+${JSON.stringify(label)});
    for(let p=e.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;
    if(e.checked!==${included}){e.checked=${included};e.dispatchEvent(new Event('change',{bubbles:true}));}})()`);
}
async function add(s, id, query) {
  await s.clickSelector('[data-add="all"]');
  await field(s, 'Search Add anything…', query);
  await s.wait(`document.querySelector('[data-library="${id}"]')`, 'matching Add control');
  await s.clickSelector(`[data-library="${id}"]`);
  await s.wait('document.querySelector(".operation-form")', 'typed authoring form');
}
async function fieldHelp(s, label) {
  await revealAndClick(s, `Help for ${label}`);
  return s.evaluate(`document.querySelector(${JSON.stringify('[aria-label="Help for '+label+'"]')})
    .closest('.operation-field').querySelector('.operation-field-help').textContent`);
}
const formError = (s) => s.evaluate('document.querySelector(".operation-error")?.textContent || ""');
async function rejected(s, text, description) {
  await button(s, 'Add operation');
  await s.wait(`document.querySelector('.operation-error')?.textContent.includes(${JSON.stringify(text)})`, description);
  assert.equal(await s.evaluate('!!document.querySelector(".operation-form")'), true, `${description}: form stays open`);
}
async function openSourcedAssembly(s, workflow) {
  await s.wait('window.studio?.store.get().server', 'Studio ready');
  await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',
    {action:'new',provider:'workflow',name:'Sourced part assembly',document:${JSON.stringify(workflow)}});
    await c.refresh();c.windows.open('workbench',{document:r.id,operation:'assembly'});})()`);
  await s.wait('document.querySelector("[data-add=all]")', 'Workbench ready');
  await s.wait('window.studio.windows.active().window.editor.getValue().includes("$artifact")', 'assembly operation loaded');
}

test('FreeCAD Studio discovers rigid assemblies of modelled parts and keeps the constructor template unchanged', {timeout: 120000}, async () => {
  const s = await launch({provider: 'freecad'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio ready');
    await s.evaluate(`window.studio.bus.emit('new-instance')`);
    await s.wait(`document.querySelector('[aria-label="Search adaptors"]')`, 'adaptor discovery');
    // Phrases a user may type for this route that the packaged adaptor text contains.
    for (const intent of ['rigid assembly', 'named mounts', 'modelled parts', 'fixed joint']) {
      await field(s, 'Search adaptors', intent);
      await s.wait(`document.querySelector('[role=listbox]')?.textContent.includes('FreeCAD')`, `FreeCAD discovered by "${intent}"`);
    }
    await field(s, 'Search adaptors', 'sanitize redact encrypt PDF');
    await s.wait(`!document.querySelector('[role=listbox]')?.textContent.includes('FreeCAD')`, 'unrelated intent does not offer FreeCAD');
    await field(s, 'Search adaptors', 'FreeCAD');
    await s.wait(`document.querySelector('[role=listbox]')?.textContent.includes('FreeCAD')`, 'FreeCAD listed');
    await s.evaluate(`[...document.querySelectorAll('[role=listbox] [role=option]')].find(o=>o.querySelector('.title')?.textContent.trim()==='FreeCAD').click()`);

    // The constructor assembly template stays declared, literal and host-valid.
    const library = await s.evaluate(`window.studio.api.get('/api/studio/adaptor', {id: 'freecad'})`);
    const template = library.templates.find((item) => item.id === 'fixed-assembly');
    assert.ok(template?.document, 'fixed-assembly template is declared with a literal document');
    assert.equal(template.document.version, ROUTE);
    assert.ok(template.document.parts.length >= 2);
    assert.ok(template.document.parts.every((part) => part.type && part.options && !('source' in part) && !('mounts' in part)),
      'constructor parts keep type/options and never mix in sources');
    // Its two required dimensions are declared fill fields; unfilled, the host refuses it, filled with the declared defaults it is valid.
    assert.deepEqual(Object.keys(template.fields).sort(), ['height', 'thickness']);
    const unfilled = await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(template.document))}})`);
    assert.equal(unfilled.valid, false);
    assert.equal(unfilled.diagnostics[0].code, 'UNFILLED_VALUES');
    const filled = JSON.parse(JSON.stringify(template.document, (key, value) => (value && typeof value.$fill === 'string'
      ? template.fields[value.$fill].default : value)));
    const checked = await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(filled))}})`);
    assert.equal(checked.valid, true, JSON.stringify(checked.diagnostics));
    assert.deepEqual(checked.diagnostics, []);
    const option = await s.evaluate(`[...document.querySelectorAll('select option')].map(o => o.value).includes('fixed-assembly')`);
    assert.equal(option, true, 'the new-instance dialog offers the template by its stable id');
    await s.evaluate(`(() => {const t=[...document.querySelectorAll('select')].find(x=>[...x.options].some(o=>o.value==='fixed-assembly'));
      t.value='fixed-assembly';t.dispatchEvent(new Event('change',{bubbles:true}));})()`);
    await s.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent.trim()==='Create instance').click()`);
    await s.wait('window.studio.windows.active()?.window?.editor?.getValue', 'template document opened');
    await s.wait(`window.studio.windows.active().window.editor.getValue().includes('"parts"')`, 'assembly source shown');
    const created = JSON.parse(await s.evaluate('window.studio.windows.active().window.editor.getValue()'));
    assert.equal(created.version, ROUTE);
    assert.deepEqual(created.parts, template.document.parts);
    assert.deepEqual(created.joints, template.document.joints);
    assert.deepEqual(s.exceptions, []);
  } finally {await s.close();}
});

test('FreeCAD Studio authors sourced-part joints with guidance, bounds, cancellation and atomic undo', {timeout: 180000}, async () => {
  const workflow = JSON.parse(await readFile(WORKFLOW, 'utf8'));
  const operation = workflow.operations.find((item) => item.id === 'assembly').document;
  assert.equal(operation.version, ROUTE);
  assert.ok(operation.parts.every((part) => part.source?.$artifact && part.mounts));
  const s = await launch({provider: 'freecad'});
  try {
    await openSourcedAssembly(s, workflow);
    const source = () => s.evaluate('window.studio.windows.active().window.editor.getValue()');
    const initial = await source();
    assert.deepEqual(JSON.parse(initial), operation);
    assert.equal(await s.evaluate(`window.studio.windows.active().window.editor.getValue().includes('"index": 2')`), true);

    // Guidance for the new mount, offset and clocking concepts comes from reviewed field explanations.
    await add(s, 'document:parts', 'parts');
    await field(s, 'parts[0] value kind', '2');
    for (const label of ['parts[0].source', 'parts[0].mounts', 'parts[0].id']) {
      assert.equal(await s.evaluate(`!!document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')})`), true, label);
    }
    assert.match(await fieldHelp(s, 'parts[0].source'), /model\.FCStd publication of a verified schemaxis\.freecad\/1 run/);
    const mountHelp=await fieldHelp(s, 'parts[0].mounts');
    assert.match(mountHelp, /mounting frames on the selected source Body/);
    assert.match(mountHelp, /Joint endpoints use mount IDs/);
    // Mounts use a JSON control; malformed JSON is refused before any draft edit.
    await field(s, 'parts[0].id', 'bracket');
    await field(s, 'parts[0].source', '/replace/with/bracket/model.FCStd');
    await field(s, 'parts[0].mounts', '{"top":');
    await button(s, 'Add operation');
    await s.wait(`document.querySelector('.operation-error')?.textContent.trim().length > 0`, 'malformed mount JSON refused');
    assert.equal(await source(), initial);
    // Abandoning a half-authored sourced part leaves the draft byte for byte.
    await field(s, 'parts[0].mounts', '{"top":{"position":[0,0,5]}}');
    await button(s, 'Cancel');
    assert.equal(await source(), initial);

    // Joints: boundaries at the form, then typed offset and clocking edits.
    await add(s, 'document:joints', 'joint');
    assert.match(await fieldHelp(s, 'joints[0].offset'), /Translation \[x, y, z\] in millimetres/);
    assert.match(await fieldHelp(s, 'joints[0].clocking'), /about the parent mount's \+Z axis, applied after the offset/);
    const parentHelp = await fieldHelp(s, 'joints[0].parent');
    assert.match(parentHelp, /face \(top or bottom\) for constructor parts/);
    assert.match(parentHelp, /a named mount of that component's part for modelled parts/);
    await button(s, 'Remove', '.operation-form');
    await rejected(s, 'Expected at least 1 item', 'joint list lower bound');
    assert.equal(await source(), initial);
    await button(s, 'Add joints item', '.operation-form');
    await field(s, 'joints[0].id', 'baseToSpacer');
    await field(s, 'joints[0].parent value kind', '1');
    await field(s, 'joints[0].parent', '{"component":"base","mount":"top"}');
    await field(s, 'joints[0].child value kind', '1');
    await field(s, 'joints[0].child', '{"component":"spacer","mount":"bottom"}');
    await setIncluded(s, 'Include joints[0].offset', true);
    await field(s, 'joints[0].offset[0]', '5');
    await field(s, 'joints[0].offset[1]', '0');
    await field(s, 'joints[0].offset[2]', '0');
    await setIncluded(s, 'Include joints[0].clocking', true);
    await field(s, 'joints[0].clocking', '361');
    await rejected(s, 'Must be at most 360', 'clocking upper bound');
    await field(s, 'joints[0].clocking', '-361');
    await rejected(s, 'Must be at least -360', 'clocking lower bound');
    await field(s, 'joints[0].clocking', '45');
    await field(s, 'joints[0].offset[0]', '100001');
    await rejected(s, 'Must be at most 100000', 'offset upper bound');
    assert.equal(await source(), initial);
    await field(s, 'joints[0].offset[0]', '7');
    await button(s, 'Add joints item', '.operation-form');
    await field(s, 'joints[1].id', 'spacerToCover');
    await field(s, 'joints[1].parent value kind', '1');
    await field(s, 'joints[1].parent', '{"component":"spacer","mount":"top"}');
    await field(s, 'joints[1].child value kind', '1');
    await field(s, 'joints[1].child', '{"component":"cover","mount":"side"}');
    await setIncluded(s, 'Include joints[1].offset', true);
    await field(s, 'joints[1].offset[0]', '0');
    await field(s, 'joints[1].offset[1]', '0');
    await field(s, 'joints[1].offset[2]', '2');
    await setIncluded(s, 'Include joints[1].clocking', false);
    await button(s, 'Add operation');
    await s.wait(`JSON.parse(window.studio.windows.active().window.editor.getValue()).joints[0].clocking===45`, 'typed joints inserted');
    const changed = JSON.parse(await source());
    assert.deepEqual(changed.joints, [
      {id: 'baseToSpacer', type: 'fixed', parent: {component: 'base', mount: 'top'}, child: {component: 'spacer', mount: 'bottom'},
        offset: [7, 0, 0], clocking: 45},
      {id: 'spacerToCover', type: 'fixed', parent: {component: 'spacer', mount: 'top'}, child: {component: 'cover', mount: 'side'},
        offset: [0, 0, 2]},
    ]);
    // Everything else, including the artifact bindings that identify the producers, is untouched.
    assert.deepEqual(changed, {...operation, joints: changed.joints});
    assert.deepEqual(changed.parts.map((part) => part.source), [{$artifact: 'plate', index: 2}, {$artifact: 'spacer', index: 2}]);

    // A later abandoned edit changes nothing; one undo restores the whole earlier joint list.
    const edited = await source();
    await add(s, 'document:joints', 'joint');
    await field(s, 'joints[0].id', 'abandoned');
    await button(s, 'Cancel');
    assert.equal(await source(), edited);
    await s.evaluate('window.studio.windows.active().window.editor.focus()');
    await s.key('z', {modifiers: 2});
    await s.wait(`JSON.parse(window.studio.windows.active().window.editor.getValue()).joints[0].clocking===90`, 'atomic joint-list undo');
    assert.equal(await source(), initial);
    assert.deepEqual(s.exceptions, []);
  } finally {await s.close();}
});

test('reviewed search case "rigid assembly of modelled parts at named mounts" reaches FreeCAD', {
  timeout: 60000,
}, async () => {
  const s = await launch({provider: 'freecad'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio ready');
    await s.evaluate(`window.studio.bus.emit('new-instance')`);
    await s.wait(`document.querySelector('[aria-label="Search adaptors"]')`, 'adaptor discovery');
    await field(s, 'Search adaptors', 'rigid assembly of modelled parts at named mounts');
    await s.wait(`document.querySelector('[role=listbox]')?.textContent.includes('FreeCAD')`, 'FreeCAD discovered by the reviewed phrase', 5000);
  } finally {await s.close();}
});

test('nested sourced assembly shows no false host diagnostic for its $artifact bindings', {
  timeout: 120000,
}, async () => {
  const workflow = JSON.parse(await readFile(WORKFLOW, 'utf8'));
  const s = await launch({provider: 'freecad'});
  try {
    await openSourcedAssembly(s, workflow);
    await s.evaluate(`(() => {window.__validations=[];const post=window.studio.api.post.bind(window.studio.api);
      window.studio.api.post=async(...args)=>{const r=await post(...args);if(args[0]==='/api/validate')window.__validations.push(r);return r;};})()`);
    await s.evaluate('window.studio.windows.active().window.editor.focus()');
    await s.key('End', {modifiers: 2});
    await s.type('\n');
    await s.wait('window.__validations.length>0', 'background validation ran', 30000);
    await s.wait(`!document.querySelector('.wb-diagnostic-state').textContent.startsWith('Editing')`, 'validation settled');
    assert.equal(await s.evaluate(`document.querySelector('.wb-diagnostic-state').textContent`), '0 diagnostics');
  } finally {await s.close();}
});

test('assembly part forms still reject out-of-range constructor options and invalid mount axes', {
  timeout: 120000,
}, async () => {
  const workflow = JSON.parse(await readFile(WORKFLOW, 'utf8'));
  const s = await launch({provider: 'freecad'});
  try {
    await openSourcedAssembly(s, workflow);
    const source = () => s.evaluate('window.studio.windows.active().window.editor.getValue()');
    const initial = await source();
    await add(s, 'document:parts', 'parts');
    await setIncluded(s, 'Include parts[0].options', true);
    await setIncluded(s, 'Include parts[0].options.length', true);
    await field(s, 'parts[0].options.length', '0');
    await button(s, 'Add operation');
    await s.wait(`document.querySelector('.operation-error')?.textContent.includes('Must be at least 0.01')`, 'constructor option lower bound', 8000);
    assert.equal(await source(), initial);
    await button(s, 'Cancel');
    await add(s, 'document:parts', 'parts');
    await field(s, 'parts[0] value kind', '2');
    await field(s, 'parts[0].id', 'bracket');
    await field(s, 'parts[0].source', '/replace/with/bracket/model.FCStd');
    await field(s, 'parts[0].mounts', '{"top":{"z":"up"}}');
    await button(s, 'Add operation');
    await s.wait(`document.querySelector('.operation-error')?.textContent.includes('/0/mounts/top/z')`, 'sourced mount axis enumeration', 8000);
    assert.equal(await source(), initial);
  } finally {await s.close();}
});

test('packaged FreeCAD assembly Help explains modelled parts at named mounts', {
  timeout: 60000,
}, async () => {
  const index = JSON.parse(await readFile(new URL('../../src/schemaxis/studio_ui/help/index.json', import.meta.url), 'utf8'));
  const entry = index.entries.find((item) => item.source === 'docs/freecad-assemblies.md');
  assert.ok(entry, 'assembly guide is packaged');
  const page = await readFile(new URL(`../../src/schemaxis/studio_ui/help/${entry.id}.json`, import.meta.url), 'utf8');
  assert.match(page, /Assembling modelled parts at named mounts/);
  assert.match(page, /Frame convention/);
});
