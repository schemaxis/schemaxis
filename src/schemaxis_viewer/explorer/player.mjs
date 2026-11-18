// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// Sequence player: one or more panes, each showing a sequence of images.
// Panes can be linked to one slider or stepped separately, and "Split by"
// fills the panes with the sequences that differ only in one property
// (for example axis X | Y | Z). Playback runs forward or in reverse, looping,
// bouncing or stopping at the end.

import {h, icon, iconButton, toggleButton, textButton, clear} from './dom.mjs';
import {mediaURL} from './host.mjs';
import {formatValue} from './names.mjs';
import {captionFor, commonChips} from './collection.mjs';
import {ZoomImage} from './viewer.mjs';

const SPEEDS = [1, 2, 4, 8, 12, 24, 30];

function frames(group) {
  return group.items.filter(item => item.kind === 'image');
}

export class PlayerView {
  constructor(app, root) {
    this.app = app;
    this.root = root;
    root.classList.add('fill');
    this.state = app.playerState;
    this.direction = 1;
    this.timer = null;
    this.paneViews = [];
    this.preloaded = new Set();
  }

  dispose() {
    this.stop();
    for (const pane of this.paneViews) pane.zoom.dispose();
    this.root.classList.remove('fill');
  }

  available() {
    return this.app.sequences().filter(group => frames(group).length > 0);
  }

  titles(sequences) {
    const {distinct} = commonChips(sequences);
    const showFolder = new Set(sequences.map(group => group.folder).filter(Boolean)).size > 1;
    return new Map(sequences.map(group => {
      const chips = (distinct.get(group.id) || []).map(([key, value]) => `${key} ${formatValue(value)}`);
      const folder = showFolder && group.folder ? group.folder.split('/').at(-1) + ' ›' : null;
      const text = [folder, [group.label, ...chips].filter(Boolean).join(' · ')].filter(Boolean).join(' ')
        || (group.id === '@other' ? 'Other files' : 'Sequence');
      return [group.id, `${text} (${frames(group).length})`];
    }));
  }

  contextControls() {
    const sequences = this.available();
    const splitKeys = new Set();
    const values = new Map();
    for (const group of sequences) for (const [key, value] of group.chips) {
      if (!values.has(key)) values.set(key, new Set());
      values.get(key).add(JSON.stringify(value));
    }
    for (const [key, tokens] of values) if (tokens.size > 1) splitKeys.add(key);
    return [
      h('label', {class: 'field'}, 'Split by',
        h('select', {'aria-label': 'Split by', onChange: event => this.split(event.target.value)},
          h('option', {value: ''}, 'One pane'),
          [...splitKeys].map(key => h('option', {value: key, selected: this.state.splitBy === key}, key)))),
      textButton('Add pane', () => this.addPane(), {class: 'button small', disabled: !sequences.length}),
      toggleButton(this.state.linked ? 'link' : 'unlink', this.state.linked ? 'Panes move together (click to unlink)' : 'Panes move separately (click to link)',
        this.state.linked, () => {
          this.state.linked = !this.state.linked;
          if (this.state.linked) this.syncFromMaster();
          this.render();
          this.app.renderContextbar();
        }),
      h('span', {class: 'field'}, this.state.linked ? 'Linked' : 'Separate')
    ];
  }

  ensurePanes() {
    const sequences = this.available();
    const ids = new Set(sequences.map(group => group.id));
    this.state.panes = this.state.panes.filter(pane => ids.has(pane.groupId));
    if (!this.state.panes.length && sequences.length) {
      const focused = this.app.focus && sequences.find(group => group.items.some(item => item.id === this.app.focus));
      this.state.panes = [{groupId: (focused || sequences[0]).id, index: 0}];
    }
    return sequences;
  }

  split(key) {
    this.state.splitBy = key || null;
    const sequences = this.available();
    const base = this.app.findSequence(this.state.panes[0]?.groupId) || sequences[0];
    if (!key || !base) {
      this.state.panes = base ? [{groupId: base.id, index: this.state.panes[0]?.index || 0}] : [];
      this.render();
      return;
    }
    const others = new Map(base.chips.filter(([k]) => k !== key).map(([k, v]) => [k, JSON.stringify(v)]));
    const matching = sequences.filter(group => {
      if (group.label !== base.label) return false;
      const own = new Map(group.chips.map(([k, v]) => [k, JSON.stringify(v)]));
      if (!own.has(key)) return false;
      if (own.size !== others.size + 1) return false;
      for (const [k, token] of others) if (own.get(k) !== token) return false;
      return true;
    });
    matching.sort((a, b) => String(a.chips.find(([k]) => k === key)?.[1]).localeCompare(String(b.chips.find(([k]) => k === key)?.[1])));
    if (matching.length < 2) {
      this.app.toast(`The current sequence has no siblings that differ only in “${key}”.`, true);
      return;
    }
    this.state.panes = matching.slice(0, 6).map(group => ({groupId: group.id, index: 0}));
    this.syncFromMaster();
    this.render();
  }

