# Copyright (C) 2026 David L F Gaden
"""Independent linear-tetrahedron measurements from retained mesh coordinates.

Mean ratio is 12*(3*V)**(2/3)/sum(edge_length**2): one for a regular
tetrahedron, tending to zero for a degenerate one. It is not a solver error.
"""
import math
from .mesh import check, determinant


def tetrahedron(points):
    volume = determinant(*points)
    check(math.isfinite(volume) and volume > 0, 'quality requires positive tetrahedra')
    squared = [math.fsum((points[i][k]-points[j][k])**2 for k in range(3))
               for i in range(4) for j in range(i+1, 4)]
    denominator = math.fsum(squared)
    check(math.isfinite(denominator) and min(squared) > 0, 'invalid tetrahedron edges')
    ratio = 12*(3*volume)**(2/3)/denominator
    check(math.isfinite(ratio) and 0 < ratio <= 1+1e-12, 'invalid mean-ratio quality')
    return {'meanRatio': min(1.0, ratio), 'minimumEdgeLength': math.sqrt(min(squared)),
            'maximumEdgeLength': math.sqrt(max(squared)), 'volume': volume,
            'centroid': [math.fsum(p[k] for p in points)/4 for k in range(3)]}


def cells(data):
    for dimension, _, vertices in data['cells']:
        if dimension == 3:
            yield tetrahedron([data['nodes'][node] for node in vertices])


def distribution(values):
    ordered = sorted(values)
    check(bool(ordered) and all(math.isfinite(v) for v in ordered), 'empty or invalid quality distribution')
    def percentile(fraction):
        position = (len(ordered)-1)*fraction
        left = math.floor(position); right = math.ceil(position)
        return ordered[left]+(ordered[right]-ordered[left])*(position-left)
    return {'minimum': ordered[0], 'p05': percentile(.05), 'median': percentile(.5),
            'p95': percentile(.95), 'maximum': ordered[-1],
            'mean': math.fsum(ordered)/len(ordered)}


def assess(data):
    measured = list(cells(data))
    check(bool(measured), 'quality assessment needs tetrahedra')
    ratios = [cell['meanRatio'] for cell in measured]
    bins = [0]*10
    for value in ratios:
        bins[min(9, int(value*10))] += 1
    worst = sorted(enumerate(measured), key=lambda item: (item[1]['meanRatio'], item[0]))[:20]
    boundaries = {}
    for dimension, tag, vertices in data['cells']:
        if dimension == 2:
            points = [data['nodes'][n] for n in vertices]
            boundaries.setdefault(tag, []).append(max(math.dist(points[i], points[j]) for i,j in ((0,1),(1,2),(2,0))))
    return {'version': 'schemaxis.tetrahedron-quality/1', 'tetrahedra': len(measured),
            'units': {'length': 'mm', 'volume': 'mm^3', 'meanRatio': 'dimensionless'},
            'meanRatio': distribution(ratios),
            'minimumEdgeLength': distribution([c['minimumEdgeLength'] for c in measured]),
            'maximumEdgeLength': distribution([c['maximumEdgeLength'] for c in measured]),
            'volume': distribution([c['volume'] for c in measured]),
            'boundaries': [{'name': data['groups'][2,tag], 'tag': tag, 'triangles': len(values),
                            'maximumEdgeLength': distribution(values)} for tag,values in sorted(boundaries.items())],
            'histogram': {'metric': 'meanRatio', 'edges': [i/10 for i in range(11)],
                          'counts': bins, 'intervals': 'left-closed; final interval includes 1'},
            'diagnostic': {'metric': 'meanRatio', 'below': .2,
                           'count': sum(q < .2 for q in ratios),
                           'meaning': 'diagnostic threshold only; acceptance is declared separately'},
            'worstCells': [{'cellIndex': index, **cell} for index, cell in worst],
            'cellIndexMeaning': 'zero-based tetrahedron order in volume.vtu',
            'scope': 'linear tetrahedral shape and size; no solution-error or convergence claim'}
