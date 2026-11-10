"""Native faceted solid construction and geometry-only BREP inventory.

This module never restores submitted native documents. Callers admit STL bytes
and generate dense valid facet indices before entering makeShapeFromMesh.
"""
import math
import FreeCAD as App
import Part
from schemaxis.errors import fail
from .mesh_source import MAX_FACETS
from .step_source import checkpoint


def inventory(shape, location):
    checkpoint()
    if (shape.countElement('Face')>MAX_FACETS or shape.countElement('Vertex')>3*MAX_FACETS
            or shape.countElement('Edge')>3*MAX_FACETS):
        fail('INVALID_MESH','Native mesh conversion exceeds its bounded topology inventory',location)
    volume=shape.Volume
    if not shape.isClosed() or not shape.isValid() or len(shape.Solids)!=1 or not math.isfinite(volume) or volume<=0:
        fail('INVALID_MESH','STL must enclose exactly one valid solid, including consistently oriented cavity shells',location)
    try:shape.check(True)
    except Exception as error:fail('INVALID_MESH','Native solid self-intersection/BOP check refused the STL',location,detail=str(error)[:300])
    vertices=shape.Vertexes;faces=shape.Faces
    if len(faces)<4:fail('INVALID_MESH','Native mesh solid has too few facets',location)
    # Native isSame supplies topological identity; coordinates are measured
    # separately and matched to STL by the installed host checker.
    indexed={vertex.hashCode():[] for vertex in vertices}
    for index,vertex in enumerate(vertices):indexed[vertex.hashCode()].append((index,vertex))
    def vertex_index(vertex):
        candidates=[index for index,candidate in indexed.get(vertex.hashCode(),[]) if vertex.isSame(candidate)]
        if len(candidates)!=1:fail('VERIFICATION_FAILED','Native mesh facet has an ambiguous vertex identity',location)
        return candidates[0]
    measured=[]
    for index,face in enumerate(faces):
        if index%256==0:checkpoint()
        if len(face.Vertexes)!=3 or len(face.Edges)!=3 or len(face.Wires)!=1:
            fail('INVALID_MESH','Conversion must preserve every unrefined STL triangle',location)
        normal=face.normalAt(0,0)
        measured.append({'vertices':[vertex_index(v) for v in face.Vertexes],
            'normal':[normal.x,normal.y,normal.z],'planar':isinstance(face.Surface,Part.Plane),
            'straight':all(isinstance(edge.Curve,Part.Line) for edge in face.Edges),'edges':3,'wires':1})
    checkpoint()
    return {'vertices':[[v.Point.x,v.Point.y,v.Point.z] for v in vertices],'faces':measured}


def construct(points, faces, location):
    shape=Part.Shape()
    checkpoint()
    try:
        shape.makeShapeFromMesh(([App.Vector(*p) for p in points],faces),1e-7,True)
        solid=Part.Solid(shape)
    except Exception as error:fail('INVALID_MESH','FreeCAD could not sew the admitted STL triangles into a solid',location,detail=str(error)[:300])
    measured=inventory(solid,location)
    from .mesh_geometry import verify_inventory
    verify_inventory(measured,points,faces,location)
    return solid,measured


def configure(obj, node, sources):
    from .mesh_import import geometry
    from .step_source import read_bounded
    from .step_import_native import matrix
    record=sources[node['id']];data=read_bounded(record['retained'],node['id'])
    facts,points,faces=geometry(data,node['options'],node['id'])
    if facts['sha256']!=record['sha256'] or any(facts[k]!=node['source'][k] for k in facts):
        fail('INPUT_CHANGED','Retained STL differs from the planned mesh',node['id'])
    shape,_=construct(points,faces,node['id']);obj.Shape=shape
    obj.Placement=App.Placement(matrix(node['frame']['worldFromFile'],node['frame']['translation']))
    obj.addProperty('App::PropertyString','SourceSHA256','Schemaxis');obj.SourceSHA256=record['sha256']


def observe(doc, node, index, sources):
    from .mesh_import import geometry
    from .mesh_geometry import verify_inventory,verify_placement
    from .step_import_native import facts,placement_values,expected_placement
    from .step_source import read_bounded
    obj=doc.getObject('N'+str(index));record=sources[node['id']]
    if obj is None or obj.TypeId!='Part::Feature' or getattr(obj,'SourceSHA256',None)!=record['sha256']:
        fail('VERIFICATION_FAILED','Mesh source object or captured digest differs',node['id'])
    actual=placement_values(obj.Placement);verify_placement(actual,expected_placement(node),node['id'])
    source,points,faces=geometry(read_bounded(record['retained'],node['id']),node['options'],node['id'])
    if any(source[k]!=node['source'][k] for k in source):fail('VERIFICATION_FAILED','Mesh source facts differ',node['id'])
    local=obj.Shape.copy();local.Placement=App.Placement()
    verify_inventory(inventory(local,node['id']),points,faces,node['id'])
    output=obj;refine=None
    if node['options']['refine']:
        output=doc.getObject('N'+str(index)+'Refined')
        if output is None or output.TypeId!='Part::Refine' or output.Source!=obj or not output.Placement.isIdentity():
            fail('VERIFICATION_FAILED','Mesh refine output must retain its source link and identity Placement',node['id'])
        equivalent_material(obj.Shape,output.Shape,node['id'])
        refine={'object':output.Name,'source':obj.Name,'placement':placement_values(output.Placement),'output':facts(output.Shape)}
    return {'sourceObject':obj.Name,'sourceSHA256':obj.SourceSHA256,'placement':actual,'fileFrame':facts(local),
            'source':facts(obj.Shape),'refine':refine,'output':facts(output.Shape),'outputObject':output.Name}


def equivalent_material(source, refined, location):
    """Refine may merge facets, while the exact material set stays unchanged."""
    checkpoint()
    if (not refined.isValid() or not refined.isClosed() or len(refined.Solids)!=1
            or not math.isfinite(refined.Volume) or refined.Volume<=0):
        fail('PREPARATION_CHANGED_GEOMETRY','Mesh refinement did not preserve one valid closed solid',location)
    for a,b in ((source,refined),(refined,source)):
        checkpoint()
        remainder=a.cut(b)
        if remainder.countElement('Vertex') or remainder.countElement('Face'):
            fail('PREPARATION_CHANGED_GEOMETRY','Mesh refinement changed the material set',location)
    checkpoint()


def inspect_saved_breps(directory):
    """Read bounded geometry-only files selected and extracted by the host."""
    from pathlib import Path
    from schemaxis.artifacts import atomic_json,file_digest
    from .step_import_native import placement_values
    directory=Path(directory)
    import json
    requests=json.loads((directory/'mesh-breps.json').read_text());result={}
    for record in requests:
        checkpoint();path=directory/record['file']
        if file_digest(path)!=record['sha256']:fail('INPUT_CHANGED','Saved mesh geometry changed before measurement',record['id'])
        shape=Part.Shape();shape.read(str(path));placement=placement_values(shape.Placement)
        shape.Placement=App.Placement()
        result[record['id']]={'placement':placement,'geometry':inventory(shape,record['id'])}
    atomic_json(directory/'mesh-inventories.json',result)
