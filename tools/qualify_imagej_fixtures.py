#!/usr/bin/env python3
"""Write or check the original synthetic ImageJ particle calibration fixtures.

The images are analytic test targets, not experimental data. Every particle is a
union of axis-aligned pixel rectangles, so pixel counts, areas, centroids and
bounds are known in closed form. See examples/schemaxis/fixtures/imagej/README.md.
"""
import argparse
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'examples/schemaxis/fixtures/imagej'
WIDTH, HEIGHT, BACKGROUND = 64, 48, 20
# (x, y, width, height, raw 8-bit value); later rectangles overwrite earlier ones.
RECTANGLES = [
    (59, 0, 5, 4, 255),                     # edge block touching top/right borders: 20 px
    (4, 4, 10, 6, 200),                     # rectangle: 60 px
    (30, 6, 8, 8, 180),                     # square at the inclusive-threshold boundary: 64 px
    (20, 20, 1, 1, 150),                    # single pixel: 1 px
    (4, 24, 12, 4, 220), (4, 28, 4, 6, 220),  # L shape: 48 + 24 = 72 px
    (40, 26, 12, 12, 160),                  # ring outer square: 144 px ...
    (43, 29, 6, 6, BACKGROUND),             # ... minus 36 px hole = 108 px
    (45, 31, 2, 2, 230),                    # island inside the hole: 4 px
    (24, 36, 3, 3, 240), (27, 39, 3, 3, 240)]  # corner-touching squares: 8-connected 18 px


def raster():
    values = [BACKGROUND]*(WIDTH*HEIGHT)
    for x, y, w, h, value in RECTANGLES:
        for row in range(y, y+h):
            values[row*WIDTH+x:row*WIDTH+x+w] = [value]*w
    return values


def pgm8(values):
    return b'P5\n# Schemaxis synthetic particle calibration target\n%d %d\n255\n' % (WIDTH, HEIGHT) + bytes(values)


def tiff16(values):
    """Big-endian, uncompressed, two-strip 16-bit TIFF; intensities are 100x the 8-bit target."""
    data = struct.pack(f'>{len(values)}H', *(100*value for value in values))
    half = (HEIGHT//2)*WIDTH*2
    entries = [(256, 3, 1, WIDTH), (257, 3, 1, HEIGHT), (258, 3, 1, 16), (259, 3, 1, 1), (262, 3, 1, 1),
               (273, 4, 2, None), (277, 3, 1, 1), (278, 3, 1, HEIGHT//2), (279, 4, 2, None)]
    directory = 8
    extra = directory+2+12*len(entries)+4
    offsets, counts = extra, extra+8
    first = counts+8
    out = bytearray(b'MM\x00*' + struct.pack('>I', directory) + struct.pack('>H', len(entries)))
    for tag, kind, count, value in entries:
        out += struct.pack('>HHI', tag, kind, count)
        if tag == 273: out += struct.pack('>I', offsets)
        elif tag == 279: out += struct.pack('>I', counts)
        elif kind == 3: out += struct.pack('>HH', value, 0)
        else: out += struct.pack('>I', value)
    out += struct.pack('>I', 0)
    out += struct.pack('>II', first, first+half) + struct.pack('>II', half, len(data)-half)
    return bytes(out + data)


def fixtures():
    values = raster()
    return {'particles-8bit.pgm': pgm8(values), 'particles-16bit.tif': tiff16(values)}


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
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    if stale:
        print('stale ImageJ fixtures: '+', '.join(stale), file=sys.stderr)
        return 1
    print('ImageJ fixtures ' + ('match' if args.check else 'written') + ': ' + ', '.join(sorted(fixtures())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
