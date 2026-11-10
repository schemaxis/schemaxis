// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import {captureColumns} from './search.mjs';
export const RULE_VERSION='artifact.filename-rules/1';
export const presets={
  slices:{name:'Slices',enabled:true,pattern:'[sS]lices[._-]([XYZ])[._-]([0-9]+)',columns:[{index:1,key:'axis',type:'text'},{index:2,key:'number',type:'number'}]},
  tags:{name:'Dot-separated tags',enabled:true,pattern:'-tags-([^-]+)-enclosedByDashes-',columns:[{index:1,key:'tags',type:'tags',separator:'.'}]},
};
export function validateRules(rules) {
  if(!Array.isArray(rules)||rules.length>20)throw Error('Use at most 20 filename rules.');
  return rules.map((rule,i)=>{
    if(!rule||typeof rule.pattern!=='string'||rule.pattern.length>2000||typeof rule.name!=='string'||rule.name.length>100||typeof rule.enabled!=='boolean')throw Error(`Invalid filename rule ${i+1}.`);
    if(rule.enabled&&!rule.pattern)throw Error(`Enter a pattern for rule ${i+1}.`);
    const re=rule.enabled?new RegExp(rule.pattern,rule.sensitive===false?'i':''):null;
    const captures=captureColumns(rule.pattern);
    if(!Array.isArray(rule.columns)||rule.columns.length>20||rule.enabled&&!captures.length)throw Error(`Rule ${i+1} needs at least one capture group.`);
    const seen=new Set();
    const columns=rule.columns.map(column=>{
      if(!column||!Number.isInteger(column.index)||column.index<1||column.index>20||rule.enabled&&column.index>captures.length||! /^[A-Za-z][A-Za-z0-9]*$/.test(column.key)||!['text','number','tags'].includes(column.type)||seen.has(column.key))throw Error(`Invalid or repeated capture field in rule ${i+1}.`);
      seen.add(column.key);
      if(column.type==='tags'&&(typeof column.separator!=='string'||!column.separator||column.separator.length>10))throw Error('A tag separator must contain 1–10 literal characters.');
      return {index:column.index,key:column.key,type:column.type,...(column.type==='tags'?{separator:column.separator}:{})};
    });
    return {name:rule.name,enabled:rule.enabled,pattern:re?re.source:rule.pattern,sensitive:rule.sensitive!==false,columns};
  });
}
export function extractFilenameProperties(records,rules) {
  const compiled=validateRules(rules).filter(rule=>rule.enabled).map(rule=>({...rule,re:new RegExp(rule.pattern,rule.sensitive?'':'i')}));
  const counts=compiled.map(rule=>({name:rule.name,matched:0}));
  const properties=records.map(record=>{
    const result=Object.create(null),name=record.name.split('/').at(-1);if(record.skip)return result;
    for(let i=0;i<compiled.length;i++) {
      const rule=compiled[i],match=rule.re.exec(name);if(!match)continue;counts[i].matched++;
      for(const column of rule.columns) {
        const captured=match[column.index];if(captured===undefined||!captured.trim())continue;
        let values;
        if(column.type==='tags')values=[...new Set(captured.split(column.separator).map(v=>v.trim()).filter(Boolean))];
        else if(column.type==='number'){const n=Number(captured);if(!Number.isFinite(n))continue;values=[n];}
        else values=[captured];
        if(!values.length)continue;
        const key='grep.'+column.key,previous=result[key];
        const combined=[...new Set([...(previous===undefined?[]:Array.isArray(previous)?previous:[previous]),...values])];
        result[key]=column.type==='tags'||previous!==undefined?combined:combined[0];
      }
    }
    return result;
  });
  return {properties,counts};
}
