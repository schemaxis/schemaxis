import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {VERSION,attachMetadata,buildGroups,cornersFor,advance,parseDelimited,relativeItem,nearestIndex,inferName,boundsFor,cameraUV} from '../../src/schemaxis_viewer/web/model.mjs';
import {meshFromBytes,quadWeights} from '../../src/schemaxis_viewer/web/scene.mjs';
import {imageUV,xyzSets} from '../../src/schemaxis_viewer/web/sequences.mjs';
const spatial={state:'known',frame:'case',units:'m',mapping:'pixel-edge-rays-to-slice-plane',corners:[[0,1,0],[1,1,0],[1,0,0],[0,0,0]],cornerOrder:['top-left','top-right','bottom-right','bottom-left']};
const item=(name,metadata={})=>({name,size:1,metadata});
test('three corner reconstruction, validation and camera-plane distinction',()=>{
 assert.deepEqual(cornersFor({spatial}),spatial.corners);
 assert.deepEqual(cornersFor({spatial:{...spatial,corners:[spatial.corners[0],spatial.corners[1],spatial.corners[3]],cornerOrder:['top-left','top-right','bottom-left']}}),spatial.corners);
 assert.equal(cornersFor({spatial:{...spatial,mapping:'camera-focal-plane'}}),null);
 assert.equal(cornersFor({spatial:{...spatial,corners:[[0,0,0],[0,0,0],[0,0,0],[0,0,0]]}}),null);
 assert.equal(cornersFor({spatial:{...spatial,corners:[[0,1,0],[1,1,0],[1,0,1],[0,0,0]]}}),null);
});
test('numeric filenames group X Y Z in natural numeric order without declaring spatial evidence',()=>{
 const groups=buildGroups(['10','2','1'].flatMap(n=>['x','y','z'].map(a=>item(`run/pressure_${a}_${n}.png`))));
 assert.equal(groups.length,1);assert.equal(groups[0].sequences.length,3);assert.equal(xyzSets(groups[0].sequences).length,1);
 assert.deepEqual(groups[0].sequences[0].items.map(i=>i.sequence.value),[1,2,10]);
 assert.equal(groups[0].sequences[0].inferred,true);
 assert.equal(inferName('image.png'),null);
});
test('time and frame prevent unrelated spatial stacks merging',()=>{
 const records=[0,1].flatMap(time=>['x','y','z'].flatMap(axis=>[1,2].map(value=>item(`${time}_${axis}_${value}.png`,{group:'case',viewTime:time,spatial,sequence:{id:'p',axis,value,units:'m'}}))));
 const g=buildGroups(records)[0];assert.equal(g.sequences.filter(s=>s.axis!=='time').length,6);assert.equal(g.sequences.filter(s=>s.axis==='time').length,6);assert.equal(xyzSets(g.sequences).length,2);
});
test('playback boundaries: repeat, oscillate, once, reverse, singleton',()=>{
 assert.deepEqual(advance(2,1,3,'repeat'),{index:0,direction:1,stopped:false});
 assert.deepEqual(advance(2,1,3,'oscillate'),{index:1,direction:-1,stopped:false});
 assert.deepEqual(advance(0,-1,3,'oscillate'),{index:1,direction:1,stopped:false});
 assert.deepEqual(advance(2,1,3,'once'),{index:2,direction:1,stopped:true});
 assert.equal(advance(0,1,1,'repeat').stopped,true);
 assert.equal(nearestIndex([{sequence:{value:1}},{sequence:{value:8}},{sequence:{value:15}}],10),1);
});
test('quoted CSV, embedded delimiters, multiline fields and blank trailing fields',()=>{
 assert.deepEqual(parseDelimited('a,b,c\r\n1,"two, three","four\nlines"\r\n2,"a ""quote""",\r\n'),[['a','b','c'],['1','two, three','four\nlines'],['2','a "quote"','']]);
 assert.throws(()=>parseDelimited('x,"unfinished'),/Unterminated/);
 assert.deepEqual(parseDelimited('a,b\n1,2\n3,"unfinished\nfield',',',{allowIncomplete:true}),[['a','b'],['1','2']]);
});
test('overview paths resolve only selected artifacts',()=>{
 const owner=item('root/slices/x.png'),overview=item('root/domain.png');
 assert.equal(relativeItem([owner,overview],owner,'../domain.png'),overview);
 assert.equal(relativeItem([owner,overview],owner,'../../../etc/passwd'),null);
 assert.equal(relativeItem([owner],owner,'https://bad.test'),null);
});
test('metadata ownership and hash must match; foreign sidecars remain ordinary files',async()=>{
 const bytes=new TextEncoder().encode('image').buffer;
 const hash=Buffer.from(await webcrypto.subtle.digest('SHA-256',bytes)).toString('hex');
 const target={name:'root/slice.png',size:1,bytes:async()=>bytes};
 const make=data=>({name:'root/slice.png.metadata.json',size:100,text:async()=>JSON.stringify(data)});
 const foreign=make({version:'other/1'});assert.deepEqual(await attachMetadata([target,foreign]),[]);assert.equal(foreign.isMetadata,undefined);
 let side=make({version:VERSION,artifact:{file:'slice.png',sha256:hash},spatial});
 assert.deepEqual(await attachMetadata([target,side]),[]);assert.equal(target.metadataStatus,'SHA-256 matched');
 delete target.metadata;side=make({version:VERSION,artifact:{file:'slice.png',sha256:'0'.repeat(64)},spatial});
 assert.match((await attachMetadata([target,side]))[0],/mismatch/);assert.equal(target.metadata,undefined);
});
test('OBJ triangulates polygons, supports negative indices, rejects bad vertices',()=>{
 const bytes=s=>new TextEncoder().encode(s).buffer;
 assert.equal(meshFromBytes(bytes('v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf -4 -3 -2 -1'),'a.obj').length,18);
 assert.throws(()=>meshFromBytes(bytes('v NaN 0 0\nv 1 0 0\nv 1 1 0\nf 1 2 3'),'a.obj'),/Invalid mesh/);
 assert.throws(()=>meshFromBytes(bytes('v 0 0 0\nf 1 2 3'),'a.obj'),/missing/);
});
test('projective UV mapping honours corners and interior for trapezoid',()=>{
 const c=[[0,1,0],[2,1,0],[1.5,0,0],[.5,0,0]];
 assert.equal(quadWeights(c).length,4);
 for(const [i,expected]of [[0,[0,0]],[1,[1,0]],[2,[1,1]],[3,[0,1]]])imageUV(c,c[i]).forEach((v,k)=>assert.ok(Math.abs(v-expected[k])<1e-8));
 assert.equal(imageUV(c,[10,10,0]),null);
});

