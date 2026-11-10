"""Analytic intent for the bounded primitive family; no native imports."""
import math

PRIMITIVES = ('box', 'cylinder', 'hollowCylinder', 'sphere')


def measures(source):
    """Exact volume and world-axis bounds, independently of OpenCASCADE."""
    kind, options = source['filter'], source['options']
    if kind == 'box':
        origin, size = options['origin'], options['size']
        return math.prod(size), origin+[a+b for a,b in zip(origin,size)]
    radius = options['radius']
    if kind == 'sphere':
        centre = options['centre']
        return 4*math.pi*radius**3/3, [c-radius for c in centre]+[c+radius for c in centre]
    axis = 'xyz'.index(options['axis']); origin = options['origin']
    lower = [c-radius if i != axis else c for i,c in enumerate(origin)]
    upper = [c+radius if i != axis else c+options['height'] for i,c in enumerate(origin)]
    inner = options.get('innerRadius',0)
    return math.pi*(radius**2-inner**2)*options['height'], lower+upper


def verify(source, cad, data):
    """Verify primitive CAD readback and every mesh node against analytic intent."""
    from .mesh import check
    kind, options = source['filter'], source['options']
    volume, bounds = measures(source)
    check(math.isclose(cad['volume'],volume,rel_tol=1e-10,abs_tol=1e-8), 'CAD volume differs from analytic primitive')
    check(len(cad['bounds']) == 6 and all(abs(a-b) <= 1e-6 for a,b in zip(cad['bounds'],bounds)),
          'CAD bounds differ from analytic primitive')
    for point in data['nodes'].values():
        check(all(bounds[i]-1e-6 <= point[i] <= bounds[i+3]+1e-6 for i in range(3)),
              'mesh node exceeds analytic primitive bounds')
        if kind == 'sphere':
            distance = math.dist(point,options['centre'])
            check(distance <= options['radius']+1e-6, 'mesh node exceeds analytic sphere')
        elif kind in ('cylinder','hollowCylinder'):
            axis = 'xyz'.index(options['axis'])
            radial = math.sqrt(math.fsum((point[i]-options['origin'][i])**2 for i in range(3) if i != axis))
            check(options.get('innerRadius',0)-1e-6 <= radial <= options['radius']+1e-6,
                  'mesh node exceeds analytic cylinder or enters its bore')


    # A closed mesh inside the envelope can still have a dented boundary. Each
    # boundary triangle must belong to one analytic surface, using vertices;
    # straight chord interiors intentionally approximate curved surfaces.
    for dimension, _, vertices in data.get('cells', []):
        if dimension != 2:
            continue
        points = [data['nodes'][tag] for tag in vertices]
        if kind == 'sphere':
            on_surface = all(abs(math.dist(point,options['centre'])-options['radius']) <= 1e-6 for point in points)
        elif kind in ('cylinder','hollowCylinder'):
            axis = 'xyz'.index(options['axis'])
            on_cap = any(all(abs(point[axis]-plane) <= 1e-6 for point in points)
                         for plane in (options['origin'][axis],options['origin'][axis]+options['height']))
            radii = [math.sqrt(math.fsum((point[i]-options['origin'][i])**2 for i in range(3) if i != axis))
                     for point in points]
            on_wall = any(all(abs(radial-radius) <= 1e-6 for radial in radii)
                          for radius in [options['radius']]+([options['innerRadius']] if kind == 'hollowCylinder' else []))
            on_surface = on_cap or on_wall
        else:
            on_surface = any(all(abs(point[axis]-plane) <= 1e-6 for point in points)
                             for axis in range(3) for plane in (bounds[axis],bounds[axis+3]))
        check(on_surface, 'boundary triangle vertices differ from analytic primitive surface')


def face_area(source, selector):
    """Exact selected cap area when the primitive contract determines one."""
    kind, options = source['filter'], source['options']
    if kind == 'box':
        axis = 'xyz'.index(selector['axis'])
        if any(abs(selector['coordinate']-v) <= selector['tolerance'] for v in
               (options['origin'][axis],options['origin'][axis]+options['size'][axis])):
            return math.prod(v for i,v in enumerate(options['size']) if i != axis)
    elif kind in ('cylinder','hollowCylinder') and selector['axis'] == options['axis']:
        axis = 'xyz'.index(options['axis'])
        if any(abs(selector['coordinate']-v) <= selector['tolerance'] for v in
               (options['origin'][axis],options['origin'][axis]+options['height'])):
            return math.pi*(options['radius']**2-options.get('innerRadius',0)**2)
    return None


def walls(source):
    """Analytic cylindrical walls of a primitive, each with its axial range."""
    kind, options = source['filter'], source['options']
    if kind not in ('cylinder', 'hollowCylinder'):
        return []
    axis = 'xyz'.index(options['axis'])
    lower = options['origin'][axis]
    result = [{'axis': options['axis'], 'centre': options['origin'], 'radius': options['radius'],
               'side': 'outer', 'range': [lower, lower+options['height']]}]
    if kind == 'hollowCylinder':
        result.append({**result[0], 'radius': options['innerRadius'], 'side': 'inner'})
    return result


def wall_match(wall, group):
    """True when a selector describes this analytic wall within the selector's tolerance."""
    transverse = [k for k in range(3) if k != 'xyz'.index(group['axis'])]
    return (wall['axis'] == group['axis'] and wall['side'] == group['side']
            and abs(wall['radius']-group['radius']) <= group['tolerance']
            and all(abs(wall['centre'][k]-group['centre'][k]) <= group['tolerance'] for k in transverse))


def remainder_empty(source, settings):
    """True when a primitive's declared plane and cylinder groups cover its entire boundary."""
    walls_ = walls(source)
    if not walls_ or not settings.get('cylinderGroups'):
        return False
    options = source['options']
    covered = all(any(wall_match(w, g) for g in settings['cylinderGroups']) for w in walls_)
    ends = [w for w in walls_[0]['range']]
    caps = all(any(g['axis'] == options['axis'] and abs(g['coordinate']-end) <= g['tolerance']
                   for g in settings['faceGroups']) for end in ends)
    return covered and caps


def verify_wall(source, group, report):
    """Check a measured wall against the primitive's exact lateral area and axial extent."""
    from .mesh import check
    wall = next((w for w in walls(source) if wall_match(w, group)), None)
    check(wall is not None, 'cylinder group does not describe a wall of the primitive')
    lower, upper = wall['range']
    check(math.isclose(report['unrolledArea'], 2*math.pi*wall['radius']*(upper-lower), rel_tol=1e-9, abs_tol=1e-9),
          'unrolled wall area differs from 2*pi*r*h')
    check(abs(report['axialRange'][0]-lower) <= 1e-6 and abs(report['axialRange'][1]-upper) <= 1e-6,
          'wall axial extent differs from the primitive')
    return 2*math.pi*wall['radius']*(upper-lower)
