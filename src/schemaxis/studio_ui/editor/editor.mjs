// Copyright (C) 2026 David L F Gaden
// Schemaxis Studio JSON editor: textarea + highlight overlay, schema completion,
// hover documentation, diagnostics and ghost previews. See createJsonEditor().

import {dumpYaml, yamlRender} from './yaml-parse.mjs';
import {formatJson} from './json-format.mjs';
import {debounce} from '../lib/dom.mjs';
import {parse, documentValue} from './json-parse.mjs';
import {pointerAt, rangeOfPointer} from './json-pointer.mjs';
import {validateDocument} from './schema-registry.mjs';
import {planInsert} from './insert.mjs';
import {matchBracket} from './editing.mjs';
import {computeLineStarts, lineOfOffset} from './highlight.mjs';
import {resolveDiagnostics, lineMarks, locationPointer} from './diagnostics.mjs';
import {EditorView} from './view.mjs';
import {Assist} from './editor-assist.mjs';
import {attachInput} from './editor-input.mjs';
import {Preview} from './editor-preview.mjs';
import {DiagnosticSettler} from './settle-state.mjs';
import {duplicateKeyDiagnostics} from './settle.mjs';
import {createFillMode} from './fill.mjs';

const ANALYSIS_DELAY = 150;
const LARGE_ANALYSIS_DELAY = 600;
const LARGE_TEXT = 256 * 1024;

/**
 * Create a JSON editor inside `container`.
 * Options: {value, schema, registry, suggestions = true, readOnly, changeDelay = 150, indent = '  '}
 */
