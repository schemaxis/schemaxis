"""Declared auxiliary conic lenses for an empirical float-endpoint model.

The auxiliary chain includes VIRTUAL ideal-law/token joins. They are neither
integrated nor one-form-proxied. Localisation and a winding-difference cap do
not bound those omitted terms, native evaluation, or three-dimensional rungs.
No original curve, parameter interval or measured numeric piece is changed.
"""
from dataclasses import dataclass
from fractions import Fraction
import math

from .gauss_green import ConicCurve,LineCurve,RationalCurve,Unresolved,finite


def _vector(row):
    if len(row)!=2:raise Unresolved('conic lens requires two-dimensional coefficients')
    return tuple(Fraction(finite(x)) for x in row)


def _matrix(curve):
    origin,cosine,sine=map(_vector,(curve.location,curve.cosine,curve.sine))
    determinant=cosine[0]*sine[1]-cosine[1]*sine[0]
    if not determinant:raise Unresolved('conic lens requires a nondegenerate ellipse')
    return origin,cosine,sine,determinant


def _unit(point,origin,cosine,sine,determinant):
    x,y=(a-b for a,b in zip(point,origin))
    return ((sine[1]*x-sine[0]*y)/determinant,
            (cosine[0]*y-cosine[1]*x)/determinant)


def _dot(a,b):return sum(x*y for x,y in zip(a,b))
def _cross(a,b):return a[0]*b[1]-a[1]*b[0]


def _up(value):
    """Outward binary64 diagnostic value; positive quantities never vanish."""
    value=Fraction(value)
    try:result=float(value)
    except OverflowError as error:raise Unresolved('conic lens diagnostic overflow')from error
    if not math.isfinite(result):raise Unresolved('conic lens diagnostic overflow')
    if Fraction(result)<value:result=math.nextafter(result,math.inf)
    return finite(result)


def _down(value):return -_up(-Fraction(value))


def _nearest(value):
    try:return finite(float(value))
    except OverflowError as error:raise Unresolved('conic lens sample coordinate overflow')from error


@dataclass(frozen=True)
class Lens:
    kind: str
    curve: object
    face: object
    occurrence: int
    corner: int
    role: str
    domain: tuple
    phase_window: tuple
    vertices: tuple
    area: Fraction
    cap: int
    data: tuple

    def record(self):
        return {'method':'declared-auxiliary-conic-lens/1','kind':self.kind,
                'occurrence':self.occurrence,'corner':self.corner,'role':self.role,
                'originalParameterRange':list(self.domain),
                'phaseWindowEnclosure':[str(x)for x in self.phase_window],
                'exactSupportVertices':[[str(x)for x in point]for point in self.vertices],
                'exactSupportArea':str(self.area),'windingDifferenceAbsBound':self.cap,
                'referenceWindingAssumed':True,'bound':False,
                'virtualJoins':{'integrated':False,'oneFormProxied':False},
                **dict(self.data)}

    def envelope(self):
        return [_down(min(p[0]for p in self.vertices)),_up(max(p[0]for p in self.vertices)),
                _down(min(p[1]for p in self.vertices)),_up(max(p[1]for p in self.vertices))]

    def samples(self):
        # The support is a parallelogram. Affine 3x3 grid, including every
        # vertex, edge midpoint and centre. Rounded points are preflighted.
        a,b,_,d=self.vertices
        return [tuple(_nearest(a[i]+u*(b[i]-a[i])+v*(d[i]-a[i]))for i in (0,1))
                for u in (Fraction(0),Fraction(1,2),Fraction(1))
                for v in (Fraction(0),Fraction(1,2),Fraction(1))]


def _rectangle(bounds):
    x0,x1,y0,y1=bounds
    if not x0<x1 or not y0<y1:raise Unresolved('conic lens support has no positive exact area')
    return ((x0,y0),(x1,y0),(x1,y1),(x0,y1)),(x1-x0)*(y1-y0)


