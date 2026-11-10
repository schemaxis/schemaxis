// Actual nested topology/selection forms use reviewed semantic choice labels.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

test('Blender topology stages expose distinct operations and edit a finite face box', {timeout:90000}, async()=>{
 const session=await launch({provider:'blender'});
 try {
  await session.wait('window.studio?.store.get().adaptors.length','adaptor catalogue');
  await session.evaluate(`(async()=>{
   const response=await studio.api.get('/api/studio/adaptor',{id:'blender',version:'schemaxis.blender.production/1'});
   const production=response.addCatalogue.items.find(item=>item.id==='document:production').schema;
   const {configureOperation}=await import('/windows/workbench/operation-form.mjs');
   window.editDocument={version:'schemaxis.blender.production/1',production:{objects:[{id:'plate',kind:'mesh',vertices:[[0,0,0],[2,0,0],[2,2,0],[0,2,0]],faces:[[0,1,2,3]]}]}};window.editResult=null;
   configureOperation(studio,{id:'mesh-edit',title:'Mesh edit',at:'/production/meshEdits/-',schema:production.properties.meshEdits.items},response.addCatalogue.definitions,()=>editDocument).then(result=>{window.editResult=result;});
  })()`);
  await session.wait(`document.querySelector('[aria-label="Mesh edit.steps[0] value kind"]')`,'topology form');
  const operations=await session.evaluate(`Array.from(document.querySelector('[aria-label="Mesh edit.steps[0] value kind"]').options,o=>o.textContent)`);
  assert.equal(operations.length,11);assert.equal(new Set(operations).size,11);
  for(const label of ['Extrude face region','Inset individual faces','Bridge two closed loops','Cut a mesh halfspace'])assert(operations.includes(label));
  await session.evaluate(`(()=>{
   const choice=document.querySelector('[aria-label="Mesh edit.steps[0] value kind"]');choice.value='2';choice.dispatchEvent(new Event('change',{bubbles:true}));
   const selection=document.querySelector('[aria-label="Mesh edit.steps[0].selection value kind"]');window.selectionLabels=Array.from(selection.options,o=>o.textContent);selection.value='2';selection.dispatchEvent(new Event('change',{bubbles:true}));
   document.querySelectorAll('.dialog details').forEach(x=>{x.open=true;});
   const values={'Mesh edit.object':'plate','Mesh edit.steps[0].id':'rim','Mesh edit.steps[0].distance':.25};
   for(const [bound,coords] of Object.entries({minimum:[.5,.5,0],maximum:[1.5,1.5,0]}))for(let i=0;i<3;i++)values['Mesh edit.steps[0].selection.'+bound+'['+i+']']=coords[i];
   for(const [name,value] of Object.entries(values)){const input=document.querySelector('[aria-label="'+name+'"]');if(!input)throw Error(name);input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));}
   [...document.querySelectorAll('.dialog button')].find(x=>x.textContent==='Add operation').click();
  })()`);
  assert.deepEqual(await session.evaluate('window.selectionLabels'),['All current elements','Explicit current indices','Local coordinate box','Face normal direction','Open boundary edges','Face material slots']);
  await session.wait('window.editResult','validated topology declaration');
  const target=await session.evaluate('window.editResult.inserts[0].values[0]');
  assert.equal(target.object,'plate');assert.deepEqual(target.steps,[{id:'rim',distance:.25,kind:'insetFaces',selection:{minimum:[.5,.5,0],maximum:[1.5,1.5,0],kind:'box'}}]);
 } catch(error){console.log(JSON.stringify({exceptions:session.exceptions,consoleErrors:session.consoleErrors,body:await session.evaluate('document.body.innerText.slice(0,2400)')}));throw error;}finally{await session.close();}
});
