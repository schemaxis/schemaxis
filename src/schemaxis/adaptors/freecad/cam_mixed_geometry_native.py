"""Bounded native physical regions and signed material ledger for mixed CAM."""
import math
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .adaptor import close
from .cam_mixed_budget import BooleanBudget,LIMITS
from .cam_pointed_source_native import topology
from .solid_topology_native import admit,TopologyRefused,TopologyLimit


class Geometry:
    def __init__(self):
        self.budget=BooleanBudget();self.balance_error=0.;self.identity_checks=0

    def _same(self,left,right):
        remaining_timeout();self.identity_checks+=1
        if self.identity_checks>LIMITS['facePairs']:fail('RESOURCE_LIMIT','Mixed topology comparison budget exhausted')
        return left.isSame(right)

    def mass(self,shape,*,boundary=False):
        """Actual positive Solid occurrences only; lower dimensions have no mass."""
        if shape.isNull():return {'volume':0.,'moment':[0.,0.,0.],'centreOfMass':None,'solids':0}
        topology(shape);stack=[shape];solids=[];nodes=0
        while stack:
            remaining_timeout();current=stack.pop();kind=current.ShapeType
            if kind in ('Compound','CompSolid'):
                raw=current.countElement('SubShape');nodes+=raw
                if raw>65536 or nodes>65536:fail('RESOURCE_LIMIT','Mixed material occurrence budget exhausted')
                children=current.childShapes()
                if len(children)!=raw:fail('MATERIAL_REPLAY_FAILED','Material compound repeats native occurrences')
                stack.extend(children);continue
            if kind!='Solid':
                if boundary and current.countElement('Solid')==0:continue
                fail('MATERIAL_REPLAY_FAILED','Expected closed material solids, not an open or lower-dimensional result')
            if len(solids)>=LIMITS['pieces']:fail('RESOURCE_LIMIT','Mixed material result exceeds512 solid occurrences')
            if any(self._same(current,other) for other in solids):fail('MATERIAL_REPLAY_FAILED','Mixed material repeats a solid occurrence')
            remaining=LIMITS['facePairs']-self.identity_checks
            if remaining<=0:fail('RESOURCE_LIMIT','Mixed topology comparison budget exhausted')
            try:record=admit(current,max_faces=LIMITS['faces'],max_edges=LIMITS['edges'],max_occurrences=65536,max_checks=remaining)
            except TopologyLimit as error:fail('RESOURCE_LIMIT',str(error))
            except TopologyRefused as error:fail('MATERIAL_REPLAY_FAILED',str(error))
            self.identity_checks+=record['facts']['identityComparisons'];solids.append(current)
        volumes=[];moments=[[],[],[]]
        for solid in solids:
            # STEP may return a generic Part.Shape wrapper whose ShapeType is
            # Solid but which has no CenterOfMass attribute. Complete raw one-
            # solid admission above already bound this typed map membership.
            # Retain the original occurrence's signed Volume (never abs()).
            remaining_timeout();v=solid.Volume;centre=solid.Solids[0].CenterOfMass
            if not math.isfinite(v) or v<=0 or not all(math.isfinite(c) for c in (centre.x,centre.y,centre.z)):
                fail('MATERIAL_REPLAY_FAILED','Material solid has nonpositive or nonfinite signed mass')
            volumes.append(v)
            for axis,c in enumerate((centre.x,centre.y,centre.z)):moments[axis].append(v*c)
        volume=math.fsum(volumes);moment=[math.fsum(values) for values in moments]
        return {'volume':volume,'moment':moment,'centreOfMass':[m/volume for m in moment] if volume else None,'solids':len(solids)}

    def boolean(self,left,right,kind):
        a,_=topology(left);b,_=topology(right);self.budget.before(a,b)
        if kind=='common':result=left.common(right)
        elif kind=='fuse':result=left.fuse(right)
        elif kind=='cut':result=left.cut(right)
        else:raise ValueError('Unknown finite mixed geometry operation')
        remaining_timeout();faces,edges=topology(result);self.budget.after(faces,edges)
        if not result.isNull() and not result.isValid():fail('MATERIAL_REPLAY_FAILED','Mixed Boolean produced invalid geometry')
        return result

    def union(self,left,right):
        if right.isNull():return left.copy()
        if left.isNull():return right.copy()
        a=self.mass(left)['volume'];b=self.mass(right)['volume']
        overlap=self.mass(self.boolean(left,right,'common'),boundary=True)['volume']
        result=self.boolean(left,right,'fuse');after=self.mass(result)['volume']
        self.balance_error+=abs(a+b-overlap-after)
        return result

    def difference(self,left,right):
        if left.isNull():return left.copy()
        if right.isNull():return left.copy()
        before=self.mass(left,boundary=True)['volume']
        overlap=self.mass(self.boolean(left,right,'common'),boundary=True)['volume']
        result=self.boolean(left,right,'cut');after=self.mass(result,boundary=True)['volume']
        self.balance_error+=abs(before-overlap-after)
        return result

    def prism(self,face,area,height):
        import FreeCAD as A
        remaining_timeout();topology(face)
        if not face.isValid() or not math.isfinite(face.Area) or face.Area<=0 or not close(face.Area,area) or height<=0:
            fail('MATERIAL_REPLAY_FAILED','Physical footprint differs from its analytic planar area')
        result=face.extrude(A.Vector(0,0,height));remaining_timeout();topology(result)
        volume=self.mass(result)['volume'];expected=area*height
        if not close(volume,expected):fail('MATERIAL_REPLAY_FAILED','Physical prism differs from analytic footprint times height')
        self.balance_error+=abs(volume-expected)
        return result


