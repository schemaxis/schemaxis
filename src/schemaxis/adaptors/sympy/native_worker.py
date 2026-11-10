"""Trusted SymPy worker; copied into the owned run directory and never host-imported.

Run as: python -I -B native-worker.py compute|readback   (working directory = run directory)
Reads native-config.json (coefficient and width literals only). The polynomial is built from
sympy.Rational values and a coefficient list; no string is parsed by SymPy. Writes inspectable
CSV/JSON only. Structured refusals go to <stage>-fault.json with exit status 3; readback
failures exit 4. The summary contains the native intervals and diagnostics, never a decision.
"""
import hashlib
import json
import math
import os
import re
import stat
import sys

REQUIRED_SYMPY = '1.14.0'
LITERAL = re.compile(r'([+-]?)([0-9]{1,40})(?:/([0-9]{1,40}))?\Z')
PUBLISHED = re.compile(r'(-?)([0-9]{1,400})(?:/([0-9]{1,400}))?\Z')
HEADER = 'index,lower,upper,multiplicity,pointRoot'
MAX_DEGREE = 12
CONFIG_KEYS = {'coefficients', 'maximumIntervalWidth'}


class Fault(Exception):
    def __init__(self, code, message, location='$', **details):
        super().__init__(message)
        self.payload = {'code': code, 'message': message, 'location': location, 'details': details}


def bounded(name, limit=4 * 1024 * 1024):
    fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise Fault('SYMPY_RESOURCE_LIMIT', 'native input is not a bounded regular file', name)
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise Fault('SYMPY_RESOURCE_LIMIT', 'native input exceeds its byte budget', name)
    return data


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(text):
    def bad(token):
        raise ValueError('non-finite JSON constant ' + token)

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key ' + key)
            result[key] = value
        return result
    return json.loads(text, parse_constant=bad, object_pairs_hook=unique)


def write_json(name, value):
    with open(name + '.tmp', 'w') as stream:
        stream.write(json.dumps(value, indent=1, allow_nan=False, sort_keys=True) + '\n')
    os.replace(name + '.tmp', name)


def rational_parts(text, pattern, location):
    found = pattern.match(text) if isinstance(text, str) else None
    if found is None:
        raise Fault('SYMPY_INVALID_CONTRACT', 'not a bounded rational literal', location)
    sign, numerator, denominator = found.groups()
    if denominator is not None and int(denominator) == 0:
        raise Fault('SYMPY_INVALID_CONTRACT', 'zero denominator', location)
    return (-int(numerator) if sign == '-' else int(numerator)), int(denominator or 1)


def load_config(data):
    config = strict_json(data.decode('utf-8'))
    if not isinstance(config, dict) or set(config) != CONFIG_KEYS:
        raise Fault('SYMPY_INVALID_CONTRACT', 'native configuration has exactly coefficients and maximumIntervalWidth', '$')
    coefficients = config['coefficients']
    if not isinstance(coefficients, list) or not 2 <= len(coefficients) <= MAX_DEGREE + 1:
        raise Fault('SYMPY_INVALID_CONTRACT', 'degree 1 to 12 needs 2 to 13 coefficients', '$.coefficients')
    parts = [rational_parts(c, LITERAL, f'$.coefficients[{i}]') for i, c in enumerate(coefficients)]
    if parts[0][0] == 0:
        raise Fault('SYMPY_INVALID_CONTRACT', 'the leading coefficient must be nonzero', '$.coefficients[0]')
    width = rational_parts(config['maximumIntervalWidth'], LITERAL, '$.maximumIntervalWidth')
    if not (width[0] > 0 and 10 ** 30 * width[0] >= width[1] and width[0] <= width[1]):
        raise Fault('SYMPY_INVALID_CONTRACT', 'maximumIntervalWidth is within [1e-30, 1]', '$.maximumIntervalWidth')
    return parts, width


def runtime_identity():
    try:
        import sympy
        import mpmath
    except ImportError as error:
        raise Fault('SYMPY_RUNTIME_UNAVAILABLE', 'the configured Python cannot import SymPy and mpmath', '$.runtime',
                    missing=str(getattr(error, 'name', None) or 'sympy')[:40])
    if sympy.__version__ != REQUIRED_SYMPY:
        raise Fault('SYMPY_UNSUPPORTED_RUNTIME', 'qualified for SymPy ' + REQUIRED_SYMPY + ' only', '$.runtime',
                    observed=sympy.__version__)
    return {'sympy': sympy.__version__, 'mpmath': mpmath.__version__, 'python': sys.version.split()[0], 'pid': os.getpid()}


def rational_text(value, location):
    import sympy
    if not isinstance(value, sympy.Rational):
        raise Fault('SYMPY_NATIVE_RESULT_INVALID', 'SymPy returned a non-rational endpoint', location, type=type(value).__name__)
    p, q = int(value.p), int(value.q)
    return str(p) if q == 1 else f'{p}/{q}'


def render(rows):
    lines = [HEADER] + [f'{i},{lo},{hi},{m},{"true" if lo == hi else "false"}' for i, (lo, hi, m) in enumerate(rows, 1)]
    return ('\n'.join(lines) + '\n').encode('ascii')


