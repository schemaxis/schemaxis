// Copyright (C) 2026 David L F Gaden
import {yamlPointerAt} from './yaml-parse.mjs';
// RFC 6901 pointers over the tolerant AST: caret context, pointer ranges and values.

/** Escape one pointer segment. */
export function escapeSegment(segment) {
  return String(segment).replace(/~/g, '~0').replace(/\//g, '~1');
}

/** Split a pointer into unescaped segments. '' is the root. */
export function parsePointer(pointer) {
  if (!pointer) {
    return [];
  }
  if (pointer[0] !== '/') {
    throw new Error(`Invalid JSON pointer: ${pointer}`);
  }
  return pointer.slice(1).split('/').map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~'));
}

/** Join segments into a pointer. */
export function formatPointer(segments) {
  return segments.map((segment) => `/${escapeSegment(segment)}`).join('');
}

function rootOf(ast) {
  return ast && Object.prototype.hasOwnProperty.call(ast, 'root') ? ast.root : ast;
}

function textOf(ast) {
  return ast && typeof ast.text === 'string' ? ast.text : '';
}

function lastMember(node, key) {
  let found = null;
  for (const member of node.members) {
    if (member.key.value === key) {
      found = member;
    }
  }
  return found;
}

/** The AST node at a pointer, or null. Duplicate keys resolve to the last one, like JSON.parse. */
export function nodeAtPointer(ast, pointer) {
  let node = rootOf(ast);
  for (const segment of parsePointer(pointer)) {
    if (!node) {
      return null;
    }
    if (node.type === 'object') {
      const member = lastMember(node, segment);
      node = member ? member.value : null;
    } else if (node.type === 'array' && /^(0|[1-9]\d*)$/.test(segment)) {
      node = node.items[Number(segment)] || null;
    } else {
      return null;
    }
  }
  return node || null;
}

/** {from, to, keyFrom?, keyTo?, node} for the value at a pointer, or null. */
export function rangeOfPointer(ast, pointer) {
  const segments = parsePointer(pointer);
  let node = rootOf(ast);
  let member = null;
  for (const segment of segments) {
    member = null;
    if (!node) {
      return null;
    }
    if (node.type === 'object') {
      member = lastMember(node, segment);
      node = member ? member.value : null;
      if (member && !node) {
        return {from: member.key.from, to: member.to, keyFrom: member.key.from, keyTo: member.key.to, node: null};
      }
    } else if (node.type === 'array' && /^(0|[1-9]\d*)$/.test(segment)) {
      node = node.items[Number(segment)] || null;
    } else {
      return null;
    }
  }
  if (!node) {
    return null;
  }
  const range = {from: node.from, to: node.to, node};
  if (member) {
    range.keyFrom = member.key.from;
    range.keyTo = member.key.to;
  }
  return range;
}

/** Plain JSON for the value at a pointer (undefined when absent). */
export function valueAt(ast, pointer) {
  return plain(nodeAtPointer(ast, pointer));
}

function plain(node) {
  if (!node) {
    return undefined;
  }
  if (node.type === 'object') {
    const result = {};
    for (const member of node.members) {
      const value = plain(member.value);
      if (value !== undefined) {
        result[member.key.value] = value;
      }
    }
    return result;
  }
  if (node.type === 'array') {
    return node.items.map((item) => {
      const value = plain(item);
      return value === undefined ? null : value;
    });
  }
  return node.type === 'invalid' ? undefined : node.value;
}

function containerContains(node, offset) {
  return offset > node.from && (offset < node.to || !node.closed);
}

function scalarContains(node, offset) {
  if (node.type === 'string' && node.closed) {
    return offset >= node.from && offset < node.to;
  }
  return offset >= node.from && offset <= node.to;
}

function contains(node, offset) {
  if (node.type === 'object' || node.type === 'array') {
    return containerContains(node, offset);
  }
  return scalarContains(node, offset);
}

function hasCommaBetween(text, from, to) {
  return text.slice(from, to).includes(',');
}

function valueContext(node, text, offset, pointer, parentPointer, existingKeys) {
  return {
    position: 'value',
    pointer,
    parentPointer,
    valuePrefix: text.slice(node.from, offset),
    range: {from: node.from, to: node.to},
    node,
    existingKeys,
  };
}

function emptyValue(offset, pointer, parentPointer, existingKeys) {
  return {position: 'value', pointer, parentPointer, valuePrefix: '', range: {from: offset, to: offset}, node: null,
    existingKeys};
}

function between(pointer, offset, node) {
  return {position: 'between', pointer, parentPointer: pointer, range: {from: offset, to: offset}, node};
}

function objectContext(node, text, offset, pointer) {
  const keys = node.members.map((member) => member.key.value);
  let previousEnd = node.from + 1;
  for (let index = 0; index < node.members.length; index += 1) {
    const member = node.members[index];
    const others = keys.filter((_, other) => other !== index);
    const key = member.key;
    const memberPointer = `${pointer}/${escapeSegment(key.value)}`;
    if (offset <= key.from && key.to > key.from) {
      break;
    }
    const inKey = offset < key.to || (offset === key.to && (!key.closed || !key.quoted));
    if (inKey) {
      const prefixStart = key.quoted ? key.from + 1 : key.from;
      return {
        position: 'key',
        pointer: memberPointer,
        parentPointer: pointer,
        keyPrefix: text.slice(prefixStart, Math.max(prefixStart, offset)),
        range: {from: key.from, to: key.to},
        hasColon: member.colon >= 0,
        node: member.value,
        existingKeys: others,
      };
    }
    if (member.value && contains(member.value, offset)) {
      return locate(member.value, text, offset, memberPointer, pointer, others);
    }
    if (member.colon >= 0 && offset > member.colon && (!member.value || offset <= member.value.from)) {
      return emptyValue(offset, memberPointer, pointer, others);
    }
    previousEnd = member.to;
  }
  const isFirst = previousEnd === node.from + 1;
  if (isFirst || hasCommaBetween(text, previousEnd, offset)) {
    return {position: 'key', pointer: null, parentPointer: pointer, keyPrefix: '', range: {from: offset, to: offset},
      hasColon: false, node: null, existingKeys: keys};
  }
  return {...between(pointer, offset, node), existingKeys: keys, afterMember: true};
}

function arrayContext(node, text, offset, pointer) {
  let previousEnd = node.from + 1;
  let index = 0;
  for (; index < node.items.length; index += 1) {
    const item = node.items[index];
    if (contains(item, offset)) {
      return locate(item, text, offset, `${pointer}/${index}`, pointer, undefined);
    }
    if (offset <= item.from) {
      break;
    }
    previousEnd = item.to;
  }
  if (index === 0 || hasCommaBetween(text, previousEnd, offset)) {
    const context = emptyValue(offset, `${pointer}/${index}`, pointer, undefined);
    context.insertIndex = index;
    return context;
  }
  return {...between(pointer, offset, node), afterItem: true};
}

function locate(node, text, offset, pointer, parentPointer, existingKeys) {
  if (node.type === 'object') {
    return objectContext(node, text, offset, pointer);
  }
  if (node.type === 'array') {
    return arrayContext(node, text, offset, pointer);
  }
  return valueContext(node, text, offset, pointer, parentPointer, existingKeys);
}

/**
 * Caret context at an offset:
 *   {position: 'key' | 'value' | 'between', pointer, parentPointer, keyPrefix?, valuePrefix?,
 *    range: {from, to}, existingKeys?, node, hasColon?}
 * For 'key' with pointer null the caret is in an empty property slot of parentPointer.
 */
export function pointerAt(ast, offset) {
  if (ast?.format === 'yaml') return yamlPointerAt(ast, offset);
  const root = rootOf(ast);
  const text = textOf(ast);
  if (!root) {
    return emptyValue(offset, '', null, undefined);
  }
  if (!contains(root, offset)) {
    return between('', offset, root);
  }
  return locate(root, text, offset, '', null, undefined);
}
