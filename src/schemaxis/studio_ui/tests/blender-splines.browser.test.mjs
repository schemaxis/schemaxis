// Actual nested classic spline/weight authoring through the installed adaptor schema.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

test('Blender spline form chooses rational controls and edits weight/order', {timeout:90000}, async()=>{
 const session=await launch({provider:'blender'});
 try {
  await session.wait('window.studio?.store.get().adaptors.length','adaptor catalogue');
  await session.evaluate(`(async()=>{
   const response=await studio.api.get('/api/studio/adaptor',{id:'blender',version:'schemaxis.blender.production/1'});
   const production=response.addCatalogue.items.find(i=>i.id==='document:production').schema;
   const {configureOperation}=await import('/windows/workbench/operation-form.mjs');
   window.splineDocument={version:'schemaxis.blender.production/1',production:{objects:[]}};window.splineResult=null;
   configureOperation(studio,{id:'spline',title:'Spline',at:'/production/objects/-',schema:production.properties.objects.items.oneOf[8]},response.addCatalogue.definitions,()=>splineDocument).then(r=>{window.splineResult=r;});
  })()`);
  await session.wait(`document.querySelector('[aria-label="Spline.splines[0] value kind"]')`,'spline control form');
  const labels=await session.evaluate(`Array.from(document.querySelector('[aria-label="Spline.splines[0] value kind"]').options,o=>o.textContent)`);
  assert.deepEqual(labels,['Straight polyline','Cubic Bezier controls','Rational NURBS controls']);
  await session.evaluate(`(()=>{
   const select=document.querySelector('[aria-label="Spline.splines[0] value kind"]');select.value='2';select.dispatchEvent(new Event('change',{bubbles:true}));
   document.querySelectorAll('.dialog details').forEach(x=>{x.open=true;});
   for(const key of ['Spline.splines[0].order','Spline.splines[0].points[1].weight']){const enabled=document.querySelector('[aria-label="Include '+key+'"]');enabled.checked=true;enabled.dispatchEvent(new Event('change',{bubbles:true}));}
   const values={'Spline.id':'rationalPath','Spline.splines[0].id':'arc','Spline.splines[0].order':2,'Spline.splines[0].points[1].weight':.75};
   for(const [index,coords] of [[0,[1,0,0]],[1,[0,1,0]]])for(let i=0;i<3;i++)values['Spline.splines[0].points['+index+'].position['+i+']']=coords[i];
   for(const [name,value] of Object.entries(values)){const input=document.querySelector('[aria-label="'+name+'"]');if(!input)throw Error(name);input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));}
   [...document.querySelectorAll('.dialog button')].find(x=>x.textContent==='Add operation').click();
  })()`);
  await session.wait('window.splineResult','validated rational declaration');
  const value=await session.evaluate('window.splineResult.inserts[0].values[0]');
  assert.equal(value.kind,'spline');assert.equal(value.id,'rationalPath');assert.equal(value.splines[0].kind,'NURBS');assert.equal(value.splines[0].order,2);assert.equal(value.splines[0].points[1].weight,.75);assert.deepEqual(value.splines[0].points.map(p=>p.position),[[1,0,0],[0,1,0]]);
 } catch(error){console.log(JSON.stringify({exceptions:session.exceptions,consoleErrors:session.consoleErrors,body:await session.evaluate('document.body.innerText.slice(0,2400)')}));throw error;}finally{await session.close();}
});
