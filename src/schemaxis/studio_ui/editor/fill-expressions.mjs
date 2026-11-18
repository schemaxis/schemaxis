// Copyright (C) 2026 David L. F. Gaden.
import {readSpatialInput, spatialInput, spatialField} from './spatial-input.mjs';
// Keyboard-accessible expression forms generated from the authored schema.
import {h} from '../lib/dom.mjs';
import {contextFor, expand} from './schema-core.mjs';
import {expressionNodes} from './fill-schema.mjs';
import {documentPointers} from './fill-data.mjs';

function constants(nodes, name, context) {
  return [...new Set(nodes.flatMap((node) => {
    const property = node.properties?.[name];
    const parts = context ? expand(context, context.adopt(node, property), undefined) : [property];
    return parts.flatMap((part) => part?.enum || (Object.hasOwn(part || {}, 'const') ? [part.const] : []));
  }))];
}

export function createExpressionForm({schema, value, pointer, kind, catalogue = {}, onChange}) {
  const element = h('div', {class: 'sx-fill-expression'});
  const controls = new Map();
  let extra = null;
  let reader = () => ({});
  const nodes = expressionNodes(schema, value, pointer).filter((node) => node.properties?.[kind]);
  const context = schema ? contextFor(schema) : null;
  const field = (label, initial, {choices, json = false, spatial = false} = {}) => {
    const input = choices?.length ? h('select', {'aria-label': label},
      choices.map((choice) => h('option', {value: String(choice)}, String(choice))))
      : spatial ? spatialInput({label, value: initial}).element
      : h('input', {type: 'text', 'aria-label': label, value: json ? JSON.stringify(initial) : String(initial ?? '')});
    if (choices?.length && choices.includes(initial)) input.value = String(initial);
    input.addEventListener('input', onChange);
    input.addEventListener('change', onChange);
    element.append(h('label', {class: 'sx-fill-control'}, h('span', {}, label), input));
    const read = () => spatial ? readSpatialInput(input.value) : json ? JSON.parse(input.value) : input.value;
    controls.set(label, input);
    return read;
  };
  const identity = (name) => typeof name === 'string' && name.length > 0;
  const ids = (Array.isArray(value?.nodes) ? value.nodes : []).map((node) => node?.id).filter(identity);
  const childNodes = (key, instance) => nodes.flatMap((node) =>
    expand(context, context.adopt(node, node.properties[key]), instance, true));

  if (kind === '$document') {
    const read = field('Document pointer', '', {choices: documentPointers(value)});
    reader = () => ({$document: read()});
  } else if (kind === '$sweep') {
    const names = (Array.isArray(value?.sweeps) ? value.sweeps : []).map((axis) => axis?.name).filter(identity);
    const name = field('Sweep', names[0] || 'sweep', {choices: [...names, 'Create a sweep…']});
    const newName = field('New sweep name', 'sweep');
    const values = field('New sweep values (JSON)', [0, 1], {json: true});
    const showCreation = () => {
      for (const key of ['New sweep name', 'New sweep values (JSON)']) {
        controls.get(key).parentElement.hidden = name() !== 'Create a sweep…';
      }
    };
    controls.get('Sweep').addEventListener('change', showCreation);
    showCreation();
    reader = () => {
      extra = null;
      if (name() === 'Create a sweep…') {
        if (!newName() || names.includes(newName())) throw new Error('Choose a new, unique sweep name.');
        const list = values();
        if (!Array.isArray(list) || !list.length) throw new Error('A sweep needs a nonempty values array.');
        extra = {name: newName(), values: list};
        return {$sweep: newName()};
      }
      return {$sweep: name()};
    };
  } else if (kind === '$value' || kind === '$call') {
    const allowed = constants(nodes, kind, context);
    const functions = Object.entries(catalogue.functions || {}).filter(([name, spec]) =>
      allowed.includes(name) && (kind === '$call' || (!spec.result?.objectKind
        && !Object.values(spec.arguments || {}).some((arg) => arg.objectKind))));
    const names = functions.map(([name]) => name);
    const chosen = field('Function', names[0] || '', {choices: names});
    const args = h('div', {class: 'sx-fill-arguments'});
    element.append(args);
    let argumentsRead = [];
    const updateArguments = () => {
      args.replaceChildren();
      argumentsRead = [];
      const spec = catalogue.functions?.[chosen()];
      for (const [name, declaration] of Object.entries(spec?.arguments || {})) {
        const initial = declaration.default ?? (declaration.type === 'string' ? ''
          : declaration.type === 'array' ? Array(declaration.minItems || 0).fill(0) : 0);
        const numeric = spatialField(declaration);
        const input = numeric ? spatialInput({label: `${name} argument`, value: initial}).element
          : h('input', {type: 'text', 'aria-label': `${name} argument`, value: JSON.stringify(initial)});
        input.addEventListener('input', onChange);
        args.append(h('label', {class: 'sx-fill-control'},
          h('span', {}, `${name} · ${declaration.type || declaration.objectKind}`
            + (declaration.required ? ' *' : '')), input));
        argumentsRead.push([name, () => numeric ? readSpatialInput(input.value) : JSON.parse(input.value)]);
      }
      onChange();
    };
    controls.get('Function').addEventListener('change', updateArguments);
    updateArguments();
    reader = () => {
      if (!chosen()) throw new Error('No compatible functions are available.');
      return {[kind]: chosen(), args: Object.fromEntries(argumentsRead.map(([name, read]) => [name, read()]))};
    };
  } else if (kind === '$analytic') {
    const allowed = constants(childNodes('$analytic'), 'type', context);
    const type = field('Analytic type', allowed[0], {choices: allowed});
    const values = field('Values (JSON array)', [0, 1], {json: true});
    const start = field('Start (number or vector)', 0, {spatial: true});
    const end = field('End (number or vector)', 1, {spatial: true});
    const count = field('Count', 5, {spatial: true});
    const elevation = field('Elevation', 0, {spatial: true});
    const showAnalytic = () => {
      controls.get('Values (JSON array)').parentElement.hidden = type() !== 'values';
      controls.get('Elevation').parentElement.hidden = type() !== 'orbit';
      for (const key of ['Start (number or vector)', 'End (number or vector)', 'Count']) {
        controls.get(key).parentElement.hidden = type() === 'values';
      }
    };
    controls.get('Analytic type').addEventListener('change', showAnalytic);
    showAnalytic();
    reader = () => {
      if (type() === 'values') return {$analytic: {type: 'values', values: values()}};
      const spec = {type: type(), start: start(), end: end(), count: count()};
      if (type() === 'orbit') spec.elevation = elevation();
      if (spec.count === 1 && [spec.start, spec.end].every(value => typeof value === 'number') && spec.start !== spec.end) {
        throw new Error('One sample requires equal endpoints.');
      }
      return {$analytic: spec};
    };
  } else if (kind === '$expr') {
    const shared = spatialInput({label: 'Expression', value: {$expr: ''}, onChange});
    element.append(shared.element); reader = shared.read;
  } else if (kind === '$calc') {
    const choices = constants(nodes, '$calc', context);
    const operation = field('Operation', choices.includes('add') ? 'add' : choices[0], {choices});
    const args = field('Arguments (JSON array)', [0, 1], {json: true});
    reader = () => ({$calc: operation(), args: args()});
  } else {
    const node = field('Source node', ids[0] || '', {choices: ids});
    if (kind === '$sample') {
      const association = field('Association', 'POINTS', {choices: constants(nodes, 'association', context)});
      const name = field('Field name', '');
      const index = field('Index', 0, {spatial: true});
      reader = () => ({$sample: node(), association: association(), field: name(), index: index()});
    } else {
      const path = field('Observation path (JSON array)', ['bounds'], {json: true});
      reader = () => ({$observe: node(), path: path()});
    }
  }
  return {element, read: () => ({value: reader(), axis: extra})};
}
