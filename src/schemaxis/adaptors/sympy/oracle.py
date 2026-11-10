"""Independent host verifier for real-root isolation: Fraction arithmetic, Yun and Sturm; never imports SymPy.

Polynomials are lists of Fractions in descending order. The verifier takes only the published rational
intervals and multiplicities and decides, from the coefficients alone, whether they are a complete,
disjoint, narrow-enough isolation of every distinct real root with the correct multiplicity.
"""
from fractions import Fraction
import re

from schemaxis.core.faults import Fault, SchemaxisError

LIMITS = {'minDegree': 1, 'maxDegree': 12, 'maxCoefficientDigits': 40, 'maxPublishedDigits': 400,
          'minimumWidth': '1/1000000000000000000000000000000', 'maximumWidth': '1'}
LITERAL = re.compile(r'([+-]?)([0-9]{1,40})(?:/([0-9]{1,40}))?')
PUBLISHED = re.compile(r'(-?)([0-9]{1,400})(?:/([0-9]{1,400}))?')
HEADER = 'index,lower,upper,multiplicity,pointRoot'
MIN_WIDTH, MAX_WIDTH = Fraction(1, 10 ** 30), Fraction(1)


def raise_fault(code, message, location, recovery=None, **observed):
    raise SchemaxisError(Fault(code, message, location, 'pipeline', observed=observed, recovery=recovery))


# ---------------------------------------------------------------- rational text

def text(value):
    """Canonical rational text: reduced, positive denominator, no plus sign, no /1."""
    value = Fraction(value)
    return str(value.numerator) if value.denominator == 1 else f'{value.numerator}/{value.denominator}'


def literal(raw, location, code):
    """Strict rational literal: optional sign, digits, optional /digits. Never an expression."""
    if not isinstance(raw, str):
        raise_fault(code, 'give an exact rational literal as a string such as "-3/2" or "7"', location, type=type(raw).__name__)
    found = LITERAL.fullmatch(raw)
    if found is None:
        raise_fault(code, 'use only an optional sign, up to 40 digits and an optional /denominator of up to 40 digits; '
                    'expressions, decimals, exponents, spaces and names are not accepted', location,
                    recovery='write the exact fraction, for example "1/3" rather than 0.333 or 1/3.0')
    sign, numerator, denominator = found.groups()
    if denominator is not None and int(denominator) == 0:
        raise_fault(code, 'the denominator must not be zero', location)
    return Fraction(-int(numerator) if sign == '-' else int(numerator), int(denominator) if denominator is not None else 1)


def published(raw, location):
    found = PUBLISHED.fullmatch(raw)
    if found is None or (found.group(3) is not None and int(found.group(3)) == 0):
        raise_fault('SYMPY_CERTIFICATION_FAILED', 'published endpoint is not a bounded rational literal', location, text=raw[:60])
    value = Fraction(-int(found.group(2)) if found.group(1) else int(found.group(2)), int(found.group(3) or 1))
    if text(value) != raw:
        raise_fault('SYMPY_CERTIFICATION_FAILED', 'published endpoint is not in canonical reduced form', location, text=raw[:60])
    return value


# ---------------------------------------------------------------- polynomial arithmetic

def trim(p):
    p = list(p)
    while p and p[0] == 0:
        p.pop(0)
    return p


def degree(p):
    return len(trim(p)) - 1


def derivative(p):
    n = len(p) - 1
    return trim([c * (n - i) for i, c in enumerate(p[:-1])])


def evaluate(p, x):
    result = Fraction(0)
    for c in p:
        result = result * x + c
    return result


def divmod_poly(a, b):
    a, b = trim(a), trim(b)
    if not b:
        raise ZeroDivisionError('polynomial division by zero')
    quotient = []
    remainder = list(a)
    while len(remainder) >= len(b) and remainder:
        factor = remainder[0] / b[0]
        quotient.append(factor)
        for i, c in enumerate(b):
            remainder[i] -= factor * c
        remainder.pop(0)
        remainder = trim(remainder) if len(remainder) < len(b) else remainder
    return quotient or [Fraction(0)], trim(remainder)


