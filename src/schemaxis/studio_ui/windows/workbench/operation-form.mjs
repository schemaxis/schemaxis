// Copyright (C) 2026 David L. F. Gaden.
import {assertCollectionCapacity} from './collection-limit.mjs';
import {spatialAction, spatialRequest} from '../spatial/host.mjs';
import {spatialInput, spatialField, readSpatialInput, expressionValue, spatialFieldType, reportSpatialCheck, reportSpatialFault} from '../../editor/spatial-input.mjs';
// Recursive literal schema forms. Unknown/free JSON remains editable; required
// blanks become durable fill markers rather than plausible invented values.
import {conceptHelp, nativeBinding, correctionHelp, sameExplanation} from './concept-help.mjs';
import {createViewer3d} from '../../viewers/viewer3d.mjs';
import {presentationControl} from './presentation-controls.mjs';
import {subsetChips} from './subset-chips.mjs';
import {editVolume} from '../spatial/volume-editor.mjs';
import {quotedName} from '../spatial/volume-model.mjs';
import {readerSelection} from './reader-selection.mjs';
import {fileSubsetBrowser, inputBrowser} from './input-browser.mjs';
import {selectLine} from './line-selector.mjs';
import {initialOperation, nextIdentity, pipelineChoices} from './authoring-defaults.mjs';
import {referenceControl} from './pipeline-picker.mjs';
import {h, mount} from '../../lib/dom.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {validate} from '../../editor/schema-validate.mjs';
import {atPointer, replacing} from '../../editor/fill-data.mjs';
import {escapeSegment} from '../../editor/json-pointer.mjs';
import {chooseValue, manageVariables} from '../variables/panel.mjs';
import {GROUPS, scopes, ownerAt, equal, inspectionInput} from '../variables/model.mjs';
import {markers} from '../../editor/insert-fields.mjs';
import {isFill} from '../../editor/fill-data.mjs';
import {multiMode} from './multi-mode.mjs';
import {suggestedName, applyRows, savedNameHelp, instanceNames} from './element-authoring.mjs';
import {entryName} from './authoring-defaults.mjs';
import {contextTopic, decodePage} from '../help/model.mjs';
import {renderPage} from '../help/render.mjs';

export function resolve(spec, definitions) {
  if (!spec?.$ref) return spec || {};
  const key = spec.$ref.replace('#/$defs/', '').replaceAll('~1', '/').replaceAll('~0', '~');
  const result = {...definitions[key], ...Object.fromEntries(Object.entries(spec).filter(([key]) => key !== '$ref'))};
  const guide = definitions[key]?.['x-studio-guide'];
  if (guide) {
    const local = spec['x-studio-guide'];
    result['x-studio-guide'] = {...guide, ...(local?.explanation ? local : {}),
      ...(local?.authoring ? {authoring: local.authoring} : {})};
  }
  return result;
}
function supportsOutputPort(schema, definitions, depth = 0) {
  if (depth > 8) return false;
  const spec = resolve(schema, definitions);
  return Boolean(spec.properties?.node && spec.properties?.port)
    || Boolean(spec.items && supportsOutputPort(spec.items, definitions, depth + 1))
    || (spec.oneOf || spec.anyOf || []).some(branch => supportsOutputPort(branch, definitions, depth + 1));
}

export function marker(spec, label) {
  let type = spec.enum ? 'enum' : spatialFieldType(spec) || (['string', 'boolean'].includes(spec.type) ? spec.type : 'json');
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

function authoringLiteral(value) {
  if (expressionValue(value)) return {$fill: 'runtimeValue'};
  if (Array.isArray(value)) return value.map(authoringLiteral);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, authoringLiteral(child)]));
}

function control(raw, definitions, label, documentValue, seed, depth = 0, ctx = null, path = '') {
  // Preserve authored links and placeholders even when their literal schema is
  // an object/union. Opening a guided form must never flatten a runtime value.
  if ((expressionValue(seed) || isFill(seed)) && !spatialField(resolve(raw, definitions))) {
    let nested;
    const slot = h('div');
    const input = h('textarea', {class: 'input mono', 'aria-label': `${label} linked value`, value: JSON.stringify(seed)});
    const element = h('div', {class: 'operation-field'}, h('strong', {}, label.split('.').at(-1)),
      h('p', {class: 'wb-help'}, 'Linked value or placeholder · preserved until explicitly changed.'), input,
      h('button', {class: 'button small', type: 'button', onClick: () => {
        nested = control(raw, definitions, label, documentValue, undefined, depth, ctx, path);
        input.hidden = true; mount(slot, nested.element);
      }}, 'Replace using controls'), slot);
    return {element, read: () => nested ? nested.read() : JSON.parse(input.value)};
  }
  const result = literalControl(raw, definitions, label, documentValue, seed, depth, ctx, path);
  const spec = resolve(raw, definitions);
  if (!ctx?.pickValue || !path || Object.hasOwn(spec, 'const') || /\/(id|filter|version)$/.test(path)
      || !(spatialField(spec) || spec['x-studio-control']?.kind === 'camera' || spec.oneOf || spec.anyOf || ['string', 'number', 'integer', 'boolean', 'array'].includes(spec.type))) return result;
  let override;
  const status = h('code', {class: 'variables-preview', hidden: true});
  const reset = h('button', {type: 'button', class: 'button small', hidden: true, onClick: () => {
    override = undefined; status.hidden = reset.hidden = true;
  }}, 'Use typed value');
  result.element.append(h('button', {type: 'button', class: 'button small', 'aria-label': `Value or expression for ${label}`,
    onClick: () => ctx.call(async () => {
      const value = await ctx.pickValue(path);
      if (!value) return;
      override = value.value; status.textContent = JSON.stringify(override); status.hidden = reset.hidden = false;
    })}, spec['x-studio-control']?.kind === 'frame' ? 'Choose Spatial box or expression…' : 'Value or expression…'), status, reset);
  return {...result, read: () => override === undefined ? result.read() : override};
}

