// Actual adaptor schema and authoring form for a typed whole-asset resource.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

test('Blender resource choices distinguish object, public collection and whole asset', {timeout:90000}, async () => {
 const session=await launch({provider:'blender'});
 try {
  await session.wait('window.studio?.store.get().adaptors.length','adaptor catalogue');
  await session.evaluate(`(async()=>{
   const response=await studio.api.get('/api/studio/adaptor',{id:'blender',version:'schemaxis.blender.production/1'});
   const production=response.addCatalogue.items.find(item=>item.id==='document:production').schema;
   const {configureOperation}=await import('/windows/workbench/operation-form.mjs');
   window.resourceDocument={version:'schemaxis.blender.production/1',production:{assets:[{id:'cad',file:'/replace/source.glb',format:'glb'}]}};window.resourceResult=null;
   configureOperation(studio,{id:'geometry-resource',title:'Geometry resource',at:'/production/geometryResources/-',schema:production.properties.geometryResources.items},response.addCatalogue.definitions,()=>resourceDocument).then(r=>{window.resourceResult=r;});
  })()`);
  await session.wait(`document.querySelector('[aria-label="Geometry resource value kind"]')`,'resource form');
  const choices=await session.evaluate(`Array.from(document.querySelector('[aria-label="Geometry resource value kind"]').options,x=>x.textContent)`);
  assert.deepEqual(choices,['Object / selected part','Public collection','Whole asset collection']);
  await session.evaluate(`(()=>{
   const choice=document.querySelector('[aria-label="Geometry resource value kind"]');choice.value='2';choice.dispatchEvent(new Event('change',{bubbles:true}));
   document.querySelectorAll('.dialog details').forEach(x=>{x.open=true;});
   for(const [key,value] of Object.entries({'Geometry resource.id':'completeAssembly','Geometry resource.asset':'cad'})){const input=document.querySelector('[aria-label="'+key+'"]');if(!input)throw Error(key);input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));}
   [...document.querySelectorAll('.dialog button')].find(x=>x.textContent==='Add operation').click();
  })()`);
  await session.wait('window.resourceResult','validated geometry resource');
  assert.deepEqual(await session.evaluate('window.resourceResult.inserts[0].values[0]'),{id:'completeAssembly',kind:'asset',asset:'cad'});
 } catch(error) {console.log(JSON.stringify({exceptions:session.exceptions,consoleErrors:session.consoleErrors,body:await session.evaluate('document.body.innerText.slice(0,2000)')}));throw error;} finally {await session.close();}
});
