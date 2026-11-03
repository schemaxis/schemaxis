// Copyright (C) 2026 David L F Gaden
// Pure geometry and graph helpers for the Workflow Designer canvas.
// No DOM access: everything here is unit-tested with node --test.

export const NODE_WIDTH = 248;
export const HEADER_HEIGHT = 56;
export const PORT_ROW = 28;
export const PORT_PAD_TOP = 8;
export const PORT_PAD_BOTTOM = 10;
export const MIN_ZOOM = 0.2;
export const MAX_ZOOM = 2.5;
export const DATA_KINDS = ['geometry', 'image', 'video', 'table', 'series', 'text', 'number', 'vector', 'audio',
  'archive'];

const COLUMN_GAP = 120;
const ROW_GAP = 48;
const ORIGIN = {x: 80, y: 80};

/** Number of port rows a node shows; an empty node still keeps one hint row. */
export function portRows(node) {
  const ports = node.ports || {};
  const inputs = (ports.inputs || []).length;
  const outputs = (ports.outputs || []).length;
  return Math.max(1, inputs, outputs);
}

export function nodeHeight(node) {
  return HEADER_HEIGHT + PORT_PAD_TOP + portRows(node) * PORT_ROW + PORT_PAD_BOTTOM;
}

/** Centre of a port dot in world coordinates. side is 'inputs' or 'outputs'. */
export function portPosition(position, side, index) {
  return {
    x: side === 'inputs' ? position.x : position.x + NODE_WIDTH,
    y: position.y + HEADER_HEIGHT + PORT_PAD_TOP + index * PORT_ROW + PORT_ROW / 2,
  };
}

/** Anchor for port-less (authored base) references: the middle of the header edge. */
export function nodeAnchor(position, side) {
  return {
    x: side === 'inputs' ? position.x : position.x + NODE_WIDTH,
    y: position.y + HEADER_HEIGHT / 2,
  };
}

/** Horizontal control offset; wires that run backwards bow out further. */
export function controlOffset(from, to) {
  const dx = to.x - from.x;
  if (dx >= 0) {
    return Math.max(40, dx * 0.5);
  }
  return Math.max(80, Math.min(240, -dx * 0.5 + Math.abs(to.y - from.y) * 0.25));
}

/** Control points of the smooth cubic Bézier from an output port to an input port. */
export function bezierPoints(from, to) {
  const offset = controlOffset(from, to);
  return [from, {x: from.x + offset, y: from.y}, {x: to.x - offset, y: to.y}, to];
}

function round(value) {
  return Math.round(value * 100) / 100;
}

/** SVG path data for the wire. */
export function bezierPath(from, to) {
  const [a, b, c, d] = bezierPoints(from, to);
  return `M ${round(a.x)} ${round(a.y)} C ${round(b.x)} ${round(b.y)}, ${round(c.x)} ${round(c.y)}, `
    + `${round(d.x)} ${round(d.y)}`;
}

/** Point on a cubic Bézier at parameter t. */
export function bezierAt(points, t) {
  const [a, b, c, d] = points;
  const u = 1 - t;
  const w0 = u * u * u;
  const w1 = 3 * u * u * t;
  const w2 = 3 * u * t * t;
  const w3 = t * t * t;
  return {
    x: w0 * a.x + w1 * b.x + w2 * c.x + w3 * d.x,
    y: w0 * a.y + w1 * b.y + w2 * c.y + w3 * d.y,
  };
}

const LEAD = 28;
const CLEARANCE = 32;
const LANE_GAP = 14;
const CORNER = 12;

/** True when a wire cannot run left to right between its ports without crossing its nodes. */
export function isBackward(from, to) {
  return to.x - from.x < 2 * LEAD;
}

