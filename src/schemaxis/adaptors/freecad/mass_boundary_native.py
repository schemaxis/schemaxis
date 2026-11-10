"""Explicit finite boundary completion for plan-selected empirical measurement.

Keep every original pcurve, interval, occurrence and lifted chart. Straight UV
connectors, paired-face ribbons and native-vertex caps define a formal
float-endpoint chain. Its symbolic incidence closes; ideal coefficient-law
endpoint gaps are not integrated. This is an empirical model, not a certificate
of geometric closure. Numerical integration and the ledger use the same pieces.
"""
from dataclasses import dataclass
import math

from .gauss_green import LineCurve, Unresolved, uv_area_integral


@dataclass(frozen=True)
class PairPiece:
    first: int
    second: int
    coefficient: int
    start_cap: int
    end_cap: int


@dataclass(frozen=True)
class PolePiece:
    occurrence: int
    vertex: object
    coefficient: int


@dataclass(frozen=True)
class CornerPiece:
    face: object
    vertex: object
    first: int
    first_parameter: float
    before: tuple
    second: int
    second_parameter: float
    after: tuple
    chart_coefficient: int
    patch_coefficient: int
    cap_coefficient: int


def new_state():
    return {'occurrences': [], 'corners': [], 'pairs': [], 'poles': [],
            'connectors': 0, 'uvGapMaximum': 0., 'physicalEndpointMaximum': 0.,
            'wireRules': [], 'lineEndpointTokens': {}}


def add_wire(state, face, sign, ordered, endpoints, edges, uv_areas, budget):
    from .mass_native import _surface
    rows = edges[-len(ordered):]
    offset = len(state['occurrences'])
    vertices = [(edge.firstVertex(True), edge.lastVertex(True)) for edge in ordered]
    for edge, (curve, direction, _) in zip(ordered, rows):
        if edge.Degenerated:
            first, last = edge.firstVertex(False), edge.lastVertex(False)
            if first.isNull() or last.isNull() or not first.isSame(last):
                raise Unresolved('collapsed boundary requires one native endpoint vertex')
        elif tuple(edge.ParameterRange) != (curve.start, curve.end):
            raise Unresolved('native edge and pcurve parameter intervals differ')
        state['occurrences'].append((face, sign, edge, curve, direction))
        if isinstance(curve,LineCurve):
            state['lineEndpointTokens'][id(curve)]=tuple(curve.evaluate(curve.end)[0])
        for parameter in (curve.start, curve.end):
            uv = curve.evaluate(parameter)[0]
            budget.tick()
            point = face.valueAt(*uv)
            budget.tick()
            native = edge.firstVertex(False).Point if edge.Degenerated else edge.valueAt(parameter)
            state['physicalEndpointMaximum'] = max(state['physicalEndpointMaximum'], (point-native).Length)
    remaining, order = list(range(1, len(ordered))), [0]
    while remaining:
        current = order[-1]
        matches = []
        for index in remaining:
            budget.tick()
            if vertices[current][1].isSame(vertices[index][0]):
                matches.append(index)
        if len(matches) == 1:
            chosen, rule = matches[0], 'unique-native-vertex'
        else:
            candidates = [index for index in matches
                          if math.dist(endpoints[current][1], endpoints[index][0]) <= 1e-9]
            if len(candidates) != 1:
                raise Unresolved('boundary adjacency is not unique in native topology/original lifted UV')
            chosen, rule = candidates[0], 'unique-existing-UV-seam-chain'
        remaining.remove(chosen)
        order.append(chosen)
        state['wireRules'].append(rule)
    budget.tick()
    if not vertices[order[-1]][1].isSame(vertices[order[0]][0]):
        raise Unresolved('native boundary topology loop is not closed')
    for first, second in zip(order, order[1:]+order[:1]):
        before, after = tuple(endpoints[first][1]), tuple(endpoints[second][0])
        state['uvGapMaximum'] = max(state['uvGapMaximum'], math.dist(before, after))
        ci, di, _ = rows[first]
        cj, dj, _ = rows[second]
        ti = ci.end if di > 0 else ci.start
        tj = cj.start if dj > 0 else cj.end
        state['corners'].append(CornerPiece(face, vertices[first][1], offset+first, ti, before,
                                          offset+second, tj, after, sign, -sign, sign))
        if before == after:
            continue
        connector = LineCurve(0., 1., before, after)
        # The ledger/cap endpoint is the declared next trace endpoint, which
        # need not equal fl(before + fl(after-before)). Do not substitute the
        # connector evaluator's end for this actual token in its diagnostic.
        state['lineEndpointTokens'][id(connector)]=after
        domain = list(face.ParameterRange)
        for uv in (before, after):
            domain = [min(domain[0], uv[0]), max(domain[1], uv[0]),
                      min(domain[2], uv[1]), max(domain[3], uv[1])]
        uk, vk, _ = _surface(face.Surface, domain, budget)
        surface = face.Surface
        for axis, name in ((0, 'U'), (1, 'V')):
            if getattr(surface, 'is'+name+'Periodic')():
                period = getattr(surface, name+'Period')()
                if not math.isfinite(period) or period <= 0 or abs(after[axis]-before[axis]) >= period/2:
                    raise Unresolved('completion connector changes the original periodic chart side')
        # Analytic periodic surfaces have no B-spline knot inventory. Their
        # original lifted side is protected by the half-period rule above.
        for axis, knots in ((0, uk), (1, vk)):
            if any(min(before[axis], after[axis]) < knot < max(before[axis], after[axis]) for knot in knots):
                raise Unresolved('completion connector crosses an original surface knot')
        edges.append((connector, 1, [0., 1.]))
        uv_areas.append(uv_area_integral(connector, 0., 1., budget=budget))
        state['connectors'] += 1


def finish(state, budget):
    groups = {}
    for index, (_, sign, edge, _, direction) in enumerate(state['occurrences']):
        sigma = sign*direction
        if edge.Degenerated:
            state['poles'].append(PolePiece(index, edge.firstVertex(False), -sigma))
            continue
        bucket = groups.setdefault(edge.hashCode(), [])
        found = None
        for group in bucket:
            budget.tick()
            if edge.isSame(state['occurrences'][group[0]][2]):
                found = group
                break
        if found is None:
            bucket.append([index])
        else:
            found.append(index)
    for bucket in groups.values():
        for group in bucket:
            if len(group) != 2:
                raise Unresolved('completion native edge does not have exactly two occurrences')
            first, second = group
            one, two = state['occurrences'][first], state['occurrences'][second]
            sigma = one[1]*one[4]
            if sigma != -two[1]*two[4]:
                raise Unresolved('completion paired native edge orientations differ')
            state['pairs'].append(PairPiece(first, second, -sigma, -sigma, sigma))
    for key in ('occurrences', 'pairs', 'poles', 'corners', 'wireRules'):
        state[key] = tuple(state[key])
    state.pop('lineEndpointTokens',None)
    from .mass_boundary_admission import incidence_and_uv_admission
    state['admission'] = incidence_and_uv_admission(state, budget)
    return state
