// Canvas interaction: pan, zoom, node drag, marquee, wire dragging, keyboard and palette drops.

import {debounce} from '../../lib/dom.mjs';
import {
  compatibility, nodesInRect, portIndex, portPosition, rectFrom, screenToWorld, wheelFactor, zoomAt,
} from './geometry.mjs';

export const ADAPTOR_MIME = 'application/x-schemaxis-adaptor';
const DRAG_THRESHOLD = 3;
const SNAP_RADIUS = 22;
const NUDGE = 8;

function isEditable(target) {
  return target && (target.closest('input, textarea, select, [contenteditable="true"]'));
}

export function installInput(ctx, model, canvas, handlers) {
  const element = canvas.element;
  let gesture = null;
  let spaceHeld = false;
  let pointerAt = 0;
  const pendingMoves = new Set();
  const commit = debounce(() => {
    const ids = [...pendingMoves];
    pendingMoves.clear();
    model.commitMoves(ids);
  }, 250);

  const local = (event) => {
    const rect = element.getBoundingClientRect();
    return {x: event.clientX - rect.left, y: event.clientY - rect.top};
  };
  const worldPoint = (event) => screenToWorld(canvas.viewport(), local(event));

  function selectedIds() {
    const selection = model.store.get().selection;
    return selection && selection.kind === 'nodes' ? selection.ids : [];
  }

  function outputPort(operation, name) {
    const node = model.node(operation);
    return node ? node.ports.outputs.find((port) => port.name === name) : null;
  }

  function inputPort(operation, name) {
    const node = model.node(operation);
    return node ? node.ports.inputs.find((port) => port.name === name) : null;
  }

  function startConnecting(operation, port, point, keyboard = false) {
    const source = outputPort(operation, port);
    if (!source) {
      return;
    }
    model.store.set({connecting: {from: {operation, port}, source, point, snap: null, target: null, keyboard}});
  }

  /** Nearest compatible input port within the snap radius (screen pixels). */
  function snapTarget(point) {
    const state = model.store.get();
    const connecting = state.connecting;
    const viewport = canvas.viewport();
    let best = null;
    for (const node of state.projection.nodes) {
      node.ports.inputs.forEach((port, index) => {
        if (!compatibility(connecting.source, port).ok) {
          return;
        }
        const position = portPosition(state.positions[node.id], 'inputs', index);
        const distance = Math.hypot(position.x - point.x, position.y - point.y) * viewport.zoom;
        if (distance <= SNAP_RADIUS && (!best || distance < best.distance)) {
          best = {distance, position, target: {operation: node.id, port: port.name}};
        }
      });
    }
    return best;
  }

  async function finishConnecting(target) {
    const connecting = model.store.get().connecting;
    model.store.set({connecting: null});
    if (!connecting || !target) {
      return;
    }
    const port = inputPort(target.operation, target.port);
    const verdict = compatibility(connecting.source, port);
    if (!verdict.ok) {
      const reasons = {occupied: 'That input already has a connection; add another input port for fan-in.',
        'port-kind': 'Value outputs connect to value inputs, and artifact outputs to artifact inputs.',
        'data-kind': 'The ports declare different data kinds.'};
      ctx.notify.warn('Ports are not compatible', {body: reasons[verdict.reason] || 'Choose another input port.'});
      return;
    }
    if (verdict.reason === 'data-kind') {
      ctx.notify.warn('Different data kinds', {body: 'The connection is allowed, but its data description differs. '
        + 'Review the warning before running the workflow.'});
    }
    await handlers.onConnect(connecting.from, target);
  }

  function onPointerDown(event) {
    pointerAt = Date.now();
    if (isEditable(event.target)) {
      return;
    }
    const chip = event.target.closest('[data-loop]');
    if (chip && event.button === 0) {
      event.stopPropagation();
      model.select({kind: 'loop', id: chip.dataset.loop});
      return;
    }
    if (event.target.closest('.dz-zoombar, .dz-minimap')) {
      return;
    }
    element.focus({preventScroll: true});
    const point = local(event);
    if (event.button === 1 || (event.button === 0 && spaceHeld)) {
      event.preventDefault();
      const viewport = canvas.viewport();
      gesture = {type: 'pan', start: point, origin: viewport};
      element.setPointerCapture(event.pointerId);
      element.classList.add('panning');
      return;
    }
    if (event.button !== 0) {
      return;
    }
    const port = event.target.closest('.dz-port');
    if (port && port.dataset.side === 'outputs') {
      event.preventDefault();
      startConnecting(port.dataset.node, port.dataset.port, worldPoint(event));
      gesture = {type: 'wire'};
      element.setPointerCapture(event.pointerId);
      return;
    }
    const card = event.target.closest('.dz-node');
    if (card) {
      const id = card.dataset.node;
      const ids = selectedIds();
      if (event.shiftKey) {
        const next = ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id];
        model.select(next.length ? {kind: 'nodes', ids: next} : null);
        gesture = null;
        return;
      }
      const moving = ids.includes(id) ? ids : [id];
      if (!ids.includes(id)) {
        model.select({kind: 'nodes', ids: [id]});
      }
      const positions = model.store.get().positions;
      gesture = {type: 'drag', start: point, moved: false, id,
        origins: Object.fromEntries(moving.map((item) => [item, {...positions[item]}]))};
      element.setPointerCapture(event.pointerId);
      return;
    }
    const edge = event.target.closest('[data-edge]');
    if (edge) {
      model.select({kind: 'edge', id: edge.dataset.edge});
      return;
    }
    if (event.shiftKey) {
      gesture = {type: 'marquee', start: point, base: selectedIds()};
      element.setPointerCapture(event.pointerId);
      return;
    }
    const viewport = canvas.viewport();
    gesture = {type: 'pan', start: point, origin: viewport, clear: true, moved: false};
    element.setPointerCapture(event.pointerId);
    element.classList.add('panning');
  }

  function onPointerMove(event) {
    const point = local(event);
    if (!gesture) {
      const edge = event.target.closest && event.target.closest('[data-edge]');
      canvas.hoverEdge(edge ? edge.dataset.edge : null);
      return;
    }
    const dx = point.x - gesture.start?.x;
    const dy = point.y - gesture.start?.y;
    if (gesture.type === 'pan') {
      if (Math.hypot(dx, dy) > DRAG_THRESHOLD) {
        gesture.moved = true;
      }
      canvas.setViewport({...gesture.origin, x: gesture.origin.x + dx, y: gesture.origin.y + dy});
    } else if (gesture.type === 'drag') {
      if (!gesture.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) {
        return;
      }
      gesture.moved = true;
      element.classList.add('dragging');
      const zoom = canvas.viewport().zoom;
      const moves = {};
      for (const [id, origin] of Object.entries(gesture.origins)) {
        moves[id] = {x: origin.x + dx / zoom, y: origin.y + dy / zoom};
      }
      model.moveLocal(moves);
    } else if (gesture.type === 'marquee') {
      const box = rectFrom(gesture.start, point);
      Object.assign(canvas.element.querySelector('.dz-marquee').style, {
        left: `${box.x}px`, top: `${box.y}px`, width: `${box.width}px`, height: `${box.height}px`});
      canvas.element.querySelector('.dz-marquee').hidden = false;
      const viewport = canvas.viewport();
      const worldBox = rectFrom(screenToWorld(viewport, gesture.start), screenToWorld(viewport, point));
      const state = model.store.get();
      const inside = nodesInRect(state.projection.nodes, state.positions, worldBox);
      const ids = [...new Set([...gesture.base, ...inside])];
      model.select(ids.length ? {kind: 'nodes', ids} : null);
    } else if (gesture.type === 'wire') {
      const current = model.store.get().connecting;
      if (!current) {
        return;
      }
      const at = worldPoint(event);
      const snap = snapTarget(at);
      model.store.set({connecting: {...current, point: at, snap: snap ? snap.position : null,
        target: snap ? snap.target : null}});
    }
  }

  function onPointerUp(event) {
    const done = gesture;
    gesture = null;
    element.classList.remove('panning', 'dragging');
    if (element.hasPointerCapture(event.pointerId)) {
      element.releasePointerCapture(event.pointerId);
    }
    if (!done) {
      return;
    }
    if (done.type === 'pan' && done.clear && !done.moved) {
      model.select(null);
    } else if (done.type === 'drag') {
      if (done.moved) {
        for (const id of Object.keys(done.origins)) {
          pendingMoves.add(id);
        }
        commit();
      } else {
        model.select({kind: 'nodes', ids: [done.id]});
      }
    } else if (done.type === 'marquee') {
      canvas.element.querySelector('.dz-marquee').hidden = true;
    } else if (done.type === 'wire') {
      const connecting = model.store.get().connecting;
      let target = connecting && connecting.target;
      if (!target) {
        const under = document.elementFromPoint(event.clientX, event.clientY);
        const port = under && under.closest('.dz-port.in');
        target = port ? {operation: port.dataset.node, port: port.dataset.port} : null;
      }
      finishConnecting(target);
    }
  }

  function onWheel(event) {
    if (event.target.closest('.dz-minimap')) {
      return;
    }
    event.preventDefault();
    if (!event.ctrlKey && Math.abs(event.deltaX) > Math.abs(event.deltaY) * 2) {
      const viewport = canvas.viewport();
      canvas.setViewport({...viewport, x: viewport.x - event.deltaX});
      return;
    }
    canvas.setViewport(zoomAt(canvas.viewport(), local(event), wheelFactor(event.deltaY, event.deltaMode)));
  }

  function nudge(dx, dy) {
    const ids = selectedIds();
    if (!ids.length) {
      return;
    }
    const positions = model.store.get().positions;
    const moves = {};
    for (const id of ids) {
      moves[id] = {x: positions[id].x + dx, y: positions[id].y + dy};
      pendingMoves.add(id);
    }
    model.moveLocal(moves);
    commit();
  }

  function onPortKey(event, port) {
    const connecting = model.store.get().connecting;
    if (port.dataset.side === 'outputs' && !connecting) {
      startConnecting(port.dataset.node, port.dataset.port, null, true);
      ctx.notify.info('Choose an input port', {body: 'Move to a highlighted input port and press Enter. '
        + 'Escape cancels.'});
      return true;
    }
    if (port.dataset.side === 'inputs' && connecting) {
      finishConnecting({operation: port.dataset.node, port: port.dataset.port});
      return true;
    }
    return false;
  }

  function onKeyDown(event) {
    if (isEditable(event.target)) {
      return;
    }
    const modifier = event.ctrlKey || event.metaKey;
    const key = event.key;
    if (key === ' ' && !modifier) {
      spaceHeld = true;
      element.classList.add('space');
      event.preventDefault();
      return;
    }
    if (key === 'Enter') {
      const port = event.target.closest && event.target.closest('.dz-port');
      if (port && onPortKey(event, port)) {
        event.preventDefault();
        return;
      }
      const card = event.target.closest && event.target.closest('.dz-node');
      if (card) {
        event.preventDefault();
        model.select({kind: 'nodes', ids: [card.dataset.node]});
        return;
      }
    }
    if (key === 'Escape') {
      if (model.store.get().connecting) {
        model.store.set({connecting: null});
      } else {
        model.select(null);
      }
      return;
    }
    if (key === 'Delete' || key === 'Backspace') {
      event.preventDefault();
      handlers.onDelete();
      return;
    }
    if (modifier && (key === '=' || key === '+')) {
      event.preventDefault();
      canvas.zoomBy(1.2);
    } else if (modifier && key === '-') {
      event.preventDefault();
      canvas.zoomBy(1 / 1.2);
    } else if (modifier && key === '0') {
      event.preventDefault();
      canvas.zoomTo(1);
    } else if (modifier && key.toLowerCase() === 'a') {
      event.preventDefault();
      const projection = model.store.get().projection;
      model.select(projection && projection.nodes.length ? {kind: 'nodes', ids: projection.nodes.map((n) => n.id)}
        : null);
    } else if (!modifier && (key === 'f' || key === 'F')) {
      event.preventDefault();
      canvas.fit();
    } else if (!modifier && key.startsWith('Arrow') && event.target.closest('.dz-node, .dz-canvas')
      && !event.target.closest('.dz-port')) {
      const step = event.shiftKey ? NUDGE * 4 : NUDGE;
      const delta = {ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step]}[key];
      if (selectedIds().length) {
        event.preventDefault();
        nudge(...delta);
      }
    }
  }

  function onKeyUp(event) {
    if (event.key === ' ') {
      spaceHeld = false;
      element.classList.remove('space');
    }
  }

  function onFocusIn(event) {
    if (Date.now() - pointerAt < 600) {
      return; // Pointer selection already ran; focus follows it.
    }
    const card = event.target.classList && event.target.classList.contains('dz-node') ? event.target : null;
    if (card && !selectedIds().includes(card.dataset.node)) {
      model.select({kind: 'nodes', ids: [card.dataset.node]});
    }
  }

  function onDragOver(event) {
    if (event.dataTransfer && [...event.dataTransfer.types].includes(ADAPTOR_MIME)) {
      event.preventDefault();
      event.dataTransfer.dropEffect = 'copy';
      element.classList.add('drop-target');
    }
  }

  function onDrop(event) {
    element.classList.remove('drop-target');
    const adaptor = event.dataTransfer && event.dataTransfer.getData(ADAPTOR_MIME);
    if (!adaptor) {
      return;
    }
    event.preventDefault();
    const point = worldPoint(event);
    handlers.onDropAdaptor(adaptor, {x: Math.round(point.x - 124), y: Math.round(point.y - 28)});
  }

  function onDragLeave(event) {
    if (event.target === element) {
      element.classList.remove('drop-target');
    }
  }

  function onDoubleClick(event) {
    const card = event.target.closest('.dz-node');
    if (card && handlers.onOpenNode) {
      handlers.onOpenNode(card.dataset.node);
    }
  }

  const listeners = [
    ['pointerdown', onPointerDown], ['pointermove', onPointerMove], ['pointerup', onPointerUp],
    ['pointercancel', onPointerUp], ['wheel', onWheel, {passive: false}], ['keydown', onKeyDown],
    ['keyup', onKeyUp], ['focusin', onFocusIn], ['dragover', onDragOver], ['drop', onDrop],
    ['dragleave', onDragLeave], ['dblclick', onDoubleClick],
    ['pointerleave', () => canvas.hoverEdge(null)],
  ];
  for (const [name, listener, options] of listeners) {
    element.addEventListener(name, listener, options);
  }
  return () => {
    commit.cancel();
    if (pendingMoves.size) model.commitMoves([...pendingMoves]);
    for (const [name, listener, options] of listeners) {
      element.removeEventListener(name, listener, options);
    }
  };
}

/** World position of a port for tests and keyboard focus helpers. */
export function portWorld(model, operation, side, name) {
  const state = model.store.get();
  const node = model.node(operation);
  const index = node ? portIndex(node, side, name) : -1;
  return index < 0 ? null : portPosition(state.positions[operation], side, index);
}
