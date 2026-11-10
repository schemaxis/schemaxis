"""Native lowering of the reviewed drilling layout and Hole contracts."""
import math
import FreeCAD as App
import Part
import Sketcher
from schemaxis.errors import fail
from . import drilling as policy


def profile(obj,node):
    kind,o=node['filter'],node['options']
    for g in policy.geometry(kind,o):
        value=Part.LineSegment(App.Vector(*g['start'],0),App.Vector(*g['end'],0)) if g['kind']=='line' else Part.Circle(App.Vector(*g['centre'],0),App.Vector(0,0,1),g['radius'])
        obj.addGeometry(value,g['construction'])
    for c in policy.constraints(kind,o):
        args=[c['first']]
        if c['firstPos']:args.append(c['firstPos'])
        if c['second']!=-2000:
            args.append(c['second'])
            if c['secondPos']:args.append(c['secondPos'])
        if c['type'] in ('Distance','DistanceX','DistanceY','Radius','Angle'):args.append(c['value'])
        index=obj.addConstraint(Sketcher.Constraint(c['type'],*args));obj.renameConstraint(index,c['name'])
    for target,expression in policy.expressions(kind,o).items():obj.setExpression(target.lstrip('.'),expression.replace('.Constraints','Constraints'))


def configure(obj,node,objects):
    obj.Profile=objects[node['inputs']['profile']]
    settings=policy.hole_settings(node['options'])
    for key,(prop,typeid) in policy.HOLE_PROPERTIES.items():
        if key not in settings:continue
        if obj.getTypeIdOfProperty(prop)!=typeid:fail('UNSUPPORTED_RUNTIME','Native Hole property type differs from the reviewed contract',prop)
        # Countersink depth is derived; setting it would overwrite the angle.
        if key=='recessDepth' and node['options']['recess']=='countersink':continue
        setattr(obj,prop,settings[key])


def observe(obj,node):
    result={}
    for key in policy.hole_settings(node['options']):
        prop,typeid=policy.HOLE_PROPERTIES[key]
        if obj.getTypeIdOfProperty(prop)!=typeid:fail('VERIFICATION_FAILED','Native Hole property type differs',prop)
        value=getattr(obj,prop)
        result[key]=float(value.Value) if typeid in ('App::PropertyLength','App::PropertyAngle') else bool(value) if typeid=='App::PropertyBool' else str(value)
    return result


def check_removal(obj,base):
    """Every declared drill centre must reach material, not silently disappear."""
    if obj.Shape.isNull() or not 0<obj.Shape.Volume<base.Shape.Volume:
        fail('INVALID_GEOMETRY','Hole feature must remove material and retain a positive solid',obj.Label)
    sketch=obj.Profile[0];direction=sketch.Placement.Rotation.multVec(App.Vector(0,0,1 if obj.Reversed else -1));radius=float(obj.Diameter.Value)/2
    finite=obj.DepthType=='Dimension';depth=float(obj.Depth.Value);tip=radius/math.tan(math.radians(float(obj.DrillPointAngle.Value)/2)) if obj.DrillPoint=='Angled' else 0
    cylinder=depth-tip if finite and obj.DrillForDepth else depth
    for index,g in enumerate(sketch.Geometry):
        if sketch.getConstruction(index):continue
        if not isinstance(g,Part.Circle):fail('INVALID_HOLE_PROFILE','Native drilling profile contains a non-circular location',obj.Label)
        start=sketch.Placement.multVec(g.Center)
        length=cylinder if finite else max(1,base.Shape.BoundBox.DiagonalLength)+start.distanceToPoint(base.Shape.BoundBox.Center)
        cutter=Part.makeCylinder(radius,length,start,direction)
        if finite and tip:cutter=cutter.fuse(Part.makeCone(radius,0,tip,start+direction*length,direction))
        if cutter.common(base.Shape).Volume<=0:fail('INVALID_GEOMETRY','A declared drill centre does not reach material',obj.Label,centre=list(start))
