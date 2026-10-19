"""Checked import of one external STEP solid (host policy for the `importSTEP` node).

The authored units assert what the file itself assigns; OCCT converts that unit to
millimetres and no second scale is applied. Orientation maps signed file axes to
part axes, placement then positions the part. Expectations are analyst-declared
facts in the part frame (after units and orientation, before placement). They
check those facts only: symmetric parts or poorly chosen points can hide a mirror,
turn or different identity, and OCCT may silently repair file orientation.
"""
import math
from schemaxis.errors import fail
from . import step_source

AXES = {'+X': (1, 0, 0), '-X': (-1, 0, 0), '+Y': (0, 1, 0), '-Y': (0, -1, 0), '+Z': (0, 0, 1), '-Z': (0, 0, -1)}
AXIS = {'type': 'enum', 'values': list(AXES)}
POINT = {'type': 'array', 'items': {'type': 'number', 'minimum': -1e6, 'maximum': 1e6}, 'minItems': 3, 'maxItems': 3}
POINTS = {'type': 'array', 'items': POINT, 'minItems': 0, 'maxItems': 32, 'default': []}
MAX_COORDINATE = 100000


def declaration(declare):
    result = declare('Part::Feature', {
        'file': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True},
        'units': {'type': 'enum', 'values': list(step_source.UNITS), 'required': True},
        'orientation': {'type': 'object', 'default': {'z': '+Z'}, 'properties': {
            'z': {**AXIS, 'default': '+Z'}, 'x': AXIS}},
        'placement': {'type': 'object', 'default': {'position': [0, 0, 0], 'clocking': 0}, 'properties': {
            'position': {'type': 'array', 'items': {'type': 'number', 'minimum': -MAX_COORDINATE, 'maximum': MAX_COORDINATE},
                         'minItems': 3, 'maxItems': 3, 'default': [0, 0, 0]},
            'clocking': {'type': 'number', 'minimum': -360, 'maximum': 360, 'default': 0}}},
        'expect': {'type': 'object', 'required': True, 'properties': {
            'volume': {'type': 'object', 'required': True, 'properties': {
                'value': {'type': 'number', 'minimum': 0, 'exclusiveMinimum': True, 'maximum': 1e15, 'required': True},
                'relativeTolerance': {'type': 'number', 'minimum': 1e-9, 'maximum': 0.01, 'default': 1e-6}}},
            'centreOfMass': {'type': 'object', 'properties': {
                'value': {**POINT, 'required': True},
                'tolerance': {'type': 'number', 'minimum': 1e-6, 'maximum': 1, 'default': 0.01}}},
            'bounds': {'type': 'object', 'properties': {
                'value': {'type': 'array', 'items': {'type': 'number', 'minimum': -1e6, 'maximum': 1e6},
                          'minItems': 6, 'maxItems': 6, 'required': True},
                'tolerance': {'type': 'number', 'minimum': 1e-6, 'maximum': 1, 'default': 0.01}}},
            'points': {'type': 'object', 'properties': {
                'inside': POINTS, 'outside': POINTS,
                'guard': {'type': 'number', 'minimum': 1e-6, 'maximum': 10, 'required': True}}}}},
        'refine': {'type': 'boolean', 'default': False}})
    return result


def orientation(raw, location):
    z = raw.get('z', '+Z')
    x = raw.get('x')
    if x is None:
        if z not in ('+Z', '-Z'):
            fail('INVALID_AXIS', 'Give orientation.x when orientation.z is not +Z or -Z', location+'.x')
        x = '+X'
    fz, fx = AXES[z], AXES[x]
    if sum(a*b for a, b in zip(fz, fx)) != 0:
        fail('INVALID_AXIS', 'orientation.x must be perpendicular to orientation.z', location+'.x', z=z, x=x)
    fy = (fz[1]*fx[2]-fz[2]*fx[1], fz[2]*fx[0]-fz[0]*fx[2], fz[0]*fx[1]-fz[1]*fx[0])
    # Rows map file coordinates to part coordinates: part_x = p.fx, part_y = p.fy, part_z = p.fz.
    return {'z': z, 'x': x}, [list(map(float, fx)), list(map(float, fy)), list(map(float, fz))]


def clocking_rotation(degrees):
    quarter = degrees/90
    if quarter == round(quarter):
        c, s = [(1, 0), (0, 1), (-1, 0), (0, -1)][int(round(quarter)) % 4]
    else:
        c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [[float(c), float(-s), 0.0], [float(s), float(c), 0.0], [0.0, 0.0, 1.0]]


def multiply(a, b):
    return [[sum(a[r][k]*b[k][c] for k in range(3)) for c in range(3)] for r in range(3)]


