// Copyright (C) 2026 David L F Gaden
import {yamlRender} from './yaml-parse.mjs';
// Fill mode is a small editor controller. Markers stay ordinary, durable JSON.
import {h} from '../lib/dom.mjs';
import {dragSurface} from '../lib/drag.mjs';
import {documentValue} from './json-parse.mjs';
import {rangeOfPointer, pointerAt} from './json-pointer.mjs';
import {resolveSchemaContext} from './schema-registry.mjs';
import {fillDecorations} from './highlight.mjs';
import {
  findFills, parseField, checkField, fieldChoices, atPointer, replacing, substituteField, uniqueFieldValue, isFill,
} from './fill-data.mjs';
import {expressionKinds, missingProperties, checkSchemaValue, fieldFromSchemas} from './fill-schema.mjs';
import {schemasAt} from './schema-core.mjs';
import {createExpressionForm} from './fill-expressions.mjs';
import {valueLabel, VALUE_LABELS} from './value-labels.mjs';

/** core is the editor's internal editing bridge; options may provide getFunctions, observations and nodeKinds. */
export function createFillMode(core, options = {}) {
  let fields = {};
  let markers = [];
  let active = new Set();
  let current = null;
  let catalogue = options.catalogue || {};
  let loading = null;
  let recent = new Map();
  let input = null;
  let mode = null;
  let expressions = null;
  let message = null;
  let acceptButton = null;
  let dirty = false;
  let applying = false;
  let disposed = false;
  let followups = [];
  let pinned = null;
  const popover = h('section', {class: 'sx-fill-popover', hidden: true, role: 'dialog',
    'aria-label': 'Fill a value', onKeydown: (event) => {
      if (controller.keydown(event)) {
        event.preventDefault();
        event.stopPropagation();
      }
    }});
  const badge = h('button', {class: 'sx-fill-badge', type: 'button', hidden: true,
    onClick: () => controller.start()}, '');
  core.view.root.append(popover, badge);

  const data = () => documentValue(core.ensureAst());
  const choiceOptions = () => ({...options,
    observations: core.state.options.fillObservations || options.observations,
    nodeKinds: core.state.options.fillNodeKinds || options.nodeKinds,
  });
  const resolved = (pointer) => {
    const root = data();
    const context = resolveSchemaContext(core.state.registry, root, pointer, core.state.schema);
    return {...context, pointer: pointer.slice(context.base.length)};
  };
  const list = () => {
    const seen = new Set();
    return markers.filter((marker) => {
      if (!active.has(marker.pointer) || seen.has(marker.field.$fill)) return false;
      seen.add(marker.field.$fill);
      return true;
    });
  };
  const item = () => markers.find((marker) => marker.pointer === current);
  const close = () => {
    current = null;
    pinned = null;
    active.clear();
    popover.hidden = true;
    core.requestRender();
  };
  const nextFollowup = () => {
    close();
    while (followups.length) {
      if (controller.offerFollowup(followups.shift())) return;
    }
  };
  const reposition = () => {
    const marker = item();
    if (!marker || popover.hidden) return;
    const width = core.view.root.clientWidth;
    const height = core.view.root.clientHeight;
    if (pinned) {
      popover.style.left = `${Math.round(Math.max(0, Math.min(pinned.x, width - popover.offsetWidth)))}px`;
      popover.style.top = `${Math.round(Math.max(0, Math.min(pinned.y, height - 40)))}px`;
      return;
    }
    const anchor = core.anchorAt(marker.from);
    const x = Math.max(0, Math.min(anchor.x, width - popover.offsetWidth));
    const below = anchor.y + anchor.lineHeight;
    const y = Math.max(0, Math.min(below, height - popover.offsetHeight - badge.offsetHeight));
    popover.style.left = `${Math.round(x)}px`;
    popover.style.top = `${Math.round(y)}px`;
  };
  // A list of names may be typed plainly ("internalMesh, patch/inlet") where JSON is expected.
  const literal = (marker, context) => {
    try {
      return parseField(input.value, marker.field);
    } catch (error) {
      const text = input.value.trim();
      if (!(error instanceof SyntaxError) || (marker.field.type || 'json') !== 'json' || !text) throw error;
      const names = text.split(/[\n,]+/).map((name) => name.trim()).filter(Boolean);
      for (const candidate of [names, text]) {
        if (!checkSchemaValue(context.schema, context.value, context.pointer, substituteField(marker.field, candidate))) return candidate;
      }
      throw error;
    }
  };
  const read = () => {
    const marker = item();
    if (!marker) throw new Error('This field is no longer present.');
    const context = resolved(marker.pointer);
    const expression = mode?.value !== 'literal';
    const result = expression ? expressions.read() : {value: literal(marker, context)};
    const problem = expression ? '' : checkField(result.value, marker.field);
    if (problem) throw new Error(problem);
    const group = markers.filter((entry) => entry.field.$fill === marker.field.$fill
      && active.has(entry.pointer));
    const candidate = marker.field.type === 'id' ? uniqueFieldValue(data(), group, result.value) : result.value;
    for (const entry of group) {
      if (entry.field.template && expression) throw new Error('An interpolated ID needs literal text.');
      const scope = resolved(entry.pointer);
      const replacement = substituteField(entry.field, candidate);
      const problem = checkSchemaValue(scope.schema, scope.value, scope.pointer, replacement);
      if (problem) throw new Error(problem);
    }
    if (!expression && ['nodeRef', 'axisRef'].includes(marker.field.type)) {
      const choices = fieldChoices(marker.field, context.value, choiceOptions());
      if (!choices.includes(result.value)) throw new Error('Choose an existing, compatible reference.');
    }
    return result;
  };
  const validate = () => {
    if (!message) return false;
    try {
      read();
      message.textContent = 'Ready to accept';
      message.classList.remove('sx-fill-error');
      acceptButton.disabled = false;
      return true;
    } catch (error) {
      message.textContent = error instanceof SyntaxError ? 'Enter a complete JSON value, such as ["internalMesh"]. For a list of names, plain names separated by commas also work.' : error.message;
      message.classList.add('sx-fill-error');
      acceptButton.disabled = true;
      return false;
    }
  };
  const changed = () => {
    dirty = true;
    validate();
  };

  function show(pointer) {
    const marker = markers.find((entry) => entry.pointer === pointer);
    if (!marker || core.state.readOnly) return close();
    current = pointer;
    dirty = false;
    expressions = null;
    const context = resolved(pointer);
    if (context.schema) {
      const schemas = schemasAt(context.schema, context.value, context.pointer, {editing: true});
      marker.field = {...fieldFromSchemas(marker.field.$fill, schemas, marker.field.required, true), ...marker.field};
    }
    const kinds = expressionKinds(context.schema, context.value, context.pointer);
    input = h('input', {type: 'text', class: 'sx-fill-value', 'aria-label': 'Value',
      value: marker.field.default === undefined ? '' : (typeof marker.field.default === 'string'
        && marker.field.type !== 'enum' ? marker.field.default : JSON.stringify(marker.field.default)),
      placeholder: ['string', 'id', 'path', 'nodeRef', 'axisRef', 'field'].includes(marker.field.type)
        ? 'Type a value' : 'Type a JSON value', onInput: changed});
    mode = h('select', {'aria-label': 'Value or expression'},
      h('option', {value: 'literal'}, 'Type a value'),
      kinds.map((kind) => h('option', {value: kind}, valueLabel(kind))));
    const modeHelp = h('p', {class: 'sx-fill-help'});
    message = h('div', {class: 'sx-fill-message', role: 'status', 'aria-live': 'polite'});
    acceptButton = h('button', {type: 'button', class: 'button small primary', onClick: () => accept(1)}, 'Accept');
    const body = h('div', {class: 'sx-fill-body'}, input);
    const helpNodes = context.schema ? schemasAt(context.schema, context.value, context.pointer, {editing: true}) : [];
    const guide = helpNodes.find(node => node['x-studio-guide']?.binding)?.['x-studio-guide'];
    const description = marker.field.description || helpNodes.find(node => node.description)?.description;
    const choices = fieldChoices(marker.field, context.value, {...choiceOptions(),
      recent: recent.get(marker.field.type) || []});
    if (choices.length) {
      const select = h('select', {'aria-label': 'Choose a value'},
        h('option', {value: ''}, 'Choose a value…'), choices.map((value, index) =>
          h('option', {value: String(index)}, typeof value === 'string' ? value : JSON.stringify(value))));
      select.addEventListener('change', () => {
        if (select.value === '') return;
        const value = choices[Number(select.value)];
        input.value = typeof value === 'string' && marker.field.type !== 'enum' ? value : JSON.stringify(value);
        changed();
        input.focus();
      });
      body.append(select);
    }
    mode.addEventListener('change', () => {
      modeHelp.textContent = VALUE_LABELS[mode.value]?.[1] || '';
      if (mode.value === 'literal') {
        body.replaceChildren(input);
      } else {
        expressions = createExpressionForm({schema: context.schema, value: context.value,
          pointer: context.pointer, kind: mode.value, catalogue, onChange: changed});
        body.replaceChildren(expressions.element);
      }
      dirty = true;
      validate();
      reposition();
    });
    const index = list().findIndex((entry) => entry.pointer === pointer);
    const heading = h('div', {class: 'sx-fill-heading', title: 'Drag to move this window off the text'},
      h('strong', {}, marker.field.label || marker.field.$fill),
      h('span', {}, `${index + 1} of ${list().length}${marker.field.required !== false ? ' · required' : ''}`));
    let grabbed = null;
    dragSurface(heading, {
      onStart: () => { grabbed = {x: popover.offsetLeft, y: popover.offsetTop}; },
      onMove: (dx, dy) => { pinned = {x: grabbed.x + dx, y: grabbed.y + dy}; reposition(); },
    });
    popover.replaceChildren(heading,
      h('div', {class: 'sx-fill-pointer'}, pointer || '/'),
      guide?.binding ? h('p', {class: 'sx-fill-help'}, `${guide.binding.operation}.${guide.binding.property}`) : null,
      description ? h('p', {class: 'sx-fill-help'}, description) : null,
      core.state.options.chooseValue ? h('button', {type: 'button', class: 'button small',
        onClick: () => core.state.options.chooseValue({pointer, pointers: markers.filter(entry =>
          entry.field.$fill === marker.field.$fill && active.has(entry.pointer)).map(entry => entry.pointer)})},
      'Variables & expressions…') : null, mode, modeHelp, body, message,
      h('div', {class: 'sx-fill-actions'}, acceptButton,
        h('button', {type: 'button', class: 'button small', onClick: () => move(1)}, 'Leave for later'),
        h('button', {type: 'button', class: 'button small',
          onClick: () => { close(); core.textarea.focus(); }}, 'Done')),
      h('div', {class: 'sx-fill-help'},
        'Tab: next · Shift+Tab: previous · ↑: expression · ↓: choices · Enter: accept · Esc: leave'));
    popover.hidden = false;
    core.textarea.setSelectionRange(marker.from, marker.to);
    core.afterProgrammaticSelection();
    validate();
    reposition();
    input.focus({preventScroll: true});
    core.requestRender();
  }

  function move(direction) {
    const candidates = list();
    if (!candidates.length) return close();
    const index = candidates.findIndex((entry) => entry.pointer === current);
    show(candidates[(index + direction + candidates.length) % candidates.length].pointer);
  }

  function accept(direction) {
    if (core.state.readOnly) return false;
    if (!validate()) return false;
    const marker = item();
    const {value, axis} = read();
    const before = list();
    const index = before.findIndex((entry) => entry.pointer === current);
    const group = markers.filter((entry) => entry.field.$fill === marker.field.$fill
      && (!active.size || active.has(entry.pointer)));
    let result = value;
    if (marker.field.type === 'id') result = uniqueFieldValue(data(), group, result);
    let document = data();
    for (const entry of group) {
      const replacement = substituteField(entry.field, result);
      document = replacing(document, entry.pointer, replacement);
    }
    if (axis) {
      const context = resolved(marker.pointer);
      const target = `${context.base}/axes`;
      document = replacing(document, target, [...(atPointer(document, target) || []), axis]);
    }
    applying = true;
    if (core.ensureAst().format === 'yaml') {
      core.replaceText(0, core.textarea.value.length, yamlRender(core.ensureAst(), document, core.state.options.indent));
    } else if (axis) {
      core.replaceText(0, core.textarea.value.length, JSON.stringify(document, null, core.state.options.indent));
    } else {
      const sorted = group.slice().sort((a, b) => a.from - b.from);
      const from = sorted[0].from;
      const to = sorted.at(-1).to;
      let text = core.textarea.value.slice(from, to);
      for (const entry of sorted.reverse()) {
        text = text.slice(0, entry.from - from) + JSON.stringify(atPointer(document, entry.pointer))
          + text.slice(entry.to - from);
      }
      core.replaceText(from, to, text);
    }
    applying = false;
    if (mode.value === 'literal') {
      const history = recent.get(marker.field.type) || [];
      recent.set(marker.field.type, [value, ...history].slice(0, 8));
    }
    if (/\/(filter|type|operation)$/.test(marker.pointer)) {
      const target = `${marker.pointer.slice(0, marker.pointer.lastIndexOf('/'))}/options`;
      if (!followups.includes(target)) followups.push(target);
    }
    controller.refresh();
    const remaining = list();
    if (remaining.length) {
      const next = Math.max(0, Math.min(index + (direction < 0 ? -1 : 0), remaining.length - 1));
      show(remaining[next].pointer);
    } else {
      nextFollowup();
    }
    return true;
  }

  const controller = {
    start({pointers, fields: definitions = {}, keepFollowups = false} = {}) {
      if (core.state.readOnly) return false;
      if (!keepFollowups) followups = [];
      fields = {...fields, ...definitions};
      controller.refresh();
      active = new Set(markers.filter((marker) => !pointers || pointers.includes(marker.pointer))
        .map((marker) => marker.pointer));
      if (!active.size) return false;
      show(list()[0].pointer);
      if (!loading && options.getFunctions) {
        loading = Promise.resolve().then(options.getFunctions).then((result) => {
          catalogue = result || {};
          if (!disposed && current && ['$value', '$call'].includes(mode?.value)) {
            mode.dispatchEvent(new Event('change'));
          }
        }).catch((error) => {
          if (!disposed && message) message.textContent = `Function catalogue unavailable: ${error.message}`;
          options.onError?.(error);
        });
      }
      return true;
    },
    stop() {
      followups = [];
      close();
    },
    refresh() {
      if (applying) return;
      markers = findFills(core.ensureAst(), fields);
      const count = new Set(markers.map((marker) => marker.field.$fill)).size;
      badge.hidden = count === 0;
      badge.textContent = `${count} value${count === 1 ? '' : 's'} to fill`;
      if (current && !item()) {
        if (list().length) show(list()[0].pointer);
        else close();
      }
      reposition();
    },
    decorations: () => fillDecorations(markers, active, current),
    keydown(event) {
      if (core.state.readOnly || (event.key === 'Escape' && !popover.hidden && !current)) {
        close();
        return event.key === 'Escape';
      }
      if (event.key === 'Enter' && event.target?.tagName === 'BUTTON' && !popover.hidden) {
        event.target.click();
        return true;
      }
      if (!current || event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return false;
      if (event.target === input && ['ArrowUp', 'ArrowDown'].includes(event.key)) {
        const target = event.key === 'ArrowDown'
          ? popover.querySelector('[aria-label="Choose a value"]') || mode : mode;
        target.focus();
        return true;
      }
      if (event.key === 'Escape') {
        close();
        core.textarea.focus();
        return true;
      }
      if (event.key === 'Enter' && event.target?.tagName !== 'BUTTON') return accept(1) || true;
      if (event.key === 'Tab' && (event.target === input || event.target === core.textarea)) {
        const direction = event.shiftKey ? -1 : 1;
        if (dirty) accept(direction);
        else move(direction);
        return true;
      }
      return false;
    },
    fillRequired(pointer, {common = []} = {}) {
      if (core.state.readOnly) return [];
      const caret = pointerAt(core.ensureAst(), core.textarea.selectionStart);
      const target = pointer ?? caret.parentPointer ?? '';
      const context = resolved(target);
      const properties = missingProperties(context.schema, context.value, context.pointer, {common});
      if (!properties.length) return [];
      const root = data();
      const previous = atPointer(root, target);
      const object = isFill(previous) ? {} : {...previous};
      for (const property of properties) object[property.key] = property.value;
      let owner = target;
      let range = rangeOfPointer(core.ensureAst(), owner);
      const changed = replacing(root, target, object);
      while (!range && owner.includes('/')) {
        owner = owner.slice(0, owner.lastIndexOf('/'));
        range = rangeOfPointer(core.ensureAst(), owner);
      }
      if (!range) return [];
      if (core.ensureAst().format === 'yaml') {
        core.replaceText(0, core.textarea.value.length, yamlRender(core.ensureAst(), changed, core.state.options.indent));
      } else {
        const text = JSON.stringify(atPointer(changed, owner), null, core.state.options.indent);
        core.replaceText(range.from, range.to, text);
      }
      const pointers = properties.map((property) => context.base + property.pointer);
      controller.start({pointers, keepFollowups: true});
      return pointers;
    },
    offerFollowup(pointer, common) {
      if (core.state.readOnly) return false;
      common ??= core.state.options.commonProperties?.(pointer, data()) || [];
      const context = resolved(pointer);
      const properties = missingProperties(context.schema, context.value, context.pointer, {common});
      if (!properties.length) return false;
      close();
      popover.replaceChildren(h('strong', {}, 'Add properties for this choice'),
        h('div', {}, properties.map((property) => h('div', {},
          `${property.key}${property.required ? ' · required' : ''}`))),
        h('button', {type: 'button', class: 'button small',
          onClick: () => controller.fillRequired(pointer, {common})}, 'Add and fill'),
        h('button', {type: 'button', class: 'button small', onClick: nextFollowup}, 'Later'));
      popover.hidden = false;
      const anchor = core.anchorAt(core.textarea.selectionStart);
      popover.style.left = '0px';
      const bottom = core.view.root.clientHeight - popover.offsetHeight - badge.offsetHeight;
      popover.style.top = `${Math.max(0, Math.min(anchor.y, bottom))}px`;
      popover.querySelector('button').focus();
      return true;
    },
    destroy() {
      disposed = true;
      core.textarea.removeEventListener('scroll', reposition);
      popover.remove();
      badge.remove();
      recent.clear();
    },
  };
  core.textarea.addEventListener('scroll', reposition);
  controller.refresh();
  return controller;
}
