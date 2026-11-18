// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// Browsing views. Files works like a file manager (folders, grid or details
// list, optional stacking of sequences). Groups arranges the matching files
// into sequences or into groups chosen by property, each in its own order.

import {h, icon, iconButton, toggleButton, textButton, chip, clear, middleEllipsis} from './dom.mjs';
import {mediaURL} from './host.mjs';
import {formatValue, formatBytes, naturalCompare, KIND_LABELS} from './names.mjs';
import {captionFor, commonChips, sortItems, SOURCE_LABELS} from './collection.mjs';

const CHUNK = 240;
const GROUP_PREVIEW = 36;

export function shortName(item) {
  if (item.sx) {
    const values = Object.entries(item.sx.properties).filter(([key]) => key !== 'scene').map(([, value]) => formatValue(value));
    return `${item.sx.ordinal}${item.sx.worker ? '.' + item.sx.worker : ''} · ${values.join(' ')}`;
  }
  return item.name;
}

export function thumbFor(item) {
  const thumb = h('div', {class: 'thumb'});
  if (item.kind === 'image') {
    thumb.append(h('img', {src: mediaURL(item), loading: 'lazy', decoding: 'async', alt: '', draggable: 'false'}));
  } else {
    thumb.append(h('span', {class: `kind-icon kind-${item.kind}`}, icon(item.kind === 'other' ? 'other' : item.kind)),
      h('span', {class: 'ext'}, item.ext || 'file'));
  }
  return thumb;
}

function itemTile(item, caption) {
  const badges = [];
  if (item.spatial) badges.push(h('span', {class: 'badge', title: 'Placed in 3D by its metadata'}, '3D'));
  if (item.kind === 'video') badges.push(h('span', {class: 'badge'}, icon('play', 10)));
  return h('div', {class: 'tile', dataset: {id: item.id}, title: item.path},
    thumbFor(item),
    h('button', {class: 'tick', type: 'button', 'aria-label': 'Select', tabindex: '-1'}, icon('check')),
    badges.length ? h('div', {class: 'badges'}, badges) : null,
    h('div', {class: 'caption'}, caption));
}

function stackTile(group, chips, limit, showFolder) {
  const first = group.items[0];
  const name = group.label || chips.map(([key, value]) => `${key} ${formatValue(value)}`).join(' · ') || 'Sequence';
  const label = showFolder && group.folder ? `${group.folder.split('/').at(-1)} › ${name}` : name;
  return h('div', {class: 'tile stack', dataset: {group: group.id}, title: `${label}\n${group.items.length} files — double-click to play`},
    thumbFor(first),
    h('div', {class: 'badges'}, h('span', {class: 'badge'}, icon('stack', 10), String(group.items.length))),
    h('div', {class: 'caption'}, middleEllipsis(label, limit)));
}

function folderTile(node, count) {
  return h('div', {class: 'tile folder', dataset: {folder: node.key}, title: node.key},
    h('div', {class: 'thumb'}, icon('folder')),
    h('div', {class: 'caption'}, `${node.name} · ${count}`));
}

function appendChunked(view, container, entries, make) {
  let offset = 0;
  const sentinel = h('div', {class: 'more-sentinel'});
  const more = function more() {
    const slice = entries.slice(offset, offset + CHUNK);
    offset += slice.length;
    container.append(...slice.map(make));
    if (offset >= entries.length) {
      observer.disconnect();
      sentinel.remove();
    } else {
      container.after(sentinel);
    }
  };
  const observer = new IntersectionObserver(records => {
    if (records.some(record => record.isIntersecting)) more();
  }, {root: view.root, rootMargin: '900px'});
  view.observers.push(observer);
  more();
  if (offset < entries.length) observer.observe(sentinel);
}

class BrowseView {
  constructor(app, root) {
    this.app = app;
    this.root = root;
    this.observers = [];
    this.ordered = [];
    this.groupsById = new Map();
    this.onClick = this.onClick.bind(this);
    this.onDoubleClick = this.onDoubleClick.bind(this);
    root.addEventListener('click', this.onClick);
    root.addEventListener('dblclick', this.onDoubleClick);
  }

