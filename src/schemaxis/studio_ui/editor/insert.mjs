// Plan text edits that insert JSON values at RFC 6901 pointers while keeping
// the surrounding indentation. Pure functions: the editor applies the edits.
//
//   planInsert(ast, pointer, values, {indent}) -> {from, to, text, select: {from, to}}
//
// `pointer` semantics: '/a/-' appends to array a; '/a/2' inserts before item 2;
// '/a/key' sets (adds or replaces) an object member. Missing containers are
// created. Several values are only allowed for array positions.

import {nodeAtPointer, parsePointer, formatPointer, pointerAt, valueAt} from './json-pointer.mjs';
import {parse, documentValue} from './json-parse.mjs';
import {yamlInsert} from './yaml-parse.mjs';
import {markers} from './insert-fields.mjs';

const INDEX = /^(0|[1-9]\d*)$/;

function lineIndent(text, offset) {
  const start = text.lastIndexOf('\n', offset - 1) + 1;
  const match = /^[ \t]*/.exec(text.slice(start, offset));
  return match ? match[0] : '';
}

function startsLine(text, offset) {
  const start = text.lastIndexOf('\n', offset - 1) + 1;
  return /^[ \t]*$/.test(text.slice(start, offset));
}

/** JSON.stringify with 2-space (or `unit`) indentation, continuation lines prefixed by `indent`. */
export function formatValue(value, indent = '', unit = '  ') {
  const text = JSON.stringify(value, null, unit);
  if (text === undefined) {
    throw new Error('Value is not JSON-serialisable');
  }
  return text.split('\n').join(`\n${indent}`);
}

function childIndent(text, container, children, unit) {
  const first = children[0];
  const at = first ? (first.key ? first.key.from : first.from) : -1;
  if (first && startsLine(text, at)) {
    return lineIndent(text, at);
  }
  return lineIndent(text, container.from) + unit;
}

function isMultiline(text, container) {
  return text.slice(container.from, container.to).includes('\n');
}

function missingContainers(count, value) {
  return Array.from({length: count}, () => Array.isArray(value) ? [] : {});
}

function insertIntoArray(text, array, index, values, unit) {
  const items = array.items;
  const indent = childIndent(text, array, items, unit);
  const parentIndent = lineIndent(text, array.from);
  const formatted = values.map((value) => formatValue(value, indent, unit));
  const multiline = isMultiline(text, array) || items.length === 0;
  const separator = multiline ? `,\n${indent}` : ', ';
  const body = formatted.join(separator);
  if (items.length === 0) {
    const from = array.from + 1;
    const to = array.closed ? array.to - 1 : from;
    const prefix = `\n${indent}`;
    const select = {from: prefix.length, to: prefix.length + body.length};
    return {from, to, text: `${prefix}${body}\n${parentIndent}`, select};
  }
  if (index >= items.length) {
    const at = items[items.length - 1].to;
    const prefix = separator;
    return {from: at, to: at, text: prefix + body, select: {from: prefix.length, to: prefix.length + body.length}};
  }
  const at = items[index].from;
  return {from: at, to: at, text: body + separator, select: {from: 0, to: body.length}};
}

function setMember(text, object, key, value, unit) {
  let existing = null;
  for (const member of object.members) {
    if (member.key.value === key) {
      existing = member;
    }
  }
  if (existing && existing.value) {
    const indent = lineIndent(text, existing.key.from);
    const body = formatValue(value, indent, unit);
    return {from: existing.value.from, to: existing.value.to, text: body, select: {from: 0, to: body.length}};
  }
  const members = object.members;
  const indent = childIndent(text, object, members, unit);
  const parentIndent = lineIndent(text, object.from);
  const entry = `${JSON.stringify(key)}: ${formatValue(value, indent, unit)}`;
  if (members.length === 0) {
    const from = object.from + 1;
    const to = object.closed ? object.to - 1 : from;
    const prefix = `\n${indent}`;
    const select = {from: prefix.length, to: prefix.length + entry.length};
    return {from, to, text: `${prefix}${entry}\n${parentIndent}`, select};
  }
  const multiline = isMultiline(text, object);
  const prefix = multiline ? `,\n${indent}` : ', ';
  const at = members[members.length - 1].to;
  return {from: at, to: at, text: prefix + entry, select: {from: prefix.length, to: prefix.length + entry.length}};
}

/**
 * Plan inserting `values` (array of JSON values) at `pointer` in a parsed document.
 * Returns {from, to, text, select} where select is relative to `text`.
 */
export function planInsert(ast, pointer, values, options = {}) {
  if (ast.format === 'yaml') return yamlInsert(ast, pointer, values, options);
  const unit = options.indent || '  ';
  const text = ast.text;
  const list = Array.isArray(values) ? values : [values];
  const segments = parsePointer(pointer);
  if (segments.length === 0) {
    const body = formatValue(list[0], '', unit);
    return {from: 0, to: text.length, text: body, select: {from: 0, to: body.length}};
  }
  const last = segments[segments.length - 1];
  const parentPointer = formatPointer(segments.slice(0, -1));
  const parent = nodeAtPointer(ast, parentPointer);
  if (!parent) {
    const wrapped = last === '-' || INDEX.test(last)
      ? [...missingContainers(options.creatingContainer && INDEX.test(last) ? Number(last) : 0, list[0]), ...list]
      : {[last]: list[0]};
    if (segments.length === 1 && !ast.root) {
      return planInsert(ast, '', [wrapped], options);
    }
    return planInsert(ast, parentPointer, [wrapped], {...options, creatingContainer: true});
  }
  if (parent.type === 'array') {
    if (last !== '-' && !INDEX.test(last)) {
      throw new Error(`Cannot insert "${last}" into an array`);
    }
    const index = last === '-' ? parent.items.length : Number(last);
    const inserted = options.creatingContainer && index > parent.items.length
      ? [...missingContainers(index - parent.items.length, list[0]), ...list] : list;
    return insertIntoArray(text, parent, index, inserted, unit);
  }
  if (parent.type === 'object') {
    if (list.length !== 1) {
      throw new Error('Only one value can be set on an object member');
    }
    return setMember(text, parent, last, list[0], unit);
  }
  throw new Error(`Cannot insert below a ${parent.type} at ${parentPointer || '/'}`);
}

