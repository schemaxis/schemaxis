// Copyright (C) 2026 David L F Gaden
// Image viewer parts: decoding, canvas drawing, pixel sampling and toolbar.

import {h} from '../lib/dom.mjs';
import {readTokens, separator, setPressed, spacer, toolButton} from './common.mjs';
import {CRISP_ZOOM, spriteFrame, visibleRegion, zoomLabel} from './image-math.mjs';

// ---- decoding --------------------------------------------------------------

async function blobFor(item) {
  if (typeof Blob !== 'undefined' && item.blob instanceof Blob) {
    return item.blob;
  }
  if (item.bytes) {
    return new Blob([item.bytes], {type: item.type || ''});
  }
  if (typeof item.src === 'string') {
    const response = await fetch(item.src);
    if (!response.ok) {
      throw Error(`Image request failed: ${response.status} ${response.statusText}`.trim());
    }
    return response.blob();
  }
  throw Error('Each image needs a src URL, a Blob or bytes.');
}

/** Hex SHA-256 of a blob, or null when Web Crypto is unavailable (non-secure context). */
export async function sha256Hex(blob) {
  if (!globalThis.crypto?.subtle) {
    return null;
  }
  const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function decodeOne(item) {
  const descriptor = typeof item === 'string' ? {src: item} : item;
  const blob = await blobFor(descriptor);
  let source;
  try {
    source = await createImageBitmap(blob, {premultiplyAlpha: 'none', colorSpaceConversion: 'none'});
  } catch {
    throw Error(`Cannot decode ${descriptor.name || descriptor.src || 'image'}: not a supported PNG or JPEG image.`);
  }
  const digest = typeof descriptor.digest === 'string' ? descriptor.digest : await sha256Hex(blob);
  const name = descriptor.name || descriptor.label
    || (typeof descriptor.src === 'string' ? descriptor.src.split(/[?#]/)[0].split('/').pop() : undefined);
  return {source, width: source.width, height: source.height, fileWidth: source.width, fileHeight: source.height,
    offsetX: 0, offsetY: 0, digest, name, revision: descriptor.revision, type: blob.type, size: blob.size,
    sprite: false};
}

/** Decode a descriptor into display frames (see image.mjs for accepted shapes). */
export async function decodeImages(descriptor) {
  if (Array.isArray(descriptor.frames)) {
    if (!descriptor.frames.length) {
      throw Error('The frame list is empty.');
    }
    return Promise.all(descriptor.frames.map(decodeOne));
  }
  const image = await decodeOne(descriptor);
  const sprite = descriptor.sprite;
  if (!sprite) {
    return [image];
  }
  if (!(Number.isInteger(sprite.width) && Number.isInteger(sprite.height) && sprite.width > 0 && sprite.height > 0)
    || sprite.width > image.width || sprite.height > image.height) {
    throw Error('Sprite frames need integer width and height within the sheet.');
  }
  const total = spriteFrame(image.width, image.height, sprite.width, sprite.height, 0).count;
  const count = Number.isInteger(sprite.count) ? Math.min(sprite.count, total) : total;
  return Array.from({length: count}, (_, i) => {
    const rect = spriteFrame(image.width, image.height, sprite.width, sprite.height, i);
    return {...image, width: rect.width, height: rect.height, offsetX: rect.x, offsetY: rect.y, sprite: true};
  });
}

// ---- drawing ---------------------------------------------------------------

const patterns = new WeakMap();

function checkerPattern(context, light, dark) {
  const key = `${light}|${dark}`;
  const cached = patterns.get(context);
  if (cached?.key === key) {
    return cached.pattern;
  }
  const tile = document.createElement('canvas');
  tile.width = 16;
  tile.height = 16;
  const tileContext = tile.getContext('2d');
  tileContext.fillStyle = light;
  tileContext.fillRect(0, 0, 16, 16);
  tileContext.fillStyle = dark;
  tileContext.fillRect(0, 0, 8, 8);
  tileContext.fillRect(8, 8, 8, 8);
  const pattern = context.createPattern(tile, 'repeat');
  patterns.set(context, {key, pattern});
  return pattern;
}

/** Draw the visible part of a frame with a transparency checkerboard and optional pixel grid. */
export function drawImageView(canvas, image, transform, {grid, highlight}) {
  const dpr = Math.min(window.devicePixelRatio || 1, 3);
  const cssWidth = canvas.clientWidth;
  const cssHeight = canvas.clientHeight;
  const width = Math.max(1, Math.round(cssWidth * dpr));
  const height = Math.max(1, Math.round(cssHeight * dpr));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const context = canvas.getContext('2d');
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.clearRect(0, 0, width, height);
  if (!image || !transform) {
    return;
  }
  const region = visibleRegion(transform, cssWidth, cssHeight, image.width, image.height);
  if (!region) {
    return;
  }
  const tokens = readTokens(canvas, ['surface', 'surface-3', 'text-3', 'border-strong', 'accent']);
  const scale = transform.scale;
  context.setTransform(dpr, 0, 0, dpr, 0, 0);
  const dx = transform.x + region.sx * scale;
  const dy = transform.y + region.sy * scale;
  const dw = region.sw * scale;
  const dh = region.sh * scale;
  context.fillStyle = checkerPattern(context, tokens.surface, tokens['surface-3']);
  context.fillRect(dx, dy, dw, dh);
  context.imageSmoothingEnabled = scale <= CRISP_ZOOM;
  context.imageSmoothingQuality = 'high';
  context.drawImage(image.source, image.offsetX + region.sx, image.offsetY + region.sy, region.sw, region.sh,
    dx, dy, dw, dh);
  if (grid) {
    drawGrid(context, transform, region, dpr, tokens['text-3']);
  }
  if (highlight && scale >= 4) {
    context.strokeStyle = tokens.accent;
    context.lineWidth = 2 / dpr;
    context.strokeRect(transform.x + highlight[0] * scale, transform.y + highlight[1] * scale, scale, scale);
  }
  context.strokeStyle = tokens['border-strong'];
  context.lineWidth = 1 / dpr;
  context.strokeRect(transform.x - 0.5 / dpr, transform.y - 0.5 / dpr, image.width * scale + 1 / dpr,
    image.height * scale + 1 / dpr);
}

function drawGrid(context, transform, region, dpr, colour) {
  const snap = (value) => (Math.round(value * dpr) + 0.5) / dpr;
  const scale = transform.scale;
  const top = transform.y + region.sy * scale;
  const bottom = top + region.sh * scale;
  const left = transform.x + region.sx * scale;
  const right = left + region.sw * scale;
  context.save();
  // Fade the grid in as pixels grow, so it never dominates the image.
  context.globalAlpha = 0.18 + 0.3 * Math.min(1, (scale - 8) / 24);
  context.strokeStyle = colour;
  context.lineWidth = 1 / dpr;
  context.beginPath();
  for (let x = region.sx; x <= region.sx + region.sw; x++) {
    const px = snap(transform.x + x * scale);
    context.moveTo(px, top);
    context.lineTo(px, bottom);
  }
  for (let y = region.sy; y <= region.sy + region.sh; y++) {
    const py = snap(transform.y + y * scale);
    context.moveTo(left, py);
    context.lineTo(right, py);
  }
  context.stroke();
  context.restore();
}

// ---- pixel sampling --------------------------------------------------------

const TILE = 64;

/** Reads RGBA values through a cached 64 × 64 tile, so hovering stays cheap on huge images. */
export class PixelSampler {
  constructor() {
    this.canvas = document.createElement('canvas');
    this.canvas.width = TILE;
    this.canvas.height = TILE;
    this.context = this.canvas.getContext('2d', {willReadFrequently: true});
    this.reset();
  }

  reset() {
    this.source = null;
    this.tileX = -1;
    this.tileY = -1;
    this.data = null;
  }

  sample(source, x, y) {
    const tileX = Math.floor(x / TILE) * TILE;
    const tileY = Math.floor(y / TILE) * TILE;
    if (source !== this.source || tileX !== this.tileX || tileY !== this.tileY) {
      const width = Math.min(TILE, source.width - tileX);
      const height = Math.min(TILE, source.height - tileY);
      if (width <= 0 || height <= 0) {
        return null;
      }
      this.context.clearRect(0, 0, TILE, TILE);
      this.context.drawImage(source, tileX, tileY, width, height, 0, 0, width, height);
      this.data = this.context.getImageData(0, 0, TILE, TILE).data;
      this.source = source;
      this.tileX = tileX;
      this.tileY = tileY;
    }
    const offset = ((y - tileY) * TILE + (x - tileX)) * 4;
    return [this.data[offset], this.data[offset + 1], this.data[offset + 2], this.data[offset + 3]];
  }
}

// ---- toolbar ---------------------------------------------------------------

export function buildImageToolbar(actions) {
  const fit = toolButton({icon: 'fit', title: 'Fit to view (F)', onClick: actions.fit});
  const actual = toolButton({icon: 'actual', title: 'Actual size, 100 % (1)', onClick: actions.actual});
  const zoomOut = toolButton({icon: 'zoom-out', title: 'Zoom out (−)', onClick: actions.zoomOut});
  const zoom = h('output', {class: 'vw-readout vw-zoom', 'aria-label': 'Zoom level'}, '—');
  const zoomIn = toolButton({icon: 'zoom-in', title: 'Zoom in (+)', onClick: actions.zoomIn});
  const grid = toolButton({icon: 'grid', title: 'Pixel grid above 800 % (G)', pressed: true,
    onClick: () => actions.grid(grid.getAttribute('aria-pressed') !== 'true')});
  const previous = toolButton({icon: 'prev', title: 'Previous frame (,)', onClick: actions.previous});
  const play = toolButton({icon: 'play', title: 'Play / pause (Space)', onClick: actions.play});
  const next = toolButton({icon: 'next', title: 'Next frame (.)', onClick: actions.next});
  const frameLabel = h('output', {class: 'vw-readout'}, '');
  const frames = h('span', {class: 'vw-group', role: 'group', 'aria-label': 'Frames'}, previous, play, next,
    frameLabel);
  const frameSeparator = separator();

  function update(state) {
    zoom.textContent = state.scale ? zoomLabel(state.scale) : '—';
    setPressed(grid, state.grid);
    grid.classList.toggle('vw-btn-dormant', state.grid && !state.gridActive);
    const multi = state.frameCount > 1;
    frames.hidden = !multi;
    frameSeparator.hidden = !multi;
    frameLabel.textContent = multi ? `${state.index + 1} / ${state.frameCount}` : '';
    play.replaceChildren(...toolButton({icon: state.playing ? 'pause' : 'play', title: ''}).childNodes);
    play.setAttribute('aria-label', state.playing ? 'Pause' : 'Play');
    for (const button of [fit, actual, zoomOut, zoomIn]) {
      button.disabled = !state.scale;
    }
  }

  return {
    element: [fit, actual, separator(), zoomOut, zoom, zoomIn, separator(), grid, frameSeparator, frames, spacer()],
    update,
    actions,
  };
}
