"""Bounded native Gauss--Green instrument under development.

Two deterministic integration schemes provide empirical resolution controls,
not a certified error bound. Admission limits here do not exclude unfinished
modelling families from the adaptor's completion requirements.
"""
import math

from .gauss_green import (Budget, ConicCurve, EvaluationLimit, LineCurve, RationalCurve, Unresolved,
                         continuation_weight_bound, coordinate_bounds, finite,
                         integrate, partitions, uv_area_integral)


_CURVES = {'Line2d', 'Line2dSegment', 'Circle2d', 'Ellipse2d',
           'BSplineCurve2d', 'BezierCurve2d'}
_SURFACES = {'Plane', 'Cylinder', 'Cone', 'Sphere', 'Toroid',
             'BSplineSurface', 'BezierSurface', 'SurfaceOfExtrusion',
             'SurfaceOfRevolution'}
_BASES = {'Line', 'LineSegment', 'Circle', 'Ellipse', 'ArcOfCircle',
          'ArcOfEllipse', 'BSplineCurve', 'BezierCurve'}


def _numbers(values):
    return [finite(value) for value in values]


def _spline_size(geometry):
    """Inspect finite native dimensions before requesting pole arrays."""
    for name in ('NbPoles', 'NbUPoles', 'NbVPoles', 'NbKnots',
                 'NbUKnots', 'NbVKnots'):
        if hasattr(geometry, name):
            value = getattr(geometry, name)
            if type(value) is not int or not 1 <= value <= 2048:
                raise Unresolved('native spline dimension exceeds admission')
    for name in ('Degree', 'UDegree', 'VDegree'):
        if hasattr(geometry, name):
            value = getattr(geometry, name)
            if type(value) is not int or not 1 <= value <= 25:
                raise Unresolved('native spline degree exceeds admission')
    if (hasattr(geometry, 'NbUPoles') and hasattr(geometry, 'NbVPoles')
            and geometry.NbUPoles * geometry.NbVPoles > 16384):
        raise Unresolved('native surface pole allocation exceeds admission')


def _knots(geometry, method):
    if not hasattr(geometry, method):
        return []
    values = _numbers(getattr(geometry, method)())
    if len(values) > 4096 or any(a >= b for a, b in zip(values, values[1:])):
        raise Unresolved('invalid native distinct knot inventory')
    return values


def _spline_data(geometry, budget):
    """Bounded finite native poles and positive basis weights.

Positive basis weights do not certify rational continuation or integration
conditioning outside the basis domain. The numerical controls remain empirical.
"""
    _spline_size(geometry)
    if not hasattr(geometry, 'getPoles'):
        return None
    poles, weights = geometry.getPoles(), geometry.getWeights()
    if hasattr(geometry, 'NbUPoles'):
        if (len(poles) != geometry.NbUPoles or len(weights) != len(poles)
                or any(len(row) != geometry.NbVPoles for row in poles)
                or any(len(row) != geometry.NbVPoles for row in weights)):
            raise Unresolved('native surface pole/weight membership differs')
        pairs = [(p, w) for row, values in zip(poles, weights)
                 for p, w in zip(row, values)]
    else:
        if len(poles) != geometry.NbPoles or len(weights) != len(poles):
            raise Unresolved('native basis pole/weight membership differs')
        pairs = list(zip(poles, weights))
    values = []
    for point, weight in pairs:
        budget.tick()
        _numbers((point.x, point.y, point.z))
        weight = finite(weight)
        if weight <= 0:
            raise Unresolved('nonpositive native basis weight')
        values.append(weight)
    return {'poles': len(pairs), 'minimumWeight': min(values),
            'maximumWeight': max(values)}


def _basis_breaks(geometry, method, periodic_name, period_name, low, high,
                  basis_domain=None):
    knots = _knots(geometry, method)
    if not knots:
        return [], {'knots': [], 'period': None, 'trim': [low, high],
                    'basisDomain': basis_domain}
    ends = _numbers(basis_domain) if basis_domain is not None else [knots[0], knots[-1]]
    if len(ends) != 2 or not knots[0] <= ends[0] < ends[1] <= knots[-1]:
        raise Unresolved('invalid finite native basis domain')
    flag = getattr(geometry, periodic_name)
    periodic = flag() if callable(flag) else flag
    if type(periodic) is not bool:
        raise Unresolved('invalid native periodicity witness')
    if periodic:
        period = getattr(geometry, period_name)
        period = finite(period() if callable(period) else period)
        if period <= 0 or high-low > 64*period:
            raise Unresolved('periodic trim span exceeds bounded admission')
        result = set()
        # Both seam and interior knots may lie inside the actual trim domain.
        for knot in knots:
            first = math.ceil((low-knot)/period)
            last = math.floor((high-knot)/period)
            if (last-first+1)*len(knots) > 4096:
                raise Unresolved('periodic knot lifting budget exceeded')
            for turn in range(first, last+1):
                value = finite(knot+turn*period)
                if low < value < high:
                    result.add(value)
        if len(result) > 4096:
            raise Unresolved('periodic knot inventory exceeds admission')
        return sorted(result), {'knots': knots, 'period': period, 'trim': [low, high],
                                'basisDomain': ends}
    # OCCT 7.8.1 LocateParameter retains nonperiodic U and clamps the span
    # index, so the outer polynomial/rational span continues beyond a basis
    # endpoint. Integrate through valueAt/derivative1At over a separately
    # bounded original-pcurve envelope, union the reported ParameterRange;
    # never project, clamp, enlarge a mass tolerance or infer an accuracy bound
    # from native face tolerance. Record continuation rather than inventing a
    # parameter-space admission tolerance. Nonfinite/unresolved integrals refuse.
    return [k for k in knots if ends[0] < k < ends[1] and low < k < high], {
        'knots': knots, 'period': None, 'trim': [low, high],
        'basisDomain': ends,
        'continuation': [max(0., ends[0]-low), max(0., high-ends[1])]}


