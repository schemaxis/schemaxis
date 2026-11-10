// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {extractFilenameProperties,validateRules,presets} from '../../src/schemaxis_viewer/web/filename-rules.mjs';
import {automaticSequences,alphabeticRank} from '../../src/schemaxis_viewer/web/automatic-sequences.mjs';
import {matchesProperties,propertyFacets} from '../../src/schemaxis_viewer/web/filename.mjs';
import {buildGroups} from '../../src/schemaxis_viewer/web/model.mjs';
import {groupTree} from '../../src/schemaxis_viewer/web/grouping.mjs';

test('filename captures are typed and unmatched/empty groups assign no value',()=>{
  const rules=[{...presets.slices,pattern:'[sS]lices.([XYZ]).([0-9]*)'}];
  const {properties,counts}=extractFilenameProperties(['Slices.X.001.png','slices.Y.20.png','model.png','error.log','Slices.Z..png'].map(name=>({name})),rules);
  assert.deepEqual({...properties[0]},{'grep.axis':'X','grep.number':1});
  assert.deepEqual({...properties[1]},{'grep.axis':'Y','grep.number':20});
  assert.deepEqual({...properties[2]},{});assert.deepEqual({...properties[3]},{});
  assert.deepEqual({...properties[4]},{'grep.axis':'Z'});
  assert.equal(counts[0].matched,3);
  assert.deepEqual(extractFilenameProperties([{name:'Slices.X.001.png',skip:true}],rules).counts[0].matched,0);
});
test('list captures use literal separators and support OR within a key, AND across keys',()=>{
  const rules=[presets.tags,{name:'Codes',enabled:true,pattern:'file-([A-Z]+)-([0-9]+)-',columns:[{index:1,key:'code',type:'text'},{index:2,key:'index',type:'number'}]}];
  const items=['file-AAA-0-tags-red.blue.red-enclosedByDashes-name.png','file-AAB-1-tags-blue.green-enclosedByDashes-name.png','model.png'].map((name,i)=>({name,id:String(i)}));
  const {properties}=extractFilenameProperties(items,rules);items.forEach((item,i)=>item.derivedProperties=properties[i]);
  assert.deepEqual(properties[0]['grep.tags'],['red','blue']);
  assert.equal(propertyFacets(items).get('grep.tags').get('"blue"').ids.size,2);
  assert.equal(items.filter(item=>matchesProperties(item,new Map([['grep.tags',new Set(['"red"','"green"'])]]))).length,2);
  assert.equal(items.filter(item=>matchesProperties(item,new Map([['grep.tags',new Set(['"red"','"blue"'])],['grep.code','"AAA"']]))).length,1);
  buildGroups(items);const tree=groupTree(items,['grep.tags']);assert.equal(tree.find(n=>n.label==='(unspecified)').items.length,1);
});
test('rule validation, named groups, disabled rules, finite values and conflicting fields',()=>{
  const named={name:'Named',enabled:true,pattern:'(?<letter>[A-Z]+)-(?<value>.*)',columns:[{index:1,key:'letter',type:'text'},{index:2,key:'number',type:'number'}]};
  assert.equal(extractFilenameProperties([{name:'ABC-Infinity'}],[named]).properties[0]['grep.number'],undefined);
  assert.throws(()=>validateRules([{...named,pattern:'('}]));
  assert.throws(()=>validateRules([{...named,columns:[{index:1,key:'bad.key',type:'text'}]}]));
  assert.throws(()=>validateRules([{...named,columns:[{index:1,key:'tags',type:'tags',separator:''}]}]));
  assert.deepEqual({...extractFilenameProperties([{name:'ABC-2'}],[{...named,enabled:false,pattern:'('}]).properties[0]},{});
  const collision=[{...named,columns:[{index:1,key:'value',type:'text'}]},{...named,columns:[{index:2,key:'value',type:'text'}]}];
  assert.deepEqual(extractFilenameProperties([{name:'ABC-2'}],collision).properties[0]['grep.value'],['ABC','2']);
});
function infer(names) {
  const items=names.map((name,i)=>({id:String(i),name,scope:'source'})),automatic=automaticSequences(items);
  items.forEach(item=>{const entry=automatic.get(item.id);item.derivedProperties=entry.properties;item.autoFamily=entry.family;item.autoOrders=entry.orders;});
  return {items,groups:buildGroups(items)};
}
test('automatic numeric and alphabetic columns coexist and produce selectable ordered sequences',()=>{
  const {items,groups}=infer(['file-AAA-0-name.png','file-AAB-1-name.png','file-AAC-2-name.png']);
  assert.equal(groups.length,1);assert.equal(groups[0].sequences.length,2);
  assert.equal(items[1].derivedProperties['auto.number1'],1);assert.equal(items[1].derivedProperties['auto.letters1'],'AAB');
  assert.deepEqual(groups[0].sequences.find(s=>s.autoKind==='numeric').items.map(i=>i.id),['0','1','2']);
  assert.equal(groups[0].sequences.every(s=>s.axis==='index'&&s.inferred),true);
  assert.equal(infer(['file-A-1.png','file-B-2.png']).groups[0].sequences.length,2,'correlated numeric and alphabetic columns remain separate choices');
});
test('zero-padded integers order numerically and alphabetic codes use A…Z, AA… ordering',()=>{
  const numeric=infer(['shot-010.png','shot-001.png','shot-002.png']);
  assert.deepEqual(numeric.groups[0].sequences[0].items.map(i=>i.sequence.value),[1,2,10]);
  const alpha=infer(['phase-AA.png','phase-Z.png','phase-A.png','phase-B.png']);
  assert.deepEqual(alpha.groups[0].sequences[0].items.map(i=>i.sequence.displayValue),['A','B','Z','AA']);
  assert.equal(alphabeticRank('AA'),27);
});
test('automatic families respect folders and exclude ordinal dictionaries and declared metadata',()=>{
  const {groups}=infer(['first/shot-001.png','first/shot-002.png','second/shot-001.png','second/shot-002.png']);
  assert.equal(groups.length,2);assert.ok(groups.every(g=>g.sequences[0].items.length===2));
  const files=[{id:'1',name:'000001__kind_image.png'},{id:'2',name:'000002__kind_image.png'},{id:'3',name:'shot-001.png',metadata:{sequence:{id:'actual'}}},{id:'4',name:'model.png'}];
  assert.ok([...automaticSequences(files).values()].every(e=>!Object.keys(e.properties).length));
});
