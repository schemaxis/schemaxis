// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {validBounds, pointOnPlane, observedBounds, geometryBounds} from '../windows/workbench/line-selector.mjs';

test('plane picks preserve world units and the selected third coordinate', () => {
  const bounds = [10, 30, -8, 4, 100, 140];
  assert.deepEqual(pointOnPlane(bounds, 'XY', .25, .5, 123), [15, -2, 123]);
  assert.deepEqual(pointOnPlane(bounds, 'XZ', .5, .25, -3), [20, -3, 110]);
  assert.deepEqual(pointOnPlane(bounds, 'YZ', .5, .75, 25), [25, -2, 130]);
  assert.deepEqual(pointOnPlane([1, 1, 2, 4, 0, 0], 'XY', .5, .5, 0), [1, 3, 0]);
  assert.equal(validBounds([10, 1, 0, 1, 0, 1]), false);
  assert.equal(validBounds([0, Infinity, 0, 1, 0, 1]), false);
  assert.throws(() => pointOnPlane(bounds, 'XY', 0, 0, NaN));
});

test('dataset bounds stay distinct from displayed geometry and empty datasets', () => {
  const data = {observations: {flow: {points: 8, bounds: [-10, 10, -10, 10, -10, 10]},
    empty: {points: 0, bounds: [1, -1, 1, -1, 1, -1]}}, objects: [{id: 'seeds',
    edges: [{id: 'Edge0', points: [[1, 2, 3], [1, 4, 3]]}]}]};
  assert.deepEqual(observedBounds(data), [{id: 'flow', bounds: [-10, 10, -10, 10, -10, 10]}]);
  assert.deepEqual(geometryBounds(data), [1, 1, 2, 4, 3, 3]);
  assert.equal(geometryBounds({objects: []}), null);
});
