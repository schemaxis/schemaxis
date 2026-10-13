import {h, mount} from '../../lib/dom.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {pipelineChoices} from './authoring-defaults.mjs';

export function referenceControl({documentValue, reference, initial, label, kinds, allowPort = false, onChange = () => {}}) {
  const multiple = Boolean(reference.multiple);
  const choices = pipelineChoices(documentValue, reference.kind, kinds);
  let values = (multiple ? Array.isArray(initial) ? initial : [] : initial ? [initial] : [])
    .filter(value => typeof value === 'string' || typeof value?.node === 'string');
  const name = value => typeof value === 'string' ? value : value.node;
  const select = h('select', {class: 'input', 'aria-label': label, multiple,
    ...(multiple ? {size: Math.min(6, Math.max(2, choices.length))} : {}), onChange: () => {
      values = [...select.selectedOptions].filter(option => option.value).map(option => option.value);
      notify();
    }});
  const explicitPort = h('input', {type: 'checkbox', checked: typeof values[0] === 'object', onChange: notify});
  const port = h('input', {class: 'input', type: 'number', min: 0, step: 1, value: values[0]?.port ?? 0,
    'aria-label': `${label} output port`, onInput: notify});
  function render() {
    const missing = values.map(name).filter(value => !choices.some(node => node.id === value));
    mount(select, multiple ? null : h('option', {value: ''}, 'Choose an input…'),
      choices.map(node => h('option', {value: node.id, selected: values.some(value => name(value) === node.id)}, `${node.id} · ${node.filter || node.kind || 'Node'}`)),
      missing.map(value => h('option', {value, selected: true}, `${value} · unavailable`)));
    if (!multiple && !values.length) select.value = '';
  }
  function read() {
    if (multiple) return values;
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
          .map(node => h('label', {class: 'pipeline-picker-row'}, h('input', {type: multiple ? 'checkbox' : 'radio', name: 'pipeline-choice',
            checked: picked.has(node.id), onChange: event => {
              if (!multiple) picked.clear();
              if (event.target.checked) picked.add(node.id); else picked.delete(node.id);
            }}), h('span', {}, h('strong', {}, node.id), h('small', {}, node.filter || node.kind || 'Node'),
              h('small', {}, Object.entries(node.inputs || {}).map(([port, value]) => `${port}: ${JSON.stringify(value)}`).join(' · '))))));
      }
      update();
      const result = await openDialog({title: multiple ? 'Choose pipeline inputs' : 'Choose pipeline input', content: h('div', {}, search, list,
        !choices.length ? h('p', {}, 'Add a compatible source to the pipeline first.') : null),
        actions: [{label: 'Cancel', run: () => null}, {label: 'Use selection', primary: true, run: () => [...picked]}]});
      if (result && element.isConnected) { values = result; explicitPort.checked = false; render(); notify(); }
    }}, 'Browse pipeline…'),
    !multiple && allowPort ? h('details', {}, h('summary', {}, 'Advanced: output port'), h('label', {}, explicitPort, ' Use a specific output port'), port) : null);
  return {element, read};
}
