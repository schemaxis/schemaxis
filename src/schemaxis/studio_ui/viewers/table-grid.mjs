// Virtualised table grid: rows and columns are virtualised, the header is
// sticky, row numbers stick to the left. Handles cell/range selection by mouse
// and keyboard, sorting clicks, copy and optional in-cell editing.

import {h} from '../lib/dom.mjs';
import {columnName} from './chip.mjs';
import {formatValue} from './table-model.mjs';
import {isNumericType} from './data-types.mjs';
import {VirtualScroller} from './virtual-scroll.mjs';
import {viewerIcon} from './icons.mjs';

const ROW_HEIGHT = 26;
const HEADER_HEIGHT = 34;
let gridCount = 0;

/** Column widths (px) from header names and a sample of values. */
export function columnWidths(table, charWidth = 7.4) {
  const sample = Math.min(table.rows.length, 400);
  return table.columns.map((column, c) => {
    let chars = column.name.length + 3;
    for (let r = 0; r < sample; r++) {
      chars = Math.max(chars, Math.min(48, formatValue(table.rows[r][c]).split('\n')[0].length));
    }
    return Math.round(Math.max(72, Math.min(340, chars * charWidth + 26)));
  });
}

/**
 * handlers: {onSelect(selection, final), onSort(column), onEdit(viewRow, column, text) → error|null,
 *            onCopy(withHeader) → text}
 * selection = {anchor: {r, c}, focus: {r, c}}
 */
