// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import {el,button,note,warning,formatBytes} from './ui.mjs';
import {groupTree,inGroupPath,photoSeries} from './grouping.mjs';
import {attachMetadata,buildGroups,cornersFor,basename,relativeItem,filenameRange,boundsFor,cameraUV} from './model.mjs';
import {demoItems} from './demo.mjs';
import {showDetail} from './details.mjs';
import {mountSequences,xyzSets} from './sequences.mjs';
import {createScene,meshFromBytes} from './scene.mjs';
import {createLocation} from './location.mjs';
import {installPreferences} from './preferences.mjs';
import {createLocalLibrary,localURL,localRequest} from './local-library.mjs';
import {createFolders,inFolder} from './folders.mjs';
import {createPane} from './panes.mjs';
import {propertyFacets,matchesProperties,itemProperties} from './filename.mjs';
import {createFilenameRules} from './filename-rules-ui.mjs';
const $=id=>document.getElementById(id);
let items=[],groups=[],selected=null,mode='gallery',groupBy='auto',cleanups=[],serial=0,importNumber=0,loading=false,indices=new Map(),issues=[],selectedImages=[];
const visibility=new Map(),sequenceVisibility=new Map();
const propertyFilters=new Map();
const facetExpansion=new Map();
let hierarchyKeys=[],hierarchyPath=[],hierarchyItems=[];
const hierarchyExpansion=new Map();
const hierarchyHost=el('div',{class:'hierarchy-tools'});
$('workspace-controls').querySelector('.browse-controls').after(hierarchyHost);
const matchingItems=()=>!group()?[]:[...new Map(contents(group()).flatMap(section=>section.items).map(i=>[i.id,i])).values()];
$('select-all').before(button('Select matching',()=>setSelection(matchingItems(),true),{id:'select-matching'}),button('Deselect matching',()=>setSelection(matchingItems(),false),{id:'deselect-matching'}));
const facetHost=el('div',{class:'filename-facets','aria-label':'Filename properties'});
$('workspace-controls').querySelector('.browse-controls').after(facetHost);
const selections=new Map(),galleryScroll=new Map(),galleryPages=new Map();
let gallerySize=225,rendered=null,folderLocation=null,allGroup=null,folderSources=[],libraryReady=false;
const preferences=installPreferences({onChange:values=>{if(parent===window)localRequest('preferences',values).catch(()=>{});}});
const localLibrary=createLocalLibrary({openRecords,openBrowserFiles:addFiles});
const filenameRules=createFilenameRules({getItems:()=>items,onApplied:()=>{for(const key of propertyFilters.keys())if(key.startsWith('grep.'))propertyFilters.delete(key);hierarchyPath=[];selected='*';resetBrowsing();render();}});
hierarchyHost.after(filenameRules.root);
$('open-folder').disabled=true;$('add-folder').disabled=true;
const folders=createFolders({getItems:()=>items.filter(i=>!i.isMetadata),getSources:()=>folderSources,getLocation:()=>folderLocation,navigate:location=>{folderLocation=location;selected='*';resetBrowsing();render();}});
const locator=createLocation($('location'),{openFile,selectItem});
const status=text=>{$('status').textContent=text;};
function setBusy(value){loading=value;for(const id of ['open-files','open-folder','add-folder','demo','clear','close-viewer'])$(id).disabled=value||(!libraryReady&&['open-folder','add-folder'].includes(id));for(const entry of document.querySelectorAll('.recent-entry'))entry.disabled=value;$('main').setAttribute('aria-busy',String(value));}
const dispose=()=>{cleanups.forEach(fn=>fn());cleanups=[];};
function clear({redraw=true}={}) {
  filenameRules.cancel();
  hierarchyPath=[];
  propertyFilters.clear();
  dispose();for(const item of items)if(item.blob)URL.revokeObjectURL(item.url);
  items=[];groups=[];selected=null;selectedImages=[];indices.clear();visibility.clear();sequenceVisibility.clear();issues=[];selections.clear();galleryScroll.clear();galleryPages.clear();rendered=null;mode='gallery';folderLocation=null;allGroup=null;folderSources=[];locator.clear();$('filter').value='';$('type-filter').value='all';$('main').scrollTop=0;if(redraw)render();
}
function group(){return selected==='*'?allGroup:groups.find(g=>g.id===selected)||groups[0];}
function regroup(){
  const old=new Map(groups.map(g=>[g.id,g.visible]));
  // Assign file kinds before type filtering on a newly opened collection.
  buildGroups(items,{groupBy});
  const availableKeys=new Set(['folder','fileType',...propertyFacets(items).keys()]);
  if(hierarchyKeys.some(key=>!availableKeys.has(key))){hierarchyKeys=hierarchyKeys.filter(key=>availableKeys.has(key));hierarchyPath=[];}
  const visibleItems=items.filter(item=>inFolder(item,folderLocation,$('recursive').checked));
  const typed=visibleItems.filter(item=>$('type-filter').value==='all'||item.isMetadata||item.kind===$('type-filter').value);
  renderFacets(typed);
  hierarchyItems=typed.filter(item=>item.isMetadata||matchesProperties(item,propertyFilters));
  const filtered=hierarchyItems.filter(item=>item.isMetadata||inGroupPath(item,hierarchyPath));
  groups=buildGroups(filtered,{groupBy});allGroup=buildGroups(filtered,{groupBy:'all'})[0];
  for(const g of groups)g.visible=old.get(g.id)??true;
  if(allGroup&&groupBy!=='all')allGroup.sequences=groups.flatMap(g=>g.sequences);
  if(selected!=='*'&&!groups.some(g=>g.id===selected))selected=groups[0]?.id;
}
function renderFacets(records) {
  for(const branch of facetHost.querySelectorAll('[data-facet-key]'))facetExpansion.set(branch.dataset.facetKey,branch.open);
  const facets=propertyFacets(records);facetHost.replaceChildren();facetHost.hidden=!facets.size&&!propertyFilters.size;
  if(facetHost.hidden)return;
  facetHost.append(el('span',{},'Properties · metadata and filenames'));
  for(const [key,values] of [...facets].sort(([a],[b])=>a.localeCompare(b))) {
    const chosen=propertyFilters.get(key);
    // Bound each control's DOM size; an input with suggestions still accepts
    // any exact value in a large coordinate/time set.
    const entries=[...values].sort(([,a],[,b])=>String(a.value).localeCompare(String(b.value),'en',{numeric:true}));
    if(chosen instanceof Set||records.some(item=>Array.isArray(itemProperties(item)[key]))) {
      const selected=chosen instanceof Set?chosen:new Set(chosen?[chosen]:[]);
      const search=el('input',{type:'search',placeholder:'Search values','aria-label':`Search values ${key}`}),options=el('div',{class:'facet-values'});
      const drawValues=()=>{
        const filtered=entries.filter(([,row])=>String(row.value).toLowerCase().includes(search.value.toLowerCase()));let limit=200;
        const mount=()=>options.replaceChildren(...filtered.slice(0,limit).map(([token,row])=>{
          const check=el('input',{type:'checkbox',checked:selected.has(token),'aria-label':`Include ${key}: ${row.value}`,onchange:()=>{const next=new Set(selected);if(check.checked)next.add(token);else next.delete(token);if(next.size)propertyFilters.set(key,next);else propertyFilters.delete(key);resetBrowsing();render();}});
          return el('label',{},check,`${row.value} · ${row.ids.size}`);
        }),...(filtered.length>limit?[button('More values',()=>{limit+=200;mount();})]:[]));mount();
      };
      search.oninput=drawValues;drawValues();
      const branch=el('details',{class:'facet-checklist','data-facet-key':key},el('summary',{},`${key} · ${selected.size?selected.size+' selected':'Any'}`),el('div',{class:'facet-popup'},note('Any checked value matches; other fields also apply.'),search,button('Any '+key,()=>{propertyFilters.delete(key);resetBrowsing();render();}),options));branch.open=facetExpansion.get(key)??false;facetHost.append(branch);continue;
    }
    let control;
    const change=value=>{if(value==='')propertyFilters.delete(key);else propertyFilters.set(key,value);resetBrowsing();render();};
    if(entries.length<=200){
      control=el('select',{'aria-label':`Filename ${key}`},el('option',{value:''},'Any'),entries.map(([token,row])=>el('option',{value:token},`${typeof row.value==='string'?row.value:JSON.stringify(row.value)} · ${row.ids.size}`)));
      if(chosen&&!values.has(chosen))control.append(el('option',{value:chosen},chosen+' · 0'));
      control.value=chosen??'';control.onchange=()=>change(control.value);
    }else{
      const list=el('datalist',{id:'facet-'+key},entries.slice(0,200).map(([token])=>el('option',{value:token})));
      control=el('input',{'aria-label':`Filename ${key}`,list:list.id,placeholder:'Any · exact JSON value',value:chosen??''});
      control.onchange=()=>{if(control.value===''||values.has(control.value)){control.setCustomValidity('');change(control.value);}else{control.setCustomValidity('Choose an existing value; put text in double quotes.');control.reportValidity();}};
      facetHost.append(list);
    }
    facetHost.append(el('label',{},key,' ',control));
  }
  for(const [key,value] of propertyFilters)if(!facets.has(key))facetHost.append(button(`${key}: ${value} ×`,()=>{propertyFilters.delete(key);render();}));
  if(propertyFilters.size)facetHost.append(button('Clear properties',()=>{propertyFilters.clear();resetBrowsing();render();}));
}
function resetBrowsing(){rendered=null;galleryScroll.clear();galleryPages.clear();selections.clear();indices.clear();$('main').scrollTop=0;}
function setSelection(members,value) {
  for(const item of members)visibility.set(item.id,value);
  sequenceVisibility.clear();groups.forEach(g=>g.visible=true);if(allGroup)allGroup.visible=true;render();
}
function selectionControl(members,label) {
  const count=members.filter(item=>visibility.get(item.id)!==false).length;
  const check=el('input',{type:'checkbox',checked:members.length>0&&count===members.length,'aria-label':label,onchange:()=>setSelection(members,check.checked)});
  check.indeterminate=count>0&&count<members.length;return check;
}

