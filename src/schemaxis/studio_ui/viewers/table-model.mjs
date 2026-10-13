// Table model: CSV/TSV parsing (RFC 4180), delimiter sniffing, header
// detection, typed tables, column statistics, stable sorting and TSV export.
// A table is {columns: [{name, type}], rows: [[value, ...], ...]} where values
// are numbers, booleans, strings or null (see data-types.mjs).

import {convert, detectType, isEmpty, isNumberText, isNumericType} from './data-types.mjs';

const CANDIDATES = [',', '\t', ';', '|'];

/**
 * Parse delimited text. Quoted fields may contain delimiters, doubled quotes
 * and newlines; records end at CRLF, LF or CR; a final newline adds no record;
 * a leading BOM is ignored. Returns an array of string arrays.
 */
export function parseDelimited(text, delimiter = ',', limit = Infinity) {
  const rows = [];
  let row = [];
  let field = '';
  let i = text.charCodeAt(0) === 0xfeff ? 1 : 0;
  const length = text.length;
  const separator = delimiter.charCodeAt(0);
  let quoted = false;
  let fieldStart = true;
  while (i < length && rows.length < limit) {
    const code = text.charCodeAt(i);
    if (quoted) {
      if (code === 34) {
        if (text.charCodeAt(i + 1) === 34) {
          field += '"';
          i += 2;
          continue;
        }
        quoted = false;
        i++;
        continue;
      }
      const next = text.indexOf('"', i);
      const end = next < 0 ? length : next;
      field += text.slice(i, end);
      i = end;
      continue;
    }
    if (code === 34 && fieldStart) {
      quoted = true;
      fieldStart = false;
      i++;
    } else if (code === separator) {
      row.push(field);
      field = '';
      fieldStart = true;
      i++;
    } else if (code === 10 || code === 13) {
      // A blank line (no fields, nothing quoted) is not a record.
      if (row.length || !fieldStart) {
        row.push(field);
        rows.push(row);
      }
      row = [];
      field = '';
      fieldStart = true;
      i += code === 13 && text.charCodeAt(i + 1) === 10 ? 2 : 1;
    } else if (code === 34) {
      // A quote inside an unquoted field is kept literally (lenient RFC 4180).
      field += '"';
      i++;
    } else {
      // Fast path: copy a run of ordinary characters.
      let end = i + 1;
      while (end < length) {
        const c = text.charCodeAt(end);
        if (c === separator || c === 10 || c === 13 || c === 34) {
          break;
        }
        end++;
      }
      field += text.slice(i, end);
      fieldStart = false;
      i = end;
    }
  }
  if ((!fieldStart || row.length) && rows.length < limit) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

/** Guess the delimiter from the first records: the candidate with the most consistent field count > 1. */
export function sniffDelimiter(text) {
  const sample = text.slice(0, 65536);
  let best = {delimiter: ',', score: 0};
  for (const delimiter of CANDIDATES) {
    const records = parseDelimited(sample, delimiter, 40);
    if (records.length > 1 && sample.length === 65536) {
      records.pop();
    }
    const counts = new Map();
    for (const record of records) {
      counts.set(record.length, (counts.get(record.length) || 0) + 1);
    }
    let mode = 0;
    let frequency = 0;
    for (const [count, seen] of counts) {
      if (seen > frequency || (seen === frequency && count > mode)) {
        mode = count;
        frequency = seen;
      }
    }
    const score = mode > 1 ? (frequency / Math.max(1, records.length)) * 1000 + mode : 0;
    if (score > best.score) {
      best = {delimiter, score};
    }
  }
  return best.delimiter;
}

/**
 * Header heuristic (after Python's csv.Sniffer): a first row is a header when
 * its cells are non-empty, unique and, column by column, differ in type
 * (non-numeric over numbers) or in length (over fixed-length text) from the rest.
 */
export function detectHeader(rows) {
  if (rows.length < 2) {
    return false;
  }
  const first = rows[0];
  if (first.some(isEmpty) || new Set(first).size !== first.length) {
    return false;
  }
  const sample = rows.slice(1, 201);
  let votes = 0;
  first.forEach((cell, column) => {
    const values = sample.map((row) => row[column]).filter((value) => !isEmpty(value));
    if (!values.length) {
      return;
    }
    const type = detectType(values);
    if (isNumericType(type) || type === 'boolean') {
      votes += detectType([cell]) === type || (isNumericType(type) && isNumberText(cell)) ? -1 : 1;
      return;
    }
    const lengths = new Set(values.map((value) => value.length));
    if (lengths.size === 1) {
      votes += lengths.has(cell.length) ? -1 : 1;
    }
  });
  return votes > 0;
}

/** Spreadsheet-style default column names: A, B, …, Z, AA, … */
function defaultName(index) {
  let name = '';
  let value = index + 1;
  while (value > 0) {
    name = String.fromCharCode(65 + ((value - 1) % 26)) + name;
    value = Math.floor((value - 1) / 26);
  }
  return name;
}

function uniqueNames(names) {
  const seen = new Map();
  return names.map((raw, index) => {
    const base = isEmpty(raw) ? defaultName(index) : String(raw).trim();
    const count = (seen.get(base) || 0) + 1;
    seen.set(base, count);
    return count === 1 ? base : `${base}_${count}`;
  });
}

/** Type string rows column by column (ragged rows are padded with empty cells). */
function typed(names, records) {
  const width = names.length;
  const columns = names.map((name, index) => {
    function* cells() {
      for (const record of records) {
        yield record[index];
      }
    }
    return {name, type: detectType(cells())};
  });
  const rows = records.map((record) => {
    const row = new Array(width);
    for (let c = 0; c < width; c++) {
      row[c] = convert(record[c], columns[c].type);
    }
    return row;
  });
  return {columns, rows};
}

/**
 * CSV/TSV text → table. options: {delimiter: auto, header: 'auto'|true|false}.
 * Returns {columns, rows, header: boolean, delimiter}.
 */
export function tableFromDelimited(text, options = {}) {
  const delimiter = options.delimiter || sniffDelimiter(text);
  const records = parseDelimited(text, delimiter);
  const header = options.header === undefined || options.header === 'auto'
    ? detectHeader(records) : Boolean(options.header);
  const width = records.reduce((max, record) => Math.max(max, record.length), 0);
  const headerRow = header ? records[0] : [];
  const names = uniqueNames(Array.from({length: width}, (_, i) => headerRow[i]));
  return {...typed(names, header ? records.slice(1) : records), header, delimiter};
}

/**
 * {columns, rows} → table. Columns may be names or {name, type}; when a type is
 * missing it is detected from the values (strings are converted).
 */
export function tableFromData(data) {
  if (!data || !Array.isArray(data.columns) || !Array.isArray(data.rows)) {
    throw Error('Table data needs columns and rows arrays.');
  }
  const names = uniqueNames(data.columns.map((column) => (typeof column === 'string' ? column : column?.name)));
  const declared = data.columns.map((column) => (typeof column === 'object' ? column?.type : undefined));
  if (declared.every(Boolean)) {
    const width = names.length;
    const rows = data.rows.map((row) => Array.from({length: width}, (_, c) => (row[c] === undefined ? null : row[c])));
    return {columns: names.map((name, i) => ({name, type: declared[i]})), rows};
  }
  const strings = data.rows.map((row) => names.map((_, c) => (row[c] === null || row[c] === undefined
    ? '' : String(row[c]))));
  return typed(names, strings);
}

/** Statistics for one column. Numeric: count, missing, min, max, mean, std (sample, n − 1). */
export function columnStats(table, column) {
  const type = table.columns[column].type;
  let count = 0;
  let missing = 0;
  if (isNumericType(type)) {
    let mean = 0;
    let m2 = 0;
    let min = Infinity;
    let max = -Infinity;
    let nonFinite = 0;
    for (const row of table.rows) {
      const value = row[column];
      if (value === null) {
        missing++;
      } else if (!Number.isFinite(value)) {
        nonFinite++;
      } else {
        count++;
        const delta = value - mean;
        mean += delta / count;
        m2 += delta * (value - mean);
        min = Math.min(min, value);
        max = Math.max(max, value);
      }
    }
    return {type, count, missing, nonFinite, min: count ? min : null, max: count ? max : null,
      mean: count ? mean : null, std: count > 1 ? Math.sqrt(m2 / (count - 1)) : null};
  }
  const distinct = new Map();
  for (const row of table.rows) {
    const value = row[column];
    if (value === null) {
      missing++;
    } else {
      count++;
      distinct.set(value, (distinct.get(value) || 0) + 1);
    }
  }
  let top = null;
  for (const [value, seen] of distinct) {
    if (!top || seen > top.count) {
      top = {value, count: seen};
    }
  }
  return {type, count, missing, unique: distinct.size, top};
}

function compareValues(a, b) {
  if (typeof a === 'number' && typeof b === 'number') {
    if (Number.isNaN(a) || Number.isNaN(b)) {
      return Number.isNaN(a) - Number.isNaN(b);
    }
    return a - b;
  }
  if (typeof a === 'boolean' && typeof b === 'boolean') {
    return Number(a) - Number(b);
  }
  return String(a).localeCompare(String(b), undefined, {numeric: true, sensitivity: 'base'});
}

/** Stable sort order (row indices). Empty cells sort last in both directions. */
export function sortOrder(table, column, direction = 'asc') {
  const order = Array.from({length: table.rows.length}, (_, i) => i);
  const sign = direction === 'desc' ? -1 : 1;
  order.sort((i, j) => {
    const a = table.rows[i][column];
    const b = table.rows[j][column];
    if (a === null || b === null) {
      return (a === null) - (b === null) || i - j;
    }
    return sign * compareValues(a, b) || i - j;
  });
  return Uint32Array.from(order);
}

/** Case-insensitive literal row filter, preserving source indices and the supplied order. */
export function filterOrder(table, order, query) {
  const needle = String(query).toLocaleLowerCase();
  if (!needle) {
    return order;
  }
  const matches = [];
  for (let viewRow = 0; viewRow < (order?.length ?? table.rows.length); viewRow++) {
    const sourceRow = order ? order[viewRow] : viewRow;
    if (table.rows[sourceRow].some((value) => formatValue(value).toLocaleLowerCase().includes(needle))) {
      matches.push(sourceRow);
    }
  }
  return Uint32Array.from(matches);
}

/** Text shown for a cell value. */
export function formatValue(value) {
  if (value === null || value === undefined) {
    return '';
  }
  return String(value);
}

function tsvField(value) {
  const text = formatValue(value);
  return /[\t\n\r"]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** TSV for view rows [r0, r1] × columns [c0, c1] (inclusive), optionally with a header line. */
export function selectionTsv(table, order, rows, columns, includeHeader = false) {
  const lines = [];
  const [c0, c1] = columns;
  if (includeHeader) {
    lines.push(table.columns.slice(c0, c1 + 1).map((column) => tsvField(column.name)).join('\t'));
  }
  for (let r = rows[0]; r <= rows[1]; r++) {
    const row = table.rows[order ? order[r] : r];
    const cells = [];
    for (let c = c0; c <= c1; c++) {
      cells.push(tsvField(row[c]));
    }
    lines.push(cells.join('\t'));
  }
  return lines.join('\n');
}
