// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import {itemProperties} from './filename.mjs';
import {natural} from './model.mjs';

export function groupValues(item,key) {
  if(key==='folder')return [(item.rootLabel||item.scope||'Files')+'/'+(item.relativePath||item.name).split('/').slice(0,-1).join('/')];
  if(key==='fileType')return [item.kind];
  const value=itemProperties(item)[key];
  return value===undefined||Array.isArray(value)&&!value.length?['(unspecified)']:[...new Set((Array.isArray(value)?value:[value]).map(v=>JSON.stringify(v)))];
}
// Nodes retain unique membership even when a list-valued property overlaps.
export function groupTree(items,keys,path=[]) {
  if(!keys.length)return [];
  const nodes=new Map();
  for(const item of items.filter(i=>!i.isMetadata))for(const token of groupValues(item,keys[0])) {
    if(!nodes.has(token))nodes.set(token,{label:token==='(unspecified)'?token:keys[0]==='folder'||keys[0]==='fileType'?token:JSON.parse(token),path:[...path,[keys[0],token]],items:[]});
    nodes.get(token).items.push(item);
  }
  return [...nodes.values()].sort((a,b)=>natural(a.label,b.label)).map(node=>({...node,children:groupTree(node.items,keys.slice(1),node.path)}));
}
export function inGroupPath(item,path) {
  return path.every(([key,value])=>groupValues(item,key).includes(value));
}
export function photoSeries(items,id='photos') {
  const photos=items.filter(i=>i.kind==='image').sort((a,b)=>natural(a.name,b.name));
  return {id:'photos|'+id,axis:'index',units:'',inferred:false,photoSeries:true,time:'',items:photos.map((item,index)=>({...item,sequence:{axis:'index',value:index+1,id:'Photo series',label:'Photo series · filename order'}}))};
}
