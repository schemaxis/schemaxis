// Named authoring data stays in the document. No independent variable store.
import {atPointer, replacing} from '../../editor/fill-data.mjs';
import {escapeSegment} from '../../editor/json-pointer.mjs';

export const GROUPS = ['dimensions', 'settings', 'definitions'];
export const NAME = /^[A-Za-z][A-Za-z0-9_-]*$/;
export const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const namedMap = value => value && !Array.isArray(value) && typeof value === 'object'
  && !Object.keys(value).some(key => key.startsWith('$')) ? value : {};

export function scopes(root) {
  const design = root?.version?.startsWith('schemaxis.workflow-design/');
  const workflow = design ? root.workflow : root;
  if (workflow?.version === 'schemaxis.workflow/1') {
    const base = design ? '/workflow' : '';
    return [{base, label: 'Shared workflow', workflow: true}, ...(Array.isArray(workflow.operations) ? workflow.operations : []).map((op, i) =>
      ({base: `${base}/operations/${i}/document`, label: `Operation: ${op.id}`, operation: op.id}))];
  }
  return [{base: '', label: 'This document'}];
}

export function ownerAt(root, pointer = '') {
  return scopes(root).filter(scope => pointer === scope.base || pointer.startsWith(scope.base + '/'))
    .sort((a, b) => b.base.length - a.base.length)[0] || scopes(root)[0];
}

export function entries(root) {
  return scopes(root).flatMap(scope => {
    const document = atPointer(root, scope.base);
    return [...GROUPS.flatMap(group => Object.entries(namedMap(document?.[group])).map(([name, value]) =>
      ({...scope, name, group, value, pointer: `${scope.base}/${group}/${escapeSegment(name)}`}))),
    ...(Array.isArray(document?.axes) ? document.axes : []).flatMap((axis, index) => axis && typeof axis.name === 'string'
      ? [{...scope, name: axis.name, group: 'axes', value: axis, pointer: `${scope.base}/axes/${index}`}] : [])];
  });
}

export function reference(entry, target) {
  if (entry.group === 'axes') {
    if (entry.base !== target.base) throw Error('A sweep belongs to its document. Use a shared workflow value to bind across scopes.');
    return {$axis: entry.name};
  }
  const pointer = entry.pointer.slice(entry.base.length);
  return {$document: pointer, ...(entry.base === target.base ? {} : entry.workflow ? {scope: 'workflow'}
    : entry.operation ? {operation: entry.operation} : {})};
}

