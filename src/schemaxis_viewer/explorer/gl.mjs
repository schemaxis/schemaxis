// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// Dependency-free WebGL renderer: textured image planes placed by their four
// corners (projective texture mapping), shaded translucent meshes with feature
// edges, a bounding box and axes, an orbit camera and plane picking.
// Geometry is stored relative to an origin so large CFD coordinates keep precision.

const MAX_TRIANGLES = 400000;

export function meshFromBytes(bytes, name) {
  const view = new DataView(bytes), out = [];
  const push = function push(points) {
    if (out.length >= MAX_TRIANGLES * 9) throw Error(`Mesh exceeds ${MAX_TRIANGLES} triangles; provide a reduced preview mesh`);
    for (const p of points) {
      if (p.length !== 3 || !p.every(Number.isFinite)) throw Error('Invalid mesh vertex');
      out.push(p[0], p[1], p[2]);
    }
  };
  if (name.toLowerCase().endsWith('.stl')) {
    const count = bytes.byteLength >= 84 ? view.getUint32(80, true) : 0;
    if (count && 84 + count * 50 === bytes.byteLength) {
      for (let i = 0; i < count; i++) {
        const base = 84 + i * 50 + 12;
        push([0, 1, 2].map(j => [0, 1, 2].map(k => view.getFloat32(base + j * 12 + k * 4, true))));
      }
    } else {
      const text = new TextDecoder().decode(bytes), triangle = [];
      for (const match of text.matchAll(/\bvertex\s+(\S+)\s+(\S+)\s+(\S+)/gi)) {
        triangle.push(match.slice(1).map(Number));
        if (triangle.length === 3) push(triangle.splice(0));
      }
    }
  } else {
    const points = [];
    for (const line of new TextDecoder().decode(bytes).split(/\r?\n/)) {
      const [tag, ...values] = line.trim().split(/\s+/);
      if (tag === 'v') points.push(values.slice(0, 3).map(Number));
      if (tag !== 'f') continue;
      const face = values.filter(value => value && !value.startsWith('#')).map(value => {
        const index = Number(value.split('/')[0]);
        const point = points[index < 0 ? points.length + index : index - 1];
        if (!point) throw Error('OBJ face references a missing vertex');
        return point;
      });
      for (let i = 1; i < face.length - 1; i++) push([face[0], face[i], face[i + 1]]);
    }
  }
  if (!out.length) throw Error('No triangles found in this mesh');
  return Float64Array.from(out);
}

function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
function normalise(a) {
  const length = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / length, a[1] / length, a[2] / length];
}

function multiply(a, b) {
  const out = new Float32Array(16);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
    out[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
  }
  return out;
}

function perspective(fov, aspect, near, far) {
  const f = 1 / Math.tan(fov / 2), range = 1 / (near - far);
  return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * range, -1, 0, 0, 2 * far * near * range, 0]);
}

function lookAt(eye, target, up) {
  const z = normalise(sub(eye, target)), x = normalise(cross(up, z)), y = cross(z, x);
  return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, eye), -dot(y, eye), -dot(z, eye), 1]);
}

export function quadWeights(c) {
  const a = sub(c[2], c[0]), b = sub(c[3], c[1]), d = sub(c[1], c[0]);
  const aa = dot(a, a), bb = dot(b, b), ab = dot(a, b), den = aa * bb - ab * ab;
  if (Math.abs(den) < aa * bb * 1e-12) return [1, 1, 1, 1];
  const t = (dot(d, a) * bb - dot(d, b) * ab) / den;
  const u = (dot(d, a) * ab - dot(d, b) * aa) / den;
  if (t <= 0 || t >= 1 || u <= 0 || u >= 1) return [1, 1, 1, 1];
  return [1 / (1 - t), 1 / (1 - u), 1 / t, 1 / u];
}

function compile(gl, vertex, fragment) {
  const program = gl.createProgram();
  for (const [type, source] of [[gl.VERTEX_SHADER, vertex], [gl.FRAGMENT_SHADER, fragment]]) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(shader));
    gl.attachShader(program, shader);
    gl.deleteShader(shader);
  }
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(program));
  return program;
}

