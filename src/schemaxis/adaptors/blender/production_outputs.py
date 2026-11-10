"""Typed frame publications and independent, dependency-free exchange checks.

Exchange publications contain evaluated geometry at one frame. The native blend
retains the editable scene; neutral files do not promise its procedural history.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import struct

from schemaxis.errors import fail
from schemaxis.schema import NAME, object_schema

FORMATS = {'glb': 'glb', 'obj': 'obj', 'ply': 'ply', 'stl': 'stl', 'usd': 'usda'}
LIMIT = 1_000_000
MAX_FILE = 256 * 1024 * 1024
METRES = {'metres': 1.0, 'millimetres': .001, 'centimetres': .01,
          'inches': .0254, 'feet': .3048}


def output_schema_properties():
    frame = {'type': 'integer', 'minimum': 0, 'maximum': 1_000_000}
    return {
        'exports': {'type': 'array', 'maxItems': 32, 'items': object_schema({
            'id': NAME, 'format': {'enum': list(FORMATS)},
            'objects': {'type': 'array', 'items': NAME, 'minItems': 1,
                        'maxItems': 1000, 'uniqueItems': True},
            'frame': frame}, ['id', 'format', 'objects'])},
        'renderFrames': {'type': 'array', 'items': frame, 'maxItems': 1000,
                         'uniqueItems': True},
        'camera': NAME}


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validate_outputs(production, object_ids, where='production'):
    """Normalise only output fields, without altering the caller's declarations."""
    start, end = production.get('frameStart', 1), production.get('frameEnd', 250)
    current = production.get('currentFrame', start)
    if not all(_integer(x) and 0 <= x <= 1_000_000 for x in (start, end, current)) or not start <= current <= end:
        fail('INVALID_TIMELINE', 'frame range and currentFrame must be ordered bounded integers', where)
    records, seen = [], set()
    exports = production.get('exports', [])
    if not isinstance(exports, list) or len(exports) > 32:
        fail('INVALID_PUBLICATION', 'exports must contain at most 32 frame publications', where + '/exports')
    for i, item in enumerate(exports):
        at = f'{where}/exports/{i}'
        if not isinstance(item, dict) or set(item) - {'id', 'format', 'objects', 'frame'}:
            fail('INVALID_PUBLICATION', 'unknown export fields; declare id, format, objects and optional frame', at)
        identity = item.get('id')
        if not isinstance(identity, str) or not re.fullmatch(NAME['pattern'], identity) or identity in seen:
            fail('INVALID_PUBLICATION', 'export IDs must be valid unique names', at + '/id')
        if not isinstance(item.get('format'), str) or item['format'] not in FORMATS:
            fail('UNSUPPORTED_PUBLICATION', 'choose glb, obj, ply, stl or usd evaluated geometry', at + '/format')
        objects = item.get('objects')
        if (not isinstance(objects, list) or not 1 <= len(objects) <= 1000
                or any(not isinstance(x, str) or x not in object_ids for x in objects)
                or len(set(objects)) != len(objects)):
            fail('INVALID_REFERENCE', 'export objects must be unique declared object IDs', at + '/objects')
        frame = item.get('frame', current)
        if not _integer(frame) or not start <= frame <= end:
            fail('INVALID_TIMELINE', 'export frame must lie in the production frame range', at + '/frame')
        seen.add(identity)
        records.append({'id': identity, 'format': item['format'], 'objects': list(objects), 'frame': frame})
    frames = production.get('renderFrames', [])
    if (not isinstance(frames, list) or len(frames) > 1000
            or any(not _integer(x) or not start <= x <= end for x in frames)
            or len(set(frames)) != len(frames)):
        fail('INVALID_TIMELINE', 'renderFrames must be unique integers in the production frame range', where + '/renderFrames')
    result = {'exports': records, 'renderFrames': list(frames)}
    if 'camera' in production:
        if not isinstance(production['camera'], str) or production['camera'] not in object_ids:
            fail('INVALID_REFERENCE', 'camera must name a declared camera object', where + '/camera')
        result['camera'] = production['camera']
    return result


def output_count(production):
    return len(production.get('exports', [])) + len(production.get('renderFrames', []))


