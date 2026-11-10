"""High-level presentation intent with independently checked geometric decisions."""
import math
import re

from schemaxis.errors import fail
from schemaxis.schema import NAME, object_schema


def intent_schema_property():
    frame = {'type': 'integer', 'minimum': 0, 'maximum': 1_000_000}
    vector = {'type': 'array', 'minItems': 3, 'maxItems': 3, 'items': {'type': 'number'}}
    return {'type': 'array', 'maxItems': 32, 'items': object_schema({
        'id': NAME, 'kind': {'const': 'turntable'},
        'objects': {'type': 'array', 'items': NAME, 'minItems': 1, 'maxItems': 1024, 'uniqueItems': True},
        'axis': {'enum': ['X', 'Y', 'Z'], 'default': 'Z'},
        'angleDegrees': {'type': 'number', 'minimum': -36000, 'maximum': 36000, 'default': 360},
        'startFrame': frame, 'endFrame': frame,
        'pivot': {'oneOf': [{'const': 'boundsCentre'}, vector], 'default': 'boundsCentre'}},
        ['id', 'kind', 'objects'])}


def validate_intents(value, objects, timeline, where='production.intents'):
    if not isinstance(value, list) or len(value) > 32:
        fail('INVALID_INTENT', 'intents must be an array of at most 32 reusable tasks', where)
    result, names, claimed = [], set(), set()
    for i, raw in enumerate(value):
        at = f'{where}[{i}]'
        if not isinstance(raw, dict) or set(raw) - {'id', 'kind', 'objects', 'axis', 'angleDegrees', 'startFrame', 'endFrame', 'pivot'}:
            fail('INVALID_INTENT', 'choose a typed turntable intent; arbitrary native fields are not accepted', at)
        identity = raw.get('id')
        if not isinstance(identity, str) or not re.fullmatch(NAME['pattern'], identity) or identity in names or 'SX_INTENT_'+identity in objects:
            fail('INVALID_INTENT', 'intent ID must be unique and leave its generated control name available', at+'.id')
        if raw.get('kind') != 'turntable':
            fail('UNSUPPORTED_INTENT', 'supported presentation task is turntable', at+'.kind')
        selected = raw.get('objects')
        if (not isinstance(selected, list) or not 1 <= len(selected) <= 1024
                or any(not isinstance(n, str) or n not in objects or n in claimed for n in selected)
                or len(selected) != len(set(selected))):
            fail('INVALID_REFERENCE', 'use unique declared objects, controlled by only one intent', at+'.objects')
        axis, angle = raw.get('axis', 'Z'), raw.get('angleDegrees', 360)
        if not isinstance(axis, str) or axis not in ('X', 'Y', 'Z'):
            fail('INVALID_INTENT', 'turntable axis is X, Y or Z in world coordinates', at+'.axis')
        if type(angle) not in (int, float) or not math.isfinite(angle) or not 0 < abs(angle) <= 36000:
            fail('INVALID_INTENT', 'angleDegrees must be finite, nonzero and at most 100 turns', at+'.angleDegrees')
        start, end = raw.get('startFrame', timeline['frameStart']), raw.get('endFrame', timeline['frameEnd'])
        if (type(start) is not int or type(end) is not int
                or not timeline['frameStart'] <= start < end <= timeline['frameEnd']):
            fail('INVALID_TIMELINE', 'turntable needs two ordered frames within the production range', at)
        pivot = raw.get('pivot', 'boundsCentre')
        if pivot != 'boundsCentre' and (not isinstance(pivot, list) or len(pivot) != 3
                or any(type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 1e12 for x in pivot)):
            fail('INVALID_INTENT', 'pivot is boundsCentre or a finite position in production units', at+'.pivot')
        result.append({'id': identity, 'kind': 'turntable', 'objects': list(selected), 'axis': axis,
                       'angleDegrees': angle, 'startFrame': start, 'endFrame': end,
                       'pivot': list(pivot) if isinstance(pivot, list) else pivot})
        names.add(identity)
        claimed.update(selected)
    return result


