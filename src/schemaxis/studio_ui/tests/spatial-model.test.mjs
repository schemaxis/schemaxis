// Copyright (C) 2026 David L. F. Gaden.
import test from 'node:test';
import assert from 'node:assert/strict';
import {entryOverlays, literalSpatial, numericLiteral, spatialEntries, writeLiteral} from '../windows/spatial/model.mjs';

test('both literal box forms agree; flat and invalid boxes remain distinct', () => {
  const flat = literalSpatial([-2, 4, -1, 1, 0, 0]);
  assert.deepEqual(flat, literalSpatial({min: [-2, -1, 0], max: [4, 1, 0]}));
  assert.equal(flat.valid, true);
  assert.deepEqual(literalSpatial({min: [0, 0, 2], max: [1, 1, 1]}).value, {min: [1, 1, 1], max: [-1, -1, -1]});
});

test('values that are not numbers throughout are not spatial entries', () => {
  for (const value of [['x+', 'y+', 'z+'], [1, null, 3], ['a', 'b', 'c', 'd', 'e', 'f'], [0, 1, 0, 1, 0, null],
    {min: 'a', max: 'b'}, {min: [0, 0, 0], max: [1, null, 1]}, {min: [0, 0, 0], max: [1, 1, 1], label: 'x'}, 'text', true]) {
    assert.equal(literalSpatial(value), null);
  }
  assert.deepEqual(spatialEntries({settings: {directions: ['x+', 'y+', 'z+'], gap: 2}}).map(e => e.name), ['gap']);
});

test('an edited box keeps its authored form, so six-number consumers and parameters still work', () => {
  const root = {definitions: {region: [0, 2, 0, 4, 0, 6], canonical: {min: [0, 0, 0], max: [1, 1, 1]},
    corners: {$value: 'boundsFromExtents', args: {extents: {$document: '/definitions/region'}}}}};
  const [region, canonical] = spatialEntries(root);
  const identity = name => ({base: '', group: 'definitions', name});
  assert.deepEqual(writeLiteral(root, identity('region'), region.literal.value, region), root);
  assert.deepEqual(writeLiteral(root, identity('region'), {min: [0, 0, 0], max: [3, 4, 0]}, region).definitions.region, [0, 3, 0, 4, 0, 0]);
  assert.deepEqual(writeLiteral(root, identity('region'), {min: [5, 0, 0], max: [3, 4, 6]}, region).definitions.region, [1, -1, 1, -1, 1, -1]);
  assert.deepEqual(writeLiteral(root, identity('canonical'), {min: [0, 0, 0], max: [2, 1, 1]}, canonical).definitions.canonical, {min: [0, 0, 0], max: [2, 1, 1]});
  assert.deepEqual(writeLiteral(root, identity('fresh'), [0, 1, 0, 1, 0, 1]).definitions.fresh, {min: [0, 0, 0], max: [1, 1, 1]});
  const design = {version: 'schemaxis.workflow-design/2',
    workflow: {version: 'schemaxis.workflow/1', settings: {region: [0, 1, 0, 1, 0, 1]}, operations: []},
    parameters: {region: {kind: 'vector', default: [0, 1, 0, 1, 0, 1], constraints: {length: 6},
      target: {scope: 'workflow', pointer: '/settings/region'}}}};
  const exposed = spatialEntries(design, '/workflow')[0];
  const result = writeLiteral(design, {base: '/workflow', group: 'settings', name: 'region'}, {min: [0, 0, 0], max: [2, 1, 1]}, exposed);
  assert.deepEqual(result.workflow.settings.region, [0, 2, 0, 1, 0, 1]);
  assert.deepEqual(result.parameters.region.default, [0, 2, 0, 1, 0, 1]);
  assert.deepEqual(result.parameters.region.constraints, {length: 6});
});

test('expressions and nested markers are unresolved even when they look constant', () => {
  for (const value of [{$expr: '1 + 2'}, {$document: '/settings/x'}, {$value: 'boundsCentre', args: {}},
    {min: [0, 0, {$expr: '0'}], max: [1, 1, 1]}, [1, 2, {$sweep: 't'}]]) {
    assert.equal(literalSpatial(value).state, 'unresolved');
  }
});

test('scope and section identities prevent workflow collisions and guessed geometry', () => {
  const root = {version: 'schemaxis.workflow/1', definitions: {box: [0, 1, 0, 1, 0, 1]}, operations: [
    {id: 'a', document: {definitions: {box: [0, 2, 0, 2, 0, 0], point: [1, 2, 3], derived: {$expr: 'box'}}, settings: {box: 4}}},
    {id: 'b', document: {definitions: {box: [0, 9, 0, 9, 0, 9]}}},
  ]};
  const rows = spatialEntries(root, '/operations/0/document');
  assert.equal(rows.length, 4);
  const overlays = entryOverlays(rows);
  assert.equal(overlays.length, 2);
  assert.deepEqual(overlays[0].max, [2, 2, 0]);
  assert.equal(overlays[1].kind, 'point');
  assert.deepEqual(entryOverlays(rows, {vectorsAsLines: true})[1].start, [0, 0, 0]);
  assert.equal(entryOverlays(rows, {hidden: new Set([overlays[0].id])}).length, 1);
});

test('literal changes are immutable and names cannot overwrite another entry', () => {
  const root = {definitions: {existing: [0, 1, 0, 1, 0, 1], pending: {$expr: 'existing'}}};
  const before = structuredClone(root);
  const result = writeLiteral(root, {base: '', group: 'definitions', name: 'flat'}, {min: [0, 0, 0], max: [1, 1, 0]});
  assert.deepEqual(root, before);
  assert.deepEqual(result.definitions.pending, root.definitions.pending);
  assert.throws(() => writeLiteral(root, {base: '', group: 'definitions', name: 'existing'}, 1), /already exists/);
  const previous = spatialEntries(root)[0];
  assert.throws(() => writeLiteral(root, {base: '', group: 'definitions', name: 'renamed'}, 1, previous), /existing name/);
  for (const text of ['', ' ', 'null', 'true', '1/2', 'Infinity', '1e999']) assert.throws(() => numericLiteral(text), /finite number/);
  assert.equal(numericLiteral('-2.5e2'), -250);
});

test('editing an exposed shared scalar keeps its Case Runner default in sync', () => {
  const root = {version: 'schemaxis.workflow-design/2', workflow: {version: 'schemaxis.workflow/1',
    dimensions: {distance: 10}, operations: []}, parameters: {distance: {
    kind: 'number', default: 10, units: 'mm', help: 'Spacing', target: {scope: 'workflow', pointer: '/dimensions/distance'}}}};
  const previous = spatialEntries(root, '/workflow')[0];
  const result = writeLiteral(root, {base: '/workflow', group: 'dimensions', name: 'distance'}, 12.5, previous);
  assert.equal(result.workflow.dimensions.distance, 12.5);
  assert.equal(result.parameters.distance.default, 12.5);
  assert.equal(result.parameters.distance.units, 'mm');
  assert.equal(result.parameters.distance.help, 'Spacing');
  assert.equal(root.parameters.distance.default, 10);
});
