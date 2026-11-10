// Real nested surface layout and Object palette forms from the adaptor schema.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

test('Blender named face layouts and independent Object palettes remain distinct', {timeout:90000},async()=>{
 const session=await launch({provider:'blender'});
 try {
  await session.wait('window.studio?.store.get().adaptors.length','adaptor catalogue');
  await session.evaluate(`(async()=>{
   const response=await studio.api.get('/api/studio/adaptor',{id:'blender',version:'schemaxis.blender.production/1'});
   window.materialSchema=response.addCatalogue.items.find(x=>x.id==='document:production').schema.properties.materialAssignments.items;
   window.materialDefinitions=response.addCatalogue.definitions;
   const {configureOperation}=await import('/windows/workbench/operation-form.mjs');window.configureMaterials=configureOperation;
   window.materialDocument={version:'schemaxis.blender.production/1',production:{objects:[{id:'housing',kind:'mesh'},{id:'other',kind:'instance',source:'housing'}],materialGraphs:[{id:'red'},{id:'blue'},{id:'green'}]}};
   window.materialResult=null;configureMaterials(studio,{id:'surface',title:'Surface',at:'/production/materialAssignments/-',schema:materialSchema},materialDefinitions,()=>materialDocument).then(r=>{window.materialResult=r;});
  })()`);
  await session.wait(`document.querySelector('[aria-label="Surface value kind"]')`,'surface material choice');
  assert.deepEqual(await session.evaluate(`Array.from(document.querySelector('[aria-label="Surface value kind"]').options,o=>o.textContent)`),['Shared data layout','Independent Object palette']);
  await session.evaluate(`(()=>{
   document.querySelectorAll('.dialog details').forEach(x=>{x.open=true;});
   const click=text=>{const button=[...document.querySelectorAll('.dialog button')].find(x=>x.textContent===text);if(!button)throw Error(text);button.click();};
   click('Add Surface.slots item');
   for(const key of ['Surface.sharing','Surface.regions']){const e=document.querySelector('[aria-label="Include '+key+'"]');e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));}
   click('Add Surface.regions item');
   const choice=document.querySelector('[aria-label="Surface.regions[0].selection value kind"]');choice.value='1';choice.dispatchEvent(new Event('change',{bubbles:true}));
   const values={'Surface.id':'finish','Surface.object':'housing','Surface.defaultSlot':'body','Surface.slots[0].id':'body','Surface.slots[0].material':'red','Surface.slots[1].id':'label','Surface.slots[1].material':'blue','Surface.regions[0].slot':'label','Surface.regions[0].selection.indices[0]':1};
   for(const [name,value] of Object.entries(values)){const input=document.querySelector('[aria-label="'+name+'"]');if(!input)throw Error(name);input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));}
   const sharing=document.querySelector('[aria-label="Surface.sharing"]');sharing.value=[...sharing.options].find(o=>o.textContent===JSON.stringify('shared')).value;sharing.dispatchEvent(new Event('change',{bubbles:true}));
   click('Add operation');
  })()`);
  await session.wait('window.materialResult','typed surface layout');
  const layout=await session.evaluate('materialResult.inserts[0].values[0]');
  assert.equal(layout.kind,'layout');assert.equal(layout.sharing,'shared');assert.equal(layout.defaultSlot,'body');
  assert.deepEqual(layout.slots,[{id:'body',material:'red'},{id:'label',material:'blue'}]);assert.deepEqual(layout.regions,[{slot:'label',selection:{kind:'faceIndices',indices:[1]}}]);
  await session.evaluate(`(()=>{
   window.paletteResult=null;configureMaterials(studio,{id:'palette',title:'Palette',at:'/production/materialAssignments/-',schema:materialSchema},materialDefinitions,()=>materialDocument).then(r=>{window.paletteResult=r;});
  })()`);
  await session.wait(`document.querySelector('[aria-label="Palette value kind"]')`,'Object palette choice');
  await session.evaluate(`(()=>{
   const choice=document.querySelector('[aria-label="Palette value kind"]');choice.value='1';choice.dispatchEvent(new Event('change',{bubbles:true}));
   document.querySelectorAll('.dialog details').forEach(x=>{x.open=true;});
   if(document.querySelector('[aria-label="Palette.sharing"]')||document.querySelector('[aria-label="Palette.defaultSlot"]')||document.querySelector('[aria-label="Include Palette.regions"]'))throw Error('inactive DATA layout fields in Object palette');
   [...document.querySelectorAll('.dialog button')].find(x=>x.textContent==='Add Palette.slots item').click();
   const values={'Palette.id':'edition','Palette.object':'other','Palette.layout':'finish','Palette.slots[0].id':'label','Palette.slots[0].material':'blue','Palette.slots[1].id':'body','Palette.slots[1].material':'green'};
   for(const [name,value] of Object.entries(values)){const input=document.querySelector('[aria-label="'+name+'"]');if(!input)throw Error(name);input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));}
   [...document.querySelectorAll('.dialog button')].find(x=>x.textContent==='Add operation').click();
  })()`);
  await session.wait('window.paletteResult','typed Object palette');
  assert.deepEqual(await session.evaluate('paletteResult.inserts[0].values[0]'),{kind:'override',id:'edition',object:'other',layout:'finish',slots:[{id:'label',material:'blue'},{id:'body',material:'green'}]});
  assert.deepEqual(session.exceptions,[]);
 }catch(error){console.log(JSON.stringify({exceptions:session.exceptions,consoleErrors:session.consoleErrors,body:await session.evaluate('document.body.innerText.slice(0,2600)')}));throw error;}finally{await session.close();}
});
