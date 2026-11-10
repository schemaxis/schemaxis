"""Finite pointed-hole source geometry; no submitted native document restore."""
import math
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .adaptor import close
from .cam_mixed_budget import BooleanBudget,preflight,LIMITS


def topology(shape):
    """Bound native counts before materializing Python face/edge inventories."""
    faces=shape.countElement('Face');edges=shape.countElement('Edge')
    if faces>LIMITS['faces'] or edges>LIMITS['edges']:
        fail('RESOURCE_LIMIT','Pointed source geometry exceeds finite topology admission')
    remaining_timeout()
    return faces,edges


def boolean(left,right,kind,budget):
    a,_=topology(left);b,_=topology(right);budget.before(a,b)
    if kind=='fuse':result=left.fuse(right)
    elif kind=='common':result=left.common(right)
    else:raise ValueError('Unknown finite pointed geometry operation')
    remaining_timeout();faces,edges=topology(result);budget.after(faces,edges)
    if not result.isNull() and not result.isValid():
        fail('VERIFICATION_FAILED','Pointed source Boolean produced invalid geometry')
    return result


def cutting_piece(centre,spec,tool,stock,budget):
    """Complete physical cutting occupancy clipped to the ORIGINAL blank.

    The separate aboveBlank proof must establish that the cutting region reaches
    above this blank and that the complete noncutting bit/holder stays above it.
    This volume proves source-void containment, never ordered holder clearance.
    """
    import FreeCAD as A,Part
    r=tool['diameter']/2;h=tool['tipHeight'];apex=spec['finish'];junction=spec['junction']
    base=stock.BoundBox.ZMin;top=stock.BoundBox.ZMax;parts=[]
    lo=max(apex,base);hi=min(junction,top)
    if lo<hi:
        parts.append(Part.makeCone((lo-apex)*r/h,(hi-apex)*r/h,hi-lo,A.Vector(*centre,lo)))
    lo=max(junction,base)
    if lo<top:parts.append(Part.makeCylinder(r,top-lo,A.Vector(*centre,lo)))
    if not parts:fail('EMPTY_SELECTION','Pointed tool has no cutting occupancy inside the blank',spec['id'])
    for part in parts:
        faces,edges=topology(part);budget.after(faces,edges)
    piece=parts[0]
    for part in parts[1:]:piece=boolean(piece,part,'fuse',budget)
    piece=boolean(piece,stock,'common',budget)
    if piece.isNull() or not piece.isValid() or len(piece.Solids)!=1 or piece.Volume<=0:
        fail('VERIFICATION_FAILED','Pointed cutting occupancy is not one positive valid solid',spec['id'])
    return piece


def _inward(face,centre):
    u0,u1,v0,v1=face.ParameterRange;u=(u0+u1)/2;v=(v0+v1)/2
    point=face.valueAt(u,v);normal=face.normalAt(u,v)
    radial=[point.x-centre[0],point.y-centre[1]];radius=math.hypot(*radial)
    return radius>0 and (normal.x*radial[0]+normal.y*radial[1])/radius<0


def _cone_faces(shape,centre,spec,tool,interval,budget):
    """One complete rotational cone face; trimmed/split variants stay explicit.

    Exact native surface, axial interval, full angular domain, area and inward
    orientation are checked together. A scalar area witness is insufficient.
    """
    import Part
    # OCCT preserves signed cone parameterization: Part::Cone(R,0,-Z)
    # has negative axis AND semi-angle, while makeCone(0,R,+Z) has both
    # positive. Their product binds the same upward widening physical tip.
    # Apex, full axial/angular extent, area, inward normal, actual rim and
    # complete source-void containment below remain independently mandatory.
    result=[];apex=spec['finish'];slope=tool['diameter']/2/tool['tipHeight']
    lo,hi=interval;ra=(lo-apex)*slope;rb=(hi-apex)*slope
    expected_area=math.pi*(ra+rb)*math.hypot(hi-lo,rb-ra)
    for face in shape.Faces:
        budget.check();surface=face.Surface
        if not isinstance(surface,Part.Cone):continue
        tip=surface.Apex;direction=surface.Axis.z
        if (not close([tip.x,tip.y,tip.z],[*centre,apex]) or
                abs(abs(direction)-1)>1e-12 or
                abs(direction*surface.SemiAngle-math.radians(tool['tipAngle']/2))>1e-12):continue
        u0,u1,_,_=face.ParameterRange;b=face.BoundBox
        if (close([b.ZMin,b.ZMax],[lo,hi]) and abs(u1-u0-2*math.pi)<1e-12
                and close(face.Area,expected_area) and _inward(face,centre)):
            result.append(face)
    return result


