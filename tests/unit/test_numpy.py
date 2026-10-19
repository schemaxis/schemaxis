"""Host semantics of NumPy principal component analysis; never imports NumPy."""
import copy
from fractions import Fraction as F
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from schemaxis.adaptors.numpy import adaptor as a, oracle as o
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / 'examples/schemaxis'
SENSORS = EXAMPLES / 'numpy-sensors.csv'


def code(action):
    try:
        action()
    except SchemaxisError as error:
        return error.fault.code, error.fault.location
    return 'accepted', None


def baseline(**changes):
    doc = json.loads((EXAMPLES / 'numpy-sensors.json').read_text())
    doc['source'] = str(SENSORS)
    doc.update(changes)
    return doc


def publication(doc, data):
    """A native-shaped publication built from the stdlib Jacobi solution (the clean reference)."""
    p = a.plan(doc)
    config = a.native_config(p)
    keys, rows = o.parse(data, config)
    st = o.statistics(rows, config)
    vals, vecs, _ = o.jacobi(st['cov'])
    K, eta, n = config['retention']['components'], config['loadingTolerance'], len(rows)
    V = [v if v[o.anchor(v, eta)] > 0 else [-x for x in v] for v in vecs[:K]]
    mu, sc = st['means'], st['scales']
    Z = [[(x - m) / s for x, m, s in zip(r, mu, sc)] for r in rows]
    T = [[o.dot(z, v) for v in V] for z in Z]
    R = [[m + s * math.fsum(T[i][k] * V[k][j] for k in range(K)) for j, (m, s) in enumerate(zip(mu, sc))] for i in range(n)]
    whole = math.fsum(vals)
    key = keys if keys is not None else list(range(1, n + 1))
    def csv(header, body, integer):
        return (','.join(header) + '\n' + ''.join(','.join([str(int(r[0])) if integer else repr(float(r[0]))]
                + [repr(float(x)) for x in r[1:]]) + '\n' for r in body)).encode('ascii')
    names = [c['name'] for c in config['channels']]
    keyname = config['header'][0] if config['keyed'] else 'row'
    tables = {'spectrum.csv': csv(['component', 'eigenvalue', 'varianceFraction', 'cumulativeFraction'],
                                  [[k + 1, x, x / whole, math.fsum(vals[:k + 1]) / whole] for k, x in enumerate(vals)], True),
              'loadings.csv': csv(['component', *names], [[k + 1, *v] for k, v in enumerate(V)], True),
              'scores.csv': csv([keyname, *[f'PC{k + 1}' for k in range(K)]], [[key[i], *T[i]] for i in range(n)], not config['keyed']),
              'reconstruction.csv': csv([keyname, *names], [[key[i], *R[i]] for i in range(n)], not config['keyed'])}
    residual = [math.sqrt(math.fsum((o.dot(st['cov'][i], v) - lam * v[i]) ** 2 for i in range(len(v)))) for lam, v in zip(vals, V)]
    summary = {'source': {'sha256': __import__('hashlib').sha256(data).hexdigest(), 'bytes': len(data)},
               'parsedDigest': o.array_digest(rows), 'scaling': config['scaling'], 'units': [c['unit'] for c in config['channels']],
               'varianceDenominator': 'n-1', 'output': config['output'], 'means': mu, 'scales': sc, 'totalVariance': st['total'],
               'retained': K, 'explainedFraction': math.fsum(vals[:K]) / whole,
               'reconstructionRMS': [math.sqrt(math.fsum((rows[i][j] - R[i][j]) ** 2 for i in range(n)) / n) for j in range(len(mu))],
               'residualVariance': math.fsum(((rows[i][j] - R[i][j]) / sc[j]) ** 2 for i in range(n) for j in range(len(mu))) / (n - 1),
               'nativeResiduals': {'eigenpairResidual2': residual}}
    return config, summary, tables


def replace_cell(table, row, column, fn):
    lines = table.decode().splitlines()
    cells = lines[row].split(',')
    cells[column] = repr(fn(float(cells[column])))
    lines[row] = ','.join(cells)
    return ('\n'.join(lines) + '\n').encode()


