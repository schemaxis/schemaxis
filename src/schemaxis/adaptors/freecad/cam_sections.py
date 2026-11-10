"""Continuous section model for vertical-plane/cylinder 2.5D stock and targets."""
import math
from schemaxis.errors import fail


def levels(shape):
    import Part
    for face in shape.Faces:
        surface=face.Surface
        if not isinstance(surface,(Part.Plane,Part.Cylinder)):fail('UNSUPPORTED_MACHINING_TARGET','This qualified milling family requires horizontal planes and vertical planar/cylindrical walls; curved-Z surfacing remains unqualified')
        z=abs(surface.Axis.z)
        if isinstance(surface,Part.Cylinder) and abs(z-1)>1e-8 or isinstance(surface,Part.Plane) and min(z,abs(z-1))>1e-8:fail('UNSUPPORTED_MACHINING_TARGET','Oblique walls and curved-Z targets need a qualified surfacing workflow')
    return [v.Point.z for v in shape.Vertexes]


def face(shape,z,empty):
    import FreeCAD as App,Part
    wires=shape.slice(App.Vector(0,0,1),z)
    if not wires:return empty.copy()
    if any(not wire.isClosed() for wire in wires):fail('MATERIAL_REPLAY_FAILED','Independent CAD cross-section is not closed')
    result=Part.makeFace(wires,'Part::FaceMakerBullseye')
    if not result.isValid():fail('MATERIAL_REPLAY_FAILED','Independent CAD cross-section is invalid')
    return result


def difference(a,b,height):
    """Return both planar differences and a numerical consistency margin."""
    residual=a.cut(b);gouge=b.cut(a);common=a.common(b).Area
    error=(abs(residual.Area-(a.Area-common))+abs(gouge.Area-(b.Area-common)))*height
    if not all(math.isfinite(value) for value in (a.Area,b.Area,common,residual.Area,gouge.Area,error)) or not residual.isValid() or not gouge.isValid():fail('MATERIAL_REPLAY_FAILED','Independent planar CAD/replay difference is invalid')
    return residual,gouge,error