  dispose() {
    this.disconnect();
    this.root.removeEventListener('click', this.onClick);
    this.root.removeEventListener('dblclick', this.onDoubleClick);
  }

  disconnect() {
    for (const observer of this.observers) observer.disconnect();
    this.observers = [];
  }

  orderedIds() {
    return this.ordered;
  }

  onClick(event) {
    const tile = event.target.closest('.tile, tr[data-id]');
    if (!tile) {
      if (event.target === this.root || event.target.classList.contains('pane') || event.target.classList.contains('tiles')) {
        this.app.clearSelection();
      }
      return;
    }
    if (tile.dataset.folder) {
      this.app.setFolder(tile.dataset.folder);
      return;
    }
    if (tile.dataset.group) {
      const group = this.groupsById.get(tile.dataset.group);
      if (!group) return;
      const ids = group.items.map(item => item.id);
      if (!(event.ctrlKey || event.metaKey)) this.app.selection.clear();
      this.app.setSelection(ids, true);
      this.app.setFocus(ids[0]);
      return;
    }
    if (event.target.closest('.tick')) this.app.toggle(tile.dataset.id);
    else this.app.pick(tile.dataset.id, event, this.ordered);
  }

  onDoubleClick(event) {
    const tile = event.target.closest('.tile, tr[data-id]');
    if (!tile || tile.dataset.folder || event.target.closest('.tick')) return;
    if (tile.dataset.group) {
      const group = this.groupsById.get(tile.dataset.group);
      if (group) this.app.playGroup(group);
      return;
    }
    this.app.activate(tile.dataset.id, this.ordered);
  }

  refreshSelection() {
    const {selection, focus} = this.app;
    for (const node of this.root.querySelectorAll('[data-id]')) {
      node.classList.toggle('selected', selection.has(node.dataset.id));
      node.classList.toggle('focused', focus === node.dataset.id);
    }
    for (const node of this.root.querySelectorAll('[data-group]')) {
      const group = this.groupsById.get(node.dataset.group);
      node.classList.toggle('selected', !!group && group.items.every(item => selection.has(item.id)));
    }
    for (const node of this.root.querySelectorAll('.tiles')) node.classList.toggle('selecting', selection.size > 1);
    this.refreshGroupChecks?.();
  }

  anchorBeforeResize() {
    const top = this.root.getBoundingClientRect().top;
    for (const node of this.root.querySelectorAll('.tile')) {
      const rect = node.getBoundingClientRect();
      if (rect.bottom > top + 4) return {node, offset: rect.top - top};
    }
    return null;
  }

  restoreAnchor(anchor) {
    if (!anchor || !anchor.node.isConnected) return;
    const top = this.root.getBoundingClientRect().top;
    this.root.scrollTop += anchor.node.getBoundingClientRect().top - top - anchor.offset;
  }

  reveal(id) {
    const node = id && this.root.querySelector(`[data-id="${CSS.escape(id)}"]`);
    if (!node) return;
    const rect = node.getBoundingClientRect(), view = this.root.getBoundingClientRect();
    if (rect.top < view.top || rect.bottom > view.bottom) node.scrollIntoView({block: 'nearest'});
  }

  onKey(event) {
    const ids = this.ordered;
    if (!ids.length) return false;
    const current = ids.indexOf(this.app.focus);
    if (event.key === 'Enter' && current >= 0) {
      this.app.activate(ids[current], ids);
      return true;
    }
    if (event.key === ' ' && current >= 0) {
      event.preventDefault();
      this.app.toggle(ids[current]);
      return true;
    }
    const delta = {ArrowLeft: -1, ArrowRight: 1}[event.key];
    let next = -1;
    if (delta) {
      next = current < 0 ? 0 : Math.max(0, Math.min(ids.length - 1, current + delta));
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      next = this.verticalNeighbour(current, event.key === 'ArrowDown' ? 1 : -1);
    } else {
      return false;
    }
    if (next < 0) return true;
    event.preventDefault();
    if (event.shiftKey) this.app.pick(ids[next], {shiftKey: true}, ids);
    else this.app.pick(ids[next], {}, ids);
    this.reveal(ids[next]);
    return true;
  }

