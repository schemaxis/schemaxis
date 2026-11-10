// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {readdir,readFile,writeFile,mkdtemp,rm,mkdir} from 'node:fs/promises';
import {join,relative} from 'node:path';
import {homedir} from 'node:os';
import {launch} from '../../src/schemaxis/studio_ui/tests/fixtures/editor/cdp.mjs';
const root=fileURLToPath(new URL('../../src/schemaxis_viewer/web/',import.meta.url));
const sample=fileURLToPath(new URL('../../examples/viewer-test/',import.meta.url));
const click=(s,text)=>s.evaluate(`(()=>{const n=[...document.querySelectorAll('button')].find(n=>n.textContent===${JSON.stringify(text)});const details=n.closest('.filename-rules');if(details)details.open=true;n.click();})()`);
const change=(s,label,value,event='change')=>s.evaluate(`(()=>{const n=document.querySelector('[aria-label="'+${JSON.stringify(label)}+'"]');const details=n.closest('.filename-rules');if(details)details.open=true;n.value=${JSON.stringify(value)};n.dispatchEvent(new Event(${JSON.stringify(event)}));})()`);
const count=s=>s.evaluate('artifactViewer.groups.reduce((n,g)=>n+g.items.length,0)');
async function records(){
  const result=[];
  async function visit(path){for(const row of await readdir(path,{withFileTypes:true})){const file=join(path,row.name);if(row.isDirectory())await visit(file);else{const bytes=await readFile(file);result.push({name:relative(sample,file),relativePath:relative(sample,file),scope:'sample',rootLabel:'sample',size:bytes.length,url:`data:${file.endsWith('.png')?'image/png':'text/plain'};base64,${bytes.toString('base64')}`});}}}
  await visit(join(sample,'legacy'));await visit(join(sample,'folders'));return result;
}
async function open(s){await s.wait('Boolean(window.artifactViewer)','ready');await s.evaluate(`artifactViewer.openRecords(${JSON.stringify(await records())})`);}
async function rules(s){await s.evaluate('document.querySelector(".filename-rules").open=true');await click(s,'Add slice example');await click(s,'Add tags example');await click(s,'Add filename rule');await change(s,'Filename rule pattern 3','file-(?<code>[A-Z]+)-(?<index>[0-9]+)-','input');await change(s,'Rule 3 capture 2 type','number');await click(s,'Apply filename rules');await s.wait('document.querySelector(".filename-rules>summary").textContent.includes("3 applied")','rules applied');}
async function shot(s,name){if(process.env.VIEWER_SCREENSHOTS){await mkdir(process.env.VIEWER_SCREENSHOTS,{recursive:true});await s.screenshot(join(process.env.VIEWER_SCREENSHOTS,name+'.png'));}}

test('folder grouping coexists with detected numeric and alphabetic filename sequences',async()=>{
  const s=await launch({root,path:'/index.html',width:1550,height:1050});
  try{
    await open(s);
    await change(s,'Grouping level 1','folder');await change(s,'Grouping level 2','auto.letters1');
    assert.ok(await s.evaluate(`[...document.querySelectorAll('#library button')].some(n=>n.textContent==='sample/folders/alpha/icons · 4')`));
    assert.ok(await s.evaluate(`[...document.querySelectorAll('#library button')].some(n=>n.textContent==='sample/folders/beta/icons · 4')`));
    await click(s,'sample/folders/alpha/icons · 4');assert.equal(await count(s),4);
    assert.equal(await s.evaluate('artifactViewer.groups[0].sequences.length'),2);
    await s.evaluate('document.querySelector("[data-mode=sequences]").click()');
    await s.evaluate(`[...document.querySelectorAll('.sequence-select button')].find(n=>n.textContent.includes('alphabetic')).click()`);
    await change(s,'INDEX slice slider','0','input');
    await s.evaluate(`document.querySelector('[aria-label="INDEX next frame"]').click()`);
    assert.match(await s.evaluate('document.querySelector(".sequence-footer").textContent'),/Letter = AAB/);
    assert.match(await s.evaluate('document.querySelector("#location").textContent'),/Letter = AAB/);
    await shot(s,'automatic-alphabetic');
    await click(s,'All groups');await change(s,'Grouping level 1','auto.numericSequence');
    assert.ok(await s.evaluate(`[...document.querySelectorAll('#library button')].some(n=>n.textContent.includes('file-{letters1}-{number1}-name.png · 8'))`));
    assert.equal(s.exceptions.length,0,JSON.stringify(s.exceptions));
  }finally{await s.close();}
});

