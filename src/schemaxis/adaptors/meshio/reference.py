# Copyright (C) 2026 David L F Gaden
"""Independent standard-library readers for a deliberately closed ASCII subset.

These readers do not use meshio, its cell maps or its serialization code.
The canonical representation preserves point order and flattened cell order.
"""
import copy
import math
import re
import struct
import xml.etree.ElementTree as ET

MAX_ITEMS = 100000
TYPES = {5: ('triangle', 3), 10: ('tetra', 4), 12: ('hexahedron', 8)}
NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}\Z')
FLOATS = {'Float32', 'Float64', 'float', 'double'}
INTS = {'Int8', 'UInt8', 'Int16', 'UInt16', 'Int32', 'UInt32', 'Int64', 'UInt64', 'char', 'unsigned_char', 'short', 'unsigned_short', 'int', 'unsigned_int', 'long', 'unsigned_long', 'long_long', 'unsigned_long_long'}
INTEGER_BITS = {'char': 8, 'short': 16, 'int': 32, 'long': 64, 'long_long': 64}


def demand(condition, message):
    if not condition:
        raise ValueError(message)


# VTK/VTU ASCII separates tokens with space, tab, CR or LF and uses plain
# decimal syntax. Python's int()/float()/str.split() also accept digit-group
# underscores and further control/Unicode whitespace, which no VTK reader
# gives that meaning, so the oracle tokenises and converts strictly itself.
SEPARATORS = re.compile(r'[ \t\r\n]+')
INTEGER = re.compile(r'[+-]?[0-9]+\Z')
DECIMAL = re.compile(r'[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z')


def tokens(text):
    return [v for v in SEPARATORS.split(text) if v]


def integer(text):
    # Whitespace around an XML attribute value is formatting.
    value = text.strip(' \t\r\n')
    demand(INTEGER.match(value), 'plain decimal integer required')
    return int(value)


def number(text, dtype):
    if dtype in INTS: return integer(text)
    demand(DECIMAL.match(text), 'plain decimal number required')
    return float(text)


def numbers(text, dtype):
    demand(dtype in FLOATS | INTS, 'unsupported numeric type')
    values = tokens(text)
    demand(len(values) <= MAX_ITEMS * 8, 'numeric array exceeds bound')
    result = [number(v, dtype) for v in values]
    demand(all(math.isfinite(v) and abs(v) <= 2**53 for v in result), 'finite values within exact integer range required')
    if dtype in INTS:
        unsigned = dtype.startswith(('U', 'unsigned_'))
        bits = int(re.search(r'\d+', dtype)[0]) if re.search(r'\d+', dtype) else INTEGER_BITS[dtype.removeprefix('unsigned_')]
        lower, upper = (0, 2**bits-1) if unsigned else (-2**(bits-1), 2**(bits-1)-1)
        demand(all(lower <= v <= upper for v in result), 'integer value exceeds declared storage type')
    if dtype in ('float', 'Float32'):
        try:
            result = [struct.unpack('>f', struct.pack('>f', v))[0] for v in result]
        except OverflowError:
            raise ValueError('Float32 overflow') from None
    return result


def rows(values, components, count):
    demand(components in (1, 3) and len(values) == components * count, 'scalar or three-vector tuple count differs')
    return [values[i:i + components] for i in range(0, len(values), components)]


