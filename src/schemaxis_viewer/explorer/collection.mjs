// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// The opened collection: files, companions, folders and every property source
// (file facts, Schemaxis filenames, automatic sequences, user patterns and
// companion metadata), plus filtering, facets and grouping into sequences.

import {naturalCompare, fileKind, extension, companionBase, parseSchemaxisName, compareValues, formatValue, KIND_LABELS}
  from './names.mjs';
import {detectSequences} from './sequences.mjs';
import {extractRuleProperties} from './rules.mjs';

export const SOURCE_LABELS = {file: 'file', name: 'filename', auto: 'sequence', pattern: 'pattern', meta: 'metadata'};
const ORDER_CANDIDATES = ['pos', 'time', 'frame', 'n', 'n1'];
const CAPTION_SKIP = new Set(['type', 'folder', 'scene', 'sequence', 'n', 'n1', 'n2', 'n3', 'name', 'placed', 'tags']);
const SEQUENCE_ORDER = ['pos', 'frame', 'time'];

function dirname(path) {
  const slash = path.lastIndexOf('/');
  return slash < 0 ? '' : path.slice(0, slash);
}

function basename(path) {
  return path.slice(path.lastIndexOf('/') + 1);
}

function finitePoint(point) {
  return Array.isArray(point) && point.length === 3 && point.every(Number.isFinite);
}

export const METADATA_VERSION = 'schemaxis.artifact-metadata/1';
export const METADATA_VERIFIED = 'SHA-256 matched';
export const HASH_LIMIT = 256 * 1024 * 1024;

export function metadataProblem(item, metadata) {
  if (metadata?.version !== METADATA_VERSION) return 'not Schemaxis artifact metadata; not applied';
  if (metadata.artifact?.file !== item.name) return 'names a different file; not applied';
  if (!/^[a-f0-9]{64}$/i.test(metadata.artifact?.sha256 || '')) return 'SHA-256 is absent or invalid; not applied';
  if (item.size > HASH_LIMIT) return 'file is too large to verify in the browser (256 MiB); not applied';
  return null;
}

export function spatialFromMetadata(metadata) {
  const spatial = metadata?.spatial;
  if (!spatial || spatial.state !== 'known' || !Array.isArray(spatial.corners) || spatial.corners.length !== 4) return null;
  if (!spatial.corners.every(finitePoint)) return null;
  const [a, b, , d] = spatial.corners;
  const u = b.map((v, i) => v - a[i]), v = d.map((x, i) => x - a[i]);
  const normal = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const length = Math.hypot(...normal);
  if (!(length > 0)) return null;
  return {corners: spatial.corners, normal: normal.map(x => x / length), frame: spatial.frame || '', units: spatial.units || ''};
}

export class Collection {
  constructor(records, sources = []) {
    this.items = [];
    this.byId = new Map();
    this.roots = new Map();
    const companions = new Map();
    for (const record of records) {
      const relative = record.relativePath || record.name;
      const root = record.root || 'selected-files';
      const key = root + '/' + relative;
      this.roots.set(root, record.rootLabel || root);
      const base = companionBase(relative);
      if (base !== null) {
        companions.set(root + '/' + base, record);
        continue;
      }
      const name = basename(relative);
      const item = {id: String(record.id), name, root, relative, key, folder: dirname(key), path: '',
        ext: extension(name), kind: fileKind(name), size: record.size, url: record.url, file: record.file || null,
        sx: parseSchemaxisName(name), companion: null, meta: null, spatial: null, seq: null, family: null,
        props: {}, sources: {}};
      this.items.push(item);
      this.byId.set(item.id, item);
    }
    for (const item of this.items) {
      item.path = this.displayPath(item.key);
      const companion = companions.get(item.key);
      if (companion) item.companion = {url: companion.url, name: basename(companion.relativePath || companion.name),
        size: companion.size, file: companion.file || null};
    }
    this.items.sort((a, b) => naturalCompare(a.key, b.key));
    this.folders = this.buildFolders(sources);
    const sequences = detectSequences(this.items.filter(item => !item.sx)
      .map(item => ({id: item.id, folder: item.folder, name: item.name})));
    for (const [id, sequence] of sequences) this.byId.get(id).seq = sequence;
    this.rules = [];
    this.ruleErrors = new Map();
    this.derive();
  }

