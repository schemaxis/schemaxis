import {parseYaml} from './yaml-parse.mjs';
// Tolerant JSON parser. It always returns an AST (possibly partial) and a list
// of diagnostics {from, to, message, severity}. Every value and key carries
// source offsets so editor features can map between text and JSON pointers.
//
// Nodes:
//   {type: 'object', from, to, closed, members: [{key, colon, value, from, to}]}
//     key: {value, from, to, closed, quoted}
//   {type: 'array', from, to, closed, items: [node]}
//   {type: 'string' | 'number' | 'literal', from, to, value}
//   {type: 'invalid', from, to}

import {lex} from './json-lexer.mjs';

export {pointerAt, rangeOfPointer, valueAt, nodeAtPointer, parsePointer, formatPointer, escapeSegment}
  from './json-pointer.mjs';

const CLOSERS = new Set(['rbrace', 'rbracket']);
const MAX_DIAGNOSTICS = 200;

class Parser {
  constructor(text) {
    this.text = text;
    this.tokens = lex(text, {whitespace: false});
    this.index = 0;
    this.diagnostics = [];
  }

  peek() {
    return this.tokens[this.index];
  }

  next() {
    const token = this.tokens[this.index];
    this.index += 1;
    return token;
  }

  report(from, to, message) {
    if (this.diagnostics.length < MAX_DIAGNOSTICS) {
      this.diagnostics.push({from, to: Math.max(to, from), message, severity: 'error'});
    }
  }

  reportToken(token) {
    if (token.error) {
      this.report(token.from, token.to, token.error);
    }
  }

  parseValue() {
    const token = this.peek();
    if (!token) {
      return null;
    }
    switch (token.type) {
      case 'lbrace':
        return this.parseObject();
      case 'lbracket':
        return this.parseArray();
      case 'string':
      case 'number':
      case 'literal':
        this.next();
        this.reportToken(token);
        return {type: token.type, from: token.from, to: token.to, value: token.value, closed: token.closed};
      case 'error':
        this.next();
        this.reportToken(token);
        return {type: 'invalid', from: token.from, to: token.to};
      default:
        return null;
    }
  }

  parseObject() {
    const open = this.next();
    const node = {type: 'object', from: open.from, to: open.to, closed: false, members: []};
    let expectMember = true;
    let lastComma = null;
    for (;;) {
      const token = this.peek();
      if (!token) {
        this.report(node.from, node.from + 1, "Unterminated object: expected '}'");
        node.to = this.text.length;
        return node;
      }
      if (token.type === 'rbrace') {
        this.next();
        if (lastComma && node.members.length > 0) {
          this.report(lastComma.from, lastComma.to, 'Trailing comma');
        }
        node.to = token.to;
        node.closed = true;
        return node;
      }
      if (token.type === 'rbracket') {
        this.report(token.from, token.to, "Expected '}' but found ']'");
        node.to = token.from;
        return node;
      }
      if (token.type === 'comma') {
        this.next();
        if (expectMember) {
          this.report(token.from, token.to, 'Unexpected comma');
        }
        expectMember = true;
        lastComma = token;
        continue;
      }
      if (!expectMember) {
        const previous = node.members[node.members.length - 1];
        const at = previous ? previous.to : token.from;
        this.report(at, token.from > at ? token.from : at + 1, "Expected ','");
      }
      lastComma = null;
      const member = this.parseMember();
      if (member) {
        node.members.push(member);
        node.to = member.to;
      }
      expectMember = false;
    }
  }

