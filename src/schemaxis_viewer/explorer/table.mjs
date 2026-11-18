// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// CSV/TSV viewer: quoted multiline cells, sorting, row filtering and a line
// chart of numeric columns.

import {h, icon, clear, fill} from './dom.mjs';
import {readText} from './host.mjs';
import {naturalCompare} from './names.mjs';

const MAX_ROWS = 5000;
const SVG = 'http://www.w3.org/2000/svg';
const PALETTE = ['#2563c9', '#d9730d', '#18794e', '#b0479b', '#8a6d1a', '#0f8f9f', '#c4282d', '#6b56c9'];

export function parseDelimited(text, delimiter) {
  const rows = [];
  let row = [], cell = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (char === '"') {
        quoted = false;
      } else {
        cell += char;
      }
    } else if (char === '"' && cell === '') {
      quoted = true;
    } else if (char === delimiter) {
      row.push(cell);
      cell = '';
    } else if (char === '\n' || char === '\r') {
      if (char === '\r' && text[i + 1] === '\n') i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else {
      cell += char;
    }
  }
  if (cell !== '' || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter(entry => entry.length > 1 || entry[0] !== '');
}

function numeric(value) {
  return value.trim() !== '' && Number.isFinite(Number(value));
}

function svg(tag, attributes = {}, text = null) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (text !== null) node.textContent = text;
  return node;
}

function ticks(low, high, count) {
  if (low === high) return [low];
  const step = Math.pow(10, Math.floor(Math.log10((high - low) / count)));
  const multiple = [1, 2, 5, 10].find(m => (high - low) / (step * m) <= count) * step;
  const result = [];
  for (let value = Math.ceil(low / multiple) * multiple; value <= high + multiple * 1e-9; value += multiple) result.push(Number(value.toPrecision(12)));
  return result;
}

function label(value) {
  const magnitude = Math.abs(value);
  return magnitude && (magnitude >= 1e5 || magnitude < 1e-3) ? value.toExponential(1) : String(Number(value.toPrecision(6)));
}

export class TableView {
  constructor(container, item) {
    this.item = item;
    this.mode = 'table';
    this.sort = null;
    this.filter = '';
    this.root = container.appendChild(h('div', {class: 'table-viewer'}));
    this.bar = this.root.appendChild(h('div', {class: 'findbar'}));
    this.body = this.root.appendChild(h('div', {class: 'table-scroll'}));
    this.observer = new ResizeObserver(() => {
      if (this.mode === 'chart') this.drawChart();
    });
    this.observer.observe(this.root);
    this.load();
  }

  async load() {
    try {
      const {text} = await readText(this.item, 64 * 1024 * 1024);
      const firstLine = text.slice(0, text.indexOf('\n') >>> 0);
      const delimiter = this.item.ext === 'tsv' || firstLine.includes('\t') ? '\t'
        : (firstLine.split(';').length > firstLine.split(',').length ? ';' : ',');
      const rows = parseDelimited(text, delimiter);
      const headerless = rows.length && rows[0].every(numeric);
      this.header = headerless ? rows[0].map((_, index) => `column ${index + 1}`) : rows[0] || [];
      this.rows = headerless ? rows : rows.slice(1);
      const width = Math.max(this.header.length, ...this.rows.slice(0, 1000).map(row => row.length));
      while (this.header.length < width) this.header.push(`column ${this.header.length + 1}`);
      this.numeric = this.header.map((_, column) => {
        const values = this.rows.slice(0, 2000).map(row => row[column] ?? '').filter(value => value.trim() !== '');
        return values.length > 0 && values.filter(numeric).length / values.length >= 0.8;
      });
      const numericColumns = this.header.map((_, i) => i).filter(i => this.numeric[i]);
      this.x = numericColumns[0] ?? -1;
      this.y = new Set(numericColumns.filter(i => i !== this.x).slice(0, 3));
      this.renderBar();
      this.renderBody();
    } catch (error) {
      fill(this.body, h('div', {class: 'no-preview'}, error.message));
    }
  }

  renderBar() {
    const canChart = this.numeric.some(Boolean);
    fill(this.bar,
      h('div', {class: 'views'},
        h('button', {type: 'button', 'aria-pressed': String(this.mode === 'table'), onClick: () => this.setMode('table')}, icon('table'), 'Table'),
        h('button', {type: 'button', 'aria-pressed': String(this.mode === 'chart'), disabled: !canChart, onClick: () => this.setMode('chart')},
          icon('groups'), 'Chart')),
      this.mode === 'table' ? h('label', {class: 'search-box'}, icon('search'), h('input', {type: 'search', placeholder: 'Filter rows',
        value: this.filter, onInput: event => {
          this.filter = event.target.value;
          this.renderBody();
        }})) : null,
      h('span', {class: 'counter'}, `${this.rows.length} rows · ${this.header.length} columns`));
  }

  setMode(mode) {
    this.mode = mode;
    this.renderBar();
    this.renderBody();
  }

