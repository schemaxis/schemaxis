"""Host semantics of SymPy real-root isolation; never imports SymPy."""
import copy
from fractions import Fraction as F
import json
from pathlib import Path
import random
import subprocess
import sys
import unittest

from schemaxis.adaptors import registry
from schemaxis.adaptors.sympy import adaptor as a, oracle as o
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / 'examples/schemaxis'


def code(action):
    try:
        action()
    except SchemaxisError as error:
        return error.fault.code, error.fault.location
    return 'accepted', None


def document(*coefficients, width=None):
    doc = {'version': a.VERSION, 'operation': a.OPERATION, 'coefficients': list(coefficients)}
    if width is not None:
        doc['maximumIntervalWidth'] = width
    return doc


def example(name):
    return json.loads((EXAMPLES / name).read_text())


def poly(*factors):
    result = [F(1)]
    for factor in factors:
        result = o.mul(result, [F(x) for x in factor])
    return result


class PlanTests(unittest.TestCase):
    def test_plan_is_immutable_canonical_and_deterministic(self):
        doc = document('2/4', '+0', '-3/6', width='10/10000')
        before = copy.deepcopy(doc)
        plan = a.plan(doc)
        self.assertEqual(doc, before)
        self.assertEqual(a.plan(doc), plan)
        self.assertEqual(plan['coefficients'], ['1/2', '0', '-1/2'])
        self.assertEqual((plan['degree'], plan['maximumIntervalWidth']), (2, '1/1000'))
        self.assertEqual(plan['publications'], ['real-roots.csv', 'roots-summary.json', 'roots-verification.json'])
        self.assertEqual(a.plan(document('1', '-2'))['maximumIntervalWidth'], '1/1000')

    def test_registry_plans_every_valid_example_and_rejects_invalid_ones(self):
        for name in ('sympy-sqrt2', 'sympy-repeated-roots', 'sympy-no-real-roots', 'sympy-rational-roots'):
            self.assertEqual(registry.plan(example(name + '.json'))['operation'], 'isolateRealRoots', name)
        self.assertEqual(code(lambda: registry.plan(example('sympy-expression-invalid.json'))),
                         ('SYMPY_INVALID_COEFFICIENT', '$.coefficients[0]'))
        self.assertEqual(code(lambda: registry.plan(example('sympy-zero-leading-invalid.json'))),
                         ('SYMPY_ZERO_LEADING_COEFFICIENT', '$.coefficients[0]'))

    def test_unsafe_and_malformed_coefficients_are_rejected_as_data_never_evaluated(self):
        hostile = ['x**2', '__import__("os").system("true")', '1+1', '1e3', '0.5', '1/0', ' 1', '1 ', '1/2/3', '--1', '１', 'sqrt(2)',
                   'pi', '1_0', '0x10', '1\n', '١٢', 'nan', 'oo', '1/-2', '1' * 41, '1/' + '1' * 41, '/2', '2/', '+', '-']
        for text in hostile:
            with self.subTest(text=text):
                self.assertEqual(code(lambda: a.plan(document('1', text))), ('SYMPY_INVALID_COEFFICIENT', '$.coefficients[1]'))
        self.assertEqual(code(lambda: a.plan(document('1', '1' * 40, width='1/1000')))[0], 'accepted')
        self.assertEqual(code(lambda: a.plan(document('1', '')))[1], '$.coefficients[1]')       # declared minLength

    def test_non_string_and_structural_faults(self):
        for value in (1, 1.5, None, True, ['1'], {'n': 1}):
            with self.subTest(value=value):
                self.assertIn(code(lambda: a.plan(document('1', value)))[0], {'INVALID_ARGUMENT', 'SYMPY_INVALID_COEFFICIENT'})
        self.assertNotEqual(code(lambda: a.plan(document('1')))[0], 'accepted')             # degree zero
        self.assertNotEqual(code(lambda: a.plan(document(*['1'] * 14)))[0], 'accepted')     # degree 13
        self.assertEqual(code(lambda: a.plan(document(*['1'] * 13)))[0], 'accepted')        # degree 12
        self.assertNotEqual(code(lambda: a.plan({**document('1', '2'), 'extra': 1}))[0], 'accepted')
        self.assertNotEqual(code(lambda: a.plan({**document('1', '2'), 'expression': 'x-2'}))[0], 'accepted')
        self.assertNotEqual(code(lambda: a.plan({**document('1', '2'), 'operation': 'solve'}))[0], 'accepted')
        self.assertNotEqual(code(lambda: a.plan({**document('1', '2'), 'version': 'schemaxis.sympy/2'}))[0], 'accepted')
        self.assertNotEqual(code(lambda: a.plan({'version': a.VERSION, 'operation': a.OPERATION}))[0], 'accepted')

    def test_width_bounds(self):
        for text, outcome in (('1', 'accepted'), ('1/1000000000000000000000000000000', 'accepted'),
                              ('1/1000000000000000000000000000001', 'SYMPY_INVALID_WIDTH'), ('0', 'SYMPY_INVALID_WIDTH'),
                              ('-1/10', 'SYMPY_INVALID_WIDTH'), ('2', 'SYMPY_INVALID_WIDTH'), ('0.001', 'SYMPY_INVALID_WIDTH')):
            with self.subTest(width=text):
                self.assertEqual(code(lambda: a.plan(document('1', '-2', width=text)))[0], outcome)
        self.assertEqual(code(lambda: a.plan(document('1', '-2', width='0.001'))), ('SYMPY_INVALID_WIDTH', '$.maximumIntervalWidth'))

    def test_schema_matches_declarations(self):
        schema = a.schema()
        self.assertEqual(sorted(schema['properties']), ['coefficients', 'maximumIntervalWidth', 'operation', 'version'])
        self.assertEqual(schema['properties']['coefficients']['minItems'], 2)
        self.assertEqual(schema['properties']['coefficients']['maxItems'], 13)
        self.assertIn('coefficients', schema['required'])

    def test_discovery_and_planning_do_not_import_the_native_application(self):
        script = ('import sys\nfrom schemaxis.adaptors import registry\nregistry.discover()\n'
                  'import json\nregistry.plan(json.load(open(sys.argv[1])))\nregistry.capabilities() if hasattr(registry, "capabilities") else None\n'
                  'assert "sympy" not in sys.modules and "mpmath" not in sys.modules, sorted(m for m in sys.modules if "sympy" in m)\n'
                  'print("native-free")')
        done = subprocess.run([sys.executable, '-B', '-c', script, str(EXAMPLES / 'sympy-sqrt2.json')], capture_output=True, text=True,
                              env={'PYTHONPATH': str(ROOT / 'src'), 'PATH': '/usr/bin:/bin'})
        self.assertEqual(done.stdout.strip(), 'native-free', done.stderr)