function literalControl(raw, definitions, label, documentValue, seed, depth = 0, ctx = null, path = '') {
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
    conceptHelp(spec['x-studio-guide'], label, ctx, {shown: spec.description}),
    h('details', {}, h('summary', {}, 'Schema details'), constraints.map(text => h('p', {}, text)),
      h('pre', {}, JSON.stringify(spec, null, 2))));
  const body = h('div', {class: 'operation-control'});
  const element = h('div', {class: 'operation-field'}, h('div', {class: 'operation-field-label'},
    h('strong', {}, spec.title || label.split('.').at(-1)), h('button', {class: 'button quiet small', type: 'button',
      'aria-label': `Help for ${label}`, onClick: () => { help.hidden = !help.hidden; element.classList.toggle('help-open', !help.hidden); }}, '?')), nativeBinding(spec['x-studio-guide']), spec.description && spec['x-studio-guide']?.status !== 'pending' ? h('p', {class: 'operation-field-description'}, spec.description) : null, help, body);
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
    const note = ctx?.existing ? 'Existing Name. If you rename it, update any references to it as well.'
      : 'Assigned automatically. Rename it if useful.';
    if (description) description.textContent = note;
    else element.insertBefore(h('p', {class: 'operation-field-description'}, note), help);
  }
  const presentation = presentationControl({spec, definitions, label, documentValue, initial, ctx, path,
    render: (schema, title, value, context = ctx, pointer = path) => control(schema, definitions, title, documentValue, value, depth + 1, context, pointer)});
  if (presentation) {
    element.classList.add('operation-presentation-' + spec['x-studio-control'].kind);
    if (spec['x-studio-control'].kind === 'sections') {
      element.querySelector('.operation-field-label').hidden = true;
      element.querySelector('.operation-field-description')?.remove();
    }
    body.append(presentation.element); return {element, read: presentation.read};
  }
  if (spec['x-studio-control']?.kind === 'reader-selection') {
    const picker = readerSelection({initial, label, field: spec['x-studio-control'].field, inspect: live => ctx.inspectReader(live),
      names: ctx.caseNames, fallback: spec.default});
    body.append(picker.element); return {element, read: picker.read};
  }
  if (spec['x-studio-reference']) {
    const reference = spec['x-studio-reference'];
    const target = referenceControl({documentValue, reference, initial, label, kinds: ctx?.operationKinds,
      allowPort: supportsOutputPort(spec, definitions),
      onChange: () => ctx?.inputListeners?.forEach(listener => listener())});
    if (reference.port) ctx?.inputReaders?.set(reference.port, target.read);
    body.append(target.element);
    return {element, read: () => target.read() ?? marker(spec, label)};
  }
  if (spec['x-studio-control']?.kind === 'blocks') {
    const getInput = () => ctx?.inputReaders?.get(spec['x-studio-control'].input)?.();
    const inspect = async () => {
      const reference = getInput();
      if (!reference || !ctx?.inspectNode) throw Error('Choose the pipeline input first.');
      const result = await ctx.inspectNode(reference, true);
      const blocks = (result.assemblies?.Hierarchy || []).filter(block => block.depth > 0);
      const parents = new Set(blocks.map(block => block.parent));
      const data = {available: true, regions: blocks.filter(block => !parents.has(block.selector)).map(block => block.label),
        scope: `Blocks reported by the application for ${typeof reference === 'string' ? reference : reference.node}.`};
      ctx.blockChoices?.set(reference, data);
      return data;
    };
    // Case-header hints stay available in every instance; native choices are
    // shared only by controls selecting the same pipeline input.
    const names = ctx?.blockChoices ? {
      get: () => ctx.blockChoices.get(getInput()) || ctx.caseNames?.get() || null,
      subscribe: listener => {
        const update = () => listener(names.get());
        const unsubscribe = ctx.caseNames?.subscribe(update);
        const unwatch = ctx.blockChoices.subscribe(reference => {
          if (JSON.stringify(reference) === JSON.stringify(getInput())) update();
        });
        return () => { unsubscribe?.(); unwatch(); };
      },
      load: async live => {
        const data = ctx.caseNames ? await ctx.caseNames.load(live) : await inspect();
        return ctx.blockChoices.get(getInput()) || data;
      },
    } : ctx?.caseNames;
    const picker = readerSelection({initial: isFill(initial) ? undefined : initial, label, field: 'regions', blocks: true, names,
      compact: Boolean(ctx?.draftSelection),
      required: () => ctx?.draftSelection ? [] : marker(spec, label), inspect});
    let inputIdentity = JSON.stringify(getInput());
    ctx?.inputListeners?.push(() => {
      const next = JSON.stringify(getInput());
      if (next !== inputIdentity) { inputIdentity = next; picker.invalidate(ctx.blockChoices?.get(getInput())); }
    });
    body.append(picker.element); return {element, read: picker.read};
  }
  const subset = spec['x-studio-control'];
  const assemblyPaths = subset?.kind === 'assembly-paths';
  const readerArrays = subset?.kind === 'reader-array-domain';
  if ((assemblyPaths || readerArrays || subset?.kind === 'dataset-arrays') && (initial === undefined || isFill(initial)
      || Array.isArray(initial) && initial.every(value => typeof value === 'string'))) {
    const picker = subsetChips({label, choices: [], initial: Array.isArray(initial) ? initial : [],
      choiceNoun: assemblyPaths ? 'block paths' : 'dataset arrays', preserveOrder: true});
    const inputReference = () => ctx?.inputReaders?.get(subset.input)?.();
    const assembly = () => assemblyPaths
      ? ctx?.optionReaders?.get(subset.assemblyOption)?.() ?? subset.defaultAssembly : null;
    const selectionScope = () => readerArrays ? ctx?.readerChoiceScope?.() : JSON.stringify([inputReference(), assembly()]);
    const status = h('p', {class: 'wb-help', role: 'status'},
      readerArrays ? 'Load names reported for the selected reader source.' : 'Load names from the selected input.');
    const name = h('input', {class: 'input', 'aria-label': assemblyPaths ? `Block selector for ${label}` : `Array name for ${label}`});
    const add = () => {
      if (name.value.trim()) { picker.add(name.value); name.value = ''; }
    };
    name.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); add(); }
    });
    let input = selectionScope(), revision = 0;
    ctx?.inputListeners?.push(() => {
      const current = selectionScope();
      if (current !== input) {
        input = current; revision++; picker.setChoices([]);
        status.textContent = 'The selection source changed. Load names to refresh the choices.';
      }
    });
    body.append(h('div', {class: 'wb-button-row'},
      h('button', {class: 'button small', type: 'button', onClick: async () => {
        const reference = inputReference(), request = ++revision, selected = assembly();
        input = selectionScope();
        if (assemblyPaths && typeof selected !== 'string') {
          status.textContent = 'Choose a literal assembly first.'; return;
        }
        if (readerArrays && !ctx?.inspectOwnReader) {
          status.textContent = 'Reader choices are unavailable in this form.'; return;
        }
        if (!readerArrays && (!reference || !ctx?.inspectNode)) { status.textContent = 'Choose the pipeline input first.'; return; }
        if (!readerArrays && typeof reference !== 'string' && typeof reference.node !== 'string') {
          status.textContent = 'Choose a literal pipeline input first.'; return;
        }
        status.textContent = 'Loading names…';
        try {
          const result = await (readerArrays ? ctx.inspectOwnReader() : ctx.inspectNode(reference, true));
          if (request !== revision || !body.isConnected || input !== selectionScope()) return;
          if (readerArrays) {
            const available = result.readerChoices?.[subset.field];
            picker.setChoices(Array.isArray(available) ? available.map(id => ({id, label: id})) : []);
            status.textContent = available ? 'Choices reported by the reader.' : 'The reader did not report choices for this field.';
          } else if (assemblyPaths) {
            const blocks = result.assemblies?.[selected];
            picker.setChoices(Array.isArray(blocks) ? blocks.filter(block => block.depth > 0)
              .map(block => ({id: block.selector, label: block.selector})) : []);
            status.textContent = blocks ? `Paths reported for ${selected}.` : `The input did not report ${selected}.`;
          } else {
            const reported = result.observation?.fields?.[subset.association];
            picker.setChoices(Object.keys(reported || {}).map(id => ({id, label: id})));
            status.textContent = reported ? 'Choices reported by the current input.' : 'The input did not report this array association.';
          }
        } catch (fault) {
          if (request === revision) status.textContent = fault.message;
        }
      }}, assemblyPaths ? 'Load block paths' : 'Load array names'), name,
      h('button', {class: 'button small', type: 'button', onClick: add}, assemblyPaths ? 'Add selector' : 'Add exact name')), status, picker.element);
    return {element, read: picker.read};
  }
  if (spec['x-studio-control']?.kind === 'document-nodes' && (initial === undefined
      || Array.isArray(initial) && initial.every(value => typeof value === 'string'))) {
    const choices = pipelineChoices(documentValue, spec['x-studio-control'].nodeKind, ctx?.operationKinds)
      .map(node => ({id: node.id, label: `${node.id} · ${node.filter || 'Object'}`}));
    const picker = subsetChips({label, choices, initial, preserveOrder: true});
    body.append(picker.element);
    return {element, read: picker.read};
  }
  if (subset?.kind === 'inspected-entries' && (initial === undefined
      || Array.isArray(initial) && initial.every(value => typeof value === 'string')
      && new Set(initial).size === initial.length)) {
    const picker = subsetChips({label, choices: [], initial, preserveOrder: true, choiceNoun: 'source names'});
    const current = () => {
      const draft = ctx.formDraft?.() || documentValue;
      const segments = ((ctx.formPointer?.() || '') + path).split('/');
      const parent = segments.slice(0, -1 - (subset.sourceLevels || 0)).join('/');
      const pointer = (subset.documentSource ? '' : parent) + subset.source;
      const source = subset.sourcePointer ? pointer : atPointer(draft, pointer);
      return {draft, source, fingerprint: JSON.stringify(replacing(draft, segments.join('/'), null))};
    };
    const status = h('p', {class: 'wb-help', role: 'status'});
    const name = h('input', {class: 'input', 'aria-label': `Exact name for ${label}`});
    let revision = 0, inspectedSource;
    ctx.formChanges?.add(() => {
      if (!body.isConnected) return false;
      if (inspectedSource === undefined) return true;
      let fingerprint;
      try { ({fingerprint} = current()); } catch { /* A draft field is incomplete. */ }
      if (fingerprint !== inspectedSource) {
        inspectedSource = undefined;
        revision++;
        picker.setChoices([]);
        status.textContent = 'The source changed. Load names to refresh the choices.';
      }
      return true;
    });
    const load = async () => {
      const request = ++revision;
      picker.setChoices([]);
      try {
        const {draft, source, fingerprint} = current();
        if (typeof source !== 'string' || !source) throw Error('Choose a source first.');
        inspectedSource = fingerprint;
        const provider = ctx.store.get().adaptors.find(a => a.routes.includes(draft.version))?.id;
        status.textContent = 'Loading names…';
        const endpoint = subset.native ? '/api/inspect-input' : '/api/peek-input';
        const response = await ctx.api.post(endpoint, {provider, input: draft, node: source});
        const result = subset.native ? (await ctx.api.waitForJob(response.job)).result : response;
        if (request !== revision || !body.isConnected || current().fingerprint !== fingerprint) return;
        const choices = result.readerChoices?.[subset.field];
        picker.setChoices(Array.isArray(choices) ? choices.map(id => ({id, label: id})) : []);
        status.textContent = result.scope || (choices ? 'Names reported by the selected source.' : 'No choices reported.');
      } catch (fault) {
        if (request === revision && body.isConnected) status.textContent = fault.message;
      }
    };
    body.append(h('div', {class: 'wb-button-row'},
      h('button', {class: 'button small', type: 'button', onClick: load}, 'Load source names'), name,
      h('button', {class: 'button small', type: 'button', onClick: () => {
        if (name.value.trim()) { picker.add(name.value); name.value = ''; }
      }}, 'Add exact name')), status, picker.element);
    return {element, read: picker.read};
  }
  if (subset?.kind === 'document-entries' && (initial === undefined
      || Array.isArray(initial) && initial.every(value => typeof value === 'string') && new Set(initial).size === initial.length)) {
    const choices = document => {
      const segments = ((ctx?.formPointer?.() || '') + path).split('/');
      const scope = subset.scopeDepth ? segments.slice(0, subset.scopeDepth + 1).join('/') : '';
      const fields = [subset.field].flat();
      const qualified = subset.qualified;
      const ownerScope = qualified?.activeDepth ? segments.slice(0, qualified.activeDepth + 1).join('/') : scope;
      const active = qualified && new Set(qualified.activeAt.map(pointer => atPointer(document, ownerScope + pointer)));
      const collections = [...(subset.rootCollections || []), ...[subset.collection].flat().map(path => (scope || '') + path)];
      const ids = collections.flatMap(collection => {
        const entries = [atPointer(document, collection)].flat().filter(entry => {
          if (!subset.match) return true;
          const matched = entry?.[subset.match.field] === subset.match.value;
          return subset.match.invert ? !matched : matched;
        });
        if (!qualified) return entries.flatMap(entry => fields.map(field => entry?.[field]));
        return entries.flatMap(entry => {
          const owner = entry?.[qualified.ownerField], members = entry?.[qualified.members];
          if (typeof owner !== 'string' || !active.has(owner) || !Array.isArray(members)) return [];
          return members.flatMap(member => fields.map(field => member?.[field]).filter(name => typeof name === 'string')
            .map(name => qualified.unqualified ? name : `${owner}.${name}`));
        });
      });
      return [...new Set(ids.filter(id => typeof id === 'string' && id && !subset.exclude?.includes(id)))]
        .map(id => ({id, label: id}));
    };
    const picker = subsetChips({label, choices: choices(documentValue), initial, preserveOrder: true,
      choiceNoun: 'declared names'});
    const name = h('input', {class: 'input', 'aria-label': `Exact name for ${label}`});
    body.append(h('div', {class: 'wb-button-row'},
      h('button', {class: 'button small', type: 'button', onClick: () => {
        try { picker.setChoices(choices(ctx?.formDraft?.() || documentValue)); }
        catch (fault) { ctx?.notify?.error?.(fault.message); }
      }}, 'Refresh choices'), name,
      h('button', {class: 'button small', type: 'button', onClick: () => {
        if (name.value.trim()) { picker.add(name.value.trim()); name.value = ''; }
      }}, 'Add exact name')), picker.element);
    return {element, read: picker.read};
  }
  if (subset?.kind === 'enum-subset' && (initial === undefined || isFill(initial)
      || Array.isArray(initial) && initial.every(value => typeof value === 'string') && new Set(initial).size === initial.length)) {
    const offered = subset.choices || resolve(spec.items, definitions).enum;
    const picker = subsetChips({label, choices: offered.map(id => ({id, label: id})),
      initial: Array.isArray(initial) ? initial : [], choiceNoun: 'choices', preserveOrder: true});
    body.append(picker.element);
    return {element, read: picker.read};
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
      nested = control(branches[Number(choice.value)], definitions, label, documentValue, initial, depth + 1, ctx, path);
      mount(slot, nested.element);
    };
    choice.addEventListener('change', refresh); refresh(); body.append(choice, slot);
    return {element, read: () => nested.read()};
  }
  if (spatialField(spec)) {
    const input = spatialInput({label, value: isFill(initial) ? undefined : initial, 'data-spatial-path': path});
    body.append(input.element);
    return {element, read: () => input.element.value === '' ? marker(spec, label) : input.read()};
  }
  if (spec.type === 'object' && spec.properties && depth < 12) {
    if (/\.(inputs|options)$/.test(label)) {
      element.querySelector('.operation-field-description')?.remove();
      element.querySelector('.operation-field-label').hidden = true;
    }
    const controls = Object.entries(spec.properties).map(([key, value]) => {
      const required = spec.required?.includes(key) || Object.hasOwn(value, 'const');
      const enabled = h('input', {type: 'checkbox', checked: required || Object.hasOwn(initial || {}, key)
        || ['reader-selection', 'blocks', 'line'].includes(resolve(value, definitions)['x-studio-control']?.kind),
        disabled: required, 'aria-label': `Include ${label}.${key}`});
      const nested = control(value, definitions, `${label}.${key}`, documentValue, initial?.[key], depth + 1, ctx, `${path}/${escapeSegment(key)}`);
      nested.element.hidden = !enabled.checked;
      enabled.addEventListener('change', () => { nested.element.hidden = !enabled.checked; });
      if (path === '/options' && ctx?.optionReaders) {
        ctx.optionReaders.set(key, () => enabled.checked ? nested.read() : undefined);
        const update = () => ctx.inputListeners?.forEach(listener => listener());
        enabled.addEventListener('change', update);
        nested.element.addEventListener('change', update);
      }
      return {key, enabled, nested, row: h('div', {class: 'operation-option'},
        required ? null : h('label', {}, enabled, ` Include ${resolve(value, definitions).title || key}${Object.hasOwn(resolve(value, definitions), 'default')
          ? ` (default: ${JSON.stringify(resolve(value, definitions).default)})` : ''}`), nested.element)};
    });
    if (depth === 0) {
      element.querySelector('.operation-field-label').hidden = true;
      for (const row of controls) {
        if (row.key === 'filter' && Object.hasOwn(spec.properties.filter, 'const')) row.row.hidden = true;
        if ((row.key === 'id' || (row.key === 'name' && initial?.name)) && initial?.[row.key]) {
          row.row.classList.add('operation-identity');
        }
      }
    }
    const identity = controls.filter(({enabled, key}) => enabled.disabled && ['id', 'name'].includes(key));
    body.append(...(depth === 0 ? identity : []).map(({row}) => row));
    body.append(...controls.filter(({enabled, key}) => enabled.disabled && key !== 'id' && key !== 'name').map(({row}) => row));
    body.append(...(depth === 0 ? [] : identity).map(({row}) => row));
    const optional = controls.filter(({enabled}) => !enabled.disabled);
    if (optional.length) body.append(h('details', {class: 'operation-optional',
      open: optional.some(({nested}) => nested.element.querySelector('.reader-selection'))},
      h('summary', {}, `Optional settings (${optional.length})`), optional.map(({row}) => row)));
    const widget = spec['x-studio-control'];
    if (widget?.kind === 'line') body.prepend(h('button', {class: 'button small', type: 'button', onClick: async () => {
      const start = controls.find(row => row.key === widget.start), end = controls.find(row => row.key === widget.end);
      const read = row => { try { return row.nested.read(); } catch { return undefined; } };
      const selected = await selectLine({start: read(start), end: read(end), getContext: ctx?.getSpatialContext});
      if (!selected || !body.isConnected) return;
      for (const [row, value] of [[start, selected.start], [end, selected.end]]) {
        const next = control(spec.properties[row.key], definitions, `${label}.${row.key}`, documentValue, value, depth + 1, ctx, `${path}/${escapeSegment(row.key)}`);
        row.nested.element.replaceWith(next.element); row.nested = next; row.enabled.checked = true;
      }
    }}, 'Place line endpoints…'));
    const read = () => Object.fromEntries(controls.filter(({enabled}) => enabled.checked)
      .map(({key, nested}) => [key, nested.read()]).filter(([, value]) => value !== undefined));
    const authoring = spec['x-studio-guide']?.authoring;
    if (authoring?.naming && ctx?.suggestAt === path) {
      const identity = authoring.identityField || (spec.properties.id ? 'id' : 'name');
      const input = controls.find(({key}) => key === identity)?.nested.element.querySelector('input.input');
      if (input) {
        const operation = label.split('.').at(-1).replace(/\[\d+\]$/, '');
        const item = {operation, authoring, maxNameLength: resolve(spec.properties[identity], definitions).maxLength};
        let overridden = false;
        input.addEventListener('input', () => { overridden = true; });
        const suggest = () => {
          if (overridden) return;
          try {
            const used = ctx.siblingNames(identity, authoring);
            const name = suggestedName(item, read(), used);
            if (name) input.value = name;
          } catch { /* Keep the previous suggestion while a setting is incomplete. */ }
        };
        for (const event of ['input', 'change', 'click']) body.addEventListener(event, suggest);
        suggest();
      }
    }
    return {element, read};
  }
  const bulkValues = ctx?.draftSelection && spec.maxItems > 128 && subset?.kind !== 'file-subset';
  if (spec.type === 'array' && spec.items && depth < 12 && !bulkValues) {
    const rows = []; const list = h('div', {});
    const memberSpec = resolve(spec.items, definitions);
    const variants = (memberSpec.oneOf || memberSpec.anyOf || [memberSpec])
      .map(branch => resolve(branch, definitions)).filter(branch => {
        const policy = branch['x-studio-guide']?.authoring;
        const when = policy?.when;
        return policy?.multiMode && (!when || when.scope === 'member' || when.values.includes(atPointer(documentValue, when.path)));
      });
    const variantFor = value => {
      if (!value) return null;
      const candidates = variants.filter(branch => {
        const when = branch['x-studio-guide'].authoring.when;
        if (when?.scope === 'member' && !when.values.includes(atPointer(value, when.path))) return false;
        return Object.entries(branch.properties).every(([key, schema]) => {
          if (Object.hasOwn(schema, 'const')) return Object.is(value[key], schema.const);
          return !schema.enum || value[key] === undefined || schema.enum.some(choice => Object.is(value[key], choice));
        });
      });
      return candidates.length <= 1 ? candidates[0] : candidates.find(
        branch => !validate({...branch, $defs: definitions}, authoringLiteral(value)).length);
    };
    const peerNames = (authoring, identity) => {
      if (!authoring.identityPeers?.length) return [];
      const pointer = (ctx.formPointer?.() || '') + path.slice(0, path.lastIndexOf('/'));
      const parent = atPointer(ctx.formDraft?.() || documentValue, pointer);
      return authoring.identityPeers.flatMap(key => Array.isArray(parent?.[key]) ? parent[key].map(member => member?.[identity]) : []);
    };
    async function configureInstances(current) {
      const members = read(), index = rows.indexOf(current), start = members[index];
      const branch = variantFor(start);
      if (!branch) throw Error('Complete the member settings before creating several instances.');
      const authoring = branch['x-studio-guide'].authoring;
      const identity = authoring.identityField ?? (branch.properties.id ? 'id' : 'name');
      if (identity && typeof start?.[identity] !== 'string') throw Error('Choose a Name for the starting member.');
      const memberName = start.kind || spec['x-studio-item-label'] || label.split('.').at(-1);
      const item = {operation: memberName, authoring,
        maxNameLength: resolve(branch.properties[identity], definitions).maxLength};
      const value = !identity || identity === 'id' ? start : {...start, id: start[identity]};
      const names = identity ? members.map(member => ({id: member?.[identity]})) : [];
      const memberPointer = (ctx.formPointer?.() || '') + path + '/' + index;
      const memberValue = identity && identity !== 'id'
        ? ({id, ...member}) => ({...member, [identity]: id}) : member => member;
      names.push(...peerNames(authoring, identity).map(id => ({id})));
      const multi = multiMode({item, documentValue: {nodes: names}, existing: {pointer: `/nodes/${index}`, value},
        readShared: () => value,
        selectionControl: (field, seed, title, readRow, scope) => {
          const fieldSchema = field.path.slice(1).split('/').reduce(
            (schema, key) => resolve(schema, definitions).properties[key], branch);
          const formDraft = () => replacing(ctx.formDraft?.() || documentValue, memberPointer, memberValue(readRow()));
          const formChanges = scope.formChanges ||= new Set();
          return control(fieldSchema, definitions, title, formDraft(), seed, depth + 1,
            {...ctx, formPointer: () => memberPointer, formDraft, formChanges, pickValue: null, draftSelection: true}, field.path);
        }});
      const error = h('p', {class: 'operation-error', role: 'alert'});
      const result = await openDialog({title: `${memberName} instances`, className: 'operation-dialog multi-mode-active',
        wide: true, enterSubmits: false, content: () => {
          queueMicrotask(multi.activate);
          return h('div', {class: 'operation-wizard multi-mode-active'}, multi.element, error);
        }, actions: [{label: 'Cancel', run: () => null}, {label: 'Use instances', primary: true, run: () => {
          try {
            if (!multi.active) return false;
            const selected = multi.read().map(memberValue);
            if (spec.maxItems !== undefined && members.length + selected.length - 1 > spec.maxItems)
              throw Error(`This collection can contain at most ${spec.maxItems} members.`);
            const diagnostics = selected.flatMap((member, i) =>
              validate({...branch, $defs: definitions}, authoringLiteral(member))
                .map(issue => `Instance ${i + 1} ${issue.pointer}: ${issue.message}`));
            if (diagnostics.length) { error.textContent = diagnostics.join('\n'); return false; }
            const resultingMembers = members.map((member, i) => i === index ? selected[0] : member).concat(selected.slice(1));
            for (const pointer of item.authoring.uniqueFields || []) {
              const literals = resultingMembers.map(member => atPointer(member, pointer))
                .filter(value => typeof value === 'string' || typeof value === 'number');
              if (new Set(literals).size !== literals.length) {
                const field = item.authoring.instanceFields.find(field => field.path === pointer);
                throw Error(`Each ${field.label} must be distinct in this collection.`);
              }
            }
            return selected;
          } catch (fault) { error.textContent = fault.message; return false; }
        }}]});
      if (!result || !body.isConnected) return;
      if (authoring.multiMode.validatePlan) ctx.requirePlan();
      members[index] = result[0];
      members.push(...result.slice(1));
      rows.length = 0; mount(list); members.forEach(add);
      body.dispatchEvent(new Event('change', {bubbles: true}));
    }
    const add = (seed) => {
      const index = rows.length, pointer = `${path}/${index}`;
      const memberContext = seed === undefined && ctx ? {...ctx, suggestAt: pointer, siblingNames: (identity, authoring) => {
        const names = new Set(peerNames(authoring, identity));
        rows.forEach((row, position) => {
          if (position === index) return;
          try { names.add(row.nested.read()?.[identity]); } catch { /* Another member is incomplete. */ }
        });
        return names;
      }} : ctx;
      const nested = control(spec.items, definitions, `${label}[${index}]`, documentValue, seed, depth + 1, memberContext, pointer);
      const row = {nested, synthetic: seed === undefined}; rows.push(row);
      const siblings = variants.length ? h('button', {class: 'button small', type: 'button', hidden: true,
        onClick: () => ctx.call(() => configureInstances(row), {title: 'Could not configure instances'})},
        'Create sibling instances…') : null;
      if (siblings) {
        const update = () => {
          try { siblings.hidden = !variantFor(nested.read()); }
          catch { siblings.hidden = true; }
        };
        nested.element.addEventListener('change', update);
        update();
      }
      const element = h('div', {class: 'operation-array-item'}, nested.element, siblings,
        h('button', {class: 'button quiet small', type: 'button', onClick: () => {
          // Rebuild survivors with their current index so value/expression
          // pickers cannot bind to a removed row's destination.
          try {
            const retained = rows.filter(item => item !== row).map(item => item.nested.read());
            rows.length = 0; mount(list); retained.forEach(add);
          } catch (fault) { ctx?.notify?.error?.(fault.message); }
        }}, spec['x-studio-item-label'] ? `Remove ${spec['x-studio-item-label']}` : 'Remove'));
      list.append(element);
    };
    if (Array.isArray(initial)) initial.forEach(add);
    else for (let i = 0; i < (spec.minItems || 0); i++) add();
    const fileType = spec['x-studio-control']?.kind === 'file-subset' ? resolve(spec.items, definitions) : null;
    const read = () => rows.map(({nested}) => nested.read());
    if (fileType) {
      body.append(fileSubsetBrowser(ctx, label, fileType['x-studio-file']?.extensions || [],
        () => read().find(value => typeof value === 'string') || '',
        files => {
          if (!body.isConnected) return;
          // A generated minimum row is a placeholder until the user sets it.
          const authored = read().filter((value, index) => !rows[index].synthetic || !isFill(value));
          const selection = files.filter(file => !authored.includes(file));
          rows.length = 0; mount(list); [...authored, ...selection].forEach(add);
          body.dispatchEvent(new Event('change', {bubbles: true}));
        }));
    }
    body.append(list, h('button', {class: 'button small', type: 'button', onClick: () => add()}, spec['x-studio-item-label'] ? `Add ${spec['x-studio-item-label']}` : `Add ${label} item`));
    return {element, read};
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
  if (!options.existing && item.collectionLimit && !/[{}]/.test(item.collectionLimit.path))
    assertCollectionCapacity(item.collectionLimit, getDocument());
  const documentValue = structuredClone(getDocument());
  const base = options.variableSnapshot?.base || '';
  const originalRoot = options.variableSnapshot?.root || documentValue;
  let stagedRoot = structuredClone(originalRoot);
  let planRequired = false;
  const localDocument = () => atPointer(stagedRoot, base);
  const draftIsCurrent = () => equal(getDocument(), documentValue);
  // The picker stages metadata in any scope; the synthetic operation only exists
  // for destination-schema checking until the Add form is committed.
  const copyMetadata = root => {
    for (const scope of scopes(stagedRoot)) {
      const source = atPointer(root, scope.base), target = atPointer(stagedRoot, scope.base);
      for (const key of [...GROUPS, 'sweeps']) {
        if (Object.hasOwn(source, key)) target[key] = structuredClone(source[key]);
        else delete target[key];
      }
    }
    if (Object.hasOwn(root, 'parameters')) stagedRoot.parameters = structuredClone(root.parameters);
  };
  const existing = options.existing || null;
  const collection = ['/nodes/-', '/scenes/-'].includes(item.at) ? item.at.slice(0, -2) : null;
  const seed = existing ? structuredClone(existing.value) : initialOperation(item, documentValue, options.selected, options.operationKinds);
  const withNode = node => existing ? replacing(documentValue, existing.pointer, node)
    : {...documentValue, nodes: [...(documentValue.nodes || []), node]};
  let caseData = null;
  const nameListeners = new Set();
  const blockSnapshots = new Map(), blockListeners = new Set();
  const blockChoices = options.blockChoices || {
    get: reference => blockSnapshots.get(JSON.stringify(reference)),
    set(reference, data) {
      blockSnapshots.set(JSON.stringify(reference), data);
      blockListeners.forEach(listener => listener(reference));
    },
    subscribe(listener) { blockListeners.add(listener); return () => blockListeners.delete(listener); },
  };
  ctx = {...ctx, getSpatialContext, operationKinds: options.operationKinds, existing: Boolean(existing),
    requirePlan: () => { planRequired = true; },
    usedNames: instanceNames(documentValue, collection || '/nodes'), visibilityListeners: new Set(), inputReaders: new Map(), optionReaders: new Map(), inputListeners: [], blockChoices};
  const reader = Boolean(item.schema['x-studio-prepare']);
  const shared = reader ? null : options.caseData || null;
  if (reader || shared) ctx.caseNames = {
    get: () => caseData || shared?.get() || null,
    subscribe: listener => { nameListeners.add(listener); return () => nameListeners.delete(listener); },
    load: async live => {
      caseData = reader ? await ctx.inspectReader(live) : await shared.load(live);
      if (!caseData) throw Error('No names could be read. Add an OpenFOAM reader with its case file first.');
      nameListeners.forEach(listener => listener(caseData));
      return caseData;
    }};
  const expert = ctx.setting?.('help.expert') === true;
  ctx.pickValue = async path => {
    const value = form.read(), at = existing ? existing.pointer : fillPath(item.at);
    if (at.includes('{')) throw Error('Choose the target scene or input first.');
    const parent = at.slice(0, at.lastIndexOf('/'));
    const pointer = at.endsWith('/-') ? `${parent}/${(atPointer(localDocument(), parent) || []).length}` : at;
    let root = structuredClone(localDocument());
    if (at.endsWith('/-')) root = replacing(root, parent, [...(atPointer(root, parent) || []), value]);
    else root = replacing(root, pointer, value);
    root = replacing(stagedRoot, base, root);
    const chosen = await chooseValue(ctx, {root, pointer: base + pointer + path});
    if (chosen) {
      copyMetadata(chosen.document);
    }
    return chosen;
  };
  ctx.createVolume = async () => {
    const result = await editVolume(ctx, {root: stagedRoot, base});
    if (!result) return null;
    copyMetadata(result.root);
    return {$expr: `${result.group}.${quotedName(result.name)}`};
  };
  ctx.sceneVisible = pointer => {
    try { const visible = atPointer(form.read(), (pointer || '') + '/visible'); if (visible) return visible; }
    catch { /* The form is still being constructed, or has an unfinished field. */ }
    const target = (existing?.pointer || fillPath(item.at)).split('/appearances')[0].split('/visible')[0];
    return atPointer(documentValue, target + (pointer || '') + '/visible') || {};
  };
  if (seed.id) ctx.usedNames.add(seed.id);
  ctx.inspectReader = async live => {
    const node = form.read();
    const provider = ctx.store.get().adaptors.find(a => a.routes.includes(documentValue.version))?.id;
    const input = inspectionInput(stagedRoot, withNode(node), base);
    if (!live) return ctx.api.post('/api/peek-input', {provider, input, node: node.id});
    const request = await ctx.api.post('/api/inspect-input', {provider, input, node: node.id, prepare: true});
    return (await ctx.api.waitForJob(request.job)).result;
  };
  const readerConstructors = Object.entries(item.bindings || {}).filter(([, binding]) => binding.constructor)
    .map(([key]) => key);
  ctx.readerChoiceScope = () => JSON.stringify(readerConstructors.map(key => ctx.optionReaders.get(key)?.()));
  ctx.inspectOwnReader = async (node = form.read()) => {
    const provider = ctx.store.get().adaptors.find(a => a.routes.includes(documentValue.version))?.id;
    if (JSON.stringify(getDocument()) !== JSON.stringify(documentValue))
      throw Error('The pipeline changed. Reopen this form to inspect the reader.');
    const input = inspectionInput(stagedRoot, withNode(node), base);
    const request = await ctx.api.post('/api/inspect-input', {provider, input, node: node.id});
    return (await ctx.api.waitForJob(request.job)).result;
  };
  let inspection = Promise.resolve(); const cache = new Map();
  ctx.inspectNode = async (reference, refresh = false) => {
    const node = typeof reference === 'string' ? reference : reference.node, port = reference.port || 0;
    const key = JSON.stringify([node, port]);
    if (JSON.stringify(getDocument()) !== JSON.stringify(documentValue)) throw Error('The pipeline changed. Reopen this form to inspect the current input.');
    if (refresh) cache.delete(key);
    if (!cache.has(key)) {
      const result = inspection.catch(() => {}).then(async () => {
        const provider = ctx.store.get().adaptors.find(adaptor => adaptor.routes.includes(documentValue?.version))?.id;
        const request = await ctx.api.post('/api/inspect-input', {provider, input: inspectionInput(stagedRoot, documentValue, base), node, port});
        return (await ctx.api.waitForJob(request.job)).result;
      });
      inspection = result; cache.set(key, result); result.catch(() => cache.delete(key));
    }
    return cache.get(key);
  };
  let form;
  const targets = h('div', {}); const selections = {};
  const error = h('p', {role: 'alert', class: 'operation-error'});
  let preparing = false;
  const fillPath = (path) => path.replace(/\{([^}]+)\}/g, (_, key) => selections[key] === undefined ? '{' + key + '}' : String(selections[key]).replaceAll('~', '~0').replaceAll('/', '~1'));
  const selectors = [];
  const refresh = (start = 0) => {
    for (let i = start; i < selectors.length; i++) {
      const {target, select} = selectors[i];
      let values = atPointer(documentValue, fillPath(target.collection)) || [];
      if (target.kind) values = values.filter(node => pipelineChoices(documentValue, target.kind, ctx.operationKinds).includes(node));
      mount(select, values.map((value, index) => h('option', {value: target.identity ? value.id : String(index)}, value.id || String(index))));
      selections[target.name] = select.value;
    }
  };
  for (const target of item.targets || []) {
    const select = h('select', {class: 'input', 'aria-label': target.label});
    const index = selectors.length;
    select.addEventListener('change', () => {
      selections[target.name] = select.value; refresh(index + 1);
      if (item.editTarget && form) {
        const next = makeForm(); form.element.replaceWith(next.element); form = next;
      }
    });
    selectors.push({target, select}); targets.append(h('label', {}, target.label, select));
  }
  refresh();
  const formPointer = () => {
    const pointer = existing?.pointer || fillPath(item.at);
    if (!pointer.endsWith('/-')) return pointer;
    const collection = pointer.slice(0, -2);
    return `${collection}/${(atPointer(documentValue, collection) || []).length}`;
  };
  const makeForm = () => {
    const formChanges = new Set();
    const rendered = control(item.schema, definitions, item.operation || item.title, documentValue,
      item.editTarget ? existing?.value || atPointer(documentValue, fillPath(item.at)) || {} : Object.keys(seed).length ? seed : undefined,
      0, {...ctx, formPointer, formChanges, formDraft: () => replacing(documentValue, formPointer(), form.read()),
        ...(item.editTarget ? {appearanceNode: existing?.pointer.split('/').at(-1).replaceAll('~1','/').replaceAll('~0','~') || selections.node} : {})});
    const notifyChanges = () => {
      for (const listener of formChanges) if (!listener()) formChanges.delete(listener);
    };
    rendered.element.addEventListener('input', notifyChanges);
    rendered.element.addEventListener('change', notifyChanges);
    return rendered;
  };
  form = makeForm();
  const referenceBody = h('div', {class: 'operation-reference'});
  const reference = item.operation ? h('details', {class: 'operation-about'}, h('summary', {}, '? Operation reference'), referenceBody) : null;
  let referenceLoaded = false, referenceId;
  async function showReference(id) {
    referenceBody.textContent = 'Loading operation reference…';
    try {
      const page = await decodePage(await ctx.api.get(`/help/${id}.json`));
      if (reference?.isConnected) mount(referenceBody, renderPage(page, (target) => showReference(target.id), ctx.notify,
        {omitParagraphs: id === referenceId ? [item.description, item.guidance?.explanation] : []}));
    } catch (fault) { referenceBody.textContent = fault.message; }
  }
  reference?.addEventListener('toggle', async () => {
    if (!reference.open || referenceLoaded) return;
    referenceLoaded = true;
    const provider = ctx.store.get().adaptors.find((a) => a.routes.includes(documentValue?.version))?.id;
    try {
      const index = await ctx.api.get('/help/index.json');
      const topic = contextTopic(index, {provider, operation: item.operation});
      referenceId = topic?.id;
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
    if (sameExplanation(paragraph.textContent, item.description)) { paragraph.remove(); break; }
  }
  let previewViewer;
  const previewHost = h('div', {class: 'reader-preview-3d', hidden: true});
  const previewState = h('p', {class: 'wb-help', role: 'status'});
  const describeNames = data => !data ? (reader ? 'Choose the file, then press Load names to pick regions and arrays from a list.'
    : 'Press Load names to list the regions and arrays of the case in this pipeline.')
    : data.available === false ? data.reason || data.message || 'No names could be read from this case.'
      : [`${data.regions?.length || 0} regions`, `${data.cellArrays?.length || 0} cell arrays`,
        `${data.availableTimes?.length || 0} times`, data.caseType].filter(Boolean).join(' · ');
  const loadNames = live => ctx.call(async () => {
    previewState.textContent = live ? 'Asking the application…' : 'Reading case headers…';
    try { await ctx.caseNames.load(live); }
    catch (fault) { previewState.textContent = fault.message; }
  });
  const caseTools = ctx.caseNames ? h('div', {class: 'operation-case-tools', role: 'toolbar', 'aria-label': 'Case data'},
      h('button', {class: 'button small', type: 'button', dataset: {action: 'load-case'},
        title: 'Read the case headers for region, array and time names. No mesh is loaded.',
        onClick: () => loadNames(false)}, 'Load names'),
      reader ? h('button', {class: 'button small', type: 'button', title: 'Load this reader in the application and show its geometry.',
        onClick: () => ctx.call(async () => {
          previewState.textContent = 'Loading selected reader data…';
          try {
            const node = form.read(), input = inspectionInput(stagedRoot, withNode(node), base);
            const provider = ctx.store.get().adaptors.find(a => a.routes.includes(documentValue.version))?.id;
            const request = await ctx.api.post('/api/inspect-input', {provider, input, node: node.id, geometry: true});
            const result = (await ctx.api.waitForJob(request.job)).result;
            if (!previewHost.isConnected) return;
            previewState.textContent = result.scope;
            if (result.geometry) { previewHost.hidden = false; previewViewer ||= createViewer3d(previewHost); await previewViewer.load(result.geometry); }
          } catch (fault) { previewState.textContent = fault.message; }
        })}, 'Live data preview') : null) : null;
  const readerPreview = ctx.caseNames ? h('div', {class: 'reader-preview'}, previewState, previewHost) : null;
  ctx.caseNames?.subscribe(data => { previewState.textContent = describeNames(data); });
  previewState.textContent = describeNames(ctx.caseNames?.get() || null);
  const root = item.operation || item.title;
  const nameInput = form.element.querySelector(`[aria-label="${CSS.escape(root + '.id')}"]`);
  const fileInput = form.element.querySelector(`[aria-label="${CSS.escape(root + '.options.file')}"]`);
  let assigned = nameInput?.value;
  let userNamed = options.userNamed ?? Boolean(existing);
  const lockedName = options.lockName ?? (typeof existing?.value?.id === 'string');
  const savedName = lockedName ? existing?.value.id : undefined;
  if (lockedName && nameInput) {
    nameInput.readOnly = true;
    nameInput.title = savedNameHelp;
    nameInput.closest('.operation-field').querySelector('.operation-field-description').textContent = savedNameHelp;
  }
  nameInput?.addEventListener('input', () => { userNamed = true; });
  const suggest = () => {
    if (userNamed || !nameInput) return;
    try {
      ctx.usedNames.delete(assigned);
      const next = suggestedName(item, form.read(), ctx.usedNames)
        || (item.authoring?.naming && !ctx.usedNames.has(seed.id) ? seed.id : null);
      if (next) nameInput.value = assigned = next;
      ctx.usedNames.add(assigned);
    } catch { /* Keep the previous suggestion while a field is incomplete. */ }
  };
  for (const event of ['input', 'change', 'click']) form.element.addEventListener(event, suggest);
  suggest();
  const fileChanged = () => {
    if (ctx.caseNames && fileInput.value.trim()) ctx.caseNames.load(false).catch(() => {});
    if (userNamed || !nameInput) return;
    ctx.usedNames.delete(assigned);
    const next = entryName(fileInput.value, ctx.usedNames);
    if (next) nameInput.value = assigned = next;
    ctx.usedNames.add(assigned);
  };
  fileInput?.addEventListener('change', fileChanged);
  if (existing && ctx.caseNames && fileInput?.value.trim()) ctx.caseNames.load(false).catch(() => {});

  // Final values: everything Settings left as a placeholder, answered in place.
  const answers = new Map();
  const answered = value => {
    if (Array.isArray(value)) return value.map(answered);
    if (isFill(value)) return answers.has(value.$fill) ? structuredClone(answers.get(value.$fill)) : value;
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, answered(child)]));
    return value;
  };
  const pending = () => {
    const seen = new Set();
    return markers(multi?.active ? multi.draft() : form.read()).filter(({marker}) => !seen.has(marker.$fill) && seen.add(marker.$fill));
  };
  const finalBody = h('div', {class: 'operation-final'});
  const finalField = ({pointer, marker: field}) => {
    const current = answers.get(field.$fill);
    const choices = field.type === 'enum' ? field.values : field.type === 'boolean' ? [true, false]
      : field.type === 'nodeRef' ? (documentValue.nodes || []).map(node => node?.id).filter(id => typeof id === 'string') : null;
    const numeric = ['number', 'integer'].includes(field.type);
    const state = h('small', {class: 'operation-error'});
    const names = !choices && !numeric && field.type !== 'json' && caseData?.available !== false
      ? [...(caseData?.cellArrays || []), ...(caseData?.regions || [])] : [];
    const list = names.length ? h('datalist', {id: 'final-names-' + Math.random().toString(36).slice(2)},
      names.map(name => h('option', {value: name}))) : null;
    const input = choices ? h('select', {class: 'input', 'aria-label': field.label || field.$fill},
      h('option', {value: ''}, 'Fill later…'), choices.map((choice, index) => h('option', {value: String(index),
        selected: JSON.stringify(choice) === JSON.stringify(current)}, typeof choice === 'string' ? choice : JSON.stringify(choice))))
      : spatialField(field) ? spatialInput({label: field.label || field.$fill, value: current, 'data-spatial-path': pointer}).element
      : h(field.type === 'json' ? 'textarea' : 'input', {class: ['input', field.type === 'json' && 'mono'], 'aria-label': field.label || field.$fill,
        ...(numeric ? {type: 'text'} : {}), ...(list ? {list: list.id} : {}),
        value: current === undefined ? '' : field.type === 'json' ? JSON.stringify(current) : String(current),
        placeholder: field.type === 'json' ? 'A JSON value, or leave to fill later' : 'Leave empty to fill later'});
    const update = () => {
      state.textContent = '';
      if (input.value === '') { answers.delete(field.$fill); return; }
      try {
        answers.set(field.$fill, choices ? choices[Number(input.value)] : spatialField(field) ? readSpatialInput(input.value)
          : field.type === 'json' ? JSON.parse(input.value) : input.value);
      } catch { answers.delete(field.$fill); state.textContent = 'Not a complete JSON value yet.'; }
    };
    input.addEventListener('input', update);
    input.addEventListener('change', update);
    return h('div', {class: 'operation-final-field'}, h('strong', {}, field.label || field.$fill),
      h('small', {class: 'wb-help mono'}, pointer), input, list,
      field.type === 'path' ? inputBrowser(ctx, input, field.label || field.$fill) : null, state);
  };
  const multiPolicy = item.authoring?.multiMode;
  const multi = multiPolicy && collection && !options.disableMultiMode ? multiMode({item, documentValue, existing,
    existingGroup: options.existingGroup, groupStartingValue: options.groupStartingValue,
    readShared: () => answered(form.read()), isUserNamed: () => userNamed,
    onActivate: () => {
      wizard.classList.add('multi-mode-active');
      const dialog = wizard.closest('.operation-dialog');
      dialog.classList.add('multi-mode-active');
      const title = `${item.title} · Multi-mode`;
      dialog.querySelector('.dialog-header h3').textContent = title;
      dialog.setAttribute('aria-label', title);
      dialog.querySelector('.dialog-footer .primary').textContent = 'Apply instances';
      [...dialog.querySelectorAll('.dialog-footer button')].find(button => button.textContent === 'Insert required placeholders')?.setAttribute('hidden', '');
      // The ordinary form is retained only as a local snapshot. It no longer
      // participates in focus, layout or editing after the mode switch.
      for (const child of settingsStep.children) if (child !== multi.element) child.hidden = true;
      finalStep.hidden = true;
    },
    selectionControl: (field, value, label, readRow, scope) => {
      const [, group, key] = field.path.split('/');
      const schema = field.path.slice(1).split('/').reduce(
        (owner, property) => resolve(owner, definitions).properties[property], item.schema);
      if (!scope.context) {
        const row = readRow();
        scope.context = {...ctx, pickValue: null, draftSelection: true, inputListeners: [],
          optionReaders: new Map(Object.keys(row.options || {}).map(key => [key, () => readRow().options?.[key]])),
          inspectOwnReader: () => ctx.inspectOwnReader(readRow()),
          readerChoiceScope: () => JSON.stringify(readerConstructors.map(key => readRow().options?.[key])),
          inputReaders: new Map(Object.keys(row.inputs || {}).map(port => [port, () => readRow().inputs?.[port]]))};
      }
      const rowContext = scope.context;
      let choicesDocument = documentValue;
      if (collection === '/nodes' && group === 'inputs') {
        const nodes = documentValue.nodes || [];
        const index = nodes.findIndex(node => node.id === readRow().id);
        if (index !== -1) choicesDocument = {...documentValue, nodes: item.inputOrder === 'preceding'
          ? nodes.slice(0, index) : nodes.filter((_, i) => i !== index)};
      }
      const rendered = control(schema, definitions, label, choicesDocument, value, 1, rowContext, field.path);
      if (collection === '/nodes' && group === 'options') {
        rowContext.optionReaders.set(key, rendered.read);
        rendered.element.addEventListener('change', () => rowContext.inputListeners.forEach(listener => listener()));
      }
      return rendered;
    },
    rowProperties: async (value, state) => {
      const original = state.original && (options.existingGroup?.find(member => member.value.id === value.id) || existing);
      const siblings = atPointer(localDocument(), collection) || [];
      const pointer = original ? original.pointer : `${collection}/${siblings.length}`;
      const snapshot = original ? replacing(localDocument(), pointer, value)
        : replacing(localDocument(), collection, [...siblings, value]);
      const root = replacing(stagedRoot, base, snapshot);
      const configured = await configureOperation(ctx, item, definitions, () => snapshot, getSpatialContext, {
        existing: {pointer, value}, variableSnapshot: {base, root}, caseData: ctx.caseNames,
        operationKinds: options.operationKinds, blockChoices, disableMultiMode: true,
        userNamed: state.userNamed, lockName: state.original, returnAuthoringState: true, returnToMultiMode: true,
      });
      if (!configured) return null;
      let updated = configured.variableRoot || root;
      for (const addition of configured.inserts || []) {
        if ([...GROUPS, 'sweeps'].some(group => addition.at === '/' + group))
          updated = replacing(updated, base + addition.at, addition.values[0]);
      }
      copyMetadata(updated);
      return {value: configured.replace.value, userNamed: configured.authoringState.userNamed};
    }}) : null;
  multi?.element.classList.add('operation-multi-view');
  const steps = [['settings', 'Settings'], ['final', 'Final values']];
  const navigation = () => h('nav', {class: 'wb-segmented operation-steps', 'aria-label': 'Screens'},
    steps.map(([id, label], index) => h('button', {type: 'button', dataset: {step: id}, onClick: () => showStep(id)},
      `${index + 1} · ${label}`)));
  const navigations = [navigation(), navigation()];
  const settingsStep = h('div', {class: 'operation-form operation-step'});
  const finalStep = h('div', {class: 'operation-step', hidden: true},
    h('p', {class: 'wb-help'}, 'Values that Settings left open. Anything left empty here stays a placeholder in the input and can be filled from the editor later.'),
    finalBody);
  const countPending = () => {
    let count = '';
    try { count = pending().filter(({marker}) => !answers.has(marker.$fill)).length; } catch { count = ''; }
    navigations.forEach(nav => { nav.lastChild.textContent = `2 · Final values${count === '' ? '' : ` (${count})`}`; });
  };
  function showStep(id) {
    if (id === 'final') {
      error.textContent = '';
      try {
        const fields = pending();
        mount(finalBody, fields.length ? fields.map(finalField) : h('p', {}, 'Nothing is left to fill. Every required value is set.'));
      } catch (fault) { error.textContent = fault.message; return; }
    }
    settingsStep.hidden = id !== 'settings';
    finalStep.hidden = id !== 'final';
    navigations.forEach(nav => [...nav.children].forEach(button => button.setAttribute('aria-current', String(button.dataset.step === id))));
    countPending();
    requestAnimationFrame(() => {
      const body = navigations[1].closest('.dialog-body');
      navigations[1].hidden = false;
      if (body) navigations[1].hidden = body.scrollHeight - navigations[1].offsetHeight <= body.clientHeight;
    });
  }
  let counting = 0;
  const recount = () => { clearTimeout(counting); counting = setTimeout(countPending, 250); };
  for (const type of ['input', 'change', 'click']) settingsStep.addEventListener(type, recount);
  finalStep.addEventListener('input', recount);
  mount(settingsStep, h('p', {class: 'operation-intro'}, item.description),
    h('button', {type: 'button', class: 'button small', onClick: () => ctx.call(() => manageVariables(ctx, {
      root: stagedRoot, base, label: base ? 'Workflow values · shared changes save together with the new operation.'
        : 'This adaptor input · changes are added with the operation.', commit: async value => { stagedRoot = value; },
    }))}, 'Variables & expressions'),
    item.schema['x-studio-prepare'] ? h('p', {class: 'wb-help operation-intro'}, item.schema['x-studio-prepare']) : null,
    item.coverage?.qualification ? h('p', {class: 'wb-help operation-intro'}, `Native qualification: ${item.coverage.qualification}. ${item.coverage.defaults || ''}`) : null,
    item.coverage?.gaps && Object.keys(item.coverage.gaps).length ? h('details', {class: 'operation-about'}, h('summary', {}, 'Known coverage gaps'),
      h('pre', {}, JSON.stringify(item.coverage.gaps, null, 2))) : null,
    targets, form.element, multi?.element,
    h('details', {class: 'operation-about'}, h('summary', {}, 'About this operation'),
      item.nativeDescription && !sameExplanation(item.nativeDescription, item.description)
        ? h('p', {class: 'wb-help'}, 'Application documentation: ', item.nativeDescription) : null,
      conceptHelp(item.guidance, item.title, ctx, {shown: item.description, correction: false}),
      item.requirements?.length ? h('details', {}, h('summary', {}, 'Application conventions and prerequisites'),
        h('ul', {}, item.requirements.map(text => h('li', {}, text)))) : null),
    reference, correctionHelp(item.guidance, item.title, ctx));
  const wizard = h('div', {class: ['operation-wizard', expert && 'expert']},
    h('div', {class: 'operation-top'}, navigations[0], caseTools,
      expert ? h('button', {class: 'button quiet small', type: 'button', 'aria-label': 'Show or hide the help text',
        title: 'Expert mode hides the help text. Show or hide it here; each setting has its own ? as well.',
        onClick: () => wizard.classList.toggle('help-open')}, '?') : null),
    readerPreview, settingsStep, finalStep, error, navigations[1]);
  showStep('settings');
  if (existing) targets.hidden = true;
  const title = options.returnToMultiMode ? `Properties · ${seed.id}`
    : `${existing ? `Edit ${seed.id || item.title}` : `Add ${item.title}`}${multi ? ' · Single instance' : ''}`;
  const dialogResult = openDialog({title, wide: true,
    enterSubmits: false, className: 'operation-dialog',
    content: wizard,
    actions: [{label: 'Cancel', run: () => null},
      ...(existing ? [] : [{label: 'Insert required placeholders', run: async () => {
        try { return await finish(required(), multi?.active ? multi.read() : null); }
        catch (fault) { error.textContent = fault.message; return false; }
      }}]),
      {label: existing ? 'Apply changes' : 'Add operation', primary: true,
        hint: options.returnToMultiMode ? 'Return to multi-mode' : undefined, run: async () => {
        if (preparing) return false;
        preparing = true;
        try {
          const multiple = multi?.active ? multi.read() : null;
          const value = answered(multiple ? multiple[0] : form.read());
          let metadata;
          if (!existing && reader && typeof value.options?.file === 'string') {
            const inspected = inspectionInput(stagedRoot, withNode(value), base);
            const provider = ctx.store.get().adaptors.find(a => a.routes.includes(documentValue.version))?.id;
            try {
              metadata = await ctx.api.post('/api/peek-input', {provider, input: inspected, node: value.id});
              if (!value.options.caseType && metadata.caseType) value.options.caseType = metadata.caseType;
            } catch { /* Header preview is optional; explicit authored choices remain available. */ }
          }
          const candidate = await finish(value, multiple);
          if (candidate && !existing && metadata?.availableTimes?.length && !Object.hasOwn(documentValue, 'times')) candidate.inserts.push({at: '/times', values: [[metadata.availableTimes[0]]]});
          return candidate;
        } catch (fault) { error.textContent = fault.message; return false; }
        finally { preparing = false; }
      }}]});
  if (options.existingGroup) multi?.activate();
  const answer = await dialogResult;
  previewViewer?.destroy();
  return answer && options.returnAuthoringState ? {...answer, authoringState: {userNamed}} : answer;
  async function finish(value, multiple = null) {
    const values = multiple ? multiple.map(answered) : [value];
    const collectionLimit = item.collectionLimit ? {...item.collectionLimit, path: fillPath(item.collectionLimit.path)} : undefined;
    if (!existing && collectionLimit && !/[{}]/.test(collectionLimit.path))
      assertCollectionCapacity(collectionLimit, getDocument(), values.length);
    if (!draftIsCurrent()) {
      error.textContent = 'The input changed while configuring this operation. Reopen it to select current targets.'; return false;
    }
    if (!existing && selectors.some(({select}) => !select.value)) {
      error.textContent = 'Add the target scene, image or node first.'; return false;
    }
    if (!multiple && typeof savedName === 'string' && value.id !== savedName) {
      error.textContent = 'A saved Name cannot be changed in Settings.'; return false;
    }
    if (!multiple && collection && typeof value.id === 'string') {
      const used = instanceNames(documentValue, collection);
      if (existing) used.delete(existing.value.id);
      if (used.has(value.id)) { error.textContent = `Name ${value.id} is already in use. Choose another Name.`; return false; }
    }
    const at = existing ? existing.pointer : fillPath(item.at);
    const parent = at.slice(0, at.lastIndexOf('/'));
    let target = at.endsWith('/-') ? `${parent}/${(atPointer(localDocument(), parent) || []).length}` : at;
    let draft = localDocument();
    draft = at.endsWith('/-') ? replacing(draft, parent, [...(atPointer(draft, parent) || []), value]) : replacing(draft, target, value);
    if (multiple) draft = applyRows(localDocument(), values, existing, options.existingGroup, item.authoring.identityStyle, collection);
    const authored = replacing(stagedRoot, base, draft);
    async function checked(value, path = '') {
      if (expressionValue(value)) {
        if (typeof value.$expr === 'string') {
          const response = await spatialAction(ctx.api, 'spatial_check', spatialRequest(authored, base, undefined,
            {expression: value.$expr, destination: target + path}));
          if (!response.ok) {
            const fields = [...wizard.querySelectorAll('[data-spatial-path]')].filter(input =>
              !input.closest('[hidden]') && (path === input.dataset.spatialPath || path.startsWith(input.dataset.spatialPath + '/')));
            if (fields.length === 1) reportSpatialCheck(fields[0], response);
            else reportSpatialFault(wizard, response.fault);
            throw Error(response.fault?.message || 'Expression refused');
          }
        }
        return {$fill: 'runtimeValue'};
      }
      if (!value || typeof value !== 'object') return value;
      const result = Array.isArray(value) ? [] : {};
      for (const [key, child] of Object.entries(value)) result[key] = await checked(child, `${path}/${escapeSegment(key)}`);
      return result;
    }
    let literal;
    const originalTarget = target;
    for (const [index, row] of values.entries()) {
      target = options.existingGroup?.[index]?.pointer || (index === 0 ? originalTarget
        : `${collection}/${(atPointer(localDocument(), collection) || []).length + index - (options.existingGroup?.length || (existing ? 1 : 0))}`);
      try { literal = await checked(row); }
      catch (fault) { error.textContent = fault.message; return false; }
      const diagnostics = validate({...item.schema, $defs: definitions}, literal);
      if (diagnostics.length) {
        error.textContent = diagnostics.map((item) => `${multiple ? `Element ${index + 1} ` : ''}${item.pointer || '/'}: ${item.message}`).join('\n');
        return false;
      }
    }
    if (collectionLimit) assertCollectionCapacity(collectionLimit, draft, 0);
    if (planRequired || multiple && multiPolicy.validatePlan) {
      const scope = options.validationScope;
      const input = !base && scope?.base && scope.root ? replacing(scope.root, scope.base, draft) : authored;
      const provider = ctx.store.get().adaptors.find(adaptor => adaptor.routes.includes(input.version))?.id;
      if (!provider) throw Error('The host planner for this input is unavailable.');
      const result = await ctx.api.post('/api/validate', {provider, source: JSON.stringify(input), format: 'json'});
      if (!draftIsCurrent()) throw Error('The input changed while checking instances. Reopen the settings to use the current input.');
      if (!result.valid) throw Error(result.diagnostics.map(fault => `${fault.location}: ${fault.message}`).join('\n'));
    }
    const fields = Object.fromEntries(markers(values).map(({marker}) => [marker.$fill,
      Object.fromEntries(Object.entries(marker).filter(([key]) => key !== '$fill'))]));
    const staged = localDocument();
    const additions = [...GROUPS, 'sweeps'].filter(group => JSON.stringify(staged[group]) !== JSON.stringify(documentValue[group])
      && staged[group] !== undefined).map(group => ({at: '/' + group, values: [staged[group]]}));
    const outsideChanged = !equal(replacing(stagedRoot, base, documentValue), originalRoot);
    const removed = [...GROUPS, 'sweeps'].some(group => documentValue[group] !== undefined && staged[group] === undefined);
    const authoringGroup = multiple ? {authoringGroup: multi.provenance()} : {};
    if (existing) return {id: item.id, title: item.title, fields, ...authoringGroup, replace: multiple
      ? {pointer: collection, value: atPointer(draft, collection)} : {pointer: existing.pointer, value},
      inserts: additions, ...(outsideChanged || removed ? {variableRoot: stagedRoot} : {})};
    return {id: item.id, title: item.title, fields, ...authoringGroup, ...(collectionLimit ? {collectionLimit} : {}), inserts: [...additions, {at: fillPath(item.at), values}],
      ...(outsideChanged || removed ? {variableRoot: stagedRoot} : {})};
  }
}
