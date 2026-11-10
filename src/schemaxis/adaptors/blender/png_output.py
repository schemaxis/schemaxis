"""Bounded independent scanline PNG inspection for RGB/RGBA 8- and 16-bit output.

Hashes reconstructed sample bytes in PNG row/channel order. Sixteen-bit samples
retain their original big-endian bytes; no normalization, alpha fill or colour
conversion takes place. This finite profile excludes animation and transparency
keys; use explicit RGBA channels when alpha is required.
"""
import hashlib
from pathlib import Path
import stat
import struct
import zlib

from schemaxis.errors import fail

MAX_FILE_BYTES = 64 * 1024**2
MAX_DECODED_BYTES = 64 * 1024**2
MAX_PIXELS = 2048**2
MAX_CHUNKS = 4096
SIGNATURE = b'\x89PNG\r\n\x1a\n'


def _require(condition, message):
    if not condition:fail('INVALID_RENDER_OUTPUT', message)


def inspect(path):
    """Return size, source depth/channels and SHA256 of reconstructed pixel bytes."""
    try:
        path=Path(path);info=path.lstat()
        _require(stat.S_ISREG(info.st_mode), 'PNG output must be a plain file')
        _require(info.st_size<=MAX_FILE_BYTES, 'PNG output exceeds 64 MiB')
        with path.open('rb') as stream:data=stream.read(MAX_FILE_BYTES+1)
        _require(len(data)<=MAX_FILE_BYTES, 'PNG output exceeds 64 MiB')
        return _inspect(data)
    except (OSError, ValueError, TypeError, struct.error, zlib.error) as error:
        fail('INVALID_RENDER_OUTPUT', 'Malformed render PNG: '+str(error))


def _inspect(data):
    _require(data[:8]==SIGNATURE, 'PNG signature differs')
    offset=8;header=None;compressed=bytearray();seen_idat=False;idat_ended=False
    seen_palette=False;ended=False;chunks=0
    while offset<len(data):
        chunks+=1
        _require(chunks<=MAX_CHUNKS, 'PNG exceeds 4096 chunks')
        _require(not ended and offset+12<=len(data), 'PNG chunk is truncated or follows IEND')
        length,kind=struct.unpack_from('>I4s',data,offset)
        _require(all(65<=v<=90 or 97<=v<=122 for v in kind) and not kind[2]&32,
                 'PNG chunk type or reserved bit is invalid')
        _require(length<=len(data)-offset-12, 'PNG chunk extends beyond file')
        payload=memoryview(data)[offset+8:offset+8+length]
        crc=struct.unpack_from('>I',data,offset+8+length)[0]
        _require(zlib.crc32(payload,zlib.crc32(kind))&0xffffffff==crc, 'PNG chunk CRC differs')
        if header is None:
            _require(kind==b'IHDR' and length==13, 'PNG requires one initial IHDR')
            width,height,depth,colour,compression,filtering,interlace=struct.unpack('>IIBBBBB',payload)
            _require(0<width<=2048 and 0<height<=2048 and width*height<=MAX_PIXELS,
                     'PNG dimensions exceed 2048 by 2048')
            _require(depth in (8,16) and colour in (2,6) and (compression,filtering,interlace)==(0,0,0),
                     'PNG requires non-interlaced RGB/RGBA 8- or 16-bit samples')
            channels=3 if colour==2 else 4;pixel_bytes=channels*(depth//8)
            stride=width*pixel_bytes;expected=(stride+1)*height
            _require(expected<=MAX_DECODED_BYTES, 'PNG decoded scanlines exceed 64 MiB')
            header=True
        elif kind==b'IDAT':
            _require(not idat_ended, 'PNG IDAT chunks must be consecutive')
            seen_idat=True;compressed.extend(payload)
        elif kind==b'IEND':
            _require(length==0 and seen_idat and compressed, 'PNG requires data before empty IEND')
            ended=True
        else:
            _require(kind not in (b'IHDR',b'tRNS',b'acTL',b'fcTL',b'fdAT'),
                     'PNG duplicate header, transparency key or animation is unsupported')
            if kind==b'PLTE':
                _require(not seen_palette and not seen_idat and 0<length<=768 and length%3==0,
                         'PNG optional palette must precede image data')
                seen_palette=True
            else:_require(bool(kind[0]&32), 'PNG has an unsupported critical chunk')
            if seen_idat:idat_ended=True
        offset+=length+12
    _require(ended, 'PNG is missing IEND')
    decoder=zlib.decompressobj();raw=decoder.decompress(compressed,expected+1)
    _require(len(raw)==expected and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
             'PNG zlib stream is incomplete, oversized or has a trailing stream')
    digest=hashlib.sha256();previous=bytearray(stride)
    for y in range(height):
        start=y*(stride+1);filtering=raw[start]
        _require(filtering<=4, 'PNG scanline filter is invalid')
        row=bytearray(raw[start+1:start+stride+1])
        if filtering:
            for i in range(stride):
                a=row[i-pixel_bytes] if i>=pixel_bytes else 0
                b=previous[i];c=previous[i-pixel_bytes] if i>=pixel_bytes else 0
                if filtering==1:predictor=a
                elif filtering==2:predictor=b
                elif filtering==3:predictor=(a+b)//2
                else:
                    p=a+b-c;distances=(abs(p-a),abs(p-b),abs(p-c))
                    predictor=(a,b,c)[distances.index(min(distances))]
                row[i]=(row[i]+predictor)&255
        digest.update(row);previous=row
    return {'size':[width,height],'depth':str(depth),'channels':'rgb' if channels==3 else 'rgba',
            'pixelsSha256':digest.hexdigest()}