class OracleTests(unittest.TestCase):
    def test_polynomial_arithmetic_properties(self):
        rng = random.Random(7)
        for _ in range(60):
            p = [F(rng.randint(-9, 9), rng.randint(1, 5)) for _ in range(rng.randint(2, 9))]
            q = [F(rng.randint(-9, 9), rng.randint(1, 5)) for _ in range(rng.randint(2, 5))]
            if not o.trim(p) or not o.trim(q):
                continue
            quotient, remainder = o.divmod_poly(p, q)
            self.assertEqual(o.trim(o.sub(p, o.mul(quotient, q))), remainder)
            self.assertLess(len(remainder), len(o.trim(q)))
            if len(o.trim(p)) > 1:
                x = F(rng.randint(-5, 5), 3)
                self.assertEqual(o.evaluate(o.derivative(p), x) * 1, o.evaluate(o.derivative(p), x))
        self.assertEqual(o.derivative([F(1), F(0), F(-2)]), [F(2), F(0)])

    def test_square_free_decomposition_and_sturm_counts_against_constructed_roots(self):
        p = poly((1, -1), (1, -1), (1, -1), (1, 2), (1, 2), (1, 0, 1))
        factors = dict(o.yun(p))
        self.assertEqual({k: len(v) - 1 for k, v in factors.items()}, {1: 2, 2: 1, 3: 1})
        self.assertEqual(o.total_roots(o.sturm_chain(factors[2])), 1)
        self.assertEqual(o.total_roots(o.sturm_chain(factors[1])), 0)
        chain = o.sturm_chain(poly((1, 0, -2)))
        self.assertEqual((o.total_roots(chain), o.closed_count(chain, F(0), F(2)), o.closed_count(chain, F(-2), F(2)),
                          o.closed_count(chain, F(3, 2), F(2))), (2, 1, 2, 0))
        chain = o.sturm_chain(poly((1, -1), (1, 1), (1, -3)))
        self.assertEqual((o.closed_count(chain, F(1), F(1)), o.closed_count(chain, F(0), F(1)), o.closed_count(chain, F(1), F(3)),
                          o.closed_count(chain, F(1, 2), F(1, 2))), (1, 1, 2, 0))

    def test_certifies_correct_isolations(self):
        sqrt2 = o.certify(poly((1, 0, -2)), F(1, 1000), [(F(-58, 41), F(-41, 29), 1), (F(41, 29), F(58, 41), 1)])
        self.assertEqual((sqrt2['distinctRealRoots'], sqrt2['outcome']), (2, 'certified'))
        mixed = poly((1, -1), (1, -1), (1, -1), (1, 2), (1, 2), (1, 0, 1))
        found = o.certify(mixed, F(1, 10), [(F(-2), F(-2), 2), (F(1), F(1), 3)])
        self.assertEqual((found['distinctRealRoots'], found['realRootsWithMultiplicity'], found['complexRootsWithMultiplicity']), (2, 5, 2))
        self.assertTrue(all(i['pointRoot'] for i in found['intervals']))
        none = o.certify(poly((1, 0, 1)), F(1, 10), [])
        self.assertEqual((none['distinctRealRoots'], none['complexRootsWithMultiplicity']), (0, 2))
        wide = o.certify(poly((1, 0, -2)), F(3), [(F(-2), F(-1), 1), (F(1), F(2), 1)])
        self.assertEqual(wide['widestInterval'], '1')

    def test_rejects_every_kind_of_wrong_isolation(self):
        mixed = poly((1, -1), (1, -1), (1, -1), (1, 2), (1, 2), (1, 0, 1))
        good = [(F(-2), F(-2), 2), (F(1), F(1), 3)]
        sqrt2 = [(F(-58, 41), F(-41, 29), 1), (F(41, 29), F(58, 41), 1)]
        cases = {
            'missing root': (mixed, F(1), good[:1], '$.roots'),
            'extra phantom interval': (mixed, F(1), good + [(F(5), F(5), 1)], '$.roots[2]'),
            'wrong multiplicity': (mixed, F(1), [(F(-2), F(-2), 2), (F(1), F(1), 2)], '$.roots[1]'),
            'multiplicity from wrong factor': (mixed, F(1), [(F(-2), F(-2), 3), (F(1), F(1), 3)], '$.roots[0]'),
            'two roots in one interval': (poly((1, 0, -2)), F(10), [(F(-2), F(2), 1)], '$.roots[0]'),
            'no root in interval': (poly((1, 0, -2)), F(1), [(F(0), F(1), 1), (F(41, 29), F(58, 41), 1)], '$.roots[0]'),
            'too wide': (poly((1, 0, -2)), F(1, 10000), sqrt2, '$.roots[0]'),
            'reversed endpoints': (poly((1, 0, -2)), F(1), [(F(2), F(1), 1)], '$.roots[0]'),
            'overlap': (poly((1, 0, -2)), F(10), [(F(-2), F(0), 1), (F(0), F(2), 1)], '$.roots[1]'),
            'shared endpoint': (poly((1, -1), (1, 1)), F(10), [(F(-1), F(0), 1), (F(0), F(1), 1)], '$.roots[1]'),
            'unordered': (poly((1, 0, -2)), F(1), sqrt2[::-1], '$.roots[1]'),
            'point interval off the root': (poly((1, -1), (1, 1)), F(1), [(F(-1), F(-1), 1), (F(2), F(2), 1)], '$.roots[1]'),
            'roots claimed for no real roots': (poly((1, 0, 1)), F(10), [(F(-1), F(1), 1)], '$.roots[0]'),
        }
        for label, (p, width, intervals, location) in cases.items():
            with self.subTest(label):
                self.assertEqual(code(lambda: o.certify(p, width, intervals)), ('SYMPY_CERTIFICATION_FAILED', location))

    def test_closed_interval_endpoint_roots_are_counted_once(self):
        p = poly((1, -1), (1, 1), (1, -3))
        self.assertEqual(o.certify(p, F(2), [(F(-1), F(0), 1), (F(1, 2), F(3, 2), 1), (F(2), F(4), 1)])['distinctRealRoots'], 3)
        self.assertEqual(code(lambda: o.certify(p, F(2), [(F(-1), F(0), 1), (F(0), F(2), 1), (F(2), F(4), 1)])),
                         ('SYMPY_CERTIFICATION_FAILED', '$.roots[1]'))

    def test_randomised_constructed_roots_are_certified_exactly(self):
        rng = random.Random(24)
        for _ in range(25):
            roots = [(F(rng.randint(-20, 20), rng.randint(1, 6)), rng.randint(1, 3)) for _ in range(rng.randint(1, 4))]
            merged = {}
            for r, m in roots:
                merged[r] = merged.get(r, 0) + m
            factors = [(1, -r) for r, m in merged.items() for _ in range(m)]
            scale = F(rng.randint(1, 9), rng.randint(1, 4)) * rng.choice((-1, 1))
            p = [scale * c for c in poly(*factors, *([(1, 0, rng.randint(1, 4))] if rng.random() < .5 else []))]
            truth = [(r, r, m) for r, m in sorted(merged.items())]
            found = o.certify(p, F(1, 100), truth)
            self.assertEqual((found['distinctRealRoots'], found['realRootsWithMultiplicity']), (len(merged), sum(merged.values())))
            if len(truth) > 1:
                self.assertEqual(code(lambda: o.certify(p, F(1, 100), truth[1:]))[0], 'SYMPY_CERTIFICATION_FAILED')

    def test_resource_bounded_worst_case_completes_quickly(self):
        big = [F(10 ** 39 - 1 - i * 7919, 10 ** 39 - 3) for i in range(13)]
        factors = o.yun(big)
        self.assertEqual(sum(i * (len(f) - 1) for i, f in factors), 12)
        self.assertTrue(all(0 <= o.total_roots(o.sturm_chain(f)) <= len(f) - 1 for _, f in factors))


