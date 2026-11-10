// Copyright (C) 2026 David L F Gaden
// Schema completion, hover and validation against the real generated Schemaxis schemas.
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import test from 'node:test';

import {parse} from '../editor/json-parse.mjs';
import {
  completions, hover, validate, schemasAt, SchemaRegistry, completionsFor, hoverFor, validateDocument,
  resolveSchemaContext,
} from '../editor/schema.mjs';

const GENERATED = new URL('../../../../docs/generated/', import.meta.url);
const EXAMPLES = new URL('../../../../examples/schemaxis/', import.meta.url);
const cache = new Map();
const schema = (name) => {
  if (!cache.has(name)) {
    cache.set(name, JSON.parse(readFileSync(new URL(`${name}.authored.schema.json`, GENERATED), 'utf8')));
  }
  return cache.get(name);
};

/** Complete at the '|' marker. */
function complete(root, marked) {
  const offset = marked.indexOf('|');
  const text = marked.slice(0, offset) + marked.slice(offset + 1);
  return completions(root, parse(text), offset);
}

const labels = (items) => items.map((item) => item.label);

test('ParaView node with filter "slice" offers exactly the slice options', () => {
  const items = complete(schema('paraview'),
    '{"version": "schemaxis/1", "nodes": [{"id": "a", "filter": "slice", "options": {|}}]}');
  assert.deepEqual(labels(items), ['origin', 'normal', 'crinkle', 'triangulate']);
  const normal = items.find((item) => item.label === 'normal');
  assert.equal(normal.kind, 'property');
  assert.match(normal.documentation, /axis token/);
  assert.equal(normal.insertText, '"normal": [1,0,0]');
  assert.equal(items.find((item) => item.label === 'crinkle').insertText, '"crinkle": false');
});

test('FreeCAD box offers length, width and height and excludes existing keys', () => {
  const root = schema('freecad');
  const all = complete(root,
    '{"version": "schemaxis.freecad/1", "nodes": [{"id": "b", "filter": "box", "options": {|}}]}');
  assert.deepEqual(labels(all).slice(0, 3), ['length', 'width', 'height']);
  assert.equal(all[0].insertText, '"length": 10');
  assert.deepEqual(all[0].cursor, {from: 10, to: 12}, 'default value is selected');
  const rest = complete(root,
    '{"version": "schemaxis.freecad/1", "nodes": [{"id": "b", "filter": "box", "options": {"length": 2, |}}]}');
  assert.ok(!labels(rest).includes('length'));
  assert.ok(labels(rest).includes('width'));
});

test('key completion puts required properties first and adds a comma before a following member', () => {
  const items = complete(schema('paraview'), '{"version": "schemaxis/1", "nodes": [{|"id": "a"}]}');
  assert.equal(items[0].label, 'filter');
  assert.equal(items[0].required, true);
  assert.equal(items[0].insertText, '"filter": {"$fill":"filter","label":"filter","type":"enum","required":true},');
  assert.ok(!labels(items).includes('id'));
  const typed = complete(schema('paraview'), '{"version": "schemaxis/1", "nodes": [{"id": "a", "inp|"}]}');
  assert.deepEqual(labels(typed), ['inputs']);
  assert.equal(typed[0].insertText, '"inputs": {"$fill":"inputs","label":"inputs","type":"json","required":true}');
});

test('value completion for filter lists the discriminator constants with descriptions', () => {
  const items = complete(schema('paraview'), '{"version": "schemaxis/1", "nodes": [{"id": "a", "filter": |}]}');
  assert.ok(items.length > 500, `${items.length} filters`);
  const slice = items.find((item) => item.label === 'slice');
  assert.equal(slice.insertText, '"slice"');
  const tight = complete(schema('paraview'), '{"version": "schemaxis/1", "nodes": [{"id": "a", "filter":|}]}');
  assert.equal(tight.find((item) => item.label === 'slice').insertText, ' "slice"');
  assert.equal(slice.detail, 'filter');
  assert.match(slice.documentation, /options: origin, normal, crinkle, triangulate/);
  const typed = complete(schema('paraview'), '{"version": "schemaxis/1", "nodes": [{"id": "a", "filter": "sli|"}]}');
  assert.equal(typed[0].label, 'slice');
  assert.equal(typed[0].insertText, '"slice"');
  assert.ok(typed.every((item) => item.label.toLowerCase().includes('sli')));
  const freecad = complete(schema('freecad'), '{"version": "schemaxis.freecad/1", "nodes": [{"filter": "|"}]}');
  assert.ok(labels(freecad).includes('box'));
});

