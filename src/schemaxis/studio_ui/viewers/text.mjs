// Text Viewer: virtualised display of large text (only visible lines are in
// the DOM), line numbers, find (plain / regex / case) with all matches
// highlighted, text selection picks, and grep extraction to a table.
//
//   const viewer = createTextViewer(container);
//   viewer.load(text | {text | blob, name?, revision?} | Promise);
//
// Pick payloads (lines are 1-based as displayed; from/to are UTF-16 offsets, `to` exclusive):
//   {type: 'text', from, to, lineFrom, lineTo, text, textTruncated?, name?, revision?}
//   {type: 'match', pattern, regex, caseSensitive, line, from, to, text, groups, name?, revision?}
// Events: pick, extract (table), openTable (table), search ({count, truncated}), load, error.

import {debounce, h} from '../lib/dom.mjs';
import {createEmitter, createFrame, separator, setPressed, spacer, toolButton} from './common.mjs';
import {buildSearch, createTextDocument, extractTable, findAll} from './text-model.mjs';
import {createExtractPanel, createFindBar} from './text-panels.mjs';
import {createTextRows} from './text-rows.mjs';

const MAX_PICK_TEXT = 100_000;

export function createTextViewer(container, options = {}) {
  const events = createEmitter();
  const frame = createFrame(container, {kind: 'text', label: options.label || 'Text Viewer',
    emptyMessage: options.emptyMessage || 'No text loaded'});
  const statusLeft = h('span', {class: 'vw-status-main'}, '');
  const statusRight = h('span', {class: 'vw-status-meta'});
  frame.status.append(statusLeft, statusRight);

  let doc = null;
  let meta = {};
  let search = null;
  let matches = {starts: [], ends: [], truncated: false};
  let current = -1;
  let searchJob = null;
  let extractJob = null;
  let lastTable = null;
  let loadToken = 0;

  const rows = createTextRows(frame.body, {
    onLineClick: (line, extend) => selectLines(extend ? rows.anchor() : line, line, extend),
    onSelection: (range) => emitTextPick(range.from, range.to),
  });

  const findBar = createFindBar({
    search: () => scheduleSearch(),
    next: () => step(1),
    previous: () => step(-1),
    close: () => toggleFind(false),
    reference: () => referenceMatch(),
  });
  const extractPanel = createExtractPanel({
    run: (spec) => runExtract(spec),
    cancel: () => extractJob?.abort(),
    openTable: () => lastTable && events.emit('openTable', lastTable),
  });
  findBar.element.hidden = options.find === false;
  extractPanel.element.hidden = true;
  frame.root.querySelector('.vw-stage').before(findBar.element, extractPanel.element);

  const findToggle = toolButton({icon: 'search', text: 'Find', title: 'Find (Ctrl+F)', pressed: !findBar.element.hidden,
    onClick: () => toggleFind(findBar.element.hidden)});
  const extractToggle = toolButton({icon: 'extract', text: 'Grep extract', title: 'Extract a table with a regex',
    pressed: false, onClick: () => toggleExtract(extractPanel.element.hidden)});
  const gotoInput = h('input', {class: 'vw-input vw-mono vw-goto', inputmode: 'numeric', placeholder: 'Line',
    'aria-label': 'Go to line', title: 'Go to line (Ctrl+G)'});
  gotoInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      const line = Number.parseInt(gotoInput.value, 10);
      if (Number.isInteger(line)) {
        scrollToLine(line);
        rows.focus();
      }
    }
  });
  frame.toolbar.append(findToggle, extractToggle, separator(), gotoInput, spacer());

  frame.root.addEventListener('keydown', (event) => {
    const mod = event.ctrlKey || event.metaKey;
    if (mod && event.key.toLowerCase() === 'f') {
      event.preventDefault();
      toggleFind(true);
    } else if (mod && event.key.toLowerCase() === 'g') {
      event.preventDefault();
      gotoInput.focus();
      gotoInput.select();
    } else if (event.key === 'F3') {
      event.preventDefault();
      step(event.shiftKey ? -1 : 1);
    }
  });

  function toggleFind(open) {
    findBar.element.hidden = !open;
    setPressed(findToggle, open);
    if (open) {
      findBar.focus();
    } else {
      rows.focus();
    }
    rows.resize();
  }

  function toggleExtract(open) {
    extractPanel.element.hidden = !open;
    setPressed(extractToggle, open);
    if (open) {
      extractPanel.focus();
    }
    rows.resize();
  }

  // ---- search --------------------------------------------------------------

  const scheduleSearch = debounce(() => runSearch(findBar.state()), 150);

  async function runSearch(state) {
    searchJob?.abort();
    searchJob = null;
    current = -1;
    matches = {starts: [], ends: [], truncated: false};
    findBar.setReferenceEnabled(false);
    try {
      search = doc ? buildSearch(state.pattern, state) : null;
    } catch (error) {
      search = null;
      rows.setMatches(matches, current);
      findBar.setStatus(error.message, 'error');
      return 0;
    }
    rows.setMatches(matches, current);
    if (!search) {
      findBar.setStatus('');
      return 0;
    }
    const job = new AbortController();
    searchJob = job;
    findBar.setStatus('Searching…');
    try {
      matches = await findAll(doc.text, search, {signal: job.signal, onProgress: (fraction, count) => {
        findBar.setProgress(fraction);
        findBar.setStatus(`${count.toLocaleString('en-CA')}…`);
      }});
    } catch (error) {
      if (error.name !== 'AbortError') {
        findBar.setStatus(error.message, 'error');
      }
      return 0;
    } finally {
      if (searchJob === job) {
        findBar.setProgress(null);
      }
    }
    if (searchJob !== job) {
      return 0;
    }
    searchJob = null;
    const top = doc.lineStart(Math.floor(rows.topLine()));
    current = matches.starts.length ? Math.max(0, matches.starts.findIndex((start) => start >= top)) : -1;
    showCurrent(false);
    events.emit('search', {count: matches.starts.length, truncated: matches.truncated});
    return matches.starts.length;
  }

  function showCurrent(reveal = true) {
    const count = matches.starts.length;
    rows.setMatches(matches, current);
    findBar.setReferenceEnabled(count > 0);
    if (!count) {
      findBar.setStatus(search ? 'No results' : '', search ? 'warn' : '');
      return;
    }
    const suffix = matches.truncated ? '+' : '';
    findBar.setStatus(`${(current + 1).toLocaleString('en-CA')} / ${count.toLocaleString('en-CA')}${suffix}`);
    if (reveal) {
      rows.reveal(doc.lineOf(matches.starts[current]), matches.starts[current], matches.ends[current]);
    }
  }

  function step(direction) {
    const count = matches.starts.length;
    if (!count) {
      return;
    }
    current = current < 0 ? 0 : (current + direction + count) % count;
    showCurrent(true);
  }

  function referenceMatch() {
    if (current < 0 || !search) {
      return;
    }
    const from = matches.starts[current];
    const sticky = new RegExp(search.source, `${search.flags.replace('g', '')}y`);
    sticky.lastIndex = from;
    const match = sticky.exec(doc.text);
    const state = findBar.state();
    const groups = match?.groups ? {...match.groups} : (match ? match.slice(1) : []);
    events.emit('pick', {type: 'match', pattern: state.pattern, regex: state.regex,
      caseSensitive: state.caseSensitive, line: doc.lineOf(from) + 1, from, to: matches.ends[current],
      text: doc.text.slice(from, matches.ends[current]), groups, ...meta});
  }

  // ---- picks -----------------------------------------------------------------

  function emitTextPick(from, to) {
    if (!doc || to <= from) {
      return;
    }
    const text = doc.text.slice(from, Math.min(to, from + MAX_PICK_TEXT));
    const payload = {type: 'text', from, to, lineFrom: doc.lineOf(from) + 1, lineTo: doc.lineOf(Math.max(from, to - 1)) + 1,
      text, ...meta};
    if (to - from > MAX_PICK_TEXT) {
      payload.textTruncated = true;
    }
    statusLeft.textContent = payload.lineFrom === payload.lineTo ? `Line ${payload.lineFrom} · ${to - from} chars`
      : `Lines ${payload.lineFrom}–${payload.lineTo} · ${(to - from).toLocaleString('en-CA')} chars`;
    events.emit('pick', payload);
  }

  /** Select whole lines (1-based, inclusive) and emit a text pick. */
  function selectLines(fromLine, toLine, extend = false) {
    if (!doc) {
      return;
    }
    const a = Math.max(1, Math.min(fromLine, toLine));
    const b = Math.min(doc.lineCount, Math.max(fromLine, toLine));
    rows.setLineSelection(a - 1, b - 1, extend ? undefined : a - 1);
    emitTextPick(doc.lineStart(a - 1), doc.lineEnd(b - 1));
  }

  // ---- grep extract ----------------------------------------------------------

  async function runExtract(spec) {
    if (!doc) {
      return null;
    }
    extractJob?.abort();
    const job = new AbortController();
    extractJob = job;
    extractPanel.setRunning(true);
    try {
      const table = await extractTable(doc, spec, {signal: job.signal,
        onProgress: (fraction, count) => extractPanel.setProgress(fraction, count)});
      table.source = {...table.source, ...meta};
      lastTable = table;
      extractPanel.setResult(table);
      events.emit('extract', table);
      return table;
    } catch (error) {
      extractPanel.setError(error.name === 'AbortError' ? 'Extraction cancelled.' : error.message);
      return null;
    } finally {
      if (extractJob === job) {
        extractJob = null;
        extractPanel.setRunning(false);
      }
    }
  }

  // ---- public API --------------------------------------------------------------

  function scrollToLine(line) {
    if (doc) {
      rows.scrollToLine(Math.max(0, Math.min(doc.lineCount - 1, line - 1)));
    }
  }

  async function load(input) {
    const token = ++loadToken;
    frame.setState('loading', 'Reading text…');
    let text;
    try {
      const data = await input;
      const descriptor = typeof data === 'string' ? {text: data} : data || {};
      text = typeof descriptor.text === 'string' ? descriptor.text
        : descriptor.blob ? await descriptor.blob.text() : null;
      if (text === null) {
        throw Error('Text data must be a string, {text} or {blob}.');
      }
      meta = {};
      if (descriptor.name) {
        meta.name = descriptor.name;
      }
      if (descriptor.revision !== undefined) {
        meta.revision = descriptor.revision;
      }
    } catch (error) {
      if (token === loadToken) {
        showError(error?.message || String(error));
      }
      return null;
    }
    if (token !== loadToken) {
      return null;
    }
    searchJob?.abort();
    extractJob?.abort();
    doc = createTextDocument(text);
    lastTable = null;
    rows.setDocument(doc);
    frame.setState('ready');
    statusLeft.textContent = '';
    statusRight.textContent = `${doc.lineCount.toLocaleString('en-CA')} lines · `
      + `${(text.length / 1048576).toFixed(text.length < 1048576 ? 2 : 1)} M chars${meta.name ? ` · ${meta.name}` : ''}`;
    if (findBar.state().pattern) {
      scheduleSearch();
    }
    const summary = {lines: doc.lineCount, length: text.length};
    events.emit('load', summary);
    return summary;
  }

  function clear() {
    loadToken++;
    searchJob?.abort();
    extractJob?.abort();
    doc = null;
    matches = {starts: [], ends: [], truncated: false};
    rows.setDocument(null);
    statusLeft.textContent = '';
    statusRight.textContent = '';
    frame.setState('empty');
  }

  function showError(message) {
    frame.setState('error', message);
    events.emit('error', {message});
  }

  return {
    element: frame.root,
    load,
    clear,
    resize: () => rows.resize(),
    destroy() {
      clear();
      rows.destroy();
      scheduleSearch.cancel();
      frame.root.remove();
      events.clear();
    },
    showError,
    setLoading: (message) => frame.setState('loading', message),
    on: events.on,
    /** Search and highlight all matches; resolves to the match count. */
    find(pattern, findOptions = {}) {
      toggleFind(true);
      findBar.set(pattern, findOptions);
      scheduleSearch.cancel();
      return runSearch(findBar.state());
    },
    findNext: () => step(1),
    findPrevious: () => step(-1),
    referenceMatch,
    scrollToLine,
    selectLines: (from, to = from) => selectLines(from, to),
    /** Run grep extraction ({pattern, context?, caseSensitive?, includeLine?}); resolves to the table or null. */
    extract(spec) {
      toggleExtract(true);
      extractPanel.set(spec);
      return runExtract(spec);
    },
    cancelExtract: () => extractJob?.abort(),
    get lineCount() {
      return doc ? doc.lineCount : 0;
    },
    get renderedRows() {
      return rows.renderedCount();
    },
    getText: () => doc?.text ?? '',
    setTheme: () => {},
  };
}
