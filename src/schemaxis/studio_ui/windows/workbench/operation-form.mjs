// Copyright (C) 2026 David L F Gaden
// Recursive literal schema forms. Unknown/free JSON remains editable; required
// blanks become durable fill markers rather than plausible invented values.
import {conceptHelp, nativeBinding} from './concept-help.mjs';
import {inputBrowser} from './input-browser.mjs';
import {selectLine} from './line-selector.mjs';
import {initialOperation, identityPool, nextIdentity} from './authoring-defaults.mjs';
import {referenceControl} from './pipeline-picker.mjs';
import {blockControl} from './block-picker.mjs';
import {h, mount} from '../../lib/dom.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {validate} from '../../editor/schema-validate.mjs';
import {atPointer} from '../../editor/fill-data.mjs';
import {markers} from '../../editor/insert-fields.mjs';
import {contextTopic, decodePage} from '../help/model.mjs';
import {renderPage} from '../help/render.mjs';

export function resolve(spec, definitions) {
  if (!spec?.$ref) return spec || {};
  const key = spec.$ref.replace('#/$defs/', '').replaceAll('~1', '/').replaceAll('~0', '~');
  const result = {...definitions[key], ...Object.fromEntries(Object.entries(spec).filter(([key]) => key !== '$ref'))};
  if (!spec['x-studio-guide']?.explanation && definitions[key]?.['x-studio-guide']?.explanation) {
    result['x-studio-guide'] = definitions[key]['x-studio-guide'];
  }
  return result;
}
export function marker(spec, label) {
  let type = spec.enum ? 'enum' : ['string', 'number', 'integer', 'boolean'].includes(spec.type) ? spec.type : 'json';
  if (type === 'string') {
    if (/\.(id|name)$/.test(label)) type = 'id';
    else if (label.includes('.inputs.') || /\.(node|source|geometry)(\[\d+\])?$/.test(label)) type = 'nodeRef';
    else if (/\.(file|FileName|FileNames|Filename)(\[\d+\])?$/.test(label)) type = 'path';
  }
  return {$fill: label.replace(/[^A-Za-z0-9_-]/g, '_'), label, type, required: true,
    ...(spec.enum ? {values: spec.enum} : {}),
    ...(Object.hasOwn(spec, 'default') ? {default: spec.default} : {}),
    ...Object.fromEntries(['minimum', 'maximum', 'minLength', 'maxLength', 'pattern'].filter(key => Object.hasOwn(spec, key))
      .map(key => [key, spec[key]]))};
}
export function requiredTemplate(raw, definitions, label = 'value') {
  const spec = resolve(raw, definitions);
  if (Object.hasOwn(spec, 'const')) return spec.const;
  if (spec.enum?.length === 1) return spec.enum[0];
  const branches = spec.oneOf || spec.anyOf;
  if (branches) return requiredTemplate(branches[0], definitions, label);
  if (spec.type === 'object' && spec.properties) return Object.fromEntries(
    Object.entries(spec.properties).filter(([key, value]) => spec.required?.includes(key) || Object.hasOwn(value, 'const'))
      .map(([key, value]) => [key, requiredTemplate(value, definitions, `${label}.${key}`)]));
  return marker(spec, label);
}

