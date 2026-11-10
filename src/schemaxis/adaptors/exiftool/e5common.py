"""Shared parts of the E5 container locators: result shape, slot states, offset-free protected fingerprints (standard library only).

Every container locator returns the shape of ``containers.locate`` (``container``, ``exif``, ``xmp``, ``iptc``, ``frame``, ``notes``) plus

* ``slots``: one record per metadata family with a state: ``present``, ``absent``, ``unreadable``, ``ambiguous`` or ``unsupported``;
* ``protected``: the fingerprint, an ordered list of ``(role, key, length, sha256)`` that excludes every offset, so a rewrite may relocate
  bytes but may not change, add, drop or reorder a protected part;
* ``ranges``: where each protected part lies in this file (``(role, key, offset, length)``), for streaming writers and readers;
* ``write``: ``{'admissible': bool, 'refusals': [...]}``: reading and writing are separate decisions. A file can be fully readable while a
  write is refused before any native process runs;
* ``limitations``: bounded published guarantees that apply to this file.

Nothing here decodes pixels.
"""
import hashlib

from schemaxis.adaptors.exiftool.containers import Refused

FAMILIES = ('exif', 'xmp', 'iptc')
STATES = ('present', 'absent', 'unreadable', 'ambiguous', 'unsupported')

__all__ = ['Refused', 'FAMILIES', 'STATES', 'sha', 'entry', 'new_result', 'slot', 'refuse_write', 'finish', 'compare']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def entry(role, key, data):
    """One fingerprint row. ``data`` may be bytes or a memoryview slice of the whole file (hashed without a copy)."""
    return (role, str(key), len(data), sha(data))


def new_result(container, frame=None):
    return {'container': container, 'exif': [], 'xmp': [], 'iptc': [], 'frame': frame, 'notes': [], 'slots': [], 'protected': [], 'ranges': [],
            'write': {'admissible': True, 'refusals': []}, 'limitations': []}


def slot(family, state, *, role=None, count=0, code=None, message=None, **extra):
    if family not in FAMILIES or state not in STATES:
        raise ValueError('unknown slot family or state')
    record = {'family': family, 'state': state, 'role': role, 'count': count}
    if code:
        record['code'] = code
        record['message'] = message or code
    record.update(extra)
    return record


def refuse_write(result, code, message, **observed):
    """Record a precise write refusal (once per code and observation); the file stays readable."""
    refusal = {'code': code, 'message': message}
    if observed:
        refusal['observed'] = observed
    if refusal not in result['write']['refusals']:
        result['write']['refusals'].append(refusal)
    result['write']['admissible'] = False


def finish(result):
    """Slot problems also refuse a write: an unreadable, ambiguous or unsupported slot cannot be edited safely."""
    for record in result['slots']:
        known = {r['code'] for r in result['write']['refusals']}
        if record['state'] in ('unreadable', 'unsupported') and record.get('code') and record['code'] not in known:
            refuse_write(result, record['code'], record['message'], family=record['family'])
    return result


def compare(before, after, *, allow=()):
    """Faults between two fingerprints as ``[{'kind', 'path', 'role', 'key'}]``; empty when equal.

    ``allow`` holds ``(role, key)`` pairs or bare roles that a plan declares changeable (planned targets, closed side effects); those rows
    are ignored on both sides. Reordering of protected rows is a fault.
    """
    def keep(rows):
        return [row for row in rows if row[0] not in allow and (row[0], row[1]) not in allow]
    left, right = keep(before), keep(after)
    if left == right:
        return []
    faults = []
    after_by_name = {(r[0], r[1]): r for r in right}
    before_names = {(r[0], r[1]) for r in left}
    for row in left:
        other = after_by_name.get((row[0], row[1]))
        kind = 'missing' if other is None else ('changed' if other != row else None)
        if kind:
            faults.append({'kind': kind, 'path': '%s[%s]' % (row[0], row[1]), 'role': row[0], 'key': row[1]})
    for row in right:
        if (row[0], row[1]) not in before_names:
            faults.append({'kind': 'added', 'path': '%s[%s]' % (row[0], row[1]), 'role': row[0], 'key': row[1]})
    if not faults:
        first = next(i for i, (a, b) in enumerate(zip(left, right)) if a != b)
        faults.append({'kind': 'reordered', 'path': '%s[%s]' % (left[first][0], left[first][1]), 'role': left[first][0], 'key': left[first][1]})
    return faults
