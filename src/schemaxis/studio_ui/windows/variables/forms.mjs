// Copyright (C) 2026 David L. F. Gaden.
import {spatialInput, readSpatialInput, expressionValue, reportSpatialCheck} from '../../editor/spatial-input.mjs';
import {previewSpatial, spatialAction, spatialRequest} from '../spatial/host.mjs';
import {h, mount} from '../../lib/dom.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {atPointer} from '../../editor/fill-data.mjs';
import {escapeSegment} from '../../editor/json-pointer.mjs';
import {createExpressionForm} from '../../editor/fill-expressions.mjs';
import {expressionKinds, expressionNodes, checkSchemaValue} from '../../editor/fill-schema.mjs';
import {VALUE_LABELS, valueLabel} from '../../editor/value-labels.mjs';
import {entries, valueCandidates, scopes, ownerAt, reference, saveEntry} from './model.mjs';

export const button = (label, run, props = {}) => h('button', {type: 'button', class: 'button small', onClick: run, ...props}, label);
export const field = (label, input) => input.type === 'checkbox'
  ? h('label', {class: 'checkbox'}, input, h('span', {}, label))
  : h('label', {class: 'field'}, h('span', {}, label), input);
export const input = (label, value = '') => h('input', {class: 'input', 'aria-label': label, value});
const select = (label, pairs) => h('select', {class: 'select', 'aria-label': label},
  pairs.map(([value, text]) => h('option', {value}, text)));

export async function schemaContext(ctx, root, pointer) {
  const scope = ownerAt(root, pointer), value = atPointer(root, scope.base);
  if (!value?.version) throw Error('Choose a registered document with valid JSON or YAML syntax before editing values.');
  const schema = await ctx.api.get('/api/schema', {version: value.version});
  return {scope, value, schema, pointer: pointer.slice(scope.base.length)};
}

export function literalEditor(initial, candidates = [], scope) {
  const type = select('Value type', ['number', 'integer', 'text', 'boolean', 'vector', 'box', 'JSON'].map(t => [t, t]));
  type.value = typeof initial === 'string' ? 'text' : typeof initial === 'boolean' ? 'boolean'
    : Array.isArray(initial) && initial.length === 6 && initial.every(Number.isFinite) ? 'box'
    : Array.isArray(initial) && initial.length === 3 && initial.every(Number.isFinite) ? 'vector'
      : initial?.min && initial?.max ? 'box' : initial && typeof initial === 'object' ? 'JSON' : 'number';
  const value = spatialInput({label: 'Value', value: initial ?? 0}).element;
  if (typeof initial === 'string') value.value = initial;
  const flatBox = Array.isArray(initial) && initial.length === 6;
  const boxSeed = flatBox ? {min: [initial[0], initial[2], initial[4]], max: [initial[1], initial[3], initial[5]]} : initial;
  const coordinates = h('div', {class: 'variables-fields'});
  const component = (label, seed) => {
    const source = select(label + ' source', [['literal', 'Typed value / expression'], ...candidates.map((e, i) => [String(i), e.name + ' · ' + e.label])]);
    const coordinate = spatialInput({label, value: seed ?? 0});
    const text = coordinate.element;
    source.addEventListener('change', () => { text.hidden = source.value !== 'literal'; });
    coordinates.append(field(label, h('div', {}, source, text)));
    return () => source.value === 'literal' ? coordinate.read() : reference(candidates[Number(source.value)], scope);
  };
  let readCoordinates;
  const refresh = () => {
    coordinates.replaceChildren(); value.parentElement.hidden = ['vector', 'box'].includes(type.value);
    coordinates.hidden = !['vector', 'box'].includes(type.value);
    if (type.value === 'vector') { const readers = Array.from({length: 3}, (_, i) => component('XYZ'[i] || `Component ${i}`, Array.isArray(initial) ? initial[i] : 0)); readCoordinates = () => readers.map(read => read()); }
    if (type.value === 'box') {
      const minimum = [...'XYZ'].map((axis, i) => component('Minimum ' + axis, boxSeed?.min?.[i] ?? 0));
      const maximum = [...'XYZ'].map((axis, i) => component('Maximum ' + axis, boxSeed?.max?.[i] ?? 1));
      readCoordinates = () => ({min: minimum.map(read => read()), max: maximum.map(read => read())});
    }
  };
  const element = h('div', {class: 'variables-fields variables-literal'}, field('Type', type), field('Value', value), coordinates);
  type.addEventListener('change', refresh); refresh();
  return {element, read() {
    if (['vector', 'box'].includes(type.value)) {
      const result = readCoordinates();
      const coordinates = type.value === 'box' ? [...result.min, ...result.max] : result;
      if (!coordinates.every(v => typeof v === 'number' && Number.isFinite(v) || v && !Array.isArray(v) && typeof v === 'object' && Object.keys(v).some(k => k.startsWith('$')))) {
        throw Error('Each coordinate needs a finite number or a scalar expression.');
      }
      return type.value === 'box' && flatBox ? [0, 1, 2].flatMap(i => [result.min[i], result.max[i]]) : result;
    }
    if (type.value === 'text') return value.value;
    const result = ['number', 'integer'].includes(type.value) ? readSpatialInput(value.value) : JSON.parse(value.value);
    if (expressionValue(result)) return result;
    if (['number', 'integer'].includes(type.value) && (typeof result !== 'number' || !Number.isFinite(result)
      || type.value === 'integer' && !Number.isInteger(result))) throw Error(`Enter a finite ${type.value}.`);
    if (type.value === 'boolean' && typeof result !== 'boolean') throw Error('Enter true or false.');
    if (type.value === 'vector' && (!Array.isArray(result) || !result.length || !result.every(Number.isFinite))) throw Error('Enter a nonempty numeric vector, such as [0, 0, 1].');
    return result;
  }};
}

