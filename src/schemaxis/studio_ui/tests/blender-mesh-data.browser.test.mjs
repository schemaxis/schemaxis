// Real adaptor schema and recursive authoring form; no native Blender is launched.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

test('Blender mesh fields expose meaningful typed choices and sparse vector controls', {timeout: 90000}, async () => {
  const session = await launch({provider: 'blender'});
  try {
    await session.wait('window.studio?.store.get().adaptors.length', 'adaptor catalogue');
    await session.evaluate(`(async () => {
      const response = await studio.api.get('/api/studio/adaptor', {id:'blender',version:'schemaxis.blender.production/1'});
      const production = response.addCatalogue.items.find(item => item.id === 'document:production').schema;
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      window.meshTestDocument = {version:'schemaxis.blender.production/1', production:{objects:[{id:'plate',kind:'mesh',vertices:[[0,0,0],[1,0,0],[0,1,0]],faces:[[0,1,2]]}]}};
      window.meshFormResult = null;
      configureOperation(studio, {id:'mesh-data',title:'Mesh data',at:'/production/meshData/-',schema:production.properties.meshData.items}, response.addCatalogue.definitions, () => meshTestDocument)
        .then(result => {window.meshFormResult = result;});
    })()`);
    await session.wait(`document.querySelector('[aria-label="Include Mesh data.attributes"]')`, 'mesh fields form');
    await session.evaluate(`(() => {
      document.querySelectorAll('.dialog details').forEach(item => {item.open=true;});
      const include = document.querySelector('[aria-label="Include Mesh data.attributes"]');
      include.checked=true;include.dispatchEvent(new Event('change',{bubbles:true}));
      [...document.querySelectorAll('.dialog button')].find(item => item.textContent==='Add Mesh data.attributes item').click();
    })()`);
    const choices = await session.evaluate(`Array.from(document.querySelector('[aria-label="Mesh data.attributes[0] value kind"]').options, item => item.textContent)`);
    assert.equal(choices.length, 24);assert.equal(new Set(choices).size,24);
    assert.ok(choices.includes('Vector (sparse)'));assert.ok(choices.includes('sRGB byte colour (dense)'));
    await session.evaluate(`(() => {
      const choice = document.querySelector('[aria-label="Mesh data.attributes[0] value kind"]');
      choice.value = String(Array.from(choice.options).findIndex(item => item.textContent==='Vector (sparse)'));
      choice.dispatchEvent(new Event('change',{bubbles:true}));
      const values={'Mesh data.object':'plate','Mesh data.attributes[0].name':'displacement','Mesh data.attributes[0].default[0]':0,'Mesh data.attributes[0].default[1]':0,'Mesh data.attributes[0].default[2]':0,'Mesh data.attributes[0].entries[0].index':1,'Mesh data.attributes[0].entries[0].value[0]':0,'Mesh data.attributes[0].entries[0].value[1]':0,'Mesh data.attributes[0].entries[0].value[2]':2};
      for (const [name,value] of Object.entries(values)) {
        const input = document.querySelector('[aria-label="'+name+'"]');if (!input) throw Error(name);input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));
      }
      [...document.querySelectorAll('.dialog button')].find(item => item.textContent==='Add operation').click();
    })()`);
    await session.wait('window.meshFormResult', 'typed mesh declaration');
    const declaration = await session.evaluate('window.meshFormResult.inserts[0].values[0]');
    assert.equal(declaration.object,'plate');assert.deepEqual(declaration.attributes,[{name:'displacement',kind:'vector',mode:'sparse',default:[0,0,0],entries:[{index:1,value:[0,0,2]}]}]);
  } finally {await session.close();}
});
