import assert from 'node:assert/strict';
import {test} from 'node:test';
import {parse, documentValue} from '../editor/json-parse.mjs';
import {pointerAt, rangeOfPointer} from '../editor/json-pointer.mjs';
import {planInsert, planInserts} from '../editor/insert.mjs';
import {yamlRender} from '../editor/yaml-parse.mjs';
import {completionsFor, validateDocument} from '../editor/schema-registry.mjs';

const schema = {type: 'object', properties: {version: {const: 'test'}, count: {type: 'integer'},
  enabled: {type: 'boolean'}, label: {type: 'string'}, nodes: {type: 'array'}}, required: ['version', 'count']};

test('YAML AST shares values, ranges, diagnostics and schema services', () => {
  const text = '# heading\nversion: test\ncount: 3\nenabled: true\nlabel: |\n  hello\n  world\n';
  const ast = parse(text, 'yaml');
  assert.deepEqual(ast.diagnostics, []);
  assert.deepEqual(documentValue(ast), {version: 'test', count: 3, enabled: true, label: 'hello\nworld\n'});
  assert.equal(text.slice(rangeOfPointer(ast, '/count').from, rangeOfPointer(ast, '/count').to), '3');
  assert.equal(pointerAt(ast, text.indexOf('3')).pointer, '/count');
  assert.deepEqual(validateDocument(null, documentValue(ast), schema), []);
});

test('profile rejects ambiguous keys, tags, aliases and multiple documents', () => {
  for (const text of ['a: 1\na: 2', 'a: .nan', 'a: !!str 2', 'a: &x [1]\nb: *x',
    '<<: {a: 1}', '1: value', 'a: 1\n---\nb: 2', '%YAML 1.1\n---\na: yes', '%TAG !e! tag:example.com,2026:\n---\na: 1']) {
    assert.ok(parse(text, 'yaml').diagnostics.length, text);
  }
  assert.deepEqual(documentValue(parse('date: 2026-10-09\ntext: yes\nnumber: 012', 'yaml')),
    {date: '2026-10-09', text: 'yes', number: 12});
});

test('schema completion uses YAML properties and flow-compatible values', () => {
  const ast = parse('version: test\ncount: 3\n', 'yaml');
  const items = completionsFor(null, ast, ast.text.length, schema);
  assert.ok(items.some(item => item.label === 'enabled' && item.insertText.startsWith('enabled: ')));
  const values = completionsFor(null, parse('enabled: false\n', 'yaml'), 10, schema);
  assert.ok(values.some(item => item.insertText === 'false'));
});

test('structured edits and grouped snippets preserve comments', () => {
  const ast = parse('# heading\nversion: test\ncount: 3 # count note\nnodes: []\n', 'yaml');
  const edit = planInsert(ast, '/count', [5]);
  assert.equal(planInsert(ast, '/nodes/-', [{id: 'preview'}]).text, planInsert(ast, '/nodes/-', [{id: 'preview'}]).text);
  assert.equal(documentValue(ast).count, 3);
  assert.match(edit.text, /# heading/);
  assert.match(edit.text, /count: 5 # count note/);
  const revised = parse(edit.text, 'yaml');
  const group = planInserts(revised, [{at: '/nodes/-', values: [{id: 'first'}]}, {at: '/nodes/-', values: [{id: 'second'}]}]);
  const final = revised.text.slice(0, group.from) + group.text + revised.text.slice(group.to);
  assert.deepEqual(documentValue(parse(final, 'yaml')).nodes, [{id: 'first'}, {id: 'second'}]);
  assert.match(final, /# heading/);
  assert.throws(() => planInserts(parse('nodes: [', 'yaml'), [{at: '/nodes/-', values: [{}]}]));
});

test('canvas-style reconciliation retains notes when objects move', () => {
  const ast = parse('nodes:\n- id: first # first note\n  x: 1\n- id: second # second note\n  x: 2\n', 'yaml');
  const value = structuredClone(documentValue(ast));
  value.nodes.reverse();
  const source = yamlRender(ast, value);
  assert.deepEqual(documentValue(parse(source, 'yaml')), value);
  assert.match(source, /second # second note/);
  assert.match(source, /first # first note/);
});
