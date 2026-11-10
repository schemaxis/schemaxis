// Copyright (C) 2026 David L F Gaden
// Schema-driven completion for the JSON editor.
//
// Items: {label, insertText, kind: 'property' | 'value' | 'snippet', detail,
//         documentation, required, deprecated?, sortText, range: {from, to}, cursor?: {from, to}}
// `cursor` is relative to the start of insertText and selects the placeholder.

import {parsePointer} from './json-pointer.mjs';
import {propertyFill, expressionKinds, expressionExample} from './fill-schema.mjs';
import {contextFor, expand, schemasAt, childSchemas, excludedFields} from './schema-core.mjs';

const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
const MAX_ITEMS = 1000;
const MAX_INLINE_DEFAULT = 80;

/** Collect the type names a set of nodes admits. */
export function typesOf(nodes) {
  const types = new Set();
  for (const node of nodes) {
    if (node.type !== undefined) {
      for (const type of [].concat(node.type)) {
        types.add(type);
      }
    }
    if (hasOwn(node, 'const')) {
      types.add(jsonType(node.const));
    }
    if (Array.isArray(node.enum)) {
      node.enum.forEach((option) => types.add(jsonType(option)));
    }
    if (node.properties && node.type === undefined) {
      types.add('object');
    }
  }
  return [...types];
}

function jsonType(value) {
  if (value === null) {
    return 'null';
  }
  if (Array.isArray(value)) {
    return 'array';
  }
  if (typeof value === 'number') {
    return Number.isInteger(value) ? 'integer' : 'number';
  }
  return typeof value;
}

export function firstAnnotation(nodes, name) {
  for (const node of nodes) {
    if (typeof node[name] === 'string' && node[name]) {
      return node[name];
    }
  }
  return '';
}

export function firstDefault(nodes) {
  for (const node of nodes) {
    if (hasOwn(node, 'default')) {
      return {value: node.default};
    }
  }
  return null;
}

/** A value skeleton for a set of schema nodes: {text, cursor}. */
export function skeleton(nodes) {
  const fallback = firstDefault(nodes);
  if (fallback) {
    const text = JSON.stringify(fallback.value);
    if (text.length <= MAX_INLINE_DEFAULT) {
      const quoted = typeof fallback.value === 'string';
      return {text, cursor: quoted ? {from: 1, to: text.length - 1} : {from: 0, to: text.length}};
    }
  }
  const consts = nodes.filter((node) => hasOwn(node, 'const'));
  if (consts.length === 1) {
    const text = JSON.stringify(consts[0].const);
    return {text, cursor: {from: text.length, to: text.length}};
  }
  const types = typesOf(nodes);
  const order = ['object', 'array', 'string', 'number', 'integer', 'boolean', 'null'];
  const pick = order.find((type) => types.includes(type));
  switch (pick) {
    case 'object':
      return {text: '{}', cursor: {from: 1, to: 1}};
    case 'array':
      return {text: '[]', cursor: {from: 1, to: 1}};
    case 'string':
      return {text: '""', cursor: {from: 1, to: 1}};
    case 'number':
    case 'integer':
      return {text: '0', cursor: {from: 0, to: 1}};
    case 'boolean':
      return {text: 'false', cursor: {from: 0, to: 5}};
    case 'null':
      return {text: 'null', cursor: {from: 4, to: 4}};
    default:
      return {text: '', cursor: {from: 0, to: 0}};
  }
}

function rank(label, prefix) {
  if (!prefix) {
    return 0;
  }
  const lower = label.toLowerCase();
  if (lower.startsWith(prefix)) {
    return 0;
  }
  return lower.includes(prefix) ? 1 : -1;
}

function nextSignificant(text, offset) {
  const match = /\S/.exec(text.slice(offset, offset + 200));
  return match ? match[0] : '';
}

function summariseBranch(context, owner, key) {
  const lines = [];
  const required = (owner.required || []).filter((name) => name !== key);
  if (required.length) {
    lines.push(`Requires: ${required.join(', ')}`);
  }
  for (const [name, child] of Object.entries(owner.properties || {})) {
    if (name === key) {
      continue;
    }
    const nodes = expand(context, context.adopt(owner, child), undefined);
    const names = new Set();
    for (const node of nodes) {
      Object.keys(node.properties || {}).forEach((property) => names.add(property));
    }
    if (names.size) {
      const list = [...names];
      const shown = list.slice(0, 12).join(', ');
      lines.push(`${name}: ${shown}${list.length > 12 ? `, … (${list.length})` : ''}`);
    }
  }
  return lines.join('\n');
}

