"""Bounded independent inspection of the render bundle's scanline EXR files.

The supported publication profile is single-part, full-resolution scanlines with
NONE, ZIPS or ZIP compression. This is not a general OpenEXR interchange reader.
FileOutput uses legacy interleaving explicitly; other layouts remain unqualified.
"""
import hashlib
import math
from pathlib import Path
import struct
import zlib

from schemaxis.errors import fail


MAX_FILE_BYTES = 256 * 1024**2
MAX_HEADER_BYTES = 1024**2
MAX_PIXELS = 2048**2
MAX_CHANNELS = 128
MAX_DECODED_BYTES = 256 * 1024**2
MAX_CHUNK_BYTES = 16 * 1024**2
PIXEL_TYPES = {0: ('uint', 'I', 4), 1: ('half', 'e', 2), 2: ('float', 'f', 4)}


def _require(condition, message):
    if not condition:
        fail('INVALID_RENDER_OUTPUT', message)


class _Reader:
    def __init__(self, raw):
        self.raw, self.position = raw, 0

    def take(self, count):
        _require(0 <= count <= len(self.raw) - self.position,
                 'EXR value extends beyond the file')
        value = self.raw[self.position:self.position + count]
        self.position += count
        return value

    def string(self):
        end = self.raw.find(b'\0', self.position, self.position + 1025)
        _require(end >= self.position, 'EXR name is missing or exceeds 1024 bytes')
        value = self.raw[self.position:end].decode('utf-8')
        self.position = end + 1
        return value


def inspect(path, *, samples=()):
    """Return independently decoded file facts and optional zero-based samples.

    A sample records the original component bits as well as the numeric value:
    Cryptomatte IDs must never be compared using floating-point tolerances.
    Memory is bounded by the file and one decoded chunk, not Python pixel arrays.
    """
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        _require(len(raw) <= MAX_FILE_BYTES, 'EXR file exceeds 256 MiB')
        return _inspect(raw, samples)
    except (OSError, ValueError, TypeError, struct.error, UnicodeError, zlib.error) as error:
        fail('INVALID_RENDER_OUTPUT', 'Malformed render EXR: ' + str(error))


