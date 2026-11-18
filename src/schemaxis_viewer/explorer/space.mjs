// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// 3D view: images whose metadata gives their four corners are drawn in place,
// together with meshes from the collection. Slices of one sequence form a
// stack with its own slider, so one slice per stack can be stepped through.

import {h, icon, iconButton, textButton, chip, clear, fill} from './dom.mjs';
import {mediaURL, readBytes} from './host.mjs';
import {formatValue} from './names.mjs';
import {commonChips} from './collection.mjs';
import {Renderer, meshFromBytes} from './gl.mjs';

const MESH_COLOURS = [[0.55, 0.68, 0.88], [0.86, 0.62, 0.42], [0.55, 0.8, 0.62], [0.8, 0.6, 0.85]];

function offsetAlong(item) {
  const n = item.spatial.normal, c = item.spatial.corners[0];
  return n[0] * c[0] + n[1] * c[1] + n[2] * c[2];
}

function stackKey(item) {
  if (item.family) return item.family.id;
  return 'normal:' + item.folder + ':' + item.spatial.normal.map(v => v.toFixed(3)).join(',');
}

function dominantAxis(normal) {
  const a = normal.map(Math.abs);
  return a[0] >= a[1] && a[0] >= a[2] ? 'X' : a[1] >= a[2] ? 'Y' : 'Z';
}

export class SpaceView {
  constructor(app, root) {
    this.app = app;
    this.root = root;
    root.classList.add('fill');
    this.panelOpen = true;
    this.container = root.appendChild(h('div', {class: 'space'}));
    this.canvas = this.container.appendChild(h('canvas', {'aria-label': '3D view'}));
    this.panel = this.container.appendChild(h('div', {class: 'space-panel'}));
    this.labels = this.container.appendChild(h('div'));
    this.container.append(h('div', {class: 'space-hint'}, 'Drag to rotate · right-drag or Shift-drag to pan · wheel to zoom · double-click to fit · click a slice to inspect it'));
    try {
      this.renderer = new Renderer(this.canvas, {onPick: id => this.picked(id), onChange: () => this.placeLabels()});
      if (app.spaceState.up) this.renderer.setUp(app.spaceState.up);
    } catch (error) {
      fill(this.container, h('div', {class: 'no-preview'}, icon('cube'), error.message));
    }
    this.framed = false;
  }

  dispose() {
    if (this.renderer) this.app.spaceState.camera = {...this.renderer.camera, target: [...this.renderer.camera.target]};
    this.renderer?.dispose();
    this.root.classList.remove('fill');
  }

  resize() {
    this.renderer?.invalidate();
  }

  contextControls() {
    const app = this.app, state = app.spaceState;
    return [
      h('label', {class: 'field'}, 'Up',
        h('select', {'aria-label': 'Up axis', onChange: event => {
          state.up = event.target.value;
          this.renderer?.setUp(state.up);
        }}, ['z', 'y'].map(axis => h('option', {value: axis, selected: (state.up || 'z') === axis}, axis.toUpperCase())))),
      textButton('Fit view', () => this.renderer?.frameAll(), {class: 'button small'}),
      textButton(this.panelOpen ? 'Hide panel' : 'Show panel', () => {
        this.panelOpen = !this.panelOpen;
        this.panel.hidden = !this.panelOpen;
        app.renderContextbar();
      }, {class: 'button small'}),
      state.only ? h('span', {class: 'field'}, `Showing ${state.only.size} chosen files`,
        textButton('Show all', () => {
          state.only = null;
          app.render();
        }, {class: 'button small'})) : null
    ];
  }

  content() {
    const only = this.app.spaceState.only;
    const items = this.app.derived.visible.filter(item => !only || only.has(item.id));
    return {planes: items.filter(item => item.spatial && item.kind === 'image'), meshes: items.filter(item => item.kind === 'mesh')};
  }

