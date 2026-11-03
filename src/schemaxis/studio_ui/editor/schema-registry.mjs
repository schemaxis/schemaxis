// Copyright (C) 2026 David L F Gaden
// Multi-schema support. A document may embed other documents (workflow
// operations carry adaptor documents); each object with a string `version`
// known to the registry is validated and completed against its own schema.

import {parsePointer, formatPointer, pointerAt} from './json-pointer.mjs';
import {documentValue} from './json-parse.mjs';
import {completionsAt} from './schema-complete.mjs';
import {hoverAt} from './schema-hover.mjs';
import {validate} from './schema-validate.mjs';
import {isObject} from './schema-core.mjs';

const MAX_SCAN_DEPTH = 8;

// Some envelopes refine an embedded version (for example an empty design
// workflow). Keep those objects in their parent's schema scope.
function inlineDocuments(registry, value) {
  const schema = registry?.peek(value?.version);
  return new Set(schema?.['x-schemaxis-inlineDocuments'] || []);
}

/**
 * Schemas by document version. `provider(version)` returns (a promise of) a
 * schema or null. Options: {versions: [...]} limits which versions are known.
 */
export class SchemaRegistry {
  constructor(provider, options = {}) {
    this.provider = provider;
    this.versions = options.versions ? new Set(options.versions) : null;
    this.loaded = new Map();
    this.pending = new Map();
    this.listeners = new Set();
  }

  /** True when the version may have a schema (always true without a version list). */
  knows(version) {
    return typeof version === 'string' && (!this.versions || this.versions.has(version) || this.loaded.has(version));
  }

  /** Register a schema synchronously. */
  register(version, schema) {
    this.loaded.set(version, schema);
    this.pending.delete(version);
    this.listeners.forEach((listener) => listener(version, schema));
  }

  /** The loaded schema for a version, or undefined (null when the provider had none). */
  peek(version) {
    return this.loaded.get(version);
  }

  /** Load (once) and return the schema for a version, or null. */
  schemaFor(version) {
    if (this.loaded.has(version)) {
      return Promise.resolve(this.loaded.get(version));
    }
    if (!this.knows(version)) {
      return Promise.resolve(null);
    }
    if (!this.pending.has(version)) {
      const promise = Promise.resolve()
        .then(() => this.provider(version))
        .catch(() => null)
        .then((schema) => {
          this.register(version, schema || null);
          return schema || null;
        });
      this.pending.set(version, promise);
    }
    return this.pending.get(version);
  }

  /** Subscribe to loads: fn(version, schema). Returns an unsubscribe function. */
  onLoad(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}

/**
 * The schema governing the object at `pointer`: the nearest enclosing object
 * (including the object itself) with a string `version` whose schema is loaded.
 * Unloaded known versions start loading. Returns {schema, base, value} or the
 * fallback {schema: fallbackSchema, base: '', value: rootValue}.
 */
export function resolveSchemaContext(registry, rootValue, pointer, fallbackSchema, options = {}) {
  const inline = inlineDocuments(registry, rootValue);
  const segments = parsePointer(pointer || '');
  const chain = [{value: rootValue, depth: 0}];
  let node = rootValue;
  for (let index = 0; index < segments.length; index += 1) {
    if (node === null || typeof node !== 'object') {
      break;
    }
    node = node[segments[index]];
    chain.push({value: node, depth: index + 1});
  }
  if (registry) {
    for (let index = chain.length - 1; index >= 0; index -= 1) {
      const {value, depth} = chain[index];
      if (inline.has(formatPointer(segments.slice(0, depth)))) continue;
      if (!isObject(value) || typeof value.version !== 'string' || !registry.knows(value.version)) {
        continue;
      }
      const schema = registry.peek(value.version);
      if (schema) {
        return {schema, base: formatPointer(segments.slice(0, depth)), value};
      }
      if (schema === undefined && options.load !== false) {
        registry.schemaFor(value.version);
      }
    }
  }
  return {schema: fallbackSchema || null, base: '', value: rootValue};
}

function rebase(pointer, base) {
  if (pointer === null || pointer === undefined) {
    return pointer;
  }
  return pointer.slice(base.length);
}

function rebaseCaret(caret, base) {
  return {...caret, pointer: rebase(caret.pointer, base), parentPointer: rebase(caret.parentPointer, base)};
}

function caretFor(ast, offset) {
  return pointerAt(ast, offset);
}

/** Completions at an offset using the schema that governs the caret. */
export function completionsFor(registry, ast, offset, fallbackSchema) {
  const caret = caretFor(ast, offset);
  if (caret.position !== 'key' && caret.position !== 'value') {
    return [];
  }
  const value = documentValue(ast);
  const scope = caret.parentPointer === null ? '' : caret.parentPointer;
  const resolved = resolveSchemaContext(registry, value, scope, fallbackSchema);
  if (!resolved.schema) {
    return [];
  }
  const items = completionsAt(resolved.schema, resolved.value, rebaseCaret(caret, resolved.base), ast.text);
  if (ast.format !== 'yaml') return items;
  return items.map(item => {
    if (item.kind !== 'property') return {...item, insertText: item.insertText.replace(/,$/, '')}; // JSON flow values are valid YAML.
    const match = /^("(?:[^"\\]|\\.)*")/.exec(item.insertText);
    if (!match) return item;
    const key = JSON.parse(match[1]);
    const rendered = /^[A-Za-z_$][A-Za-z0-9_$.-]*$/.test(key) ? key : match[1];
    const suffix = item.insertText.slice(match[1].length).replace(/,$/, '');
    const shift = rendered.length - match[1].length;
    return {...item, insertText: rendered + suffix,
      cursor: item.cursor ? {from: item.cursor.from + shift, to: item.cursor.to + shift} : undefined};
  });
}

