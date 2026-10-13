// Line highlighting: JSON tokens plus decoration ranges (diagnostics, bracket
// matches, ghost text) rendered as spans. Only visible lines are rendered.

import {h} from '../lib/dom.mjs';
import {lexLine} from './json-lexer.mjs';

const TOKEN_CACHE_LIMIT = 4000;
const tokenCache = new Map();

function tokensFor(line, format = "json") {
  if (format === "yaml") return yamlTokens(line);
  let tokens = tokenCache.get(line);
  if (!tokens) {
    tokens = lexLine(line);
    if (tokenCache.size >= TOKEN_CACHE_LIMIT) {
      tokenCache.clear();
    }
    tokenCache.set(line, tokens);
  }
  return tokens;
}

function tokenClass(token, line) {
  switch (token.type) {
    case 'comment': return 'sx-tk-comment';
    case 'key': return 'sx-tk-key';
    case 'plain': return '';
    case 'string':
      if (token.key) {
        return line[token.from + 1] === '$' ? 'sx-tk-marker' : 'sx-tk-key';
      }
      return 'sx-tk-string';
    case 'number':
      return token.error ? 'sx-tk-error' : 'sx-tk-number';
    case 'literal':
      return 'sx-tk-literal';
    case 'error':
      return 'sx-tk-error';
    case 'whitespace':
      return '';
    default:
      return 'sx-tk-punct';
  }
}

/**
 * Render one line. `decorations` are {from, to, className} in document offsets;
 * `lineFrom` is the document offset of the line start.
 */
export function renderLine(line, lineFrom, decorations, format = "json") {
  const tokens = tokensFor(line, format);
  const lineTo = lineFrom + line.length;
  const local = [];
  for (const decoration of decorations) {
    if (decoration.to <= lineFrom || decoration.from >= lineTo) {
      continue;
    }
    local.push({
      from: Math.max(0, decoration.from - lineFrom),
      to: Math.min(line.length, decoration.to - lineFrom),
      className: decoration.className,
    });
  }
  if (!local.length) {
    return tokens.map((token) => {
      const text = line.slice(token.from, token.to);
      const className = tokenClass(token, line);
      return className ? h('span', {class: className}, text) : text;
    });
  }
  const cuts = new Set([0, line.length]);
  for (const token of tokens) {
    cuts.add(token.from);
    cuts.add(token.to);
  }
  for (const decoration of local) {
    cuts.add(decoration.from);
    cuts.add(decoration.to);
  }
  const points = [...cuts].sort((a, b) => a - b);
  const nodes = [];
  let tokenIndex = 0;
  for (let index = 0; index < points.length - 1; index += 1) {
    const from = points[index];
    const to = points[index + 1];
    if (from === to) {
      continue;
    }
    while (tokenIndex < tokens.length - 1 && tokens[tokenIndex].to <= from) {
      tokenIndex += 1;
    }
    const token = tokens[tokenIndex];
    const classes = [];
    if (token && token.from <= from && token.to >= to) {
      classes.push(tokenClass(token, line));
    }
    for (const decoration of local) {
      if (decoration.from <= from && decoration.to >= to) {
        classes.push(decoration.className);
      }
    }
    const text = line.slice(from, to);
    const className = classes.filter(Boolean).join(' ');
    nodes.push(className ? h('span', {class: className}, text) : text);
  }
  return nodes;
}

/** Offsets of line starts. */
export function computeLineStarts(text) {
  const starts = [0];
  let index = text.indexOf('\n');
  while (index !== -1) {
    starts.push(index + 1);
    index = text.indexOf('\n', index + 1);
  }
  return starts;
}

/** Zero-based line containing an offset (binary search). */
export function lineOfOffset(lineStarts, offset) {
  let low = 0;
  let high = lineStarts.length - 1;
  while (low < high) {
    const middle = (low + high + 1) >> 1;
    if (lineStarts[middle] <= offset) {
      low = middle;
    } else {
      high = middle - 1;
    }
  }
  return low;
}

/** Fill marker decorations share the token layer, preserving textarea alignment. */
export function fillDecorations(markers, activePointers = new Set(), currentPointer = null) {
  return markers.map((marker) => ({from: marker.from, to: marker.to,
    className: ['sx-fill-marker', activePointers.has(marker.pointer) ? 'sx-fill-active' : 'sx-fill-quiet',
      marker.field.required !== false && 'sx-fill-required',
      marker.pointer === currentPointer && 'sx-fill-current'].filter(Boolean).join(' ')}));
}

// Line tokens are presentation only; the full YAML AST supplies validation.
function yamlTokens(line) {
  const pattern = /#[^\n]*|"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[A-Za-z_$][A-Za-z0-9_$.-]*(?=\s*:)|[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|\b(?:true|false|null)\b|[{}\[\],:|>]|\s+|./g;
  const tokens = [];
  let match;
  while ((match = pattern.exec(line))) {
    const text = match[0];
    const type = text[0] === '#' ? 'comment' : /^['"]/.test(text) ? 'string'
      : /^(true|false|null)$/.test(text) ? 'literal' : /^[+-]?(\d|\.\d)/.test(text) ? 'number'
      : /^[A-Za-z_$]/.test(text) && /^\s*:/.test(line.slice(pattern.lastIndex)) ? 'key'
      : /^[{}\[\],:|>]$/.test(text) ? 'punct' : 'plain';
    tokens.push({type, from: match.index, to: pattern.lastIndex});
  }
  return tokens;
}
