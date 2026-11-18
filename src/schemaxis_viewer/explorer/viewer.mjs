// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// Full-area viewer for one file, with previous/next through the list it was
// opened from. Images keep their zoom and position while stepping, so the
// same region can be compared across a sequence.

import {h, icon, iconButton, textButton, clear, fill} from './dom.mjs';
import {mediaURL, readBytes} from './host.mjs';
import {formatBytes} from './names.mjs';
import {TextView} from './text.mjs';
import {TableView} from './table.mjs';
import {Renderer, meshFromBytes} from './gl.mjs';

export class ZoomImage {
  constructor(container, {hud = true} = {}) {
    this.container = container;
    this.root = container.appendChild(h('div', {class: 'zoom-image'}));
    this.image = this.root.appendChild(h('img', {alt: '', draggable: 'false'}));
    this.fit = true;
    this.scale = 1;
    this.x = 0;
    this.y = 0;
    this.label = h('span', {}, '100%');
    if (hud) {
      container.append(h('div', {class: 'stage-hud'},
        iconButton('chevronDown', 'Zoom out', () => this.zoomBy(1 / 1.25)),
        this.label,
        iconButton('plus', 'Zoom in', () => this.zoomBy(1.25)),
        textButton('Fit', () => this.fitView(), {class: 'button small'}),
        textButton('1:1', () => this.actual(), {class: 'button small'})));
    }
    this.image.addEventListener('load', () => {
      if (this.fit) this.fitView();
      else this.apply();
    });
    this.root.addEventListener('wheel', event => {
      event.preventDefault();
      const rect = this.root.getBoundingClientRect();
      this.zoomAt(Math.exp(-event.deltaY * 0.0015), event.clientX - rect.left, event.clientY - rect.top);
    }, {passive: false});
    this.root.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      this.drag = {x: event.clientX - this.x, y: event.clientY - this.y};
      this.root.setPointerCapture(event.pointerId);
      this.root.classList.add('dragging');
    });
    this.root.addEventListener('pointermove', event => {
      if (!this.drag) return;
      this.x = event.clientX - this.drag.x;
      this.y = event.clientY - this.drag.y;
      this.fit = false;
      this.apply();
    });
    this.root.addEventListener('pointerup', () => {
      this.drag = null;
      this.root.classList.remove('dragging');
    });
    this.root.addEventListener('dblclick', event => {
      const rect = this.root.getBoundingClientRect();
      if (this.fit) this.zoomAt(1 / this.scale, event.clientX - rect.left, event.clientY - rect.top);
      else this.fitView();
    });
    this.observer = new ResizeObserver(() => {
      if (this.fit) this.fitView();
    });
    this.observer.observe(this.root);
  }

  show(url) {
    if (this.image.getAttribute('src') !== url) this.image.src = url;
  }

  fitView() {
    const width = this.image.naturalWidth, height = this.image.naturalHeight;
    const rect = this.root.getBoundingClientRect();
    if (!width || !height || !rect.width) return;
    this.scale = Math.min(rect.width / width, rect.height / height) * 0.98;
    this.x = (rect.width - width * this.scale) / 2;
    this.y = (rect.height - height * this.scale) / 2;
    this.fit = true;
    this.apply();
  }

  actual() {
    const rect = this.root.getBoundingClientRect();
    this.zoomAt(1 / this.scale, rect.width / 2, rect.height / 2);
  }

  zoomBy(factor) {
    const rect = this.root.getBoundingClientRect();
    this.zoomAt(factor, rect.width / 2, rect.height / 2);
  }

  zoomAt(factor, cx, cy) {
    const scale = Math.min(64, Math.max(0.02, this.scale * factor));
    const applied = scale / this.scale;
    this.x = cx - (cx - this.x) * applied;
    this.y = cy - (cy - this.y) * applied;
    this.scale = scale;
    this.fit = false;
    this.apply();
  }

  apply() {
    this.image.style.setProperty('transform', `translate(${this.x}px, ${this.y}px) scale(${this.scale})`);
    this.root.classList.toggle('pixelated', this.scale > 3);
    this.label.textContent = `${Math.round(this.scale * 100)}%`;
  }

  dispose() {
    this.observer.disconnect();
  }
}

export class MeshView {
  constructor(container, item) {
    this.canvas = container.appendChild(h('canvas'));
    this.renderer = new Renderer(this.canvas);
    container.append(h('div', {class: 'space-hint'}, 'Drag to rotate · right-drag or Shift-drag to pan · wheel to zoom · double-click to reset'));
    readBytes(item).then(bytes => {
      this.renderer.setMeshes([{id: item.id, triangles: meshFromBytes(bytes, item.name), colour: [0.45, 0.62, 0.85], opacity: 1}]);
      this.renderer.frameAll();
    }).catch(error => {
      container.append(h('div', {class: 'no-preview'}, icon('mesh'), error.message));
    });
  }