def compute():
    runtime = runtime_identity()
    import sympy
    config_bytes = bounded('native-config.json', 1024 * 1024)
    write_json('compute-inputs.json', {'native-config.json': sha(config_bytes), 'native-worker.py': sha(bounded('native-worker.py'))})
    coefficients, width = load_config(config_bytes)
    x = sympy.Symbol('x')
    poly = sympy.Poly([sympy.Rational(n, d) for n, d in coefficients], x, domain=sympy.QQ)
    if poly.degree() != len(coefficients) - 1:
        raise Fault('SYMPY_NATIVE_RESULT_INVALID', 'SymPy degree differs from the declared degree', '$.coefficients')
    # The list API exposes strict=True. Poly.intervals can return touching
    # endpoints (including a neighbouring exact root), which are not disjoint
    # closed certificates. Keep the host's stronger contract unchanged.
    found = sympy.intervals([poly], eps=sympy.Rational(*width), strict=True)
    rows = []
    for i, item in enumerate(found):
        (lower, upper), multiplicities = item
        if not isinstance(multiplicities, dict) or set(multiplicities) != {0}:
            raise Fault('SYMPY_NATIVE_RESULT_INVALID', 'root must belong to the one declared polynomial', f'$.roots[{i}]')
        multiplicity = multiplicities[0]
        if type(multiplicity) is not int or not 1 <= multiplicity <= MAX_DEGREE:
            raise Fault('SYMPY_NATIVE_RESULT_INVALID', 'multiplicity is not a small integer', f'$.roots[{i}]')
        rows.append((rational_text(lower, f'$.roots[{i}].lower'), rational_text(upper, f'$.roots[{i}].upper'), multiplicity))
    if len(rows) > MAX_DEGREE:
        raise Fault('SYMPY_NATIVE_RESULT_INVALID', 'more intervals than the degree', '$.roots')
    table = render(rows)
    with open('real-roots.csv', 'wb') as stream:
        stream.write(table)
    summary = {
        'version': 'schemaxis.sympy.summary/1', 'runtime': runtime,
        'call': {'api': 'sympy.intervals', 'domain': 'QQ', 'all': False, 'sqf': False, 'fast': False,
                 'eps': rational_text(sympy.Rational(*width), 'eps'), 'strict': True, 'polynomials': 1, 'construction': 'sympy.Poly(list of sympy.Rational, Symbol x)'},
        'degree': poly.degree(),
        'intervals': [{'lower': lo, 'upper': hi, 'multiplicity': m} for lo, hi, m in rows],
        'diagnostics': {'role': 'native diagnostics only; the host verifier owns every decision',
                        'countRoots': int(poly.count_roots()), 'isSquareFree': bool(poly.is_sqf)},
        'files': {'real-roots.csv': sha(table)},
    }
    write_json('roots-summary.json', summary)


def readback():
    """Separate process: published intervals must re-parse to the same exact rationals the compute stage reported."""
    result = {'pid': os.getpid()}
    try:
        config_bytes = bounded('native-config.json', 1024 * 1024)
        summary_bytes = bounded('roots-summary.json')
        table = bounded('real-roots.csv')
        write_json('readback-inputs.json', {'native-config.json': sha(config_bytes), 'native-worker.py': sha(bounded('native-worker.py')),
                                            'roots-summary.json': sha(summary_bytes), 'real-roots.csv': sha(table)})
        coefficients, _ = load_config(config_bytes)
        result['runtime'] = runtime_identity()
        import sympy
        summary = strict_json(summary_bytes.decode('utf-8'))
        lines = table.decode('ascii').rstrip('\n').split('\n')
        if lines[0] != HEADER:
            raise ValueError('header differs')
        x = sympy.Symbol('x')
        poly = sympy.Poly([sympy.Rational(n, d) for n, d in coefficients], x, domain=sympy.QQ)
        rows = []
        for r, line in enumerate(lines[1:], 1):
            cells = line.split(',')
            lo, hi = (sympy.Rational(*rational_parts(cells[k], PUBLISHED, f'row {r}')) for k in (1, 2))
            point = lo == hi
            if cells[4] != ('true' if point else 'false') or lo > hi:
                raise ValueError(f'row {r}: pointRoot or order differs')
            if point and poly.eval(lo) != 0:
                raise ValueError(f'row {r}: a point interval is not a root')
            rows.append((cells[1], cells[2], int(cells[3])))
        listed = [(i['lower'], i['upper'], i['multiplicity']) for i in summary['intervals']]
        ok = (rows == listed and render(rows) == table and summary['files'] == {'real-roots.csv': sha(table)}
              and summary['degree'] == poly.degree())
        result.update({'ok': ok, 'rows': len(rows), 'tableMatchesSummary': rows == listed})
        if not ok:
            result['reason'] = 'published table differs from the native summary'
    except (OSError, ValueError, KeyError, IndexError, TypeError, Fault) as error:
        result.update({'ok': False, 'reason': f'{type(error).__name__}: {error}'})
    write_json('readback.json', result)
    return result['ok']


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024 ** 3, 4 * 1024 ** 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 ** 2, 16 * 1024 ** 2))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    stage = sys.argv[1] if len(sys.argv) == 2 else None
    if stage == 'compute':
        try:
            compute()
        except Fault as fault:
            write_json('compute-fault.json', {**fault.payload, 'pid': os.getpid()})
            sys.exit(3)
    elif stage == 'readback':
        sys.exit(0 if readback() else 4)
    else:
        sys.exit(2)


if __name__ == '__main__':
    main()