def check_expectations(expect, location):
    points = expect.get('points')
    if points is not None:
        if not points['inside'] and not points['outside']:
            fail('INVALID_ARGUMENT', 'expect.points needs at least one inside or outside point', location+'.points')
    has_points = points is not None and points['inside'] and points['outside']
    if 'centreOfMass' not in expect and not has_points:
        fail('INVALID_ARGUMENT', 'Declare expect.centreOfMass or at least one inside and one outside point besides volume; '
             'bounds, volume and area alone accept a mirrored or turned part', location,
             recovery='add the part-frame centre of mass from the drawing, or points that must lie inside and outside the solid')
    bounds = expect.get('bounds')
    if bounds is not None and any(bounds['value'][2*k] > bounds['value'][2*k+1] for k in range(3)):
        fail('INVALID_ARGUMENT', 'expect.bounds must be [xmin,xmax,ymin,ymax,zmin,zmax]', location+'.bounds')


def prepare(identity, options, provider):
    """Host facts bound into the plan: resolved source, admission facts and frames."""
    location = identity+'.options'
    normalised, part_from_file = orientation(options['orientation'], location+'.orientation')
    options['orientation'] = normalised
    rotation = clocking_rotation(options['placement']['clocking'])
    check_expectations(options['expect'], location+'.expect')
    provider = provider or step_source.AuthoredSources()
    frame = {'partFromFile': part_from_file, 'worldFromPart': rotation, 'worldFromFile': multiply(rotation, part_from_file),
             'translation': [float(v) for v in options['placement']['position']]}
    if getattr(provider, 'reads', True) is False:
        return {'frame': frame}
    path, data = provider.read(options['file'], identity, location+'.file')
    facts = step_source.admit(data, location+'.file')
    if facts['unit'] != options['units']:
        fail('UNIT_MISMATCH', 'The STEP file assigns a different length unit than the authored units', location+'.units',
             authored=options['units'], assigned=facts['unit'],
             recovery='set units to what the file declares; units assert file meaning and never rescale it')
    return {'source': {'path': path, **{k: facts[k] for k in ('sha256', 'bytes', 'schema', 'unit', 'structure', 'solid',
                                                               'entities', 'maxLoopEdges')}},
            'frame': frame}


def within(a, b, tolerance):
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in (*a, *b)) and len(a) == len(b) \
        and math.dist(a, b) <= tolerance


def evaluate(expect, observed, location):
    """Host re-evaluation of the native part-frame observation against declared facts."""
    def fault(member, message, **detail):
        fail('EXPECTATION_FAILED', message, location+'.'+member, **detail)
    volume = observed.get('volume')
    if not isinstance(volume, float) or not math.isfinite(volume) or \
            abs(volume-expect['volume']['value']) > expect['volume']['relativeTolerance']*expect['volume']['value']:
        fault('volume', 'Imported part volume differs from the declared value', expected=expect['volume']['value'],
              observed=volume, relativeTolerance=expect['volume']['relativeTolerance'])
    if 'centreOfMass' in expect and not within(observed.get('centreOfMass', []), expect['centreOfMass']['value'],
                                                expect['centreOfMass']['tolerance']):
        fault('centreOfMass', 'Imported part centre of mass differs from the declared value',
              expected=expect['centreOfMass']['value'], observed=observed.get('centreOfMass'),
              tolerance=expect['centreOfMass']['tolerance'])
    if 'bounds' in expect:
        bounds = observed.get('bounds', [])
        if len(bounds) != 6 or any(not math.isfinite(b) or abs(b-e) > expect['bounds']['tolerance']
                                   for b, e in zip(bounds, expect['bounds']['value'])):
            fault('bounds', 'Imported part bounds differ from the declared value', expected=expect['bounds']['value'],
                  observed=bounds, tolerance=expect['bounds']['tolerance'])
    points = expect.get('points')
    records = observed.get('points', {})
    for side in ('inside', 'outside'):
        declared = points[side] if points else []
        found = records.get(side, [])
        if len(found) != len(declared):
            fault('points', 'Imported part point observations are incomplete')
        for k, (point, record) in enumerate(zip(declared, found)):
            distance = record.get('distance')
            member = 'points.'+side+'['+str(k)+']'
            if not isinstance(distance, float) or not math.isfinite(distance) or distance < points['guard']:
                fail('INVALID_ARGUMENT', 'Declared point is within the guard distance of the surface; choose a clearly '
                     'interior or exterior point', location+'.'+member, distance=distance, guard=points['guard'])
            if record.get('inside') is not (side == 'inside'):
                fault(member, 'Declared point lies on the wrong side of the imported solid', point=point,
                      expected=side, distance=distance)
