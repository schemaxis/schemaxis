// Copyright (C) 2026 David L F Gaden
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {convert, detectType, parseNumber} from '../viewers/data-types.mjs';
import {
  columnStats, detectHeader, filterOrder, parseDelimited, selectionTsv, sniffDelimiter, sortOrder, tableFromData,
  tableFromDelimited,
} from '../viewers/table-model.mjs';

test('RFC 4180: quotes, doubled quotes, embedded delimiters and newlines, CRLF / CR / LF', () => {
  const text = 'a,b,c\r\n"x, y","say ""hi""","line1\nline2"\r\n1,,3\r4,5,6\n';
  assert.deepEqual(parseDelimited(text), [
    ['a', 'b', 'c'],
    ['x, y', 'say "hi"', 'line1\nline2'],
    ['1', '', '3'],
    ['4', '5', '6'],
  ]);
});

test('parser edge cases: BOM, no final newline, trailing delimiter, blank lines, empty quoted, stray quotes', () => {
  assert.deepEqual(parseDelimited('﻿a,b\n1,2'), [['a', 'b'], ['1', '2']]);
  assert.deepEqual(parseDelimited('a,\n'), [['a', '']]);
  assert.deepEqual(parseDelimited('a\n\nb\n'), [['a'], ['b']]);
  assert.deepEqual(parseDelimited('""\n'), [['']]);
  assert.deepEqual(parseDelimited('5" pipe,ok\n"q"x,y'), [['5" pipe', 'ok'], ['qx', 'y']]);
  assert.deepEqual(parseDelimited('"unterminated, still,field'), [['unterminated, still,field']]);
  assert.deepEqual(parseDelimited(' a , b '), [[' a ', ' b ']], 'whitespace is preserved');
  assert.deepEqual(parseDelimited(''), []);
  assert.deepEqual(parseDelimited('a\tb\n1\t2', '\t'), [['a', 'b'], ['1', '2']]);
});

test('delimiter sniffing ignores delimiters inside quotes', () => {
  assert.equal(sniffDelimiter('a\tb\tc\n1\t2\t3\n'), '\t');
  assert.equal(sniffDelimiter('a;b;c\n"1,5";2;3\n"4,2";5;6\n'), ';');
  assert.equal(sniffDelimiter('a|b\n1|2\n'), '|');
  assert.equal(sniffDelimiter('name,"note; with; semicolons"\nx,"y; z"\n'), ',');
  assert.equal(sniffDelimiter('single column\nvalue\n'), ',');
});

test('header detection heuristic', () => {
  assert.equal(detectHeader([['time', 'value'], ['0.1', '3'], ['0.2', '4']]), true);
  assert.equal(detectHeader([['0.0', '1'], ['0.1', '3'], ['0.2', '4']]), false);
  assert.equal(detectHeader([['code', 'n'], ['AB1', '1'], ['CD2', '2']]), true);
  assert.equal(detectHeader([['ab', 'cd'], ['ef', 'gh']]), false, 'same-length text is ambiguous');
  assert.equal(detectHeader([['a', 'a'], ['1', '2']]), false, 'duplicate names');
  assert.equal(detectHeader([['a', ''], ['1', '2']]), false, 'empty name');
  assert.equal(detectHeader([['only']]), false);
});

test('type detection: integer, number, boolean, text, empty; special numerics', () => {
  assert.equal(detectType(['1', '-2', ' 3 ', '']), 'integer');
  assert.equal(detectType(['1', '2.5', '1e-05', '.5', '-3E+2']), 'number');
  assert.equal(detectType(['1', 'nan', 'inf', '-Infinity']), 'number');
  assert.equal(detectType(['true', 'FALSE', '']), 'boolean');
  assert.equal(detectType(['1', 'x']), 'text');
  assert.equal(detectType(['', '  ', null]), 'empty');
  assert.equal(detectType(['12345678901234567890']), 'number', 'unsafe integers are numbers');
  assert.equal(detectType(['0x10']), 'text');
  assert.equal(parseNumber('1e-05'), 1e-05);
  assert.ok(Number.isNaN(parseNumber('abc')));
  assert.equal(convert('  ', 'number'), null);
  assert.equal(convert('True', 'boolean'), true);
});

test('CSV fixture → typed table with header, ragged rows padded', () => {
  const text = readFileSync(new URL('./fixtures/viewers/sample.csv', import.meta.url), 'utf8');
  const table = tableFromDelimited(text);
  assert.equal(table.header, true);
  assert.equal(table.delimiter, ',');
  assert.deepEqual(table.columns.map((c) => `${c.name}:${c.type}`), ['case:text', 'inlet velocity:number',
    'spoiler angle:integer', 'drag:number', 'lift:number', 'converged:boolean', 'note:text']);
  assert.equal(table.rows.length, 240);
  assert.equal(table.rows[0][6], 'restart\nfrom t = 0.5');
  assert.equal(table.rows[1][6], null);
  const ragged = tableFromDelimited('a,b,c\n1,2\n3,4,5,6\n');
  assert.deepEqual(ragged.columns.map((c) => c.name), ['a', 'b', 'c', 'D']);
  assert.deepEqual(ragged.rows, [[1, 2, null, null], [3, 4, 5, 6]]);
  const forced = tableFromDelimited('1,2\n3,4\n', {header: true});
  assert.deepEqual(forced.columns.map((c) => c.name), ['1', '2']);
  const none = tableFromDelimited('x,y\n1,2\n', {header: false});
  assert.deepEqual(none.columns.map((c) => c.name), ['A', 'B']);
  assert.deepEqual(none.columns.map((c) => c.type), ['text', 'text']);
});

