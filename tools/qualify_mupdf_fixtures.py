#!/usr/bin/env python3
"""Hand-built PDF fixture and literal oracle: no PDF library/native output inputs."""
from pathlib import Path
import json
import struct
import zlib

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'examples/schemaxis/fixtures/mupdf/review.pdf'
# Each CropBox is inside a larger MediaBox with a nonzero origin. /Rotate=90
# lives on the page-tree parent; pages 1/3 override it with 0/270 respectively.
PAGES=[([10,20,250,200],[30,40,210,160],0,b'Review Alpha'),
       ([80,180,280,460],[100,200,244,416],None,b'Review caf\xe9'),
       ([-20,-40,140,180],[0,-20,96,124],270,b'Review Gamma')]


def fixture(count=3):
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',
             ('<< /Type /Pages /Kids ['+' '.join(str(4+2*i)+' 0 R' for i in range(count))+'] /Count '+str(count)+' /Rotate 90 >>').encode(),
             b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>']
    for i,(media,crop,rotate,text) in enumerate((PAGES[j%3] for j in range(count))):
        fmt=lambda v:('['+' '.join(map(str,v))+']').encode()
        page=b'<< /Type /Page /Parent 2 0 R /MediaBox '+fmt(media)+b' /CropBox '+fmt(crop)
        if rotate is not None:page+=b' /Rotate '+str(rotate).encode()
        if i==2:page+=b' /UserUnit 2'
        page+=b' /Resources << /Font << /F1 3 0 R >> >> /Contents '+str(5+i*2).encode()+b' 0 R >>'
        x,y,x1,y1=crop;w=(x1-x)/2;h=(y1-y)/2
        commands=[]
        for rgb,xx,yy in [('1 0 0',x,y),('0 1 0',x+w,y),('0 0 1',x,y+h),('1 1 0',x+w,y+h)]:
            commands.append(f'{rgb} rg {xx:g} {yy:g} {w:g} {h:g} re f'.encode())
        commands.append(f'0 0 0 rg BT /F1 9 Tf {x+6} {y+h+6:g} Td ('.encode()+text+b') Tj ET')
        stream=b'\n'.join(commands)+b'\n'
        objects.extend([page,b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'endstream'])
    data=bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n');offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data));data.extend(str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n')
    xref=len(data);data.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return bytes(data)


# This decoder deliberately does not import the adaptor's PNG inspection code.
# It parses native PNG with its own zlib unfilter to independently sample colours.
def pixels(path):
    data=path.read_bytes();assert data[:8]==b'\x89PNG\r\n\x1a\n';pos=8;compressed=b''
    while pos<len(data):
        size=int.from_bytes(data[pos:pos+4],'big');kind=data[pos+4:pos+8];body=data[pos+8:pos+8+size]
        assert int.from_bytes(data[pos+8+size:pos+12+size],'big')==zlib.crc32(kind+body)
        if kind==b'IHDR':
            w,h,depth,colour,_,_,interlace=struct.unpack('>IIBBBBB',body);assert (depth,colour,interlace)==(8,2,0)
        if kind==b'IDAT':compressed+=body
        pos+=12+size
    assert w*h<=16777216
    raw=zlib.decompress(compressed);stride=w*3;previous=[0]*stride;rows=[]
    for y in range(h):
        at=y*(stride+1);f=raw[at];row=list(raw[at+1:at+1+stride])
        for x in range(stride):
            left=row[x-3] if x>=3 else 0;up=previous[x];diagonal=previous[x-3] if x>=3 else 0
            if f==0:prediction=0
            elif f==1:prediction=left
            elif f==2:prediction=up
            elif f==3:prediction=(left+up)//2
            else:
                estimate=left+up-diagonal;dist=[abs(estimate-v) for v in (left,up,diagonal)]
                prediction=(left,up,diagonal)[dist.index(min(dist))]
            row[x]=(row[x]+prediction)%256
        rows.append(row);previous=row
    return w,h,rows


def check(directory,order,dpi,rotation):
    # Literal expectations derived from the fixture's CropBoxes and /Rotate.
    sizes={1:(180,120),2:(216,144),3:(288,192)}
    colours={1:['blue','yellow','red','green'],2:['red','blue','green','yellow'],3:['yellow','green','blue','red']}
    rgb={'red':(255,0,0),'green':(0,255,0),'blue':(0,0,255),'yellow':(255,255,0)}
    text={1:'Review Alpha',2:'Review café',3:'Review Gamma'}
    summary=json.loads((directory/'review-summary.json').read_text());assert summary['pageCount']==3
    for index,page in enumerate(order,1):
        w,h=sizes[page];w=w*dpi//72;h=h*dpi//72
        expected=list(colours[page])
        for _ in range(rotation//90):expected=[expected[2],expected[0],expected[3],expected[1]]
        if rotation in (90,270):w,h=h,w
        actual_w,actual_h,rows=pixels(directory/f'page-{index:03d}.png');assert (actual_w,actual_h)==(w,h),((actual_w,actual_h),(w,h))
        for (x,y),name in zip(((w//4,h//4),(w*3//4,h//4),(w//4,h*3//4),(w*3//4,h*3//4)),expected):
            # Check a 5x5 interior region, far from text, edges and antialiasing.
            for yy in range(y-2,y+3):
                for xx in range(x-2,x+3):assert tuple(rows[yy][xx*3:xx*3+3])==rgb[name],(page,x,y,name)
        assert (directory/f'page-{index:03d}.txt').read_text().strip()==text[page]
        observed=summary['pages'][index-1]
        assert observed['page']==page and observed['mediaBox']==PAGES[page-1][0] and observed['cropBox']==PAGES[page-1][1]
        assert observed['inheritedRotation']==[0,90,270][page-1]
        assert observed['userUnit']==(2 if page==3 else 1)
    return {'pages':order,'dpi':dpi,'rotation':rotation,'checked':'literal crop geometry, page order, 100 RGB samples/page and text including café'}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--write',action='store_true');args=parser.parse_args()
    if args.write:FIXTURE.parent.mkdir(parents=True,exist_ok=True);FIXTURE.write_bytes(fixture())
    assert FIXTURE.read_bytes()==fixture()
    print('Independent PDF fixture matches literal source')
