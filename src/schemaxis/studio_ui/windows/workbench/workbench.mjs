// Copyright (C) 2026 David L. F. Gaden.
// Public factory: workbenchWindow.create(ctx, {document, operation?}, host).
// An operation edits nested input in its parent workflow design using the parent's revision.
import {openLiveData} from '../spatial/live-data.mjs';
import {createComprehension, formattingControls} from './comprehension.mjs';
import {h, icon, mount} from '../../lib/dom.mjs';
import {Store} from '../../lib/store.mjs';
import {createJsonEditor} from '../../editor/editor.mjs';
import {documentChooser} from '../documents.mjs';
import {identity} from '../../shell/providers.mjs';
import {confirmDialog, openMenu} from '../../shell/dialog.mjs';
import {outline, mapDiagnostics, operationPointer, validationRequest, valueAt} from './model.mjs';
import {createLibrary} from './library.mjs';
import {createSelectionGuide} from './properties.mjs';
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
    return {sidebar: ['guide', 'library', 'hidden'].includes(value.sidebar) ? value.sidebar : 'guide',
      shown: value.shown === 'library' ? 'library' : 'guide', controls: value.controls !== false,
      caseData: value.caseData !== false};
  } catch {
    return {sidebar: 'guide', shown: 'guide', controls: true, caseData: true};
  }
}

