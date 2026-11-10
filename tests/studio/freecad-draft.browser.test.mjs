import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

async function field(s,label,value) {
  await s.evaluate(`(() => {const e=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});
    if(!e || e.disabled)throw Error('Missing field '+${JSON.stringify(label)});
    for(let p=e.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;
    e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}

test('FreeCAD Draft starter and typed planar/cylindrical selection preserve atomic source edits',{timeout:120000},async()=>{
  const s=await launch({provider:'freecad'});
  try {
    await s.wait('window.studio?.store.get().server','Studio ready');
    const library=await s.evaluate(`window.studio.api.get('/api/studio/adaptor',{id:'freecad'})`);
    const template=library.templates.find(t=>t.id==='drafted-enclosure');assert.ok(template?.document);
    const release=template.document.nodes.find(n=>n.filter==='bodyDraft');assert.equal(release.options.faces.length,4);assert.equal(release.inputs.neutralPlane,'outline');
    const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(template.document))}})`);
    assert.equal(checked.valid,true,JSON.stringify(checked.diagnostics));
    const original={version:'schemaxis.freecad/1',nodes:[{id:'body',filter:'body'},
      {id:'outline',filter:'circle',options:{radius:15},inputs:{body:'body'}},
      {id:'stock',filter:'pad',options:{length:20},inputs:{body:'body',profile:'outline'}}],output:'stock'};
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',{action:'new',provider:'freecad',name:'Moulded cup',document:${JSON.stringify(original)}});await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")','Workbench ready');
    await s.clickSelector('[data-add="all"]');await field(s,'Search Add anything…','mould release draft');
    await s.wait(`document.querySelector('[data-library="operation:bodyDraft"]')`,'Draft discovery');
    await s.clickSelector('[data-library="operation:bodyDraft"]');await s.wait('document.querySelector(".operation-form")','Draft form');
    const choices=await s.evaluate(`Array.from(document.querySelector('[aria-label="bodyDraft.options.faces[0] value kind"]').options,o=>o.textContent)`);
    assert.deepEqual(choices,['Planar wall','Cylindrical wall']);
    assert.equal(await s.evaluate(`!!document.querySelector('[aria-label="bodyDraft.options.faces[0].normal[0]"]')`),true);
    await field(s,'bodyDraft.id','release');await field(s,'bodyDraft.inputs.base','stock');await field(s,'bodyDraft.inputs.neutralPlane','outline');
    await field(s,'bodyDraft.options.faces[0] value kind','1');
    assert.equal(await s.evaluate(`!!document.querySelector('[aria-label="bodyDraft.options.faces[0].normal[0]"]')`),false);
    for(const [i,value] of [0,0,-1].entries())await field(s,`bodyDraft.options.faces[0].axis[${i}]`,String(value));
    await field(s,'bodyDraft.options.faces[0].radius','15');
    await s.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent.trim()==='Add operation').click()`);
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===4','Typed Draft inserted');
    const authored=JSON.parse(await s.evaluate('window.studio.windows.active().window.editor.getValue()'));
    assert.deepEqual(authored.nodes.slice(0,3),original.nodes);assert.equal(authored.nodes[3].filter,'bodyDraft');
    assert.deepEqual(authored.nodes[3].options.faces,[{surface:'cylinder',axis:[0,0,-1],radius:15}]);
    authored.output='release';
    const valid=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(authored))}})`);
    assert.equal(valid.valid,true,JSON.stringify(valid.diagnostics));
    await s.evaluate('window.studio.windows.active().window.editor.focus()');await s.key('z',{modifiers:2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes.length===3','Atomic undo');
    assert.deepEqual(JSON.parse(await s.evaluate('window.studio.windows.active().window.editor.getValue()')),original);
    assert.deepEqual(s.exceptions,[]);
  } finally {await s.close();}
});
