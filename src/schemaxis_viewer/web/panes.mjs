import {el,button} from './ui.mjs';

const heights=new Map();
let expanded=null;
const notifyExpanded=value=>{if(parent!==window)parent.postMessage({type:'artifact-expand',expanded:value},location.origin);};

// Expand the existing DOM, preserving playback, canvas state and file selection.
export function createPane(target,{label,cleanups,root=el('section'),height=360,min=140,max=1000,key=label}={}) {
  const previous=[...root.childNodes].filter(node=>node!==target);
  const heading=previous.find(node=>node.nodeName==='H2')||el('h2',{},label);
  const footer=el('div',{class:'pane-footer'},previous.filter(node=>node!==heading));
  root.classList.add('viewer-pane');root.setAttribute('aria-label',label+' viewer');
  const slider=el('input',{type:'range',min,max,step:10,value:heights.get(key)||height,'aria-label':label+' view height'});
  const value=el('output',{class:'pane-height-value'});
  const expand=button('⛶',()=>root.classList.contains('pane-expanded')?restore():enlarge(),{class:'pane-expand','aria-label':'Expand '+label,title:'Expand to browser window','aria-pressed':'false'});
  const viewport=el('div',{class:'pane-viewport'},el('div',{class:'pane-content'},target),el('label',{class:'pane-height-control'},el('span',{},'Height'),slider,value));
  const handle=el('div',{class:'pane-resize',role:'separator',tabindex:0,'aria-orientation':'horizontal','aria-label':'Resize '+label+' vertically',title:'Drag to resize vertically; arrow keys adjust height'},el('span',{'aria-hidden':'true'},'═'));
  root.replaceChildren(el('div',{class:'pane-heading'},heading,expand),viewport,footer,handle);
  function setHeight(next) {
    const size=Math.max(min,Math.min(max,Math.round(next/10)*10));heights.set(key,size);slider.value=size;value.textContent=size+' px';
    viewport.style.height=size+'px';handle.setAttribute('aria-valuemin',min);handle.setAttribute('aria-valuemax',max);handle.setAttribute('aria-valuenow',size);
  }
  slider.oninput=()=>setHeight(Number(slider.value));setHeight(Number(slider.value));
  let drag=null,focusBefore=null,placeholder=null,scrollPositions=[];
  handle.onpointerdown=event=>{if(event.button!==0)return;event.preventDefault();drag={y:event.clientY,height:Number(slider.value)};handle.setPointerCapture(event.pointerId);};
  handle.onpointermove=event=>{if(drag)setHeight(drag.height+event.clientY-drag.y);};
  handle.onpointerup=handle.onpointercancel=handle.onlostpointercapture=()=>{drag=null;};
  handle.onkeydown=event=>{const change={ArrowDown:10,ArrowUp:-10,PageDown:100,PageUp:-100}[event.key];if(change){event.preventDefault();setHeight(Number(slider.value)+change);}};
  function restore({focus=true}={}) {
    if(expanded?.root!==root)return;
    root.classList.remove('pane-expanded');placeholder?.remove();placeholder=null;for(const [node,top,left] of scrollPositions){node.scrollTop=top;node.scrollLeft=left;}scrollPositions=[];root.removeAttribute('role');root.removeAttribute('aria-modal');document.body.classList.remove('has-expanded-pane');expanded=null;
    expand.textContent='⛶';expand.setAttribute('aria-label','Expand '+label);expand.setAttribute('aria-pressed','false');expand.title='Expand to browser window';
    document.removeEventListener('keydown',onKey,true);notifyExpanded(false);
    if(focus&&focusBefore?.isConnected)focusBefore.focus({preventScroll:true});
  }
  function enlarge() {
    expanded?.restore({focus:false});focusBefore=document.activeElement;
    scrollPositions=[];for(let node=root.parentElement;node;node=node.parentElement)scrollPositions.push([node,node.scrollTop,node.scrollLeft]);
    const box=root.getBoundingClientRect(),style=getComputedStyle(root);placeholder=el('div',{class:'pane-placeholder','aria-hidden':'true'});placeholder.style.height=box.height+'px';placeholder.style.marginTop=style.marginTop;placeholder.style.marginBottom=style.marginBottom;root.before(placeholder);
    expanded={root,restore};root.classList.add('pane-expanded');root.setAttribute('role','dialog');root.setAttribute('aria-modal','true');document.body.classList.add('has-expanded-pane');
    expand.textContent='↙ Restore';expand.setAttribute('aria-label','Restore '+label);expand.setAttribute('aria-pressed','true');expand.title='Restore previous size (Escape)';
    document.addEventListener('keydown',onKey,true);notifyExpanded(true);expand.focus({preventScroll:true});
  }
  function onKey(event) {
    if(event.key==='Escape'&&!document.querySelector('dialog[open]')){event.preventDefault();event.stopImmediatePropagation();restore();}
    if(event.key==='Tab') {
      const nodes=[...root.querySelectorAll('button,input,select,a[href],[tabindex="0"]')].filter(node=>!node.disabled&&node.getClientRects().length);
      const first=nodes[0],last=nodes.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
    }
  }
  cleanups.push(()=>{drag=null;restore({focus:false});});
  return {root,footer,setHeight,restore};
}
