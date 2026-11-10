"""Finite first-consumer simulation cache contracts, independent of native imports.

A saved cache descriptor is provenance, never source authority. Admission needs a
fresh reconstruction from constructor intent, admitted dependencies and runtime,
then independent file/geometry comparison. No authored Python or native lookup.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import stat

from schemaxis.errors import fail

MAX_BYTES = 64*1024**2
MAX_FILES = 2048
MAX_FRAMES = 1000
VERSION = 'schemaxis.blender.point-cache/1'


def fingerprint(value):
    try:data = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (ValueError, TypeError) as error:fail('INVALID_CACHE', 'cache intent must be finite JSON', detail=str(error))
    if len(data) > 8*1024**2:fail('RESOURCE_BUDGET_EXCEEDED', 'cache intent exceeds 8 MiB')
    return hashlib.sha256(data).hexdigest()


def plan(request, constructor):
    if not isinstance(request, dict) or set(request) != {'id','kind','object','scene','frameStart','frameEnd','storage'}:
        fail('INVALID_CACHE', 'cache needs an exact finite owner/range/storage record')
    for key in ('id','scene'):
        if not isinstance(request[key], str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,62}', request[key]):
            fail('INVALID_CACHE', 'cache identity must be a portable identifier', key)
    if request['kind'] not in ('rigidBody','cloth') or request['storage'] not in ('packed','disk'):
        fail('UNSUPPORTED_CACHE', 'only rigid-body world and cloth point caches are implemented')
    if request['kind']=='rigidBody' and request['storage']=='disk':
        fail('UNSUPPORTED_CACHE', 'rigid-body disk conversion crashes qualified5.2.3; required native repair remains OPEN; use packed storage')
    if (request['kind']=='rigidBody' and request['object'] != '' or request['kind']=='cloth'
            and (not isinstance(request['object'], str) or not request['object'])):
        fail('INVALID_CACHE', 'cloth needs its object identity; rigid-body cache belongs to the scene')
    start, end = request['frameStart'], request['frameEnd']
    if type(start) is not int or type(end) is not int or not 1 <= start <= end or end-start+1 > MAX_FRAMES:
        fail('RESOURCE_BUDGET_EXCEEDED', 'cache range needs 1 through 1000 consecutive positive frames')
    if (not isinstance(constructor, dict) or set(constructor) != {'version','intent','dependencies','runtime'}
            or constructor['version'] != 'schemaxis.blender.cache-constructor/1'
            or not isinstance(constructor['intent'], dict) or not isinstance(constructor['dependencies'], list)
            or constructor['runtime'] != {'version':[5,2,3],'build':'e13b728c6880'}):
        fail('INVALID_CACHE', 'cache needs typed constructor intent, admitted dependencies and qualified runtime')
    seen = set()
    for item in constructor['dependencies']:
        if (not isinstance(item, dict) or set(item) != {'id','sha256','bytes'}
                or not isinstance(item['id'], str) or not item['id'] or item['id'] in seen
                or not isinstance(item['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', item['sha256'])
                or type(item['bytes']) is not int or not 0 <= item['bytes'] <= MAX_BYTES):
            fail('INVALID_CACHE', 'cache dependencies need distinct exact content fingerprints')
        seen.add(item['id'])
    if sum(item['bytes'] for item in constructor['dependencies']) > MAX_BYTES:
        fail('RESOURCE_BUDGET_EXCEEDED', 'cache dependencies exceed 64 MiB aggregate')
    return {'version':VERSION, **copy.deepcopy(request), 'constructor':copy.deepcopy(constructor),
            'sourceFingerprint':fingerprint(constructor), 'requestFingerprint':fingerprint(request),
            'nativeType':'RIGID_BODY' if request['kind']=='rigidBody' else 'CLOTH',
            'losses':['Fixed Blender/solver build; cache is not an interchange simulation format',
                      'No GN/fluid/soft-body/joint/motor/animated-input cache contract yet']}


def validate(compiled):
    keys={'version','id','kind','object','scene','frameStart','frameEnd','storage','constructor','sourceFingerprint','requestFingerprint','nativeType','losses'}
    if not isinstance(compiled,dict) or set(compiled)!=keys:fail('INVALID_CACHE','compiled cache fields differ from finite contract')
    expected = plan({key:compiled[key] for key in ('id','kind','object','scene','frameStart','frameEnd','storage')}, compiled['constructor'])
    if expected != compiled:fail('INVALID_CACHE', 'compiled cache differs from recompiled constructor intent')
    return expected


def inventory(root, *, publication_directory=None):
    """Bounded no-follow inventory of a dedicated host-owned cache directory."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():fail('INVALID_CACHE', 'cache directory must be a real directory')
    companions=set()
    if publication_directory is not None:
        from schemaxis.publication_metadata import committed_companions
        companions={p for p in committed_companions(publication_directory,None) if p.parent==root.resolve()}
    result = {};total = 0
    for path in sorted(root.iterdir()):
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.is_symlink() or path.stat().st_dev != root.stat().st_dev:
            fail('INVALID_CACHE', 'cache members must be same-filesystem plain files', str(path))
        if path.resolve() in companions:
            payload=path.with_name(path.name.removesuffix('.metadata.json'))
            if not path.name.endswith('.bphys.metadata.json') or payload.is_symlink() or not payload.is_file():
                fail('INVALID_CACHE','committed cache companion must belong to a present solver payload',path.name)
            continue
        if path.suffix != '.bphys':fail('INVALID_CACHE', 'undeclared cache member', path.name)
        size = path.stat().st_size;total += size
        if not size or total > MAX_BYTES or len(result) >= MAX_FILES:fail('RESOURCE_BUDGET_EXCEEDED', 'cache files exceed finite bounds')
        h = hashlib.sha256()
        with path.open('rb') as stream:
            read = 0
            for block in iter(lambda:stream.read(1<<20), b''):
                read += len(block)
                if read > size:fail('INPUT_CHANGED', 'cache grew while read', path.name)
                h.update(block)
        if read != size:fail('INPUT_CHANGED', 'cache size changed while read', path.name)
        result[path.name] = {'bytes':size,'sha256':h.hexdigest()}
    return result


