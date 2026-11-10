// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn,execFileSync} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {homedir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {launch} from '../../src/schemaxis/studio_ui/tests/fixtures/editor/cdp.mjs';
const repository=fileURLToPath(new URL('../../',import.meta.url));

test('portable ZIP runs independently under isolated Python and serves working search workers with strict CSP',async()=>{
  const temporary=await mkdtemp(join(homedir(),'artifact-portable-'));let server,session;
  try{
    const archive=join(temporary,'viewer.zip');
    execFileSync('python3',[join(repository,'tools/package_viewer.py'),archive,'--sample',join(repository,'examples/viewer-test')],{timeout:15000});
    execFileSync('python3',['-I','-S','-m','zipfile','-e',archive,temporary],{timeout:15000});
    const folder=join(temporary,'artifact-viewer'),environment={...process.env};delete environment.PYTHONPATH;
    server=spawn('python3',['-I','-S',join(folder,'launch.py'),'--no-browser',join(folder,'sample')],{cwd:folder,env:{...environment,XDG_STATE_HOME:join(temporary,'state')},stdio:['ignore','pipe','pipe']});
    const url=await new Promise((resolve,reject)=>{
      let output='';const timer=setTimeout(()=>reject(Error('Portable server startup timed out: '+output)),10000);
      server.stdout.on('data',data=>{output+=data;const match=/Artifact viewer: (http:\/\/\S+)/.exec(output);if(match){clearTimeout(timer);resolve(match[1]);}});
      server.once('error',error=>{clearTimeout(timer);reject(error);});
      server.once('exit',code=>{clearTimeout(timer);reject(Error('Portable server exited: '+code));});
    });
    const response=await fetch(url);assert.match(response.headers.get('content-security-policy'),/script-src 'self'/);
    session=await launch({root:join(folder,'schemaxis_viewer/web'),path:'/index.html',width:1500,height:1000});
    await session.send('Page.navigate',{url});
    await session.wait('Boolean(window.artifactViewer)&&artifactViewer.items.some(i=>i.name.endsWith("legacy/alphabetic/phase-AA.png"))','portable sample inventory');
    assert.equal(await session.evaluate('artifactViewer.issues.length'),0);
    assert.equal(await session.evaluate('artifactViewer.items.filter(i=>i.metadata?.spatial?.corners).length'),36);
    await session.evaluate(`document.querySelector('.filename-rules').open=true;[...document.querySelectorAll('button')].find(n=>n.textContent==='Add slice example').click();[...document.querySelectorAll('button')].find(n=>n.textContent==='Apply filename rules').click();`);
    await session.wait('artifactViewer.items.filter(i=>i.derivedProperties["grep.axis"]).length===4','filename rule worker under packaged CSP');
    await session.evaluate('artifactViewer.openFile(artifactViewer.items.find(i=>i.filename?.properties.name==="solver"))');
    await session.wait(`Boolean(document.querySelector('[aria-label="Search text"]'))`,'portable text viewer');
    await session.evaluate(`(()=>{const input=document.querySelector('[aria-label="Search text"]');input.value='Time=';input.dispatchEvent(new Event('input'));})()`);
    await session.wait('document.querySelector(".text-tools").textContent.includes("450 matches")','worker results under CSP');
    assert.equal(session.exceptions.length,0,JSON.stringify(session.exceptions));
  }finally{
    await session?.close();
    if(server&&server.exitCode===null){const exited=new Promise(resolve=>server.once('exit',resolve));server.kill();await exited;}
    await rm(temporary,{recursive:true,force:true});
  }
});
