// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
export function captureColumns(pattern) {
  const columns=[];let bracket=false;
  for(let i=0;i<pattern.length;i++) {
    if(pattern[i]==='\\'){i++;continue;}
    if(pattern[i]==='[')bracket=true;
    if(pattern[i]===']')bracket=false;
    if(bracket||pattern[i]!=='(')continue;
    if(pattern[i+1]!=='?')columns.push({index:columns.length+1,name:'Group '+(columns.length+1)});
    else if(pattern.slice(i+1,i+3)==='?<'&&!['=','!'].includes(pattern[i+3])) {
      const end=pattern.indexOf('>',i+3);columns.push({index:columns.length+1,name:pattern.slice(i+3,end)});
    }
  }
  return columns;
}
export function searchLines({lines,pattern,sensitive=false,regex=false,wholeWord=false,limit=20000}) {
  const escaped=regex?pattern:pattern.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const source=wholeWord?'\\b(?:'+escaped+')\\b':escaped;
  const re=new RegExp(source,sensitive?'g':'gi'),columns=regex?captureColumns(pattern):[],hits=[];
  let truncated=false;
  if(pattern)outer:for(let line=0;line<lines.length;line++)for(const match of lines[line].matchAll(re)) {
    if(hits.length>=limit){truncated=true;break outer;}
    hits.push({line,start:match.index,length:match[0].length,captures:columns.map(c=>match[c.index]??'')});
  }
  return {hits,columns,truncated};
}
