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
  await s.wait(`document.querySelector('[data-library="${id}"]')`,'Physical CAM discovery');
  await s.evaluate(`document.querySelector('[data-library="${id}"]').scrollIntoView({block:'center'})`);
  await s.clickSelector(`[data-library="${id}"]`);await s.wait('document.querySelector(".operation-form")','Physical CAM form');
}
async function action(s,text) {
  await s.evaluate(`(()=>{const b=[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent.trim()===${JSON.stringify(text)});if(!b)throw Error('Missing action');b.click();})()`);
}

test('Physical CAM starter and reduced native profile authoring are closed atomic choices',{timeout:120000},async()=>{
 const s=await launch({provider:'freecad'});
 try {
  await s.wait('window.studio?.store.get().server','Studio ready');
  const library=await s.evaluate(`window.studio.api.get('/api/studio/adaptor',{id:'freecad'})`);
  const template=library.templates.find(t=>t.id==='physical-drilling');assert.ok(template?.document);
  const original=JSON.parse(JSON.stringify(template.document,(k,v)=>v&&typeof v.$fill==='string'?template.fields[v.$fill].default:v));
  const validated=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(original))}})`);
  assert.equal(validated.valid,true,JSON.stringify(validated.diagnostics));
  await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',{action:'new',provider:'freecad',name:'Physical pointed tools',document:${JSON.stringify(original)}});await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
  await s.wait('document.querySelector("[data-add=all]")','Workbench ready');
  await s.wait(`document.querySelector('[data-library="physical-drilling"]')`,'Matching physical starter visible in its CAM Workbench');
  assert.equal(await s.evaluate('document.querySelector(".wb-library").textContent.includes("no packaged library")'),false);
  const source=()=>s.evaluate('window.studio.windows.active().window.editor.getValue()');const initial=await source();
  await add(s,'document:tools','tools');await field(s,'tools[0] value kind','1');
  for(const [key,value] of Object.entries({id:'pilot',diameter:2,tipAngle:90,cuttingReach:3,length:16,rpm:5000,feed:400,plunge:100}))await field(s,'tools[0].'+key,String(value));
  await field(s,'Include tools[0].shankDiameter',true);await field(s,'tools[0].shankDiameter','1');
  await field(s,'Include tools[0].holder',true);await field(s,'tools[0].holder.stickOut','12');
  await field(s,'tools[0].holder.steps[0].diameter','4');await field(s,'tools[0].holder.steps[0].length','6');
  const help=await s.evaluate('document.querySelector(".operation-form").textContent');
  assert.match(help,/SCXReducedDrill/);assert.match(help,/physical tip|physical cone|physical bit/);assert.match(help,/holder/i);
  if(process.env.FREECAD_CAM_PHYSICAL_SCREENSHOT)await s.screenshot(process.env.FREECAD_CAM_PHYSICAL_SCREENSHOT);
  await action(s,'Add operation');
  await s.wait('JSON.parse(window.studio.windows.active().window.editor.getValue()).tools[0].shankDiameter===1','Reduced tool inserted');
  const authored=JSON.parse(await source());assert.deepEqual(authored.source,original.source);assert.deepEqual(authored.operations,original.operations);assert.deepEqual(authored.setup,original.setup);
  const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(authored))}})`);assert.equal(checked.valid,true,JSON.stringify(checked.diagnostics));
  await s.evaluate('window.studio.windows.active().window.editor.focus()');await s.key('z',{modifiers:2});
  await s.wait('window.studio.windows.active().window.editor.getValue()==='+JSON.stringify(initial),'Atomic undo');assert.equal(await source(),initial);
  await add(s,'document:setup','setup');await field(s,'Include setup.toolClearance',true);await field(s,'setup.toolClearance value kind','1');await field(s,'setup.toolClearance.minimumSeparation','.3');
  const policy=await s.evaluate('document.querySelector(".operation-form").textContent');assert.match(policy,/prefix stock|remaining stock|current prefix/);assert.match(policy,/positive/);
  await action(s,'Cancel');assert.equal(await source(),initial);assert.deepEqual(s.exceptions,[]);
 } finally {await s.close();}
});
