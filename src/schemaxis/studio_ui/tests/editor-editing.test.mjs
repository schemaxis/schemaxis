// Copyright (C) 2026 David L F Gaden
// Pure editing rules and pointer insertion of the Studio JSON editor.
import assert from 'node:assert/strict';
import test from 'node:test';

import {parse} from '../editor/json-parse.mjs';
import {planInsert, applyEdit} from '../editor/insert.mjs';
import {
  newlineEdit, typeCharEdit, backspaceEdit, indentEdit, outdentEdit, matchBracket,
} from '../editor/editing.mjs';
import {resolveDiagnostics, rangeForPointer, lineMarks} from '../editor/diagnostics.mjs';
import {computeLineStarts, lineOfOffset} from '../editor/highlight.mjs';

const insert = (text, pointer, values) => applyEdit(text, planInsert(parse(text), pointer, values));

test('insertAtPointer appends to arrays with matching indentation', () => {
  const text = '{\n  "nodes": [\n    {"id": "a"}\n  ]\n}';
  assert.equal(insert(text, '/nodes/-', [{id: 'b'}]),
    '{\n  "nodes": [\n    {"id": "a"},\n    {\n      "id": "b"\n    }\n  ]\n}');
  const several = insert(text, '/nodes/-', [1, 2]);
  assert.deepEqual(JSON.parse(several).nodes, [{id: 'a'}, 1, 2]);
  const before = insert(text, '/nodes/0', ['first']);
  assert.deepEqual(JSON.parse(before).nodes, ['first', {id: 'a'}]);
});

test('insertAtPointer fills empty containers and creates missing ones', () => {
  assert.equal(insert('{\n  "nodes": []\n}', '/nodes/-', [{id: 'a'}]),
    '{\n  "nodes": [\n    {\n      "id": "a"\n    }\n  ]\n}');
  assert.equal(insert('{}', '/nodes/-', [1]), '{\n  "nodes": [\n    1\n  ]\n}');
  assert.deepEqual(JSON.parse(insert('{"a": 1}', '/b/c', [true])), {a: 1, b: {c: true}});
  assert.equal(insert('', '', [{a: 1}]), '{\n  "a": 1\n}');
});

test('insertAtPointer sets object members', () => {
  const text = '{\n  "options": {\n    "size": 1\n  }\n}';
  assert.equal(insert(text, '/options/size', [[1, 2]]),
    '{\n  "options": {\n    "size": [\n      1,\n      2\n    ]\n  }\n}');
  assert.equal(insert(text, '/options/name', ['x']), '{\n  "options": {\n    "size": 1,\n    "name": "x"\n  }\n}');
  assert.equal(insert('{"a": 1}', '/b', [2]), '{"a": 1, "b": 2}');
  assert.throws(() => planInsert(parse('[1]'), '/x', [1]), /Cannot insert/);
  const edit = planInsert(parse(text), '/options/name', ['x']);
  assert.equal(edit.text.slice(edit.select.from, edit.select.to), '"name": "x"');
});

test('Enter keeps indentation and splits empty pairs', () => {
  const text = '{\n  "a": {}\n}';
  const inside = text.indexOf('{}') + 1;
  const edit = newlineEdit(text, inside, inside);
  assert.equal(applyEdit(text, edit), '{\n  "a": {\n    \n  }\n}');
  assert.equal(edit.selectFrom, inside + 5);
  const plain = newlineEdit(text, text.indexOf('{}') + 2, text.indexOf('{}') + 2);
  assert.equal(plain.text, '\n  ');
  const afterOpen = newlineEdit('[1', 1, 1);
  assert.equal(afterOpen.text, '\n  ');
});

test('typing auto-closes pairs and types over closers', () => {
  assert.deepEqual(typeCharEdit('', 0, 0, '{'), {from: 0, to: 0, text: '{}', selectFrom: 1, selectTo: 1});
  assert.equal(typeCharEdit('{}', 1, 1, '[').text, '[]');
  assert.equal(typeCharEdit('{}', 1, 1, '"').text, '""');
  assert.deepEqual(typeCharEdit('{}', 1, 1, '}'), {from: 1, to: 1, text: '', selectFrom: 2, selectTo: 2});
  assert.equal(typeCharEdit('{"ab"}', 4, 4, '"').selectFrom, 5, 'type over the closing quote');
  assert.equal(typeCharEdit('{"a"}', 1, 1, '"'), null, 'no pair before a word character');
  assert.equal(typeCharEdit('{"ab"}', 3, 3, '{'), null, 'no pair inside strings');
  assert.deepEqual(typeCharEdit('{"a"}', 4, 4, ':'), {from: 4, to: 4, text: ': ', selectFrom: 6, selectTo: 6});
  assert.equal(typeCharEdit('ab', 0, 2, '[').text, '[ab]', 'wrap selection');
  assert.equal(typeCharEdit('x', 1, 1, 'y'), null);
});

