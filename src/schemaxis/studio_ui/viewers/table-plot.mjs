// Copyright (C) 2026 David L F Gaden
// Small SVG line plot for the table viewer: one numeric Y against X, axes with
// nice ticks, optional log Y, per-pixel min/max decimation and a hover read-out.

import {h, s} from '../lib/dom.mjs';
import {formatNumber} from './common.mjs';

const MARGIN = {top: 28, right: 18, bottom: 36, left: 64};

/** "Nice" ticks covering [min, max] (about `count` of them). */
export function niceTicks(min, max, count = 5) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    return [];
  }
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const raw = (max - min) / Math.max(1, count);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((f) => f * magnitude).find((candidate) => candidate >= raw) || raw;
  const ticks = [];
  for (let value = Math.ceil(min / step) * step; value <= max + step * 1e-9; value += step) {
    ticks.push(Math.abs(value) < step * 1e-9 ? 0 : Number(value.toPrecision(12)));
  }
  return ticks;
}

/** Decade ticks for a log axis. */
function logTicks(min, max) {
  const ticks = [];
  for (let e = Math.floor(Math.log10(min)); e <= Math.ceil(Math.log10(max)); e++) {
    ticks.push(10 ** e);
  }
  return ticks.length > 8 ? ticks.filter((_, i) => i % Math.ceil(ticks.length / 8) === 0) : ticks;
}

/**
 * Points (x ascending, stable) for X and Y columns; rows with missing or non-finite
 * values (or Y ≤ 0 on a log axis) are skipped. Returns {xs, ys, rows, skipped}.
 */
export function plotPoints(table, xColumn, yColumn, logY = false) {
  const points = [];
  let skipped = 0;
  table.rows.forEach((row, index) => {
    const x = xColumn < 0 ? index : row[xColumn];
    const y = row[yColumn];
    if (typeof x === 'number' && typeof y === 'number' && Number.isFinite(x) && Number.isFinite(y) && (!logY || y > 0)) {
      points.push([x, y, index]);
    } else {
      skipped++;
    }
  });
  points.sort((a, b) => a[0] - b[0] || a[2] - b[2]);
  return {xs: points.map((p) => p[0]), ys: points.map((p) => p[1]), rows: points.map((p) => p[2]), skipped};
}

/** Keep the first, min, max and last point of each pixel column (preserves the visual envelope). */
export function decimate(xs, ys, toPixel, width) {
  if (xs.length <= width * 4) {
    return xs.map((_, i) => i);
  }
  const keep = [];
  let column = -1;
  let first = 0;
  let low = 0;
  let high = 0;
  let last = 0;
  const flush = () => {
    if (column >= 0) {
      keep.push(...[...new Set([first, low, high, last])].sort((a, b) => a - b));
    }
  };
  for (let i = 0; i < xs.length; i++) {
    const pixel = Math.floor(toPixel(xs[i]));
    if (pixel !== column) {
      flush();
      column = pixel;
      first = low = high = last = i;
    } else {
      last = i;
      if (ys[i] < ys[low]) {
        low = i;
      }
      if (ys[i] > ys[high]) {
        high = i;
      }
    }
  }
  flush();
  return keep;
}

