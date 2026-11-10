# Copyright (C) 2026 David L F Gaden
"""Independent bounded MSH 2.2 reader, tetrahedron checks and explicit VTU export.

No Gmsh imports. The supported interchange subset is ASCII linear triangles and
positive tetrahedra with one physical group per element and no orphan nodes.
"""
from collections import Counter
import math
from pathlib import Path
import shlex
import xml.etree.ElementTree as ET
from schemaxis.errors import fail

MAX_NODES = 50000
MAX_CELLS = 200000
MAX_BYTES = 64 * 1024 * 1024


def check(condition, message):
    if not condition:
        fail('VERIFICATION_FAILED', message)


def determinant(a, b, c, d):
    u, v, w = ([p[i]-a[i] for i in range(3)] for p in (b, c, d))
    return (u[0]*(v[1]*w[2]-v[2]*w[1]) - u[1]*(v[0]*w[2]-v[2]*w[0])
            + u[2]*(v[0]*w[1]-v[1]*w[0])) / 6


def read(path):
    path = Path(path)
    check(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_BYTES,
          'mesh must be a regular file within 64 MiB')
    lines = path.read_text(encoding='ascii').splitlines()
    sections = {}
    index = 0
    while index < len(lines):
        key = lines[index]
        check(key in ('$MeshFormat', '$PhysicalNames', '$Nodes', '$Elements') and key not in sections,
              'unexpected or repeated MSH section')
        end = '$End'+key[1:]
        try:
            stop = lines.index(end, index+1)
        except ValueError:
            fail('VERIFICATION_FAILED', 'unterminated MSH section')
        sections[key] = lines[index+1:stop]
        index = stop+1
    check(set(sections) == {'$MeshFormat', '$PhysicalNames', '$Nodes', '$Elements'}, 'MSH sections missing')
    check(sections['$MeshFormat'] == ['2.2 0 8'], 'expected ASCII MSH 2.2 double coordinates')
    def records(key, maximum):
        value = sections[key]
        check(bool(value), 'empty MSH section')
        count = int(value[0])
        check(0 < count <= maximum and len(value) == count+1, 'invalid MSH record count')
        return value[1:]
    groups = {}
    for line in records('$PhysicalNames', 14):
        values = shlex.split(line)
        check(len(values) == 3, 'invalid physical name')
        dim, tag = map(int, values[:2])
        check(dim in (2, 3) and tag > 0 and (dim, tag) not in groups, 'invalid physical group')
        groups[dim, tag] = values[2]
    check(sum(d == 3 for d, _ in groups) == 1 and any(d == 2 for d, _ in groups), 'require boundary groups and one volume group')
    nodes = {}
    for line in records('$Nodes', MAX_NODES):
        values = line.split()
        check(len(values) == 4, 'invalid node')
        tag = int(values[0]); xyz = tuple(map(float, values[1:]))
        check(tag > 0 and tag not in nodes and all(math.isfinite(v) for v in xyz), 'invalid node tag/coordinates')
        nodes[tag] = xyz
    cells = []; tags = set(); used = set(); unique = set()
    for line in records('$Elements', MAX_CELLS):
        values = list(map(int, line.split()))
        check(len(values) >= 8, 'invalid mesh element')
        tag, kind, count = values[:3]
        check(tag > 0 and tag not in tags and kind in (2, 4) and count == 2, 'only tagged linear triangles/tetrahedra are supported')
        dim, width = (2, 3) if kind == 2 else (3, 4)
        physical, entity = values[3:5]; vertices = tuple(values[5:])
        check(len(vertices) == width and len(set(vertices)) == width and all(v in nodes for v in vertices), 'invalid element connectivity')
        check((dim, physical) in groups and entity > 0, 'element has no declared physical group/entity')
        identity = (dim, tuple(sorted(vertices)))
        check(identity not in unique, 'duplicate mesh element')
        unique.add(identity); tags.add(tag); used.update(vertices)
        cells.append((dim, physical, vertices))
    check(used == set(nodes), 'unreferenced mesh nodes')
    return {'nodes': nodes, 'cells': cells, 'groups': groups}