  addPane() {
    const sequences = this.available();
    const used = new Set(this.state.panes.map(pane => pane.groupId));
    const next = sequences.find(group => !used.has(group.id)) || sequences[0];
    if (!next) return;
    this.state.panes.push({groupId: next.id, index: 0});
    this.syncFromMaster();
    this.render();
  }

  length() {
    return Math.max(1, ...this.state.panes.map(pane => frames(this.app.findSequence(pane.groupId) || {items: []}).length));
  }

  syncFromMaster() {
    const longest = this.length();
    for (const pane of this.state.panes) {
      const count = frames(this.app.findSequence(pane.groupId) || {items: []}).length;
      pane.index = count <= 1 ? 0 : longest <= 1 ? 0 : Math.round(this.state.index * (count - 1) / (longest - 1));
    }
  }

  render() {
    const sequences = this.ensurePanes();
    clear(this.root);
    for (const pane of this.paneViews) pane.zoom.dispose();
    this.paneViews = [];
    if (!sequences.length) {
      this.root.append(h('div', {class: 'empty-state'}, icon('player'),
        'No image sequences match the current folder, search and filters.', h('br'),
        'Sequences come from numbered filenames, Schemaxis output names (pos, time or frame), or a property chosen in Groups.'));
      return;
    }
    const titles = this.titles(sequences);
    this.state.index = Math.min(this.state.index, this.length() - 1);
    const player = this.root.appendChild(h('div', {class: 'player'}));
    const panes = player.appendChild(h('div', {class: 'player-panes'}));
    for (const [position, pane] of this.state.panes.entries()) panes.append(this.paneView(pane, position, sequences, titles));
    if (this.state.panes.length === 1) player.append(this.filmstrip());
    player.append(this.transport());
    this.preload();
    this.show();
  }

  paneView(pane, position, sequences, titles) {
    const image = h('div', {class: 'pane-image'});
    const zoom = new ZoomImage(image, {hud: false});
    const value = h('div', {class: 'value'});
    image.append(value);
    const slider = h('input', {type: 'range', min: 0, value: pane.index, 'aria-label': 'Frame', onInput: event => {
      pane.index = Number(event.target.value);
      this.show();
    }});
    const label = h('span', {class: 'value-label'});
    const node = h('div', {class: 'player-pane'},
      h('div', {class: 'pane-head'},
        h('select', {'aria-label': 'Sequence', onChange: event => {
          pane.groupId = event.target.value;
          pane.index = 0;
          this.state.splitBy = null;
          this.syncFromMaster();
          this.render();
          this.app.renderContextbar();
        }}, sequences.map(group => h('option', {value: group.id, selected: group.id === pane.groupId}, titles.get(group.id)))),
        this.state.panes.length > 1 ? iconButton('close', 'Remove this pane', () => {
          this.state.panes.splice(position, 1);
          this.render();
        }, {class: 'icon-button small'}) : null),
      image,
      this.state.linked ? null : h('div', {class: 'pane-foot'}, slider, label));
    this.paneViews.push({pane, zoom, value, slider, label});
    return node;
  }

  filmstrip() {
    const pane = this.state.panes[0];
    const group = this.app.findSequence(pane.groupId);
    const strip = h('div', {class: 'filmstrip'});
    for (const [index, item] of frames(group).entries()) {
      strip.append(h('button', {type: 'button', title: captionFor(item, group.orderKey, group.vary), dataset: {index}, onClick: () => {
        this.state.index = index;
        pane.index = index;
        this.show();
      }}, h('img', {src: mediaURL(item), loading: 'lazy', alt: ''})));
    }
    this.strip = strip;
    return strip;
  }

  transport() {
    this.playButton = iconButton('play', 'Play (Space)', () => this.toggle(1), {class: 'icon-button play'});
    this.reverseButton = iconButton('reverse', 'Play backwards', () => this.toggle(-1));
    this.master = h('input', {type: 'range', class: 'master', min: 0, max: this.length() - 1, value: this.state.index,
      'aria-label': 'Frame', hidden: !this.state.linked, onInput: event => {
        this.state.index = Number(event.target.value);
        this.syncFromMaster();
        this.show();
      }});
    this.frameLabel = h('span', {class: 'frame-label'});
    return h('div', {class: 'transport'},
      iconButton('first', 'First frame (Home)', () => this.jump(0)),
      iconButton('stepBack', 'Previous frame (←)', () => this.step(-1)),
      this.reverseButton, this.playButton,
      iconButton('stepForward', 'Next frame (→)', () => this.step(1)),
      iconButton('last', 'Last frame (End)', () => this.jump(Infinity)),
      this.master, this.state.linked ? null : h('div', {class: 'spacer'}),
      this.frameLabel,
      h('select', {'aria-label': 'At the end', title: 'At the end of the sequence', onChange: event => { this.state.mode = event.target.value; }},
        [['loop', 'Loop'], ['bounce', 'Bounce'], ['once', 'Stop at end']].map(([value, text]) =>
          h('option', {value, selected: this.state.mode === value}, text))),
      h('select', {'aria-label': 'Speed', title: 'Frames per second', onChange: event => {
        this.state.fps = Number(event.target.value);
        if (this.timer) this.start(this.direction);
      }}, SPEEDS.map(fps => h('option', {value: fps, selected: this.state.fps === fps}, `${fps} fps`))));
  }

