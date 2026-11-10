"""Literal qualification oracles; independent of Blender's render compilers.

Only EXR decoding is shared. Camera basis, plane equations, expected regions,
Cryptomatte IDs and additive light membership are supplied explicitly by callers.
These finite pixel checks supplement native/source authority, never replace it.
"""
import json
import math
from pathlib import Path
import struct

from schemaxis.adaptors.blender.exr_output import inspect


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _near(actual, expected, tolerance):
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (actual, expected, tolerance)) or tolerance < 0:
        raise ValueError('nonfinite/non-numeric sample')
    if abs(actual-expected) > tolerance:
        raise ValueError(f'literal sample differs: {actual} versus {expected} ± {tolerance}')


def _basis(camera):
    vectors = [camera[k] for k in ('right', 'up', 'forward')]
    if any(len(v) != 3 or not all(math.isfinite(x) for x in v) for v in vectors):
        raise ValueError('camera basis needs finite triples')
    for i, a in enumerate(vectors):
        _near(dot(a, a), 1, 1e-10)
        for b in vectors[:i]:_near(dot(a, b), 0, 1e-10)
    return vectors


def ray_plane(camera, size, pixel, plane):
    """Pixel-centre perspective intersection; EXR y increases downward.

    halfWidth/halfHeight are literal sensor half extents at unit forward depth,
    including the explicitly chosen aspect fit. Plane is normal·P=offset.
    forward points into the scene; returned depth is optical Z, not ray length.
    """
    right, up, forward = _basis(camera)
    x, y = pixel; width, height = size
    u = (2*(x+.5)/width-1)*camera['halfWidth']
    v = (1-2*(y+.5)/height)*camera['halfHeight']
    ray = [f+u*r+v*t for f, r, t in zip(forward, right, up)]
    denominator = dot(plane['normal'], ray)
    if abs(denominator) < 1e-12:raise ValueError('ray is parallel to plane')
    z = (plane['offset']-dot(plane['normal'], camera['origin']))/denominator
    if z <= 0:raise ValueError('plane is behind camera')
    return {'opticalZ': z, 'position': [o+z*d for o, d in zip(camera['origin'], ray)]}