export function createJsonEditor(container, options = {}) {
  const view = new EditorView(container);
  const textarea = view.textarea;
  const state = {
    options: {suggestions: true, changeDelay: 150, indent: '  ', ...options},
    registry: options.registry || null,
    schema: options.schema || null,
    readOnly: false,
    ast: null,
    astText: null,
    lineStarts: [0],
    lastText: '',
    diagnostics: [],
    external: [],
    applying: false,
    frame: 0,
  };
  const changeListeners = new Set();
  const diagnosticListeners = new Set();
  let unsubscribeRegistry = null;

  const ensureAst = () => {
    const text = textarea.value;
    if (state.astText !== text) {
      state.ast = parse(text, state.options.format || 'json');
      state.astText = text;
    }
    return state.ast;
  };

  const hasSchema = () => Boolean(state.schema || state.registry);

  const requestRender = () => {
    if (!state.frame) {
      state.frame = requestAnimationFrame(() => {
        state.frame = 0;
        render();
      });
    }
  };

  function render() {
    const model = preview.model(textarea.value, state.lineStarts);
    const decorations = [];
    for (const decoration of core.fill.decorations()) {
      decorations.push({...decoration, from: model.map(decoration.from), to: model.map(decoration.to)});
    }
    for (const diagnostic of state.diagnostics) {
      decorations.push({from: model.map(diagnostic.from), to: model.map(diagnostic.to),
        className: `sx-diag sx-diag-${diagnostic.severity}`});
    }
    const caret = textarea.selectionStart;
    if (!model.ghost && document.activeElement === textarea && caret === textarea.selectionEnd) {
      const pair = matchBracket(textarea.value, caret, 100000);
      if (pair) {
        decorations.push({from: pair.open, to: pair.open + 1, className: 'sx-bracket'});
        decorations.push({from: pair.close, to: pair.close + 1, className: 'sx-bracket'});
      }
    }
    if (model.ghost) {
      for (const ghost of model.ghosts || [model.ghost]) decorations.push({...ghost, className: 'sx-ghost'});
    }
    view.render({
      format: state.options.format || 'json',
      text: model.text,
      lineStarts: model.lineStarts,
      decorations,
      caretLine: model.ghost ? null : lineOfOffset(model.lineStarts, caret),
      marks: lineMarks(state.diagnostics, model.lineStarts, model.map),
      label: model.label,
      ghostLines: model.ghostLines,
    });
  }

  const analyse = () => {
    analyseSoon.cancel();
    analyseLater.cancel();
    const ast = ensureAst();
    const syntax = resolveDiagnostics(ast, [...ast.diagnostics, ...duplicateKeyDiagnostics(ast)], 'syntax');
    let schemaProblems = [];
    if (!syntax.length && ast.root && hasSchema()) {
      try {
        const found = validateDocument(state.registry, documentValue(ast), state.schema);
        schemaProblems = resolveDiagnostics(ast, found, 'schema');
      } catch (error) {
        console.warn('Schema validation failed', error);
      }
    }
    const external = resolveDiagnostics(ast, state.external, 'external');
    settling.analyse(ast, [...syntax, ...schemaProblems, ...external]);
  };
  const settling = new DiagnosticSettler({caret: () => textarea.selectionStart, publish: (diagnostics) => {
    state.diagnostics = diagnostics;
    diagnosticListeners.forEach((listener) => listener(diagnostics.slice()));
    requestRender();
  }});
  const analyseSoon = debounce(analyse, ANALYSIS_DELAY);
  const analyseLater = debounce(analyse, LARGE_ANALYSIS_DELAY);
  const scheduleAnalysis = () => (textarea.value.length > LARGE_TEXT ? analyseLater() : analyseSoon());

  let notifyChange = null;
  const makeNotifier = () => {
    const emit = () => {
      const value = textarea.value;
      changeListeners.forEach((listener) => listener(value));
    };
    notifyChange = state.options.changeDelay > 0 ? debounce(emit, state.options.changeDelay) : emit;
  };
  makeNotifier();

  const ensureCaretVisible = () => {
    const offset = textarea.selectionEnd;
    const line = lineOfOffset(state.lineStarts, offset);
    view.scrollIntoView(line, offset - state.lineStarts[line]);
  };

  const handleInput = () => {
    const text = textarea.value;
    state.external = [];
    settling.changed();
    state.lastText = text;
    state.lineStarts = computeLineStarts(text);
    preview.clear();
    core.fill.refresh();
    scheduleAnalysis();
    notifyChange();
    assist.refresh();
    requestRender();
  };

  /** Replace a range through the browser's editing commands so native undo/redo records it. */
  const replaceText = (from, to, text) => {
    if (from === to && text === '') {
      return;
    }
    state.applying = true;
    textarea.focus({preventScroll: true});
    textarea.setSelectionRange(from, to);
    let done = false;
    try {
      done = text === '' ? document.execCommand('delete') : document.execCommand('insertText', false, text);
    } catch {
      done = false;
    }
    if (!done) {
      textarea.setRangeText(text, from, to, 'end');
      textarea.dispatchEvent(new Event('input', {bubbles: true}));
    }
    state.applying = false;
  };

  const afterProgrammaticSelection = () => {
    ensureCaretVisible();
    requestRender();
  };

  const applyEdit = (edit) => {
    replaceText(edit.from, edit.to, edit.text);
    textarea.setSelectionRange(edit.selectFrom, edit.selectTo);
    afterProgrammaticSelection();
  };

  const offsetAtPoint = (clientX, clientY) => {
    const {line, column} = view.positionAt(clientX, clientY);
    const starts = state.lineStarts;
    if (line < 0 || line >= starts.length || column < 0) {
      return -1;
    }
    const end = line + 1 < starts.length ? starts[line + 1] - 1 : textarea.value.length;
    return starts[line] + column < end ? starts[line] + column : -1;
  };

  const core = {
    view, textarea, state, ensureAst, hasSchema, replaceText, applyEdit, offsetAtPoint, requestRender,
    afterProgrammaticSelection,
    anchorAt: (offset) => view.coordsAt(state.lineStarts, offset),
    allDiagnostics: () => state.diagnostics,
    previewing: () => preview.active(),
  };
  const preview = new Preview(core);
  const assist = new Assist(core);
  core.fill = createFillMode(core, {getFunctions: options.getFunctions, ...options.fill});
  const detachInput = attachInput(core, assist);

  const listeners = [
    [textarea, 'input', handleInput],
    [textarea, 'scroll', () => {
      requestRender();
      assist.reposition();
      assist.hideHover();
    }],
    [textarea, 'mousemove', (event) => assist.mouseMove(event)],
    [textarea, 'mouseleave', () => assist.hideHover()],
    [textarea, 'blur', () => {
      assist.close();
      analyse();
      settling.refresh({blurred: true});
      requestRender();
    }],
    [textarea, 'focus', () => settling.refresh({blurred: false})],
    [view.gutter, 'wheel', (event) => {
      textarea.scrollTop += event.deltaY;
      event.preventDefault();
    }, {passive: false}],
    [document, 'selectionchange', () => {
      if (document.activeElement === textarea) {
        settling.refresh();
        requestRender();
        if (assist.isOpen() && textarea.selectionStart < assist.anchorFrom) {
          assist.close();
        }
      }
    }],
  ];
  for (const [target, type, handler, flags] of listeners) {
    target.addEventListener(type, handler, flags);
  }
  const resizeObserver = typeof ResizeObserver === 'function' ? new ResizeObserver(requestRender) : null;
  resizeObserver?.observe(view.root);
  document.fonts?.ready.then(() => {
    view.measure();
    requestRender();
  });

  const api = {
    element: view.root,
    textarea,

    undo() { if (state.readOnly) return false; textarea.focus(); return document.execCommand('undo'); },
    redo() { if (state.readOnly) return false; textarea.focus(); return document.execCommand('redo'); },
    getValue: () => textarea.value,
    getDocument: () => {
      const ast = ensureAst();
      if (ast.diagnostics.length) throw Error('Repair source syntax before structured editing');
      return structuredClone(documentValue(ast));
    },
    convertFormat(format) {
      const ast = ensureAst();
      if (ast.diagnostics.length || state.readOnly) return false;
      const value = documentValue(ast);
      const source = format === 'yaml' ? dumpYaml(value) : formatJson(value, {indent: state.options.indent});
      api.setFormat(format);
      api.setValue(source, {preserveUndo: true});
      return true;
    },
    setFormat(format) {
      if (!["json", "yaml"].includes(format)) throw Error("Choose json or yaml");
      state.options.format = format; state.astText = null;
      textarea.setAttribute("aria-label", "Source " + format.toUpperCase());
      analyse();
    },

    /** Replace the text. {preserveUndo: true} records it as an undoable edit. */
    setValue(text, {preserveUndo = false} = {}) {
      const value = String(text ?? '');
      if (preserveUndo && !state.readOnly) {
        replaceText(0, textarea.value.length, value);
      } else {
        textarea.value = value;
        state.lastText = value;
        state.diagnostics = [];
        handleInput();
      }
      analyse();
      if (!preserveUndo) settling.refresh({explicit: true});
    },

    onChange(listener) {
      changeListeners.add(listener);
      return () => changeListeners.delete(listener);
    },

    onDiagnostics(listener) {
      diagnosticListeners.add(listener);
      return () => diagnosticListeners.delete(listener);
    },

    focus: () => textarea.focus(),

    revealOffset(from, to = from) {
      const length = textarea.value.length;
      const start = Math.max(0, Math.min(from, length));
      const end = Math.max(start, Math.min(to, length));
      textarea.focus({preventScroll: true});
      textarea.setSelectionRange(start, end);
      const line = lineOfOffset(state.lineStarts, start);
      view.scrollIntoView(line, start - state.lineStarts[line], true);
      requestRender();
      return true;
    },

    revealPointer(pointer) {
      const ast = ensureAst();
      const range = rangeOfPointer(ast, locationPointer(pointer, documentValue(ast)));
      return range ? api.revealOffset(range.from, range.to) : false;
    },

    getCursor() {
      const offset = textarea.selectionStart;
      const line = lineOfOffset(state.lineStarts, offset);
      const caret = pointerAt(ensureAst(), offset);
      return {
        offset,
        line: line + 1,
        column: offset - state.lineStarts[line] + 1,
        selectionStart: textarea.selectionStart,
        selectionEnd: textarea.selectionEnd,
        pointer: caret.pointer ?? caret.parentPointer ?? '',
        position: caret.position,
      };
    },

    setReadOnly(readOnly) {
      state.readOnly = Boolean(readOnly);
      textarea.readOnly = state.readOnly;
      view.root.classList.toggle('sx-ed-readonly', state.readOnly);
      if (state.readOnly) {
        assist.close();
      }
    },

    setSchemaRegistry(registry) {
      unsubscribeRegistry?.();
      state.registry = registry || null;
      unsubscribeRegistry = registry ? registry.onLoad(() => {
        scheduleAnalysis();
        assist.refresh();
      }) : null;
      scheduleAnalysis();
    },

    setSchema(schema) {
      state.schema = schema || null;
      scheduleAnalysis();
    },

    setOption(name, value) {
      state.options[name] = value;
      if (name === 'suggestions' && !value) {
        assist.close();
      }
      if (name === 'changeDelay') {
        notifyChange.cancel?.();
        makeNotifier();
      }
    },

    getOption: (name) => state.options[name],

    /** External diagnostics, e.g. server faults: [{pointer? | from, to, message, severity}]. */
    setDiagnostics(diagnostics, {version = settling.version, explicit = true} = {}) {
      if (version !== settling.version) return false;
      state.external = Array.isArray(diagnostics) ? diagnostics.slice() : [];
      analyse();
      settling.refresh({explicit});
      return true;
    },

    getTextVersion: () => settling.version,
    /** One undoable document edit, preserving the selected source format. */
    replaceDocument(value) {
      if (state.readOnly) throw Error('This editor is read-only.');
      const ast = ensureAst();
      replaceText(0, textarea.value.length, ast.format === 'yaml'
        ? yamlRender(ast, value, state.options.indent) : JSON.stringify(value, null, state.options.indent));
    },
    getSettledState: () => settling.snapshot(),
    onSettledState: (listener) => settling.subscribe(listener),
    flushDiagnostics() {
      analyse();
      return settling.refresh({explicit: true});
    },

    getDiagnostics: () => state.diagnostics.slice(),

    startFill: (request) => core.fill.start(request),
    stopFill: () => core.fill.stop(),
    fillRequired: (pointer, request) => core.fill.fillRequired(pointer, request),
    offerFollowup: (pointer, common) => core.fill.offerFollowup(pointer, common),

    triggerCompletion: () => assist.open(),

    /** Pretty-print when the text is valid JSON (undoable). Returns false otherwise. */
    format(options = {}) {
      const ast = ensureAst();
      if (!ast.root || ast.diagnostics.length || state.readOnly) {
        return false;
      }
      const formatted = ast.format === "yaml" ? ast.yamlDocument.toString({indent: state.options.indent.length})
        : formatJson(documentValue(ast), {...options, indent: state.options.indent});
      if (formatted === textarea.value) {
        return true;
      }
      const caret = pointerAt(ast, textarea.selectionStart);
      replaceText(0, textarea.value.length, formatted);
      const pointer = caret.pointer ?? caret.parentPointer;
      const range = pointer ? rangeOfPointer(ensureAst(), pointer) : null;
      api.revealOffset(range ? range.from : 0);
      return true;
    },

    preview: (request) => preview.show(request),
    commitPreview: () => preview.commit(),
    clearPreview: () => preview.clear(),

    /** Insert or set a JSON value at an RFC 6901 pointer ('/nodes/-' appends). {multiple: true} inserts a list. */
    insertAtPointer(pointer, jsonValue, {multiple = false, select = true} = {}) {
      if (state.readOnly) {
        return null;
      }
      const values = multiple ? jsonValue : [jsonValue];
      const edit = planInsert(ensureAst(), pointer, values, {indent: state.options.indent});
      replaceText(edit.from, edit.to, edit.text);
      const from = edit.from + (select ? edit.select.from : edit.text.length);
      const to = edit.from + (select ? edit.select.to : edit.text.length);
      textarea.setSelectionRange(from, to);
      afterProgrammaticSelection();
      return {from, to};
    },

    destroy() {
      settling.destroy();
      analyseSoon.cancel();
      analyseLater.cancel();
      notifyChange.cancel?.();
      cancelAnimationFrame(state.frame);
      assist.destroy();
      core.fill.destroy();
      detachInput();
      unsubscribeRegistry?.();
      resizeObserver?.disconnect();
      for (const [target, type, handler, flags] of listeners) {
        target.removeEventListener(type, handler, flags);
      }
      view.root.remove();
      changeListeners.clear();
      diagnosticListeners.clear();
    },
  };

  if (options.registry) {
    api.setSchemaRegistry(options.registry);
  }
  if (options.readOnly) {
    api.setReadOnly(true);
  }
  textarea.value = String(options.value ?? '');
  state.lastText = textarea.value;
  state.lineStarts = computeLineStarts(textarea.value);
  core.fill.refresh();
  view.measure();
  analyse();
  render();
  return api;
}
