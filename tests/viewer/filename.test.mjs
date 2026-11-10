// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {parseFilename,propertyFacets,matchesProperties} from '../../src/schemaxis_viewer/web/filename.mjs';
import {buildGroups,cornersFor,sequenceInfo} from '../../src/schemaxis_viewer/web/model.mjs';
import {xyzSets} from '../../src/schemaxis_viewer/web/sequences.mjs';

test('Python producer and JavaScript consumer agree on scalar types, vectors, text and worker identifiers',()=>{
  const properties={kind:'slice',pos:-4.38e-6,normal:[-2.1,1,3],related:['A','B','C',11]};
  const samples=[properties,{value:'wall_shear'},{value:'é'},{value:'11'},{value:'list'},{value:''},
    {value:'a.x5F.b'},{value:true},{value:null},{value:[]},{value:['false','list','',null,false,3]}];
  const generated=JSON.parse(execFileSync('python3',['-c',
    'import json,sys;from schemaxis.artifact_names import stem;print(json.dumps([stem(i,p)+".png" for i,p in enumerate(json.loads(sys.argv[1]))]))',JSON.stringify(samples)],
    {env:{...process.env,PYTHONPATH:'src'},encoding:'utf8'}));
  generated.forEach((name,i)=>{assert.deepEqual({...parseFilename(name).properties},samples[i]);assert.match(name,/^[A-Za-z0-9._-]+$/);});
  assert.equal(parseFilename('000003.2__kind_image.png').worker,'2');
  assert.equal(parseFilename('000003.20__kind_image.png').worker,'20');
});
test('malformed dictionaries do not partially parse or fall back to numeric animation',()=>{
  for(const name of ['000000__var_U__var_p.png','000000__var_.xGG..png','000000__normal_list_list.png',
    '000000__pos_1e999.png','000000__var_.xFF..png','000000__noValue.png','000000__var_.png']) {
    assert.equal(parseFilename(name),null,name);
    assert.equal(sequenceInfo({name}),null,name);
  }
  assert.equal(parseFilename('000003__var_U.png.metadata.json'),null);
  assert.equal(sequenceInfo({name:'000003.20__kind_image__var_U.png'}),null);
});
test('overlapping facets intersect, lists contribute each member, and metadata companions stay out',()=>{
  const items=[{id:'a',name:'000000__kind_slice__axis_X__var_U__tags_list_A_B.png'},
    {id:'b',name:'000001__kind_slice__axis_Y__var_p__tags_list_B.png'},
    {id:'c',name:'000002__kind_table__var_U.csv'}];
  const facets=propertyFacets(items);
  assert.equal(facets.get('tags').get('"B"').ids.size,2);
  const filters=new Map([['kind','"slice"'],['var','"U"'],['tags','"B"']]);
  assert.deepEqual(items.filter(i=>matchesProperties(i,filters)).map(i=>i.id),['a']);
});
test('slice scenes group across numbered scene names, keep variants separate and form XYZ sets',()=>{
  let i=0;
  const items=['X','Y','Z'].flatMap(axis=>[0,.2].map(pos=>({name:`${String(i++).padStart(6,'0')}__kind_slice__scene_slice${axis}${i}__axis_${axis}__pos_${pos}__var_U__time_0__view_0.png`})));
  const groups=buildGroups(items);
  assert.equal(groups.length,1);assert.equal(groups[0].sequences.length,3);
  assert.equal(xyzSets(groups[0].sequences).length,1);
  assert.equal(cornersFor(items[0].metadata),null);
  items.push({name:'000007__kind_slice__axis_X__pos_0.1__var_U__time_0__view_1.png'});
  assert.equal(buildGroups(items)[0].sequences.length,3); // The singleton view is not spliced into view 0.
});
test('checked metadata coordinates take precedence over contradictory filename hints',()=>{
  const item={name:'000001__kind_slice__axis_X__pos_123__var_U.png',metadata:{spatial:{state:'known',mapping:'pixel-edge-rays-to-slice-plane',plane:{origin:[0,0,.5],normal:[0,0,1]},units:'m'}}};
  assert.equal(sequenceInfo(item).axis,'z');assert.equal(sequenceInfo(item).value,.5);
});
test('all-files grouping never splices independent import scopes or builds cross-scope XYZ sets',()=>{
  let i=0;
  const items=['X','Y','Z'].flatMap(axis=>[0,1].map(pos=>({scope:axis==='X'?'caseA':'caseB',name:`${String(i++).padStart(6,'0')}__kind_slice__axis_${axis}__pos_${pos}__var_U.png`})));
  const group=buildGroups(items,{groupBy:'all'})[0];
  assert.equal(xyzSets(group.sequences).length,0);
  const duplicates=buildGroups([...items,...items.map(i=>({...i,scope:'caseC'}))],{groupBy:'all'})[0];
  assert.equal(duplicates.sequences.length,6);
  assert.equal(xyzSets(duplicates.sequences).length,1);
});
test('filename time separates spatial stacks and also forms fixed-position temporal sequences',()=>{
  let index=0;
  const items=[0,1].flatMap(time=>['X','Y','Z'].flatMap(axis=>[0,.2].map(pos=>({name:`${String(index++).padStart(6,'0')}__kind_slice__axis_${axis}__pos_${pos}__var_U__time_${time}.png`}))));
  const group=buildGroups(items)[0];
  assert.equal(group.sequences.filter(s=>s.axis!=='time').length,6);
  assert.equal(group.sequences.filter(s=>s.axis==='time').length,6);
  assert.equal(xyzSets(group.sequences).length,2);
  assert.ok(group.sequences.every(s=>s.inferred));
});
