# Copyright (C) 2026 David L F Gaden
"""Portable output companions, committed independently of native receipts."""
import copy
import csv
import json
import math
from pathlib import Path, PureWindowsPath
import struct

from .artifacts import file_digest
from .storage import atomic, encoded
from .errors import fail
from .core.faults import SchemaxisError
from .run_paths import MANIFEST, METADATA_VERSION, owned_path, recorded_directory


def atomic_json(path, value):
    atomic(path, encoded(value))

VERSION = METADATA_VERSION


def _path(directory, value):
    if not isinstance(value, str):
        fail('PUBLICATION_METADATA_FAILED', 'publication requires a file path')
    return owned_path(directory, value, fault='PUBLICATION_METADATA_FAILED').resolve()


def _size(path, *, table=False):
    result = {'bytes': path.stat().st_size}
    if path.suffix.lower() == '.png':
        with path.open('rb') as stream:
            header = stream.read(24)
        if len(header) == 24 and header[:8] == b'\x89PNG\r\n\x1a\n' and header[12:16] == b'IHDR':
            result['pixels'] = list(struct.unpack('>II', header[16:24]))
    if path.suffix.lower() in ('.csv', '.tsv'):
        try:
            with path.open(newline='', encoding='utf-8') as stream:
                records, minimum, maximum = 0, None, 0
                for row in csv.reader(stream, delimiter='\t' if path.suffix.lower() == '.tsv' else ',', strict=True):
                    records += 1
                    minimum = len(row) if minimum is None else min(minimum, len(row))
                    maximum = max(maximum, len(row))
        except (UnicodeError, csv.Error) as error:
            # A lossless file handoff can contain arbitrary bytes under any
            # extension. Its suffix alone does not declare a table contract.
            if table:
                fail('PUBLICATION_METADATA_FAILED', 'Declared table cannot be inspected as UTF-8 CSV/TSV', str(path), detail=str(error))
        else:
            # Header presence is an adaptor observation, never a filename
            # inference. Physical records include any header; logical rows may
            # subsequently be supplied by the verified native descriptor.
            result.update(records=records, header='unknown', columnCountRange=[minimum or 0, maximum])
            if minimum is None or minimum == maximum:
                result['columns'] = maximum
    return result


def _unit(value):
    length = math.sqrt(sum(v*v for v in value))
    if not math.isfinite(length) or length == 0: raise ValueError('degenerate camera vector')
    return [v/length for v in value]


def camera_mapping(camera, pixels, plane=None):
    """Project ordered image edges onto a native slice or camera focal plane."""
    position, focal = camera['position'], camera['focalPoint']
    forward = _unit([focal[i]-position[i] for i in range(3)])
    up = camera['up']
    right = _unit([forward[1]*up[2]-forward[2]*up[1], forward[2]*up[0]-forward[0]*up[2], forward[0]*up[1]-forward[1]*up[0]])
    up = [right[1]*forward[2]-right[2]*forward[1], right[2]*forward[0]-right[0]*forward[2], right[0]*forward[1]-right[1]*forward[0]]
    distance = math.sqrt(sum((focal[i]-position[i])**2 for i in range(3)))
    height = camera.get('projectionScaleY', camera['scale']) if camera['parallel'] else distance*math.tan(math.radians(camera['viewAngle'])/2)
    width = height*pixels[0]/pixels[1]
    origin, normal = (plane['origin'], _unit(plane['normal'])) if plane else (focal, forward)
    corners = []
    for x,y in ((-1,1),(1,1),(1,-1),(-1,-1)):
        point = [focal[i]+x*width*right[i]+y*height*up[i] for i in range(3)]
        ray_origin = point if camera['parallel'] else position
        direction = forward if camera['parallel'] else [point[i]-position[i] for i in range(3)]
        denominator = sum(direction[i]*normal[i] for i in range(3))
        if abs(denominator) < 1e-12: raise ValueError('image edge ray is parallel to slice plane')
        parameter = sum((origin[i]-ray_origin[i])*normal[i] for i in range(3))/denominator
        if not camera['parallel'] and parameter <= 0: raise ValueError('slice plane lies behind image camera')
        corners.append([ray_origin[i]+parameter*direction[i] for i in range(3)])
    return {'state': 'known', 'frame': 'native-world', 'units': 'unknown',
            'mapping': 'pixel-edge-rays-to-slice-plane' if plane else 'camera-focal-plane',
            'pixelOrigin': 'top-left', 'rowDirection': 'down',
            'cornerOrder': ['top-left', 'top-right', 'bottom-right', 'bottom-left'],
            'corners': corners, 'plane': {'origin': list(origin), 'normal': list(normal)},
            'camera': copy.deepcopy(camera),
            'scope': 'viewport projection; overlays and pixels without slice geometry are not surface samples' if plane else 'camera image plane only; surface depth is unavailable'}