def output_jobs(production, prefix):
    if not isinstance(prefix, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', prefix):
        fail('INVALID_PUBLICATION', 'publication prefix must be a simple file stem')
    exports = [{'id': e['id'], 'format': e['format'], 'objects': e['objects'],
                'frame': e.get('frame', production.get('currentFrame', production.get('frameStart', 1))),
                'kind': 'asset' if e['format'] in ('glb', 'usd') else 'geometry',
                'name': f"{prefix}-export-{e['id']}.{FORMATS[e['format']]}"}
               for e in production.get('exports', [])]
    renders = [{'id': f'frame-{f}', 'format': 'png', 'frame': f, 'kind': 'image',
                'name': f'{prefix}-frame-{f:06d}.png'} for f in production.get('renderFrames', [])]
    return exports + renders


def triangle_metrics(triangles):
    """Geometric moments insensitive to vertex splitting and face ordering."""
    count, area, volume = 0, 0.0, 0.0
    lower, upper, moment = [math.inf] * 3, [-math.inf] * 3, [0.0] * 3
    for vertices in triangles:
        if len(vertices) != 3 or any(len(p) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in p) for p in vertices):
            fail('INVALID_GEOMETRY', 'publication triangles must contain finite coordinates')
        count += 1
        if count > LIMIT:
            fail('RESOURCE_BUDGET_EXCEEDED', 'publication exceeds one million triangles')
        a, b, c = vertices
        u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
        cross = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        weight = math.hypot(*cross) / 2
        area += weight
        volume += (a[0]*(b[1]*c[2]-b[2]*c[1]) + a[1]*(b[2]*c[0]-b[0]*c[2]) + a[2]*(b[0]*c[1]-b[1]*c[0])) / 6
        for i in range(3):
            lower[i] = min(lower[i], *(p[i] for p in vertices))
            upper[i] = max(upper[i], *(p[i] for p in vertices))
            moment[i] += weight * sum(p[i] for p in vertices) / 3
    if not count or not math.isfinite(area) or not area > 0 or not math.isfinite(volume):
        fail('INVALID_GEOMETRY', 'publication needs finite nonzero surface geometry')
    return {'triangles': count, 'area': area, 'signedVolume': volume,
            'bounds': [v for pair in zip(lower, upper) for v in pair],
            'surfaceCentre': [x / area for x in moment]}


def matching_metrics(left, right):
    try:
        if not _integer(left['triangles']) or not _integer(right['triangles']) or left['triangles'] != right['triangles']:
            return False
        if len(left['bounds']) != 6 or len(right['bounds']) != 6 or len(left['surfaceCentre']) != 3 or len(right['surfaceCentre']) != 3:
            return False
        dimensions = [left['bounds'][i+1] - left['bounds'][i] for i in (0, 2, 4)]
        length = max(dimensions)
        if not math.isfinite(length) or not length > 0 or any(x < 0 for x in dimensions):
            return False
        pairs = [(left['area'], right['area'], length**2),
                 (left['signedVolume'], right['signedVolume'], length**3)]
        pairs += [(a, b, length) for a, b in zip(left['bounds'], right['bounds'])]
        pairs += [(a, b, length) for a, b in zip(left['surfaceCentre'], right['surfaceCentre'])]
        # Float32 interchange, ASCII exporter rounding and downstream evaluation.
        return all(not isinstance(a, bool) and not isinstance(b, bool)
                   and isinstance(a, (int, float)) and isinstance(b, (int, float))
                   and math.isfinite(a) and math.isfinite(b)
                   and math.isclose(a, b, rel_tol=2e-5, abs_tol=2e-6*scale) for a, b, scale in pairs)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _faces(vertices, faces):
    for indices in faces:
        if len(indices) != 3 or any(not _integer(i) or not 0 <= i < len(vertices) for i in indices):
            fail('VERIFICATION_FAILED', 'exchange publication must contain valid triangular faces')
        yield [vertices[i] for i in indices]


