// Framework-independent collection model. Metadata is evidence, never executable input.
import {parseFilename,filenameSequence} from './filename.mjs';
export const VERSION = 'schemaxis.artifact-metadata/1';
export const natural = (a, b) => String(a).localeCompare(String(b), 'en', {numeric: true});
export const basename = name => name.split('/').at(-1);
export const dirname = name => name.includes('/') ? name.slice(0, name.lastIndexOf('/')) : '';
const sideSuffix = /(?:\.metadata\.json|\.scxmeta(?:\.json)?|\.METADATA)$/i;
const finite = x => typeof x === 'number' && Number.isFinite(x);
const vector = x => Array.isArray(x) && x.length === 3 && x.every(finite);
export function kind(name) {
  const ext = name.toLowerCase().split('.').at(-1);
  if (['png','jpg','jpeg','webp','gif','bmp','avif','svg'].includes(ext)) return 'image';
  if (['stl','obj'].includes(ext)) return 'mesh';
  if (['mp4','webm','ogv','mov'].includes(ext)) return 'video';
  if (['mp3','wav','ogg','flac','m4a','aac'].includes(ext)) return 'audio';
  if (['csv','tsv'].includes(ext)) return 'table';
  if (['txt','log','json','yaml','yml','xml','md','py','c','h','cpp','js','mjs','sh','foam','vtk','vtu','vtp','vts','html','css','dat'].includes(ext) || !name.includes('.')) return 'text';
  return 'file';
}
const sub = (a,b) => a.map((v,i)=>v-b[i]);
const cross = (a,b) => [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const norm = a => Math.hypot(...a);
export function cornersFor(metadata) {
  const s = metadata?.spatial;
  // A camera focal plane is useful context, but is not a registered slice.
  if (s?.state !== 'known' || s.mapping !== 'pixel-edge-rays-to-slice-plane') return null;
  if ((s.pixelOrigin && s.pixelOrigin!=='top-left') || (s.rowDirection && s.rowDirection!=='down')) return null;
  const c = s.corners;
  if (!Array.isArray(c) || ![3,4].includes(c.length) || !c.every(vector)) return null;
  const order = s.cornerOrder;
  if (!Array.isArray(order)) return null;
  const names = ['top-left','top-right','bottom-right','bottom-left'];
  let ordered;
  if (c.length === 3) {
    const tl = c[order.indexOf('top-left')], tr = c[order.indexOf('top-right')], bl = c[order.indexOf('bottom-left')];
    if (!tl || !tr || !bl) return null;
    ordered = [tl,tr,tr.map((v,i)=>v+bl[i]-tl[i]),bl];
  } else {
    if (new Set(order).size !== 4 || !names.every(n=>order.includes(n))) return null;
    ordered = names.map(n=>c[order.indexOf(n)]);
  }
  const u = sub(ordered[1],ordered[0]), v = sub(ordered[3],ordered[0]), n = cross(u,v);
  const scale = Math.max(norm(u),norm(v));
  if (scale === 0 || norm(n) < scale*scale*1e-10) return null;
  if (Math.abs(sub(ordered[2],ordered[0]).reduce((s,x,i)=>s+x*n[i],0)) > norm(n)*scale*1e-7) return null;
  // Convex, consistent winding prevents folded/self-intersecting textures.
  if (!ordered.every((p,i)=>cross(sub(ordered[(i+1)%4],p),sub(ordered[(i+2)%4],ordered[(i+1)%4])).reduce((s,x,j)=>s+x*n[j],0)>0)) return null;
  return ordered;
}
export function spatialAxis(metadata) {
  const plane = metadata?.spatial?.plane;
  if (!plane || metadata?.spatial?.state !== 'known' || !vector(plane.normal) || !vector(plane.origin) || metadata?.spatial?.mapping === 'camera-focal-plane') return null;
  const length = norm(plane.normal);
  const index = plane.normal.findIndex(v => Math.abs(v)/length > 1-1e-8);
  return index < 0 ? null : {axis:'xyz'[index],value:plane.origin[index]};
}
export function inferName(name) {
  const parsed=parseFilename(name);
  if(parsed){const sequence=filenameSequence(parsed);return sequence&&{...sequence,prefix:sequence.id};}
  if(/^[0-9]{6}(?:\.[0-9]+)?__/.test(basename(name)))return null;
  const file = basename(name).replace(/\.[^.]+$/, '');
  // Explicit axis token is required for spatial inference; numbered images are
  // index sequences, never assigned invented physical coordinates.
  const axis = /(^|[_\-. ])([xyz])(?:[_\- ]?slice)?[_= ]?(-?\d+(?:\.\d+)?)(?=$|[_\- ])/i.exec(file);
  if (axis) return {axis:axis[2].toLowerCase(), value:Number(axis[3]),
    prefix:file.slice(0,axis.index)+axis[1]+file.slice(axis.index+axis[0].length), inferred:true};
  const number = /(-?\d+(?:\.\d+)?)(?!.*\d)/.exec(file);
  if (number) return {axis:'index',value:Number(number[1]),prefix:file.slice(0,number.index)+'#'+file.slice(number.index+number[0].length),inferred:true};
  return null;
}
export function sequenceInfo(item) {
  const explicit = item.metadata?.sequence;
  if (explicit && typeof explicit.id === 'string' && ['x','y','z','time','index'].includes(explicit.axis) && finite(explicit.value))
    return {axis:explicit.axis,value:explicit.value,id:explicit.id,units:typeof explicit.units==='string'?explicit.units:'',inferred:false};
  const observed = spatialAxis(item.metadata);
  const inferred = inferName(item.name);
  const identity=item.metadata?.identity;
  const named=item.filename||parseFilename(item.name),hint=named&&filenameSequence(named);
  const identityId=identity&&typeof identity.writer==='string'?`${identity.writer} · appearance ${identity.appearance??0} · camera ${identity.camera??0}`:null;
  if (observed) return {...observed,id:hint?.id||identityId||inferred?.prefix || 'slice',label:hint?.label,units:item.metadata.spatial.units || '',inferred:false};
  if (finite(item.metadata?.viewTime)) return {axis:'time',value:item.metadata.viewTime,id:[identityId||inferred?.prefix||'time',JSON.stringify(identity?.indices||{})].join(' · '),units:'',inferred:false};
  return inferred && {...inferred,id:inferred.prefix,units:''};
}
export function groupKey(item) {
  if (typeof item.metadata?.group === 'string' && item.metadata.group.trim()) return [item.scope,item.metadata.group].filter(Boolean).join(' / ');
  const named=item.filename||parseFilename(item.name);
  if(named){const p=named.properties;return [dirname(item.name),p.kind==='slice'?'Slices':p.scene||p.kind||'Files',p.var?(typeof p.var==='string'?p.var:JSON.stringify(p.var)):''].filter(Boolean).join(' / ');}
  if(typeof item.metadata?.identity?.scene==='string') return [dirname(item.name),item.metadata.identity.scene].filter(Boolean).join(' / ');
  if(item.autoFamily)return [dirname(item.name),item.autoFamily].filter(Boolean).join(' / ');
  const info = sequenceInfo(item);
  const prefix = (inferName(item.name)?.prefix || '').replace(/[_\-. ]+$/,'').replace(/^[_\-. ]+/,'');
  return [dirname(item.name),prefix || (info ? 'Slices' : 'Files')].filter(Boolean).join(' / ');
}
export function buildGroups(items,{groupBy='auto'}={}) {
  const groups = new Map();
  for (const item of items) {
    if (item.isMetadata) continue;
    item.filename=parseFilename(item.name);
    item.kind = kind(item.name);
    item.sequence = item.kind === 'image' ? sequenceInfo(item) : null;
    if(item.sequence?.axis==='index'&&item.sequence.inferred&&item.autoOrders?.some(order=>order.kind==='numeric'))item.sequence=null;
    const hint=item.filename&&filenameSequence(item.filename);
    item.filenameWarning=hint&&item.sequence&&!item.sequence.inferred&&(hint.axis!==item.sequence.axis||hint.value!==item.sequence.value)?'Filename sequence hints differ from checked metadata. Metadata controls sequence placement and order.':null;
    const key = groupBy==='all'?'All selected files':groupBy==='folder'?(dirname(item.name)||'Selected files'):groupKey(item);
    if (!groups.has(key)) groups.set(key,{id:key,name:key,items:[],visible:true,sequences:[]});
    groups.get(key).items.push(item);
  }
  for (const group of groups.values()) {
    group.items.sort((a,b)=>natural(a.name,b.name));
    const seqs = new Map();
    for (const item of group.items) {
      const s = item.sequence;
      if (!s) continue;
      // Distinct times and coordinate frames must not be spliced into one stack.
      const time = s.axis==='time' ? '' : item.metadata?.viewTime ?? item.filename?.properties.time ?? '';
      const key = JSON.stringify([group.id,item.scope||dirname(item.name),s.id,s.axis,time,item.metadata?.spatial?.frame||'',s.units]);
      if (!seqs.has(key)) seqs.set(key,{id:key,axis:s.axis,units:s.units,inferred:s.inferred,items:[],time});
      seqs.get(key).items.push(item);
    }
    // A fixed spatial coordinate across several observed view times is also a
    // temporal stack. Copies retain artifact IDs but carry the selected axis.
    const temporal=new Map();
    for(const item of group.items) {
      const time=item.metadata?.viewTime??item.filename?.properties.time;
      if(item.kind!=='image'||item.sequence?.axis==='time'||!finite(time))continue;
      const observedCoordinate=spatialAxis(item.metadata),coordinate=observedCoordinate||(['x','y','z'].includes(item.sequence?.axis)?item.sequence:null),identity=item.metadata?.identity||{};
      const id=[item.sequence?.id||'time',coordinate?`${coordinate.axis}=${coordinate.value}`:'',JSON.stringify(identity.indices||{})].join(' · ');
      const key=JSON.stringify([group.id,item.scope||dirname(item.name),id,item.metadata?.spatial?.frame||'',item.metadata?.spatial?.units||'']);
      if(!temporal.has(key))temporal.set(key,{id:'time|'+key,axis:'time',units:'',inferred:false,items:[],time:''});
      const inferred=!finite(item.metadata?.viewTime);
      temporal.get(key).items.push({...item,sequence:{axis:'time',value:time,id,units:'',inferred}});
      temporal.get(key).inferred ||= inferred;
    }
    for(const [key,value] of temporal)if(new Set(value.items.map(i=>i.sequence.value)).size>1)seqs.set('time|'+key,value);
    group.sequences = [...seqs.values()].filter(s=>new Set(s.items.map(i=>i.sequence.value)).size>1).map(s=>{
      s.items.sort((a,b)=>a.sequence.value-b.sequence.value || natural(a.name,b.name));
      return s;
    }).sort((a,b)=>natural(a.axis,b.axis)||natural(a.id,b.id));
    const automatic=new Map();
    for(const item of group.items)for(const order of item.autoOrders||[]) {
      const key='automatic|'+group.id+'|'+order.id;
      if(!automatic.has(key))automatic.set(key,{id:key,axis:'index',units:'',inferred:true,autoKind:order.kind,time:'',items:[]});
      automatic.get(key).items.push({...item,sequence:{axis:'index',value:order.value,displayValue:order.displayValue,orderKind:order.kind,id:order.label,label:order.label,inferred:true}});
    }
    for(const series of automatic.values())if(new Set(series.items.map(i=>i.sequence.value)).size>1) {
      series.items.sort((a,b)=>a.sequence.value-b.sequence.value||natural(a.name,b.name));group.sequences.push(series);
    }
    group.range = filenameRange(group.items);
  }
  return [...groups.values()].sort((a,b)=>natural(a.name,b.name));
}
export function filenameRange(items) {
  if (!items.length) return '';
  const names = items.map(i=>basename(i.name));
  if (names.length===1) return names[0];
  let prefix=names[0], suffix=names[0];
  for (const name of names) {
    while (!name.startsWith(prefix)) prefix=prefix.slice(0,-1);
    while (!name.endsWith(suffix)) suffix=suffix.slice(1);
  }
  if(prefix.length+suffix.length>=names[0].length) suffix='';
  const middle = names.map(n=>n.slice(prefix.length,suffix?-suffix.length:undefined));
  return `${prefix}[${middle[0]}…${middle.at(-1)}]${suffix} · ${names.length} files`;
}
export function nearestIndex(items, value) {
  return items.reduce((best,item,i)=>Math.abs(item.sequence.value-value)<Math.abs(items[best].sequence.value-value)?i:best,0);
}
export function advance(index,direction,length,mode) {
  if(length<2) return {index:0,direction,stopped:true};
  let next=index+direction;
  if(next>=0 && next<length) return {index:next,direction,stopped:false};
  if(mode==='repeat') return {index:direction>0?0:length-1,direction,stopped:false};
  if(mode==='oscillate') return {index:index-direction,direction:-direction,stopped:false};
  return {index,direction,stopped:true};
}
export function relativeItem(items,item,reference) {
  if(typeof reference!=='string' || reference.startsWith('/') || reference.includes('\\') || /^[a-z]+:/i.test(reference)) return null;
  const parts = [...dirname(item.name).split('/').filter(Boolean)];
  for(const part of reference.split('/')) {
    if(part==='..') {if(!parts.length) return null; parts.pop();}
    else if(part && part!=='.') parts.push(part);
  }
  return items.find(i=>i.name===parts.join('/')) || null;
}
export async function attachMetadata(items) {
  const warnings=[];
  const byName=new Map(items.map(i=>[i.name,i]));
  const recognised=new Set();
  for (const sidecar of items.filter(i=>sideSuffix.test(i.name))) {
    const target=byName.get(sidecar.name.replace(sideSuffix,''));
    try {
      if(sidecar.size>2*1024*1024) throw Error('sidecar exceeds 2 MiB');
      const data=JSON.parse(await sidecar.text());
      if(data?.version!==VERSION) continue; // Extension alone does not establish Schemaxis ownership.
      sidecar.isMetadata=true;
      if(!target) throw Error('matching artifact is absent');
      if(recognised.has(target.name)){delete target.metadata;delete target.metadataStatus;target.metadataConflict=true;throw Error('multiple recognised sidecars; placement is ambiguous and not applied');}
      recognised.add(target.name);
      if(data.artifact?.file!==basename(target.name)) throw Error('artifact filename does not match');
      if(!/^[a-f0-9]{64}$/i.test(data.artifact?.sha256||'')) throw Error('artifact SHA-256 is absent or invalid');
      // WebCrypto needs the whole buffer. Do not silently omit verification for huge artifacts.
      if(target.size>256*1024*1024) throw Error('artifact exceeds browser hash limit (256 MiB); metadata not applied');
      const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',await target.bytes()))].map(n=>n.toString(16).padStart(2,'0')).join('');
      if(hash!==data.artifact.sha256.toLowerCase()) throw Error('artifact SHA-256 mismatch; metadata not applied');
      if(target.metadata) throw Error('multiple recognised sidecars for the same artifact');
      target.metadata=data;
      target.metadataStatus='SHA-256 matched';
      if(data.spatial?.corners && !cornersFor(data)) {
        target.spatialWarning=data.spatial.mapping==='camera-focal-plane'?'Camera focal plane only; no physical slice registration.':'Invalid, degenerate or unordered corners; spatial projection unavailable.';
      }
    } catch(error) {warnings.push(`${sidecar.name}: ${error.message}`);}
  }
  return warnings;
}
export function parseDelimited(text, delimiter=',',{allowIncomplete=false}={}) {
  const rows=[];let row=[],cell='',quoted=false;
  for(let i=0;i<text.length;i++) {
    const c=text[i];
    if(c==='"') {
      if(quoted && text[i+1]==='"') {cell+='"';i++;}
      else if(quoted || !cell) quoted=!quoted;
      else cell+=c;
    } else if(c===delimiter && !quoted) {row.push(cell);cell='';}
    else if((c==='\n'||c==='\r')&&!quoted) {
      row.push(cell);rows.push(row);row=[];cell='';
      if(c==='\r'&&text[i+1]==='\n')i++;
    } else cell+=c;
  }
  if(allowIncomplete)return rows;
  if(quoted) throw Error('Unterminated quoted field');
  if(cell||row.length) {row.push(cell);rows.push(row);}
  return rows;
}

export function boundsFor(metadata) {
  const s=metadata?.spatial,b=s?.bounds,order=s?.boundsOrder;
  const names=['xmin','xmax','ymin','ymax','zmin','zmax'];
  if(!Array.isArray(b)||b.length!==6||!b.every(finite)||!Array.isArray(order)||order.length!==6||!names.every(n=>order.includes(n)))return null;
  const result=names.map(n=>b[order.indexOf(n)]);
  return result[0]<=result[1]&&result[2]<=result[3]&&result[4]<=result[5]?result:null;
}

export function cameraUV(point,camera,aspect) {
  if(!vector(point)||!vector(camera?.position)||!vector(camera?.focalPoint)||!vector(camera?.up)||!finite(aspect)||aspect<=0)return null;
  const unit=a=>a.map(v=>v/(norm(a)||1)),dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
  const forward=unit(sub(camera.focalPoint,camera.position)),right=unit(cross(forward,camera.up)),up=cross(right,forward);
  if(norm(right)<.99||norm(up)<.99)return null;
  const q=sub(point,camera.parallel?camera.focalPoint:camera.position),depth=dot(q,forward);
  if(!camera.parallel&&depth<=0)return null;
  const height=camera.parallel?(camera.projectionScaleY??camera.scale):depth*Math.tan(camera.viewAngle*Math.PI/360);
  if(!finite(height)||height<=0)return null;
  return [.5+dot(q,right)/(2*height*aspect),.5-dot(q,up)/(2*height)];
}
