// Image view arithmetic. A view transform {scale, x, y} maps image pixel
// coordinates to viewport CSS pixels: screen = (x + px * scale, y + py * scale).
// Pixel coordinates are integers with the origin at the top-left.

export const MIN_ZOOM = 1 / 64;
export const MAX_ZOOM = 256;
export const CRISP_ZOOM = 2;
export const GRID_ZOOM = 8;
const ZOOM_STEPS = [1 / 64, 1 / 32, 1 / 16, 1 / 8, 1 / 6, 1 / 4, 1 / 3, 1 / 2, 2 / 3, 1, 1.5, 2, 3, 4, 6, 8, 12, 16,
  24, 32, 48, 64, 96, 128, 192, 256];

const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

/** Match object-fit: contain / centre (ported from the console). Bounds are CSS pixels. */
export function containedImageRect(bounds, width, height) {
  const valid = Number.isSafeInteger(width) && Number.isSafeInteger(height) && width >= 1 && height >= 1
    && bounds.width > 0 && bounds.height > 0;
  if (!valid) {
    return null;
  }
  const scale = Math.min(bounds.width / width, bounds.height / height);
  const drawnWidth = width * scale;
  const drawnHeight = height * scale;
  return {
    left: bounds.left + (bounds.width - drawnWidth) / 2,
    top: bounds.top + (bounds.height - drawnHeight) / 2,
    width: drawnWidth,
    height: drawnHeight,
    scale,
  };
}

/** Integer image pixel under a client point for a contained image, or null in the margins. */
export function imagePixelAt(clientX, clientY, bounds, width, height) {
  const rect = containedImageRect(bounds, width, height);
  if (!rect || !Number.isFinite(clientX) || !Number.isFinite(clientY)) {
    return null;
  }
  const transform = {scale: rect.scale, x: rect.left, y: rect.top};
  return pixelAt(transform, clientX, clientY, width, height);
}

/** Transform that fits the image inside the viewport with a margin, centred. */
export function fitTransform(viewWidth, viewHeight, width, height, margin = 16) {
  const availableWidth = Math.max(1, viewWidth - 2 * margin);
  const availableHeight = Math.max(1, viewHeight - 2 * margin);
  const scale = clamp(Math.min(availableWidth / width, availableHeight / height), MIN_ZOOM, MAX_ZOOM);
  return centredTransform(viewWidth, viewHeight, width, height, scale);
}

/** Transform at a given scale, centred in the viewport. */
export function centredTransform(viewWidth, viewHeight, width, height, scale) {
  return {scale, x: (viewWidth - width * scale) / 2, y: (viewHeight - height * scale) / 2};
}

/** Zoom by factor keeping the image point under (cx, cy) fixed on screen. */
export function zoomAt(transform, factor, cx, cy, min = MIN_ZOOM, max = MAX_ZOOM) {
  const scale = clamp(transform.scale * factor, min, max);
  const imageX = (cx - transform.x) / transform.scale;
  const imageY = (cy - transform.y) / transform.scale;
  return {scale, x: cx - imageX * scale, y: cy - imageY * scale};
}

/** Next zoom step above (direction 1) or below (-1) the current scale. */
export function steppedZoom(scale, direction) {
  if (direction > 0) {
    return ZOOM_STEPS.find((step) => step > scale * 1.0001) ?? MAX_ZOOM;
  }
  return [...ZOOM_STEPS].reverse().find((step) => step < scale / 1.0001) ?? MIN_ZOOM;
}

/** Integer pixel [x, y] under a viewport point, or null outside the image. */
export function pixelAt(transform, px, py, width, height) {
  const x = Math.floor((px - transform.x) / transform.scale);
  const y = Math.floor((py - transform.y) / transform.scale);
  if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0 || x >= width || y >= height) {
    return null;
  }
  return [x, y];
}

/** Keep at least `keep` CSS pixels of the image inside the viewport. */
export function clampPan(transform, viewWidth, viewHeight, width, height, keep = 48) {
  const drawnWidth = width * transform.scale;
  const drawnHeight = height * transform.scale;
  const keepX = Math.min(keep, drawnWidth);
  const keepY = Math.min(keep, drawnHeight);
  return {
    scale: transform.scale,
    x: clamp(transform.x, keepX - drawnWidth, viewWidth - keepX),
    y: clamp(transform.y, keepY - drawnHeight, viewHeight - keepY),
  };
}

/**
 * Integer source rectangle of the image that is visible in the viewport
 * ({sx, sy, sw, sh}), or null when nothing is visible. Drawing only this
 * region keeps very large images and extreme zooms fast and precise.
 */
export function visibleRegion(transform, viewWidth, viewHeight, width, height) {
  const sx = clamp(Math.floor(-transform.x / transform.scale), 0, width);
  const sy = clamp(Math.floor(-transform.y / transform.scale), 0, height);
  const ex = clamp(Math.ceil((viewWidth - transform.x) / transform.scale), 0, width);
  const ey = clamp(Math.ceil((viewHeight - transform.y) / transform.scale), 0, height);
  if (ex <= sx || ey <= sy) {
    return null;
  }
  return {sx, sy, sw: ex - sx, sh: ey - sy};
}

/** Sprite-sheet frame rectangle: frames run left to right, then top to bottom. */
export function spriteFrame(sheetWidth, sheetHeight, frameWidth, frameHeight, index) {
  const columns = Math.max(1, Math.floor(sheetWidth / frameWidth));
  const rows = Math.max(1, Math.floor(sheetHeight / frameHeight));
  const count = columns * rows;
  const frame = ((index % count) + count) % count;
  return {x: (frame % columns) * frameWidth, y: Math.floor(frame / columns) * frameHeight, width: frameWidth,
    height: frameHeight, count};
}

/** "12.5%", "100%", "1,600%". */
export function zoomLabel(scale) {
  const percent = scale * 100;
  const digits = percent < 10 ? 1 : 0;
  return `${Number(percent.toFixed(digits)).toLocaleString('en-CA')}%`;
}
