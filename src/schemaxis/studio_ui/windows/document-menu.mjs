// Workspace document actions shared by tabs and recent-document lists.
import {h} from '../lib/dom.mjs';
import {openDialog, openMenu, confirmDialog} from '../shell/dialog.mjs';

export function documentMenu(ctx, documentId, anchor) {
  const record = ctx.store.get().server?.documents.find((item) => item.id === documentId);
  if (!record) return;
  const change = async (action, extra = {}) => {
    const result = await ctx.call(() => ctx.api.post('/api/documents', {
      action, id: documentId, revision: record.revision, ...extra,
    }), {title: 'Could not update document', source: {document: documentId}});
    if (result) await ctx.refresh();
    return result;
  };
  openMenu(anchor, [
    {label: 'Open in Schema Editor', icon: 'braces', run: () =>
      ctx.windows.open('schema-editor', {document: documentId})},
    {label: 'Rename document…', icon: 'file', run: async () => {
      if ([...ctx.windows.instances.values()].some((item) =>
        item.params.document === documentId && item.window.isDirty?.())) {
        ctx.notify.warn('Save the draft before renaming', {body: 'Renaming changes the document revision.'});
        return;
      }
      const input = h('input', {class: 'input', value: record.name, 'aria-label': 'Document name'});
      const name = await openDialog({title: 'Rename document', content: input,
        actions: [{label: 'Cancel', run: () => null},
          {label: 'Rename', primary: true, run: () => input.value.trim() || false}]});
      if (name) await change('rename', {name});
    }},
    {label: 'Duplicate document', icon: 'copy', run: async () => {
      const copied = await change('duplicate');
      if (copied) ctx.openDocument(copied.id);
    }},
    {label: 'Remove from workspace…', icon: 'close', run: async () => {
      const windows = [...ctx.windows.instances.values()].filter((item) => item.params.document === documentId);
      if (windows.some((item) => item.window.isDirty?.())) {
        ctx.notify.warn('Save or discard the open draft first', {body: 'This document has unsaved changes in an editor.'});
        return;
      }
      if (!await confirmDialog('Remove document from workspace?',
        `Remove “${record.name}” and its workspace history? Saved files and run outputs remain on disk.`,
        {confirm: 'Remove document', danger: true})) return;
      const result = await change('close');
      if (result) {
        for (const item of windows) await ctx.windows.close(item.key);
      }
    }},
  ]);
}
