// Copyright (C) 2026 David L F Gaden
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildSearch, captureNames, createTextDocument, extractTable, extractTableSync, findAll,
} from '../viewers/text-model.mjs';

const LOG = [
  'Starting time loop',
  '',
  'Time = 0.005',
  '',
  'smoothSolver:  Solving for Ux, Initial residual = 0.0123, Final residual = 1e-05, No Iterations 3',
  'smoothSolver:  Solving for Uy, Initial residual = 0.0456, Final residual = 2.5e-06, No Iterations 2',
  'GAMG:  Solving for p, Initial residual = 1, Final residual = 0.0091, No Iterations 14',
  'ExecutionTime = 0.31 s',
  '',
  'Time = 0.01',
  '',
  'smoothSolver:  Solving for Ux, Initial residual = 0.0098, Final residual = 8.1e-06, No Iterations 3',
  'smoothSolver:  Solving for Uy, Initial residual = 0.0311, Final residual = 1.9e-06, No Iterations 2',
  'GAMG:  Solving for p, Initial residual = 0.42, Final residual = 0.0038, No Iterations 12',
  'End',
].join('\n');

const RESIDUALS = 'Solving for (?<field>\\w+), Initial residual = (?<initial>[^,]+), '
  + 'Final residual = (?<final>[^,]+), No Iterations (?<iterations>\\d+)';

const immediate = () => Promise.resolve();

test('line index handles LF, CRLF, a trailing newline and empty text', () => {
  const doc = createTextDocument('a\r\nbb\n\nccc\n');
  assert.equal(doc.lineCount, 4);
  assert.deepEqual([0, 1, 2, 3].map(doc.lineText), ['a', 'bb', '', 'ccc']);
  assert.equal(doc.maxLength, 3);
  assert.equal(doc.lineOf(0), 0);
  assert.equal(doc.lineOf(3), 1);
  assert.equal(doc.lineOf(7), 3);
  assert.equal(createTextDocument('').lineCount, 1);
  assert.equal(createTextDocument('x').lineText(0), 'x');
});

test('line index scales to a million lines', () => {
  const text = 'line of a log file with some numbers 0.125 1e-05\n'.repeat(1_000_000);
  const started = performance.now();
  const doc = createTextDocument(text);
  const elapsed = performance.now() - started;
  assert.equal(doc.lineCount, 1_000_000);
  assert.equal(doc.lineText(999_999), 'line of a log file with some numbers 0.125 1e-05');
  assert.ok(elapsed < 2000, `indexing took ${elapsed} ms`);
});

test('plain search escapes metacharacters; case and regex options apply', async () => {
  const doc = createTextDocument('a.b A.B axb\n(x) [y]');
  const plain = await findAll(doc.text, buildSearch('a.b'));
  assert.deepEqual(plain.starts, [0, 4]);
  const sensitive = await findAll(doc.text, buildSearch('a.b', {caseSensitive: true}));
  assert.deepEqual(sensitive.starts, [0]);
  const regex = await findAll(doc.text, buildSearch('a.b', {regex: true}));
  assert.deepEqual(regex.starts, [0, 4, 8]);
  const brackets = await findAll(doc.text, buildSearch('(x) [y]'));
  assert.deepEqual(brackets.starts, [12]);
  assert.throws(() => buildSearch('(', {regex: true}), /Invalid regular expression/);
  assert.equal(buildSearch(''), null);
  const anchored = await findAll(doc.text, buildSearch('^\\(', {regex: true}));
  assert.deepEqual(anchored.starts, [12], 'anchors match per line');
  const empty = await findAll(doc.text, buildSearch('x*', {regex: true}));
  assert.ok(empty.starts.every((start, i) => empty.ends[i] > start), 'zero-length matches are skipped');
});

test('incremental search yields, reports progress and can be cancelled', async () => {
  const text = 'abc '.repeat(200_000);
  let yields = 0;
  const result = await findAll(text, buildSearch('b'), {budgetMs: 0, yieldFn: async () => {
    yields++;
  }});
  assert.equal(result.starts.length, 200_000);
  assert.ok(yields > 10);
  const controller = new AbortController();
  await assert.rejects(findAll(text, buildSearch('b'), {budgetMs: 0, signal: controller.signal,
    yieldFn: async () => controller.abort()}), {name: 'AbortError'});
});

