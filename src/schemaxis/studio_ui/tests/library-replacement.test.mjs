// Copyright (C) 2026 David L. F. Gaden.
// Semantic replacement classification of library requests from the planner's own
// sequential, resolved actions: root values versus merge, append and array insertion.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {parse, documentValue} from '../editor/json-parse.mjs';
import {applyEdit, planInsert, planInserts} from '../editor/insert.mjs';
import {libraryRequest, scopeReplacements, scopeRequest} from '../editor/insert-fields.mjs';

const adaptor = new URL('../../adaptors/shotcut/', import.meta.url);
const library = JSON.parse(readFileSync(new URL('studio.json', adaptor), 'utf8'));
const snippet = library.snippets.find((item) => item.id === 'edit-timeline');
const template = {...library.templates.find((item) => item.id === 'trim-reorder')};
template.document = JSON.parse(readFileSync(new URL(template.file, adaptor), 'utf8'));

const populated = {version: 'schemaxis.shotcut/1', nodes: [{id: 'MyOrderedTimeline', filter: 'editTimeline', options: {
  assets: [{name: 'second', file: '/clips/second — Ünïcode.mkv'}, {name: 'first', file: '/clips/first.mkv'}],
  clips: [{asset: 'first', startFrame: 3, frameCount: 3}, {asset: 'second', startFrame: 0, frameCount: 2},
    {asset: 'first', startFrame: 3, frameCount: 3}], fps: 25, width: 32, height: 24, threads: 1}}]};

const marker = (item, id, name = id) => ({...item.fields[id], $fill: name});
const text = (value) => JSON.stringify(value, null, 2);

function plan(source, request, options = {}, format = 'json') {
  const edit = planInserts(parse(source, format), request.inserts, options);
  return {edit, candidate: applyEdit(source, edit)};
}

function expectedSnippet(names = {assets: 'assets', clips: 'clips'}) {
  const value = structuredClone(snippet.inserts[0].values[0]);
  value.nodes[0].options.assets = marker(snippet, 'assets', names.assets);
  value.nodes[0].options.clips = marker(snippet, 'clips', names.clips);
  return value;
}

test('actual Shotcut root snippet and template replace a named populated input and keep its outer whitespace', () => {
  const source = text(populated) + '\n';
  const request = libraryRequest(snippet, populated);
  assert.deepEqual(request.inserts.map((entry) => entry.at), ['']);
  const {edit, candidate} = plan(source, request);
  assert.deepEqual(edit.summaries, [{pointer: '', count: 1, action: 'insert', effect: 'replace'}]);
  assert.deepEqual(scopeReplacements(edit.summaries, ''), [0]);
  assert.equal(candidate, text(expectedSnippet()) + '\n');
  assert.deepEqual(edit.edits[0], {from: 0, to: source.length - 1, length: text(expectedSnippet()).length});
  assert.deepEqual(edit.pointers, ['/nodes/0/options/assets', '/nodes/0/options/clips']);
  assert.deepEqual(Object.keys(request.fields), ['assets', 'clips']);

  const filled = libraryRequest(template, populated);
  const result = plan(source, filled);
  const document = structuredClone(template.document);
  document.nodes[0].options.assets[0].file = marker(template, 'file');
  assert.equal(result.candidate, text(document) + '\n');
  assert.deepEqual(scopeReplacements(result.edit.summaries), [0]);
  assert.deepEqual(result.edit.pointers, ['/nodes/0/options/assets/0/file']);
});

test('JSON root replacement preserves leading and trailing whitespace; empty text keeps its whole-text plan', () => {
  const source = ' \n  {"a": 1}\n\n';
  const edit = planInsert(parse(source), '', [{b: 2}]);
  assert.equal(edit.effect, 'replace');
  assert.deepEqual([edit.from, edit.to], [source.indexOf('{'), source.indexOf('}') + 1]);
  assert.equal(applyEdit(source, edit), ' \n  {\n  "b": 2\n}\n\n');
  const empty = planInsert(parse(''), '', [{a: 1}]);
  assert.deepEqual([empty.from, empty.to, empty.text], [0, 0, '{\n  "a": 1\n}']);
});

