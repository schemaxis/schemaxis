#!/usr/bin/env python3
"""Write or check the original analytic ImageJ region-series fixtures.

The ramp planes are intensity ramps, value = base + sx*x + sy*y + st*frame, on a small
12x8 grid, so every rectangle count, sum, minimum and maximum has a closed form.
The fractional planes (9x6, frac8-*/frac16-*) add a cross term and a modulus so that
rectangle sums are not multiples of the pixel count and means are non-terminating
fractions such as 1/3. The images are test targets, not experimental data. See
examples/schemaxis/fixtures/imagej/README.md.
"""
import argparse
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'examples/schemaxis/fixtures/imagej/series'
WIDTH, HEIGHT = 12, 8
EIGHT = (10, 8, 12, 20)          # base, x step, y step, frame step (max 242)
SIXTEEN = (1000, 900, 1700, 3000)  # (max 25800)
FRAMES = 4
FRACTION_WIDTH, FRACTION_HEIGHT, FRACTION_FRAMES = 9, 6, 3
FRACTION8 = (29, 53, 17, 11, 256)       # value = (a*x + b*y + c*frame + d*x*y) mod m
FRACTION16 = (4099, 7919, 1013, 977, 65536)


def fraction(parameters, frame):
    a, b, c, d, modulus = parameters
    return [(a*x+b*y+c*frame+d*x*y) % modulus for y in range(FRACTION_HEIGHT) for x in range(FRACTION_WIDTH)]


def ramp(parameters, frame):
    base, sx, sy, st = parameters
    return [base+sx*x+sy*y+st*frame for y in range(HEIGHT) for x in range(WIDTH)]


def pgm8(values, frame, width=WIDTH, height=HEIGHT, label='analytic ramp'):
    return b'P5\n# Schemaxis %s, frame %d\n%d %d\n255\n' % (label.encode(), frame, width, height)+bytes(values)


def tiff16(values, width=WIDTH, height=HEIGHT):
    """Little-endian, one-strip, uncompressed 16-bit unsigned TIFF."""
    data = struct.pack(f'<{len(values)}H', *values)
    entries = [(256, 3, 1, width), (257, 3, 1, height), (258, 3, 1, 16), (259, 3, 1, 1), (262, 3, 1, 1),
               (273, 4, 1, None), (277, 3, 1, 1), (278, 3, 1, height), (279, 4, 1, len(data))]
    start = 8+2+12*len(entries)+4
    out = bytearray(b'II*\x00'+struct.pack('<IH', 8, len(entries)))
    for tag, kind, count, value in entries:
        out += struct.pack('<HHI', tag, kind, count)
        out += struct.pack('<I', start) if tag == 273 else struct.pack('<HH', value, 0) if kind == 3 else struct.pack('<I', value)
    return bytes(out+struct.pack('<I', 0)+data)


def fixtures():
    files = {f'ramp8-t{frame}.pgm': pgm8(ramp(EIGHT, frame), frame) for frame in range(FRAMES)}
    files.update({f'ramp16-t{frame}.tif': tiff16(ramp(SIXTEEN, frame)) for frame in range(3)})
    files.update({f'frac8-t{frame}.pgm': pgm8(fraction(FRACTION8, frame), frame, FRACTION_WIDTH, FRACTION_HEIGHT, 'fractional-mean plane')
                  for frame in range(FRACTION_FRAMES)})
    files.update({f'frac16-t{frame}.tif': tiff16(fraction(FRACTION16, frame), FRACTION_WIDTH, FRACTION_HEIGHT) for frame in range(FRACTION_FRAMES)})
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='fail if committed fixtures differ')
    args = parser.parse_args()
    stale = []
    for name, data in fixtures().items():
        path = FOLDER/name
        if args.check:
            if not path.is_file() or path.read_bytes() != data: stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
    if stale:
        print('stale ImageJ series fixtures: '+', '.join(stale), file=sys.stderr); return 1
    print('ImageJ series fixtures '+('match' if args.check else 'written')+': '+', '.join(sorted(fixtures())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