def overperiod_residual(curve,index,corner_index,piece,occurrences,corners,budget):
    """One surplus turn, ONE occurrence in its native closed wire only."""
    from .conic_phase import cos_sin_enclosure,period_interval
    budget.check();origin,cosine,sine,determinant=_matrix(curve)
    face,_,edge,_,direction=occurrences[index]
    if (direction not in (-1,1) or piece.first!=index or piece.second!=index
            or piece.face is not face or getattr(edge,'Degenerated',None)is not False
            or not callable(getattr(edge,'isClosed',None)) or not edge.isClosed()
            or sum(c.first==index or c.second==index for c in corners)!=1):
        raise Unresolved('overperiod conic lens requires a single-occurrence closed native wire')
    start,end=Fraction(curve.start),Fraction(curve.end)
    period=period_interval(budget);width=end-start
    if not period[1]<width<2*period[0]:
        raise Unresolved('conic lens needs one strictly resolved surplus turn below two periods')
    if max(abs(start),abs(end))>2**20:raise Unresolved('conic phase reduction outside bounded range')
    first,last=tuple(curve.evaluate(curve.start)[0]),tuple(curve.evaluate(curve.end)[0])
    before,after=(last,first)if direction>0 else(first,last)
    if (tuple(piece.before)!=before or tuple(piece.after)!=after
            or piece.first_parameter!=(curve.end if direction>0 else curve.start)
            or piece.second_parameter!=(curve.start if direction>0 else curve.end)):
        raise Unresolved('conic lens tokens or endpoint roles differ from original occurrence')
    phi=(width-period[1],width-period[0])
    cos,sin=cos_sin_enclosure(start,budget)
    anchor=[];bounds=[]
    for o,c,s in zip(origin,cosine,sine):
        terms=[c*x+s*y for x in cos for y in sin]
        anchor.append((o+min(terms),o+max(terms)))
        radius=(abs(c)+abs(s))*phi[1]
        axis=len(bounds)
        bounds.append((min(anchor[-1][0]-radius,Fraction(first[axis]),Fraction(last[axis])),
                       max(anchor[-1][1]+radius,Fraction(first[axis]),Fraction(last[axis]))))
    vertices,area=_rectangle((*bounds[0],*bounds[1]))
    budget.check()
    return Lens('one-surplus-turn',curve,face,index,corner_index,'closed-wire',(curve.start,curve.end),
                (start+period[0],end),vertices,area,2,
                (('idealAnchorEnclosure',[[str(x)for x in pair]for pair in anchor]),
                 ('residualAngleEnclosure',[str(x)for x in phi]),
                 ('ledgerTokens',[list(before),list(after)]),
                 ('primitiveCountMaximum',4),('returnSegmentsMaximum',3),
                 ('theorem','one injective ellipse subarc plus at most three straight return segments; absolute winding difference at most two')))


def tangent_contact(first,last,curve,budget):
    """Exact strictly interior double root, or None; secants are not tangents."""
    budget.check();origin,cosine,sine,determinant=_matrix(curve)
    a,z=map(_vector,(first,last));u=_unit(a,origin,cosine,sine,determinant)
    v=_unit(z,origin,cosine,sine,determinant);d=tuple(y-x for x,y in zip(u,v))
    aa=_dot(d,d);bb=2*_dot(u,d);cc=_dot(u,u)-1
    if not aa or bb*bb-4*aa*cc!=0:return None
    parameter=-bb/(2*aa)
    if not 0<parameter<1:return None
    q=tuple(x+parameter*y for x,y in zip(u,d))
    if _dot(q,q)!=1:raise Unresolved('exact tangent contact has no rational unit preimage')
    budget.check()
    return {'parameter':parameter,'unit':q,'point':tuple(x+parameter*(y-x)for x,y in zip(a,z))}


def _phase_lift(q,endpoint,start,end,budget):
    from .conic_phase import atan2_enclosure,period_interval
    phase=atan2_enclosure(q[0],q[1],budget);period=period_interval(budget)
    estimate=round((endpoint-sum(phase)/2)/(sum(period)/2));candidates=[]
    for lift in (estimate-1,estimate,estimate+1):
        budget.check();offset=sorted(lift*x for x in period)
        low,high=phase[0]+offset[0],phase[1]+offset[1]
        if start<low and high<end:candidates.append((low,high))
        elif high<start or low>end:continue
        else:raise Unresolved('conic tangent phase lift meets an unresolved interval boundary')
    if len(candidates)!=1:raise Unresolved('conic tangent requires one strict original phase lift')
    return candidates[0],period


