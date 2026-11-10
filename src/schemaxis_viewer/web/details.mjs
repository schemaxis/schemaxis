// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import {mountText} from "./text.mjs";
import {el,button,note,warning,formatBytes,boundedText} from './ui.mjs';
import {basename,parseDelimited} from './model.mjs';
import {createScene,meshFromBytes} from './scene.mjs';
import {createPane} from './panes.mjs';
export async function showDetail(host,item,{back,cleanups}) {
  const download=el('a',{href:item.url,download:basename(item.name)},'Download original ↗');
  host.append(el('div',{class:'detail-toolbar'},button('← Collection',back),el('h2',{},basename(item.name)),download));
  const body=el('div',{class:'detail-body'}),pane=createPane(body,{label:basename(item.name),cleanups,height:480,key:'detail-'+item.kind});host.append(pane.root);host=body;
  if(item.kind==='image') {
    let scale=1,x=0,y=0,drag=null;
    const image=el('img',{src:item.url,class:'detail-image',alt:item.name}),stage=el('div',{class:'image-stage'},image);
    const update=()=>image.style.transform=`translate(${x}px,${y}px) scale(${scale})`;
    const zoom=d=>{scale=Math.max(.1,Math.min(20,scale*d));update();};
    stage.onwheel=e=>{e.preventDefault();zoom(Math.exp(-e.deltaY*.001));};
    stage.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY};stage.setPointerCapture(e.pointerId);};
    stage.onpointermove=e=>{if(drag){x+=e.clientX-drag.x;y+=e.clientY-drag.y;drag={x:e.clientX,y:e.clientY};update();}};
    stage.onpointerup=stage.onpointercancel=()=>{drag=null;};
    image.onerror=()=>stage.replaceChildren(warning('This browser could not decode the image. Download the original to open it in another application.'));
    host.append(el('div',{class:'zoom-controls'},button('−',()=>zoom(1/1.2),{'aria-label':'Zoom out'}),button('＋',()=>zoom(1.2),{'aria-label':'Zoom in'}),button('Fit',()=>{scale=1;x=y=0;update();})),stage,note('Drag to pan · Wheel to zoom'));
  } else if(item.kind==='mesh') {
    if(item.size>64*1024*1024){host.append(warning('Mesh exceeds the 64 MiB preview limit. Provide a reduced STL or OBJ preview.'));return;}
    const canvas=el('canvas',{class:'scene',tabindex:0,'aria-label':'3D mesh. Drag to orbit, Shift-drag to pan, wheel to zoom, F to fit.'});host.append(canvas);
    const mesh=meshFromBytes(await item.bytes(),item.name);
    if(!host.isConnected)return;
    const scene=createScene(canvas);cleanups.push(()=>scene.dispose());await scene.setData([],mesh);
    const wire=el('input',{type:'checkbox',checked:true,onchange:()=>scene.setWireframe(wire.checked)});
    host.append(el('div',{class:'scene-toolbar'},button('Fit',()=>scene.fit()),...['iso','x','y','z'].map(axis=>button(axis.toUpperCase(),()=>scene.view(axis))),el('label',{},wire,'Wireframe')),note('STL / OBJ preview · Drag rotate · Shift-drag pan · Wheel zoom · Arrow keys rotate · F fit. Units are as stored; no conversion.'));
  } else if(item.kind==='video'||item.kind==='audio') {
    const media=el(item.kind,{controls:'',src:item.url,preload:'metadata'});
    media.onerror=()=>host.append(warning('This browser cannot decode the media codec. Download the original to play it externally.'));
    cleanups.push(()=>{media.pause();media.removeAttribute('src');media.load();});host.append(media);
  } else if(item.kind==='table') {
    const text=await boundedText(item);
    if(!host.isConnected)return;
    if(item.size>4*1024*1024)host.append(warning('Preview limited to the first 4 MiB; the final partial record is omitted. Download for complete data.'));
    const rows=parseDelimited(text,basename(item.name).toLowerCase().endsWith('.tsv')?'\t':',',{allowIncomplete:item.size>4*1024*1024});
    const search=el('input',{type:'search',placeholder:'Search all preview rows','aria-label':'Search table'}),grid=el('div',{class:'table-wrap'}),pager=el('div',{class:'pager'}),plot=el('div');
    let page=0,filtered=rows.slice(1);
    const render=()=>{
      filtered=rows.slice(1).filter(row=>row.some(cell=>cell.toLowerCase().includes(search.value.toLowerCase())));
      page=Math.min(page,Math.max(0,Math.ceil(filtered.length/100)-1));
      grid.replaceChildren(el('table',{},el('thead',{},el('tr',{},(rows[0]||[]).map(c=>el('th',{},c)))),el('tbody',{},filtered.slice(page*100,page*100+100).map(row=>el('tr',{},row.map(c=>el('td',{},c)))))));
      pager.replaceChildren(button('Previous',()=>{page--;render();},{disabled:page===0}),`${filtered.length} rows · Page ${page+1} of ${Math.max(1,Math.ceil(filtered.length/100))}`,button('Next',()=>{page++;render();},{disabled:(page+1)*100>=filtered.length}));
    };
    search.oninput=()=>{page=0;render();};
    host.append(note('First record shown as column headings. Quoted fields and embedded newlines are preserved.'),el('div',{class:'text-tools'},search),grid,pager,plot);render();
    if(rows[0]?.length>1) {
      const makeSelect=label=>el('select',{'aria-label':label},rows[0].map((name,i)=>el('option',{value:i},name||`Column ${i+1}`)));
      const x=makeSelect('Plot horizontal column'),y=makeSelect('Plot vertical column');y.value='1';
      const canvas=el('canvas',{class:'chart','aria-label':'Numeric line plot'});
      const draw=()=>{
        const points=rows.slice(1).filter(r=>r[+x.value]?.trim()&&r[+y.value]?.trim()).map(r=>[Number(r[+x.value]),Number(r[+y.value])]).filter(p=>p.every(Number.isFinite));
        canvas.width=Math.max(300,canvas.clientWidth*devicePixelRatio);canvas.height=230*devicePixelRatio;const c=canvas.getContext('2d'),w=canvas.width,h=canvas.height,d=devicePixelRatio;
        const colours=getComputedStyle(document.documentElement);
        c.fillStyle=colours.getPropertyValue('--panel');c.fillRect(0,0,w,h);c.font=`${11*d}px system-ui`;c.fillStyle=colours.getPropertyValue('--muted');
        if(!points.length){c.fillText('No numeric pairs in these columns',20*d,40*d);return;}
        const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;
        for(let i=0;i<xs.length;i++){xmin=Math.min(xmin,xs[i]);xmax=Math.max(xmax,xs[i]);ymin=Math.min(ymin,ys[i]);ymax=Math.max(ymax,ys[i]);}
        const left=65*d,right=20*d,top=20*d,bottom=40*d;
        c.strokeStyle=colours.getPropertyValue('--muted');c.beginPath();c.moveTo(left,top);c.lineTo(left,h-bottom);c.lineTo(w-right,h-bottom);c.stroke();
        c.fillText(ymax.toPrecision(4),5*d,top+8*d);c.fillText(ymin.toPrecision(4),5*d,h-bottom);c.fillText(xmin.toPrecision(4),left,h-15*d);c.fillText(xmax.toPrecision(4),w-right-50*d,h-15*d);
        c.strokeStyle=colours.getPropertyValue('--accent');c.lineWidth=1.5*d;c.beginPath();points.forEach(([a,b],i)=>{const px=left+(a-xmin)/(xmax-xmin||1)*(w-left-right),py=h-bottom-(b-ymin)/(ymax-ymin||1)*(h-top-bottom);if(!i)c.moveTo(px,py);else c.lineTo(px,py);});c.stroke();
      };
      x.onchange=y.onchange=draw;plot.append(el('div',{class:'scene-toolbar'},'Plot',x,'against',y),canvas,note('Plot uses all numeric pairs in the preview, in file order; table filtering does not alter the plot.'));
      const observer=new ResizeObserver(draw);observer.observe(canvas);document.addEventListener('artifact-themechange',draw);cleanups.push(()=>{observer.disconnect();document.removeEventListener('artifact-themechange',draw);});draw();
    }
  } else if(item.kind==='text') {
    const text=await boundedText(item);if(!host.isConnected)return;
    if(item.size>4*1024*1024)host.append(warning('Text preview limited to the first 4 MiB. Download for the complete file.'));
    mountText(host,text,cleanups);
  } else host.append(el('div',{class:'empty'},el('div',{class:'empty-icon'},'◇'),el('h2',{},'Original file available'),note(`${basename(item.name)} · ${formatBytes(item.size)}`),note('This format has no built-in preview. For workbooks, export a sheet to CSV or TSV. For 3D data, provide an STL or OBJ preview.'),download.cloneNode(true)));
}