def verify_files(submitted, fresh_reference, *, storage):
    """Compare actual bytes to freshly reconstructed files, NOT a saved manifest."""
    actual, expected = inventory(submitted), inventory(fresh_reference)
    if storage not in ('packed','disk'):fail('INVALID_CACHE', 'unknown cache storage')
    if storage=='disk' and not expected:fail('VERIFICATION_FAILED', 'fresh disk bake has no cache payload')
    if storage=='packed' and (actual or expected):fail('VERIFICATION_FAILED', 'packed cache unexpectedly owns disk files')
    if actual != expected:fail('VERIFICATION_FAILED', 'cache payload differs from fresh trusted reconstruction')
    return actual


def _public_options():
    from .spline import array, record
    from .node_catalogue import text, choice, integer
    request=record({'id':{**text(),'minLength':1,'maxLength':63},
                    'kind':choice('rigidBody',['rigidBody','cloth']),
                    'object':text(),'frameStart':integer(1,minimum=1),
                    'frameEnd':integer(10,minimum=1),'storage':choice('packed',['packed','disk'])},
                   ['id','kind','frameStart','frameEnd','storage'])
    return {'simulationCaches':array(request,32)}


def schema_property():
    """Public cache requests contain intent only; authority fields stay internal."""
    from schemaxis.schema import arguments_schema
    return arguments_schema(_public_options())['properties']['simulationCaches']


def validate_public(value, *, kinds, rigid_bodies, cloth, frame_start, frame_end):
    """Bind public logical consumers and ranges before native allocation."""
    from schemaxis.core.declarations import validate_arguments
    where='production.simulationCaches'
    records=validate_arguments(_public_options(), {'simulationCaches':value},location=where)['simulationCaches']
    identities=set();consumers=set();disk_frames=0
    cloth_objects={item['object'] for item in cloth}
    for item in records:
        if not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,62}',item['id']) or item['id'] in identities:
            fail('INVALID_CACHE','cache IDs must be distinct portable identifiers',where)
        identities.add(item['id']);key=(item['kind'],item['object'])
        if key in consumers:fail('INVALID_CACHE','one cache per actual logical consumer',where)
        consumers.add(key)
        if item['frameStart']!=frame_start or item['frameEnd']!=frame_end or item['frameEnd']-item['frameStart']+1>MAX_FRAMES:
            fail('INVALID_CACHE','first public caches must cover the complete production timeline within1000frames',where)
        if item['kind']=='rigidBody':
            if item['object'] or not rigid_bodies:fail('INVALID_CACHE','rigid cache requires the production world and empty object selector',where)
            if item['storage']=='disk':fail('UNSUPPORTED_CACHE','rigid-body disk conversion crashes qualified5.2.3; required repair remains OPEN',where)
        elif item['object'] not in cloth_objects or kinds.get(item['object']) not in ('mesh','instance'):
            fail('INVALID_CACHE','cloth cache must name an existing production cloth mesh consumer',where)
        if item['storage']=='disk':disk_frames+=item['frameEnd']-item['frameStart']+1
    if disk_frames>MAX_FILES:fail('RESOURCE_BUDGET_EXCEEDED','aggregate baked disk frame files exceed2048',where)
    return records
