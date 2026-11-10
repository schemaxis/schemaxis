import {themeIcon} from './icons.mjs';
// Match Studio: the icon offers the opposite theme; system is the initial choice.
export function installPreferences({onChange=()=>{}}={}) {
  const toggle=document.querySelector('#theme'),system=matchMedia('(prefers-color-scheme: dark)');
  let choice='system';
  try{choice=localStorage.getItem('artifact.theme')||'system';}catch{}
  const supplied=new URL(location.href).searchParams.get('theme');
  if(parent!==window&&['light','dark','system'].includes(supplied))choice=supplied;
  function apply(value,{save=true}={}) {
    choice=['light','dark','system'].includes(value)?value:'system';
    const dark=choice==='dark'||choice==='system'&&system.matches;
    document.documentElement.dataset.theme=dark?'dark':'light';
    toggle.replaceChildren(themeIcon(dark));toggle.dataset.icon=dark?'sun':'moon';toggle.setAttribute('aria-label','Toggle theme');
    toggle.title=`Switch to ${dark?'light':'dark'} mode${choice==='system'?' · following system theme':''}`;
    if(save){try{localStorage.setItem('artifact.theme',choice);}catch{}onChange({theme:choice});}
    document.dispatchEvent(new Event('artifact-themechange'));
  }
  toggle.onclick=()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';apply(theme);if(parent!==window)parent.postMessage({type:'artifact-theme-preference',theme},location.origin);};
  system.addEventListener('change',()=>apply(choice,{save:false}));apply(choice,{save:false});
  document.querySelector('#toggle-library').onclick=()=>{
    const collapsed=document.body.classList.toggle('library-collapsed');
    document.querySelector('#toggle-library').setAttribute('aria-expanded',String(!collapsed));
    try{localStorage.setItem('artifact.sidebarCollapsed',String(collapsed));}catch{}onChange({sidebarCollapsed:collapsed});
  };
  try{if(localStorage.getItem('artifact.sidebarCollapsed')==='true'){document.body.classList.add('library-collapsed');document.querySelector('#toggle-library').setAttribute('aria-expanded','false');}}catch{}
  return {apply,setCollapsed:value=>{document.body.classList.toggle('library-collapsed',value);document.querySelector('#toggle-library').setAttribute('aria-expanded',String(!value));}};
}
