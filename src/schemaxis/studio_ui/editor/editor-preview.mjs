// Copyright (C) 2026 David L F Gaden
// Ghost previews: render would-be inserted text inline without changing the
// textarea value, then commit it as one normal (undoable) edit.

import {planInsert, planInserts} from './insert.mjs';
import {computeLineStarts, lineOfOffset} from './highlight.mjs';

function countNewlines(text) {
  let count = 0;
  for (let index = text.indexOf('\n'); index !== -1; index = text.indexOf('\n', index + 1)) {
    count += 1;
  }
  return count;
}

export class Preview {
  constructor(core) {
    this.core = core;
    this.current = null;
  }

  active() {
    return this.current !== null;
  }

  /** Display model: the text with the ghost inserted, line labels and an offset map. */
  model(text, lineStarts) {
    const preview = this.current;
    if (!preview) {
      return {text, lineStarts, map: (offset) => offset, ghostLines: null, label: null, ghost: null};
    }
    if (!preview.display) {
      const display = text.slice(0, preview.from) + preview.text + text.slice(preview.to);
      const starts = computeLineStarts(display);
      const first = lineOfOffset(starts, preview.ghosts?.[0]?.from ?? preview.from);
      const ghostLines = new Set();
      for (const range of preview.ghosts || [{from: preview.from, to: preview.from + preview.text.length}]) {
        const start = lineOfOffset(starts, range.from);
        const end = lineOfOffset(starts, range.to);
        for (let line = start; line <= end; line += 1) {
          ghostLines.add(line);
        }
      }
      const added = countNewlines(preview.text) - countNewlines(text.slice(preview.from, preview.to));
      const label = (line) => {
        if (preview.edits) {
          if (ghostLines.has(line)) return '+';
          let offset = starts[line];
          for (const edit of [...preview.edits].reverse()) {
            if (offset >= edit.from + edit.length) offset -= edit.length - (edit.to - edit.from);
            else if (offset >= edit.from) offset = edit.from;
          }
          return String(lineOfOffset(lineStarts, offset) + 1);
        }
        if (line <= first) {
          return String(line + 1);
        }
        return ghostLines.has(line) ? '+' : String(line - added + 1);
      };
      preview.display = {text: display, lineStarts: starts, ghostLines, label, added, firstLine: first};
    }
    const map = (offset) => {
      const edits = preview.edits || [{from: preview.from, to: preview.to, length: preview.text.length}];
      return edits.reduce((position, edit) => position < edit.from ? position
        : position >= edit.to ? position + edit.length - (edit.to - edit.from) : edit.from, offset);
    };
    const ghost = {from: preview.from, to: preview.from + preview.text.length};
    return {...preview.display, map, ghost, ghosts: preview.ghosts};
  }

  /** Show a preview: {at: offset | pointer, text} or {at: pointer, value | values}. */
  show({at, text, value, values, inserts, fields}) {
    const core = this.core;
    this.clear();
    let edit;
    try {
      if (inserts) {
        edit = planInserts(core.ensureAst(), inserts, {indent: core.state.options.indent,
          caret: core.textarea.selectionStart});
      } else if (typeof at === 'number') {
        edit = {from: at, to: at, text: String(text)};
      } else {
        const list = values ?? (value !== undefined ? [value] : [JSON.parse(text)]);
        edit = planInsert(core.ensureAst(), at, list, {indent: core.state.options.indent});
      }
    } catch (error) {
      console.warn('Preview failed', error);
      return null;
    }
    this.current = {...edit, fields, base: core.textarea.value};
    core.view.root.classList.add('sx-ed-previewing');
    const model = this.model(core.textarea.value, core.state.lineStarts);
    core.view.beginPreview(model, core.requestRender);
    core.view.scrollIntoView(model.firstLine, 0, true);
    core.requestRender();
    return {...edit, fields};
  }

  /** Insert the previewed text as a normal edit. Returns false when stale or read-only. */
  commit() {
    const core = this.core;
    const preview = this.current;
    this.clear();
    if (!preview || preview.base !== core.textarea.value || core.state.readOnly) {
      return false;
    }
    core.replaceText(preview.from, preview.to, preview.text);
    const end = preview.ghosts?.[0]?.from ?? preview.from + preview.text.length;
    core.textarea.setSelectionRange(end, end);
    core.afterProgrammaticSelection();
    return true;
  }

  clear() {
    if (!this.current) {
      return;
    }
    const restore = this.current.base === this.core.textarea.value;
    this.current = null;
    this.core.view.root.classList.remove('sx-ed-previewing');
    this.core.view.endPreview(restore);
    this.core.requestRender();
  }
}