def terminal_tangent(curve,index,corner_index,piece,occurrences,budget):
    """A sharp K=1 auxiliary terminal lens; all other guards remain required."""
    from .conic_completion_separation import conic_period_relation
    if piece.first==piece.second:return None
    if conic_period_relation(curve,budget)!='shorter':return None
    face,_,_,_,direction=occurrences[index]
    if direction not in (-1,1)or piece.face is not face:
        raise Unresolved('conic tangent face or wire direction differs')
    if index==piece.first:role='incoming';endpoint=piece.first_parameter;token=piece.before
    elif index==piece.second:role='outgoing';endpoint=piece.second_parameter;token=piece.after
    else:raise Unresolved('tangent lens occurrence is not adjacent to its corner')
    expected=(curve.end if direction>0 else curve.start)if role=='incoming'else(curve.start if direction>0 else curve.end)
    if endpoint!=expected or tuple(curve.evaluate(endpoint)[0])!=tuple(token):
        raise Unresolved('tangent lens endpoint role or token differs')
    contact=tangent_contact(piece.before,piece.after,curve,budget)
    if contact is None:return None
    start,end,e=map(Fraction,(curve.start,curve.end,endpoint))
    if max(abs(start),abs(end))>2**20:raise Unresolved('conic phase reduction outside bounded range')
    phase,period=_phase_lift(contact['unit'],e,start,end,budget)
    sigma=1 if endpoint==curve.end else -1
    delta=(e-phase[1],e-phase[0])if sigma>0 else(phase[0]-e,phase[1]-e)
    if not 0<delta[0]<=delta[1]<period[0]/4:
        raise Unresolved('conic tangent lens has no strict short terminal tail')
    origin,cosine,sine,determinant=_matrix(curve);q=contact['unit'];perpendicular=(-q[1],q[0])
    t=_unit(_vector(token),origin,cosine,sine,determinant)
    xi,eta=_dot(q,t),_dot(perpendicular,t)
    if xi!=1 or sigma*eta<=0:
        raise Unresolved('conic tangent token is not on its strict terminal support side')
    eta_max=max(delta[1],abs(eta))
    # xi>=1-delta_hi²/2 bounds a circle phase by
    # 2*asin(delta_hi/2)<=pi*delta_hi/2<=pi*eta_max/2.
    # The xi bound is essential: eta_max itself may exceed one.
    if end-start-delta[0]>=period[0]-period[1]*eta_max/4:
        raise Unresolved('retained conic may re-enter terminal lens support')
    normal=(1-delta[1]*delta[1]/2,Fraction(1))
    tangent=(Fraction(0),eta_max)if sigma>0 else(-eta_max,Fraction(0))
    local,_=_rectangle((*normal,*tangent));vertices=[]
    for x,y in local:
        u,v=(q[i]*x+perpendicular[i]*y for i in (0,1))
        vertices.append(tuple(o+c*u+s*v for o,c,s in zip(origin,cosine,sine)))
    area=abs(determinant)*(normal[1]-normal[0])*(tangent[1]-tangent[0])
    if area<=0:raise Unresolved('conic tangent lens has no positive exact support area')
    return Lens('exact-terminal-tangent',curve,face,index,corner_index,role,(curve.start,curve.end),
                (min(e,phase[0]),max(e,phase[1])),tuple(vertices),area,1,
                (('exactContact',[str(x)for x in contact['point']]),
                 ('exactContactParameter',str(contact['parameter'])),
                 ('phaseEnclosure',[str(x)for x in phase]),
                 ('residualAngleEnclosure',[str(x)for x in delta]),
                 ('supportFrameUnit',[str(x)for x in q]),
                 ('supportFrameBounds',[[str(x)for x in pair]for pair in (normal,tangent)]),
                 ('ledgerToken',list(token)),('returnSegmentsMaximum',2),
                 ('theorem','one ellipse subarc shorter than half a period plus at most two straight return segments; absolute winding difference at most one')))


def _separate_polygons(first,second):
    """Exact strict SAT on finite rational convex hulls, without an epsilon."""
    axes=[(Fraction(1),Fraction(0)),(Fraction(0),Fraction(1))]
    for polygon in (first,second):
        axes.extend((b[1]-a[1],a[0]-b[0])for a,b in zip(polygon,polygon[1:]+polygon[:1]))
    for axis in axes:
        if axis==(0,0):continue
        a=[_dot(axis,p)for p in first];b=[_dot(axis,p)for p in second]
        if max(a)<min(b)or max(b)<min(a):return True
    return False


