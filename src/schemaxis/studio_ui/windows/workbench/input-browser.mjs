// Copyright (C) 2026 David L F Gaden
// Choosing a file on the computer running Studio. Studio's own Open window
// follows the desktop conventions: places, a folder list, a file name and
// Open. Selecting a path never uploads or copies its bytes.
import {h, icon, mount} from '../../lib/dom.mjs';
import {openDialog} from '../../shell/dialog.mjs';

const RECENT = 'schemaxis.studio.folders';

function recentFolders() {
  try {
    const value = JSON.parse(localStorage.getItem(RECENT) || '[]');
    return Array.isArray(value) ? value.filter((item) => typeof item === 'string').slice(0, 6) : [];
  } catch {
    return [];
  }
}

function rememberFolder(folder) {
  try {
    localStorage.setItem(RECENT, JSON.stringify([folder, ...recentFolders().filter((item) => item !== folder)].slice(0, 6)));
  } catch {
    // Recent folders are a convenience only.
  }
}

/**
 * Ask for a file. Resolves with its absolute path, or null when cancelled.
 * `save` names a destination, which need not exist yet.
 */
export function chooseFile(ctx, {label, extensions = [], current = '', save = false}) {
  let sequence = 0;
  let parent = '';
  let directory = '';
  let entries = [];
  let history = [];
  let index = -1;
  let selected = null;
  let finish = () => {};
  const location = h('input', {class: 'input mono', 'aria-label': `Browse folder for ${label}`, title: 'Type a folder and press Enter',
    onKeydown: (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        event.stopPropagation();
        load(location.value);
      }
    }});
  const state = h('p', {class: 'wb-help', role: 'status'});
  const list = h('div', {class: 'operation-file-list', role: 'listbox', 'aria-label': 'Folders and files'});
  const crumbs = h('nav', {class: 'operation-file-crumbs', 'aria-label': 'Folder path'});
  const places = h('nav', {class: 'operation-file-places', 'aria-label': 'Places'});
  const search = h('input', {class: 'input', type: 'search', placeholder: 'Filter this folder…',
    'aria-label': 'Filter files', onInput: render});
  const hidden = h('input', {type: 'checkbox', onChange: render});
  const allFiles = h('input', {type: 'checkbox', onChange: () => load(directory, false)});
  const name = h('input', {class: 'input mono', 'aria-label': 'File name',
    placeholder: save ? 'Name the file to save' : 'Select a file above, or type its name',
    onKeydown: (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        event.stopPropagation();
        accept();
      }
    }});
  const back = h('button', {class: 'button small', type: 'button', disabled: true, title: 'Back',
    onClick: () => load(history[index - 1], false, index - 1)}, 'Back');
  const forward = h('button', {class: 'button small', type: 'button', disabled: true, title: 'Forward',
    onClick: () => load(history[index + 1], false, index + 1)}, 'Forward');
  const up = h('button', {class: 'button small', type: 'button', title: 'Parent folder', onClick: () => load(parent)}, 'Up');
  const panel = h('section', {class: 'operation-file-browser'},
    h('div', {class: 'operation-file-tools'}, back, forward, up, location),
    crumbs,
    h('div', {class: 'operation-file-panes'}, places,
      h('div', {class: 'operation-file-main'},
        h('div', {class: 'operation-file-tools'}, search, h('label', {}, hidden, ' Hidden files'),
          extensions.length ? h('label', {}, allFiles, ' All file types') : null), list, state)),
    h('label', {class: 'operation-file-name'}, h('span', {}, 'File name'), name),
    h('small', {class: 'wb-help'}, `${extensions.length ? `Suggested types: ${extensions.join(', ')}` : 'All file types'}`
      + ' · files on the computer running Studio'));

  function path() {
    const value = name.value.trim();
    if (!value) return null;
    return value.startsWith('/') || value.startsWith('~') ? value : `${directory.replace(/\/$/, '')}/${value}`;
  }

  function accept() {
    const value = path();
    const folder = entries.find((entry) => entry.directory && entry.path === value);
    if (folder) {
      load(folder.path);
      return false;
    }
    if (!value) {
      state.textContent = 'Select a file, or type its name.';
      return false;
    }
    rememberFolder(directory);
    finish(value);
    return value;
  }

  function render() {
    const query = search.value.trim().toLocaleLowerCase();
    const matches = entries.filter((entry) => (hidden.checked || !entry.name.startsWith('.'))
      && entry.name.toLocaleLowerCase().includes(query));
    state.textContent = `${matches.length} of ${entries.length} entries${matches.length ? '' : ' · No matches. Clear the filter or choose another folder.'}`;
    mount(list, matches.map((entry) => h('button', {class: 'operation-file-entry', type: 'button', role: 'option',
      title: entry.path, 'aria-selected': String(entry.path === selected),
      onClick: () => {
        if (entry.directory) {
          load(entry.path);
          return;
        }
        selected = entry.path;
        name.value = entry.name;
        list.querySelectorAll('[aria-selected]').forEach((item) => item.setAttribute('aria-selected', String(item.title === selected)));
      },
      onDblclick: () => { if (!entry.directory) accept(); }},
    icon(entry.directory ? 'folder' : 'file'),
    h('span', {class: 'visually-hidden'}, entry.directory ? 'Folder: ' : 'File: '), entry.name)));
  }

  function renderPlaces() {
    const workspace = ctx.store.get().server?.workspace;
    const place = (title, folder) => h('button', {class: 'operation-file-place', type: 'button', title: folder,
      'aria-current': folder === directory ? 'true' : undefined, onClick: () => load(folder)}, title);
    mount(places, h('strong', {}, 'Places'), place('Home', '~'), workspace ? place('Workspace', workspace) : null,
      recentFolders().length ? h('strong', {}, 'Recent') : null,
      recentFolders().map((folder) => place(folder.split('/').filter(Boolean).at(-1) || '/', folder)));
  }

  async function load(folder, push = true, nextIndex = index) {
    const token = ++sequence;
    state.textContent = 'Loading folder…';
    mount(list);
    try {
      const result = await ctx.api.get('/api/input-files', {directory: folder,
        extensions: allFiles.checked ? '' : extensions.join(',')});
      if (token !== sequence || !panel.isConnected) return;
      directory = result.directory;
      location.value = directory;
      parent = result.parent;
      entries = result.entries;
      if (push && history[index] !== directory) {
        history = history.slice(0, index + 1);
        history.push(directory);
        index++;
      } else if (!push) index = nextIndex;
      back.disabled = index <= 0;
      forward.disabled = index >= history.length - 1;
      up.disabled = parent === directory;
      search.value = '';
      const parts = directory.split('/').filter(Boolean);
      mount(crumbs, h('button', {class: 'button quiet small', type: 'button', onClick: () => load('/')}, '/'),
        parts.map((part, i) => h('button', {class: 'button quiet small', type: 'button',
          onClick: () => load('/' + parts.slice(0, i + 1).join('/'))}, part)));
      renderPlaces();
      render();
    } catch (error) {
      if (token === sequence && panel.isConnected) state.textContent = error.message;
    }
  }

  const result = openDialog({title: save ? 'Save as' : `Open ${label.split(/[./]/).at(-1) || 'file'}`, wide: true, enterSubmits: false,
    className: 'file-dialog', initialFocus: '[aria-label="Filter files"]', content: (close) => {
      finish = close;
      return panel;
    }, actions: [{label: 'Cancel', run: () => null}, {label: save ? 'Save here' : 'Open', primary: true, run: accept}]});
  if (current.includes('/')) {
    selected = current;
    name.value = current.slice(current.lastIndexOf('/') + 1);
  }
  load(current.includes('/') ? current.slice(0, current.lastIndexOf('/')) || '/' : ctx.store.get().server?.workspace);
  return result.then((value) => typeof value === 'string' ? value : null);
}

