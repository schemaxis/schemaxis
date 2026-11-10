import {h, mount} from '../../lib/dom.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {atPointer, replacing} from '../../editor/fill-data.mjs';
import {checkSchemaValue} from '../../editor/fill-schema.mjs';
import {entries, valueCandidates, scopes, ownerAt, reference, preview, removeEntry, equal} from './model.mjs';
import {button, field, editEntry, valueEditor, schemaContext} from './forms.mjs';

function display(root, entry) {
  if (entry.group === 'axes') return entry.value.values ? `${entry.value.values.length} samples` : JSON.stringify(entry.value.series);
  try { return JSON.stringify(preview(root, entry.value, entry)); }
  catch { return 'Computed value · resolved during validation or execution'; }
}

function admissible(root, value, context) {
  const problem = checkSchemaValue(context.schema, context.value, context.pointer, value);
  if (problem) return problem;
  if (value?.$axis) {
    const axis = entries(root).find(entry => entry.group === 'axes' && entry.base === context.scope.base && entry.name === value.$axis);
    if (!axis) return 'This sweep is not declared in the destination document.';
    const samples = axis.value.values || [axis.value.series?.start, axis.value.series?.end];
    if (!value.path && samples.some(sample => sample !== undefined
      && checkSchemaValue(context.schema, context.value, context.pointer, sample))) return 'The sweep samples do not match this field’s type or limits.';
  }
  try {
    const resolved = preview(root, value, context.scope);
    return checkSchemaValue(context.schema, context.value, context.pointer, resolved);
  } catch (fault) {
    return /Available when|Resolved by host|Preview needs/.test(fault.message) ? '' : fault.message;
  }
}

/** Stages creation and binding together; caller commits the returned document in one undo group. */
export async function chooseValue(ctx, {root, pointer, pointers = [pointer]}) {
  let staged = structuredClone(root), expression;
  const context = await schemaContext(ctx, root, pointer);
  const list = h('div', {class: 'variables-list'}), slot = h('div'), error = h('p', {role: 'alert', class: 'error-text'});
  const readout = h('output', {class: 'variables-preview'});
  let chosen, chosenEntry, rendering = false;
  const summary = () => {
    try { const value = chosen || expression?.read(); readout.textContent = `Preview: ${JSON.stringify(preview(staged, value, context.scope))}`; }
    catch (fault) { readout.textContent = fault.message; }
  };
  const render = async () => {
    rendering = true;
    const all = valueCandidates(staged).filter(entry => entry.pointer !== pointer
      && (entry.group !== 'axes' || entry.base === context.scope.base));
    const rows = all.map(entry => {
      const value = reference(entry, context.scope), reason = admissible(staged, value, context);
      return {entry, value, reason};
    }).sort((a, b) => Boolean(a.reason) - Boolean(b.reason));
    mount(list, rows.length ? rows.map(({entry, value, reason}) => button(
      `${entry.name} · ${entry.label} · ${display(staged, entry)}${reason ? ' — ' + reason : ''}`,
      () => { chosen = value; chosenEntry = entry; error.textContent = ''; summary(); list.querySelectorAll('button').forEach(b => b.classList.remove('primary'));
        [...list.children].find(b => b.dataset.pointer === entry.pointer)?.classList.add('primary'); },
      {class: `button small${equal(value, chosen) ? ' primary' : ''}`, disabled: Boolean(reason), title: reason || 'Use this value', dataset: {pointer: entry.pointer}}))
      : h('p', {class: 'hint'}, 'No named values yet. Create one below, even before adding an operation.'));
    expression = await valueEditor(ctx, {root: staged, pointer, initial: atPointer(root, pointer)?.$fill ? undefined : atPointer(root, pointer),
      onChange: () => { if (!rendering) { chosen = chosenEntry = undefined; list.querySelectorAll('button').forEach(b => b.classList.remove('primary')); summary(); } }});
    mount(slot, expression.element); rendering = false; summary();
  };
  await render();
  return openDialog({title: 'Choose a value or expression', wide: true,
    content: h('div', {class: 'variables-fields'}, h('p', {}, `Destination: ${context.scope.label} · ${context.pointer || '/'}`),
      h('h3', {}, 'Named values and sweeps'), list,
      button('Create new value…', () => ctx.call(async () => {
        const result = await editEntry(ctx, staged, {base: context.scope.base});
        if (!result) return;
        staged = result.document; chosenEntry = result.entry; chosen = reference(result.entry, context.scope); await render();
      })), h('details', {open: !entries(staged).length}, h('summary', {}, 'Type a value or build an expression'), slot), readout, error),
    actions: [{label: 'Cancel', run: () => null}, {label: 'Use value', primary: true, run: async () => {
      if (rendering) { error.textContent = 'Loading the updated value choices…'; return false; }
      try {
        const value = chosen || expression.read();
        let result = staged;
        for (const target of pointers) {
          const where = await schemaContext(ctx, result, target);
          const binding = chosenEntry ? reference(chosenEntry, where.scope) : value;
          const problem = admissible(result, binding, where);
          if (problem) throw Error(problem);
          result = replacing(result, target, binding);
          const after = admissible(result, binding, where);
          if (after) throw Error(after);
        }
        return {document: result, value};
      } catch (fault) { error.textContent = fault.message; return false; }
    }}]});
}

