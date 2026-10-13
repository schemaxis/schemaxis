// Pure scene helpers for the 3D viewer: picking through the camera, pick
// payloads, section-plane state and projection of world points.

import {eyeOf, viewParameters} from './camera.mjs';
import {formatNumber, parseColour} from './common.mjs';
import {add, basis, isPerspective, mul, pickGeometry, projectPoint, screenRay, unit, WALK_FAR, WALK_FOV,
  WALK_NEAR} from './geometry.mjs';

export const PICK_RADIUS_PX = 7;

/**
 * Pick at normalised device coordinates. heightPx is the viewport CSS height
 * (the pick radius is PICK_RADIUS_PX CSS pixels). Returns pickGeometry's hit or null.
 */
export function pickAt(mesh, camera, section, nx, ny, aspect, heightPx) {
  if (!mesh) {
    return null;
  }
  const parameters = viewParameters(camera, aspect, nx, ny);
  const perspective = isPerspective(parameters.mode);
  const {origin, direction} = screenRay(parameters);
  const pixel = (2 * PICK_RADIUS_PX) / Math.max(1, heightPx);
  const tolerance = pixel * (perspective ? Math.tan(WALK_FOV / 2) : camera.scale);
  const projection = perspective ? {...parameters, pixelTolerance: pixel} : null;
  return pickGeometry(mesh, origin, direction, section.axis, section.cut, tolerance, projection, section.side);
}

/** The pick payload for an element: identities come only from the loaded payload. */
export function referenceFor(mesh, element, point, source) {
  const payload = {
    type: element.type,
    object: element.object,
    subelement: element.id,
    point,
    revision: mesh.revision,
    label: element.label,
    objectLabel: element.objectLabel,
    source,
  };
  if (mesh.document !== undefined) {
    payload.document = mesh.document;
  }
  return payload;
}

export function describeElement(element) {
  return element ? `${element.objectLabel} › ${element.label} · ${element.type}` : 'No element selected';
}

/**
 * Apply a section change: {axis: -1|0|1|2|'x'|'y'|'z'|null, cut (normalised),
 * position (world), side: 1|-1, flip: boolean}. Choosing an axis centres the plane.
 */
export function nextSection(section, change, mesh) {
  const next = {...section};
  if ('axis' in change) {
    const named = {x: 0, y: 1, z: 2}[change.axis];
    next.axis = named ?? ([0, 1, 2].includes(change.axis) ? change.axis : -1);
    if (next.axis >= 0 && mesh) {
      next.cut = (mesh.bounds.minimum[next.axis] + mesh.bounds.maximum[next.axis]) / 2;
    }
  }
  if (Number.isFinite(change.cut)) {
    next.cut = change.cut;
  }
  if (Number.isFinite(change.position) && mesh && next.axis >= 0) {
    next.cut = (change.position - mesh.centre[next.axis]) / mesh.radius;
  }
  if (change.side === 1 || change.side === -1) {
    next.side = change.side;
  }
  if (typeof change.flip === 'boolean') {
    next.side = change.flip ? -1 : 1;
  }
  return next;
}

/** World coordinate of the section plane, or null. */
export function sectionPosition(mesh, section) {
  return mesh && section.axis >= 0 ? mesh.centre[section.axis] + section.cut * mesh.radius : null;
}

export function sectionLabel(mesh, section) {
  if (section.axis < 0) {
    return '';
  }
  const relation = section.side > 0 ? '≤' : '≥';
  return `${'XYZ'[section.axis]} ${relation} ${formatNumber(sectionPosition(mesh, section) ?? 0, 5)}`;
}

/** Normalised device coordinates of a world point, or null when not visible. */
export function projectWorld(mesh, camera, worldPoint, aspect) {
  const local = worldPoint.map((value, i) => (value - mesh.centre[i]) / mesh.radius);
  const projected = projectPoint(local, viewParameters(camera, aspect));
  return projected.visible ? {nx: projected.nx, ny: projected.ny} : null;
}

/** Renderer view parameters for a camera and viewport aspect ratio. */
export function drawParameters(camera, aspect) {
  const b = basis(camera.yaw, camera.pitch);
  const perspective = isPerspective(viewParameters(camera, aspect).mode);
  const extent = perspective ? Math.tan(WALK_FOV / 2) : camera.scale;
  return {
    ...b,
    target: camera.target,
    eye: eyeOf(camera),
    extent: [extent * aspect, extent],
    perspective,
    depthRange: [WALK_NEAR, WALK_FAR],
    light: unit(add(add(b.forward, mul(b.up, 0.45)), mul(b.right, 0.25))),
  };
}

/** State shown by the toolbar (see viewer3d-controls.mjs). */
export function toolbarState(camera, section, mesh, wireframe, wireframeAvailable) {
  const axis = section.axis;
  const bounds = mesh?.bounds;
  return {
    perspective: camera.projection === 'perspective',
    navigation: camera.navigation,
    speed: camera.speed,
    wireframe,
    wireframeAvailable,
    axis,
    cut: section.cut,
    side: section.side,
    sectionMin: bounds && axis >= 0 ? bounds.minimum[axis] : -1,
    sectionMax: bounds && axis >= 0 ? bounds.maximum[axis] : 1,
    sectionLabel: sectionLabel(mesh, section),
  };
}

export const PALETTE_TOKENS = ['kind-geometry', 'accent', 'warn', 'text', 'text-3', 'surface'];

/** Renderer colours (RGB 0..1) from theme tokens. Surfaces are the geometry kind colour, lifted slightly. */
export function paletteFromTokens(tokens) {
  const geometry = parseColour(tokens['kind-geometry']);
  const paper = parseColour(tokens.surface);
  return {
    surface: geometry.slice(0, 3).map((value, i) => value * 0.82 + paper[i] * 0.18),
    select: parseColour(tokens.accent).slice(0, 3),
    hover: parseColour(tokens.warn).slice(0, 3),
    line: parseColour(tokens.text).slice(0, 3),
    wire: parseColour(tokens['text-3']).slice(0, 3),
  };
}
