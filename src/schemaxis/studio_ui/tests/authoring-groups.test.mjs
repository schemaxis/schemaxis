// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import test from 'node:test';
import {createAuthoringGroups} from '../windows/workbench/authoring-groups.mjs';
import {applyRows} from '../windows/workbench/element-authoring.mjs';
const node = (id, selector='//wall') => ({id,filter:'extractBlock',inputs:{input:'source'},options:{selectors:[selector]}});
test('explicit batches persist per scope, follow node identity, and tolerate Undo and missing membership', () => {
  const data=new Map(), storage={getItem:key=>data.get(key),setItem:(key,value)=>data.set(key,value)};
  const groups=createAuthoringGroups('doc:scope',storage);
  const startingValue=node('a');
  groups.remember({operation:'extractBlock',members:['a','b'],startingValue});
  const document={nodes:[node('unrelated'),node('b'),node('a')]};
  let saved=createAuthoringGroups('doc:scope',storage);
  const group=saved.find(document,'b','extractBlock');
  assert.deepEqual(group.existing.map(member=>member.pointer),['/nodes/2','/nodes/1']);
  assert.deepEqual(group.startingValue,startingValue);
  assert.equal(saved.find(document,'unrelated','extractBlock'),null,'same type and settings never imply membership');
  assert.equal(createAuthoringGroups('other',storage).find(document,'a','extractBlock'),null);
  groups.remember({operation:'extractBlock',members:['a','b','c'],startingValue});
  saved=createAuthoringGroups('doc:scope',storage);
  assert.equal(saved.find(document,'a','extractBlock').existing.length,2,'Undo restores earlier complete batch');
  assert.equal(saved.find({nodes:[...document.nodes,node('c')]},'c','extractBlock').existing.length,3,'Redo restores later batch');
  assert.deepEqual(saved.find({nodes:[node('a')]},'a','extractBlock').existing.map(member=>member.value.id),['a'],
    'a lone surviving member retains its batch without resurrecting deleted members');
  assert.equal(saved.find({nodes:[node('a')]},'b','extractBlock'),null,'the requested member must still exist');
  assert.equal(saved.find({nodes:[]},'a','extractBlock'),null,'a fully deleted batch cannot be reopened');
  assert.equal(saved.find({nodes:[node('a'),node('a'),node('b')]},'a','extractBlock'),null,'ambiguous identities are refused');
  assert.equal(saved.find({nodes:[node('a'),{id:'b',filter:'sphere'}]},'a','extractBlock'),null);
});
test('batch recovery omits deleted members, retains authored order and never absorbs other extracts', () => {
  const groups=createAuthoringGroups(null);
  const startingValue=node('a');
  groups.remember({operation:'extractBlock',members:['a','b','c'],startingValue});
  for (const removed of ['a','b','c']) {
    const nodes=['unrelated','c','a','b'].filter(id=>id!==removed).map(id=>node(id));
    const survivors=['a','b','c'].filter(id=>id!==removed);
    const group=groups.find({nodes},survivors[0],'extractBlock');
    assert.deepEqual(group.existing.map(member=>member.value.id),survivors);
    assert.deepEqual(group.existing.map(member=>nodes[Number(member.pointer.split('/').at(-1))].id),survivors);
    assert.deepEqual(group.members,['a','b','c'],'provenance retains deleted members for Undo');
    assert.deepEqual(group.startingValue,startingValue);
    assert.equal(groups.find({nodes},'unrelated','extractBlock'),null);
  }
});
test('reopened batches update noncontiguous originals in place and append new instances', () => {
  const a=node('a'),b=node('b');
  const document={nodes:[a,{id:'use_b',filter:'surface',inputs:{input:'b'}},b],scenes:[{geometry:['a','b']}]};
  const originals=[{pointer:'/nodes/2',value:b},{pointer:'/nodes/0',value:a}];
  const rows=[node('b','//changedB'),node('a','//changedA'),node('c')];
  const result=applyRows(document,rows,originals[1],originals);
  assert.equal(result.nodes.length,4);
  assert.deepEqual(result.nodes.map(value=>value.id),['a','use_b','b','c']);
  assert.deepEqual(result.nodes[0].options.selectors,['//changedA']);
  assert.deepEqual(result.nodes[2].options.selectors,['//changedB']);
  assert.equal(result.nodes[1].inputs.input,'b');
  assert.deepEqual(result.scenes,document.scenes);
  assert.deepEqual(document.nodes[0].options.selectors,['//wall']);
  assert.throws(()=>applyRows(document,[rows[1],rows[0]],originals[1],originals),/original Names/);
});
