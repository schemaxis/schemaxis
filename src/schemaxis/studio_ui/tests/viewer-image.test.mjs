import assert from 'node:assert/strict';
import test from 'node:test';
import {
  MAX_ZOOM, MIN_ZOOM, clampPan, containedImageRect, fitTransform, imagePixelAt, pixelAt, spriteFrame,
  steppedZoom, visibleRegion, zoomAt,
} from '../viewers/image-math.mjs';

test('contained images preserve native pixel identity and reject letterbox margins', () => {
  const bounds = {left: 10, top: 20, width: 400, height: 300};
  assert.deepEqual(containedImageRect(bounds, 200, 100), {left: 10, top: 70, width: 400, height: 200, scale: 2});
  assert.deepEqual(imagePixelAt(10, 70, bounds, 200, 100), [0, 0]);
  assert.deepEqual(imagePixelAt(210, 170, bounds, 200, 100), [100, 50]);
  assert.deepEqual(imagePixelAt(409.99, 269.99, bounds, 200, 100), [199, 99]);
  for (const [x, y] of [[10, 69.9], [210, 20], [210, 270], [410, 100], [9.9, 100]]) {
    assert.equal(imagePixelAt(x, y, bounds, 200, 100), null);
  }
  const portrait = {left: 0, top: 0, width: 400, height: 200};
  assert.deepEqual(imagePixelAt(200, 100, portrait, 100, 200), [50, 100]);
  assert.equal(imagePixelAt(100, 100, portrait, 100, 200), null);
  assert.deepEqual(imagePixelAt(200, 100, portrait, 4000, 2000), [2000, 1000]);
  assert.equal(imagePixelAt(NaN, 0, portrait, 4000, 2000), null);
  assert.equal(imagePixelAt(0, 0, portrait, 0, 10), null);
});

test('cursor zoom preserves fractional image coordinates and respects zoom limits', () => {
  const transform = {scale: 1.5, x: -80, y: 50};
  for (const factor of [0.00001, 0.5, 3, 100000]) {
    const zoomed = zoomAt(transform, factor, 175, 230);
    assert.ok(zoomed.scale >= MIN_ZOOM && zoomed.scale <= MAX_ZOOM);
    assert.equal((175 - zoomed.x) / zoomed.scale, (175 - transform.x) / transform.scale);
    assert.equal((230 - zoomed.y) / zoomed.scale, (230 - transform.y) / transform.scale);
  }
  assert.equal(steppedZoom(1, 1), 1.5);
  assert.equal(steppedZoom(1, -1), 2 / 3);
  assert.equal(steppedZoom(MAX_ZOOM, 1), MAX_ZOOM);
  assert.equal(steppedZoom(MIN_ZOOM, -1), MIN_ZOOM);
});

test('8k fit, constrained pan and visible source rectangles avoid off-image pixels', () => {
  const fit = fitTransform(832, 432, 8000, 4000);
  assert.deepEqual(fit, {scale: 0.1, x: 16, y: 16});
  assert.deepEqual(pixelAt(fit, 16, 16, 8000, 4000), [0, 0]);
  assert.deepEqual(pixelAt(fit, 815.99, 415.99, 8000, 4000), [7999, 3999]);
  assert.equal(pixelAt(fit, 816, 416, 8000, 4000), null);
  assert.deepEqual(visibleRegion({scale: 8, x: -400, y: -800}, 800, 400, 8000, 4000),
    {sx: 50, sy: 100, sw: 100, sh: 50});
  assert.equal(visibleRegion({scale: 1, x: 1000, y: 1000}, 800, 400, 80, 40), null);
  assert.deepEqual(clampPan({scale: 2, x: -10000, y: 10000}, 800, 400, 8000, 4000),
    {scale: 2, x: -10000, y: 352});
});

test('sprite frames wrap in both directions and retain source-image coordinates', () => {
  assert.deepEqual(spriteFrame(160, 100, 80, 50, 0), {x: 0, y: 0, width: 80, height: 50, count: 4});
  assert.deepEqual(spriteFrame(160, 100, 80, 50, 3), {x: 80, y: 50, width: 80, height: 50, count: 4});
  assert.deepEqual(spriteFrame(160, 100, 80, 50, -1), spriteFrame(160, 100, 80, 50, 3));
  assert.deepEqual(spriteFrame(160, 100, 80, 50, 4), spriteFrame(160, 100, 80, 50, 0));
});
