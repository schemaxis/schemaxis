// Text viewer panels: the find bar and the grep-extract panel (DOM only;
// the viewer owns the document and runs the jobs).

import {h} from '../lib/dom.mjs';
import {setPressed, toolButton} from './common.mjs';
import {viewerIcon} from './icons.mjs';

/**
 * Find bar. handlers: {search({pattern, regex, caseSensitive}), next(), previous(), close(), reference()}
 * Returns {element, focus(), state(), setStatus(text, kind), setProgress(fraction|null)}.
 */
export function createFindBar(handlers) {
  const input = h('input', {type: 'search', class: 'vw-input vw-find-input', placeholder: 'Find',
    'aria-label': 'Find in text', spellcheck: 'false', autocomplete: 'off'});
  const caseButton = toolButton({icon: 'case', title: 'Match case', pressed: false,
    onClick: () => toggle(caseButton)});
  const regexButton = toolButton({icon: 'regex', title: 'Regular expression', pressed: false,
    onClick: () => toggle(regexButton)});
  const status = h('output', {class: 'vw-find-status', 'aria-live': 'polite'}, '');
  const previous = toolButton({icon: 'up', title: 'Previous match (Shift+Enter)', onClick: handlers.previous});
  const next = toolButton({icon: 'down', title: 'Next match (Enter)', onClick: handlers.next});
  const reference = toolButton({icon: 'pixel', text: 'Reference', title: 'Reference the current match (Alt+Enter)',
    onClick: handlers.reference});
  const close = toolButton({icon: 'close', title: 'Close find (Escape)', onClick: handlers.close});
  const progress = h('div', {class: 'vw-progress vw-progress-inline', hidden: true},
    h('div', {class: 'vw-progress-bar'}));
  const element = h('div', {class: 'vw-findbar', role: 'search'},
    h('span', {class: 'vw-icon-label', 'aria-hidden': 'true'}, viewerIcon('search')),
    input, caseButton, regexButton, status, progress, previous, next, reference, close);

  const state = () => ({
    pattern: input.value,
    caseSensitive: caseButton.getAttribute('aria-pressed') === 'true',
    regex: regexButton.getAttribute('aria-pressed') === 'true',
  });
  const changed = () => handlers.search(state());

  function toggle(button) {
    setPressed(button, button.getAttribute('aria-pressed') !== 'true');
    changed();
    input.focus();
  }

  input.addEventListener('input', changed);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && event.altKey) {
      event.preventDefault();
      handlers.reference();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      (event.shiftKey ? handlers.previous : handlers.next)();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      handlers.close();
    }
  });

  return {
    element,
    focus() {
      input.focus();
      input.select();
    },
    state,
    set(pattern, options = {}) {
      input.value = pattern;
      setPressed(caseButton, Boolean(options.caseSensitive));
      setPressed(regexButton, Boolean(options.regex));
    },
    setStatus(text, kind = '') {
      status.textContent = text;
      status.dataset.kind = kind;
      input.setAttribute('aria-invalid', String(kind === 'error'));
    },
    setProgress(fraction) {
      progress.hidden = fraction === null;
      progress.firstChild.style.width = `${Math.round((fraction || 0) * 100)}%`;
    },
    setReferenceEnabled(enabled) {
      reference.disabled = !enabled;
    },
  };
}

const EXAMPLES = [
  ['', 'Examples…'],
  ['residuals', 'Solver residuals (OpenFOAM-style)'],
  ['assignments', 'name = number'],
  ['numbers', 'All numbers on matching lines'],
];

const EXAMPLE_SPECS = {
  residuals: {pattern: 'Solving for (?<field>\\w+), Initial residual = (?<initial>[^,]+), '
    + 'Final residual = (?<final>[^,]+), No Iterations (?<iterations>\\d+)', context: '^Time = (?<Time>\\S+)'},
  assignments: {pattern: '^\\s*(?<name>[A-Za-z_][\\w.]*)\\s*=\\s*(?<value>[-+]?[\\d.]+(?:[eE][-+]?\\d+)?)\\b',
    context: ''},
  numbers: {pattern: '([-+]?\\d+\\.?\\d*(?:[eE][-+]?\\d+)?)\\D+([-+]?\\d+\\.?\\d*(?:[eE][-+]?\\d+)?)', context: ''},
};

