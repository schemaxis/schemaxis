// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// Artifact Explorer: a local file browser and data viewer. This module owns
// application state, the top bar, the context bar, selection, keyboard input,
// theme and loading; the views, sidebar, inspector and viewers render from it.

import {h, icon, iconButton, toggleButton, textButton, chip, clear, fill} from './dom.mjs';
import {Collection, inFolder, matchesFilters, matchesSearch, facets, groupItems, propertyKeys, metadataProblem, METADATA_VERIFIED} from './collection.mjs';
import {formatValue} from './names.mjs';
import * as host from './host.mjs';
import {FilesView, GroupsView} from './browse.mjs';
import {PlayerView} from './player.mjs';
import {SpaceView} from './space.mjs';
import {FileViewer} from './viewer.mjs';
import {Sidebar} from './sidebar.mjs';
import {Inspector} from './inspector.mjs';
import {folderDialog, patternsDialog, confirmDialog} from './dialogs.mjs';

const PREFERENCES = 'artifact.explorer.preferences';
const RULES = 'artifact.explorer.rules';
const THEME = 'artifact.theme';
const VIEWS = [
  {id: 'files', label: 'Files', icon: 'files', key: '1'},
  {id: 'groups', label: 'Groups', icon: 'groups', key: '2'},
  {id: 'player', label: 'Player', icon: 'player', key: '3'},
  {id: 'space', label: '3D', icon: 'cube', key: '4'}
];
const VIEW_CLASSES = {files: FilesView, groups: GroupsView, player: PlayerView, space: SpaceView};

function readStorage(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value === null ? fallback : JSON.parse(value);
  } catch {
    return fallback;
  }
}

function writeStorage(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    return;
  }
}

function typing(event) {
  const target = event.target;
  return target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
}

class Explorer {
  constructor() {
    const saved = readStorage(PREFERENCES, {});
    this.state = {
      view: 'files', folder: '', recursive: !!saved.recursive, query: '', filters: new Map(),
      groupBy: ['@sequence'], orderBy: 'auto', layout: saved.layout === 'list' ? 'list' : 'grid',
      thumb: Number.isFinite(saved.thumb) ? saved.thumb : 180, stack: saved.stack !== false,
      sidebar: saved.sidebar !== false, inspector: saved.inspector !== false, sidebarTab: saved.sidebarTab || 'folders'
    };
    this.selection = new Set();
    this.focus = null;
    this.anchor = null;
    this.collection = null;
    this.records = [];
    this.sources = [];
    this.label = '';
    this.loads = 0;
    this.generation = 0;
    this.metaCache = new Map();
    this.metaPending = 0;
    this.rules = readStorage(RULES, []);
    this.recent = [];
    this.hostAvailable = false;
    this.adhoc = new Map();
    this.playerState = {panes: [], linked: true, mode: 'loop', fps: 4, index: 0};
    this.spaceState = {stacks: new Map(), meshes: new Map(), camera: null};
    this.derived = null;
    this.dom = {app: document.getElementById('app'), topbar: document.getElementById('topbar'),
      contextbar: document.getElementById('contextbar'), main: document.getElementById('main'),
      viewer: document.getElementById('viewer'), statusbar: document.getElementById('statusbar'),
      fileInput: document.getElementById('file-input')};
    this.view = null;
    this.viewer = null;
    this.sidebar = new Sidebar(this, document.getElementById('sidebar'));
    this.inspector = new Inspector(this, document.getElementById('inspector'));
    this.renderQueued = false;
    window.artifactExplorer = this;
  }

  async start() {
    this.installTheme();
    this.installEvents();
    this.applyLayoutClasses();
    this.dom.app.style.setProperty('--thumb', this.state.thumb + 'px');
    this.renderTopbar();
    try {
      await this.refreshRecent();
      this.hostAvailable = true;
    } catch {
      this.hostAvailable = false;
    }
    let initial = null;
    try {
      initial = await host.initialCollection();
    } catch (error) {
      this.toast(error.message, true);
    }
    if (initial) this.load(initial, {replace: true});
    else this.render();
    host.notifyParent({type: 'artifact-ready'});
  }

