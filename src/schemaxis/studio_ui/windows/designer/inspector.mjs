// Copyright (C) 2026 David L F Gaden
// Inspector: design summary, edge details, and dispatch to node and loop panels.

import {h, icon, mount} from '../../lib/dom.mjs';
import {humanise} from '../../shell/notify.mjs';
import {kindColour} from './geometry.mjs';
import {nodePanel} from './inspector-node.mjs';
import {loopPanel} from './inspector-loop.mjs';

const STATUS = {
  empty: {label: 'Empty', tone: ''},
  ready: {label: 'Ready to compile', tone: 'ok'},
  'feedback-configuration-required': {label: 'Loop needs settings', tone: 'loop'},
  'feedback-execution-unavailable': {label: 'Feedback design', tone: 'loop'},
};

export function statusBadge(status) {
  const info = STATUS[status] || {label: humanise(status ? status.replaceAll('-', '_').toUpperCase() : 'UNKNOWN'),
    tone: ''};
  return h('span', {class: ['badge', info.tone]}, info.label);
}

export function section(title, ...children) {
  return h('section', {class: 'dz-section'}, h('h4', {class: 'section-title'}, title), children);
}

function stat(value, label) {
  return h('div', {class: 'dz-stat'}, h('div', {class: 'dz-stat-value'}, String(value)),
    h('div', {class: 'dz-stat-label'}, label));
}

function summaryPanel(model, actions) {
  const projection = model.store.get().projection;
  const warnings = projection.warnings || [];
  const compileReason = projection.loops.length ? 'Feedback loops cannot compile yet; remove a connection in each '
    + 'loop to compile a DAG.' : !projection.nodes.length ? 'Add operations first.'
      : projection.unfilled?.length ? 'Fill the remaining values before compiling the workflow.' : '';
  return h('div', {class: 'dz-inspector-body'},
    h('div', {class: 'dz-inspector-title'},
      h('div', {class: 'dz-inspector-icon'}, icon('flow')),
      h('div', {}, h('h3', {}, model.store.get().name || 'Workflow design'),
        h('div', {class: 'subtitle'}, 'Design summary')),
      statusBadge(projection.status)),
    h('div', {class: 'dz-stats'},
      stat(projection.nodes.length, 'operations'),
      stat(projection.connections.length, 'connections'),
      stat(projection.loops.length, 'loops'),
      stat(Object.keys(projection.parameters || {}).length, 'parameters')),
    section('Validation', warnings.length ? h('ul', {class: 'dz-warnings'}, warnings.map((warning) => h('li', {
      class: 'dz-warning', role: 'button', tabindex: '0',
      onClick: () => model.select({kind: 'edge', id: warning.connection}),
      onKeydown: (event) => {
        if (event.key === 'Enter') {
          model.select({kind: 'edge', id: warning.connection});
        }
      },
    }, icon('alert'), h('div', {}, h('div', {}, warning.message),
      h('div', {class: 'muted mono'}, `${warning.connection}: ${JSON.stringify(warning.from)} → `
        + `${JSON.stringify(warning.to)}`)))))
      : h('div', {class: 'dz-calm'}, icon('check'), projection.nodes.length ? 'No data mismatches declared.'
        : 'Nothing to validate yet.')),
    section('Deliver',
      h('div', {class: 'dz-button-column'},
        h('button', {class: 'button primary', disabled: !projection.compilationAvailable,
          title: compileReason || 'Compile to an ordinary workflow document', onClick: actions.compile},
        icon('play'), 'Compile workflow'),
        h('button', {class: 'button', disabled: !projection.templateExportAvailable,
          title: (!projection.templateExportAvailable && compileReason)
          || 'Write a template bundle for the Case Runner', onClick: actions.exportTemplate},
        icon('folder'), 'Export template…')),
      compileReason ? h('p', {class: 'hint'}, compileReason) : null),
    section('Tips', h('ul', {class: 'dz-tips'},
      h('li', {}, 'Drag from an output port to an input port to connect.'),
      h('li', {}, 'Shift-drag selects several operations; Delete removes them.'),
      h('li', {}, 'Drag the background, or hold Space, to pan. F fits the view.'))));
}

