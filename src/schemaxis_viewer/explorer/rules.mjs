// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// User filename patterns: a regular expression, optionally with capture
// groups, turns parts of a filename into properties. Without captures the
// whole match becomes the value of a property named after the rule.
// Saved/imported as artifact.filename-rules/1 (compatible with the classic viewer).

export const RULES_VERSION = 'artifact.filename-rules/1';
const KEY = /^[A-Za-z][A-Za-z0-9_.-]{0,40}$/;

export function captureNames(pattern) {
  const names = [];
  const source = String(pattern);
  let count = 0;
  for (let i = 0; i < source.length; i++) {
    const char = source[i];
    if (char === '\\') {
      i++;
      continue;
    }
    if (char === '[') {
      for (i++; i < source.length && source[i] !== ']'; i++) if (source[i] === '\\') i++;
      continue;
    }
    if (char !== '(') continue;
    if (source[i + 1] !== '?') {
      names.push({index: ++count, name: null});
    } else {
      const named = /^\(\?<([A-Za-z_$][\w$]*)>/.exec(source.slice(i));
      if (named) names.push({index: ++count, name: named[1]});
    }
  }
  return names;
}

export function slug(text) {
  const value = String(text || '').trim().replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^[^A-Za-z]+/, '').slice(0, 40);
  return value || 'match';
}

export function compileRule(rule) {
  if (!rule || typeof rule.pattern !== 'string' || !rule.pattern) throw Error('Enter a pattern');
  const regex = new RegExp(rule.pattern, rule.ignoreCase ? 'i' : '');
  const captures = captureNames(rule.pattern);
  const columns = captures.map(function column(capture) {
    const configured = (rule.columns || []).find(c => c.index === capture.index) || {};
    return {
      index: capture.index,
      key: configured.key || capture.name || `${slug(rule.name)}${captures.length > 1 ? capture.index : ''}`,
      type: ['text', 'number', 'tags'].includes(configured.type) ? configured.type : 'text',
      separator: typeof configured.separator === 'string' && configured.separator ? configured.separator : '.'
    };
  });
  for (const column of columns) if (!KEY.test(column.key)) throw Error(`Invalid property name "${column.key}"`);
  return {regex, columns, key: slug(rule.name), target: rule.target === 'path' ? 'path' : 'name'};
}

function convert(text, column) {
  if (text === undefined) return undefined;
  if (column.type === 'number') {
    const value = Number(text);
    return text !== '' && Number.isFinite(value) ? value : text;
  }
  if (column.type === 'tags') return text.split(column.separator).filter(Boolean);
  return text;
}

export function applyRule(compiled, item) {
  const subject = compiled.target === 'path' ? item.path : item.name;
  const match = compiled.regex.exec(subject);
  if (!match) return null;
  const values = {};
  if (!compiled.columns.length) {
    values[compiled.key] = match[0];
  } else {
    for (const column of compiled.columns) {
      const value = convert(match[column.index], column);
      if (value !== undefined) values[column.key] = value;
    }
  }
  return {values, match};
}

export function extractRuleProperties(items, rules) {
  const result = new Map(), errors = new Map();
  for (const rule of rules) {
    if (!rule.enabled) continue;
    let compiled;
    try {
      compiled = compileRule(rule);
    } catch (error) {
      errors.set(rule.id, error.message);
      continue;
    }
    for (const item of items) {
      const hit = applyRule(compiled, item);
      if (!hit) continue;
      result.set(item.id, Object.assign(result.get(item.id) || {}, hit.values));
    }
  }
  return {properties: result, errors};
}

export function exportRules(rules) {
  return {version: RULES_VERSION, rules: rules.map(function plain(rule) {
    return {name: rule.name, enabled: rule.enabled, pattern: rule.pattern, ignoreCase: !!rule.ignoreCase,
      target: rule.target || 'name', columns: rule.columns || []};
  })};
}

export function importRules(document) {
  if (!document || document.version !== RULES_VERSION || !Array.isArray(document.rules)) {
    throw Error(`Expected a ${RULES_VERSION} document`);
  }
  return document.rules.map(function normalise(rule, index) {
    if (typeof rule.pattern !== 'string') throw Error(`Rule ${index + 1} has no pattern`);
    return {id: `rule-${Date.now()}-${index}`, name: String(rule.name || `Rule ${index + 1}`), enabled: rule.enabled !== false,
      pattern: rule.pattern, ignoreCase: !!rule.ignoreCase, target: rule.target === 'path' ? 'path' : 'name',
      columns: Array.isArray(rule.columns) ? rule.columns : []};
  });
}
