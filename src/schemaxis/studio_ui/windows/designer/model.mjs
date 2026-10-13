// Designer data flow: one store per window holding the design projection, revision,
// selection and viewport. Every mutation posts with the current revision.

import {Store} from '../../lib/store.mjs';
import {autoLayout} from './geometry.mjs';

const STALE_NOTICE_INTERVAL = 5000;
// Actions whose projection is unchanged; applying it would only re-render needlessly.
const READ_ONLY = new Set(['project', 'suggest_ports', 'export_template', 'compile']);

/** Selection is null, {kind: 'nodes', ids}, {kind: 'edge', id} or {kind: 'loop', id}. */
export function createModel(ctx, documentId) {
  const store = new Store({
    name: '',
    revision: null,
    projection: null,
    fault: null,
    selection: null,
    viewport: null,
    positions: {},
    local: {},
    undoCount: 0,
    redoCount: 0,
    busy: false,
    connecting: null,
  });
  let inFlight = 0;
  let externalPending = false;
  let lastStaleNotice = 0;
  let documentCache = null;
  let pending = Promise.resolve();

  // Two quick gestures must use successive revisions, rather than race each other.
  function serial(task) {
    const result = pending.then(task);
    pending = result.catch(() => {});
    return result;
  }

  const model = {store, documentId};

  /** Effective positions: local drags win over the server layout; missing ones are laid out. */
  model.layout = (projection, local) => {
    if (!projection) {
      return {};
    }
    const saved = {...(projection.layout && projection.layout.nodes), ...local};
    return autoLayout(projection.nodes, projection.edges, saved);
  };

  function pruneSelection(selection, projection) {
    if (!selection || !projection) {
      return selection;
    }
    if (selection.kind === 'nodes') {
      const ids = selection.ids.filter((id) => projection.nodes.some((node) => node.id === id));
      return ids.length ? {kind: 'nodes', ids} : null;
    }
    if (selection.kind === 'edge') {
      return projection.edges.some((edge) => edge.id === selection.id) ? selection : null;
    }
    if (selection.kind === 'loop') {
      return projection.loops.some((loop) => loop.id === selection.id) ? selection : null;
    }
    return null;
  }

  function settleLocal(local, projection) {
    // Drop local overrides the server now agrees with; keep any that are still pending.
    const saved = (projection.layout && projection.layout.nodes) || {};
    const next = {};
    for (const [id, point] of Object.entries(local)) {
      const server = saved[id];
      const exists = projection.nodes.some((node) => node.id === id);
      if (exists && (!server || server.x !== point.x || server.y !== point.y)) {
        next[id] = point;
      }
    }
    return next;
  }

  function apply(result) {
    const state = store.get();
    const projection = result.projection;
    const local = settleLocal(state.local, projection);
    store.set({
      revision: result.revision,
      projection,
      fault: null,
      undoCount: result.undoCount ?? state.undoCount,
      redoCount: result.redoCount ?? state.redoCount,
      selection: pruneSelection(state.selection, projection),
      local,
      positions: model.layout(projection, local),
    });
  }

  async function post(action, params) {
    const state = store.get();
    return ctx.api.post('/api/design', {document: documentId, revision: state.revision, action, params});
  }

  /** Fetch the record (name, revision) and a fresh projection. */
  async function load() {
    const record = await ctx.call(() => ctx.api.get('/api/document', {id: documentId}),
      {title: 'Could not load the design'});
    if (!record) {
      return false;
    }
    documentCache = {revision: record.revision, record};
    store.set({name: record.name, revision: record.revision, undoCount: record.undoCount,
      redoCount: record.redoCount});
    try {
      const upgrade = record.document?.version === 'schemaxis.workflow-design/1';
      apply(await post(upgrade ? 'upgrade' : 'project', {}));
      if (upgrade) await ctx.refresh();
      return true;
    } catch (error) {
      store.set({fault: error.fault || {message: error.message}, projection: null});
      ctx.notify.error(error, {title: 'Could not project the design', source: {document: documentId}});
      return false;
    }
  }

  model.load = () => serial(load);

  function staleNotice() {
    const now = Date.now();
    if (now - lastStaleNotice > STALE_NOTICE_INTERVAL) {
      lastStaleNotice = now;
      ctx.notify.info('Design refreshed', {
        body: 'The design changed in another window, so the latest version was loaded. Repeat your last edit.',
      });
    }
  }

  /**
   * Run one design action. Returns the server result, or undefined after reporting a fault.
   * Options: title (toast title), quiet (also return {fault} for inline dialog recovery).
   */
  model.action = (action, params = {}, {title, quiet = false} = {}) => serial(async () => {
    inFlight += 1;
    store.set({busy: true});
    try {
      const result = await post(action, params);
      if (result.projection && !READ_ONLY.has(action)) {
        apply(result);
        await ctx.refresh();
      }
      return result;
    } catch (error) {
      if (error.code === 'STALE_REVISION') {
        await load();
        staleNotice();
        return undefined;
      }
      ctx.notify.error(error, {title: title || 'Design action failed', source: {document: documentId}});
      if (quiet) {
        return {fault: error.fault || {code: error.code, message: error.message}};
      }
      return undefined;
    } finally {
      inFlight -= 1;
      store.set({busy: inFlight > 0});
      if (!inFlight && externalPending) {
        externalPending = false;
        model.load();
      }
    }
  });

  /** Undo or redo through the shared authoring endpoint, then refresh the projection. */
  model.history = (direction) => serial(async () => {
    const state = store.get();
    const label = direction === 'undo' ? 'Undo' : 'Redo';
    inFlight += 1;
    store.set({busy: true});
    try {
      await ctx.api.post('/api/authoring', {action: direction, document: documentId, revision: state.revision});
    } catch (error) {
      if (error.code === 'STALE_REVISION') {
        await load();
        staleNotice();
      } else {
        ctx.notify.error(error, {title: `${label} failed`, source: {document: documentId}});
      }
      return false;
    } finally {
      inFlight -= 1;
      store.set({busy: false});
    }
    store.set({local: {}});
    await load();
    await ctx.refresh();
    return true;
  });

  /** Apply complete source using its editing baseline, retaining conflicting local drafts. */
  model.saveSource = (source, revision, format = "json") => serial(async () => {
    store.set({busy: true});
    try {
      const result = await ctx.api.post('/api/authoring', {action: 'source', document: documentId, revision, source, format});
      documentCache = null;
      store.set({local: {}});
      await load();
      await ctx.refresh();
      return result;
    } catch (error) {
      ctx.notify.error(error, {title: 'Could not apply design source', source: {document: documentId}});
      if (error.code === 'STALE_REVISION') await load();
      return undefined;
    } finally {
      store.set({busy: false});
    }
  });

  /** Port suggestions for an operation, cached per revision. Resolves with suggestions or null. */
  const suggestionCache = new Map();
  model.suggestions = async (operation) => {
    const key = `${store.get().revision}:${operation}`;
    if (!suggestionCache.has(key)) {
      suggestionCache.set(key, model.action('suggest_ports', {operation}, {quiet: true}).then((result) => {
        if (!result || result.fault) {
          suggestionCache.delete(key);
          return null;
        }
        return result.suggestions;
      }));
    }
    return suggestionCache.get(key);
  };

  /** The full stored document (source and body), cached per revision. */
  model.record = async () => {
    const revision = store.get().revision;
    if (documentCache && documentCache.revision === revision) {
      return documentCache.record;
    }
    const record = await ctx.call(() => ctx.api.get('/api/document', {id: documentId}),
      {title: 'Could not read the design source'});
    if (record) {
      documentCache = {revision: record.revision, record};
    }
    return record;
  };

  /** React to another window changing this document. */
  model.external = (record) => {
    if (record.id !== documentId || record.revision === store.get().revision) {
      return;
    }
    if (inFlight) {
      externalPending = true;
      return;
    }
    model.load();
  };

  /** Locally move nodes (optimistic); persist later with commitMoves. */
  model.moveLocal = (moves) => {
    const state = store.get();
    const local = {...state.local, ...moves};
    store.set({local, positions: {...state.positions, ...moves}});
  };

  model.commitMoves = async (ids) => {
    const state = store.get();
    const positions = {};
    for (const id of ids) {
      if (state.positions[id]) {
        positions[id] = {x: Math.round(state.positions[id].x), y: Math.round(state.positions[id].y)};
      }
    }
    if (!Object.keys(positions).length) {
      return;
    }
    await model.action('move', {positions}, {title: 'Could not save the layout'});
  };

  model.select = (selection) => {
    store.set({selection});
  };

  model.node = (id) => {
    const projection = store.get().projection;
    return projection ? projection.nodes.find((node) => node.id === id) : null;
  };

  model.edge = (id) => {
    const projection = store.get().projection;
    return projection ? projection.edges.find((edge) => edge.id === id) : null;
  };

  model.loop = (id) => {
    const projection = store.get().projection;
    return projection ? projection.loops.find((loop) => loop.id === id) : null;
  };

  /** Loops containing an operation or an edge. */
  model.loopsOf = (projection, {node, edge}) => (projection ? projection.loops : []).filter((loop) => (
    node ? loop.members.includes(node) : loop.edgeIds.includes(edge)));

  return model;
}
