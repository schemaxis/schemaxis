#!/usr/bin/env python3
"""Regenerate literal RGBA grids; no native program or image generation service."""
from pathlib import Path
import struct
import zlib

ROOT=Path(__file__).resolve().parents[1]
GRID=[[(255,0,0,255),(0,255,0,128),(17,33,65,0)],[(0,0,255,255),(255,255,0,64),(0,255,255,255)]]


def fixture(rows,rgba=True,tagged=True):
    def chunk(k,v):return struct.pack('>I',len(v))+k+v+struct.pack('>I',zlib.crc32(k+v)&0xffffffff)
    raw=b''.join(b'\0'+b''.join(bytes(p if rgba else p[:3]) for p in row) for row in rows)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',len(rows[0]),len(rows),8,6 if rgba else 2,0,0,0))+(chunk(b'sRGB',b'\0') if tagged else b'')+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')


if __name__=='__main__':
    p=ROOT/'examples/schemaxis/fixtures/imagemagick';p.mkdir(parents=True,exist_ok=True)
    (p/'grid.png').write_bytes(fixture(GRID))
    (p/'grid-changed.png').write_bytes(fixture([[(255,255,255,255),*GRID[0][1:]],GRID[1]]))
    (p/'grid-rgb.png').write_bytes(fixture(GRID,rgba=False))
