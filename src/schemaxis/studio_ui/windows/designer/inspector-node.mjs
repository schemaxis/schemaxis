// Node inspector: identity, actions, port editor and "Expose as parameter".

import {h, icon, mount} from '../../lib/dom.mjs';
import {avatar, identity} from '../../shell/providers.mjs';
import {dataKind, kindColour} from './geometry.mjs';
import {ID_PATTERN} from './dialogs.mjs';
import {section} from './inspector.mjs';

function literal(value) {
  return ['number', 'string', 'boolean'].includes(typeof value)
    || (Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === 'number'));
}

function short(value) {
  const text = JSON.stringify(value);
  return text.length > 28 ? `${text.slice(0, 26)}…` : text;
}

function dataSummary(data) {
  if (!data) {
    return '';
  }
  const parts = [];
  if (data.formats) {
    parts.push(data.formats.join('/'));
  }
  if (data.units) {
    parts.push(data.units);
  }
  if (data.layout) {
    parts.push(data.layout);
  }
  if (data.streaming) {
    parts.push('streaming');
  }
  if (data.contiguous) {
    parts.push('contiguous');
  }
  return parts.join(' · ');
}

function portRow(actions, node, side, port) {
  const kind = dataKind(port);
  const connected = port.connections.length > 0;
  const where = side === 'inputs' ? port.target : `artifact ${port.artifact}${port.valuePath || ''}`;
  return h('li', {class: 'dz-port-item'},
    h('span', {class: ['dz-dot-static', port.kind === 'value' && 'value', connected && 'connected'],
      style: {'--port': kindColour(kind)}}),
    h('button', {class: 'dz-port-item-main', title: 'Edit port',
      onClick: () => actions.editPort(node.id, side, port.name)},
    h('span', {class: 'dz-port-item-name'}, port.name, port.generated ? h('span', {class: 'muted'}, ' · generated')
      : null),
    h('span', {class: 'dz-port-item-where mono'}, where),
    dataSummary(port.data) ? h('span', {class: 'dz-port-item-meta'}, dataSummary(port.data)) : null),
    h('span', {class: 'dz-kind-badge', style: {'--port': kindColour(kind)}}, kind || port.kind),
    h('button', {class: 'button ghost small icon-only', 'aria-label': `Remove port ${port.name}`,
      title: connected ? 'Disconnect this port before removing it' : 'Remove port', disabled: connected,
      onClick: () => actions.removePort(node.id, side, port.name)}, icon('close')));
}

function portsSection(actions, node) {
  const group = (side, label) => {
    const ports = node.ports[side] || [];
    return h('div', {class: 'dz-port-group'},
      h('div', {class: 'dz-port-group-header'}, h('span', {}, label, h('span', {class: 'muted'}, ` ${ports.length}`)),
        h('button', {class: 'button ghost small', onClick: () => actions.addPort(node.id, side)}, icon('plus'),
          side === 'inputs' ? 'Add input' : 'Add output')),
      ports.length ? h('ul', {class: 'dz-port-list'}, ports.map((port) => portRow(actions, node, side, port)))
        : h('div', {class: 'dz-port-empty'}, side === 'inputs' ? 'No input ports. Inputs drive one runtime value '
          + 'or file of this operation.' : 'No output ports. Outputs publish an artifact or a value inside one.'));
  };
  return section('Ports', group('inputs', 'Inputs'), group('outputs', 'Outputs'));
}

