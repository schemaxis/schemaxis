// Copyright (C) 2026 David L. F. Gaden.
// Adaptor-declared presentation widgets. Values remain ordinary document fields.
import {h, mount} from '../../lib/dom.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {spatialInput, expressionValue} from '../../editor/spatial-input.mjs';
import {escapeSegment} from '../../editor/json-pointer.mjs';
import {pipelineChoices} from './authoring-defaults.mjs';
import {subsetChips} from './subset-chips.mjs';
import {colourControl} from './colour-control.mjs';
import {quotedName} from '../spatial/volume-model.mjs';

const button = (label, run, props = {}) => h('button', {type:'button',class:'button small',onClick:run,...props},label);
const field = (label, element) => h('label',{class:'scene-field'},h('span',{},label),element);
const plain = value => value && typeof value==='object' && !Array.isArray(value) && !expressionValue(value) && !value.$fill;
const withoutWidget = spec => {const result={...spec};delete result['x-studio-control'];return result;};

export function presentationControl(args) {
  const {spec,initial,label,definitions,ctx,path,render}=args;
  const widget=spec['x-studio-control'];
  switch(widget?.kind) {
    case 'colour': return colourControl({initial,label,palette:definitions[widget.palette]?.['x-studio-palette'],opaque:widget.opaque});
    case 'pipeline-map': return pipelineMap(args);
    case 'appearance': return appearance(args);
    case 'data-field': return dataField(args);
    case 'camera': return camera(args);
    case 'frame': {
      const input=spatialInput({label,value:initial,'data-spatial-path':path});
      const nodes=pipelineChoices(args.documentValue,'data',ctx?.operationKinds);
      const select=h('select',{class:'input','aria-label':`${label} pipeline object`},h('option',{value:''},'Choose a pipeline object…'),
        nodes.map(node=>h('option',{value:node.id},node.id)));
      const assign=value=>{input.element.value=typeof value?.$expr==='string' ? value.$expr : JSON.stringify(value);input.element.dispatchEvent(new Event('input',{bubbles:true}));};
      const error=h('p',{role:'alert',class:'operation-error'});
      const element=h('div',{class:'scene-frame'},input.element,h('div',{class:'scene-tools'},select,
        button('Use object bounds',()=>{if(select.value)assign({$expr:`extents(${quotedName(select.value)})`});}),
        ctx?.createVolume ? button('New volume…',async()=>{try{const value=await ctx.createVolume();if(value)assign(value);}catch(fault){error.textContent=fault.message;}}):null),
        h('p',{class:'wb-help'},'Use a linked Spatial box or object bounds. The frame follows later changes; it does not crop geometry. For all visible objects, leave this setting out.'),error);
      return {element,read:()=>input.element.value.trim() ? input.read() : {$fill: label.replace(/[^A-Za-z0-9_-]/g,'_'), label, type:'bounds', required:true}};
    }
    case 'number-pair': {
      const inputs=(widget.labels||['First','Second']).map((name,i)=>spatialInput({label:`${label} ${name}`,value:initial?.[i],'data-spatial-path':`${path}/${i}`}));
      const presets=widget.presets ? h('select',{class:'input','aria-label':`${label} preset`,onChange:event=>{
        if(event.target.value)JSON.parse(event.target.value).forEach((v,i)=>{inputs[i].element.value=String(v);});
      }},h('option',{value:''},'Custom size'),widget.presets.map(value=>h('option',{value:JSON.stringify(value)},value.join(' × ')))):null;
      return {element:h('div',{class:'scene-number-pair'},presets,inputs.map((input,i)=>field(widget.labels[i],input.element))),read:()=>inputs.map((input,i)=>input.element.value.trim() ? input.read() : {$fill:(label+'_'+i).replace(/[^A-Za-z0-9_-]/g,'_'),label:label+' '+widget.labels[i],type:'number',required:true})};
    }
    case 'sections': return sections(args);
    default:return null;
  }
}