def verify(path, expected):
    """Check explicit named planes, geometric regions, matte ranks and sums.

    Expected schema is intentionally small and fixture-owned, not a public API.
    All channel names and membership IDs are literal input, never inferred from
    an output manifest or a provider layout. Tolerances are absolute and explicit.
    """
    def triple(value):
        return isinstance(value, (list, tuple)) and len(value) == 3 and all(type(v) in (int, float) and math.isfinite(v) for v in value)
    regions = expected['regions']
    if not isinstance(regions, list) or not regions:raise ValueError('literal semantic regions must be nonempty')
    identities, pixels = set(), set()
    for region in regions:
        identity, pixel = region.get('id'), region.get('pixel')
        if not isinstance(identity, str) or not identity or identity in identities:raise ValueError('region identities must be nonempty and distinct')
        if not isinstance(pixel, (list, tuple)) or len(pixel) != 2 or any(type(v) is not int or v < 0 for v in pixel) or tuple(pixel) in pixels:raise ValueError('region pixels must be valid and distinct')
        identities.add(identity);pixels.add(tuple(pixel))
        if not any(region.get(key) for key in ('values', 'bits', 'geometry', 'matteRanks', 'lightSums')):raise ValueError('region must check semantic values')
        geometry = region.get('geometry')
        if geometry:
            for key in ('positionChannels', 'normalChannels'):
                names = geometry[key]
                if not isinstance(names, (list, tuple)) or len(names) != 3 or len(set(names)) != 3 or not all(isinstance(n, str) and n for n in names):raise ValueError('geometry channels require three distinct names')
            if not triple(geometry['worldNormal']) or not triple(geometry['plane']['normal']) or not triple(expected['camera']['origin']):raise ValueError('geometry vectors and camera origin require finite triples')
    points = [r['pixel'] for r in regions]
    facts = inspect(path, samples=points)
    if facts['size'] != expected['size']:raise ValueError('literal image dimensions differ')
    channels = {c['name'] for c in facts['channels']}
    if 'channels' in expected and channels != set(expected['channels']):
        raise ValueError('literal complete channel membership differs')
    checks = []
    for region in expected['regions']:
        x, y = region['pixel'];sample = facts['samples'][f'{x},{y}']
        def number(name):return sample[name]['value']
        for name, value in region.get('values', {}).items():
            _near(number(name), value, region['tolerance'])
        for name, bits in region.get('bits', {}).items():
            if sample[name]['bits'] != bits:raise ValueError('literal component bits differ: '+name)
        geometry = region.get('geometry')
        if geometry:
            camera, plane = expected['camera'], geometry['plane']
            position = [number(n) for n in geometry['positionChannels']]
            relative = [v-o for v, o in zip(position, camera['origin'])]
            _near(dot(plane['normal'], position), plane['offset'], geometry['tolerance'])
            _near(number(geometry['depthChannel']), dot(relative, camera['forward']), geometry['tolerance'])
            radius = geometry.get('pixelRadius', 0)
            if radius < 0:raise ValueError('negative ray footprint radius')
            optical = dot(relative, camera['forward'])
            if optical <= 0:raise ValueError('observed position behind camera')
            right, up, _ = _basis(camera)
            for axis, component, extent, index, flip in ((right, x, camera['halfWidth'], 0, 1), (up, y, camera['halfHeight'], 1, -1)):
                predicted = flip*(2*(component+.5)/facts['size'][index]-1)*extent
                bound = 2*radius/facts['size'][index]*extent
                _near(dot(relative, axis)/optical, predicted, bound+geometry['tolerance'])
            depths = [ray_plane(camera, facts['size'], [x+dx, y+dy], plane)['opticalZ']
                      for dx in (-radius, radius) for dy in (-radius, radius)]
            depth = number(geometry['depthChannel'])
            if not min(depths)-geometry['tolerance'] <= depth <= max(depths)+geometry['tolerance']:
                raise ValueError('depth outside literal top-down ray footprint')
            for name, value in zip(geometry['normalChannels'], geometry['worldNormal']):
                _near(number(name), value, geometry['tolerance'])
        for matte in region.get('matteRanks', []):
            # Explicit ordered rank channels bind ID bits AND associated coverage.
            if sample[matte['idChannel']]['bits'] != struct.pack('<I', int(matte['idBits'], 16)).hex():
                raise ValueError('Cryptomatte rank identity differs')
            _near(number(matte['coverageChannel']), matte['coverage'], matte['tolerance'])
        for addition in region.get('lightSums', []):
            if addition['policy'] != 'linear-radiance-complete-disjoint-groups':
                raise ValueError('light sum requires explicit complete disjoint linear radiance policy')
            if not addition['groups'] or len(set(addition['groups'])) != len(addition['groups']):raise ValueError('light groups must be distinct and nonempty')
            _near(number(addition['combined']), sum(number(n) for n in addition['groups']), addition['tolerance'])
        checks.append({'region': region['id'], 'pixel': [x, y], 'verified': True})
    if 'manifests' in expected and set(facts['cryptomatte']) != set(expected['manifests']):
        raise ValueError('literal Cryptomatte layer membership differs')
    for layer, manifest in expected.get('manifests', {}).items():
        if facts['cryptomatte'].get(layer, {}).get('manifest') != manifest:
            raise ValueError('literal Cryptomatte membership differs')
    return {'verified': True, 'fileSha256': facts['sha256'], 'checks': checks}


