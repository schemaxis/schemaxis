// Copyright (C) 2026 David L F Gaden
// Completion popup and hover tooltip for the JSON editor.

import {h, mount} from '../lib/dom.mjs';

const MAX_ROWS = 300;
const KIND_LABELS = {property: 'P', value: 'V', snippet: 'S'};

function place(element, host, anchor) {
  element.hidden = false;
  const hostRect = host.getBoundingClientRect();
  const width = element.offsetWidth;
  const height = element.offsetHeight;
  let left = anchor.x;
  const maxLeft = Math.max(0, Math.min(hostRect.width, window.innerWidth - hostRect.left) - width - 4);
  left = Math.max(0, Math.min(left, maxLeft));
  let top = anchor.y + anchor.lineHeight;
  const spaceBelow = window.innerHeight - (hostRect.top + top);
  if (height > spaceBelow && anchor.y - height > -hostRect.top) {
    top = anchor.y - height;
  }
  element.style.left = `${Math.round(left)}px`;
  element.style.top = `${Math.round(top)}px`;
}

/** Completion list with a documentation side pane. */
export class CompletionPopup {
  constructor(host, {onAccept}) {
    this.host = host;
    this.onAccept = onAccept;
    this.items = [];
    this.index = 0;
    this.list = h('div', {class: 'sx-ed-popup-list', role: 'listbox', 'aria-label': 'Suggestions'});
    this.doc = h('div', {class: 'sx-ed-popup-doc'});
    this.element = h('div', {class: 'sx-ed-popup', hidden: true}, this.list, this.doc);
    this.element.addEventListener('mousedown', (event) => event.preventDefault());
    host.append(this.element);
  }

  isOpen() {
    return !this.element.hidden;
  }

  show(items, anchor) {
    this.items = items;
    this.index = 0;
    const rows = items.slice(0, MAX_ROWS).map((item, index) => this.row(item, index));
    if (items.length > MAX_ROWS) {
      rows.push(h('div', {class: 'sx-ed-item-more'}, `${items.length - MAX_ROWS} more — keep typing to filter`));
    }
    mount(this.list, rows);
    this.select(0);
    place(this.element, this.host, anchor);
  }

  row(item, index) {
    const kind = item.kind || 'value';
    return h('div', {
      class: ['sx-ed-item', item.deprecated && 'deprecated'],
      role: 'option',
      id: `sx-ed-item-${index}`,
      dataset: {index: String(index)},
      onMousedown: (event) => {
        event.preventDefault();
        this.select(index);
        this.onAccept(this.items[index]);
      },
      onMousemove: () => {
        if (this.index !== index) {
          this.select(index);
        }
      },
    },
    h('span', {class: ['sx-ed-kind', `sx-ed-kind-${kind}`], 'aria-hidden': 'true'}, KIND_LABELS[kind] || '·'),
    h('span', {class: 'sx-ed-item-label'}, item.label,
      item.required ? h('span', {class: 'sx-ed-required', title: 'Required'}, '*') : null),
    h('span', {class: 'sx-ed-item-detail'}, item.detail || ''));
  }

  select(index) {
    const count = Math.min(this.items.length, MAX_ROWS);
    if (!count) {
      return;
    }
    this.index = (index + count) % count;
    for (const row of this.list.querySelectorAll('.sx-ed-item.selected')) {
      row.classList.remove('selected');
      row.setAttribute('aria-selected', 'false');
    }
    const row = this.list.children[this.index];
    if (row) {
      row.classList.add('selected');
      row.setAttribute('aria-selected', 'true');
      const top = row.offsetTop;
      const bottom = top + row.offsetHeight;
      if (top < this.list.scrollTop) {
        this.list.scrollTop = top;
      } else if (bottom > this.list.scrollTop + this.list.clientHeight) {
        this.list.scrollTop = bottom - this.list.clientHeight;
      }
    }
    this.renderDoc(this.items[this.index]);
  }

  renderDoc(item) {
    if (!item || (!item.documentation && !item.detail)) {
      this.doc.hidden = true;
      mount(this.doc);
      return;
    }
    this.doc.hidden = false;
    mount(this.doc,
      h('div', {class: 'sx-ed-doc-title'}, item.label),
      item.detail ? h('div', {class: 'sx-ed-doc-detail'}, item.required ? `${item.detail} · required` : item.detail)
        : null,
      item.documentation ? h('div', {class: 'sx-ed-doc-body'}, item.documentation) : null);
  }

  move(delta) {
    this.select(this.index + delta);
  }

  selected() {
    return this.items[this.index] || null;
  }

  hide() {
    this.element.hidden = true;
    this.items = [];
  }
}

/** A small tooltip for hover documentation and diagnostics. */
export class HoverTooltip {
  constructor(host) {
    this.host = host;
    this.element = h('div', {class: 'sx-ed-tooltip', role: 'tooltip', hidden: true});
    host.append(this.element);
  }

  show(children, anchor) {
    mount(this.element, children);
    this.element.hidden = false;
    const hostRect = this.host.getBoundingClientRect();
    const width = this.element.offsetWidth;
    const height = this.element.offsetHeight;
    const maxLeft = Math.max(0, Math.min(hostRect.width, window.innerWidth - hostRect.left) - width - 4);
    const left = Math.max(0, Math.min(anchor.x, maxLeft));
    let top = anchor.y - height - 4;
    if (hostRect.top + top < 0) {
      top = anchor.y + anchor.lineHeight + 4;
    }
    this.element.style.left = `${Math.round(left)}px`;
    this.element.style.top = `${Math.round(top)}px`;
  }

  hide() {
    this.element.hidden = true;
  }
}

/** Build hover tooltip content from diagnostics and schema hover information. */
export function hoverContent(diagnostics, info) {
  const parts = [];
  for (const diagnostic of diagnostics) {
    parts.push(h('div', {class: ['sx-ed-tip-diag', `sx-ed-sev-${diagnostic.severity || 'error'}`]},
      `${diagnostic.message} (${diagnostic.pointer || '$'} · line ${diagnostic.line || 1}, column ${diagnostic.column || 1})`));
  }
  if (info) {
    const heading = [info.key && h('span', {class: 'sx-ed-tip-key'}, info.key),
      info.type && h('span', {class: 'sx-ed-tip-type'}, info.type),
      info.required && h('span', {class: 'sx-ed-tip-flag'}, 'required')];
    parts.push(h('div', {class: 'sx-ed-tip-head'}, heading));
    if (info.title && info.title !== info.description) {
      parts.push(h('div', {class: 'sx-ed-tip-title'}, info.title));
    }
    if (info.description) {
      parts.push(h('div', {class: 'sx-ed-tip-body'}, info.description));
    }
    if (info.alternatives && info.alternatives.length > 1) {
      parts.push(h('div', {class: 'sx-ed-tip-meta'}, `One of: ${info.alternatives.slice(1).join(' · ')}`));
    }
    const facts = [];
    if (info.default !== undefined) {
      facts.push(`default ${JSON.stringify(info.default)}`);
    }
    for (const [name, value] of Object.entries(info.constraints || {})) {
      facts.push(`${name} ${typeof value === 'string' ? value : JSON.stringify(value)}`);
    }
    if (info.enum && info.enum.length > 1 && info.enum.length <= 12) {
      facts.push(`one of ${info.enum.map((value) => JSON.stringify(value)).join(', ')}`);
    }
    if (facts.length) {
      parts.push(h('div', {class: 'sx-ed-tip-meta'}, facts.join(' · ')));
    }
  }
  return parts;
}
