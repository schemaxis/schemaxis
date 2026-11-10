# Copyright (C) 2026 David L F Gaden
"""Independent bounded PNG8 decoder and exact encoded-sample raster oracle.

No ImageMagick identity/decode is used to establish expected pixels. Rows are
unfiltered according to PNG's five filters; no colour transforms are inferred.
"""
import struct
import zlib

from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.errors import fail

SIGNATURE = b'\x89PNG\r\n\x1a\n'
PIXELS = 1048576
BYTES = 8 * 1024 * 1024
CHROMATICITIES = (31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000)
# Sample depths PNG itself allows per colour type; other pairs are malformed, not merely unsupported.
LEGAL_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
MALFORMED_RECOVERY = ('The PNG data is corrupt, truncated or violates the PNG chunk structure. '
    'Re-capture or re-export it from its producer, check that it transferred intact, and retry; do not repair it by hand.')
UNSUPPORTED_RECOVERY = ('The PNG is intact but outside the supported subset and Schemaxis does not convert images. '
    'Re-export it deliberately as a non-interlaced 8-bit RGB or RGBA PNG of at most 4096 pixels per side and 1,048,576 pixels, '
    'with no ICC profile, palette, tRNS or animation and only sRGB, standard gAMA+cHRM, pHYs, tEXt or tIME metadata, then retry.')


class Unsupported(ValueError):
    """A well-formed PNG feature outside the supported subset (distinct from corruption)."""
    def __init__(self, feature, reason):
        super().__init__(reason); self.feature = feature; self.reason = reason


def source_fault(code, category, feature, reason, recovery, location='$'):
    prefix = 'PNG is malformed: ' if category == 'malformed' else 'PNG is well-formed but unsupported: '
    return SchemaxisError(Fault(code, prefix + reason, location, 'pipeline',
        observed={'category': category, 'feature': feature, 'reason': reason}, recovery=recovery))


