// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import {el,button,note,transport,formatNumber,warning} from './ui.mjs';
import {advance,nearestIndex,cornersFor,basename,dirname} from './model.mjs';
import {quadWeights} from './scene.mjs';
import {createPane} from './panes.mjs';
const sub=(a,b)=>a.map((v,i)=>v-b[i]);
const dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
// Native world point -> source image UV via projective interpolation.
export function imageUV(c,point) {
  const q=quadWeights(c),uv=[[0,0],[1,0],[1,1],[0,1]];
  for(const ids of [[0,1,2],[0,2,3]]) {
    const [a,b,d]=ids.map(i=>c[i]),v0=sub(b,a),v1=sub(d,a),v2=sub(point,a);
    const aa=dot(v0,v0),ab=dot(v0,v1),bb=dot(v1,v1),da=dot(v2,v0),db=dot(v2,v1),den=aa*bb-ab*ab;
    const u=(bb*da-ab*db)/den,v=(aa*db-ab*da)/den,w=1-u-v;
    if(u>=-1e-8&&v>=-1e-8&&w>=-1e-8){const weights=[w,u,v],total=ids.reduce((s,i,k)=>s+q[i]*weights[k],0);return [0,1].map(axis=>ids.reduce((s,i,k)=>s+uv[i][axis]*q[i]*weights[k],0)/total);}
  }
  return null;
}
export function xyzSets(sequences) {
  const sets=new Map();
  for(const s of sequences.filter(s=>'xyz'.includes(s.axis)&&s.axis.length===1)) {
    const first=s.items[0],m=first.metadata,key=JSON.stringify([first.scope||dirname(first.name),first.sequence.id.replace(/(?:[-_ ]+[xyz])$/i,''),s.time,m?.spatial?.frame||'filename',s.units]);
    if(!sets.has(key))sets.set(key,{});sets.get(key)[s.axis]=s;
  }
  return [...sets.entries()].filter(([,v])=>v.x&&v.y&&v.z).map(([id,v])=>({id,sequences:['x','y','z'].map(a=>v[a])}));
}
export function mountSequences(host,sequences,{xyz=false,cleanups,openFile,inspect,indices=new Map(),onSelection=()=>{},spatialOnly=false}) {
  const sets=xyzSets(sequences);
  let selected=xyz?sets[0]?.sequences:[sequences.find(s=>s.id===indices.get('active-sequence'))||sequences[0]];
  if(!selected?.length){host.append(warning('No compatible X, Y and Z stacks are available.'));return;}
  const select=el('div',{class:'sequence-select'}),body=el('div');host.append(select,body);
  let localCleanups=[],sync=false;
  const clearLocal=()=>{localCleanups.forEach(fn=>fn());localCleanups=[];};cleanups.push(clearLocal);
  function mount() {
    clearLocal();body.replaceChildren();
    const stacks=selected.map(s=>({...s,index:Math.min(s.items.length-1,indices.get(s.id)??(s.photoSeries?0:Math.floor(s.items.length/2)))}));
    const updaters=[],transports=[];
    const playback=(fn,label,all=false)=>{let control;control=transport(fn,localCleanups,label,{caption:all?'All axes':null,beforePlay:()=>{if(sync||all)transports.forEach(t=>{if(t!==control)t.stop();});},onPause:()=>{if(sync||all)transports.forEach(t=>t.stop());}});transports.push(control);return control;};
    let groupDirection=1;const directions=new Map();
    const update=()=>{for(const s of stacks)indices.set(s.id,s.index);updaters.forEach(fn=>fn());onSelection(stacks.map(s=>s.items[s.index]));};
    const step=(s,d,mode)=>{const next=advance(s.index,d,s.items.length,mode);s.index=next.index;if(sync){const progress=s.index/(s.items.length-1||1);for(const other of stacks)if(other!==s)other.index=Math.round(progress*(other.items.length-1));}update();return next;};
    if(xyz) {
      const coords=el('div',{class:'coordinates'},el('span',{},'Coordinates:'));
      for(const s of stacks) {
        const input=el('input',{type:'number',step:'any','aria-label':`${s.axis.toUpperCase()} coordinate`});
        input.onchange=()=>{const value=Number(input.value);if(Number.isFinite(value)){s.index=nearestIndex(s.items,value);update();}};
        // Native numeric steppers use observed neighbour spacing so arrow clicks
        // can select irregularly spaced coordinates without inventing slices.
        input.onkeydown=e=>{if(e.key==='ArrowUp'||e.key==='ArrowDown'){e.preventDefault();step(s,e.key==='ArrowUp'?1:-1,'once');}};
        input.oninput=e=>{if(e.inputType==='insertText')return;};
        coords.append(el('label',{class:`coordinate axis-${s.axis}`},s.axis.toUpperCase(),input,s.units==='unknown'?'':s.units));
        updaters.push(()=>{input.value=String(s.items[s.index].sequence.value);input.min=s.items[0].sequence.value;input.max=s.items.at(-1).sequence.value;const delta=s.items[Math.min(s.index+1,s.items.length-1)].sequence.value-s.items[s.index].sequence.value;input.step=delta||'any';});
      }
      body.append(coords);
      const synced=el('input',{type:'checkbox','aria-label':'Link slice progress',checked:sync,onchange:()=>{sync=synced.checked;if(sync)transports.forEach(t=>t.stop());}});
      body.append(el('div',{class:'scene-toolbar group-playback'},playback((d,mode)=>{
        if(sync)return step(stacks[0],d,mode);
        if(groupDirection!==d){directions.clear();groupDirection=d;}
        const next=stacks.map(s=>{const result=advance(s.index,directions.get(s.id)??d,s.items.length,mode);s.index=result.index;directions.set(s.id,result.direction);return result;});update();return {direction:d,stopped:next.every(r=>r.stopped)};
      },'All coordinates',true),el('label',{},synced,'Link slice progress')));
      const linkNote=note('Each slice moves independently.');linkNote.classList.add('link-note');body.append(linkNote);
      synced.addEventListener('change',()=>{linkNote.textContent=sync?'Linked: sliders sweep each axis at the same fraction of its range.':'Each slice moves independently.';});
    }
    const grid=el('div',{class:spatialOnly?'spatial-controls':xyz?'triptych':'sequence-single'});body.append(grid);
    for(const s of stacks) {
      const panel=el('section',{class:'sequence-panel'}),axis=s.axis.toUpperCase(),image=el('img',{alt:`${axis} sequence frame`}),marker=el('span',{class:'crosshair',hidden:true}),stage=el('div',{class:'sequence-image'},image,marker),value=el('span'),frame=el('span'),file=button('',()=>openFile(s.items[s.index]),{class:'group-name',title:'Open individual image'}),slider=el('input',{type:'range',min:0,max:s.items.length-1,step:1,'aria-label':`${axis} slice slider`});
      slider.oninput=()=>{s.index=Number(slider.value);if(sync&&xyz){const progress=s.index/(s.items.length-1);for(const other of stacks)if(other!==s)other.index=Math.round(progress*(other.items.length-1));}update();};
      image.onerror=()=>{image.alt='Image unavailable or unsupported by this browser';};
      panel.classList.toggle('compact-axis',spatialOnly);
      panel.append(...[el('h2',{class:`axis-${s.axis}`},`${axis==='TIME'?'Time':axis==='INDEX'?'Frame':axis+' slices'}`),spatialOnly?null:stage,el('div',{class:'sequence-footer'},value,frame),slider,playback((d,mode)=>step(s,d,mode),axis),file,spatialOnly?null:note(s.photoSeries?'Photo series in natural filename order; no physical coordinates inferred.':s.autoKind?`Automatic ${s.autoKind} filename sequence; physical placement unverified.`:s.inferred?'Order inferred from filename numbers; physical placement unverified.':`Metadata sequence · ${s.items.length} images`)].filter(Boolean));
      if(!spatialOnly)createPane(stage,{root:panel,label:axis==='TIME'?'Time sequence':axis==='INDEX'?'Frame sequence':axis+' slices',cleanups:localCleanups,height:xyz?250:430,key:'sequence-'+axis});
      grid.append(panel);
      updaters.push(()=>{
        const item=s.items[s.index];if(!spatialOnly&&image.dataset.id!==item.id){image.src=item.url;image.dataset.id=item.id;}
        value.textContent=s.autoKind?`${s.autoKind==='alphabetic'?'Letter':'Frame'} = ${item.sequence.displayValue}`:`${axis} = ${formatNumber(item.sequence.value)} ${s.units==='unknown'?'':s.units}`;frame.textContent=`${s.index+1} / ${s.items.length}`;slider.value=s.index;file.textContent=basename(item.name);
        marker.hidden=true;
        if(xyz&&!spatialOnly) {
          const selectedItems=stacks.map(s=>s.items[s.index]),first=selectedItems[0].metadata?.spatial;
          if(first?.frame && first?.units && first.units!=='unknown' && selectedItems.every(i=>i.metadata?.spatial?.frame===first.frame&&i.metadata?.spatial?.units===first.units)) {
            const c=cornersFor(item.metadata),point=stacks.map(s=>s.items[s.index].sequence.value);
            if(c){const uv=imageUV(c,point);if(uv){
              // Respect object-fit:contain letterboxing when placing indicators.
              const show=()=>{const scale=Math.min(stage.clientWidth/image.naturalWidth,stage.clientHeight/image.naturalHeight),w=image.naturalWidth*scale,h=image.naturalHeight*scale;if(!w||!h)return;marker.style.left=`${(stage.clientWidth-w)/2+uv[0]*w}px`;marker.style.top=`${(stage.clientHeight-h)/2+uv[1]*h}px`;marker.hidden=false;};show();image.onload=show;
            }}
          }
        }
      });
      if(!spatialOnly){const observer=new ResizeObserver(update);observer.observe(stage);localCleanups.push(()=>observer.disconnect());}
      stage.ondblclick=()=>openFile(s.items[s.index]);stage.onclick=()=>inspect(s.items[s.index]);
    }
    update();
  }
  const choices=xyz?sets:sequences.map(s=>({id:s.id,sequences:[s]}));
  const buttons=choices.map(choice=>button(xyz?`${choice.sequences[0].items[0].sequence.label||choice.sequences[0].items[0].sequence.id}${choice.sequences[0].time!==''?' · t='+choice.sequences[0].time:''}`:`${choice.sequences[0].axis.toUpperCase()} · ${choice.sequences[0].items[0].sequence.label||choice.sequences[0].items[0].sequence.id}${choice.sequences[0].time!==''?' · t='+choice.sequences[0].time:''}`,()=>{selected=choice.sequences;indices.set('active-sequence',choice.sequences[0].id);buttons.forEach((b,i)=>b.classList.toggle('active',choices[i]===choice));mount();},{class:choice.sequences[0].id===selected[0].id?'active':''}));
  if(choices.length>1)select.append(...buttons);
  mount();
  return ()=>clearLocal();
}