def _inspect(raw, samples):
    reader = _Reader(raw)
    magic, version = struct.unpack('<II', reader.take(8))
    _require(magic == 20000630 and version & 255 == 2,
             'Render output is not an OpenEXR version 2 file')
    # Only the long-names flag is permitted. Tiled, deep and multipart layouts
    # need their own bounded contracts; do not interpret their bytes as scanlines.
    _require(version & ~(255 | 1024) == 0,
             'Render EXR requires the reviewed single-part scanline layout')
    attributes = {}
    while True:
        _require(reader.position <= MAX_HEADER_BYTES, 'EXR header exceeds 1 MiB')
        name = reader.string()
        if not name:
            break
        kind = reader.string()
        length, = struct.unpack('<i', reader.take(4))
        _require(name not in attributes and 0 <= length <= MAX_HEADER_BYTES,
                 'EXR attribute is repeated or exceeds the header bound')
        value = reader.take(length)
        _require(reader.position <= MAX_HEADER_BYTES, 'EXR header exceeds 1 MiB')
        _require(len(attributes) < 512, 'EXR header exceeds 512 attributes')
        attributes[name] = (kind, value)

    def attribute(name, kind, size=None):
        _require(name in attributes, 'EXR required attribute is missing: ' + name)
        actual_kind, value = attributes[name]
        _require(actual_kind == kind and (size is None or len(value) == size),
                 'EXR attribute type or size differs: ' + name)
        return value

    window = struct.unpack('<4i', attribute('dataWindow', 'box2i', 16))
    display = struct.unpack('<4i', attribute('displayWindow', 'box2i', 16))
    xmin, ymin, xmax, ymax = window
    width, height = xmax - xmin + 1, ymax - ymin + 1
    _require(0 < width <= 2048 and 0 < height <= 2048 and width * height <= MAX_PIXELS,
             'EXR dimensions exceed the render output bound')
    _require(display == window, 'Render EXR data and display windows must agree')
    aspect, = struct.unpack('<f', attribute('pixelAspectRatio', 'float', 4))
    _require(math.isfinite(aspect) and aspect > 0, 'EXR pixel aspect is invalid')
    compression = attribute('compression', 'compression', 1)[0]
    _require(compression in (0, 2, 3), 'EXR codec requires reviewed NONE, ZIPS or ZIP')
    order = attribute('lineOrder', 'lineOrder', 1)[0]
    _require(order in (0, 1), 'EXR scanline order is unsupported')
    channel_reader = _Reader(attribute('channels', 'chlist'))
    channels, names = [], set()
    while True:
        name = channel_reader.string()
        if not name:
            break
        pixel_type, linear, x_sampling, y_sampling = struct.unpack(
            '<iB3xii', channel_reader.take(16))
        _require(name not in names and len(channels) < MAX_CHANNELS,
                 'EXR channels are repeated or exceed 128')
        _require(pixel_type in PIXEL_TYPES and linear in (0, 1)
                 and x_sampling == y_sampling == 1,
                 'EXR channel type or subsampling is unsupported')
        names.add(name)
        channels.append({'name': name, 'pixelType': PIXEL_TYPES[pixel_type][0],
                         'linear': bool(linear), '_type': pixel_type})
    _require(channels and channel_reader.position == len(channel_reader.raw),
             'EXR channel declaration has missing or trailing data')
    row_bytes = width * sum(PIXEL_TYPES[c['_type']][2] for c in channels)
    _require(row_bytes * height <= MAX_DECODED_BYTES,
             'EXR decoded planes exceed 256 MiB')
    _require(isinstance(samples, (list, tuple)) and len(samples) <= 4096,
             'EXR inspection samples exceed 4096')
    requested = set()
    for point in samples:
        _require(isinstance(point, (list, tuple)) and len(point) == 2
                 and all(type(v) is int for v in point)
                 and 0 <= point[0] < width and 0 <= point[1] < height,
                 'EXR inspection sample is outside the image')
        requested.add(tuple(point))
    values = {f'{x},{y}': {} for x, y in sorted(requested)}
    requested_rows = {}
    for x, y in sorted(requested):
        requested_rows.setdefault(y + ymin, []).append(x)
    hashes = {c['name']: hashlib.sha256() for c in channels}
    lines = 16 if compression == 3 else 1
    count = (height + lines - 1) // lines
    offsets = struct.unpack('<' + 'Q' * count, reader.take(count * 8))
    table_end = reader.position
    intervals, visited = [], set()
    for offset in offsets:
        _require(table_end <= offset <= len(raw) - 8, 'EXR chunk offset is invalid')
        y, length = struct.unpack_from('<ii', raw, offset)
        _require(ymin <= y <= ymax and (y - ymin) % lines == 0
                 and 0 <= length <= len(raw) - offset - 8,
                 'EXR chunk row or byte range is invalid')
        intervals.append((offset, offset + 8 + length))
        rows = min(lines, ymax - y + 1)
        expected = row_bytes * rows
        _require(expected <= MAX_CHUNK_BYTES and length <= expected,
                 'EXR chunk exceeds its decoded size bound')
        packed = raw[offset + 8:offset + 8 + length]
        if compression and length < expected:
            decoder = zlib.decompressobj()
            restored = bytearray(decoder.decompress(packed, expected + 1))
            _require(len(restored) == expected and decoder.eof
                     and not decoder.unused_data and not decoder.unconsumed_tail,
                     'EXR compressed chunk length or stream differs')
            for i in range(1, len(restored)):
                restored[i] = (restored[i - 1] + restored[i] - 128) & 255
            half = (expected + 1) // 2
            data = bytearray(expected)
            data[0::2], data[1::2] = restored[:half], restored[half:]
        else:
            data = packed
        _require(len(data) == expected, 'EXR raw chunk length differs')
        position = 0
        for row in range(y, y + rows):
            _require(row not in visited, 'EXR repeats a scanline')
            visited.add(row)
            for channel in channels:
                name = channel['name']
                _, code, size = PIXEL_TYPES[channel['_type']]
                plane = data[position:position + width * size]
                hashes[name].update(struct.pack('<i', row))
                hashes[name].update(plane)
                for x in requested_rows.get(row, ()):
                    component = plane[x * size:(x + 1) * size]
                    number, = struct.unpack('<' + code, component)
                    if isinstance(number, float) and not math.isfinite(number):
                        number = 'nan' if math.isnan(number) else 'inf' if number > 0 else '-inf'
                    values[f'{x},{row-ymin}'][name] = {
                        'value': number, 'bits': bytes(component).hex()}
                position += width * size
        _require(position == len(data), 'EXR decoded chunk has trailing data')
    _require(len(visited) == height, 'EXR scanlines are missing')
    intervals.sort()
    _require(intervals[0][0] == table_end and intervals[-1][1] == len(raw)
             and all(a[1] == b[0] for a, b in zip(intervals, intervals[1:])),
             'Render EXR chunks overlap or contain unclaimed bytes')
    for channel in channels:
        channel.pop('_type')
        channel['decodedSha256'] = hashes[channel['name']].hexdigest()
    from .cryptomatte_output import metadata
    return {'format': 'exr', 'sha256': hashlib.sha256(raw).hexdigest(),
            'bytes': len(raw), 'size': [width, height], 'dataWindow': list(window),
            'pixelAspect': aspect, 'compression': {0: 'none', 2: 'zips', 3: 'zip'}[compression],
            'channels': channels, 'samples': values, 'cryptomatte': metadata(attributes),
            'attributes': {name: {'type': kind, 'sha256': hashlib.sha256(value).hexdigest()}
                           for name, (kind, value) in sorted(attributes.items())}}