class NumpyPlanTests(unittest.TestCase):
    def test_planning_is_immutable_with_located_semantic_faults(self):
        doc = baseline()
        before = copy.deepcopy(doc)
        plan = a.plan(doc)
        self.assertEqual(doc, before)
        self.assertEqual(a.plan(doc), plan)
        self.assertEqual(plan['publications'][-1], 'pca-verification.json')
        self.assertEqual((plan['output'], plan['loadingTolerance']), ('components', 1e-6))
        cases = [
            (lambda d: d['channels'][1].update(unit='V'), ('PCA_UNIT_MISMATCH', '$.scaling')),
            (lambda d: d.update(scaling='declared'), ('PCA_INVALID_CONTRACT', '$.channels[0].scale')),
            (lambda d: d['channels'][2].update(scale=2.0), ('PCA_INVALID_CONTRACT', '$.channels[2].scale')),
            (lambda d: d.update(retention={}), ('PCA_INVALID_CONTRACT', '$.retention')),
            (lambda d: d.update(retention={'components': 2, 'minimumExplainedVariance': 0.5}), ('PCA_INVALID_CONTRACT', '$.retention')),
            (lambda d: d['channels'][0].update(name='PC1'), ('PCA_INVALID_CONTRACT', '$.channels[0].name')),
            (lambda d: d['rowKey'].update(name='ch1'), ('PCA_INVALID_CONTRACT', '$.channels[0].name')),
            (lambda d: d.update(source='relative.csv'), ('PCA_INVALID_SOURCE', '$.source')),
            (lambda d: d.update(source='/abs/table.txt'), ('PCA_INVALID_SOURCE', '$.source')),
            (lambda d: d['requirements']['reconstructionRMS'].append({'channel': 'ch1', 'maximum': 1}), ('PCA_INVALID_CONTRACT', '$.requirements.reconstructionRMS[1].channel')),
            (lambda d: d.update(loadingTolerance=0.5), ('INVALID_ARGUMENT', '$.loadingTolerance')),
            (lambda d: d['channels'][0].update(unit='m²'), ('PCA_INVALID_CONTRACT', '$.channels[0].unit')),
        ]
        for change, expected in cases:
            d = copy.deepcopy(doc); change(d)
            with self.subTest(expected=expected):
                self.assertEqual(code(lambda: a.plan(d)), expected)

    def test_declared_scales_require_finite_positive_values(self):
        doc = baseline(scaling='declared')
        for value in (0, -1.0, float('inf'), float('nan'), True):
            d = copy.deepcopy(doc)
            for channel in d['channels']:
                channel['scale'] = 1.0
            d['channels'][1]['scale'] = value
            with self.subTest(value=value):
                self.assertNotEqual(code(lambda: a.plan(d))[0], 'accepted')

    def test_schema_matches_declarations_and_is_closed(self):
        schema = a.schema()
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(set(schema['properties']), {'version', 'operation', *a.OPTIONS})
        self.assertEqual(set(schema['required']), {'version', 'operation', 'source', 'channels', 'scaling', 'retention'})
        channel = schema['properties']['channels']['items']
        self.assertEqual(set(channel['properties']), {'name', 'unit', 'scale'})
        self.assertEqual(set(channel['required']), {'name', 'unit'})
        self.assertEqual(channel['properties']['scale'], {'type': 'number', 'exclusiveMinimum': 0})
        self.assertEqual(schema['properties']['scaling']['enum'], ['none', 'standardise', 'declared'])
        self.assertEqual(set(a.DECLARATIONS), {'principalComponents'})

    def test_examples_plan_or_fail_with_declared_faults(self):
        readiness = json.loads((ROOT / 'src/schemaxis/adaptors/numpy/readiness.json').read_text())
        for example in readiness['routes'][a.VERSION]['examples']:
            doc = json.loads((ROOT / example['reference']).read_text())
            observed = code(lambda: a.plan(doc))[0]
            with self.subTest(example=example['id']):
                self.assertEqual(observed, example.get('fault', 'accepted'))

    def test_host_never_imports_numpy(self):
        source = ('import sys,json;from schemaxis.adaptors.numpy import adaptor,oracle,capabilities;adaptor.schema();'
                  'capabilities.catalogue();assert not any(k.split(".")[0]=="numpy" for k in sys.modules), sorted(sys.modules)')
        done = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


