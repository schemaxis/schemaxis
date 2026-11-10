"""Finite SDK tool mapping and fresh physical-envelope measurements for plan/3.

Call on fresh trusted SDK constructions. Submitted proxy objects must not be
restored to discover their vocabulary or measure their claimed physical facts.
"""
import math
import json
import uuid

from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .adaptor import close
from .cam_pointed import ENDMILL_SHANK_OVERLAP


def template_record(tool):
    if tool['kind'] == 'flatEndmill':
        from .cam_tools import template_record as flat
        return flat(tool)
    if tool['kind'] != 'drill':
        fail('UNSUPPORTED_TOOL', 'Unexpected compiled physical tool kind')
    if 'shankDiameter' in tool:
        return {'version':1,'name':tool['controller'],'nr':tool['number'],
                'tool':{'version':2,'id':tool['nativeId'],'name':tool['nativeTool'],
                        'shape':'SCXReducedDrill','shape-type':'SCXReducedDrill',
                        'parameter':{'Diameter':str(tool['diameter'])+' mm',
                                     'Length':str(tool['length'])+' mm',
                                     'TipAngle':str(tool['tipAngle'])+' deg',
                                     'CuttingEdgeHeight':str(tool['cuttingReach'])+' mm',
                                     'ShankDiameter':str(tool['shankDiameter'])+' mm',
                                     'Flutes':tool['flutes']}}}
    params = {'Diameter': str(tool['diameter'])+' mm',
              'Length': str(tool['length'])+' mm',
              'TipAngle': str(tool['tipAngle'])+' deg', 'Flutes': tool['flutes'],
              'Material': 'HSS', 'SpindleDirection': 'Forward'}
    return {'version': 1, 'name': tool['controller'], 'nr': tool['number'],
            'tool': {'version': 2, 'id': tool['nativeId'], 'name': tool['nativeTool'],
                     'shape': 'drill', 'shape-type': 'Drill', 'parameter': params}}


def attach_cutting_metadata(native_tool, tool):
    """One finite quantity; the native Drill has no flute-length parameter."""
    name = 'SchemaxisCuttingReach' if tool['kind'] == 'drill' else 'SchemaxisNoncuttingStart'
    if name in native_tool.PropertiesList:
        fail('VERIFICATION_FAILED', 'Trusted SDK tool unexpectedly owns adaptor envelope metadata', name)
    value = tool['cuttingReach'] if tool['kind'] == 'drill' else tool['noncuttingStart']
    description = ('Declared axial cutting reach from the physical tip; not a native flute measurement'
                   if tool['kind'] == 'drill' else
                   'Derived first non-cutting material, including the fixed builtin wider-shank overlap')
    native_tool.addProperty('App::PropertyLength', name, 'Schemaxis tool envelope', description)
    setattr(native_tool, name, str(value)+' mm')
    if tool['kind'] != 'drill':
        native_tool.setEditorMode(name, 1)


def _bounded_shape(shape):
    remaining_timeout()
    if (not shape.isValid() or shape.countElement('Solid') != 1 or
            shape.countElement('Face') > 8 or shape.countElement('Edge') > 32 or
            not math.isfinite(shape.Volume) or shape.Volume <= 0):
        fail('VERIFICATION_FAILED', 'Trusted SDK tool lacks one bounded valid positive-volume solid')


def _near(actual, expected):
    return math.isfinite(actual) and abs(actual-expected) <= 1e-7


def _axial(surface):
    return abs(abs(surface.Axis.z)-1) <= 1e-12