function endpoint(model, end, side) {
  const node = model.node(end.operation);
  const port = node && end.port !== null ? node.ports[side].find((item) => item.name === end.port) : null;
  return h('button', {class: 'dz-endpoint', onClick: () => model.select({kind: 'nodes', ids: [end.operation]})},
    h('span', {class: 'dz-dot-static', style: {'--port': kindColour(port && port.data && port.data.kind)}}),
    h('span', {class: 'mono'}, end.port === null ? end.operation : `${end.operation}.${end.port}`));
}

function edgePanel(model, actions, edge) {
  const base = edge.from.port === null || edge.to.port === null;
  const loops = model.loopsOf(model.store.get().projection, {edge: edge.id});
  const rows = [
    ['Kind', edge.kind],
    ['Data kind', edge.dataKind || 'unspecified'],
    ['Artifact', edge.artifactIndex ?? '—'],
    ['Value path', edge.kind === 'value' ? edge.valuePath : '—'],
    ['Target input', edge.targetPointer],
    ['Origin', base ? 'Authored reference in the operation document' : 'Design connection'],
  ];
  return h('div', {class: 'dz-inspector-body'},
    h('div', {class: 'dz-inspector-title'},
      h('div', {class: 'dz-inspector-icon'}, icon('chevron-right')),
      h('div', {}, h('h3', {class: 'mono'}, edge.id), h('div', {class: 'subtitle'},
        base ? 'Authored reference' : 'Connection')),
      loops.length ? h('span', {class: 'badge loop'}, icon('loop'), 'In loop') : null),
    section('Endpoints', h('div', {class: 'dz-endpoints'}, endpoint(model, edge.from, 'outputs'),
      h('span', {class: 'dz-endpoint-arrow', 'aria-hidden': 'true'}, '→'), endpoint(model, edge.to, 'inputs'))),
    section('Details', h('dl', {class: 'kv'}, rows.flatMap(([label, value]) => [h('dt', {}, label),
      h('dd', {class: typeof value === 'string' && value.startsWith('/') ? 'mono' : ''}, String(value))]))),
    loops.length ? h('button', {class: 'button', onClick: () => model.select({kind: 'loop', id: loops[0].id})},
      icon('loop'), 'Loop settings') : null,
    base ? h('p', {class: 'dz-calm'}, icon('info'), 'Authored references are part of an operation document and '
      + 'are not removable here. Edit them in the Source tab or the Adaptor Workbench.')
      : h('button', {class: 'button danger', onClick: () => actions.disconnect(edge.id)}, icon('close'),
        'Remove connection'));
}

export function createInspector(ctx, model, actions) {
  const element = h('aside', {class: 'dz-inspector', 'aria-label': 'Inspector'});
  let token = 0;
  const render = () => {
    const state = model.store.get();
    token += 1;
    if (!state.projection) {
      mount(element, h('div', {class: 'dz-inspector-body'}, h('div', {class: 'empty-state'},
        icon(state.fault ? 'error' : 'spinner'), state.fault ? 'The design could not be loaded.' : 'Loading…')));
      return;
    }
    const selection = state.selection;
    let body;
    if (selection && selection.kind === 'nodes' && selection.ids.length === 1) {
      body = nodePanel(ctx, model, actions, model.node(selection.ids[0]), token);
    } else if (selection && selection.kind === 'nodes') {
      body = h('div', {class: 'dz-inspector-body'},
        h('div', {class: 'dz-inspector-title'}, h('div', {class: 'dz-inspector-icon'}, icon('layers')),
          h('div', {}, h('h3', {}, `${selection.ids.length} operations`), h('div', {class: 'subtitle'},
            selection.ids.join(', ')))),
        h('button', {class: 'button danger', onClick: () => actions.removeOperations(selection.ids)},
          icon('close'), 'Remove selected'));
    } else if (selection && selection.kind === 'edge') {
      body = edgePanel(model, actions, model.edge(selection.id));
    } else if (selection && selection.kind === 'loop') {
      body = loopPanel(model, actions, model.loop(selection.id));
    } else {
      body = summaryPanel(model, actions);
    }
    mount(element, h('div', {class: 'dz-pane-header'}, h('span', {class: 'section-title'}, 'Inspector')), body);
  };
  const unsubscribe = model.store.subscribe((state, previous) => {
    if (state.projection !== previous.projection || state.selection !== previous.selection
      || state.fault !== previous.fault || state.name !== previous.name) {
      render();
    }
  });
  render();
  return {element, dispose: unsubscribe};
}
