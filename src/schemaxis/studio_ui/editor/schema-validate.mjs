// Copyright (C) 2026 David L F Gaden
// Light, conservative schema validation for editor squiggles. The server is
// authoritative; this only reports problems it can attribute unambiguously:
// type, const/enum, required, additionalProperties and numeric/array/string bounds.
// When several anyOf/oneOf branches remain plausible it stays silent.

import {escapeSegment} from './json-pointer.mjs';
import {
  candidateBranches, contextFor, deepEqual, discriminatorOf as discriminatorIndex, evaluateIf, isMarkerInstance,
  isMarkerSchema, isObject, matches, staticParts, stringLength, typeMatches, typeOf,
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

const hasKeyword = (schema, keyword) => isObject(schema) && schema[keyword] !== undefined;

/**
 * Property names a schema can accept. Deliberately a superset: the node's own `properties` plus those of every
 * applicator child ($ref, allOf/anyOf/oneOf, then/else), so a key declared anywhere in the local tree is never
 * treated as forbidden.
 */
function declaredKeys(context, schema, depth = 0, names = new Set()) {
  if (!isObject(schema) || depth > 12) {
    return names;
  }
  if (isObject(schema.properties)) {
    Object.keys(schema.properties).forEach((key) => names.add(key));
  }
  if (schema.$ref !== undefined) {
    declaredKeys(context, context.resolve(schema), depth + 1, names);
  }
  for (const keyword of ['allOf', 'anyOf', 'oneOf']) {
    for (const branch of Array.isArray(schema[keyword]) ? schema[keyword] : []) {
      declaredKeys(context, context.adopt(schema, branch), depth + 1, names);
    }
  }
  for (const keyword of ['then', 'else']) {
    declaredKeys(context, context.adopt(schema, schema[keyword]), depth + 1, names);
  }
  return names;
}

/**
 * Does the schema certainly reject a field that is present in the instance because a closed object
 * (`additionalProperties: false`, no `patternProperties`) does not declare it? Anything uncertain answers
 * false, so a branch is only excluded when it cannot apply. `only` restricts the question to one key.
 * (Instances carrying `$` marker keys never reach this code: `check` skips them first.)
 */
function forbidsPresentKey(context, schema, instance, only = null, depth = 0) {
  if (!isObject(schema) || !isObject(instance) || depth > 12) {
    return false;
  }
  const next = (child) => forbidsPresentKey(context, context.adopt(schema, child), instance, only, depth + 1);
  if (schema.additionalProperties === false && !schema.patternProperties) {
    const allowed = declaredKeys(context, schema);
    for (const key of Object.keys(instance)) {
      if (!allowed.has(key) && (only === null || key === only)) {
        return true;
      }
    }
  }
  if (schema.$ref !== undefined && forbidsPresentKey(context, context.resolve(schema), instance, only, depth + 1)) {
    return true;
  }
  if (Array.isArray(schema.allOf) && schema.allOf.some(next)) {
    return true;
  }
  for (const keyword of ['anyOf', 'oneOf']) {
    if (Array.isArray(schema[keyword])) {
      const alternatives = schema[keyword].filter((branch) => !isMarkerSchema(context, context.adopt(schema, branch)));
      if (alternatives.length && alternatives.every(next)) {
        return true;
      }
    }
  }
  if (schema.if !== undefined) {
    const result = evaluateIf(context, context.adopt(schema, schema.if), instance);
    if (result === true) {
      return next(schema.then);
    }
    if (result === false) {
      return next(schema.else);
    }
    return next(schema.then) && (schema.else === false || next(schema.else));
  }
  return false;
}

const ANNOTATION = /^(x-|\$comment$|title$|description$)/;

/** A value set a tag may take: a const, an enum, or the const-or-marker `anyOf` that generated schemas emit. */
function isTagValueSet(schema) {
  if (!isObject(schema) || !Object.keys(schema).every((name) => ['const', 'enum', 'anyOf'].includes(name) || ANNOTATION.test(name))) {
    return false;
  }
  const valueBranch = (branch) => isObject(branch) && Object.keys(branch).length === 1 && (hasOwn(branch, 'const') || Array.isArray(branch.enum));
  const markerBranch = (branch) => isObject(branch) && Object.keys(branch).length === 1 && branch.type === 'object';
  if (hasOwn(schema, 'const') || Array.isArray(schema.enum)) {
    return !hasOwn(schema, 'anyOf');
  }
  return Array.isArray(schema.anyOf) && schema.anyOf.some(valueBranch)
    && schema.anyOf.every((branch) => valueBranch(branch) || markerBranch(branch));
}

/**
 * The tag key of a pure tag condition, else null. Pure means `required` is exactly the tag key and `properties`
 * has exactly that key with a value set, beside at most `type: "object"` and annotations. Anything else could fail
 * for a reason other than the tag, so it must not be used to call a tag value unknown.
 */
function pureTagKey(condition) {
  if (!isObject(condition) || !Array.isArray(condition.required) || condition.required.length !== 1
    || !isObject(condition.properties)) {
    return null;
  }
  const key = condition.required[0];
  if (Object.keys(condition.properties).length !== 1 || !hasOwn(condition.properties, key)) {
    return null;
  }
  for (const name of Object.keys(condition)) {
    if (name === 'properties' || name === 'required' || ANNOTATION.test(name) || (name === 'type' && condition.type === 'object')) {
      continue;
    }
    return null;
  }
  return isTagValueSet(condition.properties[key]) ? key : null;
}

/**
 * A tag-like branch (`if` on one required key with properties, `else: false`) whose condition is NOT a pure tag, whose tag
 * field is present, and whose full condition did not hold: the instance may be an invalid form of that branch, so nothing can
 * be attributed. A branch whose condition does hold is positively selected and reports its own errors instead.
 */
function hasImpureTaggedBranch(context, viable, instance) {
  return isObject(instance) && viable.some((branch) => isObject(branch) && isObject(branch.if) && branch.else === false
    && Array.isArray(branch.if.required) && branch.if.required.length === 1 && isObject(branch.if.properties)
    && pureTagKey(branch.if) === null && hasOwn(instance, branch.if.required[0])
    && !selectedByCondition(context, branch, instance));
}

/** A conditional branch whose `if` is certainly satisfied by the instance (its discriminator is present and matches). */
function selectedByCondition(context, branch, instance) {
  return hasKeyword(branch, 'if') && evaluateIf(context, context.adopt(branch, branch.if), instance) === true;
}

/**
 * Narrow several plausible alternatives without guessing: a positively selected conditional branch wins; otherwise
 * branches that forbid a present field are set aside. When that would leave nothing, or several remain,
 * the original set is kept so the caller stays silent.
 *
 * Precedence rule (intentional, not ambiguity handling): this only runs after no whole alternative matched the
 * instance. A conditional branch whose condition is certainly true dominates every other plausible alternative, even an
 * open untagged one that also admits the tag, because the instance itself declared which branch it means; the tagged
 * branch's errors are then reported instead of staying silent. Pinned by a test in editor-alternatives-validation.
 */
function narrowCandidates(context, candidates, instance) {
  let pool = candidates;
  const selected = pool.filter((branch) => selectedByCondition(context, branch, instance));
  if (selected.length) {
    pool = selected;
  }
  if (pool.length > 1) {
    const open = pool.filter((branch) => !forbidsPresentKey(context, branch, instance));
    if (open.length) {
      pool = open;
    }
  }
  return pool;
}

/**
 * Strictly tagged (if/then, else: false) alternatives beside untagged ones: the tag is present, no tagged branch
 * accepts its value, and every untagged branch is a closed object that does not declare the tag field.
 */
function unknownTag(context, viable, instance) {
  const tagged = viable.filter((branch) => isObject(branch) && branch.else === false && pureTagKey(branch.if) !== null);
  if (!tagged.length || tagged.length === viable.length || !isObject(instance)) {
    return null;
  }
  const key = pureTagKey(tagged[0].if);
  if (tagged.some((branch) => pureTagKey(branch.if) !== key) || typeof instance[key] !== 'string') {
    return null;
  }
  if (tagged.some((branch) => selectedByCondition(context, branch, instance))) {
    return null;
  }
  const untagged = viable.filter((branch) => !tagged.includes(branch));
  return untagged.every((branch) => forbidsPresentKey(context, branch, instance, key)) ? key : null;
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
    } else if (typeof instance === 'string') {
      this.checkString(schema, instance, pointer);
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

  checkString(schema, value, pointer) {
    if (schema.minLength === undefined && schema.maxLength === undefined) return;
    const length = stringLength(value);
    if (schema.minLength !== undefined && length < schema.minLength) {
      this.report(pointer, `Expected at least ${schema.minLength} character${schema.minLength === 1 ? '' : 's'}`);
    }
    if (schema.maxLength !== undefined && length > schema.maxLength) {
      this.report(pointer, `Expected at most ${schema.maxLength} character${schema.maxLength === 1 ? '' : 's'}`);
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
    if (viable.length > 1 && hasImpureTaggedBranch(context, viable, instance)) {
      return;
    }
    const tag = viable.length > 1 ? unknownTag(context, viable, instance) : null;
    if (tag !== null) {
      this.report(`${pointer}/${escapeSegment(tag)}`, `Unknown ${tag} "${instance[tag]}"`);
      return;
    }
    let candidates = viable.length === 1 ? viable : viable.filter((branch) => plausible(context, branch, instance));
    if (candidates.length > 1) {
      candidates = narrowCandidates(context, candidates, instance);
    }
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