/** SVG path through orthogonal points with rounded corners. */
export function roundedPath(points, radius = CORNER) {
  let d = `M ${round(points[0].x)} ${round(points[0].y)}`;
  for (let index = 1; index < points.length - 1; index += 1) {
    const previous = points[index - 1];
    const corner = points[index];
    const next = points[index + 1];
    const before = Math.hypot(corner.x - previous.x, corner.y - previous.y);
    const after = Math.hypot(next.x - corner.x, next.y - corner.y);
    const r = Math.min(radius, before / 2, after / 2);
    const start = {
      x: corner.x - ((corner.x - previous.x) / (before || 1)) * r,
      y: corner.y - ((corner.y - previous.y) / (before || 1)) * r,
    };
    const end = {
      x: corner.x + ((next.x - corner.x) / (after || 1)) * r,
      y: corner.y + ((next.y - corner.y) / (after || 1)) * r,
    };
    d += ` L ${round(start.x)} ${round(start.y)} Q ${round(corner.x)} ${round(corner.y)}, `
      + `${round(end.x)} ${round(end.y)}`;
  }
  const last = points[points.length - 1];
  return `${d} L ${round(last.x)} ${round(last.y)}`;
}

/**
 * Route a wire. Forward wires are smooth Béziers. Backward wires (feedback, or a
 * target placed left of its source) leave the output to the right, run in a lane
 * below both node boxes, and enter the input from the left, so they never pass
 * behind a node. `boxes` are {x, y, width, height}; `lane` separates parallel
 * backward wires. Returns {d, mid, backward}.
 */
export function edgeRoute(from, to, {boxes = [], lane = 0} = {}) {
  if (!isBackward(from, to)) {
    const points = bezierPoints(from, to);
    return {d: bezierPath(from, to), mid: bezierAt(points, 0.5), backward: false};
  }
  const lowest = boxes.length
    ? Math.max(...boxes.map((box) => box.y + box.height))
    : Math.max(from.y, to.y);
  const bottom = lowest + CLEARANCE + lane * LANE_GAP;
  const out = from.x + LEAD + lane * LANE_GAP / 2;
  const back = to.x - LEAD - lane * LANE_GAP / 2;
  const points = [from, {x: out, y: from.y}, {x: out, y: bottom}, {x: back, y: bottom}, {x: back, y: to.y}, to];
  return {d: roundedPath(points), mid: {x: (out + back) / 2, y: bottom}, backward: true};
}

/** Arrowhead triangle pointing right with its tip at the input port. */
export function arrowPath(tip, size = 7) {
  const back = tip.x - size * 1.4;
  return `M ${round(tip.x)} ${round(tip.y)} L ${round(back)} ${round(tip.y - size * 0.7)} `
    + `L ${round(back)} ${round(tip.y + size * 0.7)} Z`;
}

export function clampZoom(zoom) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

export function screenToWorld(viewport, point) {
  return {x: (point.x - viewport.x) / viewport.zoom, y: (point.y - viewport.y) / viewport.zoom};
}

export function worldToScreen(viewport, point) {
  return {x: point.x * viewport.zoom + viewport.x, y: point.y * viewport.zoom + viewport.y};
}

/** Zoom by factor keeping the world point under the cursor fixed (cursor in viewport pixels). */
export function zoomAt(viewport, cursor, factor) {
  const zoom = clampZoom(viewport.zoom * factor);
  const ratio = zoom / viewport.zoom;
  return {
    x: cursor.x - (cursor.x - viewport.x) * ratio,
    y: cursor.y - (cursor.y - viewport.y) * ratio,
    zoom,
  };
}

/** Wheel delta to a zoom factor; smooth for trackpads, stepped for wheels. */
export function wheelFactor(deltaY, deltaMode = 0) {
  const pixels = deltaMode === 1 ? deltaY * 16 : deltaMode === 2 ? deltaY * 400 : deltaY;
  return Math.exp(-Math.max(-200, Math.min(200, pixels)) * 0.0015);
}