def _glb_triangles(data):
    if len(data) < 28 or struct.unpack_from('<III', data) != (0x46546C67, 2, len(data)):
        fail('VERIFICATION_FAILED', 'invalid GLB2 header')
    chunks, offset = [], 12
    while offset < len(data):
        length, kind = struct.unpack_from('<II', data, offset)
        offset += 8
        if length % 4 or offset + length > len(data):
            fail('VERIFICATION_FAILED', 'invalid GLB chunk bounds')
        chunks.append((kind, data[offset:offset+length]))
        offset += length
    if [c[0] for c in chunks] != [0x4E4F534A, 0x004E4942]:
        fail('VERIFICATION_FAILED', 'frame GLB requires one JSON and one embedded binary chunk')
    document, binary = json.loads(chunks[0][1]), chunks[1][1]
    if (document.get('asset', {}).get('version') != '2.0'
            or len(document.get('buffers', [])) != 1 or 'uri' in document['buffers'][0]
            or document.get('skins') or document.get('animations')
            or any('uri' in image for image in document.get('images', []))):
        fail('VERIFICATION_FAILED', 'frame GLB must be static and self-contained')
    buffer_length = document['buffers'][0]['byteLength']
    if not _integer(buffer_length) or not 0 < buffer_length <= len(binary):
        fail('VERIFICATION_FAILED', 'GLB embedded buffer length differs')
    def accessor(index, positions=False):
        if not _integer(index) or not 0 <= index < len(document.get('accessors', [])):
            fail('VERIFICATION_FAILED', 'GLB accessor reference differs')
        record = document['accessors'][index]
        if record.get('sparse') or record.get('normalized'):
            fail('VERIFICATION_FAILED', 'unsupported frame GLB accessor encoding')
        count, component = record['count'], record['componentType']
        if not _integer(count) or not 0 < count <= 3*LIMIT:
            fail('VERIFICATION_FAILED', 'GLB accessor count exceeds bounds')
        if positions:
            if component != 5126 or record['type'] != 'VEC3':
                fail('VERIFICATION_FAILED', 'GLB positions must be float32 triples')
            code, width = '3f', 12
        else:
            if component not in (5121, 5123, 5125) or record['type'] != 'SCALAR':
                fail('VERIFICATION_FAILED', 'GLB triangle indices must be unsigned scalars')
            code, width = {5121: ('B', 1), 5123: ('H', 2), 5125: ('I', 4)}[component]
        vi = record['bufferView']
        if not _integer(vi) or not 0 <= vi < len(document.get('bufferViews', [])):
            fail('VERIFICATION_FAILED', 'GLB buffer view reference differs')
        view = document['bufferViews'][vi]
        begin, length = view.get('byteOffset', 0), view['byteLength']
        local, stride = record.get('byteOffset', 0), view.get('byteStride', width)
        if (not _integer(view.get('buffer')) or view['buffer'] != 0 or any(not _integer(x) for x in (begin, length, local, stride))
                or min(begin, local) < 0 or length < width or stride < width
                or begin + length > buffer_length or local+(count-1)*stride+width > length):
            fail('VERIFICATION_FAILED', 'GLB accessor byte bounds differ')
        values = [struct.unpack_from('<'+code, binary, begin+local+i*stride) for i in range(count)]
        # glTF is Y-up; Blender's reviewed exporter maps (x,y,z) -> (x,z,-y).
        return [(v[0], -v[2], v[1]) for v in values] if positions else [v[0] for v in values]
    nodes, scenes = document.get('nodes', []), document.get('scenes', [])
    selected = document.get('scene', 0)
    if (not _integer(selected) or not 0 <= selected < len(scenes)
            or len(scenes) != 1 or any(not _integer(i) for i in scenes[selected].get('nodes', []))
            or set(scenes[selected].get('nodes', [])) != set(range(len(nodes)))
            or len(scenes[selected].get('nodes', [])) != len(nodes)):
        fail('VERIFICATION_FAILED', 'frame GLB scene membership differs')
    for node in nodes:
        if set(node) - {'name', 'mesh'} or 'mesh' not in node:
            fail('VERIFICATION_FAILED', 'frame GLB must contain baked identity mesh nodes')
        index = node['mesh']
        if not _integer(index) or not 0 <= index < len(document.get('meshes', [])):
            fail('VERIFICATION_FAILED', 'GLB mesh reference differs')
        for primitive in document['meshes'][index]['primitives']:
            if primitive.get('mode', 4) != 4 or primitive.get('extensions'):
                fail('VERIFICATION_FAILED', 'frame GLB needs uncompressed triangular primitives')
            vertices = accessor(primitive['attributes']['POSITION'], True)
            indices = accessor(primitive['indices'])
            if len(indices) % 3:
                fail('VERIFICATION_FAILED', 'GLB triangle index count differs')
            yield from _faces(vertices, [indices[i:i+3] for i in range(0, len(indices), 3)])


