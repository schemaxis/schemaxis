// Collapsible bottom strip under the canvas: Parameters, Outputs, Naming and Source tabs.

import {h, icon, mount} from '../../lib/dom.mjs';
import {createOutputsTab, createParametersTab} from './tables.mjs';
import {createSamplesTab} from './samples.mjs';
import {createSourceTab} from './source.mjs';
import {DEFAULT_PATTERN, DEFAULT_WIDTH, TOKENS, preview, sampleEntries} from './naming.mjs';

const PREVIEW_LIMIT = 8;

function sampleValues(projection, record) {
  const workflow = record && record.document ? record.document.workflow : {};
  const values = {};
  for (const [id, spec] of Object.entries(projection.parameters || {})) {
    if ('default' in spec) {
      values[id] = spec.default;
      continue;
    }
    const parts = (spec.target && spec.target.pointer || '').split('/').slice(1);
    let value = workflow;
    for (const part of parts) {
      value = value && typeof value === 'object' ? value[part.replaceAll('~1', '/').replaceAll('~0', '~')] : undefined;
    }
    values[id] = value === undefined ? 1 : value;
  }
  return values;
}

function sampleAxes(record) {
  const axes = {};
  const list = record && record.document && record.document.workflow ? record.document.workflow.axes : null;
  for (const axis of Array.isArray(list) ? list : []) {
    if (axis && axis.name && Array.isArray(axis.values) && axis.values.length) {
      axes[axis.name] = axis.values[0];
    }
  }
  return axes;
}

function createNamingTab(ctx, model) {
  const pattern = h('input', {class: 'input mono dz-naming-input', 'aria-label': 'Naming pattern',
    spellcheck: 'false'});
  const width = h('input', {class: 'input dz-naming-width', type: 'number', min: '1', max: '12', step: '1',
    'aria-label': 'Index width'});
  const list = h('ol', {class: 'dz-naming-preview'});
  const message = h('div', {class: 'dz-naming-message'});
  const save = h('button', {class: 'button primary small'}, icon('check'), 'Save naming');
  let record = null;
  let saved = {};
  let initialised = false;

  const settingWidth = () => ctx.setting('output.indexWidth') || DEFAULT_WIDTH;
  const settingPattern = () => ctx.setting('output.namingPattern') || DEFAULT_PATTERN;

  const update = () => {
    const projection = model.store.get().projection;
    if (!projection) {
      return;
    }
    const entries = sampleEntries(projection, sampleValues(projection, record), sampleAxes(record));
    const result = preview(pattern.value, entries.length ? entries : [{operation: 'operation', output: 'output',
      ext: '.dat'}], Number(width.value));
    pattern.setAttribute('aria-invalid', String(Boolean(result.error)));
    if (result.error) {
      mount(message, h('span', {class: 'error-text'}, icon('error'), result.error));
    } else if (result.collisions.length) {
      mount(message, h('span', {class: 'warn-text'}, icon('alert'), `Collision: ${result.collisions.join(', ')}. `
        + 'Naming never overwrites; add {index} or another token.'));
    } else {
      mount(message, h('span', {class: 'muted'}, entries.length ? `${entries.length} sample output`
        + `${entries.length === 1 ? '' : 's'}; parameter values use defaults.` : 'Declare output ports or named '
        + 'outputs to preview real names.'));
    }
    mount(list, result.names.slice(0, PREVIEW_LIMIT).map((name) => h('li', {class: 'mono'}, name)),
      result.names.length > PREVIEW_LIMIT ? h('li', {class: 'muted'}, `+${result.names.length - PREVIEW_LIMIT} more`)
        : null);
    const changed = pattern.value !== (saved.pattern || settingPattern())
      || Number(width.value) !== (saved.indexWidth || settingWidth());
    save.disabled = Boolean(result.error) || !changed;
  };

  const load = async () => {
    const projection = model.store.get().projection;
    if (!projection) {
      return;
    }
    const next = projection.naming || {};
    if (!initialised || JSON.stringify(next) !== JSON.stringify(saved)) {
      initialised = true;
      saved = next;
      pattern.value = saved.pattern || ctx.setting('output.namingPattern') || DEFAULT_PATTERN;
      width.value = String(saved.indexWidth || settingWidth());
    }
    record = await model.record();
    update();
  };

  const insert = (token) => {
    const start = pattern.selectionStart ?? pattern.value.length;
    const end = pattern.selectionEnd ?? start;
    pattern.setRangeText(token, start, end, 'end');
    pattern.focus();
    if (token.includes(':')) {
      const colon = start + token.indexOf(':') + 1;
      pattern.setSelectionRange(colon, start + token.length - 1);
    }
    update();
  };

  pattern.addEventListener('input', update);
  width.addEventListener('input', update);
  save.addEventListener('click', async () => {
    const naming = {pattern: pattern.value};
    if (Number(width.value) !== settingWidth() || saved.indexWidth) {
      naming.indexWidth = Number(width.value);
    }
    const result = await model.action('set_naming', {naming}, {title: 'Could not save naming'});
    if (result) {
      ctx.notify.ok('Output naming saved');
    }
  });

  const element = h('div', {class: 'dz-tab-panel dz-naming'},
    h('div', {class: 'dz-naming-editor'},
      h('div', {class: 'field'}, h('label', {}, 'Pattern'), pattern),
      h('div', {class: 'field'}, h('label', {}, 'Index width'), width),
      save),
    h('div', {class: 'dz-token-row'}, h('span', {class: 'muted'}, 'Insert'), TOKENS.map((token) => h('button', {
      class: 'dz-token', type: 'button', onClick: () => insert(token)}, token))),
    message,
    list,
    h('p', {class: 'hint'}, 'Names apply after a run verifies: Studio links each verified artifact under named/ '
      + 'without renaming native outputs. Values are sanitised: . → p, - → m, others → _.'));
  const unsubscribe = model.store.watch((state) => state.projection, load);
  load();
  return {element, isDirty: () => initialised && (pattern.value !== (saved.pattern || settingPattern())
    || Number(width.value) !== (saved.indexWidth || settingWidth())), dispose: unsubscribe};
}

