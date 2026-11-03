// Copyright (C) 2026 David L F Gaden
// Adaptor-declared viewers, local sample loading and reference chips.

import {h, mount} from '../../lib/dom.mjs';
import {createViewer3d} from '../../viewers/viewer3d.mjs';
import {createImageViewer} from '../../viewers/image.mjs';
import {createTableViewer} from '../../viewers/table.mjs';
import {createTextViewer} from '../../viewers/text.mjs';
import {createChip, referenceLabel} from '../../viewers/chip.mjs';
import {sha256, staleReason, verifiedArtifact} from './provenance.mjs';

const FACTORIES = {'3d': createViewer3d, image: createImageViewer, table: createTableViewer, text: createTextViewer};
export const VIEWER_LABELS = {'3d': '3D', image: 'Image', table: 'Table', text: 'Text'};

export function createViewers({ctx, store, onTab, onObservation = () => {}}) {
  const instances = new Map();
  const digests = new Map();
  const downloads = new Set();
  let disposed = false;
  const artifacts = h('section', {class: 'wb-artifacts', hidden: true});
  const references = h('section', {class: 'wb-references'});
  const chipList = h('div', {class: 'wb-chips', 'aria-label': 'Picked references'});
  const empty = h('p', {class: 'wb-help'}, 'Pick a face, pixel, table cell or text to collect a reference.');
  const details = h('pre', {class: 'wb-reference-detail mono', hidden: true});
  references.append(h('h3', {class: 'wb-section-title'}, 'References'), empty, chipList, details,
    h('button', {class: 'button small', onClick: () => ctx.call(async () => {
      await navigator.clipboard.writeText(JSON.stringify(store.get().references.map(markStale), null, 2));
      ctx.notify.ok('References copied');
    }, {title: 'Could not copy references'})}, 'Copy references'));

  const markStale = (reference) => {
    const reason = staleReason(reference, store.get().record, digests);
    return reason ? {...reference, stale: true, staleReason: reason} : reference;
  };
  function renderReferences() {
    const items = store.get().references;
    empty.hidden = Boolean(items.length);
    mount(chipList, items.map((reference, index) => {
      const marked = markStale(reference);
      const chip = createChip({reference: marked,
        label: `${referenceLabel(reference)}${marked.stale ? ' · stale' : ''}`,
        title: marked.staleReason || referenceLabel(reference),
        onActivate: () => {
          details.hidden = false;
          details.textContent = JSON.stringify(markStale(reference), null, 2);
        },
        onRemove: () => {
          store.set({references: store.get().references.filter((_, position) => position !== index)});
          details.hidden = true;
          return false;
        }});
      chip.classList.toggle('wb-stale', Boolean(marked.stale));
      return chip;
    }));
  }
  const unsubscribe = store.subscribe((state, previous) => {
    if (state.dirty !== previous.dirty || state.record !== previous.record) {
      instances.forEach((item) => {
        if (item.provenance?.document) {
          const stale = state.dirty || item.provenance.revision !== state.record?.revision;
          item.label.textContent = item.loadedLabel + (stale ? ' · earlier input; preview again to refresh' : '');
        }
      });
    }
    if (state.references !== previous.references || state.record !== previous.record) {
      details.hidden = true;
      renderReferences();
    }
  });
  const unsubscribeNative = store.watch((state) => state.native, (native) => {
    instances.forEach((item) => {
      if (item.nativeButton) {
        item.nativeButton.disabled = native !== 'live';
      }
    });
  });

  function addReference(reference, provenance) {
    if (!reference || !provenance) {
      return;
    }
    const marked = {...reference, ...provenance};
    const items = store.get().references;
    if (!items.some((item) => JSON.stringify(item) === JSON.stringify(marked))) {
      store.set({references: [...items, marked]});
    }
  }

  function beginLoad(target) {
    target.controller?.abort();
    target.controller = new AbortController();
    target.provenance = null;
    target.viewer.clear();
    target.label.textContent = 'Loading…';
    return ++target.sequence;
  }

  async function finishLoad(target, token, data, provenance, label) {
    if (disposed || token !== target.sequence) return;
    const loaded = await target.viewer.load(data);
    if (!loaded || disposed || token !== target.sequence) return;
    target.provenance = provenance;
    target.loadedLabel = label;
    target.label.textContent = label;
    if (provenance.resource && provenance.digest) digests.set(provenance.resource, provenance.digest);
    renderReferences();
  }

  function get(kind) {
    if (!FACTORIES[kind]) {
      return null;
    }
    if (!instances.has(kind)) {
      const body = h('div', {class: 'wb-viewer-body'});
      const input = h('input', {type: 'file', hidden: true,
        accept: kind === 'image' ? 'image/png,image/jpeg,image/webp' : kind === '3d' ? '.json' : undefined});
      const label = h('span', {class: 'wb-help'}, 'Use Preview with live data in Input to execute this draft, or open a sample file.');
      const nativeButton = ['3d', 'image'].includes(kind)
        ? h('button', {class: 'button small', disabled: store.get().native !== 'live',
          onClick: () => ctx.call(() => nativePreview(kind, store.get().record),
            {title: 'Could not load native preview'})}, 'Load native preview') : null;
      const panel = h('div', {class: 'wb-viewer-panel', hidden: true, dataset: {viewerPanel: kind}},
        h('div', {class: 'wb-viewer-tools'}, h('button', {class: 'button small',
          onClick: () => input.click()}, 'Open sample file…'), nativeButton, label, input), body);
      const viewer = FACTORIES[kind](body);
      const target = {panel, viewer, label, nativeButton, sequence: 0, provenance: null, controller: null};
      viewer.on('pick', (reference) => addReference(reference, target.provenance));
      viewer.on('error', (error) => ctx.notify.error(error, {title: `${VIEWER_LABELS[kind]} viewer` }));
      viewer.on('extract', async (table) => {
        const destination = get('table');
        const provenance = target.provenance;
        if (!provenance) return;
        await finishLoad(destination, beginLoad(destination), table, provenance, target.label.textContent);
        onTab('table');
      });
      input.addEventListener('change', () => ctx.call(async () => {
        const file = input.files?.[0];
        if (!file) {
          return;
        }
        const token = beginLoad(target);
        const bytes = await file.arrayBuffer();
        const digest = await sha256(bytes);
        const data = kind === '3d' ? JSON.parse(new TextDecoder().decode(bytes))
          : {blob: file, name: file.name, digest};
        await finishLoad(target, token, data,
          {origin: 'sample', name: file.name, digest, resource: `sample:${kind}:${file.name}`}, file.name);
        input.value = '';
      }, {title: 'Could not open sample file'}));
      instances.set(kind, target);
    }
    return instances.get(kind);
  }

  function artifactKind(artifact) {
    const path = artifact.file.toLowerCase();
    if (artifact.kind === 'liveGeometry') {
      return '3d';
    }
    if (/\.(png|jpg|jpeg|webp)$/.test(path)) {
      return 'image';
    }
    if (/\.(csv|tsv)$/.test(path)) {
      return 'table';
    }
    return /\.(json|txt|log)$/.test(path) ? 'text' : null;
  }

  async function openArtifact(artifact, provenance) {
    const kind = artifactKind(artifact);
    const target = get(kind);
    if (!target) {
      return;
    }
    const token = beginLoad(target);
    let output;
    try { output = await readVerified(artifact, target.controller.signal); }
    catch (error) {
      if (error.name === 'AbortError') return;
      if (!disposed && token === target.sequence) target.label.textContent = 'Output could not be verified.';
      throw error;
    }
    const {bytes, digest, contentType} = output;
    const name = artifact.file.split('/').at(-1);
    const data = kind === '3d' ? JSON.parse(new TextDecoder().decode(bytes))
      : {blob: new Blob([bytes], {type: contentType}), name, digest};
    await finishLoad(target, token, data, {...provenance, digest, artifact: artifact.file,
      resource: `artifact:${artifact.file}`}, `${name} · verified bytes · revision ${provenance.revision}`);
    if (!disposed && token === target.sequence) onTab(kind);
  }

  async function readVerified(artifact, signal) {
    try { return await verifiedArtifact(ctx.api, artifact, signal); }
    catch (error) {
      if (error.code === 'VERIFICATION_FAILED') {
        digests.set(`artifact:${artifact.file}`, null);
        details.hidden = true;
        renderReferences();
      }
      throw error;
    }
  }

  async function nativePreview(kind, record) {
    const target = get(kind);
    const token = beginLoad(target);
    const provenance = {origin: 'native', document: record.id, revision: record.revision,
      resource: `native:${record.id}:${kind}`};
    try {
      let data;
      if (kind === '3d') {
        data = await ctx.api.get('/api/geometry', {document: record.id, revision: record.revision});
        provenance.digest = await sha256(new TextEncoder().encode(JSON.stringify(data)));
      } else if (kind === 'image') {
        const info = await ctx.api.get('/api/image-info', {document: record.id, revision: record.revision});
        data = {src: ctx.api.url('/api/image', {document: record.id,
          revision: record.revision, digest: info.sha256}), digest: info.sha256, revision: record.revision};
        provenance.digest = info.sha256;
      }
      await finishLoad(target, token, data, provenance, `Native preview · revision ${record.revision}`);
      if (!disposed && token === target.sequence && data.observations) onObservation(data.observations);
      if (!disposed && token === target.sequence) onTab(kind);
    } catch (error) {
      if (['NATIVE_DIVERGENCE', 'STALE_REFERENCE', 'NO_GEOMETRY'].includes(error.code)) {
        digests.set(provenance.resource, null);
        details.hidden = true;
        renderReferences();
      }
      if (!disposed && token === target.sequence) target.label.textContent = 'Native preview unavailable.';
      throw error;
    }
  }

  async function downloadArtifact(artifact) {
    const request = new AbortController();
    downloads.add(request);
    try {
      const {bytes, contentType} = await readVerified(artifact, request.signal);
      if (disposed) return;
      const url = URL.createObjectURL(new Blob([bytes], {type: contentType}));
      h('a', {href: url, download: artifact.file.split('/').at(-1)}).click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      if (error.name !== 'AbortError') throw error;
    } finally { downloads.delete(request); }
  }

  return {references, artifacts, get, addReference,
    async showArtifacts(items) {
      const record = store.get().record;
      const provenance = {origin: 'artifact', document: record.id, revision: record.revision};
      artifacts.hidden = !items.length;
      const supported = store.get().metadata.viewers;
      mount(artifacts, h('h3', {class: 'wb-section-title'}, 'Verified outputs'),
      h('p', {class: 'wb-help'}, `Run input · revision ${record.revision}`), items.map((artifact) => {
        const kind = artifactKind(artifact);
        return h('div', {class: 'wb-artifact'}, h('a', {
          href: ctx.api.url('/api/file', {path: artifact.file, sha256: artifact.sha256}),
          onClick: (event) => {
            event.preventDefault();
            ctx.call(() => downloadArtifact(artifact), {title: 'Could not download output'});
          },
          download: artifact.file.split('/').at(-1)}, artifact.file.split('/').at(-1)),
        kind && supported.includes(kind) ? h('button', {class: 'button small',
          onClick: () => ctx.call(() => openArtifact(artifact, provenance), {title: 'Could not open output'})},
        'View') : null);
      }));
      const first = items.find((item) => supported.includes(artifactKind(item)));
      if (first) {
        await openArtifact(first, provenance);
      }
    },
    preview: nativePreview,
    resize() {
      instances.forEach((item) => item.viewer.resize());
    },
    destroy() {
      disposed = true;
      unsubscribe();
      unsubscribeNative();
      downloads.forEach((request) => request.abort());
      instances.forEach((item) => {
        item.sequence += 1;
        item.controller?.abort();
        item.viewer.destroy();
      });
    }};
}