test('value completion offers booleans, defaults and version constants', () => {
  const booleans = complete(schema('paraview'),
    '{"version": "schemaxis/1", "nodes": [{"id": "a", "filter": "slice", "options": {"triangulate": |}}]}');
  assert.deepEqual(labels(booleans.filter((item) => item.kind === 'value')), ['true', 'false']);
  assert.ok(booleans.some((item) => item.label === '$document'));
  assert.equal(booleans[0].detail, 'default');
  const version = complete(schema('gmsh'), '{"version": |}');
  assert.deepEqual(labels(version), ['schemaxis.gmsh/1']);
});

test('composition markers are accepted and offered only when asked for', () => {
  const root = schema('paraview');
  const plain = complete(root,
    '{"version": "schemaxis/1", "nodes": [{"id": "a", "filter": "slice", "options": {"origin": {|}}}]}');
  assert.ok(!labels(plain).some((label) => label.startsWith('$')));
  const markers = complete(root,
    '{"version": "schemaxis/1", "nodes": [{"id": "a", "filter": "slice", "options": {"origin": {"$|"}}}]}');
  for (const marker of ['$document', '$expr', '$value', '$axis']) {
    assert.ok(labels(markers).includes(marker), marker);
  }
  const document = {version: 'schemaxis.freecad/1', output: 'b', nodes: [{id: 'b', filter: 'box', options: {
    length: {$document: '/settings/length', scope: 'workflow'}, width: {$expr: {op: 'add', args: [1, 2]}},
    height: {$analytic: {type: 'values', values: [1, 2]}}, origin: [0, {$axis: 'x'}, 0]}}]};
  assert.deepEqual(validate(schema('freecad'), document), []);
});

test('schemasAt evaluates if/then discriminators against the instance', () => {
  const root = schema('paraview');
  const value = {version: 'schemaxis/1', nodes: [{id: 'a', filter: 'clip'}]};
  const nodes = schemasAt(root, value, '/nodes/0/options');
  const names = new Set(nodes.flatMap((node) => Object.keys(node.properties || {})));
  assert.ok(names.has('invert'));
  assert.ok(!names.has('triangulate'));
  const editing = schemasAt(root, value, '/nodes/0/filter', {editing: true});
  assert.ok(editing.filter((node) => 'const' in node).length > 500);
});

test('hover returns title, description, type, default and constraints', () => {
  const root = schema('paraview');
  const text = '{"version": "schemaxis/1", "nodes": [{"id": "a", "filter": "slice", "options": {"normal": "x+"}}]}';
  const info = hover(root, parse(text), text.indexOf('normal') + 2);
  assert.equal(info.key, 'normal');
  assert.match(info.description, /azimuth and elevation/);
  assert.deepEqual(info.default, [1, 0, 0]);
  const box = '{"version": "schemaxis.freecad/1", "nodes": [{"id": "b", "filter": "box", "options": {"length": 5}}]}';
  const length = hover(schema('freecad'), parse(box), box.indexOf('length'));
  assert.equal(length.type, 'number');
  assert.deepEqual(length.constraints, {exclusiveMinimum: 0, maximum: 100000});
  assert.equal(length.default, 10);
});