/**
 * Grep-extract panel. handlers: {run(spec), cancel(), openTable()}
 * Returns {element, focus(), setRunning(on), setProgress(fraction, rows), setResult(table), setError(message)}.
 */
export function createExtractPanel(handlers) {
  const pattern = h('input', {class: 'vw-input vw-mono vw-extract-pattern', spellcheck: 'false', autocomplete: 'off',
    placeholder: 'Row pattern with capture groups, e.g. residual = (?<initial>\\S+),', 'aria-label': 'Row pattern'});
  const context = h('input', {class: 'vw-input vw-mono', spellcheck: 'false', autocomplete: 'off',
    placeholder: 'Optional: carry groups from lines like ^Time = (?<Time>\\S+)', 'aria-label': 'Context pattern'});
  const caseSensitive = h('input', {type: 'checkbox', checked: true});
  const includeLine = h('input', {type: 'checkbox', checked: true});
  const examples = h('select', {class: 'vw-select', 'aria-label': 'Example patterns'},
    EXAMPLES.map(([value, text]) => h('option', {value}, text)));
  examples.addEventListener('change', () => {
    const spec = EXAMPLE_SPECS[examples.value];
    if (spec) {
      pattern.value = spec.pattern;
      context.value = spec.context;
    }
    examples.value = '';
    pattern.focus();
  });
  const run = h('button', {type: 'button', class: 'vw-btn vw-btn-primary', onClick: () => submit()}, 'Extract');
  const cancel = h('button', {type: 'button', class: 'vw-btn', hidden: true, onClick: handlers.cancel}, 'Cancel');
  const openTable = h('button', {type: 'button', class: 'vw-btn vw-btn-labelled', disabled: true,
    onClick: handlers.openTable}, viewerIcon('table'), h('span', {}, 'Open in Table'));
  const progress = h('div', {class: 'vw-progress', hidden: true}, h('div', {class: 'vw-progress-bar'}));
  const message = h('div', {class: 'vw-extract-message', 'aria-live': 'polite'},
    'Each matching line becomes a row; capture groups become columns (named groups name them).');
  const columns = h('div', {class: 'vw-extract-columns'});

  const submit = () => handlers.run({pattern: pattern.value, context: context.value,
    caseSensitive: caseSensitive.checked, includeLine: includeLine.checked});
  for (const input of [pattern, context]) {
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        submit();
      }
    });
  }

  const element = h('div', {class: 'vw-extract', role: 'region', 'aria-label': 'Grep extract'},
    h('div', {class: 'vw-extract-row'}, h('label', {class: 'vw-extract-label'}, 'Rows'), pattern, examples),
    h('div', {class: 'vw-extract-row'}, h('label', {class: 'vw-extract-label'}, 'Carry'), context,
      h('label', {class: 'vw-check'}, caseSensitive, 'Match case'),
      h('label', {class: 'vw-check'}, includeLine, 'Line column')),
    h('div', {class: 'vw-extract-row'}, h('span', {class: 'vw-extract-label'}), run, cancel, openTable, progress,
      message),
    columns);

  return {
    element,
    focus: () => pattern.focus(),
    set(spec) {
      pattern.value = spec.pattern || '';
      context.value = spec.context || '';
    },
    setRunning(on) {
      run.disabled = on;
      cancel.hidden = !on;
      progress.hidden = !on;
      if (on) {
        openTable.disabled = true;
        columns.replaceChildren();
      }
    },
    setProgress(fraction, rows) {
      progress.firstChild.style.width = `${Math.round(fraction * 100)}%`;
      message.dataset.kind = '';
      message.textContent = `${Math.round(fraction * 100)}% · ${rows.toLocaleString('en-CA')} rows so far`;
    },
    setResult(table) {
      message.dataset.kind = table.rows.length ? 'ok' : 'warn';
      message.textContent = `${table.rows.length.toLocaleString('en-CA')} rows × ${table.columns.length} columns `
        + `from ${table.source.lines.toLocaleString('en-CA')} lines`;
      openTable.disabled = !table.rows.length;
      columns.replaceChildren(...table.columns.map((column) => h('span', {class: 'vw-type-tag',
        dataset: {type: column.type}}, h('b', {}, column.name), ` ${column.type}`)));
    },
    setError(text) {
      message.dataset.kind = 'error';
      message.textContent = text;
      columns.replaceChildren();
    },
  };
}
