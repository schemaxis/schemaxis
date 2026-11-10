// Copyright (C) 2026 David L F Gaden
// Workflow Designer window: adaptor palette, canvas, inspector and design tables.
//
// Bus events: emits 'open-operation' {document, operation}; consumes 'document-changed'.

import {h, icon} from '../../lib/dom.mjs';
import {documentChooser} from '../documents.mjs';
import {confirmDialog} from '../../shell/dialog.mjs';
import {createModel} from './model.mjs';
import {createCanvas} from './canvas.mjs';
import {createPalette} from './palette.mjs';
import {createInspector, statusBadge} from './inspector.mjs';
import {createBottom} from './bottom.mjs';
import {createActions} from './actions.mjs';

function header(model, actions) {
  const title = h('h2');
  const subtitle = h('div', {class: 'subtitle'});
  const status = h('span', {class: 'dz-header-status'});
  const undo = h('button', {class: 'button ghost icon-only', 'aria-label': 'Undo', title: 'Undo (Ctrl Z)',
    onClick: actions.undo}, icon('undo'));
  const redo = h('button', {class: 'button ghost icon-only', 'aria-label': 'Redo', title: 'Redo (Ctrl Y)',
    onClick: actions.redo}, icon('redo'));
  const compile = h('button', {class: 'button', onClick: actions.compile}, icon('play'), 'Compile');
  const expose = h('button', {class: 'button', onClick: actions.exposeUnfilled, hidden: true},
    'Expose unfilled values as parameters');
  const exportButton = h('button', {class: 'button primary', onClick: actions.exportTemplate}, icon('folder'),
    'Export template');
  const busy = h('span', {class: 'dz-busy', 'aria-live': 'polite'});
  const element = h('div', {class: 'window-header dz-header'},
    h('div', {class: 'dz-header-mark'}, icon('flow')),
    h('div', {class: 'titles'}, title, subtitle),
    status,
    h('div', {class: 'actions'}, busy, undo, redo, h('span', {class: 'dz-header-sep'}), expose, compile, exportButton));
  const render = (state) => {
    title.textContent = state.name || 'Workflow design';
    const projection = state.projection;
    subtitle.textContent = projection
      ? `Workflow design · ${projection.nodes.length} operations · revision ${state.revision}`
      : 'Workflow design';
    status.replaceChildren(projection ? statusBadge(projection.status) : '');
    undo.disabled = !state.undoCount;
    redo.disabled = !state.redoCount;
    const blocked = !projection || !projection.compilationAvailable;
    const reason = !projection ? '' : projection.loops.length
      ? 'Feedback loops cannot compile or export yet' : !projection.nodes.length ? 'Add operations first' : '';
    compile.disabled = blocked;
    exportButton.disabled = !projection?.templateExportAvailable;
    expose.hidden = !projection?.unfilled?.length;
    expose.disabled = state.busy || projection?.templateExportAvailable;
    compile.title = reason || 'Compile to an ordinary workflow document';
    exportButton.title = reason || 'Write a template bundle for the Case Runner';
    busy.replaceChildren(state.busy ? icon('spinner') : '');
    if (state.busy) {
      busy.firstChild.classList.add('spin');
    }
  };
  model.store.subscribe(render);
  render(model.store.get());
  return element;
}

function designer(ctx, documentId, host) {
  const model = createModel(ctx, documentId);
  let canvas = null;
  const actions = createActions(ctx, model, {getCanvas: () => canvas});
  canvas = createCanvas(ctx, model, {
    onConnect: actions.connect,
    onDelete: actions.deleteSelection,
    onDropAdaptor: actions.addOperation,
    onOpenNode: actions.openWorkbench,
  });
  const palette = createPalette(ctx, {onAdd: (adaptor) => actions.addOperation(adaptor)});
  const inspector = createInspector(ctx, model, actions);
  const bottom = createBottom(ctx, model);
  const element = h('div', {class: 'window-body dz'},
    header(model, actions),
    h('div', {class: 'dz-main'},
      palette.element,
      h('div', {class: 'dz-centre'}, canvas.element, bottom.element),
      inspector.element));

  element.addEventListener('keydown', (event) => {
    const modifier = event.ctrlKey || event.metaKey;
    if (!modifier || event.target.closest('input, textarea, select')) {
      return;
    }
    const key = event.key.toLowerCase();
    if (key === 'z' && !event.shiftKey) {
      event.preventDefault();
      actions.undo();
    } else if (key === 'y' || (key === 'z' && event.shiftKey)) {
      event.preventDefault();
      actions.redo();
    }
  });

  model.store.watch((state) => state.name, (name) => host.setTitle(name || 'Workflow design', 'Workflow Designer'));
  const offChanged = ctx.bus.on('document-changed', (record) => model.external(record));
  const offReveal = ctx.bus.on('reveal-location', (detail) => {
    if (detail.document !== documentId) return;
    ctx.openDocument(documentId);
    bottom.reveal(detail.pointer || detail.location || '');
  });
  model.load();
  // Exposed for diagnostics and browser tests (window.studio is ctx).
  ctx.designers = ctx.designers || new Map();
  ctx.designers.set(documentId, {model, canvas, actions});
  return {
    element,
    variableContext: async () => {
      if (bottom.isDirty()) throw Error('Apply or discard the edits in the design tables or Source tab before editing shared variables.');
      const record = await model.record();
      if (!record?.document) throw Error('Wait for the design to load.');
      return {root: record.document, label: `${record.name} · shared workflow values and Case Runner parameters`,
        applyLabel: 'Save changes to workflow', commit: async root => {
          if (bottom.isDirty()) throw Error('The design has unapplied edits. Apply them first.');
          await model.saveDocument(root, record.revision);
        }};
    },
    isDirty: () => bottom.isDirty() || canvas.isDirty() || model.store.get().busy
      || Object.keys(model.store.get().local).length > 0,
    canClose: async () => !bottom.isDirty() || Boolean(await confirmDialog('Discard unapplied design edits?',
      'The source or design tables have edits that have not been applied. Closing this tab discards them.',
      {confirm: 'Discard edits', danger: true})),
    onShow: () => canvas.element.focus({preventScroll: true}),
    dispose: () => {
      offChanged();
      offReveal();
      canvas.dispose();
      palette.dispose();
      inspector.dispose();
      bottom.dispose();
      ctx.designers.delete(documentId);
    },
  };
}

export const designerWindow = {
  type: 'designer',
  title: 'Workflow Designer',
  icon: 'flow',
  create(ctx, params, host) {
    if (!params.document) {
      const chooser = documentChooser(ctx, {
        title: 'Workflow Designer',
        description: 'Open a workflow design, or create one to connect adaptor instances.',
        providers: (provider) => provider === 'workflow-design',
        createLabel: 'New workflow design',
        onCreate: () => ctx.bus.emit('new-design'),
        emptyIcon: 'flow',
      });
      return {element: h('div', {class: 'window-body'}, chooser.element), dispose: chooser.dispose};
    }
    return designer(ctx, params.document, host);
  },
};
