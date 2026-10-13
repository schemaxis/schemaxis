// Schema hover information for the JSON editor.

import {parsePointer} from './json-pointer.mjs';
import {schemasAt} from './schema-core.mjs';
import {firstAnnotation, firstDefault, typesOf} from './schema-complete.mjs';

const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

function constraintsOf(nodes) {
  const names = ['minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'minLength', 'maxLength',
    'pattern', 'minItems', 'maxItems', 'uniqueItems'];
  const result = {};
  for (const node of nodes) {
    for (const name of names) {
      if (hasOwn(node, name) && !hasOwn(result, name)) {
        result[name] = node[name];
      }
    }
  }
  return result;
}

/** Hover information at a caret context, or null. */
export function hoverAt(rootSchema, documentValue, caret) {
  if (!caret || !caret.pointer || (caret.position !== 'key' && caret.position !== 'value')) {
    return null;
  }
  const nodes = schemasAt(rootSchema, documentValue, caret.pointer);
  if (!nodes.length) {
    return null;
  }
  const key = parsePointer(caret.pointer).pop();
  const parents = schemasAt(rootSchema, documentValue, caret.parentPointer || '');
  const required = parents.some((node) => Array.isArray(node.required) && node.required.includes(key));
  const titles = [...new Set(nodes.map((node) => node.title).filter(Boolean))];
  const enumValues = [];
  for (const node of nodes) {
    if (hasOwn(node, 'const')) {
      enumValues.push(node.const);
    }
    (node.enum || []).forEach((option) => enumValues.push(option));
  }
  const fallback = firstDefault(nodes);
  return {
    pointer: caret.pointer,
    key,
    title: titles[0] || '',
    alternatives: titles.length > 1 ? titles : [],
    description: firstAnnotation(nodes, 'description'),
    type: typesOf(nodes).join(' | '),
    default: fallback ? fallback.value : undefined,
    enum: enumValues.length && enumValues.length <= 50 ? enumValues : undefined,
    constraints: constraintsOf(nodes),
    required,
    range: caret.position !== 'key' && caret.node ? {from: caret.node.from, to: caret.node.to} : caret.range,
  };
}