  renderBody() {
    if (this.mode === 'chart') {
      this.renderChart();
      return;
    }
    clear(this.body).className = 'table-scroll';
    let rows = this.rows.map((row, index) => ({row, index}));
    if (this.filter) {
      const needle = this.filter.toLowerCase();
      rows = rows.filter(entry => entry.row.some(cell => cell.toLowerCase().includes(needle)));
    }
    if (this.sort) {
      const {column, descending} = this.sort;
      const isNumber = this.numeric[column];
      rows.sort((a, b) => {
        const x = a.row[column] ?? '', y = b.row[column] ?? '';
        const order = isNumber ? (Number(x) - Number(y)) || 0 : naturalCompare(x, y);
        return descending ? -order : order;
      });
    }
    const shown = rows.slice(0, MAX_ROWS);
    const table = h('table', {class: 'data-table'},
      h('thead', {}, h('tr', {}, h('th', {}, '#'), this.header.map((name, column) => h('th', {title: 'Sort', onClick: () => {
        this.sort = {column, descending: this.sort?.column === column ? !this.sort.descending : false};
        this.renderBody();
      }}, name, this.sort?.column === column ? (this.sort.descending ? ' ↓' : ' ↑') : '')))),
      h('tbody', {}, shown.map(entry => h('tr', {}, h('td', {class: 'rowno'}, entry.index + 1),
        this.header.map((_, column) => h('td', {class: this.numeric[column] ? 'num' : ''}, entry.row[column] ?? ''))))));
    this.body.append(table);
    if (rows.length > MAX_ROWS) this.body.append(h('div', {class: 'sidebar-note'}, `Showing the first ${MAX_ROWS} of ${rows.length} rows. Filter or sort to see others.`));
  }

  renderChart() {
    clear(this.body).className = 'chart-wrap';
    const columns = this.header.map((name, index) => ({name, index})).filter(column => this.numeric[column.index]);
    const xSelect = h('select', {'aria-label': 'X axis', onChange: event => {
      this.x = Number(event.target.value);
      this.drawChart();
    }}, h('option', {value: -1, selected: this.x === -1}, 'Row number'),
    columns.map(column => h('option', {value: column.index, selected: column.index === this.x}, column.name)));
    const picks = h('div', {class: 'series-picks'}, columns.map(column => h('label', {},
      h('input', {type: 'checkbox', checked: this.y.has(column.index), onChange: event => {
        if (event.target.checked) this.y.add(column.index);
        else this.y.delete(column.index);
        this.drawChart();
      }}), column.name)));
    this.legend = h('div', {class: 'chart-legend'});
    this.svg = svg('svg', {role: 'img', 'aria-label': 'Line chart'});
    this.body.append(h('div', {class: 'findbar'}, h('label', {class: 'field'}, 'X ', xSelect), h('span', {}, 'Y'), picks), this.svg, this.legend);
    this.drawChart();
  }

  drawChart() {
    if (!this.svg?.isConnected) return;
    const rect = this.svg.getBoundingClientRect();
    const width = Math.max(200, rect.width), height = Math.max(160, rect.height);
    this.svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    this.svg.replaceChildren();
    const series = [...this.y].map((column, order) => ({column, colour: PALETTE[order % PALETTE.length],
      points: this.rows.map((row, index) => [this.x < 0 ? index + 1 : Number(row[this.x]), Number(row[column])])
        .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y))}));
    for (const entry of series) entry.points.sort((a, b) => a[0] - b[0]);
    const all = series.flatMap(entry => entry.points);
    fill(this.legend, ...series.map(entry => {
      const node = h('span', {}, this.header[entry.column]);
      node.style.setProperty('--swatch', entry.colour);
      return node;
    }));
    if (!all.length) {
      this.svg.append(svg('text', {x: width / 2, y: height / 2, 'text-anchor': 'middle', class: 'chart-label'}, 'Choose one or more numeric columns'));
      return;
    }
    const margin = {left: 64, right: 16, top: 10, bottom: 34};
    const xs = all.map(p => p[0]), ys = all.map(p => p[1]);
    let [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    if (x0 === x1) { x0 -= 1; x1 += 1; }
    if (y0 === y1) { y0 -= 1; y1 += 1; }
    const pad = (y1 - y0) * 0.05;
    y0 -= pad;
    y1 += pad;
    const sx = x => margin.left + (x - x0) / (x1 - x0) * (width - margin.left - margin.right);
    const sy = y => height - margin.bottom - (y - y0) / (y1 - y0) * (height - margin.top - margin.bottom);
    for (const value of ticks(y0, y1, 6)) {
      this.svg.append(svg('line', {x1: margin.left, x2: width - margin.right, y1: sy(value), y2: sy(value), class: 'chart-grid'}),
        svg('text', {x: margin.left - 8, y: sy(value) + 4, 'text-anchor': 'end', class: 'chart-label'}, label(value)));
    }
    for (const value of ticks(x0, x1, Math.max(2, Math.floor(width / 110)))) {
      this.svg.append(svg('text', {x: sx(value), y: height - margin.bottom + 18, 'text-anchor': 'middle', class: 'chart-label'}, label(value)));
    }
    this.svg.append(svg('line', {x1: margin.left, x2: width - margin.right, y1: height - margin.bottom, y2: height - margin.bottom, class: 'chart-axis'}),
      svg('line', {x1: margin.left, x2: margin.left, y1: margin.top, y2: height - margin.bottom, class: 'chart-axis'}),
      svg('text', {x: (width + margin.left) / 2, y: height - 4, 'text-anchor': 'middle', class: 'chart-label'}, this.x < 0 ? 'row' : this.header[this.x]));
    for (const entry of series) {
      const path = entry.points.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join('');
      this.svg.append(svg('path', {d: path, class: 'chart-line', stroke: entry.colour}));
    }
  }

  dispose() {
    this.observer.disconnect();
  }
}
