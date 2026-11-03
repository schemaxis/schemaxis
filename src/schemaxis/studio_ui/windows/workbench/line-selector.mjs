// Copyright (C) 2026 David L F Gaden
// Shared world-coordinate line placement, using explicit bounds or a native snapshot.
import {h} from '../../lib/dom.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {createViewer3d} from '../../viewers/viewer3d.mjs';

export const point3 = value => Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
export const validBounds = value => Array.isArray(value) && value.length === 6 && value.every(Number.isFinite)
  && [0, 2, 4].every(i => value[i] <= value[i + 1]);
export const planeAxes = plane => ({XY: [0, 1, 2], XZ: [0, 2, 1], YZ: [1, 2, 0]})[plane];
export function pointOnPlane(bounds, plane, u, v, depth) {
  if (!validBounds(bounds) || !planeAxes(plane) || ![u, v, depth].every(Number.isFinite)) throw Error('Enter finite plane coordinates and ordered bounds.');
  const [a, b, c] = planeAxes(plane), point = [];
  point[a] = bounds[2 * a] + Math.max(0, Math.min(1, u)) * (bounds[2 * a + 1] - bounds[2 * a]);
  point[b] = bounds[2 * b] + Math.max(0, Math.min(1, v)) * (bounds[2 * b + 1] - bounds[2 * b]);
  point[c] = depth;
  return point;
}
export function observedBounds(payload) {
  return Object.entries(payload?.observations || {}).filter(([, value]) => value?.points > 0 && validBounds(value.bounds))
    .map(([id, value]) => ({id, bounds: value.bounds}));
}
export function geometryBounds(payload) {
  const bounds = [Infinity, -Infinity, Infinity, -Infinity, Infinity, -Infinity];
  function include(point) {
    if (point3(point)) point.forEach((value, i) => { bounds[2 * i] = Math.min(bounds[2 * i], value); bounds[2 * i + 1] = Math.max(bounds[2 * i + 1], value); });
  }
  for (const object of payload?.objects || []) {
    for (const face of object.faces || []) for (const triangle of face.triangles || []) triangle.forEach(i => include(face.vertices?.[i]));
    for (const edge of object.edges || []) (edge.points || []).forEach(include);
    for (const vertex of object.vertices || []) include(vertex.point);
  }
  return validBounds(bounds) ? bounds : null;
}

