// Copyright (C) 2026 David L F Gaden
// JSON lexer with source offsets. It never throws: malformed input becomes
// 'error' tokens or tokens carrying an `error` message, so partial documents
// can be highlighted and parsed tolerantly.
//
// Token: {type, from, to, value?, closed?, error?}
// Types: 'lbrace' 'rbrace' 'lbracket' 'rbracket' 'colon' 'comma'
//        'string' 'number' 'literal' 'whitespace' 'error'

const PUNCTUATION = {
  '{': 'lbrace',
  '}': 'rbrace',
  '[': 'lbracket',
  ']': 'rbracket',
  ':': 'colon',
  ',': 'comma',
};

const LITERALS = {
  true: true,
  false: false,
  null: null,
};

const ESCAPES = {
  '"': '"',
  '\\': '\\',
  '/': '/',
  b: '\b',
  f: '\f',
  n: '\n',
  r: '\r',
  t: '\t',
};

const NUMBER = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/;
const WORD_CHAR = /[A-Za-z0-9_$.+-]/;

function isWhitespace(code) {
  return code === 0x20 || code === 0x0a || code === 0x0d || code === 0x09;
}

function readWhitespace(text, start) {
  let index = start;
  while (index < text.length && isWhitespace(text.charCodeAt(index))) {
    index += 1;
  }
  return {type: 'whitespace', from: start, to: index};
}

/** Read a string starting at the opening quote. Strings end at a newline when unterminated. */
export function readString(text, start) {
  let index = start + 1;
  let value = '';
  let error = null;
  while (index < text.length) {
    const char = text[index];
    if (char === '"') {
      return {type: 'string', from: start, to: index + 1, value, closed: true, error};
    }
    if (char === '\n' || char === '\r') {
      break;
    }
    if (char === '\\') {
      const next = text[index + 1];
      if (next === undefined || next === '\n' || next === '\r') {
        index += 1;
        break;
      }
      if (next === 'u') {
        const hex = text.slice(index + 2, index + 6);
        if (/^[0-9a-fA-F]{4}$/.test(hex)) {
          value += String.fromCharCode(parseInt(hex, 16));
          index += 6;
        } else {
          error = error || 'Invalid unicode escape';
          index += 2;
        }
        continue;
      }
      if (next in ESCAPES) {
        value += ESCAPES[next];
      } else {
        error = error || `Invalid escape '\\${next}'`;
        value += next;
      }
      index += 2;
      continue;
    }
    if (char.charCodeAt(0) < 0x20) {
      error = error || 'Control character in string';
    }
    value += char;
    index += 1;
  }
  return {type: 'string', from: start, to: index, value, closed: false, error: error || 'Unterminated string'};
}

function readWord(text, start) {
  let index = start;
  while (index < text.length && WORD_CHAR.test(text[index])) {
    index += 1;
  }
  if (index === start) {
    index = start + 1;
  }
  const word = text.slice(start, index);
  if (Object.prototype.hasOwnProperty.call(LITERALS, word)) {
    return {type: 'literal', from: start, to: index, value: LITERALS[word]};
  }
  const first = word[0];
  if (first === '-' || (first >= '0' && first <= '9')) {
    if (NUMBER.test(word)) {
      return {type: 'number', from: start, to: index, value: Number(word)};
    }
    return {type: 'number', from: start, to: index, value: Number.parseFloat(word), error: 'Invalid number'};
  }
  return {type: 'error', from: start, to: index, value: word, error: `Unexpected '${word}'`};
}

/** Read the token that starts at `start`. */
export function readToken(text, start) {
  const char = text[start];
  if (isWhitespace(text.charCodeAt(start))) {
    return readWhitespace(text, start);
  }
  if (char in PUNCTUATION) {
    return {type: PUNCTUATION[char], from: start, to: start + 1};
  }
  if (char === '"') {
    return readString(text, start);
  }
  return readWord(text, start);
}

/** Lex a whole text. Options: {whitespace: false} drops whitespace tokens. */
export function lex(text, options = {}) {
  const keepWhitespace = options.whitespace !== false;
  const tokens = [];
  let index = options.from || 0;
  const end = options.to === undefined ? text.length : options.to;
  while (index < end) {
    const token = readToken(text, index);
    if (keepWhitespace || token.type !== 'whitespace') {
      tokens.push(token);
    }
    index = token.to;
  }
  return tokens;
}

/**
 * Lex one line for highlighting. JSON strings cannot contain raw newlines, so a
 * line lexes correctly in isolation. Strings followed by ':' get `key: true`.
 */
export function lexLine(line) {
  const tokens = lex(line);
  let pendingString = null;
  for (const token of tokens) {
    if (token.type === 'whitespace') {
      continue;
    }
    if (pendingString && token.type === 'colon') {
      pendingString.key = true;
    }
    pendingString = token.type === 'string' ? token : null;
  }
  return tokens;
}

/** True when the character can start a JSON value. */
export function startsValue(char) {
  return char === '{' || char === '[' || char === '"' || char === '-' || (char >= '0' && char <= '9')
    || char === 't' || char === 'f' || char === 'n';
}