export function createBottom(ctx, model) {
  const tabs = [
    {id: 'parameters', label: 'Parameters', create: createParametersTab},
    {id: 'outputs', label: 'Outputs', create: createOutputsTab},
    {id: 'naming', label: 'Naming', create: createNamingTab},
    {id: 'source', label: 'Source', create: createSourceTab},
    {id: 'samples', label: 'Sample data', create: createSamplesTab},
  ];
  const instances = new Map();
  let current = 'parameters';
  let open = true;
  const body = h('div', {class: 'dz-bottom-body'});
  const toggle = h('button', {class: 'button ghost small icon-only', 'aria-label': 'Collapse panel'});
  const buttons = tabs.map((tab) => h('button', {class: 'dz-bottom-tab', role: 'tab', dataset: {tab: tab.id},
    onClick: () => select(tab.id, true)}, tab.label, h('span', {class: 'dz-tab-count'})));
  const resize = h('div', {class: 'dz-bottom-resize', role: 'separator', tabindex: '0',
    'aria-label': 'Resize design details', 'aria-orientation': 'horizontal'});
  const element = h('div', {class: 'dz-bottom'}, resize,
    h('div', {class: 'dz-bottom-bar', role: 'tablist', 'aria-label': 'Design tables'}, buttons,
      h('span', {class: 'grow'}), toggle),
    body);

  function select(id, reveal) {
    if (current === id && open && reveal) {
      setOpen(false);
      return;
    }
    const previous = instances.get(current);
    if (previous && previous.hide) {
      previous.hide();
    }
    current = id;
    if (!instances.has(id)) {
      instances.set(id, tabs.find((tab) => tab.id === id).create(ctx, model));
    }
    const instance = instances.get(id);
    mount(body, instance.element);
    if (instance.show) {
      instance.show();
    }
    for (const button of buttons) {
      button.setAttribute('aria-selected', String(button.dataset.tab === id));
    }
    if (reveal) {
      setOpen(true);
    }
  }

  function setOpen(value) {
    open = value;
    element.classList.toggle('collapsed', !open);
    toggle.setAttribute('aria-label', open ? 'Collapse panel' : 'Expand panel');
    toggle.replaceChildren(icon(open ? 'chevron-down' : 'chevron-right'));
  }

  function setHeight(height) {
    const available = element.parentElement?.clientHeight || 600;
    const size = Math.max(180, Math.min(available - 140, height));
    element.style.setProperty('--dz-bottom-height', `${size}px`);
    resize.setAttribute('aria-valuenow', String(Math.round(size)));
  }
  let resizing = null;
  resize.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    setOpen(true);
    resizing = {y: event.clientY, height: element.clientHeight};
    resize.setPointerCapture(event.pointerId);
  });
  resize.addEventListener('pointermove', (event) => {
    if (resizing) setHeight(resizing.height + resizing.y - event.clientY);
  });
  resize.addEventListener('pointerup', () => { resizing = null; });
  resize.addEventListener('pointercancel', () => { resizing = null; });
  resize.addEventListener('keydown', (event) => {
    if (!['ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    setOpen(true);
    setHeight(element.clientHeight + (event.key === 'ArrowUp' ? 32 : -32));
  });

  toggle.addEventListener('click', () => setOpen(!open));
  const counts = () => {
    const projection = model.store.get().projection;
    const values = {parameters: Object.keys(projection?.parameters || {}).length,
      outputs: Object.keys(projection?.outputs || {}).length};
    for (const button of buttons) {
      const count = values[button.dataset.tab];
      button.lastChild.textContent = count ? String(count) : '';
    }
  };
  const unsubscribe = model.store.watch((state) => state.projection, counts);
  select('parameters', false);
  setOpen(true);
  counts();
  return {element, select: (id) => select(id, false), setOpen,
    reveal: (location) => {
      select('source', false);
      setOpen(true);
      return instances.get('source').reveal(location);
    },
    isDirty: () => [...instances.values()].some((instance) => instance.isDirty?.()), dispose: () => {
    unsubscribe();
    for (const instance of instances.values()) {
      if (instance.dispose) {
        instance.dispose();
      }
    }
  }};
}
