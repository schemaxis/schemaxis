// Pure canvas geometry: Bézier wires, zoom to cursor, port positions, compatibility, layout.

import assert from 'node:assert/strict';
import {test} from 'node:test';
import {
  HEADER_HEIGHT, NODE_WIDTH, PORT_PAD_TOP, PORT_ROW, arrowPath, autoLayout, bezierAt, bezierPath, bezierPoints,
  compatibility, contentExceeds, edgeEndpoints, edgeRoute, isBackward, roundedPath, fitViewport, kindColour, minimapTransform, nodeHeight, nodesBounds,
  nodesInRect, portPosition, rectFrom, screenToWorld, uniqueId, wheelFactor, worldToScreen, zoomAt,
} from '../windows/designer/geometry.mjs';

const close = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-9,
  `${message}: ${actual} != ${expected}`);

function node(id, inputs = [], outputs = []) {
  return {id, ports: {inputs: inputs.map((name) => ({name})), outputs: outputs.map((name) => ({name}))}};
}

test('port positions sit on the card edges, one row per port', () => {
  const position = {x: 100, y: 50};
  assert.deepEqual(portPosition(position, 'inputs', 0),
    {x: 100, y: 50 + HEADER_HEIGHT + PORT_PAD_TOP + PORT_ROW / 2});
  assert.deepEqual(portPosition(position, 'outputs', 2),
    {x: 100 + NODE_WIDTH, y: 50 + HEADER_HEIGHT + PORT_PAD_TOP + 2.5 * PORT_ROW});
  assert.equal(nodeHeight(node('a')), nodeHeight(node('b', ['x'])));
  assert.equal(nodeHeight(node('c', ['x', 'y', 'z'], ['o'])) - nodeHeight(node('d', ['x'])), 2 * PORT_ROW);
});

test('wires are horizontal-tangent cubic Béziers', () => {
  const from = {x: 0, y: 0};
  const to = {x: 200, y: 100};
  const points = bezierPoints(from, to);
  assert.equal(points[1].y, from.y);
  assert.equal(points[2].y, to.y);
  assert.equal(points[1].x, 100);
  assert.equal(bezierPath(from, to), 'M 0 0 C 100 0, 100 100, 200 100');
  assert.deepEqual(bezierAt(points, 0), from);
  assert.deepEqual(bezierAt(points, 1), to);
  assert.deepEqual(bezierAt(points, 0.5), {x: 100, y: 50});
  const backwards = bezierPoints({x: 300, y: 0}, {x: 0, y: 0});
  assert.ok(backwards[1].x > 300 + 79, 'backward wires bow out');
  assert.match(arrowPath({x: 10, y: 10}), /^M 10 10 L /);
});

test('zoom keeps the point under the cursor fixed', () => {
  const viewport = {x: 40, y: -20, zoom: 1};
  const cursor = {x: 300, y: 200};
  const before = screenToWorld(viewport, cursor);
  const zoomed = zoomAt(viewport, cursor, 1.5);
  close(zoomed.zoom, 1.5, 'zoom');
  const after = screenToWorld(zoomed, cursor);
  close(after.x, before.x, 'x');
  close(after.y, before.y, 'y');
  const round = worldToScreen(zoomed, after);
  close(round.x, cursor.x, 'round x');
  assert.equal(zoomAt(viewport, cursor, 100).zoom, 2.5, 'clamped high');
  assert.equal(zoomAt(viewport, cursor, 0.001).zoom, 0.2, 'clamped low');
  assert.ok(wheelFactor(-100) > 1 && wheelFactor(100) < 1);
  close(wheelFactor(100) * wheelFactor(-100), 1, 'symmetric');
});

test('fit centres the bounds and caps the zoom', () => {
  const bounds = {x: 0, y: 0, width: 400, height: 200};
  const fitted = fitViewport(bounds, {width: 1000, height: 600}, {padding: 50});
  assert.equal(fitted.zoom, 1);
  const centre = screenToWorld(fitted, {x: 500, y: 300});
  close(centre.x, 200, 'centre x');
  close(centre.y, 100, 'centre y');
  const large = fitViewport({x: 0, y: 0, width: 4000, height: 1000}, {width: 1000, height: 600}, {padding: 0});
  close(large.zoom, 0.25, 'shrinks to fit');
  assert.deepEqual(fitViewport(null, {width: 10, height: 10}), {x: 0, y: 0, zoom: 1});
});

test('bounds, marquee and overflow', () => {
  const nodes = [node('a', ['x']), node('b')];
  const positions = {a: {x: 0, y: 0}, b: {x: 400, y: 300}};
  const bounds = nodesBounds(nodes, positions);
  assert.deepEqual(bounds, {x: 0, y: 0, width: 400 + NODE_WIDTH, height: 300 + nodeHeight(nodes[1])});
  assert.deepEqual(nodesInRect(nodes, positions, rectFrom({x: 500, y: 500}, {x: 350, y: 250})), ['b']);
  assert.deepEqual(nodesInRect(nodes, positions, rectFrom({x: -10, y: -10}, {x: 700, y: 700})), ['a', 'b']);
  assert.equal(contentExceeds(bounds, {x: 0, y: 0, zoom: 1}, {width: 2000, height: 2000}), false);
  assert.equal(contentExceeds(bounds, {x: 0, y: 0, zoom: 1}, {width: 300, height: 300}), true);
  const mini = minimapTransform(bounds, {x: 0, y: 0, zoom: 1}, {width: 300, height: 300}, {width: 200, height: 140});
  const corner = mini.toMini({x: bounds.x, y: bounds.y});
  const back = mini.toWorld(corner);
  close(back.x, bounds.x, 'minimap inverse');
  assert.ok(corner.x >= 0 && corner.y >= 0);
});

