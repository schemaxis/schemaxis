// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {assertCollectionCapacity, assertInsertionCapacity} from '../windows/workbench/collection-limit.mjs';

test('closed literal bounds permit capacity and refuse full or malformed collections without edits', () => {
  const limit = {path:'/nodes',maxItems:1}, root = {nodes:[{id:'saved'}]};
  const before = structuredClone(root);
  assert.doesNotThrow(() => assertCollectionCapacity(limit,{nodes:[]}));
  assert.doesNotThrow(() => assertCollectionCapacity(limit,{}));
  assert.doesNotThrow(() => assertCollectionCapacity(undefined,root,20));
  assert.throws(() => assertCollectionCapacity(limit,root), /Edit settings/);
  assert.throws(() => assertCollectionCapacity(limit,{nodes:null}), /must be an array/);
  assert.throws(() => assertCollectionCapacity(limit,{nodes:{}}), /must be an array/);
  assert.throws(() => assertCollectionCapacity(limit,null), /unavailable/);
  for (const bad of [{...limit,maxItems:true},{...limit,extra:1},{path:'/nodes'}, {...limit,path:'/a/{b}'}])
    assert.throws(() => assertCollectionCapacity(bad,root), /Invalid collection limit/);
  assert.deepEqual(root,before);
});

test('generic bounded collections count all inserted rows and recheck the current document', () => {
  const configured={collectionLimit:{path:'/chapters',maxItems:2},inserts:[{at:'/chapters/-',values:[{id:'a'},{id:'b'}]}]};
  assert.doesNotThrow(() => assertInsertionCapacity(configured,{chapters:[]}));
  assert.throws(() => assertInsertionCapacity(configured,{chapters:[{id:'existing'}]}), /at most 2/);
  assert.doesNotThrow(() => assertCollectionCapacity({path:'/scenes/0/images',maxItems:2},{scenes:[{images:[]}]},2));
  assert.throws(() => assertCollectionCapacity({path:'/scenes/0/images',maxItems:2},{scenes:[]}), /unavailable/);
  assert.throws(() => assertCollectionCapacity({path:'/empty',maxItems:0},{}), /at most 0/);
});


test('multiple or zero capacity and existing invalid settings have precise distinct recovery', () => {
  for (const maxItems of [0,2]) {
    const nodes=Array.from({length:maxItems},(_,i)=>({id:String(i)}));
    assert.throws(() => assertCollectionCapacity({path:'/nodes',maxItems},{nodes}), error =>
      /before adding more items/.test(error.message) && !/Edit settings/.test(error.message));
  }
  const invalid={nodes:[{id:'first'},{id:'second'}]},before=structuredClone(invalid);
  assert.throws(() => assertCollectionCapacity({path:'/nodes',maxItems:1},invalid,0), error =>
    /already contains 2/.test(error.message) && /before applying settings/.test(error.message)
      && !/Open the existing/.test(error.message));
  assert.deepEqual(invalid,before);
});
