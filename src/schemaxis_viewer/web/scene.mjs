// Small, dependency-free orthographic scene renderer. World coordinates remain
// doubles on the CPU; GPU coordinates are centred/scaled for CFD-sized offsets.
const sub=(a,b)=>a.map((v,i)=>v-b[i]);
const add=(a,b)=>a.map((v,i)=>v+b[i]);
const mul=(a,s)=>a.map(v=>v*s);
const dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const norm=a=>Math.hypot(...a);
export function meshFromBytes(bytes,name) {
  const data=new DataView(bytes), vertices=[];
  const append=(...points)=>{
    if(vertices.length>1800000) throw Error('Mesh exceeds 200,000 triangles; provide a reduced preview mesh');
    for(const p of points) {
      if(p.length!==3 || !p.every(Number.isFinite)) throw Error('Invalid mesh vertex');
      vertices.push(...p);
    }
  };
  if(name.toLowerCase().endsWith('.stl')) {
    const count=bytes.byteLength>=84?data.getUint32(80,true):0;
    if(count && 84+count*50===bytes.byteLength) {
      if(count>200000) throw Error('Mesh exceeds 200,000 triangles; provide a reduced preview mesh');
      for(let i=0;i<count;i++) {
        const p=84+i*50+12;
        append(...[0,1,2].map(j=>[0,1,2].map(k=>data.getFloat32(p+j*12+k*4,true))));
      }
    } else {
      const text=new TextDecoder().decode(bytes), pattern=/\bvertex\s+(\S+)\s+(\S+)\s+(\S+)/gi;
      const triangle=[];
      for(const m of text.matchAll(pattern)) {
        triangle.push(m.slice(1).map(Number));
        if(triangle.length===3) {append(...triangle);triangle.length=0;}
      }
      if(triangle.length) throw Error('Incomplete STL triangle');
    }
  } else {
    const points=[];
    for(const line of new TextDecoder().decode(bytes).split(/\r?\n/)) {
      const [tag,...values]=line.trim().split(/\s+/);
      if(tag==='v') points.push(values.slice(0,3).map(Number));
      if(tag==='f') {
        const face=values.filter(v=>!v.startsWith('#')).map(v=>{
          const n=Number(v.split('/')[0]);
          if(!Number.isInteger(n)||n===0) throw Error('Invalid OBJ vertex index');
          const p=points[n<0?points.length+n:n-1];
          if(!p) throw Error('OBJ face references a missing vertex');
          return p;
        });
        for(let i=1;i<face.length-1;i++) append(face[0],face[i],face[i+1]);
      }
    }
  }
  if(!vertices.length || vertices.length%9) throw Error('No supported triangles in this mesh');
  return vertices;
}
function program(gl,vertex,fragment) {
  const shaders=[gl.VERTEX_SHADER,gl.FRAGMENT_SHADER].map((type,i)=>{
    const s=gl.createShader(type);gl.shaderSource(s,i?fragment:vertex);gl.compileShader(s);
    if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(s));return s;
  });
  const p=gl.createProgram();shaders.forEach(s=>gl.attachShader(p,s));gl.linkProgram(p);
  shaders.forEach(s=>gl.deleteShader(s));
  if(!gl.getProgramParameter(p,gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(p));return p;
}
// Projective UVs: diagonal intersection ratios preserve the original camera
// mapping for trapezoidal four-corner footprints, not just rectangles.
export function quadWeights(c) {
  const a=sub(c[2],c[0]), b=sub(c[3],c[1]), d=sub(c[1],c[0]);
  const aa=dot(a,a),bb=dot(b,b),ab=dot(a,b),den=aa*bb-ab*ab;
  if(Math.abs(den)<aa*bb*1e-12) throw Error('Degenerate plane diagonals');
  const t=(dot(d,a)*bb-dot(d,b)*ab)/den;
  const u=(dot(d,a)*ab-dot(d,b)*aa)/den;
  if(t<=0||t>=1||u<=0||u>=1) throw Error('Non-convex image plane');
  return [1/(1-t),1/(1-u),1/t,1/u];
}
export function createScene(canvas,{onError=()=>{}}={}) {
  const gl=canvas.getContext('webgl',{alpha:false,antialias:true,preserveDrawingBuffer:true});
  if(!gl) throw Error('WebGL is unavailable. Gallery and sequence views remain available.');
  const p=program(gl,`
    attribute vec3 pos; attribute vec3 uvq;
    uniform vec3 right; uniform vec3 up; uniform vec3 forward;
    uniform vec2 pan; uniform float zoom; uniform float aspect;
    varying vec3 texcoord;
    void main(){gl_Position=vec4((dot(pos,right)*zoom+pan.x)/aspect,dot(pos,up)*zoom+pan.y,-dot(pos,forward)*0.1,1.0);texcoord=uvq;}
  `,`
    precision mediump float; varying vec3 texcoord;
    uniform sampler2D image; uniform bool textured; uniform vec4 colour;
    void main(){vec4 c=textured?texture2D(image,texcoord.xy/texcoord.z):colour;if(c.a<0.02)discard;gl_FragColor=c;}
  `);
  const attrs=['pos','uvq'].map(n=>gl.getAttribLocation(p,n));
  const uniforms=Object.fromEntries(['right','up','forward','pan','zoom','aspect','image','textured','colour'].map(n=>[n,gl.getUniformLocation(p,n)]));
  const buffer=gl.createBuffer(),textures=new Map(),pendingTextures=new Map();
  let planes=[],mesh=null,bounds=null,centre=[0,0,0],radius=1,yaw=.8,pitch=.48,zoom=.9,pan=[0,0],wire=true,showBox=true,disposed=false;
  let drag=null,frame=0,meshCache=null;
  const discardMesh=()=>{if(meshCache){gl.deleteBuffer(meshCache.solid);gl.deleteBuffer(meshCache.wire);meshCache=null;}};
  const normalized=p=>mul(sub(p,centre),1/radius);
  function updateBounds() {
    const points=planes.flatMap(p=>p.corners);
    if(mesh) for(let i=0;i<mesh.length;i+=3) points.push(mesh.slice(i,i+3));
    if(bounds) for(let i=0;i<8;i++) points.push([bounds[(i&1)?1:0],bounds[(i&2)?3:2],bounds[(i&4)?5:4]]);
    if(!points.length)return;
    const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];
    for(const point of points) for(let i=0;i<3;i++) {lo[i]=Math.min(lo[i],point[i]);hi[i]=Math.max(hi[i],point[i]);}
    centre=lo.map((v,i)=>v+(hi[i]-v)/2);radius=Math.max(norm(sub(hi,lo))/2,1e-20);
    if(!bounds) bounds=[lo[0],hi[0],lo[1],hi[1],lo[2],hi[2]];
  }
  function invalidate(){if(!frame&&!disposed)frame=requestAnimationFrame(draw);}
  function batch(points,mode,colour,texture=null,uvs=null) {
    if(!points.length)return;
    const data=new Float32Array(points.length*6);
    points.forEach((point,i)=>{data.set(normalized(point),i*6);data.set(uvs?.[i]||[0,0,1],i*6+3);});
    gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,data,gl.DYNAMIC_DRAW);
    drawBuffer(buffer,points.length,mode,colour,texture);
  }
  function drawBuffer(target,count,mode,colour,texture=null) {
    gl.bindBuffer(gl.ARRAY_BUFFER,target);
    attrs.forEach((loc,i)=>{gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,3,gl.FLOAT,false,24,i*12);});
    gl.uniform1i(uniforms.textured,texture?1:0);gl.uniform4fv(uniforms.colour,colour);
    if(texture)gl.bindTexture(gl.TEXTURE_2D,texture);
    gl.drawArrays(mode,0,count);
  }
  function prepareMesh() {
    const key=JSON.stringify([centre,radius]);
    if(meshCache?.mesh===mesh&&meshCache.key===key)return;
    discardMesh();if(!mesh)return;
    const make=wire=>{
      const count=wire?mesh.length/3*2:mesh.length/3,data=new Float32Array(count*6);
      let offset=0;
      for(let i=0;i<mesh.length;i+=9)for(const j of (wire?[0,1,1,2,2,0]:[0,1,2])) {
        for(let k=0;k<3;k++)data[offset+k]=(mesh[i+j*3+k]-centre[k])/radius;
        data[offset+5]=1;offset+=6;
      }
      const target=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,target);gl.bufferData(gl.ARRAY_BUFFER,data,gl.STATIC_DRAW);return target;
    };
    meshCache={mesh,key,solid:make(false),wire:make(true)};
  }
  function draw() {
    frame=0;if(disposed)return;
    const dpr=Math.min(devicePixelRatio||1,2),w=Math.max(1,Math.round(canvas.clientWidth*dpr)),h=Math.max(1,Math.round(canvas.clientHeight*dpr));
    if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
    gl.viewport(0,0,w,h);gl.clearColor(.039,.063,.086,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    gl.useProgram(p);gl.enable(gl.DEPTH_TEST);gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
    const right=[-Math.sin(yaw),Math.cos(yaw),0],forward=[Math.cos(pitch)*Math.cos(yaw),Math.cos(pitch)*Math.sin(yaw),Math.sin(pitch)],up=cross(forward,right);
    gl.uniform3fv(uniforms.right,right);gl.uniform3fv(uniforms.up,up);gl.uniform3fv(uniforms.forward,forward);
    gl.uniform2fv(uniforms.pan,pan);gl.uniform1f(uniforms.zoom,zoom);gl.uniform1f(uniforms.aspect,w/h);gl.uniform1i(uniforms.image,0);
    gl.depthMask(true);
    if(mesh){
      prepareMesh();
      drawBuffer(wire?meshCache.wire:meshCache.solid,mesh.length/3*(wire?2:1),wire?gl.LINES:gl.TRIANGLES,wire?[.4,.56,.63,.25]:[.28,.39,.45,1]);
    }
    const sorted=[...planes].sort((a,b)=>dot(sub(a.corners[0],centre),forward)-dot(sub(b.corners[0],centre),forward));
    for(const plane of sorted){
      const tex=textures.get(plane.item.id);if(!tex)continue;
      const indices=[0,1,2,0,2,3], uv=[[0,0],[1,0],[1,1],[0,1]],q=quadWeights(plane.corners);
      batch(indices.map(i=>plane.corners[i]),gl.TRIANGLES,[1,1,1,1],tex,indices.map(i=>[uv[i][0]*q[i],uv[i][1]*q[i],q[i]]));
      const lines=plane.corners.flatMap((c,i)=>[c,plane.corners[(i+1)%4]]);
      batch(lines,gl.LINES,plane.axis==='x'?[1,.65,.45,1]:plane.axis==='y'?[.5,.95,.8,1]:[.55,.7,1,1]);
    }
    gl.depthMask(false);
    if(showBox&&bounds){
      const corners=Array.from({length:8},(_,i)=>[bounds[(i&1)?1:0],bounds[(i&2)?3:2],bounds[(i&4)?5:4]]),lines=[];
      for(let i=0;i<8;i++) for(const bit of [1,2,4])if(!(i&bit))lines.push(corners[i],corners[i|bit]);
      batch(lines,gl.LINES,[.6,.72,.8,.55]);
      const origin=corners[0],extent=radius*.35;
      for(let i=0;i<3;i++){const end=[...origin];end[i]+=extent;batch([origin,end],gl.LINES,[[1,.65,.45,1],[.5,.95,.8,1],[.55,.7,1,1]][i]);}
    }
    gl.depthMask(true);
  }
  function loadTexture(item) {
    if(textures.has(item.id))return Promise.resolve();
    if(pendingTextures.has(item.id))return pendingTextures.get(item.id);
    const task=decodeTexture(item).finally(()=>pendingTextures.delete(item.id));
    pendingTextures.set(item.id,task);return task;
  }
  async function decodeTexture(item) {
    if(textures.has(item.id))return;
    const image=new Image();image.src=item.url;
    await image.decode();if(disposed||!planes.some(p=>p.item.id===item.id))return;
    const max=gl.getParameter(gl.MAX_TEXTURE_SIZE);
    if(image.width>max||image.height>max)throw Error(`Image exceeds WebGL texture limit (${max}px): ${item.name}`);
    const t=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,t);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,image);textures.set(item.id,t);invalidate();
  }
  const down=e=>{drag={x:e.clientX,y:e.clientY,pan:e.shiftKey||e.button===2};canvas.setPointerCapture(e.pointerId);canvas.focus();};
  const move=e=>{if(!drag)return;const x=e.clientX-drag.x,y=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;
    if(drag.pan){pan[0]+=x/canvas.clientHeight*2;pan[1]-=y/canvas.clientHeight*2;}else{yaw+=x*.008;pitch=Math.max(-1.55,Math.min(1.55,pitch+y*.008));}invalidate();};
  const up=()=>{drag=null;};
  const wheel=e=>{e.preventDefault();zoom=Math.max(.05,Math.min(30,zoom*Math.exp(-e.deltaY*.001)));invalidate();};
  const key=e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-','=','f','F'].includes(e.key)){e.preventDefault();
    if(e.key==='ArrowLeft')yaw-=.12;if(e.key==='ArrowRight')yaw+=.12;if(e.key==='ArrowUp')pitch=Math.min(1.55,pitch+.12);if(e.key==='ArrowDown')pitch=Math.max(-1.55,pitch-.12);
    if(e.key==='+'||e.key==='=')zoom=Math.min(30,zoom*1.1);if(e.key==='-')zoom=Math.max(.05,zoom/1.1);if(e.key.toLowerCase()==='f'){zoom=.9;pan=[0,0];}invalidate();}};
  const context=e=>e.preventDefault();
  for(const [name,fn] of [['pointerdown',down],['pointermove',move],['pointerup',up],['pointercancel',up],['wheel',wheel],['keydown',key],['contextmenu',context]]) canvas.addEventListener(name,fn,{passive:false});
  const resize=new ResizeObserver(invalidate);resize.observe(canvas);
  return {
    async setData(nextPlanes,nextMesh=null,nextBounds=null){
      planes=nextPlanes;mesh=nextMesh;bounds=nextBounds;updateBounds();
      const keep=new Set(planes.map(p=>p.item.id));for(const [id,t] of textures)if(!keep.has(id)){gl.deleteTexture(t);textures.delete(id);}
      invalidate();await Promise.all(planes.map(plane=>loadTexture(plane.item).catch(onError)));
    },
    setWireframe(value){wire=value;invalidate();},setBox(value){showBox=value;invalidate();},
    view(axis){if(axis==='iso'){yaw=.8;pitch=.48;}else{yaw=axis==='x'?0:Math.PI/2;pitch=axis==='z'?Math.PI/2:0;}invalidate();},
    fit(){zoom=.9;pan=[0,0];invalidate();},
    camera:()=>({yaw,pitch,zoom,pan:[...pan]}),
    dispose(){disposed=true;discardMesh();cancelAnimationFrame(frame);resize.disconnect();for(const t of textures.values())gl.deleteTexture(t);gl.deleteBuffer(buffer);gl.deleteProgram(p);for(const [name,fn] of [['pointerdown',down],['pointermove',move],['pointerup',up],['pointercancel',up],['wheel',wheel],['keydown',key],['contextmenu',context]])canvas.removeEventListener(name,fn);},
  };
}
