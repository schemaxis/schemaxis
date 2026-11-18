// Copyright (C) 2026 David L. F. Gaden.
import {h, mount} from '../../lib/dom.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {createViewer3d} from '../../viewers/viewer3d.mjs';
import {openLiveData} from './live-data.mjs';
import {spatialSession} from './session.mjs';
import {saveSpatial, spatialAction, spatialRequest} from './host.mjs';
import {escapeSegment} from '../../editor/json-pointer.mjs';
import {atPointer} from '../../editor/fill-data.mjs';
import {suggestedVolumeName, canSaveVolume, STEPS, FACES, coordinateSource, initialVolume, volumeSources, volumeExpression, boxSummary, formatPoint} from './volume-model.mjs';

const button = (label, run, props = {}) => h('button', {type: 'button', class: 'button small', onClick: run, ...props}, label);
const field = (label, input) => h('label', {class: 'field'}, h('span', {}, label), input);
const select = (label, values, value, change) => h('select', {class: 'select', 'aria-label': label, onChange: e => change(e.target.value)},
  values.map(([id, text]) => h('option', {value: id, selected: id === value}, text)));

/** A local recipe. Only its host-checked expression (or explicit fixed snapshot) enters the document. */
export async function editVolume(ctx, {root, base = '', previous, source, spatial, revision = 0}) {
  let state = initialVolume(previous, source), saved = structuredClone(state), undo = [], redo = [];
  state.autoName = !previous;
  if (state.autoName) state.name = suggestedVolumeName(state, root, base);
  saved = structuredClone(state);
  let closed = false, timer, serial = 0, record, expression, pending = false, loadError = '', session;
  const form = h('div', {class: 'volume-controls'}), error = h('p', {class: 'error-text', role: 'alert'});
  const readout = h('output', {class: 'volume-result', 'aria-label': 'Volume result', role: 'status', 'aria-live': 'polite'});
  const data = h('output', {class: 'volume-data', 'aria-label': 'Builder data extents'});
  const viewerHost = h('div', {class: 'volume-viewer'});
  const viewer = createViewer3d(viewerHost, {label: 'Volume preview', emptyMessage: 'Choose a source to preview your volume'});
  const generated = h('code', {class: 'volume-expression'});
  const load = button('Select Live Data…', () => void loadPreview());
  const selectData = button('Live Data selection…', () => void chooseData());
  const cancelLoad = button('Cancel load', () => void session.cancel(), {hidden: true});
  const fixedHint = h('p', {class: 'hint'});
  const save = button(previous ? 'Update volume' : 'Add volume', () => void accept(), {class: 'button primary', disabled: true});
  let finish;
  const candidates = () => volumeSources(root, base, session.rows || [], previous);
  const valid = () => !pending && !session.busy && record?.state === 'resolved' && record.type === 'box' && record.valid;
  const saveable = () => !pending && !session.busy && canSaveVolume(record, state.mode);
  function display() {
    if (closed) return;
    const capability = session.capabilities.extents;
    const noReaders = session.dataExtents && session.dataExtents.state !== 'fault' && session.dataExtents.dependsOn?.nodes?.length === 0;
    data.textContent = `dataExtents = ${!capability ? 'Not available in this scope.' : noReaders
      ? 'Unavailable — no data readers in this scope.' : boxSummary(session.dataExtents)}`;
    data.title = session.dataExtents?.state === 'resolved' ? JSON.stringify(session.dataExtents.value) : '';
    readout.textContent = pending ? 'Checking volume…' : session.busy ? 'Loading source data…' : boxSummary(record);
    if (valid()) {
      const {min, max} = record.value;
      readout.textContent += ` · size ${formatPoint(max.map((v,i) => v-min[i]))} · model units`;
      readout.title = JSON.stringify(record.value);
      viewer.setOverlays([{id: 'result', kind: 'box', ...record.value}], {selected: 'result'});
    } else { viewer.setOverlays([]); readout.title = ''; }
    selectData.hidden = !session.liveData.enabled;
    selectData.disabled = session.busy;
    load.textContent = session.liveData.enabled ? 'Refresh from Live Data' : 'Select Live Data…';
    load.title = session.liveData.enabled ? 'Recalculate this volume from resident sources; source files are not reread.' : 'Choose sources to keep loaded in memory.';
    load.disabled = session.busy || pending || !capability || !expression || record?.state === 'fault';
    load.hidden = !session.busy && record?.state === 'resolved' && !record.dependsOn?.nodes?.length;
    cancelLoad.hidden = !session.busy;
    save.disabled = !saveable();
    save.title = save.disabled ? (pending ? 'Checking the expression.' : loadError || boxSummary(record))
      : state.mode === 'linked' ? 'Save the recipe; coordinates resolve when data is available.' : 'Save the measured coordinates.';
    const fixed = form.querySelector('[aria-label="Save as fixed numbers"]');
    if (fixed) { fixed.disabled = !valid(); fixed.title = valid() ? 'Save the current coordinates.' : 'Enable Live Data to resolve coordinates before saving a fixed snapshot.'; }
    for (const [label, stack] of [['Undo step',undo], ['Redo step',redo]]) {
      const control = form.querySelector(`[aria-label="${label}"]`);
      if (control) control.disabled = !stack.length || session.busy;
    }
    fixedHint.textContent = state.mode === 'fixed'
      ? 'A snapshot of the full-precision result shown here. It will not follow the data.'
      : 'Linked: follows its sources when the document runs. No mesh is changed by these box operations.';
    error.textContent = loadError;
  }
  session = spatialSession(ctx.api, {root, base, revision, spatial, includeDataExtents: true, autoRefresh: () => ctx.store.get().settings?.values['spatial.autoRefresh'] !== false, changed: display});
  function changed(rebuild = false) {
    if (state.autoName) {
      state.name = suggestedVolumeName(state, root, base, previous);
      const input = form.querySelector('[aria-label="Volume name"]');
      if (input) input.value = state.name;
    }
    if (JSON.stringify(state) !== JSON.stringify(saved)) {
      undo.push(saved); saved = structuredClone(state); redo = [];
    }
    if (rebuild) draw();
    schedule();
  }
  function restore(from, to) {
    if (!from.length || session.busy) return;
    to.push(structuredClone(state)); state = from.pop(); saved = structuredClone(state); draw(); schedule();
  }
  function schedule() {
    clearTimeout(timer); serial++; pending = true; record = undefined; loadError = '';
    try { expression = volumeExpression(state); generated.textContent = expression; }
    catch (fault) { expression = ''; pending = false; loadError = fault.message; generated.textContent = ''; }
    display();
    if (expression) timer = setTimeout(() => void preview(), 250);
  }
  async function preview() {
    clearTimeout(timer);
    if (!expression || closed) return;
    const token = ++serial, text = expression;
    pending = true; display();
    try {
      const result = await session.evaluate(text);
      if (closed || token !== serial) return;
      record = result;
    } catch (fault) { if (token === serial) loadError = fault.message; }
    finally { if (!closed && token === serial) { pending = false; display(); } }
  }
  async function chooseData() {
    try { await openLiveData(ctx, {root, base}); await session.refresh(); if (!closed) await preview(); }
    catch (fault) { if (!closed) { loadError = fault.message; display(); } }
  }
  async function loadPreview() {
    if (!expression || session.busy) return;
    ++serial; const text = expression;
    clearTimeout(timer); pending = false; loadError = '';
    try {
      if (session.liveData.enabled) await session.refreshLive(text);
      else { await openLiveData(ctx, {root, base}); await session.refresh(); }
      if (!closed) await preview();
    } catch (fault) { if (!closed) { loadError = fault.message; display(); } }
  }
  function number(label, value, set) {
    return field(label, h('input', {class: 'input', inputMode: 'decimal', 'aria-label': label, value,
      onInput: e => { set(e.target.value); changed(); }}));
  }
  function sourceControls(value, title, replace, allowCurrent = false) {
    const available = candidates();
    const choices = [['coordinates', 'Coordinates'], ['data', 'Data extents'], ['node', 'A node’s extents'], ['value', 'A saved value']];
    if (allowCurrent && value.kind === 'current') choices.push(['current', 'Current definition']);
    const details = h('div', {class: 'volume-source-fields'});
    const choice = select(title, choices, value.kind, kind => {
      replace(kind === 'coordinates' ? coordinateSource() : kind === 'node' ? {kind, node: available.nodes[0]?.id || ''}
        : kind === 'value' ? {kind, expression: available.values[0]?.expression || ''} : {kind}); changed(true);
    });
    if (value.kind === 'coordinates') {
      details.append(field('Coordinates', select(title+' coordinate layout', [['corners','Corners'],['centre','Centre and size']], value.layout,
        next => { value.layout = next; changed(true); })));
      const a = value.layout === 'centre' ? 'Centre' : 'Min', b = value.layout === 'centre' ? 'Size' : 'Max';
      for (const [key,label] of [['a',a],['b',b]]) details.append(h('div', {class: 'spatial-coordinates'},
        [...'XYZ'].map((axis,i) => number(`${title} ${label} ${axis}`, value[key][i], n => { value[key][i] = n; }))));
      details.append(h('p', {class: 'hint'}, 'Coordinates are in model units. Flat boxes are fine.'));
    } else if (value.kind === 'node') {
      details.append(field('Node', select(title+' node', [['','Choose a node…'], ...available.nodes.map(n => [n.id,n.label])], value.node,
        id => { value.node = id; changed(); })), h('p', {class: 'hint'}, 'Uses this node’s output bounds. Save the linked recipe now, or enable Live Data to preview it. Data stays loaded until you disable it.'));
    } else if (value.kind === 'value') {
      details.append(field('Saved box', select(title+' saved value', [['','Choose a box…'], ...available.values.map(v => [v.expression,v.label])], value.expression,
        text => { value.expression = text; changed(); })), h('p', {class: 'hint'}, available.values.length
          ? 'Uses the named value, keeping its dependency.' : 'No saved box values are available in this scope.'));
    } else if (value.kind === 'data') details.append(h('p', {class: 'hint'}, 'Encloses all data readers before filtering. Use a node’s extents for a smaller region.'));
    else details.append(h('p', {class: 'hint'}, 'Adjustments wrap the existing definition, keeping its sources.'));
    return h('div', {class: 'volume-source'}, field(title, choice), details);
  }
  function draw() {
    const history = h('div', {class: 'volume-history'},
      button('Undo step', () => restore(undo,redo), {'aria-label':'Undo step', disabled: !undo.length}),
      button('Redo step', () => restore(redo,undo), {'aria-label':'Redo step', disabled: !redo.length}));
    const steps = h('div', {class: 'volume-steps'}, state.steps.map((step,i) => {
      const spec = STEPS.find(s => s.id === step.id);
      const fields = spec.labels ? h('div', {class: 'spatial-coordinates'}, spec.labels.map((label,j) =>
        number(`${i+1}. ${label}`, step.values[j], value => { step.values[j] = value; })))
        : sourceControls(step.source, `${i+1}. Other volume`, value => { step.source = value; });
      return h('section', {class: 'volume-step', 'aria-label': `${i+1}. ${spec.title}`},
        h('div', {class: 'volume-step-heading'}, h('h5', {}, `${i+1}. ${spec.title}`),
          button('Remove', () => { state.steps.splice(i,1); changed(true); }, {'aria-label': `Remove step ${i+1}`})),
        h('p', {class: 'hint'}, spec.help), spec.face ? field('Face', select(`${i+1}. Face`, FACES, step.face, v => {step.face=v; changed();})) : null, fields);
    }));
    const groups = h('div', {class: 'volume-step-groups'}, [...new Set(STEPS.map(s=>s.group))].map(group =>
      h('div', {class: 'volume-step-group', role: 'group', 'aria-label': group}, h('span', {class: 'hint'}, group),
        h('div', {}, STEPS.filter(s=>s.group===group).map(spec => button(spec.title, () => {
          state.steps.push({id: spec.id, ...(spec.values ? {values: spec.values.map(String)} : {source: coordinateSource()}), ...(spec.face ? {face:spec.face} : {})}); changed(true);
        }))))));
    const mode = h('div', {class: 'volume-mode'},
      field('Keep linked to sources', h('input', {type: 'radio', name: 'volume-mode', checked: state.mode==='linked',
        onChange: () => { state.mode='linked'; changed(); }})),
      field('Fixed numbers', h('input', {type: 'radio', name: 'volume-mode', checked: state.mode==='fixed', 'aria-label': 'Save as fixed numbers',
        onChange: () => { state.mode='fixed'; changed(); }})));
    mount(form,
      h('section', {}, h('h4', {}, '1 · Start from'), sourceControls(state.source, 'Volume source', v => {state.source=v;}, true)),
      h('section', {}, h('div', {class: 'volume-step-heading'},h('h4', {}, '2 · Adjust'),history),
        h('p', {class:'hint'}, 'Add adjustments below. Steps run from top to bottom.'),groups,steps),
      h('section', {}, h('h4', {}, '3 · Add as'), h('div', {class:'spatial-identity'},
        field('Name', h('input', {class:'input', 'aria-label':'Volume name', value:state.name,
          onInput:e=>{state.name=e.target.value; state.autoName=false; changed();}})),
        field('Group', select('Volume group', ['definitions','settings','dimensions'].map(v=>[v,v]), state.group,v=>{state.group=v;changed();}))),
        mode,fixedHint));
    if (previous) form.querySelector('[aria-label="Volume group"]').disabled = true;
    display();
  }
  async function accept() {
    if (!saveable()) return;
    const token = serial;
    try {
      if (['dataExtents','time','pi','true','false','definitions','settings','dimensions','workflow','sweeps'].includes(state.name)) {
        throw Error(`“${state.name}” is built in. Choose a different name for your volume.`);
      }
      const plain = state.mode === 'fixed' || state.source.kind === 'coordinates' && state.steps.length === 0;
      let value = plain ? structuredClone(record.value) : {$expr: expression};
      if (plain && Array.isArray(previous?.value)) value = [0,1,2].flatMap(i=>[value.min[i],value.max[i]]);
      const next = await saveSpatial(ctx.api, root,{base,name:state.name,group:state.group},value,previous);
      const checked = await spatialAction(ctx.api,'spatial_check',spatialRequest(next,base,session.draft,
        {expression: plain ? expression : value.$expr,destination:`/${state.group}/${escapeSegment(state.name)}`}));
      if (closed || token !== serial) return;
      if (!checked.ok) throw Error(checked.fault?.message || 'This volume cannot be added.');
      finish({root:next, name:state.name, group:state.group});
    } catch (fault) { loadError=fault.message; display(); }
  }
  draw();
  const content = h('div', {class:'volume-content'},
    h('p', {class:'hint'}, 'Build a bounding volume with controls. Your data and geometry stay unchanged.'),
    h('div', {class:'volume-layout'},form,h('aside', {class:'volume-preview'},viewerHost,readout,data,
      h('div', {class:'volume-load-actions'},load,selectData,cancelLoad),
      h('details', {},h('summary', {},'Show expression'),h('p', {class:'hint'},'These controls create a normal expression. It is evaluated by Schemaxis.'),generated))),error);
  content.addEventListener('keydown', e=>{
    if ((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='z' && !['INPUT','TEXTAREA'].includes(e.target.tagName)) {
      e.preventDefault(); e.stopPropagation(); e.shiftKey ? restore(redo,undo) : restore(undo,redo);
    }
  });
  const dialog = openDialog({title:previous?'Adjust volume':'New volume',className:'volume-dialog',wide:true,enterSubmits:false,
    content:close=>{finish=close;return h('div',{},content,h('div',{class:'volume-actions'},button('Cancel volume',()=>close(null)),save));}});
  content.closest('.dialog').addEventListener('keydown', e => {
    if (e.key !== 'Tab') return;
    const controls = [...e.currentTarget.querySelectorAll('button,input,select,textarea,summary,[tabindex]')]
      .filter(el => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length);
    const edge = e.shiftKey ? controls[0] : controls.at(-1);
    if (document.activeElement === edge) { e.preventDefault(); (e.shiftKey ? controls.at(-1) : controls[0]).focus(); }
  });
  void session.refresh().then(()=>{if(!closed){draw();schedule();}}).catch(fault=>{loadError=fault.message;display();});
  schedule();
  try {return await dialog;}
  finally {closed=true;serial++;clearTimeout(timer);void session.cancel().catch(()=>{});session.dispose();viewer.destroy();}
}
