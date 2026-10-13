// Durable field markers, choices and literal validation shared by the fill UI.
import {escapeSegment, parsePointer, rangeOfPointer} from './json-pointer.mjs';
import {documentValue} from './json-parse.mjs';

export const isFill = (value) => Boolean(value && typeof value === 'object' && typeof value.$fill === 'string');

export function findFills(ast, fields = {}) {
  const result = [];
  function visit(value, pointer) {
    if (isFill(value)) {
      const field = {...fields[value.$fill], ...value};
      const range = rangeOfPointer(ast, pointer);
      if (range) result.push({pointer, ...range, field});
      return;
    }
    if (value && typeof value === 'object') {
      for (const [key, child] of Object.entries(value)) visit(child, `${pointer}/${escapeSegment(key)}`);
    }
  }
  visit(documentValue(ast), '');
  return result.sort((a, b) => Number(b.field.required !== false) - Number(a.field.required !== false)
    || a.from - b.from);
}

export function atPointer(value, pointer) {
  for (const segment of parsePointer(pointer || '')) value = value?.[segment];
  return value;
}

export function replacing(value, pointer, replacement) {
  const segments = parsePointer(pointer);
  function copy(node, index) {
    if (index === segments.length) return replacement;
    const result = Array.isArray(node) ? node.slice() : {...node};
    Object.defineProperty(result, segments[index], {value: copy(node?.[segments[index]], index + 1),
      enumerable: true, configurable: true, writable: true});
    return result;
  }
  return copy(value, 0);
}

export function parseField(text, field) {
  if (['string', 'id', 'path', 'nodeRef', 'axisRef', 'field'].includes(field.type)) return text;
  return JSON.parse(text);
}

export function checkField(value, field) {
  const type = field.type || 'json';
  if (type === 'integer' && !Number.isInteger(value)) return 'Enter an integer.';
  if (type === 'number' && (typeof value !== 'number' || !Number.isFinite(value))) return 'Enter a finite number.';
  if (type === 'boolean' && typeof value !== 'boolean') return 'Choose true or false.';
  if (['string', 'id', 'path', 'nodeRef', 'axisRef', 'field'].includes(type) && typeof value !== 'string') {
    return 'Enter text.';
  }
  if (['id', 'nodeRef', 'axisRef', 'path'].includes(type) && !value) return 'Enter a value.';
  if (type === 'id' && !/^[A-Za-z][A-Za-z0-9_-]*$/.test(value)) {
    return 'Use a letter, then letters, numbers, _ or -.';
  }
  const length = {vector3: 3, colour: 3, bounds: 6}[type];
  if (length && (!Array.isArray(value) || value.length !== length || value.some((v) => !Number.isFinite(v)))) {
    return `Enter ${length} numbers as a JSON array.`;
  }
  if (type === 'colour' && value.some((v) => v < 0 || v > 1)) return 'Colour components must be between 0 and 1.';
  if (type === 'bounds' && [0, 2, 4].some((i) => value[i] > value[i + 1])) {
    return 'Each minimum must precede its maximum.';
  }
  if (field.values && !field.values.some((v) => JSON.stringify(v) === JSON.stringify(value))) {
    return 'Choose a listed value.';
  }
  if (typeof value === 'string') {
    if (field.minLength !== undefined && value.length < field.minLength) {
      return `Use at least ${field.minLength} characters.`;
    }
    if (field.maxLength !== undefined && value.length > field.maxLength) {
      return `Use at most ${field.maxLength} characters.`;
    }
    if (field.pattern && !new RegExp(field.pattern).test(value)) {
      return 'This text does not match the required pattern.';
    }
  }
  if (typeof value === 'number') {
    if (field.minimum !== undefined && value < field.minimum) return `Enter at least ${field.minimum}.`;
    if (field.maximum !== undefined && value > field.maximum) return `Enter at most ${field.maximum}.`;
  }
  if (type === 'path' && field.extensions?.length) {
    const suffixes = field.extensions.map((extension) => extension.replace(/^\*?\.?/, '').toLowerCase());
    if (!suffixes.some((extension) => value.toLowerCase().endsWith(`.${extension}`))) {
      return `Use a file ending in ${field.extensions.join(', ')}.`;
    }
  }
  return '';
}

export function fieldChoices(field, document, options = {}) {
  const isIdentity = (value) => typeof value === 'string' && value.length > 0;
  let choices = field.values || (field.type === 'boolean' ? [true, false] : []);
  if (field.type === 'nodeRef') {
    choices = (Array.isArray(document?.nodes) ? document.nodes : []).filter((node) => isIdentity(node?.id))
      .filter((node) => {
      const kinds = options.nodeKinds?.[node.id] || node.outputKinds || (node.kind ? [node.kind] : []);
      return !field.acceptsKinds?.length || !kinds.length || kinds.some((kind) => field.acceptsKinds.includes(kind));
    }).map((node) => node.id);
  } else if (field.type === 'axisRef') {
    choices = (Array.isArray(document?.axes) ? document.axes : []).map((axis) => axis?.name).filter(isIdentity);
  } else if (field.type === 'field') {
    choices = (options.observations || []).map((field) => typeof field === 'string' ? field : field?.name)
      .filter(isIdentity);
  }
  const values = [...choices, ...(options.recent || [])];
  const filtered = ['nodeRef', 'axisRef', 'field'].includes(field.type) ? values.filter(isIdentity) : values;
  return [...new Map(filtered.map((value) => [JSON.stringify(value), value])).values()];
}

export function documentPointers(value) {
  const pointers = [];
  function visit(node, pointer) {
    if (isFill(node)) return;
    if (pointer) pointers.push(pointer);
    if (node && typeof node === 'object') {
      for (const [key, child] of Object.entries(node)) visit(child, `${pointer}/${escapeSegment(key)}`);
    }
  }
  visit(value, '');
  return pointers;
}

export function substituteField(field, value) {
  const name = field.templateField || field.$fill;
  return field.template && typeof value === 'string' ? field.template.replaceAll(`\${${name}}`, value) : value;
}

/** A repeated prefix is tested against every derived id in its own containing collection. */
export function uniqueFieldValue(document, markers, value) {
  if (typeof value !== 'string') return value;
  const groups = markers.map((marker) => {
    const segments = parsePointer(marker.pointer);
    let collection = document;
    let occupied = [];
    for (const segment of segments) {
      if (Array.isArray(collection)) {
        occupied = collection.flatMap((entry) => [entry?.id, entry?.name]).filter((id) => typeof id === 'string');
      }
      collection = collection?.[segment];
    }
    return {marker, occupied: new Set(occupied)};
  });
  let result = value;
  let suffix = 2;
  while (groups.some(({marker, occupied}) => occupied.has(substituteField(marker.field, result)))) {
    result = `${value}_${suffix++}`;
  }
  return result;
}