  displayPath(key) {
    const slash = key.indexOf('/');
    const root = slash < 0 ? key : key.slice(0, slash);
    const label = this.roots.get(root) || root;
    return slash < 0 ? label : label + key.slice(slash);
  }

  buildFolders(sources) {
    const nodes = new Map();
    const ensure = function ensure(key) {
      if (nodes.has(key)) return nodes.get(key);
      const node = {key, name: '', children: [], files: 0, total: 0};
      nodes.set(key, node);
      const parent = dirname(key);
      if (parent) ensure(parent).children.push(node);
      return node;
    };
    for (const [root] of this.roots) ensure(root);
    for (const source of sources || []) {
      if (!this.roots.has(source.root)) continue;
      for (const folder of source.folders || []) ensure(source.root + '/' + folder);
    }
    for (const item of this.items) {
      ensure(item.folder).files++;
      for (let key = item.folder; key; key = dirname(key)) nodes.get(key).total++;
    }
    for (const node of nodes.values()) {
      node.name = dirname(node.key) ? basename(node.key) : (this.roots.get(node.key) || node.key);
      node.children.sort((a, b) => naturalCompare(a.name, b.name));
    }
    return {nodes, roots: [...this.roots.keys()].map(root => nodes.get(root))};
  }

  setRules(rules) {
    this.rules = rules;
    this.derive();
  }

  setMetadata(item, metadata, status) {
    item.meta = metadata;
    item.metaStatus = status;
    item.metaVerified = status === METADATA_VERIFIED;
    item.spatial = item.metaVerified ? spatialFromMetadata(metadata) : null;
    this.deriveItem(item, this.lastRuleProperties?.get(item.id));
  }

  derive() {
    const {properties, errors} = extractRuleProperties(this.items, this.rules);
    this.ruleErrors = errors;
    this.lastRuleProperties = properties;
    for (const item of this.items) this.deriveItem(item, properties.get(item.id));
  }

  deriveItem(item, ruleValues) {
    const props = {}, sources = {};
    const put = function put(key, value, source) {
      props[key] = value;
      sources[key] = source;
    };
    put('type', KIND_LABELS[item.kind], 'file');
    put('folder', this.displayPath(item.folder), 'file');
    if (item.seq) {
      put('sequence', item.seq.label, 'auto');
      if (item.seq.values.length === 1) put('n', item.seq.values[0], 'auto');
      else item.seq.values.forEach((value, index) => put(`n${index + 1}`, value, 'auto'));
    }
    if (item.sx) for (const [key, value] of Object.entries(item.sx.properties)) put(key, value, 'name');
    for (const [key, value] of Object.entries(ruleValues || {})) put(key, value, 'pattern');
    const declared = item.metaVerified ? item.meta.properties : null;
    if (declared && typeof declared === 'object' && !Array.isArray(declared)) {
      for (const [key, value] of Object.entries(declared)) {
        const plain = (Array.isArray(value) ? value : [value]).every(v => v === null || ['string', 'boolean'].includes(typeof v)
          || (typeof v === 'number' && Number.isFinite(v)));
        if (plain) put(key, value, 'meta');
      }
    }
    if (item.spatial) put('placed', 'in 3D', 'meta');
    item.props = props;
    item.sources = sources;
    item.family = familyOf(item);
  }
}

function familyOf(item) {
  if (item.sx) {
    const p = item.sx.properties;
    const order = SEQUENCE_ORDER.find(key => typeof p[key] === 'number');
    if (!order) return null;
    const chips = Object.keys(p).filter(key => key !== order && key !== 'scene').sort().map(key => [key, p[key]]);
    return {id: 'sx:' + item.folder + JSON.stringify(chips), chips, order, label: null, folder: item.props.folder};
  }
  if (item.seq) return {id: item.seq.family, chips: [], order: '@rank', label: item.seq.label, folder: item.props.folder};
  return null;
}

