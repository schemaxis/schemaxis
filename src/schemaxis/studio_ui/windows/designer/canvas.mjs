// Designer canvas: an HTML world layer (node cards) over an SVG wire layer, both under
// one pan/zoom transform. Interaction lives in canvas-input.mjs, the minimap in minimap.mjs.

import {debounce, h, icon, s} from '../../lib/dom.mjs';
import {avatar, identity} from '../../shell/providers.mjs';
import {
  HEADER_HEIGHT, NODE_WIDTH, PORT_PAD_BOTTOM, PORT_PAD_TOP, PORT_ROW, arrowPath, bezierPath, edgeRoute,
  compatibility, dataKind, edgeEndpoints, fitViewport, kindColour, nodeHeight, nodesBounds, portPosition,
} from './geometry.mjs';
import {installInput} from './canvas-input.mjs';
import {createMinimap} from './minimap.mjs';

const GRID = 24;

function portLabel(node, side, port) {
  const kind = dataKind(port) || 'unknown data';
  const direction = side === 'inputs' ? 'Input' : 'Output';
  return `${direction} port ${port.name} of ${node.id}: ${kind}, ${port.kind}`;
}

function portElement(node, side, port, connecting) {
  const kind = dataKind(port);
  const classes = ['dz-port', side === 'inputs' ? 'in' : 'out', port.kind === 'value' ? 'value' : 'artifact',
    (port.connections || []).length && 'connected'];
  if (connecting) {
    if (side === 'inputs') {
      const source = connecting.source;
      const verdict = compatibility(source, port);
      classes.push(verdict.ok ? 'compatible' : 'incompatible');
      if (verdict.reason === 'data-kind') classes.push('advisory');
    } else if (connecting.from.operation === node.id && connecting.from.port === port.name) {
      classes.push('source');
    } else {
      classes.push('inert');
    }
  }
  const title = side === 'inputs' ? port.target : `artifact ${port.artifact}${port.valuePath ? port.valuePath : ''}`;
  return h('div', {
    class: classes, tabindex: '0', role: 'button', title,
    'aria-label': portLabel(node, side, port),
    dataset: {node: node.id, port: port.name, side, key: `port:${node.id}:${side}:${port.name}`},
    style: {'--port': kindColour(kind)},
  },
  h('span', {class: 'dz-dot', 'aria-hidden': 'true'}),
  h('span', {class: 'dz-port-name'}, port.label || port.name),
  h('span', {class: 'dz-port-kind'}, kind || port.kind));
}

function nodeElement(node, state, loops, warned) {
  const selected = state.selection && state.selection.kind === 'nodes' && state.selection.ids.includes(node.id);
  const info = identity(node.provider);
  const inputs = node.ports.inputs || [];
  const outputs = node.ports.outputs || [];
  const rows = [];
  const count = Math.max(inputs.length, outputs.length);
  for (let index = 0; index < count; index += 1) {
    rows.push(h('div', {class: 'dz-port-row'},
      inputs[index] ? portElement(node, 'inputs', inputs[index], state.connecting) : h('span'),
      outputs[index] ? portElement(node, 'outputs', outputs[index], state.connecting) : h('span')));
  }
  const loop = loops.find((item) => item.members.includes(node.id));
  const chips = [];
  if (loop) {
    chips.push(h('button', {class: 'dz-chip loop', tabindex: '-1', title: 'Feedback loop: open its settings',
      dataset: {loop: loop.id}}, icon('loop'), 'Loop'));
  }
  if (warned.has(node.id)) {
    chips.push(h('span', {class: 'dz-chip warn', title: 'A connection declares mismatched data'},
      icon('alert'), 'Check'));
  }
  const position = state.positions[node.id] || {x: 0, y: 0};
  return h('div', {
    class: ['dz-node', selected && 'selected', loop && 'loop'],
    tabindex: '0', role: 'group',
    'aria-label': `${node.id}, ${info.name} operation with ${inputs.length} inputs and ${outputs.length} outputs`,
    'aria-selected': String(Boolean(selected)),
    dataset: {node: node.id, key: `node:${node.id}`},
    style: {width: `${NODE_WIDTH}px`, height: `${nodeHeight(node)}px`,
      transform: `translate(${position.x}px, ${position.y}px)`},
  },
  h('div', {class: 'dz-node-header'},
    avatar(node.provider),
    h('div', {class: 'dz-node-titles'},
      h('div', {class: 'dz-node-id'}, node.id),
      h('div', {class: 'dz-node-adaptor'}, info.name)),
    chips.length ? h('div', {class: 'dz-node-chips'}, chips) : null),
  h('div', {class: 'dz-node-ports'},
    rows.length ? rows : h('div', {class: 'dz-node-hint'}, 'No ports yet · add them in the inspector')));
}

