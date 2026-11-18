// Copyright (C) 2026 David L. F. Gaden.
// Declarative element naming and atomic multi-mode expansion; no adaptor branches.
import {atPointer, replacing} from '../../editor/fill-data.mjs';
import {identityPool} from './authoring-defaults.mjs';

export const savedNameHelp = 'A saved Name cannot be changed in Settings because other items may refer to it.';

export function instanceNames(documentValue, collection = '/nodes') {
  return collection === '/nodes' ? identityPool(documentValue)
    : new Set((atPointer(documentValue, collection) || []).map(item => item?.id));
}

export function suggestedName(item, value, used = new Set()) {
  const policy = item.authoring?.naming;
  if (!policy) return null;
  const fields = policy.path ? [policy] : item.authoring.instanceFields;
  const fragments = [];
  for (const field of fields || []) {
    if (field.style === 'omit') continue;
    const raw = atPointer(value, field.path);
    if (raw === undefined && !policy.path) continue;
    if (field.style === 'count') {
      if (Array.isArray(raw) && raw.length) fragments.push(String(raw.length));
      continue;
    }
    const values = Array.isArray(raw) ? raw : [raw];
    const entries = field.nameField ? values.flatMap(value => value?.[field.nameField]) : values;
    for (const entry of entries) {
      if (entry === undefined && field.nameField) continue;
      if (field.path.startsWith('/inputs/') && typeof entry?.node === 'string' && Number.isSafeInteger(entry.port)) {
        fragments.push(`${entry.node}_p${entry.port}`);
        continue;
      }
      const kinds = policy.path ? ['string'] : ['string', 'number', 'boolean'];
      if (!kinds.includes(typeof entry) || !String(entry).trim()) return null;
      const text = String(entry);
      fragments.push(field.style === 'lastSegment' ? text.split('/').filter(Boolean).at(-1) : text);
    }
  }
  if (!fragments.some(Boolean)) return null;
  const limit = item.maxNameLength || 100;
  let base = [policy.prefix || item.operation, ...fragments].filter(Boolean).join('_')
    .replace(/[^A-Za-z0-9_-]+/g, '_').replace(/_+/g, '_').replace(/_+$/, '');
  if (!base) return null;
  if (['lowercase', 'underscore'].includes(item.authoring.identityStyle)) base = base.replace(/[-_]+/g, '_');
  if (item.authoring.identityStyle === 'lowercase') base = base.toLowerCase();
  if (!/^[A-Za-z]/.test(base)) base = 'item_' + base;
  let name = base.slice(0, limit), suffix = 2;
  while (used.has(name)) {
    const ending = '_' + suffix++;
    if (ending.length >= limit) return null;
    name = base.slice(0, limit - ending.length) + ending;
  }
  return name;
}

export function rowValue(base, path, selection, name) {
  const value = replacing(structuredClone(base), path, structuredClone(selection));
  return name === undefined ? value : {...value, id: name};
}

/** Preserve the selected node's identity and every reference to it. New rows append in order. */
export function applyRows(documentValue, rows, existing = null, existingGroup = null, identityStyle, collection = '/nodes') {
  if (!rows.length) throw Error('Add at least one row.');
  const originals = existingGroup || (existing ? [existing] : []);
  const used = instanceNames(documentValue, collection);
  originals.forEach(member => used.delete(member.value.id));
  for (const row of rows) {
    if (identityStyle === 'label') {
      if (typeof row.id !== 'string' || !row.id.trim() || /[\u0000-\u001f\u007f-\u009f]/.test(row.id))
        throw Error('Enter a nonempty Name without control characters.');
    } else if (identityStyle === 'lowercase') {
      if (typeof row.id !== 'string' || !/^[a-z][a-z0-9_]*$/.test(row.id))
        throw Error('Each Name must start with a lowercase letter and use lowercase letters, digits, or _.');
    } else if (identityStyle === 'underscore') {
      if (typeof row.id !== 'string' || !/^[A-Za-z][A-Za-z0-9_]*$/.test(row.id))
        throw Error('Each Name must start with a letter and contain only letters, digits, or _.');
    } else if (typeof row.id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(row.id)) {
      throw Error('Each Name must start with a letter or digit and contain letters, digits, _ or -.');
    }
    if (used.has(row.id)) throw Error(`Name ${row.id} is already in use. Choose another Name.`);
    used.add(row.id);
  }
  if (originals.some((member, index) => rows[index]?.id !== member.value.id))
    throw Error('The original Names must stay unchanged to preserve their references.');
  let next = structuredClone(documentValue);
  originals.forEach((member, index) => { next = replacing(next, member.pointer, rows[index]); });
  return replacing(next, collection, [...(atPointer(next, collection) || []), ...rows.slice(originals.length)]);
}

const canonical = value => JSON.stringify(value, function (key, child) {
  return child && typeof child === 'object' && !Array.isArray(child)
    ? Object.fromEntries(Object.entries(child).sort(([a], [b]) => a.localeCompare(b))) : child;
});

export function groupRows(rows, selected, path) {
  const chosen = rows.filter((_, index) => selected.has(index));
  if (chosen.length < 2) throw Error('Select at least two new rows to group.');
  if (chosen.some(row => row.original)) throw Error('The original row cannot be grouped away; other nodes may refer to it.');
  const settings = row => canonical({...replacing(row.value, path, null), id: null});
  if (chosen.some(row => settings(row) !== settings(chosen[0]))) throw Error('Selected rows have different settings. Apply common settings before grouping.');
  const values = chosen.flatMap(row => atPointer(row.value, path));
  if (values.some(value => typeof value !== 'string')) throw Error('Group exact entries only. Patterns and exclusions keep their own selection semantics.');
  const merged = {...chosen[0], value: replacing(chosen[0].value, path, [...new Set(values)])};
  return rows.flatMap(row => row === chosen[0] ? [merged] : chosen.includes(row) ? [] : [row]);
}

/** Explicit master fan-out; discard only the untouched, sole draft starter. */
export function splitMasterRows(rows, source, path) {
  const entries = atPointer(source, path);
  if (!Array.isArray(entries) || !entries.length || entries.some(entry => typeof entry !== 'string' || !entry.trim()))
    throw Error('Choose exact items in the batch selection first. Patterns and exclusions stay together.');
  const replaceStarter = rows.length === 1 && rows[0].starter && !rows[0].original;
  const starter = replaceStarter ? rows[0] : null;
  const retained = replaceStarter ? [] : rows.slice();
  const same = value => canonical({...value, id: null});
  if (new Set(entries).size !== entries.length)
    throw Error('The batch selection contains repeated items. Select each item once.');
  for (const entry of entries) {
    const value = rowValue(source, path, [entry], source.id);
    if (retained.some(row => same(row.value) === same(value)))
      throw Error(`An instance already uses ${entry} with these settings. Remove it from the batch selection.`);
    const named = retained.length === 0 && starter?.named;
    if (named) value.id = starter.value.id;
    retained.push({value, selected: true, named: Boolean(named), expanded: false});
  }
  return {rows: retained, replaced: Boolean(replaceStarter), added: retained.length - (replaceStarter ? 0 : rows.length)};
}
