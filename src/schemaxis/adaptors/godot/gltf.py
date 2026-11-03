# Copyright (C) 2026 David L F Gaden
"""Bounded, embedded, static glTF geometry; no external resources or scripts."""
import base64
import json
import math
import struct

from .errors import fault

MAX_BYTES = 8 * 1024 * 1024


def inspect(data):
    """Validate a deliberately narrow glTF subset and measure actual vertices."""
    def require(condition, message):
        if not condition:
            fault('UNSUPPORTED_RESOURCE', message, '$.readGLTF',
                  'Use one static triangle mesh with embedded buffers, POSITION and optional NORMAL.')

    def closed(value, allowed):
        require(isinstance(value, dict) and not set(value) - set(allowed),
                'glTF contains unsupported fields')

    def integer(value, low, high):
        require(type(value) is int and low <= value <= high, 'glTF integer is outside its bounds')
        return value

    try:
        require(len(data) <= MAX_BYTES, 'glTF exceeds 8 MiB')
        doc = json.loads(data)
        closed(doc, ('asset', 'buffers', 'bufferViews', 'accessors', 'meshes', 'nodes', 'scenes', 'scene'))
        closed(doc['asset'], ('version', 'generator', 'copyright'))
        require(doc['asset']['version'] == '2.0', 'expected glTF 2.0')
        require(len(doc['meshes']) == len(doc['nodes']) == len(doc['scenes']) == 1,
                'expected one mesh, one identity node and one scene')
        closed(doc['nodes'][0], ('mesh', 'name'))
        closed(doc['scenes'][0], ('nodes', 'name'))
        require(doc['nodes'][0]['mesh'] == 0 and doc['scenes'][0]['nodes'] == [0]
                and doc.get('scene', 0) == 0, 'invalid glTF scene selection')
        mesh = doc['meshes'][0]
        closed(mesh, ('primitives', 'name'))
        require(len(mesh['primitives']) == 1, 'expected one triangle primitive')
        primitive = mesh['primitives'][0]
        closed(primitive, ('attributes', 'indices', 'mode'))
        require(primitive.get('mode', 4) == 4, 'only TRIANGLES are supported')
        closed(primitive['attributes'], ('POSITION', 'NORMAL'))
        require('POSITION' in primitive['attributes'], 'POSITION is required')
        require(1 <= len(doc['buffers']) <= 3 and 1 <= len(doc['bufferViews']) <= 3
                and 1 <= len(doc['accessors']) <= 3, 'too many glTF buffers or accessors')
        buffers = []
        for buffer in doc['buffers']:
            closed(buffer, ('uri', 'byteLength'))
            uri = buffer['uri']
            require(isinstance(uri, str) and uri.startswith(('data:application/octet-stream;base64,',
                    'data:application/gltf-buffer;base64,')), 'only embedded base64 buffers are supported')
            raw = base64.b64decode(uri.split(',', 1)[1], validate=True)
            require(len(raw) == integer(buffer['byteLength'], 1, MAX_BYTES), 'buffer length differs')
            buffers.append(raw)
        for view in doc['bufferViews']:
            closed(view, ('buffer', 'byteOffset', 'byteLength', 'byteStride', 'target'))
            b = integer(view['buffer'], 0, len(buffers)-1)
            offset = integer(view.get('byteOffset', 0), 0, len(buffers[b]))
            length = integer(view['byteLength'], 1, len(buffers[b]))
            require(offset + length <= len(buffers[b]), 'buffer view exceeds buffer')
        values = []
        for accessor in doc['accessors']:
            closed(accessor, ('bufferView', 'byteOffset', 'componentType', 'count', 'type', 'min', 'max'))
            view = doc['bufferViews'][integer(accessor['bufferView'], 0, len(doc['bufferViews'])-1)]
            kind = accessor['componentType']
            require((kind == 5126 and accessor['type'] == 'VEC3') or
                    (kind in (5121, 5123, 5125) and accessor['type'] == 'SCALAR'), 'unsupported accessor')
            fmt = {5126: '<3f', 5121: '<B', 5123: '<H', 5125: '<I'}[kind]
            size = struct.calcsize(fmt)
            stride = integer(view.get('byteStride', size), size, 252)
            count = integer(accessor['count'], 1, 100000)
            offset = integer(accessor.get('byteOffset', 0), 0, view['byteLength'])
            require(offset + (count-1)*stride + size <= view['byteLength'], 'accessor exceeds view')
            raw = buffers[view['buffer']]
            start = view.get('byteOffset', 0) + offset
            rows = [struct.unpack_from(fmt, raw, start+i*stride) for i in range(count)]
            require(all(math.isfinite(x) and abs(x) <= 100000 for row in rows for x in row),
                    'nonfinite or unbounded accessor values')
            values.append(rows)
        index = integer(primitive['attributes']['POSITION'], 0, len(values)-1)
        positions = values[index]
        require(doc['accessors'][index]['type'] == 'VEC3', 'POSITION must be VEC3')
        for attribute, index in primitive['attributes'].items():
            index = integer(index, 0, len(values)-1)
            require(doc['accessors'][index]['type'] == 'VEC3' and len(values[index]) == len(positions),
                    'vertex attribute shape differs')
        if 'indices' in primitive:
            index = integer(primitive['indices'], 0, len(values)-1)
            require(doc['accessors'][index]['type'] == 'SCALAR', 'indices must be unsigned scalars')
            indices = [row[0] for row in values[index]]
            require(all(i < len(positions) for i in indices), 'index exceeds vertex count')
        else:
            indices = list(range(len(positions)))
        require(len(indices) % 3 == 0, 'triangle index count must be divisible by three')
        # Require tight declared extrema when supplied; measure bytes, not metadata.
        bounds = [min(v[i] for v in positions) for i in range(3)] + [max(v[i] for v in positions) for i in range(3)]
        pos = doc['accessors'][primitive['attributes']['POSITION']]
        for key, expected in [('min', bounds[:3]), ('max', bounds[3:])]:
            if key in pos:
                require(len(pos[key]) == 3 and all(math.isclose(a, b, abs_tol=1e-6, rel_tol=1e-6)
                        for a, b in zip(pos[key], expected)), 'POSITION extrema differ from bytes')
        return {'bounds': bounds, 'triangles': len(indices)//3}
    except (KeyError, TypeError, ValueError, IndexError, struct.error, OverflowError, AttributeError, RecursionError) as error:
        fault('INVALID_RESOURCE', 'Malformed glTF: '+str(error), '$.readGLTF', 'Provide valid embedded glTF 2.0 geometry.')
