// Copyright (C) 2026 David L F Gaden
import test from 'node:test';
import assert from 'node:assert/strict';
import {formatJson} from '../editor/json-format.mjs';
import {comprehensionEntries} from '../windows/workbench/comprehension.mjs';
const value = {args: [{$observe: 'speed', path: ['bounds', 1]}, {$observe: 'speed', path: ['bounds', 0]}]};
test('compact layout respects width, retains short paths and preserves JSON values', () => {
  for (const width of [40, 70, 100, 240]) {
    const source = formatJson(value, {compact: true, width});
    assert.deepEqual(JSON.parse(source), value);
    assert.ok(source.includes('["bounds", 1]'));
    assert.ok(source.split('\n').every(line => line.length <= width));
  }
  assert.equal(formatJson(value), JSON.stringify(value, null, 2));
  assert.equal(formatJson(value, {compact: true, width: 240}).split('\n').length, 1);
});
test('escaped keys, empty containers and long indivisible strings survive formatting', () => {
  const data = {'quote"': ['line\nnext', {}, [], null, 'x'.repeat(200)], bool: false};
  assert.deepEqual(JSON.parse(formatJson(data, {compact: true, width: 40})), data);
});
test('comprehension describes named dependencies and nested workflow nodes with navigable pointers', () => {
  const entries = comprehensionEntries({workflow: {operations: [{document: {nodes: [
    {id: 'speed', filter: 'calculator', inputs: {input: 'flow'}, options: {expression: 'mag(U)'}},
    {id: 'case', filter: 'foam', options: {file: {$document: '/settings/case'}}},
  ]}}]}});
  assert.equal(entries[0].pointer, '/workflow/operations/0/document/nodes/0');
  assert.match(entries[0].label, /0 · calculator → speed/);
  assert.match(entries[0].detail, /input: flow.*expression: mag\(U\)/);
  assert.match(entries[1].detail, /document \/settings\/case/);
  assert.deepEqual(comprehensionEntries(null), []);
});