def physical(native_tool, tool):
    """Independent ideal-profile checks plus actual conservative axial start."""
    import Part
    shape = native_tool.Shape
    _bounded_shape(shape)
    b = shape.BoundBox
    r, length = tool['diameter']/2, tool['length']
    parameters = [('Diameter', tool['diameter']), ('Length', length)]
    parameters += ([('TipAngle', tool['tipAngle'])] if tool['kind'] == 'drill' else
                   [('CuttingEdgeHeight', tool['cuttingLength']), ('ShankDiameter', tool['shankDiameter'])])
    if tool['kind']=='drill' and 'shankDiameter' in tool:
        parameters.extend([('CuttingEdgeHeight',tool['cuttingReach']),('ShankDiameter',tool['shankDiameter'])])
    if (any(not _near(getattr(native_tool, key).Value, value) for key, value in parameters) or
            type(native_tool.Flutes) is not int or native_tool.Flutes != tool['flutes']):
        fail('VERIFICATION_FAILED', 'Native tool dimensions or integral flute count differ from compiled intent')
    outer = r if tool['kind'] == 'drill' else max(r, tool['shankDiameter']/2)
    if not all(_near(a, e) for a, e in zip(
            [b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax],
            [-outer, outer, -outer, outer, 0, length])):
        fail('VERIFICATION_FAILED', 'Trusted tool origin, radius or physical length differs')
    faces = shape.Faces
    if any(not isinstance(f.Surface, (Part.Plane, Part.Cylinder, Part.Cone)) for f in faces):
        fail('VERIFICATION_FAILED', 'Trusted finite tool profile contains an unexpected surface')
    centre = shape.Solids[0].CenterOfMass
    if tool['kind'] == 'drill':
        h = tool['tipHeight']
        cones = [f for f in faces if isinstance(f.Surface, Part.Cone)]
        cylinders = [f for f in faces if isinstance(f.Surface, Part.Cylinder)]
        planes = [f for f in faces if isinstance(f.Surface, Part.Plane)]
        reduced='shankDiameter' in tool
        if len(cones) != 1 or len(cylinders) != (2 if reduced else 1) or len(planes) != (2 if reduced else 1):
            fail('VERIFICATION_FAILED', 'Native pointed tool surface inventory differs from its finite standard or reduced profile')
        cone=cones[0]
        cylinders=sorted(cylinders,key=lambda f:f.BoundBox.ZMin)
        planes=sorted(planes,key=lambda f:f.BoundBox.ZMin)
        cylinder,end=cylinders[0],planes[-1]
        cutting_end=tool['cuttingReach'] if reduced else length
        end_radius=tool['shankDiameter']/2 if reduced else r
        apex = cone.Surface.Apex
        if (not _axial(cone.Surface) or not _axial(cylinder.Surface) or
                not all(_near(v, 0) for v in (apex.x, apex.y, apex.z)) or
                not _near(abs(cone.Surface.SemiAngle), math.radians(tool['tipAngle']/2)) or
                not all(_near(a, e) for a, e in (
                    (cone.BoundBox.ZMin, 0), (cone.BoundBox.ZMax, h),
                    (cylinder.Surface.Radius, r), (cylinder.BoundBox.ZMin, h),
                    (cylinder.BoundBox.ZMax, cutting_end), (end.BoundBox.ZMin, length),
                    (end.BoundBox.ZMax, length), (end.Area, math.pi*end_radius*end_radius)))):
            fail('VERIFICATION_FAILED', 'Actual pointed cone/cylinder geometry differs from typed angle and tip origin')
        if reduced:
            shank,shoulder=cylinders[1],planes[0];c=tool['cuttingReach'];rs=end_radius
            if (not _axial(shank.Surface) or not all(_near(a,e) for a,e in (
                    (shank.Surface.Radius,rs),(shank.BoundBox.ZMin,c),(shank.BoundBox.ZMax,length),
                    (shoulder.BoundBox.ZMin,c),(shoulder.BoundBox.ZMax,c),
                    (shoulder.Area,math.pi*(r*r-rs*rs))))):
                fail('VERIFICATION_FAILED','Actual complete reduced shank or cutting shoulder differs')
            expected_volume=math.pi*(r*r*(c-2*h/3)+rs*rs*(length-c))
            moment=math.pi*(r*r*(c*c/2-h*h/4)+rs*rs*(length*length-c*c)/2)
        else:
            expected_volume = math.pi*r*r*(length-2*h/3)
            moment = math.pi*r*r*(length*length/2-h*h/4)
        start = tool['cuttingReach']
        metadata = native_tool.SchemaxisCuttingReach.Value
    elif tool['kind'] == 'flatEndmill':
        c, rs, d = tool['cuttingLength'], tool['shankDiameter']/2, ENDMILL_SHANK_OVERLAP
        sketches = [o for o in native_tool.BitBody.Group if o.TypeId == 'Sketcher::SketchObject']
        if len(sketches) != 1 or len(sketches[0].Constraints) != 21:
            fail('VERIFICATION_FAILED', 'Native endmill does not have its fixed constrained profile')
        constraint = sketches[0].Constraints[20]
        if (constraint.Type != 'DistanceY' or constraint.Value != d or
                (constraint.First, constraint.FirstPos, constraint.Second, constraint.SecondPos) != (5, 1, 2, 2)):
            fail('VERIFICATION_FAILED', 'Native endmill axial-overlap profile differs from the fixed template')
        bottom = [f for f in faces if isinstance(f.Surface, Part.Plane) and
                  _near(f.BoundBox.ZMin, 0) and _near(f.BoundBox.ZMax, 0) and _near(f.Area, math.pi*r*r)]
        shanks = [f for f in faces if isinstance(f.Surface, Part.Cylinder) and
                  _axial(f.Surface) and _near(f.Surface.Radius, rs) and
                  _near(f.BoundBox.ZMin, c-d) and _near(f.BoundBox.ZMax, length)]
        if len(bottom) != 1 or len(shanks) != 1:
            fail('VERIFICATION_FAILED', 'Native flat tool lacks its physical end or complete shank interval')
        # Signed disjoint radial regions of the exact constrained rotational
        # profile, including its 0.01 mm overlap; not a fitted mass correction.
        a, delta = c-d, r-rs
        transition = (2*r*r+2*rs*rs-r*rs)/3
        expected_volume = math.pi*(r*r*a+rs*rs*(length-c)+d*transition)
        moment = math.pi*(r*r*a*a/2+rs*rs*(length*length-c*c)/2+
                          d*a*(r*r-rs*delta-delta*delta/3)+
                          d*d*(r*r/2-2*rs*delta/3-delta*delta/4))
        start = min(tool['noncuttingStart'], shanks[0].BoundBox.ZMin) if rs > r else tool['noncuttingStart']
        metadata = native_tool.SchemaxisNoncuttingStart.Value
    else:
        fail('UNSUPPORTED_TOOL', 'Unexpected compiled physical tool kind')
    expected_start = tool['cuttingReach'] if tool['kind'] == 'drill' else tool['noncuttingStart']
    if (not _near(metadata, expected_start) or not close(shape.Volume, expected_volume) or
            not close([centre.x, centre.y, centre.z], [0, 0, moment/expected_volume])):
        fail('VERIFICATION_FAILED', 'Native tool mass, first moment or declared cutting envelope differs')
    remaining_timeout()
    return {'tool': tool['id'], 'noncuttingStart': start, 'volume': shape.Volume,
            'centreOfMass': [centre.x, centre.y, centre.z],
            'expectedVolume': expected_volume, 'expectedZMoment': moment,
            'cuttingReachIsDeclared': tool['kind'] == 'drill'}


