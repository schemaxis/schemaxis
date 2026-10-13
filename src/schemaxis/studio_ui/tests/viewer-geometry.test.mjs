// Ported from console_ui/tests/geometry.test.mjs, plus BVH, flip and element-point tests.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  basis, dot, elementPoint, length, pickGeometry, prepareGeometry, projectPoint, rayTriangle, sameRevision,
  screenRay, trianglePoints, WALK_NEAR,
} from '../viewers/geometry.mjs';

const data = {revision: 7, objects: [{id: 'body', label: 'Body', faces: [
  {id: 'front', vertices: [[-1, -1, 1], [1, -1, 1], [0, 1, 1]], triangles: [[0, 1, 2]]},
  {id: 'back', vertices: [[-1, -1, -1], [1, -1, -1], [0, 1, -1]], triangles: [[0, 1, 2]]},
]}]};

const distance = (a, b) => length(a.map((v, i) => v - b[i]));

test('ray tests are double-sided, include boundaries and reject misses / behind the eye', () => {
  const a = [-1, -1, 0];
  const b = [1, -1, 0];
  const c = [0, 1, 0];
  assert.deepEqual(rayTriangle([0, 0, 2], [0, 0, -1], a, b, c).point, [0, 0, 0]);
  assert.deepEqual(rayTriangle([0, 0, -2], [0, 0, 1], a, b, c).point, [0, 0, 0]);
  assert.equal(rayTriangle([3, 0, 2], [0, 0, -1], a, b, c), null);
  assert.equal(rayTriangle([0, 0, 2], [0, 0, 1], a, b, c), null);
  assert.equal(rayTriangle([0, 0, 2], [1, 0, 0], a, b, c), null);
  assert.ok(rayTriangle([0, 1, 2], [0, 0, -1], a, b, c));
  assert.equal(rayTriangle([0, 0, 2], [0, 0, -1], a, a, a), null);
});

test('native identity and world coordinates survive normalisation; closest visible face wins', () => {
  const mesh = prepareGeometry(data);
  const hit = pickGeometry(mesh, [0, 0, 4], [0, 0, -1]);
  assert.equal(hit.face.id, 'front');
  assert.equal(hit.face.object, 'body');
  assert.ok(distance(hit.point, [0, 0, 1]) < 1e-12);
  const interior = pickGeometry(mesh, [0, 0, 4], [0, 0, -1], 2, 0);
  assert.equal(interior.face.id, 'back');
  assert.ok(distance(interior.point, [0, 0, -1]) < 1e-12);
  assert.equal(pickGeometry(mesh, [0, 0, 4], [0, 0, -1], 2, -1), null);
  assert.equal(mesh.packed.length, 60);
});

test('flipped section keeps the other half-space', () => {
  const mesh = prepareGeometry(data);
  const kept = pickGeometry(mesh, [0, 0, 4], [0, 0, -1], 2, 0, 0, null, -1);
  assert.equal(kept.face.id, 'front');
  const fromBelow = pickGeometry(mesh, [0, 0, -4], [0, 0, 1], 2, 0, 0, null, -1);
  assert.equal(fromBelow.face.id, 'front', 'back face is removed when the plane is flipped');
});

test('translated large-coordinate geometry remains pickable', () => {
  const shifted = structuredClone(data);
  for (const face of shifted.objects[0].faces) {
    face.vertices = face.vertices.map((p) => p.map((v) => v + 1e9));
  }
  const hit = pickGeometry(prepareGeometry(shifted), [0, 0, 4], [0, 0, -1]);
  assert.deepEqual(hit.point, [1e9, 1e9, 1e9 + 1]);
});

test('camera basis is orthonormal at orbit extremes and axis views', () => {
  for (const pitch of [-Math.PI / 2, -1.55, 0, 0.55, 1.55, Math.PI / 2]) {
    for (const yaw of [-4, 0, Math.PI]) {
      const {right, up, forward} = basis(yaw, pitch);
      for (const vector of [right, up, forward]) {
        assert.ok(Math.abs(length(vector) - 1) < 1e-12);
      }
      assert.ok(Math.abs(dot(right, up)) < 1e-12);
      assert.ok(Math.abs(dot(up, forward)) < 1e-12);
    }
  }
});

