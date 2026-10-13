// Light, conservative schema validation for editor squiggles. The server is
// authoritative; this only reports problems it can attribute unambiguously:
// type, const/enum, required, additionalProperties and numeric/array bounds.
// When several anyOf/oneOf branches remain plausible it stays silent.

import {escapeSegment} from './json-pointer.mjs';
import {
  candidateBranches, contextFor, deepEqual, discriminatorOf as discriminatorIndex, evaluateIf, isMarkerInstance,
  isMarkerSchema, isObject, matches, staticParts, typeMatches, typeOf,
} from './schema-core.mjs';

const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
const MAX_ITEMS_CHECKED = 5000;

function describe(value) {
  const text = JSON.stringify(value);
  return text.length > 40 ? `${text.slice(0, 37)}…` : text;
}

function typeNames(type) {
  return [].concat(type).join(' or ');
}

/** Can this branch possibly describe the instance (type, consts, discriminators)? */
function plausible(context, schema, instance, depth = 0) {
  if (schema === true || schema === undefined) {
    return true;
  }
  if (schema === false || depth > 24) {
    return schema !== false;
  }
  if (!isObject(schema)) {
    return true;
  }
  if (schema.$ref !== undefined && !plausible(context, context.resolve(schema), instance, depth + 1)) {
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
  if (isObject(instance) && schema.properties) {
    for (const key in schema.properties) {
      const property = schema.properties[key];
      if (hasOwn(instance, key) && isObject(property) && hasOwn(property, 'const')
        && !isMarkerInstance(instance[key]) && !deepEqual(property.const, instance[key])) {
        return false;
      }
    }
  }
  const adopt = (branch) => context.adopt(schema, branch);
  if (schema.allOf && !schema.allOf.every((branch) => plausible(context, adopt(branch), instance, depth + 1))) {
    return false;
  }
  for (const keyword of ['anyOf', 'oneOf']) {
    if (schema[keyword]) {
      const all = candidateBranches(context, schema, keyword, instance);
      const branches = all.filter((branch) => !isMarkerSchema(context, adopt(branch)));
      if (all.length === 0) {
        return false;
      }
      if (branches.length && !branches.some((branch) => plausible(context, branch, instance, depth + 1))) {
        return false;
      }
    }
  }
  if (schema.if !== undefined) {
    const result = evaluateIf(context, adopt(schema.if), instance);
    if (result === true) {
      return plausible(context, adopt(schema.then), instance, depth + 1);
    }
    if (result === false) {
      return plausible(context, adopt(schema.else), instance, depth + 1);
    }
  }
  return true;
}

/** The discriminator key shared by a set of conditional branches, if any. */
function discriminatorOf(branches) {
  let key = null;
  for (const branch of branches) {
    const condition = branch && branch.if;
    if (!isObject(condition) || !Array.isArray(condition.required) || condition.required.length !== 1) {
      return null;
    }
    if (key !== null && key !== condition.required[0]) {
      return null;
    }
    key = condition.required[0];
  }
  return key;
}

class Validator {
  constructor(rootSchema, options) {
    this.context = contextFor(rootSchema);
    this.root = rootSchema;
    this.skip = options.skip || null;
    this.limit = options.maxErrors || 200;
    this.errors = [];
  }

  report(pointer, message) {
    if (this.errors.length < this.limit) {
      this.errors.push({pointer, message, severity: 'warning'});
    }
  }

  check(schema, instance, pointer, depth = 0) {
    if (isObject(instance) && typeof instance.$fill === 'string') return;
    if (schema === true || schema === undefined || depth > 200 || this.errors.length >= this.limit) {
      return;
    }
    if (schema === false) {
      this.report(pointer, 'Value is not allowed here');
      return;
    }
    if (!isObject(schema) || isMarkerInstance(instance) || (this.skip && this.skip.has(pointer))) {
      return;
    }
    const context = this.context;
    const adopt = (branch) => context.adopt(schema, branch);
    if (schema.$ref !== undefined) {
      this.check(context.resolve(schema), instance, pointer, depth + 1);
    }
    if (schema.type !== undefined && !typeMatches(schema.type, instance)) {
      this.report(pointer, `Expected ${typeNames(schema.type)}, found ${typeOf(instance)}`);
      return;
    }
    if (hasOwn(schema, 'const') && !deepEqual(schema.const, instance)) {
      this.report(pointer, `Expected ${describe(schema.const)}`);
      return;
    }
    if (Array.isArray(schema.enum) && !schema.enum.some((option) => deepEqual(option, instance))) {
      const shown = schema.enum.slice(0, 6).map(describe).join(', ');
      this.report(pointer, `Expected one of ${shown}${schema.enum.length > 6 ? ', …' : ''}`);
      return;
    }
    if (typeof instance === 'number') {
      this.checkNumber(schema, instance, pointer);
    } else if (Array.isArray(instance)) {
      this.checkArray(schema, instance, pointer, depth);
    } else if (isObject(instance)) {
      this.checkObject(schema, instance, pointer, depth);
    }
    for (const branch of schema.allOf || []) {
      this.check(adopt(branch), instance, pointer, depth + 1);
    }
    for (const keyword of ['anyOf', 'oneOf']) {
      if (schema[keyword]) {
        this.checkAlternatives(schema, keyword, instance, pointer, depth);
      }
    }
    if (schema.if !== undefined) {
      const branch = matches(context, adopt(schema.if), instance) ? schema.then : schema.else;
      if (branch !== false) {
        this.check(adopt(branch), instance, pointer, depth + 1);
      }
    }
  }

  checkNumber(schema, value, pointer) {
    if (schema.minimum !== undefined && value < schema.minimum) {
      this.report(pointer, `Must be at least ${schema.minimum}`);
    } else if (schema.maximum !== undefined && value > schema.maximum) {
      this.report(pointer, `Must be at most ${schema.maximum}`);
    } else if (schema.exclusiveMinimum !== undefined && value <= schema.exclusiveMinimum) {
      this.report(pointer, `Must be greater than ${schema.exclusiveMinimum}`);
    } else if (schema.exclusiveMaximum !== undefined && value >= schema.exclusiveMaximum) {
      this.report(pointer, `Must be less than ${schema.exclusiveMaximum}`);
    }
  }

  checkArray(schema, items, pointer, depth) {
    if (schema.minItems !== undefined && items.length < schema.minItems) {
      this.report(pointer, `Expected at least ${schema.minItems} item${schema.minItems === 1 ? '' : 's'}`);
    }
    if (schema.maxItems !== undefined && items.length > schema.maxItems) {
      this.report(pointer, `Expected at most ${schema.maxItems} item${schema.maxItems === 1 ? '' : 's'}`);
    }
    const prefix = Array.isArray(schema.prefixItems) ? schema.prefixItems : [];
    const count = Math.min(items.length, MAX_ITEMS_CHECKED);
    for (let index = 0; index < count; index += 1) {
      const item = index < prefix.length ? prefix[index] : schema.items;
      if (item === false && index >= prefix.length && prefix.length > 0) {
        this.report(`${pointer}/${index}`, `Expected at most ${prefix.length} items`);
        break;
      }
      if (item !== undefined) {
        this.check(this.context.adopt(schema, item), items[index], `${pointer}/${index}`, depth + 1);
      }
    }
  }

  checkObject(schema, instance, pointer, depth) {
    for (const key of schema.required || []) {
      if (!hasOwn(instance, key)) {
        this.report(pointer, `Missing required property "${key}"`);
      }
    }
    const properties = schema.properties || {};
    for (const key of Object.keys(instance)) {
      const child = `${pointer}/${escapeSegment(key)}`;
      if (hasOwn(properties, key)) {
        this.check(this.context.adopt(schema, properties[key]), instance[key], child, depth + 1);
      } else if (schema.patternProperties) {
        continue;
      } else if (schema.additionalProperties === false) {
        this.report(child, `Property "${key}" is not allowed`);
      } else if (isObject(schema.additionalProperties)) {
        this.check(this.context.adopt(schema, schema.additionalProperties), instance[key], child, depth + 1);
      }
    }
  }

  checkAlternatives(owner, keyword, instance, pointer, depth) {
    const context = this.context;
    const index = discriminatorIndex(context, owner, keyword);
    if (index && isObject(instance) && typeof instance[index.key] === 'string') {
      const branches = index.map.get(instance[index.key]);
      if (!branches) {
        this.report(`${pointer}/${escapeSegment(index.key)}`, `Unknown ${index.key} "${instance[index.key]}"`);
      } else if (branches.length === 1) {
        this.check(branches[0], instance, pointer, depth + 1);
      }
      return;
    }
    const branches = owner[keyword].map((branch) => context.adopt(owner, branch));
    const viable = branches.filter((branch) => !isMarkerSchema(context, branch));
    if (!viable.length || viable.some((branch) => matches(context, branch, instance))) {
      return;
    }
    const candidates = viable.length === 1 ? viable : viable.filter((branch) => plausible(context, branch, instance));
    if (candidates.length === 1) {
      this.check(candidates[0], instance, pointer, depth + 1);
      return;
    }
    if (candidates.length > 1) {
      return;
    }
    const key = discriminatorOf(viable);
    if (key !== null && isObject(instance)) {
      if (!hasOwn(instance, key)) {
        this.report(pointer, `Missing required property "${key}"`);
      } else if (typeof instance[key] === 'string') {
        this.report(`${pointer}/${escapeSegment(key)}`, `Unknown ${key} "${instance[key]}"`);
      }
      return;
    }
    const types = new Set();
    for (const branch of viable) {
      for (const node of staticParts(context, branch).nodes) {
        if (node.type === undefined && !hasOwn(node, 'const') && !node.enum && !node.$ref && !node.anyOf
          && !node.oneOf && !node.allOf && node.if === undefined) {
          return;
        }
        if (node.type !== undefined) {
          [].concat(node.type).forEach((type) => types.add(type));
        }
      }
    }
    if (types.size && ![...types].some((type) => typeMatches(type, instance))) {
      this.report(pointer, `Expected ${[...types].join(' or ')}, found ${typeOf(instance)}`);
    }
  }
}

/**
 * Validate a JSON value: [{pointer, message, severity: 'warning'}].
 * Options: {skip: Set<pointer>} leaves sub-documents to another schema; {maxErrors}.
 */
export function validate(rootSchema, value, options = {}) {
  if (value === undefined) {
    return [];
  }
  const validator = new Validator(rootSchema, options);
  validator.check(rootSchema, value, '');
  return validator.errors;
}
