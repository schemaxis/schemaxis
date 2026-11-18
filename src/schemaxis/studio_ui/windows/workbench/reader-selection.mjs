// Copyright (C) 2026 David L. F. Gaden
// Choosing names from a case: reader regions and arrays, or the blocks a filter
// extracts. A selection is everything, or a list of entries. An entry is an
// exact name, a regular expression, or (for blocks) an exclusion; expressions
// are resolved against the names in the case when it is loaded.
import {h, mount} from '../../lib/dom.mjs';

const nameOrder = new Intl.Collator('en', {numeric: true, sensitivity: 'base'});

/** Natural, case-insensitive offered-name order, with a stable exact-name tie break. */
export function sortedNames(names) {
  return [...names].sort((a, b) => nameOrder.compare(a, b) || (a < b ? -1 : a > b ? 1 : 0));
}

export function parseNames(text) {
  const trimmed = text.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith('[')) {
    const values = JSON.parse(trimmed);
    if (!Array.isArray(values) || !values.every(v => typeof v === 'string' && v.length)) throw Error('Enter a JSON list of names.');
    return values;
  }
  return trimmed.split(/[\n,]+/).map(s => s.trim()).filter(Boolean).map(s => s.startsWith('"') ? JSON.parse(s) : s);
}

/** Entries from an authored value: names, {pattern} and {exclude} objects, or one {pattern}. */
export function entriesOf(value) {
  const entry = (item) => typeof item === 'string' ? {text: item, regex: false}
    : typeof item?.pattern === 'string' ? {text: item.pattern, regex: true}
      : typeof item?.exclude === 'string' ? {text: item.exclude, regex: true, exclude: true} : null;
  if (Array.isArray(value)) return value.map(entry).filter(Boolean);
  return typeof value?.pattern === 'string' ? [entry(value)] : [];
}

/** The name a block selector such as "//inlet" or "/Root/boundary/inlet" ends in. */
export const blockName = (selector) => selector.split('/').filter(Boolean).at(-1) || selector;

/** The names an entry selects from `available`; null when its expression is invalid. */
export function matchesOf(entry, available, blocks = false) {
  if (!entry.regex) return available.filter((name) => name === (blocks ? blockName(entry.text) : entry.text));
  try {
    const pattern = new RegExp(entry.text);
    return available.filter((name) => pattern.test(name));
  } catch {
    return null;
  }
}

/** The names a whole entry list selects, in the order the application resolves them. */
export function selectedNames(entries, available, blocks = false) {
  const result = new Set(entries.length && !entries.some((entry) => !entry.exclude) ? available : []);
  const offered = new Set(available);
  for (const entry of entries) {
    const exact = blocks ? blockName(entry.text) : entry.text;
    const matches = entry.regex ? matchesOf(entry, available, blocks) || [] : offered.has(exact) ? [exact] : [];
    for (const name of matches) {
      if (entry.exclude) result.delete(name);
      else result.add(name);
    }
  }
  return [...result];
}

/** Toggle one offered name without removing other names selected by a pattern. */
export function toggledName(entries, name, available, {blocks = false, all = false} = {}) {
  const exact = value => ({text: blocks ? '//' + value : value, regex: false});
  if (all) return {all: false, materialized: true, entries: available.filter(value => value !== name).map(exact)};
  const selected = selectedNames(entries, available, blocks).includes(name);
  const implicitAll = entries.length > 0 && entries.every(entry => entry.exclude);
  const exclusion = '^' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$';
  let next;
  if (selected) {
    next = entries.filter(entry => entry.regex || !matchesOf(entry, [name], blocks).length);
    // Removing the final positive selector must not turn leftover exclusions
    // into a new implicit selection of every other block.
    if (!implicitAll && !next.some(entry => !entry.exclude)) next = [];
    if (selectedNames(next, available, blocks).includes(name)) {
      if (blocks) next = [...next, {text: exclusion, regex: true, exclude: true}];
      else {
        next = next.flatMap(entry => entry.regex && matchesOf(entry, [name])?.length
          ? matchesOf(entry, available).filter(value => value !== name).map(exact) : [entry]);
        return {all: false, entries: next, materialized: true};
      }
    }
  } else {
    next = entries.filter(entry => !(entry.exclude && entry.text === exclusion));
    if (implicitAll && !next.length) next = [{text: '.*', regex: true}];
    if (!selectedNames(next, available, blocks).includes(name)) {
      if (implicitAll && next.every(entry => entry.exclude)) next = [{text: '.*', regex: true}, ...next];
      next = [...next, exact(name)];
    }
  }
  return {all: false, entries: next, materialized: false};
}