test('bounds honour declared order and reject unspecified conventions',()=>{
 assert.deepEqual(boundsFor({spatial:{bounds:[0,0,0,2,3,4],boundsOrder:['xmin','ymin','zmin','xmax','ymax','zmax']}}),[0,2,0,3,0,4]);
 assert.equal(boundsFor({spatial:{bounds:[0,2,0,3,0,4]}}),null);
});
test('native publication identities group visits and isolate camera styles',()=>{
 const records=[0,1].flatMap(value=>[0,1].map(camera=>item(`case/visit-${value}-camera-${camera}.png`,{identity:{scene:'cuts',writer:'pressure',appearance:0,camera},spatial:{...spatial,plane:{origin:[value,0,0],normal:[1,0,0]}}})));
 const groups=buildGroups(records);assert.equal(groups.length,1);assert.equal(groups[0].sequences.length,2);assert.deepEqual(groups[0].sequences[0].items.map(i=>i.sequence.value),[0,1]);
 assert.equal(buildGroups(records,{groupBy:'all'})[0].name,'All selected files');
});
test('duplicate recognised companions invalidate ambiguous placement',async()=>{
 const bytes=new TextEncoder().encode('image').buffer,hash=Buffer.from(await webcrypto.subtle.digest('SHA-256',bytes)).toString('hex');
 const target={name:'slice.png',size:1,bytes:async()=>bytes};
 const value={version:VERSION,artifact:{file:'slice.png',sha256:hash},spatial};
 const sides=['slice.png.metadata.json','slice.png.scxmeta'].map(name=>({name,size:1,text:async()=>JSON.stringify(value)}));
 assert.match((await attachMetadata([target,...sides]))[0],/ambiguous/);assert.equal(target.metadata,undefined);
});

test('overview camera maps world coordinates without inventing a registration',()=>{
 const camera={position:[0,0,10],focalPoint:[0,0,0],up:[0,1,0],parallel:true,scale:1};
 assert.deepEqual(cameraUV([0,0,0],camera,2),[.5,.5]);assert.deepEqual(cameraUV([2,1,0],camera,2),[1,0]);
 assert.equal(cameraUV([0,0,11],{...camera,parallel:false,viewAngle:45},2),null);assert.equal(cameraUV([0,0,0],{},2),null);
});