  stacks(planes) {
    const map = new Map();
    for (const item of planes) {
      const key = stackKey(item);
      if (!map.has(key)) map.set(key, {id: key, items: [], chips: item.family?.chips || [], label: item.family?.label || null,
        orderKey: item.family?.order || null, axis: dominantAxis(item.spatial.normal)});
      map.get(key).items.push(item);
    }
    const stacks = [...map.values()];
    for (const stack of stacks) stack.items.sort((a, b) => offsetAlong(a) - offsetAlong(b));
    stacks.sort((a, b) => a.axis.localeCompare(b.axis));
    const state = this.app.spaceState.stacks;
    const seenAxes = new Set();
    for (const stack of stacks) {
      if (!state.has(stack.id)) {
        const first = !seenAxes.has(stack.axis) || this.app.spaceState.only;
        state.set(stack.id, {visible: !!first, index: Math.floor(stack.items.length / 2), all: false});
      }
      if (state.get(stack.id).visible) seenAxes.add(stack.axis);
    }
    const focusId = this.app.spaceState.focusItem;
    if (focusId) {
      for (const stack of stacks) {
        const index = stack.items.findIndex(item => item.id === focusId);
        if (index >= 0) Object.assign(state.get(stack.id), {visible: true, index});
      }
      this.app.spaceState.focusItem = null;
    }
    return stacks;
  }

  render() {
    if (!this.renderer) return;
    const {planes, meshes} = this.content();
    if (!planes.length && !meshes.length) {
      this.panel.hidden = false;
      fill(this.panel, h('div', {class: 'sidebar-note'}, h('strong', {}, 'Nothing to place in 3D here.'), h('br'),
        'Images appear in 3D when they have a metadata companion (for example ', h('code', {}, 'name.png.metadata.json'),
        ') that gives their four corners. STL and OBJ models are shown as well.'));
      this.renderer.setPlanes([]);
      this.renderer.setMeshes([]);
      return;
    }
    this.stackList = this.stacks(planes);
    this.meshItems = meshes;
    this.renderPanel();
    this.updateScene();
    this.loadMeshes();
  }

  renderPanel() {
    const state = this.app.spaceState;
    this.panel.hidden = !this.panelOpen;
    clear(this.panel);
    const {distinct} = commonChips(this.stackList.map(stack => ({id: stack.id, chips: stack.chips})));
    if (this.stackList.length) this.panel.append(h('h4', {}, 'Slices'));
    for (const stack of this.stackList) {
      const entry = state.stacks.get(stack.id);
      const item = stack.items[entry.index];
      const valueText = stack.orderKey && item.props[stack.orderKey] !== undefined
        ? `${stack.orderKey} ${formatValue(item.props[stack.orderKey])}` : `${entry.index + 1} / ${stack.items.length}`;
      const names = (distinct.get(stack.id) || []).map(([key, value]) => chip(key, formatValue(value)));
      if (!names.length) names.push(h('span', {}, stack.label || `${stack.axis} planes`));
      const value = h('span', {}, entry.all ? `all ${stack.items.length}` : valueText);
      const visibleBox = h('input', {type: 'checkbox', checked: entry.visible, 'aria-label': 'Show this stack', onChange: event => {
        entry.visible = event.target.checked;
        this.updateScene();
      }});
      this.panel.append(h('div', {class: 'stack-row'},
        h('div', {class: 'top'},
          visibleBox,
          h('div', {class: 'names'}, (distinct.get(stack.id) || []).some(([key]) => key === 'axis') ? null
            : h('span', {class: 'chip'}, h('span', {class: 'chip-value'}, stack.axis)), names),
          stack.items.length > 1 ? h('label', {class: 'check', title: 'Show every slice of this stack'},
            h('input', {type: 'checkbox', checked: entry.all, onChange: event => {
              entry.all = event.target.checked;
              this.renderPanel();
              this.updateScene();
            }}), 'all') : null),
        stack.items.length > 1 && !entry.all ? h('div', {class: 'slider'},
          h('input', {type: 'range', min: 0, max: stack.items.length - 1, value: entry.index, 'aria-label': `${stack.axis} slice`,
            onInput: event => {
              entry.index = Number(event.target.value);
              entry.visible = true;
              const current = stack.items[entry.index];
              value.textContent = stack.orderKey && current.props[stack.orderKey] !== undefined
                ? `${stack.orderKey} ${formatValue(current.props[stack.orderKey])}` : `${entry.index + 1} / ${stack.items.length}`;
              visibleBox.checked = true;
              this.updateScene();
            }}), value) : h('div', {class: 'slider'}, value)));
    }
    if (this.meshItems.length) {
      this.panel.append(h('h4', {}, 'Models'));
      for (const item of this.meshItems) {
        const visible = state.meshes.get(item.id)?.visible !== false;
        this.panel.append(h('div', {class: 'stack-row'}, h('label', {class: 'check'},
          h('input', {type: 'checkbox', checked: visible, onChange: event => {
            const entry = state.meshes.get(item.id) || {};
            entry.visible = event.target.checked;
            state.meshes.set(item.id, entry);
            this.updateMeshes();
          }}), item.name)));
      }
    }
  }

