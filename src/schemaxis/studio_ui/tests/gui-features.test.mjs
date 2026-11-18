// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {caseDataCopy, caseDataCsv} from '../windows/workbench/case-data.mjs';
import {entriesOf, selectedNames, setNamesSelected} from '../windows/workbench/reader-selection.mjs';

test('case-data exports keep section identity, time types, ordering and CSV quoting', () => {
  const data={regions:['wall10','wall2','comma,name','quote"name','two\nlines'],cellArrays:['U','p'],availableTimes:[0.6,0.8,1]};
  assert.deepEqual(caseDataCopy(data).availableTimes,[0.6,0.8,1]);
  assert.deepEqual(caseDataCopy(data).regions.slice(-2),['wall2','wall10']);
  const csv=caseDataCsv(data);
  assert.ok(csv.includes('"Regions","comma,name"\r\n'));
  assert.ok(csv.includes('"Regions","quote""name"\r\n'));
  assert.ok(csv.includes('"Regions","two\nlines"\r\n'));
  assert.ok(csv.includes('"Times","0.6"\r\n'));
  assert.equal(caseDataCsv(data,'cellArrays'),'"Section","Value"\r\n"Cell arrays","p"\r\n"Cell arrays","U"\r\n');
});

test('bulk subset changes preserve unoffered paths and patterns, and cannot create implicit all', () => {
  const names=['wall1','wall2','inlet'];
  const original=entriesOf([{pattern:'^wall'},'/Root/other/not_loaded']);
  const removed=setNamesSelected(original,['wall1','wall2'],names,false,{blocks:true});
  assert.deepEqual(selectedNames(removed.entries,names,true),[]);
  assert.equal(removed.entries[0].text,'^wall');
  assert.equal(removed.entries[1].text,'/Root/other/not_loaded');
  assert.deepEqual(selectedNames(removed.entries,[...names,'wall3'],true),['wall3']);
  const restored=setNamesSelected(removed.entries,['wall1'],names,true,{blocks:true});
  assert.deepEqual(selectedNames(restored.entries,names,true),['wall1']);
  assert.deepEqual(original,entriesOf([{pattern:'^wall'},'/Root/other/not_loaded']));
  assert.deepEqual(setNamesSelected(entriesOf(['//wall1',{exclude:'inlet'}]),['wall1'],names,false,{blocks:true}).entries,[]);
  assert.deepEqual(setNamesSelected([],['not_available'],names,true,{blocks:true}).entries,[]);
});

test('large loaded supersets retain exact order and selections outside a bulk removal', () => {
  const names=Array.from({length:10000},(_,i)=>`block${i}`);
  const all=setNamesSelected([],names,names,true,{blocks:true});
  assert.deepEqual(selectedNames(all.entries,names,true),names);
  const remaining=setNamesSelected(all.entries,names.slice(200,9800),names,false,{blocks:true});
  assert.deepEqual(selectedNames(remaining.entries,names,true),[...names.slice(0,200),...names.slice(9800)]);
});
