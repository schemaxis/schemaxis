// Copyright (C) 2026 David L. F. Gaden.
// Encode literals or opaque expression text. Only the host checks expressions.
import {h} from '../lib/dom.mjs';

export const numericChoices = spec => {
  const values = spec?.enum || spec?.values || spec?.constraints?.enum;
  return Array.isArray(values) && values.length > 0 && values.every(Number.isFinite) ? values : null;
};
export function spatialFieldType(spec) {
  const type = spec?.type || spec?.kind;
  if (['number', 'integer', 'vector', 'vector3', 'bounds', 'box', 'colour'].includes(type)) return type;
  if (numericChoices(spec)) return 'number';
  if (type === 'object' && spec.properties?.min && spec.properties?.max) return 'box';
  if (type === 'array' && ['number', 'integer'].includes(spec.items?.type)) {
    if (spec.minItems === 3 && spec.maxItems === 3) return 'vector3';
    if (spec.minItems === 6 && spec.maxItems === 6) return 'bounds';
  }
  return null;
}
export const spatialField = spec => spatialFieldType(spec) !== null;
export const expressionValue = value => Boolean(value && !Array.isArray(value) && typeof value === 'object'
  && Object.keys(value).some(key => key.startsWith('$') && key !== '$fill'));
export function readSpatialInput(text) {
  if (!text.trim()) throw Error('Enter a number, name or expression.');
  // Decimal entry syntax is broader than JSON; this recognises a whole literal,
  // never operators, names or other expression-language constructs.
  if (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text.trim())) {
    const value = Number(text);
    if (!Number.isFinite(value)) throw Error('Enter a finite number.');
    return value;
  }
  try {
    const value = JSON.parse(text);
    const finite = item => {
      if (typeof item === 'number' && !Number.isFinite(item)) throw Error('Enter a finite number.');
      if (item && typeof item === 'object') Object.values(item).forEach(finite);
    };
    finite(value);
    return value;
  } catch (fault) {
    if (!(fault instanceof SyntaxError)) throw fault;
    return {$expr: text};
  }
}
export function spatialInputText(value) {
  if (value === undefined) return '';
  if (typeof value?.$expr === 'string' && Object.keys(value).length === 1) {
    // Keep an explicit marker when bare text would read back as a literal, even
    // for consumers that read the element's text without retaining the control.
    try {
      if (readSpatialInput(value.$expr)?.$expr === value.$expr) return value.$expr;
    } catch { if (!value.$expr.trim()) return value.$expr; }
  }
  return JSON.stringify(value);
}

/** All numeric entry points share this control and encoding, including coordinates. */
export function spatialInput({label, value, onChange = () => {}, ...props}) {
  const element = h('input', {class: 'input', type: 'text', 'aria-label': label,
    placeholder: 'Number, name or expression', ...props, value: spatialInputText(value),
    onInput: event => { element.removeAttribute('aria-invalid'); onChange(event); }});
  return {element, read: () => readSpatialInput(element.value)};
}

/** Host fault positions count Unicode code points; DOM selections count UTF-16. */
export function expressionFaultRange(text, fault) {
  const observed = fault?.observed;
  if (typeof observed?.expression !== 'string' || !Number.isInteger(observed.position) || !Number.isInteger(observed.length)) return null;
  const points = Array.from(observed.expression), start = Math.max(0, observed.position);
  const before = points.slice(0, start).join(''), through = points.slice(0, start + Math.max(0, observed.length)).join('');
  if (observed.expression === text) return [before.length, through.length];
  // A structured numeric field can contain a quoted $expr. Locate its exact
  // JSON string once; escaped characters count towards the displayed selection.
  try { JSON.parse(text); } catch { return null; }
  const quoted = JSON.stringify(observed.expression), at = text.indexOf(quoted);
  if (at < 0 || text.indexOf(quoted, at + quoted.length) >= 0) return null;
  return [at + JSON.stringify(before).length - 1, at + JSON.stringify(through).length - 1];
}

export function reportSpatialCheck(input, response) {
  input.setAttribute('aria-invalid', String(!response.ok));
  const range = expressionFaultRange(input.value, response.fault);
  if (range) { input.focus(); input.setSelectionRange(...range); }
}

/** Select an unambiguous host span in a form, without parsing the expression. */
export function reportSpatialFault(container, fault) {
  const inputs = [...container.querySelectorAll('input, textarea')].filter(input =>
    !input.disabled && !input.closest('[hidden]') && expressionFaultRange(input.value, fault));
  if (inputs.length !== 1) return false;
  reportSpatialCheck(inputs[0], {ok: false, fault});
  return true;
}
