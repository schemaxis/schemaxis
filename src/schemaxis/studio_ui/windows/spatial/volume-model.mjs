// Copyright (C) 2026 David L. F. Gaden.
// Generate declared expressions from controls. Evaluation belongs to the host.
import {atPointer} from '../../editor/fill-data.mjs';
import {entries, ownerAt} from '../variables/model.mjs';
import {literalSpatial, numericLiteral} from './model.mjs';

export const STEPS = [
  {id: 'inflate', group: 'Size', title: 'Inflate %', help: '10% makes each dimension 10% longer: 5% at each end. Negative shrinks; −100% makes a flat box.', labels: ['Change X (%)', 'Change Y (%)', 'Change Z (%)'], values: [10,10,10]},
  {id: 'inflateAbs', group: 'Size', title: 'Inflate by distance', help: 'Add to the total size, in model units. 0.2 adds 0.1 at each face. Negative shrinks.', labels: ['Add to size X', 'Add to size Y', 'Add to size Z'], values: [0,0,0]},
  {id: 'resize', group: 'Size', title: 'Resize', help: 'Set the new total size in model units. The centre stays where it is. Zero gives a flat box.', labels: ['New size X', 'New size Y', 'New size Z'], values: [1,1,1]},
  {id: 'translate', group: 'Position', title: 'Translate', help: 'Move the whole box by these distances in model units. Its size stays the same.', labels: ['Move by X', 'Move by Y', 'Move by Z'], values: [0,0,0]},
  {id: 'pushAbs', group: 'Faces', title: 'Push face', help: 'Positive moves this face outward; negative moves it inward. Other faces stay in place.', labels: ['Distance'], values: [0], face: 'x+'},
  {id: 'setFace', group: 'Faces', title: 'Set face', help: 'Place this face at an exact coordinate in model units.', labels: ['Coordinate'], values: [0], face: 'x+'},
  {id: 'union', group: 'Combine', title: 'Union', help: 'The smallest axis-aligned box enclosing both volumes. This combines bounds, not the underlying geometry.'},
  {id: 'intersect', group: 'Combine', title: 'Intersect', help: 'Keep only the overlap. Boxes that touch give a flat box; boxes that do not overlap give an empty result.'},
];
export const FACES = [['x-', 'Min X'], ['x+', 'Max X'], ['y-', 'Min Y'], ['y+', 'Max Y'], ['z-', 'Min Z'], ['z+', 'Max Z']];
export const coordinateSource = () => ({kind: 'coordinates', layout: 'corners', a: ['0','0','0'], b: ['1','1','1']});
export function quotedName(name) {
  // The expression grammar uses backticks without escape sequences.
  if (typeof name !== 'string' || !name || /[`\x00-\x1f\x7f]/.test(name)) throw Error('This name cannot be used in a spatial expression.');
  return '`' + name + '`';
}
const vector = values => `vector(${values.join(', ')})`;
const numbers = values => values.map(value => numericLiteral(String(value)));
export function sourceExpression(source) {
  if (source.kind === 'data') return 'dataExtents';
  if (source.kind === 'node') {
    if (!source.node) throw Error('Choose a node whose bounds you want to use.');
    return `extents(${quotedName(source.node)})`;
  }
  if (source.kind === 'value') {
    if (!source.expression) throw Error('Choose a saved box value.');
    return source.expression;
  }
  if (source.kind === 'current') return source.expression;
  const a = numbers(source.a), b = numbers(source.b);
  if (source.layout === 'centre') {
    if (b.some(n => n < 0)) throw Error('Sizes must be zero or greater.');
    return `boxAt(${vector(a)}, ${vector(b)})`;
  }
  if (a.some((n,i) => n > b[i])) throw Error('Each maximum must be at least its minimum. Equal values make a flat box.');
  return `box(${vector(a)}, ${vector(b)})`;
}
export function volumeExpression(state) {
  let expression = sourceExpression(state.source);
  for (const step of state.steps) {
    const spec = STEPS.find(s => s.id === step.id);
    if (!spec) throw Error('Choose an available volume adjustment.');
    if (step.id === 'union' || step.id === 'intersect') {
      expression = `${step.id}(${expression}, ${sourceExpression(step.source)})`;
      continue;
    }
    let values = numbers(step.values);
    if (step.id === 'inflate') {
      if (values.some(n => n < -100)) throw Error('An inflate percentage must be at least −100%.');
      values = values.map(n => n / 100);
    }
    if (step.id === 'resize') {
      if (values.some(n => n < 0)) throw Error('Sizes must be zero or greater.');
      expression = `boxAt((${expression}).mid, ${vector(values)})`;
    } else if (spec.face) {
      if (!FACES.some(([id]) => id === step.face)) throw Error('Choose a face of the box.');
      expression = `${step.id}(${expression}, '${step.face}', ${values[0]})`;
    } else expression = `${step.id}(${expression}, ${vector(values)})`;
  }
  return expression;
}
export function volumeSources(root, base, rows = [], previous) {
  const owner = ownerAt(root, base), document = atPointer(root, base);
  const nodes = (Array.isArray(document?.nodes) ? document.nodes : []).filter(n => typeof n?.id === 'string')
    .map(n => ({id: n.id, label: `${n.id} · ${n.filter || 'node'}`}));
  const values = entries(root).filter(e => e.group !== 'sweeps' && e.pointer !== previous?.pointer
    && (e.base === base || e.workflow && !owner.workflow)).flatMap(e => {
    const row = rows.find(r => r.pointer === e.pointer);
    const literal = row?.literal || literalSpatial(e.value);
    if ((row?.record?.type || literal?.type) !== 'box') return [];
    return [{id: e.pointer, label: `${e.workflow && e.base !== base ? 'Shared workflow · ' : ''}${e.group}.${e.name}`,
      expression: `${e.base === base ? '' : 'workflow.'}${e.group}.${quotedName(e.name)}`}];
  });
  return {nodes, values};
}
export function initialVolume(previous, source) {
  const literal = literalSpatial(previous?.value);
  let start = source || coordinateSource();
  if (previous) {
    if (literal?.type === 'box' && literal.state === 'resolved' && literal.valid) {
      start = {...coordinateSource(), a: literal.value.min.map(String), b: literal.value.max.map(String)};
    } else if (typeof previous.value?.$expr === 'string') start = {kind: 'current', expression: previous.value.$expr};
    else throw Error('This value uses a structured expression. Create a new volume from the saved value, or edit its expression.');
  }
  return {source: start, steps: [], name: previous?.name || 'volume', group: previous?.group || 'definitions', mode: 'linked'};
}
const formatted = n => Number(n.toPrecision(6)).toString();
export const formatPoint = point => `(${point.map(formatted).join(', ')})`;
export function boxSummary(record) {
  if (record?.state === 'fault') return record.fault?.message || record.reason || 'Could not evaluate this volume.';
  if (record?.state !== 'resolved') return record?.reason === 'stale-data' ? 'Out of date — load data again.'
    : 'Unavailable until data loads.';
  if (record.type !== 'box') return 'This value is not a box.';
  if (!record.valid) return 'Empty or invalid box — there may be no overlap.';
  return `${formatPoint(record.value.min)}, ${formatPoint(record.value.max)}`;
}

export function suggestedVolumeName(state, root, base = '', previous) {
  const source = state.source;
  const label = source.kind === 'node' ? `${source.node || 'node'}_extents`
    : source.kind === 'data' ? 'data_volume'
    : source.kind === 'value' ? `${source.expression.split('.').at(-1).replaceAll('`','')}_volume`
    : source.kind === 'coordinates' ? 'box' : 'volume';
  let stem = [label, ...state.steps.map(step => step.id)].join('_').replace(/[^A-Za-z0-9_-]+/g,'_');
  if (!/^[A-Za-z]/.test(stem)) stem = 'volume_' + stem;
  const names = new Set(Object.keys(atPointer(root,base)?.[state.group] || {}).filter(n => n !== previous?.name));
  let name = stem, suffix = 2;
  while (names.has(name)) name = stem + '_' + suffix++;
  return name;
}
export function canSaveVolume(record, mode) {
  return record?.type === 'box' && (record.state === 'resolved' ? record.valid
    : mode === 'linked' && record.state === 'unresolved' && ['needs-data','stale-data','needs-state'].includes(record.reason));
}
