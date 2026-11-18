// Copyright (C) 2026 David L. F. Gaden.
import {openLiveData} from './live-data.mjs';
import {spatialSession} from './session.mjs';
import {spatialInput, reportSpatialCheck} from '../../editor/spatial-input.mjs';
import {saveSpatial, spatialAction, spatialRequest} from './host.mjs';
import {escapeSegment} from '../../editor/json-pointer.mjs';
import {h, mount} from '../../lib/dom.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {createViewer3d} from '../../viewers/viewer3d.mjs';
import {entries, equal, scopes, GROUPS} from '../variables/model.mjs';
import {entryOverlays, numericLiteral, spatialEntries, hasMarker} from './model.mjs';
import {editVolume} from './volume-editor.mjs';
import {boxSummary, formatPoint} from './volume-model.mjs';

const button = (text, run, props = {}) => h('button', {type: 'button', class: 'button small', onClick: run, ...props}, text);
const field = (label, control) => h('label', {class: 'field'}, h('span', {}, label), control);
const select = (label, items) => h('select', {class: 'select', 'aria-label': label},
  items.map(([value, text]) => h('option', {value}, text)));

/** Edit a snapshot using the same guarded, single-undo commit as Variables. */
export async function manageSpatial(ctx, snapshot) {
  let staged = structuredClone(snapshot.root), selected = null, applying = false, expressionMode = false, closed = false;
  let session;
  const owners = scopes(staged), hidden = new Set();
  const owner = select('Spatial scope', owners.map(s => [s.base, s.label]));
  owner.value = snapshot.base ?? owners[0].base;
  const list = h('div', {class: 'spatial-list', 'aria-label': 'Spatial entries'});
  const editor = h('div', {class: 'spatial-form'});
  const error = h('p', {class: 'error-text', role: 'alert'});
  const summary = h('p', {class: 'hint', 'aria-live': 'polite'});
  const legend = h('div', {class: 'hint', 'aria-label': 'Visible spatial overlays'});
  const viewHost = h('div', {class: 'spatial-viewer'});
  const vectorLines = h('input', {type: 'checkbox', 'aria-label': 'Vectors as lines from origin'});
  const dataReadout = h('output', {class: 'spatial-data-value', 'aria-label': 'Data extents', 'aria-live': 'polite'});
  const dataHint = h('p', {class: 'hint'});
  const showData = h('input', {type: 'checkbox', checked: true, 'aria-label': 'Show data extents', onChange: () => redraw()});
  const loadData = button('Refresh extents', () => ctx.call(async () => {
    try { error.textContent = ''; await session.refreshLive('dataExtents'); } catch (fault) { error.textContent = fault.message; }
  }), {class: 'button primary small'});
  const useData = button('Create volume from data…', () => volume(undefined, {kind: 'data'}));
  const viewer = createViewer3d(viewHost, {label: 'Spatial model view', emptyMessage: 'No resolved boxes or vectors in this scope'});

  const live = button('Live Data selection…', () => ctx.call(() => openLiveData(ctx, {root:staged, base:owner.value})));
  const loadValues = button('Refresh from Live Data', () => ctx.call(async () => {
    try {error.textContent='';await session.refreshLive();}catch(fault){error.textContent=fault.message;}
  }));
  const cancelLive = button('Cancel live data', () => ctx.call(() => session.cancel()), {hidden: true});
  session = spatialSession(ctx.api, {root: staged, base: owner.value, identity: snapshot.identity || 'spatial-draft',
    autoRefresh: () => ctx.store.get().settings?.values['spatial.autoRefresh'] !== false,
    revision: snapshot.revision ?? 0, spatial: snapshot.spatial, includeDataExtents: true,
    observed: snapshot.observeSpatial, changed: () => { if (!closed) redraw(); }});
  async function volume(previous, source) {
    try {
      const result = await editVolume(ctx, {root: staged, base: owner.value, previous, source,
        spatial: session.snapshot, revision: session.draft.revision});
      if (!result || closed) return;
      staged = result.root; session.edit(staged); selected = null; expressionMode = false;
      drawEditor(); await refresh();
    } catch (fault) { error.textContent = fault.message; }
  }
  async function refresh() {
    try { await session.refresh(); } catch (fault) { if (!closed) error.textContent = `Host: ${fault.message}`; }
  }
  function redraw() {
    const rows = (session.rows ?? spatialEntries(staged, owner.value)).filter(row => row.base === owner.value);
    const freshSelection = selected && rows.find(row => row.pointer === selected.pointer);
    if (freshSelection) {
      const typeChanged = freshSelection.literal.type !== selected.literal.type;
      selected = freshSelection;
      if (typeChanged && !expressionMode) drawEditor();
    }
    loadValues.hidden = !session.capabilities?.extents; loadValues.disabled = session.busy || !session.liveData.enabled;
    loadValues.title = session.liveData.enabled ? 'Recalculate values and needed derived nodes using sources in memory; does not reread source files.' : 'Choose sources in Live Data selection first. Cached values remain available.';
    live.hidden = !session.capabilities?.extents; live.disabled = session.busy;
    cancelLive.hidden = !session.busy;
    const data = session.dataExtents, supported = session.capabilities.extents;
    const noReaders = data && data.state !== 'fault' && data.dependsOn?.nodes?.length === 0;
    dataReadout.textContent = `dataExtents = ${session.busy ? 'Loading data…' : !supported ? 'Unavailable in this scope.'
      : noReaders ? 'Unavailable — no data readers in this scope.' : boxSummary(data)}`;
    dataReadout.title = data?.state === 'resolved' ? JSON.stringify(data.value) : '';
    loadData.disabled = session.busy || !supported || noReaders || !session.liveData.enabled;
    loadData.title = loadValues.title;
    useData.disabled = session.busy || !supported || noReaders;
    showData.disabled = data?.state !== 'resolved' || !data.valid;
    dataHint.textContent = data?.state === 'resolved' && data.valid
      ? `Size ${formatPoint(data.value.max.map((v,i) => v-data.value.min[i]))} · model units · first time / sweep position`
      : 'Select Live Data sources to resolve reader bounds. For generated geometry or filtered regions, create a volume from a node’s extents.';
    const items = entryOverlays(rows, {vectorsAsLines: vectorLines.checked, hidden});
    if (showData.checked && !showData.disabled) items.unshift({id: 'builtin:dataExtents', kind: 'box', ...data.value});
    try { viewer.setOverlays(items, {selected: selected?.pointer}); }
    catch (fault) { viewer.setOverlays([]); error.textContent = fault.message; }
    mount(legend, rows.filter(row => items.some(item => item.id === row.pointer)).map(row => h('div', {},
      `${row.name} · ${row.literal.type}${row.record ? ' · draft revision ' + (row.draft?.revision ?? '?') : ' · literal'}`)));
    summary.textContent = `${items.length} visible · ${rows.filter(e => e.literal.state === 'unresolved').length} unresolved · model coordinates`;
    mount(list, rows.length ? rows.map(entry => {
      const {literal} = entry;
      const drawable = literal.state === 'resolved' && (literal.type === 'vector' || literal.type === 'box' && literal.valid);
      const visible = h('input', {type: 'checkbox', checked: !hidden.has(entry.pointer), disabled: !drawable,
        'aria-label': `Show ${entry.group}.${entry.name}`, onChange: () => {
          if (visible.checked) hidden.delete(entry.pointer); else hidden.add(entry.pointer);
          redraw();
        }});
      const state = literal.state === 'unresolved' ? 'Unresolved · ' + (literal.reason || 'needs host evaluation')
        : literal.state === 'fault' ? literal.reason : literal.type === 'box' && !literal.valid ? 'Invalid box · not drawn' : entry.record ? `${entry.record.source?.kind || entry.record.phase} · ${literal.type} · draft revision ${entry.draft?.revision ?? '?'}` : 'Literal · ' + literal.type;
      return h('div', {class: ['spatial-row', selected?.pointer === entry.pointer && 'selected'], dataset: {pointer: entry.pointer}},
        visible, h('div', {}, button(entry.name, () => { selected = entry; expressionMode = false; drawEditor(); redraw(); },
          {'aria-label': `Select ${entry.group}.${entry.name}`, 'aria-pressed': String(selected?.pointer === entry.pointer)}),
        h('div', {class: 'hint'}, `${entry.group} · ${state}`),
        literal.type === 'box' && literal.state === 'resolved' && literal.valid
          ? h('code', {}, `${formatPoint(literal.value.min)}, ${formatPoint(literal.value.max)}`) : null,
        h('details', {}, h('summary', {}, hasMarker(entry.value) ? 'Linked expression' : 'Fixed value'), h('code', {}, JSON.stringify(entry.value)))));
    }) : h('p', {class: 'hint'}, 'Create a box, vector or scalar to begin.'));
  }

  function suggestName(control, label) {
    if (control.dataset.userNamed === 'true') return;
    const stem = (label || 'value').replace(/[^A-Za-z0-9_-]+/g,'_').replace(/^_+|_+$/g,'').slice(0,80) || 'value';
    let prefix = /^[A-Za-z]/.test(stem) ? stem : 'value_' + stem;
    if (['dataExtents','time','pi','true','false','definitions','settings','dimensions','workflow','sweeps'].includes(prefix)) prefix += '_value';
    const names = new Set(entries(staged).filter(e=>e.base===owner.value).map(e=>e.name));
    let name=prefix, i=2;while(names.has(name))name=prefix+'_'+i++;
    control.value=name;
  }
  function drawEditor() {
    error.textContent = '';
    const current = selected;
    if (expressionMode) {
      const name = h('input', {class: 'input', 'aria-label': 'Spatial name', value: current?.name || 'spatialValue'});
      const group = select('Spatial group', GROUPS.map(g => [g, g])); group.value = current?.group || 'definitions';
      group.disabled = Boolean(current);
      const shared = spatialInput({label: 'Spatial expression', value: current?.value ?? {$expr: ''}});
      name.addEventListener('input',()=>{name.dataset.userNamed='true';});
      if(current)name.dataset.userNamed='true';
      shared.element.addEventListener('input',()=>suggestName(name,shared.element.value));
      if(!current)suggestName(name,'expression');
      const completion = h('datalist', {id: 'spatial-functions'}, session.functions.map(fn => h('option', {value: fn.name})));
      shared.element.setAttribute('list', 'spatial-functions');
      const status = h('output', {class: 'hint', 'aria-live': 'polite'});
      let checking = false, ticket = 0;
      const candidate = async () => {
        const value = shared.read();
        const next = await saveSpatial(ctx.api, staged, {base: owner.value, group: group.value, name: name.value}, value, current);
        return {value, next, base: owner.value, destination: `/${group.value}/${escapeSegment(name.value)}`};
      };
      const checked = async (draft, serial) => {
        if (typeof draft.value?.$expr !== 'string') return true;
        const result = await spatialAction(ctx.api, 'spatial_check', spatialRequest(draft.next, draft.base, session.draft,
          {expression: draft.value.$expr, destination: draft.destination}));
        if (serial !== ticket || !shared.element.isConnected) return false;
        if (shared.element.value === (typeof draft.value.$expr === 'string' ? draft.value.$expr : '')) reportSpatialCheck(shared.element, result);
        const spatial = ['scalar', 'vector', 'box'].includes(result.type);
        status.textContent = !result.ok ? result.fault?.message || 'Expression refused'
          : spatial ? `${result.type} · ${result.phase}` : 'Choose an expression of type scalar, vector or box.';
        return result.ok && spatial;
      };
      const act = save => ctx.call(async () => {
        if (checking) return;
        checking = true;
        const serial = ++ticket, before = staged, text = shared.element.value, scope = owner.value;
        try {
          const draft = await candidate();
          if (!await checked(draft, serial)) return;
          if (closed || !shared.element.isConnected || serial !== ticket || scope !== owner.value
              || before !== staged || text !== shared.element.value) return;
          if (save) {
            staged = draft.next; session.edit(staged); expressionMode = false; selected = null;
            drawEditor(); await refresh();
          }
        } catch (fault) { error.textContent = fault.message; }
        finally { checking = false; }
      });
      for (const control of [shared.element, name, group]) control.addEventListener('input', () => { ticket++; status.textContent = ''; });
      mount(editor, h('h4', {}, current ? 'Edit expression' : 'New expression'), field('Name', name), field('Group', group),
        field('Number, name or expression', shared.element), completion, status,
        h('p', {class: 'hint'}, 'Use dataExtents for all readers, or extents(nodeId) for one node. For example: inflate(dataExtents, 0.1). The volume builder writes expressions for you.'),
        button('Check expression', () => act(false)), button(current ? 'Update expression' : 'Add expression', () => act(true)));
      return;
    }
    if (current && hasMarker(current.value)) {
      mount(editor, h('h4', {}, current.name), h('p', {class: 'hint'},
        current.literal.state === 'resolved' ? 'Computed value. Edit its expression to keep the dependency.'
          : 'This value is unresolved. Its authored expression is preserved; it is not drawn.'),
        current.literal.type === 'box' ? button('Adjust volume…', () => volume(current), {class: 'button primary small'}) : null,
        h('pre', {}, JSON.stringify(current.value, null, 2)), button('Edit expression', () => { expressionMode = true; drawEditor(); }));
      return;
    }
    const name = h('input', {class: 'input', 'aria-label': 'Spatial name', value: current?.name || 'spatialValue'});
    const group = select('Spatial group', GROUPS.map(g => [g, g]));
    group.value = current?.group || 'definitions'; group.disabled = Boolean(current);
    const type = select('Spatial type', [['box', 'Box'], ['vector', 'Vector'], ['scalar', 'Scalar']]);
    type.value = current?.literal.type || 'box'; type.disabled = Boolean(current);
    name.addEventListener('input',()=>{name.dataset.userNamed='true';});
    if(current)name.dataset.userNamed='true';
    const coordinates = h('div', {class: 'spatial-coordinates'});
    let read;
    function fields() {
      coordinates.replaceChildren();
      suggestName(name,type.value);
      const seed = current?.literal.value;
      const input = (label, initial) => {
        const control = h('input', {class: 'input', inputMode: 'decimal', 'aria-label': label, value: String(initial)});
        coordinates.append(field(label, control));
        return () => numericLiteral(control.value);
      };
      const triple = (prefix, values) => [...'XYZ'].map((axis, i) => input(prefix + axis, values[i]));
      if (type.value === 'box') {
        const minimum = triple('Minimum ', seed?.min || [0, 0, 0]), maximum = triple('Maximum ', seed?.max || [1, 1, 1]);
        read = () => ({min: minimum.map(f => f()), max: maximum.map(f => f())});
      } else if (type.value === 'vector') {
        const values = triple('', Array.isArray(seed) ? seed : [0, 0, 0]);
        read = () => values.map(f => f());
      } else read = input('Scalar value', typeof seed === 'number' ? seed : 0);
    }
    type.addEventListener('change', fields); fields();
    mount(editor, h('h4', {}, current ? 'Edit literal' : 'Quick literal'),
      current?.literal.type === 'box' && current.literal.valid ? button('Adjust volume…', () => volume(current), {class: 'button primary small'}) : null,
      field('Name', name),
      h('div', {class: 'spatial-identity'}, field('Group', group), field('Type', type)), coordinates,
      h('p', {class: 'hint'}, 'Equal corners make a flat box. Reversed corners make an invalid box, which is kept in the list.'),
      button(current ? 'Update literal' : 'Add literal', async () => {
        try {
          staged = await saveSpatial(ctx.api, staged, {base: owner.value, group: group.value, name: name.value}, read(), current, true);
          selected = spatialEntries(staged, owner.value).find(e => e.group === group.value && e.name === name.value);
          session.edit(staged); redraw(); drawEditor(); void refresh();
        } catch (fault) { error.textContent = fault.message; }
      }, {class: 'button primary small'}));
  }
  owner.addEventListener('change', () => { selected = null; expressionMode = false; session.edit(staged, owner.value); drawEditor(); redraw(); void refresh(); });
  vectorLines.addEventListener('change', redraw);
  drawEditor(); redraw(); void refresh();
  try {
    return await openDialog({title: 'Spatial', wide: true, className: 'spatial-dialog', enterSubmits: false,
      content: h('div', {class: 'spatial-content'}, h('p', {class: 'hint'}, snapshot.label || 'Values belong to this document.'),
        h('div', {class: 'spatial-tools'}, field('Scope', owner),
          button('Add literal / volume…', () => volume(), {class: 'button primary small'}),
          button('Quick literal', () => { selected = null; expressionMode = false; drawEditor(); redraw(); }),
          button('New expression', () => { selected = null; expressionMode = true; drawEditor(); }), live, loadValues, cancelLive,
          h('label', {class: 'checkbox'}, vectorLines, 'Vectors as lines from origin')),
        h('section', {class: 'spatial-data', 'aria-label': 'Built-in data extents'},
          h('div', {}, h('h4', {}, 'Data extents'), dataReadout, dataHint),
          h('div', {class: 'spatial-data-actions'}, loadData, useData, h('label', {class: 'checkbox'}, showData, 'Show bounds'))),
        h('div', {class: 'spatial-layout'}, h('div', {class: 'spatial-sidebar'}, list, editor, error),
          h('div', {}, viewHost, summary, legend, h('p', {class: 'hint'}, 'Boxes are outlines. Vectors are points or lines from the origin. Scalars are listed only. Available Live Data resolves volumes automatically by default. Refresh reuses loaded sources. Unresolved values are never drawn.')))),
      actions: [{label: 'Cancel', run: () => null}, {label: snapshot.applyLabel || 'Apply changes', primary: true, run: async () => {
        if (applying) return false;
        applying = true;
        try { if (!equal(staged, snapshot.root)) await snapshot.commit(staged); return true; }
        catch (fault) { error.textContent = fault.message; return false; }
        finally { applying = false; }
      }}]});
  } finally { closed = true; void session.cancel().catch(() => {}); session.dispose(); viewer.destroy(); }
}

export async function openSpatial(ctx) {
  const active = ctx.windows.active()?.window;
  if (active?.variableContext) return manageSpatial(ctx, await active.variableContext());
  const records = ctx.store.get().server?.documents || [];
  if (!records.length) throw Error('Open or create a document first, then open Spatial.');
  const choice = select('Spatial document', records.map(r => [r.id, r.name]));
  const id = await openDialog({title: 'Choose a document for Spatial', content: field('Document', choice),
    actions: [{label: 'Cancel', run: () => null}, {label: 'Open Spatial', primary: true, run: () => choice.value}]});
  if (!id) return;
  const existing = [...ctx.windows.instances.values()].find(w => w.params.document === id && !w.params.operation && w.window.variableContext);
  if (existing) return manageSpatial(ctx, await existing.window.variableContext());
  const record = await ctx.api.get('/api/document', {id});
  return manageSpatial(ctx, {root: record.document, identity: record.id, revision: record.revision, label: record.name, applyLabel: 'Save changes to workspace', commit: async root => {
    await ctx.api.post('/api/authoring', {action: 'patch', document: id, revision: record.revision,
      edits: [{op: 'replace', path: '', value: root}]});
    await ctx.refresh();
  }});
}
