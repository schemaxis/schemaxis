// Copyright (C) 2026 David L F Gaden
import {h, mount} from '../../lib/dom.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {pipelineChoices} from './authoring-defaults.mjs';
import {subsetChips} from './subset-chips.mjs';

function referenceSubset(choices, initial, label, onChange, allowPort) {
  const offered = choices.map(node => ({id: node.id, label: `${node.id} · ${node.filter || 'Node'}`}));
  const references = new Map(choices.map(node => [node.id, node.id]));
  const selected = [];
  const explicit = new Map();
  for (const value of Array.isArray(initial) ? initial : []) {
    const base = typeof value === 'string' ? value : typeof value?.node === 'string'
      ? `${value.node}:port ${value.port}` : 'Authored reference';
    const id = selected.includes(base) ? `${base} · entry ${selected.length + 1}` : base;
    references.set(id, value);
    selected.push(id);
    if (typeof value?.node === 'string') explicit.set(id, {id, label: id});
  }
  const read = () => picker.read().map(id => references.get(id));
  const picker = subsetChips({choices: [...offered, ...explicit.values()], initial: selected,
    label, preserveOrder: true, onChange: () => onChange(read())});
  if (!allowPort) return {element: picker.element, read};
  const node = h('select', {class: 'input', 'aria-label': `${label} explicit-port node`},
    choices.map(item => h('option', {value: item.id}, item.id)));
  const port = h('input', {class: 'input', type: 'number', min: 0, step: 1, value: 0,
    'aria-label': `${label} explicit port`});
  const status = h('span', {role: 'status'});
  const add = h('button', {class: 'button small', type: 'button', onClick: () => {
    const output = Number(port.value);
    if (!node.value || port.value === '' || !Number.isSafeInteger(output) || output < 0) {
      status.textContent = 'Choose a node and enter a non-negative integer port.'; return;
    }
    const id = `${node.value}:port ${output}`;
    references.set(id, {node: node.value, port: output});
    explicit.set(id, {id, label: id});
    picker.setChoices([...offered, ...explicit.values()]);
    picker.add(id);
    status.textContent = '';
  }}, 'Add output port');
  const advanced = h('details', {}, h('summary', {}, 'Choose a specific output port'),
    h('div', {class: 'wb-button-row'}, node, port, add), status);
  return {element: h('div', {class: 'pipeline-reference-control'}, picker.element, advanced), read};
}

export function referenceControl({documentValue, reference, initial, label, kinds, allowPort = false, onChange = () => {}}) {
  const multiple = Boolean(reference.multiple);
  const choices = pipelineChoices(documentValue, reference.kind, kinds);
  if (multiple) return referenceSubset(choices, initial, label, onChange, allowPort);
  let values = (initial ? [initial] : [])
    .filter(value => typeof value === 'string' || typeof value?.node === 'string');
  const name = value => typeof value === 'string' ? value : value.node;
  const select = h('select', {class: 'input', 'aria-label': label, onChange: () => {
      values = [...select.selectedOptions].filter(option => option.value).map(option => option.value);
      notify();
    }});
  const explicitPort = h('input', {type: 'checkbox', checked: typeof values[0] === 'object', onChange: notify});
  const port = h('input', {class: 'input', type: 'number', min: 0, step: 1, value: values[0]?.port ?? 0,
    'aria-label': `${label} output port`, onInput: notify});
  function render() {
    const missing = values.map(name).filter(value => !choices.some(node => node.id === value));
    mount(select, h('option', {value: ''}, 'Choose an input…'),
      choices.map(node => h('option', {value: node.id, selected: values.some(value => name(value) === node.id)}, `${node.id} · ${node.filter || node.kind || 'Node'}`)),
      missing.map(value => h('option', {value, selected: true}, `${value} · unavailable`)));
    if (!values.length) select.value = '';
  }
  function read() {
    const value = values[0];
    return value && allowPort && explicitPort.checked ? {node: name(value), port: Number(port.value)} : value && name(value);
  }
  function notify() { onChange(read()); }
  render();
  const element = h('div', {class: 'pipeline-reference-control'}, select,
    h('button', {class: 'button small', type: 'button', onClick: async () => {
      const picked = new Set(values.map(name));
      const list = h('div', {class: 'pipeline-picker-list'});
      const search = h('input', {class: 'input', type: 'search', placeholder: 'Find a pipeline object…', 'aria-label': 'Find pipeline object', onInput: update});
      function update() {
        mount(list, choices.filter(node => `${node.id} ${node.filter}`.toLowerCase().includes(search.value.toLowerCase()))
          .map(node => h('label', {class: 'pipeline-picker-row'}, h('input', {type: 'radio', name: 'pipeline-choice',
            checked: picked.has(node.id), onChange: event => {
              picked.clear();
              if (event.target.checked) picked.add(node.id); else picked.delete(node.id);
            }}), h('span', {}, h('strong', {}, node.id), h('small', {}, node.filter || node.kind || 'Node'),
              h('small', {}, Object.entries(node.inputs || {}).map(([port, value]) => `${port}: ${JSON.stringify(value)}`).join(' · '))))));
      }
      update();
      const result = await openDialog({title: 'Choose pipeline input', content: h('div', {}, search, list,
        !choices.length ? h('p', {}, 'Add a compatible source to the pipeline first.') : null),
        actions: [{label: 'Cancel', run: () => null}, {label: 'Use selection', primary: true, run: () => [...picked]}]});
      if (result && element.isConnected) { values = result; explicitPort.checked = false; render(); notify(); }
    }}, 'Browse pipeline…'),
    allowPort ? h('details', {}, h('summary', {}, 'Advanced: output port'), h('label', {}, explicitPort, ' Use a specific output port'), port) : null);
  return {element, read};
}
