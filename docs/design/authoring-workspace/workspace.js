/* Interaction prototype. No native execution, network requests or AI calls. */
'use strict';
const $ = id => document.getElementById(id);
const fixture = window.SCHEMAXIS_DESIGN;
const clone = value => JSON.parse(JSON.stringify(value));
let doc = clone(fixture.elbow), revision = 1, format = 'json', valid = true;
let selected = 'dimensions', selection = null, history = [], proposalRevision = null;
let renderedDoc = clone(doc), renderedRevision = 1, setupStep = 0;
let setup = {work: ['CAD'], downloads: false, folder: '~/Applications/Schemaxis', connection: 'later', availability: 'any'};
let toastTimer, yaw = -2.3, pitch = .65, zoom = 1.2, section = false, drag = null;
let endTargets = [];
const names = {freecad:'FreeCAD',paraview:'ParaView',blender:'Blender',octave:'GNU Octave',calc:'LibreOffice Calc',aseprite:'Aseprite',ffmpeg:'FFmpeg',godot:'Godot',qgis:'QGIS'};
const descriptions = {
  circle:'A circular sketch that can feed an extrusion or revolution.',
  rectangle:'A dimensioned rectangular sketch, centred on its local origin.',
  revolve:'Turn a profile around an axis to create a solid.',
  extrude:'Create a solid from a sketch profile along a direction.',
  cut:'Subtract the tool solid from the base solid.',
  fuse:'Join two solids into a single connected result.',
  fillet:'Round selected native edges of a solid.',
  chamfer:'Bevel selected native edges of a solid.',
};
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function notify(message) {
  $('status-message').textContent = message;
  $('toast').textContent = message; $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => {$('toast').hidden = true;}, 4500);
}
function showDialog(id) { $(id).showModal(); }
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => {if(event.target === dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}}));
function upstreamSignature(document) {
  return JSON.stringify({dimensions:document.dimensions,nodes:document.nodes.filter(n=>['outerProfile','innerProfile','outerBend','innerBend','pipe'].includes(n.id))});
}
function selectionCurrent() { return selection && selection.signature === upstreamSignature(doc); }
function resolve(value, document = doc) {
  if(value && typeof value==='object' && !Array.isArray(value) && Object.keys(value).length===1 && typeof value.$document==='string') {
    if(!value.$document.startsWith('/')) throw Error('This design only resolves absolute $document paths.');
    const result=value.$document.slice(1).split('/').reduce((target,key)=>target?.[key.replace(/~1/g,'/').replace(/~0/g,'~')],document);
    if(result===undefined)throw Error('Unknown document reference: '+value.$document);
    return result;
  }
  return value;
}
function draftCheck(candidate) {
  if(!candidate || typeof candidate!=='object' || Array.isArray(candidate))throw Error('The input must be an object.');
  if(candidate.version!=='schemaxis.freecad/1')throw Error('This interactive example edits schemaxis.freecad/1 documents.');
  if(!Array.isArray(candidate.nodes))throw Error('nodes must be an array.');
  const ids=new Map();
  for(const node of candidate.nodes){
    if(!node||typeof node.id!=='string'||!node.id||ids.has(node.id))throw Error('Each node needs a unique, nonempty id.');
    const declaration=fixture.freecad[node.filter];
    if(!declaration)throw Error('Unknown FreeCAD operation: '+String(node.filter));
    for(const [key,field] of Object.entries(declaration.options||{})){
      const spec=field.value;const value=resolve(node.options?.[key] ?? spec.default,candidate);
      if(value===undefined && spec.required)throw Error(node.id+'.'+key+' is required.');
      if(value!==undefined && (spec.type==='number'||spec.type==='integer')){
        if(typeof value!=='number'||!Number.isFinite(value)||(spec.type==='integer'&&!Number.isInteger(value)))throw Error(node.id+'.'+key+' must be a finite '+spec.type+'.');
        if(spec.minimum!==undefined && (value<spec.minimum||(spec.exclusiveMinimum===true&&value===spec.minimum)))throw Error(node.id+'.'+key+' must be '+(spec.exclusiveMinimum?'greater than ':'at least ')+spec.minimum+'.');
        if(spec.maximum!==undefined&&value>spec.maximum)throw Error(node.id+'.'+key+' must be at most '+spec.maximum+'.');
      }
      if(spec.type==='enum' && value!==undefined && !spec.values.includes(value))throw Error(node.id+'.'+key+' must be one of '+spec.values.join(', ')+'.');
    }
    for(const [port,spec] of Object.entries(declaration.inputs||{})){
      const sources=spec.multiple?node.inputs?.[port]:[node.inputs?.[port]];
      if(!Array.isArray(sources)||!sources.length||sources.some(source=>!ids.has(source)))throw Error(node.id+'.inputs.'+port+' must reference earlier compatible features.');
      if(sources.some(source=>ids.get(source)!==spec.kind))throw Error(node.id+'.inputs.'+port+' requires '+spec.kind+' input.');
    }
    ids.set(node.id,declaration.kinds[0]);
  }
  if(candidate.nodes.length && !ids.has(candidate.output))throw Error('output must name an existing feature.');
  if(candidate.dimensions && typeof candidate.dimensions==='object'){
    for(const key of ['bendRadius','outerRadius','innerRadius','bendAngle','meshDeflection']){
      const value=candidate.dimensions[key];
      if(value!==undefined && (typeof value!=='number'||!Number.isFinite(value)||value<=0))throw Error('dimensions.'+key+' must be a positive number.');
    }
    if(candidate.dimensions.innerRadius>=candidate.dimensions.outerRadius)throw Error('For this elbow, innerRadius must be smaller than outerRadius.');
  }
}
function diagnostic(error) {
  valid=!error;$('diagnostic').classList.toggle('error',!!error);
  $('diagnostic').querySelector('.status-mark').textContent=error?'!':'✓';
  $('diagnostic-text').textContent=error?error+' Last usable document retained.':'Draft checks passed · native planning not connected';
  $('export').disabled=!valid;$('preview').disabled=!valid;
  $('properties-panel').querySelectorAll('input,select,button[data-mutation]').forEach(input=>input.disabled=!valid);
  $('ai-apply').disabled=!valid||proposalRevision!==revision;
}
function yaml(value, depth=0) {
  const indent='  '.repeat(depth);
  const scalar=v=>JSON.stringify(v);
  if(Array.isArray(value)){
    if(!value.length)return indent+'[]';
    return value.map(item=>{
      if(item!==null&&typeof item==='object')return indent+'-\n'+yaml(item,depth+1);
      return indent+'- '+scalar(item);
    }).join('\n');
  }
  if(value!==null&&typeof value==='object'){
    if(!Object.keys(value).length)return indent+'{}';
    return Object.entries(value).map(([key,item])=>{
      const safeKey=/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(key)?key:JSON.stringify(key);
      if(item!==null&&typeof item==='object'&&Object.keys(item).length)return indent+safeKey+':\n'+yaml(item,depth+1);
      return indent+safeKey+': '+scalar(item);
    }).join('\n');
  }
  return indent+scalar(value);
}
function lineNumbers(){ $('line-numbers').textContent=Array.from({length:$('source').value.split('\n').length},(_,i)=>i+1).join('\n'); }
function renderSource(){
  $('source').value=format==='json'?JSON.stringify(doc,null,2):'# YAML export preview · editing arrives with the shared YAML loader\n'+yaml(doc)+'\n';
  $('source').readOnly=format==='yaml';$('format-source').disabled=format==='yaml';
  $('source-mode').textContent=format==='yaml'?'Read-only export preview':'Editable source';
  $('document-filename').textContent='pipe.input.'+(format==='yaml'?'yaml':'json');
  lineNumbers();
}
function commit(candidate, fromSource=false) {
  draftCheck(candidate);
  history.push(clone(doc));if(history.length>60)history.shift();
  doc=clone(candidate);revision++;valid=true;
  if(!fromSource)renderSource();
  renderState();diagnostic(null);
}
function edit(mutator){
  if(!valid){notify('Repair the source or Undo before applying another edit.');return;}
  const candidate=clone(doc);
  try{mutator(candidate);commit(candidate);}catch(error){notify(error.message);renderProperties();}
}
function undo(){
  if(!valid){renderSource();diagnostic(null);renderState();notify('Restored the last usable source.');return;}
  if(!history.length)return;
  doc=history.pop();revision++;renderSource();renderState();diagnostic(null);notify('Previous document restored as a new draft revision.');
}
function showPanel(panel){
  document.querySelectorAll('[data-panel]').forEach(button=>{const active=button.dataset.panel===panel;button.classList.toggle('selected',active);button.setAttribute('aria-pressed',active);});
  $('properties-panel').hidden=panel!=='properties';$('assistant-panel').hidden=panel!=='assistant';
}
function selectNode(id){selected=id;showPanel('properties');renderTree();renderProperties();}
function renderTree(){
  const tree=$('feature-tree');tree.replaceChildren();
  for(const node of doc.nodes){
    const button=el('button',undefined,'feature'+(selected===node.id?' selected':''));
    button.append(el('span',({circle:'○',revolve:'↻',extrude:'↑',cut:'−',fuse:'+'})[node.filter]||'◇','feature-kind'),el('span',node.id));
    if(node.id===doc.output)button.append(el('span','OUTPUT','output-label'));
    button.addEventListener('click',()=>selectNode(node.id));tree.append(button);
  }
  $('node-count').textContent=doc.nodes.length;
}
function renderSelection(){
  $('selection-list').replaceChildren();$('selection-count').textContent=selection?'1':'0';
  if(!selection){$('selection-list').append(el('p','Pick an end in the model to give it a reusable name.','empty-note'));$('ai-selection').hidden=true;return;}
  const current=selectionCurrent();const button=el('button',undefined,'selection-item'+(current?'':' stale'));
  button.append(el('span','◎'));const label=el('span','@'+selection.name);label.append(el('small',current?'pipe · illustrative '+selection.end:'Source changed · pick again'));button.append(label);
  button.addEventListener('click',()=>selectNode('selection'));$('selection-list').append(button);
  $('ai-selection').hidden=false;$('ai-selection').textContent='◎ @'+selection.name+(current?' · context selection':' · stale selection');
}
function renderState(){
  $('dirty').hidden=JSON.stringify(doc)===JSON.stringify(fixture.elbow);
  $('undo').disabled=!history.length&&valid;
  $('revision-label').textContent='Draft revision '+revision;
  $('ai-revision').textContent='revision '+revision;
  $('preview-state').textContent=renderedRevision===revision?'Illustration · revision '+renderedRevision:'Earlier illustration · revision '+renderedRevision;
  $('preview-state').style.color=renderedRevision===revision?'':'var(--amber)';
  if(proposalRevision!==null&&proposalRevision!==revision){$('ai-apply').disabled=true;$('proposal-status').textContent='The draft has changed. Generate a fresh example suggestion.';}
  renderTree();renderSelection();renderProperties();
}
function propertyField(parent,label,value,onChange,{unit='',note='',readOnly=false,type='number',min,max,step='any'}={}){
  const wrap=el('div',undefined,'field');const labelEl=el('label',label,'field-label');
  const control=el('div',undefined,'field-control'),input=el('input');input.type=type;input.value=value??'';input.readOnly=readOnly;input.disabled=!valid;
  if(type==='number'){input.step=step;if(min!==undefined)input.min=min;if(max!==undefined)input.max=max;}
  input.setAttribute('aria-label',label);input.addEventListener('change',()=>{if(!input.checkValidity()){input.reportValidity();return;}onChange(type==='number'?Number(input.value):input.value);});
  labelEl.append(control);control.append(input);if(unit)control.append(el('span',unit,'unit'));wrap.append(labelEl);
  if(note)wrap.append(el('small',note,note.startsWith('$document')?'expression':''));parent.append(wrap);return input;
}
function helpCard(parent,title,text){const card=el('div',undefined,'help-card');card.append(el('strong',title),el('p',text));parent.append(card);}
function renderProperties(){
  const panel=$('properties-panel');panel.replaceChildren();
  if(selected==='selection'&&selection){
    panel.append(el('div','GEOMETRY SELECTION','eyebrow'),el('h1',selection.name),el('p','A named end becomes context for commands, forms and AI. This pick belongs to the illustrative elbow.','description'));
    propertyField(panel,'Selection name',selection.name,name=>{if(!/^[A-Za-z][A-Za-z0-9_]*$/.test(name)){notify('Use a name starting with a letter, followed by letters, digits or underscores.');renderProperties();return;}selection.name=name;renderSelection();renderProperties();},{type:'text'});
    const summary=el('div',undefined,'summary-table');
    for(const [key,value]of [['Source feature','pipe'],['Element',selection.end+' annulus'],['State',selectionCurrent()?'Current illustration':'Stale · pick again']]){const row=el('div');row.append(el('span',key),el('strong',value));summary.append(row);}panel.append(summary);
    const group=el('div',undefined,'property-group');group.append(el('h3','Extend this end'));
    const length=propertyField(group,'Extension length',20,()=>{},{unit:'mm',min:.01});
    const button=el('button',selection.end==='inlet'?'Add extension to draft':'Outlet support planned','primary full');button.dataset.mutation='true';button.disabled=!valid||!selectionCurrent()||selection.end!=='inlet';
    button.addEventListener('click',()=>{if(!length.checkValidity()){length.reportValidity();return;}extendInlet(Number(length.value));});group.append(button);panel.append(group);
    helpCard(panel,'Bounded first implementation','The inlet example reuses outerProfile and innerProfile, extrudes them, subtracts the bore and fuses the tube to the pipe. General native face extrusion is future work.');return;
  }
  if(selected==='dimensions'||!doc.nodes.some(node=>node.id===selected)){
    panel.append(el('div','DOCUMENT PARAMETERS','eyebrow'),el('h1','Shape the elbow.'),el('p','Set the dimensions once. The profiles and revolutions follow the same named values.','description'));
    const group=el('div',undefined,'property-group');group.append(el('h3','Dimensions'));
    for(const [key,label,unit]of [['bendRadius','Bend radius','mm'],['outerRadius','Outer radius','mm'],['innerRadius','Inner radius','mm'],['bendAngle','Bend angle','°']]){
      if(doc.dimensions?.[key]===undefined)continue;
      propertyField(group,label,doc.dimensions[key],value=>edit(next=>next.dimensions[key]=value),{unit,min:.001,max:key==='bendAngle'?360:100000,note:key==='bendRadius'?'Shared by the outer and inner profiles.':''});
    }
    panel.append(group);const summary=el('div',undefined,'summary-table');
    for(const [key,value]of [['Wall thickness',doc.dimensions?Number((doc.dimensions.outerRadius-doc.dimensions.innerRadius).toFixed(3))+' mm':'—'],['Output',doc.output],['Document type','FreeCAD solids']]){const row=el('div');row.append(el('span',key),el('strong',String(value)));summary.append(row);}panel.append(summary);
    helpCard(panel,'Parameters, not copied values','The source retains $document references when you edit these dimensions. Preview design refreshes only the illustration; native planning and execution are separate future connections.');return;
  }
  const node=doc.nodes.find(item=>item.id===selected),declaration=fixture.freecad[node.filter];
  panel.append(el('div',node.filter.toUpperCase()+' · FREECAD','eyebrow'),el('h1',node.id),el('p',descriptions[node.filter]||'Declared FreeCAD operation. Options below come from its registered declaration.','description'));
  const group=el('div',undefined,'property-group');group.append(el('h3','Options'));
  for(const [key,field]of Object.entries(declaration.options||{})){
    const spec=field.value,value=node.options?.[key]??spec.default;
    if(value&&typeof value==='object'&&value.$document){
      let effective;try{effective=resolve(value);}catch{effective='unresolved';}
      propertyField(group,key,effective,()=>{},{type:'text',readOnly:true,note:'$document: '+value.$document});
      continue;
    }
    const numeric=spec.type==='number'||spec.type==='integer';
    propertyField(group,key,numeric?value:typeof value==='string'?value:JSON.stringify(value),newValue=>{
      let nextValue=newValue;
      if(!numeric&&spec.type!=='string'&&spec.type!=='enum'){try{nextValue=JSON.parse(newValue);}catch{notify('Enter a JSON value for '+key+'.');renderProperties();return;}}
      edit(next=>{const target=next.nodes.find(item=>item.id===node.id);target.options??={};target.options[key]=nextValue;});
    },{type:numeric?'number':'text',min:spec.minimum,max:spec.maximum,step:spec.type==='integer'?'1':'any',note:spec.values?'Choices: '+spec.values.join(', '):undefined});
  }
  if(!Object.keys(declaration.options||{}).length)group.append(el('p','This operation has no additional options.','micro-copy'));
  panel.append(group);
  if(Object.keys(declaration.inputs||{}).length){
    const inputs=el('div',undefined,'property-group');inputs.append(el('h3','Inputs'));
    const index=doc.nodes.indexOf(node);
    for(const [port,spec]of Object.entries(declaration.inputs)){
      if(spec.multiple){inputs.append(el('p',port+': '+JSON.stringify(node.inputs?.[port]),'micro-copy'));continue;}
      const label=el('label',port+' · '+spec.kind,'field-label'),select=el('select');select.style.width='100%';select.style.marginTop='7px';select.disabled=!valid;
      doc.nodes.slice(0,index).filter(item=>fixture.freecad[item.filter].kinds[0]===spec.kind).forEach(item=>{const option=el('option',item.id);option.value=item.id;select.append(option);});select.value=node.inputs?.[port]||'';
      select.addEventListener('change',()=>edit(next=>next.nodes.find(item=>item.id===node.id).inputs[port]=select.value));label.append(select);inputs.append(label);
    }panel.append(inputs);
  }
  helpCard(panel,'Context-aware suggestions','Input menus contain earlier features of the required kind. Full dependency, geometry and cross-option checks will come from the existing Schemaxis planner.');
}
function pick(end){
  if(!valid||renderedRevision!==revision){notify('Preview the current usable draft before picking an end.');return;}
  selection={name:end,end,signature:upstreamSignature(doc)};selectNode('selection');renderSelection();draw();notify('Illustrative '+end+' selected. Name it or use it to prepare an operation.');
}
function extendInlet(length){
  if(!Number.isFinite(length)||length<=0||!selectionCurrent())return;
  if(['outerExtension','innerExtension','straightPipe','extendedPipe'].some(id=>doc.nodes.some(n=>n.id===id))){notify('This demo extension already exists. Edit its extrusion options or Undo.');return;}
  edit(next=>{
    next.nodes.push(
      {id:'outerExtension',filter:'extrude',options:{length,direction:[0,-1,0]},inputs:{profile:'outerProfile'}},
      {id:'innerExtension',filter:'extrude',options:{length,direction:[0,-1,0]},inputs:{profile:'innerProfile'}},
      {id:'straightPipe',filter:'cut',options:{},inputs:{base:'outerExtension',tool:'innerExtension'}},
      {id:'extendedPipe',filter:'fuse',options:{},inputs:{base:'pipe',tool:'straightPipe'}});
    next.output='extendedPipe';
  });
  selected='outerExtension';renderState();notify('Four existing operations added. Export reproduces the authored graph; native verification remains required.');
}
function preview(){
  if(!valid)return;renderedDoc=clone(doc);renderedRevision=revision;renderState();draw();notify('Illustration refreshed. No native application was executed.');
}
$('source').addEventListener('input',()=>{
  lineNumbers();
  try{const candidate=JSON.parse($('source').value);draftCheck(candidate);if(JSON.stringify(candidate)!==JSON.stringify(doc))commit(candidate,true);else diagnostic(null);}
  catch(error){diagnostic(error.message);$('undo').disabled=false;}
});
$('source').addEventListener('scroll',()=>{$('line-numbers').scrollTop=$('source').scrollTop;});
document.querySelectorAll('[data-format]').forEach(button=>button.addEventListener('click',()=>{
  if(!valid){notify('Repair the JSON draft or Undo before changing format.');return;}
  format=button.dataset.format;document.querySelectorAll('[data-format]').forEach(item=>{item.classList.toggle('selected',item===button);item.setAttribute('aria-pressed',item===button);});renderSource();
}));
document.querySelectorAll('[data-view]').forEach(button=>{if(button.tagName!=='BUTTON')return;button.addEventListener('click',()=>{
  $('source').blur();document.querySelector('.work-surfaces').dataset.view=button.dataset.view;
  document.querySelectorAll('button[data-view]').forEach(item=>{item.classList.toggle('selected',item===button);item.setAttribute('aria-pressed',item===button);});requestAnimationFrame(draw);
});});
document.querySelectorAll('[data-panel]').forEach(button=>button.addEventListener('click',()=>showPanel(button.dataset.panel)));
$('dimensions-select').addEventListener('click',()=>selectNode('dimensions'));
$('document-select').addEventListener('click',()=>selectNode('dimensions'));
$('undo').addEventListener('click',undo);$('preview').addEventListener('click',preview);
$('format-source').addEventListener('click',()=>{if(valid)renderSource();else notify('Repair the JSON before formatting.');});
$('reset').addEventListener('click',()=>{history.push(clone(doc));doc=clone(fixture.elbow);revision++;valid=true;selection=null;selected='dimensions';renderedDoc=clone(doc);renderedRevision=revision;renderSource();renderState();diagnostic(null);draw();notify('Original elbow restored. Undo can recover the previous usable document.');});
$('export').addEventListener('click',()=>{
  if(!valid)return;const data=format==='json'?JSON.stringify(doc,null,2)+'\n':yaml(doc)+'\n';
  const url=URL.createObjectURL(new Blob([data],{type:format==='json'?'application/json':'application/yaml'}));
  const link=el('a');link.href=url;link.download='pipe.input.'+format;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notify('Exported the current '+format.toUpperCase()+' document. Native planning has not run.');
});
$('pick-inlet').addEventListener('click',()=>pick('inlet'));$('pick-outlet').addEventListener('click',()=>pick('outlet'));
$('ai-propose').addEventListener('click',()=>{
  if(!valid){notify('Repair the source before requesting an example proposal.');return;}
  proposalRevision=revision;$('ai-before').textContent='− '+String(doc.dimensions?.bendRadius??'undefined');$('ai-proposal').hidden=false;$('ai-apply').disabled=false;$('proposal-status').textContent='Bound to draft revision '+revision+'. Native verification is still required.';
});
$('ai-apply').addEventListener('click',()=>{
  if(!valid||proposalRevision!==revision){notify('The draft changed. Generate a fresh proposal.');return;}
  edit(next=>{next.dimensions??={};next.dimensions.bendRadius=80;});$('proposal-status').textContent='Applied to the draft. Undo is available; preview still needs refreshing.';notify('Example suggestion applied. No AI service was contacted.');
});
function renderCatalogue(){
  const query=$('catalogue-search').value.toLowerCase();$('adaptor-cards').replaceChildren();
  for(const adaptor of fixture.adaptors.filter(item=>[item.id,...item.keywords].join(' ').toLowerCase().includes(query))){
    const card=el('article',undefined,'adaptor-card'),header=el('header');header.append(el('strong',names[adaptor.id]||adaptor.id),el('small',adaptor.id==='freecad'?'ACTIVE EXAMPLE':'REGISTERED ADAPTOR'));card.append(header,el('p',adaptor.keywords.join(' · ')));
    const button=el('button',adaptor.id==='freecad'?'Return to CAD example':'Explore capabilities');
    button.addEventListener('click',()=>{if(adaptor.id==='freecad'){$('catalogue-dialog').close();return;}let details=card.querySelector('.capability-detail');if(!details){details=el('p',adaptor.execution+' Native installation status is not checked by this prototype.','capability-detail');card.append(details);}else details.hidden=!details.hidden;});
    card.append(button);$('adaptor-cards').append(card);
  }
  if(!$('adaptor-cards').children.length)$('adaptor-cards').append(el('p','No registered adaptor matches that search. Future adaptor ideas do not appear as available capabilities.','description'));
}
$('adaptor-open').addEventListener('click',()=>{renderCatalogue();showDialog('catalogue-dialog');});$('catalogue-search').addEventListener('input',renderCatalogue);
let operation='extrude';
function renderOperations(){
  const query=$('operation-search').value.toLowerCase();$('operation-list').replaceChildren();
  Object.keys(fixture.freecad).filter(name=>name.toLowerCase().includes(query)).forEach(name=>{const button=el('button',name,'operation-choice'+(name===operation?' selected':''));button.addEventListener('click',()=>{operation=name;renderOperations();});$('operation-list').append(button);});
  const declaration=fixture.freecad[operation],detail=$('operation-detail');detail.replaceChildren();
  detail.append(el('div','DECLARATION-DRIVEN SNIPPET','eyebrow'),el('h1',operation),el('p',descriptions[operation]||'Options and input kinds come from the current FreeCAD registry.'));
  const snippet={id:operation+'Feature',filter:operation,options:{}};
  for(const [key,field]of Object.entries(declaration.options||{}))if(field.value.default!==undefined)snippet.options[key]=field.value.default;
  const ports=Object.entries(declaration.inputs||{});
  if(ports.length){snippet.inputs={};for(const [port,spec]of ports){const choices=doc.nodes.filter(node=>fixture.freecad[node.filter].kinds[0]===spec.kind);snippet.inputs[port]=spec.multiple?choices.slice(0,spec.minItems||1).map(node=>node.id):choices.at(-1)?.id??'<choose '+spec.kind+'>';}}
  detail.append(el('pre',JSON.stringify(snippet,null,2)));
  const insert=el('button','Insert into draft','primary');insert.disabled=!valid;
  insert.addEventListener('click',()=>{
    let suffix=1;const node=clone(snippet);while(doc.nodes.some(item=>item.id===node.id))node.id=snippet.id+(suffix++);
    try{const next=clone(doc);next.nodes.push(node);next.output=node.id;commit(next);selected=node.id;renderState();$('operations-dialog').close();notify('Operation inserted. Inspect its arguments before native planning.');}catch(error){notify(error.message);}
  });detail.append(insert,el('p','Illustration supports the elbow dimensions and example inlet extension. Other inserted operations require a real native preview.','micro-copy'));
}
$('add-operation').addEventListener('click',()=>{renderOperations();showDialog('operations-dialog');});$('operation-search').addEventListener('input',renderOperations);
$('command-toggle').addEventListener('click',()=>{const expanded=$('command-body').hidden;$('command-body').hidden=!expanded;$('command-toggle').setAttribute('aria-expanded',expanded);requestAnimationFrame(draw);});
$('command-form').addEventListener('submit',event=>{
  event.preventDefault();const text=$('command').value.trim();
  try{
    if(text==='help'){$('command-result').textContent='Prototype subset:\nset NODE OPTION JSON\nset document dimensions JSON\nundo\npreview\n\nThe production console supports more commands. No native process runs here.';return;}
    if(text==='undo'){undo();$('command-result').textContent='Undo applied to the draft.';return;}
    if(text==='preview'){preview();$('command-result').textContent='Illustration refreshed; native execution is not connected.';return;}
    if(!valid)throw Error('Repair the source or Undo before running an editing command.');
    const match=text.match(/^set\s+(\S+)\s+(\S+)\s+([\s\S]+)$/);if(!match)throw Error('Use help to see the prototype command subset.');
    let value=match[3];if(value.startsWith("'")&&value.endsWith("'"))value=value.slice(1,-1);value=JSON.parse(value);
    const candidate=clone(doc);
    if(match[1]==='document'){if(match[2]!=='dimensions')throw Error('This prototype supports set document dimensions only.');candidate.dimensions=value;}
    else{const node=candidate.nodes.find(item=>item.id===match[1]);if(!node)throw Error('Unknown node '+match[1]);if(!fixture.freecad[node.filter].options[match[2]])throw Error('Unknown option '+match[2]);node.options??={};node.options[match[2]]=value;}
    commit(candidate);$('command-result').textContent='Applied to draft revision '+revision+'. Preview design to refresh the illustration.';$('command').value='';
  }catch(error){$('command-result').textContent=error.message;}
});
const workChoices=[['CAD','Parametric CAD'],['meshes','Meshes & rendering'],['CFD','Scientific data & CFD'],['1D','1D data & signals'],['maps','Maps & geospatial'],['sprites','Images & animation']];
function renderSetup(){
  const area=$('setup-content');area.replaceChildren();
  document.querySelectorAll('[data-step-label]').forEach(item=>item.classList.toggle('active',Number(item.dataset.stepLabel)===setupStep));
  $('setup-back').disabled=setupStep===0;$('setup-progress').textContent='Step '+(setupStep+1)+' of 3';$('setup-next').textContent=setupStep===2?'Finish setup preview':'Continue';
  if(setupStep===0){
    area.append(el('h3','Start with the work you want to do.'),el('p','Choose any that apply. You can add applications later.','description'));
    const choices=el('div',undefined,'setup-choices');for(const [value,label]of workChoices){const row=el('label',undefined,'setup-choice'),input=el('input');input.type='checkbox';input.checked=setup.work.includes(value);input.addEventListener('change',()=>{setup.work=input.checked?[...setup.work,value]:setup.work.filter(item=>item!==value);});row.append(input,el('span',label));choices.append(row);}area.append(choices);
    helpCard(area,'Open to future capabilities','The category catalogue will grow as useful adaptors are implemented. Circuit design and your additional extraction tools are future directions, not advertised capabilities.');
  }else if(setupStep===1){
    area.append(el('h3','Keep existing applications. Add what you need.'),el('p','A production setup checks versions, locations and each distributor’s licence and download terms. Those checks are not connected here.','description'));
    const licenceLabel=el('label','Application availability preference','field-label'),licenceSelect=el('select');
    for(const [value,name]of [['any','Show all licensing models'],['free','Freely available'],['trial','Trial or demo available'],['licensed','Include applications requiring a licence']]){const option=el('option',name);option.value=value;licenceSelect.append(option);}
    licenceSelect.value=setup.availability;licenceSelect.addEventListener('change',()=>{setup.availability=licenceSelect.value;notify('Preference selected for the design. Licence metadata is not connected; the list is not filtered.');});licenceLabel.append(licenceSelect);area.append(licenceLabel);
    const matches=fixture.adaptors.filter(item=>setup.work.some(work=>[item.id,...item.keywords].join(' ').toLowerCase().includes(work.toLowerCase())));
    for(const item of matches){const row=el('div',undefined,'setup-runtime');row.append(el('span',names[item.id]),el('small','Location & licence not checked'));area.append(row);}
    if(!matches.length)area.append(el('p','No categories selected. You can configure applications later.','micro-copy'));
    const field=el('div',undefined,'field'),label=el('label','Managed application folder','field-label'),input=el('input');input.type='text';input.value=setup.folder;input.addEventListener('input',()=>setup.folder=input.value);label.append(input);field.append(label,el('small','Existing installations and project data keep their own locations.'));area.append(field);
    const download=el('label',undefined,'setup-choice'),check=el('input');check.type='checkbox';check.checked=setup.downloads;check.addEventListener('change',()=>setup.downloads=check.checked);download.append(check,el('span','Allow selected applications to be downloaded'));area.append(download);
    area.append(el('p','Design preference only. No files are installed or downloaded.','micro-copy'));
  }else{
    area.append(el('h3','Choose how assistance will connect.'),el('p','Authoring and native execution remain available without AI. Each provider’s supported connection method must be verified during implementation.','description'));
    const label=el('label','Connection method','field-label'),select=el('select');for(const [value,name]of [['later','Set up later'],['agent','Connect a supported local agent'],['api','Connect a model provider API']]){const option=el('option',name);option.value=value;select.append(option);}select.value=setup.connection;select.addEventListener('change',()=>setup.connection=select.value);label.append(select);area.append(label);
    helpCard(area,'Document context, explicit changes','The assistant will receive the context selected for the task and propose edits against a document revision. This prototype collects no credentials and connects to no subscription.');
  }
}
$('setup-open').addEventListener('click',()=>{setupStep=0;renderSetup();showDialog('setup-dialog');});
$('setup-next').addEventListener('click',()=>{if(setupStep<2){setupStep++;renderSetup();}else{$('setup-dialog').close();notify('Setup preview complete. Preferences were not saved and no applications were installed.');}});
$('setup-back').addEventListener('click',()=>{if(setupStep>0){setupStep--;renderSetup();}});
['help-open','guide-open'].forEach(id=>$(id).addEventListener('click',()=>showDialog('guide-dialog')));

