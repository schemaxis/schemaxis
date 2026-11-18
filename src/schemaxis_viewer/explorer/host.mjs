// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// Access to the local read-only host (standalone server or Studio). Files are
// read in place from the local disk; nothing is uploaded anywhere.

const params = new URL(location.href).searchParams;
const token = params.get('token');
let browserRoots = 0;

export const embedded = window.parent !== window;
export const suppliedTheme = params.get('theme');
export const suppliedCollection = params.get('collection');

export function localURL(value) {
  const url = new URL(value, location.href);
  if (token && url.origin === location.origin && !url.protocol.startsWith('blob')) url.searchParams.set('token', token);
  return url.href;
}

export async function api(route, body) {
  const response = await fetch(localURL('api/' + route), {method: body ? 'POST' : 'GET', cache: 'no-store',
    headers: body ? {'Content-Type': 'application/json'} : {}, body: body ? JSON.stringify(body) : undefined});
  if (!response.ok) {
    let message = '';
    try {
      message = (await response.json()).fault?.message || '';
    } catch {
      message = '';
    }
    throw Error(message || `The local viewer service answered HTTP ${response.status}`);
  }
  return response.json();
}

export async function initialCollection() {
  if (suppliedCollection) {
    const records = await api('inventory?id=' + encodeURIComponent(suppliedCollection));
    let label = 'Results';
    try {
      const listing = await api('library');
      const entry = listing.collections?.find(row => row.id === suppliedCollection);
      if (entry) return {records, sources: entry.sources || [], label: entry.label || label};
    } catch {
      label = 'Results';
    }
    return {records, sources: [], label};
  }
  try {
    const response = await fetch(localURL('inventory.json'), {cache: 'no-store'});
    if (!response.ok) return null;
    const records = await response.json();
    if (!Array.isArray(records) || !records.length) return null;
    const roots = [...new Set(records.map(record => record.rootLabel || record.root))];
    return {records, sources: [], label: roots.join(', ')};
  } catch {
    return null;
  }
}

export async function openPaths(paths) {
  const result = await api('open', {paths});
  return {records: result.records, sources: result.sources || [], label: paths.map(path => path.split('/').filter(Boolean).at(-1)).join(', '), id: result.id};
}

export async function library() {
  return api('library');
}

export async function browse(directory) {
  return api('browse' + (directory ? '?directory=' + encodeURIComponent(directory) : ''));
}

export async function reopen(row) {
  if (row.kind === 'run') {
    const records = await api('inventory?id=' + encodeURIComponent(row.id));
    return {records, sources: [], label: row.label};
  }
  return openPaths(row.paths);
}

export function browserRecords(entries, label = 'Selected files') {
  const root = `browser-${++browserRoots}`;
  return {records: entries.map(function record(entry, index) {
    return {id: `${root}-${index}`, relativePath: entry.path, root, rootLabel: label, size: entry.file.size,
      url: URL.createObjectURL(entry.file), file: entry.file};
  }), sources: [], label};
}

export async function droppedEntries(dataTransfer) {
  const entries = [];
  const pending = [...dataTransfer.items].map(item => item.webkitGetAsEntry?.()).filter(Boolean);
  if (!pending.length) return [...dataTransfer.files].map(file => ({file, path: file.name}));
  while (pending.length) {
    const entry = pending.shift();
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      entries.push({file, path: entry.fullPath.replace(/^\//, '')});
    } else if (entry.isDirectory && entry.name !== '.output-index') {
      const reader = entry.createReader();
      for (;;) {
        const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
        if (!batch.length) break;
        pending.push(...batch);
      }
    }
    if (entries.length > 50000) throw Error('More than 50,000 files were dropped; choose a smaller folder');
  }
  return entries;
}

export async function readText(item, limit = 32 * 1024 * 1024) {
  const response = await fetch(item.file ? item.url : localURL(item.url), {cache: 'no-store'});
  if (!response.ok) throw Error(`Could not read ${item.name} (HTTP ${response.status})`);
  const blob = await response.blob();
  const truncated = blob.size > limit;
  return {text: await (truncated ? blob.slice(0, limit) : blob).text(), truncated, size: blob.size};
}

export async function readBytes(item) {
  const response = await fetch(item.file ? item.url : localURL(item.url), {cache: 'no-store'});
  if (!response.ok) throw Error(`Could not read ${item.name} (HTTP ${response.status})`);
  return response.arrayBuffer();
}

export async function sha256(item) {
  if (!globalThis.crypto?.subtle) throw Error('this browser cannot compute SHA-256 here');
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', await readBytes(item)));
  return Array.from(digest, byte => byte.toString(16).padStart(2, '0')).join('');
}

export async function readCompanion(companion) {
  if (!companion || companion.size > 2 * 1024 * 1024) return null;
  const response = await fetch(companion.file ? companion.url : localURL(companion.url), {cache: 'no-store'});
  if (!response.ok) return null;
  return response.json();
}

export function mediaURL(item) {
  return item.file ? item.url : localURL(item.url);
}

export function notifyParent(message) {
  if (embedded) window.parent.postMessage(message, location.origin);
}
