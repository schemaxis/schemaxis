// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// DOM construction helpers and the icon set. Styles are applied through the
// CSSOM only, because the viewer's content security policy forbids inline styles.

const SVG = 'http://www.w3.org/2000/svg';

const ICONS = {
  menu: 'M3 6h18M3 12h18M3 18h18',
  folder: 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
  folderOpen: 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1H7l-4 9zM7 10h15l-3 9H3',
  files: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  groups: 'M4 5h16M4 5v4h16V5M4 13h16M4 13v6h16v-6M8 15.5h8',
  player: 'M7 4v16l13-8z',
  cube: 'M12 2l9 5v10l-9 5-9-5V7zM12 22V12M21 7l-9 5-9-5',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v6M12 7.5v.5',
  sun: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
  moon: 'M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z',
  chevronRight: 'M9 5l7 7-7 7',
  chevronLeft: 'M15 5l-7 7 7 7',
  chevronDown: 'M5 9l7 7 7-7',
  up: 'M12 19V5M5 12l7-7 7 7',
  close: 'M6 6l12 12M18 6L6 18',
  plus: 'M12 5v14M5 12h14',
  play: 'M7 4v16l13-8z',
  pause: 'M7 4h4v16H7zM14 4h4v16h-4z',
  stepBack: 'M18 5v14L8 12zM6 5v14',
  stepForward: 'M6 5v14l10-7zM18 5v14',
  first: 'M17 5v14L9 12zM7 5v14',
  last: 'M7 5v14l8-7zM17 5v14',
  reverse: 'M17 4v16L4 12z',
  grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  list: 'M8 6h13M8 12h13M8 18h13M3.5 6h.5M3.5 12h.5M3.5 18h.5',
  stack: 'M12 3l9 4.5-9 4.5-9-4.5zM3 12l9 4.5 9-4.5M3 16.5l9 4.5 9-4.5',
  image: 'M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15.5 9.5h.01',
  video: 'M3 6h13v12H3zM16 10l5-3v10l-5-3',
  audio: 'M9 18V5l11-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM20 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z',
  mesh: 'M12 2l9 5v10l-9 5-9-5V7zM12 22V12M21 7l-9 5-9-5',
  table: 'M3 5h18v14H3zM3 10h18M3 15h18M9 5v14',
  text: 'M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7',
  pdf: 'M6 3h9l4 4v14H6zM14 3v5h5M9 13h6M9 17h4',
  other: 'M6 3h9l4 4v14H6zM14 3v5h5',
  link: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',
  unlink: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1M4 4l16 16',
  loop: 'M17 2l4 4-4 4M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4M21 13v2a3 3 0 0 1-3 3H3',
  bounce: 'M4 12h16M8 8l-4 4 4 4M16 8l4 4-4 4',
  once: 'M4 12h14M14 8l4 4-4 4M21 6v12',
  split: 'M4 5h16v14H4zM12 5v14',
  expand: 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5',
  filter: 'M3 5h18l-7 8v6l-4 2v-8z',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2',
  pattern: 'M4 7h4M4 12h7M4 17h4M14 7l6 10M20 7l-6 10',
  check: 'M5 12l5 5 9-10',
  reset: 'M4 4v6h6M20 12a8 8 0 0 1-14.9 4M4.6 10A8 8 0 0 1 20 12',
  save: 'M12 4v11M7 10l5 5 5-5M5 20h14',
  tag: 'M3 12V4h8l10 10-8 8zM7.5 7.5h.01'
};

export function icon(name, size = 16) {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', 'icon');
  const path = document.createElementNS(SVG, 'path');
  path.setAttribute('d', ICONS[name] || ICONS.other);
  svg.append(path);
  return svg;
}

export function h(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'style') for (const [name, setting] of Object.entries(value)) node.style.setProperty(name, setting);
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (['checked', 'value', 'disabled', 'hidden', 'indeterminate', 'selected', 'open'].includes(key)) node[key] = value;
    else node.setAttribute(key, value === true ? '' : value);
  }
  append(node, children);
  return node;
}

function append(node, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) append(node, child);
    else node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function iconButton(name, label, onClick, attributes = {}) {
  return h('button', {class: 'icon-button', type: 'button', title: label, 'aria-label': label, onClick, ...attributes}, icon(name));
}

export function toggleButton(name, label, pressed, onClick, attributes = {}) {
  return h('button', {class: 'icon-button toggle', type: 'button', title: label, 'aria-label': label,
    'aria-pressed': String(!!pressed), onClick, ...attributes}, icon(name));
}

export function textButton(text, onClick, attributes = {}) {
  return h('button', {type: 'button', class: 'button', onClick, ...attributes}, text);
}

export function middleEllipsis(text, limit) {
  if (text.length <= limit) return text;
  const head = Math.ceil((limit - 1) * 0.6), tail = limit - 1 - head;
  return text.slice(0, head) + '…' + text.slice(text.length - tail);
}

export function chip(key, value, attributes = {}) {
  return h('span', {class: 'chip', ...attributes}, h('span', {class: 'chip-key'}, key), h('span', {class: 'chip-value'}, value));
}

export function fill(node, ...children) {
  node.replaceChildren();
  append(node, children);
  return node;
}

export function clear(node) {
  node.replaceChildren();
  return node;
}
