"""Independent standard-library oracle and verifier for schemaxis.xarray/1.

Never imports xarray, NumPy or SciPy. The source and the published profile are decoded by the bounded
classic NetCDF reader in cdf.py; means come from exact rational (Fraction) sums cross-checked against
math.fsum.

Tolerance model (stated, not tuned): the native mean of n valid cells may be accumulated sequentially. The
first-order bound on its rounding error is (n + 1) * 2**-53 * A, where A = mean(|x|) is computed exactly. This is
the leading term of the standard sequential-summation bound; the second-order gamma terms (of order n**2 * 2**-106)
are dropped, so it is a first-order bound, not a rigorous worst case, and it is far below the 1e-9 conditioning
limit for every profile of at most 262144 cells. It is scale-aware (it follows the data magnitude) and is the only
allowance the verifier grants. A profile point is refused as ill-conditioned when this bound exceeds 1e-9 * |mean|,
so the allowance can never conceal more than a 1e-9 relative error and cancelling data (including a non-zero-scale
mean of exactly zero) is refused, not published. The reference mean is the nearest binary64 value to the exact rational mean. When the bound
rounds to zero, the published value must equal that rounded reference exactly; some subnormal cases instead
have a representable nonzero bound. For example [5e-324, 0, 0] has a zero bound and must publish the nearest-rounded
mean 0.0, not an invented zero.
No floor is added to the tolerance. Counts and coordinates must match exactly.
"""
import hashlib
import json
import math
import re
import struct
from fractions import Fraction
from itertools import product

from schemaxis.core.faults import Fault, SchemaxisError
from . import cdf

U = Fraction(1, 2**53)
MAX_MAGNITUDE = 1e100
CONDITION = Fraction(1, 10**9)
LIMITS = {**cdf.LIMITS, 'maxProfile': 2048, 'minProfile': 2, 'maxMagnitude': MAX_MAGNITUDE, 'conditionRelativeBound': 1e-9}
ALLOWED = {'coordinate': {'units': 'char', 'long_name': 'char'},
           'variable': {'units': 'char', '_FillValue': 'double', 'long_name': 'char'},
           'global': {'title': 'char'}}
POLICIES = ('skip', 'propagate', 'refuse')
REDUCTION = 'unweighted arithmetic mean over every reduced dimension; missing policy %s; not area or time weighted'
CALENDAR = re.compile(r'\bsince\b', re.I)
HEADER_SUFFIX = ('validCount', 'missingCount')


def raise_fault(code, message, location, recovery=None, **observed):
    raise SchemaxisError(Fault(code, message, location, 'pipeline', observed=observed, recovery=recovery))


def cdf_fault(error):
    raise_fault(error.code, error.message, error.location,
                'use a fixed-dimension, non-record classic NetCDF (CDF-1) file whose structure matches the declaration')


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def digest_doubles(values):
    return hashlib.sha256(struct.pack('>%dd' % len(values), *values)).hexdigest()


def selection_record(p):
    return {'variable': p['variable'], 'coordinates': p['coordinates'], 'retain': p['retain'], 'missing': p['missing']}


# ------------------------------------------------------------------ source binding

def attribute(attrs, name, kind, where, scope):
    entry = attrs.get(name)
    if entry is not None and entry[0] != kind:
        raise_fault('XR_TYPE_UNSUPPORTED', '%s must be a %s attribute' % (name, kind), where)
    return None if entry is None else entry[1]


def check_attributes(attrs, scope, where):
    for name, (kind, _) in attrs.items():
        if name not in ALLOWED[scope]:
            raise_fault('XR_ATTRIBUTE_UNSUPPORTED', 'attribute %s is outside the declared allowlist (%s)'
                        % (name, ', '.join(sorted(ALLOWED[scope]))), where + '.' + name,
                        'remove the attribute upstream; it is refused rather than silently dropped')
        if kind != ALLOWED[scope][name]:
            raise_fault('XR_TYPE_UNSUPPORTED', '%s must be a %s attribute' % (name, ALLOWED[scope][name]), where + '.' + name)


