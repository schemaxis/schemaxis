// Copyright (C) 2026 David L F Gaden
// Port editing: add or edit an input/output port from suggest_ports, and expose inputs as parameters.

import {h, mount} from '../../lib/dom.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {DATA_KINDS, uniqueId} from './geometry.mjs';
import {ID_PATTERN} from './dialogs.mjs';

const PARAMETER_PATTERN = /^[A-Za-z][A-Za-z0-9_.-]*$/;

function preview(value) {
  const text = JSON.stringify(value);
  return text && text.length > 48 ? `${text.slice(0, 45)}…` : text;
}

/** Form controls for the descriptive data metadata shared by both sides. */
function dataFields(initial = {}) {
  const kind = h('select', {class: 'select', name: 'dataKind'},
    h('option', {value: ''}, 'Unspecified'),
    DATA_KINDS.map((item) => h('option', {value: item, selected: initial.kind === item}, item)));
  const formats = h('input', {class: 'input', name: 'formats', placeholder: 'e.g. step, vtu',
    value: (initial.formats || []).join(', ')});
  const units = h('input', {class: 'input', name: 'units', placeholder: 'e.g. m, Pa', value: initial.units || ''});
  const layout = h('select', {class: 'select', name: 'layout'},
    h('option', {value: ''}, 'Unspecified'),
    h('option', {value: 'interleaved', selected: initial.layout === 'interleaved'}, 'Interleaved x0 y0 z0 x1 …'),
    h('option', {value: 'planar', selected: initial.layout === 'planar'}, 'Planar x0 x1 … y0 y1 …'));
  const streaming = h('input', {type: 'checkbox', name: 'streaming', checked: initial.streaming === true});
  const contiguous = h('input', {type: 'checkbox', name: 'contiguous', checked: initial.contiguous === true});
  const element = h('fieldset', {class: 'dz-fieldset'},
    h('legend', {}, 'Data description'),
    h('div', {class: 'dz-two'},
      h('div', {class: 'field'}, h('label', {}, 'Data kind'), kind),
      h('div', {class: 'field'}, h('label', {}, 'Formats'), formats)),
    h('div', {class: 'dz-two'},
      h('div', {class: 'field'}, h('label', {}, 'Units'), units),
      h('div', {class: 'field'}, h('label', {}, 'Component layout'), layout)),
    h('div', {class: 'dz-checks'},
      h('label', {class: 'checkbox'}, streaming, 'Streaming'),
      h('label', {class: 'checkbox'}, contiguous, 'Contiguous')),
    h('div', {class: 'hint'}, 'Descriptive only: mismatches become warnings; the native planner stays authoritative.'));
  return {
    element, kind,
    value() {
      const data = {};
      if (kind.value) {
        data.kind = kind.value;
      }
      const list = formats.value.split(',').map((item) => item.trim()).filter(Boolean);
      if (list.length) {
        data.formats = [...new Set(list)];
      }
      if (units.value.trim()) {
        data.units = units.value.trim();
      }
      if (layout.value) {
        data.layout = layout.value;
      }
      if (streaming.checked) {
        data.streaming = true;
      }
      if (contiguous.checked) {
        data.contiguous = true;
      }
      return data;
    },
  };
}

function choiceList(items, render, onChoose) {
  const list = h('div', {class: 'dz-choices', role: 'radiogroup'});
  let chosen = null;
  const buttons = items.map((item, index) => h('button', {
    type: 'button', class: 'dz-choice', role: 'radio', 'aria-checked': 'false',
    onClick: () => {
      chosen = index;
      for (const [position, button] of buttons.entries()) {
        button.setAttribute('aria-checked', String(position === index));
      }
      onChoose(item);
    },
  }, render(item)));
  mount(list, buttons.length ? buttons : h('div', {class: 'muted dz-choices-empty'}, 'No suggestions.'));
  return {element: list, chosen: () => chosen, pick: (index) => buttons[index] && buttons[index].click()};
}

/**
 * Add or edit one port. side is 'inputs' or 'outputs'; existing is the current spec when editing.
 * Resolves with {name, spec} or null.
 */
