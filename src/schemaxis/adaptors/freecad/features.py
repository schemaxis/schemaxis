"""Trusted native property bindings for the extended CAD feature tree."""
import FreeCAD as App
import Part
from schemaxis.errors import fail

# Values are literal mm/degrees; option-to-native mapping is application code.
DIMENSIONS = {'length':'Length','width':'Width','height':'Height','radius':'Radius',
              'radius1':'Radius1','radius2':'Radius2','majorRadius':'Radius1','minorRadius':'Radius2'}
PLANES = {'XY':App.Rotation(), 'XZ':App.Rotation(App.Vector(1,0,0),90),
          'YZ':App.Rotation(App.Vector(0,0,1),90).multiply(App.Rotation(App.Vector(1,0,0),90))}


def input_property(kind, port):
    return ('Base' if kind=='extrude' else 'Source') if port=='profile' else port.title()


def configure(obj, node, objects, sources):
    kind, options = node['filter'], node['options']
    if kind == 'importSTEP':
        from .step_import_native import configure as configure_import
        configure_import(obj, node, sources)
        return
    if kind in ('body','pad','pocket'):
        from .part_design_native import configure as configure_body
        configure_body(obj,node,objects)
        return
    if kind not in ('extrude','fillet','chamfer','rectangle','circle'):
        for key, prop in DIMENSIONS.items():
            if key in options:
                setattr(obj, prop, options[key])
    if 'origin' in options and kind != 'revolve':
        obj.Placement.Base = App.Vector(*options['origin'])
    if 'axis' in options and kind != 'revolve':
        obj.Placement.Rotation = App.Rotation(App.Vector(0,0,1),App.Vector(*options['axis']))
    for port,source in node['inputs'].items():
        if port=='body':continue
        setattr(obj,input_property(kind,port),[objects[item] for item in source] if isinstance(source,list) else objects[source])
    if kind == 'loft':
        obj.Solid=True; obj.Ruled=options['ruled']; obj.Closed=False
    elif kind == 'multiFuse':
        obj.Refine=options['refine']
    elif kind in ('rectangle','circle'):
        from .sketch_features import configure as configure_sketch
        obj.Placement.Rotation=PLANES[options['plane']]
        configure_sketch(obj,kind,options)
        if 'body' in node['inputs']:
            from .part_design_native import attach
            attach(obj,objects[node['inputs']['body']])
    elif kind=='polygon':
        obj.Placement.Rotation=PLANES[options['plane']]
        points=[App.Vector(x,y,0) for x,y in options['points']]
        for a,b in zip(points,points[1:]+points[:1]):
            obj.addGeometry(Part.LineSegment(a,b),False)
    elif kind=='extrude':
        obj.DirMode='Custom';obj.Dir=App.Vector(*options['direction']);obj.LengthFwd=options['length'];obj.Solid=True
    elif kind=='revolve':
        obj.Axis=App.Vector(*options['axis']);obj.Base=App.Vector(*options['origin']);obj.Angle=options['angle'];obj.Solid=True
    elif kind in ('fillet','chamfer'):
        base=objects[node['inputs']['base']]
        base.Document.recompute()
        indices = options['edges']
        if isinstance(indices, dict):
            from .selections import native_edges, resolve
            indices = resolve(indices, native_edges(base.Shape), node['id'])
        if any(index>len(base.Shape.Edges) for index in indices):
            fail('INVALID_EDGE', 'edge index exceeds source topology', node['id'], available=len(base.Shape.Edges))
        radius=options['radius'] if kind=='fillet' else options['distance']
        obj.Edges=[(index,radius,radius) for index in indices]
    elif kind=='readSTEP':
        record=sources[node['id']]
        shape=Part.Shape();shape.read(record['retained'])
        if not shape.isValid() or len(shape.Solids)!=1:
            fail('INVALID_GEOMETRY', 'STEP reader requires one valid solid',node['id'])
        obj.Shape=shape
        obj.addProperty('App::PropertyString','SourceSHA256','Schemaxis');obj.SourceSHA256=record['sha256']


def check(obj,node,close,sources,names=None):
    """`names` maps node IDs to their output objects when an import adds a refine output."""
    kind,options=node['filter'],node['options']
    if kind in ('body','pad','pocket'):return
    def require(condition,property):
        if not condition:fail('VERIFICATION_FAILED','native CAD feature setting differs',node['id'],property=property)
    if kind not in ('extrude','fillet','chamfer','rectangle','circle'):
        for key,prop in DIMENSIONS.items():
            if key in options:require(close(float(getattr(obj,prop).Value),options[key]),key)
    if 'origin' in options and kind!='revolve':require(close(list(obj.Placement.Base),options['origin']),'origin')
    if 'axis' in options and kind!='revolve':
        axis=App.Vector(*options['axis']);axis.normalize()
        require(close(list(obj.Placement.Rotation.multVec(App.Vector(0,0,1))),list(axis)),'axis')
    for port,source in node['inputs'].items():
        if port=='body':continue
        value=getattr(obj,input_property(kind,port))
        if names is None:
            require(([item.Label for item in value] if isinstance(source,list) else value.Label)==source,port)
        else:
            require(([item.Name for item in value] if isinstance(source,list) else value.Name)==([names[item] for item in source] if isinstance(source,list) else names[source]),port)
    if kind == 'loft':
        require(obj.Solid and not obj.Closed and obj.Ruled == options['ruled'], 'loft')
    elif kind == 'multiFuse':
        require(obj.Refine == options['refine'], 'refine')
    elif kind in ('rectangle','circle'):
        from .sketch_features import check as check_sketch
        require(close(list(obj.Placement.Rotation.Q),list(PLANES[options['plane']].Q)),'plane')
        check_sketch(obj,kind,options,close,require)
    elif kind=='polygon':
        require(obj.GeometryCount==len(options['points']),'points')
        require(close(list(obj.Placement.Rotation.Q),list(PLANES[options['plane']].Q)),'plane')
        points=options['points']
        for i,(a,b) in enumerate(zip(points,points[1:]+points[:1])):
            require(close(list(obj.Geometry[i].StartPoint),[*a,0]) and close(list(obj.Geometry[i].EndPoint),[*b,0]),'points')
    elif kind=='extrude':
        axis=App.Vector(*options['direction']);axis.normalize();actual=App.Vector(obj.Dir);actual.normalize()
        require(close(list(actual),list(axis)) and close(obj.LengthFwd.Value,options['length']) and obj.Solid and not obj.Symmetric and not obj.Reversed,'extrusion')
    elif kind=='revolve':
        actual=App.Vector(obj.Axis);actual.normalize();axis=App.Vector(*options['axis']);axis.normalize()
        require(close(list(actual),list(axis)) and close(list(obj.Base),options['origin']) and close(obj.Angle,options['angle']) and obj.Solid,'revolution')
    elif kind in ('fillet','chamfer'):
        radius=options['radius'] if kind=='fillet' else options['distance']
        indices = options['edges']
        if isinstance(indices, dict):
            from .selections import native_edges, resolve
            indices = resolve(indices, native_edges(obj.Base.Shape), node['id'])
        require(close([list(edge) for edge in obj.Edges],[[index,radius,radius] for index in indices]),'edges')
    elif kind in ('readSTEP','importSTEP'):require(obj.SourceSHA256==sources[node['id']]['sha256'],'sourceDigest')
