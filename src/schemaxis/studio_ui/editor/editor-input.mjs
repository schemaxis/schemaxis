// Keyboard and text-input behaviour of the JSON editor.

import {backspaceEdit, indentEdit, newlineEdit, outdentEdit, typeCharEdit} from './editing.mjs';

const AUTO_TRIGGERS = new Set(['"', ':', ',', '[']);

/** Attach input handling; returns a detach function. */
export function attachInput(core, assist) {
  const textarea = core.textarea;

  const run = (edit) => {
    if (!edit) {
      return false;
    }
    core.applyEdit(edit);
    return true;
  };

  const keydown = (event) => {
    if (event.isComposing) {
      return;
    }
    if (core.fill?.keydown(event) || assist.keydown(event)) {
      event.preventDefault();
      return;
    }
    const ctrl = event.ctrlKey || event.metaKey;
    if (ctrl && (event.key === ' ' || event.code === 'Space')) {
      event.preventDefault();
      assist.open();
      return;
    }
    if (event.key === 'Escape') {
      assist.hideHover();
      return;
    }
    if (core.state.readOnly || ctrl || event.altKey) {
      return;
    }
    const text = textarea.value;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const unit = core.state.options.indent;
    let handled = false;
    if (event.key === 'Enter' && !event.shiftKey) {
      if (core.state.options.format === 'yaml') {
        const before = text.slice(text.lastIndexOf('\n', start-1)+1, start);
        const indent = /^ */.exec(before)[0] + (/[:|-]\s*$/.test(before) ? unit : '');
        const insertion = '\n' + indent;
        handled = run({from: start, to: end, text: insertion, selectFrom: start+insertion.length, selectTo: start+insertion.length});
      } else handled = run(newlineEdit(text, start, end, unit));
    } else if (event.key === 'Tab') {
      if (event.shiftKey) {
        run(outdentEdit(text, start, end, unit));
        handled = true;
      } else {
        handled = run(indentEdit(text, start, end, unit));
      }
    } else if (event.key === 'Backspace') {
      handled = run(backspaceEdit(text, start, end));
    }
    if (handled) {
      event.preventDefault();
    }
  };

  const beforeInput = (event) => {
    if (core.state.readOnly || event.inputType !== 'insertText' || typeof event.data !== 'string') {
      return;
    }
    if (event.data.length !== 1 || core.state.applying) {
      return;
    }
    const char = event.data;
    const edit = typeCharEdit(textarea.value, textarea.selectionStart, textarea.selectionEnd, char);
    if (edit) {
      event.preventDefault();
      queueMicrotask(() => {
        core.applyEdit(edit);
        afterChar(char);
      });
      return;
    }
    setTimeout(() => afterChar(char), 0);
  };

  const afterChar = (char) => {
    if (!assist.isOpen() && core.state.options.suggestions && AUTO_TRIGGERS.has(char)) {
      assist.open();
    }
  };

  textarea.addEventListener('keydown', keydown);
  textarea.addEventListener('beforeinput', beforeInput);
  return () => {
    textarea.removeEventListener('keydown', keydown);
    textarea.removeEventListener('beforeinput', beforeInput);
  };
}
