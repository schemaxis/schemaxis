"""Curated discovery for exact real-root isolation of rational polynomials."""
import json
from importlib.resources import files


def catalogue():
    return {
        'application': {'label': 'SymPy',
            'purpose': 'Find every real root of a polynomial with exact rational coefficients as a rational isolating interval with its '
                       'multiplicity, certified independently by Sturm sequences, including exact point roots and the no-real-root case.',
            'keywords': ['SymPy', 'real root isolation', 'polynomial roots', 'Sturm sequence', 'exact rational arithmetic']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements': ['Isolated Python with exactly SymPy 1.14.0 (and its mpmath dependency); the host never imports SymPy.',
                         'Literal exact rational coefficients of degree 1 to 12 in descending powers; no expressions, decimals or symbols.'],
        'references': ['docs/sympy.md', 'src/schemaxis/adaptors/sympy/readiness.json'],
        'operations': {'isolateRealRoots': {
            'purpose': 'Locate all real roots of a rational polynomial exactly: disjoint rational intervals each holding one distinct root, '
                       'with multiplicity, exact point roots where the root is rational, and a host-checked count of complex roots.',
            'keywords': ['real root isolation', 'isolating intervals', 'polynomial roots', 'polynomial zeros', 'Sturm sequence', 'Sturm count',
                         'square-free', 'repeated roots', 'multiplicity', 'rational roots', 'no real roots', 'root counting',
                         'Descartes', 'exact roots', 'Poly.intervals', 'univariate polynomial', 'real zeros'],
            'semantics': ['Coefficients are exact rational strings in descending powers; the first entry multiplies x^degree and must be nonzero.',
                          'Intervals are closed, rational, disjoint and at most maximumIntervalWidth wide; a point interval is an exact root.',
                          'The host verifier decides completeness and multiplicity from the coefficients with Yun and Sturm; SymPy output is not trusted.'],
            'examples': [{'reference': 'examples/schemaxis/sympy-sqrt2.json', 'purpose': 'The two irrational roots of x^2 - 2.'},
                         {'reference': 'examples/schemaxis/sympy-repeated-roots.json', 'purpose': 'Exact point roots with multiplicities 2 and 3 and a complex pair.'},
                         {'reference': 'examples/schemaxis/sympy-no-real-roots.json', 'purpose': 'A polynomial with no real roots.'},
                         {'reference': 'examples/schemaxis/sympy-rational-roots.json', 'purpose': 'Three exact non-integer rational roots.'}]}}
    }