function createWorkbench(ctx, params, host) {
  const store = new Store({record: null, provider: null, value: null, schema: null, selected: '', tab: 'input',
    dirty: false, busy: false, references: [], metadata: {templates: [], snippets: [], viewers: []}});
  let disposed = false;
  let loading = 0;
  let lastInspection;
  const status = h('button', {class: 'badge', type: 'button', 'aria-label': 'Native application setup'});
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
    renderSelection();
  }

  function showTab(tab, {report = true} = {}) {
    if (report && store.get().tab === 'input' && tab !== 'input') {
      reportDiagnostics(ctx, editor, {document: params.document, show: () => showTab('input')});
    }
    if (VIEWER_LABELS[tab]) {
      const item = viewers.get(tab);
      if (!item.panel.isConnected) {
        panels.append(item.panel);
      }
    }
    store.set({tab});
    if (tab === 'schema') renderSelection();
    authoringTools.hidden = tab !== 'input' || !preferences.controls;
    controlsToggle.hidden = tab !== 'input';
    if (tab === 'input') library.updateSection();
    else library.section.hidden = true;
    [...panels.children].forEach((panel) => {
      panel.hidden = panel === editorHost ? tab !== 'input'
        : panel === selectionGuide.schemaElement ? tab !== 'schema' : panel.dataset.viewerPanel !== tab;
    });
    [...tabs.children].forEach((button) => button.setAttribute('aria-selected', String(button.dataset.tab === tab)));
    viewers.resize();
  }

  function select(pointer, {reveal = true} = {}) {
    store.set({selected: pointer});
    renderOutline();
    renderSelection();
    if (store.get().tab === 'input') {
      if (reveal) editor.revealPointer(pointer);
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
  // Names read from the case, shared by Case data and the settings windows.
  const nameListeners = new Set();
  const sharedNames = {
    get: () => store.get().inspection || null,
    subscribe: (listener) => { nameListeners.add(listener); return () => nameListeners.delete(listener); },
    load: async (live) => {
      const result = await actions.inspect(live);
      if (!result) throw Error('No names could be read. Add an OpenFOAM reader with its case file first; details are in Problems.');
      return result;
    }};
  const selectionGuide = createSelectionGuide({ctx, onReveal: pointer => { showTab('input'); select(pointer); }});
  selectionGuide.schemaElement.hidden = true;
  panels.append(selectionGuide.schemaElement);
  const viewers = createViewers({ctx, store, onTab: showTab, spatialContext: () => {
    const {record, value, spatial} = store.get();
    if (!record) return {root: value || {}};
    const base = operationPointer(record, params.operation);
    return {root: base ? replacing(record.document, base, value) : value, base: base || null, spatial};
  },
    onObservation: (value) => editor.setOption('fillObservations', observationFields(value))});
  const library = createLibrary({ctx, editor, getSpatialContext, authoringScope: `${params.document}:${params.operation || ''}`, getDocument: () => editor.getDocument(),
    scope: () => ({base: '', value: editor.getDocument(), label: params.operation ? 'operation input' : 'input',
      context: [store.get().record, params.operation || '']}),
    getSelectedNode: () => valueAt(store.get().value, store.get().selected)?.id,
    showInput: () => showTab('input'), changed, caseNames: sharedNames});
  const comprehension = createComprehension(editor, (pointer) => { showTab('input'); select(pointer, {reveal: Boolean(pointer)}); },
    (pointer) => library.editOperation(pointer));
  const actions = createActions({ctx, store, editor, params, load, viewers, showTab});
  const variables = bindVariables(ctx, editor, {changed, snapshot: async () => {
    const {record} = store.get(), version = editor.getTextVersion();
    if (!record) throw Error('Wait for the input to load.');
    const base = operationPointer(record, params.operation);
    const root = base ? replacing(record.document, base, editor.getDocument()) : editor.getDocument();
    return {root, base, identity: record.id, revision: version, spatial: store.get().spatial,
      observeSpatial: spatial => store.set({spatial}), label: `${record.name}${base ? ' · shared changes save this operation and its workflow together.' : ' · changes remain in the input draft until saved.'}`,
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
    title: 'Choose which sources and nodes to keep in memory.',
    onClick: () => ctx.call(async () => openLiveData(ctx, await variables.context()))}, 'Live Data…');
  const inspectData = h('button', {class: 'button', dataset: {action: 'inspect-live'}, hidden: true,
    title: 'Load or reuse the selected node to inspect its mesh, bounds and block names.',
    onClick: () => actions.inspect(true)}, 'Inspect selected node');
  const buttons = h('div', {class: 'wb-toolbar actions', role: 'toolbar', 'aria-label': 'Adaptor actions'}, status,
    h('button', {class: 'button', dataset: {action: 'help'}, onClick: () => {
      const {value, selected, provider} = store.get();
      const pointer = selected.match(/^\/nodes\/\d+/)?.[0];
      const node = pointer ? valueAt(value, pointer) : null;
      ctx.openHelp({provider, operation: node?.filter});
    }, title: 'Open the adaptor guide for the selected operation'}, 'Adaptor help'), actionButton('Validate', 'validate'),
    actionButton('Preview', 'preview'), liveData, inspectData, actionButton('Run', 'run'),
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
    h('button', {class: 'button small primary', dataset: {action: 'edit-settings'},
      title: 'Reopen the settings window for the item at the cursor',
      onClick: () => {
        const pointer = store.get().selected;
        if (pointer) library.editOperation(pointer);
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
  const caseDataToggle = h('button', {class: 'button ghost small icon-only wb-sidebar-toggle wb-case-data-toggle', type: 'button',
    'aria-label': 'Show or hide Case data', title: 'Show or hide Case data',
    onClick: () => { preferences.caseData = !preferences.caseData; remember(); applyLayout(); }},
  h('span', {class: 'wb-sidebar-icon wb-sidebar-icon-right', 'aria-hidden': 'true'}));
  const sidebarModes = h('div', {class: 'wb-segmented', role: 'radiogroup', 'aria-label': 'Sidebar contents'},
    [['guide', 'Overview', 'The pipeline, following your cursor'], ['library', 'Templates', 'Document sections, templates and snippets']]
      .map(([mode, label, hint]) => h('button', {type: 'button', role: 'radio',
      dataset: {sidebar: mode}, title: hint, onClick: () => setSidebar(mode)}, label)));
  const sections = h('div', {class: 'wb-sections'}, h('h3', {class: 'wb-section-title'}, 'Document sections'),
    outlineList, library.element, viewers.artifacts);
  const guide = h('div', {class: 'wb-guide'}, comprehension.element, selectionGuide.element);
  const sidebar = h('aside', {class: 'wb-left'}, h('div', {class: 'wb-sidebar-head'},
    h('div', {class: 'wb-sidebar-modes'}, sidebarModes,
      h('button', {class: 'button ghost small icon-only', type: 'button', 'aria-label': 'Hide the sidebar', title: 'Hide the sidebar',
        onClick: () => setSidebar('hidden')}, icon('close')))),
    h('div', {class: 'wb-sidebar-content'}, guide, sections));
  const caseData = createCaseData({onLoad: () => actions.inspect(false), onUse: useCaseName});
  const viewBar = h('div', {class: 'wb-view-bar'}, sidebarToggle, tabs,
    h('div', {class: 'wb-view-actions'}, controlsToggle, caseDataToggle));
  const rightSidebar = h('aside', {class: 'wb-right', 'aria-label': 'Case data panel'}, caseData.element, viewers.references);
  const layout = h('div', {class: 'wb-layout'}, sidebar,
    h('section', {class: 'wb-centre'}, viewBar, authoringTools, panels),
    rightSidebar);
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
    rightSidebar.hidden = !preferences.caseData;
    layout.classList.toggle('wb-no-case-data', rightSidebar.hidden);
    caseDataToggle.setAttribute('aria-pressed', String(!rightSidebar.hidden));
    guide.hidden = mode === 'library';
    sections.hidden = mode === 'guide';
    sidebarToggle.setAttribute('aria-pressed', String(!sidebar.hidden));
    [...sidebarModes.children].forEach((button) => button.setAttribute('aria-checked', String(button.dataset.sidebar === mode)));
    controlsToggle.setAttribute('aria-pressed', String(preferences.controls));
    authoringTools.hidden = store.get().tab !== 'input' || !preferences.controls;
  }

  async function useCaseName(value) {
    showTab('input');
    const documentValue = editor.getDocument();
    let pointer = editor.getCursor().pointer || '';
    if (!Array.isArray(valueAt(documentValue, pointer))) pointer = pointer.slice(0, pointer.lastIndexOf('/'));
    const target = valueAt(documentValue, pointer);
    const values = Array.isArray(value) ? value : value !== null && typeof value !== 'object' ? [value] : null;
    if (values && Array.isArray(target) && target.every((item) => typeof item !== 'object' || item?.pattern)) {
      const additions = [...new Set(values)].filter(item => !target.includes(item));
      if (!additions.length) return `These values are already in ${pointer}.`;
      editor.insertAtPointer(`${pointer}/-`, additions, {multiple: true});
      changed();
      return `Added ${additions.length} value${additions.length === 1 ? '' : 's'} to ${pointer}. Undo restores the list.`;
    }
    // JSON lists/objects are also valid YAML flow values; quoting preserves
    // strings such as "1", commas, newlines and names with punctuation.
    const text = JSON.stringify(value, null, 2);
    if (!navigator.clipboard?.writeText) throw Error('Clipboard access is unavailable in this browser.');
    await navigator.clipboard.writeText(text);
    if (!values) return 'Copied all case-data sections as JSON.';
    return Array.isArray(value) ? `Copied ${value.length} values as a list. Put the cursor in a list to add them directly.`
      : `Copied ${text}. Put the cursor in a list of names to add it directly.`;
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

  function renderSelection() {
    const {schema, value, selected} = store.get();
    editor.setOption('fillNodeKinds', nodeKinds(store.get().metadata, value));
    const owner = selected.match(/^(.*\/nodes\/\d+)(?:\/|$)/)?.[1];
    const pointer = valueAt(value, owner || selected) === undefined ? '' : owner || selected;
    const operation = store.get().metadata.addCatalogue?.items?.find(item => item.operation === valueAt(value, owner)?.filter);
    // Clearing selection hides its guide. Building the entire document schema
    // here blocks the click for no visible benefit; prepare it when Schema opens.
    if (selected || store.get().tab === 'schema') selectionGuide.update(schema, value, pointer, operation);
    const entry = owner && comprehension.element.querySelector(`[data-pointer="${CSS.escape(owner)}"]`);
    const destination = entry?.closest('.wb-overview-node') || guide;
    if (selectionGuide.element.parentElement !== destination) destination.append(selectionGuide.element);
    selectionGuide.element.hidden = !selected;
    const disabled = store.get().busy || !store.get().record || !library.hasSettings(selected);
    comprehension.setAvailability({busy: store.get().busy || !store.get().record, canEdit: !disabled});
    editorTools.querySelector('[data-action="edit-settings"]').disabled = disabled;
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
    renderSelection();
    loadCaseNames();
    if (params.fill) {
      delete params.fill;
      editor.startFill();
    }
  }

  const unsubscribeStore = store.subscribe((state) => {
    const configured = ctx.store.get().server?.configured?.includes(state.provider);
    status.textContent = state.native === 'live' ? 'Live' : configured ? 'Configured' : 'Native unavailable';
    status.className = configured ? 'badge ok' : 'badge';
    status.title = configured ? 'The native application is configured. Host editing and validation are always available.'
      : 'The native application has no usable configured location. Open Application Setup to enable live inspection and execution.';
    status.onclick = () => ctx.role() === 'admin' ? ctx.windows.open('setup')
      : ctx.notify.info('Native application setup', {body: 'Select Admin in the title bar, then open Application Setup to choose the native executable. Editing, metadata preview and host validation remain available.'});
    liveData.hidden = !state.metadata.inspection?.live;
    inspectData.hidden = liveData.hidden;
    caseData.update(state.inspection);
    if (state.inspection !== lastInspection) {
      lastInspection = state.inspection;
      nameListeners.forEach((listener) => listener(lastInspection || null));
    }
    caseData.element.querySelectorAll('button').forEach((button) => { button.disabled = state.busy || !state.record; });
    editorTools.querySelectorAll('button').forEach(button => { button.disabled = state.busy || !state.record; });
    const disabled = state.busy || !state.record || !library.hasSettings(state.selected);
    editorTools.querySelector('[data-action=edit-settings]').disabled = disabled;
    comprehension.setAvailability({busy: state.busy || !state.record, canEdit: !disabled});
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
    store.set({selected}); renderOutline(); renderSelection();
  };
  document.addEventListener('selectionchange', cursorChanged);
  const unsubscribeChange = editor.onChange(changed);
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
      library.cancelReview();
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
