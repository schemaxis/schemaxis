// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import {el,button,warning} from './ui.mjs';

export function mountText(host,text,cleanups) {
  const lines=text.split(/\r?\n/),search=el('input',{type:'search',placeholder:'Find text or regex','aria-label':'Search text'});
  const regex=el('input',{type:'checkbox','aria-label':'Use regular expression'}),sensitive=el('input',{type:'checkbox','aria-label':'Case sensitive'}),whole=el('input',{type:'checkbox','aria-label':'Whole words'});
  const mode=el('select',{'aria-label':'Text search mode'},el('option',{value:'find'},'Find in text'),el('option',{value:'grep'},'Grep / capture table'));
  const output=el('div',{class:'text-result',tabindex:0}),pager=el('div',{class:'pager'}),status=el('div',{role:'status'}),fields=el('fieldset',{class:'capture-fields',hidden:true}),counter=el('span',{'aria-live':'polite'});
  let page=0,worker=null,timeout=null,token=0,hits=[],columns=[],current=-1,truncated=false,selectedColumns=new Set(),byLine=new Map();
  const stop=()=>{worker?.terminate();worker=null;clearTimeout(timeout);};cleanups.push(stop);
  function drawFields() {
    fields.hidden=mode.value!=='grep'||!columns.length;
    fields.replaceChildren(el('legend',{},'Capture columns'),...columns.map((column,index)=>{
      const check=el('input',{type:'checkbox',checked:selectedColumns.has(index),'aria-label':'Capture '+column.name});
      check.onchange=()=>{if(check.checked)selectedColumns.add(index);else selectedColumns.delete(index);draw();};
      return el('label',{},check,column.name);
    }));
  }
  function draw() {
    const grep=mode.value==='grep',length=grep?hits.length:lines.length;
    page=Math.max(0,Math.min(page,Math.ceil(length/200)-1));
    counter.textContent=search.value?`${hits.length}${truncated?'+':''} matches${current>=0?' · '+(current+1)+' of '+hits.length:''}`:'';
    if(grep) {
      const chosen=[...selectedColumns].sort((a,b)=>a-b);
      output.replaceChildren(el('div',{class:'table-wrap'},el('table',{class:'grep-table'},el('thead',{},el('tr',{},['Line','Column','Match',...chosen.map(i=>columns[i].name),'Text'].map(name=>el('th',{},name)))),el('tbody',{},hits.slice(page*200,(page+1)*200).map(hit=>el('tr',{},[hit.line+1,hit.start+1,lines[hit.line].slice(hit.start,hit.start+hit.length),...chosen.map(i=>hit.captures[i]),lines[hit.line]].map(value=>el('td',{},value))))))));
    } else {
      output.replaceChildren(...lines.slice(page*200,(page+1)*200).map((line,index)=>{
        const lineNumber=page*200+index,content=el('span');let end=0;
        for(const hit of byLine.get(lineNumber)||[]) {
          content.append(document.createTextNode(line.slice(end,hit.start)),el('mark',{class:hit===hits[current]?'current-match':'','data-match':''},line.slice(hit.start,hit.start+hit.length)||'▏'));end=hit.start+hit.length;
        }
        content.append(document.createTextNode(line.slice(end)));
        return el('div',{class:'text-line'},el('span',{class:'line-number'},lineNumber+1),content);
      }));
    }
    pager.replaceChildren(button('Previous',()=>{page--;draw();},{disabled:page===0}),`Page ${page+1} of ${Math.max(1,Math.ceil(length/200))}`,button('Next',()=>{page++;draw();},{disabled:(page+1)*200>=length}));
  }
  function navigate(direction) {
    if(!hits.length)return;
    current=(current+direction+hits.length)%hits.length;page=Math.floor((mode.value==='grep'?current:hits[current].line)/200);draw();
    output.querySelector('.current-match')?.scrollIntoView({block:'nearest'});
  }
  function run() {
    stop();const revision=++token;status.replaceChildren();hits=[];byLine.clear();columns=[];selectedColumns.clear();current=-1;page=0;drawFields();draw();
    if(!search.value)return;
    worker=new Worker(new URL('./search-worker.mjs',import.meta.url),{type:'module'});
    worker.onmessage=({data})=>{
      if(revision!==token)return;stop();
      if(data.error){status.append(warning(data.error));return;}
      ({hits,columns,truncated}=data);selectedColumns=new Set(columns.map((_,i)=>i));
      for(const hit of hits){if(!byLine.has(hit.line))byLine.set(hit.line,[]);byLine.get(hit.line).push(hit);}
      current=hits.length?0:-1;if(current>=0)page=Math.floor((mode.value==='grep'?current:hits[0].line)/200);
      if(truncated)status.append(warning('Showing the first 20,000 matches. Narrow the expression for a complete result.'));
      drawFields();draw();
    };
    worker.onerror=()=>{stop();status.append(warning('Search worker unavailable. Reopen this viewer in a current browser.'));};
    timeout=setTimeout(()=>{stop();status.append(warning('Search took too long. Use a more specific expression.'));},1000);
    worker.postMessage({lines,pattern:search.value,regex:regex.checked,sensitive:sensitive.checked,wholeWord:whole.checked});
  }
  for(const control of [search,regex,sensitive,whole])control.oninput=run;
  mode.onchange=()=>{page=0;drawFields();draw();};
  search.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();navigate(event.shiftKey?-1:1);}};
  const shortcut=event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='f'&&host.isConnected){event.preventDefault();search.focus();search.select();}if(event.key==='F3'){event.preventDefault();navigate(event.shiftKey?-1:1);}};
  document.addEventListener('keydown',shortcut);cleanups.push(()=>document.removeEventListener('keydown',shortcut));
  const exportCSV=()=>{
    const chosen=[...selectedColumns].sort((a,b)=>a-b),rows=[['Line','Column','Match',...chosen.map(i=>columns[i].name),'Text'],...hits.map(hit=>[hit.line+1,hit.start+1,lines[hit.line].slice(hit.start,hit.start+hit.length),...chosen.map(i=>hit.captures[i]),lines[hit.line]])];
    const csv=rows.map(row=>row.map(value=>'"'+String(value).replaceAll('"','""')+'"').join(',')).join('\r\n');
    const url=URL.createObjectURL(new Blob([csv],{type:'text/csv'})),link=el('a',{href:url,download:'grep-results.csv'});link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  host.append(el('div',{class:'text-tools'},mode,search,el('label',{},regex,'Regex'),el('label',{},sensitive,'Case sensitive'),el('label',{},whole,'Whole words'),button('Previous match',()=>navigate(-1)),button('Next match',()=>navigate(1)),counter,button('Export matches CSV',exportCSV)),fields,status,output,pager);draw();
}
