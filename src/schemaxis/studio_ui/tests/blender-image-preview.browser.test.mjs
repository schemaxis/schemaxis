import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {test} from 'node:test';
import {launch} from './harness.mjs';

test('Blender preview selection, image interpretation and real folder selection remain distinct', {timeout:90000},async()=>{
 const session=await launch({provider:'blender'});
 const folder=fileURLToPath(new URL('../../../../examples/schemaxis/',import.meta.url));
 try {
  await session.wait('window.studio?.store.get().adaptors.length','adaptor catalogue');
  await session.evaluate(`(async()=>{
   window.response=await studio.api.get('/api/studio/adaptor',{id:'blender',version:'schemaxis.blender.production/1'});
   window.production=response.addCatalogue.items.find(x=>x.id==='document:production').schema;
   const {configureOperation}=await import('/windows/workbench/operation-form.mjs');window.configurePreview=configureOperation;
   window.previewDocument={version:'schemaxis.blender.production/1',production:{images:[{id:'fieldImage',file:'field.png'}],materialGraphs:[]}};
   window.previewResult=null;
   configureOperation(studio,{id:'preview',title:'Preview',at:'/production/materialGraphs/0/displayTexture',schema:production.properties.materialGraphs.items.properties.displayTexture},response.addCatalogue.definitions,()=>previewDocument).then(r=>{window.previewResult=r;});
  })()`);
  await session.wait(`document.querySelector('[aria-label="Preview value kind"]')`,'display texture choice');
  await session.evaluate(`(()=>{
   const select=document.querySelector('[aria-label="Preview value kind"]');select.value='1';select.dispatchEvent(new Event('change',{bubbles:true}));
   const input=document.querySelector('[aria-label="Preview.image"]');input.value='fieldImage';input.dispatchEvent(new Event('input',{bubbles:true}));
   [...document.querySelectorAll('.dialog button')].find(x=>x.textContent==='Add operation').click();
  })()`);
  await session.wait('window.previewResult','selected preview image');
  assert.deepEqual(await session.evaluate('previewResult.inserts[0].values[0]'),{kind:'image',image:'fieldImage'});
  await session.evaluate(`(()=>{
   window.imageResult=null;configurePreview(studio,{id:'image',title:'Image',at:'/production/images/-',schema:production.properties.images.items},response.addCatalogue.definitions,()=>previewDocument).then(r=>{window.imageResult=r;});
  })()`);
  await session.wait(`document.querySelector('[aria-label="Image.id"]')`,'captured image form');
  await session.evaluate(`(()=>{
   document.querySelectorAll('.dialog details').forEach(x=>{x.open=true;});
   const id=document.querySelector('[aria-label="Image.id"]');id.value='label';id.dispatchEvent(new Event('input',{bubbles:true}));
   for(const key of ['alphaMode','colourSpace']){const e=document.querySelector('[aria-label="Include Image.'+key+'"]');if(e&&!e.checked){e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));}}
   for(const [key,value] of [['alphaMode','premultiplied'],['colourSpace','Non-Color']]){const e=document.querySelector('[aria-label="Image.'+key+'"]');const option=[...e.options].find(o=>o.textContent===JSON.stringify(value));if(!option)throw Error(key+': '+JSON.stringify([...e.options].map(x=>[x.value,x.textContent])));e.value=option.value;e.dispatchEvent(new Event('change',{bubbles:true}));}
   document.querySelector('[aria-label="Browse for Image.file"]').click();
  })()`);
  await session.wait(`document.querySelector('.operation-file-browser:not([hidden])')`,'real host folder browser');
  await session.evaluate(`(()=>{const input=document.querySelector('[aria-label="Browse folder for Image.file"]');input.value=${JSON.stringify(folder)};input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));})()`);
  await session.wait(`Array.from(document.querySelectorAll('.operation-file-entry')).some(x=>x.textContent==='File: blender-image-preview.png')`,'authored PNG fixture');
  await session.evaluate(`Array.from(document.querySelectorAll('.operation-file-entry')).find(x=>x.textContent==='File: blender-image-preview.png').click()`);
  await session.evaluate(`Array.from(document.querySelectorAll('.file-dialog .dialog-footer button')).find(x=>x.textContent==='Open').click()`);
  await session.wait(`!document.querySelector('.file-dialog')`,'file chosen');
  assert.equal(await session.evaluate(`document.querySelector('[aria-label="Image.file"]').value`),folder+'blender-image-preview.png');
  await session.evaluate(`Array.from(document.querySelectorAll('.dialog button')).find(x=>x.textContent==='Add operation').click()`);
  await session.wait('window.imageResult','image interpretation declaration');
  const image=await session.evaluate('imageResult.inserts[0].values[0]');
  assert.equal(image.alphaMode,'premultiplied');assert.equal(image.colourSpace,'Non-Color');
  assert.equal(image.file,folder+'blender-image-preview.png');
  await session.evaluate(`(()=>{
   const render=response.addCatalogue.items.find(x=>x.id==='document:render').schema;
   const variants=render.properties.renderer.anyOf;const wb=variants.find(x=>x.properties.kind.enum?.includes('workbench')||x.properties.kind.const==='workbench');
   window.textureChoice=wb.properties.colourSource.anyOf.findIndex(x=>x.properties.kind.enum?.includes('texture')||x.properties.kind.const==='texture');window.colourResult=null;
   configurePreview(studio,{id:'colour',title:'Colour source',at:'/render/renderer/colourSource',schema:wb.properties.colourSource},response.addCatalogue.definitions,()=>previewDocument).then(r=>{window.colourResult=r;});
  })()`);
  await session.wait(`document.querySelector('[aria-label="Colour source value kind"]')`,'renderer texture choice');
  await session.evaluate(`(()=>{const select=document.querySelector('[aria-label="Colour source value kind"]');select.value=String(textureChoice);select.dispatchEvent(new Event('change',{bubbles:true}));[...document.querySelectorAll('.dialog button')].find(x=>x.textContent==='Add operation').click();})()`);
  await session.wait('window.colourResult','typed renderer texture');
  assert.deepEqual(await session.evaluate('colourResult.inserts[0].values[0]'),{kind:'texture'});
  assert.deepEqual(session.exceptions,[]);
 }catch(error){console.log(JSON.stringify({exceptions:session.exceptions,consoleErrors:session.consoleErrors,body:await session.evaluate('document.body.innerText.slice(0,2500)')}));throw error;}finally{await session.close();}
});
