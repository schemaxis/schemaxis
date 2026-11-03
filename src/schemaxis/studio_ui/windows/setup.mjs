// Copyright (C) 2026 David L F Gaden
// Application Setup keeps native locations in the current workspace.
import {h, icon, mount} from '../lib/dom.mjs';
import {avatar, identity} from '../shell/providers.mjs';

export const setupWindow = {
  type: 'setup', title: 'Application Setup', icon: 'gear', singleton: true, roles: ['admin'],
  create(ctx) {
    const list = h('div', {class: 'setup-list'});
    const result = h('div', {class: 'hint secondary-text', role: 'status'});
    let disposed = false;
    let applications = [];
    const render = () => {
      mount(list, applications.map((item) => {
        const path = h('input', {class: 'input mono', value: item.location || '',
          placeholder: item.locationKind === 'roots' ? 'Absolute installation root' : 'Absolute executable path',
          'aria-label': `${identity(item.provider).name} location`, disabled: ctx.role() !== 'admin'});
        const save = h('button', {class: 'button small', disabled: ctx.role() !== 'admin', onClick: async () => {
          save.disabled = true;
          try {
            const data = await ctx.api.post('/api/setup', {action: 'configure', provider: item.provider,
              location: path.value, role: ctx.role()});
            applications = data.applications;
            await ctx.refresh();
            render();
            ctx.notify.ok(`${identity(item.provider).name} configured`, {
              body: 'The location is saved in this workspace. Preview or run a case to verify native operation.',
            });
          } catch (error) {
            ctx.notify.error(error, {title: 'Application location was not saved'});
          } finally { save.disabled = ctx.role() !== 'admin'; }
        }}, 'Save location');
        return h('section', {class: 'card setup-application'},
          h('div', {class: 'setup-identity'}, avatar(item.provider),
            h('div', {class: 'grow'}, h('strong', {}, identity(item.provider).name),
              h('div', {class: 'secondary-text'}, item.locationKind === 'roots' ? 'Installation root' : 'Executable')),
            h('span', {class: `badge ${item.available ? 'ok' : 'warn'}`},
              item.available ? 'Located' : item.location ? 'Unavailable' : 'Not configured')),
          h('div', {class: 'setup-path'}, path, save));
      }));
    };
    const load = async () => {
      result.textContent = 'Checking application locations…';
      const data = await ctx.call(() => ctx.api.post('/api/setup', {action: 'read'}));
      if (!data || disposed) return;
      applications = data.applications;
      result.textContent = `${applications.filter((item) => item.available).length} of ${applications.length} located. `
        + 'Location checks do not start applications or certify native behaviour.';
      render();
    };
    const unsubscribe = ctx.store.watch((state) => state.settings, render);
    load();
    return {element: h('div', {class: 'window-body settings'},
      h('div', {class: 'settings-inner setup-inner'}, h('div', {class: 'chooser-header'},
        h('div', {}, h('h2', {}, 'Application Setup'),
          h('p', {class: 'secondary-text'}, 'Locate native applications for previews and workflow execution.')),
        h('button', {class: 'button', onClick: load}, icon('refresh'), 'Check locations')),
      result, list)),
    dispose: () => { disposed = true; unsubscribe(); }};
  },
};