def _ellipse_disjoint(vertices,curve):
    origin,cosine,sine,determinant=_matrix(curve)
    points=tuple(_unit(p,origin,cosine,sine,determinant)for p in vertices)
    norms=[_dot(p,p)for p in points]
    if max(norms)<1:return True
    signs=[_cross(tuple(y-x for x,y in zip(a,z)),tuple(-x for x in a))
           for a,z in zip(points,points[1:]+points[:1])]
    if all(x>=0 for x in signs)or all(x<=0 for x in signs):return False
    minimum=min(norms)
    for a,z in zip(points,points[1:]+points[:1]):
        d=tuple(y-x for x,y in zip(a,z));square=_dot(d,d)
        if square:
            t=-_dot(a,d)/square
            if 0<t<1:minimum=min(minimum,_dot(tuple(x+t*y for x,y in zip(a,d)),tuple(x+t*y for x,y in zip(a,d))))
    return minimum>1


def separated_support_curve(lens,curve,budget):
    """Finite coefficient isolation, not an enclosure of native evaluation."""
    from .mass_boundary_admission import _hull,_split
    budget.check()
    if isinstance(curve,LineCurve):
        first=tuple(Fraction(v)for v in curve.first);slope=tuple(Fraction(v)for v in curve.slope)
        ideal=tuple(tuple(x+(Fraction(t)-Fraction(curve.start))*d for x,d in zip(first,slope))
                    for t in (curve.start,curve.end))
        points=tuple(_hull([*ideal,*[_vector(curve.evaluate(t)[0])for t in (curve.start,curve.end)]]))
        if not _separate_polygons(lens.vertices,points):raise Unresolved('conic lens support meets another original line')
        return 1
    if isinstance(curve,ConicCurve)and _ellipse_disjoint(lens.vertices,curve):return 1
    if isinstance(curve,RationalCurve):
        # Original finite homogeneous controls first: floating knot insertion
        # or midpoint subdivision can collapse a genuine intersecting lobe.
        # The whole positive-weight B-spline hull is always sufficient when
        # strictly separated. Subdivide only an original single Bezier span,
        # using Fraction throughout. Ambiguous multi-span extraction refuses.
        poles=tuple(tuple(Fraction(v)for v in p)for p in curve.poles)
        if any(p[2]<=0 for p in poles):raise Unresolved('conic lens isolation requires positive rational weights')
        points=tuple(_hull([(p[0]/p[2],p[1]/p[2])for p in poles]))
        if _separate_polygons(lens.vertices,points):return 1
        if (len(poles)!=curve.degree+1 or len(set(curve.knots))!=2
                or curve.knots!=[curve.start]*(curve.degree+1)+[curve.end]*(curve.degree+1)):
            raise Unresolved('conic lens isolation needs exact unresolved multi-span rational extraction')
        pending=[('rational',poles,0)]
    elif isinstance(curve,ConicCurve):pending=[('conic',(Fraction(curve.start),Fraction(curve.end)),0)]
    else:raise Unresolved('conic lens isolation has an unreviewed original curve')
    visited=0
    while pending:
        budget.check();kind,data,depth=pending.pop();visited+=1
        if visited>32768:raise Unresolved('conic lens isolation allocation refusal')
        if kind=='rational':
            if any(p[2]<=0 for p in data):raise Unresolved('conic lens isolation requires positive rational weights')
            points=tuple(_hull([(Fraction(p[0])/Fraction(p[2]),Fraction(p[1])/Fraction(p[2]))for p in data]))
        else:
            from .conic_phase import cos_sin_enclosure
            a,z=data;mid=(a+z)/2;radius=(z-a)/2;c,s=cos_sin_enclosure(mid,budget)
            origin,cosine,sine,_=_matrix(curve);bounds=[]
            for o,cc,ss in zip(origin,cosine,sine):
                values=[o+cc*x+ss*y for x in c for y in s];pad=(abs(cc)+abs(ss))*radius
                bounds.append((min(values)-pad,max(values)+pad))
            points,_=_rectangle((*bounds[0],*bounds[1]))
        if _separate_polygons(lens.vertices,points):continue
        if depth>=24:raise Unresolved('conic lens support meets unresolved original curve hull')
        if kind=='rational':one,two=_split(data);pending.extend(((kind,one,depth+1),(kind,two,depth+1)))
        else:a,z=data;mid=(a+z)/2;pending.extend(((kind,(a,mid),depth+1),(kind,(mid,z),depth+1)))
    return visited