def _angular_breaks(period, low, high, ends):
    """Explicit analytic seams; a missing spline knot method is not a period."""
    period=finite(period)
    if period<=0 or high-low>64*period:
        raise Unresolved('periodic trim span exceeds bounded admission')
    first=math.ceil((low-ends[0])/period)
    last=math.floor((high-ends[0])/period)
    if last-first+1>4096:
        raise Unresolved('periodic seam inventory exceeds admission')
    seams=[finite(ends[0]+turn*period) for turn in range(first,last+1)]
    return [value for value in seams if low<value<high], {
        'knots':[],'seams':list(ends),'period':period,'trim':[low,high],
        'basisDomain':list(ends)}


def _curve_basis(basis, low, high, budget):
    """Admit the actual meridian/extrusion basis before pole allocation."""
    kind=type(basis).__name__
    if kind not in _BASES:
        raise Unresolved('unreviewed swept-surface basis '+kind)
    original_kind=kind
    arc_domain=None
    if kind in ('ArcOfCircle','ArcOfEllipse'):
        # The native swept surface remains the evaluator. Inspect the exact
        # internal conic only to establish its analytic period and radii;
        # retain the trimmed basis domain separately from the full conic.
        # FreeCAD 1.1.4 ArcOfCircle.Circle / ArcOfEllipse.Ellipse API.
        arc_domain=_numbers((basis.FirstParameter,basis.LastParameter))
        if not arc_domain[0]<arc_domain[1]:
            raise Unresolved('invalid finite meridian arc domain')
        basis=getattr(basis,'Circle' if kind=='ArcOfCircle' else 'Ellipse')
        kind=type(basis).__name__
        if kind!=original_kind[5:]:
            raise Unresolved('native meridian arc conic type differs')
    if kind=='Circle' and finite(basis.Radius)<=0:
        raise Unresolved('circular meridian needs a finite positive radius')
    if kind=='Ellipse' and not 0<finite(basis.MinorRadius)<=finite(basis.MajorRadius):
        raise Unresolved('elliptical meridian needs finite positive ordered radii')
    data=_spline_data(basis,budget)
    ends=(_numbers((basis.FirstParameter,basis.LastParameter))
          if kind in ('BSplineCurve','BezierCurve','Circle','Ellipse') else None)
    if kind in ('Circle','Ellipse'):
        if basis.isPeriodic() is not True:
            raise Unresolved('analytic meridian periodicity differs')
        knots,info=_angular_breaks(basis.period(),low,high,ends)
    else:
        knots,info=_basis_breaks(basis,'getKnots','isPeriodic','period',low,high,ends)
    if kind=='BezierCurve':
        if ends!=[0.,1.]:raise Unresolved('Bezier meridian basis domain differs')
        info.update(knots=[0.,1.],continuation=[max(0.,-low),max(0.,high-1)])
    if arc_domain is not None:
        info['trimmedBasisDomain']=arc_domain
        info['periodSource']='underlying analytic conic, not trimmed-basis periodicity'
    return knots,info,data,getattr(basis,'Degree',1),original_kind