// Procedural dimensional study, deliberately separate from native tessellation.
const canvas=$('model'),ctx=canvas.getContext('2d');
function draw(){
  const rect=canvas.getBoundingClientRect();if(!rect.width||!rect.height)return;
  const ratio=window.devicePixelRatio||1;canvas.width=Math.round(rect.width*ratio);canvas.height=Math.round(rect.height*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);
  const w=rect.width,h=rect.height;ctx.clearRect(0,0,w,h);endTargets=[];
  const dim=renderedDoc.dimensions||{};
  const radius=Number(dim.bendRadius),outer=Number(dim.outerRadius),inner=Number(dim.innerRadius),angle=Number(dim.bendAngle)*Math.PI/180;
  if(![radius,outer,inner,angle].every(Number.isFinite)||radius<=0||inner>=outer){ctx.fillStyle='#b1c4b5';ctx.textAlign='center';ctx.fillText('Illustration requires the elbow example dimensions.',w/2,h/2);return;}
  const extension=renderedDoc.nodes.find(n=>n.id==='outerExtension')?.options?.length||0;
  $('model-dimensions').textContent='R'+radius+' · Ø'+(outer*2)+' / Ø'+(inner*2)+' mm';
  document.querySelector('.model-caption strong').textContent=dim.bendAngle+'° pipe elbow';
  const scale=Math.min(w/(radius*2+outer*4),h/(radius*1.45+outer*3))*zoom;
  const centre=[radius*.43,radius*.43-extension*.22,0];
  function project(point){const x=point[0]-centre[0],y=point[1]-centre[1],z=point[2];const x1=x*Math.cos(yaw)-y*Math.sin(yaw),y1=x*Math.sin(yaw)+y*Math.cos(yaw);return [w*.5+x1*scale,h*.56-(z*Math.cos(pitch)-y1*Math.sin(pitch))*scale,z*Math.sin(pitch)+y1*Math.cos(pitch)];}
  function path(points){ctx.beginPath();points.forEach((point,i)=>i?ctx.lineTo(point[0],point[1]):ctx.moveTo(point[0],point[1]));ctx.closePath();}
  // Ground grid is a view aid, not measured geometry.
  ctx.strokeStyle='#6d8b7820';ctx.lineWidth=.6;
  for(let i=-3;i<8;i++){for(const points of [[[i*20,-60,-outer-4],[i*20,140,-outer-4]],[[-60,i*20,-outer-4],[140,i*20,-outer-4]]]){const a=project(points[0]),b=project(points[1]);ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();}}
  const faces=[],around=32,along=38;
  function tubePoint(t,p,r){return [(radius+r*Math.cos(p))*Math.cos(t),(radius+r*Math.cos(p))*Math.sin(t),r*Math.sin(p)];}
  function addFace(points,normal,inside=false,cap=false){
    if(section&&points.reduce((sum,p)=>sum+p[2],0)/points.length>0)return;
    const p=points.map(project);const light=Math.max(0,normal[0]*.3-normal[1]*.3+normal[2]*.85),base=inside?43:77;
    const colour=cap?`rgb(157 192 162)`:`rgb(${base+light*60} ${base+25+light*64} ${base+15+light*50})`;
    faces.push({p,depth:p.reduce((sum,v)=>sum+v[2],0)/p.length,colour,cap});
  }
  for(let i=0;i<along;i++)for(let j=0;j<around;j++){
    const t0=angle*i/along,t1=angle*(i+1)/along,p0=2*Math.PI*j/around,p1=2*Math.PI*(j+1)/around,t=(t0+t1)/2,p=(p0+p1)/2;
    for(const r of [outer,inner])addFace([tubePoint(t0,p0,r),tubePoint(t1,p0,r),tubePoint(t1,p1,r),tubePoint(t0,p1,r)],[Math.cos(t)*Math.cos(p),Math.sin(t)*Math.cos(p),Math.sin(p)],r===inner);
  }
  if(extension>0)for(let j=0;j<around;j++){
    const p0=2*Math.PI*j/around,p1=2*Math.PI*(j+1)/around,p=(p0+p1)/2;
    for(const r of [outer,inner])addFace([[radius+r*Math.cos(p0),0,r*Math.sin(p0)],[radius+r*Math.cos(p0),-extension,r*Math.sin(p0)],[radius+r*Math.cos(p1),-extension,r*Math.sin(p1)],[radius+r*Math.cos(p1),0,r*Math.sin(p1)]],[Math.cos(p),0,Math.sin(p)],r===inner);
  }
  for(const [end,t]of [['inlet',0],['outlet',angle]]){
    const shift=end==='inlet'?-extension:0;
    for(let j=0;j<around;j++){
      const p0=2*Math.PI*j/around,p1=2*Math.PI*(j+1)/around;
      addFace([tubePoint(t,p0,outer),tubePoint(t,p1,outer),tubePoint(t,p1,inner),tubePoint(t,p0,inner)].map(p=>[p[0],p[1]+shift,p[2]]),[0,0,1],false,true);
    }
    endTargets.push({end,point:project([radius*Math.cos(t),radius*Math.sin(t)+shift,0])});
  }
  faces.sort((a,b)=>a.depth-b.depth);
  for(const face of faces){path(face.p);ctx.fillStyle=face.colour;ctx.fill();ctx.strokeStyle=face.colour;ctx.lineWidth=.6;ctx.stroke();}
  for(const target of endTargets){
    const active=selection?.end===target.end, p=target.point;ctx.beginPath();ctx.arc(p[0],p[1],active?8:5,0,Math.PI*2);ctx.fillStyle=active?'#c4f3d0':'#263f33';ctx.fill();ctx.strokeStyle='#ccf0d3';ctx.lineWidth=1.3;ctx.stroke();
    ctx.font='10px ui-monospace,monospace';ctx.textAlign='left';const label=active?'@'+selection.name:target.end;const width=ctx.measureText(label).width;
    ctx.fillStyle='#14251de8';ctx.fillRect(p[0]+12,p[1]-9,width+12,19);ctx.fillStyle='#cae9ce';ctx.fillText(label,p[0]+18,p[1]+4);
  }
}
canvas.addEventListener('pointerdown',event=>{drag={x:event.clientX,y:event.clientY,initialX:event.clientX,initialY:event.clientY,moved:false};canvas.setPointerCapture(event.pointerId);});
canvas.addEventListener('pointermove',event=>{if(!drag)return;const dx=event.clientX-drag.x,dy=event.clientY-drag.y;if(Math.hypot(event.clientX-drag.initialX,event.clientY-drag.initialY)>4)drag.moved=true;if(drag.moved){yaw+=dx*.008;pitch=Math.max(-1.3,Math.min(1.3,pitch+dy*.008));draw();}drag.x=event.clientX;drag.y=event.clientY;});
canvas.addEventListener('pointerup',event=>{if(drag&&!drag.moved){const r=canvas.getBoundingClientRect(),x=event.clientX-r.left,y=event.clientY-r.top;const target=endTargets.find(item=>Math.hypot(x-item.point[0],y-item.point[1])<30);if(target)pick(target.end);}drag=null;});
canvas.addEventListener('pointercancel',()=>drag=null);
canvas.addEventListener('wheel',event=>{event.preventDefault();zoom=Math.max(.4,Math.min(2.5,zoom*Math.exp(-event.deltaY*.001)));draw();},{passive:false});
$('fit').addEventListener('click',()=>{yaw=-2.3;pitch=.65;zoom=1.2;draw();});
$('section').addEventListener('click',()=>{section=!section;$('section').classList.toggle('selected',section);$('section').setAttribute('aria-pressed',section);draw();});
new ResizeObserver(draw).observe(canvas);
renderSource();renderState();diagnostic(null);draw();