def _viewer_hints(artifact):
    """Retain explicit presentation hints without guessing physical semantics."""
    result = {}
    for key in ('group', 'sequence', 'overview'):
        if key not in artifact:
            continue
        value = artifact[key]
        if key == 'group':
            valid = isinstance(value, str) and bool(value.strip())
        elif key == 'sequence':
            valid = (isinstance(value, dict)
                     and isinstance(value.get('id'), str) and bool(value['id'].strip())
                     and value.get('axis') in ('x', 'y', 'z', 'time')
                     and type(value.get('value')) in (int, float) and math.isfinite(value['value'])
                     and ('units' not in value or isinstance(value['units'], str)))
        else:
            reference = value.get('file') if isinstance(value, dict) else None
            valid = (isinstance(reference, str) and bool(reference.strip())
                     and not Path(reference).is_absolute()
                     and not PureWindowsPath(reference).is_absolute()
                     and ':' not in reference and '\\' not in reference)
        if not valid:
            fail('PUBLICATION_METADATA_FAILED', 'invalid explicit viewer '+key, key)
        result[key] = copy.deepcopy(value)
    return result


def describe(directory, artifact):
    directory = Path(directory).resolve()
    path = _path(directory, artifact.get('file', artifact.get('path')))
    size = _size(path, table=artifact.get('kind', artifact.get('identity', {}).get('kind')) == 'table')
    observations = artifact.get('data', {})
    for key in ('dimensions', 'points', 'cells', 'rows', 'columns', 'frames', 'duration', 'triangles', 'facets', 'features', 'nodes', 'elements'):
        if key in artifact: size[key] = copy.deepcopy(artifact[key])
        elif isinstance(observations, dict) and key in observations: size[key] = copy.deepcopy(observations[key])
    spatial = copy.deepcopy(artifact.get('spatial', {'state': 'unknown', 'reason': 'native spatial placement was not observed'}))
    if 'spatial' not in artifact and artifact.get('kind', artifact.get('identity', {}).get('kind')) in ('table', 'measurement', 'workbook', 'video', 'sprite', 'audio'):
        spatial = {'state': 'notApplicable', 'reason': 'output has no declared physical 3D placement'}
    if 'camera' in artifact and 'pixels' in size:
        try:
            spatial = camera_mapping(artifact['camera'], size['pixels'], artifact.get('slicePlane'))
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            spatial = {'state': 'unknown', 'camera': copy.deepcopy(artifact['camera']), 'reason': 'projection cannot be reconstructed from native observations'}
    if 'units' in artifact: spatial['units'] = artifact['units']
    for key in ('bounds', 'transform', 'orientation', 'crs', 'extent'):
        if key in artifact: spatial[key] = copy.deepcopy(artifact[key])
    result = {'version': VERSION, 'artifact': {'file': path.name, 'sha256': file_digest(path),
              'kind': artifact.get('kind', artifact.get('identity', {}).get('kind', 'unspecified'))},
              'size': size, 'spatial': spatial}
    for key in ('identity', 'verificationScope', 'losses', 'viewTime'):
        if key in artifact: result[key] = copy.deepcopy(artifact[key])
    result.update(_viewer_hints(artifact))
    members = artifact.get('files', [])
    if members:
        records = []
        for member in members:
            member_path = _path(directory, member.get('file') if isinstance(member, dict) else member)
            records.append({'file': member_path.relative_to(path.parent).as_posix(),
                            'bytes': member_path.stat().st_size, 'sha256': file_digest(member_path)})
        result['members'] = records
        result['size']['bundleBytes'] = sum(member['bytes'] for member in records)
    return path, result


def receipt_artifacts(directory):
    receipt = json.loads((Path(directory)/'verification.json').read_text())
    if 'artifacts' in receipt:
        return receipt['artifacts']
    if 'artifact' in receipt: return [receipt['artifact']]
    if 'states' in receipt and 'images' in receipt:
        return [{'file': state['file'], 'kind': 'geometry', **state.get('live', {}),
                 'spatial': {'state': 'known', 'frame': 'native-world', 'units': 'unknown',
                             'bounds': state.get('live', {}).get('bounds'),
                             'boundsOrder':['xmin','xmax','ymin','ymax','zmin','zmax'],
                             'plane': {'origin': state['origin'], 'normal': receipt['normal']}}}
                for state in receipt['states']] + receipt['images']
    if 'slices' in receipt:
        return [{'file': str(Path(item['directory'])/item['geometryFile']), 'kind': 'geometry', **item.get('live', {}),
                 'spatial': {'state': 'known', 'frame': 'native-world', 'units': 'unknown',
                             'selectionPlane' if item.get('options', {}).get('crinkle') else 'plane': {'origin': item['origin'], 'normal': item['normal']},
                             'bounds': item.get('live', {}).get('bounds'), 'boundsOrder':['xmin','xmax','ymin','ymax','zmin','zmax']}} for item in receipt['slices']]
    if 'geometryFile' in receipt:
        return [{'file': receipt['geometryFile'], 'kind': 'geometry', **receipt.get('live', {}), 'spatial': {
            'state': 'known', 'frame': 'native-world', 'units': 'unknown',
            'selectionPlane' if receipt.get('options', {}).get('crinkle') else 'plane': {'origin': receipt['origin'], 'normal': receipt['normal']},
            'bounds': receipt.get('live', {}).get('bounds'), 'boundsOrder':['xmin','xmax','ymin','ymax','zmin','zmax']}}]
    fail('PUBLICATION_METADATA_FAILED', 'receipt does not declare publication membership', str(directory))


