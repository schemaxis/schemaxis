import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {parse} from '../editor/json-parse.mjs';
import {completions, validate} from '../editor/schema.mjs';
import {
  findFills, parseField, checkField, fieldChoices, documentPointers, uniqueFieldValue, substituteField,
} from '../editor/fill-data.mjs';
import {expressionKinds, missingProperties, checkSchemaValue, propertyFill} from '../editor/fill-schema.mjs';
import {fillDecorations} from '../editor/highlight.mjs';

const schema = (name) => JSON.parse(readFileSync(new URL(
  `../../../../docs/generated/${name}.authored.schema.json`, import.meta.url), 'utf8'));
const paraview = schema('paraview');
const freecad = schema('freecad');
const document = {version: 'schemaxis/1', nodes: [{id: 'source', filter: 'sphere'},
  {id: 'slice', filter: 'slice', inputs: {input: 'source'}, options: {origin: {$fill: 'origin'}}}], scenes: []};
const pointer = '/nodes/1/options/origin';

test('fill navigation is required-first and retains source ranges and metadata', () => {
  const text = '{"a":{"$fill":"later","required":false},"b":{"$fill":"first"},"c":{"$fill":"second"}}';
  const markers = findFills(parse(text), {first: {label: 'First field', type: 'integer'}});
  assert.deepEqual(markers.map((marker) => marker.field.$fill), ['first', 'second', 'later']);
  assert.equal(markers[0].field.label, 'First field');
  assert.deepEqual(JSON.parse(text.slice(markers[0].from, markers[0].to)), {$fill: 'first'});
  const decorations = fillDecorations(markers, new Set(['/b']), '/b');
  assert.match(decorations[0].className, /sx-fill-active.*sx-fill-required.*sx-fill-current/);
  assert.match(decorations[2].className, /sx-fill-quiet/);
});

test('markers are draft values without schema type cascades, including false schema', () => {
  assert.deepEqual(validate({type: 'object', properties: {value: false}}, {value: {$fill: 'later'}}), []);
  const problems = validate(paraview, document);
  assert.ok(!problems.some((problem) => problem.pointer.startsWith(pointer)));
});

test('field input validates declared primitive, vector, colour, bounds and path types', () => {
  assert.equal(parseField('source', {type: 'nodeRef'}), 'source');
  assert.equal(parseField('3', {type: 'integer'}), 3);
  assert.equal(checkField(2, {type: 'integer', minimum: 1, maximum: 5}), '');
  assert.match(checkField(1.5, {type: 'integer'}), /integer/);
  assert.match(checkField([1, 2], {type: 'vector3'}), /3 numbers/);
  assert.match(checkField([0, 2, 0], {type: 'colour'}), /between/);
  assert.match(checkField([2, 1, 0, 1, 0, 1], {type: 'bounds'}), /minimum/);
  assert.match(checkField('mesh.txt', {type: 'path', extensions: ['.vtu']}), /ending/);
});

