// Copyright (C) 2026 David L F Gaden
// Schema evaluation context: memoised $ref resolution (with embedded schema
// resources), discriminator indexes, marker-branch detection and JSON helpers.

import {parsePointer} from './json-pointer.mjs';

const contexts = new WeakMap();
const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

export function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** True for an instance object that carries a '$'-prefixed key. */
export function isMarkerInstance(value) {
  if (!isObject(value)) {
    return false;
  }
  for (const key in value) {
    if (key.charCodeAt(0) === 36) {
      return true;
    }
  }
  return false;
}

/** JSON type name of an instance ('integer' is reported as 'number'). */
export function typeOf(value) {
  if (value === null) {
    return 'null';
  }
  if (Array.isArray(value)) {
    return 'array';
  }
  return typeof value;
}

export function typeMatches(type, value) {
  const types = Array.isArray(type) ? type : [type];
  const actual = typeOf(value);
  for (const name of types) {
    if (name === actual) {
      return true;
    }
    if (name === 'integer' && actual === 'number' && Number.isInteger(value)) {
      return true;
    }
  }
  return false;
}

export function deepEqual(a, b) {
  if (a === b) {
    return true;
  }
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) {
    return false;
  }
  if (Array.isArray(a) !== Array.isArray(b)) {
    return false;
  }
  const keysA = Object.keys(a);
  if (keysA.length !== Object.keys(b).length) {
    return false;
  }
  return keysA.every((key) => hasOwn(b, key) && deepEqual(a[key], b[key]));
}

class SchemaContext {
  constructor(root) {
    this.root = root;
    this.bases = new WeakMap();
    this.refs = new Map();
    this.parts = [new WeakMap(), new WeakMap()];
    this.markers = new WeakMap();
    this.patterns = new Map();
    this.discriminators = new WeakMap();
    this.bases.set(root, root);
  }

  /** Remember the resource base of a child schema reached from `parent`. */
  adopt(parent, child) {
    if (isObject(child) && !this.bases.has(child)) {
      const isResource = hasOwn(child, '$defs') && (hasOwn(child, '$schema') || hasOwn(child, '$id'));
      this.bases.set(child, isResource ? child : this.baseOf(parent));
    }
    return child;
  }

  baseOf(schema) {
    return this.bases.get(schema) || this.root;
  }

  resolve(schema) {
    const ref = schema.$ref;
    const base = this.baseOf(schema);
    let cache = this.refs.get(base);
    if (!cache) {
      cache = new Map();
      this.refs.set(base, cache);
    }
    if (cache.has(ref)) {
      return cache.get(ref);
    }
    let target = walkRef(base, ref);
    let targetBase = base;
    if (target === undefined && base !== this.root) {
      target = walkRef(this.root, ref);
      targetBase = this.root;
    }
    if (isObject(target) && !this.bases.has(target)) {
      const isResource = hasOwn(target, '$defs') && (hasOwn(target, '$schema') || hasOwn(target, '$id'));
      this.bases.set(target, isResource ? target : targetBase);
    }
    cache.set(ref, target);
    return target;
  }

  regex(pattern) {
    if (!this.patterns.has(pattern)) {
      let compiled = null;
      try {
        compiled = new RegExp(pattern, 'u');
      } catch {
        compiled = null;
      }
      this.patterns.set(pattern, compiled);
    }
    return this.patterns.get(pattern);
  }
}

function walkRef(base, ref) {
  if (typeof ref !== 'string' || ref[0] !== '#') {
    return undefined;
  }
  let node = base;
  for (const segment of parsePointer(ref.slice(1))) {
    if (node === null || typeof node !== 'object' || !hasOwn(node, segment)) {
      return undefined;
    }
    node = node[segment];
  }
  return node;
}

/** The memoised evaluation context of a root schema. */
export function contextFor(root) {
  let context = contexts.get(root);
  if (!context) {
    context = new SchemaContext(root);
    contexts.set(root, context);
  }
  return context;
}

function discriminatorConst(condition, key) {
  const property = isObject(condition.properties) ? condition.properties[key] : undefined;
  if (!isObject(property)) {
    return undefined;
  }
  if (hasOwn(property, 'const')) {
    return property.const;
  }
  const options = property.anyOf;
  if (Array.isArray(options) && options.length === 2 && isObject(options[0]) && hasOwn(options[0], 'const')
    && isObject(options[1]) && options[1].type === 'object' && Object.keys(options[1]).length === 1) {
    return options[0].const;
  }
  return undefined;
}

function buildDiscriminator(context, owner, branches) {
  let key = null;
  const map = new Map();
  for (const branch of branches) {
    context.adopt(owner, branch);
    const condition = isObject(branch) ? branch.if : undefined;
    if (!isObject(condition) || branch.else !== false || !Array.isArray(condition.required)
      || condition.required.length !== 1) {
      return null;
    }
    const name = condition.required[0];
    if (key !== null && key !== name) {
      return null;
    }
    key = name;
    const value = discriminatorConst(condition, key);
    if (typeof value !== 'string') {
      return null;
    }
    if (!map.has(value)) {
      map.set(value, []);
    }
    map.get(value).push(branch);
  }
  return key === null || branches.length < 4 ? null : {key, map};
}

/**
 * Index of a discriminated union: anyOf/oneOf whose branches are all
 * {if: {properties: {K: const}, required: [K]}, then, else: false}. Returns {key, map} or null.
 */
export function discriminatorOf(context, owner, keyword) {
  const branches = owner[keyword];
  if (!Array.isArray(branches)) {
    return null;
  }
  if (!context.discriminators.has(branches)) {
    context.discriminators.set(branches, buildDiscriminator(context, owner, branches));
  }
  return context.discriminators.get(branches);
}

/**
 * Branches of owner[keyword] that can apply to the instance. Uses the discriminator
 * index when the instance carries a string discriminator value.
 */
export function candidateBranches(context, owner, keyword, instance) {
  const index = discriminatorOf(context, owner, keyword);
  if (index && isObject(instance) && typeof instance[index.key] === 'string') {
    return index.map.get(instance[index.key]) || [];
  }
  return owner[keyword];
}

/** True when a schema only describes composition markers. */
export function isMarkerSchema(context, schema, depth = 0) {
  if (!isObject(schema) || depth > 32) {
    return false;
  }
  if (context.markers.has(schema)) {
    return context.markers.get(schema);
  }
  context.markers.set(schema, false);
  let result = false;
  if (Array.isArray(schema.required) && schema.required.some((key) => key[0] === '$')) {
    result = true;
  } else if (schema.$ref !== undefined) {
    result = isMarkerSchema(context, context.adopt(schema, context.resolve(schema)), depth + 1);
  } else if (!schema.type && !schema.properties && (schema.anyOf || schema.oneOf)) {
    const branches = schema.anyOf || schema.oneOf;
    result = branches.length > 0
      && branches.every((branch) => isMarkerSchema(context, context.adopt(schema, branch), depth + 1));
  } else if (schema.if !== undefined && schema.else === false) {
    result = isMarkerSchema(context, context.adopt(schema, schema.then), depth + 1);
  }
  context.markers.set(schema, result);
  return result;
}
