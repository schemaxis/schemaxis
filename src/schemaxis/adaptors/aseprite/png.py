"""Dependency-free bounded PNG sample decoder, independent of Aseprite.

Source assets deliberately support only unprofiled, noninterlaced RGBA8 PNG.
Publication decoding also permits RGB8 and ignorable ancillary metadata. Pixel
samples are compared without colour transformations; hidden transparent RGB is
normalised because Aseprite may discard it when trimming empty cels.
"""
import struct
import zlib

from schemaxis.errors import fail

MAX_BYTES = 2 * 1024 * 1024
SIGNATURE = b'\x89PNG\r\n\x1a\n'


def decode(data, *, source=True, location='$.source'):
    def reject(message):
        fail('UNSUPPORTED_IMAGE', message, location)
    if len(data) > MAX_BYTES or not data.startswith(SIGNATURE):
        reject('provide a PNG within the 2 MiB file limit')
    offset, chunks, compressed, seen_end = 8, [], bytearray(), False
    width = height = channels = 0
    idat_ended = False
    while offset < len(data):
        if offset + 12 > len(data): reject('truncated PNG chunk')
        size, kind = struct.unpack('>I4s', data[offset:offset+8])
        end = offset + 12 + size
        if end > len(data): reject('truncated PNG payload')
        body = data[offset+8:offset+8+size]
        if zlib.crc32(kind+body) & 0xffffffff != struct.unpack('>I', data[end-4:end])[0]:
            reject('PNG checksum differs')
        if not chunks and kind != b'IHDR': reject('PNG must start with IHDR')
        if kind == b'IHDR':
            if chunks or size != 13: reject('invalid PNG image header')
            width, height, depth, mode, compression, filtering, interlace = struct.unpack('>IIBBBBB', body)
            if not (1 <= width <= (256 if source else 8192) and 1 <= height <= 256):
                reject('PNG dimensions exceed the supported pixel bounds')
            if depth != 8 or mode not in ((6,) if source else (2, 6)) or compression or filtering or interlace:
                reject('use noninterlaced RGBA8 PNG without palette, grayscale or 16-bit samples')
            channels = 4 if mode == 6 else 3
        elif kind == b'IDAT':
            if idat_ended: reject('PNG image data must be consecutive')
            compressed.extend(body)
        elif kind == b'IEND':
            if size or b'IDAT' not in chunks or end != len(data): reject('invalid PNG end or trailing data')
            seen_end = True
        else:
            if source or not (kind[0] & 32) or kind in (b'acTL', b'fcTL', b'fdAT'):
                reject('source PNG must contain only IHDR, IDAT and IEND; strip profiles/metadata and animation')
        if chunks and chunks[-1] == b'IDAT' and kind != b'IDAT': idat_ended = True
        chunks.append(kind)
        offset = end
    if not seen_end: reject('PNG has no complete IEND')
    stride = width * channels
    limit = (stride+1)*height
    try:
        inflater = zlib.decompressobj()
        raw = inflater.decompress(compressed, limit+1)
        if len(raw) != limit or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
            reject('PNG inflated data length differs from dimensions')
    except zlib.error:
        reject('PNG image data is not valid zlib')
    pixels, previous = bytearray(), bytearray(stride)
    for y in range(height):
        row = bytearray(raw[y*(stride+1)+1:(y+1)*(stride+1)])
        method = raw[y*(stride+1)]
        if method > 4: reject('unknown PNG row filter')
        for i in range(stride):
            left = row[i-channels] if i >= channels else 0
            above = previous[i]
            corner = previous[i-channels] if i >= channels else 0
            if method == 1: prediction = left
            elif method == 2: prediction = above
            elif method == 3: prediction = (left+above)//2
            elif method == 4:
                p = left+above-corner
                distances = (abs(p-left), abs(p-above), abs(p-corner))
                prediction = (left, above, corner)[distances.index(min(distances))]
            else: prediction = 0
            row[i] = (row[i]+prediction) & 255
        for i in range(0, stride, channels):
            rgba = bytes(row[i:i+3]) + bytes([row[i+3] if channels == 4 else 255])
            if rgba[3] not in (0, 255): reject('PNG alpha must be binary: 0 or 255; partial alpha is unsupported')
            pixels.extend(rgba if rgba[3] else b'\0\0\0\0')
        previous = row
    return {'width': width, 'height': height, 'pixels': pixels.hex()}