export async function manageVariables(ctx, snapshot) {
  let staged = structuredClone(snapshot.root);
  const list = h('div', {class: 'variables-list'}), error = h('p', {role: 'alert', class: 'error-text'});
  const render = () => mount(list, entries(staged).map(entry => h('div', {class: 'card variable-row'},
    h('div', {}, h('strong', {}, entry.name), h('div', {class: 'hint'}, `${entry.label} · ${entry.group}`),
      h('code', {}, display(staged, entry))),
    button('Edit', () => ctx.call(async () => {
      const result = await editEntry(ctx, staged, {previous: entry});
      if (result) { staged = result.document; render(); }
    }), {'aria-label': `Edit ${entry.name}`}),
    button('Remove', () => {
      try { staged = removeEntry(staged, entry); error.textContent = ''; render(); }
      catch (fault) { error.textContent = fault.message; }
    }, {'aria-label': `Remove ${entry.name}`}))));
  render(); let applying = false;
  return openDialog({title: 'Variables & expressions', wide: true,
    content: h('div', {class: 'variables-fields'}, h('p', {}, snapshot.label || 'Values belong to the document shown below.'),
      h('p', {class: 'hint'}, 'Create reusable values, calculations or sweeps before or after adding operations. Use the value picker beside a field to bind one. Changes below are staged until Apply.'),
      button('Create new value…', () => ctx.call(async () => {
        const result = await editEntry(ctx, staged, {base: snapshot.base ?? scopes(staged)[0].base});
        if (result) { staged = result.document; render(); }
      })), list, error),
    actions: [{label: 'Cancel', run: () => null}, {label: snapshot.applyLabel || 'Apply changes', primary: true, run: async () => {
      if (applying) return false;
      applying = true;
      try { if (!equal(staged, snapshot.root)) await snapshot.commit(staged); return true; }
      catch (fault) { error.textContent = fault.message; return false; }
      finally { applying = false; }
    }}]});
}

export async function openVariables(ctx) {
  const active = ctx.windows.active()?.window;
  if (active?.variableContext) return manageVariables(ctx, await active.variableContext());
  const records = ctx.store.get().server?.documents || [];
  const choice = h('select', {class: 'select', 'aria-label': 'Variables document'}, records.map(record =>
    h('option', {value: record.id}, record.name)));
  const selected = await openDialog({title: 'Choose a document for variables',
    content: h('div', {class: 'variables-fields'}, field('Document', choice),
      h('p', {}, 'Values have an owner. Choose an existing document or create an empty workflow design and define its parameters before adding operations.')),
    actions: [{label: 'Cancel', run: () => null}, {label: 'New workflow design', run: () => 'new'},
      {label: 'Open variables', primary: true, run: () => choice.value || false}]});
  if (!selected) return;
  let record;
  if (selected === 'new') {
    record = await ctx.api.post('/api/documents', {action: 'new', provider: 'workflow-design', name: 'Parameterised workflow'});
    await ctx.refresh();
  } else record = await ctx.api.get('/api/document', {id: selected});
  // Prefer an open editor's actual draft over its saved revision.
  const existing = [...ctx.windows.instances.values()].find(w => w.params.document === record.id && !w.params.operation && w.window.variableContext);
  if (existing) return manageVariables(ctx, await existing.window.variableContext());
  await manageVariables(ctx, {root: record.document, label: record.name, applyLabel: 'Save changes to workspace', commit: async root => {
    await ctx.api.post('/api/authoring', {action: 'patch', document: record.id, revision: record.revision,
      edits: [{op: 'replace', path: '', value: root}]});
    await ctx.refresh();
  }});
  ctx.openDocument(record.id);
}
