// Lexer, tolerant parser and pointer helpers of the Studio JSON editor.
import assert from 'node:assert/strict';
import test from 'node:test';

import {lex, lexLine} from '../editor/json-lexer.mjs';
import {parse, toValue, documentValue, pointerAt, rangeOfPointer, valueAt, parsePointer, formatPointer}
  from '../editor/json-parse.mjs';

const messages = (text) => parse(text).diagnostics.map((diagnostic) => diagnostic.message);
const caret = (marked) => {
  const offset = marked.indexOf('|');
  const text = marked.slice(0, offset) + marked.slice(offset + 1);
  const context = pointerAt(parse(text), offset);
  delete context.node;
  return context;
};

test('lexer produces offsets for every token class', () => {
  const tokens = lex('{"a\\n\\u0041": [1.5e3, -0, true, null], "b": false}', {whitespace: false});
  assert.deepEqual(tokens.map((token) => token.type), ['lbrace', 'string', 'colon', 'lbracket', 'number', 'comma',
    'number', 'comma', 'literal', 'comma', 'literal', 'rbracket', 'comma', 'string', 'colon', 'literal', 'rbrace']);
  assert.equal(tokens[1].value, 'a\nA');
  assert.deepEqual([tokens[1].from, tokens[1].to], [1, 12]);
  assert.equal(tokens[4].value, 1500);
  assert.equal(tokens[15].value, false);
});

test('lexer is robust on partial and malformed input', () => {
  const [unterminated] = lex('"abc');
  assert.equal(unterminated.closed, false);
  assert.equal(unterminated.error, 'Unterminated string');
  const [badEscape] = lex('"a\\qb"');
  assert.match(badEscape.error, /Invalid escape/);
  assert.equal(lex('01', {whitespace: false})[0].error, 'Invalid number');
  assert.equal(lex('tru', {whitespace: false})[0].type, 'error');
  const line = lex('"a"\n"b"');
  assert.equal(line[0].to, 3, 'strings stop at newlines');
  const keyed = lexLine('  "key": "value",');
  assert.equal(keyed.find((token) => token.type === 'string').key, true);
  assert.equal(keyed.filter((token) => token.type === 'string')[1].key, undefined);
});

test('parser produces a full AST with offsets for valid JSON', () => {
  const text = '{"a": [1, {"b": "c"}], "d": null}';
  const ast = parse(text);
  assert.deepEqual(ast.diagnostics, []);
  assert.deepEqual(toValue(ast.root), JSON.parse(text));
  const member = ast.root.members[0];
  assert.deepEqual([member.key.from, member.key.to, member.value.from, member.value.to], [1, 4, 6, 21]);
  assert.equal(documentValue(ast), documentValue(ast), 'memoised per AST');
});

test('parser recovers from missing commas, trailing commas and stray tokens', () => {
  assert.deepEqual(toValue(parse('{"a": 1 "b": 2}').root), {a: 1, b: 2});
  assert.deepEqual(messages('{"a": 1 "b": 2}'), ["Expected ','"]);
  assert.deepEqual(toValue(parse('[1, 2,]').root), [1, 2]);
  assert.deepEqual(messages('[1, 2,]'), ['Trailing comma']);
  assert.deepEqual(messages('{"a": 1,}'), ['Trailing comma']);
  assert.deepEqual(toValue(parse('[1,,2]').root), [1, 2]);
  assert.deepEqual(messages('{a: 1}'), ['Property names must be double-quoted strings']);
  assert.deepEqual(toValue(parse('{a: 1}').root), {a: 1});
  assert.deepEqual(messages('{"a" 1}'), ["Expected ':' after property name"]);
  assert.deepEqual(messages('{"a": }'), ['Expected a value']);
  assert.deepEqual(messages('{} []'), ['Unexpected content after the JSON value']);
  assert.deepEqual(messages('{"a": [1}'), ["Expected ']' but found '}'"]);
});

test('parser keeps partial structure of incomplete documents', () => {
  const ast = parse('{"nodes": [{"id": "a", "filter": "sl');
  assert.deepEqual(toValue(ast.root), {nodes: [{id: 'a', filter: 'sl'}]});
  assert.deepEqual(ast.diagnostics.map((diagnostic) => diagnostic.message), ['Unterminated string',
    "Unterminated object: expected '}'", "Unterminated array: expected ']'", "Unterminated object: expected '}'"]);
  assert.equal(parse('').root, null);
  assert.deepEqual(parse('   ').diagnostics, []);
  for (let cut = 0; cut <= 60; cut += 1) {
    const text = '{"a": [1, 2.5, "x\\"y"], "b": {"c": true, "d": null}, "e": -3e2}'.slice(0, cut);
    assert.doesNotThrow(() => parse(text), `prefix ${cut}`);
  }
});

test('pointer helpers escape segments and map pointers to ranges and values', () => {
  assert.deepEqual(parsePointer('/a~1b/~0c/0'), ['a/b', '~c', '0']);
  assert.equal(formatPointer(['a/b', '~c', 0]), '/a~1b/~0c/0');
  const text = '{"a/b": {"list": [10, {"x": true}]}}';
  const ast = parse(text);
  const range = rangeOfPointer(ast, '/a~1b/list/1/x');
  assert.equal(text.slice(range.from, range.to), 'true');
  assert.equal(text.slice(range.keyFrom, range.keyTo), '"x"');
  assert.deepEqual(valueAt(ast, '/a~1b/list'), [10, {x: true}]);
  assert.equal(valueAt(ast, '/missing'), undefined);
  assert.equal(rangeOfPointer(ast, '/a~1b/list/7'), null);
});

test('pointerAt reports key positions with prefix and existing keys', () => {
  const context = caret('{"version": "x", "nod|"}');
  assert.equal(context.position, 'key');
  assert.equal(context.keyPrefix, 'nod');
  assert.equal(context.parentPointer, '');
  assert.equal(context.pointer, '/nod');
  assert.deepEqual(context.existingKeys, ['version']);
  const slot = caret('{"a": 1, |}');
  assert.equal(slot.position, 'key');
  assert.equal(slot.pointer, null);
  assert.deepEqual(slot.existingKeys, ['a']);
  assert.equal(caret('{|}').position, 'key');
});

test('pointerAt reports value positions inside objects and arrays', () => {
  const value = caret('{"nodes": [{"filter": "sl|"}]}');
  assert.equal(value.position, 'value');
  assert.equal(value.pointer, '/nodes/0/filter');
  assert.equal(value.parentPointer, '/nodes/0');
  assert.equal(value.valuePrefix, '"sl');
  const empty = caret('{"a": |}');
  assert.equal(empty.position, 'value');
  assert.equal(empty.pointer, '/a');
  assert.deepEqual(empty.range, {from: 6, to: 6});
  const item = caret('{"a": [1, |]}');
  assert.equal(item.position, 'value');
  assert.equal(item.pointer, '/a/1');
  assert.equal(item.insertIndex, 1);
  const literal = caret('{"a": tr|}');
  assert.equal(literal.position, 'value');
  assert.equal(literal.valuePrefix, 'tr');
  assert.equal(caret('|').position, 'value');
});

test('pointerAt reports between positions after complete values', () => {
  assert.equal(caret('{"a": 1|}').position, 'value');
  assert.equal(caret('{"a": 1 |}').position, 'between');
  assert.equal(caret('{"a": "x"|}').position, 'between');
  assert.equal(caret('[1 |]').position, 'between');
  assert.equal(caret('{}|').position, 'between');
});