def _surface(surface, domain, budget):
    kind = type(surface).__name__
    if kind not in _SURFACES:
        raise Unresolved('unreviewed native surface ' + kind)
    if kind == 'Cylinder' and finite(surface.Radius) <= 0:
        raise Unresolved('cylinder requires a finite positive radius')
    data = _spline_data(surface, budget)
    basis_bounds = (_numbers(surface.bounds()) if kind == 'BSplineSurface'
                    else [0., 1., 0., 1.] if kind == 'BezierSurface' else [None]*4)
    uknots, uinfo = _basis_breaks(surface, 'getUKnots', 'isUPeriodic',
                                 'UPeriod', domain[0], domain[1],
                                 basis_bounds[:2] if basis_bounds[0] is not None else None)
    vknots, vinfo = _basis_breaks(surface, 'getVKnots', 'isVPeriodic',
                                 'VPeriod', domain[2], domain[3],
                                 basis_bounds[2:] if basis_bounds[2] is not None else None)
    basis_type=None
    if kind in ('SurfaceOfExtrusion','SurfaceOfRevolution'):
        direction=_numbers(list(surface.Direction))
        if len(direction)!=3 or finite(math.hypot(*direction))==0:
            raise Unresolved('swept surface needs a finite nonzero direction')
        axis=0 if kind=='SurfaceOfExtrusion' else 2
        knots,info,data,degree,basis_type=_curve_basis(
            surface.BasisCurve,domain[axis],domain[axis+1],budget)
        if kind=='SurfaceOfExtrusion':
            uknots,uinfo=knots,info;degrees=(degree,0)
        else:
            _numbers(list(surface.Location))
            if surface.isUPeriodic() is not True or finite(surface.UPeriod())!=2*math.pi:
                raise Unresolved('revolution requires its native angular U period')
            uknots,uinfo=_angular_breaks(2*math.pi,domain[0],domain[1],[0.,2*math.pi])
            vknots,vinfo=knots,info;degrees=(0,degree)
    else:
        degrees = (getattr(surface, 'UDegree', 1), getattr(surface, 'VDegree', 1))
    if kind == 'BezierSurface':
        uinfo.update(knots=[0., 1.], continuation=[max(0., -domain[0]), max(0., domain[1]-1)])
        vinfo.update(knots=[0., 1.], continuation=[max(0., -domain[2]), max(0., domain[3]-1)])
    if data is not None:
        data['denominatorWeightBound'] = continuation_weight_bound(
            data['minimumWeight'], data['maximumWeight'],
            [(degree, info['knots'], info['trim'], info['period'] is not None,
              info['basisDomain'])
             for degree, info in zip(degrees, (uinfo, vinfo))])
    return uknots, vknots, {'u': uinfo, 'v': vinfo, 'basisData': data,
                           'basisType':basis_type,
                           'continuationDegrees':list(degrees) if data is not None else None,
                           'domainSource': 'original-pcurve-envelope-union-ParameterRange'}


def _curve(curve, start, end, face, edge, budget, *, completed_boundary=False):
    kind = type(curve).__name__
    if kind not in _CURVES:
        raise Unresolved('unreviewed native pcurve ' + kind)
    _spline_size(curve)
    start, end = finite(start), finite(end)
    if not start < end:
        raise Unresolved('invalid original pcurve interval')
    budget.check()
    if kind in ('Line2d', 'Line2dSegment'):
        first, last = curve.value(start), curve.value(end)
        evaluator = LineCurve(start, end, [first.x, first.y], [last.x, last.y])
        degree, poles = 1, 2
    elif kind in ('Circle2d', 'Ellipse2d'):
        location, xaxis, yaxis = curve.Location, curve.XAxis, curve.YAxis
        radii = ((curve.Radius, curve.Radius) if kind == 'Circle2d'
                 else (curve.MajorRadius, curve.MinorRadius))
        evaluator = ConicCurve(start, end, [location.x, location.y],
                               [xaxis.x, xaxis.y], [yaxis.x, yaxis.y], radii)
        degree, poles = None, None
    else:
        # FreeCAD Curve2d.toBSpline uses ShapeConstruct_Curve conversion at
        # Precision::Confusion, which need not preserve a conic exactly.
        # Use original rational data; segmenting an existing spline inserts
        # knots instead of approximating its geometric locus.
        if kind == 'BSplineCurve2d':
            multiplicities=curve.getMultiplicities()
            clamped=(not curve.isPeriodic() and multiplicities[0]==curve.Degree+1
                     and multiplicities[-1]==curve.Degree+1)
            if clamped and (start,end)==(curve.FirstParameter,curve.LastParameter):
                spline=curve
            else:
                spline = curve.copy()
                spline.segment(start, end)
            budget.check()
            # Native Segment may snap a requested endpoint onto a nearby knot.
            # The evaluator and the 3D endpoint check must use the SAME exact
            # original interval; six matching sample values cannot prove that.
            if (spline.FirstParameter,spline.LastParameter)!=(start,end):
                raise Unresolved('native pcurve segmentation changed the original interval')
            _spline_size(spline)
            knots = list(spline.KnotSequence)
            source = spline
        else:
            source = curve
            if start != 0 or end != 1:
                raise Unresolved('trimmed original Bezier interval requires review')
            knots = [start]*(source.Degree+1)+[end]*(source.Degree+1)
        from .pcurve_native import NativeRationalCurve
        evaluator = NativeRationalCurve(source.Degree, knots,
                                       [[p.x, p.y] for p in source.getPoles()],
                                       list(source.getWeights()),budget)
        degree, poles = source.Degree, source.NbPoles
    maximum = 0.0
    for fraction in (0., .13, .37, .71, .91, 1.):
        budget.tick()
        t = evaluator.start+(evaluator.end-evaluator.start)*fraction
        point, derivative = evaluator.evaluate(t)
        original = curve.value(t)
        maximum = max(maximum, math.hypot(point[0]-original.x, point[1]-original.y))
        if math.hypot(*derivative) == 0:
            raise Unresolved('zero original pcurve speed')
    if maximum > 1e-9:
        raise Unresolved('original pcurve evaluation differs: '+repr((kind, maximum)))
    if not completed_boundary:
        for parameter in (start, end):
            uv = curve.value(parameter)
            point = face.valueAt(uv.x, uv.y)
            if (point-edge.valueAt(parameter)).Length > 1e-7:
                raise Unresolved('pcurve and three-dimensional edge endpoints differ')
    return evaluator, {'type': kind, 'degree': degree, 'poles': poles,
                       'originalValueCheck': maximum, 'approximateConversion': False,
                       **({'embedding':evaluator.embedding} if isinstance(evaluator,RationalCurve) else {})}