  verticalNeighbour(current, direction) {
    const ids = this.ordered;
    if (current < 0) return 0;
    const from = this.root.querySelector(`[data-id="${CSS.escape(ids[current])}"]`);
    if (!from) return current;
    const origin = from.getBoundingClientRect();
    let best = -1, distance = Infinity;
    for (let i = current + direction; i >= 0 && i < ids.length; i += direction) {
      const node = this.root.querySelector(`[data-id="${CSS.escape(ids[i])}"]`);
      if (!node) break;
      const rect = node.getBoundingClientRect();
      const dy = (rect.top - origin.top) * direction;
      if (dy <= 2) continue;
      const score = dy * 4 + Math.abs(rect.left - origin.left);
      if (score < distance) {
        distance = score;
        best = i;
      }
      if (dy > origin.height * 3) break;
    }
    return best < 0 ? current : best;
  }
}

export class FilesView extends BrowseView {
  constructor(app, root) {
    super(app, root);
    this.sort = {key: 'name', descending: false};
  }

  contextControls() {
    const app = this.app, state = app.state;
    const crumbs = [];
    for (let key = state.folder; key; key = key.includes('/') ? key.slice(0, key.lastIndexOf('/')) : '') {
      const node = app.collection.folders.nodes.get(key);
      crumbs.unshift(h('button', {type: 'button', onClick: () => app.setFolder(key)}, node?.name || key));
    }
    const multipleRoots = app.collection.folders.roots.length > 1;
    if (multipleRoots) crumbs.unshift(h('button', {type: 'button', onClick: () => app.setFolder('')}, 'All folders'));
    const parts = [];
    for (const [index, crumb] of crumbs.entries()) {
      if (index) parts.push(icon('chevronRight', 14));
      parts.push(crumb);
    }
    const parent = state.folder.includes('/') ? state.folder.slice(0, state.folder.lastIndexOf('/')) : (multipleRoots && state.folder ? '' : null);
    return [
      iconButton('up', 'Up one folder (Backspace)', () => app.setFolder(parent), {disabled: parent === null}),
      h('nav', {class: 'breadcrumbs', 'aria-label': 'Folder path'}, parts),
      h('div', {class: 'spacer'}),
      h('label', {class: 'check', title: 'Show the files in all subfolders of this folder'},
        h('input', {type: 'checkbox', checked: state.recursive, onChange: event => app.set({recursive: event.target.checked}, {persist: true})}),
        'Include subfolders'),
      h('label', {class: 'check', title: 'Show each numbered or keyed sequence as one stack'},
        h('input', {type: 'checkbox', checked: state.stack, onChange: event => app.set({stack: event.target.checked}, {persist: true})}),
        'Stack sequences'),
      h('div', {class: 'divider'}),
      toggleButton('grid', 'Icons', state.layout === 'grid', () => app.set({layout: 'grid'}, {persist: true})),
      toggleButton('list', 'Details', state.layout === 'list', () => app.set({layout: 'list'}, {persist: true})),
      state.layout === 'grid' ? app.sizeControl() : null
    ];
  }

  onKey(event) {
    if (event.key === 'Backspace' || (event.altKey && event.key === 'ArrowUp')) {
      const folder = this.app.state.folder;
      if (folder) {
        event.preventDefault();
        this.app.setFolder(folder.includes('/') ? folder.slice(0, folder.lastIndexOf('/')) : '');
      }
      return true;
    }
    return super.onKey(event);
  }

