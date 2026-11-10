// Copyright (C) 2026 David L F Gaden
// Public factory: workbenchWindow.create(ctx, {document, operation?}, host).
// An operation edits nested input in its parent workflow design using the parent's revision.
import {createComprehension, formattingControls} from './comprehension.mjs';
import {h, icon, mount} from '../../lib/dom.mjs';
import {Store} from '../../lib/store.mjs';
import {createJsonEditor} from '../../editor/editor.mjs';
import {documentChooser} from '../documents.mjs';
import {identity} from '../../shell/providers.mjs';
import {confirmDialog, openMenu} from '../../shell/dialog.mjs';
import {outline, mapDiagnostics, operationPointer, validationRequest, valueAt} from './model.mjs';
import {createLibrary} from './library.mjs';
import {createProperties} from './properties.mjs';
import {createViewers, VIEWER_LABELS} from './viewers.mjs';
import {createActions} from './actions.mjs';
import {commonProperties, nodeKinds, observationFields} from './guidance.mjs';
import {backgroundValidation, reportDiagnostics} from '../../editor/settle-server.mjs';
import {bindVariables} from '../variables/editor.mjs';
import {replacing} from '../../editor/fill-data.mjs';
import {equal} from '../variables/model.mjs';
import {caseNames, createCaseData} from './case-data.mjs';

const PREFERENCES = 'schemaxis.studio.workbench';

function readPreferences() {
  try {
    const value = JSON.parse(localStorage.getItem(PREFERENCES) || '{}');
    return {sidebar: ['all', 'guide', 'library', 'hidden'].includes(value.sidebar) ? value.sidebar : 'all',
      shown: ['all', 'guide', 'library'].includes(value.shown) ? value.shown : 'all', controls: value.controls !== false,
      right: value.right === 'case' ? 'case' : 'properties'};
  } catch {
    return {sidebar: 'all', shown: 'all', controls: true, right: 'properties'};
  }
}