function sections({spec,initial,label,ctx,path,render}) {
  const seed=plain(initial)?initial:{};
  const controls=new Map();
  for(const [key,raw] of Object.entries(spec.properties)) {
    const required=spec.required?.includes(key);
    const included=required || Object.hasOwn(seed,key) || !ctx?.existing && spec['x-studio-control'].includeByDefault?.includes(key);
    const enabled=h('input',{type:'checkbox',checked:included,disabled:required,'aria-label':`Include ${label}.${key}`});
    const nested=render(raw,`${label}.${key}`,seed[key],ctx,`${path}/${escapeSegment(key)}`);
    nested.element.hidden=!included;
    enabled.addEventListener('change',()=>{nested.element.hidden=!enabled.checked;});
    const heading=nested.element.querySelector(':scope > .operation-field-label');
    const toggle=required?null:h('div',{class:'scene-enable'},h('label',{},enabled,` ${raw.title||key}`),heading?.querySelector('button'));
    if(toggle && heading)heading.hidden=true;
    controls.set(key,{enabled,nested,element:h('div',{class:'scene-section-field'},toggle,nested.element)});
  }
  const assigned=new Set(spec['x-studio-control'].sections.flatMap(section=>section.fields));
  const element=h('div',{class:'scene-sections'},[...controls].filter(([key])=>!assigned.has(key)).map(([,row])=>row.element),
    spec['x-studio-control'].sections.map((section,index)=>{
      const simple=section.fields.length===1 && (spec.properties[section.fields[0]]?.title||section.fields[0]).toLowerCase()===section.title.toLowerCase();
      return h(simple?'section':'details',{class:'scene-section',...(!simple ? {open:index<2 || section.fields.some(key=>Object.hasOwn(seed,key))} : {})},
        simple?null:h('summary',{},section.title),section.fields.map(key=>controls.get(key)?.element));
    }));
  return {element,read:()=>({...Object.fromEntries(Object.entries(seed).filter(([key])=>!controls.has(key))),
    ...Object.fromEntries([...controls].filter(([,row])=>row.enabled.checked).map(([key,row])=>[key,row.nested.read()]))})};
}