test('placeholder text bounds count Unicode code points with inclusive limits', () => {
  const bounded = {type: 'string', minLength: 2, maxLength: 3};
  for (const accepted of ['ab', 'abc', '😀🚀', '😀🚀🛰', 'e\u0301', 'e\u0301x']) {
    assert.equal(checkField(accepted, bounded), '', JSON.stringify(accepted));
  }
  assert.equal(checkField('a', bounded), 'Use at least 2 characters.');
  assert.equal(checkField('😀', bounded), 'Use at least 2 characters.', 'one astral character is one code point');
  assert.equal(checkField('abcd', bounded), 'Use at most 3 characters.');
  assert.equal(checkField('😀🚀🛰🛸', bounded), 'Use at most 3 characters.', 'four astral characters exceed three');
  assert.equal(checkField('e\u0301x', bounded), '', 'a combining mark counts as its own code point');
  assert.equal(checkField('e\u0301xy', bounded), 'Use at most 3 characters.', 'four code points exceed three');
  // Empty text: rejected only where a minimum applies; id/path types still demand a value.
  assert.equal(checkField('', {type: 'string'}), '');
  assert.equal(checkField('', {type: 'string', maxLength: 0}), '');
  assert.equal(checkField('', {type: 'string', minLength: 0}), '');
  assert.equal(checkField('', {type: 'string', minLength: 1}), 'Use at least 1 characters.');
  assert.equal(checkField('😀', {type: 'string', maxLength: 0}), 'Use at most 0 characters.');
  assert.equal(checkField('', {type: 'path', minLength: 0}), 'Enter a value.');
  // Other checks keep their precedence and behaviour.
  assert.equal(checkField('😀😀', {type: 'string', maxLength: 2, pattern: '^x'}), 'This text does not match the required pattern.');
  assert.equal(checkField('😀', {type: 'string', values: ['x'], maxLength: 5}), 'Choose a listed value.');
  assert.equal(checkField(5, {type: 'string', maxLength: 1}), 'Enter text.');
  assert.equal(checkField('😀😀😀', {type: 'string', maxLength: 3}), '', 'regression: UTF-16 counting rejected this');
  assert.equal(checkField('😀😀', {type: 'string', minLength: 4}), 'Use at least 4 characters.', 'regression: UTF-16 counting accepted this');
  assert.equal(checkField('😀'.repeat(40), {type: 'string', maxLength: 40}), '');
  assert.equal(checkField('😀'.repeat(41), {type: 'string', maxLength: 40}), 'Use at most 40 characters.');
});

test('choices use enum, kinds, axes, observations and recent values', () => {
  const value = {nodes: [{id: 'mesh'}, {id: 'picture'}], axes: [{name: 'sweep'}]};
  assert.deepEqual(fieldChoices({type: 'nodeRef', acceptsKinds: ['geometry']}, value,
    {nodeKinds: {mesh: ['geometry'], picture: ['image']}}), ['mesh']);
  assert.deepEqual(fieldChoices({type: 'axisRef'}, value), ['sweep']);
  assert.deepEqual(fieldChoices({type: 'field'}, value, {observations: [{name: 'pressure'}]}), ['pressure']);
  assert.deepEqual(fieldChoices({type: 'enum', values: [1, 2]}, value, {recent: [2, 3]}), [1, 2, 3]);
  assert.ok(!documentPointers({a: {$fill: 'x'}, b: {c: 1}}).includes('/a'));
});

test('reference choices exclude unresolved markers and other non-string identities', () => {
  const marker = {$fill: 'prefix'};
  const value = {nodes: [{id: 'source'}, {id: marker}, {id: 7}, {id: ''}, null],
    axes: [{name: 'height'}, {name: marker}, {name: false}, {name: ''}, null]};
  assert.deepEqual(fieldChoices({type: 'nodeRef'}, value, {recent: [marker]}), ['source']);
  assert.deepEqual(fieldChoices({type: 'axisRef'}, value, {recent: [marker]}), ['height']);
  assert.deepEqual(fieldChoices({type: 'field'}, value, {
    observations: ['velocity', {name: 'pressure'}, {name: marker}, {name: 4}, {name: ''}, null],
    recent: [marker],
  }), ['velocity', 'pressure']);
});

test('only schema-supported expressions are offered at the current real-schema pointer', () => {
  assert.deepEqual(expressionKinds(paraview, document, '/version'), []);
  assert.deepEqual(expressionKinds(paraview, document, pointer),
    ['$document', '$value', '$axis', '$analytic', '$expr', '$observe', '$sample', '$calc', '$call']);
  const box = {version: 'schemaxis.freecad/1', nodes: [{id: 'box', filter: 'box', options: {length: {$fill: 'size'}}}]};
  const allowed = expressionKinds(freecad, box, '/nodes/0/options/length');
  assert.ok(allowed.includes('$value'));
  assert.ok(!allowed.includes('$observe'));
});

