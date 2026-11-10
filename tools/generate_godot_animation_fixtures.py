#!/usr/bin/env python3
"""Generate the tiny original Godot animated-sprite development-kit fixtures.

Writes a 24x8 RGBA sheet of three analytic 8x8 frames and the two matching
``schemaxis.aseprite.sheet/1`` metadata documents (authored 100/250/400 ms and a
changed 250/100/400 ms timing). ``--check`` fails when the committed files differ.
"""
import argparse
import json
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'examples/schemaxis'
BACKGROUND = (20, 40, 80, 255)
DOTS = ((1, 1, 2, 2, (250, 150, 30, 255)), (3, 3, 3, 2, (40, 200, 120, 255)), (5, 5, 2, 3, (230, 60, 90, 255)))
TAGS = [{'name': 'pulse', 'fromFrame': 1, 'toFrame': 3, 'direction': 'forward'},
        {'name': 'bounce', 'fromFrame': 1, 'toFrame': 2, 'direction': 'pingPong'}]


def frame_pixels(index):
    x, y, width, height, colour = DOTS[index]
    raw = bytearray()
    for row in range(8):
        for column in range(8):
            raw += bytes(colour if x <= column < x+width and y <= row < y+height else BACKGROUND)
    return bytes(raw)


def sheet_png():
    frames = [frame_pixels(i) for i in range(3)]
    rows = b''.join(b'\0'+b''.join(frame[row*32:(row+1)*32] for frame in frames) for row in range(8))
    def chunk(kind, body):
        return struct.pack('>I', len(body))+kind+body+struct.pack('>I', zlib.crc32(kind+body) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', 24, 8, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows, 9))+chunk(b'IEND', b''))


def metadata(durations):
    return (json.dumps({'version': 'schemaxis.aseprite.sheet/1', 'width': 24, 'height': 8,
                        'frames': [{'x': 8*i, 'y': 0, 'width': 8, 'height': 8, 'durationMS': d} for i, d in enumerate(durations)],
                        'tags': TAGS}, indent=2)+'\n').encode()


def expected():
    return {'sprite-animation-fixture.png': sheet_png(), 'sprite-animation-fixture.json': metadata((100, 250, 400)),
            'sprite-animation-fixture-variant.json': metadata((250, 100, 400))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='fail if committed fixtures differ')
    arguments = parser.parse_args()
    stale = []
    for name, data in expected().items():
        path = FOLDER/name
        if arguments.check:
            if not path.is_file() or path.read_bytes() != data:
                stale.append(name)
        else:
            path.write_bytes(data)
    if stale:
        print('Stale Godot animation fixtures: '+', '.join(stale)+'; run tools/generate_godot_animation_fixtures.py', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
