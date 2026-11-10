"""Trusted native construction and typed readback of paths and sweeps."""
import math
import FreeCAD as App
import Part
import Sketcher
from schemaxis.errors import fail
from . import sweep


def path(obj,node):
    for g in sweep.path_geometry(node['options']):
        value=Part.LineSegment(App.Vector(*g['start'],0),App.Vector(*g['end'],0)) if g['kind']=='line' else Part.ArcOfCircle(Part.Circle(App.Vector(*g['centre'],0),App.Vector(0,0,1),g['radius']),math.radians(g['startAngle']),math.radians(g['endAngle']))
        obj.addGeometry(value,g['construction'])
    for c in sweep.path_constraints(node['options']):
        args=[c['first']]
        if c['firstPos']:args.append(c['firstPos'])
        if c['second']!=-2000:
            args.append(c['second'])
            if c['secondPos']:args.append(c['secondPos'])
        if c['type'] in ('Distance','Angle'):args.append(c['value'])
        obj.renameConstraint(obj.addConstraint(Sketcher.Constraint(c['type'],*args)),c['name'])


def check_wire(obj,identity,*,section=False):
    shape=obj.Shape
    if shape.isNull() or not shape.isValid() or not shape.Wires or (not section and len(shape.Wires)!=1) or any(not wire.Edges or section and not wire.isClosed() for wire in shape.Wires):
        fail('INVALID_SWEEP_SECTION' if section else 'INVALID_SWEEP_PATH','Sweep sections need closed wires; each path needs one connected wire',identity)


def check_transition(obj,node):
    if node['options']['transition']!='transformed':return
    edges=obj.Shape.Wires[0].OrderedEdges
    pairs=list(zip(edges,edges[1:]))
    if len(edges)>1 and obj.Shape.Wires[0].isClosed():pairs.append((edges[-1],edges[0]))
    for first,second in pairs:
        a=[first.valueAt(first.FirstParameter),first.valueAt(first.LastParameter)]
        b=[second.valueAt(second.FirstParameter),second.valueAt(second.LastParameter)]
        shared=[(i,j) for i in range(2) for j in range(2) if (a[i]-b[j]).Length<1e-7]
        if len(shared)!=1:fail('INVALID_SWEEP_PATH','Sweep path junction must connect exactly two endpoints',node['id'])
        i,j=shared[0]
        before=first.tangentAt(first.FirstParameter if i==0 else first.LastParameter)*(1 if i==1 else -1)
        after=second.tangentAt(second.FirstParameter if j==0 else second.LastParameter)*(1 if j==0 else -1)
        if before.dot(after)<1-1e-7:
            fail('INVALID_SWEEP_TRANSITION','Transformed transition requires a tangent-continuous path; choose miter or rounded at a corner',node['id'])


def configure(obj,node,objects):
    i=node['inputs'];obj.Document.recompute()
    for identity in [i['profile']]+i.get('sections',[]):check_wire(objects[identity],identity,section=True)
    for identity in [i['spine']]+([i['auxiliary']] if 'auxiliary' in i else []):check_wire(objects[identity],identity)
    check_transition(objects[i['spine']],node)
    for key,typ in [('Profile','App::PropertyLinkSub'),('Spine','App::PropertyLinkSub'),('AuxiliarySpine','App::PropertyLinkSub'),('Sections','App::PropertyLinkSubList')]:
        if obj.getTypeIdOfProperty(key)!=typ:fail('UNSUPPORTED_RUNTIME','Native sweep link type differs',key)
    obj.Profile=(objects[i['profile']],[]);obj.Spine=(objects[i['spine']],[])
    obj.Sections=[(objects[k],['']) for k in i.get('sections',[])];obj.AuxiliarySpine=(objects[i['auxiliary']],[]) if 'auxiliary' in i else None
    # ProfileBased places a subsequent feature in its predecessor's frame,
    # and a first feature in its profile's frame. Authored directions are world
    # vectors; FreeCAD's Binormal property is local to that feature frame.
    pose=objects[i.get('base',i['profile'])].Placement
    for key,value in sweep.settings(node).items():
        prop,typ=sweep.PROPERTIES[key]
        if obj.getTypeIdOfProperty(prop)!=typ:fail('UNSUPPORTED_RUNTIME','Native sweep property type differs',prop)
        setattr(obj,prop,pose.Rotation.inverted().multVec(App.Vector(*value)) if typ=='App::PropertyVector' else value)


def observe(obj):
    result={}
    for key,(prop,typ) in sweep.PROPERTIES.items():
        if obj.getTypeIdOfProperty(prop)!=typ:fail('VERIFICATION_FAILED','Native sweep property type differs',prop)
        value=getattr(obj,prop);result[key]=list(obj.Placement.Rotation.multVec(value)) if typ=='App::PropertyVector' else bool(value) if typ=='App::PropertyBool' else str(value)
    return result