test('real schema validates literal and expression structures, typed arguments and analytic bounds', () => {
  assert.equal(checkSchemaValue(paraview, document, pointer, [0, 1, 2]), '');
  assert.ok(checkSchemaValue(paraview, document, pointer, 'wrong'));
  assert.equal(checkSchemaValue(paraview, document, pointer,
    {$value: 'boundsCentre', args: {bounds: [0, 1, 0, 1, 0, 1]}}), '');
  assert.ok(checkSchemaValue(paraview, document, pointer, {$value: 'boundsCentre', args: {bounds: [0, 1]}}));
  assert.equal(checkSchemaValue(paraview, document, pointer,
    {$analytic: {type: 'linear', start: 0, end: 1, count: 3}}), '');
  assert.ok(checkSchemaValue(paraview, document, pointer, {$analytic: {type: 'linear', start: 0, end: 1, count: 0}}));
  assert.ok(checkSchemaValue(paraview, document, pointer, {$analytic: {type: 'orbit', start: 0, end: 90,
    count: 3, elevation: 90}}));
  assert.equal(checkSchemaValue(paraview, document, pointer, {$sample: 'source', association: 'POINTS',
    field: 'pressure', index: 0}), '');
});

test('required properties and discriminator follow-up follow the actual variant', () => {
  const value = {version: 'schemaxis/1', nodes: [{id: 'slice', filter: 'slice'}]};
  const required = missingProperties(paraview, value, '/nodes/0');
  assert.deepEqual(required.map((item) => item.key), ['inputs']);
  const common = missingProperties(paraview, value, '/nodes/0', {common: ['options']});
  assert.deepEqual(common.map((item) => item.key), ['inputs', 'options']);
  assert.deepEqual(common.map((item) => item.required), [true, false]);
  assert.ok(common.every((item) => item.value.$fill));
});

test('key completion uses valid markers without defaults and keeps declared defaults', () => {
  const text = '{"version":"schemaxis/1","nodes":[{"id":"a", }]}';
  const items = completions(paraview, parse(text), text.indexOf(', }') + 2);
  const item = items.find((item) => item.label === 'filter');
  assert.equal(JSON.parse(`{${item.insertText}}`).filter.$fill, 'filter');
  assert.equal(propertyFill('size', [{type: 'number', default: 10}], true), 10);
});

test('id prefix substitution and uniquification use each containing collection', () => {
  const value = {nodes: [{id: 'sliceX'}, {id: {$fill: 'p', template: '${prefix}X', templateField: 'prefix'}}],
    scenes: [{id: 'sceneX'}, {id: {$fill: 'p', template: '${prefix}X', templateField: 'prefix'}}]};
  const markers = findFills(parse(JSON.stringify(value)));
  assert.equal(uniqueFieldValue(value, markers, 'slice'), 'slice_2');
  assert.equal(uniqueFieldValue(value, markers, 'scene'), 'scene_2');
  assert.equal(substituteField(markers[0].field, 'slice_2'), 'slice_2X');
});


test('Workbench guidance uses declared kinds and scientific arrays from native observations', async () => {
  const {nodeKinds, observationFields} = await import('../windows/workbench/guidance.mjs');
  assert.deepEqual(nodeKinds({operationKinds: {box: ['solid']}}, {nodes: [
    {id: 'body', filter: 'box'}, {id: {$fill: 'next'}, filter: 'box'}]}), {body: ['solid']});
  const draft = {nodes: {$fill: 'nodes'}, axes: {$fill: 'axes'}};
  assert.deepEqual(nodeKinds({}, draft), {});
  assert.deepEqual(fieldChoices({type: 'nodeRef'}, draft), []);
  assert.deepEqual(fieldChoices({type: 'axisRef'}, draft), []);
  const observed = {objects: [{fields: {POINTS: {pressure: {}, velocity: {}}, CELLS: {pressure: {}}}}],
    metadata: {name: 'ignore'}, mesh: {pointData: {temperature: {components: 1}}}};
  assert.deepEqual(observationFields(observed), ['pressure', 'temperature', 'velocity']);
});
