// Validate a native geometry payload and pack it for WebGL and picking.
//
// Payload (from session.geometry() / live FreeCAD and Blender workers):
//   {revision, document?, objects: [{id, label?, faces?: [{id, label?, vertices: [[x,y,z]...],
//    triangles: [[i,j,k]...]}], edges?: [{id, label?, points: [[x,y,z]...]}],
//    vertices?: [{id, label?, point: [x,y,z]}]}]}
//
// Vertex layout for every buffer: position(3) normal(3) element(1) barycentric(3)
// = 10 floats. Lines and points use barycentric (1, 1, 1) as a marker.

import {MAX_SEGMENTS, MAX_TRIANGLES, MAX_VERTICES} from './geometry.mjs';

const STRIDE = 10;

const isIdentity = (value) => typeof value === 'string' && value.length > 0;
const isPoint = (p) => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite);

function validate(data) {
  if (!data || !Array.isArray(data.objects) || !['string', 'number'].includes(typeof data.revision)) {
    throw Error('Geometry requires a revision and objects array.');
  }
  const minimum = [Infinity, Infinity, Infinity];
  const maximum = [-Infinity, -Infinity, -Infinity];
  const include = (p) => {
    for (let axis = 0; axis < 3; axis++) {
      minimum[axis] = Math.min(minimum[axis], p[axis]);
      maximum[axis] = Math.max(maximum[axis], p[axis]);
    }
  };
  const faces = [];
  const edges = [];
  const vertices = [];
  const objectIds = new Set();
  let triangleCount = 0;
  let segmentCount = 0;
  for (const object of data.objects) {
    const badList = ['faces', 'edges', 'vertices'].some((key) => object?.[key] !== undefined
      && !Array.isArray(object[key]));
    if (!isIdentity(object?.id) || objectIds.has(object.id) || badList) {
      throw Error('Invalid or duplicate geometry object.');
    }
    objectIds.add(object.id);
    const ids = new Set();
    const metadata = (element, type) => ({
      object: object.id,
      objectLabel: String(object.label || object.id),
      id: element.id,
      label: String(element.label || element.id),
      type,
    });
    for (const face of object.faces || []) {
      if (!isIdentity(face.id) || ids.has(face.id) || !Array.isArray(face.vertices)
        || !Array.isArray(face.triangles)) {
        throw Error('Invalid or duplicate native face.');
      }
      ids.add(face.id);
      if (!face.vertices.every(isPoint)) {
        throw Error('Native vertices must be finite XYZ triples.');
      }
      for (const triangle of face.triangles) {
        const valid = Array.isArray(triangle) && triangle.length === 3
          && triangle.every((i) => Number.isInteger(i) && i >= 0 && i < face.vertices.length);
        if (!valid) {
          throw Error('Invalid native triangle indices.');
        }
        for (const i of triangle) {
          include(face.vertices[i]);
        }
      }
      triangleCount += face.triangles.length;
      if (triangleCount > MAX_TRIANGLES) {
        throw Error('Preview exceeds two million triangles; request coarser native tessellation.');
      }
      faces.push({...metadata(face, 'face'), vertices: face.vertices, indices: face.triangles});
    }
    for (const edge of object.edges || []) {
      if (!isIdentity(edge.id) || ids.has(edge.id) || !Array.isArray(edge.points) || edge.points.length < 2
        || !edge.points.every(isPoint)) {
        throw Error('Invalid or duplicate native edge polyline.');
      }
      ids.add(edge.id);
      edge.points.forEach(include);
      segmentCount += edge.points.length - 1;
      if (segmentCount > MAX_SEGMENTS) {
        throw Error('Preview exceeds two million edge segments; request coarser native tessellation.');
      }
      edges.push({...metadata(edge, 'edge'), worldPoints: edge.points});
    }
    for (const vertex of object.vertices || []) {
      if (!isIdentity(vertex.id) || ids.has(vertex.id) || !isPoint(vertex.point)) {
        throw Error('Invalid or duplicate native vertex.');
      }
      ids.add(vertex.id);
      include(vertex.point);
      vertices.push({...metadata(vertex, 'vertex'), worldPoint: vertex.point});
      if (vertices.length > MAX_VERTICES) {
        throw Error('Preview exceeds one million native vertices.');
      }
    }
  }
  return {faces, edges, vertices, minimum, maximum, triangleCount, segmentCount};
}