  dispose() {
    this.renderer.dispose();
  }
}

export class FileViewer {
  constructor(app, root, list, item) {
    this.app = app;
    this.root = root;
    this.list = list.length ? list : [item];
    this.index = Math.max(0, this.list.indexOf(item));
    this.zoom = null;
    this.content = null;
    this.render();
  }

  get item() {
    return this.list[this.index];
  }

  render() {
    const item = this.item;
    this.position = h('span', {class: 'position'});
    this.title = h('div', {class: 'title'});
    this.prev = iconButton('chevronLeft', 'Previous (←)', () => this.step(-1));
    this.next = iconButton('chevronRight', 'Next (→)', () => this.step(1));
    this.stage = h('div', {class: 'stage'});
    fill(this.root,
      h('div', {class: 'stage-header'},
        iconButton('chevronLeft', 'Back (Esc)', () => this.app.closeViewer()),
        this.title, this.position, this.prev, this.next,
        h('a', {class: 'button small', href: mediaURL(item), download: item.name, dataset: {role: 'download'}}, icon('save', 14), 'Save a copy')),
      this.stage);
    this.show();
  }

  show() {
    const item = this.item;
    this.app.focus = item.id;
    this.app.inspector.render();
    this.title.replaceChildren(h('strong', {title: item.name}, item.name), h('span', {}, `${item.path} · ${formatBytes(item.size)}`));
    this.position.textContent = this.list.length > 1 ? `${this.index + 1} / ${this.list.length}` : '';
    this.prev.disabled = this.index === 0;
    this.next.disabled = this.index >= this.list.length - 1;
    const download = this.root.querySelector('[data-role=download]');
    download.href = mediaURL(item);
    download.download = item.name;
    if (item.kind === 'image') {
      if (!this.zoom) {
        this.disposeContent();
        clear(this.stage);
        this.stage.className = 'stage';
        this.zoom = new ZoomImage(this.stage);
      }
      this.zoom.show(mediaURL(item));
      return;
    }
    this.disposeContent();
    clear(this.stage);
    this.stage.className = 'stage' + (['text', 'table', 'pdf'].includes(item.kind) ? ' light' : '');
    if (item.kind === 'video') {
      this.stage.append(h('video', {src: mediaURL(item), controls: true, preload: 'metadata'}));
    } else if (item.kind === 'audio') {
      this.stage.append(h('audio', {src: mediaURL(item), controls: true, preload: 'metadata'}));
    } else if (item.kind === 'text') {
      this.content = new TextView(this.stage, item);
    } else if (item.kind === 'table') {
      this.content = new TableView(this.stage, item);
    } else if (item.kind === 'mesh') {
      this.content = new MeshView(this.stage, item);
    } else if (item.kind === 'pdf') {
      this.stage.append(h('iframe', {src: mediaURL(item), title: item.name}));
    } else {
      this.stage.append(h('div', {class: 'no-preview'}, icon('other'), h('div', {}, 'No preview for this kind of file.'),
        h('div', {}, `${item.ext ? '.' + item.ext + ' · ' : ''}${formatBytes(item.size)}`)));
    }
  }

  disposeContent() {
    this.content?.dispose?.();
    this.content = null;
    this.zoom?.dispose();
    this.zoom = null;
  }

  step(delta) {
    const index = Math.max(0, Math.min(this.list.length - 1, this.index + delta));
    if (index === this.index) return;
    this.index = index;
    this.show();
  }

  onKey(event) {
    if (event.key === 'Escape') {
      if (event.target instanceof HTMLInputElement && event.target.value) return;
      event.preventDefault();
      this.app.closeViewer();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f' && this.content?.focusFind) {
      event.preventDefault();
      this.content.focusFind();
      return;
    }
    const target = event.target;
    if (target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
    if (event.target instanceof HTMLMediaElement) return;
    if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
      event.preventDefault();
      this.step(-1);
    } else if (event.key === 'ArrowRight' || event.key === 'PageDown') {
      event.preventDefault();
      this.step(1);
    } else if (event.key === 'Home') {
      this.step(-this.list.length);
    } else if (event.key === 'End') {
      this.step(this.list.length);
    }
  }

  dispose() {
    this.disposeContent();
  }
}