test('backspace removes empty pairs and Tab indents or outdents lines', () => {
  assert.deepEqual(backspaceEdit('{}', 1, 1), {from: 0, to: 2, text: '', selectFrom: 0, selectTo: 0});
  assert.equal(backspaceEdit('{a}', 2, 2), null);
  assert.equal(indentEdit('ab', 1, 1).text, ' ', 'pads to the next 2-column stop');
  const block = 'a\nb\nc';
  const indented = indentEdit(block, 0, 3);
  assert.equal(applyEdit(block, indented), '  a\n  b\nc');
  assert.deepEqual([indented.selectFrom, indented.selectTo], [2, 7]);
  const outdented = outdentEdit('    a\n  b', 0, 9);
  assert.equal(applyEdit('    a\n  b', outdented), '  a\nb');
  assert.equal(outdentEdit('a', 0, 1), null);
});

test('bracket matching skips brackets inside strings', () => {
  const text = '{"a": "}", "b": [1, {"c": "]"}]}';
  assert.deepEqual(matchBracket(text, 0), {open: 0, close: text.length - 1});
  const array = text.indexOf('[');
  assert.deepEqual(matchBracket(text, array), {open: array, close: text.length - 2});
  assert.deepEqual(matchBracket(text, text.length), {open: 0, close: text.length - 1});
  assert.equal(matchBracket('"{"', 1), null);
});

test('diagnostics map pointers to ranges and lines', () => {
  const text = '{\n  "nodes": [\n    {"id": "a", "bogus": 1}\n  ]\n}';
  const ast = parse(text);
  const range = rangeForPointer(ast, '/nodes/0/bogus', true);
  assert.equal(text.slice(range.from, range.to), '"bogus"');
  const container = rangeForPointer(ast, '/nodes/0');
  assert.equal(text.slice(container.from, container.to), '{');
  const missing = rangeForPointer(ast, '/nodes/0/options/size');
  assert.equal(text.slice(missing.from, missing.to), '{');
  const resolved = resolveDiagnostics(ast, [
    {pointer: '/nodes/0/bogus', message: 'Property "bogus" is not allowed', severity: 'warning'},
    {from: text.length, to: text.length, message: 'At end'},
  ], 'test');
  assert.equal(text.slice(resolved[0].from, resolved[0].to), '"bogus"');
  assert.equal(resolved[1].to - resolved[1].from, 1, 'empty ranges get one visible character');
  assert.equal(resolved[1].severity, 'error');
  const marks = lineMarks(resolved, computeLineStarts(text));
  assert.equal(marks.get(2).severity, 'warning');
  assert.equal(marks.get(4).severity, 'error');
  assert.equal(lineOfOffset(computeLineStarts('a\nb\nc'), 4), 2);
});

test('diagnostics follow edits until the next analysis', async () => {
  const {changedRange, shiftDiagnostics} = await import('../editor/diagnostics.mjs');
  const change = changedRange('{"a": 1, "b": x}', '{"a": 123, "b": x}');
  assert.deepEqual(change, {from: 7, oldTo: 7, newTo: 9});
  const moved = shiftDiagnostics([{from: 14, to: 15, message: 'x'}, {from: 6, to: 7, message: 'one'}], change);
  assert.deepEqual(moved.map((diagnostic) => [diagnostic.from, diagnostic.to]), [[16, 17], [6, 7]]);
  assert.equal(changedRange('same', 'same'), null);
  const removed = shiftDiagnostics([{from: 2, to: 4, message: 'gone'}], changedRange('abcdef', 'af'));
  assert.deepEqual(removed, []);
});

test('host diagnostics resolve JSON paths, node names and Unicode syntax offsets', () => {
  const text = '{"label":"😀", "nodes":[{"id":"body","options":{"width":2}}]}';
  const ast = parse(text);
  for (const location of ['$.nodes[0].options.width', 'body.width', '/nodes/0/options/width']) {
    const [diagnostic] = resolveDiagnostics(ast, [{location, message: 'Too small'}], 'external');
    assert.equal(diagnostic.pointer, '/nodes/0/options/width');
    assert.equal(text.slice(diagnostic.from, diagnostic.to), '2');
  }
  const offset = Array.from(text.slice(0, text.indexOf('2'))).length;
  const [syntax] = resolveDiagnostics(ast, [{offset, location: '$', message: 'Invalid syntax'}], 'external');
  assert.equal(text.slice(syntax.from, syntax.to), '2');
});