/** Bounding box of positioned nodes, or null when there are none. */
export function nodesBounds(nodes, positions) {
  let box = null;
  for (const node of nodes) {
    const position = positions[node.id];
    if (!position) {
      continue;
    }
    const right = position.x + NODE_WIDTH;
    const bottom = position.y + nodeHeight(node);
    if (!box) {
      box = {x: position.x, y: position.y, right, bottom};
    } else {
      box = {x: Math.min(box.x, position.x), y: Math.min(box.y, position.y),
        right: Math.max(box.right, right), bottom: Math.max(box.bottom, bottom)};
    }
  }
  return box && {x: box.x, y: box.y, width: box.right - box.x, height: box.bottom - box.y};
}

/** Viewport that shows bounds inside a size with padding, never zooming in beyond maxZoom. */
export function fitViewport(bounds, size, {padding = 64, maxZoom = 1} = {}) {
  if (!bounds || size.width <= 0 || size.height <= 0) {
    return {x: 0, y: 0, zoom: 1};
  }
  const width = Math.max(1, size.width - padding * 2);
  const height = Math.max(1, size.height - padding * 2);
  const zoom = clampZoom(Math.min(maxZoom, width / Math.max(1, bounds.width), height / Math.max(1, bounds.height)));
  return {
    x: size.width / 2 - (bounds.x + bounds.width / 2) * zoom,
    y: size.height / 2 - (bounds.y + bounds.height / 2) * zoom,
    zoom,
  };
}

/** Normalised rectangle from two corner points. */
export function rectFrom(a, b) {
  return {x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(a.x - b.x), height: Math.abs(a.y - b.y)};
}

export function rectsIntersect(a, b) {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

/** Operation IDs whose cards intersect a world-space marquee rectangle. */
export function nodesInRect(nodes, positions, rect) {
  return nodes.filter((node) => {
    const position = positions[node.id];
    if (!position) {
      return false;
    }
    return rectsIntersect(rect, {x: position.x, y: position.y, width: NODE_WIDTH, height: nodeHeight(node)});
  }).map((node) => node.id);
}

/** Does the visible viewport (in world units) contain all content? */
export function contentExceeds(bounds, viewport, size) {
  if (!bounds) {
    return false;
  }
  const view = {x: -viewport.x / viewport.zoom, y: -viewport.y / viewport.zoom,
    width: size.width / viewport.zoom, height: size.height / viewport.zoom};
  return bounds.x < view.x || bounds.y < view.y || bounds.x + bounds.width > view.x + view.width
    || bounds.y + bounds.height > view.y + view.height;
}

/** Map world coordinates to a minimap box that shows both content and the current view. */
export function minimapTransform(bounds, viewport, size, mini, padding = 8) {
  const view = {x: -viewport.x / viewport.zoom, y: -viewport.y / viewport.zoom,
    width: size.width / viewport.zoom, height: size.height / viewport.zoom};
  const box = bounds ? {
    x: Math.min(bounds.x, view.x), y: Math.min(bounds.y, view.y),
    right: Math.max(bounds.x + bounds.width, view.x + view.width),
    bottom: Math.max(bounds.y + bounds.height, view.y + view.height),
  } : {x: view.x, y: view.y, right: view.x + view.width, bottom: view.y + view.height};
  const width = box.right - box.x;
  const height = box.bottom - box.y;
  const scale = Math.min((mini.width - padding * 2) / width, (mini.height - padding * 2) / height);
  const offsetX = (mini.width - width * scale) / 2 - box.x * scale;
  const offsetY = (mini.height - height * scale) / 2 - box.y * scale;
  return {
    scale,
    toMini: (point) => ({x: point.x * scale + offsetX, y: point.y * scale + offsetY}),
    toWorld: (point) => ({x: (point.x - offsetX) / scale, y: (point.y - offsetY) / scale}),
    view,
  };
}

/** Data kind of a port, or null when undeclared. */
export function dataKind(port) {
  const kind = port && port.data && port.data.kind;
  return DATA_KINDS.includes(kind) ? kind : null;
}

/** CSS colour expression for a data kind. */
export function kindColour(kind) {
  return `var(--kind-${DATA_KINDS.includes(kind) ? kind : 'unknown'})`;
}

/**
 * Can an output port feed an input port?
 * Returns {ok, reason}. The port kind (value/artifact) must match, the input must be free,
 * while descriptive data kinds are advisory, matching the backend compatibility contract.
 */
export function compatibility(output, input) {
  if (!output || !input) {
    return {ok: false, reason: 'missing'};
  }
  if ((input.connections || []).length) {
    return {ok: false, reason: 'occupied'};
  }
  if (output.kind !== input.kind) {
    return {ok: false, reason: 'port-kind'};
  }
  const source = dataKind(output);
  const target = dataKind(input);
  if (source && target && source !== target) {
    return {ok: true, reason: 'data-kind'};
  }
  return {ok: true, reason: source && target ? 'match' : 'unknown'};
}

/** A unique identifier from a base, sanitised to the backend name rule. */
export function uniqueId(base, existing) {
  let stem = String(base || 'c').replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^[^A-Za-z]+/, '');
  if (!stem) {
    stem = 'c';
  }
  stem = stem.slice(0, 48);
  const taken = existing instanceof Set ? existing : new Set(existing);
  if (!taken.has(stem)) {
    return stem;
  }
  let number = 2;
  while (taken.has(`${stem}-${number}`)) {
    number += 1;
  }
  return `${stem}-${number}`;
}

