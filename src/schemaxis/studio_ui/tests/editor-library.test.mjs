import assert from 'node:assert/strict';
import test from 'node:test';
import {parse} from '../editor/json-parse.mjs';
import {applyEdit, planInserts} from '../editor/insert.mjs';
import {libraryRequest, markers, namespaceRequest, uniquifyInserts} from '../editor/insert-fields.mjs';

function insert(value, inserts, options) {
  const text = JSON.stringify(value, null, 2);
  const edit = planInserts(parse(text), inserts, options);
  return {value: JSON.parse(applyEdit(text, edit)), edit};
}

test('multi-insert creates containers and preserves deep merge conflict details', () => {
  const before = {nodes: [{id: 'source'}], scenes: [{visible: {source: {opacity: 1, colour: 'red'}}}]};
  const {value, edit} = insert(before, [
    {at: '/nodes/-', values: [{id: 'cut'}]},
    {at: '/axes/-', values: [{name: 'height', values: [1, 2]}]},
    {at: '/scenes/0/visible', merge: {source: {opacity: 0.5}, cut: {}}},
  ]);
  assert.equal(value.nodes.length, 2);
  assert.equal(value.axes.length, 1);
  assert.deepEqual(value.scenes[0].visible.source, {opacity: 0.5, colour: 'red'});
  assert.deepEqual(edit.conflicts, [{pointer: '/scenes/0/visible/source/opacity', previous: 1, value: 0.5}]);
  assert.equal(edit.summaries.length, 3);
  assert.equal(edit.ghosts.length, 3);
  assert.equal(before.nodes.length, 1);
});

test('caret-compatible append follows current item and cursor values replace atomically', () => {
  const document = {nodes: [{id: 'first'}, {id: 'last'}], value: 3};
  const text = JSON.stringify(document, null, 2);
  const appended = insert(document, [{at: '/nodes/-', values: [{id: 'middle'}]}], {caret: text.indexOf('first')});
  assert.deepEqual(appended.value.nodes.map((node) => node.id), ['first', 'middle', 'last']);
  const replaced = insert(document, [{at: '@cursor', values: [{$fill: 'value'}]}], {caret: text.indexOf('3')});
  assert.deepEqual(replaced.value.value, {$fill: 'value'});
  assert.deepEqual(replaced.edit.pointers, ['/value']);
  assert.throws(() => insert(document, [{at: '@cursor', values: [1]}], {caret: 1}), /caret/);
});

test('missing array containers preserve declared numeric indices', () => {
  const inserts = [{at: '/scenes/2/visible', merge: {source: {}}}];
  for (const document of [{}, {scenes: []}, {scenes: [{id: 'first'}]}]) {
    const {value} = insert(document, inserts);
    assert.equal(value.scenes.length, 3);
    assert.deepEqual(value.scenes[0], document.scenes?.[0] || {});
    assert.deepEqual(value.scenes[1], {});
    assert.deepEqual(value.scenes[2], {visible: {source: {}}});
  }
  assert.deepEqual(insert({}, [{at: '/matrix/2/0', values: [7]}]).value, {matrix: [[], [], [7]]});
  assert.deepEqual(insert({}, [{at: '/nodes/2', values: [{id: 'new'}]}]).value, {nodes: [{id: 'new'}]});
});

test('identities are assigned while other fields preserve typed, namespaced markers', () => {
  const item = {fields: {prefix: {type: 'id', label: 'Prefix', default: 'cut'},
    count: {type: 'integer', label: 'Count'}},
    inserts: [{at: '/nodes/-', values: [{id: '${prefix}X', count: {$fill: 'count'}}, {id: '${prefix}Y'}]}]};
  const document = {nodes: [{id: {$fill: 'prefix'}}]};
  const request = libraryRequest(item, document);
  assert.equal(request.inserts[0].values[0].id, 'cutX');
  assert.equal(request.inserts[0].values[1].id, 'cutY');
  const filled = libraryRequest(item, document, {prefix: 'cut', count: 5});
  assert.deepEqual(filled.inserts[0].values[0], {id: 'cutX', count: 5});
  const first = insert(document, request.inserts).value;
  assert.equal(markers(first).length, 2);
  const repeated = libraryRequest(item, first);
  assert.equal(repeated.inserts[0].values[0].id, 'cutX2');
  assert.equal(repeated.inserts[0].values[0].count.$fill, 'count_2');
});

