// JSON Schema (2020-12 subset) evaluation core: $ref resolution, branch
// flattening, conditional evaluation against instance data and descent along
// JSON pointers. Everything expensive is memoised per schema object.
//
// Schemaxis composition markers ($document, $expr, $value, $axis, $analytic,
// $artifact, ...) are objects with a '$'-prefixed key. Schema branches that
// only describe such markers are "marker branches": they are skipped for
// completion unless asked for, and marker instances are never validated here.

import {parsePointer} from './json-pointer.mjs';
import {
  candidateBranches, contextFor, deepEqual, isMarkerInstance, isMarkerSchema, isObject, typeMatches,
} from './schema-context.mjs';

export {
  candidateBranches, contextFor, deepEqual, discriminatorOf, isMarkerInstance, isMarkerSchema, isObject, typeMatches,
  typeOf,
} from './schema-context.mjs';

const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

function collect(context, schema, includeMarkers, out, seen) {
  if (!isObject(schema) || seen.has(schema)) {
    return;
  }
  seen.add(schema);
  out.nodes.push(schema);
  if (schema.$ref !== undefined) {
    const target = context.resolve(schema);
    collect(context, target, includeMarkers, out, seen);
  }
  for (const branch of schema.allOf || []) {
    collect(context, context.adopt(schema, branch), includeMarkers, out, seen);
  }
  for (const keyword of ['anyOf', 'oneOf']) {
    for (const branch of schema[keyword] || []) {
      context.adopt(schema, branch);
      if (includeMarkers || !isMarkerSchema(context, branch)) {
        collect(context, branch, includeMarkers, out, seen);
      }
    }
  }
  if (schema.if !== undefined) {
    context.adopt(schema, schema.if);
    context.adopt(schema, schema.then);
    context.adopt(schema, schema.else);
    out.conditions.push(schema);
  }
}

/** Flattened applicator closure of a schema, independent of the instance. */
export function staticParts(context, schema, includeMarkers = false) {
  const cache = context.parts[includeMarkers ? 1 : 0];
  let parts = cache.get(schema);
  if (!parts) {
    parts = {nodes: [], conditions: []};
    collect(context, schema, includeMarkers, parts, new Set());
    cache.set(schema, parts);
  }
  return parts;
}

/**
 * Evaluate a conditional's `if` against an instance: true, false, or undefined
 * when the instance is absent or lacks a property the condition requires.
 */
export function evaluateIf(context, schema, instance) {
  if (instance === undefined) {
    return undefined;
  }
  if (isObject(instance) && Array.isArray(schema.required)) {
    if (schema.required.some((key) => !hasOwn(instance, key))) {
      return undefined;
    }
  }
  return matches(context, schema, instance);
}

function constConflicts(node, instance) {
  if (!isObject(instance) || !node.properties) {
    return false;
  }
  for (const key in node.properties) {
    const property = node.properties[key];
    if (isObject(property) && hasOwn(property, 'const') && hasOwn(instance, key)) {
      const value = instance[key];
      if (!isMarkerInstance(value) && !deepEqual(value, property.const)) {
        return true;
      }
    }
  }
  return false;
}

/**
 * Schema nodes that apply to an instance (undefined = unknown, e.g. while it is
 * being typed). Conditionals are evaluated; unknown conditions keep both sides.
 */
export function expand(context, schema, instance, includeMarkers = false, out = [], seen = new Set()) {
  if (!isObject(schema)) {
    return out;
  }
  const markers = includeMarkers || isMarkerInstance(instance);
  const parts = staticParts(context, schema, markers);
  for (const node of parts.nodes) {
    if (seen.has(node)) {
      continue;
    }
    if (instance !== undefined && node.type !== undefined && !typeMatches(node.type, instance)) {
      continue;
    }
    if (constConflicts(node, instance)) {
      continue;
    }
    seen.add(node);
    out.push(node);
  }
  for (const condition of parts.conditions) {
    const result = evaluateIf(context, condition.if, instance);
    if (result !== false) {
      expand(context, condition.then, instance, includeMarkers, out, seen);
    }
    if (result !== true) {
      expand(context, condition.else, instance, includeMarkers, out, seen);
    }
  }
  return out;
}

/** Child schemas of a set of nodes for one pointer segment. */
export function childSchemas(context, nodes, segment) {
  const result = [];
  const isIndex = /^(0|[1-9]\d*)$/.test(segment);
  for (const node of nodes) {
    let matched = false;
    if (node.properties && hasOwn(node.properties, segment)) {
      result.push(context.adopt(node, node.properties[segment]));
      matched = true;
    }
    if (node.patternProperties) {
      for (const [pattern, child] of Object.entries(node.patternProperties)) {
        const regex = context.regex(pattern);
        if (regex && regex.test(segment)) {
          result.push(context.adopt(node, child));
          matched = true;
        }
      }
    }
    if (!matched && isObject(node.additionalProperties)) {
      result.push(context.adopt(node, node.additionalProperties));
    }
    if (isIndex) {
      const index = Number(segment);
      if (Array.isArray(node.prefixItems) && index < node.prefixItems.length) {
        result.push(context.adopt(node, node.prefixItems[index]));
      } else if (isObject(node.items)) {
        result.push(context.adopt(node, node.items));
      }
    }
  }
  return result;
}

function childInstance(instance, segment) {
  if (Array.isArray(instance)) {
    return /^(0|[1-9]\d*)$/.test(segment) ? instance[Number(segment)] : undefined;
  }
  if (isObject(instance) && hasOwn(instance, segment)) {
    return instance[segment];
  }
  return undefined;
}

