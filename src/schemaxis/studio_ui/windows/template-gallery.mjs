// Copyright (C) 2026 David L F Gaden
// Shared, keyboard-accessible starter selection for document and operation dialogs.
import {h, icon, mount} from '../lib/dom.mjs';

export function templateGallery(select, templates = []) {
  const element = h('div', {class: 'template-gallery', role: 'group', 'aria-label': 'Starter templates'});
  function render(items) {
    mount(element, items.map((item) => h('button', {class: 'template-card', type: 'button',
      'aria-pressed': String(select.value === item.id), dataset: {template: item.id}, onClick: () => {
        select.value = item.id;
        select.dispatchEvent(new Event('change', {bubbles: true}));
      }}, h('span', {class: 'library-card-title'}, icon(item.icon || 'file-code'), h('strong', {}, item.title)),
    h('span', {class: 'library-card-description'}, item.description || 'Start a new document'),
    Object.keys(item.fields || {}).length ? h('span', {class: 'library-card-fields'},
      `Fill: ${Object.values(item.fields).map((field) => field.label).join(', ')}`) : null)));
  }
  select.addEventListener('change', () => {
    element.querySelectorAll('[data-template]').forEach((card) =>
      card.setAttribute('aria-pressed', String(card.dataset.template === select.value)));
  });
  render(templates);
  return {element, update: render};
}