test('ID uniqueness is collection-specific and rewrites references without rewriting labels', () => {
  const document = {nodes: [{id: 'cut'}], scenes: [{id: 'scene'}], metadata: {id: 'arbitrary'}};
  const result = uniquifyInserts(document, [
    {at: '/nodes/-', values: [{id: 'cut', label: 'cut'}, {id: 'child', inputs: {input: 'cut'}}]},
    {at: '/scenes/0/visible', merge: {cut: {}}},
    {at: '/scenes/-', values: [{id: 'cut'}]},
    {at: '/metadata/list/-', values: [{id: 'arbitrary'}]},
  ]);
  assert.equal(result[0].values[0].id, 'cut2');
  assert.equal(result[0].values[0].label, 'cut');
  assert.equal(result[0].values[1].inputs.input, 'cut2');
  assert.deepEqual(result[1].merge, {cut2: {}});
  assert.equal(result[2].values[0].id, 'cut');
  assert.equal(result[3].values[0].id, 'arbitrary');
});

test('nested requests namespace fields across the root while node IDs stay collection-scoped', () => {
  const root = {operations: [{document: {nodes: [{id: 'cut', count: {$fill: 'count'}, idField: {$fill: 'prefix'}}]}},
    {document: {nodes: []}}]};
  const item = {fields: {count: {type: 'integer', label: 'Count'}, prefix: {type: 'id', label: 'Prefix'}},
    inserts: [{at: '/nodes/-', values: [{id: 'cut', count: {$fill: 'count'}},
      {id: '${prefix}X', count: {$fill: 'count'}}]}]};
  const initial = libraryRequest(item, root.operations[1].document);
  const request = namespaceRequest(initial, root);
  assert.deepEqual(Object.keys(initial.fields), ['count', 'prefix']);
  assert.deepEqual(Object.keys(request.fields), ['count_2', 'prefix_2']);
  assert.equal(request.inserts[0].values[0].id, 'cut');
  assert.equal(request.inserts[0].values[1].id, 'prefix1X');
  const inserts = request.inserts.map((entry) => ({...entry, at: '/operations/1/document' + entry.at}));
  const {value, edit} = insert(root, inserts);
  assert.deepEqual(edit.pointers, ['/operations/1/document/nodes/0/count',
    '/operations/1/document/nodes/1/count']);
  assert.deepEqual(value.operations[0], root.operations[0]);
  assert.equal(value.operations[1].document.nodes[0].count.$fill, 'count_2');
});

test('multi-insert rejects malformed JSON and merge over scalar without partial application', () => {
  assert.throws(() => planInserts(parse('{bad'), [{at: '/nodes/-', values: [1]}]));
  assert.throws(() => insert({value: 3}, [{at: '/nodes/-', values: [1]}, {at: '/value', merge: {x: 1}}]), /non-object/);
});

test('multi-preview maps unchanged text between all inserts and commits one replacement', async () => {
  const {Preview} = await import('../editor/editor-preview.mjs');
  const {computeLineStarts, lineOfOffset} = await import('../editor/highlight.mjs');
  const text = JSON.stringify({nodes: [], unchanged: 'middle', axes: []}, null, 2);
  const calls = [];
  const core = {textarea: {value: text, selectionStart: 0, style: {}, setSelectionRange() {}},
    state: {options: {}, lineStarts: computeLineStarts(text)}, ensureAst: () => parse(text),
    view: {root: {classList: {add() {}, remove() {}}}, beginPreview() {}, endPreview() {}, scrollIntoView() {}},
    requestRender() {}, afterProgrammaticSelection() {}, replaceText: (...args) => calls.push(args)};
  const preview = new Preview(core);
  preview.show({inserts: [{at: '/nodes/-', values: [{id: 'source'}]},
    {at: '/axes/-', values: [{name: 'height', values: [1]}]}]});
  const model = preview.model(text, core.state.lineStarts);
  const original = text.indexOf('middle');
  const mapped = model.map(original);
  assert.equal(model.text.slice(mapped, mapped + 6), 'middle');
  assert.equal(model.label(lineOfOffset(model.lineStarts, mapped)),
    String(lineOfOffset(core.state.lineStarts, original) + 1));
  assert.equal(model.firstLine, lineOfOffset(model.lineStarts, model.ghosts[0].from));
  assert.equal(model.ghosts.length, 2);
  assert.ok(model.ghosts.every((ghost) => mapped < ghost.from || mapped >= ghost.to));
  assert.equal(preview.commit(), true);
  assert.equal(calls.length, 1);
  assert.deepEqual(JSON.parse(applyEdit(text, {from: calls[0][0], to: calls[0][1], text: calls[0][2]})),
    {nodes: [{id: 'source'}], unchanged: 'middle', axes: [{name: 'height', values: [1]}]});
});