export async function portDialog(ctx, model, operation, side, {existingName, existing} = {}) {
  const suggestions = (await model.suggestions(operation)) || {inputs: [], outputs: [], notes: []};
  const ports = (model.store.get().projection.ports[operation] || {})[side] || {};
  const taken = Object.keys(ports).filter((name) => name !== existingName);
  const name = h('input', {class: 'input', name: 'portName', value: existingName || '', spellcheck: 'false'});
  const error = h('div', {class: 'error-text', role: 'alert'});
  const data = dataFields(existing && existing.data);
  const body = [];
  let target = existing && existing.target;
  let kind = existing ? existing.kind : 'artifact';
  const artifact = h('input', {class: 'input', type: 'number', min: '0', step: '1', name: 'artifact',
    value: existing && side === 'outputs' ? String(existing.artifact) : '0'});
  const outputKind = h('select', {class: 'select', name: 'outputKind'},
    h('option', {value: 'artifact', selected: kind === 'artifact'}, 'Artifact (file)'),
    h('option', {value: 'value', selected: kind === 'value'}, 'Value (number inside an artifact)'));
  const valuePath = h('input', {class: 'input mono', name: 'valuePath', placeholder: '/rows/0/0',
    value: (existing && existing.valuePath) || ''});
  const valueField = h('div', {class: 'field'}, h('label', {}, 'Value path'), valuePath,
    h('div', {class: 'hint'}, 'JSON pointer within the producer artifact. Not knowable before execution; '
      + 'choose it from a verified artifact.'));
  const syncValue = () => {
    valueField.hidden = outputKind.value !== 'value';
  };
  outputKind.addEventListener('change', syncValue);

  if (side === 'inputs') {
    const candidates = suggestions.inputs.filter((item) => !item.declared || item.target === target);
    const choices = choiceList(candidates, (item) => [
      h('span', {class: 'dz-choice-main'}, h('span', {class: 'mono'}, item.target),
        h('span', {class: 'badge'}, item.kind)),
      h('span', {class: 'dz-choice-sub'}, `current ${preview(item.current)}`
        + (item.dataKinds && item.dataKinds.length ? ` · accepts ${item.dataKinds.join(', ')}` : '')),
    ], (item) => {
      target = item.target;
      kind = item.kind;
      if (!name.value || !existingName) {
        name.value = uniqueId(item.name, taken);
      }
      if (item.dataKindKnown && item.dataKinds.length === 1 && !data.kind.value) {
        data.kind.value = item.dataKinds[0];
      }
    });
    body.push(h('div', {class: 'field'}, h('label', {}, 'Target input'), choices.element,
      h('div', {class: 'hint'}, 'An input port drives exactly one runtime input of this operation.')));
    const current = candidates.findIndex((item) => item.target === target);
    if (current >= 0) {
      queueMicrotask(() => choices.pick(current));
    }
  } else {
    const choices = choiceList(suggestions.outputs, (item) => [
      h('span', {class: 'dz-choice-main'}, h('span', {}, item.name), h('span', {class: 'badge'},
        `artifact ${item.artifact}`)),
      h('span', {class: 'dz-choice-sub'}, `${item.filter || 'output'} node ${item.node}`
        + (item.nodeKinds.length ? ` · ${item.nodeKinds.join(', ')}` : '')),
    ], (item) => {
      artifact.value = String(item.artifact);
      if (!existingName) {
        name.value = uniqueId(item.name, taken);
      }
      const known = item.nodeKinds.find((value) => DATA_KINDS.includes(value));
      if (known && !data.kind.value) {
        data.kind.value = known;
      }
    });
    body.push(h('div', {class: 'field'}, h('label', {}, 'Suggested outputs'), choices.element,
      h('div', {class: 'hint'}, 'Artifact indices assume one publication per declared output, in order; '
        + 'the producer receipt is authoritative.')));
    body.push(h('div', {class: 'dz-two'},
      h('div', {class: 'field'}, h('label', {}, 'Artifact index'), artifact),
      h('div', {class: 'field'}, h('label', {}, 'Port kind'), outputKind)));
    body.push(valueField);
    syncValue();
  }

  const title = `${existingName ? 'Edit' : 'Add'} ${side === 'inputs' ? 'input' : 'output'} port`;
  return openDialog({
    title,
    wide: true,
    content: h('div', {class: 'dz-dialog-grid'},
      h('p', {class: 'secondary-text'}, `Operation ${operation}`),
      body,
      h('div', {class: 'field'}, h('label', {}, 'Port name'), name),
      data.element,
      error),
    actions: [
      {label: 'Cancel', run: () => null},
      {label: existingName ? 'Save port' : 'Add port', primary: true, run: () => {
        const portName = name.value.trim();
        if (!ID_PATTERN.test(portName)) {
          error.textContent = 'Port names start with a letter and use letters, digits, - or _.';
          return false;
        }
        if (taken.includes(portName)) {
          error.textContent = 'This operation already has a port with that name.';
          return false;
        }
        const spec = {};
        if (side === 'inputs') {
          if (!target) {
            error.textContent = 'Choose the input this port drives.';
            return false;
          }
          Object.assign(spec, {target, kind});
        } else {
          const index = Number(artifact.value);
          if (!Number.isInteger(index) || index < 0) {
            error.textContent = 'The artifact index is a nonnegative integer.';
            return false;
          }
          Object.assign(spec, {artifact: index, kind: outputKind.value});
          if (outputKind.value === 'value') {
            if (!valuePath.value.trim().startsWith('/')) {
              error.textContent = 'Value ports need a JSON pointer such as /rows/0/0.';
              return false;
            }
            spec.valuePath = valuePath.value.trim();
          }
        }
        const described = data.value();
        if (Object.keys(described).length) {
          spec.data = described;
        }
        if (existing && existing.label) {
          spec.label = existing.label;
        }
        return {name: portName, spec};
      }},
    ],
  });
}