def inspect(mesh):
    nodes, cells, groups = (mesh[key] for key in ('nodes', 'cells', 'groups'))
    faces = Counter(); boundary = set(); volumes = []; areas = {}; group_nodes = {}; group_counts = Counter()
    for dim, physical, vertices in cells:
        if dim == 2:
            boundary.add(tuple(sorted(vertices)))
            a,b,c = (nodes[i] for i in vertices)
            u,v = ([p[i]-a[i] for i in range(3)] for p in (b,c))
            area = math.sqrt(sum((u[i]*v[j]-u[j]*v[i])**2 for i,j in ((0,1),(1,2),(2,0))))/2
            check(math.isfinite(area) and area > 0, 'degenerate boundary triangle')
            areas.setdefault(physical,[]).append(area)
            group_nodes.setdefault(physical,set()).update(vertices)
            group_counts[physical] += 1
        else:
            volume = determinant(*(nodes[i] for i in vertices))
            check(math.isfinite(volume) and volume > 0, 'inverted or degenerate tetrahedron')
            volumes.append(volume)
            for i in range(4):
                faces[tuple(sorted(vertices[:i]+vertices[i+1:]))] += 1
    check(bool(volumes) and bool(boundary), 'missing volume or boundary elements')
    check(all(count in (1, 2) for count in faces.values()), 'non-manifold tetrahedral face')
    check(boundary == {face for face, count in faces.items() if count == 1}, 'boundary triangles do not cover the exterior tetrahedral faces')
    # Every boundary edge belongs to exactly two triangles in a closed manifold.
    edges = Counter()
    for a, b, c in boundary:
        edges.update((tuple(sorted(pair)) for pair in ((a,b), (b,c), (c,a))))
    check(all(count == 2 for count in edges.values()), 'boundary is not a closed manifold')
    bounds = [f(p[k] for p in nodes.values()) for f in (min, max) for k in range(3)]
    check(set(areas) == {tag for dim,tag in groups if dim == 2}, 'empty physical boundary group')
    return {'nodes': len(nodes), 'tetrahedra': len(volumes), 'triangles': len(boundary),
            'volume': math.fsum(volumes), 'minimumVolume': min(volumes), 'bounds': bounds,
            'groups': [{'dimension': dim, 'tag': tag, 'name': name}
                       for (dim, tag), name in sorted(groups.items())],
            'boundaryGroups': [{'tag':tag,'name':groups[2,tag],'triangles':group_counts[tag],
                'area':math.fsum(areas[tag]),
                'bounds':[f(nodes[n][k] for n in group_nodes[tag]) for f in (min,max) for k in range(3)]}
                for tag in sorted(areas)]}


def verify_face_groups(data, selectors, cylinders=()):
    """Classify every boundary triangle from coordinates, without native face IDs.

    Planes take precedence; a triangle on no plane is a wall of the one cylinder
    group whose radius it matches with axial extent, and anything else is remainder.
    """
    from . import cylinders as walls, groups
    for dim, physical, vertices in data['cells']:
        if dim != 2:
            continue
        points = [data['nodes'][n] for n in vertices]
        matches = [groups.plane_tag(i) for i,g in enumerate(selectors)
                   if all(abs(p['xyz'.index(g['axis'])]-g['coordinate']) <= g['tolerance'] for p in points)]
        check(len(matches) <= 1, 'boundary triangle matches overlapping face selectors')
        wall = walls.classify(points, matches, cylinders)
        expected = matches[0] if matches else groups.REMAINDER_TAG if wall is None else groups.plane_tag(len(selectors)+wall)
        check(physical == expected, 'physical face tag differs from authored plane or cylinder selector; one possible cause is a flat face inscribed in a selected cylinder, which needs a finer mesh' if cylinders
              else 'physical face tag differs from authored plane selector')