  parseMember() {
    const token = this.peek();
    let key;
    if (token.type === 'string') {
      this.next();
      this.reportToken(token);
      key = {value: token.value, from: token.from, to: token.to, closed: token.closed, quoted: true};
    } else if (token.type === 'error' || token.type === 'literal' || token.type === 'number') {
      this.next();
      this.report(token.from, token.to, 'Property names must be double-quoted strings');
      const raw = this.text.slice(token.from, token.to);
      key = {value: raw, from: token.from, to: token.to, closed: false, quoted: false};
    } else if (token.type === 'colon') {
      this.report(token.from, token.to, 'Expected a property name');
      key = {value: '', from: token.from, to: token.from, closed: false, quoted: false};
    } else {
      // A nested value where a key belongs: report, parse it and drop it.
      this.report(token.from, token.to, 'Expected a property name');
      const start = this.index;
      this.parseValue();
      if (this.index === start) {
        this.next();
      }
      return null;
    }
    const member = {key, colon: -1, value: null, from: key.from, to: key.to};
    const colon = this.peek();
    if (colon && colon.type === 'colon') {
      this.next();
      member.colon = colon.from;
      member.to = colon.to;
    } else {
      this.report(key.from, key.to, "Expected ':' after property name");
      if (!colon || colon.type === 'comma' || CLOSERS.has(colon.type) || colon.type === 'string') {
        return member;
      }
    }
    const value = this.parseValue();
    if (value) {
      member.value = value;
      member.to = value.to;
    } else {
      this.report(member.to - 1, member.to, 'Expected a value');
    }
    return member;
  }

  parseArray() {
    const open = this.next();
    const node = {type: 'array', from: open.from, to: open.to, closed: false, items: []};
    let expectItem = true;
    let lastComma = null;
    for (;;) {
      const token = this.peek();
      if (!token) {
        this.report(node.from, node.from + 1, "Unterminated array: expected ']'");
        node.to = this.text.length;
        return node;
      }
      if (token.type === 'rbracket') {
        this.next();
        if (lastComma && node.items.length > 0) {
          this.report(lastComma.from, lastComma.to, 'Trailing comma');
        }
        node.to = token.to;
        node.closed = true;
        return node;
      }
      if (token.type === 'rbrace') {
        this.report(token.from, token.to, "Expected ']' but found '}'");
        node.to = token.from;
        return node;
      }
      if (token.type === 'comma') {
        this.next();
        if (expectItem) {
          this.report(token.from, token.to, 'Unexpected comma');
        }
        expectItem = true;
        lastComma = token;
        continue;
      }
      if (token.type === 'colon') {
        this.next();
        this.report(token.from, token.to, "Unexpected ':' in array");
        continue;
      }
      if (!expectItem) {
        const previous = node.items[node.items.length - 1];
        this.report(previous.to, token.from > previous.to ? token.from : previous.to + 1, "Expected ','");
      }
      lastComma = null;
      const item = this.parseValue();
      if (item) {
        node.items.push(item);
        node.to = item.to;
      }
      expectItem = false;
    }
  }

  parseDocument() {
    if (!this.peek()) {
      return null;
    }
    const root = this.parseValue();
    if (!root) {
      const token = this.next();
      this.report(token.from, token.to, 'Expected a JSON value');
    }
    while (this.peek()) {
      const token = this.next();
      if (root) {
        this.report(token.from, this.text.length, 'Unexpected content after the JSON value');
        break;
      }
    }
    return root;
  }
}

/** Parse text tolerantly: {root, diagnostics, text}. */
export function parse(text, format = "json") {
  if (format === 'yaml') return parseYaml(text);
  const parser = new Parser(text);
  const root = parser.parseDocument();
  return {root, diagnostics: parser.diagnostics, text};
}

/** Convert an AST node to plain JSON. Missing values become undefined and are skipped. */
export function toValue(node) {
  if (!node) {
    return undefined;
  }
  switch (node.type) {
    case 'object': {
      const result = {};
      for (const member of node.members) {
        if (member.value) {
          const value = toValue(member.value);
          if (value !== undefined) {
            Object.defineProperty(result, member.key.value, {value, enumerable: true, configurable: true, writable: true});
          }
        }
      }
      return result;
    }
    case 'array':
      return node.items.map((item) => {
        const value = toValue(item);
        return value === undefined ? null : value;
      });
    case 'invalid':
      return undefined;
    default:
      return node.value;
  }
}

const documentValues = new WeakMap();

/** Plain JSON of a parse result, memoised per AST. */
export function documentValue(ast) {
  if (!documentValues.has(ast)) {
    documentValues.set(ast, toValue(ast.root));
  }
  return documentValues.get(ast);
}
