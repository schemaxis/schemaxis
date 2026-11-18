// Copyright (C) 2026 David L. F. Gaden.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {volumeExpression, initialVolume, volumeSources, quotedName} from '../windows/spatial/volume-model.mjs';
const repository = fileURLToPath(new URL('../../../..', import.meta.url));
const root = {version:'schemaxis/1', definitions:{'my-box':{min:[0,0,0],max:[10,20,30]}}};
function evaluate(states) {
  const result = spawnSync('python3', ['-c', 'import sys,json\nfrom schemaxis.spatial_actions import spatial_eval\np=json.load(sys.stdin)\nprint(json.dumps([spatial_eval({"input":p["root"],"expression":e})["records"][0] for e in p["expressions"]]))'],
    {cwd:repository,env:{...process.env,PYTHONPATH:'src'},encoding:'utf8',input:JSON.stringify({root,expressions:states.map(volumeExpression)})});
  assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout);
}
const state = step => ({...initialVolume(),source:{kind:'value',expression:'definitions.`my-box`'},steps:step?[step]:[]});
test('all guided operations agree with the real host, including flat and disjoint results',()=>{
  const specs = [
    [{id:'inflate',values:['10','20','-100']},{min:[-.5,-2,15],max:[10.5,22,15]}],
    [{id:'inflateAbs',values:['2','4','6']},{min:[-1,-2,-3],max:[11,22,33]}],
    [{id:'resize',values:['2','4','0']},{min:[4,8,15],max:[6,12,15]}],
    [{id:'translate',values:['1','-2','3']},{min:[1,-2,3],max:[11,18,33]}],
    [{id:'pushAbs',face:'x-',values:['2']},{min:[-2,0,0],max:[10,20,30]}],
    [{id:'setFace',face:'z+',values:['40']},{min:[0,0,0],max:[10,20,40]}],
    [{id:'union',source:{kind:'coordinates',layout:'corners',a:['-1','0','0'],b:['11','2','3']}},{min:[-1,0,0],max:[11,20,30]}],
    [{id:'intersect',source:{kind:'coordinates',layout:'corners',a:['10','0','0'],b:['11','2','3']}},{min:[10,0,0],max:[10,2,3]}],
  ];
  const records = evaluate(specs.map(([step])=>state(step)));
  records.forEach((record,i)=>{assert.equal(record.state,'resolved',JSON.stringify(record));assert.equal(record.valid,true);assert.deepEqual(record.value,specs[i][1]);});
  const [empty] = evaluate([state({id:'intersect',source:{kind:'coordinates',layout:'corners',a:['11','0','0'],b:['12','2','3']}})]);
  assert.equal(empty.valid,false);
});
test('sources quote identifiers, respect workflow scope and reject bad numbers',()=>{
  const workflow={version:'schemaxis.workflow/1',definitions:{shared:[0,1,0,1,0,1]},operations:[
    {id:'one',document:{...root,nodes:[{id:'my-node',filter:'sphere'}]}},
    {id:'two',document:{version:'schemaxis/1',definitions:{private:[0,1,0,1,0,1]}}}]};
  const sources=volumeSources(workflow,'/operations/0/document');
  assert.deepEqual(sources.values.map(v=>v.expression),['workflow.definitions.`shared`','definitions.`my-box`']);
  assert.equal(volumeExpression({...initialVolume(),source:{kind:'node',node:sources.nodes[0].id}}),'extents(`my-node`)');
  assert.throws(()=>quotedName('bad`name'));
  assert.throws(()=>volumeExpression(state({id:'resize',values:['','1','2']})),/finite number/);
  assert.throws(()=>volumeExpression(state({id:'resize',values:['-1','1','2']})),/zero or greater/);
  const original={$expr:'inflate(definitions.`my-box`, 0.1)'};
  const edited=initialVolume({value:original,name:'adjusted',group:'definitions'});
  edited.steps.push({id:'translate',values:['1','2','3']});
  assert.equal(volumeExpression(edited),'translate(inflate(definitions.`my-box`, 0.1), vector(1, 2, 3))');
  assert.deepEqual(original,{$expr:'inflate(definitions.`my-box`, 0.1)'});
});
