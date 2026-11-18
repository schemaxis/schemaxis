// Copyright (C) 2026 David L. F. Gaden
// Names read from the selected case (regions, arrays, times), kept beside the
// editor so they can be dropped into the input wherever the cursor is.
import {h, mount} from '../../lib/dom.mjs';
import {sortedNames} from './reader-selection.mjs';

const GROUPS = [['regions', 'Regions', 'region'], ['cellArrays', 'Cell arrays', 'cell array'],
  ['pointArrays', 'Point arrays', 'point array'], ['availableTimes', 'Times', 'time']];

/** Preserve supplied time order and numeric types; naturally sort names. */
export function caseDataValues(inspection, key) {
  const values = inspection?.[key] || [];
  return key === 'availableTimes' ? [...values] : sortedNames(values);
}

export function caseDataCopy(inspection) {
  return Object.fromEntries(GROUPS.filter(([key]) => inspection?.[key]?.length)
    .map(([key]) => [key, caseDataValues(inspection, key)]));
}

/** A long-form CSV keeps uneven section lengths and punctuation lossless. */
export function caseDataCsv(inspection, section = null) {
  const quote = value => `"${String(value).replaceAll('"', '""')}"`;
  const rows = [['Section', 'Value'], ...GROUPS.filter(([key]) => !section || section === key)
    .flatMap(([key, label]) => caseDataValues(inspection, key).map(value => [label, value]))];
  return rows.map(row => row.map(quote).join(',')).join('\r\n') + '\r\n';
}

/** Names offered to the editor's completion list for a value at `pointer`. */
export function caseNames(inspection, pointer) {
  if (!inspection?.available) return [];
  const key = pointer.split('/').filter((part) => part && !/^\d+$/.test(part)).at(-1) || '';
  if (/^(id|file|filter|version|kind|type|node|input|source|writer|name)$/.test(key)) return [];
  const regions = (inspection.regions || []).map((value) => ({value, detail: 'region'}));
  const arrays = (inspection.cellArrays || []).map((value) => ({value, detail: 'cell array'}));
  return key === 'regions' ? regions : key === 'cellArrays' ? arrays : [...arrays, ...regions];
}

/** onUse(value) appends scalars/lists at the cursor, or copies, and returns a status line. */
export function createCaseData({onLoad, onUse}) {
  let inspection = null;
  const load = h('button', {class: 'button small', type: 'button', dataset: {action: 'case-names'},
    title: 'Read the case headers for region, array and time names. No mesh is loaded.', onClick: onLoad}, 'Load names');
  const state = h('p', {class: 'wb-help', role: 'status'});
  const filter = h('input', {class: 'input', type: 'search', placeholder: 'Filter names…', 'aria-label': 'Filter case names',
    hidden: true, onInput: render});
  const lists = h('div', {class: 'wb-case-lists'});
  const tools = h('div', {class: 'operation-file-tools wb-case-tools', hidden: true},
    h('button', {class: 'button small', type: 'button', title: 'Copy all sections as a JSON object',
      dataset: {action: 'copy-case-data'}, onClick: () => use(caseDataCopy(inspection))}, 'Copy all'),
    h('button', {class: 'button small', type: 'button', title: 'Export every section, including names hidden by the filter',
      dataset: {action: 'export-case-data'}, onClick: () => exportCsv()}, 'Export CSV'));
  const element = h('section', {class: 'wb-case-data', 'aria-label': 'Case data'},
    h('div', {class: 'wb-case-heading'}, h('h3', {class: 'wb-section-title'}, 'Case data'), load), state, tools, filter, lists);

  async function use(value) {
    try { state.textContent = await onUse(value); }
    catch (error) { state.textContent = `Could not copy or insert: ${error.message}`; }
  }

  function exportCsv(key = null) {
    const url = URL.createObjectURL(new Blob([caseDataCsv(inspection, key)], {type: 'text/csv;charset=utf-8'}));
    const link = h('a', {href: url, download: `case-data${key ? '-' + key : ''}.csv`});
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    state.textContent = `Exported ${key ? GROUPS.find(group => group[0] === key)[1] : 'all sections'} as CSV.`;
  }

  function render() {
    const available = Boolean(inspection?.available);
    filter.hidden = !available;
    tools.hidden = !available;
    load.textContent = available ? 'Refresh' : 'Load names';
    if (!inspection) {
      state.textContent = 'Load the names in the case to pick regions and arrays while you edit.';
      mount(lists);
      return;
    }
    if (!available) {
      state.textContent = inspection.reason || inspection.message || 'No names could be read from this case.';
      mount(lists);
      return;
    }
    const query = filter.value.trim().toLowerCase();
    state.textContent = `${inspection.node} · click a name to add it at the cursor.`;
    const observed = inspection.observation;
    mount(lists, observed ? h('div', {class: 'wb-help'},
      h('p', {}, `${observed.points} points · ${observed.cells} cells`),
      h('p', {}, `Bounds: ${observed.bounds.join(', ')}`)) : null,
    GROUPS.filter(([key]) => inspection[key]?.length).map(([key, label]) => {
      const offered = caseDataValues(inspection, key);
      const values = offered.filter((value) => String(value).toLowerCase().includes(query));
      return h('details', {open: Boolean(query) || key !== 'availableTimes', dataset: {section: key}},
        h('summary', {}, `${label} (${query ? `${values.length} of ` : ''}${inspection[key].length})`),
        h('div', {class: 'operation-file-tools wb-case-section-tools'},
          h('button', {class: 'button small', type: 'button', 'aria-label': `Copy ${label}`,
            title: `Use all ${offered.length} values in this section, including names hidden by the filter`,
            onClick: () => use(offered)}, 'Copy'),
          h('button', {class: 'button small', type: 'button', 'aria-label': `Export ${label} CSV`,
            title: `Export all ${label.toLowerCase()} as CSV`, onClick: () => exportCsv(key)}, 'Export CSV')),
        h('div', {class: 'wb-case-names'}, values.map((value) => h('button', {class: 'wb-case-name mono', type: 'button',
          title: `Add ${JSON.stringify(value)} at the cursor`,
          onClick: () => use(value)}, String(value)))));
    }), inspection.scope ? h('p', {class: 'wb-help'}, inspection.scope) : null);
  }
  render();
  return {element, update(next) {
    if (next !== inspection) {
      inspection = next || null;
      render();
    }
  }};
}