def _matrix(pivot, axis, degrees):
    angle = math.radians(degrees)
    c, s = math.cos(angle), math.sin(angle)
    rotation = {'X': [[1, 0, 0], [0, c, -s], [0, s, c]],
                'Y': [[c, 0, s], [0, 1, 0], [-s, 0, c]],
                'Z': [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis]
    return [rotation[i] + [pivot[i]-sum(rotation[i][j]*pivot[j] for j in range(3))]
            for i in range(3)] + [[0, 0, 0, 1]]


def _close(a, b):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    return (type(a) in (int, float) and type(b) in (int, float) and math.isfinite(a)
            and math.isfinite(b) and math.isclose(a, b, rel_tol=2e-6, abs_tol=2e-6))


def verify_intents(spec, records, baseline=None):
    try:
        return _verify_intents(spec, records, baseline)
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, OverflowError) as error:
        fail('VERIFICATION_FAILED', 'presentation evidence is malformed: '+str(error))


def _verify_intents(spec, records, baseline=None):
    if not isinstance(records, list) or len(records) != len(spec):
        fail('VERIFICATION_FAILED', 'presentation intent membership differs')
    for intent, observed in zip(spec, records):
        at = 'intent.'+intent['id']
        if (observed.get('id') != intent['id'] or observed.get('control') != 'SX_INTENT_'+intent['id']
                or observed.get('selected') != intent['objects'] or observed.get('parent') is not None
                or observed.get('rotationMode') != 'XYZ' or not _close(observed.get('scale'), [1, 1, 1])):
            fail('VERIFICATION_FAILED', 'presentation control identity or ownership differs', at)
        bounds = observed.get('beforeBounds')
        if (not isinstance(bounds, list) or len(bounds) != 6 or not all(type(x) in (int, float) and math.isfinite(x) for x in bounds)
                or any(bounds[i] > bounds[i+1] for i in (0, 2, 4))):
            fail('VERIFICATION_FAILED', 'presentation source bounds are invalid', at)
        pivot = [(bounds[i]+bounds[i+1])/2 for i in (0, 2, 4)] if intent['pivot'] == 'boundsCentre' else intent['pivot']
        if not _close(observed.get('pivot'), pivot):
            fail('VERIFICATION_FAILED', 'presentation pivot differs from the geometric decision', at)
        roots = observed.get('roots')
        if (not isinstance(roots, list) or not roots or len(set(roots)) != len(roots)
                or not set(roots) <= set(intent['objects'])
                or observed.get('rootParents') != {n: observed['control'] for n in roots}
                or set(observed.get('beforeWorld', {})) != set(roots)):
            fail('VERIFICATION_FAILED', 'presentation root ownership differs', at)
        for axis, curve in enumerate(observed.get('curves', [])):
            expected = [[intent['startFrame'], 0], [intent['endFrame'], math.radians(intent['angleDegrees']) if axis == 'XYZ'.index(intent['axis']) else 0]]
            if (type(curve.get('index')) is not int or curve.get('index') != axis or curve.get('path') != 'rotation_euler'
                    or curve.get('muted') is not False or curve.get('modifiers') != 0
                    or curve.get('extrapolation') != 'CONSTANT'
                    or curve.get('interpolation') != ['LINEAR', 'LINEAR'] or not _close(curve.get('keys'), expected)):
                fail('VERIFICATION_FAILED', 'presentation motion curve differs', at)
        if len(observed.get('curves', [])) != 3:
            fail('VERIFICATION_FAILED', 'presentation needs exactly three rotation channels', at)
        frames = [intent['startFrame'], (intent['startFrame']+intent['endFrame'])/2, intent['endFrame']]
        samples = observed.get('samples', [])
        if len(samples) != 3:
            fail('VERIFICATION_FAILED', 'presentation sample membership differs', at)
        for f, sample in zip(frames, samples):
            if not _close(sample.get('frame'), f) or set(sample.get('world', {})) != set(roots):
                fail('VERIFICATION_FAILED', 'presentation sampled frame/objects differ', at)
            angle = intent['angleDegrees']*(f-intent['startFrame'])/(intent['endFrame']-intent['startFrame'])
            transform = _matrix(pivot, intent['axis'], angle)
            for root in roots:
                before = observed['beforeWorld'][root]
                if not isinstance(before, list) or len(before) != 4 or any(not isinstance(r, list) or len(r) != 4 for r in before):
                    fail('VERIFICATION_FAILED', 'presentation source transform is malformed', at)
                expected = [[sum(transform[i][k]*before[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
                if not _close(sample['world'][root], expected):
                    fail('VERIFICATION_FAILED', 'presentation evaluated motion differs from independent rigid rotation', at)
    return True