def decode(data, *, output=False):
    """Return width, height, RGBA8 bytes, and observed colour declaration."""
    try:
        if not data.startswith(SIGNATURE): raise ValueError('require a PNG signature')
        if len(data) > BYTES: raise Unsupported('byte-budget', 'PNG exceeds the 8MiB byte budget')
        pos = 8; chunks = []; compressed = bytearray(); seen = set(); ended_data = False; unsupported = []
        def note(feature, reason):
            # Published output never has an unsupported category; source files are classified only after the
            # whole chunk structure validated, so corruption is never mislabelled as unsupported.
            if output: raise ValueError(reason)
            if not unsupported: unsupported.append((feature, reason))
        width = height = channels = 0; srgb = gamma = chroma = False
        while pos < len(data):
            if pos + 12 > len(data): raise ValueError('truncated chunk')
            size = struct.unpack('>I', data[pos:pos+4])[0]; kind = data[pos+4:pos+8]
            if size > BYTES or pos + size + 12 > len(data): raise ValueError('chunk byte budget/truncation')
            value = data[pos+8:pos+8+size]; crc = struct.unpack('>I', data[pos+8+size:pos+12+size])[0]
            if zlib.crc32(kind+value) & 0xffffffff != crc: raise ValueError('chunk CRC differs')
            pos += size + 12
            if not all(65 <= c <= 90 or 97 <= c <= 122 for c in kind): raise ValueError('invalid chunk name')
            if not chunks and kind != b'IHDR': raise ValueError('IHDR must be first')
            if kind == b'IHDR':
                if chunks or size != 13: raise ValueError('one 13-byte IHDR required')
                width,height,depth,colour,compression,filtering,interlace = struct.unpack('>IIBBBBB',value)
                if not 1 <= width <= 0x7fffffff or not 1 <= height <= 0x7fffffff: raise ValueError('image width and height must be positive')
                if colour not in LEGAL_DEPTHS or depth not in LEGAL_DEPTHS[colour]: raise ValueError('invalid colour type and sample depth combination')
                if (compression,filtering) != (0,0) or interlace not in (0,1): raise ValueError('invalid compression, filter or interlace method')
                if width > 4096 or height > 4096 or width*height > PIXELS: note('dimensions', 'image pixel/dimension budget exceeded')
                if depth != 8: note('bit-depth', f'{depth}-bit samples are not supported; only 8-bit')
                if colour not in ((6,) if output else (2,6)): note('colour-type', f'PNG colour type {colour} is not supported; only RGB or RGBA' + (' output required' if output else ''))
                if interlace: note('interlace', 'only non-interlaced PNG is supported')
                channels = 3 if colour == 2 else 4
            elif kind == b'IDAT':
                if ended_data: raise ValueError('IDAT chunks must be consecutive')
                compressed.extend(value)
            elif kind == b'IEND':
                if size or b'IDAT' not in seen or pos != len(data): raise ValueError('IEND must finish the complete image')
                chunks.append(kind); break
            else:
                if output: raise ValueError('published PNG must contain only IHDR, consecutive IDAT and IEND; metadata is stripped')
                if b'IDAT' in seen: ended_data = True
                if kind in (b'sRGB', b'gAMA', b'cHRM', b'pHYs'):
                    if kind in seen or b'IDAT' in seen: raise ValueError('unique pre-IDAT metadata required')
                    if kind == b'sRGB':
                        if size != 1 or value[0] > 3: raise ValueError('invalid sRGB intent')
                        srgb = True
                    if kind == b'gAMA':
                        if size != 4: raise ValueError('invalid gAMA length')
                        if struct.unpack('>I',value)[0] != 45455: note('colour-declaration', 'only standard sRGB gamma is supported')
                        gamma = True
                    if kind == b'cHRM':
                        if size != 32: raise ValueError('invalid cHRM length')
                        if struct.unpack('>8I',value) != CHROMATICITIES: note('colour-declaration', 'only standard sRGB chromaticities are supported')
                        chroma = True
                    if kind == b'pHYs' and (size != 9 or value[-1] not in (0,1)): raise ValueError('invalid physical pixel metadata')
                elif kind == b'tEXt':
                    if b'\0' not in value: raise ValueError('invalid text metadata: keyword separator missing')
                    if size > 65536: note('metadata-size', 'text metadata exceeds the 64KiB bound')
                elif kind == b'tIME':
                    if size != 7 or kind in seen: raise ValueError('invalid time metadata')
                else: note('chunk', 'unsupported chunk '+kind.decode('ascii')+'; no ICC, animation, palette, transparency keys or compressed metadata')
            chunks.append(kind); seen.add(kind)
        if not chunks or chunks[-1] != b'IEND': raise ValueError('missing IEND')
        # A lone gAMA/cHRM assertion cannot establish sRGB interpretation.
        if not srgb and gamma != chroma: note('colour-declaration', 'supply sRGB or matching standard gAMA+cHRM, or remove colour metadata and explicitly assume sRGB')
        if unsupported: raise Unsupported(*unsupported[0])
        stride = width*channels; expected = (stride+1)*height
        inflater = zlib.decompressobj(); raw = inflater.decompress(bytes(compressed),expected+1)
        if len(raw) != expected or not inflater.eof or inflater.unconsumed_tail or inflater.unused_data: raise ValueError('PNG decompression length/stream differs')
        rgba = bytearray(width*height*4); previous = bytearray(stride)
        for y in range(height):
            base = y*(stride+1); mode = raw[base]; row = bytearray(raw[base+1:base+1+stride])
            if mode > 4: raise ValueError('unknown PNG row filter')
            for x in range(stride):
                a = row[x-channels] if x >= channels else 0; b = previous[x]; c = previous[x-channels] if x >= channels else 0
                if mode == 1: prediction = a
                elif mode == 2: prediction = b
                elif mode == 3: prediction = (a+b)//2
                elif mode == 4:
                    p = a+b-c; pa,pb,pc = abs(p-a),abs(p-b),abs(p-c)
                    prediction = a if pa <= pb and pa <= pc else b if pb <= pc else c
                else: prediction = 0
                row[x] = (row[x]+prediction)&255
            for x in range(width):
                at = 4*(y*width+x); rgba[at:at+3] = row[x*channels:x*channels+3]; rgba[at+3] = row[x*channels+3] if channels == 4 else 255
            previous = row
        colour = 'sRGB chunk' if srgb else 'standard sRGB gAMA+cHRM' if gamma else 'untagged: authored assume-srgb'
        return width,height,bytes(rgba),colour
    except Unsupported as error:
        raise source_fault('UNSUPPORTED_RASTER_PNG','unsupported',error.feature,error.reason,UNSUPPORTED_RECOVERY) from None
    except (ValueError,struct.error,zlib.error,IndexError) as error:
        if output: fail('VERIFICATION_FAILED',str(error))
        raise source_fault('INVALID_RASTER_PNG','malformed','structure',str(error),MALFORMED_RECOVERY) from None


