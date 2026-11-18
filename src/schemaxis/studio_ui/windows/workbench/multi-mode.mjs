// Copyright (C) 2026 David L. F. Gaden.
import {h, mount} from '../../lib/dom.mjs';
import {confirmDialog} from '../../shell/dialog.mjs';
import {atPointer, isFill} from '../../editor/fill-data.mjs';
import {nextIdentity} from './authoring-defaults.mjs';
import {suggestedName, rowValue, groupRows, applyRows, splitMasterRows, savedNameHelp, instanceNames} from './element-authoring.mjs';

/** A local transaction: rows become ordinary elements only when the enclosing form applies. */
export function multiMode({item, documentValue, existing, existingGroup, groupStartingValue, readShared, selectionControl, isUserNamed = () => false, rowProperties, onActivate = () => {}}) {
  const policy = item.authoring.multiMode, path = policy.batchPath || policy.path;
  const named = item.authoring.identityField !== false;
  const collection = item.at?.slice(0, -2) || '/nodes';
  const family = item.operation || item.id;
  const fields = item.authoring.instanceFields || [{path, label: policy.label}];
  const batchField = fields.find(field => field.path === path);
  const fieldValue = (base, field, value) => rowValue(base, field.path, value, base.id);
  let rows = [], active = false, batch, startingValue, batchControl;
  const notice = h('p', {class: 'operation-error', role: 'alert'});
  const status = h('p', {class: 'wb-help multi-mode-status', role: 'status'});
  const list = h('div', {class: 'multi-mode-rows'});
  const batchPicker = h('div', {class: 'multi-mode-batch-picker'});
  const panel = h('section', {class: 'multi-mode', hidden: true});
  const fingerprint = value => JSON.stringify({...value, id: null});
  function captureRow(row) {
    if (!row.controls) return;
    const readings = row.controls.map(({control}) => control.read());
    row.value = row.controls.reduce((value, entry, index) => {
      const entered = readings[index], fingerprint = JSON.stringify(entered);
      if (entry.readable && entry.displayed === fingerprint) return value;
      entry.displayed = fingerprint;
      entry.readable = true;
      return fieldValue(value, entry.field, entered);
    }, row.value);
    if (named && !row.original) row.value.id = row.name.value.trim();
    row.renderedValue = fingerprint(row.value);
  }
  function capture() { rows.forEach(captureRow); }
  function rename() {
    if (named) {
      const used = instanceNames(documentValue, collection);
      rows.filter(row => row.original || row.named).forEach(row => used.add(row.value.id));
      for (const row of rows) if (!row.original && !row.named) {
        row.value.id = suggestedName(item, row.value, used) || nextIdentity(item.operation || item.title, used);
        used.add(row.value.id);
        if (row.name) row.name.value = row.value.id;
      }
    }
    rows.forEach(row => row.refresh?.());
  }
  function run(action) {
    try { capture(); notice.textContent = ''; status.textContent = ''; action(); rename(); render(); }
    catch (fault) { notice.textContent = fault.message; }
  }
  function add(value, {original = false, named = false, starter = false, expanded = true} = {}) {
    rows.push({value: structuredClone(value), original, named: original || named, selected: true, starter, expanded});
  }
  const describe = value => value == null || (Array.isArray(value) && !value.length) ? '—' :
    (Array.isArray(value) ? value : [value]).map(entry => ['string', 'number', 'boolean'].includes(typeof entry) ? String(entry)
    : typeof entry?.node === 'string' ? `${entry.node} · port ${entry.port}` : entry?.pattern ? `pattern: ${entry.pattern}` : entry?.exclude ? `exclude: ${entry.exclude}` : 'Choose items').join(', ');
  function render() {
    mount(list, rows.map((row, index) => {
      if (row.element && row.index === index && row.renderedValue === fingerprint(row.value)) {
        row.refresh(); return row.element;
      }
      row.name = named ? h('input', {class: 'input', 'aria-label': `Row ${index + 1} Name`, value: row.value.id,
        readOnly: row.original,
        title: row.original ? savedNameHelp : undefined,
        onInput: () => { row.named = true; row.starter = false; row.value.id = row.name.value; row.refresh(); }}) : null;
      const scope = {};
      row.controls = fields.map(field => {
        const value = atPointer(row.value, field.path);
        const control = selectionControl(field, field === batchField ? value ?? [] : value,
          `Row ${index + 1}.${field.label}`, () => row.value, scope);
        // A control can display a schema default or a literal placeholder for
        // an omitted field. Opening the row must not author that display value.
        try { return {field, control, readable: true, displayed: JSON.stringify(control.read())}; }
        catch { return {field, control, readable: false}; }
      });
      const selection = h('input', {type: 'checkbox', checked: row.selected, 'aria-label': `Select row ${index + 1}`,
        onChange: event => { row.selected = event.target.checked; }});
      const summaryName = h('strong', {class: 'multi-mode-summary-name'});
      const summaryItems = h('span', {class: 'multi-mode-summary-items'});
      const toggle = h('button', {type: 'button', class: 'multi-mode-row-toggle',
        'aria-controls': `multi-instance-editor-${index + 1}`, onClick: () => {
          row.expanded = !row.expanded;
          if (!row.expanded) row.starter = false;
          row.refresh();
        }}, h('span', {class: 'multi-mode-summary-text'}, summaryName, summaryItems),
        row.original ? h('span', {class: 'badge'}, 'original') : null,
        h('span', {class: 'multi-mode-chevron', 'aria-hidden': 'true'}, '▾'));
      const header = h('div', {class: 'multi-mode-row-summary'}, selection, toggle);
      const controls = h('div', {class: 'multi-mode-selection'}, row.controls.map(({control}) => control.element));
      for (const event of ['input', 'change', 'click']) controls.addEventListener(event, () => {
        try {
          const before = JSON.stringify(row.value);
          captureRow(row); rename();
          for (const listener of scope.formChanges || []) if (!listener()) scope.formChanges.delete(listener);
          if (before !== JSON.stringify(row.value)) row.starter = false;
          row.refresh();
        } catch { /* Incomplete text remains editable and is validated on outer Apply. */ }
      });
      const editor = h('div', {class: 'multi-mode-row-editor', id: `multi-instance-editor-${index + 1}`},
        row.name ? h('label', {}, 'Name', row.name) : null, controls,
        h('div', {class: 'wb-button-row'},
          rowProperties ? h('button', {type: 'button', class: 'button small', onClick: async () => {
            try {
              captureRow(row);
              const result = await rowProperties(structuredClone(row.value), {original: Boolean(row.original), userNamed: Boolean(row.named)});
              if (!result) return;
              if (row.original && result.value.id !== row.value.id) throw Error('The original Name must stay unchanged to preserve its references.');
              row.value = structuredClone(result.value); row.named = row.named || Boolean(result.userNamed);
              row.starter = false; notice.textContent = ''; rename(); render();
            } catch (fault) { notice.textContent = fault.message; }
          }}, 'Properties…') : null,
          h('button', {type: 'button', class: 'button small', disabled: row.original,
            title: row.original ? 'The original instance is kept because other elements may refer to it.' : undefined,
            onClick: async () => {
              if (await confirmDialog('Delete instance?', `Delete ${row.name?.value || 'this instance'} from this draft?`, {confirm: 'Delete', danger: true})) {
                rows = rows.filter(candidate => candidate !== row); rename(); render();
              }
            }}, 'Delete')));
      const section = h('section', {class: 'multi-mode-row', 'aria-label': `Instance ${index + 1}`}, header, editor);
      row.refresh = () => {
        selection.hidden = !batch?.open;
        summaryName.textContent = named ? row.value.id || 'Unnamed instance' : `Instance ${index + 1}`;
        summaryItems.textContent = fields.map(field => {
          const description = describe(atPointer(row.value, field.path));
          return field === batchField && description === '—' ? `No ${field.label.toLowerCase()} selected` :
            `${field.label}: ${description}`;
        }).join(' · ');
        editor.hidden = !row.expanded;
        if (!row.expanded) section.style.minHeight = '';
        section.classList.toggle('compact', !row.expanded);
        section.classList.toggle('expanded', Boolean(row.expanded));
        toggle.setAttribute('aria-expanded', String(Boolean(row.expanded)));
      };
      row.element = section; row.index = index; row.renderedValue = fingerprint(row.value); row.refresh();
      return section;
    }));
  }
  const toolbar = h('div', {class: 'multi-mode-toolbar'},
    h('button', {type: 'button', class: 'button small primary', onClick: () => {
      let added;
      run(() => {
        rows.forEach(row => { row.expanded = false; });
        add(path ? fieldValue(startingValue, batchField, []) : startingValue);
        added = rows.at(-1);
      });
      if (added) {
        (added.element.querySelector('.wb-case-name') || added.name || added.element.querySelector('.multi-mode-row-toggle')).focus({preventScroll: true});
        // Keep the preceding summary above the new editor so adding a row is
        // visibly an addition. Scroll only this list, leaving its toolbar fixed.
        const previous = rows.at(-2)?.element;
        const layout = getComputedStyle(list);
        const padding = parseFloat(layout.paddingTop) + parseFloat(layout.paddingBottom);
        const contextHeight = previous ? previous.getBoundingClientRect().height + parseFloat(layout.rowGap) : 0;
        // Even a short editor fills the remaining viewport, so the scroll range
        // can place the preceding summary at the top instead of showing older rows.
        added.element.style.minHeight = `${Math.max(0, list.clientHeight - padding - contextHeight)}px`;
        const anchor = previous || added.element;
        list.scrollTop += anchor.getBoundingClientRect().top - list.getBoundingClientRect().top
          - list.clientTop - parseFloat(layout.paddingTop);
      }
    }}, 'Add instance'),
    batch = h('details', {class: 'multi-mode-batch', hidden: !batchField, onToggle: () => rows.forEach(row => row.refresh?.())},
    h('summary', {}, 'Batch actions'),
    h('div', {class: 'multi-mode-batch-panel'},
    h('p', {class: 'wb-help'}, 'Select instance checkboxes to split, group or restore their starting settings. New instances always use the settings captured when multi-mode opened.'),
    batchPicker, h('div', {class: 'wb-button-row'},
    h('button', {type: 'button', class: 'button small primary', onClick: () => run(() => {
      const source = rowValue(startingValue, path, batchControl.read(), startingValue.id);
      const result = splitMasterRows(rows, source, path);
      rows = result.rows;
      batch.open = false;
      status.textContent = `${result.replaced ? 'Replaced the draft starter. ' : 'Kept existing instances. '}`
        + `Created ${result.added} instance${result.added === 1 ? '' : 's'}.`;
    })}, 'One instance per selected item'),
    h('button', {type: 'button', class: 'button small', onClick: () => run(() => {
      const candidates = rows.filter(row => row.selected);
      if (!candidates.length || candidates.some(row => row.original)) throw Error('Select new rows to split. The original row keeps its identity.');
      if (candidates.some(row => { const values = atPointer(row.value, path); return !Array.isArray(values) || !values.length || values.some(value => typeof value !== 'string'); }))
        throw Error('Split exact entries only. Patterns and exclusions stay together.');
      rows = rows.flatMap(row => !row.selected ? [row] : atPointer(row.value, path).map((entry, index) =>
        ({value: rowValue(row.value, path, [entry], row.value.id), selected: true, named: index === 0 && row.named, expanded: false})));
    })}, 'Split selected rows'),
    h('button', {type: 'button', class: 'button small', onClick: () => run(() => {
      const source = startingValue;
      for (const row of rows.filter(row => row.selected)) {
        const current = row.value;
        row.value = fields.reduce((value, field) => fieldValue(value, field, atPointer(current, field.path)),
          named ? {...structuredClone(source), id: current.id} : structuredClone(source));
        row.starter = false;
      }
    })}, 'Use starting settings for selected instances'),
    h('button', {type: 'button', class: 'button small', onClick: () => run(() => {
      rows = groupRows(rows, new Set(rows.flatMap((row, index) => row.selected ? [index] : [])), path);
      rows.forEach(row => { row.starter = false; row.expanded = false; });
    })}, 'Group selected rows')))));
  panel.append(toolbar, notice, status, list);
  function activate() {
    if (active) return;
    try {
      rows = [];
      let source = readShared();
      const selection = path ? atPointer(source, path) : undefined;
      if (path && (selection === undefined || isFill(selection))) source = fieldValue(source, batchField, []);
      startingValue = structuredClone(groupStartingValue || source);
      if (batchField) {
        batchControl = selectionControl(batchField, atPointer(startingValue, path) || [],
          `Batch.${batchField.label}`, () => startingValue, {});
        mount(batchPicker, batchControl.element);
      }
      if (existingGroup) existingGroup.forEach(member => add(member.value, {original: true, expanded: false}));
      else add(source, {original: Boolean(existing), named: isUserNamed(), starter: !existing,
        expanded: !Array.isArray(selection) || !selection.length});
      rename(); render(); onActivate();
      active = true; panel.hidden = false; button.hidden = true; button.disabled = true; notice.textContent = '';
      panel.scrollIntoView({block: 'nearest'});
      if (rows[0].expanded) (rows[0].element.querySelector('.wb-case-name') || rows[0].name || rows[0].element.querySelector('.multi-mode-row-toggle')).focus({preventScroll: true});
    } catch (fault) { rows = []; panel.hidden = false; notice.textContent = fault.message; }
  }
  const button = h('button', {type: 'button', class: 'button', title: 'Create several instances using these starting settings. Later Properties changes affect only the edited instance.', onClick: activate}, 'Switch to multi-mode');
  function draft() {
    capture(); rename();
    return rows.map(row => structuredClone(row.value));
  }
  return {element: h('div', {class: 'multi-mode-host'}, button, panel), get active() { return active; }, activate,
    provenance() { return {operation: family, collection, members: rows.map(row => row.value.id), startingValue: structuredClone(startingValue)}; }, draft, read() {
    const values = draft();
    if (named) applyRows(documentValue, values, existing, existingGroup, item.authoring.identityStyle, collection);
    return values;
  }};
}
