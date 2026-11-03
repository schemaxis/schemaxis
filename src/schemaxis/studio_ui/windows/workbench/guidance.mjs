// Copyright (C) 2026 David L F Gaden
// Common options come from the packaged recipes for the chosen operation.
import {parsePointer} from '../../editor/json-pointer.mjs';

export function nodeKinds(library, documentValue) {
  const nodes = Array.isArray(documentValue?.nodes) ? documentValue.nodes : [];
  return Object.fromEntries(nodes.filter((node) => typeof node?.id === 'string')
    .map((node) => [node.id, library?.operationKinds?.[node.filter] || []]));
}

/** Only scientific array containers from a native observation contribute choices. */
export function observationFields(value) {
  const names = new Set();
  const pending = [value];
  for (let visited = 0; pending.length && visited < 10000; visited += 1) {
    const current = pending.pop();
    if (!current || typeof current !== 'object') continue;
    for (const [key, child] of Object.entries(current)) {
      if (['pointData', 'cellData', 'fieldData', 'rowData', 'POINTS', 'CELLS', 'ROWS'].includes(key)
          && child && typeof child === 'object' && !Array.isArray(child)) {
        Object.keys(child).forEach((name) => names.add(name));
      } else if (child && typeof child === 'object') pending.push(child);
    }
  }
  return [...names].sort();
}

export function commonProperties(library, documentValue, pointer) {
  const parts = parsePointer(pointer || '');
  if (parts.at(-1) !== 'options') return [];
  let node = documentValue;
  for (const part of parts.slice(0, -1)) node = node?.[part];
  if (typeof node?.filter !== 'string') return [];
  const counts = new Map();
  const visit = (value) => {
    if (!value || typeof value !== 'object') return;
    if (value.filter === node.filter) {
      for (const key of Object.keys(value.options || {})) counts.set(key, (counts.get(key) || 0) + 1);
    }
    Object.values(value).forEach(visit);
  };
  for (const item of [...(library?.snippets || []), ...(library?.templates || [])]) {
    visit(item.inserts || item.document);
  }
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 8).map(([key]) => key);
}
