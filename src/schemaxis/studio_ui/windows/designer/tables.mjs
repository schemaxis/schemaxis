// Bottom tabs: template Parameters and named Outputs, edited as tables and saved as a whole.

import {h, icon, mount} from '../../lib/dom.mjs';
import {TEMPLATE_ID_PATTERN} from './dialogs.mjs';

const OUTPUT_KINDS = ['table', 'image', 'video', 'geometry', 'text', 'audio', 'archive', 'value'];

function cellInput(value, {type = 'text', placeholder = '', label, mono = false, step} = {}) {
  return h('input', {class: ['input', 'dz-cell-input', mono && 'mono'], type, placeholder, step,
    'aria-label': label, value: value === undefined || value === null ? '' : String(value)});
}

function numberOrUndefined(text) {
  if (text.trim() === '') {
    return undefined;
  }
  const value = Number(text);
  return Number.isFinite(value) ? value : NaN;
}

function emptyRow(columns, text) {
  return h('tr', {}, h('td', {colspan: String(columns), class: 'dz-table-empty'}, text));
}

function footer(dirty, onSave, onReset, extra) {
  return h('div', {class: 'dz-table-footer'},
    extra,
    h('span', {class: 'grow'}),
    h('span', {class: ['dz-dirty', dirty && 'visible']}, 'Unsaved changes'),
    h('button', {class: 'button small', disabled: !dirty, onClick: onReset}, 'Discard'),
    h('button', {class: 'button primary small', disabled: !dirty, onClick: onSave}, icon('check'), 'Save'));
}

/** Parameters: label, units, default and limits are editable; IDs and targets come from Expose. */
export function createParametersTab(ctx, model) {
  const element = h('div', {class: 'dz-tab-panel'});
  let draft = null;
  let baseline = null;

  const render = () => {
    const projection = model.store.get().projection;
    if (!projection) {
      mount(element);
      return;
    }
    const source = projection.parameters || {};
    if (!draft) {
      draft = structuredClone(source);
      baseline = JSON.stringify(source);
    }
    const dirty = JSON.stringify(draft) !== JSON.stringify(source);
    const rows = Object.entries(draft).map(([id, spec]) => {
      const numeric = ['number', 'integer', 'vector'].includes(spec.kind);
      const constraints = spec.constraints || {};
      const set = (field, value) => {
        if (value === undefined || value === '') {
          delete spec[field];
        } else {
          spec[field] = value;
        }
        render();
      };
      const setLimit = (field, text) => {
        const value = numberOrUndefined(text);
        const next = {...constraints};
        if (value === undefined) {
          delete next[field];
        } else {
          next[field] = value;
        }
        if (Object.keys(next).length) {
          spec.constraints = next;
        } else {
          delete spec.constraints;
        }
        render();
      };
      const label = cellInput(spec.label, {label: `Label of ${id}`});
      label.addEventListener('change', () => set('label', label.value.trim() || id));
      const units = cellInput(spec.units, {label: `Units of ${id}`, placeholder: numeric ? '—' : 'n/a'});
      units.disabled = !numeric;
      units.addEventListener('change', () => set('units', units.value.trim()));
      const fallback = cellInput(spec.default === undefined ? '' : JSON.stringify(spec.default),
        {label: `Default of ${id}`, placeholder: 'current value', mono: true});
      fallback.addEventListener('change', () => {
        if (!fallback.value.trim()) {
          set('default', undefined);
          return;
        }
        try {
          set('default', JSON.parse(fallback.value));
        } catch {
          set('default', fallback.value);
        }
      });
      const minimum = cellInput(constraints.minimum, {type: 'number', step: 'any', label: `Minimum of ${id}`});
      minimum.disabled = !numeric;
      minimum.addEventListener('change', () => setLimit('minimum', minimum.value));
      const maximum = cellInput(constraints.maximum, {type: 'number', step: 'any', label: `Maximum of ${id}`});
      maximum.disabled = !numeric;
      maximum.addEventListener('change', () => setLimit('maximum', maximum.value));
      return h('tr', {},
        h('td', {class: 'mono strong'}, id),
        h('td', {}, label),
        h('td', {}, h('span', {class: 'badge'}, spec.kind)),
        h('td', {}, units),
        h('td', {}, fallback),
        h('td', {class: 'dz-limits'}, minimum, h('span', {class: 'muted'}, '…'), maximum),
        h('td', {class: 'mono muted'}, spec.target ? spec.target.pointer : ''),
        h('td', {}, h('button', {class: 'button ghost small icon-only', 'aria-label': `Remove parameter ${id}`,
          title: 'Remove parameter (its value stays in workflow settings)', onClick: () => {
            delete draft[id];
            render();
          }}, icon('close'))));
    });
    mount(element,
      h('div', {class: 'dz-table-wrap'}, h('table', {class: 'dz-table'},
        h('thead', {}, h('tr', {}, ['ID', 'Label', 'Kind', 'Units', 'Default', 'Limits', 'Target', '']
          .map((text) => h('th', {}, text)))),
        h('tbody', {}, rows.length ? rows : emptyRow(8, 'No parameters yet. Select an operation and use '
          + '“Expose as parameter” in the inspector.')))),
      footer(dirty, async () => {
        if (JSON.stringify(model.store.get().projection.parameters || {}) !== baseline) {
          ctx.notify.warn('Parameters changed elsewhere', {body: 'Your edits are kept. Discard to load the latest '
            + 'parameters before editing them again.'});
          return;
        }
        const result = await model.action('set_parameters', {parameters: draft}, {title: 'Could not save parameters'});
        if (result) {
          draft = null;
          render();
          ctx.notify.ok('Parameters saved');
        }
      }, () => {
        draft = null;
        render();
      }, h('span', {class: 'muted'}, 'Parameters are the values users set in a case file.')));
  };

  const unsubscribe = model.store.watch((state) => state.projection, () => {
    if (!draft || JSON.stringify(draft) === baseline) draft = null;
    render();
  });
  render();
  return {element, isDirty: () => draft !== null && JSON.stringify(draft) !== baseline, dispose: unsubscribe};
}

