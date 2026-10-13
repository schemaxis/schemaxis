// Geometry math for the 3D viewer (ported from the console viewer).
// Geometry stays in native world coordinates at the API boundary. Rendering and
// ray tests use a centred unit sphere to preserve floating-point precision.

import {buildBvh, traverseBvh} from './bvh.mjs';

export const add = (a, b) => a.map((value, i) => value + b[i]);
export const sub = (a, b) => a.map((value, i) => value - b[i]);
export const mul = (a, scalar) => a.map((value) => value * scalar);
export const dot = (a, b) => a.reduce((sum, value, i) => sum + value * b[i], 0);
export const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
export const length = (a) => Math.hypot(...a);
export const unit = (a) => mul(a, 1 / (length(a) || 1));

export const WALK_FOV = Math.PI / 3;
export const WALK_NEAR = 0.001;
export const WALK_FAR = 10000;
export const MAX_TRIANGLES = 2_000_000;
export const MAX_SEGMENTS = 2_000_000;
export const MAX_VERTICES = 1_000_000;
const EPSILON = 1e-9;

/** Revisions match only when both are present and equal as strings. */
export function sameRevision(a, b) {
  return a !== undefined && a !== null && b !== undefined && b !== null && String(a) === String(b);
}

/** Camera basis. `forward` points from the target towards the eye; the view looks along -forward. */
export function basis(yaw, pitch) {
  const forward = [Math.cos(pitch) * Math.cos(yaw), Math.cos(pitch) * Math.sin(yaw), Math.sin(pitch)];
  const right = [-Math.sin(yaw), Math.cos(yaw), 0];
  return {forward, right, up: cross(forward, right)};
}

/** Perspective cameras: walk mode, or orbit with a perspective projection. */
export function isPerspective(mode) {
  return mode === 'walk' || mode === 'perspective';
}

/** Ray through normalised device coordinates (nx, ny in -1..1). */
export function screenRay({nx, ny, aspect, scale = 1.15, yaw, pitch, mode = 'orbit', eye = [0, 0, 3],
  target = [0, 0, 0], fov = WALK_FOV}) {
  const {right, up, forward} = basis(yaw, pitch);
  if (isPerspective(mode)) {
    const tangent = Math.tan(fov / 2);
    const across = add(mul(right, nx * tangent * aspect), mul(up, ny * tangent));
    const direction = unit(add(mul(forward, -1), across));
    // Start at the near plane so invisible geometry immediately at the eye
    // cannot intercept a pick. This also permits picking from inside a solid.
    const origin = add(eye, mul(direction, WALK_NEAR / -dot(direction, forward)));
    return {origin, direction};
  }
  const offset = add(mul(right, nx * scale * aspect), mul(up, ny * scale));
  return {origin: add(target, add(offset, mul(forward, 4))), direction: mul(forward, -1)};
}

/** Project a normalised model point to device coordinates; depth is along the view direction. */
export function projectPoint(point, {aspect, scale = 1.15, yaw, pitch, mode = 'orbit', eye = [0, 0, 3],
  target = [0, 0, 0], fov = WALK_FOV}) {
  const {right, up, forward} = basis(yaw, pitch);
  const perspective = isPerspective(mode);
  const q = sub(point, perspective ? eye : target);
  const depth = -dot(q, forward);
  if (perspective) {
    const tangent = Math.tan(fov / 2);
    return {
      nx: dot(q, right) / (depth * tangent * aspect),
      ny: dot(q, up) / (depth * tangent),
      depth,
      visible: depth >= WALK_NEAR && depth <= WALK_FAR,
    };
  }
  return {nx: dot(q, right) / (scale * aspect), ny: dot(q, up) / scale, depth, visible: Math.abs(depth) <= 8};
}

/** Möller–Trumbore, double-sided, boundaries included. Returns {distance, point} or null. */
export function rayTriangle(origin, direction, a, b, c) {
  const e1 = sub(b, a);
  const e2 = sub(c, a);
  const p = cross(direction, e2);
  const determinant = dot(e1, p);
  if (Math.abs(determinant) < 1e-13) {
    return null;
  }
  const inverse = 1 / determinant;
  const t = sub(origin, a);
  const u = dot(t, p) * inverse;
  if (u < -EPSILON || u > 1 + EPSILON) {
    return null;
  }
  const q = cross(t, e1);
  const v = dot(direction, q) * inverse;
  if (v < -EPSILON || u + v > 1 + EPSILON) {
    return null;
  }
  const distance = dot(e2, q) * inverse;
  return distance >= 0 ? {distance, point: add(origin, mul(direction, distance))} : null;
}

