// Copyright (C) 2026 David L F Gaden
// Start window: what to do next, recent documents and installed adaptors.

import {h, icon, mount} from '../lib/dom.mjs';
import {avatar, identity, windowFor} from '../shell/providers.mjs';
import {documentMenu} from './document-menu.mjs';

/** The Studio applications a developer works in, each with its own documents. */
const APPS = [
  {window: 'designer', icon: 'flow', title: 'Workflow Designer', description: 'Connect adaptors with ports and arrows',
    create: 'New design…', event: 'new-design', provider: 'workflow-design'},
  {window: 'workbench', icon: 'adaptor', title: 'Adaptor Workbench', description: 'Author one application input with its schema',
    create: 'New instance…', event: 'new-instance'},
  {window: 'schema-editor', icon: 'braces', title: 'Schema Editor', description: 'Edit any JSON against adaptor schemas',
    create: 'New scratch…', scratch: true},
];

function action(iconName, title, description, run) {
  return h('button', {class: 'start-action card', onClick: run},
    h('span', {class: 'start-action-icon'}, icon(iconName)),
    h('span', {class: 'start-action-text'},
      h('span', {class: 'title'}, title),
      h('span', {class: 'subtitle'}, description)));
}

function recentItem(ctx, record) {
  return h('li', {class: 'list-item', role: 'button', tabindex: '0', title: record.file || 'Kept in this workspace; not saved to a file yet',
    onClick: () => ctx.openDocument(record.id),
    onKeydown: (event) => {
      if (event.key === 'Enter') ctx.openDocument(record.id);
    }},
  avatar(record.provider), h('div', {class: 'grow'},
    h('div', {class: 'title'}, record.name),
    h('div', {class: 'subtitle'}, `${identity(record.provider).name} · ${record.file || 'not saved to a file yet'}`)),
  record.valid ? null : h('span', {class: 'badge error'}, 'Invalid draft'),
  h('button', {class: 'button ghost small icon-only', 'aria-label': `Actions for ${record.name}`,
    onClick: (event) => {
      event.stopPropagation();
      documentMenu(ctx, record.id, event.currentTarget);
    }}, icon('more')));
}

function appCard(ctx, app, records, count) {
  const recent = records.filter((record) => windowFor(record.provider) === app.window).slice(0, count);
  return h('section', {class: 'start-app card', dataset: {app: app.window}},
    h('div', {class: 'start-app-head'}, h('span', {class: 'start-action-icon'}, icon(app.icon)),
      h('div', {}, h('div', {class: 'title'}, app.title), h('div', {class: 'subtitle'}, app.description))),
    h('div', {class: 'start-app-actions'},
      h('button', {class: 'button primary', dataset: {action: 'new'}, onClick: () => app.scratch
        ? ctx.windows.open('schema-editor', {id: 'scratch'}) : ctx.bus.emit(app.event)}, icon('plus'), app.create),
      h('button', {class: 'button', dataset: {action: 'open-file'}, title: 'Open a saved file from disk',
        onClick: () => ctx.bus.emit('open-file', {provider: app.provider})}, icon('folder'), 'Open…'),
      app.scratch ? null : h('button', {class: 'button ghost', title: `Show every ${app.title} document in this workspace`,
        onClick: () => ctx.windows.open(app.window, {chooser: true, id: 'chooser'})}, 'All…')),
    count ? h('h4', {}, 'Open recent') : null,
    count ? h('ul', {class: 'list'}, recent.length ? recent.map((record) => recentItem(ctx, record))
      : h('li', {class: 'empty-state'}, 'Nothing yet. Create one, or open a saved file.')) : null);
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
    const apps = h('div', {class: 'start-apps'});
    const adaptors = h('div', {class: 'adaptor-grid'});
    const adaptorSection = h('section', {}, h('h3', {class: 'section-title'}, 'New adaptor instance for…'), adaptors);
    const greeting = h('p', {class: 'secondary-text'});

    const render = () => {
      const role = ctx.role();
      const dev = role !== 'user';
      greeting.textContent = dev
        ? 'Design workflows across applications, configure each adaptor, and hand finished templates to users.'
        : 'Choose a workflow template, enter its parameters and run it.';
      mount(actions,
        action('play', 'Run a template', 'Fill in parameters and produce outputs', () => ctx.windows.open('runner')),
        action('folder', 'Results', 'Browse outputs from earlier runs', () => ctx.openResults()),
        action('help', 'Help', 'Guides and adaptor references', () => ctx.openHelp()));
      const server = ctx.store.get().server;
      const records = server ? [...server.documents].sort((a, b) => b.revision - a.revision) : [];
      const count = ctx.setting('files.recentCount') ?? 10;
      apps.hidden = adaptorSection.hidden = !dev;
      mount(apps, dev ? APPS.map((app) => appCard(ctx, app, records, count)) : null);
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
        apps, actions, adaptorSection));
    return {element, dispose: () => unsubscribe.forEach((fn) => fn())};
  },
};
