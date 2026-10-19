"""Independent bounded grayscale image decoding and particle reference model.

Nothing here imports or calls ImageJ. The model restates the documented ImageJ
1.x particle-analyser contract from first principles (inclusive raw threshold,
raster discovery order, 8- or 4-connected particles, optional enclosed-hole
filling, bounding-box edge exclusion and inclusive pixel-count filtering) so
native tables, labels and summaries can be checked against an unrelated path.
"""
from array import array
from collections import deque
import struct

from schemaxis.errors import fail

MAX_FILE_BYTES = 16*1024*1024
MAX_SIDE = 2048
MAX_PIXELS = 1024*1024
MAX_PARTICLES = 4096
# Hole filling explores each particle's padded bounding box; bound total work.
MAX_FILL_WORK = 64*1024*1024


def _invalid(message, location='$.image', **details):
    fail('INVALID_IMAGE', message, location, **details)


def _unsupported(message, location='$.image', **details):
    fail('UNSUPPORTED_IMAGE', message, location, **details)


def _dimensions(width, height):
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE and width*height <= MAX_PIXELS):
        fail('RESOURCE_LIMIT', f'images are limited to {MAX_SIDE} pixels per side and {MAX_PIXELS} pixels',
             '$.image', width=width, height=height)


def read_pgm(data):
    """Binary P5 PGM with maxval 255 (8-bit) or 65535 (16-bit, big-endian)."""
    if len(data) < 3 or data[2] > 32: _invalid('PGM magic must be followed by whitespace')
    position, fields = 2, []
    while len(fields) < 3:
        if position >= len(data):
            _invalid('truncated PGM header')
        byte = data[position]
        if byte == 35:  # comment to end of line
            end = data.find(b'\n', position)
            if end < 0: _invalid('unterminated PGM header comment')
            position = end+1
        elif byte <= 32:
            position += 1
        elif 48 <= byte <= 57:
            start = position
            while position < len(data) and 48 <= data[position] <= 57 and position-start < 9:
                position += 1
            fields.append(int(data[start:position]))
            if position >= len(data) or data[position] > 32:
                _invalid('PGM header fields must be decimal integers separated by whitespace')
        else:
            _invalid('PGM header fields must be decimal integers separated by whitespace')
    width, height, maximum = fields
    _dimensions(width, height)
    if maximum not in (255, 65535):
        _unsupported('PGM maxval must be 255 (8-bit) or 65535 (16-bit)', maxval=maximum)
    position += 1  # exactly one whitespace byte before the raster
    size = 1 if maximum == 255 else 2
    raster = data[position:]
    if len(raster) != width*height*size:
        _invalid('PGM raster length differs from its header; trailing or missing samples are rejected',
                 expectedBytes=width*height*size, observedBytes=len(raster))
    values = array('H', list(raster)) if size == 1 else array('H', struct.unpack(f'>{width*height}H', raster))
    return {'format': 'pgm', 'width': width, 'height': height, 'bitDepth': 8*size,
            'byteOrder': 'big' if size == 2 else 'none', 'values': values}


TIFF_TYPES = {1: (1, 'B'), 2: (1, 'B'), 3: (2, 'H'), 4: (4, 'I'), 5: (8, 'II')}
# Baseline tags accepted by the bounded subset; others (tiles, colour maps,
# predictors, ImageJ overlay metadata) are rejected rather than ignored.
TIFF_ALLOWED = {254, 256, 257, 258, 259, 262, 266, 270, 273, 274, 277, 278, 279, 282, 283, 284, 296, 305, 306, 339}


