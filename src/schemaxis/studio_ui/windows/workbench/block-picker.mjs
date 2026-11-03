// Copyright (C) 2026 David L F Gaden
import {h, mount} from '../../lib/dom.mjs';

// Choices are native paths with human labels, scoped to the form's selected input.
export function blockControl({initial, getInput, inspect, subscribe}) {
  let selected = new Set(Array.isArray(initial) ? initial : []), blocks = [], generation = 0, source = '';
  const state = h('p', {class: 'wb-help', role: 'status'});
  const list = h('div', {class: 'block-picker-list', 'aria-label': 'Available blocks'});
  const search = h('input', {class: 'input', type: 'search', 'aria-label': 'Filter blocks', placeholder: 'Find a block or patch…', onInput: render});
  const manual = h('textarea', {class: 'input mono', rows: 3, 'aria-label': 'Advanced block selectors',
    value: [...selected].join('\n'), onInput: () => { selected = new Set(manual.value.split('\n').map(s => s.trim()).filter(Boolean)); render(); }});
  const reload = h('button', {class: 'button small', type: 'button', onClick: () => load(true)}, 'Refresh blocks');
  const element = h('div', {class: 'block-picker'}, state, h('div', {class: 'operation-file-tools'}, search, reload), list,
    h('details', {}, h('summary', {}, 'Advanced: selector paths'),
      h('p', {class: 'wb-help'}, 'Each selected block has a native path. Custom selectors can be entered one per line.'), manual));
  function render() {
    const query = search.value.toLowerCase();
    const known = new Set(blocks.map(block => block.selector));
    const choices = [...blocks, ...[...selected].filter(value => !known.has(value))
      .map(selector => ({selector, label: 'Custom: ' + selector, depth: 0}))];
    mount(list, choices.filter(block => `${block.label} ${block.selector}`.toLowerCase().includes(query))
      .map(block => h('label', {class: 'block-picker-row', style: {paddingLeft: `${8 + Math.min(block.depth, 12) * 16}px`}, title: block.selector},
        h('input', {type: 'checkbox', checked: selected.has(block.selector), 'aria-label': `Extract ${block.label}`, onChange: event => {
          if (event.target.checked) selected.add(block.selector); else selected.delete(block.selector);
          manual.value = [...selected].join('\n');
        }}), h('span', {}, block.label))));
  }
  async function load(force = false) {
    const ref = getInput?.(), node = typeof ref === 'string' ? ref : ref?.node;
    const key = JSON.stringify([node, ref?.port || 0]);
    if (!force && key === source) return;
    if (source && key !== source) { selected.clear(); manual.value = ''; }
    source = key; blocks = []; render(); const token = ++generation;
    if (!node) { state.textContent = 'Choose a pipeline input to see its blocks.'; return; }
    if (!inspect) { state.textContent = 'Block inspection is unavailable here; enter selector paths below.'; return; }
    state.textContent = `Reading blocks from ${node}…`; reload.disabled = true;
    try {
      const result = await inspect(ref, force);
      if (token !== generation || !element.isConnected) return;
      blocks = (result.assemblies?.Hierarchy || []).map(block => block.depth === 0 ? {...block, label: 'All blocks'} : block);
      state.textContent = blocks.length ? `Blocks in ${node}. Select a group to include its children.`
        : `${node} has no selectable composite blocks. Choose a composite reader or filter input.`;
      render();
    } catch (error) { if (token === generation) state.textContent = error.message; }
    finally { if (token === generation) reload.disabled = false; }
  }
  subscribe?.(() => load());
  queueMicrotask(() => load(true));
  return {element, read: () => [...selected]};
}
