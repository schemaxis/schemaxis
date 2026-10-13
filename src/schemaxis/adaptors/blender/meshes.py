"""Native geometry construction for the curated Blender declarations."""
import math
import bmesh
from mathutils import Matrix, Euler, Vector
from schemaxis.adaptors.blender.operations import PRIMITIVES


def populate(mesh, kind, values):
    mesh.clear_geometry()
    if kind in ('polylineTube', 'curveFromCSV'):
        if kind == 'curveFromCSV':
            from .table_curve import points_from_csv
            values = {**values, 'points': points_from_csv(values)}
        populate_tube(mesh, values)
    elif kind == 'lathe':
        from .profiles import lathe_mesh
        points, faces = lathe_mesh(values['profile'], values['segments'], values['caps'])
        mesh.from_pydata(points, [], faces)
    elif kind == 'grid':
        nx, ny = values['xSegments'], values['ySegments']
        points = [((i/nx-.5)*values['width'], (j/ny-.5)*values['height'], 0)
                  for j in range(ny+1) for i in range(nx+1)]
        faces = [(j*(nx+1)+i, j*(nx+1)+i+1, (j+1)*(nx+1)+i+1, (j+1)*(nx+1)+i)
                 for j in range(ny) for i in range(nx)]
        mesh.from_pydata(points, [], faces)
    elif kind == 'disk':
        n = values['segments']
        mesh.from_pydata([(values['radius']*math.cos(2*math.pi*i/n), values['radius']*math.sin(2*math.pi*i/n), 0)
                          for i in range(n)], [], [tuple(range(n))])
    elif kind == 'plane':
        x, y = values['width']/2, values['height']/2
        mesh.from_pydata([(-x,-y,0), (x,-y,0), (x,y,0), (-x,y,0)], [], [(0,1,2,3)])
    elif kind == 'torus':
        n, m = values['majorSegments'], values['minorSegments']
        points = []
        for i in range(n):
            a = 2*math.pi*i/n
            for j in range(m):
                b = 2*math.pi*j/m
                r = values['majorRadius'] + values['minorRadius']*math.cos(b)
                points.append((r*math.cos(a), r*math.sin(a), values['minorRadius']*math.sin(b)))
        faces = [(i*m+j, ((i+1)%n)*m+j, ((i+1)%n)*m+(j+1)%m, i*m+(j+1)%m)
                 for i in range(n) for j in range(m)]
        mesh.from_pydata(points, [], faces)
    else:
        bm = bmesh.new()
        try:
            if kind == 'uvSphere':
                bmesh.ops.create_uvsphere(bm, u_segments=values['segments'], v_segments=values['rings'], radius=values['radius'])
            elif kind == 'icoSphere':
                bmesh.ops.create_icosphere(bm, subdivisions=values['subdivisions'], radius=values['radius'])
            elif kind in ('cone', 'cylinder'):
                bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=values['segments'],
                                      radius1=values['radius'], radius2=values.get('tipRadius', values['radius']),
                                      depth=values['depth'])
            else:
                raise ValueError('undeclared primitive: ' + kind)
            bm.to_mesh(mesh)
        finally:
            bm.free()
    for face in mesh.polygons:
        face.use_smooth = values['smoothShading']
    mesh.update()


def transform(values):
    rotation = Euler([math.radians(x) for x in values['rotation']], 'XYZ').to_matrix().to_4x4()
    return Matrix.Translation(Vector(values['translation'])) @ rotation @ Matrix.Diagonal([*values['scale'], 1])


def populate_tube(mesh, values):
    """Convert a bounded native POLY curve; temporary datablocks never leak."""
    import bpy
    from schemaxis.errors import fail
    from .settings import matching
    points = values['points']
    if not 2 <= len(points) <= 1024 or any(len(p)!=3 or any(not math.isfinite(v) or abs(v)>100000 for v in p) for p in points):
        fail('INVALID_GEOMETRY', 'tube needs 2 to 1024 finite points within +/-100000')
    pairs = list(zip(points, points[1:]))
    if values['closed']:
        if len(points) < 3: fail('INVALID_GEOMETRY', 'closed tube needs at least three points')
        pairs.append((points[-1], points[0]))
    if any(math.dist(a, b) < 1e-8 for a, b in pairs):
        fail('INVALID_GEOMETRY', 'tube contains a zero-length segment')
    curve = bpy.data.curves.new('schemaxis-tube-source', 'CURVE')
    obj = bpy.data.objects.new('schemaxis-tube-source', curve)
    bpy.context.scene.collection.objects.link(obj)
    try:
        curve.dimensions = '3D'
        curve.bevel_depth = values['radius']
        curve.bevel_resolution = values['resolution']
        curve.use_fill_caps = values['caps']
        spline = curve.splines.new('POLY')
        spline.points.add(len(points)-1)
        for point, coordinate in zip(spline.points, points): point.co = [*coordinate, 1]
        spline.use_cyclic_u = values['closed']
        if not matching(curve.bevel_depth, values['radius']) or curve.bevel_resolution != values['resolution']:
            fail('NATIVE_VALUE_MISMATCH', 'native curve bevel differs')
        if curve.use_fill_caps != values['caps'] or spline.use_cyclic_u != values['closed']:
            fail('NATIVE_VALUE_MISMATCH', 'native curve closure differs')
        if any(not matching(list(point.co)[:3], coordinate) for point, coordinate in zip(spline.points, points)):
            fail('NATIVE_VALUE_MISMATCH', 'native curve points differ')
        bpy.context.view_layer.update()
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        native_mesh = evaluated.to_mesh()
        bm = bmesh.new()
        try:
            bm.from_mesh(native_mesh)
            bm.to_mesh(mesh)
        finally:
            bm.free()
            evaluated.to_mesh_clear()
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.curves.remove(curve)
