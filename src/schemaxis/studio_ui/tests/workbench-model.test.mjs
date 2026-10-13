import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {diagnosticPointer, fieldsAt, fillPlaceholders, operationPointer, outline, parseField, placeholders,
  snippetRequest, valueAt} from '../windows/workbench/model.mjs';

const schema = JSON.parse(await readFile(new URL('../../../../docs/generated/freecad.authored.schema.json',
  import.meta.url), 'utf8'));
const documentValue = {version: 'schemaxis.freecad/1', units: 'mm',
  nodes: [{id: 'body', filter: 'box', options: {length: 30, width: 20, height: 10}}], output: 'body'};

test('properties follow the real adaptor filter schema, including absent options', () => {
  const fields = fieldsAt(schema, documentValue, '/nodes/0/options');
  assert.equal(fields.find((field) => field.name === 'length').type, 'number');
  assert.equal(fields.find((field) => field.name === 'length').value, 30);
  assert.ok(fields.some((field) => field.name === 'origin'));
  assert.equal(fields.some((field) => field.name === 'radius'), false);
  assert.deepEqual(outline(documentValue).map((item) => item.label), ['Document', 'body', 'output']);
});

test('property values preserve numeric, boolean, array and marker types', () => {
  assert.equal(parseField('30', {name: 'length', type: 'number'}), 30);
  assert.throws(() => parseField('', {name: 'length', type: 'number'}), /requires a number/);
  assert.throws(() => parseField('1.2', {name: 'count', type: 'integer'}), /integer/);
  assert.equal(parseField('false', {type: 'boolean'}), false);
  assert.deepEqual(parseField('[1,2,3]', {type: 'array'}), [1, 2, 3]);
  assert.deepEqual(parseField('{"$document":"/settings/x"}', {type: 'object'}), {$document: '/settings/x'});
});

test('snippet forms substitute strings recursively without parsing values as code', () => {
  const values = [{id: '${name:box}', options: {file: '${path:a b.json}'}}];
  assert.deepEqual(placeholders(values), [{name: 'name', value: 'box'}, {name: 'path', value: 'a b.json'}]);
  assert.deepEqual(fillPlaceholders(values, {name: 'newBox'}), [{id: 'newBox', options: {file: 'a b.json'}}]);
  const snippet = {insert: {at: '/nodes/-', values}};
  assert.throws(() => snippetRequest(snippet, documentValue, {name: 'body'}), /already exists/);
  assert.equal(snippetRequest(snippet, documentValue, {name: 'fresh'}).values[0].id, 'fresh');
});

test('nested operation addresses stay attached to operation identity after reordering', () => {
  const record = {document: {workflow: {operations: [{id: 'other'}, {id: 'cad', document: documentValue}]}}};
  const pointer = operationPointer(record, 'cad');
  assert.equal(pointer, '/workflow/operations/1/document');
  assert.deepEqual(valueAt(record.document, pointer), documentValue);
  assert.throws(() => operationPointer(record, 'gone'), /no longer/);
  assert.equal(valueAt({'a/b': {'~key': 7}}, '/a~1b/~0key'), 7);
});


test('server fault locations map back to exact node options', () => {
  assert.equal(diagnosticPointer('$.nodes[0].options.length', documentValue), '/nodes/0/options/length');
  assert.equal(diagnosticPointer('body.length', documentValue), '/nodes/0/options/length');
  assert.equal(diagnosticPointer('/nodes/0/id', documentValue), '/nodes/0/id');
  assert.equal(diagnosticPointer('unknown', documentValue), '');
});

test('a merged value branch does not replace the field title or explanation', () => {
  const guide = (address, explanation) => ({status: explanation ? 'reviewed' : 'pending', address,
    ...(explanation ? {explanation} : {})});
  const wrapped = {type: 'object', $defs: {runtime: {type: 'object', title: 'Runtime value',
    description: 'Computed during the visit.', 'x-studio-guide': guide('/$defs/runtime', 'Computed during the visit.')}},
  properties: {scale: {description: 'Glyph scale factor.', 'x-studio-guide': {...guide('/properties/scale', 'Glyph scale factor.'),
    binding: {operation: 'Glyph', property: 'ScaleFactor', key: 'scale'}},
  anyOf: [{type: 'number', description: 'Glyph scale factor.', 'x-studio-guide': guide('/properties/scale/anyOf/0', 'Glyph scale factor.')},
    {$ref: '#/$defs/runtime', title: 'Runtime value', description: 'Computed during the visit.',
      'x-studio-guide': guide('/properties/scale/anyOf/1', 'Computed during the visit.')}]}}};
  const field = fieldsAt(wrapped, {}, '').find(item => item.name === 'scale');
  assert.equal(field.schema.title, undefined);
  assert.equal(field.schema.description, 'Glyph scale factor.');
  assert.equal(field.schema['x-studio-guide'].address, '/properties/scale');
});