/** Set a subset without replacing patterns or selections outside that subset. */
export function setNamesSelected(entries, names, available, selected, options = {}) {
  if (options.blocks && !options.all) {
    const offered = new Set(available);
    const chosen = new Set(selectedNames(entries, available, true));
    const targets = [...new Set(names)].filter(name => offered.has(name) && chosen.has(name) !== selected);
    if (!targets.length) return {entries, all: false, materialized: false};
    const implicitAll = entries.length > 0 && entries.every(entry => entry.exclude);
    const exclusion = name => '^' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$';
    let next;
    if (selected) {
      const exclusions = new Set(targets.map(exclusion));
      next = entries.filter(entry => !(entry.exclude && exclusions.has(entry.text)));
      if (implicitAll && !next.length) next = [{text: '.*', regex: true}];
      const retained = new Set(selectedNames(next, available, true));
      const missing = targets.filter(name => !retained.has(name));
      if (implicitAll && missing.length && next.every(entry => entry.exclude)) next = [{text: '.*', regex: true}, ...next];
      next = [...next, ...missing.map(name => ({text: '//' + name, regex: false}))];
    } else {
      const removed = new Set(targets);
      next = entries.filter(entry => entry.regex || !removed.has(blockName(entry.text)));
      if (!implicitAll && !next.some(entry => !entry.exclude)) next = [];
      const retained = new Set(selectedNames(next, available, true));
      next = [...next, ...targets.filter(name => retained.has(name)).map(name => ({text: exclusion(name), regex: true, exclude: true}))];
    }
    return {entries: next, all: false, materialized: false};
  }
  let result = {entries, all: Boolean(options.all), materialized: false};
  for (const name of new Set(names)) {
    if (!available.includes(name)) continue;
    const chosen = result.all || selectedNames(result.entries, available, options.blocks).includes(name);
    if (chosen === selected) continue;
    const next = toggledName(result.entries, name, available, {...options, all: result.all});
    result = {...next, materialized: result.materialized || next.materialized};
  }
  return result;
}

const KINDS = [['exact', 'Exact name'], ['regex', 'Regular expression'], ['exclude', 'Exclude (regular expression)']];

/**
 * `names` is optional shared case data: {get() -> inspection or null, subscribe(listener), load(live)}.
 * Without it the control loads names itself through `inspect(live)`.
 * `blocks` selects blocks of a pipeline input: no All mode, exclusions allowed, names shown without
 * their region prefix. read() returns undefined when nothing is chosen (the reader's default,
 * `fallback`, stays in force), or `required()` when the setting cannot be left out.
 * `compact` puts offered names first and folds the exact/pattern entry editor.
 */
