// Text model for the text viewer: line index, search and grep extraction.
// Pure logic (no DOM); long jobs are incremental and cancellable.

import {typeTable} from './data-types.mjs';
import {upperIndex} from './virtual.mjs';

const now = () => (globalThis.performance ? performance.now() : Date.now());

/** Yield to the event loop so long jobs never freeze the UI. */
export function defaultYield() {
  if (globalThis.scheduler?.yield) {
    return globalThis.scheduler.yield();
  }
  if (typeof MessageChannel !== 'undefined') {
    return new Promise((resolve) => {
      const channel = new MessageChannel();
      channel.port1.onmessage = () => {
        channel.port1.close();
        resolve();
      };
      channel.port2.postMessage(null);
    });
  }
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function abortError() {
  const error = Error('Cancelled');
  error.name = 'AbortError';
  return error;
}

/**
 * Index a text: lines are separated by \n; a trailing \r is not part of the
 * line; a final newline does not start an extra empty line.
 */
export function createTextDocument(text) {
  let starts = new Uint32Array(1024);
  let count = 0;
  let position = 0;
  let maxLength = 0;
  starts[count++] = 0;
  for (;;) {
    const newline = text.indexOf('\n', position);
    if (newline < 0) {
      break;
    }
    maxLength = Math.max(maxLength, newline - position);
    position = newline + 1;
    if (count === starts.length) {
      const grown = new Uint32Array(starts.length * 2);
      grown.set(starts);
      starts = grown;
    }
    starts[count++] = position;
  }
  maxLength = Math.max(maxLength, text.length - position);
  let finalEnd = text.length;
  if (count > 1 && starts[count - 1] === text.length) {
    count--;
    finalEnd = text.length - 1;
  }
  const lineStart = (i) => starts[i];
  const lineEnd = (i) => {
    let end = i + 1 < count ? starts[i + 1] - 1 : finalEnd;
    if (end > starts[i] && text.charCodeAt(end - 1) === 13) {
      end--;
    }
    return end;
  };
  return {
    text,
    lineCount: count,
    maxLength,
    lineStart,
    lineEnd,
    lineText: (i) => text.slice(starts[i], lineEnd(i)),
    /** Zero-based line containing a UTF-16 offset. */
    lineOf: (offset) => Math.max(0, upperIndex(starts, offset, count)),
  };
}

export function escapeRegex(text) {
  return text.replace(/[\\^$.*+?()[\]{}|/-]/g, '\\$&');
}

/** Global search regex for find. Throws Error('Invalid regular expression: …'). */
export function buildSearch(pattern, {regex = false, caseSensitive = false} = {}) {
  if (!pattern) {
    return null;
  }
  try {
    return new RegExp(regex ? pattern : escapeRegex(pattern), `gm${caseSensitive ? '' : 'i'}`);
  } catch (error) {
    throw Error(`Invalid regular expression: ${error.message.replace(/^Invalid regular expression: /, '')}`);
  }
}

/**
 * Find all non-empty matches incrementally. Returns {starts, ends, truncated}
 * (UTF-16 offsets). onProgress(fraction, count) is called between slices.
 */
export async function findAll(text, search, {budgetMs = 12, signal, onProgress, yieldFn = defaultYield,
  limit = 2_000_000} = {}) {
  const starts = [];
  const ends = [];
  let truncated = false;
  search.lastIndex = 0;
  let deadline = now() + budgetMs;
  for (;;) {
    const match = search.exec(text);
    if (!match) {
      break;
    }
    if (match[0].length === 0) {
      search.lastIndex = match.index + 1;
    } else {
      starts.push(match.index);
      ends.push(match.index + match[0].length);
      if (starts.length >= limit) {
        truncated = true;
        break;
      }
    }
    if (now() > deadline) {
      onProgress?.(search.lastIndex / Math.max(1, text.length), starts.length);
      await yieldFn();
      if (signal?.aborted) {
        throw abortError();
      }
      deadline = now() + budgetMs;
    }
  }
  return {starts, ends, truncated};
}

/**
 * Capture-group column names in order: named groups keep their name, others
 * become "group N" (N = capture number). Character classes and escapes are honoured.
 */
export function captureNames(source) {
  const names = [];
  let inClass = false;
  for (let i = 0; i < source.length; i++) {
    const char = source[i];
    if (char === '\\') {
      i++;
    } else if (inClass) {
      inClass = char !== ']';
    } else if (char === '[') {
      inClass = true;
    } else if (char === '(') {
      if (source[i + 1] !== '?') {
        names.push(`group ${names.length + 1}`);
      } else if (source[i + 2] === '<' && source[i + 3] !== '=' && source[i + 3] !== '!') {
        const end = source.indexOf('>', i + 3);
        names.push(source.slice(i + 3, end));
      }
    }
  }
  return names;
}

function compile(pattern, caseSensitive, what) {
  try {
    return new RegExp(pattern, caseSensitive ? '' : 'i');
  } catch (error) {
    throw Error(`Invalid ${what} pattern: ${error.message.replace(/^Invalid regular expression: /, '')}`);
  }
}

function groupNames(regex) {
  const expected = new RegExp(`${regex.source}|`).exec('').length - 1;
  const names = captureNames(regex.source);
  return names.length === expected ? names : Array.from({length: expected}, (_, i) => `group ${i + 1}`);
}

/**
 * Compile a grep extraction: {pattern, context?, caseSensitive = true, includeLine = true}.
 * Rows come from lines matching `pattern` (one column per capture group, or the
 * whole match when it has none). Groups of `context` (e.g. "^Time = (?<Time>\S+)")
 * are carried forward from the last matching line into following rows.
 */
export function compileExtraction({pattern, context = '', caseSensitive = true, includeLine = true}) {
  if (!pattern) {
    throw Error('Enter a pattern with capture groups, for example: Initial residual = (?<initial>\\S+),');
  }
  const regex = compile(pattern, caseSensitive, 'row');
  const contextRegex = context ? compile(context, caseSensitive, 'context') : null;
  const rowNames = groupNames(regex);
  const contextNames = contextRegex ? groupNames(contextRegex) : [];
  const wholeMatch = rowNames.length === 0;
  const raw = [...(includeLine ? ['line'] : []), ...contextNames, ...(wholeMatch ? ['match'] : rowNames)];
  const seen = new Map();
  const columns = raw.map((name) => {
    const count = (seen.get(name) || 0) + 1;
    seen.set(name, count);
    return count === 1 ? name : `${name}_${count}`;
  });
  return {pattern, context, regex, contextRegex, contextNames, wholeMatch, includeLine, columns};
}

/** Process lines [from, to) into state.rows (string cells), carrying context in state.context. */
export function extractLines(documentModel, extraction, state, from, to) {
  for (let i = from; i < to; i++) {
    const line = documentModel.lineText(i);
    if (extraction.contextRegex) {
      const context = extraction.contextRegex.exec(line);
      if (context) {
        state.context = extraction.contextNames.length ? context.slice(1).map((v) => v ?? '') : [];
      }
    }
    const match = extraction.regex.exec(line);
    if (!match) {
      continue;
    }
    const values = extraction.wholeMatch ? [match[0]] : match.slice(1).map((v) => v ?? '');
    const context = state.context || extraction.contextNames.map(() => '');
    state.rows.push([...(extraction.includeLine ? [String(i + 1)] : []), ...context, ...values]);
  }
}

/**
 * Extract a typed table from a text document without freezing the UI.
 * Resolves to {columns: [{name, type}], rows, source: {pattern, context, lines, matched}}.
 * Results are independent of chunk size and timing.
 */
export async function extractTable(documentModel, spec, {chunkLines = 2000, budgetMs = 12, signal, onProgress,
  yieldFn = defaultYield} = {}) {
  const extraction = compileExtraction(spec);
  const state = {rows: [], context: null};
  let line = 0;
  let deadline = now() + budgetMs;
  while (line < documentModel.lineCount) {
    const end = Math.min(documentModel.lineCount, line + chunkLines);
    extractLines(documentModel, extraction, state, line, end);
    line = end;
    if (line < documentModel.lineCount && now() > deadline) {
      onProgress?.(line / documentModel.lineCount, state.rows.length);
      await yieldFn();
      if (signal?.aborted) {
        throw abortError();
      }
      deadline = now() + budgetMs;
    }
  }
  onProgress?.(1, state.rows.length);
  return finish(extraction, state, documentModel.lineCount);
}

/** Synchronous extraction (small inputs and tests). */
export function extractTableSync(documentModel, spec) {
  const extraction = compileExtraction(spec);
  const state = {rows: [], context: null};
  extractLines(documentModel, extraction, state, 0, documentModel.lineCount);
  return finish(extraction, state, documentModel.lineCount);
}

function finish(extraction, state, lines) {
  const table = typeTable(extraction.columns, state.rows);
  return {
    ...table,
    source: {pattern: extraction.pattern, context: extraction.context || null, lines, matched: state.rows.length},
  };
}
