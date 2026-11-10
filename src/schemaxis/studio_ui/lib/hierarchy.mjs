// Copyright (C) 2026 David L. F. Gaden
// Shared disclosure controls for Studio's details-based hierarchical lists.
import {h} from './dom.mjs';
export function setDepth(root, depth = Infinity) {
  for (const node of root.querySelectorAll('details')) {
    let level = 1, parent = node.parentElement.closest('details');
    while (parent && root.contains(parent)) { level++; parent = parent.parentElement.closest('details'); }
    node.open = level <= depth;
  }
}
export function hierarchyControls(root) {
  const depth = h('input', {class: 'input', type: 'number', min: 0, max: 30, value: 2, 'aria-label': 'Expansion depth'});
  return h('div', {class: 'tree-tools', role: 'toolbar', 'aria-label': 'Hierarchical list controls'},
    h('button', {class: 'button small', type: 'button', onClick: () => setDepth(root)}, 'Expand all'),
    h('button', {class: 'button small', type: 'button', onClick: () => setDepth(root, 0)}, 'Collapse all'),
    h('label', {}, 'Depth ', depth),
    h('button', {class: 'button small', type: 'button', onClick: () => setDepth(root, Math.max(0, Number(depth.value) || 0))}, 'Apply depth'));
}
// Every details summary gets two narrow buttons on its left: [▸] opens one level
// (or closes the item and everything below it), [▸▸] opens everything below a
// closed item and closes an open one.
export function installHierarchyControls(root) {
  function enhance(container) {
    if (!(container instanceof Element)) return;
    const details = [...(container.matches('details') ? [container] : []), ...container.querySelectorAll('details')];
    for (const node of details) {
      const summary = node.querySelector(':scope > summary');
      if (!summary || summary.dataset.disclosure) continue;
      summary.dataset.disclosure = 'true';
      const collapse = () => { setDepth(node, 0); node.open = false; };
      const press = (action) => (event) => { event.preventDefault(); event.stopPropagation(); action(); };
      const toggle = h('button', {class: 'tree-toggle', type: 'button', title: 'Expand one level, or collapse',
        'aria-label': 'Expand or collapse this item', 'aria-expanded': String(node.open),
        onClick: press(() => { if (node.open) collapse(); else node.open = true; })});
      const subtree = h('button', {class: 'tree-subtree', type: 'button', title: 'Expand everything below, or collapse',
        'aria-label': 'Expand all below',
        onClick: press(() => { if (node.open) collapse(); else { node.open = true; setDepth(node); } })});
      node.addEventListener('toggle', () => { toggle.setAttribute('aria-expanded', String(node.open)); });
      summary.addEventListener('click', event => { if (node.open && !event.target.closest('button')) setDepth(node, 0); });
      summary.prepend(h('span', {class: 'tree-buttons'}, toggle, subtree));
    }
  }
  enhance(root);
  const observer = new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(enhance)));
  observer.observe(root, {childList: true, subtree: true});
  return () => observer.disconnect();
}
export function schemaTree(value, label = 'Schema', depth = 0) {
  if (value && typeof value === 'object' && depth < 10) return h('details', {open: depth === 0},
    h('summary', {}, label), Object.entries(value).map(([key, child]) => schemaTree(child, key, depth + 1)));
  return h('div', {class: 'schema-leaf mono'}, `${label}: ${JSON.stringify(value)}`);
}
