// Copyright (C) 2026 David L F Gaden
// Multi-schema JSON authoring using the shared Studio editor and panel language.
import {createComprehension, formattingControls} from './workbench/comprehension.mjs';
import {h, icon, mount} from '../lib/dom.mjs';
import {createJsonEditor} from '../editor/editor.mjs';
import {bindVariables} from './variables/editor.mjs';
import {SchemaRegistry, resolveSchemaContext} from '../editor/schema-registry.mjs';
import {backgroundValidation, reportDiagnostics} from '../editor/settle-server.mjs';
import {identity} from '../shell/providers.mjs';
import {downloadText, chooseTextFile, confirmDiscard} from './source-files.mjs';
import {createLibrary} from './workbench/library.mjs';
import {commonProperties, nodeKinds} from './workbench/guidance.mjs';
import {namespaceRequest} from '../editor/insert-fields.mjs';

export const schemaEditorWindow = {
  type: 'schema-editor',
  title: 'Schema Editor',
  icon: 'braces',
  roles: ['admin', 'dev'],
  create(ctx, params, host) {
    let record = null;
    let savedSource = '{\n  "version": "schemaxis.freecad/1",\n  "nodes": []\n}\n';
    let disposed = false;
    let loading = false;
    let saving = false;
    let opening = false;
    const selected = new Set(params.versions || ['schemaxis.freecad/1', 'schemaxis.workflow/1']);
    const name = h('input', {class: 'input schema-name', value: 'Untitled', 'aria-label': 'Document name'});
    const subtitle = h('div', {class: 'subtitle'}, 'JSON / YAML authoring · local workspace');
    const status = h('span', {class: 'badge'}, 'Draft');
    const sourceHost = h('div', {class: 'schema-source'});
    const schemaList = h('div', {class: 'schema-list'});
    const problems = h('div', {class: 'schema-diagnostics'});
    const search = h('input', {class: 'input', placeholder: 'Find a schema…', 'aria-label': 'Find a schema'});
    const registry = new SchemaRegistry(async (version) => {
      const schema = await ctx.call(() => ctx.api.get('/api/schema', {version}), {title: 'Schema unavailable'});
      return selected.has(version) ? schema : null;
    }, {versions: []});
    const editor = createJsonEditor(sourceHost, {
      value: savedSource, registry,
      getFunctions: () => ctx.api.get('/api/functions'),
      suggestions: ctx.setting('editor.suggestions') !== false,
      hover: ctx.setting('editor.hover') !== false,
      indent: ' '.repeat(ctx.setting('editor.tabSize') || 2),
    });
    const comprehension = createComprehension(editor);
    const dirty = () => editor.getValue() !== savedSource || (record && name.value.trim() !== record.name);
    let libraryProvider = null;
    let libraryMetadata = null;
    let libraryRequest = 0;
    let libraryActive = true;
    function libraryScope() {
      let value;
      try { value = editor.getDocument(); } catch { return {value: null, base: ''}; }
      return {...resolveSchemaContext(registry, value, editor.getCursor().pointer, null), root: value};
    }
    editor.setOption('commonProperties', (pointer, value) => commonProperties(libraryMetadata, value, pointer));
    const library = createLibrary({ctx, editor: {...editor, preview: (request) => {
      const {base, root} = libraryScope();
      const scoped = namespaceRequest(request, root);
      // The library starts fill mode with this request's field definitions after committing.
      request.fields = scoped.fields;
      const inserts = scoped.inserts?.map((insert) => ({...insert,
        at: insert.at === '@cursor' ? insert.at : base + insert.at}));
      return editor.preview({...scoped, inserts});
    }}, getDocument: () => libraryScope().value,
    getSelectedNode: () => {
      const {value, base} = libraryScope();
      const index = editor.getCursor().pointer.slice(base.length).match(/^\/nodes\/(\d+)/)?.[1];
      return value?.nodes?.[index]?.id;
    }, changed: () => { updateStatus(); refreshLibrary(); }});
    async function refreshLibrary() {
      const scope = libraryScope();
      editor.setOption('fillNodeKinds', nodeKinds(libraryMetadata, scope.value));
      const provider = ctx.store.get().adaptors.find((adaptor) => adaptor.routes.includes(scope.value?.version))?.id;
      const libraryIdentity = provider + ':' + scope.value?.version;
      if (!provider || libraryIdentity === libraryProvider) return;
      libraryProvider = libraryIdentity;
      const request = ++libraryRequest;
      try {
        const metadata = await ctx.api.get('/api/studio/adaptor', {id: provider, version: scope.value?.version});
        if (disposed || request !== libraryRequest) return;
        libraryMetadata = metadata;
        editor.setOption('fillNodeKinds', nodeKinds(metadata, scope.value));
        library.update(metadata);
        library.registerCommands(libraryActive ? ctx.commands : null);
      } catch {
        libraryProvider = null;
      }
    }
    const onSelection = () => {
      if (document.activeElement === editor.textarea) refreshLibrary();
    };
    document.addEventListener('selectionchange', onSelection);
    const report = (error, title) => ctx.notify.error(error, {title, source: {document: params.document}});
    const reportAction = (error, title) => {
      editor.setDiagnostics([{...(error.fault || error), message: error.message, source: 'server'}]);
      reportDiagnostics(ctx, editor, {title, document: params.document});
    };

    function updateStatus() {
      status.textContent = saving ? 'Saving…' : dirty() ? 'Unsaved changes' : record ? 'Saved' : 'Draft';
      status.className = `badge ${dirty() ? 'warn' : record ? 'ok' : ''}`;
      subtitle.textContent = record
        ? `${identity(record.provider).name} · revision ${record.revision}` : 'JSON / YAML authoring · local workspace';
      host.setTitle(`${name.value || 'Untitled'}${dirty() ? ' •' : ''}`, 'Schema Editor');
    }

    function schemaChoices() {
      const items = ctx.store.get().adaptors.flatMap((adaptor) =>
        adaptor.routes.map((version) => ({adaptor, version})));
      const query = search.value.toLowerCase();
      mount(schemaList, items.filter(({adaptor, version}) =>
        `${identity(adaptor.id).name} ${version}`.toLowerCase().includes(query)).map(({adaptor, version}) => {
        const check = h('input', {type: 'checkbox', checked: selected.has(version),
          onChange: () => {
            if (check.checked) selected.add(version);
            else selected.delete(version);
            applySchemas();
          }});
        return h('label', {class: 'schema-choice'}, check, h('span', {},
          h('strong', {}, identity(adaptor.id).name), h('small', {}, version)));
      }));
    }

    function applySchemas() {
      params.versions = [...selected];
      for (const version of registry.loaded.keys()) {
        if (!selected.has(version) || registry.loaded.get(version) === null) {
          registry.loaded.delete(version);
        }
      }
      registry.versions = new Set(selected);
      for (const version of selected) registry.schemaFor(version);
      editor.setSchemaRegistry(registry);
      schemaChoices();
    }

    function detectSchemas(value) {
      const known = new Set(ctx.store.get().adaptors.flatMap((adaptor) => adaptor.routes));
      const visit = (item, depth) => {
        if (!item || typeof item !== 'object' || depth > 12) return;
        if (known.has(item.version)) selected.add(item.version);
        Object.values(item).forEach((child) => visit(child, depth + 1));
      };
      visit(value, 0);
      applySchemas();
    }

    async function load({force = false} = {}) {
      if (!params.document || loading || disposed) return;
      if (record && dirty() && !force) return;
      const before = editor.getValue();
      const beforeName = name.value;
      loading = true;
      try {
        const next = await ctx.api.get('/api/document', {id: params.document});
        if (disposed) return;
        if (editor.getValue() !== before || name.value !== beforeName) {
          ctx.notify.warn('Draft changed while refreshing', {body: 'Your unsaved edits were preserved. Reload when ready.'});
          return;
        }
        record = next;
        savedSource = next.source;
        name.value = next.name;
        editor.setFormat(next.sourceFormat || "json");
        sourceFormat.value = editor.getOption("format");
        editor.setValue(next.source);
        comprehension.refresh();
        editor.setDiagnostics(next.diagnostics);
        detectSchemas(next.document);
        refreshLibrary();
        if (params.revealLocation) {
          editor.revealPointer(params.revealLocation);
          delete params.revealLocation;
        }
        updateStatus();
      } catch (error) {
        report(error, 'Could not open document');
      } finally {
        loading = false;
      }
    }

    async function save() {
      if (saving || loading || opening || disposed) return false;
      saving = true;
      editor.flushDiagnostics();
      const source = editor.getValue();
      const title = name.value.trim() || 'Untitled';
      updateStatus();
      try {
        if (!record) {
          let value;
          try { value = editor.getDocument(); } catch { /* Invalid drafts use the selected schema. */ }
          const version = value?.version || [...selected][0];
          const adaptor = ctx.store.get().adaptors.find((item) => item.routes.includes(version));
          if (!adaptor) throw new Error('Choose a registered schema to save a workspace draft, or export the source.');
          record = await ctx.api.post('/api/documents', {action: 'new', provider: adaptor.id,
            name: title, source, format: editor.getOption("format") || "json"});
          params.document = record.id;
          ctx.windows.persist();
        } else {
          const result = await ctx.api.post('/api/authoring', {action: 'source', document: record.id,
            revision: record.revision, source, format: editor.getOption("format") || "json"});
          record = {...record, revision: result.revision, sourceFormat: editor.getOption("format") || "json", diagnostics: result.diagnostics};
          if (title !== record.name) {
            record = await ctx.api.post('/api/documents', {action: 'rename', id: record.id,
              revision: record.revision, name: title});
          }
        }
        savedSource = source;
        if (editor.getValue() === source) {
          editor.setDiagnostics(record.diagnostics);
          reportDiagnostics(ctx, editor, {document: params.document, title: 'Draft diagnostics'});
        }
        await ctx.refresh();
        if (!editor.getDiagnostics().length) {
          ctx.notify.ok('Draft saved', {body: 'Your document is retained in this workspace.'});
        }
        return true;
      } catch (error) {
        reportAction(error, 'Could not save draft');
        return false;
      } finally {
        saving = false;
        updateStatus();
      }
    }

    async function validate() {
      try {
        editor.flushDiagnostics();
        const version = editor.getTextVersion();
        const source = editor.getValue();
        let value;
        try { value = editor.getDocument(); } catch { value = {}; }
        const provider = record?.provider || ctx.store.get().adaptors.find((a) =>
          a.routes.includes(value.version || [...selected][0]))?.id;
        if (!provider) throw new Error('Choose a registered schema for host validation.');
        const result = await ctx.api.post('/api/validate', {provider, source, format: editor.getOption("format") || "json"});
        if (editor.getTextVersion() !== version) return;
        editor.setDiagnostics(result.diagnostics);
        const problems = reportDiagnostics(ctx, editor, {document: params.document, title: 'Document validation'});
        if (result.valid && !problems.length) ctx.notify.ok('Document validated');
      } catch (error) { reportAction(error, 'Validation failed'); }
    }

    async function openFile() {
      if (saving || loading || opening) return;
      opening = true;
      try {
        if (dirty() && !(await confirmDiscard())) return;
        const file = await chooseTextFile('.json,.yaml,.yml,application/json,application/yaml,text/yaml');
        if (!file || disposed) return;
        record = null;
        params.document = null;
        ctx.windows.persist();
        name.value = file.name.replace(/\.(json|yaml|yml)$/i, '');
        savedSource = '';
        editor.setFormat(/\.ya?ml$/i.test(file.name) ? "yaml" : "json");
        sourceFormat.value = editor.getOption("format");
        editor.setValue(file.text);
        try { detectSchemas(editor.getDocument()); } catch { /* Retain invalid JSON for repair. */ }
        updateStatus();
      } finally { opening = false; }
    }

    async function history(action) {
      if (!record || saving || loading || opening) return;
      if (dirty() && !(await confirmDiscard())) return;
      const before = editor.getValue();
      const beforeName = name.value;
      try {
        await ctx.api.post('/api/authoring', {action, document: record.id, revision: record.revision});
        if (editor.getValue() === before && name.value === beforeName) await load({force: true});
        else ctx.notify.warn('Draft changed during saved history', {body: 'Your unsaved edits were preserved.'});
        await ctx.refresh();
      } catch (error) { report(error, `Could not ${action}`); }
    }

    const unsubscribers = [
      backgroundValidation(editor, async (source) => {
        const value = editor.getDocument();
        const provider = record?.provider || ctx.store.get().adaptors.find((adaptor) =>
          adaptor.routes.includes(value.version || [...selected][0]))?.id;
        if (!provider || saving || loading || opening) return null;
        const result = await ctx.api.post('/api/validate', {provider, source, format: editor.getOption("format") || "json"});
        return result.diagnostics;
      }),
      editor.onChange(() => { updateStatus(); refreshLibrary(); }),
      editor.onSettledState((state) => {
        const items = state.diagnostics;
        mount(problems, h('div', {class: 'schema-problems-heading'},
          state.editing ? 'Editing…' : `${items.length} diagnostic${items.length === 1 ? '' : 's'}`),
        items.slice(0, 100).map((item) => h('button', {class: 'schema-problem',
          onClick: () => editor.revealOffset(item.from, item.to)},
        icon(item.severity === 'warning' ? 'alert' : 'error'),
        h('span', {}, item.message, h('small', {}, `${item.pointer || '$'} · line ${item.line || 1}, column ${item.column || 1}`)))));
      }),
      ctx.bus.on('document-changed', (changed) => {
        if (changed.id !== params.document || saving) return;
        if (!dirty()) load();
        else ctx.notify.warn('Document changed elsewhere', {
          body: 'Your draft is retained. Reload to see the saved revision before editing it.',
        });
      }),
      ctx.bus.on('reveal-location', (detail) => {
        if (detail.document === params.document) editor.revealPointer(detail.location);
      }),
      ctx.store.watch((state) => state.settings, () => {
        editor.setOption('suggestions', ctx.setting('editor.suggestions') !== false);
        editor.setOption('hover', ctx.setting('editor.hover') !== false);
        editor.setOption('indent', ' '.repeat(ctx.setting('editor.tabSize') || 2));
      }),
    ];
    search.addEventListener('input', schemaChoices);
    name.addEventListener('input', updateStatus);
    const button = (label, glyph, run, primary = false) => h('button', {
      class: `button small${primary ? ' primary' : ''}`, onClick: run,
    }, icon(glyph), label);
    const sourceFormat = h('select', {'aria-label': 'Schema source format', onChange: event => {
      if (!editor.convertFormat(event.target.value)) event.target.value = editor.getOption('format') || 'json';
      updateStatus(); refreshLibrary();
    }}, h('option', {value: 'json'}, 'JSON'), h('option', {value: 'yaml'}, 'YAML'));
    const element = h('div', {class: 'window-body schema-editor'},
      h('div', {class: 'window-header'}, icon('braces'), h('div', {class: 'titles'}, name, subtitle),
        h('div', {class: 'actions'}, status, button('Open input', 'folder', openFile),
          button('Export source', 'download', () => {
            reportDiagnostics(ctx, editor, {document: params.document, title: 'Export diagnostics'});
            downloadText(`${name.value || 'document'}.${editor.getOption('format') === 'yaml' ? 'yaml' : 'json'}`, editor.getValue());
          }),
          button('Save draft', 'save', save, true))),
      h('div', {class: 'schema-layout'},
        h('aside', {class: 'schema-sidebar'}, comprehension.element, h('h3', {class: 'section-title'}, 'Schemas'), search,
          h('p', {class: 'hint'},
            'Select versions for completion. Nested workflow documents use their own schema.'), schemaList),
        h('section', {class: 'schema-main'},
          library.bar, library.section,
          h('div', {class: 'schema-toolbar'}, sourceFormat, button('Validate', 'check', validate),
            formattingControls(editor),
            button('Undo saved edit', 'undo', () => history('undo')),
            button('Redo saved edit', 'redo', () => history('redo')),
            button('Reload', 'refresh', async () => {
              if (saving || opening) return;
              if (!dirty() || await confirmDiscard()) await load({force: true});
            })), sourceHost, problems)));
    element.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        save();
      }
    });
    applySchemas();
    refreshLibrary();
    if (params.document) load();
    const variables = bindVariables(ctx, editor);
    return {
      element, editor, variableContext: variables.context,
      isDirty: dirty,
      onShow: () => {
        libraryActive = true;
        library.registerCommands(ctx.commands);
        editor.focus();
      },
      onHide: () => {
        libraryActive = false;
        library.registerCommands(null);
        reportDiagnostics(ctx, editor, {document: params.document});
      },
      canClose: () => !dirty() || confirmDiscard(),
      dispose: () => {
        disposed = true;
        document.removeEventListener('selectionchange', onSelection);
        comprehension.dispose();
        library.destroy();
        unsubscribers.forEach((unsubscribe) => unsubscribe());
        editor.destroy();
      },
    };
  },
};
