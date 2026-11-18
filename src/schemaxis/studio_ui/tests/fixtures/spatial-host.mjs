// Copyright (C) 2026 David L. F. Gaden.
// Appendix A transport stub. Expressions have explicit fixtures; no parser or evaluator.
import {entries, preview, ownerAt} from '../../windows/variables/model.mjs';
import {literalSpatial} from '../../windows/spatial/model.mjs';

export function installSpatialHost(api, {expressions = {}, extents = true, live = false} = {}) {
  const calls = [], jobs = new Map();
  const post = api.post.bind(api), wait = api.waitForJob.bind(api);
  const state = request => request.state || {timeIndex: 0, indices: {}};
  const pending = {entries: [], nodes: [], sweeps: [], awaits: []};
  async function common(request) {
    const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(request.input)));
    return {inputDigest: Array.from(new Uint8Array(hash), n => n.toString(16).padStart(2, '0')).join(''),
      ...(request.draft === undefined ? {} : {draft: structuredClone(request.draft)}), capabilities: {extents}};
  }
  function describe(value, request) {
    const fixture = expressions[typeof value?.$expr === 'string' ? value.$expr : JSON.stringify(value)];
    if (fixture) return fixture;
    let resolved = value;
    try { resolved = preview(request.input, value, ownerAt(request.input, entries(request.input).find(e => e.operation === request.operation)?.base || '')); } catch { /* Only explicit computed fixtures resolve. */ }
    const literal = literalSpatial(resolved);
    return literal?.state === 'resolved' ? {...literal, phase: 'constant', kind: 'literal'}
      : {type: literal ? 'unknown' : 'json', phase: 'constant', value: resolved};
  }
  function record(value, request, meta, loaded = false, identity = {}) {
    const spec = describe(value, request), phase = spec.phase || 'constant';
    const base = {...identity, type: spec.type, phase, dependsOn: spec.dependsOn || pending,
      ...(typeof value?.$expr === 'string' ? {expression: value.$expr} : {})};
    if (spec.fault) return {...base, state: 'fault', fault: spec.fault};
    if (request.action === 'spatial_list' && phase === 'visit') return {...base, state: 'unresolved', reason: 'needs-state'};
    if (phase === 'observed' && (!loaded || spec.unresolved)) return {...base, state: 'unresolved', reason: spec.reason || (request.observations ? 'stale-data' : 'needs-data')};
    return {...base, state: 'resolved', value: structuredClone(spec.value),
      ...(spec.type === 'box' ? {valid: spec.valid ?? true} : {}),
      source: {kind: phase === 'observed' ? 'live' : spec.kind || 'constant', inputDigest: meta.inputDigest, state: state(request)}};
  }
  function records(request, meta, loaded) {
    if (request.expression !== undefined) {
      const selected = request.operation ? request.input.operations.find(op => op.id === request.operation).document : request.input;
      const named = Object.keys(selected.definitions || {}).find(key => request.expression === `definitions.${key}`);
      return [record(named ? selected.definitions[named] : {$expr: request.expression}, request, meta, loaded)];
    }
    return entries(request.input).filter(entry => entry.group !== 'sweeps'
      && (!request.operation || entry.operation === request.operation))
      .filter(entry => !request.entries || request.entries.some(id => id.scope === (entry.workflow ? 'workflow' : 'document')
        && id.section === entry.group && id.key === entry.name))
      .map(entry => record(entry.value, request, meta, loaded, {entry: {scope: entry.workflow ? 'workflow' : 'document', section: entry.group, key: entry.name},
        ...(entry.operation ? {operation: entry.operation} : {})})).filter(r => ['scalar','vector','box'].includes(r.type));
  }
  api.post = async (path, request) => {
    if (path !== '/api/spatial' && !(path === '/api/cancel' && jobs.has(request.job))) return post(path, request);
    calls.push({path, request: structuredClone(request)});
    if (path === '/api/cancel') { jobs.get(request.job).status = 'cancelled'; return {}; }
    if (request.action === 'live_data_status') return {enabled:live};
    const meta = await common(request);
    if (request.action === 'spatial_check') {
      const spec = describe({$expr: request.expression}, request);
      return {...meta, ok: !spec.fault, type: spec.type, phase: spec.phase || 'constant', dependsOn: spec.dependsOn || pending,
        ...(spec.fault ? {fault: spec.fault} : {})};
    }
    if (request.action === 'spatial_list') return {...meta, entries: records(request, meta, false), sweeps: [], states: 1,
      functions: [{name: 'union', kind: 'builtin', parameters: [], result: 'box'}]};
    if (request.action === 'spatial_eval') {
      const obs = request.observations;
      const matching = obs && obs.inputDigest === meta.inputDigest && obs.operation === request.operation
        && JSON.stringify(obs.state) === JSON.stringify(state(request));
      return {...meta, records: records(request, meta, matching)};
    }
    if (['spatial_load','live_data_refresh'].includes(request.action)) {
      if (!extents) throw Object.assign(Error('Extents unsupported'), {code: 'EXTENTS_UNSUPPORTED'});
      const job = 'spatial-fixture-' + jobs.size;
      const observations = {inputDigest: meta.inputDigest, ...(request.operation ? {operation: request.operation} : {}),
        state: state(request), extents: [{node: 'body', port: 0, status: 'ok', bounds: [0, 4, 0, 2, 0, 0]}]};
      jobs.set(job, {status: 'succeeded', result: {...meta, observations, records: records(request, meta, true)}});
      return {job, status: 'running'};
    }
    throw Error('Unexpected spatial action: ' + request.action);
  };
  api.waitForJob = async (job, options) => jobs.has(job) ? jobs.get(job) : wait(job, options);
  return {calls, jobs};
}
