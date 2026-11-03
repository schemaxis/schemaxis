// Copyright (C) 2026 David L F Gaden
// Notifications: transient toasts plus a durable Problems/Log history.
// Errors are never silently replaced; each one stays in Problems until cleared.

import {h, icon} from '../lib/dom.mjs';
import {Store} from '../lib/store.mjs';

const ICONS = {error: 'error', warn: 'alert', info: 'info', ok: 'check'};
const DURATION = {info: 4000, ok: 3500, warn: 8000, error: 0};

let nextId = 1;

export class Notifier {
  constructor() {
    this.store = new Store({problems: [], log: []});
    this.container = h('div', {class: 'toasts', role: 'region', 'aria-label': 'Notifications'});
  }

  /** Record and show a message. Returns the entry. */
  push(level, title, {body, code, location, source, actions, sticky} = {}) {
    const entry = {
      id: nextId++, level, title, body, code, location, source,
      time: new Date(),
    };
    const log = [...this.store.get().log, entry].slice(-500);
    const update = {log};
    if (level === 'error' || level === 'warn') {
      update.problems = [...this.store.get().problems, entry];
    }
    this.store.set(update);
    this.toast(entry, actions, sticky);
    return entry;
  }

  info(title, options) {
    return this.push('info', title, options);
  }

  ok(title, options) {
    return this.push('ok', title, options);
  }

  warn(title, options) {
    return this.push('warn', title, options);
  }

  /** Report an ApiError, Error or plain fault object. */
  error(error, {title, source, actions} = {}) {
    const fault = error && error.fault ? error.fault : error || {};
    const message = fault.message || (error && error.message) || 'Something went wrong.';
    const recovery = fault.recovery ? ` ${fault.recovery}` : '';
    return this.push('error', title || humanise(fault.code) || 'Error', {
      body: message + recovery,
      code: fault.code,
      location: fault.location,
      source,
      actions,
    });
  }

  /** One toast per explicit action; each diagnostic remains independently actionable in Problems. */
  group(diagnostics, {title = 'Input needs attention', source, actions = () => []} = {}) {
    if (!diagnostics.length) return [];
    const group = nextId++;
    const entries = diagnostics.map((item) => ({
      id: nextId++, group, level: item.severity === 'warning' ? 'warn' : 'error', title,
      body: item.message, code: item.code, location: `${item.pointer || item.location || '$'}${item.line ? ` · line ${item.line}, column ${item.column || 1}` : ''}`, source,
      actions: actions(item), time: new Date(),
    }));
    this.store.set((state) => ({problems: [...state.problems, ...entries],
      log: [...state.log, ...entries].slice(-500)}));
    this.toast({level: entries.some((item) => item.level === 'error') ? 'error' : 'warn',
      title: `${entries.length} problem${entries.length === 1 ? '' : 's'} — see Problems`});
    return entries;
  }

  dismissProblem(id) {
    this.store.set((state) => ({problems: state.problems.filter((item) => item.id !== id)}));
  }

  clearProblems() {
    this.store.set({problems: []});
  }

  toast(entry, actions = [], sticky = false) {
    const close = () => {
      element.remove();
    };
    const actionButtons = (actions || []).map((action) => h('button', {
      class: 'button small',
      onClick: () => {
        action.run();
        close();
      },
    }, action.label));
    const element = h('div', {class: ['toast', entry.level], role: entry.level === 'error' ? 'alert' : 'status'},
      icon(ICONS[entry.level]),
      h('div', {},
        h('div', {class: 'toast-title'}, entry.title),
        entry.body ? h('div', {class: 'toast-body'}, entry.body) : null,
        entry.code ? h('div', {class: 'toast-code'},
          entry.code + (entry.location ? ` · ${entry.location}` : '')) : null,
        actionButtons.length ? h('div', {class: 'toast-actions'}, actionButtons) : null),
      h('button', {class: 'button ghost small icon-only', 'aria-label': 'Dismiss', onClick: close}, icon('close')));
    this.container.append(element);
    while (this.container.children.length > 4) {
      this.container.firstElementChild.remove();
    }
    const duration = sticky ? 0 : DURATION[entry.level];
    if (duration) {
      setTimeout(close, duration);
    }
  }
}

/** Turn FAULT_CODE into "Fault code". */
export function humanise(code) {
  if (!code) {
    return '';
  }
  const words = code.toLowerCase().split('_').join(' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}
