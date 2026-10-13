// DOM controller for virtual scrolling (text and table viewers).
// Structure: scroller (overflow: auto) > sizer (full virtual size) > layer
// (translated to the viewport). The fractional top row is the source of
// truth, so stepping stays exact even when the scroll range is scaled.

import {h} from '../lib/dom.mjs';
import {contentHeight, scrollTopFor, topRowFor} from './virtual.mjs';

export class VirtualScroller {
  /** options: {onRender(window), keyboard = true, headerHeight = 0 (sticky header above the rows)} */
  constructor(scroller, options = {}) {
    this.scroller = scroller;
    this.onRender = options.onRender;
    this.sizer = h('div', {class: 'vw-vsizer'});
    this.layer = h('div', {class: 'vw-vlayer'});
    this.sizer.append(this.layer);
    scroller.append(this.sizer);
    this.rowCount = 0;
    this.rowHeight = 20;
    this.headerHeight = options.headerHeight || 0;
    this.top = 0;
    this.expected = 0;
    this.frame = 0;
    this.onScroll = () => {
      const scrollTop = scroller.scrollTop;
      if (Math.abs(scrollTop - this.expected) > 1) {
        this.top = topRowFor(scrollTop, this.viewportHeight(), this.rowHeight, this.rowCount);
      }
      this.expected = scrollTop;
      this.schedule();
    };
    this.onWheel = (event) => {
      // In scaled mode a native wheel step would jump many rows; scroll by rows instead.
      if (!this.scaled() || event.ctrlKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
        return;
      }
      event.preventDefault();
      const delta = event.deltaMode === 1 ? event.deltaY : event.deltaY / this.rowHeight;
      this.setTop(this.top + delta);
    };
    this.onKey = (event) => {
      if (event.altKey || event.target !== scroller) {
        return;
      }
      const page = Math.max(1, Math.floor(this.viewportHeight() / this.rowHeight) - 1);
      const mod = event.ctrlKey || event.metaKey;
      const moves = {ArrowDown: 1, ArrowUp: -1, PageDown: page, PageUp: -page};
      if (moves[event.key] && !mod) {
        this.setTop(this.top + moves[event.key]);
      } else if (event.key === 'Home' && mod) {
        this.setTop(0);
      } else if (event.key === 'End' && mod) {
        this.setTop(this.rowCount);
      } else {
        return;
      }
      event.preventDefault();
    };
    scroller.addEventListener('scroll', this.onScroll, {passive: true});
    scroller.addEventListener('wheel', this.onWheel, {passive: false});
    if (options.keyboard !== false) {
      scroller.addEventListener('keydown', this.onKey);
    }
  }

  viewportHeight() {
    return Math.max(0, this.scroller.clientHeight - this.headerHeight);
  }

  scaled() {
    return this.rowCount * this.rowHeight > contentHeight(this.rowCount, this.rowHeight);
  }

  maxTop() {
    return Math.max(0, this.rowCount - this.viewportHeight() / this.rowHeight);
  }

  /** Set row count, row height (px) and content width (px). Keeps the top row when possible. */
  setRows(rowCount, rowHeight, width) {
    this.rowCount = rowCount;
    this.rowHeight = rowHeight;
    this.sizer.style.height = `${contentHeight(rowCount, rowHeight) + this.headerHeight}px`;
    if (width !== undefined) {
      this.sizer.style.width = `${Math.max(0, width)}px`;
    }
    this.setTop(Math.min(this.top, this.maxTop()));
  }

  setTop(row) {
    this.top = Math.max(0, Math.min(this.maxTop(), row));
    const scrollTop = scrollTopFor(this.top, this.viewportHeight(), this.rowHeight, this.rowCount);
    this.expected = scrollTop;
    this.scroller.scrollTop = scrollTop;
    this.expected = this.scroller.scrollTop;
    this.schedule();
  }

  /** Scroll so that `row` is fully visible (minimal movement). */
  reveal(row) {
    const visible = this.viewportHeight() / this.rowHeight;
    if (row < this.top) {
      this.setTop(row);
    } else if (row + 1 > this.top + visible) {
      this.setTop(row + 1 - visible);
    }
  }

  /** Rows to render: {first, last, offset}; row `first` is drawn `offset` px (≤ 0) below the viewport top. */
  window() {
    if (!this.rowCount) {
      return {first: 0, last: -1, offset: 0};
    }
    const first = Math.min(this.rowCount - 1, Math.floor(this.top));
    const offset = -(this.top - first) * this.rowHeight;
    const last = Math.min(this.rowCount - 1, first + Math.ceil((this.viewportHeight() - offset) / this.rowHeight));
    return {first, last, offset};
  }

  schedule() {
    if (!this.frame) {
      this.frame = requestAnimationFrame(() => this.render());
    }
  }

  render() {
    cancelAnimationFrame(this.frame);
    this.frame = 0;
    const view = this.window();
    const y = this.scroller.scrollTop + view.offset + this.headerHeight;
    this.layer.style.transform = `translateY(${y}px)`;
    this.onRender?.(view);
  }

  destroy() {
    cancelAnimationFrame(this.frame);
    this.scroller.removeEventListener('scroll', this.onScroll);
    this.scroller.removeEventListener('wheel', this.onWheel);
    this.scroller.removeEventListener('keydown', this.onKey);
  }
}