test('capture names: named, unnamed, non-capturing, lookarounds, classes and escapes', () => {
  assert.deepEqual(captureNames('(?<a>x)(y)(?:z)(?=w)(?<=v)(?<!u)(?<b>\\()[(](t)'),
    ['a', 'group 2', 'b', 'group 4']);
  assert.deepEqual(captureNames('no groups'), []);
});

test('grep extraction: OpenFOAM residual lines become typed columns with carried Time', () => {
  const doc = createTextDocument(LOG);
  const table = extractTableSync(doc, {pattern: RESIDUALS, context: '^Time = (?<Time>\\S+)'});
  assert.deepEqual(table.columns, [
    {name: 'line', type: 'integer'},
    {name: 'Time', type: 'number'},
    {name: 'field', type: 'text'},
    {name: 'initial', type: 'number'},
    {name: 'final', type: 'number'},
    {name: 'iterations', type: 'integer'},
  ]);
  assert.equal(table.rows.length, 6);
  assert.deepEqual(table.rows[0], [5, 0.005, 'Ux', 0.0123, 1e-05, 3]);
  assert.deepEqual(table.rows[5], [14, 0.01, 'p', 0.42, 0.0038, 12]);
  assert.deepEqual(table.source, {pattern: RESIDUALS, context: '^Time = (?<Time>\\S+)', lines: 15, matched: 6});
});

test('grep extraction: unnamed groups, whole matches, missing optional groups and no line column', () => {
  const doc = createTextDocument(LOG);
  const unnamed = extractTableSync(doc, {pattern: '^Time = ([\\d.]+)', includeLine: false});
  assert.deepEqual(unnamed.columns, [{name: 'group 1', type: 'number'}]);
  assert.deepEqual(unnamed.rows, [[0.005], [0.01]]);
  const whole = extractTableSync(doc, {pattern: 'GAMG', includeLine: false});
  assert.deepEqual(whole.columns, [{name: 'match', type: 'text'}]);
  assert.equal(whole.rows.length, 2);
  const optional = extractTableSync(doc, {pattern: 'Execution(Time) = ([\\d.]+)( s)?(x)?', includeLine: false});
  assert.deepEqual(optional.columns.map((c) => c.type), ['text', 'number', 'text', 'empty']);
  assert.deepEqual(optional.rows[0], ['Time', 0.31, ' s', null]);
  const insensitive = extractTableSync(doc, {pattern: 'solving FOR (\\w+)', caseSensitive: false});
  assert.equal(insensitive.rows.length, 6);
  assert.throws(() => extractTableSync(doc, {pattern: '('}), /Invalid row pattern/);
  assert.throws(() => extractTableSync(doc, {pattern: ''}), /capture groups/);
  const duplicate = extractTableSync(doc, {pattern: 'Time = (?<line>\\S+)'});
  assert.deepEqual(duplicate.columns.map((c) => c.name), ['line', 'line_2']);
});

test('chunked extraction is deterministic regardless of chunk size and yields', async () => {
  const lines = [];
  for (let step = 1; step <= 3000; step++) {
    lines.push(`Time = ${step * 0.005}`);
    for (const field of ['Ux', 'p']) {
      lines.push(`Solving for ${field}, Initial residual = ${(1 / step).toExponential(3)}, `
        + `Final residual = ${(0.01 / step).toExponential(2)}, No Iterations ${step % 7}`);
    }
  }
  const doc = createTextDocument(lines.join('\n'));
  const spec = {pattern: RESIDUALS, context: '^Time = (?<Time>\\S+)'};
  const reference = extractTableSync(doc, spec);
  assert.equal(reference.rows.length, 6000);
  for (const chunkLines of [1, 7, 333, 100000]) {
    const progress = [];
    const table = await extractTable(doc, spec, {chunkLines, budgetMs: 0, yieldFn: immediate,
      onProgress: (fraction) => progress.push(fraction)});
    assert.deepEqual(table, reference);
    assert.equal(progress.at(-1), 1);
    assert.ok(progress.every((value, i) => i === 0 || value >= progress[i - 1]), 'progress is monotonic');
  }
  const controller = new AbortController();
  await assert.rejects(extractTable(doc, spec, {chunkLines: 10, budgetMs: 0, signal: controller.signal,
    yieldFn: async () => controller.abort()}), {name: 'AbortError'});
});
