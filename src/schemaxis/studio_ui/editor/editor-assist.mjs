// Completion popup and hover documentation controller for the JSON editor.

import {CompletionPopup, HoverTooltip, hoverContent} from './popup.mjs';
import {completionsFor, hoverFor} from './schema-registry.mjs';
import {diagnosticsAt} from './diagnostics.mjs';
import {pointerAt} from './json-pointer.mjs';
import {findFills} from './fill-data.mjs';

const HOVER_DELAY = 400;

export class Assist {
  constructor(core) {
    this.core = core;
    this.popup = new CompletionPopup(core.view.root, {onAccept: (item) => this.accept(item)});
    this.tooltip = new HoverTooltip(core.view.root);
    this.anchorFrom = 0;
    this.hoverTimer = null;
    this.hoverOffset = -1;
  }

  isOpen() {
    return this.popup.isOpen();
  }

  /** Compute and show completions at the caret. Returns true when items are shown. */
  open() {
    const core = this.core;
    const textarea = core.textarea;
    const offset = textarea.selectionStart;
    if (!core.hasSchema() || textarea.selectionEnd !== offset || core.previewing()) {
      this.close();
      return false;
    }
    let items = [];
    try {
      items = completionsFor(core.state.registry, core.ensureAst(), offset, core.state.schema);
    } catch (error) {
      console.warn('Completion failed', error);
    }
    if (!items.length) {
      this.close();
      return false;
    }
    if (core.fill && items.some((item) => item.kind === 'property' && item.required)) {
      items.push({label: 'Fill required properties', kind: 'action', detail: 'guided filling',
        documentation: 'Add every missing required property as a durable field marker.',
        range: items[0].range, action: 'fillRequired'});
    }
    this.anchorFrom = items[0].range.from;
    this.popup.show(items, core.anchorAt(this.anchorFrom));
    textarea.setAttribute('aria-expanded', 'true');
    return true;
  }

  close() {
    if (this.popup.isOpen()) {
      this.popup.hide();
      this.core.textarea.setAttribute('aria-expanded', 'false');
    }
  }

  /** After an edit or caret move: refilter, or close when the caret left the completion range. */
  refresh() {
    if (!this.isOpen()) {
      return;
    }
    const caret = this.core.textarea.selectionStart;
    if (caret < this.anchorFrom) {
      this.close();
      return;
    }
    this.open();
  }

  accept(item) {
    const core = this.core;
    const textarea = core.textarea;
    if (!item) {
      return;
    }
    const caret = textarea.selectionStart;
    const context = pointerAt(core.ensureAst(), caret);
    if (item.action === 'fillRequired') {
      this.close();
      core.fill?.fillRequired(context.parentPointer || '');
      return;
    }
    const from = item.range.from;
    const to = Math.max(item.range.to, caret);
    this.close();
    core.replaceText(from, to, item.insertText);
    const cursor = item.cursor || {from: item.insertText.length, to: item.insertText.length};
    textarea.setSelectionRange(from + cursor.from, from + cursor.to);
    core.afterProgrammaticSelection();
    if (item.insertText.includes('\"$fill\"') && core.fill) {
      const pointers = findFills(core.ensureAst()).filter((marker) => marker.from >= from
        && marker.to <= from + item.insertText.length).map((marker) => marker.pointer);
      core.fill.start({pointers});
    } else if (item.kind === 'value' && ['filter', 'type', 'operation'].includes(item.detail)) {
      const target = `${context.parentPointer || ''}/options`;
      core.fill?.offerFollowup(target);
    }
    const valueFollows = item.kind === 'property' && /: ""/.test(item.insertText);
    if (valueFollows && core.state.options.suggestions) {
      setTimeout(() => this.open(), 0);
    }
  }

  /** Keyboard handling while the popup is open. Returns true when the key was consumed. */
  keydown(event) {
    if (!this.isOpen() || event.altKey || event.ctrlKey || event.metaKey) {
      return false;
    }
    switch (event.key) {
      case 'ArrowDown':
        this.popup.move(1);
        return true;
      case 'ArrowUp':
        this.popup.move(-1);
        return true;
      case 'PageDown':
        this.popup.move(8);
        return true;
      case 'PageUp':
        this.popup.move(-8);
        return true;
      case 'Enter':
      case 'Tab':
        if (event.shiftKey) {
          return false;
        }
        this.accept(this.popup.selected());
        return true;
      case 'Escape':
        this.close();
        return true;
      default:
        return false;
    }
  }

  reposition() {
    if (this.isOpen()) {
      const anchor = this.core.anchorAt(this.anchorFrom);
      const main = this.core.view.main;
      if (anchor.y < -anchor.lineHeight || anchor.y > main.clientHeight) {
        this.close();
        return;
      }
      this.popup.element.style.left = `${Math.round(Math.max(0, anchor.x))}px`;
      this.popup.element.style.top = `${Math.round(anchor.y + anchor.lineHeight)}px`;
    }
  }

  mouseMove(event) {
    const core = this.core;
    if (event.buttons || this.isOpen() || core.previewing() || core.state.options.hover === false) {
      this.hideHover();
      return;
    }
    const offset = core.offsetAtPoint(event.clientX, event.clientY);
    if (offset === this.hoverOffset) {
      return;
    }
    this.hideHover();
    this.hoverOffset = offset;
    if (offset < 0) {
      return;
    }
    this.hoverTimer = setTimeout(() => this.showHover(offset), HOVER_DELAY);
  }

  showHover(offset) {
    const core = this.core;
    const diagnostics = diagnosticsAt(core.allDiagnostics(), offset);
    let info = null;
    if (core.hasSchema()) {
      try {
        info = hoverFor(core.state.registry, core.ensureAst(), offset, core.state.schema);
      } catch (error) {
        console.warn('Hover failed', error);
      }
    }
    if (!diagnostics.length && !info) {
      return;
    }
    const start = info && info.range ? Math.min(info.range.from, offset) : offset;
    const anchorOffset = diagnostics.length ? Math.min(diagnostics[0].from, offset) : start;
    this.tooltip.show(hoverContent(diagnostics, info), core.anchorAt(anchorOffset));
  }

  hideHover() {
    clearTimeout(this.hoverTimer);
    this.hoverOffset = -1;
    this.tooltip.hide();
  }

  destroy() {
    clearTimeout(this.hoverTimer);
  }
}