def _descriptions(directory, artifacts):
    for artifact in artifacts:
        yield describe(directory, artifact)
        for member in artifact.get('files', []):
            value = member.get('file') if isinstance(member, dict) else member
            if value != artifact.get('file'):
                spatial = copy.deepcopy(artifact.get('spatial', {'state': 'unknown'}))
                if 'bounds' in spatial:
                    spatial['logicalDatasetBounds'] = spatial.pop('bounds')
                    spatial['logicalDatasetBoundsOrder'] = spatial.pop('boundsOrder', None)
                    spatial['scope'] = 'inherited dataset frame; per-piece bounds were not observed'
                yield describe(directory, {'file': value, 'kind': 'datasetPiece', 'spatial': spatial})


def publish_artifacts(directory, artifacts):
    """Stage every companion, then commit the complete membership manifest last.

    A missing manifest means incomplete publication. Interrupted staging is safe
    to discard; verification never repairs it or manufactures missing companions.
    """
    directory = Path(directory).resolve()
    origin = recorded_directory(directory)
    descriptions = list(_descriptions(directory, artifacts))
    unique = {}
    for path, value in descriptions:
        if path in unique and unique[path] != value:
            fail('PUBLICATION_METADATA_FAILED', 'conflicting metadata for one publication', str(path))
        unique[path] = value
    entries = []
    staged = []
    try:
        for path, value in unique.items():
            companion = path.with_name(path.name+'.metadata.json')
            if companion in unique:
                fail('PUBLICATION_METADATA_FAILED', 'metadata companion collides with an output', str(companion))
            temporary = companion.with_name(companion.name+'.staging')
            if temporary in unique:
                fail('PUBLICATION_METADATA_FAILED', 'metadata staging file collides with an output', str(temporary))
            atomic_json(temporary, value)
            staged.append((temporary, companion))
            entries.append({'file': path.relative_to(directory).as_posix(),
                            'metadata': companion.relative_to(directory).as_posix(),
                            'sha256': file_digest(temporary)})
        for temporary, companion in staged: atomic(companion, temporary.read_bytes())
        manifest = {'version': VERSION, 'publications': entries}
        if origin is not None:
            manifest['recordedDirectory'] = str(origin)
        atomic_json(directory/MANIFEST, manifest)
    finally:
        for temporary, _ in staged: temporary.unlink(missing_ok=True)
    return manifest


def finalise(directory):
    return publish_artifacts(directory, receipt_artifacts(directory))


def verify(directory, artifacts=None):
    directory = Path(directory).resolve()
    try:
        artifacts = receipt_artifacts(directory) if artifacts is None else artifacts
        expected = {}
        for path, value in _descriptions(directory, artifacts):
            expected[path.relative_to(directory).as_posix()] = value
        manifest = json.loads((directory/MANIFEST).read_text())
        records = manifest['publications']
        if manifest.get('version') != VERSION or not isinstance(records, list) or len(records) != len(expected):
            raise ValueError('metadata publication membership differs')
        if [entry['file'] for entry in records] != list(expected): raise ValueError('metadata publication order differs')
        for entry in records:
            data = expected[entry['file']]
            companion = _path(directory, entry['metadata'])
            if entry['metadata'] != entry['file']+'.metadata.json': raise ValueError('companion location differs')
            if file_digest(companion) != entry['sha256'] or json.loads(companion.read_text()) != data:
                raise ValueError('metadata content or artifact relationship differs')
        return {'verified': True, 'publications': len(records), 'version': VERSION}
    except (OSError, ValueError, KeyError, TypeError, csv.Error, SchemaxisError) as error:
        fail('VERIFICATION_FAILED', 'missing or malformed output metadata: '+str(error), str(directory))


def committed_companions(directory, artifacts):
    """Return only validated generated companions for recursive inventories.

    Before publication there is no commit to exclude. After publication, missing
    or modified commit evidence is a fault, never a filename-based exemption.
    """
    directory = Path(directory).resolve()
    if not (directory/MANIFEST).exists(): return set()
    verify(directory, artifacts)
    manifest = json.loads((directory/MANIFEST).read_text())
    return {(directory/entry['metadata']).resolve() for entry in manifest['publications']}
