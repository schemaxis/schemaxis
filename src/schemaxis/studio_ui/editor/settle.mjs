// Pure edit-region classification and visibility policy for calm diagnostics.
import {lex} from './json-lexer.mjs';
import {nodeAtPointer} from './json-pointer.mjs';

export const SETTLE_DELAYS = {stable: 600, local: 1500, transient: 1500, server: 1000};
const containers = (node) => node?.type === 'object' ? node.members.map((member) => member.value)
  : node?.type === 'array' ? node.items : [];
const contains = (range, offset) => range && range.from <= offset && offset <= range.to;
const overlaps = (a, b) => a && b && a.from <= b.to && b.from <= a.to;

/** Token at/before the caret, plus its innermost container. */
export function activeEditRegion(ast, caret) {
  let container = null;
  const visit = (node) => {
    if (!node || !contains(node, caret)) return;
    if (node.type === 'object' || node.type === 'array') container = node;
    containers(node).forEach(visit);
  };
  visit(ast.root);
  const tokens = lex(ast.text, {whitespace: false});
  const current = tokens.find((token) => token.from <= caret && caret < token.to);
  const previous = tokens.findLast((token) => token.to <= caret);
  return {container, tokens: [current, previous].filter(Boolean), caret};
}

/** The tolerant parser keeps duplicate members; diagnose them without losing their ranges. */
export function duplicateKeyDiagnostics(ast) {
  const found = [];
  const visit = (node) => {
    if (node?.type === 'object') {
      const seen = new Set();
      for (const member of node.members) {
        if (seen.has(member.key.value)) {
          found.push({from: member.key.from, to: member.key.to, source: 'syntax', severity: 'error',
            message: `Duplicate property "${member.key.value}"`});
        }
        seen.add(member.key.value);
      }
    }
    containers(node).forEach(visit);
  };
  visit(ast.root);
  return found;
}

function diagnosticRegion(ast, diagnostic) {
  let owner = null;
  const visit = (node) => {
    if (!node || !contains(node, diagnostic.from)) return;
    if (node.type === 'object' || node.type === 'array') owner = node;
    containers(node).forEach(visit);
  };
  visit(ast.root);
  if (diagnostic.pointer !== undefined) {
    const target = nodeAtPointer(ast, diagnostic.pointer);
    if (target?.type === 'object' || target?.type === 'array') owner = target;
  }
  return owner ? {from: owner.from, to: owner.to} : {from: diagnostic.from, to: diagnostic.to};
}

export function classifyDiagnostics(ast, diagnostics, caret) {
  const active = activeEditRegion(ast, caret);
  return diagnostics.map((diagnostic) => {
    const source = diagnostic.code === 'UNFILLED_VALUES' ? 'fill'
      : diagnostic.source === 'external' ? 'server' : diagnostic.source || 'syntax';
    const region = diagnosticRegion(ast, diagnostic);
    const touches = overlaps(active.container, diagnostic)
      || active.tokens.some((token) => overlaps(token, diagnostic));
    const raw = ast.text.slice(diagnostic.from, diagnostic.to);
    const message = diagnostic.message || '';
    const incompleteNumber = message === 'Invalid number' && /^(?:-|-?\d+\.|-?\d+(?:\.\d+)?[eE][+-]?)$/.test(raw);
    const incompleteString = active.tokens.some((token) => token.type === 'string' && !token.closed
      && overlaps(token, diagnostic));
    const incompleteWord = /^Unexpected '(?:t|tr|tru|f|fa|fal|fals|n|nu|nul)'$/.test(message);
    const recoverable = /^(Trailing comma|Expected ':'|Expected a value|Unterminated string|Expected ',')/.test(message)
      || incompleteNumber || incompleteWord || incompleteString;
    const unclosed = /^Unterminated (object|array)/.test(message) && contains(region, caret);
    const duplicate = /^Duplicate property/.test(message)
      && active.tokens.some((token) => overlaps(token, diagnostic) && token.type === 'string');
    const sameContainer = active.container?.from === region.from && active.container?.to === region.to;
    const local = source === 'schema' && (touches || sameContainer)
      && /^(Missing required|Expected .*found |Expected at least)/.test(message);
    const settle = source === 'syntax' && ((recoverable && touches) || unclosed || duplicate)
      ? 'transient' : local ? 'local' : 'stable';
    return {...diagnostic, source, settle, region};
  });
}

/** Classification is captured at edit time; caret movement must not promote transient errors to stable. */
export function settledDiagnostics(diagnostics, {caret, idle = 0, blurred = false, explicit = false}) {
  return diagnostics.filter((diagnostic) => {
    if (explicit || blurred) return true;
    if (diagnostic.settle === 'transient') return !contains(diagnostic.region, caret) && idle >= 1500;
    if (diagnostic.settle === 'local') return !contains(diagnostic.region, caret) || idle >= 1500;
    return idle >= 600;
  });
}