def _ordered(wire):
    """Separate seam occurrences are required, even for identical TShapes."""
    return wire.OrderedEdges


def _topology_faces(shape, budget):
    """Use the shared, independently qualified native occurrence admission."""
    from .solid_topology_native import admit, TopologyLimit, TopologyRefused
    try:
        value = admit(shape, max_faces=256, max_edges=2048,
                      max_occurrences=8192, max_checks=4_000_000,
                      checkpoint=budget.tick)
    except TopologyLimit as error:
        raise EvaluationLimit('native topology admission budget exhausted: '+str(error)) from error
    except TopologyRefused as error:
        raise Unresolved('instrument requires exactly one bounded occurrence-complete solid: '
                         + str(error)) from error
    return [row['face'] for row in value['faces']], value['facts']


def prepare(shape, budget, *, boundary_method=None):
    if boundary_method not in (None, 'explicit-completed-boundary/1'):
        raise Unresolved('unreviewed boundary measurement method')
    completion = None
    if boundary_method is not None:
        from .mass_boundary_native import new_state
        completion = new_state()
    budget.check()
    faces, topology = _topology_faces(shape, budget)
    result, total, diagnostics, surface_domains = [], 0, [], []
    for original in faces:
        budget.check()
        if original.Orientation not in ('Forward', 'Reversed'):
            raise Unresolved('unsupported face orientation')
        sign = 1 if original.Orientation == 'Forward' else -1
        # Completion pairs the original native occurrences. Preserve TShapes;
        # a geometric deep copy would destroy their cross-face identity.
        face = original.copy() if completion is None else original.reversed().reversed()
        if sign < 0:
            face.reverse()
        domain = _numbers(face.ParameterRange)
        if len(domain) != 4 or not domain[0] < domain[1] or not domain[2] < domain[3]:
            raise Unresolved('invalid finite surface domain')
        reported_domain = list(domain)
        envelopes = []
        # Preflight bounded native surface data before curve wrapper arrays.
        _surface(face.Surface, domain, budget)
        edges, uv_areas = [], []
        if face.countElement('Wire') > 2048:
            raise Unresolved('native wire count exceeds admission')
        for wire in face.Wires:
            if wire.countElement('Edge') > 2048:
                raise Unresolved('native boundary count exceeds admission')
            ordered = _ordered(wire)
            total += len(ordered)
            if not ordered or total > 2048:
                raise Unresolved('oriented boundary occurrence budget exceeded')
            endpoints = []
            for edge in ordered:
                if edge.Orientation not in ('Forward', 'Reversed'):
                    raise Unresolved('unsupported boundary orientation')
                found = face.curveOnSurface(edge)
                if found is None:
                    raise Unresolved('missing oriented surface pcurve')
                evaluator, diagnostic = _curve(*found, face, edge, budget,
                                               completed_boundary=completion is not None)
                envelope = coordinate_bounds(evaluator)
                envelopes.append(envelope)
                diagnostic['originalCurveEnvelope'] = envelope
                diagnostics.append(diagnostic)
                direction = 1 if edge.Orientation == 'Forward' else -1
                a, b = evaluator.start, evaluator.end
                first, last = evaluator.evaluate(a)[0], evaluator.evaluate(b)[0]
                endpoints.append((first, last) if direction > 0 else (last, first))
                breaks = set(evaluator.knots)
                spans = partitions(a, b, sorted(breaks))
                if isinstance(evaluator,(LineCurve,ConicCurve)):
                    area=[uv_area_integral(evaluator,a,b,budget=budget)]
                else:
                    area = [integrate(lambda t: _uv_field(evaluator, t), left, right,
                                  [1e-11/len(ordered)/len(spans)], budget=budget)[0]
                            for left, right in zip(spans, spans[1:])]
                uv_areas.append(direction*math.fsum(area))
                edges.append((evaluator, direction, spans))
            if completion is not None:
                from .mass_boundary_native import add_wire
                add_wire(completion, face, sign, ordered, endpoints, edges, uv_areas, budget)
            else:
                # On a torus all four oriented seam occurrences share one 3D
                # vertex. OrderedEdges may then use a different cyclic order than
                # the UV boundary. Require one unambiguous closed UV chain using
                # EVERY occurrence; do not equate distinct periodic UV endpoints.
                remaining = list(range(1, len(endpoints)))
                current = 0
                while remaining:
                    end = endpoints[current][1]
                    matches = [i for i in remaining
                               if math.dist(endpoints[i][0], end) <= 1e-9]
                    if len(matches) != 1:
                        raise Unresolved('oriented surface boundary chain is ambiguous or open')
                    current = matches[0]
                    remaining.remove(current)
                if math.dist(endpoints[current][1], endpoints[0][0]) > 1e-9:
                    raise Unresolved('oriented surface boundary is not closed')
        if math.fsum(uv_areas) <= 0:
            raise Unresolved('oriented face UV area is not positive')
        for envelope in envelopes:
            domain = [min(domain[0], envelope[0]), max(domain[1], envelope[1]),
                      min(domain[2], envelope[2]), max(domain[3], envelope[3])]
        uknots, vknots, surface_info = _surface(face.Surface, domain, budget)
        surface_info['reportedParameterRange'] = reported_domain
        surface_info['originalPcurveEnvelope'] = [min(e[0] for e in envelopes),
            max(e[1] for e in envelopes), min(e[2] for e in envelopes), max(e[3] for e in envelopes)]
        surface_info['integrationDomain'] = domain
        if completion is not None:
            from .line_endpoint_jumps import endpoint_jump
            jumps=[];proxy_domain=list(domain)
            for edge_index,(evaluator,_,_) in enumerate(edges):
                if not isinstance(evaluator,LineCurve):continue
                jump=endpoint_jump(evaluator,completion['lineEndpointTokens'][id(evaluator)],budget)
                if jump is None:continue
                jump['edgeIndex']=edge_index
                jumps.append(jump)
                for u,v in jump['samplePoints']:
                    proxy_domain=[min(proxy_domain[0],u),max(proxy_domain[1],u),
                                  min(proxy_domain[2],v),max(proxy_domain[3],v)]
            # The diagnostic may sample the rounded ideal-law endpoint a few
            # ulps beyond the measured trace's envelope. Preflight that explicit
            # finite envelope separately; never change the integration gauge,
            # original law/domain, or measured arithmetic to accommodate it.
            puk,pvk,pinfo=(_surface(face.Surface,proxy_domain,budget) if jumps
                          else (uknots,vknots,surface_info))
            surface_info['lineEndpointJumpPreparation']={
                'envelope':proxy_domain,'uKnots':puk,'vKnots':pvk,'jumps':jumps,
                'envelopeSource':'unchanged measured domain union rounded ideal line-end diagnostic samples',
                'basis':({k:v for k,v in pinfo.items() if k!='lineEndpointJumpPreparation'}
                         if jumps else None)}
        surface_domains.append(surface_info)
        partitioned = []
        for evaluator, direction, _ in edges:
            breaks = set(evaluator.knots)
            # Both coordinates change a polynomial span of the nested strip.
            for axis, knots in ((0, uknots), (1, vknots)):
                for knot in knots:
                    breaks.update(evaluator.crossings(axis, knot, budget=budget))
            partitioned.append((evaluator, direction,
                                partitions(evaluator.start, evaluator.end, sorted(breaks))))
        edges = partitioned
        result.append((face, sign, domain, uknots, vknots, edges))
    if total != topology['edgeOccurrences']:
        raise Unresolved('integration boundary occurrence inventory differs from topology')
    if completion is not None:
        from .mass_boundary_native import finish
        finish(completion, budget)
        # Lens descriptors need the whole executable chain, so their separate
        # continuation/sample envelope is admitted only AFTER finish(). Keep
        # measured integrationDomain, knots and every numeric boundary piece.
        mapped=0
        for index,(face,_,domain,_,_,_)in enumerate(result):
            lenses=[lens for lens in completion['conicLensDescriptors']if lens.face is face]
            if not lenses:continue
            mapped+=len(lenses);proxy_domain=list(surface_domains[index]['lineEndpointJumpPreparation']['envelope'])
            for lens in lenses:
                bounds=lens.envelope()
                for axis,name in ((0,'U'),(1,'V')):
                    if getattr(face.Surface,'is'+name+'Periodic')():
                        period=finite(getattr(face.Surface,name+'Period')())
                        if period<=0 or bounds[2*axis+1]-bounds[2*axis]>=period/2:
                            raise Unresolved('conic lens support changes the original periodic chart side')
                proxy_domain=[min(proxy_domain[0],bounds[0]),max(proxy_domain[1],bounds[1]),
                              min(proxy_domain[2],bounds[2]),max(proxy_domain[3],bounds[3])]
                for u,v in lens.samples():
                    proxy_domain=[min(proxy_domain[0],u),max(proxy_domain[1],u),min(proxy_domain[2],v),max(proxy_domain[3],v)]
            puk,pvk,pinfo=_surface(face.Surface,proxy_domain,budget)
            for lens in lenses:
                bounds=lens.envelope()
                if any(bounds[2*axis]<knot<bounds[2*axis+1]for axis,knots in ((0,puk),(1,pvk))for knot in knots):
                    raise Unresolved('conic lens support crosses an unresolved surface knot')
            surface_domains[index]['conicLensPreparation']={'envelope':proxy_domain,
                'uKnots':puk,'vKnots':pvk,'descriptors':[lens.record()for lens in lenses],
                'samplePoints':[list(point)for lens in lenses for point in lens.samples()],
                'basis':pinfo,'scope':'separate diagnostic continuation; measured domain and partitions unchanged'}
        if mapped!=len(completion['conicLensDescriptors']):raise Unresolved('conic lens face identity does not match integration inventory')
        total += completion['connectors'] + len(completion['occurrences']) + len(completion['corners'])
    budget.check()
    box = shape.BoundBox
    origin = [(a+b)/2 for a, b in ((box.XMin, box.XMax),
                                  (box.YMin, box.YMax), (box.ZMin, box.ZMax))]
    reference = abs(finite(shape.Volume))
    area = finite(shape.Area)
    centre = _numbers(list(shape.Solids[0].CenterOfMass))
    if not reference > 0 or not area > 0:
        raise Unresolved('nonpositive conditioning reference')
    budget.check()
    limits = [max(1e-6, abs(area)*1e-7), max(1e-6, reference*1e-7),
              *[max(1e-6, abs(x)*1e-7) for x in centre]]
    return {'faces': result, 'edges': total, 'origin': origin,
            'referenceVolume': reference, 'limits': limits,
            'axisLevers': [box.XLength/2, box.YLength/2, box.ZLength/2],
            'topology': topology,
            'curveChecks': diagnostics, 'surfaceDomains': surface_domains,
            **({'completionState': completion} if completion is not None else {})}


