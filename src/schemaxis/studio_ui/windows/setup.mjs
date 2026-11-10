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
    const modules = h('div', {class: 'setup-modules'});
    const review = h('div', {role: 'status'});
    const postModule = async (values) => ctx.api.post('/api/setup', {...values, role: ctx.role()});
    const moduleAction = async (values, message) => {
      const data = await ctx.call(() => postModule(values), {title: 'Application module operation failed'});
      if (data) {
        ctx.notify.ok(message);
        await loadModules();
      }
      return data;
    };
    const loadModules = async () => {
      const data = await ctx.call(() => postModule({action: 'modules'}), {title: 'Could not inspect application cache'});
      if (!data || disposed) return;
      const disabled = ctx.role() !== 'admin';
      const backend = h('select', {class: 'input', 'aria-label': 'Workflow execution backend', disabled},
        h('option', {value: 'container'}, 'Packaged applications (default)'),
        h('option', {value: 'native'}, 'Existing system applications'));
      backend.value = data.settings.backend;
      const allowDownloads = h('input', {type: 'checkbox', checked: data.settings.allowDownloads, disabled});
      const manifest = h('input', {class: 'input mono', placeholder: 'Absolute path to a module manifest',
        'aria-label': 'Application module manifest', disabled});
      const preferences = h('section', {class: 'card'},
        h('h3', {}, 'Workflow applications'), backend,
        h('label', {}, allowDownloads, ' Download missing packaged applications when a workflow starts'),
        h('button', {class: 'button small', disabled, onClick: () => moduleAction({action: 'moduleSettings',
          backend: backend.value, allowDownloads: allowDownloads.checked}, 'Application preferences saved')}, 'Save preferences'),
        h('p', {class: 'secondary-text'}, 'Packaged workflows use matching application versions and dependencies. '
          + 'Existing system applications use the locations below. Interactive native sessions keep their existing setup.'),
        h('div', {class: 'setup-path'}, manifest,
          h('button', {class: 'button small', disabled, onClick: () => moduleAction({action: 'registerModule',
            manifest: manifest.value}, 'Application module registered')}, 'Register module')));
      const rows = data.modules.map((item) => {
        const keepDownload = h('input', {type: 'checkbox', disabled});
        const removeDownloads = h('input', {type: 'checkbox', disabled});
        const prepareClear = async () => {
          const plan = await ctx.call(() => postModule({action: 'cachePlan', module: item.id,
            downloads: removeDownloads.checked}), {title: 'Could not prepare cache cleanup'});
          if (!plan || disposed) return;
          const selected = plan.modules[0];
          mount(review, h('section', {class: 'card'}, h('h3', {}, `Clear ${identity(item.provider).name} cache?`),
            h('p', {}, selected.removeImage ? 'Remove the managed application runtime.'
              : 'The runtime is absent or was installed outside Schemaxis; it will be preserved.'),
            h('p', {}, selected.removeDownload ? 'Remove its saved download archive.' : 'Preserve saved downloads.'),
            h('p', {}, 'Keep application preferences, module registration, projects, input files and results.'),
            selected.blockedByContainers.length ? h('p', {}, 'Containers still reference this runtime. Finish and remove them before clearing it.') : null,
            h('button', {class: 'button', disabled: disabled || selected.blockedByContainers.length > 0,
              onClick: async () => {
                const result = await moduleAction({action: 'cacheClear', plan, confirmation: plan.confirmation}, 'Selected cache cleared');
                if (result) mount(review);
              }}, 'Clear selected cache'),
            h('button', {class: 'button', onClick: () => mount(review)}, 'Cancel')));
        };
        return h('section', {class: 'card'},
          h('strong', {}, `${identity(item.provider).name} ${item.applicationVersion}`),
          h('p', {class: 'secondary-text'}, `${item.installed ? 'Cached' : 'Not cached'} · runtime ${(item.imageBytes / 1048576).toFixed(1)} MB · `
            + `saved download ${(item.downloadBytes / 1048576).toFixed(1)} MB`),
          h('label', {}, keepDownload, ' Keep an offline download archive'),
          h('button', {class: 'button small', disabled, onClick: () => moduleAction({action: 'fetchModule',
            module: item.id, keepDownload: keepDownload.checked}, 'Application runtime ready')}, 'Fetch / restore'),
          h('label', {}, removeDownloads, ' Also remove saved downloads when clearing'),
          h('button', {class: 'button small', disabled, onClick: prepareClear}, 'Review cache cleanup'));
      });
      mount(modules, preferences, h('h3', {}, 'Application cache'),
        h('p', {class: 'secondary-text'}, data.sizeScope),
        ...(rows.length ? rows : [h('p', {}, 'No packaged application modules registered. Register a qualified module to get started.')]), review);
    };
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
      await loadModules();
    };
    const unsubscribe = ctx.store.watch((state) => state.settings, () => {
      render();
      loadModules();
    });
    load();
    return {element: h('div', {class: 'window-body settings'},
      h('div', {class: 'settings-inner setup-inner'}, h('div', {class: 'chooser-header'},
        h('div', {}, h('h2', {}, 'Application Setup'),
          h('p', {class: 'secondary-text'}, 'Locate native applications for previews and workflow execution.')),
        h('button', {class: 'button', onClick: load}, icon('refresh'), 'Check locations')),
      result, modules, h('h3', {}, 'Existing system applications'), list)),
    dispose: () => { disposed = true; unsubscribe(); }};
  },
};