def vtu(data):
    # Restrict the XML byte encoding as well as its numeric DataArray format;
    # otherwise UTF-16 declarations can evade byte-level DTD/entity refusal.
    data.decode('ascii')
    demand(b'\x00' not in data, 'NUL/UTF-16 XML unsupported; use ASCII XML')
    # XML comments are formatting (meshio emits a writer-version comment).
    # Strip only well-formed comments before refusing every other declaration.
    clean = re.sub(br'<!--(?:(?!--).)*-->', b'', data, flags=re.S)
    demand(b'<!' not in clean and b'&' not in clean and len(data) <= 32*1024*1024, 'DTD/entities and oversized XML unsupported')
    demand(clean.count(b'<') <= 256, 'XML structural element budget exceeded')
    try:
        root = ET.fromstring(clean)
    except ET.ParseError as error:
        raise ValueError('invalid VTU XML: '+str(error)) from None
    for element in root.iter():
        demand(not (element.tail or '').strip(), 'non-whitespace XML tail unsupported')
        if element.tag != 'DataArray':
            demand(not (element.text or '').strip(), 'non-whitespace text outside DataArray unsupported')
    demand(root.tag == 'VTKFile' and set(root.attrib) <= {'type', 'version', 'byte_order', 'header_type'} and root.get('type') == 'UnstructuredGrid', 'single ASCII UnstructuredGrid required')
    demand([e.tag for e in root] == ['UnstructuredGrid'], 'extra root sections unsupported')
    grid = root[0]
    demand(not grid.attrib and [e.tag for e in grid] == ['Piece'], 'single Piece required')
    piece = grid[0]
    demand(set(piece.attrib) == {'NumberOfPoints', 'NumberOfCells'}, 'unexpected Piece attributes')
    np, nc = integer(piece.get('NumberOfPoints', '')), integer(piece.get('NumberOfCells', ''))
    demand(1 <= np <= MAX_ITEMS and 1 <= nc <= MAX_ITEMS, 'point/cell count exceeds bound')
    demand(len({e.tag for e in piece}) == len(piece) and {e.tag for e in piece} <= {'Points', 'Cells', 'PointData', 'CellData'}, 'unsupported or duplicate mesh sections')
    def array(e):
        demand(e.tag == 'DataArray' and not len(e) and set(e.attrib) <= {'type', 'Name', 'NumberOfComponents', 'format'} and e.get('format') == 'ascii', 'only inline ASCII DataArray supported')
        return numbers(e.text or '', e.get('type'))
    points, cells = piece.find('Points'), piece.find('Cells')
    demand(points is not None and cells is not None and not points.attrib and not cells.attrib and len(points) == 1, 'Points/Cells required')
    demand(points[0].get('NumberOfComponents') == '3', 'three point coordinates required')
    xyz = rows(array(points[0]), 3, np)
    demand(len(cells) == 3 and {e.get('Name') for e in cells} == {'connectivity', 'offsets', 'types'}, 'three topology arrays required')
    topology = {}
    for e in cells:
        demand(e.get('type') in INTS and e.get('NumberOfComponents', '1') == '1', 'integer scalar topology required')
        topology[e.get('Name')] = array(e)
    demand(len(topology['offsets']) == nc and len(topology['types']) == nc, 'cell tuple count differs')
    connections = []; start = 0
    for end, cell_type in zip(topology['offsets'], topology['types']):
        demand(cell_type in TYPES, 'only triangle/tetra/hexahedron cells supported')
        label, size = TYPES[cell_type]
        demand(end == start + size, 'cell offsets differ from supported arity')
        connections.append([label, topology['connectivity'][start:end]]); start = end
    demand(start == len(topology['connectivity']), 'unused connectivity entries')
    result = {'points': xyz, 'cells': connections, 'pointData': {}, 'cellData': {}}
    for tag, key, count in [('PointData', 'pointData', np), ('CellData', 'cellData', nc)]:
        section = piece.find(tag)
        if section is None: continue
        demand(not section.attrib and len(section) <= 16, 'data attributes or excessive arrays unsupported')
        for e in section:
            name = e.get('Name', '')
            demand(NAME.fullmatch(name) and name not in result[key], 'unique simple array names required')
            result[key][name] = rows(array(e), integer(e.get('NumberOfComponents', '1')), count)
    return validate(result)


