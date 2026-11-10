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

test('FreeCAD STL starter and full Mesh form preserve units winding frame and atomic undo',{timeout:120000},async()=>{
  const s=await launch({provider:'freecad'});
  try {
    await s.wait('window.studio?.store.get().server','Studio ready');
    const library=await s.evaluate(`window.studio.api.get('/api/studio/adaptor',{id:'freecad'})`);
    const template=library.templates.find(t=>t.id==='mesh-bracket');assert.ok(template?.document);
    assert.equal(template.document.nodes[0].filter,'importMesh');assert.equal(template.fields.meshFile.type,'path');
    const starter=structuredClone(template.document);starter.nodes[0].options.file=template.fields.meshFile.default;
    const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(starter))}})`);
    assert.equal(checked.valid,true,JSON.stringify(checked.diagnostics));
    const original={version:'schemaxis.freecad/1',nodes:[{id:'stock',filter:'box'}],output:'stock'};
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',{action:'new',provider:'freecad',name:'Mesh preparation',document:${JSON.stringify(original)}});await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")','Workbench ready');
    await s.clickSelector('[data-add="all"]');await field(s,'Search Add anything…','STL to solid');
    await s.wait(`document.querySelector('[data-library="operation:importMesh"]')`,'Mesh discovery');
    await s.evaluate(`document.querySelector('[data-library="operation:importMesh"]').scrollIntoView({block:'center'})`);
    const hit=await s.evaluate(`(() => {const e=document.querySelector('[data-library="operation:importMesh"]');const r=e.getBoundingClientRect();const target=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {rect:[r.x,r.y,r.width,r.height],hit:e.contains(target),target:target?.outerHTML?.slice(0,300)};})()`);assert.equal(hit.hit,true,JSON.stringify(hit));
    await s.evaluate(`(() => {window.__meshFaults=[];const original=window.studio.notify.error;window.studio.notify.error=(error,options)=>{window.__meshFaults.push({message:error?.message,stack:error?.stack,options});return original(error,options);};})()`);
    await s.clickSelector('[data-library="operation:importMesh"]');try {await s.wait('document.querySelector(".operation-form")','Mesh form');} catch(error) {throw Error(error.message+'\n'+JSON.stringify(await s.evaluate('window.__meshFaults'))+'\n'+JSON.stringify(s.exceptions));}
    await field(s,'importMesh.id','casting');await field(s,'importMesh.options.file','examples/schemaxis/freecad-mesh-cavity.stl');
    for(const option of ['reverseWinding','refine','orientation','placement'])await field(s,`Include importMesh.options.${option}`,true);
    await field(s,'importMesh.options.units','cm');await field(s,'importMesh.options.reverseWinding',true);await field(s,'importMesh.options.refine',true);
    await field(s,'importMesh.options.orientation.z','+Y');
    await field(s,'Include importMesh.options.orientation.x',true);await field(s,'importMesh.options.orientation.x','-X');
    for(const [i,value] of [45,-20,13].entries())await field(s,`importMesh.options.placement.position[${i}]`,String(value));
    await field(s,'importMesh.options.placement.clocking','31');
    const help=await s.evaluate('document.querySelector(".operation-form").textContent');assert.match(help,/STL/);assert.match(help,/unit/i);
    await s.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent.trim()==='Add operation').click()`);
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===2','Mesh inserted');
    const authored=JSON.parse(await s.evaluate('window.studio.windows.active().window.editor.getValue()'));
    assert.deepEqual(authored.nodes[0],original.nodes[0]);const mesh=authored.nodes[1];assert.equal(mesh.filter,'importMesh');
    assert.equal(mesh.options.units,'cm');assert.equal(mesh.options.reverseWinding,true);assert.equal(mesh.options.refine,true);
    assert.deepEqual(mesh.options.orientation,{z:'+Y',x:'-X'});assert.deepEqual(mesh.options.placement,{position:[45,-20,13],clocking:31});
    authored.output='casting';const valid=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(authored))}})`);
    assert.equal(valid.valid,true,JSON.stringify(valid.diagnostics));
    await s.evaluate('window.studio.windows.active().window.editor.focus()');await s.key('z',{modifiers:2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===1','Atomic undo');
    assert.deepEqual(JSON.parse(await s.evaluate('window.studio.windows.active().window.editor.getValue()')),original);assert.deepEqual(s.exceptions,[]);
  } finally {await s.close();}
});
