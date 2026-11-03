// Copyright (C) 2026 David L F Gaden
// Editor DOM: a transparent textarea layered exactly over a highlighted layer,
// with a line-number gutter. Only the visible lines (plus a margin) are rendered.

import {h, mount} from '../lib/dom.mjs';
import {renderLine, lineOfOffset} from './highlight.mjs';

const MARGIN_LINES = 30;

export class EditorView {
  constructor(container) {
    this.textarea = h('textarea', {
      class: 'sx-ed-input',
      spellcheck: 'false',
      autocapitalize: 'off',
      autocomplete: 'off',
      autocorrect: 'off',
      wrap: 'off',
      'aria-label': 'JSON editor',
      'aria-multiline': 'true',
      'aria-autocomplete': 'list',
    });
    this.lines = h('div', {class: 'sx-ed-lines'});
    this.currentLine = h('div', {class: 'sx-ed-current-line'});
    this.probe = h('span', {class: 'sx-ed-probe'}, 'x'.repeat(100));
    this.layer = h('div', {class: 'sx-ed-layer', 'aria-hidden': 'true'}, this.lines, this.probe);
    this.previewSpacer = h('div', {class: 'sx-ed-preview-spacer'});
    this.previewScroller = h('div', {class: 'sx-ed-preview-scroll', hidden: true, 'aria-hidden': 'true'},
      this.previewSpacer);
    this.main = h('div', {class: 'sx-ed-main'}, this.currentLine, this.layer, this.textarea, this.previewScroller);
    this.gutterLines = h('div', {class: 'sx-ed-gutter-lines'});
    this.gutter = h('div', {class: 'sx-ed-gutter', 'aria-hidden': 'true'}, this.gutterLines);
    this.root = h('div', {class: 'sx-editor'}, this.gutter, this.main);
    container.append(this.root);
    this.metrics = null;
    this.digits = 0;
    this.previewState = null;
  }

  get scrollSurface() {
    return this.previewState ? this.previewScroller : this.textarea;
  }

  /** Give ghost text its own bounded viewport without modifying the authored textarea. */
  beginPreview(model, requestRender) {
    const input = this.textarea;
    let columns = 0;
    for (let line = 0; line < model.lineStarts.length; line += 1) {
      const end = model.lineStarts[line + 1] ?? model.text.length;
      columns = Math.max(columns, end - model.lineStarts[line]);
    }
    const onWheel = (event) => {
      this.previewScroller.scrollTop += event.deltaY;
      event.preventDefault();
      event.stopImmediatePropagation();
    };
    this.previewState = {lines: model.lineStarts.length, columns, requestRender, onWheel,
      top: input.scrollTop, left: input.scrollLeft,
      start: input.selectionStart, end: input.selectionEnd, direction: input.selectionDirection};
    this.previewScroller.hidden = false;
    this.sizePreview();
    this.previewScroller.scrollTop = input.scrollTop;
    this.previewScroller.scrollLeft = input.scrollLeft;
    this.previewScroller.addEventListener('scroll', requestRender);
    this.gutter.addEventListener('wheel', onWheel, {capture: true, passive: false});
  }

  sizePreview() {
    if (!this.previewState) return;
    const {lineHeight, charWidth, padTop, padLeft} = this.metrics || this.measure();
    this.previewSpacer.style.height = `${this.previewState.lines * lineHeight + padTop * 2}px`;
    this.previewSpacer.style.width = `${this.previewState.columns * charWidth + padLeft * 2}px`;
  }

  endPreview(restore = true) {
    const saved = this.previewState;
    if (!saved) return;
    this.previewScroller.removeEventListener('scroll', saved.requestRender);
    this.gutter.removeEventListener('wheel', saved.onWheel, true);
    this.previewState = null;
    this.previewScroller.hidden = true;
    if (restore) {
      this.textarea.setSelectionRange(saved.start, saved.end, saved.direction);
      this.textarea.scrollTop = saved.top;
      this.textarea.scrollLeft = saved.left;
    }
  }

  /** Font metrics shared by the textarea and the highlight layer. */
  measure() {
    const style = getComputedStyle(this.textarea);
    const lineHeight = parseFloat(style.lineHeight) || 20;
    const charWidth = this.probe.getBoundingClientRect().width / 100 || 8;
    this.metrics = {
      lineHeight,
      charWidth,
      padTop: parseFloat(style.paddingTop) || 0,
      padLeft: parseFloat(style.paddingLeft) || 0,
    };
    return this.metrics;
  }