  visiblePlanes() {
    const state = this.app.spaceState.stacks, focus = this.app.focus, result = [];
    for (const stack of this.stackList || []) {
      const entry = state.get(stack.id);
      if (!entry.visible) continue;
      const items = entry.all ? stack.items : [stack.items[Math.min(entry.index, stack.items.length - 1)]];
      for (const item of items) result.push({id: item.id, corners: item.spatial.corners, url: mediaURL(item),
        highlight: item.id === focus, opacity: entry.all ? 0.85 : 1});
    }
    return result;
  }

  updateScene() {
    this.renderer.setPlanes(this.visiblePlanes());
    this.updateMeshes();
    if (!this.framed && this.renderer.bounds) {
      this.framed = true;
      const saved = this.app.spaceState.camera;
      if (saved) {
        Object.assign(this.renderer.camera, saved);
        this.renderer.invalidate();
      } else {
        this.renderer.frameAll();
      }
    }
  }

  updateMeshes() {
    const state = this.app.spaceState.meshes;
    const meshes = [];
    (this.meshItems || []).forEach((item, index) => {
      const entry = state.get(item.id);
      if (!entry?.triangles) return;
      meshes.push({id: item.id, triangles: entry.triangles, colour: MESH_COLOURS[index % MESH_COLOURS.length],
        opacity: this.stackList.length ? 0.18 : 0.9, visible: entry.visible !== false});
    });
    this.renderer.setMeshes(meshes);
    if (!this.framed && this.renderer.bounds) {
      this.framed = true;
      this.renderer.frameAll();
    }
  }

  async loadMeshes() {
    const state = this.app.spaceState.meshes;
    for (const item of this.meshItems) {
      const entry = state.get(item.id) || {};
      if (entry.triangles || entry.loading || entry.error) continue;
      entry.loading = true;
      state.set(item.id, entry);
      try {
        entry.triangles = meshFromBytes(await readBytes(item), item.name);
      } catch (error) {
        entry.error = error.message;
        this.app.toast(`${item.name}: ${error.message}`, true);
      }
      entry.loading = false;
      if (this.renderer && !this.renderer.disposed) this.updateMeshes();
    }
  }

  picked(id) {
    if (!id) return;
    this.app.selection.clear();
    this.app.selection.add(id);
    this.app.focus = id;
    this.app.selectionChanged();
    this.renderer.setPlanes(this.visiblePlanes());
  }

  placeLabels() {
    const bounds = this.renderer?.bounds;
    clear(this.labels);
    if (!bounds || !this.renderer.origin) return;
    const origin = this.renderer.origin;
    const size = Math.max(...bounds.high.map((v, i) => v - bounds.low[i])) * 0.22;
    ['X', 'Y', 'Z'].forEach((name, axis) => {
      const end = bounds.low.map((v, i) => v + origin[i]);
      end[axis] += size;
      const screen = this.renderer.project(end);
      if (!screen) return;
      const label = h('div', {class: 'space-label'}, name);
      label.style.setProperty('left', screen[0] + 'px');
      label.style.setProperty('top', screen[1] + 'px');
      this.labels.append(label);
    });
  }

  refreshSelection() {
    if (this.renderer && this.stackList) this.renderer.setPlanes(this.visiblePlanes());
  }
}
