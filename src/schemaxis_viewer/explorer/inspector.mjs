// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// Inspector: the focused file's preview, properties with their sources, its
// spatial placement and its companion metadata.

import {h, icon, textButton, clear} from './dom.mjs';
import {mediaURL} from './host.mjs';
import {formatValue, formatBytes} from './names.mjs';
import {SOURCE_LABELS} from './collection.mjs';

function point(values) {
  return `(${values.map(value => Number(value.toPrecision(6))).join(', ')})`;
}

export class Inspector {
  constructor(app, root) {
    this.app = app;
    this.root = root;
  }

  render() {
    const app = this.app;
    clear(this.root);
    const item = app.focus && app.collection?.byId.get(app.focus);
    if (!item) {
      const count = app.selection.size;
      this.root.append(h('div', {class: 'empty-note'}, count ? `${count} files selected.` :
        app.collection ? 'Select a file to see its details.' : 'Details of the selected file appear here.'));
      return;
    }
    const preview = h('div', {class: 'preview'});
    if (item.kind === 'image') preview.append(h('img', {src: mediaURL(item), alt: ''}));
    else preview.append(h('span', {class: `kind-${item.kind}`}, icon(item.kind, 48)));
    const rows = Object.entries(item.props).map(([key, value]) => h('tr', {},
      h('td', {}, key), h('td', {class: 'value'}, formatValue(value)), h('td', {class: 'source'}, SOURCE_LABELS[item.sources[key]] || '')));
    this.root.append(preview,
      h('h2', {}, item.name),
      h('div', {class: 'path'}, item.path),
      h('div', {class: 'actions'},
        textButton('Open', () => app.activate(item.id, app.view?.orderedIds?.() || [item.id]), {class: 'button small primary'}),
        h('a', {class: 'button small', href: mediaURL(item), download: item.name}, 'Save a copy')),
      h('table', {class: 'props'}, h('tbody', {},
        h('tr', {}, h('td', {}, 'size'), h('td', {class: 'value'}, formatBytes(item.size)), h('td', {class: 'source'}, 'file')),
        item.sx ? h('tr', {}, h('td', {}, 'output'), h('td', {class: 'value'}, item.sx.ordinal + (item.sx.worker ? '.' + item.sx.worker : '')),
          h('td', {class: 'source'}, 'filename')) : null,
        rows)));
    if (item.spatial) {
      const s = item.spatial;
      const labels = ['top-left', 'top-right', 'bottom-right', 'bottom-left'];
      this.root.append(h('h3', {}, 'Position in 3D'),
        h('table', {class: 'props'}, h('tbody', {},
          s.frame ? h('tr', {}, h('td', {}, 'frame'), h('td', {class: 'value'}, s.frame + (s.units ? ` (${s.units})` : ''))) : null,
          h('tr', {}, h('td', {}, 'normal'), h('td', {class: 'value'}, point(s.normal))),
          s.corners.map((corner, index) => h('tr', {}, h('td', {}, labels[index]), h('td', {class: 'value'}, point(corner)))))),
        textButton('Show in 3D', () => {
          app.spaceState.only = null;
          app.spaceState.focusItem = item.id;
          app.setView('space');
        }, {class: 'button small'}));
    }
    if (item.companion) {
      this.root.append(h('h3', {}, 'Metadata'), h('div', {class: 'path'}, item.companion.name));
      if (item.meta) {
        this.root.append(h('div', {class: item.metaVerified ? 'meta-status' : 'meta-status warning'}, item.metaStatus),
          h('details', {}, h('summary', {}, 'Show JSON'), h('pre', {}, JSON.stringify(item.meta, null, 2))));
      } else {
        this.root.append(h('div', {class: 'path'}, 'Reading…'));
      }
    }
  }
}