test('invalid meshes fail before upload', () => {
  const invalid = structuredClone(data);
  invalid.objects[0].faces[0].triangles[0][0] = 99;
  assert.throws(() => prepareGeometry(invalid), /indices/);
  invalid.objects[0].faces[0].triangles = [[0, 1, 2]];
  invalid.objects[0].faces[0].vertices[0][0] = NaN;
  assert.throws(() => prepareGeometry(invalid), /finite/);
  const duplicate = structuredClone(data);
  duplicate.objects.push(duplicate.objects[0]);
  assert.throws(() => prepareGeometry(duplicate), /duplicate/);
  assert.equal(prepareGeometry({revision: 0, objects: []}).triangleCount, 0);
  assert.throws(() => prepareGeometry({objects: []}), /revision/);
});

test('revisions match only when both are present', () => {
  assert.ok(sameRevision(0, 0));
  assert.ok(sameRevision(7, '7'));
  assert.equal(sameRevision(null, null), false);
  assert.equal(sameRevision(7, 8), false);
});

test('zero-triangle sketch bounds, edge upload and exact on-segment picks', () => {
  const mesh = prepareGeometry({revision: 1, objects: [{id: 'profile', faces: [],
    edges: [{id: 'Edge1', points: [[10, 20, 0], [30, 20, 0], [30, 40, 0]]}],
    vertices: [{id: 'Vertex1', point: [10, 20, 0]}]}]});
  assert.equal(mesh.triangleCount, 0);
  assert.deepEqual(mesh.centre, [20, 30, 0]);
  assert.equal(mesh.lines.length, 40);
  assert.equal(mesh.dots.length, 10);
  const y = -10 / mesh.radius;
  const hit = pickGeometry(mesh, [0, y + 0.01, 4], [0, 0, -1], -1, 1, 0.02);
  assert.equal(hit.element.id, 'Edge1');
  assert.deepEqual(hit.point, [20, 20, 0]);
  assert.equal(pickGeometry(mesh, [0, y + 0.1, 4], [0, 0, -1], -1, 1, 0.02), null);
  const vertex = pickGeometry(mesh, [-10 / mesh.radius, y, 4], [0, 0, -1], -1, 1, 0.02);
  assert.equal(vertex.element.id, 'Vertex1');
  assert.deepEqual(vertex.point, [10, 20, 0]);
});

test('clipped edges return points on the retained segment and hidden wires cannot win', () => {
  const mesh = prepareGeometry({revision: 1, objects: [{id: 'wire',
    edges: [{id: 'Edge1', points: [[-1, 0, 0], [1, 0, 0]]}]}]});
  const clipped = pickGeometry(mesh, [0.01, 0, 4], [0, 0, -1], 0, 0, 0.02);
  assert.equal(clipped.element.id, 'Edge1');
  assert.deepEqual(clipped.point, [0, 0, 0]);
  assert.equal(pickGeometry(mesh, [0.5, 0, 4], [0, 0, -1], 0, 0, 0.02), null);
  const occluded = structuredClone(data);
  occluded.objects[0].edges = [{id: 'Edge1', points: [[-0.5, 0, -0.5], [0.5, 0, -0.5]]}];
  assert.equal(pickGeometry(prepareGeometry(occluded), [0, 0, 4], [0, 0, -1], -1, 1, 0.02).element.id, 'front');
});

test('perspective projection and rays agree at known model points, including inside a solid', () => {
  const camera = {mode: 'walk', eye: [3, 0, 0], yaw: 0, pitch: 0, aspect: 2, nx: 0, ny: 0};
  assert.deepEqual(projectPoint([0, 0, 0], camera), {nx: 0, ny: 0, depth: 3, visible: true});
  const expected = Math.sqrt(3) / 6;
  const projected = projectPoint([0, 1, 1], camera);
  assert.ok(Math.abs(projected.nx - expected) < 1e-12);
  assert.ok(Math.abs(projected.ny - expected * 2) < 1e-12);
  const ray = screenRay({...camera, nx: projected.nx, ny: projected.ny});
  const t = (0 - ray.origin[0]) / ray.direction[0];
  assert.ok(length(ray.origin.map((v, i) => v + ray.direction[i] * t - [0, 1, 1][i])) < 1e-12);
  assert.equal(projectPoint([4, 0, 0], camera).visible, false);
  assert.equal(projectPoint([3 - WALK_NEAR / 2, 0, 0], camera).visible, false);
  const mesh = prepareGeometry(data);
  const inside = {...camera, eye: [0, 0, 0], yaw: 0, pitch: -Math.PI / 2, aspect: 1};
  const interiorRay = screenRay(inside);
  const hit = pickGeometry(mesh, interiorRay.origin, interiorRay.direction, -1, 1, 0, inside);
  assert.equal(hit.element.id, 'front');
  assert.ok(Math.abs(hit.point[2] - 1) < 1e-12);
  assert.equal(pickGeometry(mesh, interiorRay.origin, interiorRay.direction, 2, 0, 0, inside), null,
    'sectioned face is not picked from inside');
});

