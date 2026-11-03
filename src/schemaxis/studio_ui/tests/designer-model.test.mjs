// Copyright (C) 2026 David L F Gaden
// Revision ordering protects rapid gestures; stale conflicts retain local node positions.

import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createModel} from '../windows/designer/model.mjs';
import {sourcePointer} from '../windows/designer/locations.mjs';

function fixture() {
  let revision = 1;
  let sourceVersion = 'schemaxis.workflow-design/2';
  let fail = null;
  const requests = [];
  const notices = [];
  const projection = {nodes: [{id: 'a', ports: {inputs: [], outputs: []}}], edges: [], loops: [],
    layout: {nodes: {a: {x: 10, y: 20}}}};
  const ctx = {
    api: {
      async get() {
        return {id: 'design', name: 'Study', revision, undoCount: revision - 1, redoCount: 0,
          document: {version: sourceVersion}};
      },
      async post(path, request) {
        requests.push({...request});
        await new Promise((resolve) => setTimeout(resolve, 5));
        if (fail) {
          const error = fail;
          fail = null;
          throw error;
        }
        if (request.revision !== revision) {
          throw {code: 'STALE_REVISION', message: 'Stale'};
        }
        if (request.action !== 'project') revision += 1;
        if (request.action === 'move') Object.assign(projection.layout.nodes, request.params.positions);
        if (request.action === 'upgrade') sourceVersion = 'schemaxis.workflow-design/2';
        return {document: 'design', revision, undoCount: revision - 1, redoCount: 0,
          projection: structuredClone(projection)};
      },
    },
    call: (action) => action(),
    refresh: async () => {},
    notify: {
      error: (...args) => notices.push(['error', ...args]),
      info: (...args) => notices.push(['info', ...args]),
    },
  };
  return {model: createModel(ctx, 'design'), requests, notices, changeExternally: () => { revision += 1; },
    legacy: () => { sourceVersion = 'schemaxis.workflow-design/1'; },
    failNext: (error) => { fail = error; }};
}

test('rapid design mutations are serialised against the latest revision', async () => {
  const {model, requests} = fixture();
  await model.load();
  await Promise.all([
    model.action('set_naming', {naming: {indexWidth: 4}}),
    model.action('set_outputs', {outputs: {}}),
    model.action('move', {positions: {a: {x: 40, y: 80}}}),
  ]);
  assert.deepEqual(requests.map((request) => request.revision), [1, 1, 2, 3]);
  assert.equal(model.store.get().revision, 4);
  assert.deepEqual(model.store.get().positions.a, {x: 40, y: 80});
  assert.equal(model.store.get().busy, false);
});

test('stale design edit refreshes and keeps unsaved drag positions visible', async () => {
  const {model, notices, changeExternally} = fixture();
  await model.load();
  model.moveLocal({a: {x: 50, y: 100}});
  changeExternally();
  assert.equal(await model.commitMoves(['a']), undefined);
  assert.deepEqual(model.store.get().positions.a, {x: 50, y: 100});
  assert.equal(model.store.get().revision, 2);
  assert.equal(notices.filter(([kind]) => kind === 'info').length, 1);
  await model.commitMoves(['a']);
  assert.deepEqual(model.store.get().local, {});
});

test('opening a legacy design migrates its port model with a revisioned undo entry', async () => {
  const {model, requests, legacy} = fixture();
  legacy();
  await model.load();
  assert.equal(requests[0].action, 'upgrade');
  assert.equal(model.store.get().revision, 2);
  assert.equal(model.store.get().undoCount, 1);
});

test('projection failure reaches notification reporting and the canvas fault', async () => {
  const {model, notices, failNext} = fixture();
  const error = {code: 'INVALID_DESIGN', message: 'Invalid design', fault: {code: 'INVALID_DESIGN',
    message: 'Invalid design', location: '$.workflow'}};
  failNext(error);
  assert.equal(await model.load(), false);
  assert.equal(notices[0][0], 'error');
  assert.deepEqual(model.store.get().fault, error.fault);
  assert.equal(model.store.get().projection, null);
});

test('backend locations reveal array values and dotted template parameter IDs', () => {
  const document = {workflow: {operations: [{document: {nodes: [{options: {count: 4}}]}}]},
    parameters: {'study.count': {target: '/settings/study.count'}}};
  assert.equal(sourcePointer('$.workflow.operations/0/document/nodes/0/options/count', document),
    '/workflow/operations/0/document/nodes/0/options/count');
  assert.equal(sourcePointer('$.parameters.study.count.target', document), '/parameters/study.count/target');
  assert.equal(sourcePointer('$.workflow.operations[0].unknown', document), '/workflow/operations/0');
});
