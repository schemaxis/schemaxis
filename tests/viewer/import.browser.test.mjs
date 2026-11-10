import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {homedir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {launch} from '../../src/schemaxis/studio_ui/tests/fixtures/editor/cdp.mjs';
const root=fileURLToPath(new URL('../../src/schemaxis_viewer/web/',import.meta.url));
const repository=fileURLToPath(new URL('../../',import.meta.url));
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jF+kAAAAASUVORK5CYII=','base64');
const selectFiles=async(session,selector,files)=>{
 const previous=await session.evaluate('artifactViewer.items.map(i=>i.id)');
 const {root}=await session.send('DOM.getDocument');
 const {nodeId}=await session.send('DOM.querySelector',{nodeId:root.nodeId,selector});
 await session.send('DOM.setFileInputFiles',{nodeId,files});
 await session.wait(`artifactViewer.items.some(i=>!${JSON.stringify(previous)}.includes(i.id))&&document.querySelector(${JSON.stringify(selector)}).value===''`,'selection finished');
};

test('Open folder replaces the current data, including same-named folders and refreshed metadata',async()=>{
 const dir=await mkdtemp(join(homedir(),'artifact-viewer-folders-'));let session;
 try{
  const first=join(dir,'first','results'),second=join(dir,'second','results');
  const writeFolder=async(folder,start)=>{
   await mkdir(folder,{recursive:true});
   for(let i=0;i<2;i++){
    const name=`slice_${i}.png`,value=start+i;
    await writeFile(join(folder,name),png);
    await writeFile(join(folder,name+'.metadata.json'),JSON.stringify({version:'schemaxis.artifact-metadata/1',artifact:{file:name,sha256:createHash('sha256').update(png).digest('hex')},group:'CFD results',sequence:{id:'pressure',axis:'x',value,units:'m'}}));
   }
  };
  await writeFolder(first,1);await writeFolder(second,11);
  await writeFile(join(dir,'notes.txt'),'additional local data');
  session=await launch({root,path:'/index.html',width:1500,height:1000});
  await session.wait('Boolean(window.artifactViewer)','viewer startup');
  await selectFiles(session,'#folder',[first]);
  assert.equal(await session.evaluate('artifactViewer.items.length'),4);
  assert.deepEqual(await session.evaluate('artifactViewer.groups[0].sequences[0].items.map(i=>i.sequence.value)'),[1,2]);
  await session.evaluate(`window.oldUrls=artifactViewer.items.map(i=>i.url);window.oldIds=artifactViewer.items.map(i=>i.id);document.querySelector('#filter').value='first-only';artifactViewer.openFile(artifactViewer.groups[0].items[1]);`);
  await session.wait('Boolean(document.querySelector(".detail-image"))','old folder detail');
  await selectFiles(session,'#folder',[second]);
  assert.equal(await session.evaluate('artifactViewer.items.length'),4,'opening a folder replaces rather than appends');
  assert.deepEqual(await session.evaluate('artifactViewer.groups[0].sequences[0].items.map(i=>i.sequence.value)'),[11,12]);
  assert.equal(await session.evaluate('document.querySelector("#filter").value'),'','old filter must not hide the new folder');
  assert.equal(await session.evaluate('document.querySelectorAll(".detail-image").length'),0);
  assert.equal(await session.evaluate('document.querySelectorAll(".card").length'),2);
  assert.match(await session.evaluate('document.querySelector("#location").textContent'),/X = 11/);
  assert.equal(await session.evaluate('artifactViewer.items.some(i=>oldIds.includes(i.id))'),false);
  assert.ok(await session.evaluate('Promise.all(oldUrls.map(url=>fetch(url).then(()=>false,()=>true))).then(results=>results.every(Boolean))'),'replaced file URLs are released');
  await selectFiles(session,'#files',[join(dir,'notes.txt')]);
  assert.equal(await session.evaluate('artifactViewer.items.length'),5,'Add files still appends');
  await writeFolder(second,21);
  await selectFiles(session,'#folder',[second]);
  assert.equal(await session.evaluate('artifactViewer.items.length'),4,'reopening the same folder refreshes the data');
  assert.deepEqual(await session.evaluate('artifactViewer.groups[0].sequences[0].items.map(i=>i.sequence.value)'),[21,22]);
  // Cancelling a picker must leave the current folder in place.
  await session.evaluate(`(()=>{const input=document.querySelector('#folder');input.dispatchEvent(new Event('change'));return Promise.resolve();})()`);
  assert.equal(await session.evaluate('artifactViewer.items.length'),4);
  // The browser-only fallback also opens an empty folder rather than retaining old data.
  await session.evaluate(`window.showDirectoryPicker=async()=>({name:'Empty folder',async *values(){}})`);
  await session.evaluate(`document.querySelector('#open-folder').onclick()`);
  await session.wait('artifactViewer.items.length===0','empty browser folder replaces the session');
  assert.match(await session.evaluate('document.querySelector("#subtitle").textContent'),/empty/i);
  assert.equal(session.exceptions.length,0,JSON.stringify(session.exceptions));
 }finally{await session?.close();await rm(dir,{recursive:true,force:true});}
});

test('real local server: checked sidecars, registered mesh, strict CSP, hash failure, browser imports',async()=>{
 const dir=await mkdtemp(join(homedir(),'artifact-viewer-test-')),state=await mkdtemp(join(homedir(),'artifact-viewer-state-'));let server,session;
 try{
  const hash=createHash('sha256').update(png).digest('hex');
  for(const axis of ['x','y','z'])for(const value of [0,1]) {
   const corners=axis==='x'?[[value,0,1],[value,1,1],[value,1,0],[value,0,0]]:axis==='y'?[[0,value,1],[1,value,1],[1,value,0],[0,value,0]]:[[0,1,value],[1,1,value],[1,0,value],[0,0,value]];
   const name=`p_${axis}_${value}.png`,normal=[0,0,0];normal['xyz'.indexOf(axis)]=1;
   await writeFile(join(dir,name),png);
   await writeFile(join(dir,name+'.metadata.json'),JSON.stringify({version:'schemaxis.artifact-metadata/1',artifact:{file:name,sha256:hash},group:'Imported CFD',sequence:{id:'p',axis,value,units:'m'},spatial:{state:'known',mapping:'pixel-edge-rays-to-slice-plane',frame:'run',units:'m',corners,cornerOrder:['top-left','top-right','bottom-right','bottom-left'],plane:{normal,origin:corners[0]},bounds:[0,1,0,1,0,1],boundsOrder:['xmin','xmax','ymin','ymax','zmin','zmax']}}));
  }
  const mesh='v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n';await writeFile(join(dir,'domain.obj'),mesh);
  await writeFile(join(dir,'domain.obj.metadata.json'),JSON.stringify({version:'schemaxis.artifact-metadata/1',artifact:{file:'domain.obj',sha256:createHash('sha256').update(mesh).digest('hex')},group:'Imported CFD',spatial:{state:'known',frame:'run',units:'m'}}));
  await writeFile(join(dir,'bad.png'),png);await writeFile(join(dir,'bad.png.metadata.json'),JSON.stringify({version:'schemaxis.artifact-metadata/1',artifact:{file:'bad.png',sha256:'0'.repeat(64)}}));
  server=spawn('python3',['-u','-m','schemaxis_viewer','--no-browser',dir],{cwd:repository,env:{...process.env,PYTHONPATH:join(repository,'src'),XDG_STATE_HOME:state},stdio:['ignore','pipe','pipe']});
  const url=await new Promise((resolve,reject)=>{let output='';const timer=setTimeout(()=>reject(Error('Server startup timed out')),10000);server.stdout.on('data',data=>{output+=data;const match=/Artifact viewer: (http:\/\/\S+)/.exec(output);if(match){clearTimeout(timer);resolve(match[1]);}});server.once('error',reject);});
  session=await launch({root,path:'/index.html',width:1500,height:1000});
  await session.send('Page.navigate',{url});await session.wait('Boolean(window.artifactViewer)&&artifactViewer.items.length===16','server inventory loaded');
  assert.equal(await session.evaluate('artifactViewer.items.filter(i=>i.metadataStatus==="SHA-256 matched").length'),7);
  assert.equal(await session.evaluate('artifactViewer.issues.length'),1);
  assert.match(await session.evaluate('artifactViewer.issues[0]'),/mismatch/);
  await session.evaluate(`document.querySelector('#library button').click()`);
  await session.evaluate(`(()=>{const b=[...document.querySelectorAll('#library button')].find(b=>b.textContent.includes('Imported CFD'));b.click();[...document.querySelectorAll('#modebar button')].find(b=>b.textContent.includes('3D')).click();})()`);
  await session.wait('Boolean(window.artifactScene)&&document.querySelectorAll(".sequence-panel").length===3','registered image planes');
  assert.ok(await session.evaluate('document.querySelector("#content").textContent.includes("supplied domain mesh")'));
  // DOM file input is the same browser import path used by Add files.
  const {root:documentRoot}=await session.send('DOM.getDocument');
  const {nodeId}=await session.send('DOM.querySelector',{nodeId:documentRoot.nodeId,selector:'#files'});
  await session.send('DOM.setFileInputFiles',{nodeId,files:[join(dir,'p_x_0.png'),join(dir,'p_x_0.png.metadata.json')]});
  await session.wait('artifactViewer.items.length===18','browser-selected files added');
  assert.equal(await session.evaluate('artifactViewer.items.filter(i=>i.metadataStatus==="SHA-256 matched").length'),8,JSON.stringify(await session.evaluate('({issues:artifactViewer.issues,items:artifactViewer.items.slice(-2).map(i=>({name:i.name,size:i.size,metadata:i.metadata,status:i.metadataStatus}))})')));
  assert.equal(session.exceptions.length,0,JSON.stringify(session.exceptions));
  const errors=session.logs.filter(l=>/violates.*Content Security|Refused to (execute|load)|not allowed by.*policy/i.test(l));assert.deepEqual(errors,[]);
 }finally{await session?.close();if(server&&server.exitCode===null){server.kill();await new Promise(r=>server.once('exit',r));}await rm(dir,{recursive:true,force:true});await rm(state,{recursive:true,force:true});}
});
