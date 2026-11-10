// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {buildGroups} from '../../src/schemaxis_viewer/web/model.mjs';
import {groupTree,inGroupPath,photoSeries} from '../../src/schemaxis_viewer/web/grouping.mjs';
import {propertyFacets,matchesProperties} from '../../src/schemaxis_viewer/web/filename.mjs';
import {searchLines,captureColumns} from '../../src/schemaxis_viewer/web/search.mjs';

test('overlapping metadata properties, nested groups and unique membership',()=>{
  const items=[{id:'1',name:'a.png',metadata:{properties:{var:'U',axis:'X',tags:['review','spatial']}}},
    {id:'2',name:'b.png',metadata:{properties:{var:'U',axis:'Y',tags:['review']}}},
    {id:'3',name:'000001__var_p.png',metadata:{properties:{var:'U',axis:'X'}}},
    {id:'4',name:'readme.txt'}];
  buildGroups(items);
  const tree=groupTree(items,['var','axis','tags']),u=tree.find(n=>n.label==='U');
  assert.equal(u.items.length,3);assert.equal(u.children.find(n=>n.label==='X').items.length,2);
  assert.equal(tree.find(n=>n.label==='(unspecified)').items.length,1);
  assert.equal(items.filter(i=>inGroupPath(i,u.children.find(n=>n.label==='Y').path)).length,1);
  assert.equal(propertyFacets(items).get('var').get('"U"').ids.size,3);
  assert.ok(matchesProperties(items[0],new Map([['var','"U"'],['tags','"spatial"']])));
  assert.equal(propertyFacets(items).get('var').has('"p"'),false,'checked properties override hints');
});
test('photo series preserves real metadata and uses natural filename ordering',()=>{
  const items=[{id:'b',name:'photo10.png',kind:'image',metadata:{spatial:{frame:'world'}}},{id:'a',name:'photo2.png',kind:'image'},{name:'note.txt',kind:'text'}];
  const sequence=photoSeries(items);
  assert.deepEqual(sequence.items.map(i=>i.id),['a','b']);
  assert.equal(sequence.items[1].sequence.value,2);assert.equal(sequence.items[1].metadata,items[0].metadata);
  assert.equal(items[0].sequence,undefined);
});
test('Find counts occurrences, handles literal punctuation, case, words and empty input',()=>{
  assert.equal(searchLines({lines:['U UPPER u U.'],pattern:'U',wholeWord:true}).hits.length,3);
  assert.equal(searchLines({lines:['U u'],pattern:'U',sensitive:true}).hits.length,1);
  assert.equal(searchLines({lines:['x [a.b] [a.b]'],pattern:'[a.b]'}).hits.length,2);
  assert.equal(searchLines({lines:['abc'],pattern:''}).hits.length,0);
});
test('Grep exposes optional, nested, named groups and zero-length matches, bounds results',()=>{
  const pattern=String.raw`(?<time>\d+) (U=(\d+))?(?:x)(?=!)`;
  const result=searchLines({lines:['12 U=3x!','45 x!'],pattern,regex:true});
  assert.deepEqual(result.columns.map(c=>c.name),['time','Group 2','Group 3']);
  assert.deepEqual(result.hits.map(h=>h.captures),[['12','U=3','3'],['45','','']]);
  assert.deepEqual(captureColumns(String.raw`\( [(] (?:x) (?<=x)(?<value>a)`),[{index:1,name:'value'}]);
  assert.equal(searchLines({lines:['aaa'],pattern:'(?=a)',regex:true}).hits.length,3);
  assert.equal(searchLines({lines:['aaa'],pattern:'a',limit:2}).truncated,true);
  assert.throws(()=>searchLines({lines:[],pattern:'(',regex:true}));
});
