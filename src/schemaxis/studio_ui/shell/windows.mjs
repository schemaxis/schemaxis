// Copyright (C) 2026 David L F Gaden
// Window manager: each tab hosts one window instance created from a registered type.
//
// A window type is {type, title, icon, roles, singleton, create(ctx, params)}; create
// returns {element, title?, subtitle?, onShow?, onHide?, dispose?, canClose?}.

import {h, icon, mount} from '../lib/dom.mjs';
import {Store} from '../lib/store.mjs';
import {documentMenu} from '../windows/document-menu.mjs';

export class WindowManager {
  constructor(ctx, host, tabBar) {
    this.ctx = ctx;
    this.host = host;
    this.tabBar = tabBar;
    this.types = new Map();
    this.instances = new Map();
    this.store = new Store({order: [], active: null});
    this.storageKey = 'schemaxis.studio.tabs';
    this.store.subscribe(() => {
      this.renderTabs();
      this.persist();
    });
  }

  register(type) {
    this.types.set(type.type, type);
  }

  key(type, params = {}) {
    const definition = this.types.get(type);
    if (definition && definition.singleton) {
      return type;
    }
    return params.document ? `${type}:${params.document}${params.operation ? `:${params.operation}` : ''}`
      : `${type}:${params.id || Date.now()}`;
  }

  /** Open (or focus) a window. Returns its key. */
  open(type, params = {}) {
    const definition = this.types.get(type);
    if (!definition) {
      this.ctx.notify.warn('Unknown window', {body: `No window type "${type}" is registered.`});
      return null;
    }
    if (definition.roles && !definition.roles.includes(this.ctx.role())) {
      this.ctx.notify.info('Change interface role to open this window', {
        body: `${definition.title} is available in ${definition.roles.join(' or ')} mode.`,
      });
      return null;
    }
    const key = params.key || this.key(type, params);
    if (!this.instances.has(key)) {
      const element = h('section', {class: 'window', hidden: true, dataset: {window: type}});
      let created;
      try {
        created = definition.create(this.ctx, params, {
          setTitle: (title, subtitle) => this.setTitle(key, title, subtitle),
          close: () => this.close(key),
        });
      } catch (error) {
        this.ctx.notify.error(error, {title: `Could not open ${definition.title}`});
        return null;
      }
      mount(element, created.element);
      this.host.append(element);
      this.instances.set(key, {key, type, params, definition, element, window: created,
        title: created.title || definition.title, subtitle: created.subtitle || ''});
      this.store.set((state) => ({order: [...state.order, key]}));
    }
    this.activate(key);
    return key;
  }

  activate(key) {
    const previous = this.store.get().active;
    if (previous === key) {
      return;
    }
    if (previous && this.instances.has(previous)) {
      const instance = this.instances.get(previous);
      instance.element.hidden = true;
      if (instance.window.onHide) {
        instance.window.onHide();
      }
    }
    const instance = this.instances.get(key);
    if (instance) {
      instance.element.hidden = false;
      if (instance.window.onShow) {
        instance.window.onShow();
      }
    }
    this.store.set({active: key});
    this.ctx.bus.emit('window-activated', instance);
  }

  async close(key) {
    const instance = this.instances.get(key);
    if (!instance) {
      return;
    }
    if (instance.window.canClose && !(await instance.window.canClose())) {
      return;
    }
    if (instance.window.dispose) {
      instance.window.dispose();
    }
    instance.element.remove();
    this.instances.delete(key);
    const order = this.store.get().order.filter((item) => item !== key);
    let active = this.store.get().active;
    if (active === key) {
      const index = this.store.get().order.indexOf(key);
      active = order[Math.min(index, order.length - 1)] || null;
    }
    this.store.set({order, active: null});
    if (active) {
      this.activate(active);
    } else {
      this.open('start');
    }
  }

  setTitle(key, title, subtitle) {
    const instance = this.instances.get(key);
    if (instance) {
      instance.title = title;
      instance.subtitle = subtitle || '';
      this.renderTabs();
    }
  }

  active() {
    return this.instances.get(this.store.get().active) || null;
  }

  renderTabs() {
    const {order, active} = this.store.get();
    mount(this.tabBar, order.map((key) => {
      const instance = this.instances.get(key);
      return h('div', {
        class: 'tab', role: 'tab', tabindex: '0',
        'aria-selected': String(key === active),
        title: instance.subtitle ? `${instance.title} — ${instance.subtitle}` : instance.title,
        onClick: () => this.activate(key),
        onContextmenu: (event) => {
          if (!instance.params.document || this.ctx.role() === 'user') return;
          event.preventDefault();
          documentMenu(this.ctx, instance.params.document, {x: event.clientX, y: event.clientY});
        },
        onKeydown: (event) => {
          if (event.key === 'Enter') {
            this.activate(key);
          }
        },
        onAuxclick: (event) => {
          if (event.button === 1) {
            this.close(key);
          }
        },
      },
      icon(instance.definition.icon, null),
      h('span', {class: 'label'}, instance.title),
      h('span', {class: 'tab-close', role: 'button', 'aria-label': `Close ${instance.title}`,
        onClick: (event) => {
          event.stopPropagation();
          this.close(key);
        }}, icon('close', null)));
    }));
  }

  persist() {
    const tabs = this.store.get().order.map((key) => {
      const instance = this.instances.get(key);
      return {key, type: instance.type, params: instance.params};
    });
    try {
      localStorage.setItem(this.storageKey, JSON.stringify({tabs, active: this.store.get().active}));
    } catch {
      // Tab restoration is a convenience only.
    }
  }

  restore(validDocuments) {
    let saved = null;
    try {
      saved = JSON.parse(localStorage.getItem(this.storageKey) || 'null');
    } catch {
      saved = null;
    }
    if (!saved || !Array.isArray(saved.tabs)) {
      return false;
    }
    for (const tab of saved.tabs) {
      if (tab.params && tab.params.document && !validDocuments.has(tab.params.document)) {
        continue;
      }
      this.open(tab.type, {...tab.params, key: tab.key});
    }
    if (saved.active && this.instances.has(saved.active)) {
      this.activate(saved.active);
    }
    return this.instances.size > 0;
  }
}
