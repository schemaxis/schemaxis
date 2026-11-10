// Copyright (C) 2026 David L. F. Gaden
// Names read from the selected case (regions, arrays, times), kept beside the
// editor so they can be dropped into the input wherever the cursor is.
import {h, mount} from '../../lib/dom.mjs';

const GROUPS = [['regions', 'Regions', 'region'], ['cellArrays', 'Cell arrays', 'cell array'],
  ['availableTimes', 'Times', 'time']];

/** Names offered to the editor's completion list for a value at `pointer`. */
export function caseNames(inspection, pointer) {
  if (!inspection?.available) return [];
  const key = pointer.split('/').filter((part) => part && !/^\d+$/.test(part)).at(-1) || '';
  if (/^(id|file|filter|version|kind|type|node|input|source|writer|name)$/.test(key)) return [];
  const regions = (inspection.regions || []).map((value) => ({value, detail: 'region'}));
  const arrays = (inspection.cellArrays || []).map((value) => ({value, detail: 'cell array'}));
  return key === 'regions' ? regions : key === 'cellArrays' ? arrays : [...arrays, ...regions];
}

/** onLoad() reads the names; onUse(value) places one in the input and returns a status line. */
export function createCaseData({onLoad, onUse}) {
  let inspection = null;
  const load = h('button', {class: 'button small', type: 'button', dataset: {action: 'case-names'},
    title: 'Read the case headers for region, array and time names. No mesh is loaded.', onClick: onLoad}, 'Load names');
  const state = h('p', {class: 'wb-help', role: 'status'});
  const filter = h('input', {class: 'input', type: 'search', placeholder: 'Filter names…', 'aria-label': 'Filter case names',
    hidden: true, onInput: render});
  const lists = h('div', {class: 'wb-case-lists'});
  const element = h('section', {class: 'wb-case-data', 'aria-label': 'Case data'},
    h('div', {class: 'wb-case-heading'}, h('h3', {class: 'wb-section-title'}, 'Case data'), load), state, filter, lists);

  function render() {
    const available = Boolean(inspection?.available);
    filter.hidden = !available;
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
    mount(lists, GROUPS.filter(([key]) => inspection[key]?.length).map(([key, label]) => {
      const values = inspection[key].filter((value) => String(value).toLowerCase().includes(query));
      return h('details', {open: Boolean(query) || key !== 'availableTimes'},
        h('summary', {}, `${label} (${query ? `${values.length} of ` : ''}${inspection[key].length})`),
        h('div', {class: 'wb-case-names'}, values.map((value) => h('button', {class: 'wb-case-name mono', type: 'button',
          title: `Add ${JSON.stringify(value)} at the cursor`,
          onClick: () => { state.textContent = onUse(value); }}, String(value)))));
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
