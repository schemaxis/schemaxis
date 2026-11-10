"""Adopt stable application-saved files or directories as pinned workflow inputs.

``adopt`` copies a stable checkpoint into a ``schemaxis.resource/1`` snapshot
(see ``workflow_resources``). A workflow consumes it with a ``$resource``
reference that also pins the trusted manifest digest. Every consumption and
every verification re-verifies the exact snapshot, compares that pinned digest
and asks the consuming adaptor's ``acceptResource`` hook whether the operation
may read the snapshot kind and member. Changed content is refused; a new digest
is never adopted implicitly. Units, frames and native project dependencies are
not inferred: they are recorded as unknown unless the adaptor policy checks them.
"""

import os
from pathlib import Path
import re

from . import workflow_resources as resources
from .errors import fail, keys


VERSION = 'schemaxis.resource.adoption/1'
_REFERENCE = ('$resource', 'digest', 'member', 'origin', 'maxFiles', 'maxBytes')
_LIMITATIONS = [
    'the snapshot is a copy of a stable checkpoint; live writers are not coordinated',
    'units, coordinate frames and native project dependencies are not inferred',
    'the manifest digest detects changes; it is not a signature',
]


def is_reference(value):
    return isinstance(value, dict) and '$resource' in value


def references(value, pointer=''):
    """Yield ``(JSON pointer, reference)`` for every captured-input reference."""
    if is_reference(value):
        yield pointer, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from references(child, pointer + '/' + str(key).replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from references(child, pointer + '/' + str(index))


def consumed(document):
    """Yield ``(pointer, reference)`` at the executable fields of a resolved document.

    Call after ``workflow_inputs`` has resolved composition references. Top-level
    parser-owned metadata (settings, definitions, dimensions) only defines values;
    a reference held there is consumed where a ``$document`` reference resolved it,
    so reader policy, verification and recheck apply at that consumer field only.
    The metadata itself is never removed or changed.
    """
    from .adaptor_runtime import META
    for pointer, value in references(document):
        if not pointer or pointer.split('/')[1] not in META:
            yield pointer, value


# Structural shape only. Snapshot bytes, membership, the pinned digest and the
# consuming adaptor's reader policy are checked by ``consume`` on the host.
_SEGMENT = r'(?!\.\.?(?:/|$))[^/\\\u0000]+'


def reference_schema():
    """Closed JSON Schema matching ``check_reference``; used only in workflow scope."""
    return {'type': 'object', 'properties': {
        '$resource': {'type': 'string', 'pattern': '^/'},
        # Exact length too: some regex engines let ``$`` match before a final newline.
        'digest': {'type': 'string', 'minLength': 64, 'maxLength': 64, 'pattern': '^[0-9a-f]{64}$'},
        'member': {'type': 'string', 'minLength': 1, 'maxLength': 4096,
                   'pattern': '^(?![A-Za-z]:)' + _SEGMENT + '(?:/' + _SEGMENT + ')*$'},
        'origin': {'type': 'string', 'minLength': 1, 'maxLength': 1024},
        'maxFiles': {'type': 'integer', 'minimum': 1},
        'maxBytes': {'type': 'integer', 'minimum': 0}},
        'required': ['$resource', 'digest'], 'additionalProperties': False}


def check_reference(value, location):
    """Validate reference shape without filesystem access."""
    keys(value, _REFERENCE, location)
    snapshot = value['$resource']
    if not isinstance(snapshot, str) or not snapshot or not Path(snapshot).is_absolute():
        fail('INVALID_RESOURCE', '$resource must be an absolute snapshot directory', location)
    if not isinstance(value.get('digest'), str) or not re.fullmatch('[0-9a-f]{64}', value['digest']):
        fail('INVALID_RESOURCE', '$resource needs the trusted 64-hex manifest digest', location + '/digest')
    if 'member' in value:
        resources._relative(value['member'], location + '/member')
    if 'origin' in value and (not isinstance(value['origin'], str) or not 0 < len(value['origin']) <= 1024):
        fail('INVALID_RESOURCE', 'origin must be a nonempty description of at most 1024 characters', location + '/origin')
    resources._limits(value.get('maxFiles', 10000), value.get('maxBytes', 1073741824))
    return value


def adopt(source, destination, *, kind='file', members=None, max_files=10000, max_bytes=1073741824):
    """Capture a stable saved file, file set or directory and return its reference."""
    manifest = resources.capture(source, destination, kind=kind, members=members,
                                 max_files=max_files, max_bytes=max_bytes)
    snapshot = os.path.abspath(Path(destination).expanduser())
    reference = {'$resource': snapshot, 'digest': manifest['digest']}
    if kind == 'file':
        reference['member'] = manifest['files'][0]['path']
    # Chosen bounds travel with the reference so later checks use the same
    # limits; defaults are omitted. Bounds are never enlarged implicitly.
    if max_files != 10000:
        reference['maxFiles'] = max_files
    if max_bytes != 1073741824:
        reference['maxBytes'] = max_bytes
    return {'version': VERSION, 'snapshot': snapshot, 'kind': kind, 'digest': manifest['digest'],
            'files': len(manifest['files']), 'directories': len(manifest['directories']),
            'totalBytes': manifest['totalBytes'], 'reference': reference,
            'units': 'unknown', 'frame': 'unknown', 'limitations': list(_LIMITATIONS)}


def open_reference(value, location):
    """Verify a snapshot against its pinned digest; return the consumed path and facts."""
    check_reference(value, location)
    limits = {'max_files': value.get('maxFiles', 10000), 'max_bytes': value.get('maxBytes', 1073741824)}
    manifest = resources.verify(value['$resource'], **limits)
    if manifest['digest'] != value['digest']:
        fail('INPUT_CHANGED', 'captured input differs from the pinned digest; adopt a new snapshot '
             'and update the workflow deliberately', location, expected=value['digest'],
             observed=manifest['digest'])
    files = [record['path'] for record in manifest['files']]
    member = value.get('member')
    if manifest['kind'] == 'file' and member is None:
        member = files[0]
    if member is not None and member not in files:
        fail('RESOURCE_MISMATCH', 'member is not a captured file', location + '/member', member=member)
    data = Path(value['$resource']) / 'data'
    return {'snapshot': value['$resource'], 'digest': manifest['digest'], 'kind': manifest['kind'],
            'member': member, 'path': str(data / member) if member else str(data),
            'data': str(data), 'files': files, 'totalBytes': manifest['totalBytes']}


def consume(document, location, operation=None):
    """Return ``document`` with verified snapshot paths and its input evidence.

    The consuming adaptor owns reader policy. Routes without ``acceptResource``
    refuse captured inputs rather than guessing which files a reader opens.
    Only references at consumer fields are opened; see ``consumed``.
    """
    found = list(consumed(document))
    if not found:
        return document, []
    from .adaptors import registry
    hook = registry.route_hook(document, 'acceptResource', legacy=True)
    evidence, paths = [], {}
    for pointer, value in found:
        if hook is None:
            fail('UNSUPPORTED_RESOURCE', 'this adaptor declares no captured-input policy', location + pointer)
        opened = open_reference(value, location + pointer)
        policy = hook(document, pointer, opened)
        paths[pointer] = opened['path']
        record = {'input': opened['snapshot'], 'pointer': pointer, 'digest': opened['digest'],
                  'kind': opened['kind'], 'member': opened['member'], 'file': opened['path'],
                  'policy': policy, 'units': 'unknown', 'frame': 'unknown',
                  'verification': 'snapshot rechecked against pinned digest'}
        if operation is not None:
            record = {'to': operation, **record}
        if 'origin' in value:
            record['origin'] = value['origin']
        evidence.append(record)

    def substitute(value, pointer=''):
        if pointer in paths:
            return paths[pointer]
        if isinstance(value, dict):
            return {key: substitute(child, pointer + '/' + str(key).replace('~', '~0').replace('/', '~1'))
                    for key, child in value.items()}
        if isinstance(value, list):
            return [substitute(child, pointer + '/' + str(index)) for index, child in enumerate(value)]
        return value
    return substitute(document), evidence


def recheck(document, location):
    """Re-verify every pinned snapshot in ``document`` after its consumer ran.

    This detects ordinary modification while a consumer executed. It is not a
    defence against an adversary replacing and restoring bytes between checks.
    """
    for pointer, value in consumed(document):
        open_reference(value, location + pointer)
