// Copyright (C) 2026 David L. F. Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {parse} from '../editor/json-parse.mjs';
import {pointerAt} from '../editor/json-pointer.mjs';
import {completionsAt} from '../editor/schema-complete.mjs';
import {entryName} from '../windows/workbench/authoring-defaults.mjs';
import {caseNames} from '../windows/workbench/case-data.mjs';
import {entriesOf, matchesOf} from '../windows/workbench/reader-selection.mjs';

test('a reader is named after its marker file, or its folder for a generic case marker', () => {
  const used = new Set(['foam1', 'coupe_AMI']);
  assert.equal(entryName('/data/run/42_b/coupe.foam', used), 'coupe');
  assert.equal(entryName('/data/run/42_b/case.foam', used), 'case_42_b');
  assert.equal(entryName('/data/run/wing/Case.foam', used), 'wing');
  assert.equal(entryName('/data/run/coupe_AMI.foam', used), 'coupe_AMI_2');
  assert.equal(entryName('/data/my case/a b.c.foam', used), 'a_b_c');
  assert.equal(entryName('', used), null);
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
