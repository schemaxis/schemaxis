// Copyright (C) 2026 David L. F. Gaden.
import {h, mount} from '../../lib/dom.mjs';

export function colourRgba(value, palette = {}) {
  if (typeof value === 'string') {
    const name = value.trim().toLowerCase();
    if (name === 'none') return [0,0,0,0];
    if (palette[name]) return [...palette[name]];
    if (/^#[\da-f]{3,4}$|^#[\da-f]{6}$|^#[\da-f]{8}$/.test(name)) {
      let hex = name.slice(1); if (hex.length <= 4) hex = [...hex].map(c => c+c).join('');
      value = hex.match(/../g).map(part => parseInt(part,16)/255);
    } else if (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/.test(name) && Number.isFinite(Number(name)) && Number(name)>=0 && Number(name)<=1) value = Array(3).fill(Number(name));
    else return null;
  }
  if (!Array.isArray(value) || ![3,4].includes(value.length) || !value.every(Number.isFinite)) return null;
  const bytes = value.every(Number.isInteger) && value.some(v => v>1);
  const values = bytes ? value.map(v=>v/255) : [...value];
  if (values.some(v=>v<0 || v>1)) return null;
  return values.length === 3 ? [...values,1] : values;
}

export function colourControl({initial, label, palette, opaque = false}) {
  const colours = palette?.colours || {};
  let value = initial, mode = Array.isArray(initial) ? 'rgb' : 'name', dirty = false;
  const preview = h('span', {class: 'scene-swatch', 'aria-label': `${label} swatch`});
  const note = h('output', {class: 'wb-help', role: 'status'});
  const input = h('input', {class: 'input', 'aria-label': `${label} name`, placeholder: 'steelblue, tab:blue, xkcd:sky blue, #336699…',
    value: typeof initial === 'string' ? initial : '', onInput: () => {dirty = true; update();}});
  const scale = h('select', {class: 'input', 'aria-label': `${label} RGB units`, onChange: () => {
    const previous = scale.dataset.previous || '1', next = scale.value;
    channels.forEach(channel => { if (channel.value !== '' && Number.isFinite(Number(channel.value))) channel.value = String(Number(channel.value)*Number(next)/Number(previous)); });
    scale.dataset.previous = next; dirty = true; update();
  }}, h('option',{value:'1'},'0–1'),h('option',{value:'255'},'0–255'));
  const isBytes = Array.isArray(initial) && initial.every(Number.isInteger) && initial.some(v=>v>1);
  scale.value = isBytes ? '255' : '1'; scale.dataset.previous = scale.value;
  const alpha = h('input', {type:'checkbox',checked: Array.isArray(initial) && initial.length===4,onChange:()=>{dirty=true;update();}});
  const channels = ['Red','Green','Blue','Alpha'].map((name,i)=>h('input',{class:'input',type:'number',step:'any',min:0,
    value:Array.isArray(initial) ? initial[i] ?? (i===3 ? Number(scale.value) : '') : i===3 ? 1 : '',
    'aria-label':`${label} ${name}`,onInput:()=>{dirty=true;update();}}));
  const rgb = h('div', {class:'scene-colour-rgb'},h('label',{},'Units',scale),channels.map((channel,i)=>h('label',{},['Red','Green','Blue','Alpha'][i],channel)),
    opaque ? null : h('label',{},alpha,' Include alpha'));
  const names = h('div', {class:'scene-palette'});
  const filter = h('input',{class:'input',type:'search','aria-label':`${label} palette search`,placeholder:'Search Matplotlib names…',onInput:renderPalette});
  const family = h('select',{class:'input','aria-label':`${label} palette family`,onChange:renderPalette},
    ['All','Base','Tableau','CSS4','xkcd'].map(name=>h('option',{value:name},name)));
  const count = h('small', {class:'wb-help'});
  function renderPalette() {
    const matches = Object.keys(colours).filter(name=>name.includes(filter.value.toLowerCase()) && (family.value==='All'
      || family.value==='xkcd' && name.startsWith('xkcd:') || family.value==='Tableau' && name.startsWith('tab:')
      || family.value==='Base' && name.length===1 || family.value==='CSS4' && name.length>1 && !name.includes(':')));
    count.textContent = `${matches.length} matches${matches.length>100 ? ' · first 100 shown; narrow the search' : ''}`;
    mount(names,matches.slice(0,100).map(name=>h('button',{type:'button',class:'scene-colour-choice',onClick:()=>{
      input.value=name; mode='name'; choice.value=mode; dirty=true; update();
    }},h('span',{class:'scene-swatch',style:{backgroundColor:`rgba(${colours[name].slice(0,3).map(v=>v*255).join(',')},${colours[name][3]})`}}),name)));
  }
  const browser = h('details',{},h('summary',{},'Browse Matplotlib colours'),h('div',{class:'scene-tools'},filter,family),count,names);
  const nameBox = h('div',{},input,browser,h('small',{class:'wb-help'},opaque ? 'Opaque name, hex or grey level. Use Transparent background for PNG alpha.' : 'Names, hex and grey levels use the bundled Matplotlib palette. “none” makes the object transparent.'));
  const choice = h('select',{class:'input','aria-label':`${label} colour format`,onChange:()=>{
    try {value=read();} catch {value=undefined;}
    mode=choice.value;
    if (mode==='rgb') {const converted=colourRgba(value,colours); if(converted) {scale.value='1';scale.dataset.previous='1';channels.forEach((c,i)=>{c.value=String(converted[i]);});alpha.checked=converted[3]!==1;}}
    else if(typeof value==='string') input.value=value;
    dirty=true;update();
  }},h('option',{value:'name'},'Named colour / hex'),h('option',{value:'rgb'},'RGB values'));
  choice.value=mode;
  function read() {
    if(!dirty && initial!==undefined) return structuredClone(initial);
    if(mode==='name') {
      if(!input.value.trim()) throw Error(`Enter a colour for ${label}.`);
      const rgba=colourRgba(input.value,colours);
      if(!rgba) throw Error('Choose a Matplotlib colour name, hex value, grey level or RGB values.');
      if(opaque && rgba[3]!==1) throw Error('Background colour must be opaque. Use Transparent background for transparency.');
      return input.value;
    }
    const values=channels.slice(0,!opaque && alpha.checked ? 4:3).map(c=>c.value.trim()==='' ? NaN : Number(c.value)/Number(scale.value));
    if(!values.every(v=>Number.isFinite(v)&&v>=0&&v<=1)) throw Error(`Enter RGB components in 0–${scale.value}.`);
    return values;
  }
  function update() {
    nameBox.hidden=mode!=='name';rgb.hidden=mode!=='rgb';channels[3].parentElement.hidden=opaque || !alpha.checked;
    try {const colour=colourRgba(read(),colours);preview.style.backgroundColor=colour ? `rgba(${colour.slice(0,3).map(v=>v*255).join(',')},${colour[3]})` : '';
      note.textContent=colour ? `RGBA ${colour.map(v=>Number(v.toFixed(4))).join(', ')}` : 'Not in the Matplotlib palette · value preserved for host validation.';
    } catch(fault) {preview.style.backgroundColor='';note.textContent=fault.message;}
  }
  const element=h('div',{class:'scene-colour-control'},h('div',{class:'scene-tools'},choice,preview,note),nameBox,rgb);
  renderPalette();update();return {element,read};
}
