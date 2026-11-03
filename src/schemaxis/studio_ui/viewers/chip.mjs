// Copyright (C) 2026 David L F Gaden
// Reference chips: a compact, focusable token for one viewer pick.
// Used by the shell in reference lists and inside the composer.

import {h} from '../lib/dom.mjs';
import {viewerIcon} from './icons.mjs';

const KINDS = new Set(['geometry', 'image', 'video', 'table', 'series', 'text', 'number', 'vector', 'audio',
  'archive', 'unknown']);

/** Spreadsheet-style column name: 0 → A, 25 → Z, 26 → AA. */
export function columnName(index) {
  let name = '';
  let value = index + 1;
  while (value > 0) {
    const remainder = (value - 1) % 26;
    name = String.fromCharCode(65 + remainder) + name;
    value = Math.floor((value - 1) / 26);
  }
  return name;
}

/** The data kind for a viewer pick payload (drives the chip colour). */
export function referenceKind(reference) {
  switch (reference?.type) {
    case 'face':
    case 'edge':
    case 'vertex':
      return 'geometry';
    case 'pixel':
      return 'image';
    case 'text':
    case 'match':
      return 'text';
    case 'cell':
    case 'range':
      return 'table';
    default:
      return 'unknown';
  }
}

/** A short human label for a viewer pick payload. Never invents identities. */
export function referenceLabel(reference) {
  if (!reference) {
    return '';
  }
  switch (reference.type) {
    case 'face':
    case 'edge':
    case 'vertex':
      return `${reference.objectLabel || reference.object}.${reference.subelement}`;
    case 'pixel':
      return `pixel (${reference.x}, ${reference.y})`;
    case 'text':
      return reference.lineFrom === reference.lineTo
        ? `line ${reference.lineFrom}`
        : `lines ${reference.lineFrom}–${reference.lineTo}`;
    case 'match':
      return `match line ${reference.line}`;
    case 'cell':
      return `${columnName(reference.columns[0])}${reference.rows[0] + 1}`;
    case 'range':
      return `${columnName(reference.columns[0])}${reference.rows[0] + 1}:`
        + `${columnName(reference.columns[1])}${reference.rows[1] + 1}`;
    default:
      return String(reference.label || reference.type || 'reference');
  }
}

/**
 * Create a chip element.
 * options: {label, kind, title, removable = true, onRemove(chip) → false to keep, onActivate(chip), reference}
 * Backspace / Delete on a focused chip removes it in one stroke and moves focus
 * to the neighbouring chip. Enter / Space activates it.
 */
export function createChip(options = {}) {
  const reference = options.reference;
  const kind = KINDS.has(options.kind) ? options.kind : referenceKind(reference);
  const label = options.label || referenceLabel(reference);
  const removable = options.removable !== false;

  const remove = () => {
    const neighbour = chip.nextElementSibling?.classList.contains('vw-chip')
      ? chip.nextElementSibling
      : chip.previousElementSibling?.classList.contains('vw-chip') ? chip.previousElementSibling : null;
    // onRemove may return false to keep the element (e.g. it re-renders the list itself).
    const keep = options.onRemove?.(chip) === false;
    if (!keep) {
      chip.remove();
    }
    neighbour?.focus();
  };

  const removeButton = removable
    ? h('button', {
      type: 'button',
      class: 'vw-chip-remove',
      tabindex: '-1',
      'aria-label': `Remove ${label}`,
      title: 'Remove',
      onClick: (event) => {
        event.stopPropagation();
        remove();
      },
    }, viewerIcon('close'))
    : null;

  const chip = h('span', {
    class: 'vw-chip',
    tabindex: '0',
    role: 'button',
    contenteditable: 'false',
    title: options.title || label,
    'aria-label': `${kind} reference ${label}${removable ? '. Press Delete to remove' : ''}`,
    style: {'--chip-kind': `var(--kind-${kind})`},
    dataset: {kind},
    onKeydown: (event) => {
      if (removable && (event.key === 'Backspace' || event.key === 'Delete')) {
        event.preventDefault();
        remove();
      } else if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        options.onActivate?.(chip);
      } else if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
        const next = event.key === 'ArrowRight' ? chip.nextElementSibling : chip.previousElementSibling;
        if (next?.classList.contains('vw-chip')) {
          event.preventDefault();
          next.focus();
        }
      }
    },
    onClick: () => options.onActivate?.(chip),
  }, h('span', {class: 'vw-chip-dot', 'aria-hidden': 'true'}), h('span', {class: 'vw-chip-label'}, label), removeButton);
  chip.reference = reference;
  return chip;
}