export async function selectLine({start, end, getContext}) {
  let bounds = null, snapshot = null, viewer = null, closed = false;
  const status = h('p', {class: 'wb-help', role: 'status'}, 'Use a native preview or enter dataset bounds. Coordinates use the dataset units.');
  const error = h('p', {class: 'operation-error', role: 'alert'});
  const points = [start, end].map((point, i) => ['X', 'Y', 'Z'].map((axis, j) => h('input', {
    class: 'input', type: 'number', step: 'any', value: point3(point) ? point[j] : '',
    'aria-label': `${i ? 'End' : 'Start'} ${axis}`, onInput: draw})));
  const readPoint = i => points[i].map(input => input.value.trim() === '' ? NaN : Number(input.value));
  const target = h('select', {class: 'input', 'aria-label': 'Place endpoint'},
    h('option', {value: '0'}, 'Place start'), h('option', {value: '1'}, 'Place end'));
  const depth = h('input', {class: 'input', type: 'number', step: 'any', 'aria-label': 'Plane coordinate', onInput: draw});
  const depthLabel = h('span', {}, 'Z coordinate');
  const plane = h('select', {class: 'input', 'aria-label': 'Selection plane', onChange: () => { centrePlane(); draw(); }},
    ['XY', 'XZ', 'YZ'].map(name => h('option', {value: name}, name)));
  const boundInputs = ['X min', 'X max', 'Y min', 'Y max', 'Z min', 'Z max'].map(name => h('input', {
    class: 'input', type: 'number', step: 'any', 'aria-label': name, onInput: () => {
      const values = boundInputs.map(input => input.value.trim() === '' ? NaN : Number(input.value));
      bounds = validBounds(values) ? values : null;
      status.textContent = 'Manually entered bounds · check against the current dataset.';
      draw();
    }}));
  const source = h('select', {class: 'input', 'aria-label': 'Bounds source', hidden: true, onChange: () => {
    const values = source.value === 'preview' ? geometryBounds(snapshot.data)
      : observedBounds(snapshot.data).find(item => `dataset:${item.id}` === source.value)?.bounds;
    setBounds(values);
  }});
  const canvas = h('canvas', {width: 640, height: 360, class: 'line-selector-plane', tabindex: 0,
    'aria-label': 'Line selection plane. Click to place the chosen endpoint, or enter XYZ coordinates.'});
  const three = h('div', {class: 'line-selector-3d', hidden: true});
  const mode = h('select', {class: 'input', 'aria-label': 'Coordinate view', onChange: async () => {
    const use3d = mode.value === '3d'; canvas.hidden = use3d; three.hidden = !use3d;
    if (use3d && snapshot?.data) {
      if (!viewer) {
        viewer = createViewer3d(three, {label: 'Preview geometry · surface picking'});
        viewer.on('pick', ref => { if (point3(ref.point)) place(ref.point); });
        await viewer.load(snapshot.data);
        if (!closed) viewer.setProjection('perspective');
      }
      if (!closed) viewer.resize();
    }
  }}, h('option', {value: '2d'}, '2D plane'), h('option', {value: '3d', disabled: true}, '3D surface picking'));
  function place(point) {
    points[Number(target.value)].forEach((input, i) => { input.value = String(Number(point[i].toPrecision(12))); });
    target.value = target.value === '0' ? '1' : '0'; draw();
  }
  function centrePlane() {
    const axis = planeAxes(plane.value)[2]; depthLabel.textContent = `${'XYZ'[axis]} coordinate`;
    if (bounds) depth.value = String(bounds[2 * axis] * 0.5 + bounds[2 * axis + 1] * 0.5);
  }
  function setBounds(values) {
    bounds = validBounds(values) ? [...values] : null;
    boundInputs.forEach((input, i) => { input.value = bounds ? String(bounds[i]) : ''; });
    centrePlane(); draw();
  }
  function plotRect() {
    if (!bounds) return null;
    const [a, b] = planeAxes(plane.value), dx = bounds[a * 2 + 1] - bounds[a * 2], dy = bounds[b * 2 + 1] - bounds[b * 2];
    const scale = Math.min(560 / (dx || 1), 280 / (dy || 1));
    const width = dx ? dx * scale : 2, height = dy ? dy * scale : 2;
    return {x: (640 - width) / 2, y: (360 - height) / 2, width, height, a, b};
  }
  function draw() {
    const g = canvas.getContext('2d'); g.clearRect(0, 0, 640, 360);
    g.fillStyle = '#152432'; g.fillRect(0, 0, 640, 360); g.font = '14px sans-serif'; g.fillStyle = '#d7e4ef';
    const rect = plotRect();
    if (!rect) { g.fillText('Load preview bounds or enter six ordered limits below.', 28, 48); return; }
    const {x, y, width, height, a, b} = rect;
    g.strokeStyle = '#8096a8'; g.strokeRect(x, y, width, height);
    g.fillText(`${'XYZ'[a]}: ${bounds[2 * a]} … ${bounds[2 * a + 1]}`, 20, 348);
    g.fillText(`${'XYZ'[b]}: ${bounds[2 * b]} … ${bounds[2 * b + 1]}   ${depthLabel.textContent}: ${depth.value}`, 20, 20);
    const project = p => [x + (p[a] - bounds[2 * a]) / (bounds[2 * a + 1] - bounds[2 * a] || 1) * width,
      y + height - (p[b] - bounds[2 * b]) / (bounds[2 * b + 1] - bounds[2 * b] || 1) * height];
    const endpoints = [readPoint(0), readPoint(1)];
    if (endpoints.every(point3)) {
      const [p, q] = endpoints.map(project); g.strokeStyle = '#60d6c2'; g.lineWidth = 2;
      g.beginPath(); g.moveTo(...p); g.lineTo(...q); g.stroke();
    }
    endpoints.forEach((p, i) => { if (point3(p)) { const q = project(p); g.fillStyle = i ? '#ffba70' : '#60d6c2';
      g.beginPath(); g.arc(...q, 6, 0, 2 * Math.PI); g.fill(); g.fillText(i ? 'End' : 'Start', q[0] + 10, q[1] - 8); } });
  }
  canvas.addEventListener('click', event => {
    const rect = plotRect(); if (!rect || !depth.value.trim() || !Number.isFinite(Number(depth.value))) return;
    const box = canvas.getBoundingClientRect(), x = (event.clientX - box.left) * 640 / box.width, y = (event.clientY - box.top) * 360 / box.height;
    if (x < rect.x || x > rect.x + rect.width || y < rect.y || y > rect.y + rect.height) return;
    place(pointOnPlane(bounds, plane.value, (x - rect.x) / rect.width, 1 - (y - rect.y) / rect.height, Number(depth.value)));
  });
  const load = h('button', {class: 'button small', type: 'button', disabled: !getContext, onClick: async () => {
    load.disabled = true;
    try {
      const value = await getContext(); if (closed) return; snapshot = value;
      const observed = observedBounds(snapshot.data), preview = geometryBounds(snapshot.data);
      source.replaceChildren(...(preview ? [h('option', {value: 'preview'}, 'All displayed geometry')] : []),
        ...observed.map(item => h('option', {value: `dataset:${item.id}`}, `Dataset: ${item.id}`)));
      source.hidden = false;
      setBounds(preview || observed[0]?.bounds);
      mode.querySelector('[value="3d"]').disabled = !snapshot.data.objects?.length;
      if (viewer) await viewer.load(snapshot.data);
      if (closed) return;
      status.textContent = `${snapshot.label}. Choose the flow dataset for its full bounds. Bounds alone do not prove a seed lies inside a fluid cell.`;
      error.textContent = bounds ? '' : 'No nonempty dataset bounds in this preview.';
    } catch (fault) { if (!closed) error.textContent = `${fault.message} Run a preview of the source first, or enter bounds manually.`; }
    finally { load.disabled = false; }
  }}, 'Load preview bounds');
  const pending = openDialog({title: 'Place line endpoints', wide: true,
    content: h('div', {class: 'line-selector'}, status, h('div', {class: 'operation-file-tools'}, load, source, mode),
      h('div', {class: 'operation-file-tools'}, target, plane, h('label', {}, depthLabel, depth)),
      h('div', {class: 'line-selector-layout'}, h('div', {}, canvas, three), h('div', {},
        points.map((inputs, i) => h('fieldset', {}, h('legend', {}, i ? 'End (Point2)' : 'Start (Point1)'),
          h('div', {class: 'line-selector-coordinates'}, inputs.map((input, j) => h('label', {}, 'XYZ'[j], input))))))),
      h('p', {class: 'wb-help'}, '2D shows the projected bounds and endpoints; click inside the box to place start then end. The third coordinate is set by the plane. 3D picks points on preview surfaces. Exact XYZ values remain editable.'),
      h('details', {}, h('summary', {}, 'Dataset bounds'), h('div', {class: 'line-selector-coordinates'},
        boundInputs.map(input => h('label', {}, input.getAttribute('aria-label'), input)))), error),
    actions: [{label: 'Cancel', run: () => null}, {label: 'Use endpoints', primary: true, run: () => {
      const start = readPoint(0), end = readPoint(1);
      if (![start, end].every(point3) || start.every((value, i) => value === end[i])) {
        error.textContent = 'Enter two different finite XYZ endpoints.'; return false;
      }
      return {start, end};
    }}]});
  draw();
  const result = await pending;
  closed = true; viewer?.destroy(); return result;
}
