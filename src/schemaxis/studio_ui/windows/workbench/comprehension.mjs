// Copyright (C) 2026 David L F Gaden
// Readable, navigable reference to the current draft, shared by both editors.
import {h, mount} from '../../lib/dom.mjs';
import {escapePointer} from './model.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {duplicateNode, removeNode} from './pipeline-edit.mjs';

export function comprehensionEntries(documentValue) {
  const entries = [];
  function visit(value, base = '') {
    if (!value || typeof value !== 'object') return;
    if (Array.isArray(value.nodes)) value.nodes.forEach((node, index) => {
      if (!node || typeof node !== 'object') return;
      const scalar = (item) => ['string', 'number', 'boolean'].includes(typeof item) ? String(item)
        : Array.isArray(item) && item.every(value => ['string', 'number', 'boolean'].includes(typeof value)) ? JSON.stringify(item)
        : item?.$document ? `document ${item.$document}` : item?.$observe ? `observe ${item.$observe}`
        : item?.node ? `${item.node}${item.port !== undefined ? ':' + item.port : ''}`
        : item?.$fill ? `${item.label || item.$fill} (to fill)` : '';
      const inputs = Object.entries(node.inputs || {}).map(([key, item]) => `${key}: ${Array.isArray(item) ? item.map(scalar).join(', ') : scalar(item)}`).join(' · ');
      const settings = Object.entries(node.options || {}).map(([key, item]) => {
        const text = scalar(item);
        return text ? `${key}: ${text}` : '';
      }).filter(Boolean).join(' · ');
      const caption = (item, fallback) => typeof item === 'string' ? item : item?.$fill ? `${item.label || item.$fill} · to fill` : fallback;
      entries.push({pointer: `${base}/nodes/${index}`, label: `${index} · ${caption(node.filter || node.kind, 'Node')} → ${caption(node.id, '(unnamed)')}`,
        detail: [inputs, settings].filter(Boolean).join(' · ')});
    });
    for (const [key, child] of Object.entries(value)) {
      if (key !== 'nodes' && child && typeof child === 'object') visit(child, `${base}/${escapePointer(key)}`);
    }
  }
  visit(documentValue);
  return entries;
}

export function createComprehension(editor, onReveal = (pointer) => editor.revealPointer(pointer)) {
  let selected = '';
  const list = h('div', {class: 'wb-comprehension-list'});
  const state = h('p', {class: 'wb-help', role: 'status'});
  const duplicate = h('button', {class: 'button small', type: 'button', disabled: true, onClick: () => edit(false)}, 'Duplicate');
  const remove = h('button', {class: 'button small', type: 'button', disabled: true, onClick: () => edit(true)}, 'Delete');
  async function edit(deleting) {
    const before = editor.getValue();
    let result;
    try { result = (deleting ? removeNode : duplicateNode)(editor.getDocument(), selected); }
    catch (error) { state.textContent = error.message; return; }
    if (deleting && (result.names.length > 1 || result.publicationsChanged)) {
      const accepted = await openDialog({title: 'Delete pipeline objects?', content: h('div', {},
        h('p', {}, `Remove ${result.names.join(', ')}?${result.names.length > 1 ? ' Dependent objects need this input and will be removed too.' : ''}`),
        result.publicationsChanged ? h('p', {}, 'Scene and output references to these objects will also be removed.') : null,
        h('p', {}, 'This is one draft edit. Undo restores it.')),
        actions: [{label: 'Cancel', run: () => null}, {label: 'Delete', danger: true, run: () => true}]});
      if (!accepted) return;
    }
    if (editor.getValue() !== before) { state.textContent = 'The pipeline changed. Select the object again.'; return; }
    editor.insertAtPointer(result.base, result.value);
    selected = result.pointer; update(); onReveal(selected);
  }
  const element = h('details', {class: 'wb-comprehension', open: true},
    h('summary', {}, 'Pipeline'),
    h('details', {}, h('summary', {}, 'How to read the pipeline'),
    h('p', {class: 'wb-help'}, 'Operations and their data connections. Each node creates a named result. Click a node to select its Properties and reveal its source. Numbers are array indices, starting at 0.'),
    h('p', {class: 'wb-help'}, '$observe reads a result measurement; path selects its nested value. $document reads a value from this document. $value evaluates a declared function with args.')), state,
    h('div', {class: 'operation-file-tools'}, duplicate, remove), list);
  function update() {
    let value;
    try { value = editor.getDocument(); }
    catch { state.textContent = 'Incomplete source — showing the last readable reference.'; return; }
    const entries = comprehensionEntries(value);
    duplicate.disabled = remove.disabled = !entries.some(item => item.pointer === selected);
    state.textContent = entries.length ? `${entries.length} nodes · current draft` : 'No nodes in this document yet.';
    mount(list, entries.map((item) => h('button', {class: 'wb-outline-item', dataset: {pointer: item.pointer},
      'aria-current': String(item.pointer === selected), onClick: () => { selected = item.pointer; update(); onReveal(item.pointer); }},
      h('span', {}, h('strong', {}, item.label), h('small', {}, item.detail || 'No inputs or scalar options declared.')))));
  }
  const unsubscribe = editor.onChange(update);
  update();
  return {element, dispose: unsubscribe, refresh: update, select(pointer) {
    selected = pointer;
    duplicate.disabled = remove.disabled = !list.querySelector(`[data-pointer="${CSS.escape(pointer)}"]`);
    list.querySelectorAll('button').forEach(button => button.setAttribute('aria-current', String(button.dataset.pointer === pointer)));
  }};
}

export function formattingControls(editor) {
  const width = h('input', {type: 'number', min: 40, max: 240, value: 100,
    'aria-label': 'Compact line width', class: 'input wb-format-width'});
  return h('span', {class: 'wb-format-controls'},
    h('button', {class: 'button ghost small', onClick: () => editor.format({compact: true,
      width: Math.max(40, Math.min(240, Number(width.value) || 100))})}, 'Compact'),
    h('button', {class: 'button ghost small', onClick: () => editor.format()}, 'Expand'),
    h('label', {class: 'wb-check'}, 'Line width ', width));
}
