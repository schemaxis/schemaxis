// Copyright (C) 2026 David L F Gaden
// Loop inspector: members and a simple controller form generated from projection.algorithms.

import {h, icon, mount} from '../../lib/dom.mjs';
import {section} from './inspector.mjs';

const FIELDS = [
  {key: 'maxIterations', label: 'Maximum iterations', step: '1', min: '1', max: '1000', integer: true,
    hint: 'An integer from 1 to 1000.'},
  {key: 'absoluteTolerance', label: 'Absolute tolerance', step: 'any', min: '0', positive: true,
    hint: 'Raw feedback residual, before relaxation. Greater than zero.'},
  {key: 'relativeTolerance', label: 'Relative tolerance', step: 'any', min: '0',
    hint: 'Zero or more.'},
  {key: 'relaxation', label: 'Relaxation factor', step: 'any', min: '0', max: '1', positive: true,
    only: 'constant-relaxation',
    hint: 'Greater than zero and at most one.'},
];

function check(field, raw) {
  if (raw === '') {
    return 'Required.';
  }
  const value = Number(raw);
  if (!Number.isFinite(value)) {
    return 'Enter a finite number.';
  }
  if (field.integer && (!Number.isInteger(value) || value < 1 || value > 1000)) {
    return field.hint;
  }
  if (field.positive && value <= 0) {
    return field.hint;
  }
  if (value < 0 || (field.max && value > Number(field.max))) {
    return field.hint;
  }
  return '';
}

export function loopPanel(model, actions, loop) {
  if (!loop) {
    return h('div', {class: 'dz-inspector-body'});
  }
  const algorithms = model.store.get().projection.algorithms || [];
  const configurable = algorithms.filter((item) => item.configurable);
  const future = algorithms.filter((item) => !item.configurable);
  const saved = loop.config || null;
  let algorithm = (saved && saved.algorithm) || (configurable[0] && configurable[0].id);
  const values = {...(configurable.find((item) => item.id === algorithm) || {}).defaults, ...(saved || {})};
  const select = h('select', {class: 'select', name: 'algorithm', 'aria-label': 'Algorithm'},
    configurable.map((item) => h('option', {value: item.id, selected: item.id === algorithm}, item.label)));
  const reason = h('p', {class: 'hint'});
  const fields = h('div', {class: 'dz-loop-fields'});
  const error = h('div', {class: 'error-text', role: 'alert'});
  const inputs = {};

  const renderFields = () => {
    const record = configurable.find((item) => item.id === algorithm);
    reason.textContent = record ? record.reason : '';
    const defaults = record ? record.defaults : {};
    const rows = [];
    for (const field of FIELDS) {
      if (field.only && field.only !== algorithm) {
        continue;
      }
      const current = inputs[field.key] ? inputs[field.key].value : values[field.key] ?? defaults[field.key];
      const input = h('input', {class: 'input', type: 'number', name: field.key, step: field.step, min: field.min,
        max: field.max, value: current === undefined ? '' : String(current)});
      const message = h('div', {class: 'error-text'});
      input.addEventListener('input', () => {
        message.textContent = check(field, input.value);
      });
      inputs[field.key] = input;
      rows.push(h('div', {class: 'field'}, h('label', {}, field.label), input,
        h('div', {class: 'hint'}, field.hint), message));
    }
    mount(fields, rows);
  };
  select.addEventListener('change', () => {
    algorithm = select.value;
    renderFields();
  });
  renderFields();

  const save = async () => {
    error.textContent = '';
    const config = {algorithm};
    for (const field of FIELDS) {
      if (field.only && field.only !== algorithm) {
        continue;
      }
      const problem = check(field, inputs[field.key].value);
      if (problem) {
        error.textContent = `${field.label}: ${problem}`;
        inputs[field.key].focus();
        return;
      }
      config[field.key] = Number(inputs[field.key].value);
    }
    await actions.configureLoop(loop.id, config);
  };

  return h('div', {class: 'dz-inspector-body'},
    h('div', {class: 'dz-inspector-title'},
      h('div', {class: 'dz-inspector-icon loop'}, icon('loop')),
      h('div', {}, h('h3', {}, 'Feedback loop'), h('div', {class: 'subtitle mono'}, loop.id.slice(0, 17))),
      h('span', {class: ['badge', loop.status === 'configured' ? 'ok' : 'loop']},
        loop.status === 'configured' ? 'Configured' : 'Needs settings')),
    h('div', {class: 'dz-note'}, icon('info'), h('div', {},
      h('strong', {}, 'Loop execution is not available yet. '),
      'Settings are saved with the design so the loop is ready when a qualified feedback executor arrives. '
      + 'Compile and export need an acyclic design.')),
    section('Members', h('div', {class: 'dz-members'}, loop.members.map((member) => h('button', {
      class: 'dz-member', onClick: () => model.select({kind: 'nodes', ids: [member]})}, member))),
    h('div', {class: 'muted'}, `${loop.edgeIds.length} connections close this loop.`)),
    section('Controller',
      h('div', {class: 'field'}, h('label', {}, 'Algorithm'), select), reason, fields, error,
      h('div', {class: 'dz-sticky-actions'},
        h('button', {class: 'button primary', onClick: save}, icon('check'), 'Save loop settings'))),
    future.length ? section('Future methods', h('ul', {class: 'dz-future'}, future.map((item) => h('li', {},
      h('details', {},
        h('summary', {}, h('span', {}, item.label), h('span', {class: 'badge'}, 'future')),
        h('p', {class: 'secondary-text'}, item.reason),
        h('div', {class: 'dz-requires-title'}, 'Requires'),
        h('ul', {class: 'dz-requires'}, item.requires.map((text) => h('li', {}, text)))))))) : null);
}