test('validation reports clear problems with pointers', () => {
  const root = schema('paraview');
  const problems = validate(root, {version: 'schemaxis/1', scenes: [{}], nodes: [
    {id: 's', filter: 'wavelet'},
    {id: 'a', filter: 'slice', inputs: {input: 's'}, options: {bogus: 1, crinkle: 'yes', origin: [0, 0]}},
    {id: 'b', filter: 'slise', inputs: {input: 's'}},
  ]}).map((problem) => `${problem.pointer} ${problem.message}`);
  assert.ok(problems.includes('/nodes/1/options/bogus Property "bogus" is not allowed'), problems.join('\n'));
  assert.ok(problems.includes('/nodes/1/options/crinkle Expected boolean, found string'));
  assert.ok(problems.includes('/nodes/1/options/origin Expected at least 3 items'));
  assert.ok(problems.includes('/nodes/2/filter Unknown filter "slise"'));
  const freecad = validate(schema('freecad'), {version: 'schemaxis.freecad/1', output: 'b',
    nodes: [{id: 'b', filter: 'box', options: {length: -1}}]});
  assert.deepEqual(freecad.map((problem) => problem.message), ['Must be greater than 0']);
});

test('validation has no false positives on the shipped examples', () => {
  // Read the adaptor-owned schema expectations; invalid planner cases can still
  // be schema-valid, while explicit schemaValid:false fixtures must be rejected.
  const packages = new URL('../../adaptors/', import.meta.url);
  const schemaInvalid = new Set();
  for (const provider of readdirSync(packages)) {
    let bundle;
    try { bundle = JSON.parse(readFileSync(new URL(`${provider}/readiness.json`, packages), 'utf8')); }
    catch { continue; }
    for (const route of Object.values(bundle.routes)) {
      for (const fixture of route.examples || []) {
        if (fixture.schemaValid === false && fixture.reference?.startsWith('examples/schemaxis/')) {
          schemaInvalid.add(fixture.reference.slice('examples/schemaxis/'.length));
        }
      }
    }
  }
  const byVersion = {'schemaxis/1': 'paraview', 'schemaxis.workflow/1': 'workflow'};
  for (const file of readdirSync(GENERATED)) {
    if (file.endsWith('.authored.schema.json')) {
      const name = file.replace('.authored.schema.json', '');
      const version = schema(name).properties?.version?.const;
      if (version && !byVersion[version]) {
        byVersion[version] = name;
      }
    }
  }
  let checked = 0;
  for (const file of readdirSync(EXAMPLES).filter((name) => name.endsWith('.json'))) {
    let document;
    try {
      document = JSON.parse(readFileSync(new URL(file, EXAMPLES), 'utf8'));
    } catch {
      continue;
    }
    const name = byVersion[document.version];
    if (name) {
      const faults = validate(schema(name), document);
      if (schemaInvalid.has(file)) assert.ok(faults.length, `${file} must fail its declared schema contract`);
      else assert.deepEqual(faults, [], file);
      checked += 1;
    }
  }
  assert.ok(checked >= 50, `${checked} examples checked`);
});

function registry() {
  const files = {'schemaxis.workflow/1': 'workflow', 'schemaxis.gmsh/1': 'gmsh', 'schemaxis.freecad/1': 'freecad',
    'schemaxis/1': 'paraview'};
  const result = new SchemaRegistry(async (version) => (files[version] ? schema(files[version]) : null),
    {versions: Object.keys(files)});
  return result;
}

test('workflow operation documents complete against their own adaptor schema', async () => {
  const schemas = registry();
  await Promise.all(['schemaxis.workflow/1', 'schemaxis.gmsh/1'].map((version) => schemas.schemaFor(version)));
  const marked = '{"version": "schemaxis.workflow/1", "operations": [{"id": "mesh", "document": '
    + '{"version": "schemaxis.gmsh/1", "nodes": [{"id": "m", "filter": |}]}}]}';
  const offset = marked.indexOf('|');
  const text = marked.replace('|', '');
  const ast = parse(text);
  const items = completionsFor(schemas, ast, offset, null);
  const filters = labels(items);
  assert.ok(filters.includes('tetrahedral'), filters.join(', '));
  assert.ok(!filters.includes('slice'), 'ParaView filters are not offered in a gmsh document');
  const context = resolveSchemaContext(schemas, JSON.parse(text.replace('"filter": }', '"filter": "box"}')),
    '/operations/0/document/nodes/0', null);
  assert.equal(context.base, '/operations/0/document');
  assert.equal(context.schema, schema('gmsh'));
  const workflow = '{"version": "schemaxis.workflow/1", "operations": [{}]}';
  const keys = completionsFor(schemas, parse(workflow), workflow.indexOf('[{}') + 2, null);
  assert.deepEqual(labels(keys).slice(0, 2), ['id', 'document']);
  const info = hoverFor(schemas, ast, text.indexOf('"nodes"') + 2, null);
  assert.equal(info.pointer, '/operations/0/document/nodes');
  assert.equal(info.schemaVersion, 'schemaxis.gmsh/1');
});

