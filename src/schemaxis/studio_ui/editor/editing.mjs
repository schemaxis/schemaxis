// Copyright (C) 2026 David L F Gaden
// Pure editing rules for the JSON editor: auto-indent, auto-close with
// type-over, pair deletion and block indent/outdent. Each function returns an
// edit {from, to, text, selectFrom, selectTo} (absolute offsets after the edit)
// or null to let the textarea do its default.

import {lexLine} from './json-lexer.mjs';

const PAIRS = {'{': '}', '[': ']', '"': '"'};
const CLOSERS = new Set(['}', ']']);

export function lineStartOf(text, offset) {
  return text.lastIndexOf('\n', offset - 1) + 1;
}

export function lineEndOf(text, offset) {
  const end = text.indexOf('\n', offset);
  return end === -1 ? text.length : end;
}

export function indentOf(text, offset) {
  const start = lineStartOf(text, offset);
  return /^[ \t]*/.exec(text.slice(start, lineEndOf(text, start)))[0];
}

function previousSignificant(text, offset) {
  const start = lineStartOf(text, offset);
  for (let index = offset - 1; index >= start; index -= 1) {
    if (text[index] !== ' ' && text[index] !== '\t') {
      return text[index];
    }
  }
  return '';
}

function nextSignificant(text, offset) {
  const end = lineEndOf(text, offset);
  for (let index = offset; index < end; index += 1) {
    if (text[index] !== ' ' && text[index] !== '\t') {
      return text[index];
    }
  }
  return '';
}

/** The string token of the caret's line that contains the caret, if any. */
function stringAt(text, offset) {
  const start = lineStartOf(text, offset);
  const line = text.slice(start, lineEndOf(text, offset));
  for (const token of lexLine(line)) {
    if (token.type === 'string' && token.from + start < offset && (offset < token.to + start || !token.closed)) {
      return {from: token.from + start, to: token.to + start, closed: token.closed};
    }
  }
  return null;
}

/** Enter: keep the indentation, indent after an opener and split an empty pair. */
export function newlineEdit(text, start, end, unit = '  ') {
  const indent = indentOf(text, start);
  const before = previousSignificant(text, start);
  const after = nextSignificant(text, end);
  if (before === '{' || before === '[') {
    const inner = indent + unit;
    if (after === PAIRS[before]) {
      let to = end;
      while (text[to] === ' ' || text[to] === '\t') {
        to += 1;
      }
      const insert = `\n${inner}\n${indent}`;
      const caret = start + 1 + inner.length;
      return {from: start, to, text: insert, selectFrom: caret, selectTo: caret};
    }
    const caret = start + 1 + inner.length;
    return {from: start, to: end, text: `\n${inner}`, selectFrom: caret, selectTo: caret};
  }
  const caret = start + 1 + indent.length;
  return {from: start, to: end, text: `\n${indent}`, selectFrom: caret, selectTo: caret};
}

/** Typing one character: auto-close pairs, type over closers, wrap selections. */
export function typeCharEdit(text, start, end, char) {
  const inString = stringAt(text, start);
  if (start === end && (CLOSERS.has(char) || char === '"') && text[start] === char) {
    const closesString = char === '"' && inString && inString.closed && inString.to === start + 1;
    if (char !== '"' || closesString) {
      return {from: start, to: start, text: '', selectFrom: start + 1, selectTo: start + 1};
    }
  }
  if (!(char in PAIRS)) {
    if (char === ':' && !inString && start === end && text[start] !== ' ') {
      return {from: start, to: end, text: ': ', selectFrom: start + 2, selectTo: start + 2};
    }
    return null;
  }
  if (inString && start === end) {
    return null;
  }
  const close = PAIRS[char];
  if (start !== end) {
    const selected = text.slice(start, end);
    return {from: start, to: end, text: char + selected + close, selectFrom: start + 1, selectTo: end + 1};
  }
  const next = text[start];
  const openToClose = next === undefined || next === '\n' || next === ' ' || next === '\t' || next === ','
    || next === ':' || next === '\r' || CLOSERS.has(next);
  if (!openToClose) {
    return null;
  }
  return {from: start, to: end, text: char + close, selectFrom: start + 1, selectTo: start + 1};
}

