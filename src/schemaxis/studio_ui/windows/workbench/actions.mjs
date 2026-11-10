// Copyright (C) 2026 David L F Gaden
// Revision-checked authoring, file saving and native jobs.
import {inspectionInput} from '../variables/model.mjs';
import {h} from '../../lib/dom.mjs';
import {inputBrowser} from './input-browser.mjs';
import {confirmDialog} from '../../shell/dialog.mjs';
import {reportDiagnostics} from '../../editor/settle-server.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {diagnosticPointer, mapDiagnostics, operationPointer, validationRequest, valueAt} from './model.mjs';

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
    const result = await ctx.api.post('/api/validate', validationRequest(store.get(), params, editor.getValue(),
      editor.getOption('format') || 'json'));
    if (version !== editor.getTextVersion()) return result;
    const diagnostics = mapDiagnostics(result.diagnostics, store.get().value);
    editor.setDiagnostics(diagnostics);
    const problems = reportDiagnostics(ctx, editor, {document: params.document, show: () => showTab('input')});
    if (success && result.valid && !problems.length) {
      ctx.notify.ok(result.validation?.deferred ? 'Workflow references checked' : 'Input validated', {
        body: result.validation?.deferred ? result.validation.message : 'The host planner accepted this input.'});
    }

    return result;
  }

  async function save({as = false} = {}) {
    const record = await publish();
    if (params.operation) {
      const problems = reportDiagnostics(ctx, editor, {document: params.document, show: () => showTab('input')});
      if (!problems.length) {
        ctx.notify.ok('Operation saved to design', {body: `${params.operation} · revision ${record.revision}`});
      }
      return;
    }
    let filename = as ? null : record.file;
    if (filename && /\.(json|yaml|yml)$/i.test(filename)) {
      const fileFormat = /\.ya?ml$/i.test(filename) ? 'yaml' : 'json';
      if (fileFormat !== (record.sourceFormat || 'json')) filename = null;
    }
    if (!filename) {
      const workspace = ctx.store.get().server?.workspace || '';
      const name = record.name.replace(/[^a-zA-Z0-9._-]/g, '-');
      const extension = record.sourceFormat === 'yaml' ? 'yaml' : 'json';
      const input = h('input', {class: 'input mono', value: as && record.file ? record.file : `${workspace}/${name}.${extension}`,
        'aria-label': 'Source file path'});
      filename = await openDialog({title: as ? 'Save input file as' : 'Save input file', wide: true,
        content: h('div', {}, h('label', {class: 'field'}, h('span', {}, 'Save to'), input),
          inputBrowser(ctx, input, 'Source file path', [extension === 'yaml' ? '.yaml' : '.json', ...(extension === 'yaml' ? ['.yml'] : [])],
            {desktop: false, save: true}),
          h('p', {class: 'wb-help'}, as && record.file ? `Currently saved to ${record.file}. Saving as a new file leaves that one as it is; later saves go to the new file.`
            : 'Later saves go to this file. Use Save as… to choose another.')),
        actions: [{label: 'Cancel', value: null},
          {label: 'Save', primary: true, run: () => input.value.trim() || false}]});
      if (!filename) {
        reportDiagnostics(ctx, editor, {document: params.document, show: () => showTab('input')});
        return;
      }
    }
    const write = overwrite => ctx.api.post('/api/authoring', {action: 'write', document: record.id,
      revision: record.revision, filename, ...(overwrite ? {overwrite: true} : {})});
    let result;
    try {
      result = await write(false);
    } catch (error) {
      if ((error.fault || error).code !== 'OUTPUT_EXISTS') throw error;
      if (!await confirmDialog('Replace the existing file?', `${filename} already exists. Replace it with this input?`,
        {confirm: 'Replace'})) return;
      result = await write(true);
    }
    await load({force: true});
    await ctx.refresh();
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
    if (params.operation && validation.validation?.requiresWorkflow) {
      ctx.notify.info('Run from the workflow', {
        body: validation.validation.deferred
          ? 'This operation needs files or values produced by earlier workflow steps.'
          : validation.validation.message
            || 'Run this operation from its workflow to preserve its resolved inputs and connections.'});
      return;
    }
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
      ctx.openResults?.({collection: 'job-' + job.job});
    }
  }

  async function inspect(live = false) {
    const state = store.get(), version = editor.getTextVersion();
    const document = inspectionInput(state.record.document, editor.getDocument(), operationPointer(state.record, params.operation));
    const pointer = state.selected.match(/^(.*\/nodes\/\d+)(?:\/|$)/)?.[1];
    const selected = pointer ? valueAt(document, pointer) : null;
    const operations = state.metadata.inspection?.metadataOperations;
    const readers = (document.nodes || []).filter(item => typeof item?.id === 'string' && typeof item.options?.file === 'string'
      && (!operations || operations.includes(item.filter)));
    const node = live ? selected || document.nodes?.find(item => typeof item.id === 'string')
      : readers.includes(selected) ? selected : readers[0] || selected || document.nodes?.find(item => typeof item.id === 'string');
    if (!node?.id) throw Error('Add or select a named input node first.');
    let result;
    if (live) {
      const request = await ctx.api.post('/api/inspect-input', {provider: state.provider, input: document, node: node.id,
        geometry: Boolean(state.metadata.inspection?.geometry)});
      result = (await ctx.api.waitForJob(request.job)).result;
    } else result = await ctx.api.post('/api/peek-input', {provider: state.provider, input: document, node: node.id});
    if (store.get().disposed) return;
    if (editor.getTextVersion() !== version) throw Error('The draft changed during inspection. Refresh the preview.');
    store.set({inspection: result, dataMode: live ? 'live' : 'metadata'});
    if (result.geometry) await viewers.showDraftGeometry(result.geometry, `Live data · ${node.id} · current draft · refresh after editing`);
    else if (result.available === false) ctx.notify.info('No names could be read', {body: result.reason || result.message || result.scope});
    else if (live) ctx.notify.info('Live data inspected', {body: result.scope});
    return result;
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

  return {publish, inspect: live => perform(() => inspect(live)), validate: () => perform(validate), save: () => perform(save),
    saveAs: () => perform(() => save({as: true})),
    preview: () => perform(() => preview(false)), run: () => perform(() => preview(true)),
    undo: () => perform(() => travel('undo')), redo: () => perform(() => travel('redo'))};
}
