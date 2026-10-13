// Command palette (Ctrl+K): fuzzy search over registered commands and documents.

import {h, icon, mount} from '../lib/dom.mjs';

export class Commands {
  constructor() {
    this.items = new Map();
  }

  /** Register {id, title, group, icon, shortcut, roles, run}. */
  register(command) {
    this.items.set(command.id, command);
    return () => this.items.delete(command.id);
  }

  list(role) {
    return [...this.items.values()].filter((item) => !item.roles || item.roles.includes(role));
  }

  run(id) {
    const command = this.items.get(id);
    if (command) {
      command.run();
    }
  }
}

/** Score a candidate: contiguous and word-start matches rank higher. 0 = no match. */
export function score(query, text) {
  if (!query) {
    return 1;
  }
  const needle = query.toLowerCase();
  const haystack = text.toLowerCase();
  const direct = haystack.indexOf(needle);
  if (direct >= 0) {
    return 100 - direct + (direct === 0 || haystack[direct - 1] === ' ' ? 50 : 0);
  }
  let position = 0;
  let total = 0;
  for (const character of needle) {
    const found = haystack.indexOf(character, position);
    if (found < 0) {
      return 0;
    }
    total += found === position ? 3 : 1;
    position = found + 1;
  }
  return total;
}

export function openPalette({commands, role, extraItems = []}) {
  const all = [...commands.list(role), ...extraItems];
  let selected = 0;
  let results = all;
  const input = h('input', {class: 'input', placeholder: 'Type a command, window or document…',
    'aria-label': 'Command palette', autocomplete: 'off', spellcheck: 'false'});
  const list = h('ul', {class: 'list palette-results', role: 'listbox'});
  const close = () => {
    backdrop.remove();
  };
  const execute = (item) => {
    close();
    item.run();
  };
  const render = () => {
    mount(list, results.slice(0, 50).map((item, index) => h('li', {
      class: 'list-item',
      role: 'option',
      'aria-selected': String(index === selected),
      onMousemove: () => {
        if (selected !== index) {
          selected = index;
          render();
        }
      },
      onClick: () => execute(item),
    },
    item.icon ? icon(item.icon) : null,
    h('div', {class: 'grow'},
      h('div', {class: 'title'}, item.title),
      item.group ? h('div', {class: 'subtitle'}, item.group) : null),
    item.shortcut ? h('kbd', {class: 'shortcut'}, item.shortcut) : null)));
    if (!results.length) {
      list.append(h('li', {class: 'empty-state'}, 'No matching commands'));
    }
    const active = list.children[selected];
    if (active && active.scrollIntoView) {
      active.scrollIntoView({block: 'nearest'});
    }
  };
  input.addEventListener('input', () => {
    const query = input.value.trim();
    results = all
      .map((item) => ({item, value: score(query, `${item.title} ${item.group || ''}`)}))
      .filter((entry) => entry.value > 0)
      .sort((a, b) => b.value - a.value)
      .map((entry) => entry.item);
    selected = 0;
    render();
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown') {
      selected = Math.min(selected + 1, Math.max(results.length - 1, 0));
      render();
      event.preventDefault();
    } else if (event.key === 'ArrowUp') {
      selected = Math.max(selected - 1, 0);
      render();
      event.preventDefault();
    } else if (event.key === 'Enter' && results[selected]) {
      execute(results[selected]);
    } else if (event.key === 'Escape') {
      close();
    }
  });
  const backdrop = h('div', {class: 'dialog-backdrop', onMousedown: (event) => {
    if (event.target === backdrop) {
      close();
    }
  }}, h('div', {class: 'dialog palette', role: 'dialog', 'aria-label': 'Command palette'}, input, list));
  document.body.append(backdrop);
  render();
  input.focus();
}
