# Copyright (C) 2026 David L F Gaden
"""Host-safe, bounded comparison of oriented float32 STL triangles."""
import hashlib
import math
import struct
from schemaxis.errors import fail
LIMIT=1_000_000


def triangle(vertices):
    rounded=[tuple(0.0 if x==0 else x for x in struct.unpack('<3f',struct.pack('<3f',*v))) for v in vertices]
    if not all(math.isfinite(x) for vertex in rounded for x in vertex):fail('INVALID_GEOMETRY','STL coordinates must be finite')
    # Rotation of a triangle's starting vertex preserves winding.
    return min(tuple(rounded[i:]+rounded[:i]) for i in range(3))


def digest(triangles):
    triangles=sorted(triangles)
    if not 0<len(triangles)<=LIMIT:fail('RESOURCE_BUDGET_EXCEEDED','STL export requires 1 to one million triangles')
    sha=hashlib.sha256()
    for vertices in triangles:sha.update(struct.pack('<9f',*(x for vertex in vertices for x in vertex)))
    return {'triangles':len(triangles),'orientedTrianglesSha256':sha.hexdigest()}


def file_snapshot(path):
    with path.open('rb') as stream:
        header=stream.read(84)
        if len(header)!=84:fail('VERIFICATION_FAILED','STL header is incomplete')
        count=struct.unpack('<I',header[80:84])[0]
        if not 0<count<=LIMIT or path.stat().st_size!=84+50*count:fail('VERIFICATION_FAILED','STL triangle count or file size differs')
        triangles=[]
        for _ in range(count):
            values=struct.unpack('<12fH',stream.read(50))
            if not all(math.isfinite(v) for v in values[:12]):fail('VERIFICATION_FAILED','STL contains nonfinite data')
            triangles.append(triangle([values[3:6],values[6:9],values[9:12]]))
    return digest(triangles)
