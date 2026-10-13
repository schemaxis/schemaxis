// Adapt verified publications to existing viewers. Native file formats remain unmodified.
import {h, mount} from '../../lib/dom.mjs';
import {ApiError} from '../../lib/api.mjs';
import {createImageViewer} from '../../viewers/image.mjs';
import {createTextViewer} from '../../viewers/text.mjs';
import {createTableViewer} from '../../viewers/table.mjs';
import {createViewer3d} from '../../viewers/viewer3d.mjs';

export function viewerKind(output) {
  const suffix = output.name.split('.').pop().toLowerCase();
  if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'].includes(suffix)) {
    return 'image';
  }
  if (['csv', 'tsv'].includes(suffix)) {
    return 'table';
  }
  if (suffix === 'stl') {
    return '3d';
  }
  if (suffix === 'json' && output.kind === 'geometry') {
    return '3d-json';
  }
  if (['json', 'txt', 'log', 'md', 'yaml', 'yml', 'xml', 'vtk', 'vtu', 'vtp', 'obj', 'msh'].includes(suffix)) {
    return 'text';
  }
  return 'download';
}

/** Convert bounded binary or ASCII STL into the viewer's explicit triangle payload. */
export function stlGeometry(buffer, name, revision) {
  const view = new DataView(buffer);
  const count = buffer.byteLength >= 84 ? view.getUint32(80, true) : 0;
  const vertices = [];
  const triangles = [];
  const add = (points) => {
    if (triangles.length >= 200000 || !points.flat().every(Number.isFinite)) {
      throw Error('STL preview needs finite vertices and at most 200,000 triangles.');
    }
    const start = vertices.length;
    vertices.push(...points);
    triangles.push([start, start + 1, start + 2]);
  };
  if (count > 0 && 84 + count * 50 === buffer.byteLength) {
    if (count > 200000) {
      throw Error('STL preview is limited to 200,000 triangles.');
    }
    for (let index = 0; index < count; index += 1) {
      const offset = 84 + index * 50 + 12;
      add(Array.from({length: 3}, (_, point) => Array.from({length: 3}, (_, axis) =>
        view.getFloat32(offset + point * 12 + axis * 4, true))));
    }
  } else {
    const text = new TextDecoder('utf-8', {fatal: true}).decode(buffer);
    const pattern = /\bvertex\s+(\S+)\s+(\S+)\s+(\S+)/g;
    let match;
    let points = [];
    while ((match = pattern.exec(text))) {
      points.push(match.slice(1).map(Number));
      if (points.length === 3) {
        add(points);
        points = [];
      }
    }
    if (points.length || !triangles.length) {
      throw Error('This file does not contain complete STL triangles.');
    }
  }
  return {revision, objects: [{id: name, faces: [{id: 'surface', vertices, triangles}]}]};
}

export function createOutputBrowser(ctx, container) {
  let viewer = null;
  let request = null;
  let sequence = 0;
  const dispose = () => {
    sequence += 1;
    request?.abort();
    viewer?.destroy?.();
    viewer = null;
  };

  async function open(output) {
    dispose();
    const token = sequence;
    request = new AbortController();
    const url = ctx.api.url('/api/file', {path: output.path, sha256: output.sha256});
    const kind = viewerKind(output);
    const stage = h('div', {class: 'runner-viewer'});
    mount(container, h('div', {class: 'runner-output-heading'},
      h('div', {}, h('strong', {}, output.name), h('div', {class: 'hint'},
        `${output.operation || 'Output'} · ${output.kind || 'artifact'} · verified publication`)),
      h('a', {class: 'button small', href: url, download: output.name}, 'Download')), stage);
    if (kind === 'download') {
      mount(stage, h('div', {class: 'empty-state'}, h('h3', {}, 'Open in its native application'),
        h('p', {}, 'A preview is not available for this file format. Download the verified publication above.')));
      return;
    }
    try {
      const response = await fetch(url, {signal: request.signal, cache: 'no-store', referrerPolicy: 'no-referrer'});
      if (!response.ok) {
        let fault;
        try {
          fault = (await response.json()).fault;
        } catch {
          // A disconnected server may return a plain HTTP error.
        }
        throw new ApiError(fault || {code: 'FILE_READ_FAILED',
          message: `Cannot open output (HTTP ${response.status}).`});
      }
      const bytes = await response.arrayBuffer();
      if (token !== sequence) {
        return;
      }
      const digest = await crypto.subtle.digest('SHA-256', bytes);
      const actual = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('');
      if (actual !== output.sha256) {
        throw new ApiError({code: 'VERIFICATION_FAILED', message: 'This publication changed after verification.'});
      }
      if (token !== sequence) return;
      if (kind === 'image') {
        viewer = createImageViewer(stage);
        viewer.on('error', (error) => ctx.notify.error(error, {title: 'Cannot preview image'}));
        await viewer.load({blob: new Blob([bytes], {type: response.headers.get('Content-Type')}), name: output.name});
      } else if (kind.startsWith('3d')) {
        const payload = kind === '3d' ? stlGeometry(bytes, output.name, output.sha256)
          : JSON.parse(new TextDecoder().decode(bytes));
        viewer = createViewer3d(stage);
        viewer.on('error', (error) => ctx.notify.error(error, {title: 'Cannot preview geometry'}));
        await viewer.load(payload);
      } else {
        const text = new TextDecoder('utf-8', {fatal: true}).decode(bytes);
        viewer = kind === 'table' ? createTableViewer(stage) : createTextViewer(stage);
        viewer.on('error', (error) => ctx.notify.error(error, {title: 'Cannot preview output'}));
        await viewer.load({text, name: output.name, delimiter: output.name.endsWith('.tsv') ? '\t' : undefined});
      }
    } catch (error) {
      if (error.name !== 'AbortError' && token === sequence) {
        mount(stage, h('div', {class: 'empty-state'}, h('h3', {}, 'Preview unavailable'), h('p', {}, error.message)));
        ctx.notify.error(error, {title: 'Cannot preview output'});
      }
    }
  }
  return {open, dispose};
}
