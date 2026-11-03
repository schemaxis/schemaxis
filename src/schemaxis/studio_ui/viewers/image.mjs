// Copyright (C) 2026 David L F Gaden
// Image Viewer: PNG/JPEG with zoom to cursor, pan, fit, 100 %, crisp pixels,
// pixel grid, cursor pixel + RGBA read-out, pixel picks and frame stepping.
//
//   const viewer = createImageViewer(container);
//   viewer.load({src | blob | bytes, digest?, name?, revision?, sprite?: {width, height}}
//               | {frames: [{src | blob | bytes, digest?, label?}], fps?} | url string | Promise);
//
// Pick payload: {type: 'pixel', x, y, width, height, digest, frame?, name?, revision?}
// x, y are integer pixels of the displayed file (origin top-left); width/height are
// that file's dimensions. digest is the supplied or computed SHA-256, else null.

import {h} from '../lib/dom.mjs';
import {createEmitter, createFrame, isTyping, watchTheme} from './common.mjs';
import {
  CRISP_ZOOM, centredTransform, clampPan, fitTransform, GRID_ZOOM, pixelAt, steppedZoom, zoomAt,
} from './image-math.mjs';
import {buildImageToolbar, decodeImages, drawImageView, PixelSampler} from './image-parts.mjs';