def bind(p, parsed):
    """Validate the declaration against the decoded file and return the selected cube."""
    names = [d['name'] for d in p['coordinates']]
    file_dims = dict(parsed['dims'])
    if set(file_dims) != set(names) or len(file_dims) != len(names):
        raise_fault('XR_DIMENSION_MISMATCH', 'declared dimensions differ from the file dimensions', '$.coordinates',
                    'declare every file dimension by its exact name and no others', declared=sorted(names), file=sorted(file_dims))
    check_attributes(parsed['attrs'], 'global', '$.source.global')
    variables = {v['name']: v for v in parsed['vars']}
    name = p['variable']['name']
    if name not in variables:
        raise_fault('XR_VARIABLE_MISSING', 'variable is absent from the file', '$.variable.name', variables=sorted(variables))
    extra = sorted(set(variables) - set(names) - {name})
    if extra:
        raise_fault('XR_EXTRA_VARIABLE', 'the file holds variables that would be silently dropped', '$.source',
                    'keep only the selected variable and its coordinate variables', variables=extra)
    data = variables[name]
    if data['dims'] != names:
        raise_fault('XR_DIMENSION_ORDER', 'declared dimension order differs from the storage order of the variable',
                    '$.coordinates', 'declare the dimensions in the exact storage order of the variable (slowest first)',
                    declared=names, storage=data['dims'])
    if data['type'] != 'double':
        raise_fault('XR_TYPE_UNSUPPORTED', 'the data variable must be double precision', '$.variable.name')
    check_attributes(data['attrs'], 'variable', '$.source.' + name)
    unit = attribute(data['attrs'], 'units', 'char', '$.source.' + name + '.units', 'variable')
    check_unit(unit, p['variable']['unit'], '$.variable.unit', name)
    fill = attribute(data['attrs'], '_FillValue', 'double', '$.source.' + name + '._FillValue', 'variable')
    if fill is None or fill != p['missing']['value']:
        raise_fault('XR_FILL_MISMATCH', 'the variable _FillValue must equal the declared missing sentinel', '$.missing.value',
                    'declare the exact _FillValue stored in the file', declared=p['missing']['value'], file=fill)
    axes = []
    for i, d in enumerate(p['coordinates']):
        coordinate = variables.get(d['name'])
        at = '$.coordinates[%d]' % i
        if coordinate is None or coordinate['dims'] != [d['name']] or coordinate['type'] != 'double':
            raise_fault('XR_COORDINATE_MISSING', 'each dimension needs a double coordinate variable of the same name', at + '.name')
        check_attributes(coordinate['attrs'], 'coordinate', '$.source.' + d['name'])
        check_unit(attribute(coordinate['attrs'], 'units', 'char', '$.source.' + d['name'] + '.units', 'coordinate'),
                   d['unit'], at + '.unit', d['name'])
        values = coordinate['values']
        for j, value in enumerate(values):
            if not math.isfinite(value) or abs(value) > MAX_MAGNITUDE:
                raise_fault('XR_COORDINATE_RANGE', 'coordinates are finite with magnitude at most 1e100', at, index=j)
            if j and not value > values[j - 1]:
                raise_fault('XR_COORDINATE_ORDER', 'coordinates must increase strictly (no duplicates, no reversal)', at,
                            'sort or deduplicate the axis upstream; reversed axes are not interpreted', index=j)
        axes.append({'name': d['name'], 'unit': d['unit'], 'values': values, 'length': len(values),
                     'long_name': attribute(coordinate['attrs'], 'long_name', 'char', at, 'coordinate'),
                     'digest': digest_doubles(values)})
        rng = d.get('range')
        if rng is None:
            lo, hi = 0, len(values)
        else:
            if rng['minimum'] < values[0] or rng['maximum'] > values[-1]:
                raise_fault('XR_RANGE_OUT_OF_BOUNDS', 'the range extends beyond the axis extent', at + '.range',
                            'select within the stored coordinate extent', extent=[values[0], values[-1]])
            lo = next((j for j, v in enumerate(values) if v >= rng['minimum']), len(values))
            hi = sum(1 for v in values if v <= rng['maximum'])
            if hi <= lo:
                raise_fault('XR_SELECTION_EMPTY', 'no coordinate lies inside the inclusive range', at + '.range',
                            'widen the range to include at least one stored coordinate')
        axes[-1].update(start=lo, stop=hi)
        if d['name'] == p['retain'] and hi - lo > LIMITS['maxProfile']:
            raise_fault('XR_RESOURCE_LIMIT', 'the selected retained axis exceeds the %d-point profile limit' % LIMITS['maxProfile'],
                        '$.retain', 'narrow the range of the retained dimension; the source axis itself may be longer',
                        selected=hi - lo, maximum=LIMITS['maxProfile'])
    cells = 1
    for a in axes:
        cells *= a['length']
    if cells != len(data['values']):
        raise_fault('XR_CDF_MALFORMED', 'variable size differs from its dimensions', '$.source')
    sentinel = p['missing']['value']
    for j, value in enumerate(data['values']):
        if value != sentinel and (not math.isfinite(value) or abs(value) > MAX_MAGNITUDE):
            raise_fault('XR_NONFINITE_VALUE' if not math.isfinite(value) else 'XR_VALUE_RANGE',
                        'data values are finite with magnitude at most 1e100 or equal the declared sentinel', '$.source.' + name,
                        'replace NaN/Inf by the declared missing sentinel upstream', flatIndex=j)
    return {'axes': axes, 'values': data['values'], 'long_name': attribute(data['attrs'], 'long_name', 'char', '$.source', 'variable'),
            'title': attribute(parsed['attrs'], 'title', 'char', '$.source', 'global'), 'dataDigest': digest_doubles(data['values'])}


