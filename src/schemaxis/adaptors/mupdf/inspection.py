# Copyright (C) 2026 David L F Gaden
"""Bounded standard-library PNG/PNM decoding, independent of MuPDF bindings."""
import hashlib
import struct
import zlib
from schemaxis.errors import fail

MAX_PIXELS = 16777216


def png(data,dpi=None):
    try:
        if data[:8] != b'\x89PNG\r\n\x1a\n': raise ValueError('signature')
        offset = 8; compressed = bytearray(); seen = []; dimensions = None
        while offset < len(data):
            size = struct.unpack('>I',data[offset:offset+4])[0]
            if size > 64*1024*1024: raise ValueError('chunk size')
            kind=data[offset+4:offset+8];body=data[offset+8:offset+8+size]
            crc=struct.unpack('>I',data[offset+8+size:offset+12+size])[0]
            if len(body)!=size or crc!=zlib.crc32(kind+body): raise ValueError('CRC')
            offset += 12+size; seen.append(kind)
            if kind==b'IHDR':
                w,h,depth,colour,compression,filtering,interlace=struct.unpack('>IIBBBBB',body)
                if not 1<=w<=4096 or not 1<=h<=4096 or w*h>MAX_PIXELS or (depth,colour,compression,filtering,interlace)!=(8,2,0,0,0): raise ValueError('RGB geometry/encoding')
                dimensions=(w,h)
            elif kind==b'IDAT': compressed.extend(body)
            elif kind==b'IEND':
                if body or offset!=len(data): raise ValueError('end/trailing data')
            elif kind==b'pHYs':
                if len(body)!=9 or body[-1] not in (0,1):raise ValueError('density chunk structure')
                if dpi is not None and struct.unpack('>IIB',body)!=(int(dpi*100/2.54+.5),int(dpi*100/2.54+.5),1):raise ValueError('density differs from requested DPI')
            else:raise ValueError('unsupported chunk')
        if seen.count(b'pHYs')>1 or (b'pHYs' in seen and (b'IDAT' not in seen or seen.index(b'pHYs')>seen.index(b'IDAT'))):raise ValueError('density chunk order')
        idats=[i for i,k in enumerate(seen) if k==b'IDAT']
        if idats and idats!=list(range(idats[0],idats[-1]+1)):raise ValueError('noncontiguous image chunks')
        if dpi is not None and seen.count(b'pHYs')!=1:raise ValueError('requested density metadata missing')
        if not seen or seen[0]!=b'IHDR' or seen[-1]!=b'IEND' or seen.count(b'IHDR')!=1 or seen.count(b'IEND')!=1 or b'IDAT' not in seen: raise ValueError('chunk order')
        w,h=dimensions; stride=w*3; expected=(stride+1)*h
        inflater=zlib.decompressobj(); raw=inflater.decompress(compressed,expected+1)
        if len(raw)!=expected or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail: raise ValueError('decoded size')
        pixels=bytearray(); previous=bytearray(stride)
        for y in range(h):
            filtering=raw[y*(stride+1)]; row=bytearray(raw[y*(stride+1)+1:(y+1)*(stride+1)])
            if filtering>4: raise ValueError('filter')
            for x in range(stride):
                a=row[x-3] if x>=3 else 0; b=previous[x]; c=previous[x-3] if x>=3 else 0
                if filtering==1: value=a
                elif filtering==2: value=b
                elif filtering==3: value=(a+b)//2
                elif filtering==4:
                    p=a+b-c; pa,pb,pc=abs(p-a),abs(p-b),abs(p-c)
                    value=a if pa<=pb and pa<=pc else b if pb<=pc else c
                else: value=0
                row[x]=(row[x]+value)&255
            pixels.extend(row); previous=row
        return w,h,bytes(pixels)
    except (ValueError,TypeError,struct.error,zlib.error,IndexError) as error:
        fail('VERIFICATION_FAILED','invalid bounded RGB PNG: '+str(error))


def pnm(data):
    try:
        # MuPDF emits the closed P6 header, without comments or colour profiles.
        magic,geometry,maximum,pixels=data.split(b'\n',3)
        w,h=map(int,geometry.split())
        if magic!=b'P6' or maximum!=b'255' or not 1<=w<=4096 or not 1<=h<=4096 or w*h>MAX_PIXELS or len(pixels)!=w*h*3: raise ValueError('header/size')
        return w,h,pixels
    except (ValueError,TypeError) as error:
        fail('VERIFICATION_FAILED','invalid native RGB readback: '+str(error))


def pixel_digest(decoded):
    w,h,pixels=decoded
    return {'width':w,'height':h,'rgbSha256':hashlib.sha256(pixels).hexdigest()}