/** Validate and pack geometry. Throws Error with a user-facing message when invalid. */
export function prepareGeometry(data) {
  const {faces, edges, vertices, minimum, maximum, triangleCount, segmentCount} = validate(data);
  const populated = minimum.every(Number.isFinite);
  // Same arithmetic as the console viewer, so world points round-trip identically.
  const centre = populated ? minimum.map((value, axis) => value * 0.5 + maximum[axis] * 0.5) : [0, 0, 0];
  const radius = populated ? Math.max(Math.hypot(...maximum.map((v, i) => v - minimum[i])) / 2, 1e-12) : 1;
  if (!centre.every(Number.isFinite) || !Number.isFinite(radius)) {
    throw Error('Native coordinate range is too large.');
  }
  const inverse = 1 / radius;
  const normalise = (p) => [(p[0] - centre[0]) * inverse, (p[1] - centre[1]) * inverse, (p[2] - centre[2]) * inverse];

  const packed = new Float32Array(triangleCount * 3 * STRIDE);
  const positions = new Float64Array(triangleCount * 9);
  const triangleFace = new Int32Array(triangleCount);
  let triangle = 0;
  faces.forEach((face, index) => {
    face.index = index;
    face.triangleStart = triangle;
    face.triangleCount = face.indices.length;
    const local = face.vertices.map(normalise);
    for (const [i, j, k] of face.indices) {
      const a = local[i];
      const b = local[j];
      const c = local[k];
      const normal = triangleNormal(a, b, c);
      [a, b, c].forEach((point, corner) => {
        const base = (triangle * 3 + corner) * STRIDE;
        packed.set(point, base);
        packed.set(normal, base + 3);
        packed[base + 6] = index;
        packed[base + 7 + corner] = 1;
        positions.set(point, triangle * 9 + corner * 3);
      });
      triangleFace[triangle] = index;
      triangle++;
    }
  });

  const lines = new Float32Array(segmentCount * 2 * STRIDE);
  let lineOffset = 0;
  edges.forEach((edge, index) => {
    edge.index = faces.length + index;
    edge.points = edge.worldPoints.map(normalise);
    for (let i = 1; i < edge.points.length; i++) {
      for (const point of [edge.points[i - 1], edge.points[i]]) {
        lines.set([...point, 0, 0, 1, edge.index, 1, 1, 1], lineOffset);
        lineOffset += STRIDE;
      }
    }
  });

  const dots = new Float32Array(vertices.length * STRIDE);
  vertices.forEach((vertex, index) => {
    vertex.index = faces.length + edges.length + index;
    vertex.point = normalise(vertex.worldPoint);
    dots.set([...vertex.point, 0, 0, 1, vertex.index, 1, 1, 1], index * STRIDE);
  });

  const bounds = populated
    ? {minimum: normalise(minimum), maximum: normalise(maximum)}
    : {minimum: [-1, -1, -1], maximum: [1, 1, 1]};
  return {
    revision: data.revision,
    document: data.document,
    objects: data.objects,
    faces,
    edges,
    vertices,
    elements: [...faces, ...edges, ...vertices],
    triangleCount,
    segmentCount,
    positions,
    triangleFace,
    packed,
    lines,
    dots,
    centre,
    radius,
    bounds,
    worldBounds: populated ? {minimum, maximum} : null,
    bvh: null,
  };
}

function triangleNormal(a, b, c) {
  const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
  const n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const size = Math.hypot(...n) || 1;
  return [n[0] / size, n[1] / size, n[2] / size];
}
