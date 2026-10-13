// The naming preview mirrors src/schemaxis/output_naming.py; cases follow
// tests/unit/test_output_naming.py so the two cannot drift silently.

import assert from 'node:assert/strict';
import {test} from 'node:test';
import {
  DEFAULT_PATTERN, NamingError, formatNumber, preview, sampleEntries, sanitise, validatePattern, validateWidth,
} from '../windows/designer/naming.mjs';

test('default pattern tokens', () => {
  assert.deepEqual(validatePattern(DEFAULT_PATTERN), ['index', 'operation', 'output', 'ext']);
});

test('invalid patterns and widths are rejected like the server', () => {
  const invalid = ['', 'plain', '../{index}', '{index}/x', '{unknown}', '{param:1x}', '.{index}', 'a b{index}',
    '{index', `${'x'.repeat(300)}{index}`, 3];
  for (const pattern of invalid) {
    assert.throws(() => validatePattern(pattern), NamingError, String(pattern));
  }
  for (const width of [0, 13, true, 2.5]) {
    assert.throws(() => validateWidth(width), NamingError, String(width));
  }
  assert.deepEqual(validatePattern('{index}-inlet_{param:inlet}-s{axis:stop}{ext}'),
    ['index', 'param:inlet', 'axis:stop', 'ext']);
});

test('sanitising matches output_naming.sanitise', () => {
  const cases = [[0.5, '0p5'], [-2, 'm2'], [2.0, '2'], [-0.125, 'm0p125'], [1e-7, '1em07'], [true, 'yes'],
    [false, 'no'], ['inlet v1.2', 'inlet_v1p2'], ['a/b', 'a_b'], [[1, 2.5], '1_2p5'], [null, 'none'],
    ['', '_'], [1e20, '1e20'], [123456.789, '123456p789'], [0.0001, '0p0001'], [0.00001, '1em05'],
    [1 / 3, '0p333333333333'], ['☃.x', '_px']];
  for (const [value, expected] of cases) {
    assert.equal(sanitise(value), expected, JSON.stringify(value));
  }
  assert.throws(() => sanitise({a: 1}), NamingError);
  assert.throws(() => sanitise([]), NamingError);
});

test('Python %.12g formatting', () => {
  assert.equal(formatNumber(1e-7), '1e-07');
  assert.equal(formatNumber(2.5e15), '2.5e+15');
  assert.equal(formatNumber(2.5e12), '2500000000000', 'JSON cannot tell integer floats apart');
  assert.equal(formatNumber(0.1 + 0.2), '0.3');
  assert.equal(formatNumber(-0), '-0');
  assert.throws(() => formatNumber(Infinity), NamingError);
});

test('preview matches the live UI cases', () => {
  const entries = [
    {operation: 'mesh', output: 'volume', ext: '.vtu', parameters: {inlet: 2.5}},
    {operation: 'mesh', output: 'volume', ext: '.vtu', parameters: {inlet: -1}},
  ];
  assert.deepEqual(preview('{index}-inlet_{param:inlet}-{output}{ext}', entries, 3),
    {names: ['001-inlet_2p5-volume.vtu', '002-inlet_m1-volume.vtu'], collisions: [], error: null});
  assert.deepEqual(preview('{operation}{ext}', entries).collisions, ['mesh.vtu']);
  assert.match(preview('{param:missing}{index}', entries).error, /parameter missing has no value/);
  assert.match(preview('{nope}', entries).error, /unknown token/);
  assert.deepEqual(preview('{index}', [{}, {}], 2).names, ['01', '02']);
});

test('sample entries come from named outputs, else output ports', () => {
  const projection = {
    nodes: [{id: 'mesh', ports: {inputs: [], outputs: [{name: 'volume', artifact: 0, data: {kind: 'geometry'}}]}}],
    outputs: {},
  };
  assert.deepEqual(sampleEntries(projection, {inlet: 1}).map((entry) => [entry.operation, entry.output, entry.ext]),
    [['mesh', 'volume', '.vtu']]);
  projection.outputs = {report: {operation: 'mesh', artifact: 1, kind: 'table'}};
  assert.deepEqual(sampleEntries(projection).map((entry) => [entry.output, entry.artifact, entry.ext]),
    [['report', 1, '.csv']]);
});
