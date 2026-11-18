// Copyright (C) 2026 David L. F. Gaden.
import {liveDataEvents, liveDataChanged} from './live-data.mjs';
import {spatialAction, spatialRequest} from './host.mjs';
import {recordRows, matchingSpatialSnapshot} from './model.mjs';

/** Appendix A: omitted visit coordinates denote zero. Missing provenance does not. */
export function sameSpatialState(left, right) {
  if (!left || !right || (left.timeIndex ?? 0) !== (right.timeIndex ?? 0)) return false;
  const keys = new Set([...Object.keys(left.indices || {}), ...Object.keys(right.indices || {})]);
  return [...keys].every(key => (left.indices?.[key] ?? 0) === (right.indices?.[key] ?? 0));
}

/** Display host records only for their captured input, scope and visit. */
export function spatialSession(api, {root, base = '', identity = 'spatial-draft', revision = 0,
  spatial, includeDataExtents = false, autoRefresh = null, changed = () => {}, observed = () => {}}) {
  let current = structuredClone(root), scope = base, serial = 0, observations;
  let job, busy = false, cancelRequested = false, disposed = false;
  let rows = null, functions = [], capabilities = {extents: false};
  let dataExtents, liveData = {enabled: false};
  const automatic = () => typeof autoRefresh === 'function' ? autoRefresh() : autoRefresh === true;
  let retained = matchingSpatialSnapshot(root, spatial) ? spatial : null;
  const state = {timeIndex: 0, indices: {}};
  if (retained?.response.observations && sameSpatialState(retained.response.observations.state, state)) {
    observations = retained.response.observations;
  }
  const draft = () => ({identity, revision});
  const notify = () => { if (!disposed) changed(); };
  const request = extra => spatialRequest(current, scope, draft(), {state: structuredClone(state), ...extra});
  const recordKey = record => JSON.stringify([record.operation, record.entry]);
  const evaluate = async (expression, allowRefresh = true) => {
    const token = serial;
    const response = await spatialAction(api, 'spatial_eval', request({expression, ...(observations ? {observations} : {})}));
    if (disposed || token !== serial) return undefined;
    const record = response.records?.[0];
    if (allowRefresh && automatic() && capabilities.extents && liveData.enabled && !busy && record?.state === 'unresolved') {
      return result.refreshLive(expression);
    }
    return record;
  };
  const readData = async () => {
    if (!includeDataExtents || !capabilities.extents) return;
    const record = await evaluate('dataExtents', false);
    if (record) { dataExtents = record; notify(); }
  };
  const publish = (response, token) => {
    if (disposed || token !== serial) return false;
    // Retained run/live records are already host-evaluated; they are never
    // substituted into expressions or applied to another document or visit.
    const saved = new Map((retained?.response.records || []).filter(record => record.state === 'resolved'
      && sameSpatialState(record.source?.state, state)).map(record => [recordKey(record), record]));
    const records = (response.records || response.entries || []).map(record =>
      record.state === 'unresolved' && record.reason === 'needs-data' ? saved.get(recordKey(record)) || record : record);
    rows = recordRows(current, records, response.draft || draft(), response.inputDigest).map(row =>
      retained?.response.records.includes(row.record) ? {...row, draft: retained.draft} : row);
    if (response.capabilities) capabilities = response.capabilities;
    notify(); return true;
  };
  const result = {
    get rows() { return rows; }, get functions() { return functions; },
    get capabilities() { return capabilities; }, get busy() { return busy; },
    get liveData() { return liveData; },
    get dataExtents() { return dataExtents; },
    get snapshot() { return retained; },
    get draft() { return draft(); },
    evaluate,
    edit(next, nextBase = scope) {
      const edited = JSON.stringify(next) !== JSON.stringify(current);
      if (edited) { revision++; retained = null; }
      current = structuredClone(next); scope = nextBase; serial++; rows = null;
      observations = undefined; dataExtents = undefined; capabilities = {extents: false}; notify();
    },
    async refresh() {
      const token = ++serial;
      if (autoRefresh !== null) liveData = await api.post('/api/spatial', {action: 'live_data_status'});
      if (disposed || token !== serial) return;
      const listed = await spatialAction(api, 'spatial_list', spatialRequest(current, scope, draft()));
      if (disposed || token !== serial) return;
      functions = listed.functions || []; capabilities = listed.capabilities || {extents: false};
      publish(listed, token);
      const evaluated = await spatialAction(api, 'spatial_eval', request({...(observations ? {observations} : {})}));
      if (publish(evaluated, token)) {
        await readData();
        if (!disposed && token === serial && !busy && automatic() && capabilities.extents && liveData.enabled
            && (rows.some(row => row.record?.state === 'unresolved') || dataExtents?.state === 'unresolved')) {
          await result.refreshLive();
        }
      }
    },
    refreshLive(expression) { return result.load(expression, {action: 'live_data_refresh', broadcast: false}); },
    async load(expression, {action = 'spatial_load', broadcast = true} = {}) {
      if (busy || disposed) return;
      busy = true; cancelRequested = false;
      const token = ++serial, captured = structuredClone(current), sent = request(expression === undefined ? {} : {expression}); notify();
      try {
        const started = await api.post('/api/spatial', {action, ...sent});
        job = started.job;
        if (!job) throw Error('The host did not return a live-data job.');
        if (cancelRequested) await api.post('/api/cancel', {job});
        const completed = await api.waitForJob(job);
        if (completed.status !== 'succeeded') {
          throw Error(completed.fault?.message || 'Live data was cancelled.');
        }
        let response = completed.result;
        if (!response) throw Error('The live-data job returned no spatial records.');
        if (disposed || token !== serial || cancelRequested) return;
        // Replace the local view with the shared session measurements.
        // Refresh reuses resident sources; it does not reread files.
        observations = response.observations;
        if (response.liveData) liveData = response.liveData;
        const loaded = expression === undefined ? undefined : response.records?.[0];
        if (expression !== undefined) {
          const evaluated = await spatialAction(api, 'spatial_eval', request({observations}));
          if (disposed || token !== serial || cancelRequested) return;
          response = {...response, records: evaluated.records};
        }
        retained = {root: captured, response, draft: sent.draft};
        publish(response, token);
        await readData();
        if (disposed || token !== serial || cancelRequested) return;
        observed(structuredClone(retained));
        if (broadcast) liveDataChanged();
        return loaded;
      } finally { busy = false; job = undefined; notify(); }
    },
    async check(expression, destination) {
      return spatialAction(api, 'spatial_check', spatialRequest(current, scope, draft(),
        {expression, ...(destination ? {destination} : {})}));
    },
    async cancel() {
      if (!busy || cancelRequested) return;
      cancelRequested = true;
      if (job) await api.post('/api/cancel', {job});
    },
    dispose() { disposed = true; serial++; liveDataEvents.removeEventListener('change', reload); },
  };
  const reload = () => { if (!disposed && !busy) void result.refresh().catch(() => {}); };
  liveDataEvents.addEventListener('change', reload);
  return result;
}
