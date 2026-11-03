// Copyright (C) 2026 David L F Gaden
import {atPointer} from '../../editor/fill-data.mjs';
import {identityPool, nextIdentity} from './authoring-defaults.mjs';

function context(documentValue, pointer) {
  const match = /^(.*)\/nodes\/(\d+)$/.exec(pointer || '');
  if (!match) throw Error('Select a pipeline object first.');
  const base = match[1], value = atPointer(documentValue, base), index = Number(match[2]);
  if (!value?.nodes?.[index]) throw Error('The selected pipeline object is no longer present.');
  return {base, value, index};
}

function observations(value, ids) {
  if (!value || typeof value !== 'object') return false;
  if (ids.has(value.$observe) || ids.has(value.$sample)) return true;
  return Object.values(value).some(child => observations(child, ids));
}
const refers = (value, ids) => Array.isArray(value) ? value.some(child => refers(child, ids))
  : ids.has(typeof value === 'string' ? value : value?.node);

export function duplicateNode(documentValue, pointer) {
  const {base, value, index} = context(documentValue, pointer);
  const copy = structuredClone(value.nodes[index]);
  copy.id = nextIdentity((typeof copy.id === 'string' ? copy.id : copy.filter || 'node') + 'Copy', identityPool(value));
  const nodes = value.nodes.slice(); nodes.splice(index + 1, 0, copy);
  return {base, value: {...value, nodes}, pointer: `${base}/nodes/${index + 1}`, names: [copy.id]};
}

export function dependentNodes(value, identity) {
  const ids = new Set(typeof identity === 'string' ? [identity] : []);
  for (let before = -1; before !== ids.size;) {
    before = ids.size;
    for (const node of value.nodes || []) if (typeof node?.id === 'string' && !ids.has(node.id)
      && (Object.values(node.inputs || {}).some(source => refers(source, ids)) || observations(node.options, ids))) ids.add(node.id);
  }
  return ids;
}

export function removeNode(documentValue, pointer) {
  const {base, value, index} = context(documentValue, pointer);
  const ids = dependentNodes(value, value.nodes[index].id);
  const result = structuredClone(value);
  const unnamed = [];
  result.nodes = result.nodes.filter((node, position) => {
    const removed = position === index || ids.has(node?.id)
      || Object.values(node?.inputs || {}).some(source => refers(source, ids)) || observations(node?.options, ids);
    if (removed && typeof node?.id !== 'string') unnamed.push(`unnamed object at node ${position}`);
    return !removed;
  });
  // Remove only reference-bearing publication positions, never arbitrary matching text.
  if (Array.isArray(result.scenes)) result.scenes = result.scenes.flatMap(scene => {
    let changed = false;
    for (const key of ['geometry', 'measurements', 'exports']) if (Array.isArray(scene[key])) {
      const retained = scene[key].filter(item => !refers(item, ids) && !observations(item, ids)
        && !Object.values(item?.resources || {}).some(resource => refers(resource, ids)));
      changed ||= retained.length !== scene[key].length; scene[key] = retained;
    }
    if (scene.visible) for (const key of Object.keys(scene.visible)) {
      if (ids.has(key) || observations(scene.visible[key], ids)) { delete scene.visible[key]; changed = true; }
    }
    if (scene.appearances) scene.appearances = scene.appearances.filter(item => !observations(item, ids))
      .map(item => Object.fromEntries(Object.entries(item).filter(([key]) => !ids.has(key))));
    if (scene.images) scene.images = scene.images.filter(item => !observations(item, ids));
    const hasData = scene.geometry?.length || Object.keys(scene.visible || {}).length || scene.measurements?.length || scene.exports?.length;
    return changed && !hasData ? [] : [scene];
  });
  if (refers(result.output, ids)) delete result.output;
  if (Array.isArray(result.outputs)) result.outputs = result.outputs.filter(item => !refers(item, ids) && !observations(item, ids));
  return {base, value: result, pointer: result.nodes.length ? `${base}/nodes/${Math.max(0, Math.min(index - 1, result.nodes.length - 1))}` : base,
    names: [...ids, ...unnamed], publicationsChanged: JSON.stringify(value.scenes) !== JSON.stringify(result.scenes)
      || JSON.stringify(value.output) !== JSON.stringify(result.output) || JSON.stringify(value.outputs) !== JSON.stringify(result.outputs)};
}
