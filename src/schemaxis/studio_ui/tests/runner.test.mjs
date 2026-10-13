import assert from 'node:assert/strict';
import {test} from 'node:test';
import {parseParameter, constraintText} from '../windows/runner/parameters.mjs';
import {stlGeometry, viewerKind} from '../windows/runner/artifacts.mjs';

test('case parameter controls preserve scalar types, defaults and vectors', () => {
  assert.equal(parseParameter({kind: 'boolean'}, 'false'), false);
  assert.equal(parseParameter({kind: 'boolean'}, ''), undefined);
  assert.equal(parseParameter({kind: 'integer'}, '12'), 12);
  assert.equal(parseParameter({kind: 'number'}, '-1.5'), -1.5);
  assert.equal(parseParameter({kind: 'number'}, ''), undefined);
  assert.equal(parseParameter({kind: 'string'}, ''), '');
  assert.equal(parseParameter({kind: 'enum', constraints: {enum: [false, true]}}, '0'), false);
  assert.equal(parseParameter({kind: 'enum', constraints: {enum: [2.5, 6]}}, '1'), 6);
  assert.deepEqual(parseParameter({kind: 'vector', constraints: {length: 3}}, '[0, -1, 2]'), [0, -1, 2]);
  assert.throws(() => parseParameter({kind: 'integer'}, '2.3'), /whole number/);
  assert.throws(() => parseParameter({kind: 'number'}, 'Infinity'), /finite number/);
  assert.throws(() => parseParameter({kind: 'boolean'}, 'wrong'), /Yes or No/);
  assert.throws(() => parseParameter({kind: 'enum', constraints: {enum: [1]}}, '2'), /listed value/);
  assert.throws(() => parseParameter({kind: 'vector', constraints: {length: 2}}, '[true, 0]'), /2 numbers/);
});

test('constraint hints retain inclusive ranges and zero lengths', () => {
  assert.equal(constraintText({constraints: {minimum: 0, maximum: 20}}), 'Minimum 0 · maximum 20');
  assert.equal(constraintText({constraints: {minLength: 0, maxLength: 10}}),
    'at least 0 characters · at most 10 characters');
});

test('output viewers select supported file formats explicitly', () => {
  assert.equal(viewerKind({name: 'table.csv', kind: 'table'}), 'table');
  assert.equal(viewerKind({name: 'stats.json', kind: 'analysis'}), 'text');
  assert.equal(viewerKind({name: 'render.PNG', kind: 'image'}), 'image');
  assert.equal(viewerKind({name: 'part.stl', kind: 'geometry'}), '3d');
  assert.equal(viewerKind({name: 'scene.json', kind: 'geometry'}), '3d-json');
  assert.equal(viewerKind({name: 'assembly.step', kind: 'geometry'}), 'download');
});

test('binary and ASCII STL preserve original coordinates and reject invalid geometry', () => {
  const binary = new ArrayBuffer(134);
  const view = new DataView(binary);
  view.setUint32(80, 1, true);
  [0, 0, 0, 10, 0, 0, 0, 20, 0].forEach((value, index) => view.setFloat32(96 + index * 4, value, true));
  const geometry = stlGeometry(binary, 'part', 'hash');
  assert.deepEqual(geometry.objects[0].faces[0].vertices, [[0, 0, 0], [10, 0, 0], [0, 20, 0]]);
  const ascii = new TextEncoder().encode('solid part\nfacet normal 0 0 1\nouter loop\n'
    + 'vertex 0 0 0\nvertex 10 0 0\nvertex 0 20 0\nendloop\nendfacet\nendsolid part');
  assert.deepEqual(stlGeometry(ascii.buffer, 'part', 'hash'), geometry);
  assert.throws(() => stlGeometry(new TextEncoder().encode('vertex NaN 1 2').buffer, 'part', 'r'));
  view.setFloat32(96, Infinity, true);
  assert.throws(() => stlGeometry(binary, 'part', 'r'), /finite vertices/);
});
