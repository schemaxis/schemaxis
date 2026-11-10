import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

async function field(s,label,value) {
  await s.evaluate(`(() => {const e=document.querySelector(${JSON.stringify('[aria-label="'+label+'"]')});
    if(!e||e.disabled)throw Error('Missing field '+${JSON.stringify(label)});
    for(let p=e.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;
    if(e.type==='checkbox')e.checked=${JSON.stringify(value)};else e.value=${JSON.stringify(value)};
    e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}
async function add(s,id,query) {
  await s.clickSelector('[data-add="all"]');await field(s,'Search Add anything…',query);
  await s.wait(`document.querySelector('[data-library="${id}"]')`,'CAM field discovery');
  await s.evaluate(`document.querySelector('[data-library="${id}"]').scrollIntoView({block:'center'})`);
  await s.clickSelector(`[data-library="${id}"]`);await s.wait('document.querySelector(".operation-form")','Typed CAM form');
}
async function button(s,text) {
  await s.evaluate(`(()=>{const b=[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent.trim()===${JSON.stringify(text)});if(!b)throw Error('Missing action');b.click();})()`);
}
function fill(template) {
  return JSON.parse(JSON.stringify(template.document,(key,value)=>value&&typeof value.$fill==='string'?template.fields[value.$fill].default:value));
}

test('Named CAM starter, closed cycle/layout choices and atomic replacement preserve authored intent',{timeout:120000},async()=>{
  const s=await launch({provider:'freecad'});
  try {
    await s.wait('window.studio?.store.get().server','Studio ready');
    const library=await s.evaluate(`window.studio.api.get('/api/studio/adaptor',{id:'freecad'})`);
    const named=library.templates.find(t=>t.id==='named-drilling');assert.ok(named?.document);
    const original=fill(named),legacy=fill(library.templates.find(t=>t.id==='checked-milling'));
    for(const d of [original,legacy]) {
      const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(d))}})`);
      assert.equal(checked.valid,true,JSON.stringify(checked.diagnostics));
    }
    const mixed=structuredClone(original);mixed.tool=legacy.tool;
    const rejected=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(mixed))}})`);
    assert.equal(rejected.valid,false);assert.ok(rejected.diagnostics.some(d=>d.code==='INVALID_MACHINING'));
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',{action:'new',provider:'freecad',name:'Named cutter cycles',document:${JSON.stringify(original)}});await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")','Workbench ready');
    const source=()=>s.evaluate('window.studio.windows.active().window.editor.getValue()');
    const initial=await source();
    await add(s,'document:tools','tools');
    const toolHelp=await s.evaluate('document.querySelector(".operation-form").textContent');
    assert.match(toolHelp,/flatEndmill/);assert.ok(/whole (?:original )?blank|full blank|entire blank/.test(toolHelp),'Legacy default tool help must retain full blank reach');
    await button(s,'Cancel');assert.equal(await source(),initial);
    await add(s,'document:operations','operations');
    for(let i=0;i<2;i++) {
      if(i)await s.evaluate(`(()=>{const b=[...document.querySelectorAll('.operation-form button')].find(b=>b.textContent==='Add operations item');if(!b)throw Error('Missing array add');b.click();})()`);
      const p=`operations[${i}]`;
      await field(s,p+' value kind','1');
      await field(s,p+'.id',i?'small':'large');
      await field(s,'Include '+p+'.tool',true);await field(s,p+'.tool',i?'pilot':'counterbore');
      await field(s,p+'.bottom',i?'0':'6');
      await field(s,p+'.locations value kind',i?'1':'0');
      if(i) {
        for(const key of ['columns','rows']) {await field(s,'Include '+p+'.locations.'+key,true);await field(s,p+'.locations.'+key,'1');}
        await field(s,p+'.locations.xPitch','20');await field(s,p+'.locations.yPitch','10');
        await field(s,'Include '+p+'.locations.centre',true);
        await field(s,p+'.locations.centre[0]','23');await field(s,p+'.locations.centre[1]','-11');
      } else {
        await field(s,p+'.locations.centres[0][0]','23');await field(s,p+'.locations.centres[0][1]','-11');
      }
      await field(s,'Include '+p+'.cycle',true);await field(s,p+'.cycle value kind',i?'2':'0');
      if(i) {
        await field(s,p+'.cycle.peck','1.375');
        const fields=await s.evaluate(`Array.from(document.querySelectorAll('.operation-form [aria-label]')).map(e=>e.getAttribute('aria-label'))`);
        assert.ok(fields.includes(p+'.cycle.peck'));assert.ok(!fields.includes(p+'.cycle.dwell'));
        await field(s,'Include '+p+'.cycle.return',true);await field(s,p+'.cycle.return','1');
      }
    }
    const help=await s.evaluate('document.querySelector(".operation-form").textContent');
    assert.match(help,/source-frame Z/);assert.match(help,/0\.254/);assert.match(help,/G98|initial/);
    if(process.env.FREECAD_CAM_BROWSER_SCREENSHOT)await s.screenshot(process.env.FREECAD_CAM_BROWSER_SCREENSHOT);
    await button(s,'Add operation');
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).operations[1].cycle.peck===1.375','Atomic CAM settings inserted');
    const authored=JSON.parse(await source());assert.deepEqual(authored.tools,original.tools);assert.deepEqual(authored.source,original.source);
    assert.deepEqual(authored.operations.map(o=>o.tool),['counterbore','pilot']);
    assert.equal(authored.operations[1].locations.kind,'grid');assert.equal(authored.operations[1].cycle.return,'retract');
    const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(authored))}})`);
    assert.equal(checked.valid,true,JSON.stringify(checked.diagnostics));
    await s.evaluate('window.studio.windows.active().window.editor.focus()');await s.key('z',{modifiers:2});
    await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).operations[1].cycle.peck===2.25','Atomic undo');
    assert.equal(await source(),initial);assert.deepEqual(s.exceptions,[]);
  } finally {await s.close();}
});
