// Diagnostics: map pointer-based messages to text ranges, and summarise them
// per line for the gutter. Pure functions (no DOM).

import {rangeOfPointer, parsePointer, formatPointer} from './json-pointer.mjs';
import {lineOfOffset} from './highlight.mjs';
import {documentValue} from './json-parse.mjs';

const SEVERITY_RANK = {error: 3, warning: 2, info: 1};

/** Host fault locations may be JSON paths, JSON pointers or declared node IDs. */
export function locationPointer(location, value) {
  if (!location || location === '$') return '';
  if (location.startsWith('/')) return location;
  const parts = location.replace(/^\$\.?/, '').replace(/\[(\d+)\]/g, '.$1').split('.');
  const index = value?.nodes?.findIndex((node) => node.id === parts[0]) ?? -1;
  if (index >= 0) {
    parts.shift();
    const node = value.nodes[index];
    const group = Object.hasOwn(node.options || {}, parts[0]) ? 'options'
      : Object.hasOwn(node.inputs || {}, parts[0]) ? 'inputs' : null;
    parts.unshift('nodes', String(index), ...(group ? [group] : []));
  }
  return formatPointer(parts);
}

/** Text range for a pointer; falls back to the nearest existing ancestor. */
export function rangeForPointer(ast, pointer, preferKey = false) {
  let segments = parsePointer(pointer || '');
  let range = null;
  for (;;) {
    range = rangeOfPointer(ast, formatPointer(segments));
    if (range || segments.length === 0) {
      break;
    }
    segments = segments.slice(0, -1);
    preferKey = true;
  }
  if (!range) {
    const length = ast.text ? ast.text.length : 0;
    return {from: 0, to: Math.min(1, length)};
  }
  const node = range.node;
  const isContainer = node && (node.type === 'object' || node.type === 'array');
  if (range.keyFrom !== undefined && (preferKey || isContainer)) {
    return {from: range.keyFrom, to: range.keyTo};
  }
  if (isContainer) {
    return {from: node.from, to: node.from + 1};
  }
  return {from: range.from, to: range.to};
}

/** Give empty ranges one visible character. */
export function visibleRange(text, from, to) {
  const start = Math.max(0, Math.min(from, text.length));
  let end = Math.max(start, Math.min(to, text.length));
  if (end > start) {
    return {from: start, to: end};
  }
  if (start < text.length && text[start] !== '\n') {
    end = start + 1;
    return {from: start, to: end};
  }
  return start > 0 ? {from: start - 1, to: start} : {from: start, to: start};
}

/**
 * Resolve diagnostics to {from, to, message, severity, source, pointer?}.
 * Entries with a pointer are mapped through the AST; others keep their offsets.
 */
export function resolveDiagnostics(ast, diagnostics, source) {
  const text = ast.text || '';
  const expanded = diagnostics.flatMap((item) => item.code === 'UNFILLED_VALUES' && item.observed?.values
    ? item.observed.values.map((field) => ({...item, pointer: field.pointer,
      message: `${field.label} (${field.type}) needs a value.`, source: 'fill'})) : [item]);
  return expanded.map((diagnostic) => {
    let range;
    const pointer = diagnostic.pointer ?? (diagnostic.location !== undefined
      ? locationPointer(diagnostic.location, documentValue(ast)) : undefined);
    if (source === 'external' && (diagnostic.code === 'INVALID_JSON' || diagnostic.pointer === undefined && !Object.hasOwn(diagnostic, 'sourcePointer')) && Number.isInteger(diagnostic.offset)) {
      // Python reports Unicode code points; textarea selections use UTF-16 units.
      const from = Array.from(text).slice(0, diagnostic.offset).join('').length;
      range = {from, to: from + 1};
    } else if (typeof pointer === 'string' && (diagnostic.from === undefined || diagnostic.to === undefined)) {
      const preferKey = /^(Missing required|Property)/.test(diagnostic.message || '');
      range = rangeForPointer(ast, pointer, preferKey);
    } else {
      range = {from: diagnostic.from || 0, to: diagnostic.to === undefined ? diagnostic.from || 0 : diagnostic.to};
    }
    const visible = visibleRange(text, range.from, range.to);
    const line = text.slice(0, visible.from).split('\n').length;
    const column = visible.from - text.lastIndexOf('\n', visible.from - 1);
    return {
      ...diagnostic,
      line, column,
      address: pointer === undefined ? diagnostic.location || '$' : pointer || '$',
      pointer,
      from: visible.from,
      to: visible.to,
      severity: diagnostic.severity || 'error',
      source: diagnostic.source || source,
    };
  });
}

/** Gutter marks: Map(line -> {severity, messages}). */
export function lineMarks(diagnostics, lineStarts, mapOffset = (offset) => offset) {
  const marks = new Map();
  for (const diagnostic of diagnostics) {
    const line = lineOfOffset(lineStarts, mapOffset(diagnostic.from));
    const mark = marks.get(line) || {severity: 'info', messages: []};
    if ((SEVERITY_RANK[diagnostic.severity] || 0) > (SEVERITY_RANK[mark.severity] || 0)) {
      mark.severity = diagnostic.severity;
    }
    mark.messages.push(diagnostic.message);
    marks.set(line, mark);
  }
  return marks;
}

/** Diagnostics covering an offset. */
export function diagnosticsAt(diagnostics, offset) {
  return diagnostics.filter((diagnostic) => diagnostic.from <= offset && offset < diagnostic.to);
}

/** The changed region between two texts: {from, oldTo, newTo}, or null when equal. */
export function changedRange(before, after) {
  if (before === after) {
    return null;
  }
  const limit = Math.min(before.length, after.length);
  let start = 0;
  while (start < limit && before.charCodeAt(start) === after.charCodeAt(start)) {
    start += 1;
  }
  let oldEnd = before.length;
  let newEnd = after.length;
  while (oldEnd > start && newEnd > start && before.charCodeAt(oldEnd - 1) === after.charCodeAt(newEnd - 1)) {
    oldEnd -= 1;
    newEnd -= 1;
  }
  return {from: start, oldTo: oldEnd, newTo: newEnd};
}

/** Move diagnostics through an edit so squiggles stay on their text until re-analysis. */
export function shiftDiagnostics(diagnostics, change) {
  if (!change) {
    return diagnostics;
  }
  const delta = change.newTo - change.oldTo;
  const move = (offset) => {
    if (offset <= change.from) {
      return offset;
    }
    return offset >= change.oldTo ? offset + delta : change.from;
  };
  return diagnostics.map((diagnostic) => ({...diagnostic, from: move(diagnostic.from), to: move(diagnostic.to)}))
    .filter((diagnostic) => diagnostic.to > diagnostic.from);
}
