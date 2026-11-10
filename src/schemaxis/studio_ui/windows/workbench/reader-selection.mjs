// Copyright (C) 2026 David L. F. Gaden
// Choosing names from a case: reader regions and arrays, or the blocks a filter
// extracts. A selection is everything, or a list of entries. An entry is an
// exact name, a regular expression, or (for blocks) an exclusion; expressions
// are resolved against the names in the case when it is loaded.
import {h, mount} from '../../lib/dom.mjs';

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
  let result = entries.some((entry) => !entry.exclude) ? [] : [...available];
  for (const entry of entries) {
    const matches = matchesOf(entry, available, blocks) || [];
    if (entry.exclude) result = result.filter((name) => !matches.includes(name));
    else result.push(...matches.filter((name) => !result.includes(name)));
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
 */
export function readerSelection({initial, label, field, inspect, names, fallback, blocks = false, required = null}) {
  let entries = entriesOf(initial);
  let all = !blocks && initial?.select === 'all';
  let editing = -1;
  let available = [];
  let loaded = false;
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
  const choices = h('div', {class: 'reader-choices'});
  const filter = h('input', {class: 'input', type: 'search', placeholder: 'Filter the names…', hidden: true,
    'aria-label': `Filter available ${short}`, onInput: renderChoices});
  const heading = h('strong', {class: 'reader-available-title'}, 'Names in the case');
  const loadButtons = h('div', {class: 'reader-load'},
    h('button', {class: 'button small', type: 'button', dataset: {action: 'load-names'}, onClick: () => load(false),
      title: 'Read the case headers. No mesh is loaded.'}, 'Load names'),
    h('button', {class: 'button small ghost', type: 'button', onClick: () => load(true),
      title: 'Ask the application for the names it reports. Slower, and complete.'}, 'Ask the application'));
  const named = h('div', {class: 'reader-named'}, list,
    h('div', {class: 'reader-add'}, kind, text, options, add, cancel), hint, summary);
  const element = h('div', {class: 'reader-selection'}, h('div', {class: 'reader-head'}, modes, loadButtons), named,
    h('div', {class: 'reader-available'}, h('div', {class: 'reader-available-head'}, heading, filter), state, choices));

  function setAvailable(inspection) {
    loaded = Boolean(inspection?.available !== false && inspection);
    const values = (inspection?.[field] || []).map(String);
    available = blocks ? [...new Set(values.map(blockName))] : values;
    heading.textContent = loaded ? `Names in the case (${available.length})` : 'Names in the case';
    state.textContent = !inspection ? 'Not loaded yet. Press Load names to list them here; entries work without them.'
      : inspection.available === false ? inspection.reason || inspection.message || 'No names could be read from this case.'
        : inspection.scope || 'Names reported by the application.';
    mount(options, available.map((name) => h('option', {value: name})));
    filter.hidden = available.length < 12;
    render();
  }

  async function load(live) {
    state.textContent = live ? 'Asking the application…' : 'Reading case headers…';
    try {
      const inspection = names ? await names.load(live) : await inspect(live);
      if (!names && element.isConnected) setAvailable(inspection);
    } catch (error) {
      state.textContent = error.message;
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

  function renderChoices() {
    const query = filter.value.trim().toLowerCase();
    const chosen = new Set(all ? available : selectedNames(entries, available, blocks));
    mount(choices, available.filter((name) => name.toLowerCase().includes(query)).map((name) => h('button', {
      class: ['wb-case-name', 'mono'], type: 'button', 'aria-pressed': String(chosen.has(name)), disabled: all,
      title: all ? 'Selected by All' : chosen.has(name) ? 'Selected by the entries' : 'Add as an exact name',
      onClick: () => {
        const value = blocks ? '//' + name : name;
        if (!entries.some((entry) => !entry.regex && entry.text === value)) entries.push({text: value, regex: false});
        render();
      }}, name)));
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
  const unsubscribe = names?.subscribe((inspection) => { if (element.isConnected) setAvailable(inspection); else unsubscribe?.(); });
  return {element, read() {
    if (all) return {select: 'all'};
    const pending = editing < 0 ? typed() : [];
    const chosen = [...entries, ...(Array.isArray(pending) ? pending : [])];
    if (!chosen.length) return required ? required() : undefined;
    return chosen.map((entry) => entry.exclude ? {exclude: entry.text} : entry.regex ? {pattern: entry.text} : entry.text);
  }};
}
