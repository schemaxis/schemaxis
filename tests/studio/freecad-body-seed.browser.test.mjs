import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

async function field(s,label,value) {
  await s.evaluate(`(() => {const e=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});
    if(!e||e.disabled)throw Error('Missing field '+${JSON.stringify(label)});
    e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));
    e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}

test('Imported Body starter and seed form preserve explicit ownership and atomic undo',{timeout:120000},async()=>{
  const s=await launch({provider:'freecad'});
  try {
    await s.wait('window.studio?.store.get().server','Studio ready');
    const library=await s.evaluate(`window.studio.api.get('/api/studio/adaptor',{id:'freecad'})`);
    const starter=library.templates.find(t=>t.id==='body-stock');assert.ok(starter?.document);
    assert.equal(starter.document.nodes.find(n=>n.filter==='bodySeed').inputs.body,'part');
    const filled=structuredClone(starter.document);
    filled.nodes[0].options.file=starter.fields.meshFile.default;
    filled.nodes.find(n=>n.id==='bore').options.radius=starter.fields.boreRadius.default;
    const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(filled))}})`);
    assert.equal(checked.valid,true,JSON.stringify(checked.diagnostics));
    const snippet=library.snippets.find(t=>t.id==='add-body-seed');assert.ok(snippet?.baseDocument);
    // Start from a complete valid document. The snippet's baseDocument is a
    // construction context to which its seed insert is applied atomically.
    const original={...filled,nodes:[...filled.nodes,{id:'nextPart',filter:'body'}]};
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',
      {action:'new',provider:'freecad',name:'Machine imported stock',document:${JSON.stringify(original)}});
      await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")','Workbench ready');
    await s.clickSelector('[data-add="all"]');await field(s,'Search Add anything…','bodySeed');
    await s.wait(`document.querySelector('[data-library="operation:bodySeed"]')`,'Seed discovery');
    await s.evaluate(`document.querySelector('[data-library="operation:bodySeed"]').scrollIntoView({block:'center'})`);
    await s.clickSelector('[data-library="operation:bodySeed"]');
    await s.wait('document.querySelector(".operation-form")','Seed form');
    await field(s,'bodySeed.id','nextSeed');await field(s,'bodySeed.inputs.body','nextPart');
    await field(s,'bodySeed.inputs.source','casting');
    const help=await s.evaluate('document.querySelector(".operation-form").textContent');
    assert.match(help,/first|empty/i);assert.match(help,/source|solid/i);
    await s.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent.trim()==='Add operation').click()`);
    await s.wait(`JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===${original.nodes.length+1}`,'Seed inserted');
    const inserted=JSON.parse(await s.evaluate('window.studio.windows.active().window.editor.getValue()'));
    assert.deepEqual(inserted.nodes.slice(0,original.nodes.length),original.nodes);
    const seed=inserted.nodes.at(-1);
    assert.equal(seed.id,'nextSeed');assert.equal(seed.filter,'bodySeed');
    assert.deepEqual(seed.inputs,{body:'nextPart',source:'casting'});
    if('options' in seed)assert.deepEqual(seed.options,{});
    const candidate={...inserted,output:'nextSeed'};
    const valid=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(candidate))}})`);
    assert.equal(valid.valid,true,JSON.stringify(valid.diagnostics));
    await s.evaluate('window.studio.windows.active().window.editor.focus()');await s.key('z',{modifiers:2});
    await s.wait(`JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===${original.nodes.length}`,'Atomic undo');
    assert.deepEqual(JSON.parse(await s.evaluate('window.studio.windows.active().window.editor.getValue()')),original);
    assert.deepEqual(s.exceptions,[]);
  } finally {await s.close();}
});