def sub(a, b):
    n = max(len(a), len(b))
    a, b = [Fraction(0)] * (n - len(a)) + list(a), [Fraction(0)] * (n - len(b)) + list(b)
    return trim([x - y for x, y in zip(a, b)])


def mul(a, b):
    out = [Fraction(0)] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return trim(out)


def monic(p):
    p = trim(p)
    return [c / p[0] for c in p]


def gcd(a, b):
    a, b = trim(a), trim(b)
    while b:
        a, b = b, divmod_poly(a, b)[1]
    return monic(a)


def exact_quotient(a, b):
    q, r = divmod_poly(a, b)
    if r:
        raise ArithmeticError('division is not exact')
    return trim(q)


def yun(p):
    """Square-free decomposition p = lc * prod(a_i ** i) with each a_i monic, square-free and pairwise coprime."""
    p = trim(p)
    g = gcd(p, derivative(p))
    c = exact_quotient(monic(p), g)
    d = sub(exact_quotient(derivative(monic(p)), g), derivative(c))
    factors, i = [], 1
    while degree(c) > 0:
        a = gcd(c, d) if d else monic(c)
        c = exact_quotient(c, a)
        d = sub(exact_quotient(d, a) if d else [], derivative(c))
        if degree(a) > 0:
            factors.append((i, a))
        i += 1
    rebuilt = [p[0]]
    for i, a in factors:
        for _ in range(i):
            rebuilt = mul(rebuilt, a)
    if rebuilt != p:
        raise ArithmeticError('square-free decomposition does not rebuild the polynomial')
    return factors


# ---------------------------------------------------------------- Sturm

def sturm_chain(f):
    chain = [trim(f), derivative(f)]
    while chain[-1]:
        remainder = divmod_poly(chain[-2], chain[-1])[1]
        if not remainder:
            break
        chain.append([-c for c in remainder])
    return chain


def variations(values):
    signs = [v > 0 for v in values if v != 0]
    return sum(1 for a, b in zip(signs, signs[1:]) if a != b)


def at(chain, x):
    return variations([evaluate(p, x) for p in chain])


def at_infinity(chain, sign):
    values = [p[0] * (sign ** (len(p) - 1)) for p in chain]
    return variations(values)


def total_roots(chain):
    return at_infinity(chain, -1) - at_infinity(chain, 1)


def closed_count(chain, lower, upper):
    """Distinct real roots of the square-free chain head in the closed interval [lower, upper]."""
    f = chain[0]
    if lower == upper:
        return 1 if evaluate(f, lower) == 0 else 0
    return at(chain, lower) - at(chain, upper) + (1 if evaluate(f, lower) == 0 else 0)


# ---------------------------------------------------------------- published table

def render(intervals):
    lines = [HEADER] + [f'{i},{text(lo)},{text(hi)},{m},{"true" if lo == hi else "false"}'
                        for i, (lo, hi, m) in enumerate(intervals, 1)]
    return ('\n'.join(lines) + '\n').encode('ascii')


def parse_table(data):
    """Strict reader for real-roots.csv: ASCII, LF, canonical rationals, sequential index, at most 12 rows."""
    if any(b > 127 for b in data) or b'\r' in data or not data.endswith(b'\n'):
        raise_fault('SYMPY_CERTIFICATION_FAILED', 'real-roots.csv must be ASCII with LF line endings', 'real-roots.csv')
    lines = data.decode('ascii')[:-1].split('\n')
    if lines[0] != HEADER or len(lines) - 1 > LIMITS['maxDegree']:
        raise_fault('SYMPY_CERTIFICATION_FAILED', 'real-roots.csv header or row count differs from the contract', 'real-roots.csv')
    intervals = []
    for number, line in enumerate(lines[1:], 1):
        where = f'real-roots.csv:row {number}'
        cells = line.split(',')
        if len(cells) != 5 or cells[0] != str(number) or not re.fullmatch(r'[1-9][0-9]?', cells[3]) or cells[4] not in ('true', 'false'):
            raise_fault('SYMPY_CERTIFICATION_FAILED', 'row is not index,lower,upper,multiplicity,pointRoot', where)
        lower, upper = published(cells[1], where + ':lower'), published(cells[2], where + ':upper')
        intervals.append((lower, upper, int(cells[3])))
    if render(intervals) != data:
        raise_fault('SYMPY_CERTIFICATION_FAILED', 'real-roots.csv is not the canonical rendering of its intervals '
                    '(including the pointRoot column)', 'real-roots.csv')
    return intervals


