// Settings window, generated from the server's setting specification.

import {h, mount} from '../lib/dom.mjs';
import {setSetting} from '../shell/preferences.mjs';

const RANK = {user: 0, dev: 1, admin: 2};
const GROUPS = [
  {title: 'Appearance', prefix: ['role', 'theme']},
  {title: 'Editor', prefix: ['editor.']},
  {title: 'Outputs', prefix: ['output.']},
  {title: 'Execution', prefix: ['execution.']},
];

function control(ctx, key, spec, value, editable) {
  const save = (next) => setSetting(ctx, {[key]: next});
  if (spec.type === 'boolean') {
    return h('label', {class: 'checkbox'},
      h('input', {type: 'checkbox', checked: value, disabled: !editable,
        onChange: (event) => save(event.target.checked)}),
      spec.label);
  }
  let input;
  if (spec.type === 'enum') {
    input = h('select', {class: 'select', disabled: !editable, onChange: (event) => save(event.target.value)},
      spec.values.map((item) => h('option', {value: item, selected: item === value}, item)));
  } else {
    input = h('input', {class: 'input', disabled: !editable, value: String(value),
      type: spec.type === 'integer' ? 'number' : 'text',
      min: spec.minimum, max: spec.maximum,
      onChange: (event) => save(spec.type === 'integer' ? Number(event.target.value) : event.target.value)});
  }
  return h('div', {class: 'field'}, h('label', {}, spec.label), input,
    editable ? null : h('div', {class: 'hint'}, `Managed by the ${spec.scope} role.`));
}

function namingPreview(settings) {
  const width = settings.values['output.indexWidth'];
  const pattern = settings.values['output.namingPattern'];
  const example = pattern
    .replace('{index}', '324'.padStart(width, '0'))
    .replace('{operation}', 'slices')
    .replace('{output}', 'pressure')
    .replace(/\{param:([^}]+)\}/g, (match, name) => `${name}_1p815`)
    .replace(/\{axis:([^}]+)\}/g, 'm0p325')
    .replace('{artifact}', '0')
    .replace('{ext}', '.png');
  return h('div', {class: 'hint'}, 'Example: ', h('code', {}, example));
}

export const settingsWindow = {
  type: 'settings',
  title: 'Settings',
  icon: 'gear',
  singleton: true,
  create(ctx) {
    const body = h('div', {class: 'settings-inner'});
    const render = () => {
      const settings = ctx.store.get().settings;
      if (!settings) {
        mount(body, h('div', {class: 'empty-state'}, 'Settings are unavailable.'));
        return;
      }
      const role = settings.values.role;
      mount(body, h('h2', {}, 'Settings'), GROUPS.map((group) => {
        const keys = Object.keys(settings.specification).filter((key) => group.prefix.some((prefix) => key === prefix
          || (prefix.endsWith('.') && key.startsWith(prefix))));
        return h('section', {class: 'card settings-group'},
          h('h3', {}, group.title),
          keys.map((key) => {
            const spec = settings.specification[key];
            return control(ctx, key, spec, settings.values[key], RANK[role] >= RANK[spec.scope]);
          }),
          group.title === 'Outputs' ? namingPreview(settings) : null,
          group.title === 'Appearance' ? h('p', {class: 'hint muted'},
            'Roles change which windows are shown. They are not access control: this Studio runs locally for '
            + 'one person.') : null);
      }));
      if (role === 'admin') {
        body.append(h('section', {class: 'card settings-group'}, h('h3', {}, 'Native applications'),
          h('p', {class: 'secondary-text'}, 'Locate executables and installation roots used by this workspace.'),
          h('button', {class: 'button', onClick: () => ctx.windows.open('setup')}, 'Open Application Setup')));
      }
    };
    const unsubscribe = ctx.store.watch((state) => state.settings, render);
    render();
    return {element: h('div', {class: 'window-body settings'}, body), dispose: unsubscribe};
  },
};