function control(raw, definitions, label, documentValue, seed, depth = 0, ctx = null) {
  const spec = resolve(raw, definitions);
  const constraints = [];
  if (spec.type) constraints.push(`Value type: ${[].concat(spec.type).join(' or ')}.`);
  if (spec.enum) constraints.push(`Allowed values: ${spec.enum.map(value => JSON.stringify(value)).join(', ')}.`);
  if (Object.hasOwn(spec, 'default')) constraints.push(`Default when omitted: ${JSON.stringify(spec.default)}.`);
  for (const [key, wording] of [['minimum', 'At least'], ['maximum', 'At most'],
    ['exclusiveMinimum', 'Greater than'], ['exclusiveMaximum', 'Less than'],
    ['minItems', 'Minimum number of items:'], ['maxItems', 'Maximum number of items:'],
    ['minLength', 'Minimum text length:'], ['maxLength', 'Maximum text length:']]) {
    if (Object.hasOwn(spec, key)) constraints.push(`${wording} ${spec[key]}.`);
  }
  if (spec.pattern) constraints.push(`Text must match ${spec.pattern}.`);
  const help = h('div', {class: 'operation-field-help', hidden: true},
    conceptHelp(spec['x-studio-guide'], label, ctx),
    h('details', {}, h('summary', {}, 'Schema details'), constraints.map(text => h('p', {}, text)),
      h('pre', {}, JSON.stringify(spec, null, 2))));
  const body = h('div', {class: 'operation-control'});
  const element = h('div', {class: 'operation-field'}, h('div', {class: 'operation-field-label'},
    h('strong', {}, spec.title || label.split('.').at(-1)), h('button', {class: 'button quiet small', type: 'button',
      'aria-label': `Help for ${label}`, onClick: () => { help.hidden = !help.hidden; }}, '?')), nativeBinding(spec['x-studio-guide']), spec.description && spec['x-studio-guide']?.status !== 'pending' ? h('p', {class: 'operation-field-description'}, spec.description) : null, help, body);
  if (Object.hasOwn(spec, 'const') || spec.enum?.length === 1) {
    const value = Object.hasOwn(spec, 'const') ? spec.const : spec.enum[0];
    body.append(h('code', {}, JSON.stringify(value)));
    return {element, read: () => value};
  }
  let initial = seed === undefined ? spec.default : seed;
  if (label.endsWith('.id') && spec.type === 'string' && initial === undefined && ctx?.usedNames) {
    initial = nextIdentity(label.split('.').at(-2).replace(/\[\d+\]/g, '') || 'item', ctx.usedNames);
  }
  if (label.endsWith('.id') && spec.type === 'string') {
    element.querySelector('strong').textContent = 'Name';
    const description = element.querySelector('.operation-field-description');
    if (description) description.textContent = 'Assigned automatically. Rename it if useful.';
    else element.insertBefore(h('p', {class: 'operation-field-description'}, 'Assigned automatically. Rename it if useful.'), help);
  }
  if (spec['x-studio-reference']) {
    const reference = spec['x-studio-reference'];
    const target = referenceControl({documentValue, reference, initial, label, kinds: ctx?.operationKinds,
      allowPort: JSON.stringify(spec).includes('"port"') || JSON.stringify(spec).includes('dataReference'),
      onChange: () => ctx?.inputListeners?.forEach(listener => listener())});
    if (reference.port) ctx?.inputReaders?.set(reference.port, target.read);
    body.append(target.element);
    return {element, read: () => target.read() ?? marker(spec, label)};
  }
  if (spec['x-studio-control']?.kind === 'blocks') {
    const picker = blockControl({initial, getInput: () => ctx?.inputReaders?.get(spec['x-studio-control'].input)?.(),
      inspect: ctx?.inspectNode, subscribe: callback => ctx?.inputListeners?.push(callback)});
    body.append(picker.element); return {element, read: picker.read};
  }
  const branches = spec.oneOf || spec.anyOf;
  if (branches && depth < 12) {
    const choice = h('select', {class: 'input', 'aria-label': `${label} value kind`}, branches.map((branch, index) => {
      const value = resolve(branch, definitions);
      return h('option', {value: String(index)}, value.title || value.properties?.type?.const || value.properties?.type?.enum?.join(', ')
        || value.properties?.writer?.const || value.properties?.filter?.const || value.type || (value.enum ? 'Listed value' : `Alternative ${index + 1}`));
    }));
    const index = initial === undefined ? 0 : branches.findIndex((branch) => !validate(
      {...resolve(branch, definitions), $defs: definitions}, initial).length);
    choice.value = String(Math.max(0, index));
    const slot = h('div', {}); let nested;
    const refresh = () => {
      nested = control(branches[Number(choice.value)], definitions, label, documentValue, initial, depth + 1, ctx);
      mount(slot, nested.element);
    };
    choice.addEventListener('change', refresh); refresh(); body.append(choice, slot);
    return {element, read: () => nested.read()};
  }
  if (spec.type === 'object' && spec.properties && depth < 12) {
    if (/\.(inputs|options)$/.test(label)) {
      element.querySelector('.operation-field-description')?.remove();
      element.querySelector('.operation-field-label').hidden = true;
    }
    const controls = Object.entries(spec.properties).map(([key, value]) => {
      const required = spec.required?.includes(key) || Object.hasOwn(value, 'const');
      const enabled = h('input', {type: 'checkbox', checked: required || Object.hasOwn(initial || {}, key)
        || Boolean(resolve(value, definitions)['x-studio-control']),
        disabled: required, 'aria-label': `Include ${label}.${key}`});
      const nested = control(value, definitions, `${label}.${key}`, documentValue, initial?.[key], depth + 1, ctx);
      nested.element.hidden = !enabled.checked;
      enabled.addEventListener('change', () => { nested.element.hidden = !enabled.checked; });
      return {key, enabled, nested, row: h('div', {class: 'operation-option'},
        required ? null : h('label', {}, enabled, ` Include ${resolve(value, definitions).title || key}${Object.hasOwn(resolve(value, definitions), 'default')
          ? ` (default: ${JSON.stringify(resolve(value, definitions).default)})` : ''}`), nested.element)};
    });
    if (depth === 0) {
      element.querySelector('.operation-field-label').hidden = true;
      for (const row of controls) {
        if (row.key === 'filter' && Object.hasOwn(spec.properties.filter, 'const')) row.row.hidden = true;
        if ((row.key === 'id' || (row.key === 'name' && initial?.name)) && initial?.[row.key]) {
          const details = h('details', {class: 'operation-identity'}, h('summary', {}, `Name: ${initial[row.key]}`), row.nested.element);
          row.row = details;
        }
      }
    }
    body.append(...controls.filter(({enabled, key}) => enabled.disabled && key !== 'id' && key !== 'name').map(({row}) => row));
    body.append(...controls.filter(({enabled, key}) => enabled.disabled && ['id', 'name'].includes(key)).map(({row}) => row));
    const optional = controls.filter(({enabled}) => !enabled.disabled);
    if (optional.length) body.append(h('details', {class: 'operation-optional'},
      h('summary', {}, `Optional settings (${optional.length})`), optional.map(({row}) => row)));
    const widget = spec['x-studio-control'];
    if (widget?.kind === 'line') body.prepend(h('button', {class: 'button small', type: 'button', onClick: async () => {
      const start = controls.find(row => row.key === widget.start), end = controls.find(row => row.key === widget.end);
      const read = row => { try { return row.nested.read(); } catch { return undefined; } };
      const selected = await selectLine({start: read(start), end: read(end), getContext: ctx?.getSpatialContext});
      if (!selected || !body.isConnected) return;
      for (const [row, value] of [[start, selected.start], [end, selected.end]]) {
        const next = control(spec.properties[row.key], definitions, `${label}.${row.key}`, documentValue, value, depth + 1, ctx);
        row.nested.element.replaceWith(next.element); row.nested = next; row.enabled.checked = true;
      }
    }}, 'Place line endpoints…'));
    return {element, read: () => Object.fromEntries(controls.filter(({enabled}) => enabled.checked)
      .map(({key, nested}) => [key, nested.read()]))};
  }
  if (spec.type === 'array' && spec.minItems === 3 && spec.maxItems === 3 && spec.items?.type === 'number') {
    const inputs = ['X', 'Y', 'Z'].map((axis, index) => h('input', {class: 'input', type: 'number', step: 'any',
      'aria-label': `${label}[${index}]`, value: Array.isArray(initial) ? initial[index] : ''}));
    body.append(h('div', {class: 'line-selector-coordinates'}, inputs.map((input, i) => h('label', {}, 'XYZ'[i], input))));
    return {element, read: () => inputs.some(input => input.value === '') ? marker(spec, label) : inputs.map(input => Number(input.value))};
  }
  if (spec.type === 'array' && spec.items && depth < 12) {
    const rows = []; const list = h('div', {});
    const add = (seed) => {
      const nested = control(spec.items, definitions, `${label}[${rows.length}]`, documentValue, seed, depth + 1, ctx);
      const row = {nested}; rows.push(row);
      const element = h('div', {class: 'operation-array-item'}, nested.element,
        h('button', {class: 'button quiet small', type: 'button', onClick: () => {
          rows.splice(rows.indexOf(row), 1); element.remove();
        }}, 'Remove'));
      list.append(element);
    };
    if (Array.isArray(initial)) initial.forEach(add);
    else for (let i = 0; i < (spec.minItems || 0); i++) add();
    body.append(list, h('button', {class: 'button small', type: 'button', onClick: () => add()}, `Add ${label} item`));
    return {element, read: () => rows.map(({nested}) => nested.read())};
  }
  if (spec.enum || spec.type === 'boolean') {
    const values = spec.enum || [true, false];
    const input = h('select', {class: 'input', 'aria-label': label}, h('option', {value: ''}, 'Fill later…'),
      values.map((value, index) => h('option', {value: String(index)}, JSON.stringify(value))));
    input.value = initial === undefined ? '' : String(values.findIndex((value) => JSON.stringify(value) === JSON.stringify(initial)));
    body.append(input);
    return {element, read: () => input.value === '' ? marker(spec, label) : values[Number(input.value)]};
  }
  const text = spec.type === 'string';
  const numeric = ['number', 'integer'].includes(spec.type);
  const input = h(text || numeric ? 'input' : 'textarea', {class: 'input', 'aria-label': label,
    ...(numeric ? {type: 'number', step: spec.type === 'integer' ? '1' : 'any'} : {}),
    value: initial === undefined ? '' : text ? initial : JSON.stringify(initial),
    placeholder: text ? 'Fill later or enter text' : numeric ? 'Fill later or enter a number' : 'JSON value (or fill later)'});
  // Reference suggestions retain arbitrary authored IDs and explicit port objects.
  if (text && (label.includes('.inputs.') || /\.(node|geometry|source)$/.test(label))) {
    const id = 'operation-refs-' + Math.random().toString(36).slice(2);
    input.setAttribute('list', id);
    body.append(h('datalist', {id}, (documentValue?.nodes || []).map((node) => h('option', {value: node.id}))));
  }
  body.append(input);
  if (text && spec['x-studio-file'] && ctx) {
    body.append(inputBrowser(ctx, input, label, spec['x-studio-file'].extensions));
  }
  return {element, read: () => input.value === '' ? marker(spec, label)
    : text ? input.value : JSON.parse(input.value)};
}

