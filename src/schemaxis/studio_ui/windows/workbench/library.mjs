// Copyright (C) 2026 David L. F. Gaden.
// V2 snippet library, shared by Workbench and Schema Editor. All insertions use
// one preview transaction and durable fill markers, including migrated v1 items.
import {h, icon, mount} from '../../lib/dom.mjs';
import {libraryRequest, scopeReplacements, scopeRequest} from '../../editor/insert-fields.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {openLibraryPopover} from './library-popover.mjs';
import {configureOperation} from './operation-form.mjs';
import {assertInsertionCapacity} from './collection-limit.mjs';
import {parse, documentValue} from '../../editor/json-parse.mjs';
import {atPointer, replacing} from '../../editor/fill-data.mjs';
import {GROUPS} from '../variables/model.mjs';
import {createAuthoringGroups} from './authoring-groups.mjs';

const SYNTAX = 'Complete the JSON syntax before inserting a snippet.';
const STALE_REVIEW = 'The input changed while this replacement was open for review. Nothing was replaced; '
  + 'choose the item again to review the current input.';
const EXCERPT_LINES = 40;

function sameContext(a, b) {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

function scopeName(snapshot) {
  return snapshot.base ? `${snapshot.label} at ${snapshot.base}` : snapshot.label;
}

function describe(result, snapshot) {
  const entries = result.summaries || [];
  const replaced = scopeReplacements(entries, snapshot.base);
  const conflicts = result.conflicts || [];
  const overwritten = conflicts.length ? `Replaces ${conflicts.map((entry) => entry.pointer).join(', ')}. ` : '';
  if (!replaced.length) {
    const additions = entries.map((entry) => `${entry.count} at ${entry.pointer || 'document'}`);
    return (additions.length > 1 ? `Adds ${additions.join('; ')}. ` : 'Preview only. ') + overwritten
      + 'Enter to insert; undo restores the previous input.';
  }
  const others = entries.filter((_, index) => !replaced.includes(index)).map((entry) =>
    `${entry.effect === 'merge' ? 'merges' : entry.effect === 'replace' ? 'sets' : 'adds'} ${entry.count} at ${entry.pointer || 'document'}`);
  return `Replaces the entire ${scopeName(snapshot)}. ` + (others.length ? `Then ${others.join('; ')}. ` : '')
    + overwritten + 'Enter to review the replacement; undo restores the previous input.';
}

function versionChange(snapshot, request, replaced) {
  const current = snapshot.value?.version;
  return replaced.map((index) => {
    const incoming = request.inserts[index].values?.[0]?.version;
    if (incoming === current && current !== undefined) return `Keeps document version ${current}.`;
    if (incoming !== undefined && current !== undefined) return `Changes document version from ${current} to ${incoming}.`;
    if (incoming !== undefined) return `Sets document version ${incoming}; the current ${snapshot.label} has none.`;
    if (current !== undefined) return `The replacement has no document version; the current ${snapshot.label} has ${current}.`;
    return `Neither the current ${snapshot.label} nor the replacement has a document version.`;
  });
}

function plannedChange(entry, index, replaced, snapshot) {
  const where = entry.pointer || 'document';
  if (replaced.includes(index)) {
    return entry.pointer === snapshot.base ? `Replace the entire ${snapshot.label}`
      : `Replace ${where}, which contains the entire ${snapshot.label}`;
  }
  if (entry.effect === 'merge') return `Merge ${entry.count} setting${entry.count === 1 ? '' : 's'} into ${where}`;
  if (entry.effect === 'replace') return `Replace the value at ${where}`;
  return `Add ${entry.count} at ${where}`;
}

function changedText(title, text, startLine) {
  const lines = text.split('\n');
  const shown = lines.slice(0, EXCERPT_LINES);
  return h('figure', {class: 'library-replace-excerpt'},
    h('figcaption', {}, `${title}: ${lines.length} line${lines.length === 1 ? '' : 's'} from line ${startLine}`
      + (shown.length < lines.length ? `, first ${shown.length} shown` : '')),
    h('pre', {}, shown.join('\n')));
}

function readPreferences() {
  try {
    const value = JSON.parse(localStorage.getItem('schemaxis.studio.library') || '{}');
    return {recent: Array.isArray(value.recent) ? value.recent : [],
      favourites: Array.isArray(value.favourites) ? value.favourites : [], tray: value.tray === true};
  } catch {
    return {recent: [], favourites: [], tray: false};
  }
}

/**
 * `scope()` returns the editor scope a library request applies to:
 * {base, value, root?, label, context}. `context` is an array compared element by element
 * with ===; a changed owner, scope or schema refuses an approved replacement.
 */
export function createLibrary({ctx, editor, getDocument, getSpatialContext, getSelectedNode = () => null, showInput = () => {}, changed = () => {},
  caseNames = null, authoringScope = null, scope = null}) {
  const authoringGroups = createAuthoringGroups(authoringScope);
  const element = h('div', {class: 'wb-library'});
  const bar = h('div', {class: 'library-bar', role: 'toolbar', 'aria-label': 'Snippet categories'});
  const section = h('div', {class: 'library-section', hidden: true});
  const hint = h('p', {class: 'wb-help library-summary'}, 'Focus or hover a snippet to preview its changes.');
  let metadata = {templates: [], snippets: [], categories: []};
  let preferences = readPreferences();
  let popover = null;
  let commands = null;
  let unregister = [];
  let generation = 0;
  let pending = null;
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

  const currentScope = () => (scope ? scope() : {base: '', value: getDocument(), label: 'input', context: []});
  const scopedRequest = (item, snapshot) => scopeRequest(libraryRequest(item, snapshot.value), snapshot);

  function preview(item) {
    try {
      const snapshot = currentScope();
      const request = scopedRequest(item, snapshot);
      const result = editor.preview(request);
      if (!result) {
        throw new Error(SYNTAX);
      }
      const message = describe(result, snapshot);
      hint.textContent = message;
      return {result, request, message};
    } catch (error) {
      editor.clearPreview();
      hint.textContent = error.message;
      return {message: error.message};
    }
  }

  /** Freeze one scoped request and its planned edit before any decision is awaited. */
  function prepare(item) {
    const snapshot = currentScope();
    const request = scopedRequest(item, snapshot);
    const token = editor.prepareInsert(request);
    if (!token) throw new Error(SYNTAX);
    return Object.freeze({item, generation, snapshot, request, token,
      replaced: scopeReplacements(token.summaries, snapshot.base)});
  }

  /** Close any open replacement review; its decision can no longer commit. */
  function cancelReview() {
    generation += 1;
    const open = pending;
    pending = null;
    open?.close(null);
  }

  function stillCurrent(intent) {
    try {
      const now = currentScope();
      return now.base === intent.snapshot.base && sameContext(now.context, intent.snapshot.context);
    } catch {
      return false;
    }
  }

  async function review(intent) {
    const {item, snapshot, request, token, replaced} = intent;
    const label = snapshot.label;
    const startLine = token.source.slice(0, token.from).split('\n').length;
    const fields = Object.values(token.fields).filter((field) => field.type !== 'id').map((field) => field.label);
    const body = h('div', {class: 'library-replace-body'},
      h('p', {}, `“${item.title}” replaces the entire ${scopeName(snapshot)}. Nothing changes until you choose `
        + `Replace ${label}; Undo then restores the previous input in one step.`),
      versionChange(snapshot, request, replaced).map((text) => h('p', {class: 'library-replace-version'}, text)),
      h('p', {}, 'Planned changes, in order:'),
      h('ol', {class: 'library-replace-list'},
        token.summaries.map((entry, index) => h('li', {}, plannedChange(entry, index, replaced, snapshot))),
        token.conflicts.map((entry) => h('li', {}, `Overwrites ${entry.pointer}`))),
      fields.length ? h('p', {}, `Afterwards, fill: ${fields.join(', ')}.`) : null,
      changedText('Changed text now', token.source.slice(token.from, token.to), startLine),
      changedText('Changed text after replacement', token.text, startLine));
    const handle = {};
    pending = handle;
    const value = await openDialog({title: `Replace ${label}?`, className: 'library-replace-review', wide: true,
      initialFocus: '.dialog-footer button', content: (close) => {
        handle.close = close;
        return body;
      },
      actions: [{label: 'Cancel', value: null, run: () => null}, {label: `Replace ${label}`, danger: true, value: true}]});
    if (pending === handle) pending = null;
    return value === true;
  }

  async function insert(item, done) {
    await ctx.call(async () => {
      cancelReview();
      assertInsertionCapacity(item, getDocument());
      showInput();
      const intent = prepare(item);
      if (intent.replaced.length) {
        editor.clearPreview({restore: false});
        if (!await review(intent)) return;
      }
      const committed = intent.generation === generation
        && editor.commitPrepared(intent.token, () => stillCurrent(intent));
      if (!committed) {
        throw new Error(intent.replaced.length ? STALE_REVIEW : SYNTAX);
      }
      preferences.recent = [key(item), ...preferences.recent.filter((value) => value !== key(item))].slice(0, 30);
      savePreferences();
      changed();
      if (item.authoringGroup) authoringGroups.remember(item.authoringGroup);
      done?.();
      editor.startFill?.({pointers: [...intent.token.pointers], fields: structuredClone(intent.token.fields)});
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
      const variableSnapshot = await editor.getOption?.('variablesContext')?.();
      const configured = await configureOperation(ctx, {...item, requirements: metadata.addCatalogue?.requirements || []}, metadata.addCatalogue.definitions, getDocument, getSpatialContext,
        {selected: getSelectedNode(), operationKinds: metadata.operationKinds, variableSnapshot, caseData: caseNames,
          validationScope: currentScope()});
      if (!configured) return;
      if (configured.variableRoot && variableSnapshot) {
        assertInsertionCapacity(configured, getDocument());
        const {result, request} = preview(configured);
        if (!result) throw Error('Complete the input syntax before adding the operation.');
        const source = editor.getValue();
        const candidate = parse(source.slice(0, result.from) + result.text + source.slice(result.to), editor.getOption('format') || 'json');
        editor.clearPreview();
        if (candidate.diagnostics.length) throw Error('The operation could not be added to this input.');
        const local = documentValue(candidate), base = variableSnapshot.base || '';
        const staged = atPointer(configured.variableRoot, base);
        for (const key of [...GROUPS, 'sweeps']) if (!Object.hasOwn(staged, key)) delete local[key];
        await variableSnapshot.commit(replacing(configured.variableRoot, base, local));
        preferences.recent = [key(item), ...preferences.recent.filter(value => value !== key(item))].slice(0, 30);
        savePreferences();
        editor.startFill?.({pointers: result.pointers, fields: request.fields});
        if (configured.authoringGroup) authoringGroups.remember(configured.authoringGroup);
      } else await insert(configured);
    }, {title: 'Could not add operation'});
  }

  function settingsAt(selected) {
    if (!selected) return null;
    const document = getDocument();
    const entries = metadata.addCatalogue?.items || [];
    const nodePath = selected.match(/^(\/nodes\/\d+)(?:\/|$)/)?.[1];
    if (nodePath) {
      const value = atPointer(document, nodePath);
      const item = entries.find(entry => entry.at === '/nodes/-' && entry.operation === value?.filter);
      if (item) return {item, pointer: nodePath, value};
    }
    for (const item of entries) {
      if (!item.id.startsWith('document:') || !item.at || item.at.includes('{')) continue;
      let pointer = item.at;
      if (pointer.endsWith('/-')) {
        const parent = pointer.slice(0, -2);
        if (!selected.startsWith(parent + '/')) continue;
        const index = selected.slice(parent.length + 1).split('/')[0];
        if (!/^\d+$/.test(index)) continue;
        pointer = parent + '/' + index;
      }
      if (selected !== pointer && !selected.startsWith(pointer + '/')) continue;
      const value = atPointer(document, pointer);
      if (value && typeof value === 'object') return {item, pointer, value};
    }
    return null;
  }

  function hasSettings(pointer) {
    try { return Boolean(settingsAt(pointer)); }
    catch { return false; }
  }

  /** Reopen the owning settings window and write its changes back as one edit. */
  async function editOperation(selected) {
    await ctx.call(async () => {
      const target = settingsAt(selected);
      if (!target) throw Error('This item has no settings window. Edit it in the text.');
      const {item, pointer, value: node} = target;
      const group = item.authoring?.multiMode
        ? authoringGroups.find(getDocument(), node.id, item.operation || item.id, item.at.slice(0, -2)) : null;
      const variableSnapshot = await editor.getOption?.('variablesContext')?.();
      const configured = await configureOperation(ctx, {...item, requirements: metadata.addCatalogue?.requirements || []},
        metadata.addCatalogue.definitions, getDocument, getSpatialContext,
        {operationKinds: metadata.operationKinds, variableSnapshot, existing: {pointer, value: node}, caseData: caseNames,
          validationScope: currentScope(),
          ...(group ? {existingGroup: group.existing, groupStartingValue: group.startingValue} : {})});
      if (!configured) return;
      showInput();
      if (configured.variableRoot && variableSnapshot) {
        const base = variableSnapshot.base || '';
        const local = replacing(atPointer(configured.variableRoot, base), configured.replace.pointer, configured.replace.value);
        await variableSnapshot.commit(replacing(configured.variableRoot, base, local));
      } else {
        let next = replacing(getDocument(), configured.replace.pointer, configured.replace.value);
        for (const addition of configured.inserts) next = replacing(next, addition.at, addition.values[0]);
        editor.replaceDocument(next);
        changed();
      }
      if (configured.authoringGroup) authoringGroups.remember({...configured.authoringGroup,
        // Keep deleted members in the provenance so Undo can restore their membership.
        members: [...new Set([...(group?.members || []), ...configured.authoringGroup.members])]});
      editor.revealPointer(pointer);
      if (Object.keys(configured.fields).length) editor.startFill?.({fields: configured.fields});
    }, {title: 'Could not edit the operation'});
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
        const tray = event.currentTarget.closest('.library-tray');
        if (tray?.hidden) tray.previousElementSibling.querySelector('.library-more')?.click();
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
    const collection = pointer.split('/').find((part) => ['nodes', 'scenes', 'sweeps', 'operations'].includes(part));
    const items = metadata.snippets.filter((item) => item.inserts?.some((insert) =>
      insert.at.split('/').includes(collection)));
    section.hidden = !collection || !items.length;
    mount(section, h('span', {}, `Start this section: ${collection || ''}`),
      ordered(items).slice(0, 3).map((item) => h('button', {class: 'button quiet', type: 'button',
        title: item.description || 'Click to insert; Ctrl+Z undoes the insertion.',
        onMouseenter: () => preview(item), onMouseleave: () => editor.clearPreview(),
        onFocus: () => preview(item), onBlur: () => editor.clearPreview(), onClick: () => insert(item)}, item.title)));
  }
  const selectionChanged = () => {
    if (document.activeElement === editor.textarea) {
      updateSection();
    }
  };
  editor.textarea?.addEventListener('keyup', selectionChanged);
  editor.textarea?.addEventListener('click', selectionChanged);
  const api = {element, bar, section, updateSection, editOperation, hasSettings, cancelReview,
    update(next) {
      metadata = {templates: [], snippets: [], categories: [], ...next};
      cancelReview();
      popover?.close();
      const categories = metadata.categories.length ? metadata.categories
        : [{id: 'general', title: 'Snippets', icon: 'layers'}];
      const operations = metadata.addCatalogue?.items || [];
      const groups = [['inputs', 'Add Input'], ['sources', 'Add Source'], ['filters', 'Add Filter'],
        ['outputs', 'Add Output'], ['presentation', 'Presentation & controls']];
      const tray = h('div', {class: 'library-tray', hidden: !preferences.tray},
        categories.map((entry) => category(entry, metadata.snippets.filter((item) =>
          item.category === entry.id || (!item.category && entry.id === 'general')))),
        metadata.templates.length ? category({id: 'templates', title: 'Templates', icon: 'file-code'},
          metadata.templates) : null);
      const more = h('button', {class: 'button library-more', type: 'button', 'aria-expanded': String(Boolean(preferences.tray)),
        title: 'Show or hide the snippet and template categories', onClick: () => {
          preferences.tray = !preferences.tray;
          savePreferences();
          tray.hidden = !preferences.tray;
          more.setAttribute('aria-expanded', String(preferences.tray));
        }}, icon('layers'), h('span', {}, `Snippets & templates (${metadata.snippets.length + metadata.templates.length})`));
      mount(bar, h('div', {class: 'library-add'},
        operations.length ? addCategory('all', 'Add anything…', operations) : null,
        groups.filter(([id]) => operations.some((item) => item.group === id))
          .map(([id, title]) => addCategory(id, title, operations.filter((item) => item.group === id))),
        tray.childElementCount ? more : null), tray);
      mount(element, h('h3', {class: 'wb-section-title'}, 'Templates & snippets'), hint,
        metadata.templates.length ? h('h4', {}, 'Starter templates') : null,
        metadata.templates.map((item) => card(item)),
        metadata.snippets.length ? h('h4', {}, 'Snippets') : null,
        ordered(metadata.snippets).slice(0, 5).map((item) => card(item)),
        metadata.snippets.length > 5 ? h('p', {class: 'wb-help'},
          `${metadata.snippets.length} snippets · open Snippets & templates above the editor, or press Ctrl+K.`) : null,
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
      cancelReview();
      editor.textarea?.removeEventListener('keyup', selectionChanged);
      editor.textarea?.removeEventListener('click', selectionChanged);
      popover?.close();
      unregister.forEach((remove) => remove());
      editor.clearPreview();
    },
  };
  return api;
}
