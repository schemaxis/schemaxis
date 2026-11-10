"""Finite geometric drilling selectors; submitted indices never establish intent."""
import math
from schemaxis.errors import fail


def select(shape,spec,tool):
    import Part
    radius=tool['diameter']/2;result=[]
    for centre in spec['centres']:
        found=[]
        for index,edge in enumerate(shape.Edges,1):
            curve=edge.Curve
            if (not isinstance(curve,Part.Circle) or not edge.isClosed()
                    or abs(curve.Radius-radius)>1e-7 or abs(abs(curve.Axis.z)-1)>1e-12
                    or math.dist([curve.Center.x,curve.Center.y],centre)>1e-7
                    or abs(curve.Center.z-spec['finish'])>1e-7
                    or abs(edge.Length-2*math.pi*radius)>1e-7):continue
            # An outer circular boss edge is not a hole. Require the adjacent
            # cylindrical material boundary to face inward, above this bottom.
            walls=[]
            for face in shape.Faces:
                surface=face.Surface
                if (not isinstance(surface,Part.Cylinder) or abs(surface.Radius-radius)>1e-7
                        or abs(abs(surface.Axis.z)-1)>1e-12
                        or not any(edge.isSame(e) for e in face.Edges)
                        or face.BoundBox.ZMax<=spec['finish']+1e-7):continue
                u0,u1,v0,v1=face.ParameterRange;u=(u0+u1)/2;v=(v0+v1)/2
                point=face.valueAt(u,v);normal=face.normalAt(u,v)
                if normal.x*(point.x-centre[0])+normal.y*(point.y-centre[1]) < -radius*(1-1e-7):walls.append(face)
            if len(walls)==1:found.append('Edge'+str(index))
        if len(found)!=1:
            fail('AMBIGUOUS_SELECTION' if found else 'EMPTY_SELECTION',
                 'Each intended drill centre, cutter radius and bottom must resolve one circular inward hole boundary',
                 spec['id'],centre=centre,bottom=spec['finish'],radius=radius,matches=len(found))
        result.extend(found)
    if len(result)!=len(set(result)) or len(result)!=len(spec['centres']):
        fail('VERIFICATION_FAILED','Drilling target cardinality or unique native selection differs',spec['id'])
    return result


def check_commands(commands,spec):
    """Upstream catches invalid generators and skips holes: check every target."""
    code='G'+str(spec['cycle']['code']);cycles=[c for c in commands if c.Name in ('G73','G81','G82','G83','G85')]
    if len(cycles)!=len(spec['centres']) or any(c.Name!=code for c in cycles):
        fail('EMPTY_TOOLPATH','Native drilling skipped or added a target, or emitted a different cycle',spec['id'])
    seen=[]
    for command in cycles:
        p=command.Parameters
        if not all(k in p for k in ('X','Y','Z','R','F')):
            fail('VERIFICATION_FAILED','Native drilling cycle has incomplete coordinates or feed',spec['id'])
        matches=[i for i,xy in enumerate(spec['centres']) if math.dist(xy,[p['X'],p['Y']])<1e-7]
        if len(matches)!=1 or matches[0] in seen:
            fail('VERIFICATION_FAILED','Native drilling emitted a duplicate or unintended location',spec['id'])
        seen.extend(matches)
        if abs(p['Z']-spec['finish'])>1e-7 or abs(p['R']-spec['cycle']['retract'])>1e-7:
            fail('VERIFICATION_FAILED','Native drilling depth or retract plane differs',spec['id'])
        for field,key in (('P','dwell'),('Q','peck')):
            expected=spec['cycle'][key]
            if (field in p)!=(expected!=0) or expected and abs(p[field]-expected)>1e-7:
                fail('VERIFICATION_FAILED','Native drilling peck/dwell state differs',spec['id'],word=field,expected=expected,actual=p.get(field))