def _header(raw):
    if len(raw) < 9 or struct.unpack_from('<II', raw) != (20000630, 2):
        raise ValueError('mutation requires simple single-part EXR v2')
    position, attributes = 8, {}
    def string():
        nonlocal position
        end = raw.index(0, position);value = bytes(raw[position:end]).decode();position = end+1
        return value
    while raw[position]:
        name, kind = string(), string();length, = struct.unpack_from('<i', raw, position);position += 4
        if length < 0 or position+length > len(raw) or name in attributes:raise ValueError('bad header')
        attributes[name] = (kind, position, length);position += length
    return attributes, position+1


def mutate_none_sample(source, destination, channel, pixel, value):
    """Change one NAMED NONE scanline sample, preserving every other byte."""
    if Path(source).resolve() == Path(destination).resolve():raise ValueError('mutation destination must differ from source')
    facts = inspect(source, samples=[pixel])
    if facts['compression'] != 'none':raise ValueError('sample mutation requires NONE compression')
    raw = bytearray(Path(source).read_bytes());attrs, table = _header(raw)
    _, start, length = attrs['channels'];position = start;declarations = []
    while raw[position]:
        end = raw.index(0, position);name = bytes(raw[position:end]).decode();position = end+1
        kind, = struct.unpack_from('<i', raw, position);position += 16
        declarations.append((name, kind))
    width, height = facts['size'];x, y = pixel;xmin, ymin, _, _ = facts['dataWindow']
    formats = {0: ('I', 4), 1: ('e', 2), 2: ('f', 4)}
    for row in range(height):
        offset, = struct.unpack_from('<Q', raw, table+8*row);native_y, count = struct.unpack_from('<ii', raw, offset)
        if native_y != y+ymin:continue
        address = offset+8
        for name, kind in declarations:
            code, size = formats[kind]
            if name == channel:
                struct.pack_into('<'+code, raw, address+x*size, value)
                Path(destination).write_bytes(raw)
                return {'channel': channel, 'pixel': list(pixel), 'byteOffset': address+x*size,
                        'sourceBytes': len(raw), 'destinationBytes': len(raw)}
            address += width*size
        raise ValueError('named channel absent')
    raise ValueError('named scanline absent')


def mutate_manifest_member(source, destination, layer, old_name, new_name, new_hash):
    """Valid JSON, same-size membership mutation; caller supplies known name hash.

    Replacing a complete encoded key/value pair preserves header lengths/chunks.
    The native format-validity control remains a separate required qualification.
    """
    import re
    if Path(source).resolve() == Path(destination).resolve():raise ValueError('mutation destination must differ from source')
    facts = inspect(source)
    original = facts['cryptomatte'][layer]['manifest'];old_hash = original[old_name]
    if new_name in original or len(new_hash) != 8:raise ValueError('replacement must be a new literal member')
    raw = bytearray(Path(source).read_bytes());attrs, _ = _header(raw)
    identifier = facts['cryptomatte'][layer]['identifier'];_, start, length = attrs['cryptomatte/'+identifier+'/manifest']
    encoded = bytes(raw[start:start+length]).decode()
    pattern = re.escape(json.dumps(old_name))+r'(\s*:\s*)'+re.escape(json.dumps(old_hash))
    matches = list(re.finditer(pattern, encoded))
    if len(matches) != 1:raise ValueError('manifest member must occur exactly once')
    match = matches[0];replacement = json.dumps(new_name)+match[1]+json.dumps(new_hash)
    if len(replacement.encode()) != len(match[0].encode()):raise ValueError('manifest mutation must preserve byte count')
    changed = encoded[:match.start()]+replacement+encoded[match.end():]
    json.loads(changed);raw[start:start+length] = changed.encode();Path(destination).write_bytes(raw)
    inspect(destination)  # Reject invalid name hashes/grammar before calling it a valid attack.
    return {'layer': layer, 'removed': old_name, 'added': new_name, 'bytes': len(raw)}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exr', type=Path)
    parser.add_argument('expectations', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = verify(args.exr, json.loads(args.expectations.read_text()))
    rendered = json.dumps(result, indent=2)+'\n'
    if args.report:args.report.write_text(rendered)
    else:print(rendered, end='')


if __name__ == '__main__':main()