export function readerSelection({initial, label, field, inspect, names, fallback, blocks = false, required = null, compact = false}) {
  let entries = entriesOf(initial);
  let all = !blocks && initial?.select === 'all';
  let editing = -1;
  let available = [];
  let loaded = false;
  let nativeBlocks = false;
  let inspectionVersion = 0;
  let anchor = null;
  let anchorSelected = true;
  const short = blocks ? 'blocks' : label.split(/[./]/).at(-1);
  const modes = h('div', {class: 'wb-segmented', role: 'radiogroup', 'aria-label': `${label} selection mode`, hidden: blocks},
    [[true, 'All', 'Everything the reader offers, resolved when the case is loaded'],
      [false, 'Named entries', 'Exact names and regular expressions']].map(([value, text, hint]) => h('button', {type: 'button',
      role: 'radio', title: hint, dataset: {mode: value ? 'all' : 'names'}, onClick: () => { all = value; render(); }}, text)));
  const list = h('div', {class: 'reader-entries', role: 'list', 'aria-label': `${label} entries`});
  const kind = h('select', {class: 'input', 'aria-label': `${label} entry kind`, onChange: () => preview()},
    KINDS.filter(([value]) => blocks || value !== 'exclude').map(([value, text]) => h('option', {value}, text)));
  const options = h('datalist', {id: 'reader-names-' + Math.random().toString(36).slice(2)});
  const text = h('input', {class: 'input mono', 'aria-label': `${label} entry`, list: options.id,
    placeholder: blocks ? 'internalMesh, or ^wheels_[FR][RL]_T' : 'internalMesh, or ^patch/wheels_.*$', onInput: () => preview(),
    onKeydown: (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        event.stopPropagation();
        commit();
      } else if (event.key === 'Escape' && editing >= 0) {
        event.stopPropagation();
        stopEditing();
      }
    }});
  const add = h('button', {class: 'button small', type: 'button', dataset: {action: 'add-entry'}, onClick: commit}, 'Add entry');
  const cancel = h('button', {class: 'button small ghost', type: 'button', hidden: true, onClick: stopEditing}, 'Cancel');
  const hint = h('p', {class: 'wb-help', role: 'status'});
  const state = h('p', {class: 'wb-help', role: 'status'});
  const summary = h('p', {class: 'reader-summary', role: 'status', hidden: true});
  const selectionNote = h('p', {class: 'wb-help reader-selection-note', role: 'status', hidden: true});
  const choices = h('div', {class: 'reader-choices'});
  const filter = h('input', {class: 'input', type: 'search', placeholder: 'Filter the names…', hidden: true,
    'aria-label': `Filter available ${short}`, onInput: () => { anchor = null; renderChoices(); }});
  const shownNames = () => available.filter(name => name.toLowerCase().includes(filter.value.trim().toLowerCase()));
  const bulk = h('div', {class: 'operation-file-tools reader-bulk', hidden: true},
    h('button', {class: 'button small', type: 'button', dataset: {action: 'select-all'},
      title: 'Add every loaded block, including names hidden by the filter', onClick: () => chooseMany(available, true)}, 'Select All'),
    h('button', {class: 'button small', type: 'button', dataset: {action: 'deselect-all'},
      title: 'Clear all selectors, patterns, exclusions and pending entries', onClick: () => {
        entries = []; all = false; anchor = null; selectionNote.hidden = true; stopEditing();
      }}, 'Deselect All'),
    h('button', {class: 'button small', type: 'button', dataset: {action: 'select-shown'},
      onClick: () => chooseMany(shownNames(), true)}, 'Select shown'),
    h('button', {class: 'button small', type: 'button', dataset: {action: 'deselect-shown'},
      onClick: () => chooseMany(shownNames(), false)}, 'Deselect shown'));
  const heading = h('strong', {class: 'reader-available-title'}, 'Names in the case');
  const loadButtons = h('div', {class: 'reader-load'},
    h('button', {class: 'button small', type: 'button', dataset: {action: 'load-names'}, onClick: () => load(false),
      title: 'Read the case headers. No mesh is loaded.'}, 'Load names'),
    h('button', {class: 'button small ghost', type: 'button', onClick: () => load(true),
      title: 'Ask the application for the names it reports. Slower, and complete.'}, 'Ask the application'));
  const named = h('div', {class: 'reader-named'}, list,
    h('div', {class: 'reader-add'}, kind, text, options, add, cancel), hint, summary, selectionNote);
  const availablePanel = h('div', {class: 'reader-available'}, h('div', {class: 'reader-available-head'}, heading, filter), state, bulk,
    blocks ? h('p', {class: 'wb-help'}, 'Click to toggle; Shift-click a range. Filter to select a group. Drag a box to add names; Ctrl/Cmd-drag toggles them.') : null, choices);
  const element = h('div', {class: ['reader-selection', compact && 'reader-selection-compact']},
    h('div', {class: 'reader-head'}, modes, loadButtons),
    ...(compact ? [availablePanel, h('details', {class: 'reader-selectors', open: entries.some(entry => entry.regex)},
      h('summary', {}, 'Selectors and patterns'), named)] : [named, availablePanel]));

  function setAvailable(inspection) {
    loaded = Boolean(inspection?.available !== false && inspection);
    const values = (inspection?.[field] || []).map(String);
    available = sortedNames(blocks ? [...new Set(values.map(blockName))] : values);
    anchor = null;
    heading.textContent = loaded ? `Names in the case (${available.length})` : 'Names in the case';
    state.textContent = !inspection ? 'Not loaded yet. Press Load names to list them here; entries work without them.'
      : inspection.available === false ? inspection.reason || inspection.message || 'No names could be read from this case.'
        : inspection.scope || 'Names reported by the application.';
    mount(options, available.map((name) => h('option', {value: name})));
    filter.hidden = blocks ? !loaded : available.length < 12;
    render();
  }

  async function load(live) {
    const version = ++inspectionVersion;
    state.textContent = live ? 'Asking the application…' : 'Reading case headers…';
    try {
      // Native block choices belong to this input, even when reader header
      // hints are shared with the rest of the workbench.
      const direct = !names || (blocks && live);
      const inspection = direct ? await inspect(live) : await names.load(live);
      if (version !== inspectionVersion || !element.isConnected) return;
      nativeBlocks = blocks && live;
      setAvailable(inspection);
    } catch (error) {
      if (version === inspectionVersion) state.textContent = error.message;
    }
  }

  function describe(entry) {
    if (!loaded) return entry.regex && matchesOf(entry, []) === null ? 'not a valid expression' : '';
    const matches = matchesOf(entry, available, blocks);
    if (matches === null) return 'not a valid expression';
    if (!entry.regex) return matches.length ? '' : 'not in the loaded names';
    return matches.length ? `${matches.length} match${matches.length === 1 ? '' : 'es'}` : 'no matches';
  }

  /** The entries the text box holds, or an error message. Nothing is added to the list. */
  function typed() {
    const value = text.value.trim();
    if (!value) return [];
    if (kind.value !== 'exact') {
      if (matchesOf({text: value, regex: true}, []) === null) return 'Not a valid regular expression.';
      return [{text: value, regex: true, ...(kind.value === 'exclude' ? {exclude: true} : {})}];
    }
    try {
      return parseNames(value).map((name) => ({text: blocks && !name.includes('/') ? '//' + name : name, regex: false}));
    } catch (error) {
      return error.message;
    }
  }

  function preview() {
    const pending = typed();
    if (!text.value.trim()) {
      hint.textContent = editing >= 0 ? 'Editing an entry. Enter or Update entry keeps the change; Esc cancels.'
        : 'Type a name or an expression, then press Add entry (or Enter). Several exact names can be separated by commas.';
      return;
    }
    if (typeof pending === 'string') {
      hint.textContent = pending;
      return;
    }
    const matches = selectedNames(pending.map((entry) => ({...entry, exclude: false})), available, blocks);
    const verb = pending[0].exclude ? 'Would remove' : 'Would match';
    hint.textContent = !loaded ? 'Not added yet. Load names to see what this matches.'
      : `Not added yet. ${verb} ${matches.length} of ${available.length}${matches.length
        ? ': ' + matches.slice(0, 8).join(', ') + (matches.length > 8 ? ', …' : '') : ''}`;
  }

  function stopEditing() {
    editing = -1;
    text.value = '';
    add.textContent = 'Add entry';
    cancel.hidden = true;
    render();
  }

  function commit() {
    const next = typed();
    if (typeof next === 'string') {
      hint.textContent = next;
      return;
    }
    if (!next.length) return;
    const same = (a, b) => a.text === b.text && a.regex === b.regex && Boolean(a.exclude) === Boolean(b.exclude);
    if (editing >= 0) entries.splice(editing, 1, ...next);
    else entries.push(...next.filter((entry) => !entries.some((item) => same(item, entry))));
    stopEditing();
    text.focus();
  }

  function capturePending() {
    const pending = typed();
    if (typeof pending === 'string') { hint.textContent = pending; return false; }
    if (pending.length) {
      if (editing >= 0) entries.splice(editing, 1, ...pending);
      else entries.push(...pending.filter(entry => !entries.some(item => item.text === entry.text
        && item.regex === entry.regex && Boolean(item.exclude) === Boolean(entry.exclude))));
    }
    editing = -1; text.value = ''; add.textContent = 'Add entry'; cancel.hidden = true;
    return true;
  }

  function chooseMany(namesToSet, select) {
    if (!capturePending()) return;
    const next = setNamesSelected(entries, namesToSet, available, select, {blocks, all});
    entries = next.entries; all = next.all;
    selectionNote.hidden = false;
    selectionNote.textContent = select
      ? 'Added exact choices from the loaded names. Existing patterns and other selections are kept.'
      : 'Deselected these loaded names. Other selections and dynamic patterns are kept.';
    render();
  }

  function renderChoices() {
    const shown = shownNames();
    bulk.hidden = !blocks;
    bulk.querySelector('[data-action=select-all]').disabled = !available.length;
    for (const action of ['select-shown', 'deselect-shown']) {
      const button = bulk.querySelector(`[data-action=${action}]`);
      button.hidden = !filter.value.trim(); button.disabled = !shown.length;
    }
    const chosen = new Set(all ? available : selectedNames(entries, available, blocks));
    mount(choices, shown.map((name) => h('button', {
      class: ['wb-case-name', 'mono'], type: 'button', 'aria-pressed': String(chosen.has(name)),
      dataset: {name},
      title: chosen.has(name) ? 'Remove from selection' : 'Add to selection',
      onClick: event => {
        const restoreFocus = document.activeElement === event.currentTarget;
        if (blocks && event.shiftKey && shown.includes(anchor)) {
          const from = shown.indexOf(anchor), to = shown.indexOf(name);
          chooseMany(shown.slice(Math.min(from, to), Math.max(from, to) + 1), anchorSelected);
          if (restoreFocus) [...choices.querySelectorAll('button')].find(button => button.dataset.name === name)?.focus({preventScroll: true});
          return;
        }
        if (blocks && !capturePending()) return;
        const next = toggledName(entries, name, available, {blocks, all});
        entries = next.entries; all = next.all;
        anchor = name; anchorSelected = selectedNames(entries, available, blocks).includes(name);
        if (editing >= 0) stopEditing();
        selectionNote.hidden = !next.materialized;
        selectionNote.textContent = next.materialized ? 'This change uses exact names from the loaded list. Choose All or add a pattern for future matches.' : '';
        render();
        if (restoreFocus) [...choices.querySelectorAll('button')].find(button => button.textContent === name)?.focus({preventScroll: true});
      }}, name)), !shown.length && loaded ? h('p', {class: 'wb-help'}, 'No names match this filter.') : null);
  }

  // Box selection is confined to the offered chips. Pointer capture keeps a
  // drag alive outside the list; touch scrolling continues to work normally.
  if (blocks) {
    let drag = null;
    let suppressClick = false;
    const finish = (apply = false) => {
      if (!drag) return;
      const current = drag; drag = null;
      current.box?.remove();
      choices.querySelectorAll('.reader-box-hit').forEach(button => button.classList.remove('reader-box-hit'));
      if (choices.hasPointerCapture(current.id)) choices.releasePointerCapture(current.id);
      if (!current.box) return;
      suppressClick = true;
      setTimeout(() => { suppressClick = false; }, 0);
      if (!apply || !current.names.length || !capturePending()) return;
      if (current.toggle) {
        for (const name of current.names) entries = toggledName(entries, name, available, {blocks: true}).entries;
        render();
      } else chooseMany(current.names, true);
      anchor = null;
      element.dispatchEvent(new Event('change', {bubbles: true}));
    };
    choices.addEventListener('pointerdown', event => {
      if (event.button !== 0 || event.pointerType !== 'mouse') return;
      drag = {id: event.pointerId, x: event.clientX, y: event.clientY, toggle: event.ctrlKey || event.metaKey, names: []};
    });
    choices.addEventListener('pointermove', event => {
      if (!drag || drag.id !== event.pointerId) return;
      if (!drag.box && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 5) return;
      if (!drag.box) {
        drag.box = h('div', {class: 'reader-selection-box', 'aria-hidden': 'true'});
        choices.append(drag.box); choices.setPointerCapture(drag.id);
      }
      event.preventDefault();
      const bounds = choices.getBoundingClientRect();
      const left = Math.max(bounds.left, Math.min(drag.x, event.clientX));
      const right = Math.min(bounds.right, Math.max(drag.x, event.clientX));
      const top = Math.max(bounds.top, Math.min(drag.y, event.clientY));
      const bottom = Math.min(bounds.bottom, Math.max(drag.y, event.clientY));
      Object.assign(drag.box.style, {left: `${left - bounds.left + choices.scrollLeft}px`, top: `${top - bounds.top + choices.scrollTop}px`,
        width: `${Math.max(0, right - left)}px`, height: `${Math.max(0, bottom - top)}px`});
      drag.names = [...choices.querySelectorAll('button')].filter(button => {
        const rect = button.getBoundingClientRect();
        const hit = right > left && bottom > top && rect.right > left && rect.left < right && rect.bottom > top && rect.top < bottom;
        button.classList.toggle('reader-box-hit', hit); return hit;
      }).map(button => button.dataset.name);
    });
    choices.addEventListener('pointerup', () => finish(true));
    choices.addEventListener('pointercancel', () => finish());
    choices.addEventListener('lostpointercapture', () => finish());
    choices.addEventListener('keydown', event => { if (event.key === 'Escape' && drag?.box) { event.stopPropagation(); finish(); } });
    choices.addEventListener('click', event => { if (suppressClick) { event.preventDefault(); event.stopPropagation(); } }, true);
    choices.addEventListener('dragstart', event => event.preventDefault());
  }

  function render() {
    [...modes.children].forEach((button) => button.setAttribute('aria-checked', String((button.dataset.mode === 'all') === all)));
    named.hidden = all;
    mount(list, entries.length ? entries.map((entry, index) => {
      const note = describe(entry);
      return h('div', {class: 'reader-entry', role: 'listitem', 'aria-current': index === editing ? 'true' : undefined},
        h('span', {class: ['badge', entry.exclude && 'warn']}, entry.exclude ? 'exclude' : entry.regex ? 'regex' : 'exact'),
        h('code', {}, entry.text),
        note ? h('small', {class: /^(no|not)/.test(note) ? 'reader-entry-warning' : 'wb-help'}, note) : null,
        h('button', {class: 'button small ghost', type: 'button', onClick: () => {
          editing = index;
          kind.value = entry.exclude ? 'exclude' : entry.regex ? 'regex' : 'exact';
          text.value = entry.text;
          add.textContent = 'Update entry';
          cancel.hidden = false;
          render();
          text.focus();
        }}, 'Edit'),
        h('button', {class: 'button small ghost', type: 'button', onClick: () => {
          entries.splice(index, 1);
          if (editing >= 0) stopEditing();
          else render();
        }}, 'Delete'));
    }) : h('p', {class: 'wb-help'}, blocks ? 'No entries yet. Add a block name, a regular expression, or an exclusion below.'
      : `No entries: this setting is left out and the reader uses ${fallback === undefined
        ? 'its own default' : JSON.stringify(fallback)}. Add a name or a regular expression below to choose.`));
    const selected = selectedNames(entries, available, blocks);
    summary.hidden = !loaded || !entries.length || (!blocks && !entries.some((entry) => entry.regex));
    summary.textContent = `Selects ${selected.length} of ${available.length} in this case${selected.length
      ? ': ' + selected.slice(0, 12).join(', ') + (selected.length > 12 ? ', …' : '') : ''}`;
    renderChoices();
    preview();
  }

  setAvailable(names?.get() || null);
  const unsubscribe = names?.subscribe((inspection) => {
    if (!element.isConnected) unsubscribe?.();
    else if (!nativeBlocks) setAvailable(inspection);
  });
  return {element, invalidate(inspection = null) { inspectionVersion++; nativeBlocks = false; setAvailable(inspection); }, read() {
    if (all) return {select: 'all'};
    const pending = editing < 0 ? typed() : [];
    if (typeof pending === 'string') throw Error(pending);
    const chosen = [...entries, ...(Array.isArray(pending) ? pending : [])];
    if (!chosen.length) return required ? required() : undefined;
    return chosen.map((entry) => entry.exclude ? {exclude: entry.text} : entry.regex ? {pattern: entry.text} : entry.text);
  }};
}
