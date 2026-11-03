// Copyright (C) 2026 David L F Gaden
// Production search functions also used by adaptor-owned acceptance cases.
export function searchAdaptors(items, query, displayName = (item) => item.label || item.id) {
  query = query.trim().toLowerCase();
  return items.filter((item) => [item.id, displayName(item), item.scope || '',
    item.searchText || '', ...(item.keywords || []), ...(item.operations || [])]
    .join(' ').toLowerCase().includes(query));
}

export function searchAdd(items, query) {
  query = query.trim().toLocaleLowerCase();
  const rank = (item) => item.title.toLocaleLowerCase() === query ? 10
    : item.title.toLocaleLowerCase().startsWith(query) ? 5
    : item.title.toLocaleLowerCase().includes(query) ? 3 : 0;
  return items.filter((item) => `${item.title} ${item.description || ''} ${item.nativeDescription || ''} ${item.group || ''} ${item.searchText || ''}`
    .toLocaleLowerCase().includes(query)).sort((a, b) => rank(b) - rank(a));
}
