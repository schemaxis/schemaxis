import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

const template = async (name) => JSON.parse(await readFile(new URL(`../../src/schemaxis/adaptors/gmsh/${name}`, import.meta.url), 'utf8'));

async function field(s, label, value) {
  await s.evaluate(`(() => {const e=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});
    if(!e || e.disabled)throw Error('Missing or disabled field '+${JSON.stringify(label)});
    e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));
    e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}
async function button(s, label, selector = '.operation-form') {
  await s.evaluate(`(() => {const b=[...document.querySelectorAll(${JSON.stringify(selector+' button')})]
    .find(b=>b.textContent.trim()===${JSON.stringify(label)});
    if(!b)throw Error('Missing button '+${JSON.stringify(label)});
    for(let p=b.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;b.click();})()`);
}
async function open(s, document, name) {
  await s.wait('window.studio?.store.get().server', 'Studio ready');
  await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',
    {action:'new',provider:'gmsh',name:${JSON.stringify(name)},document:${JSON.stringify(document)}});
    await c.refresh();c.windows.open('workbench',{document:r.id});window.openedDocument=r.id;})()`);
  await s.wait('document.querySelector("[data-add=all]")', 'Workbench ready');
}
/** Open a snippet category as a user does; newer layouts keep categories in a tray behind "Snippets & templates". */
async function openCategory(s, category) {
  const selector = `[data-category="${category}"]`;
  await s.wait(`document.querySelector('${selector}')`, `${category} snippet category`);
  const shown = `document.querySelector('${selector}').getBoundingClientRect().width>0`;
  if (!await s.evaluate(shown) && await s.evaluate(`!!document.querySelector('.library-more')`)) {
    await s.clickSelector('.library-more');
    await s.wait(shown, 'snippet categories shown');
  }
  await s.clickSelector(selector);
}
const validate = (s, document) => s.evaluate(`window.studio.api.post('/api/validate',
  {provider:'gmsh',source:${JSON.stringify(JSON.stringify(document))}})`);

test('Gmsh cylinder groups are authored through nested forms with Help, validation, cancellation and undo', {timeout: 180000}, async () => {
  const sleeve = await template('templates/named-sleeve-mesh.json');
  const document = structuredClone(sleeve);
  delete document.nodes[1].options.cylinderGroups;
  const s = await launch({provider: 'gmsh'});
  try {
    await open(s, document, 'Sleeve without wall names');
    const source = () => s.evaluate('window.studio.windows.active().window.editor.getValue()');
    const initial = await source();

    await s.clickSelector('[data-add="all"]');
    await field(s, 'Search Add anything…', 'tetrahedral');
    await s.wait('document.querySelector(\'[data-library="operation:tetrahedral"]\')', 'tetrahedral Add control');
    await s.clickSelector('[data-library="operation:tetrahedral"]');
    await s.wait('document.querySelector(".operation-form")', 'typed form');
    assert.match(await s.evaluate('document.querySelector(".operation-form").textContent'), /cylindrical wall groups/);
    await button(s, 'Add tetrahedral.options.cylinderGroups item');
    for (const name of ['name', 'axis', 'centre', 'radius', 'side', 'tolerance', 'areaTolerance']) {
      await s.wait(`document.querySelector('[aria-label="Help for tetrahedral.options.cylinderGroups[0].${name}"]')`, `Help control for ${name}`);
    }
    await s.evaluate('document.querySelector(\'[aria-label="Help for tetrahedral.options.cylinderGroups[0].side"]\').click()');
    const help = await s.evaluate('document.querySelector(".operation-form").textContent');
    assert.match(help, /material lies inside the radius/);
    assert.doesNotMatch(help, /Conceptual explanation needed/);
    await field(s, 'tetrahedral.options.cylinderGroups[0].name', 'abandoned');
    await button(s, 'Cancel', '.dialog-footer');
    assert.equal(await source(), initial, 'cancel leaves the document unchanged');

    const named = structuredClone(sleeve);
    const stale = structuredClone(sleeve);
    stale.nodes[0].options.innerRadius = 2.5;
    const rejected = await validate(s, stale);
    assert.equal(rejected.valid, false);
    assert.equal(rejected.diagnostics[0].code, 'INVALID_SELECTION');
    assert.equal(rejected.diagnostics[0].pointer, '/nodes/1/options/cylinderGroups/0');
    assert.deepEqual(rejected.diagnostics[0].observed.walls.map((w) => w.radius).sort(), [2.5, 4]);
    const accepted = await validate(s, named);
    assert.equal(accepted.valid, true);
    assert.deepEqual(accepted.diagnostics, []);
    const backwards = structuredClone(sleeve);
    backwards.nodes[1].options.cylinderGroups[0].side = 'sideways';
    assert.equal((await validate(s, backwards)).valid, false);
    const overlapping = structuredClone(sleeve);
    overlapping.nodes[1].options.cylinderGroups.push({...overlapping.nodes[1].options.cylinderGroups[0], name: 'twin'});
    const twin = await validate(s, overlapping);
    assert.equal(twin.valid, false);
    assert.equal(twin.diagnostics[0].pointer, '/nodes/1/options/cylinderGroups/2');

    await openCategory(s, 'groups');
    await s.wait('document.querySelector(\'[data-library="named-sleeve-starter"]\')', 'fully named sleeve snippet');
    await s.clickSelector('[data-library="named-sleeve-starter"]');
    await s.wait(`JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes[1].options.cylinderGroups?.length===2`, 'snippet inserted');
    assert.deepEqual(JSON.parse(await source()), sleeve);
    await s.evaluate('window.studio.windows.active().window.editor.focus()');
    await s.key('z', {modifiers: 2});
    await s.wait(`JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes[1].options.cylinderGroups===undefined`, 'atomic snippet undo');
    assert.equal(await source(), initial);
    assert.deepEqual(s.exceptions, []);
  } finally { await s.close(); }
});

test('Gmsh bore snippets keep required STEP and radius placeholders honest and validate when filled', {timeout: 180000}, async () => {
  const s = await launch({provider: 'gmsh'});
  try {
    await open(s, await template('templates/named-sleeve-mesh.json'), 'Starter');
    await openCategory(s, 'geometry');
    await s.wait('document.querySelector(\'[data-library="bore-step-starter"]\')', 'bore STEP snippet');
    await s.evaluate('document.querySelector(\'[data-library="bore-step-starter"]\').click()');
    const popover = '.sx-fill-popover:not([hidden])';
    const values = {'STEP solid': '/data/plate.step', 'Bore radius (mm)': '3.5'};
    for (let count = 0; count < 4; count++) {
      await s.wait(`document.querySelector('${popover} .sx-fill-heading strong')`, 'snippet field');
      const label = await s.evaluate(`document.querySelector('${popover} .sx-fill-heading strong').textContent`);
      assert.ok(Object.hasOwn(values, label), `Unexpected fill field: ${label}`);
      await s.evaluate(`(()=>{const e=document.querySelector('${popover} [aria-label="Value"]');
        e.value=${JSON.stringify(values[label])};e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
      await s.wait(`document.querySelector('${popover} .button.primary:not(:disabled)')`, 'valid value');
      await s.clickSelector(`${popover} .button.primary`);
      await new Promise((resolve) => setTimeout(resolve, 400));
      if (!await s.evaluate(`!!document.querySelector('${popover} .sx-fill-heading strong')`)) break;
    }
    const text = await s.evaluate('window.studio.windows.active().window.editor.getValue()');
    const authored = JSON.parse(text);
    assert.equal(authored.nodes[0].options.file, '/data/plate.step');
    assert.deepEqual(authored.nodes[1].options.cylinderGroups, [{name: 'bore', axis: 'z', centre: [0, 0, 0], radius: 3.5, side: 'inner'}]);
    const checked = await validate(s, authored);
    assert.equal(checked.valid, true);
    assert.deepEqual(s.exceptions, []);
  } finally { await s.close(); }
});

test('Gmsh sleeve runs natively from Studio and its summary text shows names, tags, sides and chord deviation', {timeout: 300000}, async () => {
  const s = await launch({provider: 'gmsh'});
  try {
    await open(s, await template('templates/named-sleeve-mesh.json'), 'Native sleeve');
    assert.ok(JSON.parse(await s.evaluate(`fetch('/api/state'+location.search).then(r=>r.text())`)).configured.includes('gmsh'), 'configure the native Gmsh runtime');
    const state = () => s.evaluate(`fetch('/api/state'+location.search).then(r=>r.text())`).then(JSON.parse);
    const record = (await state()).documents.find((d) => d.name === 'Native sleeve');
    const job = (await s.evaluate(`window.studio.api.post('/api/preview',{document:${JSON.stringify(record.id)},revision:${record.revision}})`)).job;
    let result;
    for (let attempt = 0; attempt < 120; attempt++) {
      result = JSON.parse(await s.evaluate(`fetch('/api/jobs/${job}'+location.search).then(r=>r.text())`));
      if (['succeeded', 'failed'].includes(result.status)) break;
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    assert.equal(result.status, 'succeeded', JSON.stringify(result));
    const summaryFile = result.result.artifacts.find((a) => a.kind === 'text').file;
    const text = await s.evaluate(`fetch('/api/file'+location.search+'&path='+encodeURIComponent(${JSON.stringify(summaryFile)})).then(r=>r.text())`);
    const summary = JSON.parse(text);
    assert.deepEqual(summary.groups.filter((g) => g.dimension === 2).map((g) => [g.tag, g.name]), [[3, 'start'], [4, 'end'], [5, 'bore'], [6, 'outer']]);
    assert.deepEqual(summary.cylinderChecks.map((c) => c.side), ['inner', 'outer']);
    assert.ok(summary.cylinderChecks.every((c) => c.maximumChordDeviation > 0 && c.maximumChordDeviation < 0.1));
    assert.ok(Math.abs(summary.cylinderChecks[0].cadArea - 32 * Math.PI) < 1e-8);
    assert.ok(summary.cadSurfaces.surfaces.some((x) => x.type === 'cylinder' && x.side === 'inner' && x.radius === 2));
    assert.deepEqual(s.exceptions, []);
  } finally { await s.close(); }
});
