// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// File naming: natural ordering, file kinds, companion detection and the
// Schemaxis key-value filename format (schemaxis.artifact-name/1).

const CHUNK = /(\d+)|(\D+)/g;
const NUMBER = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:e-?[0-9]+)?$/;
const COMPANION = /\.(?:metadata\.json|schemaxis-meta(?:\.json)?|scxmeta(?:\.json)?|METADATA)$/i;
const SCHEMAXIS = /^([0-9]{6})(?:\.([0-9]+))?((?:__.*)?)\.([A-Za-z][A-Za-z0-9]*)$/;

const KINDS = {
  image: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'avif', 'ico'],
  video: ['mp4', 'webm', 'ogv', 'mov', 'm4v'],
  audio: ['wav', 'mp3', 'ogg', 'oga', 'flac', 'm4a', 'aac', 'opus'],
  mesh: ['stl', 'obj'],
  table: ['csv', 'tsv'],
  pdf: ['pdf'],
  text: ['txt', 'log', 'md', 'json', 'xml', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'py', 'sh', 'c', 'h', 'cpp', 'hpp',
         'js', 'mjs', 'css', 'html', 'pvsm', 'foam', 'dat', 'out', 'err', 'rst', 'tex', 'bib', 'cmake', 'sql']
};

export const KIND_LABELS = {image: 'Images', video: 'Videos', audio: 'Audio', mesh: '3D models', table: 'Tables',
  pdf: 'PDF', text: 'Text', other: 'Other files'};

export function naturalCompare(a, b) {
  const left = String(a).match(CHUNK) || [], right = String(b).match(CHUNK) || [];
  for (let i = 0; i < Math.min(left.length, right.length); i++) {
    const x = left[i], y = right[i];
    if (x === y) continue;
    const dx = /^\d/.test(x), dy = /^\d/.test(y);
    if (dx && dy) {
      const difference = Number(x) - Number(y);
      if (difference) return difference;
      return x.length - y.length;
    }
    const order = x.localeCompare(y, undefined, {sensitivity: 'base'});
    if (order) return order;
    return x < y ? -1 : 1;
  }
  return left.length - right.length;
}

export function extension(name) {
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : '';
}

export function fileKind(name) {
  const ext = extension(name);
  for (const [kind, list] of Object.entries(KINDS)) if (list.includes(ext)) return kind;
  return 'other';
}

export function companionBase(name) {
  const match = COMPANION.exec(name);
  return match ? name.slice(0, match.index) : null;
}

function scalar(raw) {
  if (raw === 'list') throw Error('Reserved list marker');
  if (NUMBER.test(raw)) {
    const value = Number(raw);
    if (!Number.isFinite(value)) throw Error('Nonfinite number');
    return value;
  }
  if (raw === 'true') return true;
  if (raw === 'false') return false;
  if (raw === 'null') return null;
  if (raw === '.empty.') return '';
  const bytes = [];
  for (let i = 0; i < raw.length;) {
    const escape = /^\.x([0-9A-F]{2})\./.exec(raw.slice(i));
    if (escape) {
      bytes.push(parseInt(escape[1], 16));
      i += 5;
    } else if (/[A-Za-z0-9-]/.test(raw[i])) {
      bytes.push(raw.charCodeAt(i++));
    } else {
      throw Error('Invalid filename text');
    }
  }
  if (!bytes.length) throw Error('Empty token');
  return new TextDecoder('utf-8', {fatal: true}).decode(new Uint8Array(bytes));
}

export function parseSchemaxisName(file) {
  if (companionBase(file) !== null) return null;
  const match = SCHEMAXIS.exec(file);
  if (!match) return null;
  const properties = {};
  try {
    for (const field of match[3] ? match[3].slice(2).split('__') : []) {
      const parts = field.split('_'), key = parts.shift();
      if (!/^[A-Za-z][A-Za-z0-9]*$/.test(key) || Object.hasOwn(properties, key) || !parts.length) return null;
      if (parts[0] === 'list') {
        properties[key] = parts.slice(1).map(scalar);
      } else {
        if (parts.length !== 1) return null;
        properties[key] = scalar(parts[0]);
      }
    }
  } catch {
    return null;
  }
  return {ordinal: match[1], worker: match[2] ?? null, properties, extension: match[4].toLowerCase()};
}

export function formatValue(value) {
  if (Array.isArray(value)) return value.length ? value.map(formatValue).join(', ') : '(empty list)';
  if (value === null) return 'null';
  if (value === '') return '(empty)';
  return String(value);
}

export function compareValues(a, b) {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  if (typeof a === 'number') return -1;
  if (typeof b === 'number') return 1;
  return naturalCompare(formatValue(a), formatValue(b));
}

export function formatBytes(size) {
  if (!Number.isFinite(size)) return '';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = size, unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${unit ? value.toFixed(value < 10 ? 1 : 0) : value} ${units[unit]}`;
}
