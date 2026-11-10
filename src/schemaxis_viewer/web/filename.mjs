// Copyright (C) 2026 David L. F. Gaden.
// SPDX-License-Identifier: Apache-2.0
// Filename hints are descriptive data, never spatial evidence.
const number=/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:e-?[0-9]+)?$/;
function scalar(raw) {
  if(raw==='list')throw Error('Reserved list marker');
  if(number.test(raw)){const value=Number(raw);if(!Number.isFinite(value))throw Error('Nonfinite number');return value;}
  if(raw==='true')return true;if(raw==='false')return false;if(raw==='null')return null;
  if(raw==='.empty.')return '';
  const bytes=[];
  for(let i=0;i<raw.length;){
    const escape=/^\.x([0-9A-F]{2})\./.exec(raw.slice(i));
    if(escape){bytes.push(parseInt(escape[1],16));i+=5;}
    else if(/[A-Za-z0-9-]/.test(raw[i]))bytes.push(raw.charCodeAt(i++));
    else throw Error('Invalid filename text');
  }
  if(!bytes.length)throw Error('Empty token');
  return new TextDecoder('utf-8',{fatal:true}).decode(new Uint8Array(bytes));
}
export function parseFilename(name) {
  const file=name.split('/').at(-1);
  if(/\.(?:metadata\.json|scxmeta(?:\.json)?|METADATA)$/i.test(file))return null;
  const match=/^([0-9]{6})(?:\.([0-9]+))?((?:__.*)?)\.([A-Za-z][A-Za-z0-9]*)$/.exec(file);
  if(!match)return null;
  const properties=Object.create(null);
  try {
    for(const field of match[3]?match[3].slice(2).split('__'):[]) {
      const parts=field.split('_'),key=parts.shift();
      if(!/^[A-Za-z][A-Za-z0-9]*$/.test(key)||Object.hasOwn(properties,key)||!parts.length) return null;
      if(parts[0]==='list')properties[key]=parts.slice(1).map(scalar);
      else {if(parts.length!==1)return null;properties[key]=scalar(parts[0]);}
    }
  }catch{return null;}
  // Keep worker identifiers as strings: .2 and .20 must never become decimals.
  return {index:Number(match[1]),worker:match[2]??null,properties,extension:match[4].toLowerCase()};
}
// Checked companion properties override descriptive filename hints.
export function itemProperties(item) {
  const p=Object.assign(Object.create(null),(item.filename||parseFilename(item.name))?.properties);
  const metadata=item.metadata;
  if(metadata?.properties && typeof metadata.properties==='object' && !Array.isArray(metadata.properties))
    for(const [key,value] of Object.entries(metadata.properties))
      if((Array.isArray(value)?value:[value]).every(v=>v===null||['string','boolean'].includes(typeof v)||typeof v==='number'&&Number.isFinite(v)))p[key]=value;
  if(typeof metadata?.group==='string')p.group=metadata.group;
  if(typeof metadata?.spatial?.frame==='string')p.frameName=metadata.spatial.frame;
  if(typeof metadata?.identity?.scene==='string')p.scene=metadata.identity.scene;
  Object.assign(p,item.derivedProperties);
  return p;
}
export function propertyFacets(items) {
  const facets=new Map();
  for(const item of items) {
    if(item.isMetadata)continue;
    for(const [key,value] of Object.entries(itemProperties(item)))for(const member of Array.isArray(value)?value:[value]) {
      if(!facets.has(key))facets.set(key,new Map());
      const values=facets.get(key),token=JSON.stringify(member);
      if(!values.has(token))values.set(token,{value:member,ids:new Set()});
      values.get(token).ids.add(item.id??item.name);
    }
  }
  return facets;
}
export function matchesProperties(item,filters) {
  const properties=itemProperties(item);
  return [...filters].every(([key,value])=>properties&&Object.hasOwn(properties,key)&&
    (Array.isArray(properties[key])?properties[key]:[properties[key]]).some(v=>value instanceof Set?value.has(JSON.stringify(v)):JSON.stringify(v)===value));
}
export function filenameSequence(parsed) {
  const p=parsed.properties;
  const spatial=p.kind==='slice'&&typeof p.axis==='string'&&/^[XYZ]$/i.test(p.axis)&&typeof p.pos==='number';
  const axis=spatial?p.axis.toLowerCase():typeof p.frame==='number'?'index':typeof p.time==='number'?'time':null;
  if(!axis)return null; // An artifact ordinal never defines an animation.
  const value=spatial?p.pos:axis==='time'?p.time:p.frame;
  const ignored=new Set(['axis','pos','frame','time',...(spatial?['scene']:[])]);
  const entries=Object.entries(p).filter(([key])=>!ignored.has(key)).sort(([a],[b])=>a.localeCompare(b));
  const id=JSON.stringify(entries),label=entries.map(([key,value])=>`${key}=${typeof value==='string'?value:JSON.stringify(value)}`).join(' · ');
  return {axis,value,id,label,units:typeof p.units==='string'?p.units:'',inferred:true};
}
