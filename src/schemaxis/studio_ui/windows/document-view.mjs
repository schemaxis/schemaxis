// Copyright (C) 2026 David L F Gaden
// Read-only document view shared by interim windows: header, status and source.

import {h, icon, mount} from '../lib/dom.mjs';
import {identity} from '../shell/providers.mjs';

export function documentView(ctx, documentId, host, {icon: iconName}) {
  const title = h('h2');
  const subtitle = h('div', {class: 'subtitle'});
  const status = h('span');
  const source = h('pre', {class: 'document-source mono'});
  const load = async () => {
    const record = await ctx.call(() => ctx.api.get('/api/document', {id: documentId}),
      {title: 'Could not load the document'});
    if (!record) {
      return;
    }
    title.textContent = record.name;
    subtitle.textContent = `${identity(record.provider).name} · revision ${record.revision}`;
    host.setTitle(record.name, identity(record.provider).name);
    mount(status, record.valid ? h('span', {class: 'badge ok'}, icon('check', null), 'Valid')
      : h('span', {class: 'badge error'}, icon('error', null), `${record.diagnostics.length} problem(s)`));
    source.textContent = record.source;
  };
  const unsubscribe = ctx.bus.on('document-changed', (record) => {
    if (record.id === documentId) {
      load();
    }
  });
  load();
  const element = h('div', {class: 'window-body', style: {display: 'flex', flexDirection: 'column'}},
    h('div', {class: 'window-header'},
      icon(iconName),
      h('div', {class: 'titles'}, title, subtitle),
      h('div', {class: 'actions'}, status)),
    h('div', {class: 'document-source-wrap'}, source));
  return {element, dispose: unsubscribe};
}
