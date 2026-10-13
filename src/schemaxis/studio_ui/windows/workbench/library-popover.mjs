// Searchable keyboard-first library popover. The owning library handles preview
// and insertion; dismissing the popover always clears its temporary preview.
import {h, mount} from '../../lib/dom.mjs';
import {searchAdd} from '../../lib/search.mjs';

export function openLibraryPopover({anchor, title, items, card, preview, clear}) {
  const search = h('input', {class: 'input', placeholder: 'Search names, descriptions and groups…', 'aria-label': `Search ${title}`,
    autocomplete: 'off', spellcheck: 'false'});
  const list = h('div', {class: 'library-grid', role: 'list', 'aria-label': title});
  const summary = h('p', {class: 'library-summary', 'aria-live': 'polite'}, 'Focus a snippet to preview every change.');
  let matches = items;
  let selected = -1;
  let limit = 60;
  const close = () => {
    element.remove();
    document.removeEventListener('pointerdown', outside);
    clear();
    anchor.setAttribute('aria-expanded', 'false');
  };
  const choose = (index) => {
    if (!matches.length) {
      return;
    }
    selected = (index + Math.min(limit, matches.length)) % Math.min(limit, matches.length);
    list.querySelectorAll('[data-library]')[selected]?.focus();
  };
  const render = () => {
    mount(list, matches.length ? matches.slice(0, limit).map((item) => card(item, {
      inserted: () => close(),
      previewed: (message) => { summary.textContent = message; },
    })) : h('p', {class: 'library-summary'}, 'No matching snippets.'));
    if (matches.length > limit) list.append(h('button', {class: 'button small', type: 'button', onClick: () => {
      limit += 60; render();
    }}, `Show more (${matches.length - limit} remaining)`));
  };
  const element = h('section', {class: 'library-popover', role: 'dialog', 'aria-label': title,
    onKeydown: (event) => {
      if (event.key === 'Escape') {
        close();
        anchor.focus();
      } else if (['ArrowDown', 'ArrowRight', 'ArrowUp', 'ArrowLeft'].includes(event.key)
          && (event.target !== search || ['ArrowDown', 'ArrowUp'].includes(event.key))) {
        const buttons = [...list.querySelectorAll('[data-library]')];
        const current = buttons.indexOf(document.activeElement);
        choose(current + (['ArrowDown', 'ArrowRight'].includes(event.key) ? 1 : -1));
        event.preventDefault();
      }
    }}, h('div', {class: 'library-popover-heading'}, h('strong', {}, title),
    h('button', {class: 'button quiet', type: 'button', 'aria-label': 'Close snippets', onClick: () => {
      close();
      anchor.focus();
    }}, '×')), search, list, summary);
  function outside(event) {
    if (!element.contains(event.target) && event.target !== anchor && !anchor.contains(event.target)) {
      close();
    }
  }
  search.addEventListener('input', () => {
    const query = search.value.trim().toLocaleLowerCase();
    matches = searchAdd(items, query);
    selected = -1;
    limit = 60;
    clear();
    render();
  });
  anchor.parentElement.append(element);
  anchor.setAttribute('aria-expanded', 'true');
  document.addEventListener('pointerdown', outside);
  render();
  search.focus();
  return {close, element};
}
