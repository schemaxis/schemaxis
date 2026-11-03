// Copyright (C) 2026 David L F Gaden
// Parameter values preserve JSON types; constraints remain authoritative on the server.
import {h} from '../../lib/dom.mjs';
import {ApiError} from '../../lib/api.mjs';

export function parseParameter(spec, raw) {
  if (raw === '' && spec.kind !== 'string') {
    return undefined;
  }
  if (spec.kind === 'boolean') {
    if (!['true', 'false'].includes(raw)) {
      throw Error('Choose Yes or No.');
    }
    return raw === 'true';
  }
  if (spec.kind === 'enum') {
    const index = Number(raw);
    if (!Number.isInteger(index) || index < 0 || index >= spec.constraints.enum.length) {
      throw Error('Choose a listed value.');
    }
    return spec.constraints.enum[index];
  }
  if (spec.kind === 'number' || spec.kind === 'integer') {
    const number = Number(raw);
    if (!Number.isFinite(number) || (spec.kind === 'integer' && !Number.isInteger(number))) {
      throw Error(spec.kind === 'integer' ? 'Enter a whole number.' : 'Enter a finite number.');
    }
    return number;
  }
  if (spec.kind === 'vector') {
    const values = JSON.parse(raw);
    if (!Array.isArray(values) || values.length !== spec.constraints.length || !values.every(Number.isFinite)) {
      throw Error(`Enter ${spec.constraints.length} numbers in a JSON array, such as [1, 0, 0].`);
    }
    return values;
  }
  return raw;
}

export function constraintText(spec) {
  const constraints = spec.constraints || {};
  const parts = [];
  if (constraints.minimum !== undefined) {
    parts.push(`Minimum ${constraints.minimum}`);
  }
  if (constraints.maximum !== undefined) {
    parts.push(`maximum ${constraints.maximum}`);
  }
  if (constraints.length !== undefined) {
    parts.push(`${constraints.length} components`);
  }
  if (constraints.minLength !== undefined) {
    parts.push(`at least ${constraints.minLength} characters`);
  }
  if (constraints.maxLength !== undefined) {
    parts.push(`at most ${constraints.maxLength} characters`);
  }
  return parts.join(' · ');
}

export function parameterField(id, spec, value) {
  const constraints = spec.constraints || {};
  const props = {class: 'input', name: id, id: `case-param-${id}`, 'data-parameter': id,
    'aria-describedby': `case-help-${id}`};
  let input;
  if (spec.kind === 'boolean' || spec.kind === 'enum') {
    const choices = spec.kind === 'boolean' ? [true, false] : constraints.enum;
    input = h('select', {...props, class: 'select'},
      h('option', {value: '', selected: value === undefined}, 'Choose a value…'),
      choices.map((item, index) => h('option', {
        value: spec.kind === 'boolean' ? String(item) : String(index), selected: item === value,
      }, typeof item === 'boolean' ? (item ? 'Yes' : 'No') : String(item))));
  } else if (spec.kind === 'vector') {
    input = h('input', {...props, type: 'text', placeholder: `[${Array(constraints.length).fill(0).join(', ')}]`,
      value: value === undefined ? '' : JSON.stringify(value)});
  } else {
    const numeric = ['number', 'integer'].includes(spec.kind);
    input = h('input', {...props, type: numeric ? 'number' : 'text',
      min: numeric ? constraints.minimum : undefined, max: numeric ? constraints.maximum : undefined,
      step: numeric ? (spec.kind === 'integer' ? '1' : 'any') : undefined,
      value: value === undefined ? '' : String(value)});
  }
  const required = spec.default === undefined;
  return h('div', {class: 'field runner-parameter'},
    h('label', {for: props.id}, spec.label,
      spec.units ? h('span', {class: 'runner-units'}, spec.units) : null,
      required ? h('span', {class: 'runner-required'}, 'Required') : null), input,
    h('div', {class: 'hint', id: `case-help-${id}`}, spec.help || '',
      constraintText(spec) ? h('div', {}, constraintText(spec)) : null,
      required ? null : h('div', {}, `Default: ${JSON.stringify(spec.default)}`)));
}

export function collectValues(form, template, identity) {
  const values = {};
  for (const [id, spec] of Object.entries(template.parameters)) {
    const raw = form.elements.namedItem(id).value;
    try {
      const value = parseParameter(spec, raw);
      if (value !== undefined) {
        values[id] = value;
      }
    } catch (error) {
      throw new ApiError({code: 'INVALID_PARAMETER', message: `${spec.label}: ${error.message}`,
        location: `$.case.values.${id}`});
    }
  }
  return {version: 'schemaxis.workflow-values/1', template: identity, values};
}
