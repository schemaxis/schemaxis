import assert from 'node:assert/strict';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

async function field(s,label,value){
  await s.evaluate(`(()=>{const e=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});if(!e||e.disabled)throw Error('Missing '+${JSON.stringify(label)});for(let p=e;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}
test('Zstandard authors real tasks with an all-types input picker and explains nested adaptive limits',{timeout:120000},async()=>{
  const s=await launch({provider:'zstandard'});
  try{
    await s.wait('window.studio?.store.get().server','Studio ready');
    const library=await s.evaluate(`window.studio.api.get('/api/studio/adaptor',{id:'zstandard'})`);
    assert.equal(library.templates.length,12);
    const additions=library.addCatalogue.items.filter(item=>item.operation);
    assert.equal(additions.length,12);assert.ok(additions.every(item=>item.at==='/operation'&&item.guidance.status!=='pending'));
    for(const entry of library.templates){
      const report=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'zstandard',source:${JSON.stringify(JSON.stringify(entry.document))}})`);
      assert.equal(report.valid,true,JSON.stringify(report));
    }
    const source=fileURLToPath(new URL('../../examples/schemaxis/fixtures/zstandard/mixed.bin',import.meta.url));
    const doc={version:'schemaxis.zstandard/1',operation:'compress',source,adaptive:{minLevel:1,maxLevel:9},level:3};
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',{action:'new',provider:'zstandard',name:'Captured bytes',document:${JSON.stringify(doc)}});await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait(`document.querySelector('.wb-properties [aria-label="/source"]')`,'Typed document properties');
    await s.wait(`document.querySelector('.wb-properties')?.textContent.includes('historical level schedule')`,'Loaded conceptual guidance');
    assert.match(await s.evaluate('document.querySelector(".wb-properties").textContent'),/historical level schedule/);
    assert.equal(await s.evaluate("Boolean(document.querySelector('.wb-properties [aria-label=\"/samples\"], .wb-properties [aria-label=\"/fileSet\"]'))"),false);
    await field(s,'/level','6');
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).level===6','Typed compression-level edit');
    await field(s,'/adaptive',JSON.stringify({minLevel:2,maxLevel:8}));
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).adaptive.minLevel===2','Nested adaptive bounds edit');
    await s.evaluate(`(()=>{const b=document.querySelector('[aria-label="Browse folders for /source"]');if(!b)throw Error('Missing all-types file picker');for(let p=b;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;b.click();})()`);
    await s.wait('document.querySelector(".operation-file-browser:not([hidden]) .operation-file-list")?.textContent.includes("mixed.bin")','Arbitrary binary file admitted by picker');
    const picker=await s.evaluate('document.querySelector(".operation-file-browser:not([hidden])").textContent');
    assert.match(picker,/All file types/);assert.doesNotMatch(picker,/Suggested types:/);
    const edited=JSON.parse(await s.evaluate('window.studio.windows.active().window.editor.getValue()'));
    assert.deepEqual(edited,{...doc,level:6,adaptive:{minLevel:2,maxLevel:8}});
    const accepted=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'zstandard',source:${JSON.stringify(JSON.stringify(edited))}})`);
    assert.equal(accepted.valid,true);
    await s.evaluate('window.studio.windows.active().window.editor.focus()');await s.key('z',{modifiers:2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).adaptive.minLevel===1','Atomic nested edit undo');
    const bad={...doc,adaptive:{minLevel:7,maxLevel:2}};
    const refused=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'zstandard',source:${JSON.stringify(JSON.stringify(bad))}})`);
    assert.equal(refused.valid,false);assert.ok(refused.diagnostics.some(d=>d.code==='INVALID_ZSTANDARD_OPTION'));
    assert.deepEqual(s.exceptions,[]);
  }catch(error){console.error('Browser exceptions',s.exceptions);throw error;}
  finally{await s.close();}
});