/**
 * Schema nodes applying at `pointer` of a document.
 * Options: {editing: true} treats the value at the pointer as being typed (absent),
 * {includeMarkers: true} keeps composition-marker branches at the final step.
 */
export function schemasAt(rootSchema, documentValue, pointer, options = {}) {
  const context = contextFor(rootSchema);
  const segments = parsePointer(pointer || '');
  const instances = [documentValue];
  for (const segment of segments) {
    instances.push(childInstance(instances[instances.length - 1], segment));
  }
  if (options.editing && segments.length > 0) {
    const last = segments[segments.length - 1];
    const parent = instances[instances.length - 2];
    if (isObject(parent) && hasOwn(parent, last)) {
      const copy = {...parent};
      delete copy[last];
      instances[instances.length - 2] = copy;
    }
    instances[instances.length - 1] = undefined;
  }
  const last = segments.length;
  let nodes = expand(context, rootSchema, instances[0], options.includeMarkers && last === 0);
  for (let index = 0; index < last && nodes.length > 0; index += 1) {
    const children = childSchemas(context, nodes, segments[index]);
    const instance = instances[index + 1];
    const markers = options.includeMarkers && index === last - 1;
    const seen = new Set();
    nodes = [];
    for (const child of children) {
      expand(context, child, instance, markers, nodes, seen);
    }
  }
  return nodes;
}

function matchesObject(context, schema, instance) {
  if (Array.isArray(schema.required) && !schema.required.every((key) => hasOwn(instance, key))) {
    return false;
  }
  const properties = schema.properties || {};
  for (const key in instance) {
    if (hasOwn(properties, key)) {
      if (!matches(context, context.adopt(schema, properties[key]), instance[key])) {
        return false;
      }
    } else if (schema.additionalProperties === false && !schema.patternProperties) {
      return false;
    } else if (isObject(schema.additionalProperties) && !schema.patternProperties) {
      if (!matches(context, context.adopt(schema, schema.additionalProperties), instance[key])) {
        return false;
      }
    }
  }
  return true;
}

function matchesArray(context, schema, instance) {
  if (schema.minItems !== undefined && instance.length < schema.minItems) {
    return false;
  }
  if (schema.maxItems !== undefined && instance.length > schema.maxItems) {
    return false;
  }
  const prefix = Array.isArray(schema.prefixItems) ? schema.prefixItems : [];
  for (let index = 0; index < instance.length; index += 1) {
    const item = index < prefix.length ? prefix[index] : schema.items;
    if (item === false) {
      return false;
    }
    if (isObject(item) && !matches(context, context.adopt(schema, item), instance[index])) {
      return false;
    }
  }
  return true;
}

/** JSON Schema counts Unicode code points, rather than UTF-16 code units. */
export function stringLength(value) {
  let length = 0;
  for (const character of value) length += 1;
  return length;
}

function matchesString(schema, value) {
  if (schema.minLength === undefined && schema.maxLength === undefined) return true;
  const length = stringLength(value);
  return !(schema.minLength !== undefined && length < schema.minLength)
    && !(schema.maxLength !== undefined && length > schema.maxLength);
}

function matchesNumber(schema, value) {
  if (schema.minimum !== undefined && value < schema.minimum) {
    return false;
  }
  if (schema.maximum !== undefined && value > schema.maximum) {
    return false;
  }
  if (schema.exclusiveMinimum !== undefined && value <= schema.exclusiveMinimum) {
    return false;
  }
  return !(schema.exclusiveMaximum !== undefined && value >= schema.exclusiveMaximum);
}

/** Boolean validation used to pick branches. Unsupported keywords pass. */
export function matches(context, schema, instance) {
  if (schema === true || schema === undefined) {
    return true;
  }
  if (schema === false) {
    return false;
  }
  if (!isObject(schema)) {
    return true;
  }
  if (schema.$ref !== undefined && !matches(context, context.resolve(schema), instance)) {
    return false;
  }
  if (schema.type !== undefined && !typeMatches(schema.type, instance)) {
    return false;
  }
  if (hasOwn(schema, 'const') && !deepEqual(schema.const, instance)) {
    return false;
  }
  if (Array.isArray(schema.enum) && !schema.enum.some((option) => deepEqual(option, instance))) {
    return false;
  }
  if (typeof instance === 'number' && !matchesNumber(schema, instance)) {
    return false;
  }
  if (typeof instance === 'string' && !matchesString(schema, instance)) {
    return false;
  }
  if (isObject(instance) && !matchesObject(context, schema, instance)) {
    return false;
  }
  if (Array.isArray(instance) && !matchesArray(context, schema, instance)) {
    return false;
  }
  const adopt = (branch) => context.adopt(schema, branch);
  if (schema.allOf && !schema.allOf.every((branch) => matches(context, adopt(branch), instance))) {
    return false;
  }
  for (const keyword of ['anyOf', 'oneOf']) {
    if (schema[keyword]) {
      const branches = candidateBranches(context, schema, keyword, instance);
      if (!branches.some((branch) => matches(context, adopt(branch), instance))) {
        return false;
      }
    }
  }
  if (schema.not !== undefined && matches(context, adopt(schema.not), instance)) {
    return false;
  }
  if (schema.if !== undefined) {
    const branch = matches(context, adopt(schema.if), instance) ? schema.then : schema.else;
    return matches(context, adopt(branch), instance);
  }
  return true;
}
