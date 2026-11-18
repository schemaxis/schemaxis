// Copyright (C) 2026 David L. F. Gaden.
// Display literal shapes and host records; never interpret expression text.
import {entries, saveEntry} from '../variables/model.mjs';

export const INVALID_BOX = {min: [1, 1, 1], max: [-1, -1, -1]};
const triple = value => Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
export const hasMarker = value => value && typeof value === 'object' && (Object.keys(value).some(key => key.startsWith('$'))
  || Object.values(value).some(hasMarker));

export function literalSpatial(value) {
  if (hasMarker(value)) return {type: 'unknown', state: 'unresolved', reason: 'Needs host evaluation'};
  if (typeof value === 'number') return Number.isFinite(value)
    ? {type: 'scalar', state: 'resolved', value} : {type: 'scalar', state: 'fault', reason: 'Enter a finite number'};
  if (Array.isArray(value) && value.length === 3) return triple(value) ? {type: 'vector', state: 'resolved', value: [...value]} : null;
  let box;
  if (Array.isArray(value) && value.length === 6) box = {min: [value[0], value[2], value[4]], max: [value[1], value[3], value[5]]};
  else if (value && typeof value === 'object' && Object.keys(value).length === 2 && 'min' in value && 'max' in value) box = value;
  else return null;
  if (!triple(box.min) || !triple(box.max)) return null;
  const valid = box.min.every((n, i) => n <= box.max[i]);
  return {type: 'box', state: 'resolved', valid, value: structuredClone(valid ? box : INVALID_BOX)};
}

export function spatialEntries(root, base = null) {
  return entries(root).filter(e => (base === null || e.base === base) && e.group !== 'sweeps').flatMap(entry => {
    const literal = literalSpatial(entry.value);
    return literal ? [{...entry, literal}] : [];
  });
}

/** Vectors can be viewed as positions or segments from the model origin. */
export function entryOverlays(rows, {vectorsAsLines = false, hidden = new Set()} = {}) {
  return rows.flatMap(({pointer: id, literal: item}) => {
    if (hidden.has(id) || item.state !== 'resolved') return [];
    if (item.type === 'box') return item.valid ? [{id, kind: 'box', ...item.value}] : [];
    if (item.type === 'vector') return [vectorsAsLines ? {id, kind: 'line', start: [0, 0, 0], end: item.value}
      : {id, kind: 'point', point: item.value}];
    return [];
  });
}

/** Strict typed number fields: blank strings and expressions must not become zero. */
export function numericLiteral(text) {
  let value;
  try { value = JSON.parse(text); } catch { throw Error('Enter a finite number in every coordinate field.'); }
  if (typeof value !== 'number' || !Number.isFinite(value)) throw Error('Enter a finite number in every coordinate field.');
  return value;
}

/** An edited box keeps the form it was authored in; a new box is written as {min,max}. */
export function writeLiteral(root, identity, value, previous) {
  const literal = literalSpatial(value);
  if (!literal || literal.state !== 'resolved') throw Error('Enter a literal scalar, vector or box.');
  if (previous && (identity.base !== previous.base || identity.group !== previous.group || identity.name !== previous.name)) {
    throw Error('Keep the existing name and scope when editing a spatial value.');
  }
  const flat = literal.type === 'box' && Array.isArray(previous?.value);
  return writeSpatialValue(root, identity, flat ? [0, 1, 2].flatMap(i => [literal.value.min[i], literal.value.max[i]]) : literal.value, previous);
}

export function writeSpatialValue(root, identity, value, previous) {
  const parameter = previous?.workflow && Object.values(root.parameters || {}).find(p =>
    p.target?.scope === 'workflow' && previous.base + p.target.pointer === previous.pointer);
  return saveEntry(root, {...identity, value,
    ...(parameter ? {parameter: true, units: parameter.units, help: parameter.help} : {})}, previous);
}

/** Merge only records supplied by the host, preserving full scoped identities. */
export function recordRows(root, records, draft, inputDigest) {
  const authored = entries(root);
  return records.flatMap(record => {
    const untypedProblem = record.type === undefined && ['fault', 'unresolved'].includes(record.state);
    if (!record.entry || !untypedProblem && !['scalar', 'vector', 'box'].includes(record.type)) return [];
    if (record.state === 'resolved' && inputDigest && record.source?.inputDigest !== inputDigest) {
      record = {...record, state: 'unresolved', reason: 'stale-data'};
    }
    const {scope, section, key} = record.entry;
    const entry = authored.find(e => e.group === section && e.name === key
      && (scope === 'workflow' ? e.workflow : record.operation ? e.operation === record.operation : !e.workflow && !e.operation));
    if (!entry) return [];
    return [{...entry, record, draft, literal: {type: record.type || 'unknown', state: record.state,
      ...(record.state === 'resolved' ? {value: record.value, valid: record.valid} : {}),
      reason: record.fault?.message || record.reason}}];
  });
}

/** A captured response belongs to exactly one authored draft, including its workflow. */
export function matchingSpatialSnapshot(root, snapshot) {
  return Boolean(snapshot?.response?.inputDigest && Array.isArray(snapshot.response.records)
    && JSON.stringify(root) === JSON.stringify(snapshot.root));
}

export function snapshotRows(root, snapshot) {
  if (!matchingSpatialSnapshot(root, snapshot)) return null;
  // A load for one operation must not hide literals in the other operations.
  // Host records take precedence, including explicit unresolved/fault records.
  const rows = new Map(spatialEntries(root).map(row => [row.pointer, row]));
  for (const row of recordRows(root, snapshot.response.records, snapshot.draft, snapshot.response.inputDigest)) {
    rows.set(row.pointer, row);
  }
  return [...rows.values()];
}
