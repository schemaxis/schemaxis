// Copyright (C) 2026 David L F Gaden
// Timer ownership and text-version tracking, independent of editor DOM rendering.
import {classifyDiagnostics, settledDiagnostics} from './settle.mjs';

export class DiagnosticSettler {
  constructor({caret, publish, now = () => Date.now()}) {
    this.caret = caret;
    this.publish = publish;
    this.now = now;
    this.version = 0;
    this.editedAt = -Infinity;
    this.all = [];
    this.visible = [];
    this.listeners = new Set();
    this.timers = [];
    this.explicit = true;
    this.blurred = false;
    this.parses = false;
  }

  changed() {
    this.cancel();
    this.version += 1;
    this.editedAt = this.now();
    this.explicit = false;
    this.blurred = false;
    this.all = [];
    this.parses = false;
    this.pending = true;
    this.refresh();
    for (const delay of [600, 1500]) this.timers.push(setTimeout(() => this.refresh(), delay));
  }

  analyse(ast, diagnostics) {
    this.pending = false;
    this.parses = Boolean(ast.root) && !ast.diagnostics.length;
    this.all = classifyDiagnostics(ast, diagnostics, this.caret());
    this.refresh();
  }

  refresh({explicit = false, blurred = this.blurred} = {}) {
    this.explicit ||= explicit;
    this.blurred = blurred;
    this.visible = settledDiagnostics(this.all, {caret: this.caret(), idle: this.now() - this.editedAt,
      explicit: this.explicit, blurred});
    this.publish(this.visible.slice());
    const state = this.snapshot();
    this.listeners.forEach((listener) => listener(state));
    return this.visible.slice();
  }

  snapshot() {
    const suppressed = this.all.filter((item) => !this.visible.includes(item));
    return {version: this.version, diagnostics: this.visible.slice(), allDiagnostics: this.all.slice(),
      suppressed, editing: this.pending || suppressed.some((item) => item.settle === 'transient'),
      canValidate: this.parses && !this.all.some((item) => item.source === 'syntax' && item.settle === 'transient')};
  }

  subscribe(listener) {
    this.listeners.add(listener);
    listener(this.snapshot());
    return () => this.listeners.delete(listener);
  }

  cancel() {
    this.timers.forEach(clearTimeout);
    this.timers = [];
  }

  destroy() {
    this.cancel();
    this.listeners.clear();
  }
}
