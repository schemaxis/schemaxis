"""Revision-bound native selections and mixed prose/reference messages."""
import copy
import math
from pathlib import Path
import json

from .storage import atomic, encoded, digest
from .errors import fail, keys


class ReferenceStore:
    def __init__(self, workspace):
        self.path = Path(workspace) / 'references.json'
        self.data = {'version': 1, 'references': [], 'messages': []}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            if self.data.get('version') != 1:
                fail('UNSUPPORTED_VERSION', 'unsupported reference store', str(self.path))

    def _save(self, data):
        payload = encoded(data)
        try:
            atomic(self.path, payload)
        except OSError:
            # A directory sync can fail after atomic replacement. Keep the
            # visible state consistent with the published file, while still
            # reporting that durability was not confirmed.
            try:
                if self.path.read_bytes() == payload:
                    self.data = data
            except OSError:
                pass
            raise
        self.data = data

    @staticmethod
    def typed(ref):
        if ref.get('version') == 'schemaxis.reference/1': return copy.deepcopy(ref)
        image = ref.get('coordinateSpace') == 'image-pixel'
        return {**copy.deepcopy(ref), 'version': 'schemaxis.reference/1',
                'kind': 'image-pixel' if image else 'native-subelement',
                'target': {'document': ref['document'], 'revision': ref['revision']},
                'payload': {k: copy.deepcopy(ref[k]) for k in
                    (('point','imageSize','imageDigest') if image else ('object','subelement','point')) if k in ref},
                'provenance': {'kind': 'native-observation', 'scope': ref.get('selectionScope', 'historical native pick')},
                'replayable': False}

    @staticmethod
    def stale(ref, document, revision, resource_revisions=None):
        target = ref.get('target', {})
        if 'resource' in target:
            return (resource_revisions or {}).get(target['resource']) != target['revision']
        return ref.get('document') != document or ref.get('revision') != revision

    def list(self, document, revision, resource_revisions=None):
        return [{**self.typed(ref), 'stale': self.stale(ref, document, revision, resource_revisions)}
                for ref in self.data['references']]

    def register(self, request, document, geometry):
        keys(request, ('object', 'subelement', 'point', 'revision'), 'reference')
        if not document or request.get('revision') != geometry.get('revision'):
            fail('STALE_REFERENCE', 'the displayed model changed; pick again')
        obj = next((o for o in geometry.get('objects', []) if o['id'] == request.get('object')), None)
        if obj is None:
            fail('UNKNOWN_REFERENCE', 'picked object does not belong to displayed geometry')
        subelement = request.get('subelement')
        face = next((f for f in obj.get('faces', []) if f['id'] == subelement), None)
        edge = next((e for e in obj.get('edges', []) if e['id'] == subelement), None)
        vertex = next((v for v in obj.get('vertices', []) if v['id'] == subelement), None)
        if face is None and edge is None and vertex is None:
            fail('UNKNOWN_REFERENCE', 'picked subelement does not belong to displayed geometry')
        point = request.get('point')
        if not isinstance(point, list) or len(point) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in point):
            fail('INVALID_SELECTION', 'selection requires three finite model coordinates')
        vertices = face.get('vertices', []) if face else edge.get('points', []) if edge else [vertex['point']]
        if not vertices:
            fail('INVALID_SELECTION', 'selected face has no displayed geometry')
        lo = [min(v[i] for v in vertices) for i in range(3)]
        hi = [max(v[i] for v in vertices) for i in range(3)]
        tolerance = max(1e-6, math.dist(lo, hi) * 1e-5)
        if any(v < a - tolerance or v > b + tolerance for v, a, b in zip(point, lo, hi)):
            fail('INVALID_SELECTION', 'picked point lies outside the displayed face bounds')
        on_geometry = (any(_on_triangle(point, *(vertices[i] for i in triangle), tolerance)
                           for triangle in face.get('triangles', [])) if face else
                       any(_on_segment(point, a, b, tolerance) for a, b in zip(vertices, vertices[1:])) if edge else
                       math.dist(point, vertex['point']) <= tolerance)
        if not on_geometry:
            fail('INVALID_SELECTION', 'picked point is not on the displayed native tessellation')
        # Face identity is the actual native subelement. The coordinate is a
        # pick location on its display tessellation, not an inferred CAD UV.
        ref = {'document': document,
               'revision': geometry['revision'], 'object': obj['id'],
               'subelement': subelement, 'point': point,
               'label': ('surface ' if face else 'edge ' if edge else 'vertex ') + obj.get('label', obj['id']) + '.' + str(subelement),
               'coordinateSpace': 'model', 'units': geometry.get('units', 'native'),
               'selectionScope': 'native subelement identity at this revision; point on display tessellation'}
        ref['geometryDigest'] = digest(geometry)
        return self._append(self.typed(ref))

    def register_image(self, request, document, metadata):
        keys(request, ('revision', 'imageDigest', 'pixel'), 'image-reference')
        if not document or request.get('revision') != metadata.get('revision') or document != metadata.get('document'):
            fail('STALE_REFERENCE', 'the image document changed; refresh and pick again')
        if request.get('imageDigest') != metadata.get('sha256'):
            fail('STALE_REFERENCE', 'the displayed image changed; refresh and pick again')
        pixel = request.get('pixel')
        if not isinstance(pixel, list) or len(pixel) != 2 or any(type(v) is not int for v in pixel):
            fail('INVALID_SELECTION', 'image selection requires two integer pixel coordinates')
        if not 0 <= pixel[0] < metadata['width'] or not 0 <= pixel[1] < metadata['height']:
            fail('INVALID_SELECTION', 'picked pixel lies outside the image')
        return self._append({'document': document, 'revision': metadata['revision'],
            'object': 'preview', 'subelement': 'pixel('+','.join(map(str, pixel))+')',
            'point': pixel, 'label': 'image preview pixel ('+', '.join(map(str, pixel))+')',
            'coordinateSpace': 'image-pixel', 'units': 'px', 'imageDigest': metadata['sha256'],
            'imageSize': [metadata['width'], metadata['height']], 'imageArtifact': metadata['artifact'],
            'selectionScope': 'pixel in this retained PNG; origin top-left; not an inferred native surface or layer'})

    def _append(self, ref):
        index = len(self.data['references'])
        letters = ''
        while True:
            letters = chr(65 + index % 26) + letters
            index = index // 26 - 1
            if index < 0:
                break
        ref = {'id': 'ref' + letters, **self.typed(ref)}
        data = copy.deepcopy(self.data)
        data['references'].append(ref)
        self._save(data)
        return copy.deepcopy(ref)

    def message(self, segments, document, revision, image_digest=None, resource_revisions=None):
        if not isinstance(segments, list) or not 1 <= len(segments) <= 1000:
            fail('INVALID_MESSAGE', 'provide between one and 1000 prose/reference segments')
        refs = {r['id']: r for r in self.data['references']}
        resolved = []
        for segment in segments:
            keys(segment, ('text', 'reference'), 'message')
            if set(segment) == {'text'} and isinstance(segment['text'], str) and len(segment['text']) <= 100000:
                resolved.append(copy.deepcopy(segment))
            elif set(segment) == {'reference'} and isinstance(segment['reference'], str):
                ref = refs.get(segment['reference'])
                if ref is None:
                    fail('UNKNOWN_REFERENCE', 'message names an unknown selection')
                if self.stale(ref, document, revision, resource_revisions):
                    fail('STALE_REFERENCE', 'message uses a different document or evidence revision', ref['id'])
                if ref.get('imageDigest') and image_digest is not None and ref['imageDigest'] != image_digest:
                    fail('STALE_REFERENCE', 'message uses a different preview image; pick again', ref['id'])
                resolved.append({'reference': copy.deepcopy(ref)})
            else:
                fail('INVALID_MESSAGE', 'each segment must contain text or a reference ID')
        message = {'id': len(self.data['messages']) + 1, 'document': document,
                   'revision': revision, 'segments': resolved,
                   'status': 'recorded', 'executed': False}
        data = copy.deepcopy(self.data)
        data['messages'].append(message)
        self._save(data)
        return copy.deepcopy(message)


def _on_triangle(point, a, b, c, tolerance):
    def sub(x, y): return [u - v for u, v in zip(x, y)]
    def dot(x, y): return sum(u * v for u, v in zip(x, y))
    u, v, w = sub(b, a), sub(c, a), sub(point, a)
    normal = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
    length = math.sqrt(dot(normal, normal))
    if length < 1e-20 or abs(dot(w, normal)) > tolerance * length:
        return False
    uu, uv, vv = dot(u, u), dot(u, v), dot(v, v)
    determinant = uu * vv - uv * uv
    if determinant <= 0:
        return False
    s = (vv * dot(w, u) - uv * dot(w, v)) / determinant
    t = (uu * dot(w, v) - uv * dot(w, u)) / determinant
    return s >= -1e-5 and t >= -1e-5 and s + t <= 1 + 1e-5


def _on_segment(point, a, b, tolerance):
    direction = [y - x for x, y in zip(a, b)]
    length = sum(v*v for v in direction)
    if not length:
        return math.dist(point, a) <= tolerance
    t = max(0, min(1, sum((p-x)*v for p,x,v in zip(point,a,direction)) / length))
    return math.dist(point, [x+t*v for x,v in zip(a,direction)]) <= tolerance