export async function configureOperation(ctx, item, definitions, getDocument, getSpatialContext, options = {}) {
  const documentValue = getDocument();
  const seed = initialOperation(item, documentValue, options.selected, options.operationKinds);
  ctx = {...ctx, getSpatialContext, operationKinds: options.operationKinds,
    usedNames: identityPool(documentValue), inputReaders: new Map(), inputListeners: []};
  if (seed.id) ctx.usedNames.add(seed.id);
  let inspection = Promise.resolve(); const cache = new Map();
  ctx.inspectNode = async (reference, refresh = false) => {
    const node = typeof reference === 'string' ? reference : reference.node, port = reference.port || 0;
    const key = JSON.stringify([node, port]);
    if (JSON.stringify(getDocument()) !== JSON.stringify(documentValue)) throw Error('The pipeline changed. Reopen this form to inspect the current input.');
    if (refresh) cache.delete(key);
    if (!cache.has(key)) {
      const result = inspection.catch(() => {}).then(async () => {
        const provider = ctx.store.get().adaptors.find(adaptor => adaptor.routes.includes(documentValue?.version))?.id;
        const request = await ctx.api.post('/api/inspect-input', {provider, input: documentValue, node, port});
        return (await ctx.api.waitForJob(request.job)).result;
      });
      inspection = result; cache.set(key, result); result.catch(() => cache.delete(key));
    }
    return cache.get(key);
  };
  const form = control(item.schema, definitions, item.operation || item.title, documentValue, Object.keys(seed).length ? seed : undefined, 0, ctx);
  const targets = h('div', {}); const selections = {};
  const error = h('p', {role: 'alert', class: 'operation-error'});
  let preparing = false;
  const fillPath = (path) => path.replace(/\{([^}]+)\}/g, (_, key) => selections[key] === undefined ? '{' + key + '}' : String(selections[key]).replaceAll('~', '~0').replaceAll('/', '~1'));
  const selectors = [];
  const refresh = (start = 0) => {
    for (let i = start; i < selectors.length; i++) {
      const {target, select} = selectors[i];
      const values = atPointer(documentValue, fillPath(target.collection)) || [];
      mount(select, values.map((value, index) => h('option', {value: target.identity ? value.id : String(index)}, value.id || String(index))));
      selections[target.name] = select.value;
    }
  };
  for (const target of item.targets || []) {
    const select = h('select', {class: 'input', 'aria-label': target.label});
    const index = selectors.length;
    select.addEventListener('change', () => { selections[target.name] = select.value; refresh(index + 1); });
    selectors.push({target, select}); targets.append(h('label', {}, target.label, select));
  }
  refresh();
  const referenceBody = h('div', {class: 'operation-reference'});
  const reference = item.operation ? h('details', {}, h('summary', {}, '? Operation reference'), referenceBody) : null;
  let referenceLoaded = false;
  async function showReference(id) {
    referenceBody.textContent = 'Loading operation reference…';
    try {
      const page = await decodePage(await ctx.api.get(`/help/${id}.json`));
      if (reference?.isConnected) mount(referenceBody, renderPage(page, (target) => showReference(target.id), ctx.notify));
    } catch (fault) { referenceBody.textContent = fault.message; }
  }
  reference?.addEventListener('toggle', async () => {
    if (!reference.open || referenceLoaded) return;
    referenceLoaded = true;
    const provider = ctx.store.get().adaptors.find((a) => a.routes.includes(documentValue?.version))?.id;
    try {
      const index = await ctx.api.get('/help/index.json');
      const topic = contextTopic(index, {provider, operation: item.operation});
      await showReference(topic?.id || index.home);
    } catch (fault) { referenceBody.textContent = fault.message; referenceLoaded = false; }
  });
  const required = () => {
    const value = requiredTemplate(item.schema, definitions, item.operation || item.title);
    if (!Object.keys(seed).length) return value;
    return {...value, ...seed, ...(seed.inputs ? {inputs: {...value.inputs, ...seed.inputs}} : {})};
  };
  // The node's own description repeats the operation explanation shown above it.
  for (const paragraph of form.element.querySelectorAll('.operation-field-description')) {
    if (paragraph.textContent === item.description) { paragraph.remove(); break; }
  }
  return openDialog({title: `Add ${item.title}`, wide: true,
    content: h('div', {class: 'operation-form'}, h('p', {}, item.description),
      item.schema['x-studio-prepare'] ? h('p', {class: 'wb-help'}, item.schema['x-studio-prepare']) : null,
      item.coverage?.qualification ? h('p', {class: 'wb-help'}, `Native qualification: ${item.coverage.qualification}. ${item.coverage.defaults || ''}`) : null,
      item.coverage?.gaps && Object.keys(item.coverage.gaps).length ? h('details', {}, h('summary', {}, 'Known coverage gaps'),
        h('pre', {}, JSON.stringify(item.coverage.gaps, null, 2))) : null,
      targets, form.element, error,
      h('details', {}, h('summary', {}, 'About this operation'),
        item.nativeDescription ? h('p', {class: 'wb-help'}, 'Application documentation: ', item.nativeDescription) : null,
        conceptHelp(item.guidance, item.title, ctx), reference,
        item.requirements?.length ? h('details', {}, h('summary', {}, 'Application conventions and prerequisites'),
          h('ul', {}, item.requirements.map(text => h('li', {}, text)))) : null)),
    actions: [{label: 'Cancel', run: () => null},
      {label: 'Insert required placeholders', run: () => finish(required())},
      {label: 'Add operation', primary: true, run: async () => {
        if (preparing) return false;
        try {
          const value = form.read(), candidate = finish(value);
          if (!candidate || !item.schema['x-studio-prepare'] || markers(value).length) return candidate;
          preparing = true; error.textContent = 'Reading case settings…';
          const provider = ctx.store.get().adaptors.find(adaptor => adaptor.routes.includes(documentValue?.version))?.id;
          const request = await ctx.api.post('/api/inspect-input', {provider, input: {...documentValue, nodes: [...(documentValue.nodes || []), value]}, node: value.id, prepare: true});
          const result = (await ctx.api.waitForJob(request.job)).result;
          if (!form.element.isConnected) return false;
          const prepared = finish(result.value);
          if (prepared && result.times && !Object.hasOwn(documentValue, 'times')) prepared.inserts.push({at: '/times', values: [result.times]});
          if (prepared) ctx.notify?.ok('Reader configured', {body: result.summary});
          return prepared;
        } catch (fault) { error.textContent = fault.message; return false; }
        finally { preparing = false; }
      }}]});
  function finish(value) {
    if (getDocument() !== documentValue && JSON.stringify(getDocument()) !== JSON.stringify(documentValue)) {
      error.textContent = 'The input changed while configuring this operation. Reopen it to select current targets.'; return false;
    }
    if (selectors.some(({select}) => !select.value)) {
      error.textContent = 'Add the target scene, image or node first.'; return false;
    }
    const diagnostics = validate({...item.schema, $defs: definitions}, value);
    if (diagnostics.length) {
      error.textContent = diagnostics.map((item) => `${item.pointer || '/'}: ${item.message}`).join('\n'); return false;
    }
    const fields = Object.fromEntries(markers(value).map(({marker}) => [marker.$fill,
      Object.fromEntries(Object.entries(marker).filter(([key]) => key !== '$fill'))]));
    return {id: item.id, title: item.title, fields, inserts: [{at: fillPath(item.at), values: [value]}]};
  }
}
