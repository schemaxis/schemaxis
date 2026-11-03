// Copyright (C) 2026 David L F Gaden
// Local-host file chooser. Selecting a path never uploads or copies its bytes.
import {h, mount} from '../../lib/dom.mjs';
export function inputBrowser(ctx, input, label, extensions = []) {
  let sequence = 0, parent = '', directory = '', entries = [], history = [], index = -1;
  const location = h('input', {class: 'input', 'aria-label': `Browse folder for ${label}`,
    onKeydown: event => { if (event.key === 'Enter') { event.preventDefault(); load(location.value); } }});
  const state = h('p', {class: 'wb-help', role: 'status'});
  const list = h('div', {class: 'operation-file-list', 'aria-label': 'Folders and files'});
  const crumbs = h('nav', {class: 'operation-file-crumbs', 'aria-label': 'Folder path'});
  const search = h('input', {class: 'input', type: 'search', placeholder: 'Filter this folder…',
    'aria-label': 'Filter files', onInput: render});
  const hidden = h('input', {type: 'checkbox', onChange: render});
  const allFiles = h('input', {type: 'checkbox', onChange: () => load(directory, false)});
  const back = h('button', {class: 'button small', type: 'button', disabled: true,
    onClick: () => load(history[index - 1], false, index - 1)}, 'Back');
  const forward = h('button', {class: 'button small', type: 'button', disabled: true,
    onClick: () => load(history[index + 1], false, index + 1)}, 'Forward');
  const up = h('button', {class: 'button small', type: 'button', onClick: () => load(parent)}, 'Up');
  const close = () => { panel.hidden = true; sequence++; input.focus(); };
  const panel = h('section', {class: 'operation-file-browser', hidden: true,
    onKeydown: event => { if (event.key === 'Escape') { event.stopPropagation(); close(); } }},
    h('p', {class: 'wb-help'}, 'Files on the computer running Studio. Select a file to use its absolute path.'),
    h('div', {class: 'operation-file-tools'}, back, forward, up,
      h('button', {class: 'button small', type: 'button', onClick: () => load(ctx.store.get().server?.workspace)}, 'Workspace'),
      h('button', {class: 'button small', type: 'button', onClick: () => load('~')}, 'Home'),
      h('button', {class: 'button small', type: 'button', onClick: close}, 'Close browser')),
    crumbs, h('div', {class: 'operation-file-tools'}, location,
      h('button', {class: 'button small', type: 'button', onClick: () => load(location.value)}, 'Go')),
    h('div', {class: 'operation-file-tools'}, search, h('label', {}, hidden, ' Hidden files'),
      extensions.length ? h('label', {}, allFiles, ' All file types') : null),
    h('small', {class: 'wb-help'}, extensions.length ? `Suggested types: ${extensions.join(', ')}` : 'All file types'), state, list);
  function render() {
    const query = search.value.trim().toLocaleLowerCase();
    const matches = entries.filter(entry => (hidden.checked || !entry.name.startsWith('.'))
      && entry.name.toLocaleLowerCase().includes(query));
    state.textContent = `${matches.length} of ${entries.length} entries${matches.length ? '' : ' · No matches. Clear the filter or choose another folder.'}`;
    mount(list, matches.map(entry => h('button', {class: 'operation-file-entry button quiet small', type: 'button',
      title: entry.path, onClick: () => {
        if (entry.directory) load(entry.path);
        else { input.value = entry.path; input.dispatchEvent(new Event('input', {bubbles: true}));
          input.dispatchEvent(new Event('change', {bubbles: true})); close(); }
      }}, `${entry.directory ? 'Folder: ' : 'File: '}${entry.name}`)));
  }
  async function load(folder, push = true, nextIndex = index) {
    const token = ++sequence;
    state.textContent = 'Loading folder…'; mount(list);
    try {
      const result = await ctx.api.get('/api/input-files', {directory: folder,
        extensions: allFiles.checked ? '' : extensions.join(',')});
      if (token !== sequence || panel.hidden) return;
      directory = result.directory; location.value = directory; parent = result.parent; entries = result.entries;
      if (push && history[index] !== directory) { history = history.slice(0, index + 1); history.push(directory); index++; }
      else if (!push) index = nextIndex;
      back.disabled = index <= 0; forward.disabled = index >= history.length - 1; up.disabled = parent === directory;
      search.value = '';
      const parts = directory.split('/').filter(Boolean);
      mount(crumbs, h('button', {class: 'button quiet small', type: 'button', onClick: () => load('/')}, '/'),
        parts.map((part, i) => h('button', {class: 'button quiet small', type: 'button',
          onClick: () => load('/' + parts.slice(0, i + 1).join('/'))}, part)));
      render();
    } catch (error) { if (token === sequence && !panel.hidden) state.textContent = error.message; }
  }
  const openFolders = () => {
    panel.hidden = false;
    const path = input.value;
    load(path.includes('/') ? path.slice(0, path.lastIndexOf('/')) || '/' : ctx.store.get().server?.workspace);
  };
  const button = h('button', {class: 'button small', type: 'button', 'aria-label': `Browse for ${label}`, onClick: async () => {
    button.disabled = true;
    try {
      const result = await ctx.api.request('/api/input-file', {path: input.value, extensions}, {timeout: 330000});
      if (!input.isConnected) return;
      if (result.status === 'selected') {
        input.value = result.path; input.dispatchEvent(new Event('input', {bubbles: true}));
        input.dispatchEvent(new Event('change', {bubbles: true}));
      } else if (result.status === 'unavailable') openFolders();
    } catch (error) { openFolders(); state.textContent = error.message; }
    finally { button.disabled = false; }
  }}, 'Browse…');
  return h('div', {}, h('div', {class: 'operation-file-tools'}, button,
    h('button', {class: 'button quiet small', type: 'button', 'aria-label': `Browse folders for ${label}`, onClick: openFolders}, 'Browse folders…')), panel);
}
