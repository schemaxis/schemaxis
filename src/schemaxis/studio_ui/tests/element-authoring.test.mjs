// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import test from 'node:test';
import {suggestedName, applyRows, groupRows, splitMasterRows} from '../windows/workbench/element-authoring.mjs';
const item = {operation:'extractBlock', authoring:{naming:{path:'/options/selectors',style:'lastSegment',prefix:'extractBlock'}}};
const extract = (id, selectors) => ({id, filter:'extractBlock', inputs:{input:'case'},options:{selectors}});
test('configuration names work without multi-mode, retain semantic suffixes and resolve collisions', () => {
  assert.equal(suggestedName(item,extract('old',['/Root/internalMesh'])), 'extractBlock_internalMesh');
  assert.equal(suggestedName(item,extract('old',['//WT_wall_XP','//WT_wall_XM'])), 'extractBlock_WT_wall_XP_WT_wall_XM');
  assert.equal(suggestedName(item,extract('old',['//Inlet']),new Set(['extractBlock_Inlet'])), 'extractBlock_Inlet_2');
  assert.equal(suggestedName(item,extract('old',[{pattern:'wall.*'}])),null);
  assert.equal(suggestedName({operation:'other'},{}),null);
});
test('multi-mode updates the original and appends independent elements without changing references', () => {
  const original=extract('custom',['//internalMesh']);
  const document={nodes:[{id:'case',filter:'foam'},original,{id:'surface',filter:'surface',inputs:{input:'custom'}}],scenes:[{geometry:['custom']}]};
  const result=applyRows(document,[extract('custom',['//Inlet']),extract('extractBlock_wall',['//wall'])],{pointer:'/nodes/1',value:original});
  assert.equal(result.nodes.length,4);
  assert.equal(result.nodes[2].inputs.input,'custom');
  assert.deepEqual(result.scenes,document.scenes);
  assert.deepEqual(document.nodes[1].options.selectors,['//internalMesh']);
  assert.throws(()=>applyRows(document,[extract('renamed',['//x'])],{pointer:'/nodes/1',value:original}),/original Name/);
  assert.throws(()=>applyRows(document,[extract('custom',['//x'])]),/already in use/);
  assert.throws(()=>applyRows(document,[]),/at least one/);
});
test('grouping explicitly unions exact paths, refuses expressions and preserves protected originals', () => {
  const rows=[{value:extract('a',['/Root/A/wall'])},{value:extract('b',['/Root/B/wall'])}];
  const result=groupRows(rows,new Set([0,1]),'/options/selectors');
  assert.deepEqual(result[0].value.options.selectors,['/Root/A/wall','/Root/B/wall']);
  assert.equal(rows.length,2);
  assert.throws(()=>groupRows([{...rows[0],original:true},rows[1]],new Set([0,1]),'/options/selectors'),/original/);
  assert.throws(()=>groupRows([rows[0],{value:extract('b',[{exclude:'.*'}])}],new Set([0,1]),'/options/selectors'),/exact/);
});

test('master split replaces only a sole fresh starter and preserves its explicit Name', () => {
  const source=extract('myChoice',['//internalMesh','//WT_wall_XP','//WT_wall_XM','//Inlet']);
  const starter={value:structuredClone(source),starter:true,named:true};
  const result=splitMasterRows([starter],source,'/options/selectors');
  assert.equal(result.rows.length,4);
  assert.equal(result.replaced,true);
  assert.equal(result.rows[0].value.id,'myChoice');
  assert.equal(result.rows[0].named,true);
  assert.ok(result.rows.slice(1).every(row=>!row.named));
  assert.deepEqual(result.rows.map(row=>row.value.options.selectors),source.options.selectors.map(value=>[value]));
  assert.deepEqual(starter.value,source);
});
test('master split rejects conflicts atomically and compares complete settings', () => {
  const source=extract('unused',['//internalMesh','//Inlet']);
  const original={original:true,value:{options:{selectors:['//internalMesh']},inputs:{input:'case'},filter:'extractBlock',id:'owned'}};
  const conflicting=extract('unused',['//Inlet','//internalMesh']);
  assert.throws(()=>splitMasterRows([original],conflicting,'/options/selectors'),/already uses \/\/internalMesh/);
  const input=[original];
  const result=splitMasterRows(input,extract('unused',['//Inlet']),'/options/selectors');
  assert.equal(input.length,1);
  assert.equal(result.rows.length,2); assert.equal(result.rows[0],original);
  assert.throws(()=>splitMasterRows(result.rows,source,'/options/selectors'),/already uses/);
  assert.throws(()=>splitMasterRows([],extract('unused',['//Inlet','//Inlet']),'/options/selectors'),/repeated items/);
  const edited={value:extract('group',['//internalMesh','//Inlet']),starter:false,named:true};
  assert.equal(splitMasterRows([edited],source,'/options/selectors').rows.length,3);
  const different={value:{...extract('other',['//Inlet']),inputs:{input:'different'}}};
  assert.equal(splitMasterRows([different],source,'/options/selectors').rows.length,3);
  assert.throws(()=>splitMasterRows([],extract('x',[{pattern:'wall.*'}]),'/options/selectors'),/exact items/);
});

test('distinguishing settings drive names and batch keeps non-batch values fixed', () => {
  const entry = {operation: 'pvExtractBlock', authoring: {naming: {}, instanceFields: [
    {path: '/options/assembly', label: 'Assembly'},
    {path: '/options/expression', label: 'Expression', style: 'omit'},
    {path: '/options/selectors', label: 'Blocks', style: 'lastSegment'},
  ]}};
  const source = {...extract('base', ['/Root/inlet', '/Root/outlet']),
    options: {assembly: 'Hierarchy', expression: '2 * coordsX', selectors: ['/Root/inlet', '/Root/outlet']}};
  assert.equal(suggestedName(entry, source), 'pvExtractBlock_Hierarchy_inlet_outlet');
  const rows = splitMasterRows([], source, '/options/selectors').rows;
  assert.deepEqual(rows.map(row => row.value.options.assembly), ['Hierarchy', 'Hierarchy']);
  rows[1].value.options.assembly = 'Other';
  assert.throws(() => groupRows(rows, new Set([0, 1]), '/options/selectors'), /different settings/);
  assert.deepEqual(rows.map(row => row.value.options.selectors), [['/Root/inlet'], ['/Root/outlet']]);
});
