// Copyright (C) 2026 David L F Gaden
// Camera state and navigation for the 3D viewer, in normalised model space
// (the model fits the unit sphere). Pure functions: each returns a new camera.
//
// camera = {yaw, pitch, target, scale, projection: 'orthographic'|'perspective',
//           navigation: 'orbit'|'walk', eye, speed}
// `scale` is the half-height of the view at the target plane.

import {add, basis, dot, mul, unit, WALK_FOV} from './geometry.mjs';

export const ISO_YAW = Math.PI / 4;
export const ISO_PITCH = Math.atan(1 / Math.SQRT2);
export const PITCH_LIMIT = 1.55;
export const MIN_SCALE = 0.002;
export const MAX_SCALE = 100;

/** Named views: the camera looks from this direction towards the target. */
export const VIEWS = {
  iso: {yaw: ISO_YAW, pitch: ISO_PITCH, label: 'Isometric'},
  '+x': {yaw: 0, pitch: 0, label: '+X'},
  '-x': {yaw: Math.PI, pitch: 0, label: '−X'},
  '+y': {yaw: Math.PI / 2, pitch: 0, label: '+Y'},
  '-y': {yaw: -Math.PI / 2, pitch: 0, label: '−Y'},
  '+z': {yaw: -Math.PI / 2, pitch: Math.PI / 2, label: '+Z (top)'},
  '-z': {yaw: -Math.PI / 2, pitch: -Math.PI / 2, label: '−Z (bottom)'},
};

export function createCamera() {
  return {
    yaw: ISO_YAW,
    pitch: ISO_PITCH,
    target: [0, 0, 0],
    scale: 1.2,
    projection: 'orthographic',
    navigation: 'orbit',
    eye: [0, 0, 3],
    speed: 1,
  };
}

const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const focalDistance = (scale) => scale / Math.tan(WALK_FOV / 2);

/** Projection mode understood by geometry.projectPoint / screenRay. */
export function projectionMode(camera) {
  if (camera.navigation === 'walk') {
    return 'walk';
  }
  return camera.projection === 'perspective' ? 'perspective' : 'orbit';
}

/** Eye position for perspective cameras (walk: free eye; orbit: on the forward axis). */
export function eyeOf(camera) {
  if (camera.navigation === 'walk') {
    return camera.eye;
  }
  return add(camera.target, mul(basis(camera.yaw, camera.pitch).forward, focalDistance(camera.scale)));
}

/** Projection parameters for projectPoint / screenRay / pickGeometry. */
export function viewParameters(camera, aspect, nx = 0, ny = 0) {
  return {
    mode: projectionMode(camera),
    yaw: camera.yaw,
    pitch: camera.pitch,
    target: camera.target,
    scale: camera.scale,
    eye: eyeOf(camera),
    aspect,
    nx,
    ny,
  };
}

/**
 * Fit the model in view, keeping the view direction. With normalised bounds
 * ({minimum, maximum}) the projected box is fitted tightly; otherwise the unit sphere.
 */
export function fitCamera(camera, aspect, bounds = null) {
  const {right, up, forward} = basis(camera.yaw, camera.pitch);
  if (!bounds) {
    const distance = 1.15 / Math.sin(Math.atan(Math.tan(WALK_FOV / 2) * Math.min(1, aspect)));
    return {...camera, target: [0, 0, 0], scale: 1.15 / Math.min(1, aspect), eye: mul(forward, distance)};
  }
  const centre = bounds.minimum.map((value, i) => (value + bounds.maximum[i]) / 2);
  let halfWidth = 0;
  let halfHeight = 0;
  let halfDepth = 0;
  for (let corner = 0; corner < 8; corner++) {
    const point = [0, 1, 2].map((i) => ((corner >> i) & 1 ? bounds.maximum[i] : bounds.minimum[i]) - centre[i]);
    halfWidth = Math.max(halfWidth, Math.abs(dot(point, right)));
    halfHeight = Math.max(halfHeight, Math.abs(dot(point, up)));
    halfDepth = Math.max(halfDepth, Math.abs(dot(point, forward)));
  }
  const margin = camera.projection === 'perspective' || camera.navigation === 'walk' ? 1.25 : 1.1;
  const scale = clamp(Math.max(halfHeight, halfWidth / aspect, 0.01) * margin, MIN_SCALE, MAX_SCALE);
  const eye = add(centre, mul(forward, focalDistance(scale) + halfDepth));
  return {...camera, target: centre, scale, eye};
}