/** Backspace between an empty pair removes both characters. */
export function backspaceEdit(text, start, end) {
  if (start !== end || start === 0) {
    return null;
  }
  const pair = text.slice(start - 1, start + 1);
  if (pair === '{}' || pair === '[]' || pair === '""') {
    return {from: start - 1, to: start + 1, text: '', selectFrom: start - 1, selectTo: start - 1};
  }
  return null;
}

function selectedLines(text, start, end) {
  const from = lineStartOf(text, start);
  let lastEnd = end;
  if (end > start && text[end - 1] === '\n') {
    lastEnd = end - 1;
  }
  const to = lineEndOf(text, lastEnd);
  return {from, to, lines: text.slice(from, to).split('\n')};
}

/** Tab: insert spaces to the next stop, or indent every selected line. */
export function indentEdit(text, start, end, unit = '  ') {
  const multi = text.slice(start, end).includes('\n');
  if (!multi) {
    const column = start - lineStartOf(text, start);
    const spaces = unit.length - (column % unit.length);
    const insert = ' '.repeat(spaces);
    return {from: start, to: end, text: insert, selectFrom: start + spaces, selectTo: start + spaces};
  }
  const block = selectedLines(text, start, end);
  const lines = block.lines.map((line) => (line.trim() ? unit + line : line));
  const replacement = lines.join('\n');
  const firstShift = block.lines[0].trim() ? unit.length : 0;
  return {
    from: block.from,
    to: block.to,
    text: replacement,
    selectFrom: start + firstShift,
    selectTo: end + (replacement.length - (block.to - block.from)),
  };
}

/** Shift+Tab: remove up to one indentation unit from every selected line. */
export function outdentEdit(text, start, end, unit = '  ') {
  const block = selectedLines(text, start, end);
  let firstShift = 0;
  const lines = block.lines.map((line, index) => {
    const remove = Math.min(unit.length, /^ */.exec(line)[0].length);
    if (index === 0) {
      firstShift = remove;
    }
    return line.slice(remove);
  });
  const replacement = lines.join('\n');
  if (replacement.length === block.to - block.from) {
    return null;
  }
  const lineStart = block.from;
  return {
    from: block.from,
    to: block.to,
    text: replacement,
    selectFrom: Math.max(lineStart, start - firstShift),
    selectTo: Math.max(lineStart, end - (block.to - block.from - replacement.length)),
  };
}

/** Offset of the bracket matching the one at or before `offset`: {open, close} or null. */
export function matchBracket(text, offset, limit = 200000) {
  const candidates = [offset, offset - 1];
  for (const at of candidates) {
    const char = text[at];
    if (char !== '{' && char !== '[' && char !== '}' && char !== ']') {
      continue;
    }
    if (stringAt(text, at + 1) && stringAt(text, at + 1).from < at) {
      continue;
    }
    const forward = char === '{' || char === '[';
    const match = scanBracket(text, at, forward, limit);
    if (match !== -1) {
      return forward ? {open: at, close: match} : {open: match, close: at};
    }
  }
  return null;
}

function scanBracket(text, at, forward, limit) {
  let depth = 0;
  let inString = false;
  const step = forward ? 1 : -1;
  const stop = forward ? Math.min(text.length, at + limit) : Math.max(-1, at - limit);
  for (let index = at; index !== stop; index += step) {
    const char = text[index];
    if (char === '\n') {
      inString = false;
      continue;
    }
    if (char === '"' && !isEscaped(text, index)) {
      inString = !inString;
      continue;
    }
    if (inString) {
      continue;
    }
    if (char === '{' || char === '[') {
      depth += step;
    } else if (char === '}' || char === ']') {
      depth -= step;
    }
    if (depth === 0) {
      return index;
    }
  }
  return -1;
}

function isEscaped(text, index) {
  let count = 0;
  for (let at = index - 1; at >= 0 && text[at] === '\\'; at -= 1) {
    count += 1;
  }
  return count % 2 === 1;
}
