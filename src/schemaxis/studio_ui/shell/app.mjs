// Copyright (C) 2026 David L F Gaden
// Studio bootstrap: context, layout, polling and global shortcuts.

import {installHierarchyControls} from '../lib/hierarchy.mjs';
import {api} from '../lib/api.mjs';
import {h, icon} from '../lib/dom.mjs';
import {Bus, Store} from '../lib/store.mjs';
import {Notifier} from './notify.mjs';
import {Commands, openPalette} from './palette.mjs';
import {WindowManager} from './windows.mjs';
import {createPanel} from './panel.mjs';
import {openMenu} from './dialog.mjs';
import {windowFor, identity, registerIdentities} from './providers.mjs';
import {registerWindows} from '../windows/index.mjs';
import {applyTheme, setSetting} from './preferences.mjs';
import {openVariables} from '../windows/variables/panel.mjs';

const RAIL = [
  {type: 'start', icon: 'home', label: 'Start'},
  {type: 'designer', icon: 'flow', label: 'Workflow Designer', roles: ['admin', 'dev']},
  {type: 'workbench', icon: 'adaptor', label: 'Adaptor Workbench', roles: ['admin', 'dev']},
  {type: 'runner', icon: 'play', label: 'Case Runner'},
  {type: 'results', icon: 'folder', label: 'Results'},
  {type: 'schedules', icon: 'play', label: 'Schedules'},
  {type: 'schema-editor', icon: 'braces', label: 'Schema Editor', roles: ['admin', 'dev']},
  {type: 'help', icon: 'help', label: 'Help'},
];

function createContext() {
  const bus = new Bus();
  const notify = new Notifier();
  const store = new Store({
    connection: 'connecting',
    server: null,
    settings: null,
    adaptors: [],
    panelOpen: false,
    panelTab: 'problems',
  });
  const ctx = {api, bus, notify, store, commands: new Commands()};
  notify.openProblems = () => store.set({panelOpen: true, panelTab: 'problems'});
  store.watch(state => state.settings, () => {
    notify.suppressed = ctx.setting('notifications.suppress') === true;
    if (notify.suppressed) notify.container.replaceChildren();
  });
  ctx.openVariables = () => ctx.call(() => openVariables(ctx), {title: 'Could not open variables'});

  /** Run an async action; report failures and return undefined on error. */
  ctx.call = async (action, {title, quiet, source} = {}) => {
    try {
      return await action();
    } catch (error) {
      if (!quiet) {
        notify.error(error, {title, source});
      }
      return undefined;
    }
  };

  ctx.role = () => (store.get().settings ? store.get().settings.values.role : 'dev');
  ctx.setting = (key) => (store.get().settings ? store.get().settings.values[key] : undefined);

  ctx.refresh = async () => {
    try {
      const server = await api.get('/api/state');
      const previous = store.get().server;
      store.set({server, connection: 'connected'});
      announceChanges(ctx, previous, server);
      return server;
    } catch (error) {
      if (store.get().connection !== 'offline') {
        store.set({connection: 'offline'});
        notify.error(error, {title: 'Lost connection to the Studio server'});
      }
      return null;
    }
  };

  ctx.openDocument = (documentId) => {
    const server = store.get().server;
    const record = server && server.documents.find((item) => item.id === documentId);
    if (!record) {
      notify.warn('Document not found', {body: 'It may have been closed in another window.'});
      return;
    }
    ctx.windows.open(windowFor(record.provider), {document: documentId});
  };

  ctx.openResults = (detail = {}) => {
    const key = ctx.windows.open('results', detail);
    if(detail.collection)ctx.windows.instances.get(key)?.window.openCollection(detail.collection);
    return key;
  };

  ctx.openHelp = (detail = {}) => {
    const key = ctx.windows.open('help');
    return ctx.windows.instances.get(key)?.window.navigate(detail);
  };

  ctx.adaptor = (id) => store.get().adaptors.find((item) => item.id === id);
  bus.on('reveal-location', (detail) => {
    const active = ctx.windows.active();
    const target = active?.params.document === detail.document ? active
      : [...ctx.windows.instances.values()].find((item) => item.params.document === detail.document);
    if (target) ctx.windows.activate(target.key);
    else ctx.windows.open('schema-editor', {document: detail.document, revealLocation: detail.location});
  });
  return ctx;
}

