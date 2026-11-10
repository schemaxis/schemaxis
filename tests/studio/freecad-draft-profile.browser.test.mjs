import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

async function field(s,label,value) {
  await s.evaluate(`(() => {const e=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});
    if(!e || e.disabled)throw Error('Missing field '+${JSON.stringify(label)});
    for(let p=e.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;
    if(e.type==='checkbox')e.checked=${JSON.stringify(value)};else e.value=${JSON.stringify(value)};
    if(e.tagName==='SELECT'){const option=Array.from(e.options).find(o=>o.textContent===${JSON.stringify(JSON.stringify(value))});if(option)e.value=option.value;}
    e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}

test('Draft polygon starter and nested vertex form preserve frames and atomic undo',{timeout:120000},async()=>{
  const s=await launch({provider:'freecad'});
  try {
    await s.wait('window.studio?.store.get().server','Studio ready');
    const library=await s.evaluate(`window.studio.api.get('/api/studio/adaptor',{id:'freecad'})`);
    const template=library.templates.find(t=>t.id==='draft-profile-bracket');assert.ok(template?.document);
    assert.equal(template.document.nodes[0].filter,'draftProfile');
    const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(template.document))}})`);
    assert.equal(checked.valid,true,JSON.stringify(checked.diagnostics));
    const original={version:'schemaxis.freecad/1',nodes:[{id:'stock',filter:'box'}],output:'stock'};
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',{action:'new',provider:'freecad',name:'Draft polygon',document:${JSON.stringify(original)}});await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")','Workbench ready');
    await s.clickSelector('[data-add="all"]');await field(s,'Search Add anything…','Draft polygon');
    await s.wait(`document.querySelector('[data-library="operation:draftProfile"]')`,'Draft discovery');
    await s.evaluate(`document.querySelector('[data-library="operation:draftProfile"]').scrollIntoView({block:'center'})`);
    await s.clickSelector('[data-library="operation:draftProfile"]');await s.wait('document.querySelector(".operation-form")','Draft form');
    await field(s,'draftProfile.id','outline');
    const points=[[0,0],[10,0],[0,6]];
    for(const [i,p] of points.entries())for(const [j,v] of p.entries())await field(s,`draftProfile.options.points[${i}][${j}]`,String(v));
    for(const option of ['plane','origin','angle'])await field(s,`Include draftProfile.options.${option}`,true);
    await field(s,'draftProfile.options.plane','XZ');await field(s,'draftProfile.options.angle','17');
    for(const [i,v] of [20,-10,5].entries())await field(s,`draftProfile.options.origin[${i}]`,String(v));
    const help=await s.evaluate('document.querySelector(".operation-form").textContent');assert.match(help,/millimetres/);assert.match(help,/boundary/);
    await s.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent.trim()==='Add operation').click()`);
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===2','Draft inserted');
    const authored=JSON.parse(await s.evaluate('window.studio.windows.active().window.editor.getValue()'));
    assert.deepEqual(authored.nodes[0],original.nodes[0]);const node=authored.nodes[1];assert.equal(node.filter,'draftProfile');
    assert.deepEqual(node.options,{points,plane:'XZ',origin:[20,-10,5],angle:17});
    const valid=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(authored))}})`);
    assert.equal(valid.valid,true,JSON.stringify(valid.diagnostics));
    await s.evaluate('window.studio.windows.active().window.editor.focus()');await s.key('z',{modifiers:2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===1','Atomic undo');
    assert.deepEqual(JSON.parse(await s.evaluate('window.studio.windows.active().window.editor.getValue()')),original);assert.deepEqual(s.exceptions,[]);
  } finally {await s.close();}
});