export function memberTokens(value) {
  return (Array.isArray(value) ? value : [value]).map(member => JSON.stringify(member));
}

export function matchesFilters(item, filters, skipKey = null) {
  for (const [key, tokens] of filters) {
    if (key === skipKey || !tokens.size) continue;
    if (!Object.hasOwn(item.props, key)) return false;
    if (!memberTokens(item.props[key]).some(token => tokens.has(token))) return false;
  }
  return true;
}

export function matchesSearch(item, query) {
  if (!query) return true;
  const haystack = (item.path + '\n' + Object.entries(item.props).map(([k, v]) => `${k}=${formatValue(v)}`).join('\n')).toLowerCase();
  return query.toLowerCase().split(/\s+/).filter(Boolean).every(term => haystack.includes(term));
}

export function inFolder(item, folder, recursive) {
  if (!folder) return true;
  return recursive ? item.folder === folder || item.folder.startsWith(folder + '/') : item.folder === folder;
}

const FACET_ORDER = ['type', 'kind', 'var', 'axis', 'model', 'view', 'series', 'tags', 'sequence', 'placed', 'folder'];

export function facets(items, filters) {
  const keys = new Map();
  for (const item of items) for (const key of Object.keys(item.props)) keys.set(key, (keys.get(key) || 0) + 1);
  const result = [];
  for (const [key, present] of keys) {
    const values = new Map();
    for (const item of items) {
      if (!Object.hasOwn(item.props, key) || !matchesFilters(item, filters, key)) continue;
      const members = Array.isArray(item.props[key]) ? item.props[key] : [item.props[key]];
      for (const member of members) {
        const token = JSON.stringify(member);
        if (!values.has(token)) values.set(token, {token, value: member, count: 0});
        values.get(token).count++;
      }
    }
    const selected = filters.get(key) || new Set();
    for (const token of selected) if (!values.has(token)) values.set(token, {token, value: JSON.parse(token), count: 0});
    const list = [...values.values()].sort((a, b) => compareValues(a.value, b.value));
    for (const entry of list) entry.checked = selected.has(entry.token);
    if (!selected.size && !list.some(entry => entry.count > 0)) continue;
    result.push({key, present, values: list, active: selected.size > 0});
  }
  return result.sort(function order(a, b) {
    const x = FACET_ORDER.indexOf(a.key), y = FACET_ORDER.indexOf(b.key);
    if (x !== y) return (x < 0 ? 99 : x) - (y < 0 ? 99 : y);
    return naturalCompare(a.key, b.key);
  });
}

function orderValue(item, key) {
  if (key === '@rank') return item.seq ? item.seq.rank : 0;
  if (key === '@name') return item.name;
  return item.props[key];
}

export function sortItems(items, key) {
  return [...items].sort(function compare(a, b) {
    const x = orderValue(a, key), y = orderValue(b, key);
    if (x === undefined && y !== undefined) return 1;
    if (y === undefined && x !== undefined) return -1;
    return (x === undefined ? 0 : compareValues(x, y)) || naturalCompare(a.name, b.name) || naturalCompare(a.key, b.key);
  });
}

function automaticOrder(items) {
  for (const key of ORDER_CANDIDATES) {
    const values = items.map(item => item.props[key]);
    if (values.every(value => typeof value === 'number') && new Set(values).size > 1) return key;
  }
  return '@name';
}

export function captionFor(item, orderKey, vary = []) {
  let caption;
  if (orderKey === '@rank' && item.seq) caption = item.seq.values.join(' · ');
  else if (orderKey && orderKey !== '@name' && item.props[orderKey] !== undefined) caption = `${orderKey} ${formatValue(item.props[orderKey])}`;
  else return item.name;
  const extra = vary.filter(key => item.props[key] !== undefined).map(key => `${key} ${formatValue(item.props[key])}`);
  return [caption, ...extra].join(' · ');
}

