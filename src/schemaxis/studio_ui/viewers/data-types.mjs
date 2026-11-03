// Copyright (C) 2026 David L F Gaden
// Column type detection shared by grep extraction and the table viewer.
// Types: 'integer', 'number', 'boolean', 'text', 'empty'.
// Cells are strings on input; converted values are numbers, booleans,
// strings, or null for empty cells.

const NUMBER = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;
const INTEGER = /^[+-]?\d+$/;
const SPECIAL = /^[+-]?(?:nan|inf|infinity)$/i;
const BOOLEAN = /^(?:true|false)$/i;

/** True for empty or whitespace-only cells (and null/undefined). */
export function isEmpty(value) {
  return value === null || value === undefined || (typeof value === 'string' && value.trim() === '');
}

/** Parse numeric text ('1e-05', '-3', '.5', 'nan', 'inf'); returns NaN when not numeric text. */
export function parseNumber(text) {
  const value = String(text).trim();
  if (NUMBER.test(value)) {
    return Number(value);
  }
  if (SPECIAL.test(value)) {
    const lower = value.toLowerCase();
    if (lower.endsWith('nan')) {
      return NaN;
    }
    return lower.startsWith('-') ? -Infinity : Infinity;
  }
  return NaN;
}

export function isNumberText(text) {
  const value = String(text).trim();
  return NUMBER.test(value) || SPECIAL.test(value);
}

/** Detect the type of a column from its string cells (empty cells are ignored). */
export function detectType(values) {
  let seen = 0;
  let integer = true;
  let number = true;
  let boolean = true;
  for (const raw of values) {
    if (isEmpty(raw)) {
      continue;
    }
    seen++;
    const text = String(raw).trim();
    if (number && !isNumberText(text)) {
      number = false;
      integer = false;
    } else if (integer && !(INTEGER.test(text) && Number.isSafeInteger(Number(text)))) {
      integer = false;
    }
    if (boolean && !BOOLEAN.test(text)) {
      boolean = false;
    }
    if (!number && !boolean) {
      return 'text';
    }
  }
  if (!seen) {
    return 'empty';
  }
  if (integer) {
    return 'integer';
  }
  if (number) {
    return 'number';
  }
  return boolean ? 'boolean' : 'text';
}

/** Convert one string cell to the value for a column type. */
export function convert(raw, type) {
  if (isEmpty(raw)) {
    return null;
  }
  switch (type) {
    case 'integer':
    case 'number':
      return parseNumber(raw);
    case 'boolean':
      return String(raw).trim().toLowerCase() === 'true';
    default:
      return String(raw);
  }
}

export const isNumericType = (type) => type === 'integer' || type === 'number';

/**
 * Type and convert a table of string rows (the input is not modified).
 * names: column names; rows: arrays of strings. Returns {columns: [{name, type}], rows}.
 */
export function typeTable(names, rows) {
  function* cells(index) {
    for (const row of rows) {
      yield row[index];
    }
  }
  const columns = names.map((name, index) => ({name, type: detectType(cells(index))}));
  const typed = rows.map((row) => columns.map((column, index) => convert(row[index], column.type)));
  return {columns, rows: typed};
}