class NumpyGrammarTests(unittest.TestCase):
    config = a.native_config(a.plan(baseline()))

    def refuse(self, text, expected):
        self.assertEqual(code(lambda: o.parse(text.encode('latin-1') if isinstance(text, str) else text, self.config)), expected)

    def test_strict_grammar_refuses_lenient_python_float_forms(self):
        header = 'time,ch1,ch2,ch3,ch4\n'
        good = '0,1,2,3,4\n1,2,3,4,6\n2,4,1,3,1\n'
        self.assertEqual(o.parse((header + good).encode(), self.config)[1][0], [1.0, 2.0, 3.0, 4.0])
        for cell in ('1_000', ' 1', '1 ', 'Infinity', 'nan', 'inf', '0x10', '1e0001', '+', '.', '1,0'):
            with self.subTest(cell=cell):
                text = header + good.replace('0,1,2', '0,' + cell + ',2', 1)
                result = code(lambda: o.parse(text.encode(), self.config))[0]
                self.assertIn(result, ('PCA_INVALID_NUMBER', 'PCA_INVALID_CSV'))
        self.refuse(header + good.replace('0,1,2', '0,1e400,2', 1), ('PCA_VALUE_RANGE', 'line 2 column 2'))
        self.refuse(header + good.replace('0,1,2', '0,,2', 1), ('PCA_MISSING_VALUE', 'line 2 column 2'))
        self.refuse(header + good.replace('0,1,2', '0,"1",2', 1), ('PCA_INVALID_CSV', 'line 2'))
        self.refuse(b'\xef\xbb\xbf' + (header + good).encode(), ('PCA_INVALID_CSV', '$.source'))
        self.refuse('time,ch1,ch2,ch4,ch3\n' + good, ('PCA_HEADER_MISMATCH', 'line 1'))
        self.refuse(header + good + '\n', ('PCA_INVALID_CSV', 'line 5'))
        self.refuse(header + good.replace('2,4,1', '0,4,1'), ('PCA_ROW_KEY_ORDER', 'line 4'))
        self.refuse(header + '0,1,2,3,4\n1,2,3,4,6\n', ('PCA_DIMENSIONS', '$.source'))
        self.refuse(header + '0,1,2,3\n', ('PCA_INVALID_CSV', 'line 2'))
        self.refuse(b'x' * (8 * 1024 * 1024 + 1), ('PCA_RESOURCE_LIMIT', '$.source'))
        self.refuse('time,ch1,ch2,ch3,ch4\n0,١٢,2,3,4\n'.encode('utf-8'), ('PCA_INVALID_CSV', '$.source'))

    def test_closed_range_contract_at_both_sides_of_each_bound(self):
        header = 'time,ch1,ch2,ch3,ch4\n'
        rows = lambda a_: header + f'0,{a_},2,3,4\n1,{-a_},3,4,6\n2,0,1,3,1\n'
        for value in (1e48, 1e-48):
            keys, data = o.parse(rows(value).encode(), self.config)
        below = math.nextafter(1e-48, 0.0)
        self.assertEqual(code(lambda: o.parse(rows(below).encode(), self.config)), ('PCA_VALUE_RANGE', 'line 2 column 2'))
        self.assertEqual(code(lambda: o.parse(rows(math.nextafter(1e48, math.inf)).encode(), self.config)), ('PCA_VALUE_RANGE', 'line 2 column 2'))
        data = o.parse(SENSORS.read_bytes(), self.config)[1]
        declared = a.native_config(a.plan(baseline(scaling='declared', channels=[
            {'name': f'ch{i}', 'unit': 'mV', 'scale': s} for i, s in zip(range(1, 5), (1e-48, 1.0, 1.0, 1.0))])))
        self.assertEqual(code(lambda: o.statistics(data, declared)), ('PCA_SCALE_RANGE', '$.channels[0]'))
        constant = [r[:3] + [7.0] for r in data]
        self.assertEqual(code(lambda: o.statistics(constant, self.config)), ('PCA_CHANNEL_SPREAD', '$.channels[3]'))
        offset = [r[:3] + [r[3] + 2e7] for r in data]
        self.assertEqual(code(lambda: o.statistics(offset, self.config)), ('PCA_CHANNEL_SPREAD', '$.channels[3]'))


