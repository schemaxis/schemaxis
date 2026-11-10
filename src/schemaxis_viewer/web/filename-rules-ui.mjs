// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import {el,button,note,warning} from './ui.mjs';
import {captureColumns} from './search.mjs';
import {RULE_VERSION,presets,validateRules} from './filename-rules.mjs';
import {automaticSequences} from './automatic-sequences.mjs';
const storageKey='artifact.filename-rules.v1';
const clone=value=>JSON.parse(JSON.stringify(value));

export function createFilenameRules({getItems,onApplied}) {
  let active=[],draft=[],worker=null,timeout=null,revision=0,pending=null;
  try{const saved=JSON.parse(localStorage.getItem(storageKey));if(saved?.version===RULE_VERSION)active=validateRules(saved.rules);}catch{}
  draft=clone(active);
  const heading=el('summary',{},'Filename rules'),list=el('div'),status=el('div',{role:'status','aria-live':'polite'});
  const apply=button('Apply filename rules',()=>applyDraft()),input=el('input',{type:'file',accept:'.json',hidden:true,'aria-label':'Filename rules file'});
  const root=el('details',{class:'filename-rules','aria-label':'Filename rules'},heading,note('Extract capture groups from basenames. Fields become grep.* properties; unmatched files get no value. Changes take effect when applied.'),list,
    el('div',{class:'rule-actions'},button('Add filename rule',()=>add({name:'Custom',pattern:'',enabled:true,columns:[]})),button('Add slice example',()=>add(presets.slices)),button('Add tags example',()=>add(presets.tags)),apply,button('Export filename rules',exportRules),button('Import filename rules',()=>input.click())),input,status);
  function add(rule){draft.push(clone(rule));draw();}
  const updateHeading=()=>{heading.textContent=`Filename rules · ${active.filter(rule=>rule.enabled).length} applied${JSON.stringify(draft)!==JSON.stringify(active)?' · changes pending':''}`;};
  root.addEventListener('input',updateHeading);root.addEventListener('change',updateHeading);
  function draw() {
    updateHeading();
    list.replaceChildren(...draft.map((rule,index)=>{
      const number=index+1,enabled=el('input',{type:'checkbox',checked:rule.enabled,'aria-label':`Rule ${number} enabled`,onchange:event=>{rule.enabled=event.target.checked;}});
      const name=el('input',{value:rule.name,maxlength:100,'aria-label':`Rule ${number} name`,oninput:event=>{rule.name=event.target.value;}});
      const pattern=el('input',{value:rule.pattern,class:'rule-pattern',placeholder:'Pattern with (captures) or (?<name>captures)','aria-label':`Filename rule pattern ${number}`});
      const insensitive=el('input',{type:'checkbox',checked:rule.sensitive===false,'aria-label':`Rule ${number} ignore case`,onchange:event=>{rule.sensitive=!event.target.checked;}});
      const fields=el('div',{class:'rule-columns'});
      const columns=()=>{
        const captures=captureColumns(rule.pattern),previous=new Map(rule.columns.map(c=>[c.index,c]));
        rule.columns=captures.slice(0,20).map(c=>previous.get(c.index)||{index:c.index,key:/^[A-Za-z][A-Za-z0-9]*$/.test(c.name)?c.name:'capture'+c.index,type:'text'});
        fields.replaceChildren(...rule.columns.map(column=>{
          const key=el('input',{value:column.key,'aria-label':`Rule ${number} capture ${column.index} key`,oninput:event=>{column.key=event.target.value;}});
          const type=el('select',{'aria-label':`Rule ${number} capture ${column.index} type`},el('option',{value:'text'},'Text'),el('option',{value:'number'},'Number'),el('option',{value:'tags'},'Split into tags'));type.value=column.type;
          const separator=el('input',{value:column.separator||'.','aria-label':`Rule ${number} capture ${column.index} separator`,maxlength:10,hidden:column.type!=='tags',oninput:event=>{column.separator=event.target.value;}});
          type.onchange=()=>{column.type=type.value;if(type.value==='tags')column.separator=separator.value;separator.hidden=type.value!=='tags';};
          return el('label',{},`${captures[column.index-1].name} → grep.`,key,type,separator);
        }));
      };
      pattern.oninput=()=>{rule.pattern=pattern.value;columns();};columns();
      return el('fieldset',{class:'filename-rule'},el('legend',{},`Rule ${number}`),el('div',{class:'rule-actions'},el('label',{},enabled,'Enabled'),name,el('label',{},insensitive,'Ignore case'),button('Remove rule '+number,()=>{draft.splice(index,1);draw();})),pattern,fields);
    }));
  }
  function cancel() {
    revision++;worker?.terminate();worker=null;clearTimeout(timeout);pending?.(null);pending=null;apply.disabled=false;
  }
  async function calculate(rules) {
    cancel();apply.disabled=true;const token=revision,items=[...getItems()],automatic=automaticSequences(items);
    if(items.length>50000)throw Error('Filename rules are limited to 50,000 files.');
    let result={properties:items.map(()=>({})),counts:[]};
    if(rules.some(rule=>rule.enabled)) {
      result=await new Promise((resolve,reject)=>{
        pending=resolve;worker=new Worker(new URL('./filename-rules-worker.mjs',import.meta.url),{type:'module'});
        const finish=()=>{worker?.terminate();worker=null;clearTimeout(timeout);pending=null;};
        worker.onmessage=({data})=>{if(token!==revision)return;finish();data.error?reject(Error(data.error)):resolve(data);};
        worker.onerror=()=>{if(token!==revision)return;finish();reject(Error('Filename rule worker unavailable.'));};
        timeout=setTimeout(()=>{finish();reject(Error('Filename rules took too long. Simplify the expression; previous applied rules remain unchanged.'));},1500);
        worker.postMessage({records:items.map(item=>({name:item.name,skip:item.isMetadata})),rules});
      });
    }
    if(!result||token!==revision||items.length!==getItems().length||items.some((item,i)=>getItems()[i]!==item))return false;
    items.forEach((item,i)=>{const entry=automatic.get(item.id);item.derivedProperties={...entry.properties,...(item.isMetadata?{}:result.properties[i])};item.autoFamily=entry.family;item.autoOrders=entry.orders;});
    status.replaceChildren(note(result.counts.length?result.counts.map(row=>`${row.name}: ${row.matched} matched files`).join(' · '):'Automatic numeric and alphabetic filename sequences are available when detected.'));
    return true;
  }
  async function applyDraft() {
    try{
      const next=validateRules(draft);apply.disabled=true;
      if(await calculate(next)){active=clone(next);draft=clone(active);try{localStorage.setItem(storageKey,JSON.stringify({version:RULE_VERSION,rules:active}));}catch{}draw();root.open=false;onApplied();}
    }catch(error){root.open=true;status.replaceChildren(warning(error.message));}finally{apply.disabled=false;}
  }
  async function refresh() {
    try{await calculate(active);}catch(error){
      // A rule failing on a new collection must not retain another collection's values.
      const automatic=automaticSequences(getItems());for(const item of getItems()){const entry=automatic.get(item.id);item.derivedProperties=entry.properties;item.autoFamily=entry.family;item.autoOrders=entry.orders;}
      root.open=true;status.replaceChildren(warning(error.message));
    }finally{apply.disabled=false;}
  }
  function exportRules() {
    const data=JSON.stringify({version:RULE_VERSION,rules:active},null,2),url=URL.createObjectURL(new Blob([data],{type:'application/json'}));
    el('a',{href:url,download:'filename-rules.json'}).click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  input.onchange=async()=>{
    try{const file=input.files[0];if(!file)return;if(file.size>65536)throw Error('Rule files are limited to 64 KiB.');const data=JSON.parse(await file.text());if(data.version!==RULE_VERSION)throw Error('Unsupported filename rule file.');draft=validateRules(data.rules);draw();status.replaceChildren(note('Rules loaded. Apply filename rules to use them.'));}
    catch(error){status.replaceChildren(warning(error.message));}finally{input.value='';}
  };
  draw();return {root,refresh,cancel};
}
