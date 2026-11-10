#!/usr/bin/env python3
"""One-time developer authoring of the committed Tesseract text fixtures (needs Pillow; not used by tests or qualification).

Usage: author_tesseract_fixtures.py FONT.ttf OUTPUT-DIRECTORY

The committed PNGs under examples/schemaxis/fixtures/tesseract are the product; qualification reads those bytes and measures
their ink with the standard library, so Pillow is never a runtime or qualification dependency. Text is drawn dark on white;
no recogniser output is read here. Each image is opaque RGB8 with a pHYs density of 200 dpi.
"""
import struct
import sys
import zlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FIXTURES = {'baseline': ('NORTH 4096', 'RIVER 1357'), 'changed': ('NORTH 4096', 'RIVER 2468'), 'single-line': ('NORTH 4096',)}
SIZE = 56
MARGIN = 40
GAP = 36


def chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))


def encode(image, density=200):
    width, height = image.size
    raw = b''.join(b'\x00' + image.tobytes()[y * width * 3:(y + 1) * width * 3] for y in range(height))
    per_metre = int(density * 100 / 2.54 + .5)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'pHYs', struct.pack('>IIB', per_metre, per_metre, 1)) \
        + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b'')


def main(font_path, output):
    font = ImageFont.truetype(font_path, SIZE)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name, lines in FIXTURES.items():
        width = 2 * MARGIN + max(int(font.getlength(line)) for line in lines) + 8
        height = 2 * MARGIN + len(lines) * SIZE + (len(lines) - 1) * GAP
        image = Image.new('RGB', (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        for index, line in enumerate(lines):
            draw.text((MARGIN, MARGIN + index * (SIZE + GAP)), line, font=font, fill=(0, 0, 0))
        (output / (name + '.png')).write_bytes(encode(image))


if __name__ == '__main__':
    main(*sys.argv[1:3])
