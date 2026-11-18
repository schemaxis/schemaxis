// Copyright (C) 2026 David L. F. Gaden.
// Appendix A requests are stateless and always carry the whole authored draft.
import {writeSpatialValue, writeLiteral, literalSpatial} from './model.mjs';
import {ownerAt, preview} from '../variables/model.mjs';
export function spatialRequest(root, base = '', draft, extra = {}) {
  const scope = ownerAt(root, base);
  const input = root?.version?.startsWith('schemaxis.workflow-design/') ? root.workflow : root;
  return {input: structuredClone(input), ...(scope.operation ? {operation: scope.operation} : {}),
    ...(draft === undefined ? {} : {draft: structuredClone(draft)}), ...extra};
}
export async function spatialAction(api, action, request) {
  const response = await api.post('/api/spatial', {action, ...request});
  return action === 'spatial_load' ? (await api.waitForJob(response.job)).result : response;
}

/** Preview existing marker forms through an isolated named entry; never evaluate in Studio. */
export async function previewSpatial(api, root, value, base = '', {destination} = {}) {
  // Literal references need no expression interpretation; text and booleans are
  // outside spatial_eval's record types and must remain usable by Variables.
  try {
    const literal = preview(root, value, ownerAt(root, base));
    if (destination === undefined || !literalSpatial(literal) || !value || typeof value !== 'object') return literal;
  }
  catch (fault) { if (!/Available when/.test(fault.message)) throw fault; }
  if (typeof value?.$expr === 'string') {
    const result = await spatialAction(api, 'spatial_eval', spatialRequest(root, base, undefined, {expression: value.$expr, ...(destination === undefined ? {} : {destination})}));
    return resolvedValue(result.records?.[0]);
  }
  const input = structuredClone(root);
  const scope = ownerAt(input, base);
  let owner = input;
  for (const segment of scope.base.split('/').slice(1)) owner = owner[segment.replaceAll('~1', '/').replaceAll('~0', '~')];
  owner.definitions ||= {};
  let key = '_studioPreview';
  while (Object.hasOwn(owner.definitions, key)) key += '_';
  owner.definitions[key] = value;
  const target = destination === undefined ? {entries: [{scope: scope.workflow ? 'workflow' : 'document', section: 'definitions', key}]}
    : {expression: `definitions.${key}`, destination};
  const result = await spatialAction(api, 'spatial_eval', spatialRequest(input, base, undefined, target));
  return resolvedValue(result.records?.[0]);
}

export function resolvedValue(record) {
  if (record?.state !== 'resolved') {
    const fault = Error(record?.fault?.message || record?.reason || 'Unresolved');
    fault.code = record?.fault?.code || record?.reason || 'unresolved';
    throw fault;
  }
  return record.value;
}

/** Rename in the shared core so checked expression references follow the entry. */
export async function saveSpatial(api, root, identity, value, previous, literal = false) {
  const renaming = previous && previous.name !== identity.name;
  const write = literal ? writeLiteral : writeSpatialValue;
  let next = write(root, renaming ? {...identity, name: previous.name} : identity, value, previous);
  if (!renaming) return next;
  const response = await spatialAction(api, 'spatial_rename', spatialRequest(next, identity.base, undefined,
    {section: previous.group, name: previous.name, newName: identity.name}));
  if (!next.version.startsWith('schemaxis.workflow-design/')) return response.input;
  next.workflow = response.input;
  const escape = text => text.replaceAll('~','~0').replaceAll('/','~1');
  const old = `/${previous.group}/${escape(previous.name)}`, dest = `/${identity.group}/${escape(identity.name)}`;
  if (previous.workflow) for (const parameter of Object.values(next.parameters || {})) {
    const target = parameter.target;
    if (target?.scope === 'workflow' && (target.pointer === old || target.pointer.startsWith(old+'/')))
      target.pointer = dest + target.pointer.slice(old.length);
  }
  return next;
}