  sortedFiles(items) {
    const {key, descending} = this.sort;
    let list;
    if (key === 'size') list = [...items].sort((a, b) => (a.size || 0) - (b.size || 0) || naturalCompare(a.name, b.name));
    else if (key === 'type') list = [...items].sort((a, b) => naturalCompare(a.ext, b.ext) || naturalCompare(a.name, b.name));
    else list = sortItems(items, '@name');
    return descending ? list.reverse() : list;
  }

  render() {
    const app = this.app, state = app.state, d = app.derived;
    this.disconnect();
    const pane = clear(this.root).appendChild(h('div', {class: 'pane'}));
    const folders = [];
    if (!state.recursive) {
      const node = state.folder ? app.collection.folders.nodes.get(state.folder) : null;
      const children = node ? node.children : app.collection.folders.roots;
      for (const child of children) {
        const count = d.visible.filter(item => item.folder === child.key || item.folder.startsWith(child.key + '/')).length;
        if (count || !state.filters.size && !state.query) folders.push([child, count]);
      }
    }
    const files = this.sortedFiles(d.level);
    const entries = [];
    this.groupsById = new Map();
    if (state.stack && state.layout === 'grid') {
      const placed = new Set();
      const families = new Map();
      for (const group of d.groups) if (group.sequence) for (const item of group.items) families.set(item.id, group);
      for (const item of files) {
        const group = families.get(item.id);
        const members = group ? group.items.filter(member => d.level.includes(member)) : [];
        if (group && members.length > 1) {
          if (placed.has(group.id)) continue;
          placed.add(group.id);
          const shown = {...group, items: members};
          this.groupsById.set(group.id, shown);
          entries.push({group: shown});
        } else {
          entries.push({item});
        }
      }
    } else {
      for (const item of files) entries.push({item});
    }
    this.ordered = entries.flatMap(entry => entry.group ? entry.group.items.map(item => item.id) : [entry.item.id]);
    if (!folders.length && !entries.length) {
      pane.append(h('div', {class: 'empty-state'}, icon('folder'),
        state.filters.size || state.query ? 'No files here match the current search or filters.' :
          'This folder has no files. Tick “Include subfolders” to see files further down.'));
      return;
    }
    if (state.layout === 'list') {
      this.renderList(pane, folders, files);
    } else {
      const limit = app.captionLimit();
      const {distinct} = commonChips([...this.groupsById.values()]);
      const showFolder = new Set([...this.groupsById.values()].map(group => group.folder)).size > 1;
      const grid = pane.appendChild(h('div', {class: 'tiles'}));
      grid.append(...folders.map(([node, count]) => folderTile(node, count)));
      appendChunked(this, grid, entries, entry => entry.group ? stackTile(entry.group, distinct.get(entry.group.id) || entry.group.chips, limit, showFolder)
        : itemTile(entry.item, middleEllipsis(shortName(entry.item), limit)));
    }
    this.refreshSelection();
  }

  renderList(pane, folders, files) {
    const header = (key, label, numeric = false) => h('th', {class: numeric ? 'num' : '', onClick: () => {
      this.sort = {key, descending: this.sort.key === key ? !this.sort.descending : false};
      this.render();
    }}, label, this.sort.key === key ? (this.sort.descending ? ' ↓' : ' ↑') : '');
    const table = h('table', {class: 'file-list'},
      h('thead', {}, h('tr', {}, header('name', 'Name'), h('th', {}, 'Properties'), header('type', 'Type'), header('size', 'Size', true))));
    const body = table.appendChild(h('tbody'));
    for (const [node, count] of folders) {
      body.append(h('tr', {class: 'tile-row', dataset: {folder: node.key}},
        h('td', {class: 'name'}, h('span', {class: 'kind-mesh'}, icon('folder')), h('span', {}, node.name)),
        h('td', {}), h('td', {}, 'Folder'), h('td', {class: 'num'}, `${count} files`)));
    }
    appendChunked(this, body, files, item => h('tr', {dataset: {id: item.id}, title: item.path},
      h('td', {class: 'name'}, h('span', {class: `kind-${item.kind}`}, icon(item.kind)), h('span', {}, item.name)),
      h('td', {}, h('div', {class: 'props'}, Object.entries(item.props)
        .filter(([key]) => item.sources[key] !== 'file')
        .slice(0, 8).map(([key, value]) => chip(key, formatValue(value))))),
      h('td', {}, KIND_LABELS[item.kind].replace(/s$/, '') + (item.ext ? ` (.${item.ext})` : '')),
      h('td', {class: 'num'}, formatBytes(item.size))));
    pane.classList.add('listpane');
    pane.append(table);
    for (const row of table.querySelectorAll('tr[data-folder]')) {
      row.addEventListener('click', () => this.app.setFolder(row.dataset.folder));
    }
  }
}

