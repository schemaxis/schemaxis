// Copyright (C) 2026 David L F Gaden
// Adaptor palette: search adaptors and their operations; drag onto the canvas or press Enter to add.

import {debounce, h, icon, mount} from '../../lib/dom.mjs';
import {avatar, identity} from '../../shell/providers.mjs';
import {ADAPTOR_MIME} from './canvas-input.mjs';

const MAX_OPERATIONS = 6;

function adaptorText(adaptor) {
  return [adaptor.id, identity(adaptor.id).name, adaptor.scope, ...(adaptor.keywords || []),
    ...(adaptor.operations || [])].join(' ').toLowerCase();
}

/** Group operation search hits by provider. */
function groupHits(items) {
  const groups = new Map();
  for (const item of items || []) {
    if (item.kind !== 'operation' || !item.provider) {
      continue;
    }
    if (!groups.has(item.provider)) {
      groups.set(item.provider, []);
    }
    groups.get(item.provider).push(item);
  }
  return groups;
}

export function createPalette(ctx, {onAdd}) {
  const search = h('input', {class: 'input dz-palette-search', type: 'search',
    placeholder: 'Search adaptors and operations',
    'aria-label': 'Search adaptors and operations'});
  const list = h('div', {class: 'dz-palette-list', role: 'listbox', 'aria-label': 'Adaptors'});
  const footer = h('div', {class: 'dz-palette-footer'}, 'Drag onto the canvas, or press Enter to add');
  const element = h('aside', {class: 'dz-palette', 'aria-label': 'Adaptor palette'},
    h('div', {class: 'dz-pane-header'}, h('span', {class: 'section-title'}, 'Adaptors')),
    h('div', {class: 'dz-palette-search-wrap'}, icon('search'), search),
    list, footer);
  let hits = new Map();
  let token = 0;

  function adaptors() {
    return ctx.store.get().adaptors.filter((item) => !item.hostOnly);
  }

  function row(adaptor, operations) {
    const info = identity(adaptor.id);
    const item = h('div', {
      class: 'dz-palette-item', role: 'option', tabindex: '0', draggable: 'true',
      'aria-label': `${info.name}. Press Enter to add an operation.`,
      dataset: {adaptor: adaptor.id},
      title: adaptor.scope || info.name,
      onDragstart: (event) => {
        event.dataTransfer.setData(ADAPTOR_MIME, adaptor.id);
        event.dataTransfer.setData('text/plain', adaptor.id);
        event.dataTransfer.effectAllowed = 'copy';
        item.classList.add('dragging');
      },
      onDragend: () => item.classList.remove('dragging'),
      onDblclick: () => onAdd(adaptor.id),
      onKeydown: (event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          onAdd(adaptor.id);
        } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault();
          const items = [...list.querySelectorAll('.dz-palette-item')];
          const next = items[items.indexOf(item) + (event.key === 'ArrowDown' ? 1 : -1)];
          if (next) {
            next.focus();
          }
        }
      },
    },
    h('div', {class: 'dz-palette-row'},
      avatar(adaptor.id),
      h('div', {class: 'dz-palette-text'},
        h('div', {class: 'dz-palette-name'}, info.name),
        h('div', {class: 'dz-palette-scope'}, adaptor.scope || adaptor.version)),
      h('button', {class: 'button ghost small icon-only dz-palette-add', tabindex: '-1',
        'aria-label': `Add ${info.name} operation`, title: 'Add operation',
        onClick: (event) => {
          event.stopPropagation();
          onAdd(adaptor.id);
        }}, icon('plus'))),
    operations.length ? h('div', {class: 'dz-palette-ops'}, operations.slice(0, MAX_OPERATIONS).map((op) => h('span', {
      class: 'dz-op-chip', title: op.purpose || op.label}, op.label)),
    operations.length > MAX_OPERATIONS ? h('span', {class: 'dz-op-more'}, `+${operations.length - MAX_OPERATIONS}`)
      : null) : null);
    return item;
  }

  function render() {
    const query = search.value.trim().toLowerCase();
    const all = adaptors();
    const rows = [];
    for (const adaptor of all) {
      const local = !query || adaptorText(adaptor).includes(query);
      const operations = query ? (hits.get(adaptor.id) || []) : [];
      const named = query ? (adaptor.operations || []).filter((name) => name.toLowerCase().includes(query)) : [];
      const merged = [...operations];
      for (const name of named) {
        if (!merged.some((item) => item.label === name)) {
          merged.push({label: name});
        }
      }
      if (local || merged.length) {
        rows.push({adaptor, operations: merged, rank: local ? 0 : 1});
      }
    }
    rows.sort((a, b) => a.rank - b.rank || identity(a.adaptor.id).name.localeCompare(identity(b.adaptor.id).name));
    mount(list, rows.length ? rows.map((item) => row(item.adaptor, item.operations))
      : h('div', {class: 'dz-palette-empty'}, icon('search'), 'No adaptor or operation matches.'));
  }

  const searchRemote = debounce(async () => {
    const query = search.value.trim();
    const current = ++token;
    if (!query) {
      hits = new Map();
      render();
      return;
    }
    const result = await ctx.call(() => ctx.api.post('/api/capabilities', {action: 'search', query, limit: 100}),
      {title: 'Could not search capabilities'});
    if (current === token) {
      hits = groupHits(result && result.items);
      render();
    }
  }, 220);

  search.addEventListener('input', () => {
    render();
    searchRemote();
  });
  search.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown' || event.key === 'Enter') {
      const first = list.querySelector('.dz-palette-item');
      if (first) {
        event.preventDefault();
        if (event.key === 'Enter') {
          onAdd(first.dataset.adaptor);
        } else {
          first.focus();
        }
      }
    }
  });
  const unsubscribe = ctx.store.watch((state) => state.adaptors, render);
  render();
  return {element, dispose: () => {
    unsubscribe();
    searchRemote.cancel();
  }};
}
