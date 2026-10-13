// Table Viewer: virtualised read-only table (optional editing), CSV/TSV or
// {columns, rows} input, type detection, sorting, column statistics, cell and
// range selection, TSV copy and a small line plot.
//
//   const viewer = createTableViewer(container, {editable: false});
//   viewer.load(csvText | {csv | text | blob, delimiter?, header?, name?} | {columns, rows, name?} | Promise);
//
// Pick payload (rows are 0-based view positions, inclusive; equal to data rows when unsorted):
//   {type: 'cell'|'range', rows: [a, b], columns: [a, b], header: [names], sort: null|{column, name, direction},
//    sourceRows?: [data row per view row, when sorted or filtered], filter: string|null,
//    value? (cell), name?, revision?}
// Events: pick (mouse release / Enter), selectionchange, edit, sort, filter, load, error.

import {h} from '../lib/dom.mjs';
import {createEmitter, createFrame, formatNumber, separator, setPressed, spacer, toolButton} from './common.mjs';
import {columnName} from './chip.mjs';
import {convert, isEmpty, isNumberText, isNumericType} from './data-types.mjs';
import {columnStats, filterOrder, selectionTsv, sortOrder, tableFromData, tableFromDelimited} from './table-model.mjs';
import {createGrid} from './table-grid.mjs';
import {createPlot} from './table-plot.mjs';