export function saveEntry(root, {base, name, group, value, parameter, units = '', help = ''}, previous) {
  if (!NAME.test(name)) throw Error('Use a letter, then letters, digits, _ or - for the name.');
  if (![...GROUPS, 'axes'].includes(group)) throw Error('Choose a supported value group.');
  const scope = scopes(root).find(s => s.base === base);
  if (!scope) throw Error('The owner document is no longer available.');
  const duplicate = entries(root).find(e => e.base === base && e.group === group && e.name === name);
  if (duplicate && duplicate.pointer !== previous?.pointer) throw Error('That name already exists in this group.');
  if (previous && (previous.name !== name || previous.group !== group || previous.base !== base)) {
    if (previous.group !== 'axes') root = replacing(root, previous.pointer, value);
    root = relocateEntry(root, previous, {base, name, group});
    previous = entries(root).find(e => e.base === base && e.group === group && e.name === name);
    if (group !== 'axes') value = previous.value;
  }
  let result = structuredClone(root);
  const owner = atPointer(result, base);
  if (group === 'axes') {
    if (value.values && (!Array.isArray(value.values) || !value.values.length)) throw Error('Provide a nonempty list of sweep values.');
    if (!value.values && !value.series) throw Error('Provide values or a regular series.');
    owner.axes ||= [];
    const axis = {...value, name};
    if (previous) owner.axes[Number(previous.pointer.split('/').at(-1))] = axis;
    else owner.axes.push(axis);
  } else {
    if (owner[group] !== undefined && (!owner[group] || Array.isArray(owner[group]) || typeof owner[group] !== 'object'
      || Object.keys(owner[group]).some(k => k.startsWith('$')))) throw Error(`The ${group} container is an expression; edit its source first.`);
    owner[group] ||= {};
    Object.defineProperty(owner[group], name, {value, enumerable: true, configurable: true, writable: true});
  }
  if (parameter) {
    if (root.version !== 'schemaxis.workflow-design/2' || !scope.workflow || group === 'axes') {
      throw Error('Case Runner parameters belong to shared values in a workflow design.');
    }
    const kind = typeof value === 'number' ? (Number.isInteger(value) ? 'integer' : 'number')
      : typeof value === 'boolean' ? 'boolean' : typeof value === 'string' ? 'string'
        : Array.isArray(value) && value.length && value.every(Number.isFinite) ? 'vector' : null;
    if (!kind) throw Error('Expose a literal number, text, boolean or numeric vector as a parameter.');
    if (units && !['number', 'integer', 'vector'].includes(kind)) throw Error('Units apply to numeric parameters only.');
    const pointer = `/${group}/${escapeSegment(name)}`;
    const existing = Object.entries(result.parameters || {}).find(([, p]) => p.target?.scope === 'workflow' && p.target.pointer === pointer);
    if (!existing && Object.hasOwn(result.parameters || {}, name)) throw Error('A different parameter already uses that name.');
    result.parameters ||= {};
    const spec = {label: name, kind, ...(existing?.[1] || {}), default: value,
      ...(kind === 'vector' && !existing ? {constraints: {length: value.length}} : {}),
      target: {scope: 'workflow', pointer}};
    if (units) spec.units = units; else delete spec.units;
    if (help) spec.help = help; else delete spec.help;
    result.parameters[existing?.[0] || name] = spec;
  }
  return result;
}


function absoluteReference(root, value, site) {
  const owner = value.scope === 'workflow' ? scopes(root).find(s => s.workflow)
    : value.operation ? scopes(root).find(s => s.operation === value.operation) : ownerAt(root, site);
  if (!owner) return null;
  if (value.$document.startsWith('/')) return owner.base + value.$document;
  const parts = site.slice(owner.base.length).split('/').slice(1, -1);
  for (const token of value.$document.split('/')) {
    if (token === '.') continue;
    if (token === '..') { if (!parts.length) throw Error('Relative reference escapes its document.'); parts.pop(); }
    else parts.push(token);
  }
  return owner.base + '/' + parts.join('/');
}
export function relocateEntry(root, previous, next) {
  if ((previous.group === 'axes') !== (next.group === 'axes')) throw Error('Sweeps and ordinary values use different contracts. Create the destination value and rebind consumers first.');
  if (previous.group === 'axes' && previous.base !== next.base) throw Error('A sweep is local to its document. Create a sweep in the destination scope and rebind consumers first.');
  const destination = `${next.base}/${next.group}/${escapeSegment(next.name)}`;
  const oldOwner = ownerAt(root, previous.pointer), newOwner = scopes(root).find(s => s.base === next.base);
  if (!newOwner) throw Error('Choose an available scope.');
  if (previous.workflow && !newOwner.workflow && Object.values(root.parameters || {}).some(p =>
    p.target?.scope === 'workflow' && (oldOwner.base + p.target.pointer === previous.pointer || (oldOwner.base + p.target.pointer).startsWith(previous.pointer + '/')))) {
    throw Error('This value is exposed in Case Runner. Keep it in shared workflow scope.');
  }
  const canonical = (target, site) => {
    const targetOwner = ownerAt(root, target);
    return {$document: target.slice(targetOwner.base.length), ...(targetOwner.base === ownerAt(root, site).base ? {}
      : targetOwner.workflow ? {scope: 'workflow'} : {operation: targetOwner.operation})};
  };
  const moving = previous.group !== 'axes';
  const mapped = site => moving && (site === previous.pointer || site.startsWith(previous.pointer + '/'))
    ? destination + site.slice(previous.pointer.length) : site;
  function visit(value, site = '') {
    if (!value || typeof value !== 'object') return value;
    if (typeof value.$document === 'string') {
      const target = absoluteReference(root, value, site);
      if (target) return canonical(mapped(target), mapped(site));
    }
    if (Array.isArray(value)) return value.map((v, i) => visit(v, site + '/' + i));
    const result = Object.fromEntries(Object.entries(value).map(([k, v]) => [k, visit(v, site + '/' + escapeSegment(k))]));
    if (previous.group === 'axes' && value.$axis === previous.name && ownerAt(root, site).base === previous.base) result.$axis = next.name;
    return result;
  }
  let result = visit(root);
  if (previous.group === 'axes') {
    atPointer(result, previous.pointer).name = next.name;
    return result;
  }
  const original = atPointer(result, previous.pointer);
  const targetOwner = atPointer(result, next.base);
  if (targetOwner[next.group] !== undefined && (!targetOwner[next.group] || Array.isArray(targetOwner[next.group])
      || typeof targetOwner[next.group] !== 'object' || Object.keys(targetOwner[next.group]).some(k => k.startsWith('$')))) {
    throw Error('The destination group is an expression. Edit its source first.');
  }
  delete atPointer(result, previous.base)[previous.group][previous.name];
  targetOwner[next.group] ||= {};
  Object.defineProperty(targetOwner[next.group], next.name, {value: original, enumerable: true, writable: true, configurable: true});
  for (const parameter of Object.values(result.parameters || {})) if (parameter.target?.scope === 'workflow') {
    const path = scopes(root).find(s => s.workflow).base + parameter.target.pointer;
    if (path === previous.pointer || path.startsWith(previous.pointer + '/')) parameter.target.pointer = mapped(path).slice(scopes(result).find(s => s.workflow).base.length);
  }
  return result;
}

