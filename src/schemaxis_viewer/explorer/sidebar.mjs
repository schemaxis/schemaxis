// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// Sidebar: folder tree, property filters (from filenames, sequences, patterns
// and metadata) and recently opened folders and Schemaxis runs.

import {h, icon, iconButton, textButton, clear, fill} from './dom.mjs';
import {formatValue} from './names.mjs';
import {SOURCE_LABELS} from './collection.mjs';

const TABS = [{id: 'folders', label: 'Folders', icon: 'folder'}, {id: 'filters', label: 'Filters', icon: 'filter'},
  {id: 'recent', label: 'Recent', icon: 'clock'}];
const VALUE_PREVIEW = 8;

export class Sidebar {
  constructor(app, root) {
    this.app = app;
    this.root = root;
    this.open = new Set();
    this.collapsedFacets = new Set(['folder', 'n', 'n1', 'n2', 'name', 'scene']);
    this.expandedFacets = new Set();
    this.tabs = h('div', {class: 'tabs', role: 'tablist'});
    this.body = h('div', {class: 'sidebar-body'});
    root.append(this.tabs, this.body);
  }

  render() {
    const app = this.app;
    const tab = app.state.sidebarTab;
    const filterCount = [...app.state.filters.values()].reduce((sum, tokens) => sum + tokens.size, 0);
    fill(this.tabs, ...TABS.map(entry => h('button', {type: 'button', role: 'tab', 'aria-selected': String(tab === entry.id),
      onClick: () => {
        app.state.sidebarTab = entry.id;
        app.savePreferences();
        this.render();
      }}, entry.label, entry.id === 'filters' && filterCount ? h('span', {class: 'badge'}, filterCount) : null)));
    const scroll = this.body.scrollTop;
    clear(this.body);
    if (tab === 'folders') this.renderFolders();
    else if (tab === 'filters') this.renderFilters();
    else this.renderRecent();
    this.body.scrollTop = scroll;
  }

  renderFolders() {
    const app = this.app;
    if (!app.collection) {
      this.body.append(h('div', {class: 'sidebar-note'}, 'Open a folder to see its tree here.'));
      return;
    }
    const current = app.state.folder;
    for (let key = current; key; key = key.includes('/') ? key.slice(0, key.lastIndexOf('/')) : '') this.open.add(key);
    const roots = app.collection.folders.roots;
    const counts = new Map();
    for (const item of app.derived.visible) {
      for (let key = item.folder; key; key = key.includes('/') ? key.slice(0, key.lastIndexOf('/')) : '') counts.set(key, (counts.get(key) || 0) + 1);
    }
    const list = h('ul', {class: 'tree', role: 'tree'});
    if (roots.length > 1) {
      list.append(h('li', {}, h('div', {class: 'tree-row' + (current === '' ? ' current' : ''), onClick: () => app.setFolder('')},
        h('span', {class: 'twisty leaf'}), icon('files', 15), h('span', {class: 'name'}, 'All folders'),
        h('span', {class: 'count'}, app.derived.visible.length))));
    }
    for (const node of roots) list.append(this.treeNode(node, counts, current));
    this.body.append(h('div', {class: 'sidebar-head'}, 'Folders'), list);
  }

  treeNode(node, counts, current) {
    const app = this.app;
    const open = this.open.has(node.key);
    const twisty = h('button', {type: 'button', class: 'twisty' + (node.children.length ? '' : ' leaf') + (open ? ' open' : ''),
      'aria-label': open ? 'Collapse' : 'Expand', onClick: event => {
        event.stopPropagation();
        if (open) this.open.delete(node.key);
        else this.open.add(node.key);
        this.render();
      }}, icon('chevronRight', 14));
    const row = h('div', {class: 'tree-row' + (current === node.key ? ' current' : ''), role: 'treeitem', title: node.key,
      onClick: () => app.setFolder(node.key)},
      twisty, icon(open ? 'folderOpen' : 'folder', 15), h('span', {class: 'name'}, node.name),
      h('span', {class: 'count'}, counts.get(node.key) || 0));
    const item = h('li', {}, row);
    if (open && node.children.length) item.append(h('ul', {class: 'tree'}, node.children.map(child => this.treeNode(child, counts, current))));
    return item;
  }

