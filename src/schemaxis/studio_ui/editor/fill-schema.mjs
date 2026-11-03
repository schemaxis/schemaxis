// Copyright (C) 2026 David L F Gaden
// Schema-directed field creation and expression admission. No invented adaptor grammar.
import {contextFor, expand, schemasAt, childSchemas, matches} from './schema-core.mjs';
import {escapeSegment, parsePointer, formatPointer} from './json-pointer.mjs';
import {validate} from './schema-validate.mjs';
import {atPointer, replacing, isFill} from './fill-data.mjs';

export const EXPRESSION_KEYS = [
  '$document', '$value', '$axis', '$analytic', '$expr', '$observe', '$sample', '$calc', '$call',
];

export function expressionNodes(schema, value, pointer) {
  if (!schema) return [];
  return schemasAt(schema, value, pointer, {editing: true, includeMarkers: true});
}

export function expressionKinds(schema, value, pointer) {
  const nodes = expressionNodes(schema, value, pointer);
  return EXPRESSION_KEYS.filter((key) => nodes.some((node) => node.properties?.[key]));
}

export function fieldFromSchemas(name, nodes, required = true, includeValues = false) {
  const literal = nodes.filter((node) => !Object.keys(node.properties || {}).some((key) => key.startsWith('$')));
  const types = literal.flatMap((node) => [].concat(node.type || []));
  const values = literal.flatMap((node) => node.enum || (Object.hasOwn(node, 'const') ? [node.const] : []));
  const type = values.length ? 'enum' : ['string', 'integer', 'number', 'boolean'].find((type) => types.includes(type));
  const field = {$fill: name, label: name, type: type || 'json', required};
  if (values.length && includeValues) field.values = [...new Set(values)];
  for (const key of ['minimum', 'maximum', 'minLength', 'maxLength', 'pattern']) {
    const node = literal.find((node) => node[key] !== undefined);
    if (node) field[key] = node[key];
  }
  return field;
}

export function propertyFill(name, nodes, required) {
  const fixed = nodes.find((node) => Object.hasOwn(node, 'default'));
  const constants = nodes.filter((node) => Object.hasOwn(node, 'const'));
  if (fixed) return fixed.default;
  if (constants.length === 1) return constants[0].const;
  return fieldFromSchemas(name, nodes, required);
}

export function missingProperties(schema, value, pointer, {common = []} = {}) {
  if (!schema) return [];
  const instance = atPointer(value, pointer) ?? {};
  if (!instance || typeof instance !== 'object' || Array.isArray(instance)) return [];
  const context = contextFor(schema);
  const entries = new Map();
  for (const node of schemasAt(schema, value, pointer, {editing: isFill(instance)})) {
    for (const [key, child] of Object.entries(node.properties || {})) {
      if (Object.hasOwn(instance, key) || key.startsWith('$')) continue;
      const required = node.required?.includes(key) || false;
      if (!required && !common.includes(key)) continue;
      const nodes = expand(context, context.adopt(node, child), undefined);
      const old = entries.get(key);
      const field = fieldFromSchemas(key, nodes, required || old?.required || false);
      entries.set(key, {key, required: field.required, pointer: `${pointer}/${escapeSegment(key)}`, value: field});
    }
  }
  return [...entries.values()].sort((a, b) => Number(b.required) - Number(a.required));
}

// The general editor validator is conservative; a form can enforce string/collection constraints too.
function accepts(context, schema, value, depth = 0) {
  if (!matches(context, schema, value)) return false;
  if (!schema || typeof schema !== 'object' || depth > 100) return true;
  const child = (branch, instance = value) => accepts(context, context.adopt(schema, branch), instance, depth + 1);
  if (schema.$ref && !accepts(context, context.resolve(schema), value, depth + 1)) return false;
  if (typeof value === 'string') {
    if (schema.minLength !== undefined && [...value].length < schema.minLength) return false;
    if (schema.maxLength !== undefined && [...value].length > schema.maxLength) return false;
    if (schema.pattern && !context.regex(schema.pattern)?.test(value)) return false;
  }
  if (Array.isArray(value)) {
    if (schema.uniqueItems && new Set(value.map((item) => JSON.stringify(item))).size !== value.length) return false;
    for (let index = 0; index < value.length; index += 1) {
      const item = schema.prefixItems?.[index] ?? schema.items;
      if (item !== undefined && !child(item, value[index])) return false;
    }
  } else if (value && typeof value === 'object') {
    for (const [key, instance] of Object.entries(value)) {
      if (schema.properties?.[key] && !child(schema.properties[key], instance)) return false;
    }
  }
  if (schema.allOf && !schema.allOf.every((branch) => child(branch))) return false;
  for (const key of ['anyOf', 'oneOf']) {
    if (schema[key] && !schema[key].some((branch) => child(branch))) return false;
  }
  if (schema.if) return child(matches(context, context.adopt(schema, schema.if), value) ? schema.then : schema.else);
  return true;
}

export function checkSchemaValue(schema, document, pointer, value) {
  if (!schema) return '';
  const segments = parsePointer(pointer);
  const context = contextFor(schema);
  const roots = segments.length ? childSchemas(context,
    schemasAt(schema, document, formatPointer(segments.slice(0, -1))), segments.at(-1)) : [schema];
  if (roots.length && !roots.some((root) => accepts(context, root, value))) {
    return 'This value does not match the schema at this field.';
  }
  const changed = replacing(document, pointer, value);
  return validate(schema, changed).find((problem) => problem.pointer === pointer
    || problem.pointer.startsWith(`${pointer}/`))?.message || '';
}

export function expressionExample(key) {
  const field = (name, type) => ({$fill: name, label: name, type, required: true});
  return {
    $document: {$document: field('pointer', 'string')},
    $value: {$value: field('function', 'string'), args: {}},
    $axis: {$axis: field('axis', 'axisRef')},
    $analytic: {$analytic: {type: 'linear', start: field('start', 'number'), end: field('end', 'number'), count: 5}},
    $expr: {$expr: {op: 'add', args: [field('left', 'number'), field('right', 'number')]}},
    $observe: {$observe: field('source', 'nodeRef'), path: ['bounds']},
    $sample: {$sample: field('source', 'nodeRef'), association: 'POINTS', field: field('field', 'field'), index: 0},
    $calc: {$calc: 'add', args: [field('left', 'number'), field('right', 'number')]},
    $call: {$call: field('function', 'string'), args: {}},
  }[key];
}