test('editable capture rules, tag checklists, hierarchy, persistence and rule-file round trip',async()=>{
  const temporary=await mkdtemp(join(homedir(),'artifact-rule-test-'));
  const s=await launch({root,path:'/index.html',width:1550,height:1050});
  try{
    await open(s);await rules(s);
    assert.equal(await s.evaluate('artifactViewer.items.filter(i=>i.derivedProperties["grep.axis"]).length'),4);
    assert.equal(await s.evaluate('artifactViewer.items.some(i=>/model\\.png$|error\\.log$/.test(i.name)&&Object.keys(i.derivedProperties).some(k=>k.startsWith("grep.")))'),false);
    await change(s,'Filename grep.axis','"X"');assert.equal(await count(s),2);
    await change(s,'Filename grep.number','1');assert.equal(await count(s),1);
    await click(s,'Clear properties');await change(s,'Grouping level 1','grep.axis');
    assert.ok(await s.evaluate(`[...document.querySelectorAll('#library button')].some(n=>n.textContent==='X · 2')`));
    await change(s,'Grouping level 1','');
    await s.evaluate(`document.querySelector('[data-facet-key="grep.tags"]').open=true;document.querySelector('[aria-label="Include grep.tags: red"]').click()`);
    assert.equal(await count(s),2);
    await s.evaluate(`document.querySelector('[aria-label="Include grep.tags: blue"]').click()`);assert.equal(await count(s),3);
    assert.equal(await s.evaluate('document.querySelector("[data-facet-key=\\"grep.tags\\"]").open'),true);
    await change(s,'Filename grep.code','"AAA"');assert.equal(await count(s),1,'tag OR is intersected with the code filter');
    await shot(s,'grep-tags-checklist');
    await click(s,'Any grep.tags');assert.equal(await count(s),3);await click(s,'Clear properties');
    await s.evaluate('window.oldCreateURL=URL.createObjectURL;URL.createObjectURL=blob=>{window.exportedRules=blob.text();return oldCreateURL(blob);};');
    await click(s,'Export filename rules');const exported=await s.evaluate('window.exportedRules');
    await s.evaluate('URL.createObjectURL=window.oldCreateURL');
    const data=JSON.parse(exported);assert.equal(data.version,'artifact.filename-rules/1');assert.equal(data.rules.length,3);assert.equal(data.rules[2].columns[1].type,'number');
    await change(s,'Grouping level 1','grep.tags');
    await s.evaluate('document.querySelector("[aria-label=\\"Rule 2 enabled\\"]").click()');await click(s,'Apply filename rules');
    await s.wait('!artifactViewer.items.some(i=>i.derivedProperties["grep.tags"])','disabled rule removes values');
    assert.equal(await s.evaluate('document.querySelector("[aria-label=\\"Grouping level 1\\"]").value'),'','removed derived group returns to an available grouping');
    await s.open('/index.html');await open(s);
    assert.match(await s.evaluate('document.querySelector(".filename-rules>summary").textContent'),/2 applied/);
    assert.equal(await s.evaluate('artifactViewer.items.some(i=>i.derivedProperties["grep.tags"])'),false);
    const file=join(temporary,'filename-rules.json');await writeFile(file,exported);
    const {root:document}=await s.send('DOM.getDocument');const {nodeId}=await s.send('DOM.querySelector',{nodeId:document.nodeId,selector:'.filename-rules input[type=file]'});
    await s.send('DOM.setFileInputFiles',{nodeId,files:[file]});
    await s.wait('document.querySelector(".filename-rules").textContent.includes("Rules loaded")','imported');await click(s,'Apply filename rules');
    await s.wait('artifactViewer.items.filter(i=>i.derivedProperties["grep.tags"]).length===4','imported rules reapplied');
    assert.equal(s.exceptions.length,0,JSON.stringify(s.exceptions));
  }finally{await s.close();await rm(temporary,{recursive:true,force:true});}
});

test('expensive and invalid filename regexes retain previous values and never block the UI',async()=>{
  const s=await launch({root,path:'/index.html',width:1550,height:1050});
  try{
    await open(s);await s.evaluate('document.querySelector(".filename-rules").open=true');await click(s,'Add slice example');await click(s,'Apply filename rules');
    await s.wait('artifactViewer.items.some(i=>i.derivedProperties["grep.axis"]==="X")','initial values');
    const first=(await records()).find(r=>r.name.endsWith('.png'));
    await s.evaluate(`artifactViewer.openRecords([${JSON.stringify({...first,name:'a'.repeat(240)+'!.png'})}],{replace:false})`);
    await change(s,'Filename rule pattern 1','^(a+)+$','input');await click(s,'Apply filename rules');
    await s.evaluate('document.querySelector("#theme").click()');
    await s.wait('document.querySelector(".filename-rules").textContent.includes("took too long")','bounded regex execution');
    assert.equal(await s.evaluate('artifactViewer.items.filter(i=>i.derivedProperties["grep.axis"]).length'),4);
    await change(s,'Filename rule pattern 1','(?','input');await click(s,'Apply filename rules');
    assert.equal(await s.evaluate('artifactViewer.items.filter(i=>i.derivedProperties["grep.axis"]).length'),4);
    await s.evaluate(`artifactViewer.openRecords([${JSON.stringify({...first,name:'model.png'})}])`);
    assert.equal(await s.evaluate('artifactViewer.items.some(i=>Object.keys(i.derivedProperties).some(k=>k.startsWith("grep.")))'),false);
    assert.equal(s.exceptions.length,0,JSON.stringify(s.exceptions));
  }finally{await s.close();}
});