test('ID rewrites stay within the correct nested document', () => {
  const document = {operations: [{document: {nodes: [{id: 'x'}]}}, {document: {nodes: [{id: 'x'}]}}]};
  const inserts = [{at: '/operations/0/document/nodes/-', values: [{id: 'x'}, {id: 'a', inputs: {input: 'x'}}]},
    {at: '/operations/1/document/nodes/-', values: [{id: 'a', inputs: {input: 'x'}}]}];
  const result = uniquifyInserts(document, inserts);
  assert.equal(result[0].values[1].inputs.input, 'x2');
  assert.equal(result[1].values[0].inputs.input, 'x');
});

test('long preview scrolls its bounded viewport and restores authored scroll and selection', async () => {
  const {EditorView} = await import('../editor/view.mjs');
  const {computeLineStarts} = await import('../editor/highlight.mjs');
  const listeners = new Map();
  const view = Object.create(EditorView.prototype);
  const authored = '{"unchanged": true}';
  view.textarea = {value: authored, style: {}, scrollTop: 80, scrollLeft: 24,
    clientHeight: 390, clientWidth: 600, selectionStart: 3, selectionEnd: 8, selectionDirection: 'backward',
    setSelectionRange(start, end, direction) {
      Object.assign(this, {selectionStart: start, selectionEnd: end, selectionDirection: direction});
    }};
  view.previewScroller = {hidden: true, scrollTop: 0, scrollLeft: 0, clientHeight: 390, clientWidth: 600,
    addEventListener: (type, listener) => listeners.set(type, listener),
    removeEventListener: (type, listener) => { assert.equal(listeners.get(type), listener); listeners.delete(type); }};
  view.previewSpacer = {style: {}};
  view.gutter = {addEventListener() {}, removeEventListener() {}};
  view.main = {offsetLeft: 40};
  view.metrics = {lineHeight: 20, charWidth: 8, padTop: 8, padLeft: 12};
  const text = Array.from({length: 900}, (_, index) => `line ${index}`).join('\n');
  const model = {text, lineStarts: computeLineStarts(text)};
  let renders = 0;
  view.beginPreview(model, () => { renders += 1; });
  view.scrollIntoView(800, 0, true);
  assert.equal(view.scrollSurface, view.previewScroller);
  assert.equal(view.previewScroller.clientHeight, 390);
  assert.equal(view.previewSpacer.style.height, '18016px');
  assert.ok(view.previewScroller.scrollTop > 15000);
  const position = view.coordsAt(model.lineStarts, model.lineStarts[800]);
  assert.ok(position.y >= 0 && position.y + position.lineHeight <= 390);
  assert.equal(view.textarea.scrollTop, 80);
  assert.equal(view.textarea.value, authored);
  assert.deepEqual(view.textarea.style, {});
  listeners.get('scroll')();
  assert.equal(renders, 1);
  view.endPreview();
  assert.equal(view.scrollSurface, view.textarea);
  assert.equal(view.previewScroller.hidden, true);
  assert.equal(listeners.size, 0);
  assert.deepEqual([view.textarea.scrollTop, view.textarea.scrollLeft,
    view.textarea.selectionStart, view.textarea.selectionEnd, view.textarea.selectionDirection],
  [80, 24, 3, 8, 'backward']);
});
