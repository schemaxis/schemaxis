import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

test('Blender artist layer, stored UV and built-in OSL forms produce typed intent', {timeout:90000},async()=>{
 const session=await launch({provider:'blender'});
 try {
  await session.wait('window.studio?.store.get().adaptors.length','adaptor catalogue');
  await session.evaluate(`(async()=>{
   window.surfaceResponse=await studio.api.get('/api/studio/adaptor',{id:'blender',version:'schemaxis.blender.production/1'});
   window.productionSchema=surfaceResponse.addCatalogue.items.find(x=>x.id==='document:production').schema;
   window.artistSchema=productionSchema.properties.surfaceMaterials.items;
   window.surfaceDocument={version:'schemaxis.blender.production/1',production:{surfaceMaterials:[{id:'finish',samplers:[{id:'orm',image:'packed'}]}]}};
   window.configureSurface=(await import('/windows/workbench/operation-form.mjs')).configureOperation;
   window.surfaceResult=null;
   configureSurface(studio,{id:'coat',title:'Coat',at:'/production/surfaceMaterials/0/coat',schema:artistSchema.properties.coat},surfaceResponse.addCatalogue.definitions,()=>surfaceDocument).then(r=>{window.surfaceResult=r;});
  })()`);
  await session.wait(`document.querySelector('[aria-label="Include Coat.weight"]')`,'physical coat form');
  await session.evaluate(`(()=>{
   window.includeField=(label)=>{const e=document.querySelector('[aria-label="Include '+label+'"]');if(e&&!e.checked){e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));}};
   window.chooseValue=(label,value)=>{const e=document.querySelector('[aria-label="'+label+'"]');const o=[...e.options].find(o=>o.textContent===JSON.stringify(value));if(!o)throw Error(label+': '+JSON.stringify([...e.options].map(o=>o.textContent)));e.value=o.value;e.dispatchEvent(new Event('change',{bubbles:true}));};
   includeField('Coat.weight');const choice=document.querySelector('[aria-label="Coat.weight value kind"]');choice.value='1';choice.dispatchEvent(new Event('change',{bubbles:true}));
   const sampler=document.querySelector('[aria-label="Coat.weight.sampler"]');sampler.value='orm';sampler.dispatchEvent(new Event('input',{bubbles:true}));
   includeField('Coat.weight.channel');chooseValue('Coat.weight.channel','green');
   [...document.querySelectorAll('.dialog button')].find(x=>x.textContent==='Add operation').click();
  })()`);
  await session.wait('window.surfaceResult','local scalar sampler role');
  assert.deepEqual(await session.evaluate('surfaceResult.inserts[0].values[0]'),{weight:{kind:'sample',sampler:'orm',channel:'green'},roughness:{kind:'constant',value:.03},ior:{kind:'constant',value:1.5},tint:{kind:'constant',value:[1,1,1]},normal:{kind:'followBase'}});
  await session.evaluate(`(()=>{
   window.uvResult=null;const schema=productionSchema.properties.meshData.items.properties.uvMaps.items.oneOf.find(x=>x.properties.method.const==='copy');
   configureSurface(studio,{id:'uv',title:'Stored UV',at:'/production/meshData/0/uvMaps/-',schema},surfaceResponse.addCatalogue.definitions,()=>surfaceDocument).then(r=>{window.uvResult=r;});
  })()`);
  await session.wait(`document.querySelector('[aria-label="Stored UV.source"]')`,'source-owned UV copy form');
  await session.evaluate(`(()=>{
   for(const [key,value] of [['name','Finish'],['source','Base']]){const e=document.querySelector('[aria-label="Stored UV.'+key+'"]');e.value=value;e.dispatchEvent(new Event('input',{bubbles:true}));}
   includeField('Stored UV.transform');includeField('Stored UV.transform.rotationDegrees');const angle=document.querySelector('[aria-label="Stored UV.transform.rotationDegrees"]');angle.value='45';angle.dispatchEvent(new Event('input',{bubbles:true}));
   [...document.querySelectorAll('.dialog button')].find(x=>x.textContent==='Add operation').click();
  })()`);
  await session.wait('window.uvResult','named stored UV transform');
  const uv=await session.evaluate('uvResult.inserts[0].values[0]');assert.equal(uv.method,'copy');assert.equal(uv.source,'Base');assert.equal(uv.name,'Finish');assert.equal(uv.transform.rotationDegrees,45);
  await session.evaluate(`(()=>{
   window.backendResult=null;const render=surfaceResponse.addCatalogue.items.find(x=>x.id==='document:render').schema;
   const schema=render.properties.renderer.anyOf.find(x=>x.properties.kind.const==='cycles'||x.properties.kind.enum?.includes('cycles'));
   configureSurface(studio,{id:'backend',title:'Shader backend',at:'/render/renderer',schema},surfaceResponse.addCatalogue.definitions,()=>surfaceDocument).then(r=>{window.backendResult=r;});
  })()`);
  await session.wait(`document.querySelector('[aria-label="Include Shader backend.shadingSystem"]')`,'closed builtin backend choice');
  await session.evaluate(`(()=>{includeField('Shader backend.shadingSystem');chooseValue('Shader backend.shadingSystem','osl');[...document.querySelectorAll('.dialog button')].find(x=>x.textContent==='Add operation').click();})()`);
  await session.wait('window.backendResult','OSL intent');
  assert.deepEqual(await session.evaluate('backendResult.inserts[0].values[0]'),{kind:'cycles',shadingSystem:'osl'});
  assert.deepEqual(session.exceptions,[]);
 }catch(error){console.log(JSON.stringify({exceptions:session.exceptions,consoleErrors:session.consoleErrors,body:await session.evaluate('document.body.innerText.slice(0,3000)')}));throw error;}finally{await session.close();}
});