function galleryItem(g) {
  return g?.items.find(i=>i.id===selections.get(g.id)) || g?.items.find(i=>i.kind==='image'&&cornersFor(i.metadata)) || g?.items[0];
}
function selectItem(item) {
  if(!item)return;
  const g=group();selections.set(g.id,item.id);selectedImages=[item];
  for(const sequence of g.sequences){const index=sequence.items.findIndex(i=>i.id===item.id);if(index>=0)indices.set(sequence.id,index);}
  context(item);
  for(const card of $('content').querySelectorAll('.card')) {
    const selected=card.dataset.fileId===item.id;card.classList.toggle('selected',selected);
    card.querySelector('[data-select-file]')?.setAttribute('aria-pressed',String(selected));
  }
}
function context(item=null) {
  const g=group(),focused=item||(mode==='gallery'?galleryItem(g):selectedImages[0])||galleryItem(g);
  const chosen=item?[item]:mode==='gallery'?[focused]:selectedImages.length?selectedImages:[focused];
  locator.update(g,chosen,items,{mode:rendered?.detail?'detail':mode});
  const host=$('inspector');host.replaceChildren();
  if(!focused){host.append(note('Select a file to inspect its metadata.'));return;}
  const m=focused.metadata;
  host.append(el('h2',{class:'context-title'},basename(focused.name)),el('p',{class:'context-note'},[focused.rootLabel,focused.relativePath||focused.name].filter(Boolean).join('/')));
  if(focused.demo)host.append(el('span',{class:'demo-badge'},'SYNTHETIC DEMO'));
  const row=(label,value)=>host.append(el('div',{class:'context-label'},label),el('div',{class:'context-value'},value));
  row('File',`${focused.kind} · ${formatBytes(focused.size)}`);
  row('Metadata',focused.metadataStatus||'No recognised metadata');
  if(focused.filename){row('Output number',String(focused.filename.index).padStart(6,'0')+(focused.filename.worker===null?'':'.'+focused.filename.worker));for(const [key,value] of Object.entries(focused.filename.properties))row(key,Array.isArray(value)?JSON.stringify(value):String(value));}
  for(const [key,value] of Object.entries(focused.derivedProperties||{}))row(key,Array.isArray(value)?JSON.stringify(value):String(value));
  if(m?.spatial){row('Spatial frame',`${m.spatial.frame||'Unspecified'} · ${m.spatial.units||'units unknown'}`);row('Placement',cornersFor(m)?'Registered image plane':m.spatial.mapping==='camera-focal-plane'?'Camera focal plane only':m.spatial.state||'Unavailable');if(m.spatial.scope)row('Scope',m.spatial.scope);}
  if(focused.spatialWarning)host.append(warning(focused.spatialWarning));
  if(focused.filenameWarning)host.append(warning(focused.filenameWarning));
  if(m)host.append(el('details',{},el('summary',{},'Raw metadata'),el('pre',{class:'metadata-details'},JSON.stringify(m,null,2))));
  if(issues.length)host.append(el('details',{},el('summary',{},`${issues.length} import warnings`),issues.map(issue=>el('p',{class:'context-note'},issue))));
}
function availableModes(g) {
  const positioned=g.items.filter(i=>cornersFor(i.metadata)).length,meshes=g.items.filter(i=>i.kind==='mesh').length;
  return [
    {id:'gallery',label:'Gallery',detail:`${g.items.length} files · browse all`,enabled:true},
    {id:'sequences',label:'Animate',detail:g.sequences.length?`${g.sequences.length} image sequences`:g.items.filter(i=>i.kind==='image').length>1?'Photo series available':'Needs an image sequence',enabled:g.items.filter(i=>i.kind==='image').length>1},
    {id:'xyz',label:'Compare XYZ',detail:xyzSets(g.sequences).length?'X, Y and Z side by side':'Needs matching X, Y and Z',enabled:xyzSets(g.sequences).length>0},
    {id:'3d',label:'3D space',detail:positioned?`${positioned} positioned slices`:meshes?`${meshes} model${meshes===1?'':'s'}`:'Needs positioned images or a model',enabled:positioned+meshes>0},
  ];
}
function groupLabel(g) {
  const first=g.items[0];if(!first||first.demo)return g.name;
  const base=first.rootLabel||'Selected files';
  if(groupBy==='folder'){const path=(first.relativePath||'').split('/').slice(0,-1).join('/');return base+(path?' / '+path:'');}
  if(first.metadata?.group)return base+' / '+first.metadata.group;
  return g.name.replace(/^(?:Collection|Import) \d+\//,'');
}
function contents(g) {
  if(selected==='*'&&groupBy!=='all')return groups.flatMap(part=>contentSections(part).map(section=>({...section,subtitle:[groupLabel(part),section.subtitle].filter(Boolean).join(' · '),label:section.sequence?section.label:groupLabel(part)})));
  return contentSections(g);
}
function contentSections(g) {
  const used=new Set(),sections=[],filter=$('filter').value.toLowerCase();
  const filtered=g.items.filter(i=>i.name.toLowerCase().includes(filter)||g.name.toLowerCase().includes(filter));
  for(const sequence of g.sequences) {
    const members=sequence.items.filter(i=>filtered.some(f=>f.id===i.id));if(!members.length)continue;
    members.forEach(i=>used.add(i.id));
    const axis=sequence.axis,label=axis==='time'?'Time sequence':axis==='index'?'Numbered images':axis.toUpperCase()+' slices';
    sections.push({id:sequence.id,label,subtitle:(sequence.items[0].sequence.label||sequence.items[0].sequence.id)+(sequence.time!==''?' · t='+sequence.time:''),items:members,sequence});
  }
  const rest=filtered.filter(i=>!used.has(i.id));
  if(rest.length)sections.push({id:'other|'+g.id,label:sections.length?'Other files':'Files',subtitle:'',items:rest});
  return sections;
}
function openSequence(sequence) {mode='sequences';indices.set('active-sequence',sequence.id);render();}
function revealSection(index) {
  const target=$('content').querySelector(`[data-section-index="${index}"]`),main=$('main');if(!target)return;
  const top=main.scrollTop+target.getBoundingClientRect().top-main.getBoundingClientRect().top-$('workspace-controls').getBoundingClientRect().height-Math.max(0,parseFloat(getComputedStyle(main).paddingTop)+parseFloat(getComputedStyle($('workspace-controls')).top))-12;
  main.scrollTo({top,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
}
function renderSectionNav(g) {
  const host=$('sectionnav');host.hidden=mode!=='gallery';host.replaceChildren();
  if(mode!=='gallery')return;
  const sections=contents(g);
  host.append(el('span',{class:'contents-label'},'IN THIS COLLECTION'),el('div',{class:'contents-links'},sections.map((section,i)=>button(`${section.label} · ${section.items.length}`,()=>revealSection(i),{'data-jump-section':i,title:section.subtitle||section.label}))));
}
function renderHierarchyTools() {
  const keys=['folder','fileType',...propertyFacets(items).keys()].filter((key,i,list)=>list.indexOf(key)===i);
  hierarchyHost.replaceChildren(el('span',{},'Group hierarchy'));
  for(let level=0;level<3;level++) {
    const select=el('select',{'aria-label':`Grouping level ${level+1}`},el('option',{value:''},level?'None':'Flat collections'),keys.map(key=>el('option',{value:key},key)));
    select.value=hierarchyKeys[level]||'';
    select.onchange=()=>{hierarchyKeys=hierarchyKeys.slice(0,level);if(select.value)hierarchyKeys.push(select.value);hierarchyPath=[];selected='*';resetBrowsing();render();};
    if(!level||hierarchyKeys[level-1])hierarchyHost.append(el('label',{},`Level ${level+1} `,select));
  }
  if(hierarchyPath.length)hierarchyHost.append(button('All groups',()=>{hierarchyPath=[];selected='*';render();}),el('span',{},hierarchyPath.map(([key,value])=>key+'='+value).join(' / ')));
}
function renderHierarchy() {
  for(const branch of $('library').querySelectorAll('[data-group-path]'))hierarchyExpansion.set(branch.dataset.groupPath,branch.open);
  const tree=groupTree(hierarchyItems,hierarchyKeys),filter=$('filter').value.toLowerCase();
  const draw=nodes=>nodes.filter(node=>node.items.some(i=>i.name.toLowerCase().includes(filter))||String(node.label).toLowerCase().includes(filter)).map(node=>{
    const identity=JSON.stringify(node.path),active=identity===JSON.stringify(hierarchyPath);
    const label=String(node.label),row=el('div',{class:'group-top'},selectionControl(node.items,`Display group ${node.path.map(([key,value])=>key+'='+value).join(' / ')}`),button(`${label} · ${node.items.length}`,()=>{hierarchyPath=node.path;selected='*';mode='gallery';resetBrowsing();render();},{class:'group-name','aria-pressed':active}));
    if(!node.children.length)return el('div',{class:'group-item'},row);
    const branch=el('details',{class:'hierarchy-branch','data-group-path':identity},el('summary',{},row),draw(node.children));
    branch.open=hierarchyExpansion.get(identity)??true;return branch;
  });
  $('count').textContent=tree.length;
  $('library').replaceChildren(button('All outputs',()=>{hierarchyPath=[];selected='*';render();},{class:'all-outputs'}),...draw(tree));
}
function renderLibrary() {
  renderHierarchyTools();
  if(hierarchyKeys.length){renderHierarchy();return;}
  const filter=$('filter').value.toLowerCase();$('count').textContent=groups.length;
  $('library').replaceChildren(button('All outputs',()=>{selected='*';hierarchyPath=[];folderLocation=null;render();},{class:'all-outputs','aria-pressed':selected==='*'}),...groups.filter(g=>g.name.toLowerCase().includes(filter)||g.items.some(i=>i.name.toLowerCase().includes(filter))).map(g=>{
    const check=selectionControl(g.items,`Display ${g.name}`);
    const counts=new Map();for(const item of g.items)counts.set(item.kind,(counts.get(item.kind)||0)+1);
    const labels={image:'image',mesh:'model',table:'table',text:'text file',audio:'audio file',video:'video',file:'file'};
    const badges=[...counts].map(([kind,count])=>el('span',{class:'badge'},`${count} ${labels[kind]||kind}${count===1?'':'s'}`));
    if(g.sequences.length)badges.push(el('span',{class:'badge'},`${g.sequences.length} sequences`));
    return el('div',{class:`group-item${g.id===group()?.id?' selected':''}`},el('div',{class:'group-top'},check,button(groupLabel(g),()=>{if(selected!==g.id){selected=g.id;mode='gallery';render();}},{class:'group-name',title:g.name})),!g.visible?el('div',{class:'group-range'},g.range):null,el('div',{class:'group-counts'},badges));
  }));
}
function openFile(item) {
  if(rendered?.mode==='gallery'&&!rendered.detail)galleryScroll.set(rendered.id,$('main').scrollTop);
  dispose();rendered={id:group()?.id,mode,detail:true};selectItem(item);$('sectionnav').hidden=true;const host=el('div');$('content').replaceChildren(host);status(`${item.name} · ${formatBytes(item.size)}`);
  showDetail(host,item,{back:render,cleanups}).catch(error=>{if(host.isConnected)host.append(warning(error.message));});
}
function fileCard(item) {
  const visible=visibility.get(item.id)!==false,selected=galleryItem(group())?.id===item.id;
  const check=selectionControl([item],`Show preview ${basename(item.name)}`);
  const preview=item.kind==='image'?el('img',{src:item.url,alt:basename(item.name),loading:'lazy'}):el('span',{class:'file-symbol'},({mesh:'◇',table:'▤',text:'≡',video:'▷',audio:'♫'})[item.kind]||'▱');
  const card=el('article',{class:`card${selected?' selected':''}`,'data-file-id':item.id});
  if(visible)card.append(button(preview,()=>selectItem(item),{class:'card-preview','data-select-file':item.id,'aria-pressed':selected,'aria-label':`Select ${basename(item.name)}`,ondblclick:()=>openFile(item)}));
  card.append(el('div',{class:'card-info'},el('div',{class:'file-relative-path',title:item.relativePath||item.name},item.relativePath||item.name),el('div',{class:'card-coordinate'},item.sequence?`${item.sequence.axis.toUpperCase()} = ${item.sequence.value} ${item.sequence.units==='unknown'?'':item.sequence.units||''}`:item.kind),el('div',{class:'group-top'},check,button(basename(item.name),()=>selectItem(item),{class:'group-name card-title',title:basename(item.name)})),el('div',{class:'card-bottom'},el('span',{class:'subtle'},item.sequence?.inferred?'Filename order':formatBytes(item.size)),button('Open',()=>openFile(item),{class:'card-open','aria-label':`Open ${basename(item.name)}`}))));
  return card;
}
function gallery(host,g) {
  const sections=contents(g),redraw=[];
  const size=el('input',{type:'range',min:150,max:400,step:25,value:gallerySize,'aria-label':'Gallery image size'});
  size.oninput=()=>{gallerySize=Number(size.value);redraw.forEach(fn=>fn());};
  host.append(el('div',{class:'gallery-controls'},el('label',{},'Preview size',size),note('Checkboxes include or hide previews; filenames remain available.')));
  sections.forEach((section,index)=>{
    const check=selectionControl(section.items,`Show sequence ${section.label}`);
    const block=el('section',{class:'gallery-section','data-section-index':index});
    block.append(el('div',{class:'section-heading'},el('div',{class:'group-top'},check,el('div',{},el('h2',{},section.label),section.subtitle?note(section.subtitle):null)),el('div',{class:'section-actions'},el('span',{class:'badge'},`${section.items.length} ${section.sequence?'images':'files'}`),section.sequence?button('Animate →',()=>openSequence(section.sequence),{'aria-label':`Animate ${section.label}`}):null)));
    host.append(block);
    const grid=el('div',{class:'gallery'});block.append(grid);
    let count=Math.max(120,galleryPages.get(section.id)||120),columns=0;
    const more=button('Show more files',()=>{count+=120;mountRows();},{class:'load-more'});
    const mountRows=()=>{
      columns=Math.max(1,Math.floor((grid.clientWidth+16)/(gallerySize+16)));
      galleryPages.set(section.id,count);grid.replaceChildren();
      const shown=section.items.slice(0,count);
      for(let start=0;start<shown.length;start+=columns){
        const rowItems=shown.slice(start,start+columns),row=Math.floor(start/columns)+1;
        const cards=el('div',{class:'gallery-cards'},rowItems.map(fileCard));cards.style.gridTemplateColumns=`repeat(${columns},minmax(0,1fr))`;
        grid.append(el('div',{class:'gallery-row'},el('label',{class:'row-selection'},selectionControl(rowItems,`Select row ${row} of ${section.label}`),`Row ${row}`),cards));
      }
      more.hidden=count>=section.items.length;more.textContent=`Show next ${Math.min(120,section.items.length-count)} files`;
    };
    block.append(more);mountRows();redraw.push(mountRows);
    const resize=new ResizeObserver(()=>{const next=Math.max(1,Math.floor((grid.clientWidth+16)/(gallerySize+16)));if(next!==columns)mountRows();});resize.observe(grid);cleanups.push(()=>resize.disconnect());
    const observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting)&&count<section.items.length){count+=120;mountRows();}},{root:$('main'),rootMargin:'300px'});observer.observe(more);cleanups.push(()=>observer.disconnect());
  });
  if(!sections.length)host.append(note('No matching files in this folder or collection.'));
}