# ---------------------------------------------------------------- certification

def certify(coefficients, width, intervals):
    """Prove completeness, disjointness, width, one root per interval and multiplicity, or raise a located fault.

    Returns the host assessment. The conclusion uses no native count: the number of distinct real roots comes from
    Sturm sign variations at +/- infinity of each square-free factor.
    """
    p = trim(coefficients)
    factors = yun(p)
    chains = [(i, sturm_chain(a)) for i, a in factors]
    totals = {i: total_roots(chain) for i, chain in chains}
    distinct = sum(totals.values())
    with_multiplicity = sum(i * n for i, n in totals.items())
    for index, (lower, upper, m) in enumerate(intervals):
        where = f'$.roots[{index}]'
        if lower > upper:
            raise_fault('SYMPY_CERTIFICATION_FAILED', 'interval lower endpoint exceeds its upper endpoint', where)
        if upper - lower > width:
            raise_fault('SYMPY_CERTIFICATION_FAILED', 'interval is wider than maximumIntervalWidth', where,
                        width=text(upper - lower), maximum=text(width))
        if index and intervals[index - 1][1] >= lower:
            raise_fault('SYMPY_CERTIFICATION_FAILED', 'intervals must be strictly ordered and disjoint (closed intervals)', where)
    certificates, matched = [], {i: 0 for i in totals}
    for index, (lower, upper, m) in enumerate(intervals):
        counts = {i: closed_count(chain, lower, upper) for i, chain in chains}
        holders = [i for i, n in counts.items() if n]
        if sum(counts.values()) != 1 or holders != [m]:
            raise_fault('SYMPY_CERTIFICATION_FAILED',
                        'the interval does not contain exactly one distinct real root of the stated multiplicity',
                        f'$.roots[{index}]', 'inspect roots-verification.json; the native output is not accepted',
                        rootsByMultiplicity={str(i): n for i, n in counts.items()}, multiplicity=m)
        matched[m] += 1
        certificates.append({'index': index + 1, 'lower': text(lower), 'upper': text(upper), 'width': text(upper - lower),
                             'multiplicity': m, 'pointRoot': lower == upper, 'sturmRootCount': 1,
                             'boundaryRoot': evaluate(p, lower) == 0 or evaluate(p, upper) == 0})
    if matched != totals or len(intervals) != distinct:
        raise_fault('SYMPY_CERTIFICATION_FAILED', 'the isolation is incomplete: published roots differ from the independent '
                    'Sturm count of distinct real roots', '$.roots', 'rerun; the native output is not accepted',
                    published=len(intervals), independentDistinct=distinct)
    return {'degree': len(p) - 1,
            'squareFreeFactors': [{'multiplicity': i, 'degree': len(a) - 1, 'distinctRealRoots': totals[i]} for i, a in factors],
            'distinctRealRoots': distinct, 'realRootsWithMultiplicity': with_multiplicity,
            'complexRootsWithMultiplicity': len(p) - 1 - with_multiplicity,
            'maximumIntervalWidth': text(width), 'widestInterval': text(max((u - l for l, u, _ in intervals), default=Fraction(0))),
            'intervals': certificates, 'method': 'Yun square-free decomposition; Sturm sequences of each factor (Fractions)',
            'outcome': 'certified'}