function createWorkbench(ctx, params, host) {
  const store = new Store({record: null, provider: null, value: null, schema: null, selected: '', tab: 'input',
    dirty: false, busy: false, references: [], metadata: {templates: [], snippets: [], viewers: []}});
  let disposed = false;
  let loading = 0;
  let lastInspection;
  const status = h('button', {class: 'badge', type: 'button', 'aria-label': 'Native application setup'});
  const saveState = h('span', {class: 'wb-help', role: 'status'});
  const diagnosticState = h('button', {class: 'button ghost small wb-help wb-diagnostic-state', title: 'Show Problems',
    onClick: () => ctx.store.set({panelOpen: true, panelTab: 'problems'})});
  const editorHost = h('div', {class: 'wb-editor-host'});
  const editor = createJsonEditor(editorHost, {value: '', readOnly: true,
    getFunctions: () => ctx.api.get('/api/functions'),
    commonProperties: (pointer, value) => commonProperties(store.get().metadata, value, pointer),
    valueNames: (pointer) => caseNames(store.get().inspection, pointer),
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
    authoringTools.hidden = tab !== 'input' || !preferences.controls;
    controlsToggle.hidden = tab !== 'input';
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
  // Names read from the case, shared by Properties, Case data and the settings windows.
  const nameListeners = new Set();
  const sharedNames = {
    get: () => store.get().inspection || null,
    subscribe: (listener) => { nameListeners.add(listener); return () => nameListeners.delete(listener); },
    load: async (live) => {
      const result = await actions.inspect(live);
      if (!result) throw Error('No names could be read. Add an OpenFOAM reader with its case file first; details are in Problems.');
      return result;
    }};
  const properties = createProperties({ctx, getSpatialContext, getDocument: () => store.get().value,
    caseNames: sharedNames, onEditSettings: (pointer) => library.editOperation(pointer),
    hasSettings: (pointer) => library.hasSettings(pointer),
    onChooseValue: pointer => variables.pick({pointer}),
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
  const library = createLibrary({ctx, editor, getSpatialContext, getDocument: () => editor.getDocument(),
    getSelectedNode: () => valueAt(store.get().value, store.get().selected)?.id,
    showInput: () => showTab('input'), changed, caseNames: sharedNames});
  const comprehension = createComprehension(editor, (pointer) => { showTab('input'); select(pointer); },
    (pointer) => library.editOperation(pointer));
  const actions = createActions({ctx, store, editor, params, load, viewers, showTab});
  const variables = bindVariables(ctx, editor, {changed, snapshot: async () => {
    const {record} = store.get(), version = editor.getTextVersion();
    if (!record) throw Error('Wait for the input to load.');
    const base = operationPointer(record, params.operation);
    const root = base ? replacing(record.document, base, editor.getDocument()) : editor.getDocument();
    return {root, base, label: `${record.name}${base ? ' · shared changes save this operation and its workflow together.' : ' · changes remain in the input draft until saved.'}`,
      commit: async result => {
        if (editor.getTextVersion() !== version || store.get().record !== record) throw Error('The input changed. Reopen Variables & expressions.');
        if (base && !equal(replacing(result, base, valueAt(root, base)), root)) {
          await ctx.api.post('/api/authoring', {action: 'patch', document: record.id, revision: record.revision,
            edits: [{op: 'replace', path: '', value: result}]});
          await load({force: true}); await ctx.refresh();
        } else { editor.replaceDocument(base ? valueAt(result, base) : result); changed(); }
      }};
  }});
  const actionButton = (label, name, primary = false) => h('button', {class: ['button', primary && 'primary'],
    dataset: {action: name}, title: ({validate: 'Check the current draft with the host planner; no native application runs.',
      preview: 'Create a planning checkpoint for the complete draft.', run: 'Execute the complete input in the configured application and verify outputs.',
      save: 'Save the draft and write its input file.'})[name], onClick: () => actions[name]()}, label);
  const liveData = h('button', {class: 'button', dataset: {action: 'live'}, hidden: true,
    title: 'Load the selected node and everything upstream of it in the application. Unfinished downstream nodes are ignored.',
    onClick: () => actions.inspect(true)}, 'Live data');
  const buttons = h('div', {class: 'wb-toolbar actions', role: 'toolbar', 'aria-label': 'Adaptor actions'}, status,
    h('button', {class: 'button', dataset: {action: 'help'}, onClick: () => {
      const {value, selected, provider} = store.get();
      const pointer = selected.match(/^\/nodes\/\d+/)?.[0];
      const node = pointer ? valueAt(value, pointer) : null;
      ctx.openHelp({provider, operation: node?.filter});
    }, title: 'Open the adaptor guide for the selected operation'}, 'Adaptor help'), actionButton('Validate', 'validate'),
    actionButton('Preview', 'preview'), liveData, actionButton('Run', 'run'),
    h('span', {class: 'wb-save-group'}, actionButton('Save', 'save', true),
      h('button', {class: 'button primary', type: 'button', dataset: {action: 'save-menu'}, 'aria-label': 'More file actions',
        'aria-haspopup': 'menu', title: 'Save as, or open another file', onClick: (event) => openMenu(event.currentTarget, [
          {label: 'Save as…', icon: 'file', disabled: Boolean(params.operation), run: () => actions.saveAs()},
          {label: 'Open…', icon: 'folder', run: () => ctx.bus.emit('open-file')},
          {label: 'New adaptor instance…', icon: 'plus', run: () => ctx.bus.emit('new-instance')},
        ])}, '▾')));
  const suggestions = h('input', {type: 'checkbox', checked: editor.getOption('suggestions'),
    onChange: (event) => editor.setOption('suggestions', event.target.checked)});
  const sourceFormat = h('select', {'aria-label': 'Source format', onChange: event => {
    if (!editor.convertFormat(event.target.value)) event.target.value = editor.getOption('format') || 'json';
    changed();
  }}, h('option', {value: 'json'}, 'JSON'), h('option', {value: 'yaml'}, 'YAML'));
  sourceFormat.hidden = Boolean(params.operation);
  const editorTools = h('div', {class: 'wb-editor-tools'}, sourceFormat,
    h('button', {class: 'button small', dataset: {action: 'edit-settings'},
      title: 'Reopen the settings window for the pipeline item at the cursor',
      onClick: () => {
        const pointer = store.get().selected.match(/^(.*\/nodes\/\d+)(?:\/|$)/)?.[1];
        if (pointer) library.editOperation(pointer);
        else ctx.notify.info('Select a pipeline item first', {body: 'Put the cursor inside a node, or click it in the pipeline guide, then choose Edit settings.'});
      }}, 'Edit settings…'),
    h('button', {class: 'button small', onClick: () => variables.pick()}, 'Value at cursor…'),
    formattingControls(editor),
    h('button', {class: 'button small', onClick: () => editor.undo(), title: 'Undo draft edit (Ctrl+Z)'}, 'Undo'),
    h('button', {class: 'button small', onClick: () => editor.redo(), title: 'Redo draft edit (Ctrl+Shift+Z)'}, 'Redo'),
    h('button', {class: 'button ghost small', onClick: () => actions.undo()}, 'Undo saved edit'),
    h('button', {class: 'button ghost small', onClick: () => actions.redo()}, 'Redo saved edit'),
    h('label', {class: 'wb-check'}, suggestions, 'Suggestions'));
  const authoringTools = h('div', {class: 'wb-authoring-tools'}, library.bar, library.section, editorTools);
  const preferences = readPreferences();
  const remember = () => {
    try {
      localStorage.setItem(PREFERENCES, JSON.stringify(preferences));
    } catch {
      // Layout choices are a convenience; this window still remembers them.
    }
  };
  const controlsToggle = h('button', {class: 'button small wb-controls-toggle', type: 'button', 'aria-pressed': 'true',
    title: 'Show or hide the Add and editing controls above the input',
    onClick: () => { preferences.controls = !preferences.controls; remember(); applyLayout(); }}, 'Controls');
  const sidebarToggle = h('button', {class: 'button ghost small icon-only wb-sidebar-toggle', type: 'button',
    'aria-label': 'Show or hide the sidebar', title: 'Show or hide the sidebar',
    onClick: () => setSidebar(preferences.sidebar === 'hidden' ? preferences.shown : 'hidden')},
  h('span', {class: 'wb-sidebar-icon', 'aria-hidden': 'true'}));
  const sidebarModes = h('div', {class: 'wb-segmented', role: 'radiogroup', 'aria-label': 'Sidebar contents'},
    [['guide', 'Guide', 'The pipeline, following your cursor'], ['library', 'Library', 'Document sections, templates and snippets'],
      ['all', 'Both', 'Guide and library together']].map(([mode, label, hint]) => h('button', {type: 'button', role: 'radio',
      dataset: {sidebar: mode}, title: hint, onClick: () => setSidebar(mode)}, label)));
  const sections = h('div', {class: 'wb-sections'}, h('h3', {class: 'wb-section-title'}, 'Document sections'),
    outlineList, library.element, viewers.artifacts);
  const sidebar = h('aside', {class: 'wb-left'}, h('div', {class: 'wb-sidebar-head'}, sidebarModes,
    h('button', {class: 'button ghost small icon-only', type: 'button', 'aria-label': 'Hide the sidebar', title: 'Hide the sidebar',
      onClick: () => setSidebar('hidden')}, icon('close'))), comprehension.element, sections);
  const caseData = createCaseData({onLoad: () => actions.inspect(false), onUse: useCaseName});
  const rightModes = h('div', {class: 'wb-segmented wb-right-modes', role: 'radiogroup', 'aria-label': 'Right panel contents', hidden: true},
    [['properties', 'Properties'], ['case', 'Case data']].map(([mode, label]) => h('button', {type: 'button', role: 'radio',
      dataset: {right: mode}, onClick: () => { preferences.right = mode; remember(); applyLayout(); }}, label)));
  const viewBar = h('div', {class: 'wb-view-bar'}, sidebarToggle, tabs,
    h('div', {class: 'wb-view-state'}, saveState, diagnosticState), controlsToggle);
  const layout = h('div', {class: 'wb-layout'}, sidebar,
    h('section', {class: 'wb-centre'}, viewBar, authoringTools, panels),
    h('aside', {class: 'wb-right'}, rightModes, properties.element, caseData.element, viewers.references));
  const element = h('div', {class: 'window-body wb-workbench'}, buttons, conflict, layout);

  // The toolbar is drawn in the tab row; the tabs give up exactly its width.
  const reserveToolbar = (shown) => {
    const main = element.closest('.main');
    if (!main) return;
    const inRow = shown && getComputedStyle(buttons).position === 'absolute';
    main.style.setProperty('--window-tools-w', inRow ? `${Math.ceil(buttons.getBoundingClientRect().width)}px` : '0px');
  };
  const toolbarResized = () => reserveToolbar(element.closest('.window')?.hidden === false);
  const toolbarSize = new ResizeObserver(toolbarResized);
  toolbarSize.observe(buttons);
  window.addEventListener('resize', toolbarResized);


  function setSidebar(mode) {
    preferences.sidebar = mode;
    if (mode !== 'hidden') preferences.shown = mode;
    remember();
    applyLayout();
  }

  function applyLayout() {
    const mode = preferences.sidebar;
    sidebar.hidden = mode === 'hidden';
    layout.classList.toggle('wb-no-sidebar', sidebar.hidden);
    comprehension.element.hidden = mode === 'library';
    sections.hidden = mode === 'guide';
    sidebarToggle.setAttribute('aria-pressed', String(!sidebar.hidden));
    [...sidebarModes.children].forEach((button) => button.setAttribute('aria-checked', String(button.dataset.sidebar === mode)));
    const showCase = preferences.right === 'case' && !rightModes.hidden;
    [...rightModes.children].forEach((button) => button.setAttribute('aria-checked', String((button.dataset.right === 'case') === showCase)));
    properties.element.hidden = viewers.references.hidden = showCase;
    caseData.element.hidden = !showCase;
    controlsToggle.setAttribute('aria-pressed', String(preferences.controls));
    authoringTools.hidden = store.get().tab !== 'input' || !preferences.controls;
  }

  function useCaseName(value) {
    showTab('input');
    const documentValue = store.get().value;
    let pointer = editor.getCursor().pointer || '';
    if (!Array.isArray(valueAt(documentValue, pointer))) pointer = pointer.slice(0, pointer.lastIndexOf('/'));
    const target = valueAt(documentValue, pointer);
    if (Array.isArray(target) && target.every((item) => typeof item !== 'object' || item?.pattern)) {
      if (target.includes(value)) return `${JSON.stringify(value)} is already in ${pointer}.`;
      editor.insertAtPointer(`${pointer}/-`, value);
      changed();
      return `Added ${JSON.stringify(value)} to ${pointer}.`;
    }
    const text = editor.getOption('format') === 'yaml' ? String(value) : JSON.stringify(value);
    navigator.clipboard?.writeText(text).catch(() => {});
    return `Copied ${text}. Put the cursor in a list of names to add it directly.`;
  }

  async function loadCaseNames() {
    const state = store.get();
    const operations = state.metadata.inspection?.metadataOperations;
    if (!state.metadata.inspection?.metadata || state.inspection || params.operation) return;
    const node = state.value?.nodes?.find((item) => typeof item?.id === 'string' && typeof item.options?.file === 'string'
      && (!operations || operations.includes(item.filter)));
    if (!node) return;
    const record = state.record;
    try {
      const inspection = await ctx.api.post('/api/peek-input', {provider: state.provider, input: state.value, node: node.id});
      if (!disposed && store.get().record === record && !store.get().inspection && inspection.available) {
        store.set({inspection, dataMode: 'metadata'});
      }
    } catch {
      // Names are a convenience here; Load names reports the reason on request.
    }
  }

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
    host.setTitle(params.operation || record.name, `${identity(provider).name} · ${value?.version || 'JSON'}`
      + (params.operation ? ` · in ${record.name}` : ' · all operations'));
    if (providerChanged || !store.get().schema || store.get().schemaVersion !== value?.version) {
      const results = await Promise.all([
        ctx.call(() => ctx.api.get('/api/studio/adaptor', {id: provider, version: value?.version}), {title: 'Could not load adaptor library'}),
        // A nested operation uses its workflow-scoped schema: artifact and
        // captured-input references are valid there but not in standalone input.
        ctx.call(() => ctx.api.get('/api/schema', {version: value?.version, scope: params.operation ? 'workflow' : undefined}),
          {title: 'Could not load adaptor schema'}),
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
    loadCaseNames();
    if (params.fill) {
      delete params.fill;
      editor.startFill();
    }
  }

  const unsubscribeStore = store.subscribe((state) => {
    const file = state.record?.file;
    saveState.textContent = (state.busy ? 'Working…' : state.dirty ? 'Unsaved changes'
      : `Revision ${state.record?.revision ?? '…'}`) + (params.operation ? '' : file ? ` · ${file.split('/').at(-1)}` : ' · not saved to a file');
    saveState.title = params.operation ? '' : file ? `Saved to ${file}` : 'Save writes this input to a file you choose.';
    const configured = ctx.store.get().server?.configured?.includes(state.provider);
    status.textContent = state.native === 'live' ? 'Live' : configured ? 'Configured' : 'Native unavailable';
    status.className = configured ? 'badge ok' : 'badge';
    status.title = configured ? 'The native application is configured. Host editing and validation are always available.'
      : 'The native application has no usable configured location. Open Application Setup to enable live inspection and execution.';
    status.onclick = () => ctx.role() === 'admin' ? ctx.windows.open('setup')
      : ctx.notify.info('Native application setup', {body: 'Select Admin in the title bar, then open Application Setup to choose the native executable. Editing, metadata preview and host validation remain available.'});
    liveData.hidden = !state.metadata.inspection?.live;
    liveData.textContent = state.dataMode === 'live' ? 'Refresh live data' : 'Live data';
    const operations = state.metadata.inspection?.metadataOperations;
    const hasCase = Boolean(state.metadata.inspection?.metadata) && !params.operation
      && (!operations || Boolean(state.value?.nodes?.some((node) => operations.includes(node?.filter))));
    caseData.update(state.inspection);
    if (state.inspection !== lastInspection) {
      lastInspection = state.inspection;
      nameListeners.forEach((listener) => listener(lastInspection || null));
    }
    const names = state.inspection?.available ? (state.inspection.regions?.length || 0) + (state.inspection.cellArrays?.length || 0) : 0;
    rightModes.lastChild.textContent = names ? `Case data (${names})` : 'Case data';
    if (rightModes.hidden === hasCase) {
      rightModes.hidden = !hasCase;
      applyLayout();
    }
    caseData.element.querySelectorAll('button').forEach((button) => { button.disabled = state.busy || !state.record; });
    editorTools.querySelectorAll('button').forEach(button => { button.disabled = state.busy || !state.record; });
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
  const cursorChanged = () => {
    if (document.activeElement !== editor.textarea) return;
    const pointer = editor.getCursor().pointer;
    const selected = pointer.match(/^(.*\/nodes\/\d+)(?:\/|$)/)?.[1] || pointer;
    if (selected === store.get().selected) return;
    store.set({selected}); renderOutline(); renderProperties();
  };
  document.addEventListener('selectionchange', cursorChanged);
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
    const result = await ctx.api.post('/api/validate', validationRequest(store.get(), params, source,
      editor.getOption('format') || 'json'));
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
  applyLayout();
  load();
  return {element, editor, store, variableContext: variables.context,
    isDirty,
    onShow: () => {
      reserveToolbar(true);
      store.set({});
      library.registerCommands(ctx.commands);
      viewers.resize();
    },
    onHide: () => {
      reserveToolbar(false);
      library.registerCommands(null);
      reportDiagnostics(ctx, editor, {document: params.document, show: () => showTab('input')});
    },
    canClose: () => !isDirty() || confirmDialog('Discard unsaved input?',
      'This input has changes that have not been saved.', {confirm: 'Discard'}),
    dispose() {
      disposed = true;
      reserveToolbar(false);
      toolbarSize.disconnect();
      window.removeEventListener('resize', toolbarResized);
      store.set({disposed: true});
      unsubscribeStore();
      unsubscribeChange();
      document.removeEventListener('selectionchange', cursorChanged);
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
        onOpen: () => ctx.bus.emit('open-file'),
      });
      return {element: h('div', {class: 'window-body'}, chooser.element), dispose: chooser.dispose};
    }
    return createWorkbench(ctx, params, host);
  },
};