/** Named outputs: alias → operation, artifact, kind, pointer and units. */
export function createOutputsTab(ctx, model) {
  const element = h('div', {class: 'dz-tab-panel'});
  let draft = null;
  let baseline = null;
  const error = h('span', {class: 'error-text'});

  const render = () => {
    const projection = model.store.get().projection;
    if (!projection) {
      mount(element);
      return;
    }
    const source = Object.entries(projection.outputs || {}).map(([alias, spec]) => ({alias, ...spec}));
    if (!draft) {
      draft = structuredClone(source);
      baseline = JSON.stringify(source);
    }
    const dirty = JSON.stringify(draft) !== JSON.stringify(source);
    const operations = projection.nodes.map((node) => node.id);
    const rows = draft.map((row, index) => {
      const field = (key, input, parse = (value) => value) => {
        input.addEventListener('change', () => {
          const value = parse(input.value);
          if (value === undefined || value === '') {
            delete row[key];
          } else {
            row[key] = value;
          }
          render();
        });
        return input;
      };
      const operation = h('select', {class: 'select dz-cell-input', 'aria-label': 'Operation'},
        operations.map((id) => h('option', {value: id, selected: id === row.operation}, id)));
      const kind = h('select', {class: 'select dz-cell-input', 'aria-label': 'Kind'},
        [...new Set([...OUTPUT_KINDS, row.kind].filter(Boolean))].map((item) => h('option', {value: item,
          selected: item === row.kind}, item)));
      return h('tr', {},
        h('td', {}, field('alias', cellInput(row.alias, {label: 'Alias', mono: true}), (value) => value.trim())),
        h('td', {}, field('operation', operation)),
        h('td', {}, field('artifact', cellInput(row.artifact, {type: 'number', label: 'Artifact index'}),
          (value) => (value === '' ? 0 : Number(value)))),
        h('td', {}, field('kind', kind)),
        h('td', {}, field('pointer', cellInput(row.pointer, {label: 'Pointer', mono: true, placeholder: 'optional'}),
          (value) => value.trim())),
        h('td', {}, field('units', cellInput(row.units, {label: 'Units', placeholder: 'optional'}),
          (value) => value.trim())),
        h('td', {}, h('button', {class: 'button ghost small icon-only', 'aria-label': `Remove output ${row.alias}`,
          onClick: () => {
            draft.splice(index, 1);
            render();
          }}, icon('close'))));
    });
    const add = h('button', {class: 'button small', disabled: !operations.length, onClick: () => {
      const taken = new Set(draft.map((row) => row.alias));
      let number = draft.length + 1;
      while (taken.has(`output${number}`)) {
        number += 1;
      }
      draft.push({alias: `output${number}`, operation: operations[0], artifact: 0, kind: 'table'});
      render();
    }}, icon('plus'), 'Add output');
    mount(element,
      h('div', {class: 'dz-table-wrap'}, h('table', {class: 'dz-table'},
        h('thead', {}, h('tr', {}, ['Alias', 'Operation', 'Artifact', 'Kind', 'Pointer', 'Units', '']
          .map((text) => h('th', {}, text)))),
        h('tbody', {}, rows.length ? rows : emptyRow(7, 'No named outputs. Name the results users should see, '
          + 'for example “drag” or “mesh”.')))),
      footer(dirty, async () => {
        error.textContent = '';
        const current = Object.entries(model.store.get().projection.outputs || {})
          .map(([alias, spec]) => ({alias, ...spec}));
        if (JSON.stringify(current) !== baseline) {
          error.textContent = 'Outputs changed elsewhere. Your edits are kept; discard to load the latest outputs.';
          return;
        }
        const outputs = {};
        for (const row of draft) {
          if (!TEMPLATE_ID_PATTERN.test(row.alias || '') || outputs[row.alias]) {
            error.textContent = `Alias “${row.alias}” must be unique and start with a letter.`;
            return;
          }
          const {alias, ...spec} = row;
          outputs[alias] = spec;
        }
        const result = await model.action('set_outputs', {outputs}, {title: 'Could not save named outputs'});
        if (result) {
          draft = null;
          render();
          ctx.notify.ok('Named outputs saved');
        }
      }, () => {
        draft = null;
        render();
      }, [add, error]));
  };

  const unsubscribe = model.store.watch((state) => state.projection, () => {
    if (!draft || JSON.stringify(draft) === baseline) draft = null;
    render();
  });
  render();
  return {element, isDirty: () => draft !== null && JSON.stringify(draft) !== baseline, dispose: unsubscribe};
}
