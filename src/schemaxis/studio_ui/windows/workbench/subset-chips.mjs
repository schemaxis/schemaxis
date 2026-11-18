// Copyright (C) 2026 David L. F. Gaden.
// Exact subsets of declared choices. Filtering never changes the selection.
import {h, mount} from '../../lib/dom.mjs';

export function subsetChips({choices, initial = [], label, choiceNoun = 'pipeline objects', preserveOrder = false, onChange = () => {}}) {
  let selected = new Set(initial), anchor, anchorSelected = true;
  let all;
  function refreshChoices() {
    const known = new Set(choices.map(item => item.id));
    all = [...choices, ...[...selected].filter(id => !known.has(id)).map(id => ({id, label: `${id} · unavailable`, missing: true}))];
  }
  refreshChoices();
  const list = h('div', {class: 'scene-subset-chips'});
  const status = h('p', {class: 'wb-help', role: 'status'});
  const search = h('input', {class: 'input', type: 'search', placeholder: `Filter ${choiceNoun}…`, 'aria-label': `Filter ${label}`, onInput: render});
  const shown = () => all.filter(item => `${item.id} ${item.label}`.toLowerCase().includes(search.value.toLowerCase()));
  const read = () => preserveOrder ? [...selected] : all.filter(item => selected.has(item.id)).map(item => item.id);
  function change(ids, checked) {
    ids.forEach(id => checked ? selected.add(id) : selected.delete(id));
    render(); onChange(read()); element.dispatchEvent(new Event('change', {bubbles: true}));
  }
  const button = (title, run) => h('button', {type: 'button', class: 'button small', onClick: run}, title);
  const element = h('div', {class: 'scene-subset'}, search,
    h('div', {class: 'scene-tools'},
      button('Select All', () => change(choices.map(item => item.id), true)),
      button('Deselect All', () => change([...selected], false)),
      button('Select shown', () => change(shown().filter(item => !item.missing).map(item => item.id), true)),
      button('Deselect shown', () => change(shown().map(item => item.id), false))), status, list,
    h('p', {class: 'wb-help'}, 'Click to toggle. Shift-click selects a range. Drag to select; Ctrl/Cmd-drag toggles. Choices are saved by name.'));
  function render() {
    const visible = shown();
    status.textContent = `${selected.size} selected · ${choices.length} ${choiceNoun} · ${visible.length} shown`;
    mount(list, visible.map(item => h('button', {type: 'button', class: ['wb-case-name', item.missing && 'scene-missing'],
      dataset: {name: item.id}, 'aria-label': `${label}: ${item.id}`, 'aria-pressed': String(selected.has(item.id)),
      onClick: event => {
        if (event.shiftKey && visible.some(row => row.id === anchor)) {
          const a = visible.findIndex(row => row.id === anchor), b = visible.indexOf(item);
          change(visible.slice(Math.min(a,b), Math.max(a,b)+1).map(row => row.id), anchorSelected);
        } else { anchor = item.id; anchorSelected = !selected.has(item.id); change([item.id], anchorSelected); }
        [...list.querySelectorAll('button')].find(node => node.dataset.name === item.id)?.focus({preventScroll: true});
      }}, item.label || item.id)), !visible.length ? h('p', {class: 'wb-help'}, `No matching ${choiceNoun}.`) : null);
  }
  let drag, suppressClick = false;
  function finish(apply) {
    if (!drag) return;
    const current = drag; drag = null; current.box?.remove();
    if (list.hasPointerCapture(current.id)) list.releasePointerCapture(current.id);
    list.querySelectorAll('.reader-box-hit').forEach(item => item.classList.remove('reader-box-hit'));
    if (!current.box) return;
    suppressClick = true; setTimeout(() => { suppressClick = false; }, 0);
    if (apply) {
      if (current.toggle) current.names.forEach(id => selected.has(id) ? selected.delete(id) : selected.add(id));
      else current.names.forEach(id => selected.add(id));
      change([], true); anchor = undefined;
    }
  }
  list.addEventListener('pointerdown', event => {
    if (event.button === 0 && event.pointerType === 'mouse') drag = {id: event.pointerId, x: event.clientX, y: event.clientY, toggle: event.ctrlKey || event.metaKey, names: []};
  });
  list.addEventListener('pointermove', event => {
    if (!drag || drag.id !== event.pointerId || !drag.box && Math.hypot(event.clientX-drag.x, event.clientY-drag.y) < 5) return;
    if (!drag.box) { drag.box = h('div', {class: 'reader-selection-box', 'aria-hidden': 'true'}); list.append(drag.box); list.setPointerCapture(drag.id); }
    event.preventDefault();
    const rect = list.getBoundingClientRect(), left = Math.max(rect.left, Math.min(drag.x,event.clientX)), right = Math.min(rect.right,Math.max(drag.x,event.clientX));
    const top = Math.max(rect.top,Math.min(drag.y,event.clientY)), bottom = Math.min(rect.bottom,Math.max(drag.y,event.clientY));
    Object.assign(drag.box.style,{left:`${left-rect.left+list.scrollLeft}px`,top:`${top-rect.top+list.scrollTop}px`,width:`${Math.max(0,right-left)}px`,height:`${Math.max(0,bottom-top)}px`});
    drag.names = [...list.querySelectorAll('button')].filter(item => {
      const r = item.getBoundingClientRect(), hit = right>left && bottom>top && r.left<right && r.right>left && r.top<bottom && r.bottom>top;
      item.classList.toggle('reader-box-hit', hit); return hit;
    }).map(item => item.dataset.name);
  });
  list.addEventListener('pointerup', () => finish(true));
  list.addEventListener('pointercancel', () => finish(false));
  list.addEventListener('lostpointercapture', () => finish(false));
  list.addEventListener('keydown', event => { if (event.key === 'Escape' && drag?.box) { event.stopPropagation(); finish(false); } });
  list.addEventListener('click', event => { if (suppressClick) { event.preventDefault(); event.stopPropagation(); } }, true);
  list.addEventListener('dragstart', event => event.preventDefault());
  render(); return {
    element, read,
    setChoices(next) { choices = next; refreshChoices(); render(); },
    add(id) { selected.add(id); refreshChoices(); change([], true); },
  };
}
