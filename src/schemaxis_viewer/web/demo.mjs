import {cameraUV} from './model.mjs';
// Procedural sample artifacts. No remote assets or simulation claims.
function canvasBlob(canvas) {
  const binary=atob(canvas.toDataURL('image/png').split(',')[1]);
  return new Blob([Uint8Array.from(binary,c=>c.charCodeAt(0))],{type:'image/png'});
}
export async function demoItems() {
  const result=[];
  let serial=0;
  const item=(name,blob,metadata=null)=>{
    const url=URL.createObjectURL(blob);
    const value={id:`demo-${serial++}`,name,size:blob.size,url,blob,metadata,demo:true,metadataStatus:'Generated with sample data',
      bytes:()=>blob.arrayBuffer(),text:()=>blob.text()};result.push(value);return value;
  };
  const scale=v=>{
    const stops=[[28,36,100],[36,105,170],[40,184,176],[188,220,86],[249,172,55],[201,61,45]];
    const x=Math.min(4.999,Math.max(0,v*5)),i=Math.floor(x),t=x-i;return stops[i].map((v,k)=>v*(1-t)+stops[i+1][k]*t);
  };
  for(const axis of ['x','y','z']) for(let index=0;index<11;index++) {
    const canvas=document.createElement('canvas');canvas.width=420;canvas.height=260;const ctx=canvas.getContext('2d'),data=ctx.createImageData(420,260);
    for(let y=0;y<260;y++)for(let x=0;x<420;x++) {
      const u=x/420,v=y/260,t=index/10;
      const wake=Math.exp(-((v-.5-.12*Math.sin(u*8+t*5))**2)/.016)*(1-u*.5);
      const scalar=.17+.55*wake+.2*Math.sin(u*7+t*2+(axis==='z'?1:0))*Math.cos(v*8-t*3);
      const colour=scale(scalar);const p=(y*420+x)*4;data.data.set([...colour,255],p);
      // Solid circular obstruction is transparent in the sample slice texture.
      if((u-.23)**2+((v-.5)*.62)**2<.004) data.data[p+3]=0;
    }
    ctx.putImageData(data,0,0);
    const value=Number((index*.2).toFixed(1));
    const corners=axis==='x'?[[value,0,1],[value,2,1],[value,2,0],[value,0,0]]:axis==='y'?[[0,value,1],[2,value,1],[2,value,0],[0,value,0]]:[[0,2,value/2],[2,2,value/2],[2,0,value/2],[0,0,value/2]];
    const coordinate=axis==='z'?value/2:value,normal=[0,0,0];normal['xyz'.indexOf(axis)]=1;
    item(`Flow study/slices/velocity_${axis}_${index.toString().padStart(3,'0')}.png`,canvasBlob(canvas),{
      version:'schemaxis.artifact-metadata/1',group:'Flow study · synthetic sample',sequence:{id:'velocity',axis,value:coordinate,units:'m'},
      artifact:{kind:'image'},spatial:{state:'known',frame:'sample-world',units:'m',mapping:'pixel-edge-rays-to-slice-plane',corners,cornerOrder:['top-left','top-right','bottom-right','bottom-left'],bounds:[0,2,0,2,0,1],boundsOrder:['xmin','xmax','ymin','ymax','zmin','zmax'],pixelOrigin:'top-left',rowDirection:'down',plane:{origin:corners[0],normal}},
    });
  }
  const overview=document.createElement('canvas');overview.width=480;overview.height=300;const c=overview.getContext('2d');
  c.fillStyle='#101a23';c.fillRect(0,0,480,300);c.strokeStyle='#638a9b';c.lineWidth=2;
  const camera={position:[4,-5,4],focalPoint:[1,1,.5],up:[0,0,1],parallel:true,scale:1.55};
  const corners=Array.from({length:8},(_,i)=>[(i&1)?2:0,(i&2)?2:0,(i&4)?1:0]);
  const pixel=p=>{const uv=cameraUV(p,camera,480/300);return [uv[0]*480,uv[1]*300];};
  for(let i=0;i<8;i++)for(const bit of [1,2,4])if(!(i&bit)){c.beginPath();c.moveTo(...pixel(corners[i]));c.lineTo(...pixel(corners[i|bit]));c.stroke();}
  c.fillStyle='#8bdfcf';c.font='14px sans-serif';c.fillText('Synthetic domain · 2 × 2 × 1 m',80,283);
  const over=item('Flow study/overview.png',canvasBlob(overview),{group:'Flow study · synthetic sample',artifact:{kind:'image'},size:{pixels:[480,300]},spatial:{state:'known',frame:'sample-world',units:'m',mapping:'camera-focal-plane',camera}});
  for(const v of result)if(v.metadata?.sequence)v.metadata.overview={file:'../overview.png'};
  over.metadata.overview={file:'overview.png'};
  let csv='time_s,drag_N,lift_N\n';for(let i=0;i<90;i++)csv+=`${(i*.05).toFixed(2)},${(2.2+.3*Math.sin(i*.2)).toFixed(4)},${(.4*Math.sin(i*.25)).toFixed(4)}\n`;
  item('Flow study/measurements/forces.csv',new Blob([csv],{type:'text/csv'}),{group:'Run records'});
  item('Flow study/records/run.log',new Blob(['Synthetic demonstration dataset\nNo CFD solver was run.\n\nIteration 100: residual 0.00024\nIteration 200: residual 0.00006\nINFO: geometry units are metres\nINFO: export complete\n'],{type:'text/plain'}),{group:'Run records'});
  item('Geometry/wedge.obj',new Blob(['v 0 0 0\nv 2 0 0\nv 0 1 0\nv 0 0 1\nf 1 3 2\nf 1 2 4\nf 1 4 3\nf 2 3 4\n'],{type:'text/plain'}),{group:'Geometry'});
  return result;
}