def check_unit(found, declared, location, name):
    if found is None:
        raise_fault('XR_UNITS_MISSING', 'the file declares no units attribute for ' + name, location,
                    'add the units attribute upstream; units are asserted, never assumed')
    if CALENDAR.search(found):
        raise_fault('XR_UNITS_CALENDAR', 'calendar/epoch units are not interpreted by this adaptor', location,
                    'use plain elapsed units such as h or s', file=found)
    if found != declared:
        raise_fault('XR_UNITS_MISMATCH', 'the file units differ from the declared units; no conversion is applied', location,
                    'declare the exact stored unit string', declared=declared, file=found)


# ------------------------------------------------------------------ reduction

def reduce_profile(p, cube):
    """Exact per-point reduction. Raises the located policy faults; returns the expected profile."""
    axes = cube['axes']
    names = [a['name'] for a in axes]
    retain = names.index(p['retain'])
    strides = []
    stride = 1
    for a in reversed(axes):
        strides.insert(0, stride)
        stride *= a['length']
    sentinel, policy = p['missing']['value'], p['missing']['policy']
    ranges = [range(a['start'], a['stop']) for a in axes]
    points = []
    for i in ranges[retain]:
        inner = [r if k != retain else [i] for k, r in enumerate(ranges)]
        cells = [cube['values'][sum(j * s for j, s in zip(idx, strides))] for idx in product(*inner)]
        valid = [x for x in cells if x != sentinel]
        points.append({'index': i, 'coordinate': axes[retain]['values'][i], 'cells': len(cells),
                       'valid': len(valid), 'missing': len(cells) - len(valid), 'cellsValues': valid})
    at = '$.missing'
    for point in points:
        where = '%s.%s=%r' % ('$.retain', p['retain'], point['coordinate'])
        if policy == 'refuse' and point['missing']:
            raise_fault('XR_MISSING_VALUES', 'a selected cell equals the missing sentinel and the policy is refuse', where,
                        'choose skip or propagate, or narrow the range', missing=point['missing'], cells=point['cells'])
        if policy == 'skip' and point['valid'] < p['missing']['minimumValid']:
            raise_fault('XR_INSUFFICIENT_VALID', 'fewer valid cells than minimumValid; no value is invented', where,
                        'lower minimumValid, widen the selection or repair the data', valid=point['valid'],
                        minimumValid=p['missing']['minimumValid'])
    result = []
    for point in points:
        valid = point.pop('cellsValues')
        if policy == 'propagate' and point['missing'] or not valid:
            result.append({**point, 'mean': None, 'tolerance': None})
            continue
        exact = sum((Fraction(x) for x in valid), Fraction(0)) / len(valid)
        scale = sum((abs(Fraction(x)) for x in valid), Fraction(0)) / len(valid)
        bound = (len(valid) + 1) * U * scale
        if bound > CONDITION * abs(exact):
            raise_fault('XR_ILL_CONDITIONED', 'the terms cancel too strongly for the mean to be verified within 1e-9 relative',
                        '$.retain.%s=%r' % (p['retain'], point['coordinate']),
                        'select terms of one sign or a narrower range; the mean is refused rather than published',
                        exactMean=float(exact), meanMagnitude=float(scale))
        mean = float(exact)
        if abs(math.fsum(valid) / len(valid) - mean) > 2 * float(U) * abs(mean):      # independent cross-check
            raise_fault('XR_VERIFICATION_INCONSISTENT', 'exact and fsum oracles disagree', '$.oracle')
        if abs(mean - sentinel) <= float(bound):
            raise_fault('XR_SENTINEL_COLLISION', 'a published mean would be indistinguishable from the missing sentinel', at + '.value',
                        'declare a sentinel outside the data range')
        result.append({**point, 'mean': mean, 'tolerance': float(bound)})
    published = [r for r in result if r['mean'] is not None]
    if not published:
        raise_fault('XR_PROFILE_ALL_MISSING', 'every profile point is missing; nothing is published', '$.missing',
                    'use skip with a valid-count threshold, or select cells that contain data')
    if len(published) < LIMITS['minProfile']:
        raise_fault('XR_PROFILE_TOO_SHORT', 'a profile needs at least 2 published points', '$.retain',
                    'widen the selection along the retained dimension', points=len(published))
    return result


