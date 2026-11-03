// Copyright (C) 2026 David L F Gaden
// Bottom panel: Problems, Jobs, Log and the command Console.

import {h, icon, mount} from '../lib/dom.mjs';

const TABS = [
  {id: 'problems', label: 'Problems'},
  {id: 'jobs', label: 'Jobs'},
  {id: 'log', label: 'Log'},
  {id: 'console', label: 'Console'},
];
const LEVEL_ICON = {error: 'error', warn: 'alert', info: 'info', ok: 'check'};

function time(value) {
  return value.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'});
}

function entryRow(ctx, entry, {dismissable}) {
  const jump = typeof entry.location === 'string' && entry.source?.document;
  const actions = entry.actions?.length ? entry.actions : jump ? [{label: 'Show in input',
    run: () => ctx.bus.emit('reveal-location', {document: entry.source.document, location: entry.location})}] : [];
  return h('div', {
    class: ['panel-row', jump && 'clickable'],
    onClick: jump ? () => ctx.bus.emit('reveal-location', {document: entry.source.document, location: entry.location})
      : undefined,
  },
  icon(LEVEL_ICON[entry.level], null),
  h('div', {},
    h('div', {}, h('strong', {}, entry.title), entry.body ? ` — ${entry.body}` : ''),
    entry.code ? h('div', {class: 'detail'}, entry.code + (entry.location ? ` at ${entry.location}` : '')) : null,
    actions.map((action) => h('button', {class: 'button ghost small', onClick: (event) => {
      event.stopPropagation();
      action.run();
    }}, action.label))),
  h('div', {class: 'when'}, time(entry.time),
    dismissable ? h('button', {class: 'button ghost small icon-only', 'aria-label': 'Dismiss problem',
      onClick: (event) => {
        event.stopPropagation();
        ctx.notify.dismissProblem(entry.id);
      }}, icon('close')) : null));
}

function createConsole(ctx) {
  const output = h('div', {class: 'panel-body'});
  const history = [];
  let cursor = 0;
  const input = h('input', {class: 'input', placeholder: 'Console command, e.g. help, status, list',
    'aria-label': 'Console command', spellcheck: 'false', autocomplete: 'off'});
  const append = (level, text) => {
    output.append(h('div', {class: 'panel-row'}, icon(LEVEL_ICON[level], null),
      h('pre', {class: 'mono', style: {margin: 0, whiteSpace: 'pre-wrap'}}, text), h('span')));
    output.scrollTop = output.scrollHeight;
  };
  const run = async () => {
    const line = input.value.trim();
    if (!line) {
      return;
    }
    history.push(line);
    cursor = history.length;
    input.value = '';
    append('info', `› ${line}`);
    try {
      const job = await ctx.api.post('/api/command', {line});
      const result = await ctx.api.waitForJob(job.job);
      append('ok', JSON.stringify(result.result, null, 2));
    } catch (error) {
      append('error', `${error.code}: ${error.message}`);
    }
    ctx.refresh();
  };
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      run();
    } else if (event.key === 'ArrowUp' && cursor > 0) {
      cursor -= 1;
      input.value = history[cursor];
      event.preventDefault();
    } else if (event.key === 'ArrowDown' && cursor < history.length) {
      cursor += 1;
      input.value = history[cursor] || '';
      event.preventDefault();
    }
  });
  return h('div', {style: {display: 'flex', flexDirection: 'column', height: '100%'}},
    output,
    h('div', {class: 'console-input'}, input, h('button', {class: 'button', onClick: run}, 'Run')));
}

export function createPanel(ctx) {
  const tabs = h('div', {class: 'panel-tabs', role: 'tablist'});
  const body = h('div', {class: 'panel-body'});
  const consoleView = createConsole(ctx);
  const element = h('section', {class: 'panel', hidden: true, 'aria-label': 'Bottom panel'}, tabs, body);

  const render = () => {
    const state = ctx.store.get();
    element.hidden = !state.panelOpen;
    if (!state.panelOpen) {
      return;
    }
    const problems = ctx.notify.store.get().problems;
    mount(tabs, TABS.map((tab) => h('button', {
      class: 'panel-tab', role: 'tab', 'aria-selected': String(state.panelTab === tab.id),
      onClick: () => ctx.store.set({panelTab: tab.id}),
    }, tab.label, tab.id === 'problems' && problems.length ? h('span', {class: 'count'}, problems.length) : null)),
    h('span', {style: {flex: 1}}),
    state.panelTab === 'problems' && problems.length
      ? h('button', {class: 'button ghost small', onClick: () => ctx.notify.clearProblems()}, 'Clear all') : null,
    h('button', {class: 'button ghost small icon-only', 'aria-label': 'Close panel',
      onClick: () => ctx.store.set({panelOpen: false})}, icon('close')));
    if (state.panelTab === 'console') {
      if (body.firstChild !== consoleView) {
        mount(body, consoleView);
      }
      return;
    }
    if (state.panelTab === 'problems') {
      mount(body, problems.length
        ? [...problems].reverse().map((entry) => entryRow(ctx, entry, {dismissable: true}))
        : h('div', {class: 'empty-state'}, icon('check'), 'No problems.'));
    } else if (state.panelTab === 'log') {
      const log = ctx.notify.store.get().log;
      mount(body, log.length ? [...log].reverse().map((entry) => entryRow(ctx, entry, {dismissable: false}))
        : h('div', {class: 'empty-state'}, 'Nothing logged yet.'));
    } else if (state.panelTab === 'jobs') {
      const jobs = state.server ? state.server.jobs : [];
      mount(body, jobs.length ? [...jobs].reverse().map((job) => h('div', {class: 'panel-row'},
        icon(job.status === 'running' ? 'spinner' : job.status === 'failed' ? 'error' : 'check', null),
        h('div', {}, h('strong', {}, job.label || 'Command'), ` — ${job.status}`),
        h('div', {class: 'detail'}, job.id.slice(0, 8))))
        : h('div', {class: 'empty-state'}, 'No jobs have run in this session.'));
    }
  };
  ctx.store.subscribe(render);
  ctx.notify.store.subscribe(render);
  render();
  return element;
}