/** True when a normalised point is removed by the section plane (side 1 keeps ≤ cut, -1 keeps ≥ cut). */
export function isClipped(point, axis, cut, side = 1) {
  return axis >= 0 && side * (point[axis] - cut) > EPSILON;
}

/** Clip segment a-b to the kept half-space; returns [a, b] or null. */
export function clipSegment(a, b, axis, cut, side = 1) {
  if (axis < 0) {
    return [a, b];
  }
  const keepA = !isClipped(a, axis, cut, side);
  const keepB = !isClipped(b, axis, cut, side);
  if (!keepA && !keepB) {
    return null;
  }
  if (keepA === keepB) {
    return [a, b];
  }
  const t = (cut - a[axis]) / (b[axis] - a[axis]);
  const intersection = add(a, mul(sub(b, a), t));
  return keepA ? [a, intersection] : [intersection, b];
}

/** Clip a convex polygon to the kept half-space (Sutherland–Hodgman, one plane). */
export function clipPolygon(points, axis, cut, side = 1) {
  if (axis < 0) {
    return points;
  }
  const result = [];
  for (let i = 0; i < points.length; i++) {
    const a = points[i];
    const b = points[(i + 1) % points.length];
    const keepA = !isClipped(a, axis, cut, side);
    const keepB = !isClipped(b, axis, cut, side);
    if (keepA) {
      result.push(a);
    }
    if (keepA !== keepB) {
      const t = (cut - a[axis]) / (b[axis] - a[axis]);
      result.push(add(a, mul(sub(b, a), t)));
    }
  }
  return result;
}

export {prepareGeometry} from './geometry-prepare.mjs';

/** Points of triangle i of a prepared mesh (normalised coordinates). */
export function trianglePoints(mesh, i) {
  const p = mesh.positions;
  const base = i * 9;
  return [[p[base], p[base + 1], p[base + 2]], [p[base + 3], p[base + 4], p[base + 5]],
    [p[base + 6], p[base + 7], p[base + 8]]];
}

/** Lazily build the triangle BVH used by pickGeometry. */
export function ensureBvh(mesh) {
  if (!mesh.bvh) {
    mesh.bvh = buildBvh(mesh.positions, mesh.triangleCount);
  }
  return mesh.bvh;
}

function nearestFace(mesh, origin, direction, axis, cut, side, projection) {
  let nearest = null;
  traverseBvh(ensureBvh(mesh), origin, direction, (index) => {
    const hit = rayTriangle(origin, direction, ...trianglePoints(mesh, index));
    if (hit && (!projection || projectPoint(hit.point, projection).visible)
      && !isClipped(hit.point, axis, cut, side) && (!nearest || hit.distance < nearest.distance)) {
      const face = mesh.faces[mesh.triangleFace[index]];
      nearest = {...hit, face, element: face, localPoint: hit.point};
    }
    return nearest ? nearest.distance : Infinity;
  });
  if (nearest) {
    nearest.point = toWorld(mesh, nearest.localPoint);
  }
  return nearest;
}

/** Parameter along segment a-b closest to the pick ray (orthographic) or pick pixel (perspective). */
function closestOnSegment(a, b, origin, direction, projection) {
  if (projection) {
    const cameraForward = basis(projection.yaw, projection.pitch).forward;
    let da = -dot(sub(a, projection.eye), cameraForward);
    let db = -dot(sub(b, projection.eye), cameraForward);
    if ((da < WALK_NEAR && db < WALK_NEAR) || (da > WALK_FAR && db > WALK_FAR)) {
      return null;
    }
    // Clip to the eye's depth interval before dividing by w, then interpolate
    // with reciprocal depth for an exact position on the native segment.
    for (const bound of [WALK_NEAR, WALK_FAR]) {
      const outside = (depth) => (bound === WALK_NEAR ? depth < bound : depth > bound);
      if (outside(da) !== outside(db)) {
        const u = (bound - da) / (db - da);
        const p = add(a, mul(sub(b, a), u));
        if (outside(da)) {
          a = p;
          da = bound;
        } else {
          b = p;
          db = bound;
        }
      }
    }
    const pa = projectPoint(a, projection);
    const pb = projectPoint(b, projection);
    const dx = (pb.nx - pa.nx) * projection.aspect;
    const dy = pb.ny - pa.ny;
    const denominator = dx * dx + dy * dy;
    const s = denominator > 1e-20
      ? clamp01(((projection.nx - pa.nx) * projection.aspect * dx + (projection.ny - pa.ny) * dy) / denominator)
      : (da < db ? 0 : 1);
    const t = (s / db) / ((1 - s) / da + s / db);
    return add(a, mul(sub(b, a), t));
  }
  const delta = sub(b, a);
  const projected = sub(delta, mul(direction, dot(delta, direction)));
  const offset = sub(a, origin);
  const denominator = dot(projected, projected);
  const t = denominator > 1e-20
    ? clamp01(-dot(offset, projected) / denominator)
    : (dot(sub(a, origin), direction) < dot(sub(b, origin), direction) ? 0 : 1);
  return add(a, mul(sub(b, a), t));
}

