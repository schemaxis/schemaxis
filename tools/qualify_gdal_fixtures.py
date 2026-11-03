#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Independently author classic TIFF test pixels, affine metadata and GeoKeys."""
from pathlib import Path
import struct


def tiff(pixels, width=6, height=5, dtype='Int16', epsg=3857, units='m', nodata=-9999, endian='<', origin=(500000,5500000), spacing=(10,20)):
    bits,sample,fmt={'UInt16':(16,1,'H'),'Int16':(16,2,'h'),'Float32':(32,3,'f')}[dtype]
    pack=lambda fmt,*v:struct.pack(endian+fmt,*v)
    geo=[1024,0,1,1 if epsg==3857 else 2,1025,0,1,1,(3072 if epsg==3857 else 2048),0,1,epsg,(3076 if epsg==3857 else 2054),0,1,(9001 if epsg==3857 else 9102)]
    tags={256:(4,[width]),257:(4,[height]),258:(3,[bits]),259:(3,[1]),262:(3,[1]),273:(4,[0]),277:(3,[1]),278:(4,[height]),279:(4,[width*height*bits//8]),339:(3,[sample]),33550:(12,[*spacing,0]),33922:(12,[0,0,0,*origin,0]),34735:(3,[1,1,0,4,*geo]),42112:(2,f'<GDALMetadata><Item name="UNITTYPE" sample="0" role="unittype">{units}</Item></GDALMetadata>\0'),42113:(2,str(nodata)+'\0')}
    start=8+2+12*len(tags)+4;payload=bytearray();records=[]
    for tag,(kind,values) in sorted(tags.items()):
        raw=values.encode('ascii') if kind==2 else pack(str(len(values))+{3:'H',4:'I',12:'d'}[kind],*values)
        record=pack('HHI',tag,kind,len(values))
        if len(raw)<=4: record+=raw.ljust(4,b'\0')
        else:
            if (start+len(payload))%8: payload.extend(b'\0'*(8-(start+len(payload))%8))
            record+=pack('I',start+len(payload));payload.extend(raw)
        records.append((tag,record))
    pixel_offset=start+len(payload)
    records=[pack('HHII',273,4,1,pixel_offset) if tag==273 else record for tag,record in records]
    return (b'II' if endian=='<' else b'MM')+pack('HIH',42,8,len(tags))+b''.join(records)+pack('I',0)+payload+pack(str(width*height)+fmt,*pixels)


def main():
    directory=Path(__file__).resolve().parents[1]/'examples/schemaxis/fixtures/gdal';directory.mkdir(parents=True,exist_ok=True)
    pixels=[10,11,12,13,14,15,20,21,-9999,23,24,25,30,31,32,33,34,35,40,41,42,43,-9999,45,50,51,52,53,54,55]
    (directory/'elevation.tif').write_bytes(tiff(pixels))
    (directory/'temperature.tif').write_bytes(tiff([273.25+i*.25 for i in range(30)],dtype='Float32',epsg=4326,units='K',nodata=-9999,endian='>',origin=(-97.5,50.5),spacing=(.1,.2)))


if __name__=='__main__':main()