def vtk(data):
    # Only CR/LF end lines; splitlines() also breaks on VT, FF and FS/GS/RS.
    lines = re.split(r'\r\n|\n|\r', data.decode('ascii'))
    demand(len(lines) >= 5 and lines[0] == '# vtk DataFile Version 4.2' and lines[2] == 'ASCII' and lines[3] == 'DATASET UNSTRUCTURED_GRID', 'legacy VTK 4.2 ASCII unstructured grid required')
    stream = iter(tokens(' '.join(lines[4:])))
    def take():
        try: return next(stream)
        except StopIteration: raise ValueError('truncated legacy VTK') from None
    def count():
        n = integer(take()); demand(0 <= n <= MAX_ITEMS*9, 'count exceeds bound'); return n
    demand(take() == 'POINTS', 'POINTS section required')
    np, dtype = count(), take()
    xyz = rows(numbers(' '.join(take() for _ in range(3*np)), dtype), 3, np)
    demand(take() == 'CELLS', 'CELLS section required')
    nc, size = count(), count(); raw = []; consumed = 0
    for _ in range(nc):
        arity = count(); demand(arity in (3, 4, 8), 'only triangle/tetra/hexahedron connectivity supported')
        raw.append([integer(take()) for _ in range(arity)]); consumed += arity+1
    demand(size == consumed and take() == 'CELL_TYPES' and count() == nc, 'cell topology count differs')
    connections = []
    for indices in raw:
        t = integer(take()); demand(t in TYPES and TYPES[t][1] == len(indices), 'unsupported cell type/arity')
        connections.append([TYPES[t][0], indices])
    result = {'points': xyz, 'cells': connections, 'pointData': {}, 'cellData': {}}
    seen = set()
    for section in stream:
        demand(section in ('POINT_DATA', 'CELL_DATA') and section not in seen, 'only point/cell FIELD arrays supported')
        seen.add(section); n = count(); key = 'pointData' if section == 'POINT_DATA' else 'cellData'
        demand(n == (np if key == 'pointData' else nc) and take() == 'FIELD' and take() == 'FieldData', 'data tuple association differs')
        arrays = count(); demand(arrays <= 16, 'too many data arrays')
        for _ in range(arrays):
            name, components, tuples, dtype = take(), count(), count(), take()
            demand(NAME.fullmatch(name) and name not in result[key] and components in (1, 3) and tuples == n, 'array names/shapes differ')
            result[key][name] = rows(numbers(' '.join(take() for _ in range(n*components)), dtype), components, n)
    return validate(result)


