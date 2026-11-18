// Copyright (C) 2026 David L. F. Gaden.
import test from 'node:test';
import assert from 'node:assert/strict';
import {overlayBounds, prepareOverlays} from '../viewers/spatial-overlay.mjs';
import {prepareGeometry} from '../viewers/geometry.mjs';

test('boxes draw twelve edges, flat boxes four, line boxes one, and point boxes a dot', () => {
  for (const [max, segments, dots] of [[[2, 3, 4], 12, 0], [[2, 3, 0], 4, 0], [[2, 0, 0], 1, 0], [[0, 0, 0], 0, 1]]) {
    const result = prepareOverlays([{id: 'box', kind: 'box', min: [0, 0, 0], max}]);
    assert.equal(result.lines.length, segments * 20);
    assert.equal(result.dots.length, dots * 10);
    assert.ok([...result.lines, ...result.dots].every(Number.isFinite));
  }
  const invalid = prepareOverlays([{id: 'invalid', kind: 'box', min: [1, 1, 1], max: [-1, -1, -1]}]);
  assert.equal(invalid.lines.length + invalid.dots.length, 0);
  assert.equal(invalid.frame.worldBounds, null);
});

test('overlay coordinates share the native frame and never change native identities', () => {
  const mesh = prepareGeometry({revision: 4, objects: [{id: 'native', vertices: [{id: 'v', point: [100, 200, 300]}]}]});
  const result = prepareOverlays([{id: 'authored', kind: 'line', start: [100, 200, 300], end: [101, 202, 303]}], mesh);
  assert.deepEqual([...result.lines.slice(0, 3)], [0, 0, 0]);
  assert.equal(result.frame.radius, mesh.radius);
  assert.deepEqual(mesh.elements.map(e => e.object), ['native']);
  assert.deepEqual(result.frame.worldBounds, {minimum: [100, 200, 300], maximum: [101, 202, 303]});
  assert.equal(overlayBounds(mesh, result).maximum[2], 3 / mesh.radius);
});

test('large translated coordinates, points and coincident line endpoints remain finite', () => {
  const result = prepareOverlays([
    {id: 'p', kind: 'point', point: [1e9, 1e9, 1e9]},
    {id: 'l', kind: 'line', start: [1e9 + 2, 1e9, 1e9], end: [1e9 + 2, 1e9, 1e9]},
  ]);
  assert.deepEqual(result.frame.centre, [1e9 + 1, 1e9, 1e9]);
  assert.equal(result.dots.length, 20);
  assert.equal(result.lines.length, 0);
});

test('malformed and nonfinite primitives are refused before rendering', () => {
  for (const item of [{id: 'x', kind: 'point', point: [0, 0, Infinity]},
    {id: 'x', kind: 'box', min: [0, 0, 0], max: [1, 1, {$expr: '2'}]},
    {id: 'x', kind: 'line', start: [0, 0, 0]}]) assert.throws(() => prepareOverlays([item]), /finite XYZ/);
  assert.throws(() => prepareOverlays(Array(10001).fill(null)), /At most/);
});