def create_holder(document, native_tool, tool):
    """Finite declared holder geometry in the same local tip/+Z tool frame.

    The native Drill bit has no holder API. These ordinary native cylinders
    represent the separately declared physical envelope, not a machine model or
    a CAM generator's collision simulation. Whole canonical admission binds them.
    """
    import FreeCAD as A
    if 'holder' not in tool:return None
    identity='Holder'+str(tool['number']-1)
    if document.getObject(identity) is not None:
        fail('NATIVE_IDENTITY_COLLISION','Compiled holder object name is occupied',identity)
    holder=document.addObject('App::Part',identity)
    holder.Uid=holder_uid(tool)
    if holder.Name!=identity:fail('NATIVE_IDENTITY_COLLISION','Native holder identity changed',identity)
    holder.addProperty('App::PropertyLink','Tool','Schemaxis tool envelope','Holder geometry uses the linked tool local tip and +Z axis')
    holder.Tool=native_tool
    for index,step in enumerate(tool['holder']['steps']):
        remaining_timeout();name=identity+'Step'+str(index)
        if document.getObject(name) is not None:fail('NATIVE_IDENTITY_COLLISION','Compiled holder step name is occupied',name)
        part=document.addObject('Part::Cylinder',name)
        if part.Name!=name:fail('NATIVE_IDENTITY_COLLISION','Native holder step identity changed',name)
        part.Radius=str(step['radius'])+' mm';part.Height=str(step['end']-step['start'])+' mm';part.Angle=360
        part.Placement=A.Placement(A.Vector(0,0,step['start']),A.Rotation())
        holder.addObject(part)
    document.recompute();holder_readback(document,tool)
    return holder


def holder_uid(tool):
    marker=json.dumps({'tool':tool['nativeId'],'holder':tool['holder']},sort_keys=True,separators=(',',':'))
    return str(uuid.uuid5(uuid.NAMESPACE_URL,'schemaxis.freecad.cam.holder/1/'+marker))


def holder_readback(document, tool):
    """Bind every native envelope step, ownership, frame and physical geometry."""
    if 'holder' not in tool:return None
    identity='Holder'+str(tool['number']-1);holder=document.getObject(identity)
    names=[identity+'Step'+str(i) for i in range(len(tool['holder']['steps']))]
    if (holder is None or holder.TypeId!='App::Part' or str(holder.Uid)!=holder_uid(tool) or holder.Tool.Name!=tool['nativeTool'] or
            [o.Name for o in holder.Group]!=names or not close(list(holder.Placement.Matrix.A),[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])):
        fail('VERIFICATION_FAILED','Native declared holder ownership or local tool frame differs',identity)
    records=[]
    for step,name in zip(tool['holder']['steps'],names):
        part=document.getObject(name);shape=part.Shape;r=step['radius'];span=step['end']-step['start']
        _bounded_shape(shape);b=shape.BoundBox;centre=shape.Solids[0].CenterOfMass
        expected=[-r,r,-r,r,step['start'],step['end']]
        if (part.TypeId!='Part::Cylinder' or not _near(part.Radius.Value,r) or not _near(part.Height.Value,span)
                or not _near(part.Angle.Value,360) or not close([b.XMin,b.XMax,b.YMin,b.YMax,b.ZMin,b.ZMax],expected)
                or not close(shape.Volume,math.pi*r*r*span)
                or not close([centre.x,centre.y,centre.z],[0,0,step['start']+span/2])):
            fail('VERIFICATION_FAILED','Native declared holder step differs from its physical envelope',name)
        records.append({'name':name,'start':step['start'],'diameter':part.Radius.Value*2,'length':part.Height.Value,
                        'volume':shape.Volume,'centreOfMass':[centre.x,centre.y,centre.z]})
    return {'name':identity,'tool':holder.Tool.Name,'steps':records,'frame':'toolTipPositiveZ'}
