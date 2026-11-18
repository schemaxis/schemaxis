// Copyright (C) 2026 David L. F. Gaden.
// Studio provenance only: native documents remain ordinary independent nodes.
export function createAuthoringGroups(scope, storage) {
  const key = scope ? `schemaxis.studio.element-groups:${scope}` : null;
  const matchesFamily = (value, group) => group.collection === '/scenes'
    ? group.operation === 'document:scenes' && typeof value?.id === 'string' : value?.filter === group.operation;
  const valid = group => typeof group?.operation === 'string' && Array.isArray(group.members) && group.members.length
    && group.members.every(name => typeof name === 'string' && name.length)
    && new Set(group.members).size === group.members.length && matchesFamily(group.startingValue, group);
  let groups = [];
  try {
    storage ??= globalThis.localStorage;
    const saved = key && JSON.parse(storage.getItem(key) || 'null');
    if (saved?.version === 1 && Array.isArray(saved.groups)) groups = saved.groups.filter(valid);
  } catch { /* The current window can still remember batches without storage. */ }
  return {
    remember(group) {
      if (!valid(group)) return;
      // Keep earlier memberships: Undo can restore an older, smaller batch.
      if (JSON.stringify(groups.at(-1)) !== JSON.stringify(group)) groups.push(structuredClone(group));
      try { if (key) storage.setItem(key, JSON.stringify({version: 1, groups})); }
      catch { /* Storage limits do not prevent editing or lose this window's group. */ }
    },
    find(documentValue, name, operation, collection = '/nodes') {
      const elements = documentValue?.[collection.slice(1)] || [];
      for (const group of groups.slice().reverse()) {
        if (group.operation !== operation || (group.collection || '/nodes') !== collection || !group.members.includes(name)) continue;
        let invalid = false;
        const existing = group.members.flatMap(member => {
          const matches = elements.flatMap((value, index) => value?.id === member ? [{pointer: `${collection}/${index}`, value}] : []);
          // Deleted members stay in the record for Undo, but have no row to edit.
          if (!matches.length) return [];
          if (matches.length !== 1 || !matchesFamily(matches[0].value, group)) { invalid = true; return []; }
          return matches;
        });
        if (!invalid && existing.some(member => member.value.id === name)) {
          return {existing, members: [...group.members], startingValue: structuredClone(group.startingValue)};
        }
      }
      return null;
    },
  };
}
