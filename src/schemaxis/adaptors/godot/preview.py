"""Dependency-free bounded validation of native-generated PNG previews."""
import struct
import zlib
from .errors import fault


def inspect_png(data):
    def check(condition):
        if not condition:
            fault('VERIFICATION_FAILED', 'Preview is not a complete bounded 640x480 PNG.', '$.preview',
                  'Regenerate the preview with the native graphical runtime.')
    check(len(data) <= 4 * 1024 * 1024 and data[:8] == b'\x89PNG\r\n\x1a\n')
    offset, size, channels, compressed, ended = 8, None, None, bytearray(), False
    while offset < len(data):
        check(offset+12 <= len(data) and not ended)
        length, kind = struct.unpack_from('>I4s', data, offset)
        check(offset+12+length <= len(data))
        payload = data[offset+8:offset+8+length]
        crc = struct.unpack_from('>I', data, offset+8+length)[0]
        check(zlib.crc32(kind+payload) & 0xffffffff == crc)
        if size is None:
            check(kind == b'IHDR' and length == 13)
            width, height, depth, colour, compression, filtering, interlace = struct.unpack('>IIBBBBB', payload)
            check([width, height] == [640, 480] and depth == 8 and colour in (2, 6)
                  and (compression, filtering, interlace) == (0, 0, 0))
            size, channels = [width, height], 3 if colour == 2 else 4
        elif kind == b'IDAT':
            compressed.extend(payload)
        elif kind == b'IEND':
            check(length == 0 and bool(compressed))
            ended = True
        else:
            check(kind != b'IHDR' and bool(kind[0] & 32))
        offset += length+12
    check(ended)
    expected = (640*channels+1)*480
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, expected+1)
        check(len(raw) == expected and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail)
        check(all(raw[y*(640*channels+1)] <= 4 for y in range(480)))
    except zlib.error:
        check(False)
    return size