def reduction_text(p):
    """Fixed-length-bounded attribute text; the reduced dimension names are published in the summary `reduced` field."""
    return REDUCTION % p['missing']['policy']


def expectations(p, cube, points):
    reduced = [a['name'] for a in cube['axes'] if a['name'] != p['retain']]
    retained = next(a for a in cube['axes'] if a['name'] == p['retain'])
    attrs = {'schemaxis_source_sha256': cube['sourceSha256'], 'schemaxis_selection_sha256': canonical(selection_record(p)),
             'schemaxis_reduction': reduction_text(p)}
    return {'attrs': attrs, 'reduced': reduced, 'retained': retained}


def number(x):
    return repr(float(x))


def render_csv(p, points):
    name, variable = p['retain'], p['variable']['name']
    lines = [','.join([name, variable, *HEADER_SUFFIX])]
    for r in points:
        lines.append(','.join([number(r['coordinate']), '' if r['mean'] is None else number(r['mean']),
                               str(r['valid']), str(r['missing'])]))
    return ('\n'.join(lines) + '\n').encode('ascii')


# ------------------------------------------------------------------ verifying the published profile

def structure_fault(message, where, **observed):
    raise_fault('VERIFICATION_FAILED', message, where, **observed)


def verify_profile(p, cube, points, nc_bytes, csv_bytes):
    """Decode the native profile with the independent reader and check every coordinate, value, unit and count."""
    try:
        parsed = cdf.parse(nc_bytes)
    except cdf.CdfError as error:
        structure_fault('published profile is not valid bounded classic NetCDF: ' + error.message, error.location)
    expect = expectations(p, cube, points)
    retain, variable = p['retain'], p['variable']['name']
    if parsed['dims'] != [(retain, len(points))]:
        structure_fault('published dimensions differ', 'profile.nc', observed=parsed['dims'])
    got = {v['name']: v for v in parsed['vars']}
    if len(parsed['vars']) != 4 or set(got) != {retain, variable, *HEADER_SUFFIX}:
        structure_fault('published variables differ', 'profile.nc', variables=sorted(got))
    for v in parsed['vars']:
        if v['dims'] != [retain]:
            structure_fault('published variable has different dimensions', v['name'])
    axis = next(a for a in cube['axes'] if a['name'] == retain)
    unit = {retain: axis['unit'], variable: p['variable']['unit'], 'validCount': 'count', 'missingCount': 'count'}
    sentinel = p['missing']['value']
    for name, v in got.items():
        attrs = dict(v['attrs'])
        want = {'units': ('char', unit[name])}
        if name == retain and axis['long_name']:
            want['long_name'] = ('char', axis['long_name'])
        if name == variable:
            want['_FillValue'] = ('double', sentinel)
            if cube['long_name']:
                want['long_name'] = ('char', cube['long_name'])
        if attrs != want:
            structure_fault('published attributes differ for ' + name, 'profile.nc', published=repr(attrs), expected=repr(want))
    want_global = {k: ('char', v) for k, v in expect['attrs'].items()}
    if cube['title'] is not None:
        want_global['title'] = ('char', cube['title'])
    if parsed['attrs'] != want_global:
        structure_fault('published global attributes differ', 'profile.nc', published=repr(parsed['attrs']))
    if got[retain]['type'] != 'double' or got[retain]['values'] != [r['coordinate'] for r in points]:
        structure_fault('published coordinates differ from the selected source coordinates', retain)
    if got['validCount']['values'] != [r['valid'] for r in points] or got['missingCount']['values'] != [r['missing'] for r in points]:
        structure_fault('published counts differ from the independent counts', 'validCount')
    published, worst = [], 0.0
    for r, value in zip(points, got[variable]['values']):
        if r['mean'] is None:
            if value != sentinel:
                structure_fault('a missing profile point must hold the declared sentinel', variable)
            published.append(None)
            continue
        error = abs(value - r['mean'])
        if not math.isfinite(value) or error > r['tolerance'] or value == sentinel:
            structure_fault('published mean disagrees with the exact mean beyond the declared tolerance', variable,
                            coordinate=r['coordinate'], published=value, exact=r['mean'], tolerance=r['tolerance'])
        worst = max(worst, error)
        published.append(value)
    rendered = render_csv(p, [{**r, 'mean': v} for r, v in zip(points, published)])
    if csv_bytes != rendered:
        structure_fault('published CSV differs from the values and counts in profile.nc', 'profile.csv')
    return {'maxAbsoluteError': worst, 'values': published}


