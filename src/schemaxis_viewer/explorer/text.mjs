// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// Text viewer: virtualised lines, find (plain or regular expression), "matching
// lines only" (grep) and a table of capture groups when the expression has them.

import {h, icon, toggleButton, iconButton, clear, fill} from './dom.mjs';
import {readText} from './host.mjs';
import {captureNames} from './rules.mjs';

const LINE = 20;
const MAX_MATCHES = 200000;

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export class TextView {
  constructor(container, item) {
    this.item = item;
    this.lines = [];
    this.matches = [];
    this.byLine = new Map();
    this.current = -1;
    this.options = {regex: false, ignoreCase: true, grep: false, captures: false};
    this.root = container.appendChild(h('div', {class: 'text-viewer'}));
    this.input = h('input', {type: 'search', placeholder: 'Find in file', 'aria-label': 'Find in file',
      onInput: () => this.schedule(), onKeydown: event => {
        if (event.key === 'Enter') {
          event.preventDefault();
          this.move(event.shiftKey ? -1 : 1);
        }
      }});
    this.inputBox = h('label', {class: 'search-box'}, icon('search'), this.input);
    this.counter = h('span', {class: 'counter'});
    this.error = h('span', {class: 'error'});
    this.toggles = h('span', {class: 'group'});
    this.root.append(h('div', {class: 'findbar'}, this.inputBox, this.toggles,
      iconButton('chevronLeft', 'Previous match (Shift+Enter)', () => this.move(-1)),
      iconButton('chevronRight', 'Next match (Enter)', () => this.move(1)), this.counter, this.error));
    this.scroll = this.root.appendChild(h('div', {class: 'text-scroll'}));
    this.sizer = this.scroll.appendChild(h('div'));
    this.window = this.scroll.appendChild(h('div', {class: 'text-lines'}));
    this.scroll.addEventListener('scroll', () => this.paint());
    this.observer = new ResizeObserver(() => this.paint());
    this.observer.observe(this.scroll);
    this.renderToggles();
    this.load();
  }

  async load() {
    try {
      const {text, truncated, size} = await readText(this.item);
      let shown = text;
      if (this.item.ext === 'json' && !truncated && size < 5 * 1024 * 1024) {
        try {
          shown = JSON.stringify(JSON.parse(text), null, 2);
        } catch {
          shown = text;
        }
      }
      this.lines = shown.split(/\r?\n/);
      if (truncated) this.lines.push('', `… showing the first ${Math.round(text.length / 1048576)} MB of ${Math.round(size / 1048576)} MB`);
      this.scroll.style.setProperty('--gutter', `${String(this.lines.length).length * 8 + 24}px`);
      this.search();
    } catch (error) {
      fill(this.window, h('div', {class: 'no-preview'}, error.message));
    }
  }

  focusFind() {
    this.input.focus();
    this.input.select();
  }

  renderToggles() {
    const flip = key => () => {
      this.options[key] = !this.options[key];
      this.renderToggles();
      this.search();
    };
    const hasCaptures = this.options.regex && captureNames(this.input.value).length > 0;
    fill(this.toggles,
      toggleButton('pattern', 'Regular expression', this.options.regex, flip('regex')),
      h('button', {type: 'button', class: 'icon-button toggle', title: 'Match case', 'aria-label': 'Match case',
        'aria-pressed': String(!this.options.ignoreCase), onClick: () => {
          this.options.ignoreCase = !this.options.ignoreCase;
          this.renderToggles();
          this.search();
        }}, 'Aa'),
      toggleButton('filter', 'Show matching lines only (grep)', this.options.grep, flip('grep')),
      hasCaptures ? toggleButton('table', 'Show capture groups as a table', this.options.captures, flip('captures')) : null);
  }

  schedule() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.renderToggles();
      this.search();
    }, 140);
  }

  search() {
    const query = this.input.value;
    this.matches = [];
    this.byLine = new Map();
    this.error.textContent = '';
    this.inputBox.classList.remove('invalid');
    let regex = null;
    if (query) {
      try {
        regex = new RegExp(this.options.regex ? query : escapeRegExp(query), 'g' + (this.options.ignoreCase ? 'i' : '') + 'd');
      } catch (error) {
        this.error.textContent = error.message.replace(/^Invalid regular expression: /, '');
        this.inputBox.classList.add('invalid');
      }
    }
    if (regex) {
      outer: for (let line = 0; line < this.lines.length; line++) {
        regex.lastIndex = 0;
        for (const match of this.lines[line].matchAll(regex)) {
          if (!match[0].length) continue;
          const entry = {line, start: match.index, end: match.index + match[0].length, groups: match.slice(1), named: match.groups};
          this.matches.push(entry);
          if (!this.byLine.has(line)) this.byLine.set(line, []);
          this.byLine.get(line).push(entry);
          if (this.matches.length >= MAX_MATCHES) break outer;
        }
      }
    }
    this.display = this.options.grep && query ? [...this.byLine.keys()] : null;
    this.current = this.matches.length ? 0 : -1;
    this.counter.textContent = query ? (this.matches.length ? `1 / ${this.matches.length}${this.matches.length >= MAX_MATCHES ? '+' : ''}` : 'No matches') : '';
    this.showCaptures = this.options.captures && this.options.grep && regex && this.options.regex && captureNames(query).length > 0;
    if (this.showCaptures) this.renderCaptures(query);
    else this.restoreLines();
    this.reveal();
  }

  restoreLines() {
    if (this.captureTable) {
      this.captureTable.remove();
      this.captureTable = null;
      this.scroll.append(this.sizer, this.window);
    }
    this.sizer.style.setProperty('height', `${(this.display || this.lines).length * LINE + 8}px`);
    this.paint();
  }

  renderCaptures(query) {
    const names = captureNames(query);
    this.sizer.remove();
    this.window.remove();
    this.captureTable?.remove();
    const rows = this.matches.slice(0, 20000);
    this.captureTable = h('table', {class: 'capture-table'},
      h('thead', {}, h('tr', {}, h('th', {}, 'line'), names.map(capture => h('th', {}, capture.name || `$${capture.index}`)))),
      h('tbody', {}, rows.map(match => h('tr', {}, h('td', {class: 'no'}, match.line + 1),
        names.map(capture => h('td', {}, match.groups[capture.index - 1] ?? ''))))));
    this.scroll.append(this.captureTable);
  }

  move(delta) {
    if (!this.matches.length) return;
    this.current = (this.current + delta + this.matches.length) % this.matches.length;
    this.counter.textContent = `${this.current + 1} / ${this.matches.length}`;
    this.reveal();
  }

  reveal() {
    if (this.showCaptures) return;
    const match = this.matches[this.current];
    if (match) {
      const row = this.display ? this.display.indexOf(match.line) : match.line;
      const top = row * LINE, height = this.scroll.clientHeight;
      if (top < this.scroll.scrollTop || top > this.scroll.scrollTop + height - LINE * 2) this.scroll.scrollTop = Math.max(0, top - height / 3);
    }
    this.paint();
  }

  paint() {
    if (this.showCaptures) return;
    const rows = this.display || this.lines;
    const first = Math.max(0, Math.floor(this.scroll.scrollTop / LINE) - 10);
    const last = Math.min(rows.length, Math.ceil((this.scroll.scrollTop + this.scroll.clientHeight) / LINE) + 10);
    const current = this.matches[this.current];
    const nodes = [];
    for (let row = first; row < last; row++) {
      const line = this.display ? this.display[row] : row;
      const text = this.lines[line];
      const content = [];
      let cursor = 0;
      for (const match of this.byLine.get(line) || []) {
        content.push(text.slice(cursor, match.start), h('mark', {class: match === current ? 'current' : ''}, text.slice(match.start, match.end)));
        cursor = match.end;
      }
      content.push(text.slice(cursor) || ' ');
      nodes.push(h('div', {class: 'text-line'}, h('span', {class: 'no'}, line + 1), h('span', {}, content)));
    }
    this.window.style.setProperty('top', `${first * LINE + 4}px`);
    this.window.replaceChildren(...nodes);
  }

  dispose() {
    this.observer.disconnect();
    clearTimeout(this.timer);
  }
}
