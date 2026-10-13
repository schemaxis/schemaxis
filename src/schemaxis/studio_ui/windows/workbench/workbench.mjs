// Public factory: workbenchWindow.create(ctx, {document, operation?}, host).
// An operation edits nested input in its parent workflow design using the parent's revision.
import {createComprehension, formattingControls} from './comprehension.mjs';
import {h, icon, mount} from '../../lib/dom.mjs';
import {Store} from '../../lib/store.mjs';
import {createJsonEditor} from '../../editor/editor.mjs';
import {documentChooser} from '../documents.mjs';
import {identity} from '../../shell/providers.mjs';
import {confirmDialog} from '../../shell/dialog.mjs';
import {outline, mapDiagnostics, operationPointer, valueAt} from './model.mjs';
import {createLibrary} from './library.mjs';
import {createProperties} from './properties.mjs';
import {createViewers, VIEWER_LABELS} from './viewers.mjs';
import {createActions} from './actions.mjs';
import {commonProperties, nodeKinds, observationFields} from './guidance.mjs';
import {backgroundValidation, reportDiagnostics} from '../../editor/settle-server.mjs';

function createWorkbench(ctx, params, host) {
  const store = new Store({record: null, provider: null, value: null, schema: null, selected: '', tab: 'input',
    dirty: false, busy: false, references: [], metadata: {templates: [], snippets: [], viewers: []}});
  let disposed = false;
  let loading = 0;
  const title = h('h2', {}, 'Loading input…');
  const subtitle = h('div', {class: 'subtitle'});
  const status = h('span', {class: 'badge'});
  const saveState = h('span', {class: 'wb-help', role: 'status'});
  const diagnosticState = h('span', {class: 'wb-help wb-diagnostic-state', role: 'status'});
  const editorHost = h('div', {class: 'wb-editor-host'});
  const editor = createJsonEditor(editorHost, {value: '', readOnly: true,
    getFunctions: () => ctx.api.get('/api/functions'),
    commonProperties: (pointer, value) => commonProperties(store.get().metadata, value, pointer),
    suggestions: ctx.setting('editor.suggestions') !== false,
    indent: ' '.repeat(ctx.setting('editor.tabSize') || 2), hover: ctx.setting('editor.hover') !== false});
  const tabs = h('div', {class: 'wb-tabs', role: 'tablist', 'aria-label': 'Workbench views'});
  const panels = h('div', {class: 'wb-panels'}, editorHost);
  const outlineList = h('nav', {class: 'wb-outline', 'aria-label': 'Document outline'});
  const conflict = h('div', {class: 'wb-conflict', hidden: true},
    'This document changed elsewhere. Your local edits are preserved. ',
    h('button', {class: 'button small', onClick: async () => {
      if (await confirmDialog('Reload input?', 'Discard this unsaved input and load the latest revision?',
        {confirm: 'Reload'})) {
        load({force: true});
      }
    }}, 'Reload latest'));

  function isDirty() {
    const record = store.get().record;
    if (!record) {
      return false;
    }
    const baseline = params.operation
      ? JSON.stringify(valueAt(record.document, operationPointer(record, params.operation)), null, 2) : record.source;
    return editor.getValue() !== baseline;
  }

  function changed() {
    let value = null;
    try {
      value = editor.getDocument();
    } catch {
      // The editor carries syntax diagnostics; preserve the last useful outline.
    }
    store.set({value, dirty: isDirty()});
    renderOutline();
    renderProperties();
  }

  function showTab(tab) {
    if (store.get().tab === 'input' && tab !== 'input') {
      reportDiagnostics(ctx, editor, {document: params.document, show: () => showTab('input')});
    }
    if (VIEWER_LABELS[tab]) {
      const item = viewers.get(tab);
      if (!item.panel.isConnected) {
        panels.append(item.panel);
      }
    }
    store.set({tab});
    editorTools.hidden = tab !== 'input';
    library.bar.hidden = tab !== 'input';
    if (tab === 'input') library.updateSection();
    else library.section.hidden = true;
    [...panels.children].forEach((panel) => {
      panel.hidden = panel === editorHost ? tab !== 'input'
        : panel === properties.schemaElement ? tab !== 'schema' : panel.dataset.viewerPanel !== tab;
    });
    [...tabs.children].forEach((button) => button.setAttribute('aria-selected', String(button.dataset.tab === tab)));
    viewers.resize();
  }

  function select(pointer) {
    store.set({selected: pointer});
    renderOutline();
    renderProperties();
    if (store.get().tab === 'input') {
      editor.revealPointer(pointer);
      library.updateSection();
    }
  }

  async function getSpatialContext() {
    const {record, dirty} = store.get();
    if (!record || params.operation) throw Error('No standalone native preview is available for this input.');
    const data = await ctx.api.get('/api/geometry', {document: record.id, revision: record.revision});
    if (store.get().record !== record) throw Error('The saved input changed while loading geometry.');
    return {data, label: `Native preview · saved revision ${record.revision}${dirty ? ' · draft has unsaved changes' : ''}`};
  }
  const properties = createProperties({ctx, getSpatialContext, getDocument: () => store.get().value,
    getOperationKinds: () => store.get().metadata.operationKinds,
    onFillRequired: (pointer) => {
      showTab('input');
      editor.fillRequired(pointer);
      changed();
    },
    onEdit: (pointer, value) => {
      editor.insertAtPointer(pointer, value);
      changed();
      if (pointer.endsWith('/filter')) editor.offerFollowup(pointer.slice(0, -7) + '/options');
    },
    onReveal: (pointer) => {
      showTab('input');
      editor.revealPointer(pointer);
    }});
  properties.schemaElement.hidden = true;
  panels.append(properties.schemaElement);
  const viewers = createViewers({ctx, store, onTab: showTab,
    onObservation: (value) => editor.setOption('fillObservations', observationFields(value))});
  const library = createLibrary({ctx, editor, getSpatialContext, getDocument: () => store.get().value,
    getSelectedNode: () => valueAt(store.get().value, store.get().selected)?.id,
    showInput: () => showTab('input'), changed});
  const comprehension = createComprehension(editor, (pointer) => { showTab('input'); select(pointer); });
  const actions = createActions({ctx, store, editor, params, load, viewers, showTab});
  const actionButton = (label, name, primary = false) => h('button', {class: ['button', primary && 'primary'],
    dataset: {action: name}, onClick: () => actions[name]()}, label);
  const buttons = h('div', {class: 'actions'}, status,
    h('button', {class: 'button', dataset: {action: 'help'}, onClick: () => {
      const {value, selected, provider} = store.get();
      const pointer = selected.match(/^\/nodes\/\d+/)?.[0];
      const node = pointer ? valueAt(value, pointer) : null;
      ctx.openHelp({provider, operation: node?.filter});
    }}, 'Help'), actionButton('Validate', 'validate'),
    actionButton('Preview', 'preview'), actionButton('Run', 'run'), actionButton('Save', 'save', true));
  const suggestions = h('input', {type: 'checkbox', checked: editor.getOption('suggestions'),
    onChange: (event) => editor.setOption('suggestions', event.target.checked)});
  const sourceFormat = h('select', {'aria-label': 'Source format', onChange: event => {
    if (!editor.convertFormat(event.target.value)) event.target.value = editor.getOption('format') || 'json';
    changed();
  }}, h('option', {value: 'json'}, 'JSON'), h('option', {value: 'yaml'}, 'YAML'));
  sourceFormat.hidden = Boolean(params.operation);
  const editorTools = h('div', {class: 'wb-editor-tools'}, sourceFormat,
    formattingControls(editor),
    h('button', {class: 'button small', onClick: () => actions.run(),
      title: 'Validate and execute the current input in the configured application, then show verified outputs and available 3D geometry.'}, 'Preview with live data'),
    h('button', {class: 'button ghost small', onClick: () => actions.undo()}, 'Undo saved edit'),
    h('button', {class: 'button ghost small', onClick: () => actions.redo()}, 'Redo'),
    h('label', {class: 'wb-check'}, suggestions, 'Suggestions'), saveState, diagnosticState);
  const element = h('div', {class: 'window-body wb-workbench'},
    h('div', {class: 'window-header'}, icon('adaptor'), h('div', {class: 'titles'}, title, subtitle), buttons),
    conflict,
    h('div', {class: 'wb-layout'},
      h('aside', {class: 'wb-left'}, comprehension.element, h('h3', {class: 'wb-section-title'}, 'Document sections'),
        h('p', {class: 'wb-help'}, 'Document settings, scenes, components and workflow operations. Pipeline nodes are above.'),
        outlineList, library.element, viewers.artifacts),
      h('section', {class: 'wb-centre'}, tabs, library.bar, library.section, editorTools, panels),
      h('aside', {class: 'wb-right'}, properties.element, viewers.references)));

  function renderOutline() {
    const {value, selected} = store.get();
    if (!value) {
      return;
    }
    comprehension.select(selected);
    mount(outlineList, outline(value).filter(item => item.group !== 'nodes').map((item) => h('button', {class: 'wb-outline-item',
      'aria-current': item.pointer === selected ? 'true' : undefined, dataset: {pointer: item.pointer},
      onClick: () => select(item.pointer)}, icon(item.pointer ? 'adaptor' : 'file'),
    h('span', {}, h('strong', {}, item.label), h('small', {}, item.detail)))));
  }

  function renderProperties() {
    const {schema, value, selected} = store.get();
    editor.setOption('fillNodeKinds', nodeKinds(store.get().metadata, value));
    properties.update(schema, value, valueAt(value, selected) === undefined ? '' : selected);
  }

  function renderTabs() {
    const kinds = ['input', 'schema', ...store.get().metadata.viewers.filter((kind) => VIEWER_LABELS[kind])];
    mount(tabs, kinds.map((tab) => h('button', {role: 'tab', dataset: {tab},
      'aria-selected': String(tab === store.get().tab), onClick: () => showTab(tab)},
    VIEWER_LABELS[tab] || (tab === 'input' ? 'Input' : 'Schema'))));
  }

  async function load({force = false} = {}) {
    const token = ++loading;
    const record = await ctx.call(() => ctx.api.get('/api/document', {id: params.document}),
      {title: 'Could not load adaptor input'});
    if (!record || disposed || token !== loading) {
      return;
    }
    if (isDirty() && !force) {
      conflict.hidden = record.revision === store.get().record?.revision;
      return;
    }
    let pointer;
    try {
      pointer = operationPointer(record, params.operation);
    } catch (error) {
      ctx.notify.error(error, {title: 'Operation unavailable'});
      return;
    }
    const value = valueAt(record.document, pointer);
    const provider = pointer ? ctx.store.get().adaptors.find((item) => item.routes.includes(value?.version))?.id
      : record.provider;
    const source = pointer ? JSON.stringify(value, null, 2) : record.source;
    const providerChanged = provider !== store.get().provider;
    const native = record.revision === store.get().record?.revision ? store.get().native : null;
    store.set({record, provider, value, dirty: false, native});
    editor.setFormat(pointer ? "json" : record.sourceFormat || "json");
    sourceFormat.value = editor.getOption("format");
    editor.setValue(source);
    comprehension.refresh();
    editor.setDiagnostics(pointer ? [] : mapDiagnostics(record.diagnostics, value));
    conflict.hidden = true;
    title.textContent = params.operation || record.name;
    subtitle.textContent = `${identity(provider).name} · ${value?.version || 'JSON'}`
      + (params.operation ? ` · in ${record.name}` : ' · all operations');
    host.setTitle(params.operation || record.name, identity(provider).name);
    if (providerChanged || !store.get().schema || store.get().schemaVersion !== value?.version) {
      const results = await Promise.all([
        ctx.call(() => ctx.api.get('/api/studio/adaptor', {id: provider, version: value?.version}), {title: 'Could not load adaptor library'}),
        ctx.call(() => ctx.api.get('/api/schema', {version: value?.version}), {title: 'Could not load adaptor schema'}),
      ]);
      if (disposed || token !== loading) {
        return;
      }
      const [metadata, schema] = results;
      store.set({metadata: metadata || {templates: [], snippets: [], viewers: []},
        schema, schemaVersion: value?.version});
      editor.setSchema(schema);
      library.update(store.get().metadata);
      if (element.closest('.window')?.hidden !== true) library.registerCommands(ctx.commands);
      renderTabs();
    }
    renderOutline();
    renderProperties();
    if (params.fill) {
      delete params.fill;
      editor.startFill();
    }
  }

  const unsubscribeStore = store.subscribe((state) => {
    saveState.textContent = state.busy ? 'Working…' : state.dirty ? 'Unsaved changes'
      : `Revision ${state.record?.revision ?? '…'}`;
    const configured = ctx.store.get().server?.configured?.includes(state.provider);
    status.textContent = state.native === 'live' ? 'Live' : configured ? 'Configured' : 'Native unavailable';
    status.className = configured ? 'badge ok' : 'badge';
    editor.setReadOnly(state.busy || !state.record);
    buttons.querySelectorAll('button').forEach((button) => {
      button.disabled = state.busy || !state.record;
    });
  });
  const unsubscribeSettings = ctx.store.watch((state) => state.settings, () => {
    editor.setOption('suggestions', ctx.setting('editor.suggestions') !== false);
    editor.setOption('hover', ctx.setting('editor.hover') !== false);
    editor.setOption('indent', ' '.repeat(ctx.setting('editor.tabSize') || 2));
    suggestions.checked = editor.getOption('suggestions');
  });
  const unsubscribeChange = editor.onChange(changed);
  const unsubscribeSettled = editor.onSettledState((state) => {
    const describe = (item) => `${item.message} (${item.pointer || '$'} · line ${item.line || 1}, column ${item.column || 1})`;
    diagnosticState.textContent = state.editing ? 'Editing…'
      : `${state.diagnostics.length} diagnostic${state.diagnostics.length === 1 ? '' : 's'}${state.diagnostics[0] ? ' · ' + describe(state.diagnostics[0]) : ''}`;
    diagnosticState.title = state.diagnostics.map(describe).join('\n');
  });
  const stopValidation = backgroundValidation(editor, async (source) => {
    const provider = store.get().provider;
    if (!provider || store.get().busy) return null;
    const result = await ctx.api.post('/api/validate', {provider, source, format: editor.getOption('format') || 'json'});
    return mapDiagnostics(result.diagnostics, store.get().value);
  });
  const unsubscribeRemote = ctx.bus.on('document-changed', (record) => {
    if (record.id === params.document) {
      load();
    }
  });
  const unsubscribeReveal = ctx.bus.on('reveal-location', (detail) => {
    if (detail.document === params.document) {
      showTab('input');
      editor.revealPointer(detail.pointer || detail.location || '');
    }
  });
  element.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      actions.save();
    }
  });
  load();
  return {element, editor, store,
    isDirty,
    onShow: () => {
      store.set({});
      library.registerCommands(ctx.commands);
      viewers.resize();
    },
    onHide: () => {
      library.registerCommands(null);
      reportDiagnostics(ctx, editor, {document: params.document, show: () => showTab('input')});
    },
    canClose: () => !isDirty() || confirmDialog('Discard unsaved input?',
      'This input has changes that have not been saved.', {confirm: 'Discard'}),
    dispose() {
      disposed = true;
      store.set({disposed: true});
      unsubscribeStore();
      unsubscribeChange();
      unsubscribeSettled();
      stopValidation();
      unsubscribeSettings();
      unsubscribeRemote();
      unsubscribeReveal();
      comprehension.dispose();
      viewers.destroy();
      library.destroy();
      editor.destroy();
    }};
}

export const workbenchWindow = {
  type: 'workbench',
  title: 'Adaptor Workbench',
  icon: 'adaptor',
  roles: ['admin', 'dev'],
  create(ctx, params, host) {
    if (!params.document) {
      const chooser = documentChooser(ctx, {
        title: 'Adaptor Workbench',
        description: 'Open an adaptor instance, or create one from an adaptor and an optional starter template.',
        providers: (provider) => !['workflow', 'workflow-design'].includes(provider),
        createLabel: 'New adaptor instance', onCreate: () => ctx.bus.emit('new-instance'), emptyIcon: 'adaptor',
      });
      return {element: h('div', {class: 'window-body'}, chooser.element), dispose: chooser.dispose};
    }
    return createWorkbench(ctx, params, host);
  },
};