  renderFilters() {
    const app = this.app;
    this.body.append(h('div', {class: 'sidebar-head'}, 'Properties', h('span', {class: 'spacer'}),
      app.state.filters.size ? h('button', {type: 'button', class: 'link-button', onClick: () => app.clearFilters()}, 'Clear all') : null,
      textButton('Patterns…', () => app.editPatterns(), {class: 'button small', title: 'Extract properties from filenames with regular expressions', disabled: !app.collection})));
    if (!app.collection) {
      this.body.append(h('div', {class: 'sidebar-note'}, 'Open a folder to filter its files by type, filename properties, sequences and metadata.'));
      return;
    }
    const facets = app.derived.facets;
    if (!facets.length) {
      this.body.append(h('div', {class: 'sidebar-note'}, 'No properties found.'));
      return;
    }
    for (const facet of facets) this.body.append(this.facet(facet));
    if (app.collection.ruleErrors.size) {
      this.body.append(h('div', {class: 'sidebar-note'}, `${app.collection.ruleErrors.size} filename pattern(s) have errors.`));
    }
    this.body.append(h('div', {class: 'sidebar-note'},
      'Ticks within one property match any; different properties must all match. ',
      textButton('Add a filename pattern…', () => app.editPatterns(), {class: 'button small'})));
  }

  facet(facet) {
    const app = this.app;
    const collapsed = this.collapsedFacets.has(facet.key) && !facet.active;
    const sources = new Set();
    for (const item of app.derived.scope) if (item.sources[facet.key]) sources.add(SOURCE_LABELS[item.sources[facet.key]]);
    const expanded = this.expandedFacets.has(facet.key);
    const values = expanded ? facet.values : facet.values.slice(0, VALUE_PREVIEW);
    const node = h('div', {class: 'facet' + (collapsed ? ' collapsed' : '')},
      h('div', {class: 'facet-head', onClick: () => {
        if (this.collapsedFacets.has(facet.key)) this.collapsedFacets.delete(facet.key);
        else this.collapsedFacets.add(facet.key);
        node.classList.toggle('collapsed');
      }},
      this.twist(),
      h('span', {class: 'key'}, facet.key),
      h('span', {class: 'source'}, [...sources].join(', ')),
      h('span', {class: 'spacer'}),
      facet.active ? h('button', {type: 'button', class: 'clear-key', onClick: event => {
        event.stopPropagation();
        app.clearFilters(facet.key);
      }}, 'clear') : h('span', {class: 'source'}, facet.values.length)),
      h('div', {class: 'facet-values'}, values.map(entry => h('label', {class: 'facet-value' + (entry.count ? '' : ' empty'), title: formatValue(entry.value)},
        h('input', {type: 'checkbox', checked: entry.checked, onChange: () => app.toggleFilter(facet.key, entry.token)}),
        h('span', {class: 'label'}, formatValue(entry.value)),
        h('span', {class: 'count'}, entry.count)))));
    if (facet.values.length > VALUE_PREVIEW) {
      node.querySelector('.facet-values').append(h('button', {type: 'button', class: 'facet-more', onClick: () => {
        if (expanded) this.expandedFacets.delete(facet.key);
        else this.expandedFacets.add(facet.key);
        this.render();
      }}, expanded ? 'Show fewer' : `Show all ${facet.values.length}`));
    }
    return node;
  }

  twist() {
    const node = icon('chevronDown', 14);
    node.classList.add('twist');
    return node;
  }

  renderRecent() {
    const app = this.app;
    if (!app.hostAvailable) {
      this.body.append(h('div', {class: 'sidebar-note'}, 'Recent folders appear when the viewer runs from its local launcher or Studio.'));
      return;
    }
    const runs = app.recent.filter(row => row.kind === 'run');
    const folders = app.recent.filter(row => row.kind !== 'run');
    const row = entry => h('button', {class: 'recent-row', type: 'button', title: (entry.paths || []).join('\n'), onClick: () => app.reopen(entry)},
      h('strong', {}, entry.label), h('span', {}, `${entry.count ?? 0} files · ${entry.viewed ? new Date(entry.viewed).toLocaleString() : ''}`));
    this.body.append(h('div', {class: 'sidebar-head'}, 'Schemaxis runs'),
      runs.length ? runs.map(row) : h('div', {class: 'sidebar-note'}, 'Completed runs opened from Studio appear here.'),
      h('div', {class: 'sidebar-head'}, 'Folders'),
      folders.length ? folders.map(row) : h('div', {class: 'sidebar-note'}, 'Folders you open appear here. Only their paths are remembered.'));
  }
}
