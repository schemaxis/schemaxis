// V2 snippet library, shared by Workbench and Schema Editor. All insertions use
// one preview transaction and durable fill markers, including migrated v1 items.
import {h, icon, mount} from '../../lib/dom.mjs';
import {libraryRequest} from '../../editor/insert-fields.mjs';
import {openLibraryPopover} from './library-popover.mjs';
import {configureOperation} from './operation-form.mjs';

function readPreferences() {
  try {
    const value = JSON.parse(localStorage.getItem('schemaxis.studio.library') || '{}');
    return {recent: Array.isArray(value.recent) ? value.recent : [],
      favourites: Array.isArray(value.favourites) ? value.favourites : []};
  } catch {
    return {recent: [], favourites: []};
  }
}

export function createLibrary({ctx, editor, getDocument, getSpatialContext, getSelectedNode = () => null, showInput = () => {}, changed = () => {}}) {
  const element = h('div', {class: 'wb-library'});
  const bar = h('div', {class: 'library-bar', role: 'toolbar', 'aria-label': 'Snippet categories'});
  const section = h('div', {class: 'library-section', hidden: true});
  const hint = h('p', {class: 'wb-help library-summary'}, 'Focus or hover a snippet to preview its changes.');
  let metadata = {templates: [], snippets: [], categories: []};
  let preferences = readPreferences();
  let popover = null;
  let commands = null;
  let unregister = [];
  const key = (item) => `${metadata.id || 'library'}:${item.id}`;
  const savePreferences = () => {
    try {
      localStorage.setItem('schemaxis.studio.library', JSON.stringify(preferences));
    } catch {
      // Private browsing may disable persistence; this window still remembers.
    }
  };
  const ordered = (items) => [...items].sort((a, b) => {
    const rank = (item) => (preferences.favourites.includes(key(item)) ? 1000 : 0)
      + Math.max(0, 100 - preferences.recent.indexOf(key(item))) * Number(preferences.recent.includes(key(item)));
    return rank(b) - rank(a);
  });

  function preview(item) {
    showInput();
    try {
      const request = libraryRequest(item, getDocument());
      const result = editor.preview(request);
      if (!result) {
        throw new Error('Complete the JSON syntax before inserting a snippet.');
      }
      const entries = result.summaries || [];
      const additions = entries.map((entry) => `${entry.count} at ${entry.pointer || 'document'}`);
      const conflicts = result.conflicts || [];
      const message = (item.document ? 'Replaces this input. ' : '')
        + (additions.length > 1 ? `Adds ${additions.join('; ')}. ` : 'Preview only. ')
        + (conflicts.length ? `Replaces ${conflicts.map((entry) => entry.pointer).join(', ')}. ` : '')
        + 'Enter to insert; undo restores the previous input.';
      hint.textContent = message;
      return {result, request, message};
    } catch (error) {
      editor.clearPreview();
      hint.textContent = error.message;
      return {message: error.message};
    }
  }

  async function insert(item, done) {
    await ctx.call(async () => {
      const {result, request} = preview(item);
      if (!result || !editor.commitPreview()) {
        throw new Error('Complete the JSON syntax before inserting a snippet.');
      }
      preferences.recent = [key(item), ...preferences.recent.filter((value) => value !== key(item))].slice(0, 30);
      savePreferences();
      changed();
      done?.();
      editor.startFill?.({pointers: result.pointers, fields: request.fields});
    }, {title: 'Could not insert the library item'});
  }

  function card(item, {inserted, previewed} = {}) {
    const favourite = preferences.favourites.includes(key(item));
    const focusPreview = () => {
      const result = preview(item);
      previewed?.(result.message);
    };
    const fields = Object.values(item.fields || {}).filter(field => field.type !== 'id').map((field) => field.label).join(', ');
    return h('div', {class: 'library-card-row', role: 'listitem'},
      h('button', {class: 'wb-library-card', type: 'button', dataset: {library: item.id},
        onMouseenter: focusPreview, onFocus: focusPreview,
        onMouseleave: () => editor.clearPreview(), onBlur: () => editor.clearPreview(),
        onClick: () => insert(item, inserted), onKeydown: (event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            insert(item, inserted);
          }
        }},
      h('span', {class: 'library-card-title'}, icon(item.icon || 'file-code'), h('strong', {}, item.title),
        item.complexity === 'composite' ? h('span', {class: 'badge'}, 'composite') : null),
      h('span', {class: 'library-card-description'}, item.description || 'Insert into the current document'),
      fields ? h('span', {class: 'library-card-fields'}, `Fill: ${fields}`) : null,
      item.requires ? h('span', {class: 'library-card-fields'}, `Requires: ${item.requires}`) : null),
      h('button', {class: 'library-favourite', type: 'button',
        'aria-label': `${favourite ? 'Remove favourite' : 'Favourite'}: ${item.title}`,
        'aria-pressed': String(favourite), onClick: (event) => {
          const id = key(item);
          preferences.favourites = preferences.favourites.includes(id)
            ? preferences.favourites.filter((value) => value !== id)
            : [...preferences.favourites, id];
          savePreferences();
          const selected = preferences.favourites.includes(id);
          event.currentTarget.setAttribute('aria-pressed', String(selected));
          event.currentTarget.textContent = selected ? '★' : '☆';
        }}, favourite ? '★' : '☆'));
  }

  async function addOperation(item) {
    popover?.close();
    await ctx.call(async () => {
      const configured = await configureOperation(ctx, {...item, requirements: metadata.addCatalogue?.requirements || []}, metadata.addCatalogue.definitions, getDocument, getSpatialContext,
        {selected: getSelectedNode(), operationKinds: metadata.operationKinds});
      if (configured) await insert(configured);
    }, {title: 'Could not add operation'});
  }

  function operationCard(item) {
    return h('div', {class: 'library-card-row', role: 'listitem'}, h('button', {
      class: 'wb-library-card', type: 'button', dataset: {library: item.id},
      onClick: () => addOperation(item),
    }, h('strong', {}, item.title), h('span', {}, item.description),
    h('small', {}, `${item.group}${item.coverage?.qualification ? ' · ' + item.coverage.qualification : ''}`)));
  }

  function addCategory(id, title, items) {
    return h('button', {class: 'button library-category', type: 'button', 'aria-label': title,
      'aria-haspopup': 'dialog', 'aria-expanded': 'false', dataset: {add: id}, onClick: (event) => {
        popover?.close();
        popover = openLibraryPopover({anchor: event.currentTarget, title, items, card: operationCard,
          preview: () => {}, clear: () => editor.clearPreview()});
      }}, title);
  }

  function category(category, items) {
    return h('button', {class: 'button library-category', type: 'button', title: category.title,
      'aria-label': category.title, 'aria-haspopup': 'dialog', 'aria-expanded': 'false',
      dataset: {category: category.id}, onClick: (event) => {
        popover?.close();
        popover = openLibraryPopover({anchor: event.currentTarget, title: category.title,
          items: ordered(items), card, preview, clear: () => editor.clearPreview()});
      }}, icon(category.icon || 'layers'), h('span', {}, category.title));
  }

  function renderCommands() {
    unregister.forEach((remove) => remove());
    unregister = [];
    if (commands) {
      unregister = metadata.snippets.map((item) => commands.register({
        id: `snippet:${metadata.id || 'library'}:${item.id}`, title: `Insert snippet: ${item.title}`,
        group: 'Snippets', icon: item.icon || 'file-code', roles: ['admin', 'dev'], run: () => insert(item),
      }));
    }
  }

  function updateSection() {
    const pointer = editor.getCursor?.().pointer || '';
    const collection = pointer.split('/').find((part) => ['nodes', 'scenes', 'axes', 'operations'].includes(part));
    const items = metadata.snippets.filter((item) => item.inserts?.some((insert) =>
      insert.at.split('/').includes(collection)));
    section.hidden = !collection || !items.length;
    mount(section, h('span', {}, `Start this section: ${collection || ''}`),
      ordered(items).slice(0, 3).map((item) => h('button', {class: 'button quiet', type: 'button',
        onFocus: () => preview(item), onBlur: () => editor.clearPreview(), onClick: () => insert(item)}, item.title)));
  }
  const selectionChanged = () => {
    if (document.activeElement === editor.textarea) {
      updateSection();
    }
  };
  editor.textarea?.addEventListener('keyup', selectionChanged);
  editor.textarea?.addEventListener('click', selectionChanged);
  const api = {element, bar, section, updateSection,
    update(next) {
      metadata = {templates: [], snippets: [], categories: [], ...next};
      popover?.close();
      const categories = metadata.categories.length ? metadata.categories
        : [{id: 'general', title: 'Snippets', icon: 'layers'}];
      const operations = metadata.addCatalogue?.items || [];
      const groups = [['inputs', 'Add Input'], ['sources', 'Add Source'], ['filters', 'Add Filter'],
        ['outputs', 'Add Output'], ['presentation', 'Presentation & controls']];
      mount(bar, operations.length ? addCategory('all', 'Add anything…', operations) : null,
        groups.filter(([id]) => operations.some((item) => item.group === id))
          .map(([id, title]) => addCategory(id, title, operations.filter((item) => item.group === id))),
        categories.map((entry) => category(entry, metadata.snippets.filter((item) =>
        item.category === entry.id || (!item.category && entry.id === 'general')))),
      metadata.templates.length ? category({id: 'templates', title: 'Templates', icon: 'file-code'},
        metadata.templates) : null);
      mount(element, h('h3', {class: 'wb-section-title'}, 'Templates & snippets'), hint,
        metadata.templates.length ? h('h4', {}, 'Starter templates') : null,
        metadata.templates.map((item) => card(item)),
        metadata.snippets.length ? h('h4', {}, 'Snippets') : null,
        ordered(metadata.snippets).slice(0, 5).map((item) => card(item)),
        metadata.snippets.length > 5 ? h('p', {class: 'wb-help'},
          `${metadata.snippets.length} snippets · browse the categories above the editor or press Ctrl+K.`) : null,
        !metadata.templates.length && !metadata.snippets.length
          ? h('p', {class: 'wb-help'}, 'This adaptor has no packaged library yet.') : null);
      renderCommands();
      updateSection();
    },
    registerCommands(next) {
      commands = next;
      renderCommands();
      return () => { unregister.forEach((remove) => remove()); unregister = []; };
    },
    destroy() {
      editor.textarea?.removeEventListener('keyup', selectionChanged);
      editor.textarea?.removeEventListener('click', selectionChanged);
      popover?.close();
      unregister.forEach((remove) => remove());
      editor.clearPreview();
    },
  };
  return api;
}
