// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import {parseFilename} from './filename.mjs';
const image=/\.(?:png|jpe?g|webp|gif|bmp|avif|svg)$/i;
export function alphabeticRank(value) {
  return [...value.toUpperCase()].reduce((sum,c)=>sum*26+c.charCodeAt(0)-64,0);
}
// Discover changing token columns within a shared delimiter layout and folder.
// These are naming conventions, never physical coordinates or timestamps.
export function automaticSequences(items) {
  const cohorts=new Map(),result=new Map(items.map(item=>[item.id,{properties:{},orders:[]}]));
  for(const item of items) {
    if(item.isMetadata||!image.test(item.name)||parseFilename(item.name)||/^\d{6}(?:\.\d+)?__/.test(item.name.split('/').at(-1))||item.metadata?.sequence||item.metadata?.spatial?.state==='known')continue;
    const file=item.name.split('/').at(-1),extension=file.slice(file.lastIndexOf('.')),stem=file.slice(0,-extension.length),tokens=[...stem.matchAll(/[A-Za-z]+|[0-9]+/g)];
    if(!tokens.length)continue;
    let end=0;const gaps=tokens.map(token=>{const gap=stem.slice(end,token.index);end=token.index+token[0].length;return gap;});gaps.push(stem.slice(end));
    const types=tokens.map(token=>/^\d+$/.test(token[0])?'number':'letters');
    const key=JSON.stringify([item.scope||'',item.name.slice(0,item.name.lastIndexOf('/')+1),extension.toLowerCase(),gaps,types]);
    if(!cohorts.has(key))cohorts.set(key,[]);
    cohorts.get(key).push({item,tokens:tokens.map(t=>t[0]),types,gaps,extension});
  }
  for(const [identity,rows] of cohorts) {
    if(rows.length<2)continue;
    const first=rows[0],varying=first.tokens.map((_,i)=>new Set(rows.map(row=>row.types[i]==='letters'?row.tokens[i].toUpperCase():row.tokens[i])).size>1);
    const fields=[];let numeric=0,alpha=0;
    for(let i=0;i<first.tokens.length;i++)if(varying[i]) {
      if(fields.length>=4)break;
      if(first.types[i]==='number'&&rows.every(row=>Number.isSafeInteger(Number(row.tokens[i]))))fields.push({column:i,key:'auto.number'+(++numeric),kind:'numeric'});
      else if(rows.every(row=>/^[A-Z]{1,4}$/.test(row.tokens[i])||/^[a-z]$/.test(row.tokens[i])))fields.push({column:i,key:'auto.letters'+(++alpha),kind:'alphabetic'});
    }
    if(!fields.length)continue;
    const family=first.tokens.map((token,i)=>first.gaps[i]+(varying[i]?'{'+(fields.find(f=>f.column===i)?.key.slice(5)||'text')+'}':token)).join('')+first.gaps.at(-1)+first.extension;
    for(const row of rows) {
      const entry=result.get(row.item.id);entry.family=family;entry.properties['auto.sequence']=family;
      for(const field of fields) {
        const raw=row.tokens[field.column],value=field.kind==='numeric'?Number(raw):raw;
        entry.properties[field.key]=value;
        entry.properties[field.kind==='numeric'?'auto.numericSequence':'auto.alphabeticSequence']=family;
        entry.orders.push({id:identity+'|'+field.key,label:`${field.kind} · ${family} · ${field.key}`,kind:field.kind,displayValue:raw,value:field.kind==='numeric'?value:alphabeticRank(raw)});
      }
    }
  }
  return result;
}