test('singular insert, empty-object template and empty current input are semantic root replacements', () => {
  const source = text(populated);
  const singular = libraryRequest({insert: {at: '', values: [{version: 'other/2'}]}}, populated);
  assert.deepEqual(scopeReplacements(plan(source, singular).edit.summaries), [0]);
  const empty = plan(source, libraryRequest({document: {}}, populated));
  assert.equal(empty.candidate, '{}');
  assert.deepEqual(scopeReplacements(empty.edit.summaries), [0]);
  const onEmpty = plan('{}', libraryRequest(snippet, {}));
  assert.deepEqual(scopeReplacements(onEmpty.edit.summaries), [0]);
  assert.equal(onEmpty.candidate, text(expectedSnippet()));
});

test('root merge and ordinary appends never classify as replacement; root+append marks only the root', () => {
  const document = {version: 'v', settings: {a: 1, keep: true}};
  const merged = plan(text(document), {inserts: [{at: '', merge: {settings: {a: 2}, extra: true}}]});
  assert.deepEqual(merged.edit.summaries, [{pointer: '', count: 2, action: 'merge', effect: 'merge'}]);
  assert.deepEqual(merged.edit.conflicts, [{pointer: '/settings/a', previous: 1, value: 2}]);
  assert.deepEqual(scopeReplacements(merged.edit.summaries), []);
  assert.deepEqual(JSON.parse(merged.candidate), {version: 'v', settings: {a: 2, keep: true}, extra: true});

  const append = plan(text(populated), libraryRequest({inserts: [{at: '/nodes/-', values: [{id: 'extra'}]}]}, populated));
  assert.deepEqual(append.edit.summaries, [{pointer: '/nodes/-', count: 1, action: 'insert', effect: 'insert'}]);
  assert.deepEqual(scopeReplacements(append.edit.summaries), []);

  const composite = libraryRequest({inserts: [{at: '', values: [{version: 'v', nodes: [{id: 'a'}]}]},
    {at: '/nodes/-', values: [{id: 'b'}]}]}, populated);
  const both = plan(text(populated), composite);
  assert.deepEqual(both.edit.summaries.map(({pointer, effect}) => [pointer, effect]), [['', 'replace'], ['/nodes/-', 'insert']]);
  assert.deepEqual(scopeReplacements(both.edit.summaries), [0]);
  assert.deepEqual(JSON.parse(both.candidate), {version: 'v', nodes: [{id: 'a'}, {id: 'b'}]});
});

function design() {
  const second = structuredClone(populated);
  second.nodes[0].options.assets = {$fill: 'assets', label: 'Earlier'};
  second.nodes[0].options.clips = {$fill: 'clips', label: 'Earlier'};
  return {version: 'schemaxis.workflow-design/2', workflow: {version: 'schemaxis.workflow/1',
    definitions: {label: {value: 'Défini'}}, operations: [{id: 'first', document: structuredClone(populated)},
      {id: 'second', document: second}]}, ports: {}, connections: [], controllers: {}, parameters: {},
  outputs: {}, naming: {}, layout: {nodes: {}}};
}

