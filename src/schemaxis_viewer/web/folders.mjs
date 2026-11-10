import {el,button,note} from './ui.mjs';
export const pathParts=item=>({root:item.root||item.scope||'Selected files',label:item.rootLabel||item.root||item.scope||'Selected files',path:item.relativePath||item.name});
export function inFolder(item,location,recursive) {
  const file=pathParts(item);
  if(location&&file.root!==location.root)return false;
  const prefix=location?.path?location.path+'/':'';
  if(!file.path.startsWith(prefix))return false;
  return recursive||!file.path.slice(prefix.length).includes('/');
}
export function createFolders({getItems,getSources=()=>[],getLocation,navigate}) {
  function render() {
    const items=getItems(),location=getLocation(),roots=new Map();
    for(const source of getSources())roots.set(source.root,{label:source.label,folders:new Set(source.folders)});
    for(const item of items){const parts=pathParts(item);if(!roots.has(parts.root))roots.set(parts.root,{label:parts.label,folders:new Set()});const root=roots.get(parts.root),segments=parts.path.split('/');for(let n=1;n<segments.length;n++)root.folders.add(segments.slice(0,n).join('/'));}
    const tree=document.querySelector('#folder-tree');tree.replaceChildren(button('All opened folders',()=>navigate(null),{'aria-pressed':!location}));
    for(const [id,root] of roots) {
      const details=el('details',{class:'folder-root',open:''},el('summary',{},root.label));
      details.append(button('▱ '+root.label,()=>navigate({root:id,path:'',label:root.label}),{class:'tree-path','aria-pressed':location?.root===id&&!location.path}));
      for(const path of [...root.folders].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true})))details.append(button('▱ '+path,()=>navigate({root:id,path,label:root.label}),{class:'tree-path',title:path,'aria-pressed':location?.root===id&&location.path===path}));
      tree.append(details);
    }
    if(!roots.size)tree.append(note('Open a folder to browse its files.'));
    const host=document.querySelector('#foldernav');host.replaceChildren();
    if(!roots.size)return;
    const crumbs=el('div',{class:'breadcrumbs'},button('All outputs',()=>navigate(null),{'aria-label':'Show all outputs'}));
    if(location){crumbs.append(el('span',{},'/'),button(location.label,()=>navigate({...location,path:''})));const segments=location.path.split('/').filter(Boolean);segments.forEach((part,index)=>crumbs.append(el('span',{},'/'),button(part,()=>navigate({...location,path:segments.slice(0,index+1).join('/')}))));}
    host.append(crumbs);
    const children=el('div',{class:'folder-children'});
    if(!location){for(const [root,row] of roots)children.append(button('▱ '+row.label,()=>navigate({root,path:'',label:row.label}),{'data-folder':root}));}
    else {
      const root=roots.get(location.root),prefix=location.path?location.path+'/':'',names=new Set();
      for(const folder of root?.folders||[])if(folder.startsWith(prefix)){const rest=folder.slice(prefix.length);if(rest&&!rest.includes('/'))names.add(rest);}
      for(const name of [...names].sort())children.append(button('▱ '+name,()=>navigate({...location,path:prefix+name}),{'data-folder':prefix+name}));
    }
    if(children.children.length)host.append(children);
  }
  return {render};
}