  savePreferences() {
    const {recursive, layout, thumb, stack, sidebar, inspector, sidebarTab} = this.state;
    writeStorage(PREFERENCES, {recursive, layout, thumb, stack, sidebar, inspector, sidebarTab});
  }

  installTheme() {
    const system = matchMedia('(prefers-color-scheme: dark)');
    let choice = readStorage(THEME, null) || 'system';
    if (host.embedded && ['light', 'dark', 'system'].includes(host.suppliedTheme)) choice = host.suppliedTheme;
    this.themeChoice = choice;
    system.addEventListener('change', () => this.applyTheme(this.themeChoice));
    window.addEventListener('message', event => {
      if (event.source !== window.parent || event.origin !== location.origin) return;
      if (event.data?.type === 'artifact-theme') this.applyTheme(event.data.theme);
    });
    this.applyTheme(choice);
  }

  applyTheme(choice) {
    this.themeChoice = ['light', 'dark', 'system'].includes(choice) ? choice : 'system';
    const dark = this.themeChoice === 'dark' || (this.themeChoice === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    if (this.themeButton) {
      this.themeButton.replaceChildren(icon(dark ? 'sun' : 'moon'));
      this.themeButton.title = `Switch to ${dark ? 'light' : 'dark'} mode`;
    }
    document.dispatchEvent(new Event('artifact-themechange'));
  }

  toggleTheme() {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    writeStorage(THEME, next);
    this.applyTheme(next);
    host.notifyParent({type: 'artifact-theme-preference', theme: next});
    if (this.hostAvailable && !host.embedded) host.api('preferences', {theme: next}).catch(() => {});
  }

  installEvents() {
    document.addEventListener('keydown', event => this.onKey(event));
    this.dom.fileInput.addEventListener('change', () => {
      const files = [...this.dom.fileInput.files];
      this.dom.fileInput.value = '';
      if (files.length) this.load(host.browserRecords(files.map(file => ({file, path: file.name}))), {replace: !this.collection});
    });
    let depth = 0, overlay = null;
    document.addEventListener('dragenter', event => {
      if (![...event.dataTransfer.types].includes('Files')) return;
      depth++;
      if (!overlay) {
        overlay = h('div', {class: 'drop-overlay'}, 'Drop files or folders to view them');
        document.body.append(overlay);
      }
    });
    document.addEventListener('dragleave', () => {
      depth = Math.max(0, depth - 1);
      if (!depth && overlay) {
        overlay.remove();
        overlay = null;
      }
    });
    document.addEventListener('dragover', event => event.preventDefault());
    document.addEventListener('drop', async event => {
      event.preventDefault();
      depth = 0;
      overlay?.remove();
      overlay = null;
      try {
        const entries = await host.droppedEntries(event.dataTransfer);
        if (entries.length) this.load(host.browserRecords(entries, 'Dropped files'), {replace: !this.collection});
      } catch (error) {
        this.toast(error.message, true);
      }
    });
    window.addEventListener('resize', () => this.view?.resize?.());
  }

  onKey(event) {
    if (document.querySelector('.dialog-backdrop')) return;
    if (this.viewer) {
      this.viewer.onKey(event);
      return;
    }
    const meta = event.ctrlKey || event.metaKey;
    if (meta && event.key.toLowerCase() === 'f' && !this.view?.ownsFind) {
      event.preventDefault();
      this.searchInput?.focus();
      this.searchInput?.select();
      return;
    }
    if (typing(event)) {
      if (event.key === 'Escape') event.target.blur();
      return;
    }
    if (this.view?.onKey?.(event)) return;
    if (meta && event.key.toLowerCase() === 'a') {
      event.preventDefault();
      this.setSelection(this.view?.orderedIds?.() || [], true);
      return;
    }
    if (event.key === 'Escape') {
      this.clearSelection();
      return;
    }
    if (event.key === '/') {
      event.preventDefault();
      this.searchInput?.focus();
      return;
    }
    if (!meta && !event.altKey) {
      const view = VIEWS.find(entry => entry.key === event.key);
      if (view) this.setView(view.id);
    }
  }

  applyLayoutClasses() {
    this.dom.app.classList.toggle('no-sidebar', !this.state.sidebar);
    this.dom.app.classList.toggle('no-inspector', !this.state.inspector);
  }

  set(patch, {persist = false} = {}) {
    Object.assign(this.state, patch);
    if (persist) this.savePreferences();
    this.render();
  }

  render() {
    if (this.renderQueued) return;
    this.renderQueued = true;
    queueMicrotask(() => {
      this.renderQueued = false;
      this.renderNow();
    });
  }

  renderNow() {
    this.derived = this.derive();
    this.renderTopbar();
    this.renderContextbar();
    this.sidebar.render();
    this.renderMain();
    this.inspector.render();
    this.renderStatus();
  }

  derive() {
    if (!this.collection) return {all: [], scope: [], visible: [], facets: [], groups: [], keys: []};
    const all = this.collection.items;
    const {folder, recursive, query, filters} = this.state;
    const scope = all.filter(item => inFolder(item, folder, true) && matchesSearch(item, query));
    const visible = scope.filter(item => matchesFilters(item, filters));
    const groups = groupItems(visible, this.state.groupBy, this.state.orderBy);
    const level = recursive ? visible : visible.filter(item => item.folder === folder);
    return {all, scope, visible, level, facets: facets(scope, filters), groups, keys: propertyKeys(visible)};
  }

  sequences() {
    const groups = this.derived?.groups || [];
    return [...this.adhoc.values(), ...groups.filter(group => group.items.length > 1)];
  }

  findSequence(id) {
    return this.sequences().find(group => group.id === id) || null;
  }

  buildTopbar() {
    this.searchInput = h('input', {type: 'search', placeholder: 'Search names and properties', 'aria-label': 'Search',
      onInput: event => this.set({query: event.target.value})});
    this.themeButton = iconButton('moon', 'Toggle theme', () => this.toggleTheme(), {dataset: {role: 'theme'}});
    this.sidebarToggle = toggleButton('menu', 'Show or hide the sidebar', this.state.sidebar, () => {
      this.state.sidebar = !this.state.sidebar;
      this.applyLayoutClasses();
      this.savePreferences();
      this.renderTopbar();
      this.view?.resize?.();
    });
    this.inspectorToggle = toggleButton('info', 'Show or hide details', this.state.inspector, () => {
      this.state.inspector = !this.state.inspector;
      this.applyLayoutClasses();
      this.savePreferences();
      this.renderTopbar();
      this.view?.resize?.();
    });
    this.labelNode = h('span', {class: 'collection-name'});
    this.viewButtons = new Map(VIEWS.map(view => [view.id, h('button', {type: 'button', title: `${view.label} (${view.key})`,
      onClick: () => this.setView(view.id)}, icon(view.icon), h('span', {class: 'label'}, view.label), h('span', {class: 'count'}))]));
    fill(this.dom.topbar, ...[
      this.sidebarToggle,
      h('div', {class: 'brand'}, h('span', {class: 'brand-mark'}, '◈'), 'Artifact'),
      this.labelNode,
      h('button', {class: 'button', type: 'button', onClick: event => this.openMenu(event.currentTarget)},
        icon('folderOpen'), 'Open', icon('chevronDown', 14)),
      h('div', {class: 'spacer'}),
      h('nav', {class: 'views', 'aria-label': 'View'}, [...this.viewButtons.values()]),
      h('div', {class: 'spacer'}),
      h('label', {class: 'search-box'}, icon('search'), this.searchInput),
      this.inspectorToggle,
      this.themeButton,
      host.embedded ? iconButton('expand', 'Expand to the full Studio window', () => {
        this.expanded = !this.expanded;
        host.notifyParent({type: 'artifact-expand', expanded: this.expanded});
      }, {dataset: {role: 'expand'}}) : null,
      host.embedded ? iconButton('close', 'Close viewer', async () => {
        if (await confirmDialog('Close the viewer?', 'The files stay where they are on disk.', 'Close')) host.notifyParent({type: 'artifact-close'});
      }, {dataset: {role: 'close'}}) : null
    ].filter(Boolean));
    this.applyTheme(this.themeChoice);
  }

  renderTopbar() {
    if (!this.viewButtons) this.buildTopbar();
    const d = this.derived;
    const counts = {files: d?.visible.length, groups: d?.groups.filter(group => group.id !== '@other').length,
      player: null, space: d ? d.visible.filter(item => item.spatial || item.kind === 'mesh').length : null};
    for (const [id, button] of this.viewButtons) {
      button.setAttribute('aria-pressed', String(this.state.view === id && !this.viewer));
      button.disabled = !this.collection;
      button.querySelector('.count').textContent = this.collection && Number.isFinite(counts[id]) ? counts[id] : '';
    }
    this.labelNode.textContent = this.label;
    this.labelNode.title = this.label;
    this.sidebarToggle.setAttribute('aria-pressed', String(this.state.sidebar));
    this.inspectorToggle.setAttribute('aria-pressed', String(this.state.inspector));
    if (this.searchInput.value !== this.state.query) this.searchInput.value = this.state.query;
  }

  openMenu(anchor) {
    const rect = anchor.getBoundingClientRect();
    const close = () => {
      menu.remove();
      document.removeEventListener('pointerdown', outside, true);
    };
    const outside = event => {
      if (!menu.contains(event.target)) close();
    };
    const entry = (iconName, label, hint, action, disabled = false) => h('button', {type: 'button', disabled,
      onClick: () => { close(); action(); }}, icon(iconName), label, hint ? h('span', {class: 'hint'}, hint) : null);
    const menu = h('div', {class: 'menu', role: 'menu', style: {left: rect.left + 'px', top: rect.bottom + 4 + 'px'}},
      entry('folderOpen', 'Open folder…', 'replaces', () => this.chooseFolder(true), !this.hostAvailable),
      entry('plus', 'Add folder…', 'appends', () => this.chooseFolder(false), !this.hostAvailable),
      entry('files', 'Add files…', 'appends', () => this.dom.fileInput.click()),
      h('hr'),
      entry('pattern', 'Filename patterns…', '', () => this.editPatterns(), !this.collection),
      entry('close', 'Close collection', '', () => this.closeCollection(), !this.collection));
    document.body.append(menu);
    setTimeout(() => document.addEventListener('pointerdown', outside, true));
  }

  async chooseFolder(replace) {
    const result = await folderDialog(this, {replace, recursive: this.state.recursive});
    if (!result) return;
    try {
      this.busy = 'Reading folder…';
      this.renderStatus();
      const opened = await host.openPaths(result.paths);
      this.state.recursive = result.recursive;
      this.savePreferences();
      this.load(opened, {replace});
      await this.refreshRecent();
    } catch (error) {
      this.toast(error.message, true);
    } finally {
      this.busy = '';
      this.renderStatus();
    }
  }

  async refreshRecent() {
    const listing = await host.library();
    this.recent = listing.recent || [];
    this.sidebar.render();
    if (!this.collection) this.renderMain();
  }

  async reopen(row) {
    try {
      this.busy = 'Opening…';
      this.renderStatus();
      this.load(await host.reopen(row), {replace: true});
      await this.refreshRecent();
    } catch (error) {
      this.toast(error.message, true);
    } finally {
      this.busy = '';
      this.renderStatus();
    }
  }

  closeCollection() {
    this.generation++;
    this.collection = null;
    this.records = [];
    this.sources = [];
    this.label = '';
    this.resetBrowsing();
    this.render();
  }

  resetBrowsing() {
    this.selection.clear();
    this.focus = null;
    this.anchor = null;
    this.adhoc.clear();
    this.playerState.panes = [];
    this.playerState.index = 0;
    this.spaceState = {stacks: new Map(), meshes: new Map(), camera: null};
    this.state.filters = new Map();
    this.state.query = '';
    this.state.folder = '';
    this.closeViewer();
  }

  load({records, sources = [], label}, {replace}) {
    this.loads++;
    const tagged = records.map(record => ({...record, root: `${record.root || 'selected-files'}~${this.loads}`}));
    const taggedSources = sources.map(source => ({...source, root: `${source.root}~${this.loads}`}));
    if (replace) {
      this.generation++;
      this.metaCache.clear();
      this.records = tagged;
      this.sources = taggedSources;
      this.label = label || '';
      this.resetBrowsing();
    } else {
      this.records = [...this.records, ...tagged];
      this.sources = [...this.sources, ...taggedSources];
      this.label = [this.label, label].filter(Boolean).join(' + ');
    }
    this.collection = new Collection(this.records, this.sources);
    this.collection.setRules(this.rules);
    for (const item of this.collection.items) {
      const cached = this.metaCache.get(item.companion?.url);
      if (cached) this.collection.setMetadata(item, cached.metadata, cached.status);
    }
    const roots = this.collection.folders.roots;
    if (replace) {
      this.state.folder = roots.length === 1 ? roots[0].key : '';
      this.state.view = this.preferredView();
    }
    this.render();
    this.loadMetadata(this.generation);
  }

  preferredView() {
    const items = this.collection.items;
    if (!items.length) return 'files';
    const folders = new Set(items.map(item => item.folder));
    return folders.size === 1 && items.some(item => item.family) ? 'groups' : 'files';
  }

  async loadMetadata(generation) {
    const queue = this.collection.items.filter(item => item.companion && !this.metaCache.has(item.companion.url));
    this.metaPending = queue.length;
    this.renderStatus();
    let changed = 0;
    const worker = async () => {
      while (queue.length && generation === this.generation) {
        const item = queue.shift();
        try {
          const metadata = await host.readCompanion(item.companion);
          if (metadata) {
            const status = await this.verifyMetadata(item, metadata);
            if (generation !== this.generation) return;
            this.metaCache.set(item.companion.url, {metadata, status});
            this.collection.setMetadata(item, metadata, status);
            changed++;
          }
        } catch {
          changed += 0;
        }
        this.metaPending--;
        if (changed >= 40) {
          changed = 0;
          this.render();
        }
      }
    };
    await Promise.all(Array.from({length: 6}, worker));
    if (generation !== this.generation) return;
    this.metaPending = 0;
    this.render();
  }

  async verifyMetadata(item, metadata) {
    const problem = metadataProblem(item, metadata);
    if (problem) return problem;
    try {
      const actual = await host.sha256(item);
      return actual === metadata.artifact.sha256.toLowerCase() ? METADATA_VERIFIED : 'SHA-256 does not match the file; not applied';
    } catch (error) {
      return `could not be verified (${error.message}); not applied`;
    }
  }

  setRules(rules) {
    this.rules = rules;
    writeStorage(RULES, rules);
    this.collection?.setRules(rules);
    for (const key of [...this.state.filters.keys()]) {
      if (this.collection && !this.collection.items.some(item => Object.hasOwn(item.props, key))) this.state.filters.delete(key);
    }
    this.render();
  }

  async editPatterns() {
    await patternsDialog(this);
  }

  setView(view) {
    if (this.state.view === view && !this.viewer) return;
    this.closeViewer();
    this.state.view = view;
    this.render();
  }

  setFolder(folder) {
    this.state.folder = folder;
    this.closeViewer();
    if (this.state.view !== 'files' && this.state.view !== 'groups') this.state.view = 'files';
    this.render();
  }

  toggleFilter(key, token) {
    const filters = this.state.filters;
    const tokens = new Set(filters.get(key) || []);
    if (tokens.has(token)) tokens.delete(token);
    else tokens.add(token);
    if (tokens.size) filters.set(key, tokens);
    else filters.delete(key);
    this.render();
  }

  clearFilters(key = null) {
    if (key) this.state.filters.delete(key);
    else this.state.filters = new Map();
    this.render();
  }

  renderContextbar() {
    const bar = clear(this.dom.contextbar);
    if (!this.collection || this.viewer) return;
    const parts = this.view?.contextControls?.() || [];
    bar.append(...parts.filter(Boolean));
    const filterChips = [...this.state.filters].flatMap(([key, tokens]) => [...tokens].map(token =>
      h('button', {class: 'chip', type: 'button', title: 'Remove this filter', onClick: () => this.toggleFilter(key, token)},
        h('span', {class: 'chip-key'}, key), h('span', {class: 'chip-value'}, formatValue(JSON.parse(token))), icon('close', 12))));
    if (filterChips.length) {
      bar.append(h('div', {class: 'divider'}), h('div', {class: 'filter-chips'}, icon('filter', 14), filterChips,
        textButton('Clear', () => this.clearFilters(), {class: 'button small'})));
    }
    if (this.selection.size) {
      bar.append(h('div', {class: 'spacer'}), h('div', {class: 'selection-bar'},
        `${this.selection.size} selected`,
        textButton('Play', () => this.playSelection(), {class: 'button small', title: 'Play the selected files as a sequence'}),
        this.selectionSpatial() ? textButton('3D', () => this.showSelectionIn3D(), {class: 'button small'}) : null,
        iconButton('close', 'Clear selection (Esc)', () => this.clearSelection(), {class: 'icon-button small'})));
    }
  }

  selectionSpatial() {
    for (const id of this.selection) {
      const item = this.collection.byId.get(id);
      if (item?.spatial || item?.kind === 'mesh') return true;
    }
    return false;
  }

  selectedItems() {
    return [...this.selection].map(id => this.collection.byId.get(id)).filter(Boolean);
  }

  playSelection() {
    const items = this.selectedItems().filter(item => ['image', 'video'].includes(item.kind));
    if (!items.length) {
      this.toast('Select images to play them as a sequence', true);
      return;
    }
    const ordered = groupItems(items, [], 'auto')[0];
    this.adhoc.set('@selection', {...ordered, id: '@selection', label: `Selection (${items.length})`, chips: [], sequence: true});
    this.playerState.panes = [{groupId: '@selection', index: 0}];
    this.setView('player');
  }

  showSelectionIn3D() {
    this.spaceState.only = new Set(this.selection);
    this.setView('space');
  }

  playGroup(group) {
    if (!this.findSequence(group.id)) this.adhoc.set(group.id, group);
    this.playerState.panes = [{groupId: group.id, index: 0}];
    this.playerState.index = 0;
    this.setView('player');
  }

  renderMain() {
    const main = this.dom.main;
    if (!this.collection) {
      this.view?.dispose?.();
      this.view = null;
      main.className = 'main';
      fill(main, this.welcome());
      return;
    }
    const ViewClass = VIEW_CLASSES[this.state.view];
    if (!(this.view instanceof ViewClass)) {
      this.view?.dispose?.();
      clear(main);
      main.className = 'main';
      this.view = new ViewClass(this, main);
    }
    this.view.render();
    this.renderContextbar();
  }

  welcome() {
    const recent = this.recent.slice(0, 8);
    return h('div', {class: 'welcome'},
      h('h1', {}, 'Explore your results'),
      h('p', {}, 'Open a folder to browse its files, group them into sequences by their properties, play them back or place them in 3D. Files are read in place; nothing is copied or uploaded.'),
      h('div', {class: 'actions'},
        textButton('Open folder…', () => this.chooseFolder(true), {class: 'button primary', disabled: !this.hostAvailable}),
        textButton('Add files…', () => this.dom.fileInput.click())),
      h('div', {class: 'dropzone'}, 'or drop files and folders anywhere in this window'),
      recent.length ? h('h2', {}, 'Recent') : null,
      recent.map(row => h('button', {class: 'recent-row', type: 'button', title: (row.paths || []).join('\n'),
        onClick: () => this.reopen(row)}, h('strong', {}, row.label),
        h('span', {}, `${row.kind === 'run' ? 'Schemaxis run · ' : ''}${row.count ?? 0} files · ${row.viewed ? new Date(row.viewed).toLocaleString() : ''}`))));
  }

  renderStatus() {
    const bar = clear(this.dom.statusbar);
    const d = this.derived;
    if (this.collection && d) {
      bar.append(h('span', {}, `${this.collection.items.length} files`));
      if (d.visible.length !== this.collection.items.length) bar.append(h('span', {}, `${d.visible.length} match`));
      const sequences = d.groups.filter(group => group.sequence).length;
      if (sequences) bar.append(h('span', {}, `${sequences} sequences`));
      if (this.selection.size) bar.append(h('span', {}, `${this.selection.size} selected`));
    }
    if (this.metaPending > 0) bar.append(h('span', {class: 'busy'}, `Reading metadata… ${this.metaPending} left`));
    if (this.busy) bar.append(h('span', {class: 'busy'}, this.busy));
    bar.append(h('span', {class: 'spacer'}), h('span', {class: 'local', title: 'Files are read in place from this computer'},
      'Local · read-only'));
  }

  pick(id, event, ordered) {
    if (event.shiftKey && this.anchor && ordered.includes(this.anchor)) {
      const a = ordered.indexOf(this.anchor), b = ordered.indexOf(id);
      const range = ordered.slice(Math.min(a, b), Math.max(a, b) + 1);
      if (!(event.ctrlKey || event.metaKey)) this.selection.clear();
      for (const member of range) this.selection.add(member);
    } else if (event.ctrlKey || event.metaKey) {
      if (this.selection.has(id)) this.selection.delete(id);
      else this.selection.add(id);
      this.anchor = id;
    } else {
      this.selection.clear();
      this.selection.add(id);
      this.anchor = id;
    }
    this.focus = id;
    this.selectionChanged();
  }

  toggle(id) {
    if (this.selection.has(id)) this.selection.delete(id);
    else this.selection.add(id);
    this.anchor = id;
    this.focus = id;
    this.selectionChanged();
  }

  setSelection(ids, selected) {
    for (const id of ids) {
      if (selected) this.selection.add(id);
      else this.selection.delete(id);
    }
    this.selectionChanged();
  }

  clearSelection() {
    if (!this.selection.size) return;
    this.selection.clear();
    this.selectionChanged();
  }

  setFocus(id) {
    this.focus = id;
    this.view?.refreshSelection?.();
    this.inspector.render();
  }

  selectionChanged() {
    this.view?.refreshSelection?.();
    this.renderContextbar();
    this.inspector.render();
    this.renderStatus();
  }

  activate(id, ordered) {
    const item = this.collection?.byId.get(id);
    if (!item) return;
    this.focus = id;
    this.viewer?.dispose();
    this.viewer = new FileViewer(this, this.dom.viewer, ordered.map(member => this.collection.byId.get(member)).filter(Boolean), item);
    this.dom.viewer.hidden = false;
    this.renderTopbar();
    this.renderContextbar();
    this.inspector.render();
  }

  closeViewer() {
    if (!this.viewer) return;
    this.viewer.dispose();
    this.viewer = null;
    clear(this.dom.viewer).hidden = true;
    this.view?.refreshSelection?.();
    this.view?.reveal?.(this.focus);
    this.renderTopbar();
    this.renderContextbar();
  }

  setThumb(size) {
    const anchor = this.view?.anchorBeforeResize?.();
    this.state.thumb = size;
    this.dom.app.style.setProperty('--thumb', size + 'px');
    this.view?.restoreAnchor?.(anchor);
    clearTimeout(this.thumbTimer);
    this.thumbTimer = setTimeout(() => this.savePreferences(), 400);
  }

  captionLimit() {
    const width = this.dom.main.clientWidth - 32;
    const columns = Math.max(1, Math.floor((width + 10) / (this.state.thumb + 10)));
    return Math.max(10, Math.floor(((width - (columns - 1) * 10) / columns - 10) / 6.3));
  }

  sizeControl() {
    return h('label', {class: 'size-control', title: 'Thumbnail size'}, icon('image', 14),
      h('input', {type: 'range', min: 90, max: 520, step: 10, value: this.state.thumb, 'aria-label': 'Thumbnail size',
        onInput: event => this.setThumb(Number(event.target.value))}), icon('image', 18));
  }

  toast(message, error = false) {
    document.querySelector('.toast')?.remove();
    const node = h('div', {class: 'toast' + (error ? ' error' : ''), role: 'status'}, message);
    document.body.append(node);
    setTimeout(() => node.remove(), error ? 6000 : 2500);
  }
}

const explorer = new Explorer();
explorer.start();