  /** Coordinates of an offset relative to the editor root: {x, y, lineHeight}. */
  coordsAt(lineStarts, offset) {
    const metrics = this.metrics || this.measure();
    const line = lineOfOffset(lineStarts, offset);
    const column = offset - lineStarts[line];
    const mainLeft = this.main.offsetLeft;
    return {
      x: mainLeft + metrics.padLeft + column * metrics.charWidth - this.scrollSurface.scrollLeft,
      y: metrics.padTop + line * metrics.lineHeight - this.scrollSurface.scrollTop,
      lineHeight: metrics.lineHeight,
    };
  }

  /** Document position under a client point: {line, column}. */
  positionAt(clientX, clientY) {
    const metrics = this.metrics || this.measure();
    const surface = this.scrollSurface;
    const rect = surface.getBoundingClientRect();
    const y = clientY - rect.top + surface.scrollTop - metrics.padTop;
    const x = clientX - rect.left + surface.scrollLeft - metrics.padLeft;
    return {line: Math.floor(y / metrics.lineHeight), column: Math.floor(x / metrics.charWidth)};
  }

  /** Scroll so a line/column is visible. */
  scrollIntoView(line, column, center = false) {
    const metrics = this.metrics || this.measure();
    const textarea = this.scrollSurface;
    const top = metrics.padTop + line * metrics.lineHeight;
    const viewHeight = textarea.clientHeight;
    if (center || top < textarea.scrollTop || top + metrics.lineHeight > textarea.scrollTop + viewHeight) {
      textarea.scrollTop = Math.max(0, top - (center ? viewHeight / 3 : viewHeight / 2));
    }
    const left = metrics.padLeft + column * metrics.charWidth;
    const viewWidth = textarea.clientWidth;
    const visibleLeft = textarea.scrollLeft + metrics.padLeft;
    const visibleRight = textarea.scrollLeft + viewWidth - metrics.charWidth * 4;
    if (left < visibleLeft || left > visibleRight) {
      textarea.scrollLeft = Math.max(0, left - viewWidth / 2);
    }
  }

  /**
   * Render visible lines. model: {text, lineStarts, decorations, caretLine, marks: Map(line -> {severity, messages}),
   * label(line) -> string, ghostLines: Set}
   */
  render(model) {
    const metrics = this.metrics || this.measure();
    this.sizePreview();
    const textarea = this.scrollSurface;
    const {lineHeight, padTop, padLeft} = metrics;
    const total = model.lineStarts.length;
    const scrollTop = textarea.scrollTop;
    const first = Math.max(0, Math.floor((scrollTop - padTop) / lineHeight) - MARGIN_LINES);
    const visible = Math.ceil(textarea.clientHeight / lineHeight);
    const last = Math.min(total - 1, first + visible + MARGIN_LINES * 2);
    this.layer.style.transform = `translate(${-textarea.scrollLeft}px, ${-scrollTop}px)`;
    this.lines.style.top = `${padTop + first * lineHeight}px`;
    this.lines.style.left = `${padLeft}px`;
    this.lines.style.minWidth = `${Math.max(0, textarea.scrollWidth - padLeft)}px`;
    const rows = [];
    const numbers = [];
    for (let line = first; line <= last; line += 1) {
      const from = model.lineStarts[line];
      const to = line + 1 < total ? model.lineStarts[line + 1] - 1 : model.text.length;
      const ghost = model.ghostLines && model.ghostLines.has(line);
      rows.push(h('div', {class: ['sx-ed-line', ghost && 'sx-ed-ghost-line']},
        renderLine(model.text.slice(from, to), from, model.decorations, model.format)));
      const mark = model.marks && model.marks.get(line);
      numbers.push(h('div', {
        class: ['sx-ed-gutter-line', line === model.caretLine && 'current', ghost && 'ghost'],
        title: mark ? mark.messages.join('\n') : undefined,
      },
      mark ? h('span', {class: ['sx-ed-gutter-mark', `sx-ed-sev-${mark.severity}`]}) : null,
      model.label ? model.label(line) : String(line + 1)));
    }
    mount(this.lines, rows);
    this.gutterLines.style.transform = `translateY(${padTop + first * lineHeight - scrollTop}px)`;
    mount(this.gutterLines, numbers);
    const digits = String(total).length;
    if (digits !== this.digits) {
      this.digits = digits;
      this.gutter.style.setProperty('--sx-ed-digits', String(Math.max(2, digits)));
    }
    const showCurrent = model.caretLine !== null && model.caretLine !== undefined;
    this.currentLine.hidden = !showCurrent;
    if (showCurrent) {
      this.currentLine.style.top = `${padTop + model.caretLine * lineHeight - scrollTop}px`;
    }
  }
}