function exposeSection(ctx, model, actions, node, token, isCurrent) {
  const list = h('div', {class: 'dz-runtime'}, h('div', {class: 'muted'}, 'Loading runtime inputs…'));
  model.suggestions(node.id).then((suggestions) => {
    if (!isCurrent(token)) {
      return;
    }
    if (!suggestions) {
      mount(list, h('div', {class: 'muted'}, 'Runtime inputs are unavailable for this operation.'));
      return;
    }
    const driven = new Set(node.ports.inputs.filter((port) => port.connections.length).map((port) => port.target));
    const inputs = suggestions.inputs;
    mount(list, inputs.length ? h('ul', {class: 'dz-runtime-list'}, inputs.map((item) => {
      const exposable = literal(item.current) && !driven.has(item.target);
      const reference = item.current && typeof item.current === 'object' && !Array.isArray(item.current);
      return h('li', {class: 'dz-runtime-item'},
        h('div', {class: 'dz-runtime-text'},
          h('span', {class: 'mono'}, item.target),
          h('span', {class: 'muted'}, reference ? 'reference' : short(item.current))),
        driven.has(item.target) ? h('span', {class: 'badge info'}, 'connected')
          : reference ? h('span', {class: 'badge'}, 'linked')
            : h('button', {class: 'button ghost small', disabled: !exposable,
              title: 'Expose as a template parameter', onClick: () => actions.expose(node.id, item)},
            'Expose'));
    })) : h('div', {class: 'muted'}, 'This operation has no numeric or file inputs.'));
  });
  return section('Expose as parameter', h('p', {class: 'hint'}, 'Literal runtime inputs can become template '
    + 'parameters that users set in a case file.'), list);
}

export function nodePanel(ctx, model, actions, node, token) {
  if (!node) {
    return h('div', {class: 'dz-inspector-body'});
  }
  const info = identity(node.provider);
  const loops = model.loopsOf(model.store.get().projection, {node: node.id});
  const others = model.store.get().projection.nodes.map((item) => item.id).filter((id) => id !== node.id);
  const rename = h('input', {class: 'input', value: node.id, 'aria-label': 'Instance ID', spellcheck: 'false'});
  const renameError = h('div', {class: 'error-text', role: 'alert'});
  const submit = async () => {
    const next = rename.value.trim();
    if (next === node.id) {
      return;
    }
    if (!ID_PATTERN.test(next) || others.includes(next)) {
      renameError.textContent = others.includes(next) ? 'Another operation uses this ID.'
        : 'Start with a letter; use letters, digits, - or _.';
      return;
    }
    renameError.textContent = '';
    if (!(await actions.rename(node.id, next))) {
      rename.value = node.id;
    }
  };
  rename.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      submit();
    } else if (event.key === 'Escape') {
      rename.value = node.id;
      renameError.textContent = '';
    }
  });
  const isCurrent = (value) => value === token && model.store.get().selection?.ids?.[0] === node.id;
  return h('div', {class: 'dz-inspector-body'},
    h('div', {class: 'dz-inspector-title'},
      avatar(node.provider, {large: true}),
      h('div', {}, h('h3', {}, node.id), h('div', {class: 'subtitle'}, `${info.name} operation`)),
      loops.length ? h('button', {class: 'badge loop dz-badge-button',
        onClick: () => model.select({kind: 'loop', id: loops[0].id})}, icon('loop'), 'Loop') : null),
    h('div', {class: 'dz-button-row'},
      h('button', {class: 'button primary', onClick: () => actions.openWorkbench(node.id)}, icon('adaptor'),
        'Open in Workbench'),
      h('button', {class: 'button', onClick: () => actions.duplicate(node.id)}, 'Duplicate'),
      h('button', {class: 'button danger', onClick: () => actions.removeOperations([node.id])}, 'Remove')),
    section('Identity',
      h('div', {class: 'field'}, h('label', {}, 'Instance ID'),
        h('div', {class: 'dz-inline'}, rename, h('button', {class: 'button', onClick: submit}, 'Rename')),
        renameError),
      h('dl', {class: 'kv'},
        h('dt', {}, 'Adaptor'), h('dd', {}, info.name),
        h('dt', {}, 'Document'), h('dd', {class: 'mono'}, node.documentVersion),
        h('dt', {}, 'Nodes'), h('dd', {}, String(node.nodeCount)),
        h('dt', {}, 'Order'), h('dd', {}, `#${node.order + 1} in declaration order`))),
    portsSection(actions, node),
    exposeSection(ctx, model, actions, node, token, isCurrent));
}
