import assert from 'node:assert/strict';
import test from 'node:test';
import {validate} from '../editor/schema-validate.mjs';
import {contextFor, matches} from '../editor/schema-core.mjs';

test('string bounds count Unicode code points and retain inclusive limits', () => {
  const schema = {type: 'string', minLength: 1, maxLength: 2};
  const context = contextFor(schema);
  for (const value of ['a', 'ab', '😀', '😀🚀', 'e\u0301', '\u0000']) {
    assert.deepEqual(validate(schema, value), [], JSON.stringify(value));
    assert.equal(matches(context, schema, value), true, JSON.stringify(value));
  }
  for (const [value, message] of [
    ['', 'Expected at least 1 character'],
    ['abc', 'Expected at most 2 characters'],
    ['😀🚀x', 'Expected at most 2 characters'],
    ['e\u0301x', 'Expected at most 2 characters'],
  ]) {
    assert.deepEqual(validate(schema, value), [{pointer: '', message, severity: 'warning'}]);
    assert.equal(matches(context, schema, value), false);
  }
  assert.deepEqual(validate({maxLength: 0}, ''), []);
  assert.equal(validate({maxLength: 0}, 'a')[0].message, 'Expected at most 0 characters');
  assert.deepEqual(validate({minLength: 3, maxLength: 4}, 12), []);
});

test('string bounds work through references, alternatives and conditional branches', () => {
  const schema = {$defs: {name: {type: 'string', maxLength: 2}}, type: 'object', properties: {
    name: {anyOf: [{$ref: '#/$defs/name'}, {type: 'null'}]},
  }};
  assert.deepEqual(validate(schema, {name: '😀🚀'}), []);
  assert.deepEqual(validate(schema, {name: null}), []);
  assert.deepEqual(validate(schema, {name: 'abc'}).map(({pointer, message}) => ({pointer, message})),
    [{pointer: '/name', message: 'Expected at most 2 characters'}]);
  const conditional = {type: 'object', properties: {name: {type: 'string'}},
    if: {required: ['name'], properties: {name: {maxLength: 2}}},
    then: {required: ['short']}, else: {required: ['long']}};
  assert.deepEqual(validate(conditional, {name: '😀🚀', short: true}), []);
  assert.deepEqual(validate(conditional, {name: 'abc', long: true}), []);
  assert.match(validate(conditional, {name: 'abc', short: true})[0].message, /"long"/);
});

test('string feedback preserves unresolved markers and intentionally skipped documents', () => {
  const schema = {type: 'object', properties: {name: {type: 'string', maxLength: 2}}};
  assert.deepEqual(validate(schema, {name: {$fill: 'name', type: 'string'}}), []);
  assert.deepEqual(validate(schema, {name: {$document: '/name'}}), []);
  assert.deepEqual(validate(schema, {name: 'abc'}, {skip: new Set(['/name'])}), []);
  assert.deepEqual(validate({anyOf: [{type: 'string', maxLength: 2}, {type: 'string', minLength: 4}]}, 'abc'), [],
    'ambiguous alternatives remain conservative');
});

test('string bound messages use the singular only for a limit of exactly one', () => {
  const message = (schema, value) => validate(schema, value)[0].message;
  assert.equal(message({type: 'string', maxLength: 1}, 'ab'), 'Expected at most 1 character');
  assert.equal(message({type: 'string', maxLength: 1}, '😀🚀'), 'Expected at most 1 character');
  assert.equal(message({type: 'string', maxLength: 0}, 'a'), 'Expected at most 0 characters');
  assert.equal(message({type: 'string', maxLength: 2}, 'abc'), 'Expected at most 2 characters');
  assert.equal(message({type: 'string', minLength: 1}, ''), 'Expected at least 1 character');
  assert.equal(message({type: 'string', minLength: 2}, 'a'), 'Expected at least 2 characters');
});
