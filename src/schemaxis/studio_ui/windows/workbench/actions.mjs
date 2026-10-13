// Revision-checked authoring, file saving and native jobs.
import {h} from '../../lib/dom.mjs';
import {reportDiagnostics} from '../../editor/settle-server.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {diagnosticPointer, mapDiagnostics, operationPointer, valueAt} from './model.mjs';

export function createActions({ctx, store, editor, params, load, viewers, showTab}) {
  async function publish() {
    const {record} = store.get();
    const baseline = params.operation
      ? JSON.stringify(valueAt(record.document, operationPointer(record, params.operation)), null, 2) : record.source;
    if (editor.getValue() === baseline) {
      return record;
    }
    let source = editor.getValue();
    if (params.operation) {
      await ctx.api.post('/api/authoring', {action: 'patch', document: record.id, revision: record.revision,
        edits: [{op: 'replace', path: operationPointer(record, params.operation), value: editor.getDocument()}]});
      await load({force: true});
      await ctx.refresh();
      return store.get().record;
    }
    await ctx.api.post('/api/authoring', {action: 'source', document: record.id, revision: record.revision, source, ...(params.operation ? {} : {format: editor.getOption('format') || 'json'})});
    await load({force: true});
    await ctx.refresh();
    return store.get().record;
  }

  async function validate({success = true} = {}) {
    editor.flushDiagnostics();
    const version = editor.getTextVersion();
    const result = await ctx.api.post('/api/validate', {provider: store.get().provider, source: editor.getValue(), format: editor.getOption('format') || 'json'});
    if (version !== editor.getTextVersion()) return result;
    const diagnostics = mapDiagnostics(result.diagnostics, store.get().value);
    editor.setDiagnostics(diagnostics);
    const problems = reportDiagnostics(ctx, editor, {document: params.document, show: () => showTab('input')});
    if (success && result.valid && !problems.length) {
      ctx.notify.ok('Input validated', {body: 'The host planner accepted this input.'});
    }

    return result;
  }

  async function save() {
    const record = await publish();
    if (params.operation) {
      const problems = reportDiagnostics(ctx, editor, {document: params.document, show: () => showTab('input')});
      if (!problems.length) {
        ctx.notify.ok('Operation saved to design', {body: `${params.operation} · revision ${record.revision}`});
      }
      return;
    }
    let filename = record.file;
    if (filename && /\.(json|yaml|yml)$/i.test(filename)) {
      const fileFormat = /\.ya?ml$/i.test(filename) ? 'yaml' : 'json';
      if (fileFormat !== (record.sourceFormat || 'json')) filename = null;
    }
    if (!filename) {
      const workspace = ctx.store.get().server?.workspace || '';
      const name = record.name.replace(/[^a-zA-Z0-9._-]/g, '-');
      const input = h('input', {class: 'input', value: `${workspace}/${name}.${record.sourceFormat === "yaml" ? "yaml" : "json"}`, 'aria-label': 'Source file path'});
      filename = await openDialog({title: 'Save input file',
        content: h('label', {class: 'field'}, h('span', {}, 'Source file path'), input),
        actions: [{label: 'Cancel', value: null},
          {label: 'Save', primary: true, run: () => input.value.trim() || false}]});
      if (!filename) {
        reportDiagnostics(ctx, editor, {document: params.document, show: () => showTab('input')});
        return;
      }
    }
    const result = await ctx.api.post('/api/authoring', {action: 'write', document: record.id,
      revision: record.revision, filename});
    await load({force: true});
    const problems = reportDiagnostics(ctx, editor, {document: params.document, show: () => showTab('input')});
    if (!problems.length) ctx.notify.ok('Input saved', {body: result.saved});
  }

  async function travel(action) {
    await publish();
    const record = store.get().record;
    await ctx.api.post('/api/authoring', {action, document: record.id, revision: record.revision});
    await load({force: true});
    await ctx.refresh();
  }

  async function preview(run = false) {
    const validation = await validate({success: false});
    if (!validation.valid) return;
    const record = await publish();
    if (params.operation) {
      const separate = await ctx.api.post('/api/documents', {action: 'new', provider: store.get().provider,
        name: `${params.operation} preview`, document: editor.getDocument()});
      await ctx.refresh();
      ctx.windows.open('workbench', {document: separate.id});
      ctx.notify.info('Preview instance created', {
        body: 'This independent instance uses the saved operation input. Workflow references need bound values.'});
      return;
    }
    if (run && !ctx.store.get().server?.configured?.includes(store.get().provider)) {
      ctx.windows.open('setup');
      ctx.notify.info('Configure the application first', {
        body: 'Preview can still produce a host planning checkpoint.'});
      return;
    }
    const job = await ctx.api.post(run ? '/api/command' : '/api/preview',
      {...(run ? {line: 'preview'} : {}), document: record.id, revision: record.revision});
    ctx.store.set({panelOpen: true, panelTab: 'jobs'});
    await ctx.refresh();
    const result = await ctx.api.waitForJob(job.job, {onUpdate: () => ctx.refresh()});
    await ctx.refresh();
    if (store.get().disposed) {
      return;
    }
    const native = result.result?.native;
    store.set({native: result.result?.live ? 'live' : null});
    ctx.notify.ok(native ? 'Native execution verified' : 'Planning checkpoint created', {
      body: native ? result.result.preview : 'No configured application was executed. Configure one to run natively.'});
    if (native) {
      await viewers.showArtifacts(result.result.artifacts || []);
      if (result.result.live && store.get().metadata.viewers.includes('3d')) {
        await viewers.preview('3d', record);
      }
    }
  }

  async function perform(action) {
    if (store.get().busy || !store.get().record) {
      return;
    }
    store.set({busy: true});
    editor.flushDiagnostics();
    try {
      return await action();
    } catch (error) {
      const fault = error.fault || error;
      const pointer = diagnosticPointer(fault.location, store.get().value);
      editor.setDiagnostics([{...fault, message: fault.message, pointer, source: 'server'}]);
      reportDiagnostics(ctx, editor, {title: 'Workbench action failed', document: params.document,
        show: () => showTab('input')});
    } finally {
      store.set({busy: false});
    }
  }

  return {publish, validate: () => perform(validate), save: () => perform(save),
    preview: () => perform(() => preview(false)), run: () => perform(() => preview(true)),
    undo: () => perform(() => travel('undo')), redo: () => perform(() => travel('redo'))};
}
