// Local sample attachments let authors inspect output data before native applications run.

import {h, icon, mount} from '../../lib/dom.mjs';
import {createTextViewer} from '../../viewers/text.mjs';
import {createTableViewer} from '../../viewers/table.mjs';

const MAX_SAMPLE_BYTES = 10 * 1024 * 1024;

export function createSamplesTab(ctx, model) {
  const attachments = new Map();
  const port = h('select', {class: 'select', 'aria-label': 'Sample output port'});
  const input = h('input', {type: 'file', accept: '.txt,.log,.csv,.tsv,.json,text/*,application/json', hidden: true});
  const attach = h('button', {class: 'button small', onClick: () => input.click()}, icon('folder'), 'Attach file');
  const remove = h('button', {class: 'button small', onClick: () => {
    attachments.delete(port.value);
    render();
  }}, icon('close'), 'Detach');
  const mode = h('select', {class: 'select', 'aria-label': 'Sample view'},
    h('option', {value: 'text'}, 'Text / grep'), h('option', {value: 'table'}, 'Table'));
  const status = h('div', {class: 'dz-sample-status muted', 'aria-live': 'polite'});
  const textHost = h('div', {class: 'dz-sample-view'});
  const tableHost = h('div', {class: 'dz-sample-view', hidden: true});
  const text = createTextViewer(textHost, {label: 'Sample text', emptyMessage: 'Attach a text or table sample'});
  const table = createTableViewer(tableHost, {label: 'Sample table', emptyMessage: 'Attach CSV, TSV or table JSON'});
  const element = h('div', {class: 'dz-tab-panel dz-samples'},
    h('div', {class: 'dz-sample-toolbar'}, port, attach, remove, mode, input), status, textHost, tableHost,
    h('div', {class: 'dz-sample-note'}, 'Sample files stay in this window and are excluded from exported templates. '
      + 'They do not replace live workflow inputs.'));
  let displayed = null;
  let viewToken = 0;

  const report = ({message}) => ctx.notify.error({code: 'SAMPLE_VIEW_ERROR', message},
    {title: 'Could not view the sample', source: {document: model.documentId}});
  text.on('error', report);
  table.on('error', report);
  text.on('extract', async (result) => {
    const sample = attachments.get(port.value);
    if (!sample) return;
    sample.extracted = result;
    await table.load(result);
    mode.value = 'table';
    showView();
  });

  function showView() {
    textHost.hidden = mode.value !== 'text';
    tableHost.hidden = mode.value !== 'table';
    if (mode.value === 'table') table.resize();
    else text.resize();
  }

  async function loadSample(sample) {
    const token = ++viewToken;
    await text.load({text: sample.text, name: sample.name});
    if (token !== viewToken) return;
    if (sample.extracted) {
      await table.load(sample.extracted);
    } else if (/\.json$/i.test(sample.name)) {
      try {
        const parsed = JSON.parse(sample.text);
        if (Array.isArray(parsed.rows) && Array.isArray(parsed.columns)) {
          await table.load({...parsed, name: sample.name});
        } else {
          table.clear();
          mode.value = 'text';
        }
      } catch {
        table.clear();
        mode.value = 'text';
      }
    } else if (/\.(csv|tsv)$/i.test(sample.name)) {
      const delimiter = /\.tsv$/i.test(sample.name) ? '\t' : undefined;
      await table.load({text: sample.text, name: sample.name, delimiter});
    } else {
      table.clear();
      mode.value = 'text';
    }
    showView();
  }

  function render() {
    const projection = model.store.get().projection;
    const current = port.value;
    const outputs = (projection?.nodes || []).flatMap((node) => node.ports.outputs.map((item) => ({
      key: `${node.id}.${item.name}`, operation: node.id, name: item.name,
    })));
    const valid = new Set(outputs.map((item) => item.key));
    for (const key of attachments.keys()) {
      if (!valid.has(key)) attachments.delete(key);
    }
    mount(port, outputs.length ? outputs.map((item) => h('option', {value: item.key},
      `${item.key}${attachments.has(item.key) ? ' · attached' : ''}`))
      : h('option', {value: ''}, 'Add an output port first'));
    if (valid.has(current)) port.value = current;
    const sample = attachments.get(port.value);
    attach.disabled = !outputs.length;
    remove.disabled = !sample;
    mode.disabled = !sample;
    const selected = outputs.find((item) => item.key === port.value);
    const destinations = (projection?.connections || []).filter((connection) =>
      connection.from.operation === selected?.operation && connection.from.port === selected?.name)
      .map((connection) => `${connection.to.operation}.${connection.to.port}`);
    status.textContent = sample ? `${sample.name} · ${(sample.bytes / 1024).toFixed(1)} KiB`
      + (destinations.length ? ` · Feeds ${destinations.join(', ')}` : ' · No downstream connections')
      : 'Choose an output port and attach a sample to inspect its text, extract matches or explore a table.';
    if (sample !== displayed) {
      displayed = sample;
      if (sample) loadSample(sample);
      else {
        viewToken += 1;
        text.clear();
        table.clear();
      }
    }
    showView();
  }

  input.addEventListener('change', async () => {
    const file = input.files[0];
    const key = port.value;
    input.value = '';
    if (!file || !key) return;
    if (file.size > MAX_SAMPLE_BYTES) {
      ctx.notify.error({code: 'SAMPLE_TOO_LARGE', message: 'Choose a sample smaller than 10 MiB.'},
        {title: 'Sample is too large'});
      return;
    }
    try {
      const value = await file.text();
      if (value.includes('\0')) throw Error('Choose a text, CSV, TSV or JSON file. This file contains binary data.');
      attachments.set(key, {name: file.name, bytes: file.size, text: value});
      mode.value = /\.(csv|tsv)$/i.test(file.name) ? 'table' : 'text';
      render();
    } catch (error) {
      report(error);
    }
  });
  port.addEventListener('change', render);
  mode.addEventListener('change', showView);
  const unsubscribe = model.store.watch((state) => state.projection, render);
  render();
  return {element, show: showView, dispose() {
    unsubscribe();
    viewToken += 1;
    text.destroy();
    table.destroy();
    attachments.clear();
  }};
}