test('perspective orbit mode uses the same projection as walk mode', () => {
  const walk = {mode: 'walk', eye: [3, 0, 0], yaw: 0, pitch: 0, aspect: 1.5};
  const orbit = {...walk, mode: 'perspective'};
  assert.deepEqual(projectPoint([0.2, 0.3, -0.1], orbit), projectPoint([0.2, 0.3, -0.1], walk));
  assert.deepEqual(screenRay({...orbit, nx: 0.3, ny: -0.2}), screenRay({...walk, nx: 0.3, ny: -0.2}));
});

test('perspective wire picks interpolate native segment coordinates and reject near-clipped points', () => {
  const mesh = prepareGeometry({revision: 1, objects: [{id: 'profile',
    edges: [{id: 'Edge1', points: [[-1, -1, 0], [1, 1, 0]]}]}]});
  const camera = {mode: 'walk', eye: [3, 0, 0], yaw: 0, pitch: 0, aspect: 1, nx: 0, ny: 0, pixelTolerance: 0.02};
  const ray = screenRay(camera);
  const hit = pickGeometry(mesh, ray.origin, ray.direction, -1, 1, 0.01, camera);
  assert.equal(hit.element.id, 'Edge1');
  assert.ok(length(hit.point) < 1e-12);
  const missCamera = {...camera, ny: 0.2};
  const missRay = screenRay(missCamera);
  assert.equal(pickGeometry(mesh, missRay.origin, missRay.direction, -1, 1, 0.01, missCamera), null);
});

function sphere(segments) {
  const vertices = [];
  const triangles = [];
  for (let i = 0; i <= segments; i++) {
    const theta = (i / segments) * Math.PI;
    for (let j = 0; j <= segments; j++) {
      const phi = (j / segments) * 2 * Math.PI;
      vertices.push([Math.sin(theta) * Math.cos(phi), Math.sin(theta) * Math.sin(phi), Math.cos(theta)]);
    }
  }
  for (let i = 0; i < segments; i++) {
    for (let j = 0; j < segments; j++) {
      const a = i * (segments + 1) + j;
      const b = a + segments + 1;
      triangles.push([a, b, a + 1], [a + 1, b, b + 1]);
    }
  }
  return {revision: 'r1', objects: [{id: 'ball', faces: [{id: 'Face1', vertices, triangles}]}]};
}

test('BVH picking matches a brute-force nearest triangle on a dense sphere', () => {
  const mesh = prepareGeometry(sphere(40));
  let seed = 12345;
  const random = () => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed / 2147483648;
  };
  for (let trial = 0; trial < 200; trial++) {
    const origin = [random() * 4 - 2, random() * 4 - 2, 3];
    const direction = [0, 0, -1];
    let brute = null;
    for (let i = 0; i < mesh.triangleCount; i++) {
      const hit = rayTriangle(origin, direction, ...trianglePoints(mesh, i));
      if (hit && (!brute || hit.distance < brute.distance)) {
        brute = hit;
      }
    }
    const picked = pickGeometry(mesh, origin, direction);
    assert.equal(Boolean(picked), Boolean(brute));
    if (brute) {
      assert.ok(Math.abs(dot(picked.point, [0, 0, 1]) - (brute.point[2] * mesh.radius + mesh.centre[2])) < 1e-9);
    }
  }
});

test('element points lie on the retained element and respect the section plane', () => {
  const mesh = prepareGeometry({revision: 1, objects: [{id: 'body', faces: data.objects[0].faces,
    edges: [{id: 'Edge1', points: [[-1, 0, 0], [1, 0, 0]]}], vertices: [{id: 'Vertex1', point: [1, 1, 1]}]}]});
  const front = mesh.faces.find((face) => face.id === 'front');
  assert.deepEqual(elementPoint(mesh, front).map((v) => Math.round(v * 1e9) / 1e9), [0, -1 / 3, 1].map(
    (v) => Math.round(v * 1e9) / 1e9));
  assert.equal(elementPoint(mesh, front, 2, 0), null, 'front face removed by z ≤ 0');
  const edge = mesh.edges[0];
  const kept = elementPoint(mesh, edge, 0, 0);
  assert.ok(kept[0] < 0 && kept[0] >= -1 - 1e-12);
  const vertex = mesh.vertices[0];
  assert.equal(elementPoint(mesh, vertex, 0, 0), null);
  assert.deepEqual(elementPoint(mesh, vertex, 0, 0, -1).map((v) => Math.round(v * 1e9) / 1e9), [1, 1, 1]);
});