def _uv_field(curve, parameter):
    (u, _), (_, dv) = curve.evaluate(parameter)
    return [u*dv]


def _level(prepared, budget, *, fine):
    beginning = budget.calls
    reference, origin = prepared['referenceVolume'], prepared['origin']
    # Conditioning references are not authoritative measurements. Reserve half
    # their prospective budget; the unchanged postcheck uses actual metrics.
    divisor = 2000 if fine else 200
    targets = [value/divisor for value in prepared['limits']]
    # The moment field is divided by the conditioning reference, while the
    # resulting centre divides by measured volume. Allocate half the centre
    # target to each first-order contribution: moment error and volume error
    # multiplied by its maximum lever from the centred integration origin.
    # This is conditioning bookkeeping, not an integration error certificate.
    targets[2:] = [value/2 for value in targets[2:]]
    for target, lever in zip(targets[2:], prepared['axisLevers']):
        lever = finite(lever)
        if lever > 0:
            targets[1] = min(targets[1], finite(target*reference/lever))
    rows, facts, line_jump_totals, line_jump_records = [], [], [], []
    lens_totals,lens_records=[],[]
    for index, (face, sign, domain, uknots, vknots, edges) in enumerate(prepared['faces']):
        u0, u1, v0, v1 = domain
        kind = type(face.Surface).__name__
        planar = kind == 'Plane'
        # These exact native classes obey S(U,V)=C(U)+V*A, with constant A.
        # Their physical normal and volume density are independent of V;
        # moment densities are affine in V. The alternate Green primitive
        # -integral_boundary (integral_[V0,V] field(U,s) ds) dU therefore has
        # an exact midpoint strip. Preserve original UV, normal and face sign.
        # No sampled fit, axis retry, or approximate surface conversion occurs.
        linear_v = kind in ('Cylinder', 'SurfaceOfExtrusion')
        revolution = kind == 'SurfaceOfRevolution'
        from .mass_ruled_native import admit as ruled_admit
        ruled_u = ruled_admit(face.Surface)
        outer_span = u1-u0 if linear_v else v1-v0
        inner_target = [t/(16*prepared['edges']*max(1, abs(outer_span))) for t in targets]
        outer_target = [t/(4*prepared['edges']) for t in targets]
        field_calls = 0

        def field(u, v):
            nonlocal field_calls
            field_calls += 1
            if budget.calls-beginning > 2_000_000:
                raise EvaluationLimit('one measurement evaluation cap exhausted')
            point = face.valueAt(u, v)
            du, dv = face.derivative1At(u, v)
            normal = du.cross(dv)
            relative = [point.x-origin[0], point.y-origin[1], point.z-origin[2]]
            dot = math.fsum(a*b for a, b in zip(relative, (normal.x, normal.y, normal.z)))
            return [normal.Length, sign*dot/3,
                    *[sign*x*dot/(4*reference) for x in relative]]

        def diagnostic_primitive(u,v,proxy_uknots):
            """The chart one-form, used ONLY by the endpoint-jump proxy.

            Keep boundary() below unchanged: reassociating its floating
            products would change the measured values on existing recipes.
            """
            nonlocal field_calls
            budget.check()
            if (v==v0 if linear_v else u==u0):return [0.]*5
            if linear_v:
                budget.tick()
                return [finite((v-v0)*x)for x in field(u,v0+(v-v0)/2)]
            if revolution:
                from .mass_revolution_native import strip
                budget.tick();field_calls+=1
                if budget.calls-beginning>2_000_000:
                    raise EvaluationLimit('one measurement evaluation cap exhausted')
                return strip(face,u0,u,v,origin,reference,sign)
            if ruled_u:
                from .mass_ruled_native import strip as ruled_strip
                values=ruled_strip(face,u0,u,v,origin,reference,sign,budget,beginning,inner_target)
                field_calls+=3
                return values
            if planar:
                budget.tick()
                return [finite((u-u0)*x)for x in field(u0+(u-u0)/2,v)]
            inner=partitions(min(u0,u),max(u0,u),proxy_uknots)
            pieces=[integrate(lambda s:field(s,v),a,b,
                              [x/(len(inner)-1)for x in inner_target],budget=budget)
                    for a,b in zip(inner,inner[1:])]
            return [finite((1 if u>u0 else -1)*math.fsum(p[i]for p in pieces))
                    for i in range(5)]

        terms = []
        for evaluator, direction, original_spans in edges:
            spans = partitions(evaluator.start, evaluator.end, original_spans,
                               third_cut=fine)

            def boundary(t):
                nonlocal field_calls
                if budget.calls-beginning > 2_000_000:
                    raise EvaluationLimit('one measurement evaluation cap exhausted')
                (u, v), (du, dv) = evaluator.evaluate(t)
                if not domain[0] <= u <= domain[1] or not domain[2] <= v <= domain[3]:
                    raise Unresolved('pcurve evaluation exceeds the preflight integration envelope')
                differential = -du if linear_v else dv
                if differential == 0:
                    return [0.]*5
                if (v == v0 if linear_v else u == u0):
                    return [0.]*5
                if linear_v:
                    budget.tick()
                    values = field(u, v0+(v-v0)/2)
                    return [finite(direction*differential*(v-v0)*value) for value in values]
                if revolution:
                    from .mass_revolution_native import strip
                    budget.tick()
                    if budget.calls-beginning > 2_000_000:
                        raise EvaluationLimit('one measurement evaluation cap exhausted')
                    field_calls += 1
                    values=strip(face,u0,u,v,origin,reference,sign)
                    return [finite(direction*dv*value) for value in values]
                if ruled_u:
                    from .mass_ruled_native import strip as ruled_strip
                    values = ruled_strip(face, u0, u, v, origin, reference,
                                         sign, budget, beginning, inner_target)
                    field_calls += 3
                    return [finite(direction*dv*value) for value in values]
                if planar:
                    # Exact-class selection, never a fit or a retry after an
                    # adaptive failure: Plane has constant area/volume fields
                    # and affine first-moment fields in its native U,V.
                    budget.tick()
                    values = field(u0+(u-u0)/2, v)
                    return [finite(direction*dv*(u-u0)*value) for value in values]
                inner = partitions(min(u0, u), max(u0, u), uknots)
                pieces = [integrate(lambda s: field(s, v), a, b,
                                    [x/(len(inner)-1) for x in inner_target], budget=budget)
                          for a, b in zip(inner, inner[1:])]
                return [direction*dv*(1 if u > u0 else -1)*math.fsum(p[i] for p in pieces)
                        for i in range(5)]

            for a, b in zip(spans, spans[1:]):
                if planar and isinstance(evaluator, LineCurve):
                    # Original line U(t),V(t) are affine and dV/dt constant.
                    # After the affine strip primitive, each field is degree
                    # <=2 in t. Two-point Gauss is exact through degree3 in
                    # real arithmetic; floating accuracy remains empirical.
                    half = (b-a)/2
                    midpoint = a+half
                    samples = []
                    for t in (midpoint-half/math.sqrt(3), midpoint+half/math.sqrt(3)):
                        budget.tick()
                        samples.append(boundary(t))
                    terms.append([finite(half*math.fsum(row[i] for row in samples))
                                  for i in range(5)])
                else:
                    terms.append(integrate(boundary, a, b,
                                           [x/(len(spans)-1) for x in outer_target], budget=budget))
        if 'completionState' in prepared:
            from .line_endpoint_jumps import one_form_proxy
            jump_preparation=prepared['surfaceDomains'][index]['lineEndpointJumpPreparation']
            primitive_cache={}
            def cached_primitive(point):
                key=tuple(point)
                if key not in primitive_cache:
                    primitive_cache[key]=diagnostic_primitive(*key,jump_preparation['uKnots'])
                return primitive_cache[key]
            for jump in jump_preparation['jumps']:
                proxy=one_form_proxy(jump,cached_primitive,axis='V' if linear_v else 'U',
                                     envelope=jump_preparation['envelope'],budget=budget)
                line_jump_totals.append(proxy['totals'])
                line_jump_records.append({'face':index,'gaugeU0V0':[u0,v0],
                    'origin':list(origin),'normalisedMomentReferenceVolume':reference,
                    'jump':jump,**proxy})
            from .conic_lens import density_proxy
            for lens in prepared['completionState'].get('conicLensDescriptors',()):
                if lens.face is not face:continue
                proxy=density_proxy(lens,field,prepared['surfaceDomains'][index]['conicLensPreparation']['envelope'],budget)
                lens_totals.append(proxy['totals']);lens_records.append({'face':index,
                    'origin':list(origin),'normalisedMomentReferenceVolume':reference,**proxy})
        row = [math.fsum(term[i] for term in terms) for i in range(5)]
        rows.append(row)
        facts.append({'surface': kind, 'orientation': sign,
                      'edges': len(edges), 'uKnots': uknots, 'vKnots': vknots,
                      'primitiveAxis': 'V' if linear_v else 'U',
                      'outerDifferential': '-dU' if linear_v else 'dV',
                      'innerRule': ('native-linear-V-midpoint' if linear_v else
                                    'native-revolution-angular-Fourier2' if revolution else
                                    'native-coefficient-ruled-U' if ruled_u else
                                    'plane-affine-midpoint' if planar else 'adaptive-G7K15'),
                      'fieldDegrees': ([0,0,1,1,1] if linear_v or planar else None),
                      'angularHarmonics': [0,1,2,2,2] if revolution else None,
                      'ruledUFields': ({'basis':'degree1-two-clamped-poles-exact-equal-U-weights',
                                        'area':'norm-of-affine-normal',
                                        'volumeDegree':1,'momentDegree':2,
                                        'normalAnchors':'full-original-U-knot-span'}
                                       if ruled_u else None),
                      'fieldEvaluations': field_calls,
                      'lineBoundaryRule': ('plane-original-line-G2' if planar
                                           else 'adaptive-G7K15'),
                      'basis': prepared['surfaceDomains'][index]})
    try:
        jump_totals=[finite(math.fsum(row[i]for row in line_jump_totals))for i in range(5)]
    except OverflowError as error:
        raise Unresolved('line endpoint chart proxy sum overflowed')from error
    try:conic_totals=[finite(math.fsum(row[i]for row in lens_totals))for i in range(5)]
    except OverflowError as error:raise Unresolved('conic lens density proxy sum overflowed')from error
    values = [finite(math.fsum(row[i] for row in rows)) for i in range(5)]
    if budget.calls-beginning > 2_000_000:
        raise EvaluationLimit('one measurement evaluation cap exhausted')
    if values[0] <= 0 or values[1] == 0:
        raise Unresolved('nonpositive area or zero signed volume')
    centre = [finite(origin[i]+values[i+2]*reference/values[1]) for i in range(3)]
    centre_targets = [finite((targets[i+2]*reference
                              + abs(centre[i]-origin[i])*targets[1])
                             / abs(values[1])) for i in range(3)]
    return {'area': values[0], 'signedVolume': values[1], 'centre': centre,
            'targets': targets, 'propagatedCentreTargets': centre_targets,
            'evaluations': budget.calls-beginning,
            'partition': ('boundary-known-spans-one-third' if fine
                          else 'boundary-known-spans'),
            'innerPartition': 'native-linear-V-or-revolution-angular-or-known-U-spans-or-plane-affine', 'faces': facts,
            **({'lineEndpointJumpProxy':{
                'method':'sampled-chart-green-one-form-simpson3/1',
                'scope':'LineCurve law-to-token chart jumps only; excludes 3D skin/rung gaps',
                'bound':False,'records':line_jump_records,
                'totals':jump_totals},'conicLensProxy':{
                'method':'sampled-conic-lens-density-grid3/1','bound':False,
                'records':lens_records,'totals':conic_totals,
                'scope':'declared auxiliary winding differences only; virtual joins and 3D rungs remain unmodelled'}}
               if 'completionState' in prepared else {})}


