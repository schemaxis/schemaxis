"""Installed finite Draft Wire constructor and geometry-only source inspection."""
import math
import FreeCAD as App
import Part
from schemaxis.errors import fail
from .step_source import checkpoint


def inventory(shape,location):
    checkpoint()
    if shape.countElement('Vertex')>256 or shape.countElement('Edge')>256 or shape.countElement('Face')!=1:
        fail('INVALID_DRAFT_PROFILE','Draft profile topology exceeds its finite polygon',location)
    if (shape.ShapeType!='Face' or not shape.isValid() or len(shape.Wires)!=1
            or not shape.Wires[0].isClosed() or shape.Solids):
        fail('INVALID_DRAFT_PROFILE','Draft profile must be one valid planar face with one closed boundary',location)
    shape.check(True);vertices=shape.Vertexes;indexed={}
    for i,v in enumerate(vertices):indexed.setdefault(v.hashCode(),[]).append((i,v))
    def index(v):
        found=[i for i,w in indexed.get(v.hashCode(),[]) if v.isSame(w)]
        if len(found)!=1:fail('INVALID_DRAFT_PROFILE','Draft profile vertex identity is ambiguous',location)
        return found[0]
    edges=[]
    for edge in shape.Edges:
        if len(edge.Vertexes)!=2:fail('INVALID_DRAFT_PROFILE','Draft profile edge must have two endpoints',location)
        edges.append({'vertices':[index(v) for v in edge.Vertexes],'straight':isinstance(edge.Curve,Part.Line)})
    face=shape.Faces[0];n=face.normalAt(0,0)
    return {'vertices':[[v.Point.x,v.Point.y,v.Point.z] for v in vertices],
            'edges':edges,'normal':[n.x,n.y,n.z],'planar':isinstance(face.Surface,Part.Plane),
            'faces':1,'wires':1,'area':shape.Area,'perimeter':shape.Length}


def configure(obj,node):
    from draftobjects.wire import Wire
    from .step_import_native import matrix
    obj.addExtension('Part::AttachExtensionPython');Wire(obj)
    # Every native constructor option is finite application policy. Do not read
    # authored modules, Python state, preferences or arbitrary native paths.
    obj.Base=None;obj.Tool=None;obj.AttachmentSupport=[];obj.MapMode='Deactivated'
    obj.AttachmentOffset=App.Placement();obj.Closed=True;obj.MakeFace=True
    obj.FilletRadius=0;obj.ChamferSize=0;obj.Subdivisions=0
    obj.Points=[App.Vector(x,y,0) for x,y in node['options']['points']]
    f=node['profile']['frame'];obj.Placement=App.Placement(matrix(f['rotation'],f['translation']))


def observe(obj,node):
    from draftobjects.wire import Wire
    from .drafting import verify_inventory,placement
    from .mesh_geometry import verify_placement
    from .step_import_native import placement_values
    if (obj.TypeId!='Part::FeaturePython' or type(obj.Proxy) is not Wire
            or obj.Base is not None or obj.Tool is not None or obj.AttachmentSupport
            or obj.MapMode!='Deactivated' or not obj.AttachmentOffset.isIdentity()
            or obj.Closed is not True or obj.MakeFace is not True
            or obj.FilletRadius.Value!=0 or obj.ChamferSize.Value!=0 or obj.Subdivisions!=0):
        fail('VERIFICATION_FAILED','Draft profile installed proxy or finite native policy differs',node['id'])
    actual=placement_values(obj.Placement);verify_placement(actual,placement(node),node['id'])
    source=node['options']['points'];points=obj.Points
    if len(points)!=len(source) or any(not all(abs(a-b)<=64*max(math.ulp(a),math.ulp(b),math.ulp(1.0)) for a,b in zip((p.x,p.y,p.z),(*q,0))) for p,q in zip(points,source)):
        fail('VERIFICATION_FAILED','Native Draft points differ from their typed local polygon',node['id'])
    local=obj.Shape.copy();local.Placement=App.Placement()
    measured=inventory(local,node['id']);verify_inventory(measured,node)
    from .adaptor import close
    if not close(obj.Area.Value,node['profile']['area']) or not close(obj.Length.Value,node['profile']['perimeter']):
        fail('VERIFICATION_FAILED','Native Draft area or length differs from its typed polygon',node['id'])
    return {'placement':actual,'geometry':measured}


def inspect_saved_breps(directory):
    """Read host-extracted geometry only; never restore submitted native objects."""
    import json
    from pathlib import Path
    from schemaxis.artifacts import atomic_json,file_digest
    from .step_import_native import placement_values
    directory=Path(directory);result={}
    for record in json.loads((directory/'draft-profile-breps.json').read_text()):
        checkpoint();path=directory/record['file']
        if file_digest(path)!=record['sha256']:fail('INPUT_CHANGED','Saved Draft profile geometry changed before inspection',record['id'])
        shape=Part.Shape();shape.read(str(path));p=placement_values(shape.Placement);shape.Placement=App.Placement()
        result[record['id']]={'placement':p,'geometry':inventory(shape,record['id'])}
    atomic_json(directory/'draft-profile-inventories.json',result)