function valueAtPointer(value, pointer) {
  return parsePointer(pointer).reduce((parent, key) => parent?.[key], value);
}

function propertyItems(rootSchema, documentValue, caret, text) {
  const context = contextFor(rootSchema);
  const prefix = (caret.keyPrefix || '').toLowerCase();
  const includeMarkers = prefix.startsWith('$');
  let instance = documentValue;
  const editedKey = caret.pointer === null ? null : parsePointer(caret.pointer).pop();
  if (editedKey !== null) {
    instance = withoutKey(documentValue, caret.parentPointer, editedKey);
  }
  const nodes = schemasAt(rootSchema, instance, caret.parentPointer, {includeMarkers});
  const existing = new Set(caret.existingKeys || []);
  const excluded = excludedFields(nodes, valueAtPointer(instance, caret.parentPointer), rootSchema);
  const entries = new Map();
  let order = 0;
  for (const node of nodes) {
    if (!node.properties) {
      continue;
    }
    for (const [name, child] of Object.entries(node.properties)) {
      if (existing.has(name) || excluded.has(name) || (name[0] === '$' && !includeMarkers)) {
        continue;
      }
      let entry = entries.get(name);
      if (!entry) {
        entry = {name, schemas: [], required: false, order: order++};
        entries.set(name, entry);
      }
      entry.schemas.push(context.adopt(node, child));
      if (Array.isArray(node.required) && node.required.includes(name)) {
        entry.required = true;
      }
    }
  }
  const after = nextSignificant(text, caret.range.to);
  const needsComma = caret.pointer === null && (after === '"' || /[\w$]/.test(after));
  const items = [];
  for (const entry of entries.values()) {
    const score = rank(entry.name, prefix);
    if (score < 0) {
      continue;
    }
    const valueNodes = [];
    const seen = new Set();
    for (const schema of entry.schemas) {
      expand(context, schema, undefined, false, valueNodes, seen);
    }
    const key = JSON.stringify(entry.name);
    let insertText = key;
    let cursor = {from: key.length, to: key.length};
    if (!caret.hasColon) {
      const filled = propertyFill(entry.name, valueNodes, entry.required);
      const raw = JSON.stringify(filled);
      const value = filled?.$fill ? {text: raw, cursor: {from: 0, to: raw.length}} : skeleton(valueNodes);
      insertText = `${key}: ${value.text}`;
      const start = key.length + 2;
      cursor = {from: start + value.cursor.from, to: start + value.cursor.to};
      if (needsComma) {
        insertText += ',';
      }
    }
    const types = typesOf(valueNodes);
    items.push({
      label: entry.name,
      insertText,
      kind: 'property',
      detail: types.join(' | '),
      documentation: firstAnnotation(valueNodes, 'description') || firstAnnotation(valueNodes, 'title'),
      required: entry.required,
      deprecated: valueNodes.some((node) => node.deprecated === true) || undefined,
      sortText: `${score}${entry.required ? 0 : 1}${String(entry.order).padStart(5, '0')}`,
      range: caret.range,
      cursor,
    });
  }
  return items;
}

function withoutKey(value, pointer, key) {
  const segments = parsePointer(pointer || '');
  const clone = (node, index) => {
    if (node === null || typeof node !== 'object') {
      return node;
    }
    const copy = Array.isArray(node) ? node.slice() : {...node};
    if (index === segments.length) {
      if (!Array.isArray(copy)) {
        delete copy[key];
      }
      return copy;
    }
    const segment = segments[index];
    copy[segment] = clone(node[segment], index + 1);
    return copy;
  };
  return clone(value, 0);
}

function addValue(collected, value, info) {
  const insertText = JSON.stringify(value);
  if (insertText === undefined || collected.has(insertText)) {
    return;
  }
  collected.set(insertText, {value, ...info});
}