export function orbitCamera(camera, deltaYaw, deltaPitch) {
  return {...camera, yaw: camera.yaw + deltaYaw, pitch: clamp(camera.pitch + deltaPitch, -PITCH_LIMIT, PITCH_LIMIT)};
}

/** Pan by a screen offset in CSS pixels for a viewport of the given height. */
export function panCamera(camera, dx, dy, viewportHeight) {
  const {right, up} = basis(camera.yaw, camera.pitch);
  const walk = camera.navigation === 'walk';
  const factor = (2 * (walk ? camera.speed : camera.scale)) / Math.max(1, viewportHeight);
  const offset = add(mul(right, -dx * factor), mul(up, dy * factor));
  return walk ? {...camera, eye: add(camera.eye, offset)} : {...camera, target: add(camera.target, offset)};
}

/**
 * Zoom by `factor` (< 1 zooms in) keeping the target-plane point under the
 * cursor (nx, ny in -1..1) fixed on screen. Walk mode moves the eye instead.
 */
export function zoomCamera(camera, factor, nx = 0, ny = 0, aspect = 1) {
  if (camera.navigation === 'walk') {
    const forward = basis(camera.yaw, camera.pitch).forward;
    const step = Math.log(factor) * camera.speed * 1.3;
    return {...camera, eye: add(camera.eye, mul(forward, step))};
  }
  const scale = clamp(camera.scale * factor, MIN_SCALE, MAX_SCALE);
  const {right, up} = basis(camera.yaw, camera.pitch);
  const under = add(mul(right, nx * aspect), mul(up, ny));
  return {...camera, scale, target: add(camera.target, mul(under, camera.scale - scale))};
}

/** Snap to a named view (VIEWS key), keeping target and scale. */
export function viewCamera(camera, name) {
  const view = VIEWS[name];
  if (!view) {
    throw Error(`Unknown view: ${name}`);
  }
  const next = {...camera, yaw: view.yaw, pitch: view.pitch};
  if (camera.navigation === 'walk') {
    next.eye = add(camera.target, mul(basis(view.yaw, view.pitch).forward, focalDistance(camera.scale)));
  }
  return next;
}

/** Switch orbit ↔ walk keeping the same eye position and view direction. */
export function setNavigation(camera, navigation) {
  if (navigation === camera.navigation) {
    return camera;
  }
  const forward = basis(camera.yaw, camera.pitch).forward;
  if (navigation === 'walk') {
    return {...camera, navigation, eye: add(camera.target, mul(forward, focalDistance(camera.scale)))};
  }
  return {...camera, navigation, target: add(camera.eye, mul(forward, -focalDistance(camera.scale)))};
}

/** One walk step: keys is a Set of KeyboardEvent.code values, dt in seconds. */
export function walkStep(camera, keys, dt) {
  const {right, forward} = basis(camera.yaw, camera.pitch);
  const amount = (positive, negative) => Number(keys.has(positive)) - Number(keys.has(negative));
  const movement = add(add(mul(forward, amount('KeyS', 'KeyW')), mul(right, amount('KeyD', 'KeyA'))),
    [0, 0, amount('KeyE', 'KeyQ')]);
  if (movement.every((value) => value === 0)) {
    return camera;
  }
  return {...camera, eye: add(camera.eye, mul(unit(movement), camera.speed * dt))};
}

/** Interpolate two cameras (for short view transitions); angles take the short way round. */
export function blendCameras(from, to, t) {
  const mix = (a, b) => a + (b - a) * t;
  let deltaYaw = (to.yaw - from.yaw) % (2 * Math.PI);
  if (deltaYaw > Math.PI) {
    deltaYaw -= 2 * Math.PI;
  } else if (deltaYaw < -Math.PI) {
    deltaYaw += 2 * Math.PI;
  }
  return {
    ...to,
    yaw: from.yaw + deltaYaw * t,
    pitch: mix(from.pitch, to.pitch),
    scale: Math.exp(mix(Math.log(from.scale), Math.log(to.scale))),
    target: from.target.map((value, i) => mix(value, to.target[i])),
    eye: from.eye.map((value, i) => mix(value, to.eye[i])),
  };
}