const SOLID_VERTEX = `attribute vec3 position; attribute vec3 normal; uniform mat4 mvp; varying vec3 vNormal;
void main(){ vNormal = normal; gl_Position = mvp * vec4(position, 1.0); }`;
const SOLID_FRAGMENT = `precision mediump float; varying vec3 vNormal; uniform vec3 colour; uniform float opacity; uniform vec3 light; uniform bool lit;
void main(){ float shade = lit ? 0.42 + 0.58 * abs(dot(normalize(vNormal), light)) : 1.0; gl_FragColor = vec4(colour * shade, opacity); }`;
const TEXTURE_VERTEX = `attribute vec3 position; attribute vec3 uvq; uniform mat4 mvp; varying vec3 vUvq;
void main(){ vUvq = uvq; gl_Position = mvp * vec4(position, 1.0); }`;
const TEXTURE_FRAGMENT = `precision mediump float; varying vec3 vUvq; uniform sampler2D image; uniform float opacity; uniform bool ready;
void main(){ vec4 c = ready ? texture2D(image, vUvq.xy / vUvq.z) : vec4(0.35, 0.38, 0.45, 1.0); gl_FragColor = vec4(c.rgb, c.a * opacity); }`;

export class Renderer {
  constructor(canvas, {onPick = null, onChange = null} = {}) {
    this.canvas = canvas;
    this.onPick = onPick;
    this.onChange = onChange;
    const gl = canvas.getContext('webgl', {antialias: true, alpha: false, preserveDrawingBuffer: true});
    if (!gl) throw Error('WebGL is not available in this browser.');
    this.gl = gl;
    this.solid = compile(gl, SOLID_VERTEX, SOLID_FRAGMENT);
    this.textured = compile(gl, TEXTURE_VERTEX, TEXTURE_FRAGMENT);
    this.meshes = [];
    this.planes = [];
    this.textures = new Map();
    this.origin = null;
    this.bounds = null;
    this.up = 'z';
    this.camera = {target: [0, 0, 0], distance: 3, yaw: -0.9, pitch: 0.45};
    this.background = [0.07, 0.08, 0.1];
    this.frame = 0;
    this.installControls();
    this.observer = new ResizeObserver(() => this.invalidate());
    this.observer.observe(canvas);
  }