def read_tiff(data):
    """Single-IFD, uncompressed, single-sample BlackIsZero 8/16-bit unsigned TIFF."""
    if data[:4] == b'II*\x00': order = '<'
    elif data[:4] == b'MM\x00*': order = '>'
    else: _invalid('expected a classic little- or big-endian TIFF header')
    def unpack(fmt, offset):
        size = struct.calcsize(order+fmt)
        if offset < 0 or offset+size > len(data): _invalid('TIFF structure points outside the file')
        return struct.unpack_from(order+fmt, data, offset)
    (offset,) = unpack('I', 4)
    (count,) = unpack('H', offset)
    if not 1 <= count <= 64: _invalid('TIFF directory entry count is outside 1..64')
    tags = {}
    for index in range(count):
        tag, kind, number, value = unpack('HHII', offset+2+12*index)
        if tag in tags: _invalid('repeated TIFF tag', tag=tag)
        if tag not in TIFF_ALLOWED: _unsupported('TIFF tag is outside the supported baseline subset', tag=tag)
        if kind not in TIFF_TYPES or not 0 < number <= 65536: _invalid('unsupported TIFF field type or count', tag=tag)
        width, code = TIFF_TYPES[kind]
        inline = width*number <= 4
        start = offset+2+12*index+8 if inline else value
        if kind in (3, 4):
            tags[tag] = list(unpack(code[0]*number if number < 8 else f'{number}{code}', start))
        else:
            tags[tag] = None
    (following,) = unpack('I', offset+2+12*count)
    if following != 0: _unsupported('multi-page TIFF files are unsupported; supply exactly one image')
    def one(tag, default=None):
        value = tags.get(tag, None if default is None else [default])
        if value is None or len(value) != 1: _invalid('required single-valued TIFF tag is absent or invalid', tag=tag)
        return value[0]
    width, height = one(256), one(257)
    _dimensions(width, height)
    bits = one(258)
    if bits not in (8, 16): _unsupported('TIFF samples must be 8- or 16-bit', bitsPerSample=bits)
    for tag, expected, meaning in ((259, 1, 'uncompressed'), (262, 1, 'BlackIsZero grayscale'),
                                   (277, 1, 'single-sample'), (284, 1, 'chunky'), (266, 1, 'MSB fill order'),
                                   (274, 1, 'top-left orientation'), (339, 1, 'unsigned integer'), (254, 0, 'full-resolution')):
        if one(tag, expected) != expected:
            _unsupported('only ' + meaning + ' TIFF images are supported', tag=tag)
    offsets, counts = tags.get(273), tags.get(279)
    rows = one(278, height)
    if not offsets or not counts or len(offsets) != len(counts) or rows <= 0:
        _invalid('TIFF strip offsets and byte counts are absent or inconsistent')
    size = bits//8
    raster = bytearray()
    for start, length in zip(offsets, counts):
        if start+length > len(data): _invalid('TIFF strip points outside the file')
        raster.extend(data[start:start+length])
    if len(raster) != width*height*size or len(offsets) != -(-height//min(rows, height)):
        _invalid('TIFF strip data differs from width*height*bytesPerSample',
                 expectedBytes=width*height*size, observedBytes=len(raster))
    values = array('H', list(raster)) if size == 1 else array('H', struct.unpack(f'{order}{width*height}H', raster))
    return {'format': 'tiff', 'width': width, 'height': height, 'bitDepth': bits,
            'byteOrder': ('little' if order == '<' else 'big') if size == 2 else 'none', 'values': values}


def decode(data, extension):
    if len(data) > MAX_FILE_BYTES:
        fail('RESOURCE_LIMIT', 'image file exceeds 16 MiB', '$.image', observedBytes=len(data))
    if extension == '.pgm':
        if data[:2] != b'P5': _invalid('expected a binary P5 PGM')
        return read_pgm(data)
    return read_tiff(data)


def analyse(image, settings):
    """Return particles in ImageJ raster discovery order plus a label array.

    settings: lower, upper, connectivity ('eight'/'four'), includeHoles,
    excludeEdges, minimumPixels, maximumPixels (None means unbounded).
    """
    width, height, values = image['width'], image['height'], image['values']
    lower, upper = settings['lower'], settings['upper']
    inside = bytearray(1 if lower <= value <= upper else 0 for value in values)
    eight = settings['connectivity'] == 'eight'
    steps = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)) if eight else ((0, -1), (-1, 0), (1, 0), (0, 1))
    # Enclosure uses the complementary background connectivity.
    background = ((0, -1), (-1, 0), (1, 0), (0, 1)) if eight else ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))
    erased = bytearray(width*height)
    labels = array('H', bytes(2*width*height))
    particles, rejected, work = [], {'edge': 0, 'size': 0}, 0
    minimum, maximum = settings['minimumPixels'], settings['maximumPixels']
    for start in range(width*height):
        if not inside[start] or erased[start]: continue
        component, queue = [start], deque([start])
        erased[start] = 1
        while queue:
            index = queue.popleft()
            x, y = index % width, index // width
            for dx, dy in steps:
                nx, ny = x+dx, y+dy
                if 0 <= nx < width and 0 <= ny < height:
                    other = ny*width+nx
                    if inside[other] and not erased[other]:
                        erased[other] = 1
                        component.append(other)
                        queue.append(other)
        xs = [i % width for i in component]
        ys = [i // width for i in component]
        left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
        region = component
        if settings['includeHoles']:
            # Flood the padded bounding box from outside; unreached pixels are enclosed.
            boxw, boxh = right-left+3, bottom-top+3
            work += boxw*boxh
            if work > MAX_FILL_WORK:
                fail('RESOURCE_LIMIT', 'hole filling exceeds the bounded reference work budget', '$.includeHoles')
            member = bytearray(boxw*boxh)
            for index in component:
                member[(index//width-top+1)*boxw + index % width-left+1] = 1
            reached = bytearray(boxw*boxh)
            reached[0] = 1
            queue = deque([0])
            while queue:
                cell = queue.popleft()
                cx, cy = cell % boxw, cell // boxw
                for dx, dy in background:
                    nx, ny = cx+dx, cy+dy
                    if 0 <= nx < boxw and 0 <= ny < boxh:
                        other = ny*boxw+nx
                        if not reached[other] and not member[other]:
                            reached[other] = 1
                            queue.append(other)
            region = [(cy-1+top)*width + cx-1+left
                      for cy in range(1, boxh-1) for cx in range(1, boxw-1) if not reached[cy*boxw+cx]]
            for index in region: erased[index] = 1
        count = len(region)
        touches = left == 0 or top == 0 or right == width-1 or bottom == height-1
        if settings['excludeEdges'] and touches:
            rejected['edge'] += 1
            continue
        if count < minimum or (maximum is not None and count > maximum):
            rejected['size'] += 1
            continue
        if len(particles) >= MAX_PARTICLES:
            fail('RESOURCE_LIMIT', f'more than {MAX_PARTICLES} particles pass the declared threshold and filters; '
                 'tighten the threshold or size filter', '$.threshold')
        samples = [values[index] for index in region]
        label = len(particles)+1
        for index in region: labels[index] = label
        particles.append({'label': label, 'pixelCount': count,
                          'sumX': sum(index % width for index in region), 'sumY': sum(index // width for index in region),
                          'sum': sum(samples), 'minimum': min(samples), 'maximum': max(samples),
                          'left': left, 'top': top, 'width': right-left+1, 'height': bottom-top+1,
                          'start': [start % width, start // width], 'touchesEdge': touches})
    return {'particles': particles, 'labels': labels, 'rejected': rejected,
            'thresholdPixels': sum(inside)}


def read_label_pgm(data, width, height):
    """Read the native 16-bit count-mask written by the fixed native program."""
    header = b'P5\n%d %d\n65535\n' % (width, height)
    if data[:len(header)] != header or len(data) != len(header)+2*width*height:
        fail('VERIFICATION_FAILED', 'native count-mask header or size differs')
    return array('H', struct.unpack(f'>{width*height}H', data[len(header):]))