/** One value editor for the manager, field picker, and operation forms. */
export async function valueEditor(ctx, {root, pointer, initial, onChange = () => {}}) {
  const context = await schemaContext(ctx, root, pointer);
  const kinds = expressionKinds(context.schema, context.value, context.pointer);
  const nodes = expressionNodes(context.schema, context.value, context.pointer);
  if (nodes.some(node => node.properties?.$artifact)) kinds.push('$artifact');
  const mode = select('Value source', [['literal', 'Type a value'],
    ...(kinds.includes('$document') ? [['saved', 'Use a saved value']] : []),
    ...kinds.map(key => [key, valueLabel(key)]),
    ...(nodes.some(node => node.properties?.$value && node.properties?.path) && scopes(root).some(s => s.workflow)
      ? [['$result', valueLabel('$result')]] : [])]);
  const body = h('div', {class: 'variables-fields'}), explanation = h('p', {class: 'hint'});
  let read = () => initial;
  let sequence = 0;
  const catalogue = await ctx.api.get('/api/functions');
  const candidates = valueCandidates(root).filter(entry => entry.pointer !== pointer
    && (entry.group !== 'sweeps' || entry.base === context.scope.base));
  const choices = candidates.map((entry, i) => [String(i), `${entry.name} · ${entry.label} · ${entry.group}`]);

  function operand(label) {
    const source = select(`${label} source`, [['literal', 'Number'], ...choices]);
    const shared = spatialInput({label, value: 2});
    const number = shared.element;
    source.addEventListener('change', () => { number.hidden = source.value !== 'literal'; onChange(); });
    return {element: field(label, h('div', {}, source, number)), read: () => source.value === 'literal'
      ? shared.read() : reference(candidates[Number(source.value)], context.scope)};
  }
  async function render() {
    const ticket = ++sequence;
    explanation.textContent = VALUE_LABELS[mode.value]?.[1] || (mode.value === 'saved'
      ? 'Choose a named value. Scope is shown so local and shared values are distinct.' : 'Enter a value with its JSON type.');
    if (mode.value === 'literal') {
      const literal = literalEditor(initial && typeof initial === 'object' && Object.keys(initial).some(k => k.startsWith('$')) ? undefined : initial, candidates, context.scope);
      mount(body, literal.element); read = literal.read;
    } else if (mode.value === 'saved') {
      const selected = select('Saved value', choices);
      mount(body, field('Saved value', selected));
      read = () => {
        const entry = candidates[Number(selected.value)];
        if (!entry) throw Error('Create a named value first.');
        return reference(entry, context.scope);
      };
    } else if (mode.value === '$expr') {
      if (typeof initial?.$expr === 'string' || !initial?.$expr) {
        const shared = spatialInput({label: 'Expression', value: typeof initial?.$expr === 'string' ? initial : {$expr: ''}, onChange});
        mount(body, shared.element); read = shared.read; onChange(); return;
      }
      const operation = select('Calculation', ['add', 'subtract', 'multiply', 'divide'].map(op => [op, op]));
      const left = operand('Left argument'), right = operand('Right argument');
      const advanced = h('input', {type: 'checkbox', 'aria-label': 'Structured expression'});
      const json = h('textarea', {class: 'input mono', 'aria-label': 'Expression JSON', hidden: true,
        value: JSON.stringify(initial?.$expr || {op: 'multiply', args: [2, 3]}, null, 2)});
      advanced.checked = Boolean(initial?.$expr);
      const arithmetic = h('div', {class: 'variables-fields'}, field('Calculation', operation), left.element, right.element);
      const toggle = () => { json.hidden = !advanced.checked; arithmetic.hidden = advanced.checked; };
      advanced.addEventListener('change', toggle); toggle();
      mount(body, arithmetic, field('Structured expression / existing formula', advanced), json);
      read = () => ({$expr: advanced.checked ? JSON.parse(json.value) : {op: operation.value, args: [left.read(), right.read()]}});
    } else if (mode.value === '$sweep') {
      const axes = candidates.filter(entry => entry.group === 'sweeps');
      const selected = select('Named sweep', axes.map(entry => [entry.name, entry.name]));
      mount(body, field('Named sweep', selected), h('p', {class: 'hint'},
        'To add a sweep, create a named value with the group “Named sweeps”.'));
      read = () => {
        if (!selected.value) throw Error('Create a named sweep first.');
        return {$sweep: selected.value};
      };
    } else if (mode.value === '$result' || mode.value === '$artifact') {
      const owners = scopes(root), consumer = owners.findIndex(s => s.base === context.scope.base);
      const operations = owners.filter((s, index) => s.operation && s.base !== context.scope.base
        && (!context.scope.operation || index < consumer));
      const producer = select('Producer operation', operations.map(s => [s.operation, s.operation]));
      const path = input('Result pointer', ''), index = input('Artifact index', '0');
      mount(body, field('Producer operation', producer), mode.value === '$result' ? field('JSON result pointer', path) : field('Artifact index', index));
      read = () => {
        if (!producer.value) throw Error('Add an earlier producer operation first.');
        return mode.value === '$result' ? {$value: producer.value, path: path.value} : {$artifact: producer.value, index: Number(index.value)};
      };
    } else {
      const form = createExpressionForm({schema: context.schema, value: context.value, pointer: context.pointer,
        kind: mode.value, catalogue, onChange});
      if (ticket !== sequence) return;
      mount(body, form.element);
      read = () => form.read().value;
    }
    onChange();
  }
  if (initial && typeof initial === 'object') {
    const key = Object.keys(initial).find(k => kinds.includes(k));
    if (key && key === '$expr') mode.value = key;
    // Keep exact existing expressions editable without rebuilding their arguments.
    else if (Object.keys(initial).some(k => k.startsWith('$'))) {
      const exact = h('option', {value: 'exact'}, 'Edit existing expression (JSON)'); mode.append(exact); mode.value = 'exact';
    }
  }
  const draw = async () => {
    if (mode.value === 'exact') {
      const json = h('textarea', {class: 'input mono', 'aria-label': 'Expression JSON', value: JSON.stringify(initial, null, 2)});
      explanation.textContent = 'The existing expression is preserved exactly until you apply a change.';
      mount(body, json); read = () => JSON.parse(json.value); onChange();
    } else await render();
  };
  mode.addEventListener('change', () => ctx.call(draw));
  const checkResult = h('output', {class: 'hint', 'aria-live': 'polite'});
  let checkTicket = 0;
  const check = button('Check expression', () => ctx.call(async () => {
    try {
      const value = read(), ticket = ++checkTicket;
      if (typeof value?.$expr !== 'string') { checkResult.textContent = 'Enter a string expression to check.'; return; }
      const result = await spatialAction(ctx.api, 'spatial_check', spatialRequest(root, context.scope.base, undefined,
        {expression: value.$expr, destination: context.pointer}));
      if (ticket !== checkTicket) return;
      const text = body.querySelector('[aria-label="Expression"]');
      if (text) reportSpatialCheck(text, result);
      checkResult.textContent = result.ok ? `${result.type} · ${result.phase}` : result.fault?.message || 'Expression refused';
    } catch (fault) { checkResult.textContent = fault.message; }
  }));
  const element = h('div', {class: 'variables-fields'}, field('Value source', mode), explanation, body, check, checkResult);
  element.addEventListener('input', () => { checkTicket++; checkResult.textContent = ''; });
  element.addEventListener('input', onChange); element.addEventListener('change', onChange);
  await draw();
  return {element, context, read: () => {
    const value = read(), fault = checkSchemaValue(context.schema, context.value, context.pointer, value);
    if (fault) throw Error(fault);
    return value;
  }};
}

