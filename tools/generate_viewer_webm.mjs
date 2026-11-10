// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// Use Chromium's native VP8 encoder; the fixture requires no downloaded media.
import {fileURLToPath} from 'node:url';
import {writeFile} from 'node:fs/promises';
import {launch} from '../src/schemaxis/studio_ui/tests/fixtures/editor/cdp.mjs';
const root=fileURLToPath(new URL('../src/schemaxis_viewer/web/',import.meta.url));
const session=await launch({root,path:'/index.html'});
try {
  const encoded=await session.evaluate(`new Promise((resolve,reject)=>{
    const canvas=document.createElement('canvas');canvas.width=480;canvas.height=300;
    const ctx=canvas.getContext('2d'),stream=canvas.captureStream(12),chunks=[];
    const recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'});
    recorder.ondataavailable=e=>chunks.push(e.data);recorder.onerror=e=>reject(Error(e.error?.message||'Recording failed'));
    recorder.onstop=async()=>{const bytes=new Uint8Array(await new Blob(chunks).arrayBuffer());let binary='';for(const byte of bytes)binary+=String.fromCharCode(byte);stream.getTracks().forEach(t=>t.stop());resolve(btoa(binary));};
    let frame=0;const paint=()=>{ctx.fillStyle='#14202a';ctx.fillRect(0,0,480,300);ctx.fillStyle='#49c9b7';ctx.beginPath();ctx.arc(60+(frame%24)*15,150,30,0,Math.PI*2);ctx.fill();ctx.fillStyle='white';ctx.font='16px sans-serif';ctx.fillText('SYNTHETIC SAMPLE - browser animation',20,35);frame++;};
    paint();recorder.start();const timer=setInterval(paint,80);setTimeout(()=>{clearInterval(timer);recorder.stop();},1600);
  })`);
  await writeFile(process.argv[2],Buffer.from(encoded,'base64'));
}finally{await session.close();}
