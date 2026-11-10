// Sun/moon geometry matches Studio's existing icon sprite, without a runtime dependency.
export function themeIcon(dark) {
  const ns='http://www.w3.org/2000/svg';
  const element=(name,attributes)=>{const node=document.createElementNS(ns,name);for(const [key,value] of Object.entries(attributes))node.setAttribute(key,value);return node;};
  const svg=element('svg',{viewBox:'0 0 24 24',width:18,height:18,fill:'none',stroke:'currentColor','stroke-width':1.8,'stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'});
  if(dark)svg.append(element('circle',{cx:12,cy:12,r:4}),element('path',{d:'M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4'}));
  else svg.append(element('path',{d:'M20.5 14.5A8.5 8.5 0 1 1 9.5 3.5a7 7 0 0 0 11 11z'}));
  return svg;
}