/**
 * Positions for nodes lacking a saved layout: layered columns by dependency depth
 * (cycles are broken by declared order), placed to the right of positioned content.
 */
export function autoLayout(nodes, edges, saved = {}) {
  const result = {};
  const missing = nodes.filter((node) => !saved[node.id]);
  for (const node of nodes) {
    if (saved[node.id]) {
      result[node.id] = {x: saved[node.id].x, y: saved[node.id].y};
    }
  }
  if (!missing.length) {
    return result;
  }
  const order = new Map(nodes.map((node, index) => [node.id, index]));
  const depth = new Map(nodes.map((node) => [node.id, 0]));
  const forward = edges.filter((edge) => order.has(edge.source) && order.has(edge.target)
    && order.get(edge.source) < order.get(edge.target));
  for (const node of nodes) {
    for (const edge of forward) {
      if (edge.source === node.id) {
        depth.set(edge.target, Math.max(depth.get(edge.target), depth.get(node.id) + 1));
      }
    }
  }
  const placed = nodesBounds(nodes.filter((node) => saved[node.id]), saved);
  const startX = placed ? placed.x + placed.width + COLUMN_GAP : ORIGIN.x;
  const startY = placed ? placed.y : ORIGIN.y;
  const columns = new Map();
  for (const node of missing) {
    const column = depth.get(node.id);
    const y = columns.has(column) ? columns.get(column) : startY;
    result[node.id] = {x: startX + column * (NODE_WIDTH + COLUMN_GAP), y};
    columns.set(column, y + nodeHeight(node) + ROW_GAP);
  }
  return result;
}

/** Index of a port within its side, or -1. */
export function portIndex(node, side, name) {
  const list = (node.ports && node.ports[side]) || [];
  return list.findIndex((port) => port.name === name);
}

/** World endpoints of an edge: port positions when ports are named, header anchors otherwise. */
export function edgeEndpoints(edge, byId, positions) {
  const source = byId.get(edge.from.operation);
  const target = byId.get(edge.to.operation);
  const from = positions[edge.from.operation];
  const to = positions[edge.to.operation];
  if (!source || !target || !from || !to) {
    return null;
  }
  const out = edge.from.port === null ? -1 : portIndex(source, 'outputs', edge.from.port);
  const inp = edge.to.port === null ? -1 : portIndex(target, 'inputs', edge.to.port);
  return {
    from: out >= 0 ? portPosition(from, 'outputs', out) : nodeAnchor(from, 'outputs'),
    to: inp >= 0 ? portPosition(to, 'inputs', inp) : nodeAnchor(to, 'inputs'),
  };
}
