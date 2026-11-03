// Copyright (C) 2026 David L F Gaden
// Shared viewer scaffolding: events, the frame (toolbar, body, status bar,
// state overlay), small toolbar controls and theme colour reading.

import {h} from '../lib/dom.mjs';
import {viewerIcon} from './icons.mjs';

/** A tiny event emitter: on(name, handler) returns an unsubscribe function. */
export function createEmitter() {
  const handlers = new Map();
  return {
    on(name, handler) {
      if (!handlers.has(name)) {
        handlers.set(name, new Set());
      }
      handlers.get(name).add(handler);
      return () => handlers.get(name)?.delete(handler);
    },
    emit(name, payload) {
      for (const handler of [...(handlers.get(name) || [])]) {
        try {
          handler(payload);
        } catch (error) {
          // A faulty subscriber must not break the viewer; surface it asynchronously.
          setTimeout(() => {
            throw error;
          });
        }
      }
    },
    clear() {
      handlers.clear();
    },
  };
}

/**
 * Build the standard viewer frame inside a container.
 * Returns {root, toolbar, body, status, setState(state, message)}.
 * States: 'empty', 'loading', 'error', 'ready'.
 */
export function createFrame(container, {kind, label, emptyMessage}) {
  const toolbar = h('div', {class: 'vw-toolbar', role: 'toolbar', 'aria-label': `${label} tools`});
  const body = h('div', {class: 'vw-body'});
  const status = h('div', {class: 'vw-status', 'aria-live': 'polite'});
  const overlayIcon = h('div', {class: 'vw-overlay-icon', 'aria-hidden': 'true'});
  const overlayText = h('div', {class: 'vw-overlay-text'});
  const overlay = h('div', {class: 'vw-overlay', role: 'status'}, overlayIcon, overlayText);
  const root = h('section', {class: ['vw', `vw-${kind}`], 'aria-label': label, dataset: {state: 'empty'}},
    toolbar, h('div', {class: 'vw-stage'}, body, overlay), status);
  container.append(root);

  function setState(state, message) {
    root.dataset.state = state;
    overlay.hidden = state === 'ready';
    overlay.classList.toggle('vw-overlay-error', state === 'error');
    if (state === 'loading') {
      overlayIcon.replaceChildren(h('span', {class: 'vw-spinner'}));
    } else if (state === 'error') {
      overlayIcon.replaceChildren(viewerIcon('alert'));
    } else {
      overlayIcon.replaceChildren(viewerIcon(kind === 'viewer3d' ? 'cube' : kind));
    }
    overlay.setAttribute('role', state === 'error' ? 'alert' : 'status');
    overlayText.textContent = message || (state === 'loading' ? 'Loading…' : emptyMessage);
  }

  setState('empty');
  return {root, toolbar, body, status, setState};
}

/** A toolbar button. Pass {pressed: false} to make it a toggle (aria-pressed). */
export function toolButton({icon, text, title, onClick, pressed, className}) {
  const button = h('button', {
    type: 'button',
    class: ['vw-btn', className, text && icon ? 'vw-btn-labelled' : null, !text ? 'vw-btn-icon' : null],
    title,
    'aria-label': text ? undefined : title,
    'aria-pressed': pressed === undefined ? undefined : String(Boolean(pressed)),
    onClick,
  }, icon ? viewerIcon(icon) : null, text ? h('span', {}, text) : null);
  return button;
}

/** Set aria-pressed on a toggle button. */
export function setPressed(button, pressed) {
  button.setAttribute('aria-pressed', String(Boolean(pressed)));
}

/** A labelled select: options are [value, text] pairs. */
export function toolSelect({label, options, value, onChange, title}) {
  const select = h('select', {class: 'vw-select', title: title || label, 'aria-label': label},
    options.map(([optionValue, text]) => h('option', {value: optionValue}, text)));
  select.value = value;
  select.addEventListener('change', () => onChange(select.value));
  return select;
}

export function separator() {
  return h('span', {class: 'vw-sep', role: 'separator', 'aria-orientation': 'vertical'});
}

export function spacer() {
  return h('span', {class: 'vw-spacer'});
}

/** Read CSS custom properties from an element as a {name: value} map. */
export function readTokens(element, names) {
  const style = getComputedStyle(element);
  const result = {};
  for (const name of names) {
    result[name] = style.getPropertyValue(`--${name}`).trim();
  }
  return result;
}

/** Parse a CSS colour (#rgb, #rrggbb, rgb(), rgba()) into [r, g, b, a] in 0..1. */
export function parseColour(text, fallback = [0.5, 0.5, 0.5, 1]) {
  const value = String(text || '').trim();
  let match = value.match(/^#([0-9a-f]{3,8})$/i);
  if (match) {
    let hex = match[1];
    if (hex.length === 3 || hex.length === 4) {
      hex = [...hex].map((c) => c + c).join('');
    }
    const parts = [0, 2, 4, 6].map((i) => parseInt(hex.slice(i, i + 2) || 'ff', 16) / 255);
    return parts;
  }
  match = value.match(/^rgba?\(([^)]+)\)$/i);
  if (match) {
    const parts = match[1].split(/[\s,/]+/).filter(Boolean).map(Number);
    if (parts.length >= 3 && parts.slice(0, 3).every(Number.isFinite)) {
      return [parts[0] / 255, parts[1] / 255, parts[2] / 255, Number.isFinite(parts[3]) ? parts[3] : 1];
    }
  }
  return fallback;
}

/**
 * Call handler when the theme changes: a 'themechange' event on document,
 * a data-theme attribute change on <html>, or the OS colour-scheme preference.
 * Returns a function that stops watching.
 */
export function watchTheme(handler) {
  const fire = () => requestAnimationFrame(() => handler());
  document.addEventListener('themechange', fire);
  const observer = new MutationObserver(fire);
  observer.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme', 'class']});
  const media = matchMedia('(prefers-color-scheme: dark)');
  media.addEventListener('change', fire);
  return () => {
    document.removeEventListener('themechange', fire);
    observer.disconnect();
    media.removeEventListener('change', fire);
  };
}

/** Format a number compactly for read-outs. */
export function formatNumber(value, digits = 6) {
  if (typeof value !== 'number') {
    return String(value ?? '');
  }
  if (!Number.isFinite(value)) {
    return String(value);
  }
  if (Number.isInteger(value) && Math.abs(value) < 1e15) {
    return value.toLocaleString('en-CA');
  }
  const magnitude = Math.abs(value);
  if (magnitude !== 0 && (magnitude < 1e-4 || magnitude >= 1e9)) {
    return value.toExponential(Math.max(0, digits - 3));
  }
  return String(Number(value.toPrecision(digits)));
}

/** Yield to the event loop (macrotask) so long jobs never freeze the UI. */
export function yieldToBrowser() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/** True when a key event should be left to a text field. */
export function isTyping(event) {
  const target = event.target;
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement
    || target instanceof HTMLSelectElement || target?.isContentEditable;
}
