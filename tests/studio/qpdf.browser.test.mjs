import assert from 'node:assert/strict';
import {copyFile, mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

const FIXTURES = new URL('../../examples/schemaxis/fixtures/qpdf/', import.meta.url);
const ROTATIONS = [0, 90, 180, 270];

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
async function add(s, id, query) {
  await s.clickSelector('[data-add="all"]');
  await field(s, 'Search Add anything…', query);
  await s.wait(`document.querySelector('[data-library="${id}"]')`, 'matching Add control');
  await s.clickSelector(`[data-library="${id}"]`);
  await s.wait('document.querySelector(".operation-form")', 'typed authoring form');
}
// The rotation control is a typed enumeration whose options are listed by position.
async function rotation(s, index, degrees) {
  await revealAndClick(s, `Include pages[${index}].rotate`);
  await field(s, `pages[${index}].rotate`, String(ROTATIONS.indexOf(degrees)));
}
async function page(s, index, source, number, degrees) {
  await field(s, `pages[${index}].source`, source);
  await field(s, `pages[${index}].page`, String(number));
  if (degrees !== undefined) await rotation(s, index, degrees);
}
async function fieldHelp(s, label) {
  await revealAndClick(s, `Help for ${label}`);
  return s.evaluate(`document.querySelector(${JSON.stringify('[aria-label="Help for '+label+'"]')})
    .closest('.operation-field').querySelector('.operation-field-help').textContent`);
}
const validate = (s, document) => s.evaluate(`window.studio.api.post('/api/validate',
  {provider:'qpdf',source:${JSON.stringify(JSON.stringify(document))}})`);

test('QPDF Studio discovers page assembly and authors typed sources and page segments with validation, cancellation and undo', {timeout:180000}, async()=>{
  // The fixtures are only named in authored JSON; no PDF is opened or executed by this test.
  const scratch = await mkdtemp(join(tmpdir(), 'qpdf-studio-sources-'));
  const cover = fileURLToPath(new URL('cover.pdf', FIXTURES));
  const report = fileURLToPath(new URL('report.pdf', FIXTURES));
  const appendix = join(scratch, 'appendix.pdf');
  await copyFile(report, appendix);
  const document = JSON.parse(await readFile(new URL('../../examples/schemaxis/qpdf-assemble.json', import.meta.url), 'utf8'));
  document.sources[0].path = cover;
  document.sources[1].path = report;
  const s = await launch({provider: 'qpdf'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio ready');
    await s.evaluate(`window.studio.bus.emit('new-instance')`);
    await s.wait(`document.querySelector('[aria-label="Search adaptors"]')`, 'adaptor discovery');
    // The listbox renders synchronously on input, so each wait observes the phrase just typed.
    for (const intent of ['merge PDF', 'reorder PDF pages', 'combine PDFs', 'extract pages']) {
      await field(s, 'Search adaptors', intent);
      await s.wait(`document.querySelector('[role=listbox]')?.textContent.includes('QPDF')`, `QPDF discovered by user intent "${intent}"`);
    }
    // QPDF does not sanitise or redact, so that intent must not be offered QPDF.
    await field(s, 'Search adaptors', 'sanitize redact encrypt PDF');
    await s.wait(`!document.querySelector('[role=listbox]')?.textContent.includes('QPDF')`, 'QPDF not offered for sanitising intent');
    await button(s, 'Cancel');
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',
      {action:'new',provider:'qpdf',name:'Handout packet',document:${JSON.stringify(document)}});
      await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")', 'Workbench ready');
    const source = () => s.evaluate('window.studio.windows.active().window.editor.getValue()');
    const initial = await source();
    assert.deepEqual(JSON.parse(initial), document);
    const baseline = await validate(s, document);
    assert.equal(baseline.valid, true);
    assert.deepEqual(baseline.diagnostics, []);

    // Operation discovery by intent, packaged operation Help, and Cancel preserving the draft.
    await add(s, 'operation:assemble', 'merge PDF');
    await s.evaluate(`(() => {const d=[...document.querySelectorAll('.operation-form details')]
      .find(d=>d.querySelector('summary')?.textContent==='? Operation reference');
      if(!d)throw Error('Missing operation Help');for(let p=d;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;})()`);
    await s.wait(`document.querySelector('.operation-reference')?.textContent.includes('Native binding:')`, 'packaged QPDF operation Help');
    const help = await s.evaluate('document.querySelector(".operation-reference").textContent');
    assert.match(help, /qpdf --empty --pages/);
    assert.match(help, /repeat/i);
    assert.match(help, /clockwise/i);
    assert.match(help, /MuPDF/);
    await button(s, 'Cancel');
    assert.equal(await source(), initial);
    // The other advertised and working intents reach the same Add operation.
    for (const intent of ['reorder PDF pages', 'combine PDFs', 'extract pages']) {
      await add(s, 'operation:assemble', intent);
      assert.match(await s.evaluate('document.querySelector(".operation-form").textContent'), /new PDF from selected pages/);
      await button(s, 'Cancel');
      assert.equal(await source(), initial);
    }

    // Page segments: required data rejected by the form, with the draft untouched.
    await add(s, 'document:pages', 'pages');
    assert.match(await s.evaluate('document.querySelector(".operation-form").textContent'), /output page|page/i);
    const sourceHelp = await fieldHelp(s, 'pages[0].source');
    assert.match(sourceHelp, /declared in sources/);
    const pageHelp = await fieldHelp(s, 'pages[0].page');
    assert.match(pageHelp, /one-based physical position/);
    assert.match(pageHelp, /not the printed page label/);
    const rotateHelp = await fieldHelp(s, 'pages[0].rotate');
    assert.match(rotateHelp, /clockwise/);
    assert.match(rotateHelp, /effective rotation/);
    await button(s, 'Remove', '.operation-form');
    await button(s, 'Add operation');
    await s.wait(`document.querySelector('.operation-error')?.textContent.includes('Expected at least 1 item')`, 'required page list validation');
    assert.equal(await s.evaluate('!!document.querySelector(".operation-form")'), true);
    assert.equal(await source(), initial);
    await button(s, 'Add pages item', '.operation-form');
    await field(s, 'pages[0].source', 'cover');
    await field(s, 'pages[0].page', '0');
    await button(s, 'Add operation');
    await s.wait(`document.querySelector('.operation-error')?.textContent.includes('Must be at least 1')`, 'page number lower bound');
    assert.match(await s.evaluate('document.querySelector(".operation-error").textContent'), /\/0\/page/);
    await field(s, 'pages[0].page', '501');
    await button(s, 'Add operation');
    await s.wait(`document.querySelector('.operation-error')?.textContent.includes('Must be at most 500')`, 'page number upper bound');
    assert.equal(await s.evaluate('!!document.querySelector(".operation-form")'), true);
    assert.equal(await source(), initial);
    // Abandon the half-authored list: Cancel must leave the original draft byte for byte.
    await field(s, 'pages[0].page', '2');
    await button(s, 'Cancel');
    assert.equal(await source(), initial);

    // Typed sources: a third PDF is declared, order and names stay user-controlled.
    await add(s, 'document:sources', 'sources');
    assert.match(await fieldHelp(s, 'sources[0].name'), /lowercase letters, digits or hyphens/);
    assert.match(await fieldHelp(s, 'sources[0].path'), /absolute local path/);
    await field(s, 'sources[0].name', 'cover');
    await field(s, 'sources[0].path', cover);
    await button(s, 'Add sources item', '.operation-form');
    await field(s, 'sources[1].name', 'report');
    await field(s, 'sources[1].path', report);
    await button(s, 'Add sources item', '.operation-form');
    await field(s, 'sources[2].name', 'appendix');
    await field(s, 'sources[2].path', appendix);
    await button(s, 'Add operation');
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).sources.length===3', 'typed sources inserted');
    const withSources = JSON.parse(await source());
    assert.deepEqual(withSources.sources, [
      {name: 'cover', path: cover},
      {name: 'report', path: report},
      {name: 'appendix', path: appendix},
    ]);
    assert.deepEqual(withSources, {...document, sources: withSources.sources});
    // A declared source that supplies no page is refused by the authoritative host validator.
    const unused = await validate(s, withSources);
    assert.equal(unused.valid, false);
    assert.equal(unused.diagnostics.length, 1);
    assert.equal(unused.diagnostics[0].pointer, '/sources');
    assert.equal(unused.diagnostics[0].code, 'INVALID_PDF_SOURCES');
    assert.match(unused.diagnostics[0].message, /every declared source must supply at least one page/);
    assert.deepEqual(JSON.parse(await source()), withSources);

    // Ordered pages with repeats and independent rotations, authored through the typed controls.
    const afterSources = await source();
    await add(s, 'document:pages', 'pages');
    // The form starts from one blank page segment; replace it with the intended sequence.
    await button(s, 'Remove', '.operation-form');
    const wanted = [
      ['report', 3], ['report', 3, 90], ['report', 3, 270], ['cover', 1],
      ['report', 1, 180], ['appendix', 1], ['cover', 1, 90],
    ];
    for (let index = 0; index < wanted.length; index += 1) {
      await button(s, 'Add pages item', '.operation-form');
      await page(s, index, ...wanted[index]);
    }
    await button(s, 'Add operation');
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).pages.length===7', 'typed page segments inserted');
    const changed = JSON.parse(await source());
    assert.deepEqual(changed.pages, [
      {source: 'report', page: 3},
      {source: 'report', page: 3, rotate: 90},
      {source: 'report', page: 3, rotate: 270},
      {source: 'cover', page: 1},
      {source: 'report', page: 1, rotate: 180},
      {source: 'appendix', page: 1},
      {source: 'cover', page: 1, rotate: 90},
    ]);
    assert.deepEqual(changed, {...withSources, pages: changed.pages});
    const checked = await validate(s, changed);
    assert.equal(checked.valid, true);
    assert.deepEqual(checked.diagnostics, []);

    // Host validation stays authoritative for relationships and patterns the forms cannot see.
    const undeclared = structuredClone(changed);
    undeclared.pages[5].source = 'annex';
    const unknown = await validate(s, undeclared);
    assert.equal(unknown.valid, false);
    assert.ok(unknown.diagnostics.some(item => item.pointer === '/pages/5/source' && item.code === 'INVALID_PDF_PAGES'),
      JSON.stringify(unknown.diagnostics));
    const shouting = structuredClone(changed);
    shouting.sources[0].name = 'Cover';
    const named = await validate(s, shouting);
    assert.equal(named.valid, false);
    assert.equal(named.diagnostics.length, 1);
    assert.equal(named.diagnostics[0].pointer, '/sources/0/name');
    assert.equal(named.diagnostics[0].code, 'INVALID_PDF_SOURCE_NAME');
    const relative = structuredClone(changed);
    relative.sources[2].path = 'appendix.pdf';
    const located = await validate(s, relative);
    assert.equal(located.valid, false);
    assert.equal(located.diagnostics.length, 1);
    assert.equal(located.diagnostics[0].pointer, '/sources/2/path');
    assert.equal(located.diagnostics[0].code, 'INVALID_PDF_SOURCE');
    // Validation never mutates the draft.
    assert.deepEqual(JSON.parse(await source()), changed);

    // A later abandoned edit changes nothing; then one Undo per insertion restores each earlier draft.
    const edited = await source();
    await add(s, 'document:pages', 'pages');
    await field(s, 'pages[0].source', 'cover');
    await field(s, 'pages[0].page', '9');
    await button(s, 'Cancel');
    assert.equal(await source(), edited);
    await s.evaluate('window.studio.windows.active().window.editor.focus()');
    await s.key('z', {modifiers: 2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).pages.length===5', 'atomic page-list undo');
    assert.equal(await source(), afterSources);
    await s.key('z', {modifiers: 2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).sources.length===2', 'atomic source-list undo');
    assert.equal(await source(), initial);
    assert.deepEqual(s.exceptions, []);
  } finally {
    await s.close();
    await rm(scratch, {recursive: true, force: true});
  }
});
