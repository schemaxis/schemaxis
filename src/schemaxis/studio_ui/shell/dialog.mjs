// Copyright (C) 2026 David L F Gaden
// Modal dialogs and context menus.

import {h, icon} from '../lib/dom.mjs';
import {clampOffset, dragSurface} from '../lib/drag.mjs';

/**
 * Open a modal dialog. `content` is an element or a function(close) returning one.
 * `actions` are {label, primary, danger, run(close) → value|false}. Returning false
 * keeps the dialog open (for validation). Resolves with the chosen value or null.
 * Every dialog moves by its title bar. `enterSubmits: false` stops Enter in a
 * field from pressing the primary action, for forms where Enter adds a row.
 * `className` adds layout classes to the dialog.
 */
export function openDialog({title, content, actions = [], wide = false, initialFocus, enterSubmits = true, className}) {
  return new Promise((resolve) => {
    const previousFocus = document.activeElement;
    let settled = false;
    const close = (value = null) => {
      if (settled) {
        return;
      }
      settled = true;
      backdrop.remove();
      document.removeEventListener('keydown', onKey);
      if (previousFocus && previousFocus.focus) {
        previousFocus.focus();
      }
      resolve(value);
    };
    const body = typeof content === 'function' ? content(close) : content;
    const buttons = actions.map((action) => h('button', {
      class: ['button', action.primary && 'primary', action.danger && 'danger'],
      type: action.primary && enterSubmits ? 'submit' : 'button',
      onClick: async (event) => {
        event.preventDefault();
        const value = action.run ? await action.run(close) : action.value;
        if (value !== false) {
          close(value === undefined ? true : value);
        }
      },
    }, action.label));
    const header = h('div', {class: 'dialog-header', title: 'Drag to move'},
      h('h3', {}, title),
      h('button', {type: 'button', class: 'button ghost icon-only', 'aria-label': 'Close',
        onClick: () => close(null)}, icon('close')));
    const dialog = h('form', {class: ['dialog', wide && 'wide', className], role: 'dialog', 'aria-modal': 'true',
      'aria-label': title, onSubmit: (event) => event.preventDefault(),
      onKeydown: (event) => {
        if (!enterSubmits && event.key === 'Enter' && event.target.tagName === 'INPUT') event.preventDefault();
      }},
    header,
    h('div', {class: 'dialog-body'}, body),
    buttons.length ? h('div', {class: 'dialog-footer'}, buttons) : null);
    const backdrop = h('div', {class: 'dialog-backdrop', onMousedown: (event) => {
      if (event.target === backdrop) {
        close(null);
      }
    }}, dialog);
    const onKey = (event) => {
      if (event.key === 'Escape' && [...document.querySelectorAll('.dialog-backdrop')].at(-1) === backdrop) {
        event.stopImmediatePropagation();
        close(null);
      }
    };
    document.addEventListener('keydown', onKey);
    document.body.append(backdrop);
    let offset = [0, 0];
    let origin = offset;
    let rest = null;
    dragSurface(header, {
      onStart: () => {
        origin = offset;
        const rect = dialog.getBoundingClientRect();
        rest = {left: rect.left - offset[0], right: rect.right - offset[0], top: rect.top - offset[1]};
        backdrop.classList.add('moved');
      },
      onMove: (dx, dy) => {
        offset = clampOffset(rest, origin[0] + dx, origin[1] + dy);
        dialog.style.transform = `translate(${offset[0]}px, ${offset[1]}px)`;
      },
    });
    const focusTarget = initialFocus
      ? dialog.querySelector(initialFocus)
      : dialog.querySelector('.dialog-body input, .dialog-body select, .dialog-body textarea')
        || dialog.querySelector('.dialog-footer .button.primary');
    if (focusTarget) {
      focusTarget.focus();
    }
  });
}

export function confirmDialog(title, message, {confirm = 'Confirm', danger = false} = {}) {
  return openDialog({
    title,
    content: h('p', {class: 'secondary-text'}, message),
    actions: [
      {label: 'Cancel', value: null, run: () => null},
      {label: confirm, primary: !danger, danger, value: true},
    ],
  });
}

/** Show a context menu at a point or under an anchor element. */
export function openMenu(anchor, items) {
  const rect = anchor instanceof Element ? anchor.getBoundingClientRect() : {left: anchor.x, bottom: anchor.y};
  const close = () => {
    menu.remove();
    document.removeEventListener('mousedown', outside, true);
    document.removeEventListener('keydown', onKey, true);
  };
  const outside = (event) => {
    if (!menu.contains(event.target)) {
      close();
    }
  };
  const onKey = (event) => {
    if (event.key === 'Escape') {
      close();
    }
  };
  const menu = h('div', {class: 'menu', role: 'menu'}, items.map((item) => h('button', {
    class: 'menu-item',
    role: item.checked === undefined ? 'menuitem' : 'menuitemcheckbox',
    'aria-checked': item.checked === undefined ? undefined : String(Boolean(item.checked)),
    disabled: item.disabled,
    onClick: () => {
      close();
      item.run();
    },
  }, item.icon ? icon(item.icon) : null, item.label)));
  document.body.append(menu);
  const width = menu.offsetWidth;
  menu.style.left = `${Math.min(rect.left, window.innerWidth - width - 8)}px`;
  menu.style.top = `${Math.min(rect.bottom + 4, window.innerHeight - menu.offsetHeight - 8)}px`;
  document.addEventListener('mousedown', outside, true);
  document.addEventListener('keydown', onKey, true);
  const first = menu.querySelector('button:not(:disabled)');
  if (first) {
    first.focus();
  }
  return close;
}