function announceChanges(ctx, previous, current) {
  if (!previous) {
    return;
  }
  const before = new Map(previous.documents.map((item) => [item.id, item.revision]));
  for (const record of current.documents) {
    if (before.has(record.id) && before.get(record.id) !== record.revision) {
      ctx.bus.emit('document-changed', record);
    }
  }
  if (previous.busy && !current.busy) {
    ctx.bus.emit('jobs-idle', current);
  }
}

function buildTopbar(ctx) {
  const connection = h('span', {class: 'connection', 'data-state': 'connecting'}, 'Connecting');
  const workspace = h('span', {class: 'workspace'});
  const roleButton = h('button', {class: 'button ghost small', 'aria-haspopup': 'menu',
    'data-tooltip': 'Interface role', 'data-tooltip-position': 'below'}, icon('user'), h('span'), icon('chevron-down'));
  roleButton.addEventListener('click', () => {
    const current = ctx.role();
    openMenu(roleButton, ['admin', 'dev', 'user'].map((role) => ({
      label: role === 'admin' ? 'Admin' : role === 'dev' ? 'Developer' : 'User',
      checked: role === current,
      run: () => setSetting(ctx, {role}),
    })));
  });
  const themeButton = h('button', {class: 'button ghost small icon-only', 'aria-label': 'Toggle theme',
    'data-tooltip': 'Toggle theme', 'data-tooltip-position': 'below',
    onClick: () => {
      const dark = document.documentElement.dataset.theme === 'dark';
      setSetting(ctx, {theme: dark ? 'light' : 'dark'});
    }}, icon('moon'));
  const element = h('header', {class: 'topbar'},
    h('div', {class: 'brand'},
      h('span', {class: 'brand-mark', 'aria-hidden': 'true'}, 'S'),
      h('div', {}, h('div', {}, 'Schemaxis Studio'), workspace)),
    h('button', {class: 'topbar-search', onClick: () => showPalette(ctx)},
      icon('search'), 'Search commands, windows and documents', h('kbd', {}, 'Ctrl K')),
    h('div', {class: 'topbar-actions'},
      connection,
      h('button', {class: 'button ghost small', 'aria-label': 'Bottom panel',
        title: 'Show or hide Problems, Jobs, Log and Console (Ctrl+J)',
        onClick: () => ctx.store.set(state => ({panelOpen: !state.panelOpen}))}, icon('panel'), 'Panel'),
      h('button', {class: 'button ghost small', onClick: () => ctx.openVariables()}, 'Variables & expressions'),
      h('button', {class: 'button ghost small', onClick: () => ctx.openHelp()}, 'Help'),
      roleButton,
      themeButton,
      h('button', {class: 'button ghost small icon-only', 'aria-label': 'Settings', 'data-tooltip': 'Settings',
        'data-tooltip-position': 'below', onClick: () => ctx.windows.open('settings')}, icon('gear'))));
  ctx.store.subscribe((state) => {
    connection.dataset.state = state.connection;
    connection.textContent = state.connection === 'connected' ? 'Connected'
      : state.connection === 'offline' ? 'Offline' : 'Connecting';
    if (state.server) {
      const path = state.server.workspace || '';
      workspace.textContent = path.split('/').slice(-2).join('/');
      workspace.title = path;
    }
    const role = ctx.role();
    roleButton.children[1].textContent = role === 'admin' ? 'Admin' : role === 'dev' ? 'Developer' : 'User';
    themeButton.firstChild.replaceWith(icon(document.documentElement.dataset.theme === 'dark' ? 'sun' : 'moon'));
  });
  return element;
}