class NumpyNumericalTests(unittest.TestCase):
    def test_analytic_fixture_has_the_exact_documented_covariance(self):
        lines = SENSORS.read_text().splitlines()[1:]
        X = [[F(x) for x in line.split(',')[1:]] for line in lines]
        n = len(X)
        mean = [sum(col) / n for col in zip(*X)]
        cov = [[sum((r[i] - mean[i]) * (r[j] - mean[j]) for r in X) / (n - 1) for j in range(4)] for i in range(4)]
        H4 = [[1, 1, 1, 1], [1, -1, 1, -1], [1, 1, -1, -1], [1, -1, -1, 1]]
        lam = [F(64, 63) * d * d for d in (F(4), F(2), F(1), F(1, 2))]
        expected = [[sum(F(H4[i][k] * H4[j][k], 4) * lam[k] for k in range(4)) for j in range(4)] for i in range(4)]
        self.assertEqual(mean, [100, -50, 20, 5])
        self.assertEqual(cov, expected)

    def test_jacobi_certificate_bounds_actual_error_on_exact_spectra(self):
        R = [[F(3, 5), F(-4, 5), 0], [F(4, 5), F(3, 5), 0], [0, 0, 1]]
        for spectrum in ([9, 4, 1], [3, 3, 1], [1, F(1, 10**10), F(1, 10**20)]):
            exact = [[float(sum(R[i][k] * spectrum[k] * R[j][k] for k in range(3))) for j in range(3)] for i in range(3)]
            for i in range(3):
                for j in range(i):
                    exact[i][j] = exact[j][i]
            vals, vecs, _ = o.jacobi(exact)
            cert = o.certified(exact, vals, vecs)
            for got, want, bound in zip(vals, sorted(map(float, spectrum), reverse=True), cert['errors']):
                with self.subTest(spectrum=spectrum):
                    self.assertLessEqual(abs(got - want), bound + 4 * o.U * float(max(spectrum)))

    def test_declared_resolution_and_degeneracy_rules(self):
        policy = o.policy(64, 4, 10.0, 1e-6)
        config = {'retention': {'components': 1}, 'output': 'components'}
        self.assertEqual(o.decide([4.0, 4.0, 1.0, 1.0], config, policy, policy['band'])[1][0], 'PCA_DEGENERATE_COMPONENT')
        self.assertEqual(o.decide([4.0, 4.0, 1.0, 1.0], {**config, 'output': 'subspace'}, policy, policy['band'])[1][0], 'PCA_RETENTION_SPLITS_CLUSTER')
        self.assertEqual(o.decide([4.0, 4.0, 1.0, 1.0], {'retention': {'components': 2}, 'output': 'subspace'}, policy, policy['band']), (2, None))
        self.assertEqual(o.decide([6.0, 4.0, 0.0, 0.0], {'retention': {'components': 3}, 'output': 'components'}, policy, policy['band'])[1][0],
                         'PCA_COMPONENT_BELOW_RESOLUTION')
        theta = policy['gapThreshold']
        self.assertEqual(o.decide([5.0, 5.0 - theta, 0.1, 0.0], config, policy, policy['band'])[1][0], 'PCA_SPECTRUM_BORDERLINE')
        self.assertEqual(o.decide([8.0, 2.0, 0.0, 0.0], {'retention': {'minimumExplainedVariance': 0.8}, 'output': 'components'}, policy, policy['band'])[1][0],
                         'PCA_RETENTION_BORDERLINE')

    def test_three_state_requirements_never_decide_inside_the_band(self):
        self.assertEqual(o.three_state(1.0, 0.1, 2.0), 'met')
        self.assertEqual(o.three_state(1.0, 0.1, 0.5), 'unmet')
        self.assertEqual(o.three_state(1.0, 0.1, 1.05), 'indeterminate')
        self.assertEqual(o.three_state(1.0, 0.1, 0.95), 'indeterminate')
        self.assertEqual(o.three_state(1e-15, 2e-13, 1e-15), 'indeterminate')
        self.assertEqual(o.three_state(1.0, None, 1e100), 'indeterminate')