function valueItems(rootSchema, documentValue, caret, text, names = []) {
  const context = contextFor(rootSchema);
  const segments = parsePointer(caret.pointer || '');
  const key = segments.length ? segments[segments.length - 1] : null;
  const owners = [];
  if (key === null) {
    owners.push({owner: null, schemas: [rootSchema]});
  } else {
    const parentValue = withoutKey(documentValue, caret.parentPointer, key);
    const parents = schemasAt(rootSchema, parentValue, caret.parentPointer);
    for (const parent of parents) {
      const schemas = childSchemas(context, [parent], key);
      if (schemas.length) {
        owners.push({owner: parent, schemas});
      }
    }
  }
  const discriminating = owners.filter(({owner}) => owner && owner.properties && hasOwn(owner.properties, key));
  const isDiscriminator = discriminating.length > 1;
  const collected = new Map();
  const types = new Set();
  for (const {owner, schemas} of owners) {
    const nodes = [];
    const seen = new Set();
    for (const schema of schemas) {
      expand(context, schema, undefined, false, nodes, seen);
    }
    typesOf(nodes).forEach((type) => types.add(type));
    for (const node of nodes) {
      const doc = node.description || node.title || '';
      if (hasOwn(node, 'const')) {
        const ownerDoc = owner && (owner.description || owner.title);
        const documentation = doc || ownerDoc || '';
        const summarise = isDiscriminator && !documentation ? owner : null;
        addValue(collected, node.const, {detail: isDiscriminator ? key : 'constant', documentation, order: 0,
          summarise});
      }
      for (const option of node.enum || []) {
        addValue(collected, option, {detail: 'enum', documentation: doc, order: 0});
      }
      if (hasOwn(node, 'default')) {
        addValue(collected, node.default, {detail: 'default', documentation: doc, order: 1});
      }
    }
  }
  if (types.has('string') && !collected.size) {
    names.forEach((name) => addValue(collected, name.value, {detail: name.detail, order: 0}));
  }
  if (types.has('boolean')) {
    addValue(collected, true, {detail: 'boolean', order: 2});
    addValue(collected, false, {detail: 'boolean', order: 2});
  }
  if (types.has('null')) {
    addValue(collected, null, {detail: 'null', order: 2});
  }
  let prefix = (caret.valuePrefix || '').toLowerCase();
  if (prefix.startsWith('"')) {
    prefix = prefix.slice(1);
  }
  const before = caret.range.from > 0 ? text[caret.range.from - 1] : '';
  const lead = before === ':' && caret.node === null ? ' ' : '';
  const after = nextSignificant(text, caret.range.to);
  const tail = caret.node === null && after && /["{[\w-]/.test(after) ? ',' : '';
  const items = [];
  for (const [insertText, info] of collected) {
    const label = typeof info.value === 'string' ? info.value : insertText;
    const score = rank(label, prefix);
    if (score < 0) {
      continue;
    }
    items.push({
      label,
      insertText: lead + insertText + tail,
      kind: 'value',
      detail: info.detail,
      documentation: info.documentation || (info.summarise ? summariseBranch(context, info.summarise, key) : ''),
      required: false,
      sortText: `${score}${info.order}${label.toLowerCase()}`,
      range: caret.range,
    });
  }
  if (!prefix || prefix.startsWith('$')) {
    for (const key of expressionKinds(rootSchema, documentValue, caret.pointer || '')) {
      if (prefix && !key.startsWith(prefix)) continue;
      const expression = JSON.stringify(expressionExample(key));
      items.push({label: key, insertText: lead + expression + tail, kind: 'snippet', detail: 'expression',
        documentation: 'Fill the expression fields after insertion.', required: false, sortText: `04${key}`,
        range: caret.range});
    }
  }
  if (!prefix) {
    for (const [type, text2] of [['object', '{}'], ['array', '[]']]) {
      if (types.has(type) && !collected.has(text2)) {
        items.push({label: text2, insertText: lead + text2 + tail, kind: 'snippet', detail: `empty ${type}`,
          documentation: '', required: false, sortText: `03${text2}`, range: caret.range,
          cursor: {from: lead.length + 1, to: lead.length + 1}});
      }
    }
  }
  return items;
}

/**
 * Completions at a caret context (from pointerAt) inside `documentValue`.
 * Pointers in the caret context are relative to the schema's document.
 * `names` are {value, detail} strings known from outside the schema, such as
 * the regions and arrays of an inspected case; they are offered wherever text
 * is accepted and the schema lists no values of its own.
 */
export function completionsAt(rootSchema, documentValue, caret, text, names = []) {
  let items = [];
  if (caret.position === 'key') {
    items = propertyItems(rootSchema, documentValue, caret, text);
  } else if (caret.position === 'value') {
    items = valueItems(rootSchema, documentValue, caret, text, names);
  }
  items.sort((a, b) => (a.sortText < b.sortText ? -1 : a.sortText > b.sortText ? 1 : 0));
  return items.slice(0, MAX_ITEMS);
}
