// Copyright (C) 2026 David L F Gaden
// Pointer, wheel and keyboard navigation for the 3D viewer canvas.
//
// host: {getCamera(), setCamera(camera), invalidate(), render(), aspect(), ndcAt(x, y) → {nx, ny},
//        click(x, y), hover(x, y), leave(), fit(), view(name), toggleProjection(), step(direction),
//        referenceSelected(), clearSelection()}

import {orbitCamera, panCamera, walkStep, zoomCamera} from './camera.mjs';

const WALK_KEYS = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE']);
const VIEW_KEYS = {'0': 'iso', '1': '+x', '2': '-x', '3': '+y', '4': '-y', '5': '+z', '6': '-z'};
const ARROWS = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]};
const ORBIT_RATE = 0.008;
const DRAG_THRESHOLD = 4;

/** Attach navigation listeners; returns {detach()}. */
export function attachNavigation(canvas, host) {
  const keys = new Set();
  let drag = null;
  let walkFrame = 0;
  const listeners = [];
  const listen = (target, name, handler, options) => {
    target.addEventListener(name, handler, options);
    listeners.push(() => target.removeEventListener(name, handler, options));
  };
  const update = (change) => {
    host.setCamera(change(host.getCamera()));
    host.invalidate();
  };

  listen(canvas, 'contextmenu', (event) => event.preventDefault());
  listen(canvas, 'pointerdown', (event) => {
    if (drag || ![0, 1, 2].includes(event.button)) {
      return;
    }
    // Pointer focus should not draw the keyboard focus ring.
    canvas.classList.add('vw-pointer-focus');
    canvas.focus({preventScroll: true});
    canvas.setPointerCapture(event.pointerId);
    drag = {id: event.pointerId, x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY,
      pan: event.shiftKey || event.button !== 0, moved: false};
  });
  listen(canvas, 'pointermove', (event) => {
    if (!drag) {
      host.hover(event.clientX, event.clientY);
      return;
    }
    if (drag.id !== event.pointerId) {
      return;
    }
    if (Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) > DRAG_THRESHOLD) {
      drag.moved = true;
    }
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    drag.x = event.clientX;
    drag.y = event.clientY;
    if (drag.moved) {
      const pan = drag.pan;
      update((camera) => (pan
        ? panCamera(camera, dx, dy, canvas.clientHeight)
        : orbitCamera(camera, -dx * ORBIT_RATE, dy * ORBIT_RATE)));
    }
  });
  listen(canvas, 'pointerup', (event) => {
    const current = drag;
    if (!current || current.id !== event.pointerId) {
      return;
    }
    drag = null;
    canvas.releasePointerCapture(event.pointerId);
    if (!current.moved && !current.pan) {
      host.click(event.clientX, event.clientY);
    }
  });
  for (const name of ['pointercancel', 'lostpointercapture']) {
    listen(canvas, name, () => {
      drag = null;
    });
  }
  listen(canvas, 'pointerleave', () => {
    if (!drag) {
      host.leave();
    }
  });
  listen(canvas, 'wheel', (event) => {
    event.preventDefault();
    const delta = Math.max(-200, Math.min(200, event.deltaY * (event.deltaMode === 1 ? 16 : 1)));
    const {nx, ny} = host.ndcAt(event.clientX, event.clientY);
    update((camera) => zoomCamera(camera, Math.exp(delta * 0.0015), nx, ny, host.aspect()));
  }, {passive: false});

  listen(canvas, 'keydown', (event) => {
    canvas.classList.remove('vw-pointer-focus');
    if (event.ctrlKey || event.metaKey || event.altKey) {
      return;
    }
    if (host.getCamera().navigation === 'walk' && WALK_KEYS.has(event.code)) {
      event.preventDefault();
      keys.add(event.code);
      startWalk();
      return;
    }
    if (handleKey(event)) {
      event.preventDefault();
      host.invalidate();
    }
  });
  listen(canvas, 'keyup', (event) => keys.delete(event.code));
  listen(canvas, 'blur', () => keys.clear());
  listen(document, 'visibilitychange', () => {
    if (document.hidden) {
      keys.clear();
    }
  });

  function handleKey(event) {
    const key = event.key;
    if (ARROWS[key]) {
      const [x, y] = ARROWS[key];
      host.setCamera(event.shiftKey
        ? panCamera(host.getCamera(), x * 24, y * 24, canvas.clientHeight)
        : orbitCamera(host.getCamera(), x * 0.12, y * 0.12));
    } else if (key === '+' || key === '=' || key === '-') {
      host.setCamera(zoomCamera(host.getCamera(), key === '-' ? 1.15 : 1 / 1.15, 0, 0, host.aspect()));
    } else if (key === 'f' || key === 'F') {
      host.fit();
    } else if (VIEW_KEYS[key]) {
      host.view(VIEW_KEYS[key]);
    } else if (key === 'p' || key === 'P') {
      host.toggleProjection();
    } else if (key === ']' || key === '[') {
      host.step(key === ']' ? 1 : -1);
    } else if (key === 'Enter') {
      host.referenceSelected();
    } else if (key === 'Escape') {
      host.clearSelection();
    } else {
      return false;
    }
    return true;
  }

  function startWalk() {
    if (walkFrame) {
      return;
    }
    let last = performance.now();
    const step = (now) => {
      walkFrame = 0;
      if (!keys.size || host.getCamera().navigation !== 'walk') {
        return;
      }
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      host.setCamera(walkStep(host.getCamera(), keys, dt));
      host.render();
      walkFrame = requestAnimationFrame(step);
    };
    walkFrame = requestAnimationFrame(step);
  }

  return {
    clearKeys: () => keys.clear(),
    detach() {
      cancelAnimationFrame(walkFrame);
      for (const remove of listeners) {
        remove();
      }
    },
  };
}
