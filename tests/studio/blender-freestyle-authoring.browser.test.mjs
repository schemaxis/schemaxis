import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

async function field(session, label, value) {
  await session.evaluate(`(() => {const input=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});
    if(!input||input.disabled)throw Error('Missing or disabled '+${JSON.stringify(label)});
    input.value=${JSON.stringify(String(value))};input.dispatchEvent(new Event('input',{bubbles:true}));
    input.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}
async function submit(session) {
  await session.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent.trim()==='Add operation').click()`);
}

test('Freestyle authoring keeps logical styles, QI range and Material-owner line intent atomic', {timeout:90000}, async()=>{
  const source=JSON.parse(await readFile(new URL('../../examples/schemaxis/blender-freestyle-plate.json',import.meta.url),'utf8'));
  const session=await launch({provider:'blender'});
  try {
    await session.wait('window.studio?.store.get().server','Studio ready');
    const record=await session.evaluate(`(async()=>{const c=window.studio;
      const r=await c.api.post('/api/documents',{action:'new',provider:'blender',name:'Technical Freestyle plate',document:${JSON.stringify(source)}});
      await c.refresh();c.windows.open('workbench',{document:r.id});return r;})()`);
    await session.wait('window.studio.windows.active()?.window?.editor?.getValue().includes("technical")','actual example loaded');
    const editorSource=()=>session.evaluate('window.studio.windows.active().window.editor.getValue()');
    const original=await editorSource();
    assert.deepEqual(JSON.parse(original),source);
    const initialValidation=await session.evaluate(`window.studio.api.post('/api/validate',{provider:'blender',source:${JSON.stringify(JSON.stringify(source))}})`);
    assert.equal(initialValidation.valid,true,JSON.stringify(initialValidation));
    assert.deepEqual(initialValidation.diagnostics,[]);
    await session.evaluate(`(async()=>{const c=window.studio;
      window.nprResponse=await c.api.get('/api/studio/adaptor',{id:'blender',version:'schemaxis.blender.production/1'});
      window.nprSchema=nprResponse.addCatalogue.items.find(item=>item.id==='document:production').schema.properties.npr;
      window.nprDocument=JSON.parse(c.windows.active().window.editor.getValue());window.nprResult=null;
      const {configureOperation}=await import('/windows/workbench/operation-form.mjs');
      configureOperation(c,{id:'freestyle',title:'NPR',at:'/production/npr',schema:{...nprSchema,default:nprDocument.production.npr}},
        nprResponse.addCatalogue.definitions,()=>JSON.parse(c.windows.active().window.editor.getValue())).then(value=>{window.nprResult=value;});
    })()`);
    await session.wait(`document.querySelector('[aria-label="NPR.styles[0].width"]')`,'nested NPR style form');
    await session.evaluate(`(()=>{
      document.querySelectorAll('.dialog details').forEach(e=>{e.open=true;});
      window.nprInclude=(label)=>{const input=document.querySelector('[aria-label="Include '+label+'"]');
        if(input&&!input.checked){input.checked=true;input.dispatchEvent(new Event('change',{bubbles:true}));}};
      window.nprChoose=(label,value)=>{nprInclude(label);const input=document.querySelector('[aria-label="'+label+'"]');
        if(!input)throw Error('Missing '+label);const option=[...input.options].find(o=>o.textContent===JSON.stringify(value));
        if(!option)throw Error('Missing choice '+label+': '+value);input.value=option.value;input.dispatchEvent(new Event('change',{bubbles:true}));};
      nprChoose('NPR.styles[0].colourSource','materialLine');
      const ranges=nprSchema.properties.layers.items.properties.lineSets.items.properties.visibility.anyOf;
      const index=ranges.findIndex(branch=>branch.properties.kind.enum?.includes('range')||branch.properties.kind.const==='range');
      if(index<0)throw Error('Missing typed QI range branch');
      const visibility=document.querySelector('[aria-label="NPR.layers[0].lineSets[0].visibility value kind"]');
      visibility.value=String(index);visibility.dispatchEvent(new Event('change',{bubbles:true}));
      const include=document.querySelector('[aria-label="Include NPR.materials"]');
      if(include&&!include.checked){include.checked=true;include.dispatchEvent(new Event('change',{bubbles:true}));}
      const add=[...document.querySelectorAll('.dialog button')].find(e=>e.textContent==='Add NPR.materials item');
      if(!add)throw Error('Missing Material-owner line settings');add.click();
      nprInclude('NPR.materials[0].colour');nprInclude('NPR.materials[0].priority');
    })()`);
    await field(session,'NPR.styles[0].width',0);
    await field(session,'NPR.layers[0].lineSets[0].visibility.minimum',1);
    await field(session,'NPR.layers[0].lineSets[0].visibility.maximum',2);
    await field(session,'NPR.materials[0].material','white');
    await field(session,'NPR.materials[0].priority',7);
    for(const [index,value] of [0,1,0,1].entries())await field(session,`NPR.materials[0].colour[${index}]`,value);
    // A schema-invalid width must not close the form or mutate/save the draft.
    await submit(session);
    await session.wait(`document.querySelector('.operation-error')?.textContent.includes('width')`,'invalid pixel width refused');
    assert.equal(await session.evaluate('window.nprResult'),null);
    assert.equal(await editorSource(),original);
    await field(session,'NPR.styles[0].width',5);
    await submit(session);
    await session.wait('window.nprResult','typed nested NPR result');
    const changedNpr=await session.evaluate('nprResult.inserts[0].values[0]');
    assert.equal(changedNpr.styles[0].width,5);
    assert.equal(changedNpr.styles[0].colourSource,'materialLine');
    assert.deepEqual(changedNpr.layers[0].lineSets[0].visibility,{kind:'range',minimum:1,maximum:2});
    assert.equal(changedNpr.layers[0].layer,'technical');
    assert.equal(changedNpr.layers[0].lineSets[0].style,'visible');
    assert.deepEqual(changedNpr.materials,[{material:'white',colour:[0,1,0,1],priority:7}]);
    // Use the same public editor transaction as the properties panel. This
    // applies a real schema-form result; it does not replace editor JSON text.
    await session.evaluate(`window.studio.windows.active().window.editor.insertAtPointer('/production/npr',nprResult.inserts[0].values[0])`);
    const changed=JSON.parse(await editorSource());
    assert.deepEqual(changed.production.npr,changedNpr);
    const expected=structuredClone(source);expected.production.npr=changedNpr;
    assert.deepEqual(changed,expected);
    const validation=await session.evaluate(`window.studio.api.post('/api/validate',{provider:'blender',source:${JSON.stringify(JSON.stringify(changed))}})`);
    assert.equal(validation.valid,true,JSON.stringify(validation));assert.deepEqual(validation.diagnostics,[]);
    await session.evaluate('window.studio.windows.active().window.editor.focus()');await session.key('z',{modifiers:2});
    await session.wait(`JSON.parse(window.studio.windows.active().window.editor.getValue()).production.npr.styles[0].width===3`,'one atomic undo');
    assert.deepEqual(JSON.parse(await editorSource()),source);
    await session.evaluate(`window.studio.windows.active().window.editor.insertAtPointer('/production/npr',nprResult.inserts[0].values[0])`);
    assert.deepEqual(JSON.parse(await editorSource()),changed);
    const saved=await session.evaluate(`window.studio.api.get('/api/document',{id:${JSON.stringify(record.id)}})`);
    assert.equal(saved.revision,record.revision);assert.deepEqual(saved.document,source,'authoring/validation does not silently save');
    assert.deepEqual(session.exceptions,[]);
  } catch(error) {
    console.log(JSON.stringify({exceptions:session.exceptions,consoleErrors:session.consoleErrors,
      body:await session.evaluate('document.body.innerText.slice(-5000)')}));throw error;
  } finally {await session.close();}
});