class TableTests(unittest.TestCase):
    GOOD = b'index,lower,upper,multiplicity,pointRoot\n1,-2,-2,2,true\n2,41/29,58/41,1,false\n'

    def test_round_trip_and_canonical_rendering(self):
        intervals = o.parse_table(self.GOOD)
        self.assertEqual(intervals, [(F(-2), F(-2), 2), (F(41, 29), F(58, 41), 1)])
        self.assertEqual(o.render(intervals), self.GOOD)
        self.assertEqual(o.parse_table(b'index,lower,upper,multiplicity,pointRoot\n'), [])

    def test_strict_grammar_rejects_malformed_tables(self):
        head = b'index,lower,upper,multiplicity,pointRoot\n'
        bad = {
            'no final newline': self.GOOD[:-1], 'crlf': self.GOOD.replace(b'\n', b'\r\n'), 'non ascii': head + '1,-2,-2,2,true\n'.encode() + b'\xc3\xa9\n',
            'header': b'index,lo,hi,multiplicity,pointRoot\n', 'unreduced': head + b'1,2/4,1,1,false\n', 'zero denominator': head + b'1,1/0,1,1,false\n',
            'plus sign': head + b'1,+1,1,1,true\n', 'decimal': head + b'1,0.5,1,1,false\n', 'index gap': head + b'2,1,1,1,true\n',
            'wrong point flag': head + b'1,1,1,1,false\n', 'multiplicity zero': head + b'1,1,1,0,true\n', 'multiplicity padded': head + b'1,1,1,01,true\n',
            'extra column': head + b'1,1,1,1,true,0\n', 'blank line': head + b'1,1,1,1,true\n\n', 'expression': head + b'1,1+1,2,1,true\n',
            'too many rows': head + b''.join(b'%d,%d,%d,1,true\n' % (i, i, i) for i in range(1, 14)),
            'huge endpoint': head + b'1,' + b'9' * 401 + b',' + b'9' * 401 + b',1,true\n',
        }
        for label, data in bad.items():
            with self.subTest(label):
                self.assertEqual(code(lambda: o.parse_table(data))[0], 'SYMPY_CERTIFICATION_FAILED')

    def test_evidence_and_publication_membership_are_fixed(self):
        self.assertEqual([k for _, k in a.PUBLICATIONS], ['table', 'text', 'text'])
        self.assertEqual(a.PUBLICATIONS[-1][0], 'roots-verification.json')
        self.assertIn('native-worker.py', a.evidence_names())
        self.assertEqual(a.command('/x/python', 'compute'), ['/x/python', '-I', '-B', 'native-worker.py', 'compute'])
        self.assertEqual(a.reusableInputs(document('1', '-2')), {})

    def test_run_refuses_without_interpreter_and_with_bad_timeout(self):
        import os
        import tempfile
        saved = os.environ.pop('SCHEMAXIS_SYMPY', None)
        try:
            with tempfile.TemporaryDirectory() as directory:
                self.assertEqual(code(lambda: a.run(document('1', '-2'), Path(directory) / 'a'))[0], 'INTERPRETER_NOT_FOUND')
                self.assertEqual(code(lambda: a.run(document('1', '-2'), Path(directory) / 'b', executable='relative/python'))[0], 'INTERPRETER_NOT_FOUND')
                self.assertEqual(code(lambda: a.run(document('1', 'x'), Path(directory) / 'c', executable=sys.executable))[0], 'SYMPY_INVALID_COEFFICIENT')
                self.assertFalse((Path(directory) / 'c').exists())
        finally:
            if saved is not None:
                os.environ['SCHEMAXIS_SYMPY'] = saved

    def test_verify_rejects_missing_evidence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(code(lambda: a.verify(directory))[0], 'VERIFICATION_FAILED')


if __name__ == '__main__':
    unittest.main()