export class GroupsView extends BrowseView {
  constructor(app, root) {
    super(app, root);
    this.collapsed = new Set();
    this.expanded = new Set();
  }

  contextControls() {
    const app = this.app, state = app.state, keys = app.derived.keys;
    const mode = state.groupBy.length === 1 && state.groupBy[0] === '@sequence' ? '@sequence' : state.groupBy.length ? '@keys' : '@none';
    const controls = [h('label', {class: 'field'}, 'Group by',
      h('select', {'aria-label': 'Group by', onChange: event => {
        const value = event.target.value;
        app.set({groupBy: value === '@sequence' ? ['@sequence'] : value === '@none' ? [] : [value]});
      }},
      h('option', {value: '@sequence', selected: mode === '@sequence'}, 'Sequences (automatic)'),
      h('option', {value: '@none', selected: mode === '@none'}, 'Nothing'),
      h('optgroup', {label: 'Property'}, keys.map(key => h('option', {value: key, selected: mode === '@keys' && state.groupBy[0] === key}, key)))))];
    if (mode === '@keys') {
      for (const [index, key] of state.groupBy.entries()) {
        if (!index) continue;
        controls.push(icon('chevronRight', 14), h('button', {class: 'chip', type: 'button', title: 'Remove this level',
          onClick: () => app.set({groupBy: state.groupBy.filter((_, i) => i !== index)})},
          h('span', {class: 'chip-value'}, key), icon('close', 12)));
      }
      const remaining = keys.filter(key => !state.groupBy.includes(key));
      if (remaining.length) {
        controls.push(h('select', {'aria-label': 'Then group by', onChange: event => {
          if (event.target.value) app.set({groupBy: [...state.groupBy, event.target.value]});
        }}, h('option', {value: ''}, '+ then by…'), remaining.map(key => h('option', {value: key}, key))));
      }
    }
    controls.push(h('label', {class: 'field'}, 'Order by',
      h('select', {'aria-label': 'Order by', onChange: event => app.set({orderBy: event.target.value})},
        h('option', {value: 'auto', selected: state.orderBy === 'auto'}, 'Automatic'),
        h('option', {value: '@name', selected: state.orderBy === '@name'}, 'Name'),
        keys.filter(key => key !== 'type' && key !== 'folder').map(key => h('option', {value: key, selected: state.orderBy === key}, key)))));
    controls.push(h('div', {class: 'spacer'}),
      iconButton('chevronDown', 'Expand all groups', () => { this.collapsed.clear(); this.render(); }),
      iconButton('chevronRight', 'Collapse all groups', () => {
        for (const group of app.derived.groups) this.collapsed.add(group.id);
        this.render();
      }),
      app.sizeControl());
    return controls;
  }