function pipelineMap({spec,initial,label,documentValue,definitions,ctx,path,render}) {
  const saved=Object.assign(Object.create(null),plain(initial)?structuredClone(initial):{});
  const widget=spec['x-studio-control'];
  let choices=pipelineChoices(documentValue,widget.nodeKind,ctx?.operationKinds);
  // Overrides may only target visible members of their own scene, never another scene.
  const scenePath=path.match(/^(.*)\/appearances(?:\/|$)/)?.[1];
  const baseVisible=()=>ctx?.sceneVisible?.(scenePath) || {};
  if(widget.overrides)choices=choices.filter(node=>Object.hasOwn(baseVisible(),node.id));
  const rows=h('div',{class:'scene-object-list'}), batch=new Set();
  const status=h('p',{class:'wb-help',role:'status'}), error=h('p',{class:'operation-error',role:'alert'});
  async function edit(id) {
    const node=choices.find(node=>node.id===id);
    const inherited=widget.overrides ? baseVisible()[id] : undefined;
    const nested=render(spec.additionalProperties,`${label}.${id}`,saved[id]??{},
      {...ctx,appearanceNode:id,appearanceOperation:node?.filter,appearanceBase:inherited,appearanceOverride:widget.overrides},`${path}/${escapeSegment(id)}`);
    const faults=h('p',{class:'operation-error',role:'alert'});
    const answer=await openDialog({title:`Appearance · ${id}`,wide:true,enterSubmits:false,content:h('div',{class:'scene-appearance-dialog'},
      widget.overrides?h('p',{class:'wb-help'},'Only included settings override the base appearance. Omitted settings inherit.'):null,nested.element,faults),
      actions:[{label:'Cancel',run:()=>null},{label:'Apply appearance',primary:true,run:()=>{
        try{return {value:nested.read()};}catch(fault){faults.textContent=fault.message;return false;}
      }}]});
    if(answer && rows.isConnected){saved[id]=answer.value;draw();}
  }
  const picker=subsetChips({choices:choices.map(node=>({id:node.id,label:`${node.id} · ${node.filter||'Object'}`})),
    initial:Object.keys(saved),label,onChange:ids=>{ids.forEach(id=>{saved[id]??={};});draw();if(!widget.overrides)ctx?.visibilityListeners?.forEach(listener=>listener());}});
  function draw() {
    const ids=picker.read();
    status.textContent=ids.length ? `${ids.length} ${widget.overrides?'objects with overrides':'visible objects'}` : widget.overrides?'No overrides · use the base appearance.':'No objects visible. Images and glTF need visible geometry.';
    mount(rows,ids.map(id=>{
      const value=saved[id]??{},linked=expressionValue(value)||value.$fill;
      const summary=linked?'Linked value':value.field?`${value.field[1]} · ${value.field[0]==='CELLS'?'Cell data':'Point data'}`
        :Object.hasOwn(value,'colour')?JSON.stringify(value.colour):widget.overrides?'Inherit base appearance':'Default appearance';
      return h('div',{class:'scene-object-row'},h('label',{},h('input',{type:'checkbox',checked:batch.has(id),'aria-label':`Batch appearance ${id}`,onChange:event=>event.target.checked?batch.add(id):batch.delete(id)}),
        h('strong',{},id)),h('span',{class:'wb-help'},summary),button('Appearance…',()=>void edit(id),{'aria-label':`Edit appearance ${id}`}));
    }));
  }
  const copy=button('Copy settings to checked objects…',async()=>{
    error.textContent='';
    const ids=picker.read(), targets=ids.filter(id=>batch.has(id));
    if(!targets.length){error.textContent='Check the objects whose appearance you want to change.';return;}
    const source=h('select',{class:'input','aria-label':'Copy appearance from'},ids.filter(id=>plain(saved[id]??{})).map(id=>h('option',{value:id},id)));
    const keys=h('div',{class:'scene-tools'});let toggles=[];
    function update(){toggles=Object.keys(saved[source.value]||{}).map(key=>({key,input:h('input',{type:'checkbox','aria-label':`Copy ${key}`})}));mount(keys,toggles.map(row=>h('label',{},row.input,row.key)));}
    source.addEventListener('change',update);update();
    const result=await openDialog({title:'Copy selected appearance settings',content:h('div',{},source,keys,h('p',{class:'wb-help'},'Only checked keys are copied. Other settings stay unchanged.')),
      actions:[{label:'Cancel',run:()=>null},{label:'Copy settings',primary:true,run:()=>({source:source.value,keys:toggles.filter(row=>row.input.checked).map(row=>row.key)})}]});
    if(!result || !rows.isConnected)return;
    const textOperations=spec.additionalProperties['x-studio-control']?.textOperations||[];
    const kind=id=>textOperations.includes(choices.find(node=>node.id===id)?.filter);
    if(targets.some(id=>!plain(saved[id]??{}) || kind(id)!==kind(result.source))){error.textContent='Copy between objects of the same appearance type; linked values must be edited explicitly.';return;}
    const values=structuredClone(saved[result.source]||{});
    targets.forEach(id=>{saved[id]??={};result.keys.forEach(key=>{saved[id][key]=structuredClone(values[key]);});});draw();
  });
  const element=h('div',{class:'scene-pipeline-map'},picker.element,status,rows,copy,error);
  if(widget.overrides)ctx?.visibilityListeners?.add(()=>{
    if(!element.isConnected)return;
    choices=pipelineChoices(documentValue,widget.nodeKind,ctx?.operationKinds).filter(node=>Object.hasOwn(baseVisible(),node.id));
    picker.setChoices(choices.map(node=>({id:node.id,label:`${node.id} · ${node.filter||'Object'}`})));draw();
  });
  draw();return {element,read:()=>Object.fromEntries(picker.read().map(id=>[id,structuredClone(saved[id]??{})]))};
}