export function createCanvas(ctx, model, handlers) {
  const prefix = `dz${Math.random().toString(36).slice(2, 8)}`;
  const edgesLayer = s('g', {class: 'dz-edge-layer'});
  const wireLayer = s('g', {class: 'dz-wire-layer'});
  const svg = s('svg', {class: 'dz-svg', width: '1', height: '1', 'aria-hidden': 'true'}, edgesLayer, wireLayer);
  const nodesLayer = h('div', {class: 'dz-nodes'});
  const labelsLayer = h('div', {class: 'dz-labels'});
  const world = h('div', {class: 'dz-world'}, svg, nodesLayer, labelsLayer);
  const marquee = h('div', {class: 'dz-marquee', hidden: true});
  const zoomLabel = h('button', {class: 'dz-zoom-value', title: 'Reset zoom to 100%',
    onClick: () => api.zoomTo(1)}, '100%');
  const zoombar = h('div', {class: 'dz-zoombar', role: 'toolbar', 'aria-label': 'Zoom'},
    h('button', {class: 'button ghost small icon-only', 'aria-label': 'Zoom out', title: 'Zoom out (Ctrl -)',
      onClick: () => api.zoomBy(1 / 1.2)}, h('span', {class: 'dz-glyph'}, '−')),
    zoomLabel,
    h('button', {class: 'button ghost small icon-only', 'aria-label': 'Zoom in', title: 'Zoom in (Ctrl =)',
      onClick: () => api.zoomBy(1.2)}, h('span', {class: 'dz-glyph'}, '+')),
    h('span', {class: 'dz-zoombar-sep'}),
    h('button', {class: 'button ghost small', title: 'Fit the design in view (F)', onClick: () => api.fit()},
      'Fit'));
  const empty = h('div', {class: 'dz-empty', hidden: true},
    h('div', {class: 'dz-empty-mark'}, icon('flow')),
    h('h3', {}, 'Start your workflow'),
    h('p', {}, 'Drag an adaptor from the palette onto the canvas, or double-click it, to add an operation.'));
  const faultView = h('div', {class: 'dz-fault', hidden: true});
  const element = h('div', {class: 'dz-canvas', tabindex: '0', role: 'application',
    'aria-label': 'Workflow canvas. Shift-drag to select, drag the background to pan, F to fit.'},
  world, marquee, empty, faultView, zoombar);
  const minimap = createMinimap(model, element, (viewport) => api.setViewport(viewport));
  element.append(minimap.element);

  let size = {width: 0, height: 0};
  let hoverEdge = null;
  let fittedOnce = false;

  const api = {element, world, prefix};
  let unsavedViewport = false;
  const commitViewport = () => {
    if (!unsavedViewport || !model.store.get().projection) return;
    unsavedViewport = false;
    model.action('move', {positions: {}, viewport: api.viewport()}, {title: 'Could not save the viewport'});
  };
  const saveViewport = debounce(commitViewport, 400);

  api.size = () => size;
  api.isDirty = () => unsavedViewport;

  api.viewport = () => model.store.get().viewport || {x: 0, y: 0, zoom: 1};

  api.setViewport = (viewport, {persist = true} = {}) => {
    model.store.set({viewport});
    if (persist) {
      unsavedViewport = true;
      saveViewport();
    }
  };

  api.zoomBy = (factor, cursor = {x: size.width / 2, y: size.height / 2}) => {
    const viewport = api.viewport();
    const zoom = Math.min(2.5, Math.max(0.2, viewport.zoom * factor));
    const ratio = zoom / viewport.zoom;
    api.setViewport({x: cursor.x - (cursor.x - viewport.x) * ratio, y: cursor.y - (cursor.y - viewport.y) * ratio,
      zoom});
  };

  api.zoomTo = (zoom) => api.zoomBy(zoom / api.viewport().zoom);

  api.fit = ({persist = true} = {}) => {
    const state = model.store.get();
    if (!state.projection) {
      return;
    }
    const bounds = nodesBounds(state.projection.nodes, state.positions);
    api.setViewport(bounds ? fitViewport(bounds, size, {padding: 72, maxZoom: 1})
      : {x: 0, y: 0, zoom: 1}, {persist});
  };

  api.focusNode = (id) => {
    const target = nodesLayer.querySelector(`[data-key="${CSS.escape(`node:${id}`)}"]`);
    if (target) {
      target.focus({preventScroll: true});
    }
  };

  function applyViewport() {
    const viewport = api.viewport();
    world.style.transform = `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`;
    const grid = GRID * viewport.zoom;
    element.style.setProperty('--dz-grid', `${grid}px`);
    element.style.setProperty('--dz-grid-x', `${viewport.x}px`);
    element.style.setProperty('--dz-grid-y', `${viewport.y}px`);
    element.style.setProperty('--dz-dot', `${Math.max(1, Math.min(1.6, viewport.zoom * 1.2))}px`);
    zoomLabel.textContent = `${Math.round(viewport.zoom * 100)}%`;
  }

  function renderNodes() {
    const state = model.store.get();
    const projection = state.projection;
    const focusedKey = document.activeElement && nodesLayer.contains(document.activeElement)
      ? document.activeElement.dataset.key : null;
    if (!projection) {
      nodesLayer.replaceChildren();
      return;
    }
    const warned = new Set();
    for (const warning of projection.warnings || []) {
      const connection = projection.connections.find((item) => item.id === warning.connection);
      if (connection) {
        warned.add(connection.from.operation);
        warned.add(connection.to.operation);
      }
    }
    nodesLayer.replaceChildren(...projection.nodes.map((node) => nodeElement(node, state, projection.loops, warned)));
    const markers = projection.loops.map((loop) => loopMarker(loop, projection, state));
    labelsLayer.replaceChildren(...markers.filter(Boolean));
    if (focusedKey) {
      const again = nodesLayer.querySelector(`[data-key="${CSS.escape(focusedKey)}"]`);
      if (again) {
        again.focus({preventScroll: true});
      }
    }
    empty.hidden = projection.nodes.length > 0;
  }

  function loopMarker(loop, projection, state) {
    const members = projection.nodes.filter((node) => loop.members.includes(node.id));
    const bounds = nodesBounds(members, state.positions);
    if (!bounds) {
      return null;
    }
    const selected = state.selection && state.selection.kind === 'loop' && state.selection.id === loop.id;
    return h('button', {
      class: ['dz-loop-marker', selected && 'selected', loop.status], dataset: {loop: loop.id},
      title: 'Feedback loop settings',
      style: {transform: `translate(${bounds.x + bounds.width / 2}px, ${bounds.y - 18}px) translate(-50%, -100%)`},
    }, icon('loop'), loop.status === 'configured' ? 'Feedback loop · configured' : 'Feedback loop · needs settings');
  }

  function placeNodes() {
    const state = model.store.get();
    for (const card of nodesLayer.children) {
      const position = state.positions[card.dataset.node];
      if (position) {
        card.style.transform = `translate(${position.x}px, ${position.y}px)`;
      }
    }
    if (state.projection) {
      for (const marker of labelsLayer.querySelectorAll('.dz-loop-marker')) {
        const loop = state.projection.loops.find((item) => item.id === marker.dataset.loop);
        const members = state.projection.nodes.filter((node) => loop && loop.members.includes(node.id));
        const bounds = nodesBounds(members, state.positions);
        if (bounds) {
          marker.style.transform = `translate(${bounds.x + bounds.width / 2}px, ${bounds.y - 18}px) `
            + 'translate(-50%, -100%)';
        }
      }
    }
  }

  function edgeLabel(edge, middle) {
    const text = edge.dataKind ? `${edge.dataKind} · ${edge.kind}` : edge.kind === 'document-reference'
      ? 'authored reference' : edge.kind;
    return h('div', {class: 'dz-edge-label', style: {transform: `translate(${middle.x}px, ${middle.y}px) `
      + 'translate(-50%, -50%)'}}, text);
  }

  function renderEdges() {
    const state = model.store.get();
    const projection = state.projection;
    edgesLayer.replaceChildren();
    for (const old of labelsLayer.querySelectorAll('.dz-edge-label')) {
      old.remove();
    }
    if (!projection) {
      return;
    }
    const byId = new Map(projection.nodes.map((node) => [node.id, node]));
    const loopEdges = new Set(projection.loops.flatMap((loop) => loop.edgeIds));
    const selectedLoop = state.selection && state.selection.kind === 'loop' ? model.loop(state.selection.id) : null;
    const selectedNodes = state.selection && state.selection.kind === 'nodes' ? state.selection.ids : [];
    const box = (id) => ({...state.positions[id], width: NODE_WIDTH, height: nodeHeight(byId.get(id))});
    let lanes = 0;
    for (const edge of projection.edges) {
      const ends = edgeEndpoints(edge, byId, state.positions);
      if (!ends) {
        continue;
      }
      const base = edge.from.port === null || edge.to.port === null;
      const route = edgeRoute(ends.from, ends.to, {boxes: [box(edge.source), box(edge.target)], lane: lanes});
      if (route.backward) {
        lanes += 1;
      }
      const selected = (state.selection && state.selection.kind === 'edge' && state.selection.id === edge.id)
        || (selectedLoop && selectedLoop.edgeIds.includes(edge.id));
      const related = selectedNodes.includes(edge.source) || selectedNodes.includes(edge.target);
      const classes = ['dz-edge', base && 'base', loopEdges.has(edge.id) && 'loop', selected && 'selected',
        related && 'related', hoverEdge === edge.id && 'hover'];
      const colour = base ? 'var(--edge)' : kindColour(edge.dataKind);
      const path = route.d;
      edgesLayer.append(s('g', {class: classes, dataset: {edge: edge.id}, style: {'--wire': colour}},
        s('path', {class: 'dz-edge-hit', d: path}),
        s('path', {class: 'dz-edge-line', d: path}),
        base ? null : s('path', {class: 'dz-edge-arrow', d: arrowPath({x: ends.to.x - 5, y: ends.to.y})})));
      if (hoverEdge === edge.id || selected) {
        labelsLayer.append(edgeLabel(edge, route.mid));
      }
    }
    renderWire();
  }

  function renderWire() {
    const state = model.store.get();
    wireLayer.replaceChildren();
    const connecting = state.connecting;
    if (!connecting || !connecting.point || !state.projection) {
      return;
    }
    const node = model.node(connecting.from.operation);
    const index = node ? node.ports.outputs.findIndex((port) => port.name === connecting.from.port) : -1;
    if (index < 0) {
      return;
    }
    const from = portPosition(state.positions[node.id], 'outputs', index);
    const to = connecting.snap || connecting.point;
    wireLayer.append(s('path', {class: ['dz-wire', connecting.snap && 'snapped'], d: bezierPath(from, to),
      style: {'--wire': kindColour(dataKind(connecting.source))}}));
  }

  api.hoverEdge = (id) => {
    if (hoverEdge !== id) {
      hoverEdge = id;
      renderEdges();
    }
  };

  function renderFault(state) {
    faultView.hidden = !state.fault;
    if (state.fault) {
      faultView.replaceChildren(
        h('div', {class: 'dz-fault-icon'}, icon('error')),
        h('h3', {}, 'This design cannot be shown'),
        h('p', {}, state.fault.message || 'The design is invalid.'),
        state.fault.location ? h('code', {}, state.fault.location) : null,
        h('p', {class: 'muted'}, 'Undo the last change, or correct the design in the Source tab.'));
    }
  }

  const unsubscribe = model.store.subscribe((state, previous) => {
    if (state.viewport !== previous.viewport) {
      applyViewport();
    }
    const structural = state.projection !== previous.projection || state.selection !== previous.selection
      || Boolean(state.connecting) !== Boolean(previous.connecting)
      || (state.connecting && previous.connecting && state.connecting.from !== previous.connecting.from);
    if (structural) {
      renderNodes();
      renderEdges();
    } else if (state.positions !== previous.positions) {
      placeNodes();
      renderEdges();
    } else if (state.connecting !== previous.connecting) {
      renderWire();
    }
    if (state.fault !== previous.fault) {
      renderFault(state);
    }
    if (state.projection && !previous.projection && !fittedOnce && size.width) {
      initialView();
    }
    minimap.update();
  });

  function initialView() {
    fittedOnce = true;
    const state = model.store.get();
    const saved = state.projection.layout && state.projection.layout.viewport;
    if (saved) {
      api.setViewport(saved, {persist: false});
    } else {
      api.fit({persist: false});
    }
  }

  const observer = new ResizeObserver(() => {
    size = {width: element.clientWidth, height: element.clientHeight};
    if (!fittedOnce && size.width && model.store.get().projection) {
      initialView();
    }
    minimap.update();
  });
  observer.observe(element);

  const removeInput = installInput(ctx, model, api, handlers);
  applyViewport();
  element.style.setProperty('--dz-header', `${HEADER_HEIGHT}px`);
  element.style.setProperty('--dz-row', `${PORT_ROW}px`);
  element.style.setProperty('--dz-pad-top', `${PORT_PAD_TOP}px`);
  element.style.setProperty('--dz-pad-bottom', `${PORT_PAD_BOTTOM}px`);

  api.dispose = () => {
    saveViewport.cancel();
    commitViewport();
    unsubscribe();
    observer.disconnect();
    removeInput();
    minimap.dispose();
  };
  return api;
}