export function createPlot() {
  const svg = s('svg', {class: 'vw-plot-svg', role: 'img'});
  const tooltip = h('div', {class: 'vw-plot-tip', hidden: true});
  const element = h('div', {class: 'vw-plot-area'}, svg, tooltip);
  let state = null;

  function render(table, xColumn, yColumn, {logY = false} = {}) {
    const width = Math.max(200, element.clientWidth);
    const height = Math.max(140, element.clientHeight);
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('width', width);
    svg.setAttribute('height', height);
    const xName = xColumn < 0 ? 'row' : table.columns[xColumn].name;
    const yName = table.columns[yColumn].name;
    svg.setAttribute('aria-label', `Line plot of ${yName} against ${xName}`);
    const {xs, ys, rows, skipped} = plotPoints(table, xColumn, yColumn, logY);
    if (xs.length < 1) {
      state = null;
      svg.replaceChildren(s('text', {class: 'vw-plot-empty', x: width / 2, y: height / 2, 'text-anchor': 'middle'},
        logY ? 'No positive numeric values to plot on a log axis' : 'No numeric values to plot'));
      return {points: 0, skipped};
    }
    const plotWidth = width - MARGIN.left - MARGIN.right;
    const plotHeight = height - MARGIN.top - MARGIN.bottom;
    const xTicks = niceTicks(xs[0], xs.at(-1), Math.max(2, Math.floor(plotWidth / 90)));
    const yMin = Math.min(...ys);
    const yMax = Math.max(...ys);
    const yTicks = logY ? logTicks(yMin, yMax) : niceTicks(yMin, yMax, Math.max(2, Math.floor(plotHeight / 50)));
    const x0 = Math.min(xs[0], xTicks[0] ?? xs[0]);
    const x1 = Math.max(xs.at(-1), xTicks.at(-1) ?? xs.at(-1));
    const y0 = logY ? Math.log10(Math.min(yMin, yTicks[0])) : Math.min(yMin, yTicks[0]);
    const y1 = logY ? Math.log10(Math.max(yMax, yTicks.at(-1))) : Math.max(yMax, yTicks.at(-1));
    const toX = (x) => MARGIN.left + ((x - x0) / (x1 - x0 || 1)) * plotWidth;
    const toY = (y) => MARGIN.top + plotHeight - (((logY ? Math.log10(y) : y) - y0) / (y1 - y0 || 1)) * plotHeight;
    const keep = decimate(xs, ys, toX, plotWidth);
    const path = keep.map((i, k) => `${k ? 'L' : 'M'}${toX(xs[i]).toFixed(1)},${toY(ys[i]).toFixed(1)}`).join('');

    const grid = s('g', {class: 'vw-plot-grid'});
    const axes = s('g', {class: 'vw-plot-axis'});
    for (const tick of yTicks) {
      const y = toY(tick);
      grid.append(s('line', {x1: MARGIN.left, x2: MARGIN.left + plotWidth, y1: y, y2: y}));
      axes.append(s('text', {x: MARGIN.left - 8, y, 'text-anchor': 'end', 'dominant-baseline': 'middle'},
        formatNumber(tick, 4)));
    }
    for (const tick of xTicks) {
      const x = toX(tick);
      axes.append(s('line', {class: 'vw-plot-tick', x1: x, x2: x, y1: MARGIN.top + plotHeight,
        y2: MARGIN.top + plotHeight + 4}));
      axes.append(s('text', {x, y: MARGIN.top + plotHeight + 18, 'text-anchor': 'middle'}, formatNumber(tick, 5)));
    }
    axes.append(s('line', {class: 'vw-plot-baseline', x1: MARGIN.left, x2: MARGIN.left + plotWidth,
      y1: MARGIN.top + plotHeight, y2: MARGIN.top + plotHeight}));
    const title = s('text', {class: 'vw-plot-title', x: MARGIN.left, y: 16},
      `${yName}${logY ? ' (log)' : ''} vs ${xName}`,
      s('tspan', {class: 'vw-plot-note', dx: 10}, `${xs.length.toLocaleString('en-CA')} points`
        + (skipped ? ` · ${skipped.toLocaleString('en-CA')} skipped` : '')));
    const crosshair = s('line', {class: 'vw-plot-cross', y1: MARGIN.top, y2: MARGIN.top + plotHeight, visibility: 'hidden'});
    const marker = s('circle', {class: 'vw-plot-marker', r: 4.5, visibility: 'hidden'});
    const hit = s('rect', {class: 'vw-plot-hit', x: MARGIN.left, y: MARGIN.top, width: plotWidth, height: plotHeight});
    svg.replaceChildren(grid, axes, title, s('path', {class: 'vw-plot-line', d: path}), crosshair, marker, hit);
    state = {xs, ys, rows, toX, toY, crosshair, marker, xName, yName, x0, x1, plotWidth};
    return {points: xs.length, skipped};
  }

  function hover(event) {
    if (!state) {
      return;
    }
    const rect = svg.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const target = state.x0 + ((px - MARGIN.left) / state.plotWidth) * (state.x1 - state.x0);
    let low = 0;
    let high = state.xs.length - 1;
    while (low < high) {
      const middle = (low + high) >> 1;
      if (state.xs[middle] < target) {
        low = middle + 1;
      } else {
        high = middle;
      }
    }
    const index = low > 0 && Math.abs(state.xs[low - 1] - target) <= Math.abs(state.xs[low] - target) ? low - 1 : low;
    const x = state.toX(state.xs[index]);
    const y = state.toY(state.ys[index]);
    state.crosshair.setAttribute('x1', x);
    state.crosshair.setAttribute('x2', x);
    state.crosshair.setAttribute('visibility', 'visible');
    state.marker.setAttribute('cx', x);
    state.marker.setAttribute('cy', y);
    state.marker.setAttribute('visibility', 'visible');
    tooltip.hidden = false;
    tooltip.replaceChildren(
      h('div', {}, h('span', {}, state.xName), h('b', {}, formatNumber(state.xs[index], 8))),
      h('div', {}, h('span', {}, state.yName), h('b', {}, formatNumber(state.ys[index], 8))),
      h('div', {class: 'vw-plot-tip-row'}, `row ${state.rows[index] + 1}`));
    const left = x + 14 + tooltip.offsetWidth > rect.width ? x - 14 - tooltip.offsetWidth : x + 14;
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${Math.max(4, y - tooltip.offsetHeight / 2)}px`;
  }

  svg.addEventListener('pointermove', hover);
  svg.addEventListener('pointerleave', () => {
    tooltip.hidden = true;
    state?.crosshair.setAttribute('visibility', 'hidden');
    state?.marker.setAttribute('visibility', 'hidden');
  });

  return {element, render};
}