/** Apply a planned edit to text (for tests and non-DOM callers). */
export function applyEdit(text, edit) {
  return text.slice(0, edit.from) + edit.text + text.slice(edit.to);
}


function mergeValue(current, incoming, pointer, conflicts) {
  const result = structuredClone(current === undefined ? {} : current);
  if (!result || Array.isArray(result) || typeof result !== 'object') {
    throw new Error(`Cannot merge into a non-object at ${pointer || '/'}`);
  }
  for (const [key, value] of Object.entries(incoming)) {
    const path = `${pointer}/${formatPointer([key]).slice(1)}`;
    if (value && typeof value === 'object' && !Array.isArray(value) && !Object.hasOwn(value, '$fill')
        && result[key] && typeof result[key] === 'object' && !Array.isArray(result[key])) {
      result[key] = mergeValue(result[key], value, path, conflicts);
    } else {
      if (Object.hasOwn(result, key) && JSON.stringify(result[key]) !== JSON.stringify(value)) {
        conflicts.push({pointer: path, previous: result[key], value});
      }
      result[key] = structuredClone(value);
    }
  }
  return result;
}

function compatiblePosition(ast, pointer, caret) {
  if (!pointer.endsWith('/-') || !Number.isInteger(caret)) {
    return pointer;
  }
  const parentPath = pointer.slice(0, -2);
  const parent = nodeAtPointer(ast, parentPath);
  if (parent?.type !== 'array') {
    return pointer;
  }
  const index = parent.items.findIndex((item) => caret >= item.from && caret <= item.to);
  return index < 0 ? pointer : `${parentPath}/${index + 1}`;
}

/**
 * Compute a sequence against successive ASTs; the enclosing replacement commits
 * the complete transaction in one undo group while ghosts retain exact ranges.
 */
export function planInserts(ast, inserts, options = {}) {
  if (ast.format === 'yaml') {
    if (ast.diagnostics.length) throw Error('Repair YAML syntax before structured editing');
  } else JSON.parse(ast.text);
  let text = ast.text;
  let caret = options.caret;
  let ranges = [];
  const summaries = [];
  const edits = [];
  const conflicts = [];
  for (const insert of inserts) {
    const current = parse(text, ast.format);
    let pointer = insert.at;
    let edit;
    if (pointer === '@cursor') {
      const context = pointerAt(current, caret ?? 0);
      if (context.position !== 'value' || context.pointer === null || context.pointer === undefined) {
        throw new Error('Place the caret at a JSON value before inserting this snippet.');
      }
      pointer = context.pointer;
      if (current.format !== 'yaml' && context.node && !Object.hasOwn(insert, 'merge')) {
        const formatted = formatValue(insert.values[0], lineIndent(text, context.range.from), options.indent);
        edit = {...context.range, text: formatted};
      }
    } else {
      pointer = compatiblePosition(current, pointer, caret);
    }
    if (!edit) {
      const values = Object.hasOwn(insert, 'merge')
        ? [mergeValue(valueAt(current, pointer), insert.merge, pointer, conflicts)] : insert.values;
      edit = planInsert(current, pointer, values, options);
    }
    edits.push({from: edit.from, to: edit.to, length: edit.text.length});
    const delta = edit.text.length - (edit.to - edit.from);
    ranges = ranges.map((range) => range.to <= edit.from ? range : ({
      from: range.from >= edit.to ? range.from + delta : Math.min(range.from, edit.from),
      to: range.to >= edit.to ? range.to + delta : Math.max(range.to, edit.from + edit.text.length),
    }));
    ranges.push({from: edit.from, to: edit.from + edit.text.length});
    if (insert.at.endsWith('/-') && pointer !== insert.at) {
      caret = edit.from + edit.text.length;
    } else if (Number.isInteger(caret) && caret >= edit.to) {
      caret += delta;
    }
    text = applyEdit(text, edit);
    summaries.push({pointer, count: insert.values?.length || Object.keys(insert.merge || {}).length,
      action: Object.hasOwn(insert, 'merge') ? 'merge' : 'insert'});
  }
  let from = 0;
  let end = ast.text.length;
  let nextEnd = text.length;
  while (from < end && from < nextEnd && ast.text[from] === text[from]) {
    from += 1;
  }
  while (end > from && nextEnd > from && ast.text[end - 1] === text[nextEnd - 1]) {
    end -= 1;
    nextEnd -= 1;
  }
  const before = new Set(markers(documentValue(ast)).map(({marker}) => marker.$fill));
  const pointers = markers(documentValue(parse(text, ast.format))).filter(({marker}) => !before.has(marker.$fill))
    .map((item) => item.pointer);
  return {from, to: end, text: text.slice(from, nextEnd), ghosts: ranges, summaries, conflicts, pointers, edits};
}