def encode(width,height,rgba):
    """Deterministic test/canvas PNG, not a native-produced publication."""
    def chunk(kind,value): return struct.pack('>I',len(value))+kind+value+struct.pack('>I',zlib.crc32(kind+value)&0xffffffff)
    raw=b''.join(b'\0'+rgba[y*width*4:(y+1)*width*4] for y in range(height))
    return SIGNATURE+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')


def transform(image,item,alpha,background):
    """Crop, integer replicate, clockwise quarter turns, then encoded alpha blend."""
    width,height,pixels,_ = image
    crop = item.get('crop',{'x':0,'y':0,'width':width,'height':height})
    x,y,w,h = [crop[k] for k in ('x','y','width','height')]
    if x+w > width or y+h > height: fail('RASTER_CROP_OUTSIDE','crop must lie entirely inside the captured image; coordinates are top-left pixels')
    scale=item['scale']; turns=item['quarterTurns']; nw,nh=w*scale,h*scale
    if turns%2: ow,oh=nh,nw
    else: ow,oh=nw,nh
    if ow>4096 or oh>4096 or ow*oh>PIXELS: fail('RASTER_PIXEL_BUDGET','transformed image exceeds 4096 per side or 1048576 pixels')
    out=bytearray(ow*oh*4)
    for oy in range(oh):
        for ox in range(ow):
            if turns==0: sx,sy=ox,oy
            elif turns==1: sx,sy=oy,nh-1-ox
            elif turns==2: sx,sy=nw-1-ox,nh-1-oy
            else: sx,sy=nw-1-oy,ox
            at=4*((y+sy//scale)*width+x+sx//scale); pixel=pixels[at:at+4]
            if alpha=='flatten':
                a=pixel[3];pixel=bytes((v*a+b*(255-a)+127)//255 for v,b in zip(pixel[:3],background))+b'\xff'
            out[4*(oy*ow+ox):4*(oy*ow+ox)+4]=pixel
    return ow,oh,bytes(out),'sRGB encoded samples'


def layout(images,sheet):
    columns=sheet['columns'];padding=sheet['padding'];rows=(len(images)+columns-1)//columns
    cw=max(i[0] for i in images);ch=max(i[1] for i in images)
    width=columns*cw+(columns+1)*padding;height=rows*ch+(rows+1)*padding
    if width>4096 or height>4096 or width*height>PIXELS: fail('RASTER_PIXEL_BUDGET','contact sheet exceeds the pixel budget')
    places=[{'index':n,'x':padding+(n%columns)*(cw+padding),'y':padding+(n//columns)*(ch+padding),'width':im[0],'height':im[1]} for n,im in enumerate(images)]
    canvas=bytes(sheet['background']+[255])*(width*height)
    result=bytearray(canvas)
    for place,image in zip(places,images):
        for row in range(image[1]):
            at=4*((place['y']+row)*width+place['x']);result[at:at+image[0]*4]=image[2][row*image[0]*4:(row+1)*image[0]*4]
    return (width,height,bytes(result),'sRGB encoded samples'),places,canvas
