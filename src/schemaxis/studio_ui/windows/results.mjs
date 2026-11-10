// One collection viewer, shared with the standalone application.
import {h} from '../lib/dom.mjs';
import {setSetting} from '../shell/preferences.mjs';
import {confirmDialog} from '../shell/dialog.mjs';

export function createResultsFrame(ctx,collection,{onClose=()=>{}}={}) {
  const frame=h('iframe',{class:'results-frame',title:'Local results viewer',src:ctx.api.url('/artifact-viewer/index.html',{...(collection?{collection}:{}),theme:ctx.setting('theme')||'system'})});
  let placeholder=null,scrollPositions=[];
  function expand(value) {
    if(value&&!placeholder){scrollPositions=[];for(let node=frame.parentElement;node;node=node.parentElement)scrollPositions.push([node,node.scrollTop,node.scrollLeft]);placeholder=h('div',{'aria-hidden':'true'});placeholder.style.height=frame.getBoundingClientRect().height+'px';frame.before(placeholder);}
    frame.classList.toggle('results-frame-expanded',value);
    if(!value){placeholder?.remove();placeholder=null;for(const [node,top,left] of scrollPositions){node.scrollTop=top;node.scrollLeft=left;}scrollPositions=[];}
  }
  const theme=()=>frame.contentWindow?.postMessage({type:'artifact-theme',theme:ctx.setting('theme')||'system'},location.origin);
  const ready=event=>{if(event.origin!==location.origin||event.source!==frame.contentWindow)return;if(event.data?.type==='artifact-ready')theme();if(event.data?.type==='artifact-expand')expand(event.data.expanded===true);if(event.data?.type==='artifact-close')onClose();if(event.data?.type==='artifact-theme-preference'&&['light','dark','system'].includes(event.data.theme))setSetting(ctx,{theme:event.data.theme});};
  document.addEventListener('themechange',theme);window.addEventListener('message',ready);
  return {element:frame,open(identity){expand(false);frame.src=ctx.api.url('/artifact-viewer/index.html',{...(identity?{collection:identity}:{}),theme:ctx.setting('theme')||'system'});},dispose(){expand(false);document.removeEventListener('themechange',theme);window.removeEventListener('message',ready);frame.remove();}};
}

export const resultsWindow={
  type:'results',title:'Results',icon:'folder',singleton:true,
  create(ctx,params={},host) {
    let approvedClose=false,closing=null;
    const viewer=createResultsFrame(ctx,params.collection,{onClose:()=>{approvedClose=true;host.close();}});
    const canClose=()=>approvedClose|| (closing ||= confirmDialog('Close results?', 'Are you sure you want to close this results viewer?', {confirm:'Close results'}).finally(()=>{closing=null;}));
    return {element:h('div',{class:'results-window'},viewer.element),openCollection:identity=>viewer.open(identity),canClose,dispose:()=>viewer.dispose()};
  },
};
