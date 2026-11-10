// Copyright (C) 2026 David L. F. Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {entries, saveEntry, reference, scopes, preview, valueCandidates, inspectionInput} from '../windows/variables/model.mjs';
import {parseNames} from '../windows/workbench/reader-selection.mjs';

test('reader names accept multiline, JSON and quoted comma-separated entries without double encoding', () => {
  for (const value of ['U\np', '["U", "p"]', '"U", "p"', 'U, p']) assert.deepEqual(parseNames(value), ['U', 'p']);
  assert.throws(() => parseNames('[1,2]'), /names/);
});
test('rename and move update nested consumers, scoped references and parameter targets immutably', () => {
  const root = {version:'schemaxis.workflow-design/2', workflow:{version:'schemaxis.workflow/1', dimensions:{box:{min:[0,0,0],max:[2,4,6]}},operations:[
    {id:'reader', document:{version:'schemaxis/1', settings:{component:{$document:'/dimensions/box/max/0',scope:'workflow'}}}}]},parameters:{
      size:{target:{scope:'workflow',pointer:'/dimensions/box/max/0'}}}};
  const old = entries(root)[0];
  const result = saveEntry(root,{base:'/workflow',name:'model',group:'settings',value:old.value},old);
  assert.deepEqual(result.workflow.operations[0].document.settings.component, {$document:'/settings/model/max/0',scope:'workflow'});
  assert.equal(result.parameters.size.target.pointer,'/settings/model/max/0');
  assert.equal(root.workflow.dimensions.box.max[0],2);
  const candidates = valueCandidates(result);
  const component = candidates.find(e=>e.name==='model.max.x');
  assert.equal(preview(result, reference(component,scopes(result)[1]),scopes(result)[1]),2);
});
test('moving a value canonicalises its own relative references at the definition site', () => {
  const root={version:'schemaxis/1',dimensions:{size:3, twice:{$expr:{op:'multiply',args:[{$document:'../size'},2]}}},settings:{used:{$document:'/dimensions/twice'}}};
  // Reference is relative to the containing args array, so use an explicit absolute pointer here.
  root.dimensions.twice.$expr.args[0]={$document:'/dimensions/size'};
  const old=entries(root).find(e=>e.name==='twice');
  const next=saveEntry(root,{base:'',name:'double',group:'settings',value:old.value},old);
  assert.equal(preview(next,next.settings.used),6);
  assert.equal(next.settings.used.$document,'/settings/double');
  assert.equal(next.dimensions.twice,undefined);
});

test('moving a relative alias preserves its definition-site lookup', () => {
  const root={version:'schemaxis/1',dimensions:{source:3,alias:{$document:'./source'}},settings:{used:{$document:'/dimensions/alias'}}};
  const old=entries(root).find(e=>e.name==='alias');
  const next=saveEntry(root,{base:'',name:'moved',group:'settings',value:old.value},old);
  assert.deepEqual(next.settings.moved,{$document:'/dimensions/source'});
  assert.equal(preview(next,next.settings.used),3);
});

test('draft inspection binds shared reader paths and keeps unfinished downstream nodes for pruning', () => {
  const input={version:'schemaxis/1',nodes:[{id:'case',filter:'foam',options:{file:{$document:'/settings/file',scope:'workflow'}}},
    {id:'unfinished',filter:'slice',options:{$document:'/notReady'}}]};
  const root={version:'schemaxis.workflow/1',settings:{file:'case.foam'},operations:[{id:'post',document:input}]};
  const result=inspectionInput(root,input,'/operations/0/document');
  assert.equal(result.nodes[0].options.file,'case.foam');
  assert.deepEqual(result.nodes[1],input.nodes[1]);
  assert.equal(typeof input.nodes[0].options.file,'object');
});
