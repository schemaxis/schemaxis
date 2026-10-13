import assert from 'node:assert/strict';
import {test} from 'node:test';
import {execFileSync} from 'node:child_process';
import {join} from 'node:path';
import {launch} from './harness.mjs';

async function button(session, scope, text) {
  await session.evaluate(`[...document.querySelectorAll(${JSON.stringify(scope + ' button')})].find(b=>b.textContent.trim()===${JSON.stringify(text)}).click()`);
}
async function add(session, group, title, operation) {
  await session.clickSelector(`[data-add=${group}]`);
  await session.evaluate(`(() => {const e=document.querySelector('[aria-label="Search ${title}"]');e.value=${JSON.stringify(operation)};e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await session.clickSelector(`[data-library="operation:${operation}"]`);
  await session.wait('document.querySelector(".operation-form")', 'Add form');
}
const source = 'JSON.parse(window.studio.windows.active().window.editor.getValue())';
async function undo(session) {
  await session.evaluate('window.studio.windows.active().window.editor.focus()');
  await session.key('z',{modifiers:2});
}
async function select(session,index) {
  const selector=`.wb-comprehension [data-pointer="/nodes/${index}"]`;
  await session.wait(`document.querySelector(${JSON.stringify(selector)})`,'pipeline row');
  await session.clickSelector(selector);
}

test('filename-only foam, native block selection, pipeline browsing, duplicate, dependent delete and undo',
  {timeout:180000,skip:!process.env.SCHEMAXIS_LIVE_PARAVIEW}, async () => {
  const session=await launch({provider:'paraview'});
  try {
    const file=join(session.workspace,'fixture/case.foam');
    execFileSync('python3',['-c',`import json,sys\nfrom pathlib import Path\nsys.path.insert(0,'tools')\nfrom benchmark_workflows import make_foam\ncase=next(c for c in json.loads(Path('examples/benchmarks/cases.json').read_text())['rounds']['initial'] if c['family']=='cfd')\nmake_foam(case,Path(sys.argv[1]))`,join(session.workspace,'fixture')]);
    await session.wait('window.studio?.store.get().server','Studio');
    await session.evaluate(`(async()=>{const ctx=window.studio;const record=await ctx.api.post('/api/documents',
      {action:'new',provider:'paraview',name:'Normal CFD case',document:{version:'schemaxis/1',nodes:[],scenes:[]}});
      await ctx.refresh();ctx.windows.open('workbench',{document:record.id});
      const request=ctx.api.request.bind(ctx.api);ctx.api.request=(path,...args)=>path==='/api/input-file'
        ? Promise.resolve({status:'selected',path:${JSON.stringify(file)}}):request(path,...args);
    })()`);
    await session.wait('document.querySelector("[data-add=inputs]")','Add');
    await add(session,'inputs','Add Input','foam');
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="foam.id"]').value`),'foam1');
    await session.evaluate(`document.querySelector('[aria-label="Browse for foam.options.file"]').click()`);
    await session.wait(`document.querySelector('[aria-label="foam.options.file"]').value===${JSON.stringify(file)}`,'desktop choice');
    await button(session,'.dialog-footer','Add operation');
    try {await session.wait(`${source}.nodes.length===1`,'prepared foam',90000);}
    catch (error) {throw Error(await session.evaluate(`document.querySelector('.operation-error')?.textContent`) || error.message);}
    const reader=await session.evaluate(source);
    assert.equal(reader.nodes[0].options.caseType,'Reconstructed Case');
    assert.ok(reader.nodes[0].options.regions.includes('patch/walls'));
    assert.equal(typeof reader.times[0],'number');
    await select(session,0);
    await add(session,'filters','Add Filter','extractBlock');
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="extractBlock.id"]').value`),'extractBlock1');
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="extractBlock.inputs.input"]').value`),'foam1');
    try {await session.wait(`document.querySelector('[aria-label="Extract walls"]')`,'native walls block',90000);}
    catch (error) {throw Error(await session.evaluate(`document.querySelector('.block-picker')?.textContent`) || error.message);}
    await button(session,'.pipeline-reference-control','Browse pipeline…');
    await session.wait('document.querySelector(".pipeline-picker-list")','pipeline chooser');
    assert.match(await session.evaluate(`document.querySelector('.pipeline-picker-list').textContent`),/foam1/);
    await button(session,'.dialog-backdrop:last-child .dialog-footer','Use selection');
    await session.evaluate(`document.querySelector('[aria-label="Extract walls"]').click()`);
    await session.screenshot('/tmp/schemaxis-native-block-picker.png');
    await button(session,'.dialog-footer','Add operation');
    await session.wait(`${source}.nodes.length===2`,'extract block inserted');
    assert.deepEqual((await session.evaluate(source)).nodes[1].options.selectors,['/Root/boundary/walls']);
    const validation=await session.evaluate(`window.studio.api.post('/api/validate',{provider:'paraview',source:window.studio.windows.active().window.editor.getValue()})`);
    assert.deepEqual(validation.diagnostics,[]);
    await select(session,1);
    await session.wait(`document.querySelector('[aria-label="/nodes/1/inputs/input"]')`,'input Properties');
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="/nodes/1/inputs/input"] option[value="extractBlock1"]')`),null);
    await button(session,'.wb-properties','Choose blocks…');
    await session.wait(`document.querySelector('[aria-label="Extract internalMesh"]')`,'existing filter block choices',90000);
    await session.evaluate(`document.querySelector('[aria-label="Extract internalMesh"]').click()`);
    await button(session,'.dialog-footer','Use selected blocks');
    await session.wait(`${source}.nodes[1].options.selectors.length===2`,'Properties block edit');
    await undo(session);await session.wait(`${source}.nodes[1].options.selectors.length===1`,'undo block edit');
    await select(session,1);
    await button(session,'.wb-comprehension','Duplicate');
    await session.wait(`${source}.nodes.length===3`,'copy');
    assert.equal((await session.evaluate(source)).nodes[2].id,'extractBlock1Copy1');
    await undo(session);await session.wait(`${source}.nodes.length===2`,'undo copy');
    await select(session,1);
    await button(session,'.wb-comprehension','Delete');
    await session.wait(`${source}.nodes.length===1`,'delete leaf');
    await undo(session);await session.wait(`${source}.nodes.length===2`,'undo delete');
    await select(session,0);
    await button(session,'.wb-comprehension','Delete');
    assert.match(await session.evaluate(`document.querySelector('.dialog-body').textContent`),/foam1, extractBlock1/);
    await button(session,'.dialog-footer','Cancel');
    assert.equal((await session.evaluate(source)).nodes.length,2);
    await button(session,'.wb-comprehension','Delete');await button(session,'.dialog-footer','Delete');
    await session.wait(`${source}.nodes.length===0`,'delete dependents');
    await undo(session);await session.wait(`${source}.nodes.length===2`,'undo dependents');
    assert.deepEqual(session.exceptions,[]);assert.deepEqual(session.consoleErrors,[]);
  } finally {await session.close();}
});