def _usda_triangles(text):
    # This is a deliberately bounded reader for our static baked USD output,
    # not an evaluator for arbitrary USD composition or time samples.
    if (not text.startswith('#usda 1.0') or '@' in text
            or re.search(r'\b(?:references|payload|inherits|specializes|timeSamples|variantSet|orientation)\b|xformOp:', text)
            or re.search(r'\bactive\s*=(?!\s*true\b)', text)
            or re.search(r'\bsubdivisionScheme\s*=\s*"(?!none")', text)
            or not re.search(r'\bmetersPerUnit\s*=\s*1(?:\.0*)?\s', text)
            or not re.search(r'\bupAxis\s*=\s*"Z"', text)
            or any(k not in ('Mesh', 'Xform') for k in re.findall(r'\bdef\s+(\w+)', text))):
        fail('VERIFICATION_FAILED', 'frame USD must contain self-contained identity geometry in metres')
    blocks = re.split(r'\bdef\s+Mesh\s+"[^"\n]+"\s*(?:\([^)]*\)\s*)?\{', text)[1:]
    if not blocks:
        fail('VERIFICATION_FAILED', 'frame USD contains no mesh')
    for block in blocks:
        def numbers(type_name, field, integer=False):
            pattern = re.escape(type_name)+r'\[\]\s+'+field+r'\s*=\s*\[([^]]*)\]'
            matches = re.findall(pattern, block)
            if len(matches) != 1:
                fail('VERIFICATION_FAILED', 'USD mesh array missing or duplicated', field)
            pattern = r'[-+]?\d+' if integer else r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
            residue = re.sub(pattern, '', matches[0])
            if re.sub(r'[\s,()]', '', residue):
                fail('VERIFICATION_FAILED', 'USD mesh array contains unsupported syntax', field)
            values = re.findall(pattern, matches[0])
            if len(values) > 9*LIMIT:
                fail('RESOURCE_BUDGET_EXCEEDED', 'USD mesh array exceeds bounded reader')
            return [int(v) if integer else float(v) for v in values]
        coordinates = numbers('point3f', 'points')
        counts, indices = numbers('int', 'faceVertexCounts', True), numbers('int', 'faceVertexIndices', True)
        if len(coordinates) % 3 or any(n != 3 for n in counts) or len(indices) != 3*len(counts):
            fail('VERIFICATION_FAILED', 'USD frame must contain triangular faces')
        vertices = [coordinates[i:i+3] for i in range(0, len(coordinates), 3)]
        yield from _faces(vertices, [indices[i:i+3] for i in range(0, len(indices), 3)])


def file_geometry(path, format):
    try:
        return _file_geometry(path, format)
    except (ValueError, TypeError, KeyError, IndexError, OSError, struct.error) as error:
        fail('VERIFICATION_FAILED', 'malformed exchange geometry: ' + str(error), str(path))