export function createTableViewer(container, options = {}) {
  const events = createEmitter();
  const frame = createFrame(container, {kind: 'table', label: options.label || 'Table Viewer',
    emptyMessage: options.emptyMessage || 'No table loaded'});
  const statusLeft = h('span', {class: 'vw-status-main vw-mono'}, '');
  const statusRight = h('span', {class: 'vw-status-meta'});
  frame.status.append(statusLeft, statusRight);

  let table = null;
  let meta = {};
  let order = null;
  let sort = null;
  let query = '';
  let loadToken = 0;

  const gridArea = h('div', {class: 'vw-table-gridarea'});
  const statsPanel = h('aside', {class: 'vw-table-stats', 'aria-label': 'Column statistics', hidden: true});
  const plot = createPlot();
  const plotX = h('select', {class: 'vw-select', 'aria-label': 'X column'});
  const plotY = h('select', {class: 'vw-select', 'aria-label': 'Y column'});
  const plotLog = h('input', {type: 'checkbox'});
  const plotPanel = h('section', {class: 'vw-table-plot', 'aria-label': 'Plot', hidden: true},
    h('div', {class: 'vw-plot-controls'}, h('label', {class: 'vw-field'}, 'X', plotX),
      h('label', {class: 'vw-field'}, 'Y', plotY), h('label', {class: 'vw-check'}, plotLog, 'Log Y')),
    plot.element);
  frame.body.append(h('div', {class: 'vw-table-main'}, gridArea, statsPanel), plotPanel);

  const grid = createGrid(gridArea, {
    onSelect: (selection, final) => {
      updateStatus(selection);
      renderStats();
      const payload = pickPayload(selection);
      events.emit('selectionchange', payload);
      if (final) {
        events.emit('pick', payload);
      }
    },
    onSort: (column) => {
      const direction = sort?.column !== column ? 'asc' : sort.direction === 'asc' ? 'desc' : null;
      sortBy(column, direction);
    },
    onEdit: (viewRow, column, text) => editCell(viewRow, column, text),
    onCopy: (withHeader) => selectionText(withHeader),
  });
  grid.setEditable(options.editable);

  const statsToggle = toolButton({icon: 'stats', text: 'Stats', title: 'Column statistics', pressed: false,
    onClick: () => showStats(statsPanel.hidden)});
  const plotToggle = toolButton({icon: 'plot', text: 'Plot', title: 'Plot one column against another',
    pressed: false, onClick: () => showPlot(plotPanel.hidden)});
  const copyButton = toolButton({icon: 'copy', text: 'Copy', title: 'Copy selection as TSV (Ctrl+C; '
    + 'Shift-click includes the header)', onClick: (event) => copySelection(event.shiftKey)});
  const editBadge = h('span', {class: 'vw-badge', hidden: !options.editable, title: 'Double-click or F2 edits a cell'},
    'Editable');
  const filterInput = h('input', {type: 'search', class: 'vw-input vw-table-filter',
    'aria-label': 'Filter rows', placeholder: 'Filter rows…', title: 'Literal text, any column; ignores case',
    onInput: () => filterRows(filterInput.value)});
  frame.toolbar.append(statsToggle, plotToggle, separator(), copyButton, spacer(), filterInput, editBadge);

  for (const control of [plotX, plotY, plotLog]) {
    control.addEventListener('change', () => renderPlot());
  }
  const plotObserver = new ResizeObserver(() => !plotPanel.hidden && renderPlot());
  plotObserver.observe(plot.element);

  // ---- selection, picks and copy ---------------------------------------------

  const span = (a, b) => [Math.min(a, b), Math.max(a, b)];

  function pickPayload(selection) {
    if (!selection || !table) {
      return null;
    }
    const rows = span(selection.anchor.r, selection.focus.r);
    const columns = span(selection.anchor.c, selection.focus.c);
    const single = rows[0] === rows[1] && columns[0] === columns[1];
    const payload = {type: single ? 'cell' : 'range', rows, columns,
      header: table.columns.slice(columns[0], columns[1] + 1).map((column) => column.name),
      sort: sort ? {column: sort.column, name: table.columns[sort.column].name, direction: sort.direction} : null,
      filter: query || null};
    if (order) {
      payload.sourceRows = Array.from({length: rows[1] - rows[0] + 1}, (_, i) => order[rows[0] + i]);
    }
    if (single) {
      payload.value = table.rows[order ? order[rows[0]] : rows[0]][columns[0]];
    }
    return {...payload, ...meta};
  }

  function selectionText(withHeader) {
    const selection = grid.getSelection();
    if (!selection || !table) {
      return '';
    }
    return selectionTsv(table, order, span(selection.anchor.r, selection.focus.r),
      span(selection.anchor.c, selection.focus.c), withHeader);
  }

  async function copySelection(withHeader = false) {
    const text = selectionText(withHeader);
    if (text && navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        statusLeft.textContent = `Copied ${text.split('\n').length.toLocaleString('en-CA')} lines as TSV`;
      } catch {
        statusLeft.textContent = 'Clipboard unavailable: press Ctrl+C in the table instead';
      }
    }
    return text;
  }

  function updateStatus(selection) {
    if (!selection) {
      statusLeft.textContent = query && table && !order?.length ? 'No matching rows' : '';
      return;
    }
    const rows = span(selection.anchor.r, selection.focus.r);
    const columns = span(selection.anchor.c, selection.focus.c);
    const name = (r, c) => `${columnName(c)}${r + 1}`;
    if (rows[0] === rows[1] && columns[0] === columns[1]) {
      const value = table.rows[order ? order[rows[0]] : rows[0]][columns[0]];
      statusLeft.textContent = `${name(rows[0], columns[0])}  ${value === null ? '(empty)' : String(value)}`;
    } else {
      const cells = (rows[1] - rows[0] + 1) * (columns[1] - columns[0] + 1);
      statusLeft.textContent = `${name(rows[0], columns[0])}:${name(rows[1], columns[1])}  `
        + `${cells.toLocaleString('en-CA')} cells`;
    }
  }

  // ---- sorting, stats, plot, editing -----------------------------------------

  function viewTable() {
    return order ? {...table, rows: Array.from(order, (index) => table.rows[index])} : table;
  }

  function refreshView() {
    order = filterOrder(table, sort ? sortOrder(table, sort.column, sort.direction) : null, query);
    grid.clearSelection();
    grid.setTable(table, order, sort);
    updateStatus(null);
    const count = order?.length ?? table.rows.length;
    const total = table.rows.length.toLocaleString('en-CA');
    statusRight.textContent = `${query ? `${count.toLocaleString('en-CA')} of ` : ''}${total} rows`
      + ` × ${table.columns.length} columns`
      + `${table.delimiter ? ` · ${table.delimiter === '\t' ? 'TSV' : `“${table.delimiter}” delimited`}` : ''}`
      + `${meta.name ? ` · ${meta.name}` : ''}`;
    renderStats();
    renderPlot();
  }

  function filterRows(value) {
    query = String(value ?? '');
    filterInput.value = query;
    if (table) {
      refreshView();
      events.emit('filter', {query, rows: order?.length ?? table.rows.length, total: table.rows.length});
    }
  }

  function sortBy(column, direction) {
    if (!table) {
      return;
    }
    sort = direction && column >= 0 && column < table.columns.length ? {column, direction} : null;
    refreshView();
    events.emit('sort', sort ? {...sort, name: table.columns[column].name} : null);
  }

  function renderStats() {
    if (statsPanel.hidden || !table?.columns.length) {
      return;
    }
    const column = grid.getSelection()?.focus.c ?? 0;
    const stats = columnStats(viewTable(), column);
    const rows = [['Count', stats.count], ['Missing', stats.missing]];
    if (isNumericType(stats.type)) {
      rows.push(['Min', stats.min], ['Max', stats.max], ['Mean', stats.mean], ['Std (n−1)', stats.std]);
      if (stats.nonFinite) {
        rows.push(['NaN / ∞', stats.nonFinite]);
      }
    } else {
      rows.push(['Unique', stats.unique]);
      if (stats.top) {
        rows.push(['Most common', `${String(stats.top.value).slice(0, 40)} (${stats.top.count})`]);
      }
    }
    statsPanel.replaceChildren(
      h('div', {class: 'vw-stats-head'}, h('span', {class: 'vw-stats-col'}, columnName(column)),
        h('b', {}, table.columns[column].name), h('span', {class: 'vw-type-tag', dataset: {type: stats.type}},
          stats.type)),
      h('dl', {class: 'vw-stats-list'}, rows.flatMap(([label, value]) => [h('dt', {}, label),
        h('dd', {}, value === null ? '—' : typeof value === 'number' ? formatNumber(value, 7) : value)])));
  }

  function showStats(open) {
    statsPanel.hidden = !open;
    setPressed(statsToggle, open);
    renderStats();
    grid.resize();
  }

  function numericColumns() {
    return table ? table.columns.map((column, index) => [column, index])
      .filter(([column]) => isNumericType(column.type))
      : [];
  }

  function fillPlotChoices(preferred = {}) {
    const numeric = numericColumns();
    plotX.replaceChildren(h('option', {value: '-1'}, 'Row number'),
      ...numeric.map(([column, index]) => h('option', {value: String(index)}, column.name)));
    plotY.replaceChildren(...numeric.map(([column, index]) => h('option', {value: String(index)}, column.name)));
    const usable = numeric.filter(([column]) => column.name !== 'line');
    const x = preferred.x ?? (usable.length > 1 ? usable[0][1] : -1);
    const y = preferred.y ?? (usable.find(([, index]) => index !== x)?.[1] ?? numeric[0]?.[1]);
    plotX.value = String(x);
    if (y !== undefined) {
      plotY.value = String(y);
    }
    if (preferred.logY !== undefined) {
      plotLog.checked = Boolean(preferred.logY);
    }
  }

  function renderPlot() {
    if (!table || plotPanel.hidden || !plotY.value) {
      return null;
    }
    return plot.render(viewTable(), Number(plotX.value), Number(plotY.value), {logY: plotLog.checked});
  }

  function showPlot(open, choice) {
    plotPanel.hidden = !open;
    setPressed(plotToggle, open);
    if (open && choice) {
      fillPlotChoices(choice);
    }
    grid.resize();
    return open ? renderPlot() : null;
  }

  function editCell(viewRow, column, text) {
    const type = table.columns[column].type;
    if (!isEmpty(text) && isNumericType(type) && !isNumberText(text)) {
      return 'Expected a number';
    }
    if (!isEmpty(text) && type === 'integer' && !/^\s*[+-]?\d+\s*$/.test(text)) {
      return 'Expected an integer';
    }
    if (!isEmpty(text) && type === 'boolean' && !/^\s*(true|false)\s*$/i.test(text)) {
      return 'Expected true or false';
    }
    const row = order ? order[viewRow] : viewRow;
    const oldValue = table.rows[row][column];
    const value = convert(text, type === 'empty' ? 'text' : type);
    table.rows[row][column] = value;
    // Let the current edit finish before rebuilding a filtered or sorted view.
    queueMicrotask(() => table && refreshView());
    events.emit('edit', {row, viewRow, column, name: table.columns[column].name, oldValue, value, ...meta});
    return null;
  }

  // ---- public API --------------------------------------------------------------

  async function load(input) {
    const token = ++loadToken;
    frame.setState('loading', 'Reading table…');
    let next;
    try {
      const data = await input;
      const descriptor = typeof data === 'string' ? {csv: data} : data || {};
      const text = descriptor.csv ?? descriptor.text ?? (descriptor.blob ? await descriptor.blob.text() : null);
      await new Promise((resolve) => setTimeout(resolve));
      if (token !== loadToken) {
        return null;
      }
      next = typeof text === 'string'
        ? tableFromDelimited(text, {delimiter: descriptor.delimiter, header: descriptor.header})
        : tableFromData(descriptor);
      meta = {};
      if (descriptor.name || descriptor.source?.name) {
        meta.name = descriptor.name || descriptor.source.name;
      }
      if (descriptor.revision !== undefined) {
        meta.revision = descriptor.revision;
      }
    } catch (error) {
      if (token === loadToken) {
        showError(error?.message || String(error));
      }
      return null;
    }
    if (token !== loadToken) {
      return null;
    }
    table = next;
    order = null;
    sort = null;
    query = '';
    filterInput.value = '';
    frame.setState(table.columns.length ? 'ready' : 'empty', table.columns.length ? '' : 'The table is empty');
    fillPlotChoices();
    refreshView();
    const summary = {rows: table.rows.length, columns: table.columns.map((column) => ({...column}))};
    events.emit('load', summary);
    return summary;
  }

  function clear() {
    loadToken++;
    table = null;
    order = null;
    sort = null;
    query = '';
    filterInput.value = '';
    grid.clearSelection();
    grid.setTable(null);
    statusLeft.textContent = '';
    statusRight.textContent = '';
    frame.setState('empty');
  }

  function showError(message) {
    frame.setState('error', message);
    events.emit('error', {message});
  }

  return {
    element: frame.root,
    load,
    clear,
    resize: () => {
      grid.resize();
      renderPlot();
    },
    destroy() {
      clear();
      grid.destroy();
      plotObserver.disconnect();
      frame.root.remove();
      events.clear();
    },
    showError,
    setLoading: (message) => frame.setState('loading', message),
    on: events.on,
    /** Sort by column index; direction 'asc' | 'desc' | null (original order). */
    sortBy,
    /** Literal, case-insensitive text matched against any cell in each row. */
    filterRows,
    getFilter: () => query,
    /** Select view rows [a, b] × columns [a, b]; emits selectionchange and, when final, pick. */
    select({rows, columns}, final = false) {
      grid.select({anchor: {r: rows[0], c: columns[0]}, focus: {r: rows[1] ?? rows[0], c: columns[1] ?? columns[0]}},
        final);
    },
    getSelection: () => pickPayload(grid.getSelection()),
    selectionText,
    copySelection,
    showStats,
    /** Open or close the plot; choice: {x (column index or -1 for row number), y, logY}. */
    showPlot,
    setEditable(on) {
      grid.setEditable(on);
      editBadge.hidden = !on;
    },
    getTable: () => table,
    get renderedCells() {
      return grid.renderedCells();
    },
    setTheme: () => renderPlot(),
  };
}