test('port compatibility: port kind, occupancy and data kind', () => {
  const output = {kind: 'artifact', data: {kind: 'table'}};
  assert.deepEqual(compatibility(output, {kind: 'artifact', data: {kind: 'table'}}), {ok: true, reason: 'match'});
  assert.deepEqual(compatibility(output, {kind: 'artifact'}), {ok: true, reason: 'unknown'});
  assert.deepEqual(compatibility({kind: 'artifact'}, {kind: 'artifact', data: {kind: 'image'}}),
    {ok: true, reason: 'unknown'});
  assert.deepEqual(compatibility(output, {kind: 'artifact', data: {kind: 'image'}}),
    {ok: true, reason: 'data-kind'});
  assert.equal(compatibility(output, {kind: 'value'}).reason, 'port-kind');
  assert.equal(compatibility(output, {kind: 'artifact', connections: ['c1']}).reason, 'occupied');
  assert.equal(kindColour('table'), 'var(--kind-table)');
  assert.equal(kindColour('bogus'), 'var(--kind-unknown)');
});

test('unique identifiers follow the backend name rule', () => {
  assert.equal(uniqueId('samples-scaled', []), 'samples-scaled');
  assert.equal(uniqueId('a', ['a', 'a-2']), 'a-3');
  assert.equal(uniqueId('9 lives!', []), 'lives-');
  assert.equal(uniqueId('', []), 'c');
});

test('auto layout keeps saved positions and layers the rest by dependency', () => {
  const nodes = [node('a'), node('b'), node('c')];
  const edges = [{source: 'a', target: 'b'}, {source: 'b', target: 'c'}, {source: 'c', target: 'a'}];
  const layout = autoLayout(nodes, edges, {});
  assert.ok(layout.a.x < layout.b.x && layout.b.x < layout.c.x);
  const kept = autoLayout(nodes, edges, {a: {x: 5, y: 6}});
  assert.deepEqual(kept.a, {x: 5, y: 6});
  assert.ok(kept.b.x > 5 + NODE_WIDTH);
});

test('edge endpoints use ports, or header anchors for base references', () => {
  const nodes = [node('a', [], ['out']), node('b', ['in'])];
  const byId = new Map(nodes.map((item) => [item.id, item]));
  const positions = {a: {x: 0, y: 0}, b: {x: 400, y: 0}};
  const ported = edgeEndpoints({from: {operation: 'a', port: 'out'}, to: {operation: 'b', port: 'in'}},
    byId, positions);
  assert.deepEqual(ported.from, portPosition(positions.a, 'outputs', 0));
  assert.deepEqual(ported.to, portPosition(positions.b, 'inputs', 0));
  const base = edgeEndpoints({from: {operation: 'a', port: null}, to: {operation: 'b', port: null}}, byId, positions);
  assert.deepEqual(base.from, {x: NODE_WIDTH, y: HEADER_HEIGHT / 2});
  assert.equal(edgeEndpoints({from: {operation: 'x', port: null}, to: {operation: 'b', port: null}}, byId,
    positions), null);
});

test('backward wires route below both nodes instead of behind them', () => {
  const source = {x: 400, y: 100, width: 248, height: 120};
  const target = {x: 0, y: 160, width: 248, height: 90};
  const from = {x: 648, y: 180};
  const to = {x: 0, y: 200};
  assert.equal(isBackward(from, to), true);
  const route = edgeRoute(from, to, {boxes: [source, target]});
  assert.equal(route.backward, true);
  const lane = Math.max(source.y + source.height, target.y + target.height) + 32;
  assert.equal(route.mid.y, lane);
  assert.ok(route.mid.x > target.x && route.mid.x < source.x + source.width);
  assert.match(route.d, /^M 648 180 L /);
  assert.ok(route.d.endsWith('L 0 200'));
  const second = edgeRoute(from, to, {boxes: [source, target], lane: 1});
  assert.ok(second.mid.y > route.mid.y, 'parallel backward wires use separate lanes');
});

test('forward wires keep the smooth Bézier and a self-loop is backward', () => {
  const forward = edgeRoute({x: 0, y: 0}, {x: 200, y: 100});
  assert.equal(forward.backward, false);
  assert.equal(forward.d, 'M 0 0 C 100 0, 100 100, 200 100');
  const box = {x: 0, y: 0, width: 248, height: 100};
  const self = edgeRoute({x: 248, y: 70}, {x: 0, y: 70}, {boxes: [box, box]});
  assert.equal(self.backward, true);
  assert.equal(self.mid.y, 132);
});

test('rounded paths keep straight segments and quadratic corners', () => {
  const d = roundedPath([{x: 0, y: 0}, {x: 100, y: 0}, {x: 100, y: 100}], 10);
  assert.equal(d, 'M 0 0 L 90 0 Q 100 0, 100 10 L 100 100');
});
