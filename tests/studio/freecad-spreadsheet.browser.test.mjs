import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

async function field(s,label,value) {
  await s.evaluate(`(() => {const e=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});
    if(!e || e.disabled)throw Error('Missing field '+${JSON.stringify(label)});
    for(let p=e.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;
    e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}

test('FreeCAD engineering-table starter and complete document form retain typed alias intent',{timeout:120000},async()=>{
  const s=await launch({provider:'freecad'});
  try {
    await s.wait('window.studio?.store.get().server','Studio ready');
    const library=await s.evaluate(`window.studio.api.get('/api/studio/adaptor',{id:'freecad'})`);
    const template=library.templates.find(t=>t.id==='spreadsheet-enclosure');assert.ok(template?.document);
    assert.equal(template.document.spreadsheet.inputs.width.unit,'cm');assert.equal(template.document.spreadsheet.inputs.depth.unit,'in');
    const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(template.document))}})`);
    assert.equal(checked.valid,true,JSON.stringify(checked.diagnostics));
    const original={version:'schemaxis.freecad/1',nodes:[{id:'stock',filter:'box',options:{length:20,width:10,height:5}}],output:'stock'};
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',{action:'new',provider:'freecad',name:'Engineering table',document:${JSON.stringify(original)}});await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")','Workbench ready');
    await s.clickSelector('[data-add="all"]');await field(s,'Search Add anything…','spreadsheet');
    await s.wait(`document.querySelector('[data-library="document:spreadsheet"]')`,'Table discovery');
    await s.clickSelector('[data-library="document:spreadsheet"]');await s.wait('document.querySelector(".operation-form")','Table form');
    const inputs={height:{value:.5,minimum:.2,maximum:1,unit:'cm'}};
    const formulas={total:{terms:{height:2},offset:{value:1,unit:'mm'}}};
    await field(s,'spreadsheet.inputs',JSON.stringify(inputs));
    await s.evaluate(`(() => {const e=document.querySelector('[aria-label="Include spreadsheet.formulas"]');e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
    await field(s,'spreadsheet.formulas',JSON.stringify(formulas));
    const text=await s.evaluate('document.querySelector(".operation-form").textContent');
    assert.match(text,/acyclic|cycle/i);assert.match(text,/unit/i);
    await s.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent.trim()==='Add operation').click()`);
    await s.wait('!!JSON.parse(window.studio.windows.active().window.editor.getValue()).spreadsheet','Table inserted');
    const authored=JSON.parse(await s.evaluate('window.studio.windows.active().window.editor.getValue()'));
    assert.deepEqual(authored.nodes,original.nodes);assert.deepEqual(authored.spreadsheet,{inputs,formulas});
    const bound=structuredClone(authored);delete bound.nodes[0].options.height;bound.nodes[0].drive={height:{terms:{total:1}}};
    const valid=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(bound))}})`);
    assert.equal(valid.valid,true,JSON.stringify(valid.diagnostics));
    await s.evaluate('window.studio.windows.active().window.editor.focus()');await s.key('z',{modifiers:2});
    await s.wait('!JSON.parse(window.studio.windows.active().window.editor.getValue()).spreadsheet','Atomic table undo');
    assert.deepEqual(JSON.parse(await s.evaluate('window.studio.windows.active().window.editor.getValue()')),original);
    assert.deepEqual(s.exceptions,[]);
  } finally {await s.close();}
});
