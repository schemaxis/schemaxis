export function el(tag,attrs={},...children) {
  const node=document.createElement(tag);
  for(const [key,value] of Object.entries(attrs)) {
    if(key.startsWith('on') && typeof value==='function')node.addEventListener(key.slice(2),value);
    else if(key==='class')node.className=value;
    else if(key==='checked'||key==='disabled'||key==='hidden')node[key]=Boolean(value);
    else if(value!==undefined && value!==null)node.setAttribute(key,String(value));
  }
  for(const child of children.flat(Infinity))if(child!==undefined&&child!==null)node.append(child instanceof Node?child:document.createTextNode(String(child)));
  return node;
}
export const button=(label,action,attrs={})=>el('button',{type:'button',onclick:action,...attrs},label);
export const note=text=>el('p',{class:'subtle'},text);
export const formatNumber=n=>Number.isFinite(n)?Number(n.toPrecision(6)).toLocaleString('en-CA',{maximumFractionDigits:6}):'—';
export const formatBytes=n=>n<1024?`${n} B`:n<1048576?`${(n/1024).toFixed(1)} KiB`:`${(n/1048576).toFixed(1)} MiB`;
export function warning(text){return el('div',{class:'warning'},text);}
export async function boundedText(item,limit=4*1024*1024) {
  if(item.size===0)return '';
  if(item.blob)return item.blob.slice(0,limit).text();
  const response=await fetch(item.url,{headers:{Range:`bytes=0-${limit-1}`}});
  if(!response.ok)throw Error('Unable to read selected file');
  return response.text();
}
export function transport(step,cleanups,label='Sequence',options={}) {
  let timer=null,direction=1,playing=false;
  const loop=el('select',{'aria-label':`${label} playback mode`},el('option',{value:'once'},'Once'),el('option',{value:'repeat',selected:''},'Repeat'),el('option',{value:'oscillate'},'Oscillate'));
  const speed=el('input',{type:'number',min:1,max:30,step:1,value:4,'aria-label':`${label} frames per second`,class:'fps'});
  const toggle=button('▶ Play',()=>playing?pause():play(1),{'aria-label':`${label} play forward`});
  const reverse=button('◀ Play backward',()=>play(-1),{'aria-label':`${label} play backward`});
  function stop() {
    clearInterval(timer);timer=null;playing=false;
    toggle.textContent='▶ Play';toggle.setAttribute('aria-label',`${label} play forward`);
    reverse.setAttribute('aria-pressed','false');
  }
  function pause(){stop();options.onPause?.();}
  const rate=()=>1000/Math.max(1,Math.min(30,Number(speed.value)||4));
  function tick(){
    const result=step(direction,loop.value);if(result?.direction)direction=result.direction;
    if(result?.stopped){stop();return;}
    playing=true;toggle.textContent=direction<0?'Ⅱ Pause ◀':'Ⅱ Pause';toggle.setAttribute('aria-label',`${label} pause`);
    reverse.setAttribute('aria-pressed',String(direction<0));
  }
  function play(value){options.beforePlay?.();stop();direction=value;tick();if(playing)timer=setInterval(tick,rate());}
  speed.onchange=()=>{if(playing){clearInterval(timer);timer=setInterval(tick,rate());}};
  cleanups.push(stop);
  const settings=el('details',{class:'playback-options'},el('summary',{},'Playback options'),el('div',{class:'playback-settings'},reverse,el('label',{},'At end',loop),el('label',{},'Speed',speed,'fps')));
  const root=el('div',{class:'transport'},options.caption?el('span',{class:'transport-caption'},options.caption):null,
    button('‹',()=>{pause();step(-1,'once');},{'aria-label':`${label} previous frame`,title:'Previous image'}),toggle,
    button('›',()=>{pause();step(1,'once');},{'aria-label':`${label} next frame`,title:'Next image'}),settings);
  root.stop=stop;return root;
}
