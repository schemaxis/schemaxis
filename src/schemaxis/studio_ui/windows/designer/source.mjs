// The complete design remains editable, including when malformed source cannot project to a canvas.

import {h, icon} from '../../lib/dom.mjs';
import {createJsonEditor} from '../../editor/editor.mjs';
import {sourcePointer} from './locations.mjs';
import {reportDiagnostics} from '../../editor/settle-server.mjs';
import {SchemaRegistry} from '../../editor/schema-registry.mjs';
import {createLibrary} from '../workbench/library.mjs';
import {commonProperties} from '../workbench/guidance.mjs';

export function createSourceTab(ctx, model) {
  const host = h('div', {class: 'dz-source-editor'});
  let metadata = {templates: [], snippets: [], categories: []};
  const versions = ['schemaxis.workflow-design/2', 'schemaxis.workflow/1',
    ...(ctx.store.get().adaptors || []).flatMap((item) => item.routes || [item.version])];
  const registry = new SchemaRegistry((version) => ctx.call(() => ctx.api.get('/api/schema', {version}),
    {title: 'Design schema unavailable'}), {versions});
  const editor = createJsonEditor(host, {registry, changeDelay: 0,
    suggestions: ctx.setting('editor.suggestions') !== false,
    getFunctions: () => ctx.api.get('/api/functions'),
    commonProperties: (pointer, document) => commonProperties(metadata, document, pointer),
    indent: ' '.repeat(ctx.setting('editor.tabSize') || 2), hover: ctx.setting('editor.hover') !== false});
  editor.textarea.setAttribute('aria-label', 'Design source JSON');
  const status = h('span', {class: 'muted', 'aria-live': 'polite'});
  const save = h('button', {class: 'button primary small', onClick: apply}, icon('check'), 'Apply source');
  const reload = h('button', {class: 'button small', onClick: () => load(true)}, 'Discard');
  const validate = h('button', {class: 'button small', onClick: async () => {
    editor.flushDiagnostics();
    const version = editor.getTextVersion();
    const result = await ctx.call(() => ctx.api.post('/api/authoring', {action: 'validate_source',
      provider: 'workflow-design', source: editor.getValue(), format: editor.getOption('format') || 'json'}), {title: 'Could not validate the design'});
    if (result && editor.getTextVersion() === version) {
      setDiagnostics(result.diagnostics || []);
      reportDiagnostics(ctx, editor, {document: model.documentId, title: 'Design validation'});
      status.textContent = result.valid ? 'Valid design source' : `${result.diagnostics.length} source problems`;
    }
  }}, 'Validate');
  const library = createLibrary({ctx, editor, getDocument: value, changed: update});
  const sourceFormat = h('select', {'aria-label': 'Design source format', onChange: event => {
    if (!editor.convertFormat(event.target.value)) event.target.value = editor.getOption('format') || 'json';
    update();
  }}, h('option', {value: 'json'}, 'JSON'), h('option', {value: 'yaml'}, 'YAML'));
  const element = h('div', {class: 'dz-tab-panel dz-source-panel'}, library.bar, library.section,
    h('div', {class: 'dz-source-toolbar'}, sourceFormat, status, h('span', {class: 'grow'}), validate, reload, save), host);
  let active = false;
  let baseline = '';
  let shown = null;
  let loading = false;
  let request = 0;
  let disposed = false;
  let libraryLoaded = false;
  let libraryLoading = null;
  let commandsActive = false;
  const sourceCommands = {register: (command) => ctx.commands.register({...command,
    id: `${command.id}:source:${model.documentId}`})};

  function syncCommands() {
    const visible = active && element.isConnected && element.closest('.window')?.hidden !== true;
    if (commandsActive && !visible) {
      reportDiagnostics(ctx, editor, {document: model.documentId, title: 'Design source diagnostics'});
      editor.stopFill();
      editor.clearPreview();
    }
    commandsActive = visible;
    library.registerCommands(visible ? sourceCommands : null);
  }

  async function loadLibrary() {
    if (libraryLoaded || libraryLoading || disposed) return libraryLoading;
    libraryLoading = ctx.call(() => ctx.api.get('/api/studio/adaptor', {id: 'workflow-design'}),
      {title: 'Design snippets unavailable'}).then((result) => {
      if (disposed) return;
      if (result) {
        metadata = result;
        libraryLoaded = true;
        library.update(metadata);
      }
      library.bar.hidden = !metadata.snippets.length;
      library.updateSection();
      syncCommands();
    }).finally(() => { libraryLoading = null; });
    return libraryLoading;
  }

  function value() {
    try { return editor.getDocument(); }
    catch { return null; }
  }

  function setDiagnostics(items) {
    const document = value();
    editor.setDiagnostics(items.map((item) => ({...item,
      pointer: item.pointer || sourcePointer(item.location, document),
      ...(Number.isInteger(item.offset) ? {from: item.offset, to: item.offset + 1} : {}),
    })));
  }

  function update() {
    const dirty = editor.getValue() !== baseline;
    save.disabled = !dirty || loading;
    reload.disabled = !dirty;
    status.textContent = dirty ? shown !== model.store.get().revision
      ? 'Design changed elsewhere; discard to load it. Your source edits are kept.' : 'Unapplied source changes'
      : 'Canvas edits are saved automatically. Source changes apply as one undo step.';
  }

  async function load(force = false) {
    if (!active) return;
    if (!force && editor.getValue() !== baseline) {
      update();
      return;
    }
    if (!force && shown === model.store.get().revision) return;
    const token = ++request;
    const before = editor.getValue();
    const record = await model.record();
    if (request !== token) return;
    // A canvas edit may start this fetch before the user begins a local draft.
    // Discard also preserves text typed while its response is still in flight.
    if (editor.getValue() !== before) {
      update();
      return;
    }
    if (record && record.revision === model.store.get().revision) {
      baseline = record.source;
      shown = record.revision;
      editor.setFormat(record.sourceFormat || "json");
      sourceFormat.value = editor.getOption("format");
      editor.setValue(record.source);
      setDiagnostics(record.diagnostics || []);
      library.updateSection();
      update();
    }
  }

  async function apply() {
    editor.flushDiagnostics();
    const source = editor.getValue();
    loading = true;
    update();
    const result = await model.saveSource(source, shown, editor.getOption("format") || "json");
    loading = false;
    if (result) {
      baseline = source;
      shown = result.revision;
      setDiagnostics(result.diagnostics || []);
      reportDiagnostics(ctx, editor, {document: model.documentId, title: 'Design source diagnostics'});
    }
    update();
  }

  const onKeydown = (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      event.stopPropagation();
      if (!save.disabled) apply();
    }
  };
  element.addEventListener('keydown', onKeydown);
  const offActivation = ctx.bus.on('window-activated', syncCommands);
  const offChange = editor.onChange(update);
  const unsubscribe = model.store.watch((state) => state.revision, () => load());
  update();
  return {element, isDirty: () => editor.getValue() !== baseline,
    async reveal(location) {
      active = true;
      syncCommands();
      loadLibrary();
      await load();
      editor.revealPointer(sourcePointer(location, value()));
    },
    show() {
      active = true;
      syncCommands();
      loadLibrary();
      load();
    },
    hide() {
      active = false;
      syncCommands();
    },
    dispose() {
      disposed = true;
      request += 1;
      offActivation();
      element.removeEventListener('keydown', onKeydown);
      library.destroy();
      offChange();
      unsubscribe();
      editor.destroy();
    }};
}