const FIELD_KEYS=['field','component','range','preset','legend','legendTitle','logScale'];
function appearance({spec,initial,label,documentValue,ctx,path,render}) {
  const seed=plain(initial)?structuredClone(initial):{},policy=spec['x-studio-control'];
  const node=documentValue.nodes?.find(node=>node.id===ctx?.appearanceNode);
  const text=policy.textOperations.includes(ctx?.appearanceOperation||node?.filter);
  const permitted=text?policy.textKeys:policy.geometryKeys;
  const inherited=ctx?.appearanceBase||{};
  let mode=Object.hasOwn(seed,'field')?'field':ctx?.appearanceOverride?'inherit':'solid', switched=false;
  const unknown=Object.fromEntries(Object.entries(seed).filter(([key])=>!permitted.includes(key)));
  const commonKeys=permitted.filter(key=>key!=='colour'&&!FIELD_KEYS.includes(key));
  const common=render({type:'object',additionalProperties:false,'x-studio-control':{kind:'sections',sections:[{title:text?'Text settings':'Surface settings',fields:commonKeys}]},properties:Object.fromEntries(commonKeys.map(key=>[key,spec.properties[key]]))},label,Object.fromEntries(Object.entries(seed).filter(([key])=>commonKeys.includes(key))),ctx,path);
  const colourEnabled=h('input',{type:'checkbox',checked:Object.hasOwn(seed,'colour'),'aria-label':`Include ${label}.colour`});
  const colour=render(spec.properties.colour,`${label}.colour`,seed.colour,ctx,`${path}/colour`);
  colour.element.hidden=!colourEnabled.checked;
  colourEnabled.addEventListener('change',()=>{colour.element.hidden=!colourEnabled.checked;});
  const solid=h('div',{},h('label',{},colourEnabled,ctx?.appearanceOverride?' Override solid colour':' Set solid colour (otherwise use default)'),colour.element);
  const fieldSpec={type:'object',additionalProperties:false,properties:Object.fromEntries(FIELD_KEYS.filter(key=>key!=='field').map(key=>[key,spec.properties[key]]))};
  let inspectedField;
  function inspectedRange() {
    if(!inspectedField)return null;
    const selected=array.read();
    const info=inspectedField.observation?.fields?.[selected[0]]?.[selected[1]];
    const included=options.element.querySelector('input[type=checkbox][aria-label$=".component"]')?.checked;
    const component=options.element.querySelector('input[type=text][aria-label$="field settings.component"]');
    const index=included ? Number(component?.value) : -1;
    if(!Number.isInteger(index) || included && !component?.value.trim())return null;
    return index===-1 ? info?.range : info?.componentRanges?.[index];
  }
  function updateRange() {
    const range=inspectedRange();rangeButton.disabled=!range;
    rangeButton.title=range ? 'Copy this array component’s range from the current inspection as fixed numbers.' : 'Inspect this array and choose a literal component to copy its range.';
  }
  const rangeButton=button('Use inspected range',()=>{
    const range=inspectedRange();if(!range)return;
    const enable=options.element.querySelector('input[aria-label$=".range"]');
    if(enable && !enable.checked)enable.click();
    for(const [i,name] of ['Minimum','Maximum'].entries()){
      const input=options.element.querySelector(`[aria-label$=".range ${name}"]`);
      if(input){input.value=String(range[i]);input.dispatchEvent(new Event('input',{bubbles:true}));}
    }
  },{disabled:true});
  const array=render(spec.properties.field,`${label}.field`,seed.field||inherited.field,{...ctx,onInspected:data=>{
        inspectedField=data;updateRange();
      }},`${path}/field`);
  const options=render(fieldSpec,`${label} field settings`,seed,ctx,path);
  for(const event of ['input','change']) {
    array.element.addEventListener(event,updateRange);
    options.element.addEventListener(event,updateRange);
  }
  const data=h('div',{},array.element,rangeButton,options.element,h('p',{class:'wb-help'},'Without a fixed range, each visit uses its data range. Use inspected range copies fixed numbers from the current inspection. Component −1 means magnitude. Preset names are checked by ParaView.'));
  const choose=h('select',{class:'input','aria-label':`${label} Colour by`,onChange:()=>{mode=choose.value;switched=true;display();}},
    ctx?.appearanceOverride?h('option',{value:'inherit'},'Inherit base colouring'):null,h('option',{value:'solid'},'Solid colour'),h('option',{value:'field'},'Data field'));
  choose.value=mode;
  const warning=h('p',{class:'wb-help'});
  function display(){solid.hidden=mode==='field';data.hidden=mode!=='field';warning.textContent=mode==='solid' && ctx?.appearanceOverride && inherited.field
    ? 'This variant inherits a data field. The existing format cannot remove it; use a separate scene for solid colouring.' : '';
  }
  const element=h('div',{class:'scene-appearance'},text?null:field('Colour by',choose),solid,text?null:data,common.element,warning,
    Object.keys(unknown).length?h('p',{class:'wb-help'},`Existing additional settings retained: ${Object.keys(unknown).join(', ')}. Use JSON editing to change them.`):null);
  display();if(text)solid.hidden=false;
  return {element,read:()=>{
    const result={...unknown,...common.read()};
    // Preserve all field-related values when merely opening the editor.
    if(!switched && !text)FIELD_KEYS.filter(key=>Object.hasOwn(seed,key)).forEach(key=>{result[key]=structuredClone(seed[key]);});
    if(colourEnabled.checked)result.colour=colour.read();
    if(!text && mode==='field')Object.assign(result,options.read(),{field:array.read()});
    if(!text && mode==='solid' && switched){
      if(ctx?.appearanceOverride && inherited.field)throw Error('A variant cannot remove an inherited data field. Create a separate scene for solid colouring.');
      FIELD_KEYS.forEach(key=>delete result[key]);
    }
    if(!text && mode==='inherit' && switched)FIELD_KEYS.forEach(key=>delete result[key]);
    return result;
  }};
}

