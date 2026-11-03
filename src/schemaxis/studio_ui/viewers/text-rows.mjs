// Copyright (C) 2026 David L F Gaden
// Virtualised line rendering for the text viewer: a recycled pool of row
// elements, line numbers, match highlights, line selection and mapping of
// DOM selections back to document offsets.

import {h} from '../lib/dom.mjs';
import {upperIndex} from './virtual.mjs';
import {VirtualScroller} from './virtual-scroll.mjs';

const MAX_RENDER = 4000;

/**
 * handlers: {onLineClick(line1, extend), onSelection({from, to})}
 */
export function createTextRows(body, handlers) {
  const scroller = h('div', {class: 'vw-text-scroll', tabindex: '0', role: 'region',
    'aria-label': 'Text. Arrow keys and Page Up/Down scroll; click line numbers to select lines.'});
  body.append(scroller);
  const virtual = new VirtualScroller(scroller, {onRender: (view) => render(view)});
  const pool = [];
  let doc = null;
  let matches = {starts: [], ends: []};
  let current = -1;
  let version = 0;
  let selection = null;
  let anchor = 0;
  let target = -1;
  let charWidth = 8;
  let rowHeight = 20;

  function measure() {
    const probe = h('div', {class: 'vw-text-row vw-text-probe'}, h('span', {class: 'vw-text-line'}, '0'.repeat(100)));
    virtual.layer.append(probe);
    charWidth = probe.firstChild.getBoundingClientRect().width / 100 || 8;
    rowHeight = probe.getBoundingClientRect().height || 20;
    probe.remove();
  }

  function layout() {
    if (!doc) {
      virtual.setRows(0, rowHeight, 0);
      return;
    }
    const digits = String(doc.lineCount).length;
    const gutter = Math.ceil((digits + 2) * charWidth);
    scroller.style.setProperty('--vw-gutter', `${gutter}px`);
    const width = gutter + Math.ceil(Math.min(doc.maxLength, MAX_RENDER + 12) * charWidth) + 32;
    virtual.setRows(doc.lineCount, rowHeight, width);
    virtual.layer.style.width = `${width}px`;
  }

  function lineSegments(line) {
    const start = doc.lineStart(line);
    const end = doc.lineEnd(line);
    const shownEnd = Math.min(end, start + MAX_RENDER);
    const text = doc.text.slice(start, shownEnd);
    const parts = [];
    let k = upperIndex(matches.starts, start);
    if (k < 0 || matches.ends[k] <= start) {
      k++;
    }
    let cursor = start;
    for (; k < matches.starts.length && matches.starts[k] < shownEnd; k++) {
      const from = Math.max(start, matches.starts[k]);
      const to = Math.min(shownEnd, matches.ends[k]);
      if (from > cursor) {
        parts.push(text.slice(cursor - start, from - start));
      }
      if (to > from) {
        parts.push(h('mark', {class: k === current ? 'vw-match vw-match-current' : 'vw-match'},
          text.slice(from - start, to - start)));
      }
      cursor = Math.max(cursor, to);
    }
    if (cursor < shownEnd) {
      parts.push(text.slice(cursor - start));
    }
    return {parts, more: end - shownEnd};
  }

  function render(view) {
    if (!doc) {
      for (const row of pool) {
        row.element.hidden = true;
      }
      return;
    }
    const count = view.last - view.first + 1;
    while (pool.length < count) {
      const gutter = h('span', {class: 'vw-text-gutter'});
      const text = h('span', {class: 'vw-text-line'});
      const element = h('div', {class: 'vw-text-row'}, gutter, text);
      gutter.addEventListener('mousedown', (event) => {
        event.preventDefault();
        scroller.focus({preventScroll: true});
        handlers.onLineClick(Number(element.dataset.line) + 1, event.shiftKey);
      });
      virtual.layer.append(element);
      pool.push({element, gutter, text, line: -1, version: -1});
    }
    pool.forEach((row, i) => {
      const line = view.first + i;
      row.element.hidden = i >= count;
      if (i >= count) {
        return;
      }
      const selected = selection && line >= selection[0] && line <= selection[1];
      row.element.classList.toggle('vw-text-row-selected', Boolean(selected));
      row.element.classList.toggle('vw-text-row-target', line === target);
      if (row.line === line && row.version === version) {
        return;
      }
      row.line = line;
      row.version = version;
      row.element.dataset.line = String(line);
      row.gutter.textContent = String(line + 1);
      const {parts, more} = lineSegments(line);
      row.text.replaceChildren(...parts);
      if (more > 0) {
        row.text.dataset.more = ` … ${more.toLocaleString('en-CA')} more characters`;
      } else {
        delete row.text.dataset.more;
      }
    });
  }

  /** Map a DOM selection boundary to a document offset, or null outside the rows. */
  function offsetOf(node, offset) {
    const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    const row = element?.closest('.vw-text-row');
    if (!row || !virtual.layer.contains(row) || row.dataset.line === undefined) {
      return null;
    }
    const line = Number(row.dataset.line);
    const text = row.querySelector('.vw-text-line');
    let column = 0;
    if (text.contains(node)) {
      const range = document.createRange();
      range.setStart(text, 0);
      range.setEnd(node, offset);
      column = range.toString().length;
    } else if (node === row && offset > 1) {
      column = Infinity;
    }
    return Math.min(doc.lineStart(line) + column, doc.lineEnd(line));
  }

  scroller.addEventListener('mouseup', () => {
    const selected = getSelection();
    if (!doc || !selected || selected.isCollapsed || !scroller.contains(selected.anchorNode)) {
      return;
    }
    const a = offsetOf(selected.anchorNode, selected.anchorOffset);
    const b = offsetOf(selected.focusNode, selected.focusOffset);
    if (a !== null && b !== null && a !== b) {
      selection = null;
      version++;
      handlers.onSelection({from: Math.min(a, b), to: Math.max(a, b)});
    }
  });

  const resizeObserver = new ResizeObserver(() => virtual.setTop(virtual.top));
  resizeObserver.observe(scroller);

  return {
    setDocument(next) {
      doc = next;
      matches = {starts: [], ends: []};
      current = -1;
      selection = null;
      target = -1;
      version++;
      measure();
      virtual.top = 0;
      layout();
      virtual.setTop(0);
      scroller.scrollLeft = 0;
    },
    setMatches(next, index) {
      matches = next;
      current = index;
      version++;
      virtual.schedule();
    },
    reveal(line, from, to) {
      virtual.reveal(line);
      const start = doc.lineStart(line);
      const gutter = parseFloat(scroller.style.getPropertyValue('--vw-gutter')) || 0;
      const left = gutter + (from - start) * charWidth;
      const right = gutter + (to - start) * charWidth;
      if (left - gutter < scroller.scrollLeft || right > scroller.scrollLeft + scroller.clientWidth - 16) {
        scroller.scrollLeft = Math.max(0, left - gutter - scroller.clientWidth / 3);
      }
      virtual.schedule();
    },
    scrollToLine(line) {
      target = line;
      version++;
      virtual.setTop(line - Math.floor(virtual.viewportHeight() / rowHeight / 3));
    },
    topLine: () => virtual.top,
    setLineSelection(a, b, newAnchor) {
      selection = [a, b];
      if (newAnchor !== undefined) {
        anchor = newAnchor;
      }
      getSelection()?.removeAllRanges();
      virtual.schedule();
    },
    anchor: () => anchor + 1,
    focus: () => scroller.focus({preventScroll: true}),
    resize: () => virtual.setTop(virtual.top),
    renderedCount: () => pool.filter((row) => !row.element.hidden).length,
    destroy() {
      resizeObserver.disconnect();
      virtual.destroy();
    },
  };
}