export function valueCandidates(root) {
  return entries(root).flatMap(entry => {
    const result = [entry];
    const add = (value, suffix, name) => { result.push({...entry, name: entry.name + name, pointer: entry.pointer + suffix, value}); };
    if (Array.isArray(entry.value)) entry.value.forEach((v, i) => add(v, '/' + i, '.' + ('xyz'[i] || i)));
    if (entry.value?.min && entry.value?.max) for (const key of ['min', 'max']) {
      add(entry.value[key], '/' + key, '.' + key);
      entry.value[key].forEach((v, i) => add(v, `/${key}/${i}`, `.${key}.${'xyz'[i]}`));
    }
    return result;
  });
}

export function removeEntry(root, entry) {
  const uses = [];
  const scan = (value, pointer) => {
    if (pointer === entry.pointer) return;
    if (!value || typeof value !== 'object') return;
    if (typeof value.$document === 'string') {
      const owner = value.scope === 'workflow' ? scopes(root).find(s => s.workflow)
        : value.operation ? scopes(root).find(s => s.operation === value.operation) : ownerAt(root, pointer);
      const target = owner && owner.base + value.$document;
      if (target === entry.pointer || target?.startsWith(entry.pointer + '/')) uses.push(pointer);
      // Relative references need definition-site resolution; retain their targets
      // conservatively rather than deleting a value that may still be referenced.
      if (!value.$document.startsWith('/')) uses.push(pointer);
    }
    Object.entries(value).forEach(([k, v]) => scan(v, `${pointer}/${escapeSegment(k)}`));
  };
  // Axis references are local, so skip unrelated owners while checking them.
  if (entry.group === 'axes') {
    const visit = (v, p) => { if (v && typeof v === 'object') {
      if (v.$axis === entry.name) uses.push(p);
      Object.entries(v).forEach(([k, c]) => visit(c, p + '/' + escapeSegment(k)));
    }};
    visit(atPointer(root, entry.base), entry.base);
  } else scan(root, '');
  const workflow = scopes(root).find(s => s.workflow);
  const parameter = workflow && Object.values(root.parameters || {}).some(p => {
    const target = p.target?.scope === 'workflow' && workflow.base + p.target.pointer;
    return target && (target === entry.pointer || target.startsWith(entry.pointer + '/'));
  });
  if (uses.length || parameter) throw Error(`This value is in use${uses.length ? ': ' + uses.slice(0, 3).join(', ') : ' by a Case Runner parameter'}. Update its references first.`);
  const result = structuredClone(root), owner = atPointer(result, entry.base);
  if (entry.group === 'axes') owner.axes.splice(Number(entry.pointer.split('/').at(-1)), 1);
  else delete owner[entry.group][entry.name];
  return result;
}