/** Choose an existing file with the desktop's Open window when there is one, otherwise Studio's own. */
export async function pickFile(ctx, {label, extensions = [], current = '', desktop = true, save = false}) {
  if (desktop && !save && ctx.setting('files.desktopChooser') !== false) {
    const result = await ctx.api.request('/api/input-file', {path: current, extensions}, {timeout: 330000});
    if (result.status === 'selected') return result.path;
    if (result.status === 'cancelled') return null;
  }
  return chooseFile(ctx, {label, extensions, current, save});
}

/**
 * A Browse… button that fills `input` with the chosen path. On a desktop it
 * opens the operating system's own Open window (through the Studio server);
 * where that is unavailable, turned off in Settings, or `desktop` is false
 * (choosing a path to save to), it opens Studio's own.
 */
export function inputBrowser(ctx, input, label, extensions = [], {desktop = true, save = false} = {}) {
  const choose = () => pickFile(ctx, {label, extensions, current: input.value, desktop, save});
  const button = h('button', {class: 'button small', type: 'button', 'aria-label': `Browse for ${label}`,
    onClick: () => ctx.call(async () => {
      button.disabled = true;
      try {
        const chosen = await choose();
        if (!chosen) return;
        input.value = chosen;
        input.dispatchEvent(new Event('input', {bubbles: true}));
        input.dispatchEvent(new Event('change', {bubbles: true}));
        input.focus();
      } finally {
        button.disabled = false;
      }
    }, {title: 'Could not choose a file'})}, 'Browse…');
  return h('div', {class: 'operation-browse'}, button);
}