export function createGrid(body, handlers) {
  const id = `vw-grid-${++gridCount}`;
  const scroller = h('div', {class: 'vw-table-scroll', tabindex: '0', role: 'grid', 'aria-multiselectable': 'true',
    'aria-label': 'Table. Arrow keys move, Shift+arrows extend, Enter references the selection, Ctrl+C copies.'});
  body.append(scroller);
  const virtual = new VirtualScroller(scroller, {keyboard: false, headerHeight: HEADER_HEIGHT,
    onRender: (view) => render(view)});
  const corner = h('div', {class: 'vw-th vw-th-corner', role: 'columnheader'}, '#');
  const headerCells = h('div', {class: 'vw-th-cells'});
  const header = h('div', {class: 'vw-th-row', role: 'row'}, corner, headerCells);
  virtual.sizer.prepend(header);
  const pool = [];
  let table = null;
  let order = null;
  let sort = null;
  let widths = [];
  let lefts = [];
  let gutter = 56;
  let total = 0;
  let selection = null;
  let editable = false;
  let editing = null;
  let version = 0;
  let drag = null;
  const rowCount = () => order?.length ?? table?.rows.length ?? 0;

  function setTable(next, nextOrder, nextSort) {
    editing = null;
    drag = null;
    table = next;
    order = nextOrder;
    sort = nextSort;
    if (!table) {
      virtual.setRows(0, ROW_HEIGHT, 0);
      return;
    }
    widths = columnWidths(table);
    gutter = Math.max(48, String(table.rows.length).length * 8 + 24);
    lefts = [];
    total = gutter;
    for (const width of widths) {
      lefts.push(total);
      total += width;
    }
    scroller.style.setProperty('--vw-gutter', `${gutter}px`);
    scroller.setAttribute('aria-rowcount', String(rowCount() + 1));
    scroller.setAttribute('aria-colcount', String(table.columns.length));
    header.style.width = `${total}px`;
    virtual.layer.style.width = `${total}px`;
    virtual.setRows(rowCount(), ROW_HEIGHT, total);
    version++;
    virtual.schedule();
  }

  function columnRange() {
    const left = scroller.scrollLeft;
    const right = left + scroller.clientWidth;
    let first = 0;
    while (first < widths.length - 1 && lefts[first] + widths[first] <= left + gutter) {
      first++;
    }
    let last = first;
    while (last < widths.length - 1 && lefts[last + 1] < right) {
      last++;
    }
    return [first, last];
  }

  const inRange = (value, a, b) => value >= Math.min(a, b) && value <= Math.max(a, b);

  function cellClass(r, c) {
    const classes = ['vw-td'];
    if (isNumericType(table.columns[c].type)) {
      classes.push('vw-td-num');
    }
    if (selection && inRange(r, selection.anchor.r, selection.focus.r) && inRange(c, selection.anchor.c,
      selection.focus.c)) {
      classes.push('vw-td-selected');
    }
    if (selection && selection.focus.r === r && selection.focus.c === c) {
      classes.push('vw-td-focus');
    }
    return classes;
  }

  function renderHeader([c0, c1]) {
    const cells = [];
    for (let c = c0; c <= c1 && c < table.columns.length; c++) {
      const column = table.columns[c];
      const sorted = sort?.column === c ? sort.direction : null;
      const selected = selection && inRange(c, selection.anchor.c, selection.focus.c);
      cells.push(h('div', {class: ['vw-th', selected ? 'vw-th-selected' : null], role: 'columnheader',
        'aria-sort': sorted ? (sorted === 'asc' ? 'ascending' : 'descending') : 'none',
        style: {left: `${lefts[c]}px`, width: `${widths[c]}px`},
        title: `${column.name} · ${column.type} · click to sort`,
        onClick: () => handlers.onSort(c)},
      h('span', {class: 'vw-th-name'}, column.name),
      h('span', {class: 'vw-th-type', dataset: {type: column.type}}, column.type === 'integer' ? 'int'
        : column.type === 'number' ? 'num' : column.type === 'boolean' ? 'bool' : column.type),
      sorted ? h('span', {class: 'vw-th-sort'}, viewerIcon(sorted === 'asc' ? 'up' : 'down')) : null));
    }
    headerCells.replaceChildren(...cells);
  }

  function render(view) {
    if (!table) {
      headerCells.replaceChildren();
      pool.forEach((row) => {
        row.element.hidden = true;
      });
      return;
    }
    const range = columnRange();
    renderHeader(range);
    const count = view.last - view.first + 1;
    while (pool.length < count) {
      const number = h('div', {class: 'vw-td-rownum', role: 'rowheader'});
      const element = h('div', {class: 'vw-tr', role: 'row'}, number);
      virtual.layer.append(element);
      pool.push({element, number, key: ''});
    }
    pool.forEach((row, i) => {
      row.element.hidden = i >= count;
      if (i >= count) {
        return;
      }
      const r = view.first + i;
      const key = `${r}:${range[0]}:${range[1]}:${version}`;
      if (row.key === key) {
        return;
      }
      row.key = key;
      row.element.dataset.row = String(r);
      row.element.setAttribute('aria-rowindex', String(r + 2));
      row.number.textContent = String(r + 1);
      row.element.classList.toggle('vw-tr-odd', r % 2 === 1);
      row.number.classList.toggle('vw-td-rownum-selected', Boolean(selection && inRange(r, selection.anchor.r,
        selection.focus.r)));
      const values = table.rows[order ? order[r] : r];
      const cells = [];
      for (let c = range[0]; c <= range[1]; c++) {
        const value = values[c];
        const text = formatValue(value);
        const cell = h('div', {class: cellClass(r, c), role: 'gridcell', id: `${id}-${r}-${c}`,
          dataset: {col: String(c)}, style: {left: `${lefts[c]}px`, width: `${widths[c]}px`},
          title: text.length > 40 || text.includes('\n') ? text : undefined});
        if (editing && editing.r === r && editing.c === c) {
          cell.append(editing.input);
        } else if (value === null) {
          cell.classList.add('vw-td-missing');
        } else {
          cell.textContent = text.includes('\n') ? text.replace(/\r?\n/g, ' ⏎ ') : text;
        }
        cells.push(cell);
      }
      row.element.replaceChildren(row.number, ...cells);
    });
    if (selection) {
      scroller.setAttribute('aria-activedescendant', `${id}-${selection.focus.r}-${selection.focus.c}`);
    }
    editing?.input.isConnected && document.activeElement !== editing.input && editing.input.focus();
  }

  // ---- selection ------------------------------------------------------------

  function select(next, final = false, reveal = true) {
    const rows = rowCount();
    const columns = table?.columns.length ?? 0;
    const clamp = ({r, c}) => ({r: Math.max(0, Math.min(rows - 1, Math.trunc(r) || 0)),
      c: Math.max(0, Math.min(columns - 1, Math.trunc(c) || 0))});
    selection = rows && columns && next ? {anchor: clamp(next.anchor), focus: clamp(next.focus)} : null;
    version++;
    if (reveal && selection) {
      revealCell(selection.focus.r, selection.focus.c);
    }
    virtual.schedule();
    handlers.onSelect(selection, final && Boolean(selection));
  }

  function revealCell(r, c) {
    virtual.reveal(r);
    const left = lefts[c] - gutter;
    const right = lefts[c] + widths[c];
    if (left < scroller.scrollLeft) {
      scroller.scrollLeft = left;
    } else if (right > scroller.scrollLeft + scroller.clientWidth) {
      scroller.scrollLeft = right - scroller.clientWidth;
    }
  }

  function cellAt(event) {
    const element = document.elementFromPoint(event.clientX, event.clientY);
    const row = element?.closest('.vw-tr');
    if (!row || !scroller.contains(row)) {
      return null;
    }
    const cell = element.closest('.vw-td');
    const r = Number(row.dataset.row);
    return cell ? {r, c: Number(cell.dataset.col), row: false} : {r, c: 0, row: true};
  }

  scroller.addEventListener('pointerdown', (event) => {
    if (!table || event.button !== 0 || event.target.closest('.vw-th-row') || event.target === editing?.input) {
      return;
    }
    const cell = cellAt(event);
    if (!cell) {
      return;
    }
    event.preventDefault();
    scroller.focus({preventScroll: true});
    commitEdit();
    const last = table.columns.length - 1;
    if (cell.row) {
      const anchor = event.shiftKey && selection ? {r: selection.anchor.r, c: 0} : {r: cell.r, c: 0};
      select({anchor, focus: {r: cell.r, c: last}}, false, false);
    } else {
      const anchor = event.shiftKey && selection ? selection.anchor : {r: cell.r, c: cell.c};
      select({anchor, focus: {r: cell.r, c: cell.c}}, false, false);
    }
    drag = {id: event.pointerId, row: cell.row};
    scroller.setPointerCapture(event.pointerId);
  });
  scroller.addEventListener('pointermove', (event) => {
    if (!drag || drag.id !== event.pointerId) {
      return;
    }
    const cell = cellAt(event);
    if (cell && (cell.r !== selection.focus.r || (!drag.row && cell.c !== selection.focus.c))) {
      select({anchor: selection.anchor, focus: {r: cell.r, c: drag.row ? selection.focus.c : cell.c}}, false, false);
    }
  });
  scroller.addEventListener('pointerup', (event) => {
    if (drag && drag.id === event.pointerId) {
      drag = null;
      handlers.onSelect(selection, true);
    }
  });
  scroller.addEventListener('dblclick', (event) => {
    const cell = cellAt(event);
    if (cell && !cell.row) {
      startEdit(cell.r, cell.c);
    }
  });

  scroller.addEventListener('keydown', (event) => {
    if (!table || event.target !== scroller) {
      return;
    }
    const rows = rowCount();
    const columns = table.columns.length;
    if (!rows || !columns) {
      return;
    }
    const mod = event.ctrlKey || event.metaKey;
    const focus = selection?.focus || {r: 0, c: 0};
    const page = Math.max(1, Math.floor(virtual.viewportHeight() / ROW_HEIGHT) - 1);
    const moves = {ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1], PageUp: [-page, 0],
      PageDown: [page, 0]};
    let next = null;
    if (moves[event.key]) {
      const [dr, dc] = moves[event.key];
      next = mod ? {r: dr ? (dr < 0 ? 0 : rows - 1) : focus.r, c: dc ? (dc < 0 ? 0 : columns - 1) : focus.c}
        : {r: focus.r + dr, c: focus.c + dc};
    } else if (event.key === 'Home') {
      next = {r: mod ? 0 : focus.r, c: 0};
    } else if (event.key === 'End') {
      next = {r: mod ? rows - 1 : focus.r, c: columns - 1};
    } else if (mod && event.key.toLowerCase() === 'a') {
      event.preventDefault();
      select({anchor: {r: 0, c: 0}, focus: {r: rows - 1, c: columns - 1}}, false, false);
      return;
    } else if (event.key === 'Enter' && selection) {
      event.preventDefault();
      handlers.onSelect(selection, true);
      return;
    } else if (event.key === 'F2' && selection) {
      event.preventDefault();
      startEdit(selection.focus.r, selection.focus.c);
      return;
    } else if (event.key === 'Escape' && selection) {
      select({anchor: selection.focus, focus: selection.focus}, false);
      return;
    } else {
      return;
    }
    event.preventDefault();
    next = {r: Math.max(0, Math.min(rows - 1, next.r)), c: Math.max(0, Math.min(columns - 1, next.c))};
    select({anchor: event.shiftKey && selection ? selection.anchor : next, focus: next});
  });

  scroller.addEventListener('copy', (event) => {
    if (!selection || event.target === editing?.input) {
      return;
    }
    event.preventDefault();
    event.clipboardData.setData('text/plain', handlers.onCopy(false));
  });

  // ---- editing ----------------------------------------------------------------

  function startEdit(r, c) {
    if (!editable) {
      return;
    }
    commitEdit();
    const value = table.rows[order ? order[r] : r][c];
    const input = h('input', {class: 'vw-cell-input', value: formatValue(value),
      'aria-label': `Edit ${columnName(c)}${r + 1}`});
    input.addEventListener('keydown', (event) => {
      event.stopPropagation();
      if (event.key === 'Enter') {
        event.preventDefault();
        commitEdit(true);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        cancelEdit();
      }
    });
    input.addEventListener('blur', () => commitEdit());
    editing = {r, c, input, original: formatValue(value)};
    version++;
    virtual.schedule();
  }

  function commitEdit(refocus = false) {
    if (!editing) {
      return;
    }
    const current = editing;
    if (current.input.value !== current.original) {
      const error = handlers.onEdit(current.r, current.c, current.input.value);
      if (error) {
        current.input.setAttribute('aria-invalid', 'true');
        current.input.title = error;
        return;
      }
    }
    editing = null;
    version++;
    virtual.schedule();
    if (refocus) {
      scroller.focus({preventScroll: true});
    }
  }

  function cancelEdit() {
    editing = null;
    version++;
    virtual.schedule();
    scroller.focus({preventScroll: true});
  }

  scroller.addEventListener('scroll', () => virtual.schedule(), {passive: true});
  const resizeObserver = new ResizeObserver(() => virtual.setTop(virtual.top));
  resizeObserver.observe(scroller);

  return {
    setTable,
    setEditable(on) {
      editable = Boolean(on);
    },
    select: (next, final = false) => select(next, final),
    clearSelection() {
      selection = null;
      scroller.removeAttribute('aria-activedescendant');
      version++;
      virtual.schedule();
    },
    getSelection: () => selection,
    refresh() {
      version++;
      virtual.schedule();
    },
    focus: () => scroller.focus({preventScroll: true}),
    resize: () => virtual.setTop(virtual.top),
    scrollToRow: (r) => virtual.setTop(r),
    renderedCells: () => virtual.layer.querySelectorAll('.vw-tr:not([hidden]) .vw-td').length,
    destroy() {
      resizeObserver.disconnect();
      virtual.destroy();
    },
  };
}