test('tableFromData accepts names or typed columns and detects types from values', () => {
  const detected = tableFromData({columns: ['t', 't', 'flag'], rows: [[0.5, '1', 'true'], [1, '2', 'false']]});
  assert.deepEqual(detected.columns, [{name: 't', type: 'number'}, {name: 't_2', type: 'integer'},
    {name: 'flag', type: 'boolean'}]);
  assert.deepEqual(detected.rows[1], [1, 2, false]);
  const declared = tableFromData({columns: [{name: 'a', type: 'integer'}], rows: [[1], [2], []]});
  assert.deepEqual(declared.rows, [[1], [2], [null]]);
  assert.throws(() => tableFromData({columns: []}), /columns and rows/);
});

test('column statistics: count, missing, min, max, mean and sample std; text uniques', () => {
  const table = tableFromData({columns: ['x', 'label'], rows: [['2', 'a'], ['4', 'b'], ['', 'a'], ['4', ''],
    ['5', 'a'], ['nan', 'c']]});
  const stats = columnStats(table, 0);
  assert.equal(stats.count, 4);
  assert.equal(stats.missing, 1);
  assert.equal(stats.nonFinite, 1);
  assert.equal(stats.min, 2);
  assert.equal(stats.max, 5);
  assert.equal(stats.mean, 3.75);
  assert.ok(Math.abs(stats.std - Math.sqrt(4.75 / 3)) < 1e-12);
  const text = columnStats(table, 1);
  assert.deepEqual({count: text.count, missing: text.missing, unique: text.unique, top: text.top},
    {count: 5, missing: 1, unique: 3, top: {value: 'a', count: 3}});
  const empty = columnStats(tableFromData({columns: ['x'], rows: [['1']]}), 0);
  assert.equal(empty.std, null, 'std needs two values');
});

test('sorting is stable, numeric-aware, and keeps empty cells last in both directions', () => {
  const table = tableFromData({columns: ['key', 'id', 'name'], rows: [
    ['2', '0', 'b10'], ['1', '1', 'b2'], ['', '2', ''], ['2', '3', 'a'], ['1', '4', 'B1'], ['2', '5', 'c'],
  ]});
  const ids = (order) => [...order].map((i) => table.rows[i][1]);
  assert.deepEqual(ids(sortOrder(table, 0, 'asc')), [1, 4, 0, 3, 5, 2]);
  assert.deepEqual(ids(sortOrder(table, 0, 'desc')), [0, 3, 5, 1, 4, 2]);
  assert.deepEqual(ids(sortOrder(table, 2, 'asc')), [3, 4, 1, 0, 5, 2], 'natural, case-insensitive text order');
  const many = tableFromData({columns: [{name: 'k', type: 'integer'}, {name: 'i', type: 'integer'}],
    rows: Array.from({length: 5000}, (_, i) => [i % 3, i])});
  const order = sortOrder(many, 0, 'asc');
  for (let i = 1; i < order.length; i++) {
    const [a, b] = [many.rows[order[i - 1]], many.rows[order[i]]];
    assert.ok(a[0] < b[0] || (a[0] === b[0] && a[1] < b[1]), 'ties keep original order');
  }
});

test('selection TSV quotes tabs, newlines and quotes; honours sort order and header option', () => {
  const table = tableFromData({columns: ['a', 'b'], rows: [['1', 'x\ty'], ['2', 'say "hi"'], ['3', 'multi\nline']]});
  assert.equal(selectionTsv(table, null, [0, 1], [0, 1]), '1\t"x\ty"\n2\t"say ""hi"""');
  assert.equal(selectionTsv(table, Uint32Array.from([2, 1, 0]), [0, 0], [0, 1], true), 'a\tb\n3\t"multi\nline"');
  assert.equal(selectionTsv(table, null, [1, 1], [0, 0]), '2');
});

test('row filtering is literal and case-insensitive, and retains original identities after sorting and copying', () => {
  const table = tableFromData({columns: ['id', 'label', 'value'], rows: [
    [1, 'Alpha [1]', 4], [2, 'beta', 9], [3, 'ALPHA [1]', 7], [4, '', 2],
  ]});
  const sorted = sortOrder(table, 2, 'desc');
  const filtered = filterOrder(table, sorted, 'alpha [1]');
  assert.deepEqual([...filtered], [2, 0]);
  assert.equal(selectionTsv(table, filtered, [0, 1], [0, 2], true),
    'id\tlabel\tvalue\n3\tALPHA [1]\t7\n1\tAlpha [1]\t4');
  assert.equal(filterOrder(table, sorted, ''), sorted);
  assert.equal(filterOrder(table, null, ''), null);
  assert.deepEqual([...filterOrder(table, null, '9')], [1], 'numeric cells participate');
  assert.deepEqual([...filterOrder(table, sorted, '.*')], [], 'a regex-looking query is literal');
  assert.deepEqual(table.rows[0], [1, 'Alpha [1]', 4], 'source data is unchanged');
});

test('large CSV parses quickly (100k rows × 50 columns)', () => {
  const header = Array.from({length: 50}, (_, c) => `col${c}`).join(',');
  const row = Array.from({length: 50}, (_, c) => (c % 5 === 0 ? `"name ${c}"` : (c * 0.125).toString())).join(',');
  const text = `${header}\n${`${row}\n`.repeat(100000)}`;
  const started = performance.now();
  const table = tableFromDelimited(text);
  const elapsed = performance.now() - started;
  assert.equal(table.rows.length, 100000);
  assert.equal(table.columns.length, 50);
  assert.equal(table.columns[1].type, 'number');
  assert.ok(elapsed < 8000, `parse took ${elapsed} ms`);
});
