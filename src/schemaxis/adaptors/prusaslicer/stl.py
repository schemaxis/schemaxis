# Copyright (C) 2026 David L F Gaden
"""Independent bounded STL reading; no repair, no native slicer code.

Triangle winding is authoritative for orientation; stored facet normals are
ignored. Edge pairing proves a closed, consistently oriented edge graph only;
it does not prove the absence of self-intersections.
"""
import math
import re
import struct

MAX_BYTES = 16*1024*1024
MAX_TRIANGLES = 100000


def _ascii(data, problem):
    try:
        text = data.decode('ascii')
    except UnicodeError:
        problem('ASCII STL must contain only ASCII text')
    tokens = text.split()
    if len(tokens) < 2 or tokens[0] != 'solid':
        problem('STL is neither a size-consistent binary file nor ASCII text starting with solid')
    triangles = []
    index = 1
    # The solid name is optional free text; facets start at the first keyword.
    while index < len(tokens) and tokens[index] not in ('facet', 'endsolid'):
        index += 1
    while index < len(tokens) and tokens[index] == 'facet':
        if tokens[index+1:index+2] != ['normal'] or tokens[index+5:index+7] != ['outer', 'loop']:
            problem('malformed ASCII facet header', facet=len(triangles))
        index += 7
        vertices = []
        for _ in range(3):
            if tokens[index:index+1] != ['vertex']:
                problem('ASCII facets need exactly three vertices', facet=len(triangles))
            try:
                vertices.append(tuple(float(value) for value in tokens[index+1:index+4]))
            except ValueError:
                problem('ASCII vertex coordinates must be numbers', facet=len(triangles))
            if len(vertices[-1]) != 3:
                problem('ASCII vertex needs three coordinates', facet=len(triangles))
            index += 4
        if tokens[index:index+2] != ['endloop', 'endfacet']:
            problem('ASCII facets need exactly three vertices', facet=len(triangles))
        index += 2
        triangles.append(tuple(vertices))
        if len(triangles) > MAX_TRIANGLES:
            problem('triangle count exceeds the bounded slice budget', maximum=MAX_TRIANGLES)
    if index >= len(tokens) or tokens[index] != 'endsolid':
        problem('ASCII STL must end with endsolid after its facets')
    # Only the optional solid name may follow endsolid, on the same line.
    # A second solid or trailing facets would be geometry this check ignored.
    end = re.search(r'(?m)^[ \t]*endsolid\b[^\n]*$', text)
    if text.count('endsolid') != 1 or end is None or text[end.end():].strip():
        problem('ASCII STL must contain exactly one solid with nothing after endsolid except its name')
    return 'ascii', triangles


def _binary(data, count):
    triangles = []
    for offset in range(84, 84+50*count, 50):
        values = struct.unpack_from('<12f', data, offset)
        triangles.append((values[3:6], values[6:9], values[9:12]))
    return 'binary', triangles


def read(data, problem):
    """Return bounded mesh facts. ``problem(message, **observed)`` must raise."""
    if len(data) > MAX_BYTES:
        problem('STL exceeds the 16 MiB input budget', bytes=len(data))
    count = struct.unpack_from('<I', data, 80)[0] if len(data) >= 84 else None
    if count is not None and len(data) == 84 + 50*count:
        if count > MAX_TRIANGLES:
            problem('triangle count exceeds the bounded slice budget', maximum=MAX_TRIANGLES, observed=count)
        encoding, triangles = _binary(data, count)
    else:
        encoding, triangles = _ascii(data, problem)
    if len(triangles) < 4:
        problem('a closed solid needs at least four triangles', triangles=len(triangles))
    lower = [math.inf]*3
    upper = [-math.inf]*3
    volumes, areas = [], []
    directed = {}
    # Signed tetrahedra use a mesh-local reference vertex so translating the
    # mesh far from the origin does not cancel the enclosed volume.
    origin = triangles[0][0]
    for number, triangle in enumerate(triangles):
        for vertex in triangle:
            if not all(math.isfinite(value) and abs(value) <= 1e6 for value in vertex):
                problem('vertex coordinates must be finite and at most 1e6 in magnitude', facet=number)
            for axis in range(3):
                lower[axis] = min(lower[axis], vertex[axis])
                upper[axis] = max(upper[axis], vertex[axis])
        a, b, c = triangle
        u = [b[i]-a[i] for i in range(3)]
        v = [c[i]-a[i] for i in range(3)]
        cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
        twice = math.sqrt(sum(value*value for value in cross))
        if twice <= 1e-12 or len({a, b, c}) != 3:
            problem('degenerate zero-area triangles are not repaired by this adaptor', facet=number)
        areas.append(twice/2)
        p, q, r = ([vertex[i]-origin[i] for i in range(3)] for vertex in (a, b, c))
        volumes.append((p[0]*(q[1]*r[2]-q[2]*r[1]) - p[1]*(q[0]*r[2]-q[2]*r[0]) + p[2]*(q[0]*r[1]-q[1]*r[0]))/6)
        for edge in ((a, b), (b, c), (c, a)):
            if edge in directed:
                problem('mesh is not consistently oriented: a directed edge is repeated', facet=number)
            directed[edge] = number
    volume, area = math.fsum(volumes), math.fsum(areas)
    for (a, b), number in directed.items():
        if (b, a) not in directed:
            problem('mesh is not closed: an edge has no oppositely oriented neighbour', facet=number)
    # One connected shell: PrusaSlicer would treat several shells as several
    # parts, outside this single-object scope.
    parent = {}
    def find(vertex):
        while parent.setdefault(vertex, vertex) != vertex:
            parent[vertex] = parent[parent[vertex]]
            vertex = parent[vertex]
        return vertex
    for a, b, c in triangles:
        for other in (b, c):
            parent[find(other)] = find(a)
    if len({find(vertex) for vertex in parent}) != 1:
        problem('mesh must be one connected closed shell')
    if volume <= 0:
        problem('mesh encloses no positive volume; facets may be inverted', volume=volume)
    size = [upper[i]-lower[i] for i in range(3)]
    if min(size) <= 0:
        problem('mesh must have a positive extent along every axis', size=size)
    return {'encoding': encoding, 'triangles': len(triangles), 'vertices': len({p for t in triangles for p in t}),
            'minimum': lower, 'maximum': upper, 'size': size, 'volume': volume, 'area': area}