def write_vtu(path, mesh, dimension):
    """Publish one explicit cell dimension; physical IDs remain per-cell data."""
    selected = [(physical, vertices) for dim, physical, vertices in mesh['cells'] if dim == dimension]
    used = sorted({n for _, vertices in selected for n in vertices})
    indices = {tag: index for index, tag in enumerate(used)}
    width, kind = (4, 10) if dimension == 3 else (3, 5)
    root = ET.Element('VTKFile', type='UnstructuredGrid', version='0.1', byte_order='LittleEndian')
    piece = ET.SubElement(ET.SubElement(root, 'UnstructuredGrid'), 'Piece', NumberOfPoints=str(len(used)), NumberOfCells=str(len(selected)))
    def array(parent, name, scalar, values, components=None):
        attrs = {'type': scalar, 'Name': name, 'format': 'ascii'}
        if components: attrs['NumberOfComponents'] = str(components)
        ET.SubElement(parent, 'DataArray', attrs).text = ' '.join(map(str, values))
    array(ET.SubElement(piece, 'Points'), 'Points', 'Float64', (v for n in used for v in mesh['nodes'][n]), 3)
    cell = ET.SubElement(piece, 'Cells')
    array(cell, 'connectivity', 'Int64', (indices[n] for _, vertices in selected for n in vertices))
    array(cell, 'offsets', 'Int64', (width*(i+1) for i in range(len(selected))))
    array(cell, 'types', 'UInt8', (kind for _ in selected))
    cell_data = ET.SubElement(piece, 'CellData')
    array(cell_data, 'physicalTag', 'Int32', (p for p, _ in selected))
    if dimension == 3:
        from .quality import cells
        measured = list(cells(mesh))
        for key in ('meanRatio', 'maximumEdgeLength', 'volume'):
            array(cell_data, key, 'Float64', (cell[key] for cell in measured))
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def verify_vtu(path, mesh, dimension):
    check(Path(path).stat().st_size <= MAX_BYTES, 'VTU exceeds size limit')
    piece = ET.parse(path).getroot().find('UnstructuredGrid/Piece')
    check(piece is not None, 'missing VTU piece')
    selected = [(p, v) for d, p, v in mesh['cells'] if d == dimension]
    used = sorted({n for _, vertices in selected for n in vertices})
    check(piece.attrib == {'NumberOfPoints': str(len(used)), 'NumberOfCells': str(len(selected))}, 'VTU size differs')
    def values(parent, name, cast):
        found = piece.findall(parent+f'/DataArray[@Name="{name}"]')
        check(len(found) == 1 and found[0].get('format') == 'ascii', 'VTU array missing or repeated')
        return [cast(v) for v in (found[0].text or '').split()]
    coords = values('Points', 'Points', float)
    check(coords == [v for n in used for v in mesh['nodes'][n]], 'VTU coordinates differ')
    connectivity = values('Cells', 'connectivity', int)
    width, kind = (4, 10) if dimension == 3 else (3, 5)
    check(values('Cells', 'offsets', int) == [width*(i+1) for i in range(len(selected))], 'VTU offsets differ')
    check(values('Cells', 'types', int) == [kind]*len(selected), 'VTU element types differ')
    check(len(connectivity) == width*len(selected) and all(0 <= i < len(used) for i in connectivity), 'VTU connectivity invalid')
    actual = [tuple(used[i] for i in connectivity[offset:offset+width]) for offset in range(0, len(connectivity), width)]
    check(actual == [v for _, v in selected], 'VTU topology differs')
    check(values('CellData', 'physicalTag', int) == [p for p, _ in selected], 'VTU physical tags differ')
    if dimension == 3:
        from .quality import cells
        measured = list(cells(mesh))
        for key in ('meanRatio', 'maximumEdgeLength', 'volume'):
            check(values('CellData', key, float) == [cell[key] for cell in measured], 'VTU quality differs: '+key)