test('envelopes can refine an inline document without losing nested adaptor schemas', () => {
  const schemas = new SchemaRegistry(() => null);
  schemas.register('design', {type: 'object', 'x-schemaxis-inlineDocuments': ['/workflow'], properties: {
    workflow: {type: 'object', properties: {operations: {type: 'array', items: {type: 'object'}}}},
  }});
  schemas.register('workflow', {type: 'object', properties: {operations: {type: 'array', minItems: 1}}});
  schemas.register('adaptor', {type: 'object', properties: {size: {type: 'number'}}});
  const document = {version: 'design', workflow: {version: 'workflow', operations: []}};
  assert.deepEqual(validateDocument(schemas, document), []);
  document.workflow.operations.push({document: {version: 'adaptor', size: 'bad'}});
  assert.equal(validateDocument(schemas, document)[0].pointer, '/workflow/operations/0/document/size');
});

test('validateDocument checks embedded documents with their own schema', async () => {
  const schemas = registry();
  const document = JSON.parse(readFileSync(new URL('freecad-gmsh-paraview.json', EXAMPLES), 'utf8'));
  for (const version of ['schemaxis.workflow/1', 'schemaxis.gmsh/1', 'schemaxis.freecad/1', 'schemaxis/1']) {
    await schemas.schemaFor(version);
  }
  assert.deepEqual(validateDocument(schemas, document, null), []);
  document.operations[1].document.nodes[1].options.size = 'big';
  document.operations[0].document.nodes[0].options.depth = 3;
  const problems = validateDocument(schemas, document, null).map((problem) => `${problem.pointer} ${problem.message}`);
  assert.deepEqual(problems.sort(), [
    '/operations/0/document/nodes/0/options/depth Property "depth" is not allowed',
    '/operations/1/document/nodes/1/options/size Expected number, found string',
  ]);
});

test('registry loads each version once and ignores unknown versions', async () => {
  let calls = 0;
  const schemas = new SchemaRegistry(async (version) => {
    calls += 1;
    return version === 'a/1' ? {type: 'object'} : null;
  }, {versions: ['a/1', 'b/1']});
  await Promise.all([schemas.schemaFor('a/1'), schemas.schemaFor('a/1')]);
  assert.equal(calls, 1);
  assert.equal(await schemas.schemaFor('c/1'), null);
  assert.equal(await schemas.schemaFor('b/1'), null);
  assert.equal(calls, 2);
  assert.deepEqual(schemas.peek('a/1'), {type: 'object'});
});

test('completion on the 4 MB ParaView schema stays under 50 ms once warm', () => {
  const root = schema('paraview');
  const cases = [
    '{"version": "schemaxis/1", "nodes": [{"id": "a", "filter": "slice", "options": {|}}]}',
    '{"version": "schemaxis/1", "nodes": [{"id": "a", "filter": |}]}',
    '{"version": "schemaxis/1", "nodes": [{"id": "a", "filter": "pvSlice", "options": {"|"}}]}',
    '{"version": "schemaxis/1", "nodes": [{"id": "a", |}]}',
    '{|}',
  ];
  for (const marked of cases) {
    complete(root, marked);
  }
  for (const marked of cases) {
    const start = performance.now();
    const items = complete(root, marked);
    const elapsed = performance.now() - start;
    assert.ok(items.length > 0, marked);
    assert.ok(elapsed < 50, `${elapsed.toFixed(1)} ms for ${marked}`);
  }
});