function buildRail(ctx) {
  const element = h('nav', {class: 'rail', 'aria-label': 'Windows'});
  const render = () => {
    const role = ctx.role();
    const active = ctx.windows.active();
    element.replaceChildren(...RAIL.filter((item) => !item.roles || item.roles.includes(role)).map((item) => h('button', {
      class: 'rail-button', 'aria-label': item.label, 'data-tooltip': item.label,
      'aria-current': active && active.type === item.type ? 'page' : undefined,
      onClick: () => openFromRail(ctx, item.type),
    }, icon(item.icon))), h('div', {class: 'rail-spacer'}), h('button', {
      class: 'rail-button', 'aria-label': 'Toggle bottom panel', 'data-tooltip': 'Problems, jobs and log',
      onClick: () => ctx.store.set((state) => ({panelOpen: !state.panelOpen})),
    }, icon('panel')));
  };
  ctx.windows.store.subscribe(render);
  ctx.store.watch((state) => state.settings, render);
  render();
  return element;
}

function openFromRail(ctx, type) {
  const existing = [...ctx.windows.instances.values()].find((instance) => instance.type === type);
  if (existing) {
    ctx.windows.activate(existing.key);
  } else {
    ctx.windows.open(type, type === 'designer' || type === 'workbench' ? {chooser: true, id: 'chooser'} : {});
  }
}

function buildStatusbar(ctx) {
  const problems = h('button', {onClick: () => ctx.store.set({panelOpen: true, panelTab: 'problems'})});
  const jobs = h('button', {onClick: () => ctx.store.set({panelOpen: true, panelTab: 'jobs'})});
  const documentInfo = h('span');
  const render = () => {
    const count = ctx.notify.store.get().problems.length;
    problems.replaceChildren(icon(count ? 'error' : 'check', null), `${count} problem${count === 1 ? '' : 's'}`);
    const server = ctx.store.get().server;
    const running = server ? server.jobs.filter((job) => job.status === 'running').length : 0;
    jobs.replaceChildren(icon(running ? 'spinner' : 'play', null), running ? `${running} running` : 'No jobs');
    if (running) {
      jobs.firstChild.classList.add('spin');
    }
    const active = ctx.windows.active();
    const record = active && active.params.document && server
      ? server.documents.find((item) => item.id === active.params.document) : null;
    documentInfo.textContent = record ? `${identity(record.provider).name} · ${record.version || ''} · revision ${record.revision}` : '';
  };
  ctx.notify.store.subscribe(render);
  ctx.store.subscribe(render);
  ctx.windows.store.subscribe(render);
  render();
  return h('footer', {class: 'statusbar'}, problems, jobs, h('span', {class: 'push'}), documentInfo);
}

function showPalette(ctx) {
  const server = ctx.store.get().server;
  const documents = (server ? server.documents : []).map((record) => ({
    title: record.name,
    group: `Open document · ${identity(record.provider).name}`,
    icon: windowFor(record.provider) === 'designer' ? 'flow' : 'file',
    run: () => ctx.openDocument(record.id),
  }));
  openPalette({commands: ctx.commands, role: ctx.role(), extraItems: documents});
}