def select(shape,spec,tool,stock_bounds,origin,*,budget=None):
    """Bind every intended hole to real boundary AND complete cut/source void.

    Source regime intervals are authored-source coordinates; all native geometry
    here is explicitly stock-top-centre coordinates. No receipt selects indices.
    A missing cone swallowed by a later cut is not inferred from an empty void.
    """
    import FreeCAD as A,Part
    from .cam_pointed import source_regime
    if tool['kind']!='drill':raise ValueError('Pointed source selector needs a compiled drill')
    bounds=stock_bounds;top=spec['start'];base=bounds[4]
    expected=source_regime(spec['finish']+origin[2],spec['junction']+origin[2],base+origin[2],top+origin[2])
    if spec['sourceRegime']!=expected:
        fail('VERIFICATION_FAILED','Pointed source interval frame differs from typed depth semantics',spec['id'])
    count=len(spec['centres']);faces,_=topology(shape)
    if not 1<=count<=256:fail('RESOURCE_LIMIT','Pointed source selection needs one to 256 targets')
    preflight(pieces=2*count,faces=12*count,edges=24*count,
              booleans=3*count,facePairs=faces*6*count+72*count)
    budget=budget if budget is not None else BooleanBudget()
    stock=Part.makeBox(bounds[1]-bounds[0],bounds[3]-bounds[2],-base,A.Vector(bounds[0],bounds[2],base))
    interval=expected['cone'];interval=None if interval is None else [z-origin[2] for z in interval]
    from .cam_rims_native import prospective,representative
    radius=tool['diameter']/2;groups=[];used=set()
    source_edges=shape.Edges;source_faces=shape.Faces
    for centre in spec['centres']:
        remaining_timeout()
        cones=_cone_faces(shape,centre,spec,tool,interval,budget) if interval else []
        if interval and len(cones)!=1:
            fail('UNSUPPORTED_SOURCE','Each pointed target needs one complete qualified inward cone; trimmed, split or swallowed cone variants need a qualified selector',spec['id'],matches=len(cones))
        z=base if interval is None else min(spec['junction'],top)
        rim=radius if interval is None else (z-spec['finish'])*radius/tool['tipHeight']
        candidates=[]
        for index,edge in enumerate(source_edges,1):
            budget.check();curve=edge.Curve
            if (not isinstance(curve,Part.Circle) or
                    abs(curve.Radius-rim)>1e-7 or abs(abs(curve.Axis.z)-1)>1e-12 or
                    math.dist([curve.Center.x,curve.Center.y],centre)>1e-7 or
                    abs(curve.Center.z-z)>1e-7):continue
            def belongs(face):
                for member in face.Edges:
                    budget.check()
                    if edge.isSame(member):return True
                return False
            if interval:
                adjacent=[face for face in cones if belongs(face)]
            else:
                adjacent=[]
                for face in source_faces:
                    budget.check()
                    if (isinstance(face.Surface,Part.Cylinder)
                            and abs(face.Surface.Radius-radius)<1e-7 and abs(abs(face.Surface.Axis.z)-1)<1e-12
                            and face.BoundBox.ZMax>base+1e-7 and _inward(face,centre) and belongs(face)):
                        adjacent.append(face)
            if len(adjacent)==1:candidates.append((index,edge))
        if not candidates:
            fail('EMPTY_SELECTION','Each pointed target needs an actual qualified junction, spot rim or through-base circle',spec['id'])
        indices={index for index,_ in candidates}
        if used&indices:fail('AMBIGUOUS_SELECTION','Pointed targets reuse an actual source rim',spec['id'])
        used.update(indices);groups.append((centre,candidates,rim))
    # The complete inventory for EVERY target precedes the first overlap kernel.
    prospective([group for _,group,_ in groups],budget,3*count)
    result=[]
    for centre,candidates,rim in groups:
        index=representative(candidates,rim,budget,
                             lambda a,b:boolean(a,b,'common',budget),spec['id'])
        piece=cutting_piece(centre,spec,tool,stock,budget)
        occupied=boolean(piece,shape,'common',budget)
        # Any actual enclosed material fails, however small. Faces/edges on the
        # coincident boundary have no material volume. No epsilon-volume clamp.
        if occupied.Solids:
            fail('UNSUPPORTED_SOURCE','The complete intended pointed cut is not contained in the finished source void',spec['id'],centre=centre)
        result.append('Edge'+str(index))
    if len(result)!=len(set(result)) or len(result)!=count:
        fail('VERIFICATION_FAILED','Pointed target cardinality or unique source selection differs',spec['id'])
    return result
