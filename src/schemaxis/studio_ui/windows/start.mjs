// Copyright (C) 2026 David L F Gaden
// Start window: what to do next, recent documents and installed adaptors.

import {h, icon, mount} from '../lib/dom.mjs';
import {avatar, identity, windowFor} from '../shell/providers.mjs';
import {documentMenu} from './document-menu.mjs';

function action(iconName, title, description, run) {
  return h('button', {class: 'start-action card', onClick: run},
    h('span', {class: 'start-action-icon'}, icon(iconName)),
    h('span', {class: 'start-action-text'},
      h('span', {class: 'title'}, title),
      h('span', {class: 'subtitle'}, description)));
}

function adaptorCard(ctx, adaptor) {
  const info = identity(adaptor.id);
  return h('button', {class: 'adaptor-card card', title: adaptor.scope, disabled: ctx.role() === 'user',
    onClick: () => ctx.bus.emit('new-instance', {provider: adaptor.id})},
  avatar(adaptor.id, {large: true}),
  h('span', {class: 'adaptor-card-text'},
    h('span', {class: 'title'}, info.name),
    h('span', {class: 'subtitle'}, `${adaptor.operations.length} operations · ${adaptor.runtimeFamily || ''}`)));
}

export const startWindow = {
  type: 'start',
  title: 'Start',
  icon: 'home',
  singleton: true,
  create(ctx) {
    const actions = h('div', {class: 'start-actions'});
    const recent = h('ul', {class: 'list'});
    const adaptors = h('div', {class: 'adaptor-grid'});
    const greeting = h('p', {class: 'secondary-text'});

    const render = () => {
      const role = ctx.role();
      const dev = role !== 'user';
      greeting.textContent = dev
        ? 'Design workflows across applications, configure each adaptor, and hand finished templates to users.'
        : 'Choose a workflow template, enter its parameters and run it.';
      mount(actions,
        dev ? action('flow', 'New workflow design', 'Connect adaptors with ports and arrows',
          () => ctx.bus.emit('new-design')) : null,
        dev ? action('adaptor', 'New adaptor instance', 'Author one application input with its schema',
          () => ctx.bus.emit('new-instance')) : null,
        action('play', 'Run a template', 'Fill in parameters and produce outputs', () => ctx.windows.open('runner')),
        dev ? action('braces', 'Schema Editor', 'Edit any JSON against adaptor schemas',
          () => ctx.windows.open('schema-editor', {id: 'scratch'})) : null);
      const server = ctx.store.get().server;
      const records = server ? [...server.documents].sort((a, b) => b.revision - a.revision).slice(0, 12) : [];
      mount(recent, records.length ? records.map((record) => h('li', {
        class: 'list-item', role: 'button', tabindex: '0',
        onClick: () => ctx.openDocument(record.id),
        onKeydown: (event) => {
          if (event.key === 'Enter') {
            ctx.openDocument(record.id);
          }
        },
      }, avatar(record.provider), h('div', {class: 'grow'},
        h('div', {class: 'title'}, record.name),
        h('div', {class: 'subtitle'}, `${identity(record.provider).name} · ${windowFor(record.provider) === 'designer'
          ? 'Workflow Designer' : windowFor(record.provider) === 'workbench' ? 'Adaptor Workbench' : 'Schema Editor'}`
          + ` · revision ${record.revision}`)),
      record.valid ? null : h('span', {class: 'badge error'}, 'Invalid draft'),
      dev ? h('button', {class: 'button ghost small icon-only', 'aria-label': `Actions for ${record.name}`,
        onClick: (event) => {
          event.stopPropagation();
          documentMenu(ctx, record.id, event.currentTarget);
        }}, icon('more')) : null,
      icon('chevron-right'))) : h('li', {class: 'empty-state'}, 'No documents yet. Create one above.'));
      mount(adaptors, ctx.store.get().adaptors.filter((item) => !item.hostOnly).map((item) => adaptorCard(ctx, item)));
    };
    const unsubscribe = [
      ctx.store.watch((state) => state.server && state.server.documents, render),
      ctx.store.watch((state) => state.adaptors, render),
      ctx.store.watch((state) => state.settings, render),
    ];
    render();
    const element = h('div', {class: 'window-body start'},
      h('div', {class: 'start-inner'},
        h('div', {class: 'start-hero'}, h('h1', {}, 'Schemaxis Studio'), greeting),
        actions,
        h('div', {class: 'start-columns'},
          h('section', {},
            h('h3', {class: 'section-title'}, 'Recent documents'),
            h('div', {class: 'card'}, recent)),
          h('section', {},
            h('h3', {class: 'section-title'}, 'Adaptors'),
            adaptors))));
    return {element, dispose: () => unsubscribe.forEach((fn) => fn())};
  },
};
