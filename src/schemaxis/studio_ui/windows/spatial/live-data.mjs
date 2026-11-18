// Copyright (C) 2026 David L. F. Gaden.
import {h} from '../../lib/dom.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {spatialRequest} from './host.mjs';
import {scopes} from '../variables/model.mjs';

export const liveDataEvents = new EventTarget();
export const liveDataChanged = () => liveDataEvents.dispatchEvent(new Event('change'));
export function memoryLabel(bytes) {
  if (bytes == null) return 'size unavailable';
  const units = ['B','k','M','G','T'];
  let value = bytes, index = 0;
  while (value >= 1000 && index < units.length-1) {value /= 1000; index++;}
  return `${Number(value.toPrecision(3))}${units[index]}`;
}

export async function openLiveData(ctx, snapshot) {
  if (!snapshot) {
    const active = ctx.windows.active()?.window;
    if (active?.variableContext) snapshot = await active.variableContext();
    else {
      const id = ctx.store.get().server?.activeDocument;
      if (!id) throw Error('Open a document before selecting Live Data.');
      const record = await ctx.api.get('/api/document', {id});
      snapshot = {root:record.document, identity:id};
    }
  }
  const owners = scopes(snapshot.root);
  let base = snapshot.base ?? owners.find(s=>!s.workflow)?.base ?? owners[0].base;
  let busy = false, job, closed = false;
  const selection = new Set();
  let loaded = new Set();
  const list = h('div', {class:'live-data-nodes'}), status = h('p', {role:'status','aria-live':'polite'});
  const error = h('p', {class:'error-text',role:'alert'});
  const request = () => spatialRequest(snapshot.root, base, undefined);
  const load = h('button', {class:'button primary',type:'button',onClick:()=>void enable()}, 'Enable selected Live Data');
  const refreshData = h('button', {class:'button',type:'button',onClick:()=>void enable(true)}, 'Refresh from Live Data');
  function controls() {
    load.disabled = busy || ![...selection].some(id => !loaded.has(id));
    refreshData.disabled = busy || ![...selection].some(id => loaded.has(id));
    refreshData.title = [...selection].some(id => loaded.has(id)) ? 'Recalculate from selected resident nodes; source files are not reread.' : 'Select a loaded node to refresh.';
    load.title = !selection.size ? 'Select at least one source or node to load.' : load.disabled && !busy ? 'Selected nodes are already loaded. Use Refresh from Live Data to update values.' : 'Load selected nodes and retain them in memory.';
  }
  const unload = h('button', {class:'button',type:'button',onClick:()=>void disable()}, 'Disable all Live Data');
  const cancel = h('button', {class:'button',type:'button',hidden:true,onClick:()=>{if(job)void ctx.api.post('/api/cancel',{job});}}, 'Cancel loading');
  const scope = h('select', {class:'select','aria-label':'Live Data scope',onChange:async e=>{base=e.target.value;selection.clear();await refresh();}},
    owners.map(s=>h('option',{value:s.base,selected:s.base===base},s.label)));
  async function refresh() {
    try {
      const result = await ctx.api.post('/api/spatial',{action:'live_data_list',...request()});
      if(closed)return;
      status.textContent = result.enabled ? `● Live Data enabled · ${memoryLabel(result.bytes)} resident application memory`
        : '○ Live Data disabled. Previously measured extents remain available in this session.';
      loaded = new Set((result.nodes || []).filter(node => node.loaded).map(node => node.id));
      list.replaceChildren(...(result.nodes || []).map(node=>{
        const checked = selection.has(node.id) || node.loaded;
        if(checked)selection.add(node.id);
        return h('label',{class:'field'},h('span',{},h('input',{type:'checkbox',checked,'aria-label':`Load ${node.id}`,
          onChange:e=>{e.target.checked?selection.add(node.id):selection.delete(node.id);controls();}}),
          ` ${node.id} · ${node.filter} · ${node.loaded?'loaded':node.observed?'extents cached':node.source?'source':'derived node'}`));
      }));
      if(!result.supported)list.replaceChildren(h('p',{},'This scope does not provide spatial extents. Select a supported operation.'));
      controls();
      if (!result.supported) load.disabled = refreshData.disabled = true;
      unload.disabled = busy || !result.enabled;
    }catch(fault){error.textContent=fault.message;}
  }
  async function enable(refreshOnly = false){
    if(busy)return;
    busy=true;load.disabled=true;refreshData.disabled=true;unload.disabled=true;scope.disabled=true;error.textContent='';status.textContent=refreshOnly?'Refreshing from resident data…':'Loading selected data…';cancel.hidden=false;
    try{
      const started=await ctx.api.post('/api/spatial',{action:refreshOnly?'live_data_refresh':'live_data_load',...request(),nodes:[...selection].filter(id=>refreshOnly?loaded.has(id):!loaded.has(id))});job=started.job;
      const completed=await ctx.api.waitForJob(job);
      if(completed.status!=='succeeded')throw Error(completed.fault?.message||'Loading cancelled.');
      liveDataChanged();await ctx.refresh();
    }catch(fault){if(!closed)error.textContent=fault.message;}
    finally{busy=false;job=undefined;scope.disabled=false;cancel.hidden=true;if(!closed)await refresh();}
  }
  async function disable(){
    try{await ctx.api.post('/api/spatial',{action:'live_data_unload'});selection.clear();liveDataChanged();await ctx.refresh();await refresh();}
    catch(fault){error.textContent=fault.message;}
  }
  void refresh();
  try{return await openDialog({title:'Live Data selection',content:h('div',{},
    h('p',{},'Choose input sources or derived nodes to keep in memory. Required upstream nodes load with them. Adding selections retains compatible loaded data; use Disable all Live Data to release it.'),
    scope,status,list,error,h('div',{class:'dialog-actions'},load,refreshData,unload,cancel)),actions:[{label:'Close',run:()=>true}]});}
  finally{closed=true;}
}