async function spatial(host,g) {
  const registered=g.items.filter(i=>cornersFor(i.metadata)&&visibility.get(i.id)!==false);
  const frames=new Map();
  for(const item of registered){const s=item.metadata.spatial;if(!s.frame)continue;const key=JSON.stringify([item.scope||'',s.frame,s.units||'unknown']);if(!frames.has(key))frames.set(key,[]);frames.get(key).push(item);}
  const canvas=el('canvas',{class:'scene',tabindex:0,'aria-label':'Registered slice scene. Drag to rotate, Shift-drag to pan, wheel to zoom. Arrow keys rotate, F fits.'}),toolbar=el('div',{class:'scene-toolbar'}),controls=el('div');
  const pane=createPane(canvas,{label:'3D space',cleanups,height:340,key:'spatial'});host.append(pane.root);pane.footer.append(toolbar,el('p',{class:'scene-note'},'Drag rotate · Shift/right-drag pan · Wheel zoom · Arrow keys rotate · F fit'),controls);
  let scene;
  try{scene=createScene(canvas,{onError:e=>{if(host.isConnected)$('notice').replaceChildren(warning(e.message));}});}catch(error){host.append(warning(error.message));return;}
  cleanups.push(()=>scene.dispose());
  const wire=el('input',{type:'checkbox',checked:true,onchange:()=>scene.setWireframe(wire.checked)}),cage=el('input',{type:'checkbox',checked:true,onchange:()=>scene.setBox(cage.checked)});
  toolbar.append(button('Fit',()=>scene.fit()),...['iso','x','y','z'].map(axis=>button(axis.toUpperCase(),()=>scene.view(axis))),el('label',{'data-mesh-option':''},wire,'Mesh wireframe'),el('label',{},cage,'Bounds & axes'));
  // Test / embedding hook exposes state only, never arbitrary file access.
  window.artifactScene=scene;cleanups.push(()=>{if(window.artifactScene===scene)delete window.artifactScene;});
  if(!frames.size){const mesh=g.items.find(i=>i.kind==='mesh'&&visibility.get(i.id)!==false);toolbar.querySelector('[data-mesh-option]').hidden=!mesh;if(mesh){if(mesh.size>64*1024*1024)throw Error('Mesh exceeds the 64 MiB preview limit');const vertices=meshFromBytes(await mesh.bytes(),mesh.name);if(host.isConnected)await scene.setData([],vertices);}return;}
  const frameSelect=el('select',{'aria-label':'Spatial coordinate frame'},[...frames].map(([key,list])=>el('option',{value:key},`${list[0].scope?list[0].scope+' · ':''}${list[0].metadata.spatial.frame} · ${list[0].metadata.spatial.units||'units unknown'}`)));
  if(frames.size>1)toolbar.append(frameSelect);
  let controlsCleanups=[],revision=0;
  cleanups.push(()=>{revision++;controlsCleanups.forEach(fn=>fn());});
  const mountFrame=async()=>{
    const current=++revision;controlsCleanups.forEach(fn=>fn());controlsCleanups=[];controls.replaceChildren();
    const candidates=frames.get(frameSelect.value),ids=new Set(candidates.map(i=>i.id)),s=candidates[0].metadata.spatial;
    const meshes=g.items.filter(i=>i.kind==='mesh'&&visibility.get(i.id)!==false&&(i.scope||'')===(candidates[0].scope||'')&&i.metadata?.spatial?.state==='known'&&i.metadata.spatial.frame===s.frame&&(i.metadata.spatial.units||'unknown')===(s.units||'unknown'));
    let mesh=null;
    if(meshes[0]){try{if(meshes[0].size>64*1024*1024)throw Error('Domain mesh exceeds 64 MiB preview limit');mesh=meshFromBytes(await meshes[0].bytes(),meshes[0].name);}catch(e){controls.append(warning(e.message));}}
    if(current!==revision||!host.isConnected)return;
    const observedBounds=candidates.map(i=>boundsFor(i.metadata)).filter(Boolean);
    const allCorners=candidates.flatMap(i=>cornersFor(i.metadata));
    const bounds=observedBounds.length?[0,1,2,3,4,5].map(i=>observedBounds.reduce((v,b)=>i%2?Math.max(v,b[i]):Math.min(v,b[i]),i%2?-Infinity:Infinity)):[0,1,2].flatMap(axis=>[allCorners.reduce((v,p)=>Math.min(v,p[axis]),Infinity),allCorners.reduce((v,p)=>Math.max(v,p[axis]),-Infinity)]);
    toolbar.querySelector('[data-mesh-option]').hidden=!mesh;
    const update=chosen=>{selectedImages=chosen;context();const planes=chosen.filter(i=>ids.has(i.id)).map(item=>({item,corners:cornersFor(item.metadata),axis:item.sequence?.axis}));scene.setData(planes,mesh,bounds).catch(e=>{if(host.isConnected)$('notice').replaceChildren(warning(e.message));});};
    const seqs=g.sequences.map(seq=>({...seq,items:seq.items.filter(i=>ids.has(i.id))})).filter(seq=>seq.items.length>1&&sequenceVisibility.get(seq.id)!==false);
    const allPlanes=el('input',{type:'checkbox','aria-label':'Show all selected image planes'});
    const sequenceControls=el('div');controls.append(el('label',{},allPlanes,'Show all selected image planes'),sequenceControls);
    let currentChosen=[];const choose=chosen=>{currentChosen=chosen;if(!allPlanes.checked)update(chosen);};
    allPlanes.onchange=()=>{sequenceControls.hidden=allPlanes.checked;update(allPlanes.checked?candidates:currentChosen.length?currentChosen:candidates.slice(0,1));};
    if(seqs.length)mountSequences(sequenceControls,seqs,{xyz:xyzSets(seqs).length>0,cleanups:controlsCleanups,openFile,inspect:context,indices,onSelection:choose,spatialOnly:true});
    else update(candidates.slice(0,1));
    controls.prepend(note(mesh?'Registered textures with the supplied domain mesh.':'Bounds reference · no domain mesh provided.'));
    controls.append(el('details',{class:'view-notes'},el('summary',{},'About spatial placement'),note('Whole viewport images are projected, including backgrounds and annotations. Alpha is preserved; no physical surface or mask is inferred from pixels.')));
  };
  frameSelect.onchange=()=>mountFrame().catch(e=>controls.append(warning(e.message)));await mountFrame();
}
function render() {
  if(rendered?.mode==='gallery'&&!rendered.detail)galleryScroll.set(rendered.id,$('main').scrollTop);
  selectedImages=[];dispose();regroup();renderLibrary();folders.render();localLibrary.render();syncLibraryView();const g=group();rendered={id:g?.id,mode,detail:false};context();const host=el('div');$('content').replaceChildren(host);$('notice').replaceChildren();
  if(issues.length)$('notice').append(note(`${issues.length} import warning${issues.length===1?'':'s'} · open Details to inspect them.`));
  if(!g&&(items.length||folderSources.length)){
    $('title').textContent=folderLocation?(folderLocation.path||folderLocation.label):'All outputs';$('subtitle').textContent=items.length?'No files match this view.':'This folder is empty.';$('modebar').hidden=true;$('sectionnav').hidden=true;
    host.append(el('div',{class:'empty'},el('h2',{},items.length?'No matching files':'Empty folder'),note('Choose a subfolder or change the file type and subfolder settings.'),items.length?button('Show all files',()=>{propertyFilters.clear();$('type-filter').value='all';$('recursive').checked=true;folderLocation=null;selected='*';resetBrowsing();render();}):null));status('No files in this view');return;
  }
  if(!g){$('title').textContent='A clearer view of your data.';$('subtitle').textContent='Open a folder, drop files here, or explore the sample collection.';$('modebar').hidden=true;$('sectionnav').hidden=true;
    host.append(el('div',{class:'empty'},el('div',{class:'empty-icon'},'◈'),el('h2',{},'Files become a place to explore.'),el('p',{},'Bring a folder of results. Browse images, animate sequences and see registered slices in their spatial context.'),button(items.length?'Show all files':'Explore the sample collection',items.length?()=>{propertyFilters.clear();$('type-filter').value='all';$('recursive').checked=true;folderLocation=null;selected='*';render();}:loadDemo,{class:'primary'}),el('div',{class:'welcome-features'},'▦  A gallery for the whole collection','⊞  Coordinate & time sequences','◇  Spatial context from metadata')),note('Nothing is uploaded. Select files using the buttons above or drop a folder anywhere.'));status('Ready to explore');return;
  }
  $('title').textContent=folderLocation?(folderLocation.path||folderLocation.label):selected==='*'?'All outputs':groupLabel(g);$('subtitle').textContent=`${g.items.length} files · ${g.sequences.length} image sequences${g.items.some(i=>i.demo)?' · Synthetic demonstration':''}`;
  const modes=availableModes(g);if(!modes.some(m=>m.id===mode&&m.enabled))mode='gallery';
  const grouping=el('select',{'aria-label':'Collection grouping'},el('option',{value:'auto'},'Automatic groups'),el('option',{value:'folder'},'By folder'),el('option',{value:'all'},'All selected files'));grouping.value=groupBy;grouping.onchange=()=>{groupBy=grouping.value;selected='*';if(groupBy==='folder'){$('library-view').value='folders';}render();};
  const descriptions={gallery:'Browse every file. Select a thumbnail to show its location; Open enlarges it.',sequences:'Choose an image sequence, then step through it or play it.',xyz:'Compare matching X, Y and Z slices. Each coordinate can be chosen independently.','3d':'Rotate the data space and move the slices with the controls below it.'};
  $('modebar').hidden=false;$('modebar').replaceChildren(el('div',{class:'mode-tabs',role:'tablist','aria-label':'Collection view mode'},modes.map(m=>button([el('span',{class:'mode-title'},m.label),el('span',{class:'mode-description'},m.detail)],()=>{mode=m.id;render();},{role:'tab','data-mode':m.id,class:mode===m.id?'active':'','aria-selected':mode===m.id,disabled:!m.enabled,title:m.detail}))),el('div',{class:'mode-explanation'},el('span',{},descriptions[mode]),grouping));
  if([...visibility.values(),...sequenceVisibility.values()].includes(false))$('modebar').querySelector('.mode-explanation').append(button('Restore hidden previews',()=>{visibility.clear();sequenceVisibility.clear();render();},{class:'restore-previews'}));
  renderSectionNav(g);
  rendered={id:g.id,mode,detail:false};
  if(!g.visible){host.append(el('div',{class:'empty'},el('h2',{},'Collection display is off'),note(g.range),button('Show collection',()=>{g.visible=true;render();})));return;}
  if(mode==='gallery')gallery(host,g);
  else if(mode==='sequences'||mode==='xyz'){
    let seqs=g.sequences.filter(s=>sequenceVisibility.get(s.id)!==false).map(s=>({...s,items:s.items.filter(i=>visibility.get(i.id)!==false)})).filter(s=>s.items.length>1);
    if(mode==='sequences'){const photos=photoSeries(g.items.filter(i=>visibility.get(i.id)!==false),g.id);if(photos.items.length>1)seqs.push(photos);}
    if(mode==='xyz'&&!xyzSets(seqs).length||!seqs.length)host.append(note('Sequences are hidden or contain fewer than two visible images. Enable them in Gallery.'));
    else mountSequences(host,seqs,{xyz:mode==='xyz',cleanups,openFile,inspect:context,indices,onSelection:chosen=>{selectedImages=chosen;context();}});
  } else spatial(host,g).catch(error=>{if(host.isConnected)host.append(warning(error.message));});
  $('main').scrollTop=mode==='gallery'?(galleryScroll.get(g.id)||0):0;
  status(`${items.filter(i=>!i.isMetadata).length} artifacts in ${groups.length} collections · ${items.some(i=>i.demo)?'Synthetic sample':'Local files'}`);
}
async function loadDemo(){if(loading)return;clear();setBusy(true);status('Generating synthetic sample…');try{items=await demoItems();await filenameRules.refresh();regroup();render();}catch(e){$('notice').append(warning(e.message));}finally{setBusy(false);}}
async function addFiles(records,{replace=false,label=null,sources=[]}={}) {
  records=[...records].filter(record=>{const blob=record.file||record;return !(record.path||blob.webkitRelativePath||blob.name).split('/').includes('.output-index');});
  if(loading||(!records.length&&!label))return;setBusy(true);status('Reading selected files and validating metadata…');
  const next=[],nextIssues=[];let committed=false;
  try {
    if(records.length>50000)throw Error('Selection exceeds 50,000 files; choose a smaller folder');
    const number=importNumber+1,names=new Set();
    for(const record of records){const blob=record.file||record,name=record.path||blob.webkitRelativePath||blob.name;if(name.split('/').includes('.output-index'))continue;if(names.has(name)){nextIssues.push(`Duplicate selected path skipped: ${name}`);continue;}names.add(name);
      const url=URL.createObjectURL(blob);next.push({id:`local-${serial++}`,name:`Import ${number}/${name}`,scope:`Import ${number}${name.includes('/')?'/'+name.split('/')[0]:''}`,root:`Import ${number}/${name.includes('/')?name.split('/')[0]:'Selected files'}`,rootLabel:name.includes('/')?name.split('/')[0]:'Selected files',relativePath:name.includes('/')?name.slice(name.indexOf('/')+1):name,size:blob.size,url,blob,bytes:()=>blob.arrayBuffer(),text:()=>blob.text()});}
    nextIssues.push(...await attachMetadata(next));
    // Open replaces the session only after the new selection has been read.
    // Add files and drops retain their additive behaviour.
    if(replace||items.some(i=>i.demo))clear({redraw:false});
    importNumber=number;folderSources.push(...sources.map(source=>({...source,root:`Import ${number}/${source.root}`})));if(!records.length&&label&&!sources.length)folderSources.push({root:`Import ${number}/${label}`,label,folders:[]});issues.push(...nextIssues);items.push(...next);committed=true;if(replace)selected='*';await filenameRules.refresh();regroup();render();localLibrary.remember(records,label||next[0]?.rootLabel,sources);
  } catch(error){if(!committed)for(const item of next)URL.revokeObjectURL(item.url);$('notice').append(warning(error.message));}finally{setBusy(false);}
}
async function openRecords(records,{replace=true,label='Local collection',sources=[]}={}) {
  if(loading)return;
  setBusy(true);status('Opening local files and validating metadata…');
  try {
    if(records.length>50000)throw Error('Selection exceeds 50,000 files; choose a smaller folder');
    const batch=`Collection ${++importNumber}`;
    const next=records.map(record=>{
      const url=localURL(record.url);
      return {...record,id:`selected-${serial++}`,name:batch+'/'+record.name,root:batch+'/'+(record.root||record.scope||label),rootLabel:record.rootLabel||label,scope:batch+'/'+(record.scope||label),url,
        bytes:async()=>{const response=await fetch(url);if(!response.ok)throw Error('File changed or is unavailable; reopen the folder');return response.arrayBuffer();},
        text:async()=>{const response=await fetch(url);if(!response.ok)throw Error('File changed or is unavailable; reopen the folder');return response.text();}};
    });
    const nextIssues=await attachMetadata(next);
    if(replace||items.some(item=>item.demo))clear({redraw:false});
    folderSources.push(...sources.map(source=>({...source,root:batch+'/'+source.root})));
    items.push(...next);issues.push(...nextIssues);if(replace)selected='*';await filenameRules.refresh();regroup();render();
  }finally{setBusy(false);}
}
function syncLibraryView() {
  const view=$('library-view').value;
  $('library').hidden=view!=='collections';$('folder-tree').hidden=view!=='folders';$('foldernav').hidden=view!=='folders'&&groupBy!=='folder'&&!folderLocation;localLibrary.render();
}