/** Expose a literal runtime input as a template parameter. Resolves with the request params or null. */
export async function exposeDialog(ctx, model, operation, suggestion) {
  const existing = Object.keys(model.store.get().projection.parameters || {});
  const fallback = suggestion.name || 'parameter';
  const id = h('input', {class: 'input', name: 'parameterId', value: uniqueId(fallback, existing),
    spellcheck: 'false'});
  const label = h('input', {class: 'input', name: 'label', value: fallback});
  const units = h('input', {class: 'input', name: 'units', placeholder: 'optional'});
  const minimum = h('input', {class: 'input', type: 'number', step: 'any', name: 'minimum', placeholder: 'none'});
  const maximum = h('input', {class: 'input', type: 'number', step: 'any', name: 'maximum', placeholder: 'none'});
  const group = h('select', {class: 'select', name: 'group'},
    h('option', {value: 'settings'}, 'Settings'), h('option', {value: 'dimensions'}, 'Dimensions (geometry)'));
  const error = h('div', {class: 'error-text', role: 'alert'});
  const numeric = typeof suggestion.current === 'number';
  return openDialog({
    title: 'Expose as parameter',
    content: h('div', {class: 'dz-dialog-grid'},
      h('p', {class: 'secondary-text'}, 'Moves this literal into workflow ', h('code', {}, '/settings'),
        ' and replaces it with a reference, so case files can set it.'),
      h('dl', {class: 'kv'}, h('dt', {}, 'Input'), h('dd', {class: 'mono'}, suggestion.target),
        h('dt', {}, 'Current value'), h('dd', {class: 'mono'}, preview(suggestion.current))),
      h('div', {class: 'dz-two'},
        h('div', {class: 'field'}, h('label', {}, 'Parameter ID'), id),
        h('div', {class: 'field'}, h('label', {}, 'Label'), label)),
      numeric ? h('div', {class: 'dz-three'},
        h('div', {class: 'field'}, h('label', {}, 'Units'), units),
        h('div', {class: 'field'}, h('label', {}, 'Minimum'), minimum),
        h('div', {class: 'field'}, h('label', {}, 'Maximum'), maximum)) : null,
      h('div', {class: 'field'}, h('label', {}, 'Store under'), group),
      error),
    actions: [
      {label: 'Cancel', run: () => null},
      {label: 'Expose', primary: true, run: () => {
        const parameterId = id.value.trim();
        if (!PARAMETER_PATTERN.test(parameterId) || existing.includes(parameterId)) {
          error.textContent = 'Use a new ID starting with a letter (letters, digits, _, . or -).';
          return false;
        }
        const spec = {label: label.value.trim() || parameterId, group: group.value};
        if (numeric && units.value.trim()) {
          spec.units = units.value.trim();
        }
        const constraints = {};
        if (numeric && minimum.value !== '') {
          constraints.minimum = Number(minimum.value);
        }
        if (numeric && maximum.value !== '') {
          constraints.maximum = Number(maximum.value);
        }
        if (Object.keys(constraints).length) {
          spec.constraints = constraints;
        }
        return {operation, pointer: suggestion.target, parameterId, spec};
      }},
    ],
  });
}
