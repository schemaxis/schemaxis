// Copyright (C) 2026 David L. F. Gaden.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readSpatialInput, spatialInputText, expressionFaultRange} from '../editor/spatial-input.mjs';
import {parseField, checkField} from '../editor/fill-data.mjs';
import {parseParameter} from '../windows/runner/parameters.mjs';
import {libraryRequest} from '../editor/insert-fields.mjs';
const box = {min: [0, 0, 0], max: [2, 2, 0]};

test('D23 shared encoding preserves literals and opaque expressions across fill, library and runner', () => {
  for (const [text, value] of [['2', 2], ['[1,2,3]', [1,2,3]], [JSON.stringify(box), box],
    ['model.min', {$expr: 'model.min'}], ['vector(1, gap, 0)', {$expr: 'vector(1, gap, 0)'}]]) {
    assert.deepEqual(readSpatialInput(text), value);
    assert.deepEqual(readSpatialInput(spatialInputText(value)), value);
    for (const type of ['number', 'vector3', 'bounds', 'box']) {
      assert.deepEqual(parseField(text, {type}), value);
      if (value?.$expr) assert.equal(checkField(value, {type}), '');
    }
  }
  for (const kind of ['number', 'integer', 'vector', 'box']) {
    assert.deepEqual(parseParameter({kind}, 'model.span / 2'), {$expr: 'model.span / 2'});
  }
  assert.throws(() => readSpatialInput(' '), /Enter/);
  assert.throws(() => readSpatialInput('1e999'), /finite/);
  const item = {fields: {radius: {type: 'number'}}, inserts: [{at: '/nodes/-', values: [{options: {radius: {$fill: 'radius'}}}]}]};
  assert.deepEqual(libraryRequest(item, {}, {radius: 'gap / 2'}).inserts[0].values[0].options.radius, {$expr: 'gap / 2'});
});


test('numeric enums and array-generated fill markers retain literal constraints and admit expressions', async () => {
  const {fieldFromSchemas} = await import('../editor/fill-schema.mjs');
  const {requiredTemplate} = await import('../windows/workbench/operation-form.mjs');
  const vector = {type: 'array', minItems: 3, maxItems: 3, items: {type: 'number'}};
  assert.equal(fieldFromSchemas('origin', [vector]).type, 'vector3');
  assert.equal(requiredTemplate(vector, {}, 'origin').type, 'vector3');
  assert.equal(requiredTemplate({type:'number'}, {}, 'radius').type, 'number');
  const field = {type:'enum',values:[1,2]};
  assert.deepEqual(parseField('gap', field), {$expr:'gap'});
  assert.equal(checkField({$expr:'gap'}, field), '');
  assert.match(checkField(3, field), /listed/);
  assert.deepEqual(parseParameter({kind:'enum',constraints:{enum:[1,2]}},'gap'), {$expr:'gap'});
  for (const raw of ['null', 'true', '"2"', '[2]']) assert.throws(() => parseParameter({kind:'number'},raw), /finite/);
  assert.throws(() => readSpatialInput('[0, 1e999, 0]'), /finite/);
});

test('host expression faults select Unicode code-point ranges without interpreting text', () => {
  const text = '`😀` + missing';
  assert.deepEqual(expressionFaultRange(text, {observed: {expression: text, position: 6, length: 7}}), [7,14]);
  assert.equal(expressionFaultRange('changed', {observed: {expression: text, position: 6, length: 7}}), null);
});


test('A-S2-04 decimal entry syntax stays numeric across shared consumers', () => {
  for (const [raw, value] of [['.5', .5], ['5.', 5], ['-.5', -.5], ['+5.', 5], [' .5e2 ', 50]]) {
    assert.equal(readSpatialInput(raw), value);
    assert.equal(parseParameter({kind:'number'}, raw), value);
    assert.equal(parseField(raw, {type:'number'}), value);
  }
  for (const raw of ['1 + 2', 'r', '0x10']) assert.deepEqual(readSpatialInput(raw), {$expr:raw});
  assert.throws(() => readSpatialInput('.5e999'), /finite/);
  assert.throws(() => parseParameter({kind:'integer'}, '.5'), /whole/);
});

test('A-S2-06 ambiguous string expressions preserve their marker on every text round trip', () => {
  for (const text of ['2', 'true', 'null', '[1,2,3]', '.5', '1e999', 'r * 2']) {
    const expression = {$expr:text}, shown = spatialInputText(expression);
    assert.deepEqual(readSpatialInput(shown), expression);
    assert.deepEqual(parseParameter({kind:'number'}, shown), expression);
    assert.deepEqual(parseField(shown, {type:'number'}), expression);
    const item = {fields:{n:{type:'number'}}, inserts:[{at:'/nodes/-',values:[{n:{$fill:'n'}}]}]};
    assert.deepEqual(libraryRequest(item, {}, {n:shown}).inserts[0].values[0].n, expression);
  }
});

test('A-S2-07 fault selection maps escaped JSON expression strings without guessing duplicates', () => {
  const expression = '`😀` + missing', fault = {observed:{expression,position:6,length:7}};
  const text = JSON.stringify([0, {$expr:expression}, 2]);
  const [from,to] = expressionFaultRange(text,fault);
  assert.equal(text.slice(from,to),'missing');
  assert.equal(expressionFaultRange(JSON.stringify([expression,expression]),fault),null);
  assert.equal(expressionFaultRange('changed',fault),null);
  const escaped = '"a" + missing', json = JSON.stringify({$expr:escaped});
  const range = expressionFaultRange(json,{observed:{expression:escaped,position:6,length:7}});
  assert.equal(json.slice(...range),'missing');
});