function confirmClose() {
  if(loading||document.querySelector('.close-confirmation'))return;
  const dialog=el('dialog',{class:'folder-dialog close-confirmation','aria-label':'Close viewer?'});
  const cancel=button('Cancel',()=>dialog.close()),confirm=button('Close viewer',()=>{
    clear();localLibrary.release();dialog.close();
    document.body.classList.add('viewer-closed');
    const reopen=button('Open viewer',()=>{document.body.classList.remove('viewer-closed');render();},{class:'primary'});
    $('content').replaceChildren(el('div',{class:'empty closed-message'},el('h2',{},'Viewer closed'),note('Your files remain on disk.'),reopen));status('Viewer closed');
    if(parent!==window)parent.postMessage({type:'artifact-close'},location.origin);
  },{class:'primary'});
  dialog.append(el('h2',{},'Close viewer?'),el('p',{},'Are you sure you want to close this viewer? Playback will stop and the current collection will be released.'),el('div',{class:'dialog-actions'},cancel,confirm));
  dialog.onclose=()=>{dialog.remove();(document.querySelector('.closed-message button')||$('close-viewer')).focus();};document.body.append(dialog);dialog.showModal();cancel.focus();
}

async function droppedEntries(data) {
  const entries=[...data.items].map(i=>i.webkitGetAsEntry?.()).filter(Boolean),records=[];
  async function visit(entry,path='') {
    if(entry.isDirectory&&entry.name==='.output-index')return;
    if(records.length>=50000)throw Error('Drop exceeds 50,000 files; select a smaller folder');
    if(entry.isFile){const file=await new Promise((resolve,reject)=>entry.file(resolve,reject));records.push({file,path:path+file.name});}
    else if(entry.isDirectory){const reader=entry.createReader();for(;;){const batch=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject));if(!batch.length)break;for(const child of batch)await visit(child,path+entry.name+'/');}}
  }
  if(entries.length){for(const entry of entries)await visit(entry);return records;}
  return [...data.files];
}
$('open-files').onclick=()=>$('files').click();$('open-folder').onclick=()=>localLibrary.choose(true);$('add-folder').onclick=()=>localLibrary.choose(false);
$('type-filter').onchange=()=>{selected='*';resetBrowsing();render();};$('recursive').onchange=()=>{selected='*';resetBrowsing();render();};$('library-view').onchange=()=>{syncLibraryView();if(['recent','runs'].includes($('library-view').value))localLibrary.refresh();};
$('select-all').onclick=()=>setSelection(items.filter(item=>!item.isMetadata),true);$('deselect-all').onclick=()=>setSelection(items.filter(item=>!item.isMetadata),false);
for(const id of ['files','folder'])$(id).onchange=async()=>{await addFiles([...$(id).files],{replace:id==='folder'&&$('folder').dataset.replace!=='false'});$(id).value='';};
$('details-panel').ontoggle=()=>{const open=$('details-panel').open;document.body.classList.toggle('details-open',open);$('show-details').setAttribute('aria-expanded',String(open));};
$('show-details').onclick=()=>{const panel=$('details-panel');panel.open=!panel.open;document.body.classList.toggle('details-open',panel.open);$('show-details').setAttribute('aria-expanded',String(panel.open));};
const locationQuery=matchMedia('(max-width: 1050px)');
const positionLocation=()=>{(locationQuery.matches?$('compact-location'):document.querySelector('.inspector')).prepend($('location'));};
locationQuery.addEventListener('change',positionLocation);positionLocation();
new ResizeObserver(()=>{$('main').style.setProperty('--workspace-height',`${$('workspace-controls').getBoundingClientRect().height}px`);}).observe($('workspace-controls'));
$('close-viewer').onclick=confirmClose;
$('demo').onclick=loadDemo;$('clear').onclick=()=>{if(!loading)clear();};$('filter').oninput=render;
let dragDepth=0;document.addEventListener('dragover',e=>{e.preventDefault();});document.addEventListener('dragenter',e=>{e.preventDefault();dragDepth++;document.body.classList.add('drop-active');});document.addEventListener('dragleave',()=>{if(--dragDepth<=0)document.body.classList.remove('drop-active');});document.addEventListener('drop',async e=>{e.preventDefault();dragDepth=0;document.body.classList.remove('drop-active');try{await addFiles(await droppedEntries(e.dataTransfer));}catch(error){$('notice').append(warning(error.message));}});
window.addEventListener('beforeunload',()=>{filenameRules.cancel();dispose();for(const item of items)if(item.blob)URL.revokeObjectURL(item.url);});
render();
try {
  setBusy(true);
  const collection=new URL(location.href).searchParams.get('collection');
  const response=await fetch(localURL(collection?'api/inventory?id='+encodeURIComponent(collection):'inventory.json'));
  if(response.ok&&response.headers.get('content-type')?.includes('application/json')){
    const records=await response.json();
    const incoming=records.map(record=>({...record,id:`server-${record.id}`,url:localURL(record.url),bytes:async()=>{const r=await fetch(localURL(record.url));if(!r.ok)throw Error('File is no longer available');return r.arrayBuffer();},text:async()=>{const r=await fetch(localURL(record.url));if(!r.ok)throw Error('File is no longer available');return r.text();}}));
    issues.push(...await attachMetadata(incoming));items.push(...incoming);selected='*';await filenameRules.refresh();regroup();render();
  }
} catch(error){$('notice').append(warning(`Could not read the initial collection: ${error.message}`));}finally{setBusy(false);}
const librarySnapshot=await localLibrary.refresh();
if(!folderSources.length&&librarySnapshot?.collections.length){const identity=new URL(location.href).searchParams.get('collection');const collection=identity?librarySnapshot.collections.find(row=>row.id===identity):librarySnapshot.collections[0];if(collection){folderSources=collection.sources||[];render();}}
if(parent===window&&librarySnapshot?.preferences){preferences.apply(librarySnapshot.preferences.theme,{save:false});preferences.setCollapsed(librarySnapshot.preferences.sidebarCollapsed);}
libraryReady=true;setBusy(false);
// Integration state for embedding and browser acceptance checks.
window.artifactViewer={get groups(){return groups;},get items(){return items;},get mode(){return mode;},get issues(){return issues;},openFile,loadDemo,openRecords,setTheme:preferences.apply};
window.addEventListener('message',event=>{if(event.source!==parent||event.origin!==location.origin)return;if(event.data?.type==='artifact-theme')preferences.apply(event.data.theme,{save:false});});
if(parent!==window)parent.postMessage({type:'artifact-ready'},location.origin);