  render() {
    const app = this.app, d = app.derived;
    this.disconnect();
    const scroll = this.root.scrollTop;
    const pane = clear(this.root).appendChild(h('div', {class: 'pane'}));
    const groups = d.groups;
    this.groupsById = new Map(groups.map(group => [group.id, group]));
    this.ordered = groups.flatMap(group => group.items.map(item => item.id));
    if (!groups.length || !d.visible.length) {
      pane.append(h('div', {class: 'empty-state'}, icon('groups'), 'No files match the current search or filters.'));
      return;
    }
    const {common, distinct} = commonChips(groups);
    if (common.length) pane.append(h('div', {class: 'common-line'}, 'Shared by these groups:', common.map(([key, value]) => chip(key, formatValue(value)))));
    const folders = new Set(groups.filter(group => group.folder).map(group => group.folder));
    let lastFolder = null;
    const limit = app.captionLimit();
    for (const group of groups) {
      if (folders.size > 1 && group.folder && group.folder !== lastFolder) {
        lastFolder = group.folder;
        pane.append(h('div', {class: 'folder-heading'}, icon('folder'), group.folder));
      }
      pane.append(this.section(group, distinct.get(group.id) || [], limit));
    }
    this.root.scrollTop = scroll;
    this.refreshSelection();
  }

  section(group, chips, limit) {
    const app = this.app;
    const playable = group.items.filter(item => item.kind === 'image' || item.kind === 'video').length > 1;
    const spatial = group.items.some(item => item.spatial);
    const check = h('input', {type: 'checkbox', 'aria-label': 'Select this group', dataset: {groupCheck: group.id}, onClick: event => {
      event.stopPropagation();
      app.setSelection(group.items.map(item => item.id), event.target.checked);
    }});
    const title = [];
    if (group.label) title.push(h('span', {class: 'label'}, group.label));
    for (const [key, value] of chips) title.push(chip(key, value === undefined ? '—' : formatValue(value)));
    if (!title.length) title.push(h('span', {}, group.id === '@other' ? group.label : group.sequence ? 'Sequence' : 'All files'));
    const order = group.orderKey === '@rank' ? 'sequence number' : group.orderKey === '@name' ? 'name' : group.orderKey;
    const section = h('section', {class: 'group-section' + (this.collapsed.has(group.id) ? ' collapsed' : ''), dataset: {section: group.id}},
      h('div', {class: 'group-head'},
        h('button', {class: 'twisty', type: 'button', 'aria-label': 'Collapse or expand', onClick: () => {
          if (this.collapsed.has(group.id)) this.collapsed.delete(group.id);
          else this.collapsed.add(group.id);
          section.classList.toggle('collapsed');
        }}, icon('chevronDown')),
        check,
        h('div', {class: 'title'}, title),
        h('span', {class: 'meta'}, `${group.items.length} files${group.items.length > 1 ? ` · by ${order}` : ''}`),
        h('div', {class: 'spacer'}),
        playable ? textButton('Play', () => app.playGroup(group), {class: 'button small', title: 'Play this sequence'}) : null,
        spatial ? textButton('3D', () => {
          app.spaceState.only = new Set(group.items.map(item => item.id));
          app.setView('space');
        }, {class: 'button small', title: 'Show these slices in 3D'}) : null));
    const grid = section.appendChild(h('div', {class: 'tiles'}));
    const all = this.expanded.has(group.id);
    const shown = all ? group.items : group.items.slice(0, GROUP_PREVIEW);
    appendChunked(this, grid, shown, item => itemTile(item, middleEllipsis(group.orderKey === '@name' ? shortName(item) : captionFor(item, group.orderKey, group.vary), limit)));
    if (shown.length < group.items.length) {
      section.append(h('div', {class: 'group-more'}, textButton(`Show all ${group.items.length}`, () => {
        this.expanded.add(group.id);
        this.render();
      }, {class: 'button small'})));
    }
    return section;
  }

  refreshGroupChecks() {
    for (const box of this.root.querySelectorAll('[data-group-check]')) {
      const group = this.groupsById.get(box.dataset.groupCheck);
      if (!group) continue;
      const count = group.items.filter(item => this.app.selection.has(item.id)).length;
      box.checked = count === group.items.length;
      box.indeterminate = count > 0 && count < group.items.length;
    }
  }
}

export {SOURCE_LABELS};
