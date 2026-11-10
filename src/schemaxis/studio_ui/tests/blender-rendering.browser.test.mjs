import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

test('Blender rendering form chooses technical lighting and explicit exposure', {timeout:90000},async()=>{
 const session=await launch({provider:'blender'});
 try {
  await session.wait('window.studio?.store.get().adaptors.length','adaptor catalogue');
  await session.evaluate(`(async()=>{
   const response=await studio.api.get('/api/studio/adaptor',{id:'blender',version:'schemaxis.blender.production/1'});
   const schema=response.addCatalogue.items.find(i=>i.id==='document:render').schema;
   const {configureOperation}=await import('/windows/workbench/operation-form.mjs');
   window.renderDocument={version:'schemaxis.blender.production/1',production:{objects:[]}};window.renderResult=null;
   configureOperation(studio,{id:'rendering',title:'Rendering',at:'/render',schema},response.addCatalogue.definitions,()=>renderDocument).then(r=>{window.renderResult=r;});
  })()`);
  await session.wait(`document.querySelector('[aria-label="Include Rendering.renderer"]')`,'render settings form');
  await session.evaluate(`(()=>{
   document.querySelectorAll('.dialog details').forEach(x=>{x.open=true;});
   window.enableRendering=(name)=>{const e=document.querySelector('[aria-label="Include '+name+'"]');if(e&&!e.checked){e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));}};
   enableRendering('Rendering.renderer');
  })()`);
  const labels=await session.evaluate(`Array.from(document.querySelector('[aria-label="Rendering.renderer value kind"]').options,o=>o.textContent)`);
  assert.deepEqual(labels,['Cycles path tracing','EEVEE real-time shading','Workbench technical shading']);
  await session.evaluate(`(()=>{
   const select=document.querySelector('[aria-label="Rendering.renderer value kind"]');select.value='2';select.dispatchEvent(new Event('change',{bubbles:true}));
   enableRendering('Rendering.renderer.lighting');
   const lighting=document.querySelector('[aria-label="Rendering.renderer.lighting value kind"]');lighting.value='0';lighting.dispatchEvent(new Event('change',{bubbles:true}));
   enableRendering('Rendering.colourManagement');enableRendering('Rendering.colourManagement.view');
   const view=document.querySelector('[aria-label="Rendering.colourManagement.view value kind"]');view.value='1';view.dispatchEvent(new Event('change',{bubbles:true}));
   enableRendering('Rendering.colourManagement.exposure');
   const exposure=document.querySelector('[aria-label="Rendering.colourManagement.exposure"]');exposure.value='1.5';exposure.dispatchEvent(new Event('input',{bubbles:true}));
   [...document.querySelectorAll('.dialog button')].find(x=>x.textContent==='Add operation').click();
  })()`);
  await session.wait('window.renderResult','typed technical rendering declaration');
  const result=await session.evaluate('window.renderResult.inserts[0].values[0]');
  assert.equal(result.renderer.kind,'workbench');assert.equal(result.renderer.lighting.kind,'flat');assert.equal(result.colourManagement.view.kind,'standard');assert.equal(result.colourManagement.exposure,1.5);
 } catch(error){console.log(JSON.stringify({exceptions:session.exceptions,consoleErrors:session.consoleErrors,body:await session.evaluate('document.body.innerText.slice(0,2400)')}));throw error;}finally{await session.close();}
});
