// Copyright (C) 2026 David L. F. Gaden.
// Display primitives only. No expression interpretation or native identities.

const point = p => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite);
const same = (a, b) => a.every((v, i) => v === b[i]);
export const MAX_OVERLAYS = 10000;

/** Pack authored world-space primitives separately from pickable native geometry. */
export function prepareOverlays(items, reference = null) {
  if (!Array.isArray(items) || items.length > MAX_OVERLAYS) throw Error(`At most ${MAX_OVERLAYS} spatial overlays can be displayed.`);
  const segments = [], points = [], ids = new Set();
  const minimum = [Infinity, Infinity, Infinity], maximum = [-Infinity, -Infinity, -Infinity];
  const include = p => p.forEach((v, i) => { minimum[i] = Math.min(minimum[i], v); maximum[i] = Math.max(maximum[i], v); });
  const line = (a, b, index) => { include(a); include(b); if (same(a, b)) points.push([a, index]); else segments.push([a, b, index]); };
  items.forEach((item, index) => {
    if (typeof item?.id !== 'string' || !item.id || ids.has(item.id)) throw Error('Spatial overlays need unique identities.');
    ids.add(item.id);
    if (item.kind === 'point' && point(item.point)) { include(item.point); points.push([item.point, index]); }
    else if (item.kind === 'line' && point(item.start) && point(item.end)) line(item.start, item.end, index);
    else if (item.kind === 'box' && point(item.min) && point(item.max)) {
      // Invalid boxes are represented in the entry list, never drawn as guesses.
      if (item.min.some((v, i) => v > item.max[i])) return;
      const corners = Array.from({length: 8}, (_, n) => [0, 1, 2].map(i => n & (1 << i) ? item.max[i] : item.min[i]));
      const seen = new Set();
      for (let n = 0; n < 8; n++) for (let i = 0; i < 3; i++) if (!(n & (1 << i))) {
        const a = corners[n], b = corners[n | (1 << i)];
        if (same(a, b)) continue;
        const key = JSON.stringify([a, b]);
        if (!seen.has(key)) { seen.add(key); line(a, b, index); }
      }
      if (!seen.size) { include(item.min); points.push([item.min, index]); }
    } else throw Error('Spatial overlays require finite XYZ points, line endpoints or box corners.');
  });
  const populated = minimum.every(Number.isFinite);
  const centre = reference?.centre || (populated ? minimum.map((v, i) => v / 2 + maximum[i] / 2) : [0, 0, 0]);
  const radius = reference?.radius ?? (populated ? Math.max(Math.hypot(...maximum.map((v, i) => v / 2 - minimum[i] / 2)), 1e-12) : 1);
  if (!centre.every(Number.isFinite) || !Number.isFinite(radius) || radius <= 0) throw Error('Spatial coordinate range is too large to display.');
  const local = p => {
    const v = p.map((x, i) => (x - centre[i]) / radius);
    if (!v.every(x => Number.isFinite(x) && Math.abs(x) < 3e38)) throw Error('Spatial coordinate range is too large to display.');
    return v;
  };
  const pack = (p, index) => [...local(p), 0, 0, 1, index, 1, 1, 1];
  const lines = new Float32Array(segments.flatMap(([a, b, i]) => [...pack(a, i), ...pack(b, i)]));
  const dots = new Float32Array(points.flatMap(([p, i]) => pack(p, i)));
  const bounds = populated ? {minimum: local(minimum), maximum: local(maximum)} : null;
  return {lines, dots, ids: [...ids], frame: {centre, radius, bounds,
    worldBounds: populated ? {minimum, maximum} : null}};
}

/** Camera fit includes overlays but native picking keeps its original frame. */
export function overlayBounds(native, overlay) {
  const a = native?.bounds, b = overlay?.frame.bounds;
  if (!a) return b;
  if (!b) return a;
  return {minimum: a.minimum.map((v, i) => Math.min(v, b.minimum[i])),
    maximum: a.maximum.map((v, i) => Math.max(v, b.maximum[i]))};
}
