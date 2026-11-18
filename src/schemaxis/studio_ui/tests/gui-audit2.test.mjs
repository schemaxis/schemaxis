// Copyright (C) 2026 David L. F. Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {parse} from '../editor/json-parse.mjs';
import {pointerAt} from '../editor/json-pointer.mjs';
import {completionsAt} from '../editor/schema-complete.mjs';
import {entryName} from '../windows/workbench/authoring-defaults.mjs';
import {caseNames} from '../windows/workbench/case-data.mjs';
import {entriesOf, matchesOf} from '../windows/workbench/reader-selection.mjs';
import {checkField} from '../editor/fill-data.mjs';

test('reader names combine parent and file stem, collapse duplicates and keep valid unique identities', () => {
  const used = new Set(['foam1', 'run_coupe_AMI', 'run_coupe_AMI_2']);
  assert.equal(entryName('/data/run/42_b/coupe.foam', used), '42_b_coupe');
  assert.equal(entryName('/data/run/42_b/case.foam', used), '42_b_case');
  assert.equal(entryName('/data/run/wing/Case.foam', used), 'wing_Case');
  assert.equal(entryName('/data/run/coupe_AMI.foam', used), 'run_coupe_AMI_3');
  assert.equal(entryName('/data/my case/a b.c.foam', used), 'my_case_a_b_c');
  assert.equal(entryName('004_031_9d/case.foam', used), '004_031_9d_case');
  assert.equal(entryName('004_031_9d/004_031_9d.foam', used), '004_031_9d');
  assert.equal(entryName('/data/wing/wing.foam', used), 'wing');
  assert.equal(entryName('C:\\cases\\wing\\wing.foam', used), 'wing');
  assert.equal(entryName('wing.foam', used), 'wing');
  assert.equal(entryName('./wing.foam', used), 'wing');
  assert.equal(entryName('../wing.foam', used), 'wing');
  assert.equal(entryName('/data/wing/.foam', used), null);
  assert.equal(entryName({$value: 'path'}, used), null);
  assert.equal(entryName('', used), null);
  assert.deepEqual([...used], ['foam1', 'run_coupe_AMI', 'run_coupe_AMI_2']);
});

test('Name placeholders honour the instance schema without changing other identifier rules', () => {
  const instance = {type: 'id', pattern: '^[A-Za-z0-9][A-Za-z0-9_-]*$'};
  assert.equal(checkField('004_031_9d_case', instance), '');
  assert.ok(checkField('../case', instance));
  assert.ok(checkField('004_031_9d_case', {type: 'id'}));
});

test('selection entries round-trip exact names and patterns and report what they match', () => {
  const available = ['internalMesh', 'patch/wheels_FL_Tyre', 'patch/wheels_RR_Tyre', 'patch/body_upper'];
  assert.deepEqual(entriesOf(['internalMesh', {pattern: '^patch/wheels_'}]),
    [{text: 'internalMesh', regex: false}, {text: '^patch/wheels_', regex: true}]);
  assert.deepEqual(entriesOf({pattern: '^U'}), [{text: '^U', regex: true}]);
  assert.deepEqual(entriesOf({select: 'all'}), []);
  assert.deepEqual(matchesOf({text: '^patch/wheels_', regex: true}, available), available.slice(1, 3));
  assert.deepEqual(matchesOf({text: 'patch', regex: false}, available), []);
  assert.equal(matchesOf({text: '[', regex: true}, available), null);
});

test('case names are offered by setting, and never for identities or files', () => {
  const inspection = {available: true, regions: ['internalMesh', 'patch/walls'], cellArrays: ['U', 'p']};
  assert.deepEqual(caseNames(inspection, '/nodes/0/options/regions/1').map((item) => item.value), ['internalMesh', 'patch/walls']);
  assert.deepEqual(caseNames(inspection, '/nodes/0/options/cellArrays/0').map((item) => item.value), ['U', 'p']);
  assert.deepEqual(caseNames(inspection, '/nodes/2/options/field').map((item) => item.value), ['U', 'p', 'internalMesh', 'patch/walls']);
  assert.deepEqual(caseNames(inspection, '/nodes/0/id'), []);
  assert.deepEqual(caseNames(inspection, '/nodes/0/options/file'), []);
  assert.deepEqual(caseNames({available: false}, '/nodes/0/options/regions/0'), []);
  assert.deepEqual(caseNames(null, '/nodes/0/options/regions/0'), []);
});

test('the editor suggests case names where text is accepted and the schema lists no values', () => {
  const schema = {type: 'object', properties: {
    arrays: {type: 'array', items: {type: 'string'}},
    mode: {enum: ['fast', 'exact']},
    count: {type: 'integer'}}};
  const names = [{value: 'U', detail: 'cell array'}, {value: 'UMean', detail: 'cell array'}, {value: 'p', detail: 'cell array'}];
  const labels = (text, marker) => {
    const ast = parse(text.replace('|', ''));
    return completionsAt(schema, JSON.parse(text.replace('|', marker)), pointerAt(ast, text.indexOf('|')), ast.text, names)
      .filter((item) => item.kind === 'value').map((item) => item.label);
  };
  assert.deepEqual(labels('{"arrays": ["U|"]}', ''), ['U', 'UMean']);
  assert.deepEqual(labels('{"mode": "|"}', ''), ['exact', 'fast']);
  assert.deepEqual(labels('{"count": |1}', ''), []);
});
