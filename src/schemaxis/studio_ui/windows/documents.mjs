// Copyright (C) 2026 David L F Gaden
// Creating documents: new workflow designs and new adaptor instances.

import {h, icon, mount} from '../lib/dom.mjs';
import {openDialog} from '../shell/dialog.mjs';
import {avatar, identity} from '../shell/providers.mjs';
import {expandFields, markers} from '../editor/insert-fields.mjs';
import {templateGallery} from './template-gallery.mjs';
import {searchAdaptors} from '../lib/search.mjs';

const NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_-]*$/;

export function installDocumentActions(ctx) {
  ctx.bus.on('new-design', () => newDesign(ctx));
  ctx.bus.on('new-instance', (detail) => newInstance(ctx, detail || {}));
  ctx.bus.on('open-operation', (detail) => ctx.windows.open('workbench', detail));
}

async function create(ctx, request, {fill = false} = {}) {
  const result = await ctx.call(() => ctx.api.post('/api/documents', {action: 'new', ...request}),
    {title: 'Could not create the document'});
  if (result) {
    await ctx.refresh();
    if (fill) await ctx.windows.open('workbench', {document: result.id, fill: true});
    else ctx.openDocument(result.id);
  }
  return result;
}

export async function newDesign(ctx) {
  const name = h('input', {class: 'input', name: 'name', value: 'New workflow', required: true});
  const value = await openDialog({
    title: 'New workflow design',
    content: h('div', {class: 'field'}, h('label', {}, 'Design name'), name,
      h('div', {class: 'hint'}, 'A design holds adaptor instances, their ports and connections, and the template '
        + 'parameters you expose to users.')),
    actions: [
      {label: 'Cancel', run: () => null},
      {label: 'Create design', primary: true, run: () => name.value.trim() || false},
    ],
  });
  if (value) {
    await create(ctx, {name: value, provider: 'workflow-design'});
  }
}

/** Choose an adaptor, name the instance, optionally start from a template. */
export async function newInstance(ctx, {provider: preset} = {}) {
  const adaptors = ctx.store.get().adaptors.filter((item) => !item.hostOnly);
  let selected = preset || null;
  const search = h('input', {class: 'input', placeholder: 'Search by name, purpose or operation…',
    'aria-label': 'Search adaptors'});
  const list = h('ul', {class: 'list', role: 'listbox', style: {maxHeight: '260px', overflow: 'auto'}});
  const instance = h('input', {class: 'input', placeholder: 'e.g. geometry, mesher, slices'});
  const instanceError = h('div', {class: 'error-text'});
  const templates = h('select', {class: 'select'});
  const gallery = templateGallery(templates);
  const templateField = h('div', {class: 'field'}, h('label', {}, 'Start from'), templates);

  const renderTemplates = () => {
    const adaptor = adaptors.find((item) => item.id === selected);
    const options = [h('option', {value: ''}, 'Empty document')];
    for (const template of adaptor ? adaptor.templates : []) {
      options.push(h('option', {value: template.id}, template.title));
    }
    mount(templates, options);
    gallery.update(adaptor?.templates || []);
  };
  const renderList = () => {
    const query = search.value.trim().toLowerCase();
    const matches = searchAdaptors(adaptors, query, (item) => identity(item.id).name);
    mount(list, matches.map((item) => h('li', {
      class: 'list-item', role: 'option', 'aria-selected': String(item.id === selected),
      onClick: () => {
        selected = item.id;
        if (!instance.value) {
          instance.value = item.id;
        }
        renderList();
        renderTemplates();
      },
    }, avatar(item.id), h('div', {class: 'grow'},
      h('div', {class: 'title'}, identity(item.id).name),
      h('div', {class: 'subtitle'}, item.scope || item.version)),
    h('span', {class: 'badge'}, `${item.operations.length} operations`))));
    if (!matches.length) {
      list.append(h('li', {class: 'empty-state'}, 'No adaptor matches this search.'));
    }
  };
  search.addEventListener('input', renderList);
  renderList();
  renderTemplates();

  const result = await openDialog({
    title: 'New adaptor instance',
    wide: true,
    content: h('div', {class: 'new-instance-content', style: {display: 'grid', gap: 'var(--sp-4)'}},
      h('div', {class: 'field'}, h('label', {}, 'Adaptor'), search, list),
      h('div', {style: {display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 'var(--sp-3)'}},
        h('div', {class: 'field'}, h('label', {}, 'Instance name'), instance,
          h('div', {class: 'hint'}, 'Letters, digits, - and _. Used as the operation ID in workflows.'),
          instanceError),
        templateField), gallery.element),
    actions: [
      {label: 'Cancel', run: () => null},
      {label: 'Create instance', primary: true, run: () => {
        if (!selected) {
          instanceError.textContent = 'Choose an adaptor first.';
          return false;
        }
        if (!NAME_PATTERN.test(instance.value)) {
          instanceError.textContent = 'Start with a letter; use letters, digits, - or _.';
          return false;
        }
        return {provider: selected, name: instance.value, template: templates.value};
      }},
    ],
  });
  if (!result) {
    return;
  }
  let documentValue;
  if (result.template) {
    const studio = await ctx.call(() => ctx.api.get('/api/studio/adaptor', {id: result.provider}));
    const template = studio && studio.templates.find((item) => item.id === result.template);
    documentValue = template ? expandFields(template.document, template.fields || {}) : undefined;
  }
  const fill = markers(documentValue).length > 0;
  await create(ctx, {name: result.name, provider: result.provider,
    ...(fill ? {source: JSON.stringify(documentValue, null, 2)} : {document: documentValue})}, {fill});
}

/** A list of existing documents of some kinds, with a create button. Used by chooser views. */
export function documentChooser(ctx, {title, description, providers, createLabel, onCreate, emptyIcon}) {
  const list = h('ul', {class: 'list'});
  const render = () => {
    const server = ctx.store.get().server;
    const records = server ? server.documents.filter((item) => providers(item.provider)) : [];
    mount(list, records.length ? records.map((record) => h('li', {
      class: 'list-item', role: 'button', tabindex: '0',
      onClick: () => ctx.openDocument(record.id),
      onKeydown: (event) => {
        if (event.key === 'Enter') {
          ctx.openDocument(record.id);
        }
      },
    }, avatar(record.provider), h('div', {class: 'grow'},
      h('div', {class: 'title'}, record.name),
      h('div', {class: 'subtitle'}, `${identity(record.provider).name} · revision ${record.revision}`)),
    record.valid ? null : h('span', {class: 'badge error'}, 'Invalid draft'),
    icon('chevron-right'))) : h('li', {class: 'empty-state'}, icon(emptyIcon || 'file'), 'Nothing here yet.'));
  };
  const unsubscribe = ctx.store.watch((state) => state.server, render);
  render();
  const element = h('div', {class: 'chooser'},
    h('div', {class: 'chooser-header'},
      h('div', {}, h('h2', {}, title), h('p', {class: 'secondary-text'}, description)),
      h('button', {class: 'button primary', onClick: onCreate}, icon('plus'), createLabel)),
    h('div', {class: 'card'}, list));
  return {element, dispose: unsubscribe};
}