function varyingKeys(items, orderKey) {
  const values = new Map();
  for (const item of items) for (const [key, value] of Object.entries(item.props)) {
    if (key === orderKey || CAPTION_SKIP.has(key)) continue;
    if (!values.has(key)) values.set(key, new Set());
    values.get(key).add(JSON.stringify(value));
  }
  return [...values].filter(([, tokens]) => tokens.size > 1).map(([key]) => key).slice(0, 2);
}

export function groupItems(items, groupBy, orderBy = 'auto') {
  const buckets = new Map();
  const other = {id: '@other', chips: [], label: 'Other files', items: [], order: null, sequence: false, folder: ''};
  const sequenceMode = groupBy.length === 1 && groupBy[0] === '@sequence';
  if (!groupBy.length) {
    other.label = 'All files';
    other.items = items;
  } else if (sequenceMode) {
    for (const item of items) {
      if (!item.family) {
        other.items.push(item);
        continue;
      }
      if (!buckets.has(item.family.id)) {
        buckets.set(item.family.id, {id: item.family.id, chips: item.family.chips, label: item.family.label, items: [],
          order: item.family.order, sequence: true, folder: item.family.folder});
      }
      buckets.get(item.family.id).items.push(item);
    }
    for (const [id, group] of buckets) {
      if (group.items.length > 1) continue;
      other.items.push(...group.items);
      buckets.delete(id);
    }
  } else {
    for (const item of items) {
      const chips = groupBy.map(key => [key, Object.hasOwn(item.props, key) ? item.props[key] : undefined]);
      const id = 'k:' + JSON.stringify(chips);
      if (!buckets.has(id)) buckets.set(id, {id, chips, label: null, items: [], order: null, sequence: false, folder: ''});
      buckets.get(id).items.push(item);
    }
  }
  const groups = [...buckets.values()];
  if (!sequenceMode) {
    groups.sort(function compare(a, b) {
      for (let i = 0; i < a.chips.length; i++) {
        const x = a.chips[i][1], y = b.chips[i][1];
        if (x === undefined || y === undefined) {
          if (x !== y) return x === undefined ? 1 : -1;
          continue;
        }
        const order = compareValues(x, y);
        if (order) return order;
      }
      return 0;
    });
  } else {
    groups.sort((a, b) => naturalCompare(a.folder, b.folder)
      || naturalCompare(chipText(a.chips) + (a.label || ''), chipText(b.chips) + (b.label || '')));
  }
  if (other.items.length) groups.push(other);
  for (const group of groups) {
    const key = orderBy !== 'auto' ? orderBy : group.order || automaticOrder(group.items);
    group.orderKey = key;
    group.items = sortItems(group.items, key);
    group.vary = key === '@name' ? [] : varyingKeys(group.items, key);
  }
  return groups;
}

function chipText(chips) {
  return chips.map(([key, value]) => `${key}=${formatValue(value)}`).join(' ');
}

export function commonChips(groups) {
  const candidates = groups.filter(group => group.id !== '@other' && group.chips.length);
  if (candidates.length < 2) return {common: [], distinct: new Map(groups.map(group => [group.id, group.chips]))};
  const values = new Map();
  for (const group of candidates) {
    for (const [key, value] of group.chips) {
      if (!values.has(key)) values.set(key, new Set());
      values.get(key).add(JSON.stringify(value));
    }
  }
  const carriers = new Map();
  for (const group of candidates) for (const [key] of group.chips) carriers.set(key, (carriers.get(key) || 0) + 1);
  const shared = new Set([...values].filter(([key, tokens]) => tokens.size === 1 && carriers.get(key) > 1).map(([key]) => key));
  const common = [];
  for (const group of candidates) for (const chip of group.chips) {
    if (shared.has(chip[0]) && !common.some(([key]) => key === chip[0])) common.push(chip);
  }
  const distinct = new Map(groups.map(group => [group.id, group.chips.filter(([key]) => !shared.has(key))]));
  return {common, distinct};
}

export function propertyKeys(items) {
  const keys = new Map();
  for (const item of items) for (const key of Object.keys(item.props)) keys.set(key, (keys.get(key) || 0) + 1);
  return [...keys.entries()].sort((a, b) => b[1] - a[1] || naturalCompare(a[0], b[0])).map(([key]) => key);
}
