// Minimap: shown bottom-right when the design exceeds the view; click or drag to move the view.

import {h, s} from '../../lib/dom.mjs';
import {NODE_WIDTH, contentExceeds, minimapTransform, nodeHeight, nodesBounds} from './geometry.mjs';

const SIZE = {width: 200, height: 136};

export function createMinimap(model, canvasElement, setViewport) {
  const nodesGroup = s('g', {class: 'dz-mini-nodes'});
  const view = s('rect', {class: 'dz-mini-view', rx: '3'});
  const svg = s('svg', {width: String(SIZE.width), height: String(SIZE.height),
    viewBox: `0 0 ${SIZE.width} ${SIZE.height}`}, nodesGroup, view);
  const element = h('div', {class: 'dz-minimap', hidden: true, 'aria-hidden': 'true'}, svg);
  let transform = null;
  let dragging = false;

  function size() {
    return {width: canvasElement.clientWidth, height: canvasElement.clientHeight};
  }

  function update() {
    const state = model.store.get();
    const projection = state.projection;
    const viewport = state.viewport;
    const box = size();
    const bounds = projection ? nodesBounds(projection.nodes, state.positions) : null;
    const show = Boolean(viewport && bounds && box.width && contentExceeds(bounds, viewport, box));
    element.hidden = !show;
    if (!show) {
      return;
    }
    transform = minimapTransform(bounds, viewport, box, SIZE);
    const loops = new Set(projection.loops.flatMap((loop) => loop.members));
    const selected = state.selection && state.selection.kind === 'nodes' ? state.selection.ids : [];
    nodesGroup.replaceChildren(...projection.nodes.map((node) => {
      const position = state.positions[node.id];
      const corner = transform.toMini(position);
      return s('rect', {
        class: ['dz-mini-node', loops.has(node.id) && 'loop', selected.includes(node.id) && 'selected'],
        x: String(corner.x), y: String(corner.y), rx: '2',
        width: String(Math.max(2, NODE_WIDTH * transform.scale)),
        height: String(Math.max(2, nodeHeight(node) * transform.scale)),
      });
    }));
    const corner = transform.toMini(transform.view);
    view.setAttribute('x', String(corner.x));
    view.setAttribute('y', String(corner.y));
    view.setAttribute('width', String(transform.view.width * transform.scale));
    view.setAttribute('height', String(transform.view.height * transform.scale));
  }

  function centreAt(event) {
    if (!transform) {
      return;
    }
    const rect = svg.getBoundingClientRect();
    const point = transform.toWorld({x: event.clientX - rect.left, y: event.clientY - rect.top});
    const viewport = model.store.get().viewport;
    const box = size();
    setViewport({zoom: viewport.zoom, x: box.width / 2 - point.x * viewport.zoom,
      y: box.height / 2 - point.y * viewport.zoom});
  }

  element.addEventListener('pointerdown', (event) => {
    event.stopPropagation();
    dragging = true;
    element.setPointerCapture(event.pointerId);
    centreAt(event);
  });
  element.addEventListener('pointermove', (event) => {
    if (dragging) {
      centreAt(event);
    }
  });
  element.addEventListener('pointerup', (event) => {
    dragging = false;
    element.releasePointerCapture(event.pointerId);
  });

  return {element, update, dispose: () => {}};
}
