// Copyright (C) 2026 David L. F. Gaden
// Pointer dragging for floating surfaces: dialogs and the fill popover.

/** Let `handle` move `surface`. onMove(dx, dy) receives the offset from the start of the drag. */
export function dragSurface(handle, {onStart = () => {}, onMove}) {
  handle.classList.add('drag-handle');
  handle.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 || event.target.closest('button, input, select, textarea, a')) return;
    event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    onStart();
    handle.setPointerCapture(event.pointerId);
    const move = (next) => onMove(next.clientX - startX, next.clientY - startY);
    const stop = () => {
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', stop);
      handle.removeEventListener('pointercancel', stop);
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', stop);
    handle.addEventListener('pointercancel', stop);
  });
}

/** Keep a moved surface's title bar reachable inside the viewport. */
export function clampOffset(rect, dx, dy, margin = 48) {
  const x = Math.max(margin - rect.right, Math.min(window.innerWidth - margin - rect.left, dx));
  const y = Math.max(-rect.top, Math.min(window.innerHeight - margin - rect.top, dy));
  return [x, y];
}
