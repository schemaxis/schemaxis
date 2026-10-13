// Tiny PNG decoder (8-bit RGB/RGBA, non-interlaced) for screenshot comparisons in tests.

import {inflateSync} from 'node:zlib';

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) {
    return a;
  }
  return pb <= pc ? b : c;
}

/** Decode a PNG buffer to {width, height, gray: Float32Array} (0 = white, 1 = black). */
export function decodePng(buffer) {
  let offset = 8;
  let width = 0;
  let height = 0;
  let channels = 0;
  const chunks = [];
  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.toString('ascii', offset + 4, offset + 8);
    const data = buffer.subarray(offset + 8, offset + 8 + length);
    if (type === 'IHDR') {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      const colourType = data[9];
      if (data[8] !== 8 || data[12] !== 0 || (colourType !== 2 && colourType !== 6)) {
        throw new Error('Unsupported PNG format');
      }
      channels = colourType === 6 ? 4 : 3;
    } else if (type === 'IDAT') {
      chunks.push(data);
    }
    offset += 12 + length;
  }
  const raw = inflateSync(Buffer.concat(chunks));
  const stride = width * channels;
  const pixels = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y += 1) {
    const filter = raw[y * (stride + 1)];
    for (let x = 0; x < stride; x += 1) {
      const value = raw[y * (stride + 1) + 1 + x];
      const left = x >= channels ? pixels[y * stride + x - channels] : 0;
      const up = y > 0 ? pixels[(y - 1) * stride + x] : 0;
      const upLeft = x >= channels && y > 0 ? pixels[(y - 1) * stride + x - channels] : 0;
      let result = value;
      if (filter === 1) {
        result = value + left;
      } else if (filter === 2) {
        result = value + up;
      } else if (filter === 3) {
        result = value + ((left + up) >> 1);
      } else if (filter === 4) {
        result = value + paeth(left, up, upLeft);
      }
      pixels[y * stride + x] = result & 0xff;
    }
  }
  const gray = new Float32Array(width * height);
  for (let index = 0; index < width * height; index += 1) {
    const base = index * channels;
    const luminance = (pixels[base] * 0.299 + pixels[base + 1] * 0.587 + pixels[base + 2] * 0.114) / 255;
    gray[index] = 1 - luminance;
  }
  return {width, height, gray};
}

/** Best integer (dx, dy) shift of image b onto image a within ±range, by ink cross-correlation. */
export function bestShift(a, b, range = 4) {
  let best = {dx: 0, dy: 0, score: -Infinity};
  for (let dy = -range; dy <= range; dy += 1) {
    for (let dx = -range; dx <= range; dx += 1) {
      let score = 0;
      for (let y = range; y < a.height - range; y += 1) {
        for (let x = range; x < a.width - range; x += 1) {
          score += a.gray[y * a.width + x] * b.gray[(y + dy) * b.width + x + dx];
        }
      }
      if (score > best.score) {
        best = {dx, dy, score};
      }
    }
  }
  return best;
}

/** Mean absolute ink difference between two same-size images. */
export function meanDifference(a, b) {
  let total = 0;
  for (let index = 0; index < a.gray.length; index += 1) {
    total += Math.abs(a.gray[index] - b.gray[index]);
  }
  return total / a.gray.length;
}