def measure_levels(shape, *, budget=None, boundary_method=None):
    budget = budget if budget is not None else Budget()
    prepared = (prepare(shape, budget) if boundary_method is None
                else prepare(shape, budget, boundary_method=boundary_method))
    coarse = _level(prepared, budget, fine=False)
    completion = prepared.get('completionState')
    if completion is not None:
        from .mass_completion_native import complete_level
        from .mass_boundary_admission import coarse_winding
        coarse = complete_level(prepared, completion, budget, coarse, fine=False)
        beginning = budget.calls
        mesh = coarse_winding(shape, coarse['signedVolume'], coarse['area'], budget)
        coarse['evaluations'] += budget.calls-beginning
        if coarse['evaluations'] > 2_000_000:
            raise EvaluationLimit('one completed measurement evaluation cap exhausted')
    fine = _level(prepared, budget, fine=True)
    if completion is not None:
        fine = complete_level(prepared, completion, budget, fine, fine=True)
    if coarse['signedVolume'] <= 0 or fine['signedVolume'] <= 0:
        raise Unresolved('public instrument requires positive signed volume')
    a = [coarse['area'], coarse['signedVolume'], *coarse['centre']]
    b = [fine['area'], fine['signedVolume'], *fine['centre']]
    limits = [max(1e-6, abs(b[0])*1e-7), max(1e-6, abs(b[1])*1e-7),
              *[max(1e-6, abs(x)*1e-7) for x in fine['centre']]]
    differences = [abs(x-y) for x, y in zip(a, b)]
    if any(delta > limit/10 for delta, limit in zip(differences, limits)):
        raise Unresolved('independent partition resolution control differs')
    output_targets = [*fine['targets'][:2], *fine['propagatedCentreTargets']]
    if any(target > limit/1000*(1+1e-12)
           for target, limit in zip(output_targets, limits)):
        raise Unresolved('conditioning references under-budget actual metrics')
    budget.check()
    return {'method': ('gauss-green-development/1' if completion is None
                       else 'gauss-green-empirical-completed-boundary/1'),
            'coarse': coarse, 'fine': fine,
            'origin': prepared['origin'], 'limits': limits,
            'interLevelDifference': differences, 'evaluations': budget.calls,
            'topology': prepared['topology'],
            'curveChecks': prepared['curveChecks'], 'certifiedErrorBound': False,
            **({'boundaryAdmission': completion['admission'], 'coarseWinding': mesh}
               if completion is not None else {})}