def summary(p, cube, points, verified, nc_bytes, csv_bytes, source_bytes, runtime):
    expect = expectations(p, cube, points)
    published = [r for r in points if r['mean'] is not None]
    return {
        'version': 'schemaxis.xarray.summary/1', 'operation': 'reduceProfile',
        'source': {'bytes': len(source_bytes), 'sha256': cube['sourceSha256'], 'format': 'classic NetCDF CDF-1, fixed dimensions',
                   'dataSha256': cube['dataDigest']},
        'variable': p['variable'], 'missing': p['missing'], 'retain': p['retain'], 'reduced': expect['reduced'],
        'selectionSha256': canonical(selection_record(p)),
        'axes': [{'name': a['name'], 'unit': a['unit'], 'storageOrder': i, 'length': a['length'], 'coordinateSha256': a['digest'],
                  'range': next(d for d in p['coordinates'] if d['name'] == a['name']).get('range'),
                  'selectedIndices': [a['start'], a['stop'] - 1], 'selectedCount': a['stop'] - a['start'],
                  'selectedFirst': a['values'][a['start']], 'selectedLast': a['values'][a['stop'] - 1]}
                 for i, a in enumerate(cube['axes'])],
        'profile': {'dimension': p['retain'], 'unit': next(a for a in cube['axes'] if a['name'] == p['retain'])['unit'],
                    'points': len(points), 'publishedPoints': len(published),
                    'coordinates': [r['coordinate'] for r in points], 'means': verified['values'],
                    'validCounts': [r['valid'] for r in points], 'missingCounts': [r['missing'] for r in points],
                    'cellsPerPoint': [r['cells'] for r in points]},
        'totals': {'selectedCells': sum(r['cells'] for r in points), 'validCells': sum(r['valid'] for r in points),
                   'missingCells': sum(r['missing'] for r in points)},
        'reduction': {'statistic': 'unweighted arithmetic mean', 'weighting': 'none; not area, volume or time weighted',
                      'rounding': 'binary64; exact rational means rounded to nearest, native sums verified against the stated bound',
                      'toleranceModel': '(n + 1) * 2^-53 * mean(|x|) per point; refused as ill-conditioned above 1e-9 relative',
                      'maxAbsoluteError': verified['maxAbsoluteError'], 'uncertainty': 'none claimed: no measurement or sampling uncertainty'},
        'publications': {'profile.nc': hashlib.sha256(nc_bytes).hexdigest(), 'profile.csv': hashlib.sha256(csv_bytes).hexdigest()},
        'csv': {'header': ','.join([p['retain'], p['variable']['name'], *HEADER_SUFFIX]),
                'units': {p['retain']: next(a for a in cube['axes'] if a['name'] == p['retain'])['unit'],
                          p['variable']['name']: p['variable']['unit'], 'validCount': 'count', 'missingCount': 'count'},
                'missingMeanCell': 'empty (propagate policy only)'},
        'attributes': expect['attrs'], 'runtime': runtime, 'limits': LIMITS}