def _file_geometry(path, format):
    """Independently parse the deliberately triangulated OBJ/PLY/STL outputs."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_FILE:
        fail('VERIFICATION_FAILED', 'exchange file absent or exceeds the bounded reader', str(path))
    if format == 'stl':
        with path.open('rb') as stream:
            header = stream.read(84)
            if len(header) != 84:
                fail('VERIFICATION_FAILED', 'incomplete binary STL')
            n = struct.unpack_from('<I', header, 80)[0]
            if not 0 < n <= LIMIT or path.stat().st_size != 84 + 50*n:
                fail('VERIFICATION_FAILED', 'binary STL length differs')
            def triangles():
                for _ in range(n):
                    values = struct.unpack('<12fH', stream.read(50))
                    yield [values[3:6], values[6:9], values[9:12]]
            return triangle_metrics(triangles())
    if format == 'glb':
        return triangle_metrics(_glb_triangles(path.read_bytes()))
    if format == 'usd':
        return triangle_metrics(_usda_triangles(path.read_text(encoding='utf-8')))
    if format not in ('obj', 'ply'):
        fail('VERIFICATION_FAILED', 'unsupported exchange reader', format)
    vertices, faces = [], []
    with path.open(encoding='ascii') as stream:
        if format == 'obj':
            for line in stream:
                items = line.split()
                if not items or items[0].startswith('#'):
                    continue
                if items[0] == 'v':
                    if len(items) != 4:
                        fail('VERIFICATION_FAILED', 'expected three OBJ vertex coordinates')
                    vertices.append([float(x) for x in items[1:]])
                elif items[0] == 'f':
                    indices = [int(x.split('/')[0]) for x in items[1:]]
                    faces.append([i-1 if i > 0 else len(vertices)+i for i in indices])
                elif items[0] in ('mtllib', 'call', 'csh'):
                    fail('VERIFICATION_FAILED', 'geometry OBJ must be self-contained')
                if len(vertices) > 3*LIMIT or len(faces) > LIMIT:
                    fail('RESOURCE_BUDGET_EXCEEDED', 'OBJ geometry exceeds publication bounds')
        else:
            if stream.readline().strip() != 'ply' or stream.readline().strip() != 'format ascii 1.0':
                fail('VERIFICATION_FAILED', 'expected ASCII PLY')
            n, m, current, properties = None, None, None, []
            for line in stream:
                items = line.split()
                if items == ['end_header']:
                    break
                if items[:1] == ['element']:
                    current = items[1]
                    if current == 'vertex': n = int(items[2])
                    elif current == 'face': m = int(items[2])
                    else: fail('VERIFICATION_FAILED', 'unexpected PLY element')
                elif items[:1] == ['property'] and current == 'vertex':
                    properties.append(items[-1])
            if n is None or m is None or not 0 < n <= 3*LIMIT or not 0 < m <= LIMIT or not {'x', 'y', 'z'} <= set(properties):
                fail('VERIFICATION_FAILED', 'PLY vertex/face contract differs')
            columns = [properties.index(k) for k in ('x', 'y', 'z')]
            for _ in range(n):
                row = stream.readline().split()
                if len(row) != len(properties): fail('VERIFICATION_FAILED', 'PLY vertex row is incomplete')
                vertices.append([float(row[i]) for i in columns])
            for _ in range(m):
                row = [int(x) for x in stream.readline().split()]
                if len(row) != 4 or row[0] != 3: fail('VERIFICATION_FAILED', 'expected triangular PLY face')
                faces.append(row[1:])
            if stream.read().strip(): fail('VERIFICATION_FAILED', 'unexpected trailing PLY data')
    return triangle_metrics(_faces(vertices, faces))


def image_snapshot(path):
    from schemaxis.png import read
    width, height, pixels = read(path)
    return {'size': [width, height], 'pixelsSha256': hashlib.sha256(pixels).hexdigest()}


def verify_outputs(records, production, directory, prefix):
    jobs, directory = output_jobs(production, prefix), Path(directory).resolve()
    if not isinstance(records, list) or len(records) != len(jobs):
        fail('VERIFICATION_FAILED', 'production output membership differs')
    seen = set()
    for record, job in zip(records, jobs):
        path = directory / job['name']
        expected = {k: job[k] for k in ('id', 'format', 'frame', 'kind')}
        if (not isinstance(record, dict) or record.get('productionOutput') is not True
                or any(record.get(k) != v or type(record.get(k)) is not type(v) for k, v in expected.items())
                or record.get('file') != str(path) or path.resolve() != path or path in seen
                or not path.is_file() or record.get('sha256') != hashlib.sha256(path.read_bytes()).hexdigest()):
            fail('VERIFICATION_FAILED', 'production output path, identity or digest differs', str(path))
        seen.add(path)
        if job['format'] == 'png':
            if record.get('after') != image_snapshot(path):
                fail('VERIFICATION_FAILED', 'production frame pixels differ', str(path))
        else:
            source_units = production.get('units', 'metres')
            physical = job['format'] in ('glb', 'usd')
            target_units = 'metres' if physical else source_units
            scale = METRES.get(source_units) if physical else 1.0
            if (record.get('objects') != job['objects'] or record.get('units') != target_units
                    or record.get('sourceUnits') != source_units
                    or type(record.get('coordinateScale')) is not float
                    or record.get('coordinateScale') != scale
                    or not matching_metrics(record.get('before', {}), record.get('after', {}))):
                fail('VERIFICATION_FAILED', 'frame geometry readback differs', str(path))
            actual = file_geometry(path, job['format'])
            if actual is not None and not matching_metrics(record['before'], actual):
                fail('VERIFICATION_FAILED', 'independently decoded exchange geometry differs', str(path))
    return True