/** Hover information at an offset using the governing schema. */
export function hoverFor(registry, ast, offset, fallbackSchema) {
  const caret = caretFor(ast, offset);
  if (!caret.pointer || (caret.position !== 'key' && caret.position !== 'value')) {
    return null;
  }
  const value = documentValue(ast);
  const resolved = resolveSchemaContext(registry, value, caret.parentPointer || '', fallbackSchema);
  if (!resolved.schema) {
    return null;
  }
  const hover = hoverAt(resolved.schema, resolved.value, rebaseCaret(caret, resolved.base));
  if (hover) {
    hover.pointer = resolved.base + hover.pointer;
    hover.schemaVersion = resolved.value && resolved.value.version;
  }
  return hover;
}

function findSubDocuments(registry, value, pointer, depth, out, inline) {
  if (depth > MAX_SCAN_DEPTH || value === null || typeof value !== 'object') {
    return;
  }
  if (!inline.has(pointer) && isObject(value) && typeof value.version === 'string' && registry.knows(value.version)) {
    const schema = registry.peek(value.version);
    if (schema === undefined) {
      registry.schemaFor(value.version);
    } else if (schema) {
      out.push({pointer, schema, value});
    }
  }
  const entries = Array.isArray(value) ? value.map((item, index) => [String(index), item]) : Object.entries(value);
  for (const [key, child] of entries) {
    if (child !== null && typeof child === 'object') {
      findSubDocuments(registry, child, formatPointer([...parsePointer(pointer), key]), depth + 1, out, inline);
    }
  }
}

/**
 * Validate a document and every embedded document against its own schema.
 * Returns [{pointer, message, severity}] with absolute pointers.
 */
export function validateDocument(registry, rootValue, fallbackSchema, options = {}) {
  const documents = [];
  if (registry) {
    findSubDocuments(registry, rootValue, '', 0, documents, inlineDocuments(registry, rootValue));
  }
  if (!documents.some((entry) => entry.pointer === '') && fallbackSchema) {
    documents.unshift({pointer: '', schema: fallbackSchema, value: rootValue});
  }
  const results = [];
  for (const entry of documents) {
    const skip = new Set();
    for (const other of documents) {
      if (other !== entry && other.pointer.startsWith(`${entry.pointer}/`)) {
        skip.add(other.pointer.slice(entry.pointer.length));
      }
    }
    for (const error of validate(entry.schema, entry.value, {skip, maxErrors: options.maxErrors})) {
      results.push({...error, pointer: entry.pointer + error.pointer});
    }
  }
  return results;
}
