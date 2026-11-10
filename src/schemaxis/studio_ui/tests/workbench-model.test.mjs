// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {diagnosticPointer, fieldsAt, fillPlaceholders, operationPointer, outline, parseField, placeholders,
  snippetRequest, validationRequest, valueAt} from '../windows/workbench/model.mjs';

const schema = JSON.parse(await readFile(new URL('../../../../docs/generated/freecad.authored.schema.json',
  import.meta.url), 'utf8'));
const documentValue = {version: 'schemaxis.freecad/1', units: 'mm',
  nodes: [{id: 'body', filter: 'box', options: {length: 30, width: 20, height: 10}}], output: 'body'};

test('nested validation names its saved parent revision and standalone validation has no context', () => {
  const state = {provider: 'freecad', record: {id: 'workflow-id', revision: 7}};
  assert.deepEqual(validationRequest(state, {operation: 'assembly'}, '{}'), {
    provider: 'freecad', source: '{}', format: 'json', document: 'workflow-id', revision: 7, operation: 'assembly'});
  assert.deepEqual(validationRequest(state, {}, 'version: x', 'yaml'), {
    provider: 'freecad', source: 'version: x', format: 'yaml'});
});

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


test('task-specific negative guards hide absent controls and retain invalid authored values for repair', () => {
  const taskSchema = {type:'object', properties:{operation:{enum:['read','write']}, source:{type:'string'}, destination:{type:'string'}},
    oneOf:[{properties:{operation:{const:'read'}}, not:{title:'Task fields',anyOf:[{required:['destination'],'x-studio-guide':{status:'reference'}}]}},
      {properties:{operation:{const:'write'}}, not:{anyOf:[{required:['source']}]}}]};
  assert.deepEqual(fieldsAt(taskSchema, {operation:'read'}, '').map(field => field.name), ['operation','source']);
  assert.deepEqual(fieldsAt(taskSchema, {operation:'write'}, '').map(field => field.name), ['operation','destination']);
  assert.ok(fieldsAt(taskSchema, {operation:'read',destination:'wrong'}, '').some(field => field.name === 'destination'));
  assert.equal(fieldsAt(taskSchema, {}, '').length, 3);
  const jointlyForbidden = {type:'object',properties:{a:{},b:{}},not:{required:['a','b']}};
  assert.equal(fieldsAt(jointlyForbidden, {}, '').length, 2);
});


test('ambiguous task unions retain controls allowed by an unrestricted alternative', () => {
  const guarded = {properties:{operation:{const:'read'}},not:{required:['destination']}};
  for (const free of [{properties:{operation:{const:'write'}}}, {}, {properties:{operation:{const:'read'}}}]) {
    const root={type:'object',properties:{operation:{type:'string'},destination:{type:'string'}},anyOf:[guarded,free]};
    for (const doc of [{},{operation:{$document:'/definitions/task'}}]) {
      assert.ok(fieldsAt(root,doc,'').some(field => field.name==='destination'));
    }
    if (!free.properties || free.properties.operation.const==='read') {
      assert.ok(fieldsAt(root,{operation:'read'},'').some(field => field.name==='destination'));
    }
  }
});


test('nested task guards require a resolved outer alternative', () => {
  const root={type:'object',properties:{operation:{enum:['read','write']},format:{enum:['text','binary']},destination:{type:'string'}},anyOf:[
    {properties:{operation:{const:'read'}},anyOf:[
      {properties:{format:{const:'text'}},not:{required:['destination']}},
      {properties:{format:{const:'binary'}}}]},
    {properties:{operation:{const:'write'}}}]};
  for (const document of [{format:'text'},{operation:{$document:'/definitions/task'},format:'text'},{operation:'write',format:'text'}]) {
    assert.ok(fieldsAt(root,document,'').some(field=>field.name==='destination'));
  }
  assert.equal(fieldsAt(root,{operation:'read',format:'text'},'').some(field=>field.name==='destination'),false);
});
