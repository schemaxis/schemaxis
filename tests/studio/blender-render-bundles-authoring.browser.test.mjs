import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

test('render bundle forms preserve World, AOV and layer intent through validation and undo', {timeout:120000}, async()=>{
  const source=JSON.parse(await readFile(new URL('../../docs/examples/blender-render-bundles-artist.json',import.meta.url),'utf8'));
  source.production.collections=[{id:'panelSet'}];
  source.production.objects[0].collection='panelSet';
  source.production.viewLayers[0].collections=[{target:{kind:'collection',collection:'panelSet'},mode:'include'}];
  const session=await launch({provider:'blender'});
  try {
    await session.wait('window.studio?.store.get().server','Studio ready');
    const record=await session.evaluate(`(async()=>{const c=window.studio;
      const r=await c.api.post('/api/documents',{action:'new',provider:'blender',name:'Render bundle authoring',document:${JSON.stringify(source)}});
      await c.refresh();c.windows.open('workbench',{document:r.id});return r;})()`);
    await session.wait('window.studio.windows.active()?.window?.editor?.getValue().includes("artist-bundle")','artist example loaded');
    const documentValue=async()=>JSON.parse(await session.evaluate('window.studio.windows.active().window.editor.getValue()'));
    const validate=doc=>session.evaluate(`window.studio.api.post('/api/validate',{provider:'blender',source:${JSON.stringify(JSON.stringify(doc))}})`);
    assert.equal((await validate(source)).valid,true);
    await session.evaluate(`(async()=>{const c=window.studio;
      window.bundleCatalogue=await c.api.get('/api/studio/adaptor',{id:'blender',version:'schemaxis.blender.production/1'});
      window.bundleProperties=bundleCatalogue.addCatalogue.items.find(i=>i.id==='document:production').schema.properties;
      window.bundleInclude=label=>{const e=document.querySelector('[aria-label="Include '+label+'"]');
        if(e&&!e.checked){e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));}};
      window.bundleField=(label,value)=>{bundleInclude(label);const e=document.querySelector('[aria-label="'+label+'"]');
        if(!e||e.disabled)throw Error('Missing or disabled '+label);e.value=String(value);
        e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));};
      window.bundleChoose=(label,value)=>{bundleInclude(label);const e=document.querySelector('[aria-label="'+label+'"]');
        const o=e&&[...e.options].find(x=>x.textContent===JSON.stringify(value));if(!o)throw Error('Missing choice '+label);
        e.value=o.value;e.dispatchEvent(new Event('change',{bubbles:true}));};
      window.bundleBranch=(label,schema,kind)=>{bundleInclude(label);const branches=schema.anyOf||schema.oneOf;
        const index=branches.findIndex(b=>b.properties.kind.const===kind||b.properties.kind.enum?.includes(kind));
        const e=document.querySelector('[aria-label="'+label+' value kind"]');if(index<0||!e)throw Error('Missing branch '+label+': '+kind);
        e.value=String(index);e.dispatchEvent(new Event('change',{bubbles:true}));};
    })()`);
    async function form(field,title) {
      await session.evaluate(`(async()=>{const c=window.studio;window.bundleResult=null;
        const {configureOperation}=await import('/windows/workbench/operation-form.mjs');
        configureOperation(c,{id:'bundle',title:${JSON.stringify(title)},at:${JSON.stringify('/production/'+field)},
          schema:{...bundleProperties[${JSON.stringify(field)}],default:JSON.parse(c.windows.active().window.editor.getValue()).production[${JSON.stringify(field)}]}},
          bundleCatalogue.addCatalogue.definitions,()=>JSON.parse(c.windows.active().window.editor.getValue())).then(v=>{window.bundleResult=v;});})()`);
      await session.wait('document.querySelector(".dialog-footer")','schema form');
    }
    async function submit() {
      await session.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent.trim()==='Add operation').click()`);
    }
    async function result() {
      await submit();await session.wait('window.bundleResult','typed result');
      return session.evaluate('bundleResult.inserts[0].values[0]');
    }
    async function apply(field,value) {
      await session.evaluate(`window.studio.windows.active().window.editor.insertAtPointer(${JSON.stringify('/production/'+field)},${JSON.stringify(value)})`);
    }
    await form('viewLayers','Layers');
    await session.evaluate(`(()=>{const rule=bundleProperties.viewLayers.items.properties.collections.items.properties.target;
      bundleBranch('Layers[0].collections[0].target',rule,'asset');
      bundleField('Layers[0].collections[0].target.asset','missingAsset');
      bundleInclude('Layers[0].collections[0].target.path');
      const add=[...document.querySelectorAll('.dialog button')].find(e=>e.textContent==='Add Layers[0].collections[0].target.path item');
      if(!add)throw Error('Missing asset collection path control');add.click();add.click();
      bundleField('Layers[0].collections[0].target.path[0]','Assembly');bundleField('Layers[0].collections[0].target.path[1]','Body');
      bundleChoose('Layers[0].collections[0].mode','holdout');bundleField('Layers[1].cryptomatte.levels',0);})()`);
    await submit();await session.wait('document.querySelector(".operation-error")?.textContent.includes("levels")','invalid coverage count refused');
    assert.equal(await session.evaluate('window.bundleResult'),null);assert.deepEqual(await documentValue(),source);
    await session.evaluate(`bundleField('Layers[1].cryptomatte.levels',8)`);
    const layers=await result();
    assert.deepEqual(layers[0].collections[0],{target:{kind:'asset',asset:'missingAsset',path:['Assembly','Body']},mode:'holdout'});
    const unresolved=structuredClone(source);unresolved.production.viewLayers=layers;
    const refused=await validate(unresolved);assert.equal(refused.valid,false);assert.match(JSON.stringify(refused),/UNKNOWN_REFERENCE|absent/i);
    // Resolve the authored reference through a second real form, preserving the
    // other nested overrides and all unrelated example content.
    await form('viewLayers','Layers');
    await session.evaluate(`bundleChoose('Layers[0].collections[0].mode','holdout');bundleField('Layers[1].cryptomatte.levels',8)`);
    const validLayers=await result();assert.equal(validLayers[1].materialOverride,'inspection');assert.equal(validLayers[1].worldOverride,'warm');
    await apply('viewLayers',validLayers);
    await form('materialAovs','Taps');
    await session.evaluate(`(()=>{const spec=bundleProperties.materialAovs.items.properties;
      bundleBranch('Taps[3].target',spec.target,'material');bundleField('Taps[3].target.material','finish');
      bundleBranch('Taps[3].source',spec.source,'surfaceChannel');bundleChoose('Taps[3].source.channel','roughness');
      bundleField('Taps[4].source.value',0.625);})()`);
    const taps=await result();assert.deepEqual(taps[3].target,{kind:'material',material:'finish'});
    assert.deepEqual(taps[3].source,{kind:'surfaceChannel',channel:'roughness'});assert.equal(taps[4].source.value,0.625);
    // This would duplicate finish's worldTag writer only if another writer
    // targeted the same owner/AOV; the original finish tap targets roughness.
    await apply('materialAovs',taps);
    await form('worlds','Worlds');
    await session.evaluate(`(()=>{bundleBranch('Worlds[0].lighting',bundleProperties.worlds.items.properties.lighting,'environment');
      bundleField('Worlds[0].lighting.image','missingEnvironment');bundleField('Worlds[0].lighting.strength',0.3);
      bundleChoose('Worlds[0].lighting.projection','mirrorBall');})()`);
    const environment=await result();assert.equal(environment[0].lighting.image,'missingEnvironment');assert.equal(environment[0].lighting.projection,'mirrorBall');
    const missingImage=await documentValue();missingImage.production.worlds=environment;
    assert.equal((await validate(missingImage)).valid,false,'undeclared World image is refused');
    await form('worlds','Worlds');await session.evaluate(`bundleField('Worlds[0].lighting.strength',0.3)`);
    const worlds=await result();await apply('worlds',worlds);
    const changed=await documentValue();const expected=structuredClone(source);
    expected.production.viewLayers=validLayers;expected.production.materialAovs=taps;expected.production.worlds=worlds;
    assert.deepEqual(changed,expected);const final=await validate(changed);assert.equal(final.valid,true,JSON.stringify(final));
    await session.evaluate('window.studio.windows.active().window.editor.focus()');await session.key('z',{modifiers:2});
    await session.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).production.worlds[0].lighting.strength===0.1','atomic World undo');
    const undone=await documentValue();const beforeWorld=structuredClone(expected);beforeWorld.production.worlds=source.production.worlds;assert.deepEqual(undone,beforeWorld);
    await apply('worlds',worlds);assert.deepEqual(await documentValue(),expected);
    const saved=await session.evaluate(`window.studio.api.get('/api/document',{id:${JSON.stringify(record.id)}})`);
    assert.equal(saved.revision,record.revision);assert.deepEqual(saved.document,source,'form edits and validation do not implicitly save');
    assert.deepEqual(session.exceptions,[]);
  } catch(error) {
    console.log(JSON.stringify({exceptions:session.exceptions,consoleErrors:session.consoleErrors,body:await session.evaluate('document.body.innerText.slice(-5000)')}));throw error;
  } finally {await session.close();}
});
