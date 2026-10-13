// Output naming preview: a local mirror of src/schemaxis/output_naming.py.
// The server stays authoritative; this only renders a live preview while typing.

export const DEFAULT_PATTERN = '{index}-{operation}-{output}{ext}';
export const DEFAULT_WIDTH = 6;
export const TOKENS = ['{index}', '{operation}', '{output}', '{param:ID}', '{axis:NAME}', '{artifact}', '{ext}'];

const TOKEN = /\{([^{}]*)\}/g;
const SIMPLE = ['index', 'operation', 'output', 'artifact', 'ext'];
const PARAMETER = /^param:[A-Za-z][A-Za-z0-9_.-]*$/;
const AXIS = /^axis:[A-Za-z0-9_.-]+$/;
const LITERAL = /^[A-Za-z0-9_.+=,@-]*$/;
const MAX_PATTERN = 256;
const MAX_NAME = 255;
const MANIFEST = 'naming.json';

export class NamingError extends Error {}

export function validateWidth(width) {
  if (!Number.isInteger(width) || typeof width !== 'number' || width < 1 || width > 12) {
    throw new NamingError('index width must be an integer from 1 to 12');
  }
  return width;
}

/** Tokens of a safe single-component file name pattern; throws NamingError. */
export function validatePattern(pattern) {
  if (typeof pattern !== 'string' || !pattern || pattern.length > MAX_PATTERN) {
    throw new NamingError('pattern must be a nonempty string of at most 256 characters');
  }
  const tokens = [];
  let position = 0;
  for (const match of pattern.matchAll(TOKEN)) {
    const literal = pattern.slice(position, match.index);
    if (!LITERAL.test(literal)) {
      throw new NamingError(`literal text may contain letters, digits and _ . + = , @ - only: "${literal}"`);
    }
    const token = match[1];
    if (!SIMPLE.includes(token) && !PARAMETER.test(token) && !AXIS.test(token)) {
      throw new NamingError(`unknown token {${token}}; use {index}, {operation}, {output}, {param:ID}, `
        + '{axis:NAME}, {artifact} or {ext}');
    }
    tokens.push(token);
    position = match.index + match[0].length;
  }
  const tail = pattern.slice(position);
  if (!LITERAL.test(tail)) {
    throw new NamingError(`literal text may contain letters, digits and _ . + = , @ - only: "${tail}"`);
  }
  if (!tokens.length) {
    throw new NamingError('pattern needs at least one token, such as {index}');
  }
  if (pattern.startsWith('.')) {
    throw new NamingError('names must not start with a dot');
  }
  return tokens;
}

function stripZeros(text) {
  return text.includes('.') ? text.replace(/0+$/, '').replace(/\.$/, '') : text;
}

/** Python's '{:.12g}'.format(value). Integer-valued numbers print as integers. */
export function formatNumber(value) {
  if (!Number.isFinite(value)) {
    throw new NamingError('cannot name a nonfinite number');
  }
  if (Object.is(value, -0)) {
    return '-0';
  }
  if (Number.isInteger(value) && Math.abs(value) < 1e15) {
    return String(value);
  }
  const [mantissa, exponentText] = value.toExponential(11).split('e');
  const exponent = Number(exponentText);
  if (exponent >= -4 && exponent < 12) {
    return stripZeros(value.toFixed(11 - exponent));
  }
  const sign = exponent < 0 ? '-' : '+';
  return `${stripZeros(mantissa)}e${sign}${String(Math.abs(exponent)).padStart(2, '0')}`;
}

function numberFragment(value) {
  return formatNumber(value).replaceAll('+', '').replaceAll('-', 'm').replaceAll('.', 'p');
}

function scalar(value) {
  return typeof value === 'boolean' || typeof value === 'number' || typeof value === 'string';
}

/** Render one token value as a portable file name fragment (mirrors output_naming.sanitise). */
export function sanitise(value) {
  if (typeof value === 'boolean') {
    return value ? 'yes' : 'no';
  }
  if (typeof value === 'number') {
    return numberFragment(value);
  }
  if (value === null || value === undefined) {
    return 'none';
  }
  if (typeof value === 'string') {
    const text = value.replaceAll('.', 'p').replace(/[^A-Za-z0-9_-]/gu, '_');
    return text || '_';
  }
  if (Array.isArray(value) && value.length && value.every(scalar)) {
    return value.map(sanitise).join('_');
  }
  throw new NamingError('only scalars and flat lists can appear in a name');
}

function byteLength(text) {
  return new TextEncoder().encode(text).length;
}

/** One name for an entry {operation, output, artifact, ext, stem, parameters, axes}. */
export function render(pattern, entry, index, width) {
  const name = pattern.replace(TOKEN, (_, key) => {
    if (key === 'index') {
      return String(index).padStart(width, '0');
    }
    if (key === 'ext') {
      return entry.ext || '';
    }
    if (key === 'artifact') {
      return String(entry.artifact ?? 0);
    }
    if (key === 'operation' || key === 'output') {
      return sanitise(entry[key] || entry.stem || 'output');
    }
    const separator = key.indexOf(':');
    const group = key.slice(0, separator);
    const identity = key.slice(separator + 1);
    const values = (group === 'param' ? entry.parameters : entry.axes) || {};
    if (!Object.hasOwn(values, identity)) {
      throw new NamingError(`${group === 'param' ? 'parameter' : 'axis'} ${identity} has no value for this output`);
    }
    return sanitise(values[identity]);
  });
  if (byteLength(name) > MAX_NAME || name === '.' || name === '..' || name === MANIFEST) {
    throw new NamingError('pattern produced an unusable file name');
  }
  return name;
}

/**
 * Preview names; never throws. Returns {names, collisions, error}.
 * The index is the 1-based position in entries, as in output_naming.preview.
 */
export function preview(pattern, entries, width = DEFAULT_WIDTH) {
  try {
    validatePattern(pattern);
    validateWidth(width);
    const names = [];
    const seen = new Set();
    const collisions = new Set();
    entries.forEach((entry, position) => {
      const name = render(pattern, {artifact: 0, ...entry}, position + 1, width);
      if (seen.has(name)) {
        collisions.add(name);
      }
      seen.add(name);
      names.push(name);
    });
    return {names, collisions: [...collisions].sort(), error: null};
  } catch (error) {
    if (error instanceof NamingError) {
      return {names: [], collisions: [], error: error.message};
    }
    throw error;
  }
}

const EXTENSIONS = {table: '.csv', series: '.csv', image: '.png', video: '.mp4', geometry: '.vtu', text: '.txt',
  number: '.json', vector: '.json', audio: '.wav', archive: '.zip'};

/** A plausible file extension for preview purposes only. */
export function extensionFor(kind) {
  return EXTENSIONS[kind] || '.dat';
}

/**
 * Sample entries from a design: named outputs first, otherwise every declared output port.
 * parameterValues maps parameter IDs to sample values; axes maps axis names to a sample value.
 */
export function sampleEntries(projection, parameterValues = {}, axes = {}) {
  const entries = [];
  const aliases = Object.entries(projection.outputs || {});
  if (aliases.length) {
    for (const [alias, output] of aliases) {
      entries.push({operation: output.operation, output: alias, artifact: output.artifact,
        ext: extensionFor(output.kind), parameters: parameterValues, axes});
    }
    return entries;
  }
  for (const node of projection.nodes || []) {
    for (const port of (node.ports && node.ports.outputs) || []) {
      entries.push({operation: node.id, output: port.name, artifact: port.artifact,
        ext: extensionFor(port.data && port.data.kind), parameters: parameterValues, axes});
    }
  }
  return entries;
}
