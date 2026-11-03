# Copyright (C) 2026 David L F Gaden
"""Bounded, dependency-free decoding of non-interlaced 8-bit RGB/RGBA PNGs."""
import struct
import zlib
from .errors import fail

MAX_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 4096 * 4096


def decode(data):
    def check(value):
        if not value:
            fail('INVALID_IMAGE', 'expected a complete bounded non-interlaced 8-bit RGB/RGBA PNG')
    check(len(data) <= MAX_BYTES and data[:8] == b'\x89PNG\r\n\x1a\n')
    offset, header, compressed, ended, idat_ended = 8, None, bytearray(), False, False
    while offset < len(data):
        check(offset+12 <= len(data) and not ended)
        length, kind = struct.unpack_from('>I4s', data, offset)
        check(offset+12+length <= len(data))
        payload = data[offset+8:offset+8+length]
        check(zlib.crc32(kind+payload) & 0xffffffff == struct.unpack_from('>I', data, offset+8+length)[0])
        if header is None:
            check(kind == b'IHDR' and length == 13)
            w, h, depth, colour, compression, filtering, interlace = struct.unpack('>IIBBBBB', payload)
            check(0 < w <= 4096 and 0 < h <= 4096 and w*h <= MAX_PIXELS and depth == 8
                  and colour in (2, 6) and (compression, filtering, interlace) == (0, 0, 0))
            channels = 3 if colour == 2 else 4
            header = True
        elif kind == b'IDAT':
            check(not idat_ended)
            compressed.extend(payload)
        elif kind == b'IEND':
            check(length == 0 and bool(compressed))
            ended = True
        else:
            check(kind not in (b'IHDR', b'tRNS') and (bool(kind[0] & 32) or kind == b'PLTE'))
            if compressed: idat_ended = True
        offset += length+12
    check(ended)
    stride = w*channels
    expected = (stride+1)*h
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, expected+1)
        check(len(raw) == expected and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail)
    except zlib.error:
        check(False)
    output = bytearray()
    previous = bytearray(stride)
    for y in range(h):
        start = y*(stride+1)
        filtering = raw[start]
        check(filtering <= 4)
        row = bytearray(raw[start+1:start+1+stride])
        for i in range(stride):
            a = row[i-channels] if i >= channels else 0
            b = previous[i]
            c = previous[i-channels] if i >= channels else 0
            predictor = 0
            if filtering == 1: predictor = a
            elif filtering == 2: predictor = b
            elif filtering == 3: predictor = (a+b)//2
            elif filtering == 4:
                p = a+b-c
                distances = (abs(p-a), abs(p-b), abs(p-c))
                predictor = (a, b, c)[distances.index(min(distances))]
            row[i] = (row[i]+predictor) & 255
        if channels == 4: output.extend(row)
        else:
            for i in range(0, stride, 3): output.extend((*row[i:i+3], 255))
        previous = row
    return w, h, bytes(output)


def read(path):
    try:
        with open(path, 'rb') as stream:
            return decode(stream.read(MAX_BYTES+1))
    except OSError as error:
        fail('RESOURCE_NOT_FOUND', str(error), str(path))