# VTK_HEXAHEDRON corners on the reference cube [-1,1]^3. The first
# face is 0,1,2,3; 4,5,6,7 is the opposite face, with matching edges.
HEX_CORNERS = ((-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
               (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1))
GAUSS = tuple((x,y,z) for x in (-1/math.sqrt(3),1/math.sqrt(3))
              for y in (-1/math.sqrt(3),1/math.sqrt(3))
              for z in (-1/math.sqrt(3),1/math.sqrt(3)))
HEX_SAMPLES = HEX_CORNERS + ((0,0,0),) + GAUSS


def hex_jacobian(points, coordinate):
    # Differentiate the eight trilinear shape functions. Translate first to
    # avoid cancellation of a large origin in a small cell's derivatives.
    relative = [[v-a for v,a in zip(p,points[0])] for p in points]
    x,y,z = coordinate
    columns = [[sum(p[axis] * derivative for p, derivative in zip(relative, weights))
                for axis in range(3)] for weights in (
        [a*(1+b*y)*(1+c*z)/8 for a,b,c in HEX_CORNERS],
        [b*(1+a*x)*(1+c*z)/8 for a,b,c in HEX_CORNERS],
        [c*(1+a*x)*(1+b*y)/8 for a,b,c in HEX_CORNERS])]
    u,v,w = columns
    return (u[0]*(v[1]*w[2]-v[2]*w[1])
            -u[1]*(v[0]*w[2]-v[2]*w[0])
            +u[2]*(v[0]*w[1]-v[1]*w[0]))


def validate_hexahedron(points):
    scale = max(math.dist(points[0], point) for point in points)
    demand(scale > 0 and all(hex_jacobian(points, q) > 1e-12*scale**3
                            for q in HEX_SAMPLES),
           'nonpositive/near-degenerate hexahedron sampled Jacobian')


def hex_volume(points):
    # det(J) has degree at most two in each coordinate. The tensor-product
    # two-point Gauss rule integrates its signed trilinear volume exactly.
    return sum(hex_jacobian(points, q) for q in GAUSS)


def validate(mesh):
    demand(isinstance(mesh, dict) and set(mesh) == {'points', 'cells', 'pointData', 'cellData'}, 'canonical mesh fields differ')
    points, cells = mesh['points'], mesh['cells']
    demand(isinstance(points, list) and isinstance(cells, list) and 1 <= len(points) <= MAX_ITEMS and 1 <= len(cells) <= MAX_ITEMS, 'mesh counts exceed bounds')
    for point in points:
        demand(isinstance(point, list) and len(point) == 3 and all(type(v) in (int, float) and math.isfinite(v) and abs(v) <= 1e9 for v in point), 'finite bounded XYZ required')
    for cell in cells:
        demand(isinstance(cell, list) and len(cell) == 2 and cell[0] in ('triangle', 'tetra', 'hexahedron'), 'triangle/tetra/hexahedron required')
        indices = cell[1]; demand(isinstance(indices, list) and len(indices) == {'triangle': 3, 'tetra': 4, 'hexahedron': 8}[cell[0]] and len(set(indices)) == len(indices) and all(type(i) is int and 0 <= i < len(points) for i in indices), 'connectivity invalid')
        if cell[0] == 'hexahedron':
            validate_hexahedron([points[i] for i in indices])
            continue
        a, b, c = [points[i] for i in indices[:3]]
        u, v = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
        cross = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        scale = max(math.dist(a, points[i]) for i in indices)
        measure = math.sqrt(sum(x*x for x in cross)) if cell[0] == 'triangle' else sum(cross[i]*(points[indices[3]][i]-a[i]) for i in range(3))
        demand(scale > 0 and measure > 1e-12*scale**(2 if cell[0] == 'triangle' else 3), 'degenerate triangle or nonpositive/near-degenerate tetra orientation')
    for key, count in [('pointData', len(points)), ('cellData', len(cells))]:
        fields = mesh[key]; demand(isinstance(fields, dict) and len(fields) <= 16, 'bounded named data arrays required')
        for name, values in fields.items():
            demand(NAME.fullmatch(name) and isinstance(values, list) and len(values) == count and values and isinstance(values[0], list), 'data array name/count differs')
            width = len(values[0]); demand(width in (1, 3), 'scalar/three-vector data required')
            for row in values:
                demand(isinstance(row, list) and len(row) == width and all(type(v) in (int, float) and math.isfinite(v) and abs(v) <= 2**53 for v in row), 'finite bounded data required')
    return mesh


def parse(data, format):
    return vtu(data) if format == 'vtu' else vtk(data)


def scaled(mesh, factor):
    result = copy.deepcopy(mesh)
    result['points'] = [[v*factor for v in point] for point in mesh['points']]
    return validate(result)


def compare(expected, actual):
    validate(actual)
    demand(expected['cells'] == actual['cells'], 'ordered topology changed')
    for key in ('points', 'pointData', 'cellData'):
        def equal(a, b):
            if isinstance(a, dict): return isinstance(b, dict) and a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
            if isinstance(a, list): return isinstance(b, list) and len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
            return type(b) in (int, float) and (a == b if type(a) is int else math.isclose(a, b, rel_tol=1e-11, abs_tol=1e-14))
        demand(equal(expected[key], actual[key]), key+' values/order changed')
    # Coordinate-relative tolerances alone are insufficient for small cells at
    # a large origin. Also retain oriented area vectors and signed volumes.
    for kind, indices in expected['cells']:
        if kind == 'hexahedron':
            for q in HEX_SAMPLES:
                a = hex_jacobian([expected['points'][i] for i in indices], q)
                b = hex_jacobian([actual['points'][i] for i in indices], q)
                demand(abs(a-b) <= 1e-8*abs(a), 'hexahedron Jacobian changed beyond relative 1e-8')
            continue
        measures = []
        for mesh in (expected, actual):
            a, b, c = [mesh['points'][i] for i in indices[:3]]
            u, v = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
            cross = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
            measures.append(cross if kind == 'triangle' else [sum(cross[i]*(mesh['points'][indices[3]][i]-a[i]) for i in range(3))])
        original, changed = measures
        scale = math.sqrt(sum(v*v for v in original))
        error = math.sqrt(sum((a-b)**2 for a,b in zip(original, changed)))
        demand(error <= 1e-8*scale, 'oriented area/volume changed beyond relative 1e-8')


def summary(mesh):
    tetra = []; hexa = []
    for kind, ids in mesh['cells']:
        if kind == 'hexahedron':
            hexa.append(hex_volume([mesh['points'][i] for i in ids]))
        if kind != 'tetra': continue
        a, b, c, d = [mesh['points'][i] for i in ids]
        u, v, w = [[p[i]-a[i] for i in range(3)] for p in (b, c, d)]
        tetra.append((u[0]*(v[1]*w[2]-v[2]*w[1])-u[1]*(v[0]*w[2]-v[2]*w[0])+u[2]*(v[0]*w[1]-v[1]*w[0]))/6)
    return {'points': len(mesh['points']), 'cells': len(mesh['cells']), 'cellTypes': sorted({c[0] for c in mesh['cells']}), 'bounds': [[min(p[i] for p in mesh['points']), max(p[i] for p in mesh['points'])] for i in range(3)], 'tetraVolumes': tetra, 'hexahedronVolumes': hexa, 'pointArrays': sorted(mesh['pointData']), 'cellArrays': sorted(mesh['cellData'])}