def disc(point,radius):
    import FreeCAD as A,Part
    return Part.Face(Part.Wire([Part.makeCircle(radius,A.Vector(*point))]))


def capsule(a,b,radius):
    """Exact line-capsule construction; no short-segment-to-disc substitution."""
    import FreeCAD as A,Part
    if a==b:return disc(a,radius),math.pi*radius*radius
    first,last=A.Vector(*a),A.Vector(*b);delta=last-first;length=delta.Length
    if not math.isfinite(length) or length<=0:fail('UNSUPPORTED_TOOLPATH','Unresolved physical line-sweep length')
    tangent=A.Vector(delta);tangent.normalize();normal=A.Vector(-tangent.y,tangent.x,0)*radius;tangent*=radius
    aa,bb,cc,dd=first+normal,last+normal,last-normal,first-normal
    face=Part.Face(Part.Wire([Part.makeLine(aa,bb),Part.Arc(bb,last+tangent,cc).toShape(),
                             Part.makeLine(cc,dd),Part.Arc(dd,first-tangent,aa).toShape()]))
    return face,math.pi*radius*radius+2*radius*length


def arc_faces(motion,z,radius,geometry):
    """True planar circular sweep regions with explicit endpoint-disc union."""
    import FreeCAD as A,Part
    a,b,c=motion['from'],motion['to'],motion['centre'];path_radius=math.dist(a[:2],c)
    first=math.atan2(a[1]-c[1],a[0]-c[0]);last=math.atan2(b[1]-c[1],b[0]-c[0]);sign=1 if motion['code']==3 else -1
    full=a[:2]==b[:2];span=2*math.pi if full else (sign*(last-first))%(2*math.pi)
    if span<=0:fail('UNSUPPORTED_TOOLPATH','Unresolved actual circular-sweep span')
    outer,inner=path_radius+radius,max(0,path_radius-radius)
    if full:
        face=disc([*c,z],outer)
        if inner:face=geometry.boolean(face,disc([*c,z],inner),'cut')
        return [(face,math.pi*(outer*outer-inner*inner))]
    finish=first+sign*span;middle=(first+finish)/2
    def point(r,angle):return A.Vector(c[0]+r*math.cos(angle),c[1]+r*math.sin(angle),z)
    edges=[Part.Arc(point(outer,first),point(outer,middle),point(outer,finish)).toShape(),
           Part.makeLine(point(outer,finish),point(inner,finish))]
    if inner:edges.append(Part.Arc(point(inner,finish),point(inner,middle),point(inner,first)).toShape())
    edges.append(Part.makeLine(point(inner,first),point(outer,first)))
    sector=Part.Face(Part.Wire(edges))
    return [(sector,span*(outer*outer-inner*inner)/2),
            (disc([*a[:2],z],radius),math.pi*radius*radius),
            (disc([*b[:2],z],radius),math.pi*radius*radius)]