test('task field completion honours singleton prohibitions without hiding conditionally allowed fields', () => {
  const task = {type:'object',properties:{operation:{enum:['read','write']},source:{type:'string'},destination:{type:'string'}},
    oneOf:[{properties:{operation:{const:'read'}},not:{anyOf:[{required:['destination']}]}},
      {properties:{operation:{const:'write'}},not:{anyOf:[{required:['source']}]}}]};
  assert.deepEqual(labels(complete(task, '{"operation":"read",|}')), ['source']);
  assert.deepEqual(labels(complete(task, '{"operation":"write",|}')), ['destination']);
  assert.deepEqual(new Set(labels(complete(task, '{|}'))), new Set(['operation','source','destination']));
});


test('completion preserves controls allowed by ambiguous or unrestricted task alternatives', () => {
  for (const free of [{properties:{operation:{const:'write'}}}, {}, {properties:{operation:{const:'read'}}}]) {
    const root={type:'object',properties:{operation:{type:'string'},destination:{type:'string'}},anyOf:[
      {properties:{operation:{const:'read'}},not:{required:['destination']}},free]};
    assert.ok(labels(complete(root,'{|}')).includes('destination'));
    assert.ok(labels(complete(root,'{"operation":{"$document":"/definitions/task"},|}')).includes('destination'));
  }
});


test('nested task guards require a resolved outer alternative', () => {
  const root={type:'object',properties:{operation:{enum:['read','write']},format:{enum:['text','binary']},destination:{type:'string'}},anyOf:[
    {properties:{operation:{const:'read'}},anyOf:[
      {properties:{format:{const:'text'}},not:{required:['destination']}},
      {properties:{format:{const:'binary'}}}]},
    {properties:{operation:{const:'write'}}}]};
  for (const text of ['{"format":"text",|}','{"operation":{"$document":"/definitions/task"},"format":"text",|}','{"operation":"write","format":"text",|}']) {
    assert.ok(labels(complete(root,text)).includes('destination'));
  }
  assert.equal(labels(complete(root,'{"operation":"read","format":"text",|}')).includes('destination'),false);
});


test('conditional array contains selects only matching item intent', () => {
  const condition = {anyOf: [
    {required: ['tool'], properties: {tool: {required: ['holder']}}},
    {required: ['tools'], properties: {tools: {contains: {anyOf: [
      {required: ['kind'], properties: {kind: {const: 'pointed'}}}, {required: ['holder']},
    ]}}}},
    {required: ['operations'], properties: {operations: {contains: {required: ['depthReference']}}}},
  ]};
  const root = {if: condition, then: {required: ['setup']}};
  for (const value of [{}, {tools: []}, {tool: {kind: 'flat'}},
    {tools: [{kind: 'flat'}, {kind: 'flat'}]}, {operations: [{operation: 'drill'}]}]) {
    assert.deepEqual(validate(root, value), [], JSON.stringify(value));
  }
  for (const value of [{tool: {holder: {}}}, {tools: [{kind: 'flat'}, {kind: 'pointed'}]},
    {tools: [{holder: {}}]}, {operations: [{depthReference: 'tip'}]}]) {
    assert.deepEqual(validate(root, value).map(v => v.message), ['Missing required property "setup"']);
    assert.deepEqual(validate(root, {...value, setup: {}}), []);
  }
});

test('conditional contains respects count bounds and rebased local references', () => {
  const root = {$defs: {tag: {const: 'selected'}},
    if: {contains: {$ref: '#/$defs/tag'}, minContains: 2, maxContains: 3}, then: {minItems: 9}};
  for (const value of [[], ['other'], ['selected'], Array(4).fill('selected')]) {
    assert.deepEqual(validate(root, value), []);
  }
  for (const value of [['selected', 'selected'], ['other', 'selected', 'selected', 'selected']]) {
    assert.deepEqual(validate(root, value).map(v => v.message), ['Expected at least 9 items']);
  }
  root.if = {contains: false, minContains: 0, maxContains: 0};
  assert.deepEqual(validate(root, ['other']).map(v => v.message), ['Expected at least 9 items']);
  root.if = {contains: true, minContains: 1, maxContains: 1};
  assert.deepEqual(validate(root, ['other']).map(v => v.message), ['Expected at least 9 items']);
  assert.deepEqual(validate(root, ['one', 'two']), []);
});