function dataField({initial,label,ctx}) {
  let fields=null, inspected=false, ticket=0;
  const status=h('p',{class:'wb-help',role:'status'},'Type an array name, or ask the application for fields on this object.');
  const listId='scene-fields-'+Math.random().toString(36).slice(2);
  const list=h('datalist',{id:listId});
  const array=h('input',{class:'input',list:listId,'aria-label':`${label} Array`,value:initial?.[1]||'',placeholder:'p, U, …',onInput:update});
  const association=h('select',{class:'input','aria-label':`${label} Association`,onChange:update},h('option',{value:'CELLS'},'Cell data'),h('option',{value:'POINTS'},'Point data'));
  association.value=initial?.[0]||'CELLS';
  function update(){
    const names=fields?.[association.value];
    mount(list,Object.keys(names||{}).filter(name=>names[name].numeric!==false).map(name=>h('option',{value:name})));
    if(inspected){const info=names?.[array.value];status.textContent=info
      ? `From this object's inspected data · ${info.components} components${info.range ? ' · range '+info.range.join(' to '):''}`
      : `From this object's inspected data · ${Object.keys(names||{}).length} arrays${array.value?' · selected name is not in this list; it is retained':''}`;}
  }
  const ask=button('Ask the application',async()=>{
    const current=++ticket;ask.disabled=true;status.textContent='Inspecting this object and its upstream data…';
    try {
      if(!ctx?.appearanceNode||!ctx.inspectNode)throw Error('Choose a pipeline object first.');
      const data=await ctx.inspectNode(ctx.appearanceNode,true);
      if(current!==ticket||!element.isConnected)return;
      fields=data.observation?.fields||data.fields||{};inspected=true;update();ctx.onInspected?.(data);
    }catch(fault){if(current===ticket)status.textContent=fault.message;}finally{ask.disabled=false;}
  });
  const element=h('div',{class:'scene-data-field'},field('Association',association),field('Array',array),list,ask,status);
  return {element,read:()=>{if(!array.value.trim())return {$fill:label.replace(/[^A-Za-z0-9_-]/g,'_'),label,type:'json',required:true};return [association.value,array.value];}};
}

function camera({spec,initial,label,ctx,path,render}) {
  const seed=plain(initial)?initial:{};
  const presets=[['+X',[1,0,0],[0,0,1]],['−X',[-1,0,0],[0,0,1]],['+Y',[0,1,0],[0,0,1]],['−Y',[0,-1,0],[0,0,1]],
    ['+Z',[0,0,1],[0,1,0]],['−Z',[0,0,-1],[0,1,0]],['Isometric',[1,1,1],[0,0,1]]];
  let nested;
  const slot=h('div');
  const schema={...withoutWidget(spec),'x-studio-control':{kind:'sections',sections:[
    {title:'View & framing',fields:['direction','up','parallel','bounds','padding']},
    {title:'Advanced camera settings',fields:['focalPoint','scale','distance']}]}};
  function rebuild(value){nested=render(schema,label,value,ctx,path);mount(slot,nested.element);}
  rebuild(seed);
  const error=h('p',{class:'operation-error',role:'alert'});
  const element=h('div',{class:'scene-camera'},h('p',{class:'wb-help'},'View from a direction; frame all visible geometry or choose a linked Spatial box. +Z and −Z views use +Y as up.'),
    h('div',{class:'scene-tools','aria-label':`${label} view directions`},presets.map(([name,direction,up])=>button(name,()=>{
      try{const value=nested.read();rebuild({...value,direction,up});error.textContent='';}catch(fault){error.textContent=fault.message;}
    }))),slot,error);
  return {element,read:()=>nested.read()};
}
