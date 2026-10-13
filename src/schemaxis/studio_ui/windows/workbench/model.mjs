// Pure document, schema and snippet helpers shared by the Workbench panels.

import {schemasAt} from '../../editor/schema.mjs';

export const escapePointer = (part) => String(part).replaceAll('~', '~0').replaceAll('/', '~1');

export function diagnosticPointer(location, documentValue) {
  if (!location || location === '$') {
    return '';
  }
  if (location.startsWith('/')) {
    return location;
  }
  const parts = location.replace(/^\$\.?/, '').replace(/\[(\d+)\]/g, '.$1').split('.');
  const index = documentValue?.nodes?.findIndex((node) => node.id === parts[0]) ?? -1;
  if (index >= 0) {
    parts.shift();
    const node = documentValue.nodes[index];
    const group = Object.hasOwn(node.options || {}, parts[0]) ? 'options'
      : Object.hasOwn(node.inputs || {}, parts[0]) ? 'inputs' : null;
    parts.unshift('nodes', String(index), ...(group ? [group] : []));
  }
  const pointer = '/' + parts.map(escapePointer).join('/');
  return valueAt(documentValue, pointer) !== undefined ? pointer : '';
}

export function mapDiagnostics(diagnostics, documentValue) {
  return diagnostics.map((item) => ({...item,
    pointer: item.pointer || diagnosticPointer(item.location, documentValue),
    ...(Number.isInteger(item.offset) ? {from: item.offset, to: item.offset + 1} : {}),
  }));
}

export function valueAt(value, pointer) {
  if (!pointer) {
    return value;
  }
  return pointer.slice(1).split('/').reduce((item, part) => {
    const key = part.replaceAll('~1', '/').replaceAll('~0', '~');
    return item && Object.hasOwn(item, key) ? item[key] : undefined;
  }, value);
}

export function operationPointer(record, operation) {
  if (!operation) {
    return '';
  }
  const prefix = record.document?.workflow ? '/workflow' : '';
  const operations = valueAt(record.document, `${prefix}/operations`);
  const index = operations?.findIndex((item) => item.id === operation) ?? -1;
  if (index < 0) {
    throw new Error(`Operation “${operation}” is no longer in this design.`);
  }
  return `${prefix}/operations/${index}/document`;
}

export function outline(documentValue) {
  const items = [{pointer: '', label: 'Document', detail: documentValue?.version || 'JSON'}];
  const caption = (value, fallback) => typeof value === 'string' ? value
    : value?.$fill ? `${value.label || value.$fill} · to fill` : fallback;
  for (const group of ['nodes', 'components', 'scenes', 'operations']) {
    const entries = documentValue?.[group];
    if (Array.isArray(entries)) {
      entries.forEach((entry, index) => items.push({pointer: `/${group}/${index}`,
        label: caption(entry.id, `${group} ${index + 1}`), detail: caption(entry.filter, group), group}));
    }
  }
  for (const key of ['axes', 'times', 'settings', 'dimensions', 'definitions', 'views', 'output', 'outputs', 'execution']) {
    if (Object.hasOwn(documentValue || {}, key)) items.push({pointer: '/' + key, label: key,
      detail: 'document setting', group: 'settings'});
  }
  if (documentValue?.workflow && typeof documentValue.workflow === 'object') {
    items.push(...outline(documentValue.workflow).map(item => ({...item, pointer: '/workflow' + item.pointer,
      label: item.pointer ? item.label : 'Workflow'})));
  }
  return items;
}

export function fieldsAt(schema, documentValue, pointer) {
  const value = valueAt(documentValue, pointer);
  const nodes = schema ? schemasAt(schema, documentValue, pointer) : [];
  const properties = Object.assign({}, ...nodes.map((node) => node.properties || {}));
  const required = new Set(nodes.flatMap((node) => node.required || []));
  const names = [...new Set([...Object.keys(value || {}), ...Object.keys(properties)])];
  return names.filter((name) => !name.startsWith('$')).map((name) => {
    const path = `${pointer}/${escapePointer(name)}`;
    const parts = schema ? schemasAt(schema, documentValue, path) : [];
    const combined = Object.assign({}, ...parts);
    // Generic scalar/$ref branches carry pending records too. They must not
    // replace an option's scoped explanation or native binding when flattened.
    const score = guide => Number(Boolean(guide.explanation)) * 4 + Number(Boolean(guide.binding)) * 2
      + Number(guide.status !== 'pending');
    const ranked = parts.filter(part => part['x-studio-guide'])
      .sort((a, b) => score(b['x-studio-guide']) - score(a['x-studio-guide']));
    const owner = ranked[0];
    if (owner) {
      // Title and description follow the chosen record, not whichever value
      // branch (for example “Runtime value”) happened to be merged last.
      combined['x-studio-guide'] = owner['x-studio-guide'];
      if (owner.title === undefined) delete combined.title; else combined.title = owner.title;
      const description = owner.description ?? ranked.find(part => part.description !== undefined)?.description;
      if (description === undefined) delete combined.description; else combined.description = description;
    }
    const current = value?.[name];
    const choices = parts.flatMap((part) => part.enum || (Object.hasOwn(part, 'const') ? [part.const] : []));
    return {name, pointer: path, value: current, required: required.has(name), schema: combined,
      choices: [...new Set(choices)], type: combined.type || (Array.isArray(current) ? 'array' : typeof current)};
  });
}

export function parseField(text, field) {
  if (field.type === 'number' || field.type === 'integer') {
    if (!text.trim()) {
      throw new Error(`${field.name} requires a number.`);
    }
    const number = Number(text);
    if (!Number.isFinite(number) || (field.type === 'integer' && !Number.isInteger(number))) {
      throw new Error(`${field.name} requires ${field.type === 'integer' ? 'an integer' : 'a finite number'}.`);
    }
    return number;
  }
  if (field.type === 'boolean') {
    return text === 'true';
  }
  if (field.type === 'array' || field.type === 'object' || field.value === null) {
    return JSON.parse(text);
  }
  return text;
}

export function placeholders(value) {
  const found = new Map();
  const visit = (item) => {
    if (typeof item === 'string') {
      for (const match of item.matchAll(/\$\{([^}:]+):([^}]*)\}/g)) {
        found.set(match[1], {name: match[1], value: match[2]});
      }
    } else if (item && typeof item === 'object') {
      Object.values(item).forEach(visit);
    }
  };
  visit(value);
  return [...found.values()];
}

export function fillPlaceholders(value, replacements = {}) {
  if (typeof value === 'string') {
    return value.replace(/\$\{([^}:]+):([^}]*)\}/g, (_, name, fallback) => replacements[name] ?? fallback);
  }
  if (Array.isArray(value)) {
    return value.map((item) => fillPlaceholders(item, replacements));
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, fillPlaceholders(item, replacements)]));
  }
  return value;
}

export function snippetRequest(snippet, documentValue, replacements = {}) {
  const values = fillPlaceholders(snippet.insert.values, replacements);
  if (snippet.insert.at === '/nodes/-') {
    const ids = new Set((documentValue.nodes || []).map((node) => node.id));
    for (const node of values) {
      if (node.id && ids.has(node.id)) {
        throw new Error(`Node “${node.id}” already exists. Choose a different name for the snippet.`);
      }
      ids.add(node.id);
    }
  }
  return {at: snippet.insert.at, values};
}
