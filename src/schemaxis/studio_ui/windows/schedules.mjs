// Copyright (C) 2026 David L F Gaden
// Durable schedules share exact saved documents with normal verified execution.
import {h, mount} from '../lib/dom.mjs';

export const schedulesWindow = {
  type: 'schedules', title: 'Schedules', icon: 'play', singleton: true,
  create(ctx) {
    let disposed = false;
    let selected = null;
    let records = [];
    const documents = h('select', {class: 'input', 'aria-label': 'Document to schedule'});
    const objective = h('input', {class: 'input', placeholder: 'Purpose of this scheduled work', 'aria-label': 'Objective'});
    const kind = h('select', {class: 'input', 'aria-label': 'Trigger'},
      h('option', {value: 'once'}, 'Once'), h('option', {value: 'interval'}, 'At an interval'),
      h('option', {value: 'calendar'}, 'Daily at a local time'));
    const start = h('input', {class: 'input', type: 'datetime-local', 'aria-label': 'Start time'});
    const interval = h('input', {class: 'input', type: 'number', min: 1, value: 86400, 'aria-label': 'Interval in seconds'});
    const timezone = h('input', {class: 'input', value: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC', 'aria-label': 'Calendar timezone'});
    const clock = h('input', {class: 'input', type: 'time', value: '09:00', 'aria-label': 'Daily local time'});
    const maximum = h('input', {class: 'input', type: 'number', min: 1, max: 100000, value: 100, 'aria-label': 'Maximum occurrences'});
    const overlap = h('select', {class: 'input', 'aria-label': 'Overlapping work'},
      ...['queue', 'skip', 'coalesce'].map((value) => h('option', {value}, value)));
    const misfire = h('select', {class: 'input', 'aria-label': 'Missed occurrences'},
      h('option', {value: 'runOnce'}, 'Run once after a missed time'),
      h('option', {value: 'skip'}, 'Skip missed times'), h('option', {value: 'catchUp'}, 'Bounded catch-up'));
    const status = h('p', {role: 'status', class: 'secondary-text'});
    const workerCommand = h('code', {class: 'mono', 'aria-label': 'Schedule worker command'});
    const preview = h('pre', {class: 'mono'});
    const list = h('div');
    const details = h('pre', {class: 'mono'});
    const field = (label, input) => h('label', {class: 'form-field'}, h('span', {}, label), input);
    const intervalField = field('Interval (seconds)', interval);
    const zoneField = field('Calendar timezone', timezone);
    const clockField = field('Daily time', clock);
    function mode() {
      intervalField.hidden = kind.value !== 'interval';
      zoneField.hidden = clockField.hidden = kind.value !== 'calendar';
    }
    kind.addEventListener('change', mode);
    mode();
    function draftChoices() {
      const current = documents.value;
      const items = (ctx.store.get().server?.documents || []).filter((record) => record.valid && record.provider !== 'workflow-design');
      mount(documents, items.map((record) => h('option', {value: record.id}, record.name)));
      if (items.some((record) => record.id === current)) documents.value = current;
    }
    const unsubscribe = ctx.store.subscribe(draftChoices);
    draftChoices();
    async function call(value) {
      try { return await ctx.api.post('/api/schedules', value); }
      catch (error) { ctx.notify.error(error, {title: 'Schedule action failed'}); return null; }
    }
    async function load() {
      const response = await call({action: 'list'});
      if (!response || disposed) return;
      records = response.schedules;
      const quotedWorkspace = "'" + response.workspace.replaceAll("'", "'\\''") + "'";
      workerCommand.textContent = `schemaxis schedule --workspace ${quotedWorkspace} serve`;
      status.textContent = 'Registered schedules need the independent schedule worker running. Closing Studio does not remove them.';
      mount(list, records.map((record) => h('section', {class: 'card'},
        h('strong', {}, record.spec.objective),
        h('p', {}, `${record.status} · ${record.nextDue == null ? 'No future trigger' : new Date(record.nextDue * 1000).toLocaleString()}`),
        h('div', {class: 'button-row'},
          h('button', {class: 'button small', onClick: async () => {
            const result = await call({action: 'get', id: record.id});
            if (result && !disposed) { selected = result; details.textContent = JSON.stringify(result, null, 2); }
          }}, 'Details'),
          ...(['active', 'paused'].includes(record.status) ? [record.status === 'paused' ? 'resume' : 'pause'] : []).map((action) =>
            h('button', {class: 'button small', onClick: async () => { await call({action, id: record.id, revision: record.revision}); await load(); }}, action === 'pause' ? 'Pause' : 'Resume')),
          ...(!['cancelled'].includes(record.status) ? [h('button', {class: 'button small', onClick: async () => {
            await call({action: 'cancel', id: record.id, revision: record.revision}); await load();
          }}, 'Cancel')] : [])))));
      if (selected && !records.some((record) => record.id === selected.id)) details.textContent = '';
    }
    async function submit(action) {
      const record = (ctx.store.get().server?.documents || []).find((item) => item.id === documents.value);
      if (!record || !start.value || !objective.value.trim()) {
        status.textContent = 'Choose a valid saved document, purpose and start time.'; return;
      }
      const date = new Date(start.value);
      if (!Number.isFinite(date.getTime())) { status.textContent = 'Enter a valid start time.'; return; }
      const trigger = kind.value === 'once' ? {kind: 'once', at: date.toISOString()}
        : kind.value === 'interval' ? {kind: 'interval', start: date.toISOString(), seconds: Number(interval.value)}
          : {kind: 'calendar', start: date.toISOString(), timezone: timezone.value,
            hour: Number(clock.value.split(':')[0]), minute: Number(clock.value.split(':')[1]), weekdays: [0, 1, 2, 3, 4, 5, 6]};
      const result = await call({action, document: record.id, documentRevision: record.revision,
        spec: {objective: objective.value.trim(), trigger, maxOccurrences: Number(maximum.value), overlap: overlap.value, misfire: misfire.value}});
      if (!result || disposed) return;
      if (action === 'preview') preview.textContent = result.upcoming.length
        ? result.upcoming.map((instant) => new Date(instant).toLocaleString()).join('\n') : 'No upcoming trigger times.';
      else { ctx.notify.ok('Schedule registered', {body: 'The saved document was captured. Start the independent worker to execute due work.'}); await load(); }
    }
    load();
    return {element: h('div', {class: 'window-body settings'}, h('div', {class: 'settings-inner'},
      h('h2', {}, 'Schedules'), status,
      h('details', {}, h('summary', {}, 'Worker setup'),
        h('p', {}, 'Run this command in a separately supervised terminal or service. Application locations use your normal private Schemaxis CLI configuration.'),
        workerCommand),
      field('Saved document', documents), field('Purpose', objective), field('Trigger', kind),
      field('Start (your browser local time)', start), intervalField, zoneField, clockField,
      field('Maximum occurrences', maximum), field('Overlapping work', overlap), field('Missed occurrences', misfire),
      h('div', {class: 'button-row'},
        h('button', {class: 'button', onClick: () => submit('preview')}, 'Preview times'),
        h('button', {class: 'button primary', onClick: () => submit('create')}, 'Register schedule'),
        h('button', {class: 'button', onClick: load}, 'Refresh')),
      preview, list, details)), dispose() { disposed = true; unsubscribe(); }};
  },
};