  preload() {
    for (const pane of this.state.panes) {
      if (this.preloaded.has(pane.groupId)) continue;
      this.preloaded.add(pane.groupId);
      const group = this.app.findSequence(pane.groupId);
      for (const item of frames(group).slice(0, 600)) {
        const image = new Image();
        image.decoding = 'async';
        image.src = mediaURL(item);
      }
    }
  }

  show() {
    const longest = this.length();
    if (this.master) {
      this.master.max = longest - 1;
      this.master.value = this.state.index;
    }
    const labels = [];
    for (const view of this.paneViews) {
      const group = this.app.findSequence(view.pane.groupId);
      const list = frames(group);
      view.pane.index = Math.min(view.pane.index, list.length - 1);
      const item = list[view.pane.index];
      if (!item) continue;
      view.zoom.show(mediaURL(item));
      const caption = captionFor(item, group.orderKey, group.vary);
      view.value.textContent = caption;
      view.slider.max = list.length - 1;
      view.slider.value = view.pane.index;
      view.label.textContent = `${view.pane.index + 1} / ${list.length}`;
      labels.push(caption);
      if (this.paneViews.length === 1) {
        this.app.focus = item.id;
        this.app.inspector.render();
      }
    }
    this.frameLabel.textContent = this.state.linked ? `${this.state.index + 1} / ${longest}` : '';
    if (this.strip) {
      for (const button of this.strip.children) button.classList.toggle('current', Number(button.dataset.index) === this.state.panes[0]?.index);
      const current = this.strip.querySelector('.current');
      if (current) {
        const strip = this.strip.getBoundingClientRect(), rect = current.getBoundingClientRect();
        if (rect.left < strip.left || rect.right > strip.right) this.strip.scrollLeft += rect.left - strip.left - strip.width / 2;
      }
    }
  }

  step(delta) {
    if (this.state.linked) {
      this.state.index = Math.max(0, Math.min(this.length() - 1, this.state.index + delta));
      this.syncFromMaster();
    } else {
      for (const pane of this.state.panes) {
        const count = frames(this.app.findSequence(pane.groupId)).length;
        pane.index = Math.max(0, Math.min(count - 1, pane.index + delta));
      }
    }
    this.show();
  }

  jump(index) {
    this.state.index = Math.max(0, Math.min(this.length() - 1, index));
    if (this.state.linked) this.syncFromMaster();
    else for (const pane of this.state.panes) pane.index = index === 0 ? 0 : frames(this.app.findSequence(pane.groupId)).length - 1;
    this.show();
  }

  advance() {
    const last = this.length() - 1;
    let next = this.state.index + this.direction;
    if (next > last || next < 0) {
      if (this.state.mode === 'loop') next = next > last ? 0 : last;
      else if (this.state.mode === 'bounce') {
        this.direction = -this.direction;
        next = this.state.index + this.direction;
        this.updateButtons();
      } else {
        this.stop();
        return;
      }
    }
    this.state.index = Math.max(0, Math.min(last, next));
    if (this.state.linked) this.syncFromMaster();
    else for (const pane of this.state.panes) {
      const count = frames(this.app.findSequence(pane.groupId)).length;
      pane.index = (pane.index + this.direction + count) % count;
    }
    this.show();
  }

  toggle(direction) {
    if (this.timer && this.direction === direction) this.stop();
    else this.start(direction);
  }

  start(direction) {
    clearInterval(this.timer);
    this.direction = direction;
    this.timer = setInterval(() => this.advance(), 1000 / this.state.fps);
    this.updateButtons();
  }

  stop() {
    clearInterval(this.timer);
    this.timer = null;
    this.updateButtons();
  }

  updateButtons() {
    if (!this.playButton) return;
    const forward = this.timer && this.direction > 0, backward = this.timer && this.direction < 0;
    this.playButton.replaceChildren(icon(forward ? 'pause' : 'play'));
    this.playButton.title = forward ? 'Pause (Space)' : 'Play (Space)';
    this.reverseButton.replaceChildren(icon(backward ? 'pause' : 'reverse'));
  }

  onKey(event) {
    if (event.key === ' ') {
      event.preventDefault();
      this.toggle(this.direction || 1);
      return true;
    }
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      this.stop();
      this.step(event.key === 'ArrowRight' ? 1 : -1);
      return true;
    }
    if (event.key === 'Home' || event.key === 'End') {
      this.jump(event.key === 'Home' ? 0 : Infinity);
      return true;
    }
    return false;
  }

  orderedIds() {
    return this.state.panes.flatMap(pane => frames(this.app.findSequence(pane.groupId) || {items: []}).map(item => item.id));
  }
}