function registerCommands(ctx) {
  const c = ctx.commands;
  c.register({id: 'variables.open', title: 'Variables & expressions', group: 'Authoring', icon: 'braces',
    run: () => ctx.openVariables()});
  c.register({id: 'window.help', title: 'Open Help', group: 'Help', icon: 'help', shortcut: 'F1',
    run: () => ctx.openHelp()});
  c.register({id: 'window.start', title: 'Go to Start', group: 'Window', icon: 'home', run: () => ctx.windows.open('start')});
  c.register({id: 'window.settings', title: 'Open Settings', group: 'Window', icon: 'gear',
    run: () => ctx.windows.open('settings')});
  c.register({id: 'design.new', title: 'New workflow design', group: 'Workflow Designer', icon: 'flow',
    roles: ['admin', 'dev'], run: () => ctx.bus.emit('new-design')});
  c.register({id: 'adaptor.new', title: 'New adaptor instance…', group: 'Adaptor Workbench', icon: 'adaptor',
    roles: ['admin', 'dev'], run: () => ctx.bus.emit('new-instance')});
  c.register({id: 'file.open', title: 'Open input file…', group: 'File', icon: 'folder',
    roles: ['admin', 'dev'], run: () => ctx.bus.emit('open-file')});
  c.register({id: 'schema.open', title: 'Open Schema Editor', group: 'Schema Editor', icon: 'braces',
    roles: ['admin', 'dev'], run: () => ctx.windows.open('schema-editor', {id: 'scratch'})});
  c.register({id: 'runner.open', title: 'Open Case Runner', group: 'Case Runner', icon: 'play',
    run: () => ctx.windows.open('runner')});
  c.register({id: 'schedules.open', title: 'Open Schedules', group: 'Schedules', icon: 'play',
    run: () => ctx.windows.open('schedules')});
  c.register({id: 'setup.open', title: 'Open Application Setup', group: 'Settings', icon: 'gear',
    roles: ['admin'], run: () => ctx.windows.open('setup')});
  c.register({id: 'panel.toggle', title: 'Toggle bottom panel', group: 'View', icon: 'panel', shortcut: 'Ctrl J',
    run: () => ctx.store.set((state) => ({panelOpen: !state.panelOpen}))});
  c.register({id: 'theme.toggle', title: 'Toggle light / dark theme', group: 'View', icon: 'moon',
    run: () => setSetting(ctx, {theme: document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'})});
  for (const role of ['admin', 'dev', 'user']) {
    c.register({id: `role.${role}`, title: `Switch role to ${role}`, group: 'Role', icon: 'user',
      run: () => setSetting(ctx, {role})});
  }
}

function installShortcuts(ctx) {
  window.addEventListener('beforeunload', (event) => {
    if ([...ctx.windows.instances.values()].some((instance) => instance.window.isDirty?.())) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'F1') {
      event.preventDefault();
      const active = ctx.windows.active();
      const record = ctx.store.get().server?.documents.find((item) => item.id === active?.params.document);
      ctx.openHelp({provider: record?.provider});
      return;
    }
    const modifier = event.ctrlKey || event.metaKey;
    if (modifier && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      showPalette(ctx);
    } else if (modifier && event.key.toLowerCase() === 'j') {
      event.preventDefault();
      ctx.store.set((state) => ({panelOpen: !state.panelOpen}));
    }
  });
}

async function start() {
  const ctx = createContext();
  const tabBar = h('div', {class: 'tabs', role: 'tablist', 'aria-label': 'Open windows'});
  const host = h('div', {class: 'window-host'});
  ctx.windows = new WindowManager(ctx, host, tabBar);
  registerWindows(ctx);
  registerCommands(ctx);

  const settings = await ctx.call(() => api.post('/api/settings', {action: 'read'}), {title: 'Settings unavailable'});
  ctx.store.set({settings: settings || null});
  applyTheme(settings ? settings.values.theme : 'system');
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => applyTheme(ctx.setting('theme') || 'system'));

  const layout = h('div', {class: 'studio'},
    buildTopbar(ctx),
    buildRail(ctx),
    h('main', {class: 'main'}, h('div', {class: 'tab-row'}, tabBar), host),
    createPanel(ctx),
    buildStatusbar(ctx));
  document.body.replaceChildren(layout, ctx.notify.container);
  installShortcuts(ctx);
  installHierarchyControls(document.body);

  const server = await ctx.refresh();
  const adaptors = await ctx.call(() => api.get('/api/adaptors'), {title: 'Adaptor list unavailable'});
  registerIdentities(adaptors ? adaptors.adaptors : []);
  ctx.store.set({adaptors: adaptors ? adaptors.adaptors : []});
  const valid = new Set(server ? server.documents.map((item) => item.id) : []);
  if (!ctx.windows.restore(valid)) {
    ctx.windows.open('start');
  }
  setInterval(() => {
    if (!document.hidden) {
      ctx.refresh();
    }
  }, 2000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      ctx.refresh();
    }
  });
  window.studio = ctx;
}

start();