  installControls() {
    const canvas = this.canvas;
    canvas.addEventListener('contextmenu', event => event.preventDefault());
    canvas.addEventListener('pointerdown', event => {
      this.drag = {x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY,
        pan: event.button === 2 || event.button === 1 || event.shiftKey};
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener('pointermove', event => {
      if (!this.drag) return;
      const dx = event.clientX - this.drag.x, dy = event.clientY - this.drag.y;
      this.drag.x = event.clientX;
      this.drag.y = event.clientY;
      if (this.drag.pan) this.pan(dx, dy);
      else {
        this.camera.yaw -= dx * 0.008;
        this.camera.pitch = Math.max(-1.55, Math.min(1.55, this.camera.pitch + dy * 0.008));
      }
      this.invalidate();
    });
    canvas.addEventListener('pointerup', event => {
      const drag = this.drag;
      this.drag = null;
      if (drag && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 4 && this.onPick) {
        const rect = canvas.getBoundingClientRect();
        this.onPick(this.pick(event.clientX - rect.left, event.clientY - rect.top));
      }
    });
    canvas.addEventListener('wheel', event => {
      event.preventDefault();
      this.camera.distance *= Math.exp(event.deltaY * 0.0012);
      this.invalidate();
    }, {passive: false});
    canvas.addEventListener('dblclick', () => this.frameAll());
  }

  pan(dx, dy) {
    const {right, upward} = this.basis();
    const scale = this.camera.distance * 0.0016;
    for (let i = 0; i < 3; i++) this.camera.target[i] += (-right[i] * dx + upward[i] * dy) * scale;
  }

  setUp(axis) {
    this.up = axis;
    this.invalidate();
  }

  ensureOrigin(points) {
    if (this.origin || !points.length) return;
    const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity];
    for (const p of points) for (let i = 0; i < 3; i++) {
      low[i] = Math.min(low[i], p[i]);
      high[i] = Math.max(high[i], p[i]);
    }
    this.origin = low.map((value, i) => (value + high[i]) / 2);
  }

  local(point) {
    return [point[0] - this.origin[0], point[1] - this.origin[1], point[2] - this.origin[2]];
  }

  setMeshes(meshes) {
    const gl = this.gl;
    for (const mesh of this.meshes) {
      gl.deleteBuffer(mesh.buffer);
      gl.deleteBuffer(mesh.edgeBuffer);
    }
    this.meshes = [];
    for (const source of meshes) {
      const t = source.triangles;
      if (!this.origin) this.ensureOrigin([[t[0], t[1], t[2]], [t[3], t[4], t[5]], [t[6], t[7], t[8]]]);
      const count = t.length / 9;
      const data = new Float32Array(count * 18);
      const edges = new Map();
      const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity];
      for (let f = 0; f < count; f++) {
        const p = [0, 1, 2].map(v => this.local([t[f * 9 + v * 3], t[f * 9 + v * 3 + 1], t[f * 9 + v * 3 + 2]]));
        const n = normalise(cross(sub(p[1], p[0]), sub(p[2], p[0])));
        for (let v = 0; v < 3; v++) {
          data.set(p[v], (f * 3 + v) * 6);
          data.set(n, (f * 3 + v) * 6 + 3);
          for (let i = 0; i < 3; i++) {
            low[i] = Math.min(low[i], p[v][i]);
            high[i] = Math.max(high[i], p[v][i]);
          }
          const a = p[v], b = p[(v + 1) % 3];
          const ka = a.map(x => x.toPrecision(7)).join(), kb = b.map(x => x.toPrecision(7)).join();
          const key = ka < kb ? ka + '|' + kb : kb + '|' + ka;
          const entry = edges.get(key);
          if (entry) entry.normals.push(n);
          else edges.set(key, {a, b, normals: [n]});
        }
      }
      const lines = [];
      for (const edge of edges.values()) {
        const sharp = edge.normals.length !== 2 || Math.abs(dot(edge.normals[0], edge.normals[1])) < 0.94;
        if (sharp) lines.push(...edge.a, 0, 0, 0, ...edge.b, 0, 0, 0);
      }
      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      const edgeBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, edgeBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(lines), gl.STATIC_DRAW);
      this.meshes.push({id: source.id, buffer, count: count * 3, edgeBuffer, edgeCount: lines.length / 6,
        colour: source.colour || [0.6, 0.7, 0.85], opacity: source.opacity ?? 0.25, low, high, visible: source.visible !== false});
    }
    this.updateBounds();
    this.invalidate();
  }

  setPlanes(planes) {
    const gl = this.gl;
    for (const plane of this.planes) gl.deleteBuffer(plane.buffer);
    this.planes = [];
    if (!this.origin) this.ensureOrigin(planes.flatMap(plane => plane.corners));
    for (const source of planes) {
      const corners = source.corners.map(corner => this.local(corner));
      const w = quadWeights(source.corners);
      const uv = [[0, 0], [1, 0], [1, 1], [0, 1]];
      const data = new Float32Array(6 * 6);
      [0, 1, 2, 0, 2, 3].forEach((corner, index) => {
        data.set(corners[corner], index * 6);
        data.set([uv[corner][0] * w[corner], uv[corner][1] * w[corner], w[corner]], index * 6 + 3);
      });
      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      this.planes.push({id: source.id, url: source.url, corners, world: source.corners, buffer, highlight: !!source.highlight,
        opacity: source.opacity ?? 1});
      this.loadTexture(source.url);
    }
    this.updateBounds();
    this.invalidate();
  }

  loadTexture(url) {
    if (this.textures.has(url)) return;
    const gl = this.gl, texture = gl.createTexture();
    const entry = {texture, ready: false};
    this.textures.set(url, entry);
    const image = new Image();
    image.onload = () => {
      if (this.disposed) return;
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      entry.ready = true;
      this.invalidate();
    };
    image.src = url;
  }

  updateBounds() {
    const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity];
    const include = function include(p) {
      for (let i = 0; i < 3; i++) {
        low[i] = Math.min(low[i], p[i]);
        high[i] = Math.max(high[i], p[i]);
      }
    };
    for (const mesh of this.meshes) {
      if (!mesh.visible) continue;
      include(mesh.low);
      include(mesh.high);
    }
    for (const plane of this.planes) plane.corners.forEach(include);
    this.bounds = Number.isFinite(low[0]) ? {low, high} : null;
  }

  frameAll() {
    if (!this.bounds) return;
    const {low, high} = this.bounds;
    this.camera.target = low.map((value, i) => (value + high[i]) / 2);
    this.camera.distance = Math.max(Math.hypot(...sub(high, low)), 1e-9) * 1.7;
    this.camera.yaw = -0.9;
    this.camera.pitch = 0.45;
    this.invalidate();
  }

  basis() {
    const {yaw, pitch} = this.camera;
    const zUp = this.up === 'z';
    const offset = zUp ? [Math.cos(pitch) * Math.cos(yaw), Math.cos(pitch) * Math.sin(yaw), Math.sin(pitch)]
      : [Math.cos(pitch) * Math.sin(yaw), Math.sin(pitch), Math.cos(pitch) * Math.cos(yaw)];
    const worldUp = zUp ? [0, 0, 1] : [0, 1, 0];
    const forward = offset.map(v => -v);
    const right = normalise(cross(forward, worldUp));
    const upward = cross(right, forward);
    return {offset, worldUp, right, upward};
  }

  matrix() {
    const canvas = this.canvas;
    const {offset, worldUp} = this.basis();
    const eye = this.camera.target.map((value, i) => value + offset[i] * this.camera.distance);
    const aspect = Math.max(1, canvas.width) / Math.max(1, canvas.height);
    const size = this.bounds ? Math.hypot(...sub(this.bounds.high, this.bounds.low)) : 1;
    const near = Math.max(this.camera.distance - size * 4, this.camera.distance * 0.01, 1e-9);
    const far = this.camera.distance + size * 4;
    return {mvp: multiply(perspective(0.6, aspect, near, far), lookAt(eye, this.camera.target, worldUp)), eye};
  }

  project(world) {
    if (!this.origin) return null;
    const p = this.local(world);
    const m = this.matrix().mvp;
    const x = m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12];
    const y = m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13];
    const w = m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15];
    if (w <= 0) return null;
    const rect = this.canvas.getBoundingClientRect();
    return [(x / w + 1) / 2 * rect.width, (1 - y / w) / 2 * rect.height];
  }

  pick(px, py) {
    const rect = this.canvas.getBoundingClientRect();
    const {offset, right, upward} = this.basis();
    const eye = this.camera.target.map((value, i) => value + offset[i] * this.camera.distance);
    const forward = offset.map(v => -v);
    const tanHalf = Math.tan(0.3), aspect = rect.width / rect.height;
    const nx = (px / rect.width * 2 - 1) * tanHalf * aspect, ny = (1 - py / rect.height * 2) * tanHalf;
    const direction = normalise(forward.map((f, i) => f + right[i] * nx + upward[i] * ny));
    let best = null, nearest = Infinity;
    for (const plane of this.planes) {
      const c = plane.corners;
      for (const [a, b, d] of [[c[0], c[1], c[2]], [c[0], c[2], c[3]]]) {
        const e1 = sub(b, a), e2 = sub(d, a), p = cross(direction, e2), det = dot(e1, p);
        if (Math.abs(det) < 1e-12) continue;
        const s = sub(eye, a), u = dot(s, p) / det;
        if (u < 0 || u > 1) continue;
        const q = cross(s, e1), v = dot(direction, q) / det;
        if (v < 0 || u + v > 1) continue;
        const t = dot(e2, q) / det;
        if (t > 0 && t < nearest) {
          nearest = t;
          best = plane.id;
        }
      }
    }
    return best;
  }

  invalidate() {
    if (this.frame || this.disposed) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.draw();
      this.onChange?.();
    });
  }

  bindSolid(buffer, mvp, colour, opacity, lit) {
    const gl = this.gl, program = this.solid;
    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    const position = gl.getAttribLocation(program, 'position'), normal = gl.getAttribLocation(program, 'normal');
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 3, gl.FLOAT, false, 24, 0);
    gl.enableVertexAttribArray(normal);
    gl.vertexAttribPointer(normal, 3, gl.FLOAT, false, 24, 12);
    gl.uniformMatrix4fv(gl.getUniformLocation(program, 'mvp'), false, mvp);
    gl.uniform3fv(gl.getUniformLocation(program, 'colour'), colour);
    gl.uniform1f(gl.getUniformLocation(program, 'opacity'), opacity);
    gl.uniform3fv(gl.getUniformLocation(program, 'light'), normalise([0.3, 0.5, 0.8]));
    gl.uniform1i(gl.getUniformLocation(program, 'lit'), lit ? 1 : 0);
  }

  lines(points, mvp, colour) {
    const gl = this.gl;
    const data = new Float32Array(points.length * 6);
    points.forEach((p, i) => data.set(p, i * 6));
    if (!this.scratch) this.scratch = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.scratch);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);
    this.bindSolid(this.scratch, mvp, colour, 1, false);
    gl.drawArrays(gl.LINES, 0, points.length);
  }

  draw() {
    const gl = this.gl, canvas = this.canvas;
    const ratio = window.devicePixelRatio || 1;
    const width = Math.round(canvas.clientWidth * ratio), height = Math.round(canvas.clientHeight * ratio);
    if (!width || !height) return;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    gl.viewport(0, 0, width, height);
    gl.clearColor(...this.background, 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!this.bounds) return;
    const {mvp} = this.matrix();
    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.disable(gl.CULL_FACE);
    const {low, high} = this.bounds;
    const box = [];
    for (let i = 0; i < 8; i++) for (const axis of [0, 1, 2]) {
      if (i & (1 << axis)) continue;
      const a = [0, 1, 2].map(k => (i & (1 << k)) ? high[k] : low[k]);
      const b = [...a];
      b[axis] = high[axis];
      box.push(a, b);
    }
    this.lines(box, mvp, [0.42, 0.46, 0.55]);
    const size = Math.max(...sub(high, low)) * 0.18;
    for (const [axis, colour] of [[0, [0.9, 0.3, 0.3]], [1, [0.35, 0.8, 0.4]], [2, [0.35, 0.55, 0.95]]]) {
      const end = [...low];
      end[axis] += size;
      this.lines([low, end], mvp, colour);
    }
    const program = this.textured;
    for (const plane of this.planes) {
      const entry = this.textures.get(plane.url);
      gl.useProgram(program);
      gl.bindBuffer(gl.ARRAY_BUFFER, plane.buffer);
      const position = gl.getAttribLocation(program, 'position'), uvq = gl.getAttribLocation(program, 'uvq');
      gl.enableVertexAttribArray(position);
      gl.vertexAttribPointer(position, 3, gl.FLOAT, false, 24, 0);
      gl.enableVertexAttribArray(uvq);
      gl.vertexAttribPointer(uvq, 3, gl.FLOAT, false, 24, 12);
      gl.uniformMatrix4fv(gl.getUniformLocation(program, 'mvp'), false, mvp);
      gl.uniform1f(gl.getUniformLocation(program, 'opacity'), plane.opacity);
      gl.uniform1i(gl.getUniformLocation(program, 'ready'), entry?.ready ? 1 : 0);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, entry?.texture || null);
      gl.uniform1i(gl.getUniformLocation(program, 'image'), 0);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      const c = plane.corners;
      this.lines([c[0], c[1], c[1], c[2], c[2], c[3], c[3], c[0]], mvp, plane.highlight ? [1, 0.7, 0.2] : [0.75, 0.78, 0.85]);
    }
    for (const mesh of this.meshes) {
      if (!mesh.visible) continue;
      this.bindSolid(mesh.edgeBuffer, mvp, [0.78, 0.82, 0.9], 1, false);
      gl.drawArrays(gl.LINES, 0, mesh.edgeCount);
    }
    gl.depthMask(false);
    for (const mesh of this.meshes) {
      if (!mesh.visible) continue;
      this.bindSolid(mesh.buffer, mvp, mesh.colour, mesh.opacity, true);
      gl.drawArrays(gl.TRIANGLES, 0, mesh.count);
    }
    gl.depthMask(true);
  }

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    this.observer.disconnect();
    const gl = this.gl;
    for (const mesh of this.meshes) {
      gl.deleteBuffer(mesh.buffer);
      gl.deleteBuffer(mesh.edgeBuffer);
    }
    for (const plane of this.planes) gl.deleteBuffer(plane.buffer);
    for (const entry of this.textures.values()) gl.deleteTexture(entry.texture);
    gl.getExtension('WEBGL_lose_context')?.loseContext();
  }
}
