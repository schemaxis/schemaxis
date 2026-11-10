// Copyright (C) 2026 David L F Gaden
// Shared conceptual-help rendering. Pending entries stay explicit and exportable.
import {h} from '../../lib/dom.mjs';
export function nativeBinding(guide) {
  const binding = guide?.binding;
  return binding ? h('small', {class: 'wb-help operation-native'},
    `${binding.operation}.${binding.property} · JSON: ${binding.key}${binding.constructor ? ' · set at creation' : ''}`) : null;
}
export const sameExplanation = (a, b) => Boolean(a && b && a.replace(/\s+/g, ' ').trim() === b.replace(/\s+/g, ' ').trim());

export function conceptHelp(guide, label, ctx, {shown = '', correction = true} = {}) {
  if (!guide) return null;
  const pending = guide.status === 'pending';
  return h('div', {class: 'operation-concept-help'},
    nativeBinding(guide),
    h('small', {class: 'wb-help'}, pending ? 'Conceptual explanation needed' : guide.status === 'reference' ? 'From adaptor references · editorial review available' : 'Conceptual guidance'),
    guide.explanation && !sameExplanation(guide.explanation, shown) ? h('p', {}, guide.explanation) : null,
    pending ? h('p', {class: 'wb-help'}, guide.question || `Explain ${label}: what it controls, when to use it, units, an example and common mistakes.`) : null,
    guide.units ? h('p', {}, 'Units: ', guide.units) : null,
    guide.defaultMeaning ? h('p', {}, 'When omitted: ', guide.defaultMeaning) : null,
    guide.pitfalls?.length ? h('details', {}, h('summary', {}, 'Assumptions and common mistakes'),
      h('ul', {}, guide.pitfalls.map(text => h('li', {}, text)))) : null,
    guide.examples?.length ? h('details', {}, h('summary', {}, 'Examples'),
      guide.examples.map(example => h('pre', {class: 'mono'}, typeof example === 'string' ? example : JSON.stringify(example, null, 2)))) : null,
    correction ? correctionHelp(guide, label, ctx) : null);
}

export function correctionHelp(guide, label, ctx) {
  if (!guide) return null;
  return h('details', {class: 'operation-about'}, h('summary', {}, 'Suggest a correction'),
      h('p', {class: 'wb-help'}, 'Copy this context and send your correction in the chat for review. Copying does not save or submit changes.'),
      guide.sources?.length ? h('p', {class: 'wb-help'}, 'Sources: ', guide.sources.join(', ')) : null,
      h('button', {class: 'button small', type: 'button', onClick: () => ctx.call(async () => {
        await navigator.clipboard.writeText(JSON.stringify({label, ...guide}, null, 2));
        ctx.notify.ok('Guidance record copied');
      }, {title: 'Could not copy guidance record'})}, 'Copy help request'));
}
