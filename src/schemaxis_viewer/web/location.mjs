// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import {el,button,note,formatNumber} from './ui.mjs';
import {basename,cornersFor,boundsFor,cameraUV,relativeItem} from './model.mjs';

const colour = axis => ({x:'#eeaa85',y:'#8bdfcf',z:'#a4bbff'})[axis] || '#8bdfcf';

// Location has a stable home, independent of the metadata disclosure and the
// gallery's scroll position. A schematic uses actual coordinates, not image pixels.
export function createLocation(host,{openFile,selectItem}) {
  let revision=0;
  const images=new Map();
  function imageFor(url) {
    if(!images.has(url)) {const image=new Image();image.src=url;images.set(url,image);}
    return images.get(url);
  }
  return {
    clear(){revision++;images.clear();host.replaceChildren();host.hidden=true;},
    update(group,selected,items,{mode='gallery'}={}) {
      const token=++revision;
      host.replaceChildren();host.hidden=!group;
      if(!group)return;
      const chosen=selected.filter(Boolean),first=chosen[0];
      const registered=chosen.filter(item=>cornersFor(item.metadata));
      host.append(el('div',{class:'location-heading'},registered.length?'SLICE LOCATION':'CURRENT SELECTION'));
      if(!first){host.append(note('Select a file to see its context.'));return;}
      const values=el('div',{class:'location-values'});
      for(const item of chosen) {
        const sequence=item.sequence;
        if(sequence)values.append(el('span',{class:`location-coordinate axis-${sequence.axis}`},`${sequence.orderKind==='alphabetic'?'Letter':sequence.axis==='index'?'Frame':sequence.axis.toUpperCase()} = ${sequence.displayValue??formatNumber(sequence.value)} ${sequence.units&&sequence.units!=='unknown'?sequence.units:''}`));
      }
      host.append(values);
      const owner=chosen.find(i=>i.metadata?.overview?.file)||group.items.find(i=>i.metadata?.overview?.file);
      const overview=owner&&relativeItem(items,owner,owner.metadata.overview.file);
      const canvas=el('canvas',{class:'location-canvas',width:640,height:360,'aria-label':'Selected slice position'});
      const title=chosen.length>1?`${chosen.length} selected slices`:basename(first.name);
      const info=el('div',{class:'location-info'},el('div',{class:'location-file',title:first.name},title));
      const draw=(camera,background=null,bounds=null)=>{
        if(token!==revision)return;
        const ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height;
        ctx.fillStyle='#0d161e';ctx.fillRect(0,0,w,h);
        if(background)ctx.drawImage(background,0,0,w,h);
        const project=point=>{const uv=cameraUV(point,camera,w/h);return uv&&[uv[0]*w,uv[1]*h];};
        if(bounds) {
          const corners=Array.from({length:8},(_,i)=>[bounds[(i&1)?1:0],bounds[(i&2)?3:2],bounds[(i&4)?5:4]]);
          ctx.strokeStyle='#6c8798';ctx.lineWidth=1.5;
          for(let i=0;i<8;i++)for(const bit of [1,2,4])if(!(i&bit)) {const a=project(corners[i]),b=project(corners[i|bit]);if(!a||!b)continue;ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke();}
        }
        for(const item of registered) {
          const space=item.metadata.spatial;
          if(background&&(space.frame!==overview.metadata?.spatial?.frame||space.units!==overview.metadata?.spatial?.units||(item.scope||'')!==(overview.scope||'')))continue;
          const points=cornersFor(item.metadata).map(project);if(points.some(p=>!p))continue;
          ctx.strokeStyle=ctx.fillStyle=colour(item.sequence?.axis);ctx.lineWidth=3;
          ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();
          ctx.globalAlpha=.16;ctx.fill();ctx.globalAlpha=1;ctx.stroke();
          const centre=points.reduce((sum,p)=>sum.map((v,i)=>v+p[i]/4),[0,0]);
          ctx.beginPath();ctx.arc(...centre,5,0,Math.PI*2);ctx.fill();
          ctx.font='bold 21px system-ui';ctx.fillText(item.sequence?.axis?.toUpperCase()||'Slice',centre[0]+10,centre[1]-10);
        }
      };
      let caption='';
      if(registered.length) {
        const camera=overview?.metadata?.spatial?.camera;
        const matching=camera&&registered.some(i=>i.metadata.spatial.frame===overview.metadata.spatial.frame&&i.metadata.spatial.units===overview.metadata.spatial.units&&(i.scope||'')===(overview.scope||''));
        if(matching) {
          const image=imageFor(overview.url);
          // Preserve the overview's recorded aspect ratio for camera projection.
          const ready=()=>{if(token!==revision)return;canvas.height=Math.round(640*image.naturalHeight/image.naturalWidth);draw(camera,image);};
          if(image.complete&&image.naturalWidth)ready();else image.onload=ready;
          caption='Position on overview';
        } else {
          const firstSpace=registered[0].metadata.spatial;
          const sameFrame=group.items.filter(i=>i.metadata?.spatial&&i.metadata.spatial.frame===firstSpace.frame&&i.metadata.spatial.units===firstSpace.units&&(i.scope||'')===(first.scope||''));
          const observed=sameFrame.map(i=>boundsFor(i.metadata)).filter(Boolean);
          const points=sameFrame.flatMap(i=>cornersFor(i.metadata)||[]);
          const bounds=observed.length?[0,1,2,3,4,5].map(i=>observed.reduce((v,b)=>i%2?Math.max(v,b[i]):Math.min(v,b[i]),i%2?-Infinity:Infinity)):[0,1,2].flatMap(i=>[points.reduce((v,p)=>Math.min(v,p[i]),Infinity),points.reduce((v,p)=>Math.max(v,p[i]),-Infinity)]);
          const centre=[0,1,2].map(i=>(bounds[i*2]+bounds[i*2+1])/2),radius=Math.max(1e-12,Math.hypot(...[0,1,2].map(i=>bounds[i*2+1]-bounds[i*2]))/2);
          draw({position:centre.map((v,i)=>v+[3,-4,3][i]*radius),focalPoint:centre,up:[0,0,1],parallel:true,scale:radius*1.12},null,bounds);
          caption='World-position sketch · bounds reference';
        }
        host.append(el('div',{class:'location-picture'},canvas));
      } else if(first.kind==='image') {
        host.append(el('div',{class:'location-picture'},el('img',{src:first.url,alt:basename(first.name)})));
        caption=first.sequence?.inferred?'Filename order · spatial position unavailable':'Image preview · spatial position unavailable';
      } else caption=first.kind==='mesh'?'3D model · open to rotate, pan and zoom':`${first.kind} preview`;
      info.append(el('div',{class:'location-caption'},caption));
      const actions=el('div',{class:'location-actions'},button(first.kind==='image'?(chosen.length>1?`Open ${first.sequence?.axis?.toUpperCase()||'first'} image`:'Open image'):'Open file',()=>openFile(first),{class:'location-open'}));
      if(chosen.length===1&&mode==='gallery') {
        const sequence=group.sequences.find(s=>s.items.some(i=>i.id===first.id));
        if(sequence) {
          const index=sequence.items.findIndex(i=>i.id===first.id);
          actions.prepend(button('‹',()=>selectItem(sequence.items[index-1]),{disabled:index===0,'aria-label':'Select previous gallery slice'}));
          actions.append(button('›',()=>selectItem(sequence.items[index+1]),{disabled:index===sequence.items.length-1,'aria-label':'Select next gallery slice'}));
          info.append(el('div',{class:'location-caption'},`Image ${index+1} of ${sequence.items.length}`));
        }
      }
      info.append(actions);host.append(info);
    },
  };
}
