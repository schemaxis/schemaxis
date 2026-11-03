// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {parse} from '../editor/json-parse.mjs';
import {resolveDiagnostics} from '../editor/diagnostics.mjs';
import {classifyDiagnostics, duplicateKeyDiagnostics, settledDiagnostics} from '../editor/settle.mjs';
import {DiagnosticSettler} from '../editor/settle-state.mjs';
import {backgroundValidation} from '../editor/settle-server.mjs';

function classify(text, caret = text.length, extra = []) {
  const ast = parse(text);
  return classifyDiagnostics(ast,
    [...resolveDiagnostics(ast, ast.diagnostics, 'syntax'), ...duplicateKeyDiagnostics(ast), ...extra], caret);
}

for (const [title, text, needle] of [
  ['object trailing comma', '{"origin":1,}', 'Trailing comma'],
  ['array trailing comma', '[1,]', 'Trailing comma'],
  ['key without colon', '{"origin"}', "Expected ':'"],
  ['key without value', '{"origin":}', 'Expected a value'],
  ['empty value after colon', '{"origin":  }', 'Expected a value'],
  ['unfinished string', '{"origin":"hel', 'Unterminated string'],
  ['unfinished unicode string', '{"origin":"\\u12', 'Invalid unicode escape'],
  ['unfinished decimal', '{"origin":1.}', 'Invalid number'],
  ['unfinished negative number', '{"origin":-}', 'Invalid number'],
  ['unfinished exponent', '{"origin":1e}', 'Invalid number'],
  ['unfinished signed exponent', '{"origin":1e-}', 'Invalid number'],
  ['missing comma across lines', '[1\n2]', "Expected ','"],
  ['unclosed bracket', '{"nodes": [', 'Unterminated array'],
  ['unclosed brace', '{"nodes": [', 'Unterminated object'],
]) {
  test(`active edit treats ${title} as transient`, () => {
    const diagnostics = classify(text, text.length - (/[}\]]$/.test(text) ? 1 : 0));
    const found = diagnostics.find((item) => item.message.startsWith(needle));
    assert.equal(found?.settle, 'transient');
    assert.equal(found?.source, 'syntax');
    assert.deepEqual(settledDiagnostics(diagnostics, {caret: text.length - 1, idle: 10000}), []);
  });
}

test('duplicate key is transient only while editing that key', () => {
  const text = '{"origin":1,"origin":2}';
  assert.equal(classify(text, 16)[0].settle, 'transient');
  assert.equal(classify(text, 21)[0].settle, 'stable');
});

test('required and type errors are local inside the edited object', () => {
  const text = '{"nested":{"count":"x"},"next":{}}';
  const ast = parse(text);
  const errors = resolveDiagnostics(ast, [
    {pointer: '/nested', message: 'Missing required property "id"'},
    {pointer: '/nested/count', message: 'Expected number, found string'},
  ], 'schema');
  const items = classifyDiagnostics(ast, errors, 20);
  // Required-key ranges point at the object key; ownership is obtained from its pointer.
  assert.deepEqual(items.map((item) => item.settle), ['local', 'local']);
  assert.equal(settledDiagnostics(items, {caret: 20, idle: 1499}).length, 0);
  assert.equal(settledDiagnostics(items, {caret: 20, idle: 1500}).length, 2);
  assert.equal(settledDiagnostics(items, {caret: 31, idle: 1}).length, 2);
});

test('syntax outside active object and irrecoverable numbers remain stable', () => {
  const text = '{"bad":[1,],"active":{}}';
  assert.equal(classify(text, text.length - 2)[0].settle, 'stable');
  assert.equal(classify('{"x":01}', 7)[0].settle, 'stable');
});

test('transient errors require both leaving their region and idle, or blur/explicit action', () => {
  const items = classify('{"x":[1,],"y":{}}', 8);
  assert.equal(items[0].settle, 'transient');
  assert.equal(settledDiagnostics(items, {caret: 16, idle: 1499}).length, 0);
  assert.equal(settledDiagnostics(items, {caret: 16, idle: 1500}).length, 1);
  assert.equal(settledDiagnostics(items, {caret: 8, idle: 10000}).length, 0);
  assert.equal(settledDiagnostics(items, {caret: 8, blurred: true}).length, 1);
  assert.equal(settledDiagnostics(items, {caret: 8, explicit: true}).length, 1);
});

test('stable diagnostics appear at 600 ms; server and fill sources remain distinct', () => {
  const items = classify('{}', 1, [
    {from: 0, to: 1, source: 'external', message: 'Host problem'},
    {from: 0, to: 1, source: 'fill', message: 'Value to fill'},
  ]);
  assert.deepEqual(items.map((item) => item.source), ['server', 'fill']);
  assert.equal(settledDiagnostics(items, {caret: 1, idle: 599}).length, 0);
  assert.equal(settledDiagnostics(items, {caret: 1, idle: 600}).length, 2);
});

test('realistic character typing keeps every incomplete prefix quiet', () => {
  const text = '{"nodes": [{"id": "origin", "count": -1.2e3, "enabled": true}]}';
  for (let length = 1; length < text.length; length += 1) {
    const source = text.slice(0, length);
    const items = classify(source);
    assert.equal(settledDiagnostics(items, {caret: length, idle: 180}).length, 0, source);
    assert.ok(items.every((item) => item.settle === 'transient'), source);
  }
});

test('settler retains edit classification through caret departure, versions and explicit flush', () => {
  let now = 0;
  let caret = 8;
  const model = new DiagnosticSettler({caret: () => caret, publish: () => {}, now: () => now});
  try {
    model.changed();
    const ast = parse('{"x":[1,],"y":{}}');
    model.analyse(ast, resolveDiagnostics(ast, ast.diagnostics, 'syntax'));
    assert.equal(model.snapshot().version, 1);
    assert.equal(model.snapshot().editing, true);
    caret = 16;
    now = 1499;
    assert.equal(model.refresh().length, 0);
    now = 1500;
    assert.equal(model.refresh().length, 1);
    model.changed();
    assert.equal(model.snapshot().version, 2);
    assert.equal(model.snapshot().canValidate, false);
  } finally { model.destroy(); }
});

test('background validation debounces, gates syntax and discards stale results', async () => {
  let listener;
  let state = {version: 1, canValidate: false};
  let requests = 0;
  let finish;
  const applied = [];
  const editor = {
    onSettledState(fn) { listener = fn; fn(state); return () => {}; },
    getTextVersion: () => state.version,
    getSettledState: () => state,
    getValue: () => '{}',
    setDiagnostics(items, options) { if (options.version === state.version) applied.push(items); },
  };
  const stop = backgroundValidation(editor, () => {
    requests += 1;
    return new Promise((resolve) => { finish = resolve; });
  }, {delay: 25});
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  try {
    await wait(40);
    assert.equal(requests, 0);
    state = {version: 2, canValidate: true};
    listener(state);
    await wait(10);
    assert.equal(requests, 0);
    await wait(30);
    assert.equal(requests, 1);
    state = {version: 3, canValidate: false};
    listener(state);
    finish([{message: 'Old result'}]);
    await wait(0);
    assert.deepEqual(applied, []);
  } finally { stop(); }
});