def classify_lenses(state,budget):
    """Classify ALL conics, including zero-connector surplus-turn occurrences."""
    from .conic_completion_separation import conic_period_relation
    occurrences,corners=state['occurrences'],state['corners'];lenses=[];surplus=set()
    for index,(_,_,_,curve,_)in enumerate(occurrences):
        if not isinstance(curve,ConicCurve):continue
        relation=conic_period_relation(curve,budget)
        if relation is None:raise Unresolved('stored conic period relation is unresolved')
        if relation=='longer':
            adjacent=[(ci,c)for ci,c in enumerate(corners)if c.first==index or c.second==index]
            if len(adjacent)!=1:raise Unresolved('overperiod conic lens requires a single-occurrence closed native wire')
            ci,piece=adjacent[0];lenses.append(overperiod_residual(curve,index,ci,piece,occurrences,corners,budget));surplus.add(index)
    # Exact tangent candidates are resolved before any existing float endpoint
    # cone fallback, independently of whether that fallback would appear to pass.
    for ci,piece in enumerate(corners):
        if piece.before==piece.after:continue
        for index in sorted({piece.first,piece.second}):
            curve=occurrences[index][3]
            if isinstance(curve,ConicCurve)and index not in surplus:
                candidate=terminal_tangent(curve,index,ci,piece,occurrences,budget)
                if candidate is not None:lenses.append(candidate)
    return tuple(lenses),validate_lens_isolation(lenses,state,budget)


def validate_lens_isolation(lenses,state,budget):
    keys=set();tests=0
    for lens in lenses:
        budget.check();key=(id(lens.face),lens.occurrence,lens.corner,lens.role)
        if key in keys:raise Unresolved('duplicate declared conic lens identity')
        keys.add(key)
        for other in lenses:
            if other is lens:continue
            if other.occurrence==lens.occurrence and not (lens.phase_window[1]<other.phase_window[0]or other.phase_window[1]<lens.phase_window[0]):
                raise Unresolved('declared conic lens terminal windows overlap')
        for index,(face,_,_,curve,_)in enumerate(state['occurrences']):
            if face is lens.face and index!=lens.occurrence:tests+=separated_support_curve(lens,curve,budget)
        for index,piece in enumerate(state['corners']):
            if piece.face is not lens.face or index==lens.corner or piece.before==piece.after:continue
            if not _separate_polygons(lens.vertices,(_vector(piece.before),_vector(piece.after))):
                raise Unresolved('declared conic lens support meets another connector')
            tests+=1
    return tests


def density_proxy(lens,field,envelope,budget):
    """Sampled TWO-dimensional density; omitted virtual joins stay unmodelled."""
    budget.check()
    if lens.area<=0 or lens.cap not in (1,2):raise Unresolved('conic lens diagnostic needs a positive support and declared multiplicity')
    points=lens.samples()
    if len(envelope)!=4 or any(not(envelope[0]<=u<=envelope[1]and envelope[2]<=v<=envelope[3])for u,v in points):
        raise Unresolved('conic lens samples lie outside their preflight envelope')
    maxima=[0.]*5;values=[]
    for point in points:
        budget.check();budget.tick();row=[finite(x)for x in field(*point)];budget.check()
        if len(row)!=5:raise Unresolved('conic lens density needs five components')
        values.append(row);maxima=[max(x,abs(y))for x,y in zip(maxima,row)]
    totals=[_up(lens.cap*lens.area*Fraction(x))for x in maxima]
    return {'method':'sampled-conic-lens-density-grid3/1','bound':False,
            'descriptor':lens.record(),'samples':[{'uv':list(p),'density':v}for p,v in zip(points,values)],
            'sampledAbsoluteMaxima':maxima,'totals':totals,
            'scope':'auxiliary two-dimensional winding difference only; virtual endpoint joins and 3D rungs remain unintegrated and unmodelled'}