test('scoped local root namespaces fields across the root, preserves siblings and leaves the request unchanged', () => {
  const root = design();
  const base = '/workflow/operations/0/document';
  const local = libraryRequest(snippet, root.workflow.operations[0].document);
  const scoped = scopeRequest(local, {base, root});
  assert.deepEqual(Object.keys(local.fields), ['assets', 'clips']);
  assert.deepEqual(local.inserts[0].at, '');
  assert.deepEqual(Object.keys(scoped.fields), ['assets_2', 'clips_2']);
  assert.deepEqual(scoped.inserts.map((entry) => entry.at), [base]);
  const {edit, candidate} = plan(text(root), scoped);
  assert.deepEqual(edit.summaries, [{pointer: base, count: 1, action: 'insert', effect: 'replace'}]);
  assert.deepEqual(scopeReplacements(edit.summaries, base), [0]);
  assert.deepEqual(scopeReplacements(edit.summaries, ''), []);
  const value = JSON.parse(candidate);
  const expected = design();
  expected.workflow.operations[0].document = expectedSnippet({assets: 'assets_2', clips: 'clips_2'});
  assert.deepEqual(value, expected);
  assert.deepEqual(edit.pointers, [`${base}/nodes/0/options/assets`, `${base}/nodes/0/options/clips`]);
  const workbench = scopeRequest(local, {base: ''});
  assert.deepEqual(workbench, local);
  assert.notEqual(workbench.inserts, local.inserts);
});

test('resolved @cursor replacement is classified at the root or local scope; merges and array insertion are not', () => {
  const scalar = plan('"draft"', {inserts: [{at: '@cursor', values: [{version: 'v'}]}]}, {caret: 0});
  assert.deepEqual(scalar.edit.summaries, [{pointer: '', count: 1, action: 'insert', effect: 'replace'}]);
  assert.deepEqual(scopeReplacements(scalar.edit.summaries), [0]);
  assert.equal(scalar.candidate, '{\n  "version": "v"\n}');

  const source = text(design());
  const caret = source.indexOf('"document": ') + '"document": '.length;
  const base = '/workflow/operations/0/document';
  const nested = plan(source, {inserts: [{at: '@cursor', values: [{version: 'v'}]}]}, {caret});
  assert.deepEqual(nested.edit.summaries, [{pointer: base, count: 1, action: 'insert', effect: 'replace'}]);
  assert.deepEqual(scopeReplacements(nested.edit.summaries, base), [0]);
  assert.deepEqual(scopeReplacements(nested.edit.summaries, ''), []);
  assert.deepEqual(scopeReplacements(nested.edit.summaries, base + '/nodes'), [0]);
  assert.deepEqual(JSON.parse(nested.candidate).workflow.operations[1], design().workflow.operations[1]);

  const merge = plan(source, {inserts: [{at: '@cursor', merge: {extra: 1}}]}, {caret});
  assert.deepEqual(merge.edit.summaries, [{pointer: base, count: 1, action: 'merge', effect: 'merge'}]);
  assert.deepEqual(scopeReplacements(merge.edit.summaries, base), []);

  assert.throws(() => plan(source, {inserts: [{at: '@cursor', values: [{}]}]}, {caret: 0}), /Place the caret/);

  const array = '{\n  "items": [\n    1,\n    2\n  ]\n}';
  const before = plan(array, {inserts: [{at: '@cursor', values: [{version: 'x'}]}]}, {caret: array.indexOf('[') + 1});
  assert.deepEqual(before.edit.summaries, [{pointer: '/items/0', count: 1, action: 'insert', effect: 'insert'}]);
  assert.deepEqual(scopeReplacements(before.edit.summaries, '/items/0'), []);
  assert.deepEqual(JSON.parse(before.candidate).items, [{version: 'x'}, 1, 2]);
  const literal = plan(array, scopeRequest({inserts: [{at: '', values: [{version: 'x'}]}]}, {base: '/items/0'}));
  assert.deepEqual(literal.edit.summaries[0].effect, 'insert');
  assert.deepEqual(scopeReplacements(literal.edit.summaries, '/items/0'), []);
  assert.deepEqual(JSON.parse(literal.candidate).items, [{version: 'x'}, 1, 2]);
});

