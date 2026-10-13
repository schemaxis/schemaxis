// Library bodies are data. Expand fields to persistent markers and keep identity
// rewrites scoped to declarations and reference positions, never arbitrary text.

const interpolation = /\$\{([^}:]+)\}/g;
const clone = (value) => structuredClone(value);
const collections = new Set(['nodes', 'operations', 'scenes', 'axes', 'components']);
const escape = (value) => String(value).replaceAll('~', '~0').replaceAll('/', '~1');

export function markers(value, pointer = '') {
  const result = [];
  if (Array.isArray(value)) {
    value.forEach((child, index) => result.push(...markers(child, `${pointer}/${index}`)));
  } else if (value && typeof value === 'object') {
    if (Object.hasOwn(value, '$fill')) {
      result.push({pointer, marker: value});
    }
    for (const [key, child] of Object.entries(value)) {
      result.push(...markers(child, `${pointer}/${escape(key)}`));
    }
  }
  return result;
}

export function expandFields(value, fields, replacements = {}, names = {}) {
  if (Array.isArray(value)) {
    return value.map((child) => expandFields(child, fields, replacements, names));
  }
  if (value && typeof value === 'object') {
    if (Object.hasOwn(value, '$fill')) {
      const id = value.$fill;
      return Object.hasOwn(replacements, id) ? clone(replacements[id])
        : {...clone(fields[id] || {}), $fill: names[id] || id};
    }
    return Object.fromEntries(Object.entries(value).map(([key, child]) =>
      [key, expandFields(child, fields, replacements, names)]));
  }
  if (typeof value === 'string') {
    const ids = [...value.matchAll(interpolation)].map((match) => match[1]);
    if (ids.length) {
      const id = ids.find(key => !Object.hasOwn(replacements, key));
      if (id !== undefined) {
        return {...clone(fields[id] || {}), $fill: names[id] || id,
          template: value.replace(interpolation, (_, key) => Object.hasOwn(replacements, key)
            ? String(replacements[key]) : '${' + (names[key] || key) + '}')};
      }
      return value.replace(interpolation, (_, key) => String(replacements[key]));
    }
  }
  return value;
}

function at(value, path) {
  return path.split('/').slice(1).reduce((item, key) => item?.[key.replaceAll('~1', '/').replaceAll('~0', '~')], value);
}

/** Rewrite declared IDs and only positions that the document treats as references. */
function references(value, changes, key = '', parent = '') {
  if (typeof value === 'string') {
    const group = key === '$axis' ? 'axes' : key === '$artifact' || key === 'operation' ? 'operations' : 'nodes';
    const isReference = parent === 'inputs' || ['output', 'geometry', 'visible', '$axis', '$artifact', 'operation']
      .includes(key) || ['$observe', '$sample'].includes(key);
    return isReference ? changes[group]?.get(value) || value : value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => references(item, changes, key, parent));
  }
  if (value && typeof value === 'object') {
    if (typeof value.node === 'string' && (value.writer || Object.keys(value).every(key => ['node', 'port'].includes(key)))) {
      value = {...value, node: changes.nodes?.get(value.node) || value.node};
    }
    if (typeof value.$value === 'string' && Object.hasOwn(value, 'path')) {
      return {...value, $value: changes.operations?.get(value.$value) || value.$value};
    }
    return Object.fromEntries(Object.entries(value).map(([name, item]) => [
      key === 'visible' ? changes.nodes?.get(name) || name : name,
      references(item, changes, name, key),
    ]));
  }
  return value;
}

export function uniquifyInserts(documentValue, inserts) {
  const result = clone(inserts);
  const used = new Map();
  const changes = {};
  for (const insert of result) {
    const match = /^(.*\/([^/]+))\/(?:-|\d+)$/.exec(insert.at);
    if (!match || !collections.has(match[2]) || !insert.values) {
      continue;
    }
    const [, path, group] = match;
    const identity = group === 'axes' ? 'name' : 'id';
    if (!used.has(path)) {
      used.set(path, new Set((at(documentValue, path) || []).map((item) => item?.[identity])));
    }
    const ids = used.get(path);
    for (const item of insert.values) {
      if (!item || typeof item[identity] !== 'string') {
        continue;
      }
      const original = item[identity];
      let next = original;
      let suffix = 2;
      while (ids.has(next)) {
        next = `${original}${suffix++}`;
      }
      ids.add(next);
      item[identity] = next;
      if (next !== original) {
        const scope = path.slice(0, -group.length - 1);
        changes[scope] ||= {};
        changes[scope][group] ||= new Map();
        changes[scope][group].set(original, next);
      }
    }
  }
  return result.map((insert) => {
    const scopes = Object.keys(changes).filter((scope) => insert.at.startsWith(scope + '/'))
      .sort((a, b) => b.length - a.length);
    const scoped = changes[scopes[0]] || {};
    return {...insert,
      ...(insert.values ? {values: references(insert.values, scoped)} : {}),
      ...(insert.merge ? {merge: references(insert.merge, scoped, insert.at.split('/').at(-1))} : {}),
    };
  });
}

function fieldNames(fields, documentValue) {
  const occupied = new Set(markers(documentValue).map(({marker}) => marker.$fill));
  const names = {};
  for (const id of Object.keys(fields)) {
    let name = id;
    let suffix = 2;
    while (occupied.has(name)) {
      name = `${id}_${suffix++}`;
    }
    occupied.add(name);
    names[id] = name;
  }
  return names;
}

/** Keep nested insertion fields distinct from markers anywhere in the authored root. */
export function namespaceRequest(request, documentValue) {
  const names = fieldNames(request.fields || {}, documentValue);
  const inserts = clone(request.inserts);
  for (const {marker} of markers(inserts)) {
    marker.$fill = names[marker.$fill] || marker.$fill;
    if (marker.template) {
      marker.template = marker.template.replace(interpolation, (_, key) => '${' + (names[key] || key) + '}');
    }
  }
  return {...request, inserts,
    fields: Object.fromEntries(Object.entries(request.fields || {}).map(([id, field]) => [names[id], clone(field)]))};
}

/** Build a Preview request without mutating a library item or the document. */
export function libraryRequest(item, documentValue, replacements = {}) {
  const fields = item.fields || {};
  // Identity fields are bookkeeping, not questions the user must answer.
  replacements = {...Object.fromEntries(Object.entries(fields).filter(([, field]) => field.type === 'id')
    .map(([key, field]) => [key, field.default || (key === 'id' ? (item.id || 'item').replace(/[^A-Za-z0-9_-]/g, '') + '1' : key + '1')])), ...replacements};
  const names = fieldNames(fields, documentValue);
  const inserts = item.document ? [{at: '', values: [item.document]}]
    : item.inserts || (item.insert ? [item.insert] : []);
  return {inserts: uniquifyInserts(documentValue, expandFields(inserts, fields, replacements, names)),
    fields: Object.fromEntries(Object.entries(fields).map(([key, spec]) => [names[key], clone(spec)]))};
}