class NumpyVerifierTests(unittest.TestCase):
    def setUp(self):
        self.data = SENSORS.read_bytes()
        self.doc = baseline()
        self.config, self.summary, self.tables = publication(self.doc, self.data)

    def assess(self, summary=None, tables=None):
        return o.assess(self.config, self.data, summary or self.summary, tables or self.tables)

    def rejected(self, summary=None, tables=None):
        result = code(lambda: self.assess(summary, tables))
        self.assertEqual(result[0], 'VERIFICATION_FAILED')
        return result

    def test_clean_publication_is_accepted_with_host_owned_decisions(self):
        result = self.assess()
        self.assertEqual(result['outcome'], 'accepted')
        self.assertEqual(result['requirements']['status'], {'minimumExplainedVariance': 'met', 'reconstructionRMS.ch1': 'met'})
        self.assertAlmostEqual(result['requirements']['reconstructionRMS'][0], math.sqrt(0.3125), places=13)
        self.assertTrue(all(0 < r < 1e-3 for r in result['certification']['ratio']))
        self.assertLess(max(result['spectral']['loadingSineBounds']), 1e-12)
        self.assertEqual(self.assess(), result)          # deterministic recomputation

    def test_full_retention_near_zero_rms_is_indeterminate_not_unmet(self):
        doc = baseline(retention={'components': 4}, requirements={'reconstructionRMS': [
            {'channel': 'ch2', 'maximum': 1e-15}, {'channel': 'ch3', 'maximum': 1e-9}]})
        config, summary, tables = publication(doc, self.data)
        result = o.assess(config, self.data, summary, tables)
        self.assertEqual(result['requirements']['status'], {'reconstructionRMS.ch2': 'indeterminate', 'reconstructionRMS.ch3': 'met'})
        self.assertEqual(result['outcome'], 'requirementsIndeterminate')

    def test_semantic_mutants_are_rejected(self):
        flipped = dict(self.tables, **{'loadings.csv': replace_cell(self.tables['loadings.csv'], 2, 1, lambda x: -x)})
        self.rejected(tables=flipped)
        self.rejected(tables=dict(self.tables, **{'spectrum.csv': replace_cell(self.tables['spectrum.csv'], 1, 1, lambda x: x * 63 / 64)}))
        self.rejected(tables=dict(self.tables, **{'reconstruction.csv': replace_cell(self.tables['reconstruction.csv'], 1, 1, lambda x: x + 1e-6)}))
        self.rejected(summary={**self.summary, 'means': [self.summary['means'][0] + 0.01, *self.summary['means'][1:]]})
        self.rejected(summary={**self.summary, 'scales': [2.0, 1.0, 1.0, 1.0]})
        self.rejected(summary={**self.summary, 'reconstructionRMS': [x * 1.001 for x in self.summary['reconstructionRMS']]})
        self.rejected(summary={**self.summary, 'retained': 3})
        self.rejected(summary={**self.summary, 'units': ['V'] * 4})
        # Self-consistent tilt toward a discarded axis: only the independent spectrum rejects it.
        st = o.statistics(o.parse(self.data, self.config)[1], self.config)
        vals, vecs, _ = o.jacobi(st['cov'])
        lines = self.tables['loadings.csv'].decode().splitlines()
        V = [[float(x) for x in line.split(',')[1:]] for line in lines[1:]]
        c, s = math.cos(0.05), math.sin(0.05)
        V[0] = [c * x + s * y for x, y in zip(V[0], vecs[2])]
        doc_tables = dict(self.tables)
        doc_tables['loadings.csv'] = ('component,ch1,ch2,ch3,ch4\n' + ''.join(
            ','.join([str(k + 1)] + [repr(x) for x in v]) + '\n' for k, v in enumerate(V))).encode()
        result = code(lambda: o.assess(self.config, self.data, self.summary, doc_tables))
        self.assertEqual(result[0], 'VERIFICATION_FAILED')

    def test_published_value_range_and_format_are_structural(self):
        for value in (float('inf'), 1e101, -1e101):
            bad = replace_cell(self.tables['scores.csv'], 1, 1, lambda x: value)
            self.assertIn(repr(value).encode(), bad)
            result = self.rejected(tables=dict(self.tables, **{'scores.csv': bad}))
            self.assertEqual(result[1], 'scores.csv row 1')
        spectrum = self.tables['spectrum.csv'].decode().replace('\n1,', '\n1.0,', 1).encode()
        self.rejected(tables=dict(self.tables, **{'spectrum.csv': spectrum}))


