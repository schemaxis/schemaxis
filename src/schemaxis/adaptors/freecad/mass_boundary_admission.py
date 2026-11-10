"""Finite chain incidence, conservative UV separation and coarse winding checks.

UV separation uses finite floating coefficient hulls and refuses ambiguous
contacts; it is not an interval
arithmetic certificate. The mesh discriminator checks only gross winding.
"""
import collections
import copy
import math
from fractions import Fraction


def _hull(points):
    points = sorted(set(map(tuple, points)))
    def turn(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    halves = []
    for sequence in (points, points[::-1]):
        half = []
        for point in sequence:
            while len(half) > 1 and turn(half[-2], half[-1], point) <= 0:
                half.pop()
            half.append(point)
        halves.append(half)
    return halves[0][:-1]+halves[1][:-1] if len(points) > 1 else points


def _separate(first, last, hull):
    """Strict separating axes, padded against floating dot-product uncertainty."""
    axes = [(1., 0.), (0., 1.), (last[1]-first[1], first[0]-last[0])]
    axes += [(b[1]-a[1], a[0]-b[0]) for a, b in zip(hull, hull[1:]+hull[:1])]
    for x, y in axes:
        if x == y == 0:
            continue
        one = [x*p[0]+y*p[1] for p in (first, last)]
        two = [x*p[0]+y*p[1] for p in hull]
        scale = max(1., *(abs(x*p[0])+abs(y*p[1]) for p in [first, last, *hull]))
        padding = 64*math.ulp(scale)
        if max(one)+padding < min(two) or max(two)+padding < min(one):
            return True
    return False


def _split(poles):
    levels = [poles]
    while len(levels[-1]) > 1:
        levels.append([tuple((a+b)/2 for a, b in zip(p, q))
                       for p, q in zip(levels[-1], levels[-1][1:])])
    return [row[0] for row in levels], [row[-1] for row in levels[::-1]]


def separated_from_curve(first, last, curve, budget):
    from schemaxis.adaptors.freecad.gauss_green import (
        RationalCurve, LineCurve, ConicCurve, coordinate_bounds, Unresolved)
    if isinstance(curve, RationalCurve):
        pending = [(poles, 0) for _, _, poles in curve.bezier_spans(budget)]
        visited = 0
        while pending:
            budget.check()
            poles, depth = pending.pop()
            visited += 1
            if visited > 32768 or any(p[2] <= 0 for p in poles):
                raise Unresolved('connector separation allocation/positive-weight refusal')
            hull = _hull([(p[0]/p[2], p[1]/p[2]) for p in poles])
            if _separate(first, last, hull):
                continue
            if depth >= 24:
                raise Unresolved('connector meets unresolved non-adjacent rational hull')
            a, b = _split(poles)
            pending.extend(((a, depth+1), (b, depth+1)))
        return visited
    if isinstance(curve, LineCurve):
        if not _separate(first, last, [curve.evaluate(t)[0] for t in (curve.start, curve.end)]):
            raise Unresolved('connector meets non-adjacent line')
        return 1
    if isinstance(curve, ConicCurve):
        pending = [(curve.start, curve.end, 0)]
        visited = 0
        while pending:
            budget.check()
            a, b, depth = pending.pop()
            visited += 1
            if visited > 32768:
                raise Unresolved('connector conic separation allocation refusal')
            segment = copy.copy(curve)
            segment.start, segment.end = a, b
            lo, hi, bottom, top = coordinate_bounds(segment)
            if _separate(first, last, [(lo, bottom), (hi, bottom), (hi, top), (lo, top)]):
                continue
            middle = a+(b-a)/2
            if depth >= 24 or middle in (a, b):
                raise Unresolved('connector meets unresolved non-adjacent conic hull')
            pending.extend(((a, middle, depth+1), (middle, b, depth+1)))
        return visited
    raise Unresolved('connector separation unreviewed curve')


def _endpoint_cone(first, last, poles, at_end):
    """Strict one-sided separation except at one declared Bernstein endpoint.

    Exact rational arithmetic tests the finite binary64 coefficient data, not
    a certified enclosure of native evaluation. No endpoint is moved/snapped.
    Positive weights make a nonzero nonpositive Bernstein projection strictly
    negative throughout the open parameter span.
    """
    endpoint = poles[-1] if at_end else poles[0]
    x, y, w = map(Fraction, endpoint)
    anchor = (x/w, y/w)
    # The caller orients the connector so its first point is the common end.
    if anchor != tuple(map(Fraction, first)):
        raise ValueError('adjacent rational endpoint differs from original coefficient hull')
    other = tuple(Fraction(v)-a for v, a in zip(last, anchor))
    rays = []
    for px, py, pw in poles:
        px, py, pw = map(Fraction, (px, py, pw))
        if pw <= 0:raise ValueError('adjacent endpoint requires positive weights')
        rays.append((px/pw-anchor[0], py/pw-anchor[1]))
    candidates = [other]
    for ray in rays:
        if not max(map(abs,ray)):continue
        left=[float(v/max(map(abs,other)))for v in other]
        right=[float(v/max(map(abs,ray)))for v in ray]
        ln,rn=math.hypot(*left),math.hypot(*right)
        candidates.append(tuple(Fraction(a/ln-b/rn)for a,b in zip(left,right)))
    for ray in rays:
        square=sum(x*x for x in ray)
        if not square:continue
        normal=(ray[1],-ray[0])
        projection=sum(x*y for x,y in zip(normal,other))
        if projection<0:normal=tuple(-x for x in normal);projection=-projection
        if projection:
            # Exact perturbation makes the curve projection negative without
            # losing a tiny but nonzero connector-side angular separation.
            product=abs(sum(x*y for x,y in zip(ray,other)))
            epsilon=projection/(2*(product+square+1))
            candidates.append(tuple(n-epsilon*r for n,r in zip(normal,ray)))
    for a, b in [other, *rays]:
        candidates.extend(((b, -a), (-b, a)))
    for n in candidates:
        if sum(a*b for a,b in zip(n,other)) <= 0:continue
        values = [sum(a*b for a,b in zip(n,r)) for r in rays]
        if max(values) <= 0 and min(values) < 0:return True
    return False


def _conic_endpoint_cone(first, last, curve, start, end, at_end):
    """Analytic projection-derivative extrema, with strict floating slack."""
    from .gauss_green import finite
    parameter = end if at_end else start
    point, tangent = curve.evaluate(parameter)
    if tuple(point) != tuple(first):
        raise ValueError('adjacent conic endpoint differs from declared endpoint')
    delta = [b-a for a,b in zip(first,last)]
    size, speed = math.hypot(*delta), math.hypot(*tangent)
    if not size or not speed:return False
    outward = [v/speed*(-1 if at_end else 1) for v in tangent]
    direction = [v/size for v in delta]
    normals = [direction, [b-a for a,b in zip(outward,direction)],
               [outward[1],-outward[0]],[-outward[1],outward[0]]]
    for n in normals:
        scale = max(map(abs,n))
        if not scale:continue
        n = [x/scale for x in n]
        if sum(Fraction(a)*Fraction(b) for a,b in zip(n,delta)) <= 0:continue
        cosine = finite(math.fsum(a*b for a,b in zip(n,curve.sine)))
        sine = finite(-math.fsum(a*b for a,b in zip(n,curve.cosine)))
        samples = [start,end]
        phase = math.atan2(sine,cosine)
        for base in (phase,phase+math.pi):
            lo,hi = math.ceil((start-base)/(2*math.pi)),math.floor((end-base)/(2*math.pi))
            samples.extend(base+k*2*math.pi for k in range(lo,hi+1))
        values = [finite((cosine*math.cos(t)+sine*math.sin(t))*(-1 if at_end else 1)) for t in samples]
        padding = 64*math.ulp(max(1.,abs(cosine)+abs(sine)))
        if max(values)+padding < 0:return True
    return False


def _terminal_affine_retrace(first,last,curve,parameter,direction,role):
    """Admit a strict opposite overlap in the formal float-endpoint model.

    Exact endpoint laws give a zero-chain terminal retrace. A rounded line end
    can leave a non-integrated law-to-token jump; its distinct record makes no
    zero-flux claim. Every line jump also gets the per-level chart diagnostic.
    Degree1/two-pole positive rational weights only change monotone speed.
    """
    from .gauss_green import LineCurve,RationalCurve
    if type(direction)is not int or direction not in(-1,1)or role not in('incoming','outgoing'):
        return None
    if isinstance(curve,LineCurve):
        a=tuple(map(Fraction,curve.first));width=Fraction(curve.end)-Fraction(curve.start)
        b=tuple(x+Fraction(v)*width for x,v in zip(a,curve.slope));law='stored-LineCurve'
    elif isinstance(curve,RationalCurve)and curve.degree==1 and len(curve.poles)==2:
        if any(p[2]<=0 for p in curve.poles):return None
        a,b=[tuple(Fraction(v)/Fraction(p[2])for v in p[:2])for p in curve.poles]
        law='stored-degree1-two-pole-positive-weight-rational'
    else:return None
    if a==b:return None
    expected=(curve.end if direction>0 else curve.start)if role=='incoming'else(curve.start if direction>0 else curve.end)
    if parameter!=expected:return None
    anchor=a if parameter==curve.start else b
    common=tuple(map(Fraction,first if role=='incoming'else last))
    other=tuple(map(Fraction,last if role=='incoming'else first))
    jump=None
    if common!=anchor:
        # Only the actual evaluated END of a stored line has this additional
        # empirical eligibility. Rational and off-line endpoint gaps refuse.
        if (not isinstance(curve,LineCurve) or parameter!=curve.end
                or common!=tuple(map(Fraction,curve.evaluate(curve.end)[0]))):
            return None
        ray=tuple(y-x for x,y in zip(a,b))
        evaluated=tuple(y-x for x,y in zip(a,common))
        if ray[0]*evaluated[1]!=ray[1]*evaluated[0]:return None
        backwards=tuple(x-y for x,y in zip(a,common))
        to_other=tuple(x-y for x,y in zip(other,common))
        if backwards[0]*to_other[1]!=backwards[1]*to_other[0]:return None
        if not 0<sum(x*y for x,y in zip(backwards,to_other))<sum(x*x for x in backwards):
            return None
        ideal_distance=sum((x-y)**2 for x,y in zip(other,anchor))
        token_distance=sum((x-y)**2 for x,y in zip(other,common))
        jump={'exactLawEndpoint':list(map(str,anchor)),
              'ledgerEndpointToken':list(map(float,common)),
              'exactEndpointJump':[str(y-x)for x,y in zip(anchor,common)],
              'ordering':('ideal-endpoint-nearer-Q' if ideal_distance<token_distance
                          else 'ledger-endpoint-nearer-Q'),
              'residualJumpWireCoefficient':-direction,
              'nonIntegratedJump':True}
    full=tuple(y-x for x,y in zip(anchor,b if parameter==curve.start else a))
    part=tuple(y-x for x,y in zip(anchor,other))
    if full[0]*part[1]!=full[1]*part[0]:return None
    dot=sum(x*y for x,y in zip(full,part));square=sum(x*x for x in full)
    if not 0<dot<square:return None
    ratio=dot/square if parameter==curve.start else 1-dot/square
    if isinstance(curve,RationalCurve):
        w0,w1=Fraction(curve.poles[0][2]),Fraction(curve.poles[1][2])
        ratio=ratio*w0/(w1*(1-ratio)+ratio*w0)
    other_parameter=Fraction(curve.start)+(Fraction(curve.end)-Fraction(curve.start))*ratio
    return {'law':law,'role':role,'wireDirection':direction,'endpointParameter':parameter,
            'eligibilityKind':('empirical-collinear-overlap-with-line-endpoint-jump/1' if jump
                               else 'exact-terminal-affine-zero-chain/1'),
            'originalParameterRange':[curve.start,curve.end],
            'retraceParameterRange':sorted([parameter,float(other_parameter)]),
            'exactOtherParameter':str(other_parameter),
            'endpointPair':[list(first),list(last)],
            'fractionOfOriginalAffinePath':float(dot/square),
            'cancellation':('overlap cancels exactly; a signed non-integrated endpoint-jump residual remains'
                            if jump else 'opposite-oriented strict terminal subarc; exact stored-law zero-chain'),
            **(jump or {'nonIntegratedJump':False})}


def _require_unlensed_conic_period(curve,budget):
    from .conic_completion_separation import conic_period_relation
    from .gauss_green import Unresolved
    relation=conic_period_relation(curve,budget)
    if relation!='shorter':
        raise Unresolved('stored conic width exceeds one period; completed lens multiplicity is not 0/1'
                         if relation=='longer' else 'stored conic period relation is unresolved')


def separated_adjacent_curve(first, last, curve, parameters, budget, *,
                             wire_direction=None, role=None, closed=False, retraces=None,
                             conic_separations=None,declared_lens=None,
                             lens_corner=None,lens_corner_index=None):
    """Allow isolated original endpoint contact, checking ALL other spans."""
    from .gauss_green import RationalCurve,LineCurve,ConicCurve,coordinate_bounds,Unresolved
    allowed = set(parameters)
    if not allowed or allowed-set((curve.start,curve.end)):
        raise Unresolved('adjacent contact is not a complete original endpoint')
    if declared_lens is not None:
        from .conic_lens import Lens
        if (not isinstance(declared_lens,Lens) or not isinstance(curve,ConicCurve)
                or declared_lens.curve is not curve or declared_lens.domain!=(curve.start,curve.end)
                or lens_corner is None or declared_lens.face is not lens_corner.face
                or declared_lens.corner!=lens_corner_index
                or tuple(first)!=tuple(lens_corner.before)or tuple(last)!=tuple(lens_corner.after)):
            raise Unresolved('declared conic lens does not match this original corner')
        index=declared_lens.occurrence
        if declared_lens.role=='closed-wire':
            valid=(closed and lens_corner.first==lens_corner.second==index
                   and allowed=={curve.start,curve.end})
        else:
            incoming=declared_lens.role=='incoming'
            endpoint=lens_corner.first_parameter if incoming else lens_corner.second_parameter
            valid=(role==declared_lens.role and index==(lens_corner.first if incoming else lens_corner.second)
                   and allowed=={endpoint})
        if not valid:raise Unresolved('declared conic lens endpoint role differs')
        # Whole-state classification and isolation already ran. This exemption
        # applies only to its exact occurrence/corner/role, not nearby geometry.
        budget.check();return 1
    if isinstance(curve,ConicCurve):
        _require_unlensed_conic_period(curve,budget)
    if len(allowed)==1:
        eligibility=_terminal_affine_retrace(first,last,curve,next(iter(allowed)),wire_direction,role)
        if eligibility is not None:
            eligibility['nativeClosedEdge']=bool(closed)
            if retraces is not None:retraces.append(eligibility)
            return 1
    pending = ([(a,b,poles,0,a in allowed,b in allowed)
                for a,b,poles in curve.bezier_spans(budget)] if isinstance(curve,RationalCurve)
               else [(curve.start,curve.end,None,0,curve.start in allowed,curve.end in allowed)])
    visited = 0
    while pending:
        budget.check();a,b,poles,depth,touch_a,touch_b = pending.pop();visited += 1
        if visited > 32768:raise Unresolved('adjacent separation allocation refusal')
        if touch_a and touch_b:
            endpoint_ok = False
        elif touch_a or touch_b:
            at_end = touch_b;parameter = b if at_end else a
            point = curve.evaluate(parameter)[0]
            if tuple(point)==tuple(first):connector=(first,last)
            elif tuple(point)==tuple(last):connector=(last,first)
            else:raise Unresolved('adjacent curve and connector do not share the exact endpoint')
            try:
                if isinstance(curve,ConicCurve):
                    from .conic_completion_separation import separated_from_ideal_conic
                    separation=separated_from_ideal_conic(*connector,curve,budget)
                    if separation and conic_separations is not None:
                        conic_separations.append({'method':'exact-implicit-ellipse/1',
                            'side':separation,'endpointParameter':parameter,
                            'originalParameterRange':[curve.start,curve.end],
                            'floatingEndpoint':list(point),'idealConnector':[list(x)for x in connector],
                            'lawToEvaluatedEndpointGapModelled':False,'certifiedNative':False})
                    endpoint_ok = bool(separation) or _conic_endpoint_cone(*connector,curve,a,b,at_end)
                else:
                    control = poles if poles is not None else [(*curve.evaluate(t)[0],1.) for t in (a,b)]
                    endpoint_ok = _endpoint_cone(*connector,control,at_end)
            except ValueError as error:raise Unresolved(str(error)) from error
            if endpoint_ok:continue
        else:
            if poles is not None:hull=_hull([(p[0]/p[2],p[1]/p[2])for p in poles])
            elif isinstance(curve,LineCurve):hull=[curve.evaluate(t)[0]for t in(a,b)]
            elif isinstance(curve,ConicCurve):
                segment=copy.copy(curve);segment.start,segment.end=a,b
                lo,hi,bottom,top=coordinate_bounds(segment);hull=[(lo,bottom),(hi,bottom),(hi,top),(lo,top)]
            else:raise Unresolved('adjacent separation unreviewed curve')
            if _separate(first,last,hull):continue
        middle=a+(b-a)/2
        if depth>=24 or middle in(a,b):
            detail={'curve':type(curve).__name__,'connector':[first,last],
                    'domain':[curve.start,curve.end],'interval':[a,b],
                    'endpoints':[curve.evaluate(a)[0],curve.evaluate(b)[0]],
                    'touchesOriginalEndpoint':[touch_a,touch_b],
                    'homogeneousControls':poles,'depth':depth}
            raise Unresolved('connector meets unresolved adjacent curve: '+repr(detail))
        left,right=_split(poles)if poles is not None else(None,None)
        pending.extend(((a,middle,left,depth+1,touch_a,False),(middle,b,right,depth+1,False,touch_b)))
    return visited


def _retained_affine_spans(retraces, occurrences, budget):
    """Keep a strict original span after recorded terminal-overlap eligibility.

    Native closure may identify the two end vertices of an injective UV line.
    That does not permit its incoming and outgoing retraces to meet or overlap.
    Only exact parameters participate here; rounded display ranges do not.
    """
    from .gauss_green import Unresolved
    grouped=collections.defaultdict(list)
    for record in retraces:
        grouped[record['occurrence']].append(record)
    retained=[]
    for index, records in grouped.items():
        budget.check()
        _,_,edge,curve,direction=occurrences[index]
        start,end=Fraction(curve.start),Fraction(curve.end)
        lower,upper=start,end
        roles,corners,intervals=set(),set(),[]
        if len(records)>2:
            raise Unresolved('terminal affine retraces repeat an occurrence role')
        for record in records:
            budget.check()
            role=record['role']
            if (role not in ('incoming','outgoing') or role in roles
                    or record['corner'] in corners or record['wireDirection']!=direction
                    or type(direction)is not int or direction not in (-1,1)):
                raise Unresolved('terminal affine retraces have duplicate or inconsistent roles')
            roles.add(role);corners.add(record['corner'])
            expected=(end if direction>0 else start)if role=='incoming'else(start if direction>0 else end)
            parameter=Fraction(record['endpointParameter'])
            other=Fraction(record['exactOtherParameter'])
            budget.tick()
            native_closed=edge.firstVertex(False).isSame(edge.lastVertex(False))
            if (parameter!=expected or not start<other<end
                    or list(map(Fraction,record['originalParameterRange']))!=[start,end]
                    or record['nativeClosedEdge'] is not native_closed):
                raise Unresolved('terminal affine retrace has an inconsistent exact parameter')
            intervals.append(sorted((parameter,other)))
            if parameter==start:lower=other
            else:upper=other
        intervals.sort()
        if (not lower<upper or len(intervals)==2 and not intervals[0][1]<intervals[1][0]):
            raise Unresolved('terminal affine retraces leave no strict retained original span')
        retained.append({'occurrence':index,'exactRetainedParameterRange':[str(lower),str(upper)]})
    return retained


def _isolated_connector_endpoint(first, second, budget):
    """Only same native vertex + exact common UV permits isolated contact."""
    common=set((first.before,first.after))&set((second.before,second.after))
    if len(common)!=1:return False
    budget.tick()
    if not first.vertex.isSame(second.vertex):return False
    point=next(iter(common))
    a=first.after if first.before==point else first.before
    b=second.after if second.before==point else second.before
    x=[Fraction(v)-Fraction(o)for v,o in zip(a,point)]
    y=[Fraction(v)-Fraction(o)for v,o in zip(b,point)]
    cross=x[0]*y[1]-x[1]*y[0]
    # Noncollinear segments share just the endpoint; collinear same-direction
    # rays overlap, while opposite rays share only that endpoint.
    return cross!=0 or sum(a*b for a,b in zip(x,y))<0


def incidence_and_uv_admission(state, budget):
    """Check formal float-endpoint incidence of the actual piece coefficients.

    Trace tokens end at evaluated points; this is not a certificate that every
    ideal coefficient-law endpoint coincides geometrically with that token.
    """
    from .gauss_green import Unresolved
    occurrences = state['occurrences']
    # Equal evaluated tokens omit a connector, but do not remove a positive
    # ideal-law surplus turn. Check EVERY occurrence before corner traversal.
    # A future declared lens policy must explicitly classify this case too.
    from .conic_lens import classify_lenses
    lenses,lens_isolation=classify_lenses(state,budget)
    state['conicLensDescriptors']=lenses
    lens_by_key={(lens.occurrence,lens.corner,lens.role):lens for lens in lenses}
    residual, terms = collections.Counter(), collections.Counter()
    vertices, vertex_buckets = [], {}

    def vertex_token(vertex):
        bucket = vertex_buckets.setdefault(vertex.hashCode(), [])
        for index in bucket:
            budget.tick()
            if vertex.isSame(vertices[index]):
                return ('vertex', index)
        vertices.append(vertex)
        bucket.append(len(vertices)-1)
        return ('vertex', len(vertices)-1)

    def endpoint(index, end):
        face, _, _, curve, _ = occurrences[index]
        uv = curve.evaluate(curve.end if end else curve.start)[0]
        return ('uv', id(face), *uv)

    def segment(a, b, coefficient, piece):
        if a == b:
            return
        if a > b:
            a, b, coefficient = b, a, -coefficient
        residual[('segment', a, b)] += coefficient
        terms[piece] += 1

    def trace(index, coefficient, piece):
        residual[('trace', index)] += coefficient
        terms[piece] += 1

    def triangle(a, b, c, coefficient, piece):
        segment(a, b, coefficient, piece)
        segment(b, c, coefficient, piece)
        segment(c, a, coefficient, piece)

    for index, (_, sign, _, _, direction) in enumerate(occurrences):
        trace(index, sign*direction, 'chart')
    for piece in state['pairs']:
        i, j, coefficient = piece.first, piece.second, piece.coefficient
        trace(i, coefficient, 'pair-ribbon')
        trace(j, -coefficient, 'pair-ribbon')
        edge = occurrences[i][2]
        for end, rung, cap in ((False, -coefficient, piece.start_cap),
                              (True, coefficient, piece.end_cap)):
            p, q = endpoint(i, end), endpoint(j, end)
            segment(p, q, rung, 'pair-ribbon')
            native = edge.lastVertex(False) if end else edge.firstVertex(False)
            triangle(vertex_token(native), p, q, cap, 'pair-endpoint-cap')
    for piece in state['poles']:
        index, coefficient = piece.occurrence, piece.coefficient
        edge = occurrences[index][2]
        p = vertex_token(piece.vertex)
        if p != vertex_token(edge.lastVertex(False)):
            raise Unresolved('completion incidence collapsed pole differs')
        trace(index, coefficient, 'collapsed-fan')
        segment(endpoint(index, True), p, coefficient, 'collapsed-fan')
        segment(endpoint(index, False), p, -coefficient, 'collapsed-fan')
    hull_tests, connectors, connector_pair_tests, retraces, conic_records = 0, [], 0, [], []
    for index, piece in enumerate(state['corners']):
        i, j = piece.first, piece.second
        p = endpoint(i, occurrences[i][4] > 0)
        q = endpoint(j, occurrences[j][4] < 0)
        v = vertex_token(piece.vertex)
        if piece.before != piece.after:
            connectors.append(piece)
            residual[('connector', index)] += piece.chart_coefficient
            residual[('connector', index)] += piece.patch_coefficient
            terms['chart-connector'] += 1
            terms['curved-connector-patch'] += 1
            segment(p, q, -piece.patch_coefficient, 'curved-connector-patch')
            for k, (face, _, _, curve, _) in enumerate(occurrences):
                if face is not piece.face:continue
                adjacent=[]
                if k==i:adjacent.append(piece.first_parameter)
                if k==j:adjacent.append(piece.second_parameter)
                if adjacent:
                    budget.tick()
                    closed=occurrences[k][2].firstVertex(False).isSame(occurrences[k][2].lastVertex(False))
                    eligibilities=[];separations=[]
                    hull_tests+=separated_adjacent_curve(piece.before,piece.after,curve,adjacent,budget,
                        wire_direction=occurrences[k][4],role=('incoming'if k==i else'outgoing'),
                        closed=closed,retraces=eligibilities,conic_separations=separations,
                        declared_lens=lens_by_key.get((k,index,'closed-wire'if i==j else'incoming'if k==i else'outgoing')),
                        lens_corner=piece,lens_corner_index=index)
                    retraces.extend({'corner':index,'occurrence':k,**r}for r in eligibilities)
                    conic_records.extend({'corner':index,'occurrence':k,**r}for r in separations)
                else:hull_tests+=separated_from_curve(piece.before,piece.after,curve,budget)
        triangle(v, q, p, piece.cap_coefficient, 'corner-cap')
    # Two newly introduced shortcuts must not cross one another either.
    for index, first in enumerate(connectors):
        for second in connectors[index+1:]:
            budget.check()
            if first.face is not second.face:continue
            if not (_separate(first.before, first.after, [second.before, second.after])
                    or _isolated_connector_endpoint(first,second,budget)):
                raise Unresolved('completion non-adjacent UV connectors are not separated')
            connector_pair_tests += 1
    retained_spans=_retained_affine_spans(retraces,occurrences,budget)
    nonzero = {repr(key): value for key, value in residual.items() if value}
    if nonzero:
        raise Unresolved('executable completion boundary is not zero: '+repr(nonzero))
    return {'method': 'typed-completion-incidence/1', 'zeroBoundary': True,
            'boundarySpace':'formal-float-endpoint-incidence/1',
            'zeroBoundaryMeaning':'symbolic incidence of float endpoint tokens and shared piece coefficients',
            'idealLawClosureCertified':False,
            'termCounts': dict(terms), 'vertices': len(vertices), 'occurrences': len(occurrences),
            'connectorCount': len(connectors), 'nonAdjacentHullTests': hull_tests,
            'connectorPairTests': connector_pair_tests,
            'terminalAffineRetraceCount':len(retraces),'terminalAffineRetraces':retraces,
            'terminalAffineRetainedSpans':retained_spans,
            'idealConicSeparationCount':len(conic_records),'idealConicSeparations':conic_records,
            'declaredConicLensCount':len(lenses),'declaredConicLenses':[lens.record()for lens in lenses],
            'conicLensIsolationTests':lens_isolation,
            'uvSeparation': 'finite strict hulls, isolated endpoint cones, strict ideal whole-conic separation, recorded affine terminal overlap and uniquely declared isolated auxiliary conic lenses; unintegrated endpoint jumps remain empirical, not zero-flux cancellations',
            'certified': False}

def coarse_winding(shape, volume, area, budget):
    from .gauss_green import Unresolved, EvaluationLimit, MeasurementDeadline
    box = shape.BoundBox
    diagonal = math.sqrt(box.XLength**2+box.YLength**2+box.ZLength**2)
    delta = max(diagonal*1e-3, 1e-9)
    from .gauss_green import finite
    volume,area=finite(volume),finite(area)
    if volume==0 or area<=0:raise Unresolved('coarse winding requires nonzero volume and positive area')
    budget.tick()
    # TopoShape.tessellate also tightens angular tolerance with model scale.
    # Specify both independently, on a copy with no inherited triangulation.
    # FreeCAD's public copy signature is positional (copyGeom, copyMesh).
    import MeshPart
    import Part
    try:
        diagnostic_shape = shape.copy(True, False)
        mesh = MeshPart.meshFromShape(Shape=diagnostic_shape, LinearDeflection=delta,
                                     AngularDeflection=.25, Relative=False)
    except (EvaluationLimit,MeasurementDeadline):
        raise
    except (Part.OCCError,OSError,ArithmeticError,ValueError,RuntimeError) as error:
        raise Unresolved('coarse winding native mesher failed: '+str(error)) from error
    budget.check()
    if not 0 < mesh.CountFacets <= 1000000 or not 0 < mesh.CountPoints <= 1000000:
        raise Unresolved('coarse winding mesh allocation budget refusal')
    points, triangles = mesh.Topology
    if not points or not triangles or len(triangles) > 1000000:
        raise Unresolved('coarse winding mesh membership/budget refusal')
    origin = (box.Center.x, box.Center.y, box.Center.z)
    terms = []
    for triangle in triangles:
        budget.tick()
        a, b, c = [tuple(x-y for x, y in zip(points[i], origin)) for i in triangle]
        cross = (b[1]*c[2]-b[2]*c[1], b[2]*c[0]-b[0]*c[2], b[0]*c[1]-b[1]*c[0])
        terms.append(math.fsum(x*y for x, y in zip(a, cross))/6)
    observed = math.fsum(terms)
    allowance = 4*delta*area
    if abs(observed-volume) > allowance:
        raise Unresolved('gross winding differs from independent coarse signed mesh')
    return {'method': 'coarse-signed-tetrahedra/1', 'deflection': delta,
            'angularDeflection': .25, 'relativeDeflection': False,
            'triangles': len(triangles), 'signedVolume': observed, 'difference': abs(observed-volume),
            'allowance': allowance, 'allowanceToAbsoluteVolume': allowance/abs(volume), 'certified': False,
            'assumption': 'native shell non-self-intersection; gross winding discriminator only'}