test('YAML @cursor distinguishes array insertion from map and root replacement', () => {
  const items = 'items:\n  - 1\n  - 2\n';
  const inserted = plan(items, {inserts: [{at: '@cursor', values: [{version: 'x'}]}]}, {caret: items.indexOf('1')}, 'yaml');
  assert.deepEqual(inserted.edit.summaries, [{pointer: '/items/0', count: 1, action: 'insert', effect: 'insert'}]);
  assert.deepEqual(scopeReplacements(inserted.edit.summaries, '/items/0'), []);
  assert.deepEqual(documentValue(parse(inserted.candidate, 'yaml')).items, [{version: 'x'}, 1, 2]);

  const named = 'name: old # keep\nother: 2\n';
  const member = plan(named, {inserts: [{at: '@cursor', values: ['new']}]}, {caret: named.indexOf('old')}, 'yaml');
  assert.deepEqual(member.edit.summaries, [{pointer: '/name', count: 1, action: 'insert', effect: 'replace'}]);
  assert.deepEqual(scopeReplacements(member.edit.summaries, '/name'), [0]);
  assert.deepEqual(scopeReplacements(member.edit.summaries, ''), []);

  const root = plan(named, {inserts: [{at: '', values: [{name: 'Ünïcode', nodes: []}]}]}, {}, 'yaml');
  assert.deepEqual(root.edit.summaries[0].effect, 'replace');
  assert.deepEqual(scopeReplacements(root.edit.summaries), [0]);
  assert.deepEqual(documentValue(parse(root.candidate, 'yaml')), {name: 'Ünïcode', nodes: []});
  assert.match(root.candidate, /# keep/);
});

test('sequential planning resolves @cursor after earlier edits move the caret', () => {
  const source = text({a: {}, target: 1});
  const caret = source.indexOf('1');
  const request = {inserts: [{at: '/a', merge: {x: 1}}, {at: '@cursor', values: [{version: 'v'}]}]};
  const shifted = plan(source, request, {caret});
  assert.deepEqual(shifted.edit.summaries.map(({pointer, effect}) => [pointer, effect]), [['/a', 'merge'], ['/target', 'replace']]);
  assert.deepEqual(scopeReplacements(shifted.edit.summaries, '/target'), [1]);
  assert.deepEqual(JSON.parse(shifted.candidate), {a: {x: 1}, target: {version: 'v'}});
  const after = plan(source, {inserts: [{at: '/z', merge: {y: 1}}, {at: '@cursor', values: [{version: 'v'}]}]}, {caret});
  assert.deepEqual(after.edit.summaries.map(({pointer, effect}) => [pointer, effect]), [['/z', 'merge'], ['/target', 'replace']]);
  assert.deepEqual(JSON.parse(after.candidate), {a: {}, target: {version: 'v'}, z: {y: 1}});
});

test('source-wide YAML edits and widened JSON containers are not replacement prompts', () => {
  const yaml = '# heading\nversion: test\nnodes: [] # list note\n';
  const appended = plan(yaml, {inserts: [{at: '/nodes/-', values: [{id: 'n'}]}]}, {}, 'yaml');
  assert.deepEqual([appended.edit.edits[0].from, appended.edit.edits[0].to], [0, yaml.length]);
  assert.deepEqual(appended.edit.summaries, [{pointer: '/nodes/-', count: 1, action: 'insert', effect: 'insert'}]);
  assert.deepEqual(scopeReplacements(appended.edit.summaries), []);
  assert.match(appended.candidate, /# heading/);

  const widened = plan('{}', {inserts: [{at: '/sweeps/-', values: [{name: 'h'}]}]});
  assert.deepEqual(widened.edit.summaries, [{pointer: '/sweeps/-', count: 1, action: 'insert', effect: 'insert'}]);
  assert.deepEqual(scopeReplacements(widened.edit.summaries), []);
  assert.deepEqual(JSON.parse(widened.candidate), {sweeps: [{name: 'h'}]});

  const member = plan(text({version: 'v', count: 1}), {inserts: [{at: '/count', values: [2]}]});
  assert.deepEqual(member.edit.summaries[0].effect, 'replace');
  assert.deepEqual(scopeReplacements(member.edit.summaries), []);
});