export function createImageViewer(container, options = {}) {
  const events = createEmitter();
  const frame = createFrame(container, {kind: 'image', label: options.label || 'Image Viewer',
    emptyMessage: options.emptyMessage || 'No image loaded'});
  const canvas = h('canvas', {class: 'vw-image-canvas', tabindex: '0', 'aria-label': 'Image. Wheel or plus/minus '
    + 'zooms, drag or arrow keys pan, F fits, 1 shows actual size, G toggles the pixel grid, comma and period step '
    + 'frames, Enter references the pixel under the crosshair.'});
  const crosshair = h('div', {class: 'vw-crosshair', 'aria-hidden': 'true'});
  frame.body.append(canvas, crosshair);
  const statusLeft = h('span', {class: 'vw-status-main vw-mono'}, '');
  const statusRight = h('span', {class: 'vw-status-meta'});
  frame.status.append(statusLeft, statusRight);

  const sampler = new PixelSampler();
  let frames = [];
  let index = 0;
  let transform = null;
  let grid = options.grid !== false;
  let playing = null;
  let fps = 8;
  let loadToken = 0;
  let drawRequest = 0;
  let drag = null;
  let fitted = false;
  let hoverPixel = null;

  const toolbar = buildImageToolbar({
    fit: () => fit(),
    actual: () => zoomTo(1),
    zoomIn: () => zoomBy(steppedZoom(transform?.scale ?? 1, 1) / (transform?.scale ?? 1)),
    zoomOut: () => zoomBy(steppedZoom(transform?.scale ?? 1, -1) / (transform?.scale ?? 1)),
    grid: (on) => setGrid(on),
    previous: () => showFrame(index - 1),
    next: () => showFrame(index + 1),
    play: () => (playing ? pause() : play()),
  });
  frame.toolbar.append(...toolbar.element);

  const current = () => frames[index] || null;
  const viewSize = () => ({width: canvas.clientWidth, height: canvas.clientHeight});

  function invalidate() {
    if (!drawRequest) {
      drawRequest = requestAnimationFrame(draw);
    }
  }

  function draw() {
    drawRequest = 0;
    const image = current();
    drawImageView(canvas, image, transform, {grid: grid && transform?.scale >= GRID_ZOOM, highlight: hoverPixel});
    toolbar.update({
      scale: transform?.scale ?? null,
      grid,
      gridActive: Boolean(transform && transform.scale >= GRID_ZOOM),
      frameCount: frames.length,
      index,
      playing: Boolean(playing),
    });
    canvas.classList.toggle('vw-crisp', Boolean(transform && transform.scale > CRISP_ZOOM));
  }

  function setTransform(next) {
    const image = current();
    if (!image) {
      return;
    }
    const {width, height} = viewSize();
    transform = clampPan(next, width, height, image.width, image.height);
    invalidate();
  }

  function fit() {
    const image = current();
    if (!image) {
      return;
    }
    const {width, height} = viewSize();
    transform = fitTransform(width, height, image.width, image.height);
    invalidate();
  }

  function zoomTo(scale) {
    const image = current();
    if (!image) {
      return;
    }
    const {width, height} = viewSize();
    const centre = transform ? zoomAt(transform, scale / transform.scale, width / 2, height / 2)
      : centredTransform(width, height, image.width, image.height, scale);
    setTransform(centre);
  }

  function zoomBy(factor, cx, cy) {
    if (!transform) {
      return;
    }
    const {width, height} = viewSize();
    setTransform(zoomAt(transform, factor, cx ?? width / 2, cy ?? height / 2));
  }

  function setGrid(on) {
    grid = Boolean(on);
    invalidate();
  }

  // ---- pixels and picks --------------------------------------------------

  function localPoint(event) {
    const rect = canvas.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  }

  function pixelUnder(x, y) {
    const image = current();
    return image && transform ? pixelAt(transform, x, y, image.width, image.height) : null;
  }

  function pickPayload(pixel) {
    const image = current();
    const payload = {type: 'pixel', x: pixel[0] + image.offsetX, y: pixel[1] + image.offsetY,
      width: image.fileWidth, height: image.fileHeight, digest: image.digest};
    if (frames.length > 1) {
      payload.frame = index;
    }
    if (image.name) {
      payload.name = image.name;
    }
    if (image.revision !== undefined) {
      payload.revision = image.revision;
    }
    return payload;
  }

  function readout(pixel) {
    if (String(pixel) !== String(hoverPixel)) {
      hoverPixel = pixel;
      invalidate();
    }
    if (!pixel) {
      statusLeft.textContent = '';
      return;
    }
    const image = current();
    const rgba = sampler.sample(image.source, pixel[0] + image.offsetX, pixel[1] + image.offsetY);
    const colour = rgba ? `  RGBA ${rgba.map((v) => String(v).padStart(3, ' ')).join(' ')}` : '';
    statusLeft.textContent = `x ${pixel[0] + image.offsetX}  y ${pixel[1] + image.offsetY}${colour}`;
  }

  function emitPick(pixel) {
    if (!pixel) {
      return;
    }
    const payload = pickPayload(pixel);
    events.emit('pick', payload);
  }

  // ---- input ---------------------------------------------------------------

  canvas.addEventListener('pointerdown', (event) => {
    if (!current() || ![0, 1].includes(event.button)) {
      return;
    }
    canvas.classList.add('vw-pointer-focus');
    canvas.focus({preventScroll: true});
    canvas.setPointerCapture(event.pointerId);
    const [x, y] = localPoint(event);
    drag = {id: event.pointerId, x, y, startX: x, startY: y, moved: false, button: event.button};
  });
  canvas.addEventListener('pointermove', (event) => {
    const [x, y] = localPoint(event);
    if (drag && drag.id === event.pointerId) {
      if (Math.hypot(x - drag.startX, y - drag.startY) > 3) {
        drag.moved = true;
        canvas.classList.add('vw-panning');
      }
      if (drag.moved) {
        setTransform({...transform, x: transform.x + x - drag.x, y: transform.y + y - drag.y});
      }
      drag.x = x;
      drag.y = y;
    }
    readout(pixelUnder(x, y));
  });
  canvas.addEventListener('pointerup', (event) => {
    if (!drag || drag.id !== event.pointerId) {
      return;
    }
    const finished = drag;
    drag = null;
    canvas.classList.remove('vw-panning');
    canvas.releasePointerCapture(event.pointerId);
    if (!finished.moved && finished.button === 0) {
      emitPick(pixelUnder(...localPoint(event)));
    }
  });
  canvas.addEventListener('pointercancel', () => {
    drag = null;
  });
  canvas.addEventListener('pointerleave', () => {
    if (!drag) {
      readout(null);
    }
  });
  canvas.addEventListener('wheel', (event) => {
    if (!transform) {
      return;
    }
    event.preventDefault();
    const delta = Math.max(-300, Math.min(300, event.deltaY * (event.deltaMode === 1 ? 16 : 1)));
    const [x, y] = localPoint(event);
    zoomBy(Math.exp(-delta * 0.0025), x, y);
    readout(pixelUnder(x, y));
  }, {passive: false});
  canvas.addEventListener('keydown', (event) => {
    canvas.classList.remove('vw-pointer-focus');
    if (isTyping(event) || event.ctrlKey || event.metaKey || event.altKey || !current()) {
      return;
    }
    const step = event.shiftKey ? 120 : 30;
    const pans = {ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step]};
    const key = event.key;
    if (pans[key]) {
      setTransform({...transform, x: transform.x + pans[key][0], y: transform.y + pans[key][1]});
    } else if (key === '+' || key === '=') {
      toolbar.actions.zoomIn();
    } else if (key === '-') {
      toolbar.actions.zoomOut();
    } else if (key === 'f' || key === 'F' || key === '0') {
      fit();
    } else if (key === '1') {
      zoomTo(1);
    } else if (key === 'g' || key === 'G') {
      setGrid(!grid);
    } else if (key === ',' || key === '.') {
      showFrame(index + (key === '.' ? 1 : -1));
    } else if (key === ' ' && frames.length > 1) {
      playing ? pause() : play();
    } else if (key === 'Enter') {
      const {width, height} = viewSize();
      emitPick(pixelUnder(width / 2, height / 2));
    } else {
      return;
    }
    event.preventDefault();
  });

  const resizeObserver = new ResizeObserver(() => resize());
  resizeObserver.observe(frame.body);
  const stopTheme = watchTheme(() => invalidate());

  // ---- frames ----------------------------------------------------------------

  function showFrame(next) {
    if (frames.length < 2) {
      return;
    }
    const previous = current();
    index = ((next % frames.length) + frames.length) % frames.length;
    const image = current();
    if (!transform || previous.width !== image.width || previous.height !== image.height) {
      fit();
    }
    updateMeta();
    invalidate();
    events.emit('frame', {index, count: frames.length});
  }

  function play() {
    if (frames.length < 2 || playing) {
      return;
    }
    playing = setInterval(() => showFrame(index + 1), 1000 / fps);
    invalidate();
  }

  function pause() {
    clearInterval(playing);
    playing = null;
    invalidate();
  }

  function updateMeta() {
    const image = current();
    if (!image) {
      statusRight.textContent = '';
      return;
    }
    const parts = [`${image.fileWidth.toLocaleString('en-CA')} × ${image.fileHeight.toLocaleString('en-CA')} px`];
    if (image.sprite) {
      parts.push(`frame ${image.width} × ${image.height}`);
    }
    if (image.type) {
      parts.push(image.type.replace('image/', '').toUpperCase());
    }
    if (image.size) {
      parts.push(`${(image.size / 1024).toFixed(image.size < 10240 ? 1 : 0)} KiB`);
    }
    parts.push(image.digest ? `sha256 ${image.digest.slice(0, 12)}…` : 'no digest');
    statusRight.textContent = parts.join(' · ');
  }

  // ---- public API ------------------------------------------------------------

  async function load(input) {
    const token = ++loadToken;
    pause();
    frame.setState('loading', 'Decoding image…');
    let decoded;
    try {
      const data = await input;
      const descriptor = typeof data === 'string' ? {src: data} : data;
      if (!descriptor || typeof descriptor !== 'object') {
        throw Error('Image data must be a URL, Blob, bytes or {frames: [...]}.');
      }
      fps = Number.isFinite(descriptor.fps) && descriptor.fps > 0 ? descriptor.fps : 8;
      decoded = await decodeImages(descriptor);
    } catch (error) {
      if (token === loadToken) {
        showError(error?.message || String(error));
      }
      return null;
    }
    if (token !== loadToken) {
      return null;
    }
    for (const old of frames) {
      old.source.close?.();
    }
    frames = decoded;
    index = 0;
    sampler.reset();
    fitted = false;
    frame.setState('ready');
    updateMeta();
    resize();
    const image = current();
    const summary = {width: image.fileWidth, height: image.fileHeight, frames: frames.length, digest: image.digest};
    events.emit('load', summary);
    return summary;
  }

  function resize() {
    const image = current();
    if (image && !fitted && canvas.clientWidth > 0) {
      fitted = true;
      fit();
    } else if (transform && image) {
      setTransform(transform);
    }
    invalidate();
  }

  function clear() {
    loadToken++;
    pause();
    for (const old of frames) {
      old.source.close?.();
    }
    frames = [];
    transform = null;
    statusLeft.textContent = '';
    statusRight.textContent = '';
    frame.setState('empty');
    invalidate();
  }

  function showError(message) {
    frame.setState('error', message);
    events.emit('error', {message});
  }

  function destroy() {
    clear();
    cancelAnimationFrame(drawRequest);
    resizeObserver.disconnect();
    stopTheme();
    frame.root.remove();
    events.clear();
  }

  return {
    element: frame.root,
    canvas,
    load,
    clear,
    resize,
    destroy,
    showError,
    setLoading: (message) => frame.setState('loading', message),
    on: events.on,
    fit,
    zoomTo,
    zoomAt: (factor, clientX, clientY) => {
      const rect = canvas.getBoundingClientRect();
      zoomBy(factor, clientX - rect.left, clientY - rect.top);
    },
    getTransform: () => (transform ? {...transform} : null),
    setTransform: (next) => setTransform({...transform, ...next}),
    setGrid,
    showFrame,
    play,
    pause,
    get frameIndex() {
      return index;
    },
    /** Integer pixel under a client point (no event), e.g. for tests and tooltips. */
    pixelAtClient: (clientX, clientY) => {
      const rect = canvas.getBoundingClientRect();
      const pixel = pixelUnder(clientX - rect.left, clientY - rect.top);
      return pixel ? pickPayload(pixel) : null;
    },
    setTheme: () => invalidate(),
  };
}
