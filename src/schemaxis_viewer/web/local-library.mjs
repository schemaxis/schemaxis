import {el,button,note,warning} from './ui.mjs';
const token=new URL(location.href).searchParams.get('token');
export const localURL=value=>{const url=new URL(value,location.href);if(token)url.searchParams.set('token',token);return url.href;};
export async function localRequest(route,body) {
  const response=await fetch(localURL('api/'+route),{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});
  if(!response.ok){let message;try{message=(await response.json()).fault?.message;}catch{}throw Error(message||`Could not read the local folder (HTTP ${response.status})`);}
  return response.json();
}
export function createLocalLibrary({openRecords,openBrowserFiles}) {
  let available=false,recent=[],browserRecent=[],lastDirectory='',listingSnapshot=null;
  const host=document.querySelector('#recent-library');
  async function refresh(){try{const listing=await localRequest('library');listingSnapshot=listing;available=true;recent=listing.recent||[];}catch{available=false;}render();return listingSnapshot;}
  async function openPaths(paths,{replace=true}={}) {
    const result=await localRequest('open',{paths});
    await openRecords(result.records,{replace,sources:result.sources,label:paths.map(path=>path.split('/').filter(Boolean).at(-1)).join(', ')});
    await refresh();
  }
  async function reopen(row) {
    try {
      if(row.browser){await openBrowserFiles(row.records,{replace:true,label:row.label,sources:row.sources||[]});return;}
      if(row.kind==='run'){const records=await localRequest('inventory?id='+encodeURIComponent(row.id));const listing=await refresh();await openRecords(records,{replace:true,label:row.label,sources:listing?.collections.find(item=>item.id===row.id)?.sources||[]});return;}
      await openPaths(row.paths);
    }catch(error){host.prepend(warning(error.message));}
  }
  function render() {
    const kind=document.querySelector('#library-view').value;
    host.hidden=!['recent','runs'].includes(kind);host.replaceChildren();
    if(host.hidden)return;
    const rows=kind==='runs'?recent.filter(row=>row.kind==='run'):[...browserRecent,...recent.filter(row=>row.kind!=='run')];
    host.append(...rows.map(row=>button([el('strong',{},row.label),el('span',{class:'subtle'},`${row.count??row.records?.length??0} files · ${row.viewed?new Date(row.viewed).toLocaleString():'this session'}`)],()=>reopen(row),{class:'recent-entry',title:row.paths?.join('\n')||row.label})),...(!rows.length?[note(kind==='runs'?'Completed Schemaxis runs appear here.':'Folders you open appear here. No media is copied into history.')]:[]));
  }
  function remember(records,label,sources=[]) {
    browserRecent=[{browser:true,label:label||'Selected files',records:[...records],sources},...browserRecent].slice(0,15);render();
  }
  async function choose(replace) {
    // The local service chooses paths; selected media is never posted to it.
    if(!available){
      if(window.showDirectoryPicker){
        try{
          const handle=await showDirectoryPicker({mode:'read'}),records=[],sources=[{root:handle?.name,label:handle?.name,folders:[]}];
          async function visit(directory,path){for await(const entry of directory.values()){if(entry.name==='.output-index'&&entry.kind==='directory')continue;if(records.length>=50000)throw Error('Folder exceeds 50,000 files');if(entry.kind==='directory'){sources[0].folders.push((path+entry.name).slice(handle.name.length+1));await visit(entry,path+entry.name+'/');}else records.push({file:await entry.getFile(),path:path+entry.name});}}
          await visit(handle,handle.name+'/');await openBrowserFiles(records,{replace,label:handle.name,sources});
        }catch(error){if(error.name!=='AbortError')document.querySelector('#notice').append(warning(error.message));}
      }else document.querySelector('#notice').append(note('Restart the local viewer to use its folder browser. Add files is available in this browser.'));
      return;
    }
    const dialog=el('dialog',{class:'folder-dialog','aria-label':replace?'Open local folder':'Add local folder'});
    const path=el('input',{type:'text','aria-label':'Local folder path',placeholder:'Enter a local folder path'}),folders=el('div',{class:'folder-choices'}),notice=el('div');
    const confirm=button(replace?'Open folder':'Add folder',async()=>{
      confirm.disabled=true;
      try{document.querySelector('#recursive').checked=recursive.checked;await openPaths([path.value],{replace});dialog.close();dialog.remove();}catch(error){notice.replaceChildren(warning(error.message));confirm.disabled=false;}
    },{class:'primary'});
    let listing=0;
    async function list(directory) {
      const revision=++listing;path.disabled=true;confirm.disabled=true;
      try{const data=await localRequest('browse'+(directory?'?directory='+encodeURIComponent(directory):''));if(revision!==listing)return;lastDirectory=data.directory;path.value=data.directory;notice.replaceChildren();folders.replaceChildren(button('↑ Parent folder',()=>list(data.parent)),...data.folders.map(folder=>button('▱ '+folder.name,()=>list(folder.path),{class:'folder-choice'})));}
      catch(error){if(revision===listing)notice.replaceChildren(warning(error.message));}
      finally{if(revision===listing){path.disabled=false;confirm.disabled=false;}}
    }
    const recursive=el('input',{type:'checkbox',checked:document.querySelector('#recursive').checked,'aria-label':'Include subfolders when opening'});
    path.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();list(path.value);}};
    dialog.append(el('h2',{},replace?'Open local folder':'Add local folder'),note(replace?'Replace the current contents with this folder.':'Append this folder to the current contents.'),el('div',{class:'folder-path'},path,button('Go',()=>list(path.value))),el('label',{class:'inline-check'},recursive,'Include subfolders'),notice,folders,el('div',{class:'dialog-actions'},button('Cancel',()=>dialog.close()),confirm));
    document.body.append(dialog);dialog.onclose=()=>dialog.remove();dialog.showModal();await list(lastDirectory||undefined);
  }
  return {refresh,render,choose,remember,release:()=>{browserRecent=[];render();},get available(){return available;}};
}