const clamp01 = (value) => Math.max(0, Math.min(1, value));
const toWorld = (mesh, point) => add(mesh.centre, mul(point, mesh.radius));

function better(hit, current) {
  return !current || hit.separation < current.separation - EPSILON
    || (Math.abs(hit.separation - current.separation) < EPSILON && hit.distance < current.distance);
}

/**
 * Pick the nearest native element along a ray (normalised coordinates).
 * Vertices win over edges, edges over faces, within the pick tolerance and in
 * front of the nearest face. Returned points are world coordinates on the
 * actual native tessellation — a pixel-radius hit never invents a point.
 * axis/cut/side describe the section plane; projection enables perspective
 * pixel tolerance ({...camera, nx, ny, aspect, pixelTolerance}).
 */
export function pickGeometry(mesh, origin, direction, axis = -1, cut = 1, tolerance = 0, projection = null,
  side = 1) {
  const nearest = nearestFace(mesh, origin, direction, axis, cut, side, projection);
  const faceDepth = nearest?.distance ?? Infinity;
  const candidate = (point, element) => {
    const delta = sub(point, origin);
    const distance = dot(delta, direction);
    let separation = length(sub(delta, mul(direction, distance)));
    let allowed = tolerance;
    if (projection) {
      const projected = projectPoint(point, projection);
      if (!projected.visible) {
        return null;
      }
      separation = Math.hypot((projected.nx - projection.nx) * projection.aspect, projected.ny - projection.ny);
      allowed = projection.pixelTolerance;
    }
    const depthSlack = 2 * (projection ? tolerance * Math.max(1, distance) : tolerance);
    if (distance < 0 || distance > faceDepth + depthSlack || separation > allowed
      || isClipped(point, axis, cut, side)) {
      return null;
    }
    return {distance, separation, element, point: toWorld(mesh, point)};
  };

  let wire = null;
  for (const edge of mesh.edges) {
    for (let i = 1; i < edge.points.length; i++) {
      const segment = clipSegment(edge.points[i - 1], edge.points[i], axis, cut, side);
      if (!segment) {
        continue;
      }
      const point = closestOnSegment(segment[0], segment[1], origin, direction, projection);
      const hit = point && candidate(point, edge);
      if (hit && better(hit, wire)) {
        wire = hit;
      }
    }
  }
  let vertexHit = null;
  for (const vertex of mesh.vertices) {
    const hit = candidate(vertex.point, vertex);
    if (hit && better(hit, vertexHit)) {
      vertexHit = hit;
    }
  }
  return vertexHit || wire || nearest;
}

/**
 * A world point genuinely on an element's retained (unclipped) region, for
 * keyboard selection: a triangle centroid (never a bounding-box centre, which
 * can lie outside a concave face), a segment midpoint, or the vertex itself.
 * Returns null when the element is fully removed by the section plane.
 */
export function elementPoint(mesh, element, axis = -1, cut = 1, side = 1) {
  let points = null;
  if (element.type === 'face') {
    for (let i = 0; i < element.triangleCount && !points; i++) {
      const polygon = clipPolygon(trianglePoints(mesh, element.triangleStart + i), axis, cut, side);
      points = polygon.length >= 3 ? polygon : null;
    }
  } else if (element.type === 'vertex') {
    points = isClipped(element.point, axis, cut, side) ? null : [element.point];
  } else {
    for (let i = 1; i < element.points.length && !points; i++) {
      points = clipSegment(element.points[i - 1], element.points[i], axis, cut, side);
    }
  }
  if (!points) {
    return null;
  }
  const local = mul(points.reduce((sum, p) => add(sum, p), [0, 0, 0]), 1 / points.length);
  return toWorld(mesh, local);
}
