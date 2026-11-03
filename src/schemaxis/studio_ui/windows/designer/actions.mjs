// Copyright (C) 2026 David L F Gaden
// Designer commands shared by the canvas, inspector, header and keyboard.

import {confirmDialog} from '../../shell/dialog.mjs';
import {uniqueId} from './geometry.mjs';
import {exportTemplateDialog, idDialog, newOperationDialog} from './dialogs.mjs';
import {exposeDialog, portDialog} from './port-dialog.mjs';

function connectedCount(node) {
  const ports = [...(node.ports.inputs || []), ...(node.ports.outputs || [])];
  return ports.reduce((total, port) => total + (port.connections || []).length, 0);
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

export function createActions(ctx, model, {getCanvas}) {
  const actions = {};
  const state = () => model.store.get();
  const operations = () => (state().projection ? state().projection.nodes.map((node) => node.id) : []);

  actions.addOperation = async (adaptorId, position) => {
    let at = position;
    if (!at) {
      const canvas = getCanvas();
      const viewport = canvas.viewport();
      const size = canvas.size();
      const offset = operations().length % 5 * 24;
      at = {x: Math.round((size.width / 2 - viewport.x) / viewport.zoom - 124 + offset),
        y: Math.round((size.height / 2 - viewport.y) / viewport.zoom - 60 + offset)};
    }
    return newOperationDialog(ctx, model, adaptorId, at);
  };

  actions.connect = async (from, to) => {
    const projection = state().projection;
    const existing = new Set(projection.connections.map((item) => item.id));
    const id = uniqueId(`${from.operation}-${to.operation}`, existing);
    const before = new Set(projection.loops.map((loop) => loop.id));
    const result = await model.action('connect', {connection: {id, from, to}}, {title: 'Could not connect'});
    if (!result) {
      return;
    }
    const created = result.projection.loops.find((loop) => !before.has(loop.id) && loop.edgeIds.includes(id));
    if (created) {
      model.select({kind: 'loop', id: created.id});
      ctx.notify.info('Closed loop: this is now a feedback system', {
        body: `${created.members.join(', ')} now feed each other. Choose its convergence settings in the inspector.`,
      });
    } else {
      model.select({kind: 'edge', id});
    }
  };

  actions.disconnect = async (edgeId) => {
    const result = await model.action('disconnect', {connectionId: edgeId}, {title: 'Could not remove the connection'});
    if (result) {
      model.select(null);
    }
  };

  actions.removeOperations = async (ids) => {
    const nodes = ids.map((id) => model.node(id)).filter(Boolean);
    if (!nodes.length) {
      return;
    }
    const links = nodes.reduce((total, node) => total + connectedCount(node), 0);
    if (links) {
      const names = nodes.map((node) => node.id).join(', ');
      const confirmed = await confirmDialog(`Remove ${nodes.length === 1 ? names : plural(nodes.length, 'operation')}?`,
        `${names} ${nodes.length === 1 ? 'has' : 'have'} ${plural(links, 'connection')}, which will be removed too. `
        + 'You can undo this.', {confirm: 'Remove', danger: true});
      if (!confirmed) {
        return;
      }
    }
    for (const node of nodes) {
      let result = await model.action('remove_operation', {operation: node.id, cascade: false}, {quiet: true});
      if (result && result.fault && result.fault.code === 'OPERATION_IN_USE' && result.fault.observed
        && (result.fault.observed.parameters || result.fault.observed.outputs)) {
        const dependent = [...(result.fault.observed.parameters || []), ...(result.fault.observed.outputs || [])];
        const confirmed = await confirmDialog(`Remove ${node.id} and what depends on it?`,
          `Parameters or named outputs depend on ${node.id}: ${dependent.join(', ')}. They will be removed too.`,
          {confirm: 'Remove all', danger: true});
        if (!confirmed) {
          return;
        }
        result = await model.action('remove_operation', {operation: node.id, cascade: true},
          {title: `Could not remove ${node.id}`});
      } else if (result && result.fault) {
        return;
      }
      if (!result) {
        return;
      }
    }
    model.select(null);
  };

  actions.deleteSelection = () => {
    const selection = state().selection;
    if (!selection) {
      return;
    }
    if (selection.kind === 'nodes') {
      actions.removeOperations(selection.ids);
    } else if (selection.kind === 'edge') {
      const edge = model.edge(selection.id);
      if (edge && edge.removable) {
        actions.disconnect(edge.id);
      } else {
        ctx.notify.info('Authored reference', {body: 'This dashed reference is part of an operation document. '
          + 'Edit it in the Source tab or the Adaptor Workbench.'});
      }
    }
  };

  actions.rename = async (id, newId) => {
    let next = newId;
    if (next === undefined) {
      next = await idDialog({title: `Rename ${id}`, label: 'New instance ID', value: id, confirm: 'Rename',
        existing: operations().filter((item) => item !== id)});
    }
    if (!next || next === id) {
      return false;
    }
    const result = await model.action('rename_operation', {operation: id, newId: next},
      {title: `Could not rename ${id}`});
    if (result) {
      model.select({kind: 'nodes', ids: [next]});
      return true;
    }
    return false;
  };

  actions.duplicate = async (id) => {
    const next = await idDialog({title: `Duplicate ${id}`, label: 'Instance ID of the copy',
      value: uniqueId(`${id}-copy`, operations()), confirm: 'Duplicate', existing: operations()});
    if (!next) {
      return;
    }
    const result = await model.action('duplicate_operation', {operation: id, newId: next},
      {title: `Could not duplicate ${id}`});
    if (result) {
      model.select({kind: 'nodes', ids: [next]});
    }
  };

  actions.openWorkbench = (id) => {
    ctx.bus.emit('open-operation', {document: model.documentId, operation: id});
  };

  async function savePorts(operation, ports, title) {
    return model.action('set_ports', {operation, ports}, {title});
  }

  function currentPorts(operation) {
    return structuredClone(state().projection.ports[operation] || {});
  }

  actions.addPort = async (operation, side) => {
    const chosen = await portDialog(ctx, model, operation, side);
    if (!chosen) {
      return;
    }
    const ports = currentPorts(operation);
    ports[side] = {...(ports[side] || {}), [chosen.name]: chosen.spec};
    await savePorts(operation, ports, 'Could not add the port');
  };

  actions.editPort = async (operation, side, name) => {
    const ports = currentPorts(operation);
    const existing = ports[side] && ports[side][name];
    const node = model.node(operation);
    const port = node && node.ports[side].find((item) => item.name === name);
    const chosen = await portDialog(ctx, model, operation, side, {existingName: name, existing});
    if (!chosen) {
      return;
    }
    if (port?.connections.length) {
      const structural = ['target', 'kind', 'artifact', 'valuePath'];
      if (chosen.name !== name || structural.some((key) => chosen.spec[key] !== existing[key])) {
        ctx.notify.warn('Port is connected', {body: 'Disconnect this port before changing its name, target or kind. '
          + 'Its descriptive data can be edited while connected.'});
        return;
      }
    }
    const next = {};
    for (const [key, value] of Object.entries(ports[side] || {})) {
      if (key === name) {
        next[chosen.name] = chosen.spec;
      } else {
        next[key] = value;
      }
    }
    ports[side] = next;
    await savePorts(operation, ports, 'Could not save the port');
  };

  actions.removePort = async (operation, side, name) => {
    const ports = currentPorts(operation);
    if (!ports[side]) {
      return;
    }
    delete ports[side][name];
    if (!Object.keys(ports[side]).length) {
      delete ports[side];
    }
    await savePorts(operation, ports, 'Could not remove the port');
  };

  actions.expose = async (operation, suggestion) => {
    const params = await exposeDialog(ctx, model, operation, suggestion);
    if (!params) {
      return;
    }
    const result = await model.action('expose_parameter', params, {title: 'Could not expose the parameter'});
    if (result) {
      ctx.notify.ok(`Parameter ${params.parameterId} exposed`, {body: 'It is listed in the Parameters tab.'});
    }
  };

  actions.exposeUnfilled = async () => {
    const result = await model.action('expose_unfilled', {}, {title: 'Could not expose unfilled values'});
    if (result) ctx.notify.ok('Unfilled values exposed as parameters', {
      body: 'Review their types and constraints in Parameters. Case values are required before planning.'});
  };

  actions.configureLoop = async (loopId, config) => {
    const result = await model.action('configure_loop', {loopId, config}, {title: 'Could not save loop settings'});
    if (result) {
      ctx.notify.ok('Loop settings saved', {body: 'Feedback execution is not available yet; the settings are kept '
        + 'with the design.'});
    }
    return Boolean(result);
  };

  actions.compile = async () => {
    const result = await model.action('compile', {}, {title: 'Could not compile the design'});
    if (!result) {
      return;
    }
    await ctx.refresh();
    ctx.notify.ok('Workflow compiled', {body: 'The compiled workflow opened as a separate document.'});
    ctx.openDocument(result.document);
  };

  actions.exportTemplate = () => exportTemplateDialog(ctx, model);

  actions.undo = () => model.history('undo');
  actions.redo = () => model.history('redo');

  return actions;
}