class NumpyEvidenceTests(unittest.TestCase):
    def test_native_refusals_are_mapped_only_after_independent_consistency(self):
        doc = baseline(retention={'components': 4})
        p = a.plan(doc); config = a.native_config(p)
        data = SENSORS.read_bytes()
        prediction = o.predict(config, data)
        cause = SchemaxisError(o.Fault('RUNNER_FAILED', 'exit 3', 'compute', 'pipeline'))
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            def refusal(payload):
                (directory / 'compute-fault.json').write_text(json.dumps(payload))
                return code(lambda: a.native_refusal(directory, 'compute', cause, config, data))
            uncertified = {'code': 'PCA_RECONSTRUCTION_UNCERTIFIED', 'message': 'm', 'location': '$.channels[1]', 'details': {'ratio': 8.8}}
            self.assertEqual(refusal(uncertified), ('PCA_RECONSTRUCTION_UNCERTIFIED', '$.channels[1]'))
            try:
                a.native_refusal(directory, 'compute', cause, config, data)
            except SchemaxisError as error:
                self.assertIn('8.8', error.fault.recovery)
            values = list(prediction['values'])
            spectral = {'code': 'PCA_COMPONENT_BELOW_RESOLUTION', 'message': 'm', 'location': '$.retention',
                        'details': {'eigenvalues': values, 'totalVariance': prediction['stats']['total']}}
            self.assertEqual(refusal(spectral)[0], 'VERIFICATION_FAILED')        # host rule accepts K=4 here
            self.assertEqual(refusal({**spectral, 'code': 'PCA_SPECTRUM_BORDERLINE'})[0], 'VERIFICATION_FAILED')
            self.assertEqual(refusal({'code': 'PCA_INVALID_NUMBER', 'message': 'm', 'location': 'line 2 column 2', 'details': {}})[0], 'VERIFICATION_FAILED')
            self.assertEqual(refusal({'code': 'SOMETHING_ELSE', 'message': 'm', 'location': '$', 'details': {}})[0], 'VERIFICATION_FAILED')
            self.assertEqual(refusal({'code': 'PCA_VALUE_RANGE', 'message': 'm', 'location': 'published:scores.csv row 1 column PC1', 'details': {}}),
                             ('PCA_VALUE_RANGE', 'published:scores.csv row 1 column PC1'))
            (directory / 'compute-fault.json').write_text('{"code": NaN}')
            self.assertEqual(code(lambda: a.native_refusal(directory, 'compute', cause, config, data))[0], 'VERIFICATION_FAILED')

    def test_outcomes_never_pass_as_satisfied_deliverables(self):
        p = a.plan(baseline())
        base = {'outcome': 'accepted', 'certification': {'ratio': [0.1] * 4, 'uncertifiedChannels': []},
                'requirements': {'status': {'minimumExplainedVariance': 'met', 'reconstructionRMS.ch1': 'met'}, 'overall': 'met'}}
        self.assertIsNone(a.outcome_fault(p, base))
        unmet = copy.deepcopy(base); unmet['outcome'] = 'requirementsUnmet'; unmet['requirements']['status']['reconstructionRMS.ch1'] = 'unmet'
        self.assertEqual(code(lambda: a.outcome_fault(p, unmet)), ('PCA_REQUIREMENT_NOT_MET', '$.requirements.reconstructionRMS[0].maximum'))
        unknown = copy.deepcopy(base); unknown['outcome'] = 'requirementsIndeterminate'; unknown['requirements']['status']['minimumExplainedVariance'] = 'indeterminate'
        self.assertEqual(code(lambda: a.outcome_fault(p, unknown)), ('PCA_REQUIREMENT_INDETERMINATE', '$.requirements.minimumExplainedVariance'))
        uncertified = copy.deepcopy(base); uncertified['outcome'] = 'uncertified'
        uncertified['certification'] = {'ratio': [0.1, 7.16, 0.1, 0.1], 'uncertifiedChannels': ['ch2']}
        self.assertEqual(code(lambda: a.outcome_fault(p, uncertified)), ('PCA_RECONSTRUCTION_UNCERTIFIED', '$.channels[1]'))

    def test_reuse_identity_tracks_source_bytes_and_refuses_links(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'sensors.csv'
            source.write_bytes(SENSORS.read_bytes())
            doc = baseline(source=str(source))
            before = a.reusableInputs(doc)
            self.assertEqual(list(before), [str(source)])
            source.write_text(source.read_text().replace('103.75', '103.5', 1))
            self.assertNotEqual(a.reusableInputs(doc), before)
            link = Path(folder) / 'link.csv'
            link.symlink_to(source)
            self.assertEqual(code(lambda: a.reusableInputs(baseline(source=str(link))))[0], 'PCA_INVALID_SOURCE')

    def test_native_command_is_run_relative_and_exact(self):
        self.assertEqual(a.command('/opt/numpy/bin/python', 'compute'), ['/opt/numpy/bin/python', '-I', '-B', 'native-worker.py', 'compute'])
        self.assertNotEqual(a.command('/opt/numpy/bin/python', 'readback'), a.command('/opt/numpy/bin/python', 'compute'))

    def test_runtime_binding_names_the_interpreter_path_digest(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            p = a.plan(baseline())
            for name, _ in a.publications(p):
                (directory / name).write_bytes(name.encode())
            summary = {'parsedDigest': 'd', 'runtime': {'numpy': '2.5.4', 'blas': 'OpenBLAS 0.3.34', 'python': '3.12.15'}}
            runtime = a.bindings(directory, p, b'x', summary, {'nativeCommand': a.command('/opt/py', 'compute')})['runtime']
            self.assertNotIn('executableDigest', runtime)
            self.assertEqual(runtime['executablePathDigest'], hashlib.sha256(b'/opt/py').hexdigest())

    def test_publication_check_is_location_independent_but_digest_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            run, moved = Path(folder) / 'run', Path(folder) / 'exported/run'
            p = a.plan(baseline())
            for directory in (run, moved):
                directory.mkdir(parents=True)
                for name, _ in a.publications(p):
                    (directory / name).write_bytes(name.encode())
            recorded = a.artifacts(run, p)
            self.assertTrue(a.portable_artifacts(recorded, run, p))
            self.assertTrue(a.portable_artifacts(recorded, moved, p))
            name = a.publications(p)[0][0]
            (moved / name).write_bytes(b'changed')
            self.assertFalse(a.portable_artifacts(recorded, moved, p))
            (moved / name).write_bytes(name.encode())
            mutants = [recorded[::-1], recorded[:-1], [{**recorded[0], 'kind': 'image'}, *recorded[1:]],
                       [{**recorded[0], 'file': str(Path(folder) / 'other' / name)}, *recorded[1:]],
                       [{**recorded[0], 'file': name}, *recorded[1:]], [{**recorded[0], 'extra': 1}, *recorded[1:]], None]
            for mutant in mutants:
                self.assertFalse(a.portable_artifacts(mutant, moved, p))

    def retained_run(self, folder, source):
        import hashlib
        from schemaxis.artifacts import atomic_json
        doc = baseline(source=str(source))
        run = Path(folder) / 'run'
        run.mkdir()
        data = SENSORS.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        atomic_json(run / 'authored.json', doc)
        atomic_json(run / 'plan.json', a.plan(doc))
        (run / 'source.csv').write_bytes(data)
        atomic_json(run / 'capture.json', {'source': str(source), 'bytes': len(data), 'sha256': sha})
        atomic_json(run / 'compute-inputs.json', {'source.csv': sha, 'native-config.json': 'c' * 64, 'native-worker.py': 'w' * 64})
        atomic_json(run / 'pca-verification.json', {'bindings': {'source': sha}})
        return doc, run, sha

    def test_retained_inputs_come_from_the_capture_not_the_original(self):
        from schemaxis.parallel import retained_inputs
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'removed.csv'
            doc, run, sha = self.retained_run(folder, source)
            self.assertFalse(source.exists())
            self.assertEqual(a.retainedInputs(run, doc), {str(source): sha})
            # The shared scheduler reaches the hook through adaptor.json.
            self.assertEqual(retained_inputs(run, doc), {str(source): sha})
            source.write_text('changed original\n')
            self.assertEqual(a.retainedInputs(run, doc), {str(source): sha})
            self.assertNotEqual(a.reusableInputs(doc), {str(source): sha})

    def test_retained_inputs_refuse_partial_missing_or_foreign_bindings(self):
        from schemaxis.artifacts import atomic_json
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'sensors.csv'
            doc, run, sha = self.retained_run(folder, source)
            saved = {path: path.read_bytes() for path in run.iterdir()}
            def json_edit(name, change):
                def apply():
                    value = json.loads((run / name).read_text()); change(value); atomic_json(run / name, value)
                return apply
            mutants = {
                'capture missing': lambda: (run / 'capture.json').unlink(),
                'capture without bytes': json_edit('capture.json', lambda v: v.pop('bytes')),
                'capture with extra key': json_edit('capture.json', lambda v: v.update(original=str(source))),
                'capture digest differs': json_edit('capture.json', lambda v: v.update(sha256='0' * 64)),
                'capture for another path': json_edit('capture.json', lambda v: v.update(source=str(Path(folder) / 'other.csv'))),
                'capture malformed': lambda: (run / 'capture.json').write_text('{"source": '),
                'capture not an object': lambda: (run / 'capture.json').write_text('[]'),
                'retained bytes changed': lambda: (run / 'source.csv').write_bytes(SENSORS.read_bytes().replace(b'103.75', b'103.76', 1)),
                'retained bytes missing': lambda: (run / 'source.csv').unlink(),
                'compute binding differs': json_edit('compute-inputs.json', lambda v: v.update({'source.csv': '1' * 64})),
                'compute binding missing': json_edit('compute-inputs.json', lambda v: v.pop('source.csv')),
                'host binding differs': json_edit('pca-verification.json', lambda v: v['bindings'].update(source='2' * 64)),
                'host binding missing': lambda: atomic_json(run / 'pca-verification.json', {}),
                'authored differs': json_edit('authored.json', lambda v: v.update(scaling='standardise')),
                'plan differs': json_edit('plan.json', lambda v: v.update(scaling='standardise')),
            }
            for label, change in mutants.items():
                with self.subTest(label):
                    change()
                    try:
                        self.assertEqual(code(lambda: a.retainedInputs(run, doc))[0], 'VERIFICATION_FAILED')
                    finally:
                        for path in run.iterdir():
                            if path not in saved: path.unlink()
                        for path, data in saved.items(): path.write_bytes(data)
            self.assertEqual(code(lambda: a.retainedInputs(run, baseline(source=str(Path(folder) / 'other.csv'))))[0], 'VERIFICATION_FAILED')
            self.assertEqual(a.retainedInputs(run, doc), {str(source): sha})

    def test_studio_templates_plan_and_undo(self):
        from schemaxis.adaptors import registry
        from schemaxis.console_session import AdaptorConsoleSession
        from schemaxis.studio_library import instantiate_item, load_library
        library = load_library('numpy')
        before = copy.deepcopy(library)
        for item in library['templates']:
            filled = instantiate_item(library, item, provider='numpy')
            self.assertEqual(registry.plan(filled)['operation'], 'principalComponents')
            with self.assertRaises(SchemaxisError):
                registry.plan(instantiate_item(library, item, provider='numpy', filled=False))
        self.assertEqual(library, before)
        with tempfile.TemporaryDirectory() as folder:
            session = AdaptorConsoleSession(folder, provider='numpy')
            try:
                original = session.document
                draft = session.draft()
                changed = {**original, 'scaling': 'standardise'}
                result = session.edit_source(json.dumps(changed), session.active_document, draft['revision'])
                self.assertFalse(result.get('diagnostics'))
                self.assertEqual(session.document['scaling'], 'standardise')
                session.undo()
                self.assertEqual(session.document, original)
            finally:
                session.close()


if __name__ == '__main__':
    unittest.main()