export async function editEntry(ctx, root, {base = scopes(root)[0].base, previous} = {}) {
  const name = input('Variable name', previous?.name || '');
  const owner = select('Value scope', scopes(root).map(s => [s.base, s.label])); owner.value = previous?.base ?? base;
  const group = select('Value group', [['dimensions', 'Dimensions'], ['settings', 'Settings'], ['definitions', 'Reusable values'], ['sweeps', 'Named sweeps']]);
  group.value = previous?.group || 'dimensions';
  name.placeholder = 'e.g. distance';
  const slot = h('div'), error = h('p', {role: 'alert', class: 'error-text'}), result = h('output', {class: 'variables-preview'});
  const parameter = h('input', {type: 'checkbox', 'aria-label': 'Expose in Case Runner'});
  const units = input('Units'), help = input('Parameter help');
  const parameterDetails = h('div', {class: 'variable-identity', hidden: true}, field('Units (label only)', units), field('Parameter help', help));
  const parameterFields = h('div', {class: 'variables-fields'}, field('Expose in Case Runner', parameter), parameterDetails);
  parameter.addEventListener('change', () => { parameterDetails.hidden = !parameter.checked; });
  const oldParameter = Object.values(root.parameters || {}).find(p => previous?.workflow && p.target?.scope === 'workflow'
    && p.target.pointer === previous.pointer.slice(previous.base.length));
  if (oldParameter) { parameter.checked = true; parameter.disabled = true; parameterDetails.hidden = false; units.value = oldParameter.units || ''; help.value = oldParameter.help || ''; }
  let editor, sweep, ticket = 0, loading = false, currentValue = previous?.value;
  let previewTicket = 0;
  const updatePreview = async () => {
    const current = ++previewTicket;
    try {
      if (group.value === 'sweeps') { result.textContent = 'A sweep schedules one visit per sample.'; return; }
      const value = editor.read();
      const draft = saveEntry(root, {base: owner.value, group: group.value, name: name.value, value}, previous);
      const resolved = await previewSpatial(ctx.api, draft, value, owner.value);
      if (current === previewTicket) result.textContent = `Preview: ${JSON.stringify(resolved)}`;
    } catch (fault) { if (current === previewTicket) result.textContent = `Preview: ${fault.message}`; }
  };
  const refresh = async () => {
    const sequence = ++ticket;
    if (editor) { try { currentValue = editor.read(); } catch { /* Keep the last complete value. */ } }
    loading = true;
    parameterFields.hidden = root.version !== 'schemaxis.workflow-design/2' || !scopes(root).find(s => s.base === owner.value)?.workflow || group.value === 'sweeps';
    if (group.value === 'sweeps') {
      const mode = select('Sweep sampling', [['values', 'Explicit values'], ['series', 'Regular sequence'], ['custom', 'Advanced sweep JSON']]);
      mode.value = previous?.value.series ? Object.keys(previous.value.series).some(key => !['start', 'end', 'count'].includes(key)) ? 'custom' : 'series' : 'values';
      const values = input('Sweep values (JSON)', JSON.stringify(previous?.value.values || [0, 1, 2]));
      const start = spatialInput({label: 'Sweep start', value: previous?.value.series?.start ?? 0}).element;
      const end = spatialInput({label: 'Sweep end', value: previous?.value.series?.end ?? 10}).element;
      const count = spatialInput({label: 'Sweep count', value: previous?.value.series?.count ?? 3}).element;
      const linear = h('div', {class: 'variables-fields'}, field('Start', start), field('End', end), field('Count', count));
      const json = h('textarea', {class: 'input mono', 'aria-label': 'Sweep JSON', value: JSON.stringify(previous?.value || {values:[0,1]}, null, 2)});
      const change = () => { values.parentElement.hidden = mode.value !== 'values'; linear.hidden = mode.value !== 'series'; json.hidden = mode.value !== 'custom'; };
      mount(slot, field('Sampling', mode), field('Values', values), linear, json); mode.addEventListener('change', change); change();
      sweep = () => {
        if (mode.value === 'custom') return JSON.parse(json.value);
        if (mode.value === 'values') return {values: JSON.parse(values.value)};
        const a = readSpatialInput(start.value), b = readSpatialInput(end.value), n = readSpatialInput(count.value);
        if ([a, b, n].some(expressionValue)) return {series: {start: a, end: b, count: n}};
        if (!Number.isFinite(a) || !Number.isFinite(b) || !Number.isInteger(n) || n < 1 || n > 10000 || n === 1 && a !== b) throw Error('Use finite endpoints and 1–10000 samples; a single sample needs equal endpoints.');
        return {series: {start: a, end: b, count: n}};
      };
    } else {
      mount(slot, h('p', {class: 'hint'}, 'Loading value choices…'));
      const next = await valueEditor(ctx, {root, pointer: `${owner.value}/${group.value}/${escapeSegment(previous?.name || 'newValue')}`, initial: currentValue, onChange: updatePreview});
      if (sequence !== ticket) return;
      editor = next; mount(slot, next.element);
    }
    loading = false;
    updatePreview();
  };
  name.addEventListener('input', updatePreview);
  owner.addEventListener('change', () => ctx.call(refresh)); group.addEventListener('change', () => ctx.call(refresh));
  await refresh();
  return openDialog({title: previous ? `Edit ${previous.name}` : 'Create a named value', wide: true,
    content: h('div', {class: 'variables-fields'}, h('div', {class: 'variable-identity'}, field('Name', name), field('Scope', owner), field('Group', group)),
      slot, parameterFields, result, error),
    actions: [{label: 'Cancel', run: () => null}, {label: previous ? 'Apply value' : 'Create value', primary: true, run: async () => {
      if (loading) { error.textContent = 'Wait for the value choices to load.'; return false; }
      try {
        const value = group.value === 'sweeps' ? sweep() : editor.read();
        const document = saveEntry(root, {base: owner.value, name: name.value, group: group.value, value,
          parameter: !parameterFields.hidden && parameter.checked, units: units.value, help: help.value}, previous);
        const entry = entries(document).find(e => e.base === owner.value && e.group === group.value && e.name === name.value);
        const context = await schemaContext(ctx, document, entry.pointer);
        const problem = checkSchemaValue(context.schema, context.value, context.pointer, entry.value);
        if (problem) throw Error(problem);
        return {document, entry};
      } catch (fault) { error.textContent = fault.message; return false; }
    }}]});
}