/** Preview only static document references and scalar arithmetic; runtime results stay explicitly pending. */
export function preview(root, value, scope = scopes(root)[0], active = new Set()) {
  if (!value || typeof value !== 'object') return value;
  if (value.$document) {
    const owner = value.scope === 'workflow' ? scopes(root).find(s => s.workflow)
      : value.operation ? scopes(root).find(s => s.operation === value.operation) : scope;
    if (!owner || !value.$document.startsWith('/')) throw Error('Preview needs an absolute reference in an available scope.');
    const path = owner.base + value.$document;
    if (active.has(path)) throw Error('Circular value reference.');
    const target = atPointer(root, path);
    if (target === undefined) throw Error('The referenced value is missing.');
    return preview(root, target, owner, new Set([...active, path]));
  }
  if (value.$value) {
    const args = preview(root, value.args, scope, active), b = args.bounds;
    if (value.$value === 'boundsFromExtents') return {min: args.extents.filter((_, i) => i % 2 === 0), max: args.extents.filter((_, i) => i % 2 === 1)};
    if (b?.min && b?.max) {
      const mid = b.min.map((v, i) => (v + b.max[i]) / 2), size = b.min.map((v, i) => b.max[i] - v);
      if (value.$value === 'boundsCentre3D') return mid;
      if (value.$value === 'boundsSize') return size;
      if (value.$value === 'boundsPoint') return [...'xyz'].map((axis, i) => args[axis] === 'min' ? b.min[i] : args[axis] === 'max' ? b.max[i] : mid[i]);
      if (value.$value === 'boundsExtend') return {min: b.min.map((v, i) => v - (args.before?.[i] || 0) * size[i]), max: b.max.map((v, i) => v + (args.after?.[i] || 0) * size[i])};
    }
    throw Error('Resolved by host validation.');
  }
  if (value.$expr) {
    const {op, args} = value.$expr;
    if (!['add', 'subtract', 'multiply', 'divide'].includes(op)) throw Error('Resolved by host validation.');
    const values = args.map(arg => preview(root, arg, scope, active));
    if (values.length !== 2 || !values.every(v => typeof v === 'number' && Number.isFinite(v))) throw Error('Arithmetic requires two finite numbers.');
    const [a, b] = values;
    const result = {add: () => a + b, subtract: () => a - b, multiply: () => a * b, divide: () => a / b}[op]();
    if (!Number.isFinite(result)) throw Error('The calculation is not finite.');
    return result;
  }
  if (Object.keys(value).some(k => k.startsWith('$'))) throw Error('Available when the host resolves this expression or runs the workflow.');
  return Array.isArray(value) ? value.map(v => preview(root, v, scope, active))
    : Object.fromEntries(Object.entries(value).map(([k, v]) => [k, preview(root, v, scope, active)]));
}


/** Bind available shared values for draft inspection; unfinished nodes stay intact for host pruning. */
export function inspectionInput(root, document, base = '') {
  root = replacing(root, base, document);
  const scope = ownerAt(root, base);
  function visit(value) {
    if (!value || typeof value !== 'object') return value;
    if (value.$document && (value.scope || value.operation)) {
      try { return preview(root, value, scope); }
      catch { return structuredClone(value); } // The host reports unavailable required inputs after pruning.
    }
    return Array.isArray(value) ? value.map(visit) : Object.fromEntries(Object.entries(value).map(([key, item]) => [key, visit(item)]));
  }
  return visit(document);
}
