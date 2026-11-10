// Copyright (C) 2026 David L F Gaden
// Identity and connection choices shared by every adaptor's Add form.
export function identityPool(value) {
  const used = new Set();
  function visit(value) {
    if (!value || typeof value !== 'object') return;
    if (typeof value.id === 'string') used.add(value.id);
    if (Array.isArray(value.axes)) value.axes.forEach(axis => { if (typeof axis?.name === 'string') used.add(axis.name); });
    Object.values(value).forEach(visit);
  }
  visit(value); return used;
}

export function nextIdentity(base, used) {
  base = String(base || 'item').replace(/[^A-Za-z0-9_-]/g, '') || 'item';
  if (!/^[A-Za-z]/.test(base)) base = 'item' + base;
  let number = 1;
  while (used.has(base + number)) number++;
  const id = base + number; used.add(id); return id;
}

/** A node name from a chosen file: its name without the extension, or its folder for a generic "case" file. */
export function entryName(path, used) {
  const parts = String(path || '').split(/[\\/]+/).filter(Boolean);
  let base = (parts.at(-1) || '').replace(/\.[A-Za-z0-9]+$/, '');
  if (!base || /^case$/i.test(base)) base = parts.at(-2) || base;
  base = base.replace(/[^A-Za-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '');
  if (!base) return null;
  if (!/^[A-Za-z]/.test(base)) base = 'case_' + base;
  if (!used.has(base)) return base;
  let number = 2;
  while (used.has(`${base}_${number}`)) number++;
  return `${base}_${number}`;
}

export function pipelineChoices(documentValue, kind, kinds = {}) {
  return (Array.isArray(documentValue?.nodes) ? documentValue.nodes : [])
    .filter(node => typeof node?.id === 'string')
    .filter(node => !kind || kind === 'object' || !kinds[node.filter]?.length || kinds[node.filter].includes(kind));
}

export function preferredInput(documentValue, selected, kind, kinds) {
  const choices = pipelineChoices(documentValue, kind, kinds);
  return choices.find(node => node.id === selected)?.id || choices.at(-1)?.id;
}

export function initialOperation(item, documentValue, selected, kinds = {}) {
  const used = identityPool(documentValue), value = {};
  if (item.schema.properties?.id) value.id = nextIdentity(item.operation || item.id.split(':').at(-1), used);
  if (item.at === '/axes/-' && item.schema.properties?.name) value.name = nextIdentity('axis', used);
  // One primary connection is inferred; additional ports (e.g. seeds/mesh) stay explicit.
  const primary = Object.entries(item.ports || {}).find(([, port]) => port.required);
  if (primary && item.at === '/nodes/-') {
    const [name, port] = primary;
    const input = preferredInput(documentValue, selected, port.kind || 'object', kinds);
    if (input) value.inputs = {[name]: port.multiple ? [input] : input};
  }
  if (item.schema.properties?.node?.['x-studio-reference']) {
    const input = preferredInput(documentValue, selected, 'data', kinds);
    if (input) value.node = input;
  }
  return value;
}
