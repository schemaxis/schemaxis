#!/usr/bin/env python3
"""Qualify NumPy principal component analysis through the public Schemaxis path.

Runs the shared conformance kit, analytic and reviewer cases with outcomes fixed in advance,
native fault injection, hostile saved-evidence mutants with refreshed ordinary hashes, a
NumPy-to-NumPy workflow handoff with reuse/invalidation and forged scheduler provenance, a
finite study, canonical API and CLI export with the original source removed (single runs,
a workflow and a study, verified normally), exported hostile and handoff mutants, and
in-flight timeout/cancellation. Host code is standard-library only; the native runtime is the
configured isolated Python (exactly NumPy 2.5.4 linked to OpenBLAS 0.3.34).
"""
import argparse
import copy
from fractions import Fraction as F
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors import registry
from schemaxis.adaptors.numpy import adaptor as a
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis.schema_snapshots import export_run
from schemaxis import workflow

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'examples/schemaxis'


# ---------------------------------------------------------------- deterministic fixtures

def dec(x):
    x = F(x); sign = '-' if x < 0 else ''; x = abs(x)
    den, twos, fives = x.denominator, 0, 0
    while den % 2 == 0: den //= 2; twos += 1
    while den % 5 == 0: den //= 5; fives += 1
    if den != 1: raise ValueError('not a finite decimal')
    digits = max(twos, fives); scaled = x * 10**digits
    s = str(scaled.numerator).rjust(digits + 1, '0')
    return sign + (s if digits == 0 else s[:-digits] + '.' + s[-digits:])


def hadamard(N):
    H = [[1]]
    while len(H) < N:
        H = [r + r for r in H] + [r + [-x for x in r] for r in H]
    return H


H64 = hadamard(64)


def givens(p, planes):
    R = [[F(int(i == j)) for j in range(p)] for i in range(p)]
    for a_, b_ in planes:
        G = [[F(int(i == j)) for j in range(p)] for i in range(p)]
        G[a_][a_], G[a_][b_], G[b_][a_], G[b_][b_] = F(3, 5), F(-4, 5), F(4, 5), F(3, 5)
        R = [[sum(R[i][k] * G[k][j] for k in range(p)) for j in range(p)] for i in range(p)]
    return R


BALANCED = [[F(x, 2) for x in row] for row in hadamard(4)]
ROTATED = givens(4, [(0, 1), (1, 2), (2, 3), (0, 3)])


def analytic(d, offsets, R, names, keyed=True):
    """Rows offsets + H[:,1..p] diag(d) R^T; returns CSV text and exact per-channel rank-K RMS."""
    p = len(d)
    lines = [','.join((['time'] if keyed else []) + names)]
    for i in range(64):
        row = [offsets[c] + sum(F(d[j]) * H64[i][j + 1] * R[c][j] for j in range(p)) for c in range(p)]
        lines.append(','.join(([dec(F(i, 2))] if keyed else []) + [dec(v) for v in row]))
    rms = lambda K, c: math.sqrt(float(sum(F(d[j]) ** 2 * R[c][j] ** 2 for j in range(K, p))))
    return '\n'.join(lines) + '\n', rms


def document(source, names, units='mV', *, scaling='none', retention=None, output='components', keyed=True,
             scales=None, eta=None, requirements=None):
    doc = {'version': a.VERSION, 'operation': a.OPERATION, 'source': str(source),
           'channels': [{'name': n, 'unit': units if isinstance(units, str) else units[i]} for i, n in enumerate(names)],
           'scaling': scaling, 'retention': retention or {'components': 2}, 'output': output}
    if keyed: doc['rowKey'] = {'name': 'time', 'unit': 's'}
    if scales: [c.update(scale=s) for c, s in zip(doc['channels'], scales)]
    if eta is not None: doc['loadingTolerance'] = eta
    if requirements: doc['requirements'] = requirements
    return doc


# ---------------------------------------------------------------- execution helpers

def native_pids(directory):
    pids = []
    for name in ('pca-summary.json', 'readback.json', 'compute-fault.json'):
        path = Path(directory) / name
        if path.is_file():
            value = json.loads(path.read_text())
            pid = value.get('runtime', {}).get('pid') if name == 'pca-summary.json' else value.get('pid')
            if pid: pids.append(pid)
    return pids


def run_case(directory, name, doc, locations, *, expect='accept', location=None, status=None):
    """Run through registry.run, then saved verification; require the outcome fixed in advance."""
    target = directory / name
    record = {'case': name, 'expect': expect}
    try:
        result = registry.run(doc, target, locations=locations, timeout=60)
        record['outcome'] = 'accept'
        record['result'] = {k: result.get(k) for k in ('verified', 'retained', 'requirements', 'runtime')}
    except SchemaxisError as error:
        record['outcome'], record['location'] = error.fault.code, error.fault.location
    record['nativePids'] = native_pids(target) if target.exists() else []
    if record['outcome'] != expect or (location and record.get('location') != location):
        raise AssertionError('unexpected outcome: ' + json.dumps(record))
    if (target / 'pca-verification.json').is_file():
        host = json.loads((target / 'pca-verification.json').read_text())['assessment']
        record['host'] = {'outcome': host['outcome'], 'status': host['requirements']['status'],
                          'rmsTolerance': host['requirements']['rmsTolerance'], 'reconstructionRMS': host['requirements']['reconstructionRMS'],
                          'certification': host['certification']['ratio']}
        if status is not None and host['requirements']['status'] != status:
            raise AssertionError('unexpected host statuses: ' + json.dumps(record))
        try:
            a.verify(target)
            record['savedVerify'] = 'verified'
        except SchemaxisError as error:
            record['savedVerify'] = error.fault.code
        if record['savedVerify'] != ('verified' if expect == 'accept' else expect):
            raise AssertionError('saved verification differs from run outcome: ' + json.dumps(record))
    return record


def refused(action, code='VERIFICATION_FAILED'):
    try:
        action()
    except SchemaxisError as error:
        if error.fault.code != code:
            raise AssertionError(error.fault.to_dict()) from error
        return code
    raise AssertionError('invalid evidence was accepted')


# ---------------------------------------------------------------- semantic cases

def cases(directory, locations):
    out = directory / 'cases'
    out.mkdir()
    results = []
    sensors = EXAMPLES / 'numpy-sensors.csv'
    names = ['ch1', 'ch2', 'ch3', 'ch4']
    add = lambda *args, **kw: results.append(run_case(out, *args, locations=locations, **kw))
    # Analytic sensors: requirement outcomes far from, inside and near the host band.
    m = math.sqrt(0.3125)
    add('sensors-requirement-unmet', document(sensors, names, requirements={'reconstructionRMS': [{'channel': 'ch1', 'maximum': 0.5}]}),
        expect='PCA_REQUIREMENT_NOT_MET', location='$.requirements.reconstructionRMS[0].maximum',
        status={'reconstructionRMS.ch1': 'unmet'})
    add('sensors-at-analytic-bound', document(sensors, names, requirements={'reconstructionRMS': [{'channel': 'ch2', 'maximum': m}]}),
        expect='PCA_REQUIREMENT_INDETERMINATE', location='$.requirements.reconstructionRMS[0].maximum',
        status={'reconstructionRMS.ch2': 'indeterminate'})
    add('sensors-explained-at-analytic-fraction', document(sensors, names, requirements={'minimumExplainedVariance': 16 / 17}),
        expect='PCA_REQUIREMENT_INDETERMINATE', location='$.requirements.minimumExplainedVariance',
        status={'minimumExplainedVariance': 'indeterminate'})
    # Near-zero RMS (reviewer N6c family): full retention, ideal residual exactly zero.
    add('full-retention-near-zero-bounds', document(sensors, names, retention={'components': 4},
        requirements={'reconstructionRMS': [{'channel': 'ch2', 'maximum': 1e-15}, {'channel': 'ch3', 'maximum': 1e-15},
                                            {'channel': 'ch4', 'maximum': 1e-300}]}),
        expect='PCA_REQUIREMENT_INDETERMINATE', status={'reconstructionRMS.ch2': 'indeterminate', 'reconstructionRMS.ch3': 'indeterminate',
                                                        'reconstructionRMS.ch4': 'indeterminate'})
    add('full-retention-tiny-but-supported-bound', document(sensors, names, retention={'components': 4},
        requirements={'reconstructionRMS': [{'channel': 'ch1', 'maximum': 1e-9}]}), status={'reconstructionRMS.ch1': 'met'})
    add('full-retention-subspace-near-zero', document(sensors, names, retention={'components': 4}, output='subspace',
        requirements={'reconstructionRMS': [{'channel': 'ch1', 'maximum': 1e-15}]}),
        expect='PCA_REQUIREMENT_INDETERMINATE', status={'reconstructionRMS.ch1': 'indeterminate'})
    # O1: bounds inside the host band (fixed fractions of the host tolerance) must be indeterminate.
    probe = run_case(out, 'o1-measurement', document(sensors, names, retention={'components': 3}), locations)
    results.append(probe)
    rms, tol = probe['host']['reconstructionRMS'], probe['host']['rmsTolerance']
    o1 = [{'channel': 'ch1', 'maximum': rms[0] + 0.4 * tol[0]}, {'channel': 'ch2', 'maximum': rms[1] - 0.4 * tol[1]},
          {'channel': 'ch3', 'maximum': rms[2] + 3 * tol[2]}, {'channel': 'ch4', 'maximum': rms[3] - 3 * tol[3]}]
    add('o1-inside-and-outside-host-band', document(sensors, names, retention={'components': 3}, requirements={'reconstructionRMS': o1}),
        expect='PCA_REQUIREMENT_NOT_MET', status={'reconstructionRMS.ch1': 'indeterminate', 'reconstructionRMS.ch2': 'indeterminate',
                                                  'reconstructionRMS.ch3': 'met', 'reconstructionRMS.ch4': 'unmet'})
    # P3: near-degenerate partial retention, eta 1e-2; the first-order subspace term dominates.
    text, ideal = analytic([F(4), F(2), F('1.999999999375'), F(1)], [F(10), F(-5), F(2), F('0.5')], ROTATED, names, keyed=False)
    p3 = out / 'p3.csv'; p3.write_text(text)
    bounds = [ideal(2, 0) * (1 + 1e-6), ideal(2, 1) * (1 - 1e-6), ideal(2, 2) * (1 + 1e-3), ideal(2, 3) * (1 - 1e-3)]
    p3_status = {'reconstructionRMS.ch1': 'indeterminate', 'reconstructionRMS.ch2': 'indeterminate',
                 'reconstructionRMS.ch3': 'met', 'reconstructionRMS.ch4': 'unmet'}
    for output in ('components', 'subspace'):
        add('p3-near-degenerate-' + output, document(p3, names, keyed=False, output=output, eta=1e-2,
            requirements={'reconstructionRMS': [{'channel': n, 'maximum': b} for n, b in zip(names, bounds)]}),
            expect='PCA_REQUIREMENT_NOT_MET', status=p3_status)
    # Spectral refusals and subspace acceptance on exact constructions.
    rep_text, _ = analytic([F(3), F(3), F(1), F('0.5')], [F(0)] * 4, BALANCED, names)
    repeated = out / 'repeated.csv'; repeated.write_text(rep_text)
    add('repeated-k1-components', document(repeated, names, retention={'components': 1}), expect='PCA_DEGENERATE_COMPONENT', location='$.retention')
    add('repeated-k1-subspace', document(repeated, names, retention={'components': 1}, output='subspace'),
        expect='PCA_RETENTION_SPLITS_CLUSTER', location='$.retention')
    add('repeated-k2-subspace', document(repeated, names, retention={'components': 2}, output='subspace'))
    lines = sensors.read_text().splitlines()
    rank = [lines[0]] + [','.join(r.split(',')[:4] + [dec(F(r.split(',')[1]) + F(r.split(',')[2]))]) for r in lines[1:]]
    deficient = out / 'rank-deficient.csv'; deficient.write_text('\n'.join(rank) + '\n')
    add('rank-deficient-k4', document(deficient, names, retention={'components': 4}), expect='PCA_COMPONENT_BELOW_RESOLUTION', location='$.retention')
    add('rank-deficient-k3', document(deficient, names, retention={'components': 3}))
    # E1/E2/E3: extreme cross-channel declared scales (both scaled spreads inside the contract).
    pm = out / 'pm.csv'
    pm.write_text('a,b\n' + ''.join(f'{H64[i][1]},{H64[i][2]}\n' for i in range(64)))
    for label, sa, expect, where in (('e1-cross-ratio-1e7', 1e-7, 'accept', None),
                                     ('e2-cross-ratio-1e9-host-certification', 1e-9, 'PCA_RECONSTRUCTION_UNCERTIFIED', '$.channels[1]'),
                                     ('e3-cross-ratio-1e10-native-refusal', 1e-10, 'PCA_RECONSTRUCTION_UNCERTIFIED', '$.channels[1]')):
        add(label, document(pm, ['a', 'b'], ['V', 'Pa'], keyed=False, scaling='declared', scales=[sa, 1.0], retention={'components': 1}),
            expect=expect, location=where)
    published = (out / 'e2-cross-ratio-1e9-host-certification' / 'pca-summary.json').is_file()
    assert published and not (out / 'e3-cross-ratio-1e10-native-refusal' / 'pca-summary.json').exists()
    # Synthetic captured-style drift near the offset limit, and a quiet channel beyond it.
    drift = json.loads((EXAMPLES / 'numpy-pressure-drift.json').read_text())
    drift['source'] = str(EXAMPLES / 'numpy-pressure-drift.csv')
    add('drift-standardised', drift, status={'minimumExplainedVariance': 'met', 'reconstructionRMS.p1': 'met'})
    rows = (EXAMPLES / 'numpy-pressure-drift.csv').read_text().splitlines()
    quiet = [rows[0]] + [','.join(r.split(',')[:-1] + ['101340.0' + ('1' if i % 2 else '2')]) for i, r in enumerate(rows[1:])]
    (out / 'quiet.csv').write_text('\n'.join(quiet) + '\n')
    add('drift-quiet-channel', {**drift, 'source': str(out / 'quiet.csv')}, expect='PCA_CHANNEL_SPREAD', location='$.channels[5]')
    # Host refusals before launch (no native process).
    for label, change, code, where in (
            ('raw-above-range', ('103.75', '1e49'), 'PCA_VALUE_RANGE', 'line 2 column 2'),
            ('quoted-cell', ('103.75', '"103.75"'), 'PCA_INVALID_CSV', 'line 2'),
            ('nan-cell', ('103.75', 'nan'), 'PCA_INVALID_NUMBER', 'line 2 column 2'),
            ('digit-separator', ('103.75', '1_03.75'), 'PCA_INVALID_NUMBER', 'line 2 column 2')):
        path = out / (label + '.csv'); path.write_text(sensors.read_text().replace(*change, 1))
        add(label, document(path, names), expect=code, location=where)
    scaled = out / 'scaled-spread.csv'; scaled.write_text(sensors.read_text())
    add('scaled-spread-above-range', document(scaled, names, scaling='declared', scales=[1e-48, 1.0, 1.0, 1.0]),
        expect='PCA_SCALE_RANGE', location='$.channels[0]')
    for record in results:
        if record['outcome'] in ('PCA_VALUE_RANGE', 'PCA_INVALID_CSV', 'PCA_INVALID_NUMBER', 'PCA_SCALE_RANGE', 'PCA_CHANNEL_SPREAD'):
            assert not record['nativePids'], 'host refusal launched native code'
    return results


# ---------------------------------------------------------------- native fault injection

FAULTS = r'''
import importlib.util, json, math, os, sys, tempfile
spec = importlib.util.spec_from_file_location('worker', sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
import numpy as np
out = {'pid': os.getpid(), 'numpy': np.__version__,
       'foreign': sorted(k for k in sys.modules if k.split('.')[0] in ('qgis', 'FreeCAD', 'PyQt5', 'PyQt6', 'osgeo', 'paraview'))}
def trial(name, fn):
    try: fn(); out[name] = 'NO_FAULT'
    except m.Fault as f: out[name] = f.payload['code'] + ' @ ' + f.payload['location']
    except Exception as e: out[name] = 'UNSTRUCTURED ' + type(e).__name__
trial('intermediateInf', lambda: m.intermediate('Z', np.array([[1.0, math.inf]])))
trial('intermediateNan', lambda: m.intermediate('eigenvalues', np.array([1.0, math.nan])))
trial('intermediateOver', lambda: m.intermediate('singularValues', np.array([1e101])))
trial('totalNotPositive', lambda: m.intermediate('totalVariance', 0.0, positive=True))
trial('policySubnormal', lambda: m.policy(64, 4, 1e-300, 1e-6))
trial('publishedOver', lambda: m.published_check('scores.csv', ['row', 'PC1'], [[1.0, 1e101]]))
trial('publishedNan', lambda: m.published_check('reconstruction.csv', ['row', 'a'], [[1.0, math.nan]]))
trial('summaryInf', lambda: m.summary_range_check({'a': [1.0, {'b': math.inf}]}, 'pca-summary.json'))
base = {'channels': [{'name': 'a', 'unit': 'V'}, {'name': 'b', 'unit': 'V'}], 'scaling': 'none', 'retention': {'components': 1},
        'output': 'components', 'loadingTolerance': 1e-6}
trial('scaleZero', lambda: m.validate_config({**base, 'scaling': 'declared', 'channels': [{'name': 'a', 'unit': 'V', 'scale': 0}, {'name': 'b', 'unit': 'V', 'scale': 1}]}))
trial('scaleBoolean', lambda: m.validate_config({**base, 'scaling': 'declared', 'channels': [{'name': 'a', 'unit': 'V', 'scale': True}, {'name': 'b', 'unit': 'V', 'scale': 1}]}))
trial('componentsBoolean', lambda: m.validate_config({**base, 'retention': {'components': True}}))
trial('etaRange', lambda: m.validate_config({**base, 'loadingTolerance': 0.5}))
os.environ['OPENBLAS_NUM_THREADS'] = '4'; trial('threadsNotCapped', m.runtime_identity); os.environ['OPENBLAS_NUM_THREADS'] = '1'
with tempfile.TemporaryDirectory() as d:
    os.chdir(d)
    for label, text in (('readbackInf', 'component,eigenvalue\n1,inf\n'), ('readbackOver', 'component,eigenvalue\n1,1e101\n'),
                        ('readbackIndexFloat', 'component,eigenvalue\n1.0,2.0\n'), ('readbackWhitespace', 'component,eigenvalue\n1, 2.0\n'),
                        ('readbackAccepted', 'component,eigenvalue\n1,2.0\n')):
        open('spectrum.csv', 'w').write(text)
        try: m.parse_table('spectrum.csv', True); out[label] = 'ACCEPTED'
        except ValueError as e: out[label] = 'REJECTED'
    try: m.strict_json('{"a": NaN}'); out['strictJsonNan'] = 'ACCEPTED'
    except ValueError: out['strictJsonNan'] = 'REJECTED'
print(json.dumps(out))
'''


def fault_injection(directory, executable):
    script = directory / 'fault-injection.py'
    script.write_text(FAULTS)
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', **{k: '1' for k in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')}}
    done = subprocess.run([executable, '-I', '-B', str(script), str(ROOT / 'src/schemaxis/adaptors/numpy/native_worker.py')],
                          capture_output=True, text=True, env=env, timeout=60, start_new_session=True)
    if done.returncode != 0:
        raise AssertionError('fault injection failed: ' + done.stderr[-2000:])
    result = json.loads(done.stdout)
    expected_reject = [k for k in result if k.startswith('readback') and k != 'readbackAccepted'] + ['strictJsonNan']
    assert result['foreign'] == [] and result['readbackAccepted'] == 'ACCEPTED'
    assert all(result[k] == 'REJECTED' for k in expected_reject)
    structured = [k for k in result if k not in ('pid', 'numpy', 'foreign') and not k.startswith('readback') and k != 'strictJsonNan']
    assert all(result[k].startswith(('PCA_VALUE_RANGE @ ', 'PCA_INVALID_CONTRACT @ ', 'PCA_UNSUPPORTED_RUNTIME @ ')) for k in structured), result
    return result


# ---------------------------------------------------------------- hostile saved evidence

def refresh(directory, *, native=True):
    """Refresh every ordinary hash: native summary digests, consumed-input bindings, receipt and metadata."""
    directory = Path(directory)
    plan = a.read(directory, 'plan.json')
    if native:
        summary = a.read(directory, 'pca-summary.json')
        summary['files'] = {name: a.digest(directory, name) for name in summary['files']}
        atomic_json(directory / 'pca-summary.json', summary)
        bindings = a.read(directory, 'readback-inputs.json')
        bindings = {name: a.digest(directory, name) for name in bindings}
        atomic_json(directory / 'readback-inputs.json', bindings)
    receipt = a.read(directory, 'verification.json')
    # Refresh digests only: recorded publication locations are kept, never rebased onto this copy.
    receipt['artifacts'] = [{**item, 'sha256': a.digest(directory, Path(item['file']).name)} for item in receipt['artifacts']]
    receipt['evidence'] = {name: a.digest(directory, name) for name in receipt['evidence']}
    atomic_json(directory / 'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    manifest = directory / 'publication-metadata.json'
    origin = json.loads(manifest.read_text()).get('recordedDirectory') if manifest.is_file() else None
    finalise(directory)
    if origin is not None:
        atomic_json(manifest, {**json.loads(manifest.read_text()), 'recordedDirectory': origin})


def tilt(target, angle=0.05):
    """Self-consistent wrong publication: PC1 tilted toward the discarded PC3, with scores,
    reconstruction, retained Rayleigh quotients, fractions and summary measurements recomputed."""
    from schemaxis.adaptors.numpy import oracle
    plan = a.read(target, 'plan.json'); config = a.native_config(plan)
    data = (target / 'source.csv').read_bytes()
    keys, rows = oracle.parse(data, config)
    v3 = oracle.predict(config, data)['vectors'][2]
    summary = a.read(target, 'pca-summary.json')
    mu, sc = summary['means'], summary['scales']
    lines = (target / 'loadings.csv').read_text().splitlines()
    V = [[float(x) for x in line.split(',')[1:]] for line in lines[1:]]
    c, s_ = math.cos(angle), math.sin(angle)
    V[0] = [c * x + s_ * y for x, y in zip(V[0], v3)]
    Z = [[(x - m) / q for x, m, q in zip(r, mu, sc)] for r in rows]
    T = [[math.fsum(z * v for z, v in zip(zr, vk)) for vk in V] for zr in Z]
    R = [[m + q * math.fsum(T[i][k] * V[k][j] for k in range(len(V))) for j, (m, q) in enumerate(zip(mu, sc))] for i in range(len(rows))]
    n = len(rows)
    lam = [float(line.split(',')[1]) for line in (target / 'spectrum.csv').read_text().splitlines()[1:]]
    rq = [math.fsum(t[k] ** 2 for t in T) / (n - 1) for k in range(len(V))]
    lam = rq + [lam[len(V)] + math.fsum(lam[:len(V)]) - math.fsum(rq)] + lam[len(V) + 1:]
    whole = math.fsum(lam)
    write = lambda name, header, body, integer: (target / name).write_text(','.join(header) + '\n' + ''.join(
        ','.join([str(int(r[0])) if integer else repr(r[0])] + [repr(x) for x in r[1:]]) + '\n' for r in body))
    write('loadings.csv', lines[0].split(','), [[k + 1, *v] for k, v in enumerate(V)], True)
    write('scores.csv', ['time', 'PC1', 'PC2'], [[keys[i], *T[i]] for i in range(n)], False)
    write('reconstruction.csv', ['time', *[ch['name'] for ch in config['channels']]], [[keys[i], *R[i]] for i in range(n)], False)
    write('spectrum.csv', ['component', 'eigenvalue', 'varianceFraction', 'cumulativeFraction'],
          [[k + 1, x, x / whole, math.fsum(lam[:k + 1]) / whole] for k, x in enumerate(lam)], True)
    summary['explainedFraction'] = math.fsum(lam[:len(V)]) / whole
    summary['reconstructionRMS'] = [math.sqrt(math.fsum((rows[i][j] - R[i][j]) ** 2 for i in range(n)) / n) for j in range(len(mu))]
    summary['residualVariance'] = math.fsum(((rows[i][j] - R[i][j]) / sc[j]) ** 2 for i in range(n) for j in range(len(mu))) / (n - 1)
    atomic_json(target / 'pca-summary.json', summary)


def hostile(baseline, variant, declared, failed):
    results = {}
    def mutate(label, source, change, *, native=True, expect='VERIFICATION_FAILED'):
        # Mutate the original run in place and restore every byte, so the shared publication
        # metadata stays owned by this directory and each mutant meets its intended check.
        source = Path(source)
        saved = {path: path.read_bytes() for path in source.rglob('*') if path.is_file()}
        try:
            change(source)
            refresh(source, native=native)
            try:
                a.verify(source)
            except SchemaxisError as error:
                if error.fault.code != expect:
                    raise AssertionError(label + ': ' + json.dumps(error.fault.to_dict())) from error
                results[label] = {'fault': error.fault.code, 'message': error.fault.message, 'location': error.fault.location}
            else:
                raise AssertionError(label + ': mutant accepted')
        finally:
            for path in [p for p in source.rglob('*') if p.is_file() and p not in saved]:
                path.unlink()
            for path, data in saved.items():
                path.write_bytes(data)
    def edit_json(name, fn):
        def apply(target):
            value = a.read(target, name); fn(value); atomic_json(target / name, value)
        return apply
    def edit_csv(name, row, column, fn):
        def apply(target):
            lines = (target / name).read_text().splitlines()
            cells = lines[row].split(','); cells[column] = repr(fn(float(cells[column]))); lines[row] = ','.join(cells)
            (target / name).write_text('\n'.join(lines) + '\n')
        return apply
    # Re-aimed status mutants: the host record is the sole decision and is recomputed.
    mutate('hostRecordStatusFlipped', baseline, edit_json('pca-verification.json',
           lambda v: v['assessment']['requirements']['status'].update({'reconstructionRMS.ch1': 'unmet'})), native=False)
    mutate('hostRecordToleranceShrunk', baseline, edit_json('pca-verification.json',
           lambda v: v['assessment']['requirements'].update(rmsTolerance=[t * 1e-6 for t in v['assessment']['requirements']['rmsTolerance']])), native=False)
    mutate('hostRecordOutcomeAccepted', failed, edit_json('pca-verification.json',
           lambda v: v['assessment'].update(outcome='accepted')), native=False)
    def foreign(target):
        shutil.copy(Path(variant) / 'pca-verification.json', target / 'pca-verification.json')
    mutate('foreignHostRecord', baseline, foreign, native=False)
    mutate('nativeSummaryCarriesStatus', baseline, edit_json('pca-summary.json', lambda v: v.update(status={'reconstructionRMS.ch1': 'met'})))
    # Stale record: a publication changes and every ordinary hash is refreshed.
    mutate('staleRecordAfterReconstructionEdit', baseline, edit_csv('reconstruction.csv', 1, 1, lambda x: x + 1e-6))
    mutate('tiltedLoadingsRefreshed', baseline, edit_csv('loadings.csv', 1, 1, lambda x: x + 0.01))
    mutate('eigenvalueDenominatorN', baseline, edit_csv('spectrum.csv', 1, 1, lambda x: x * 63 / 64))
    mutate('meanShiftedInSummary', baseline, edit_json('pca-summary.json', lambda v: v['means'].__setitem__(0, v['means'][0] + 0.01)))
    mutate('declaredScaleChangedInSummary', declared, edit_json('pca-summary.json', lambda v: v['scales'].__setitem__(1, v['scales'][1] * 10)))
    mutate('projectorAltered', variant, edit_csv('projector.csv', 1, 1, lambda x: x + 1e-3))
    def capture(target):
        path = target / 'source.csv'; text = path.read_text().replace('103.75', '103.76', 1); path.write_text(text)
        atomic_json(target / 'capture.json', {**a.read(target, 'capture.json'), 'sha256': a.digest(target, 'source.csv')})
        inputs = a.read(target, 'compute-inputs.json'); inputs['source.csv'] = a.digest(target, 'source.csv')
        atomic_json(target / 'compute-inputs.json', inputs)
    mutate('capturedSourceChangedRehashed', baseline, capture)
    mutate('readbackDeclaredFailure', baseline, edit_json('readback.json', lambda v: v.update(ok=False)), native=False)
    mutate('readbackForeignBlas', baseline, edit_json('readback.json', lambda v: v['runtime'].update(blas='OpenBLAS 0.3.30')), native=False)
    mutate('runtimeObservationChanged', baseline, edit_json('pca-summary.json', lambda v: v['runtime'].update(numpy='2.5.3')))
    def promote(target):
        atomic_json(target / 'result.json', {'status': 'succeeded', 'verified': True})
    mutate('requirementFailurePromotedToSuccess', failed, promote, native=False, expect='PCA_REQUIREMENT_NOT_MET')
    mutate('consistentTiltedSubspace', baseline, tilt)
    for label, change in command_mutants(baseline).items():
        mutate(label, baseline, change)
    for run in (baseline, variant, declared):
        a.verify(run)
    refused(lambda: a.verify(failed), 'PCA_REQUIREMENT_NOT_MET')
    return results


def command_mutants(baseline):
    """Changed launch commands and worker bytes, each with every ordinary hash refreshed."""
    executable = a.read(baseline, 'verification.json')['executable']
    def submission(stage, argv):
        def apply(target):
            value = a.read(target, stage + '-submission.json'); value['nativeCommand'] = argv(target); atomic_json(target / (stage + '-submission.json'), value)
        return apply
    def worker(target):
        path = target / 'native-worker.py'; path.write_text(path.read_text() + '# altered\n')
        for name in ('compute-inputs.json', 'readback-inputs.json'):
            value = a.read(target, name); value['native-worker.py'] = a.digest(target, 'native-worker.py'); atomic_json(target / name, value)
    return {'commandAbsoluteWorkerPath': submission('compute', lambda t: [executable, '-I', '-B', str(t / 'native-worker.py'), 'compute']),
            'commandWithoutIsolation': submission('readback', lambda t: [executable, '-B', 'native-worker.py', 'readback']),
            'commandForeignInterpreter': submission('compute', lambda t: ['/usr/bin/python3', '-I', '-B', 'native-worker.py', 'compute']),
            'workerBytesChangedRehashed': worker}


# ---------------------------------------------------------------- canonical portable export

def saved(action):
    try:
        return {'verified': bool(action()['verified'])}
    except SchemaxisError as error:
        return {'fault': error.fault.code, 'message': error.fault.message}


def verified(action, label):
    outcome = saved(action)
    if outcome != {'verified': True}:
        raise AssertionError(label + ': ' + json.dumps(outcome))
    return outcome


def cli(*args):
    """Normal command-line entry point in a separate host process (never NumPy)."""
    done = subprocess.run([sys.executable, '-B', '-m', 'schemaxis', *map(str, args)], capture_output=True, text=True, timeout=300,
                          env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')})
    try:
        value = json.loads(done.stdout)
    except ValueError:
        value = None
    return {'exitCode': done.returncode, 'result': value, 'stderr': done.stderr[-2000:]}


def cli_verified(directory, label):
    outcome = cli('verify', directory)
    if outcome['exitCode'] != 0 or not isinstance(outcome['result'], dict) or outcome['result'].get('verified') is not True:
        raise AssertionError(label + ': ' + json.dumps(outcome))
    return {'exitCode': 0, 'verified': True}


def cli_backup(root, run, destination):
    """Reviewed storage plan, applied with its confirmation digest: the normal CLI canonical export."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    plan_path = destination.with_name(destination.name + '-plan.json')
    planned = cli('storage', 'plan', '--action', 'backup', '--root', root, '--run', run, '--destination', destination, '--save', plan_path)
    if planned['exitCode'] != 0:
        raise AssertionError('storage plan: ' + json.dumps(planned))
    applied = cli('storage', 'apply', plan_path, '--confirm', json.loads(plan_path.read_text())['confirmation'])
    if applied['exitCode'] != 0:
        raise AssertionError('storage apply: ' + json.dumps(applied))
    return destination / 'data' / run


def portable_export(directory, locations, legacy):
    """Run baseline and variant from disposable sources, export canonically, remove the sources, verify normally."""
    import hashlib
    root = directory / 'export'
    inputs = root / 'input'; inputs.mkdir(parents=True)
    report = {'runs': {}}
    exported = {}
    captured = {}
    for name, example in (('baseline', 'numpy-sensors.json'), ('variant', 'numpy-sensors-standardised.json')):
        source = inputs / (name + '.csv')
        source.write_bytes((EXAMPLES / 'numpy-sensors.csv').read_bytes())
        doc = json.loads((EXAMPLES / example).read_text()); doc['source'] = str(source)
        result = registry.run(doc, root / name, locations=locations, timeout=60)
        commands = [a.read(root / name, stage + '-submission.json')['nativeCommand'] for stage in a.STAGES]
        assert commands == [a.command(locations['numpy'], stage) for stage in a.STAGES], commands
        captured[name] = {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}
        exported[name] = {'api': root / 'exported' / name, 'cli': cli_backup(root, name, root / 'cli-backup' / name)}
        export_run(root / name, exported[name]['api'])
        report['runs'][name] = {'retained': result['retained'], 'requirements': result['requirements'], 'commands': commands,
                                'nativePids': native_pids(root / name)}
    for source in inputs.iterdir(): source.unlink()
    for name, copies in exported.items():
        record = report['runs'][name]
        for kind, target in copies.items():
            expected = json.loads((target / 'authored.json').read_text())
            assert not Path(expected['source']).exists()
            record[kind] = {'registryVerify': verified(lambda: registry.verify(target), name + ' ' + kind + ' export'),
                            'cliVerify': cli_verified(target, name + ' ' + kind + ' export'),
                            'retainedInputs': a.retainedInputs(target, expected)}
            assert record[kind]['retainedInputs'] == captured[name], record
        record['originalAfterSourceRemoval'] = verified(lambda: registry.verify(root / name), name + ' original')
        record['reuseAfterSourceRemoval'] = refused(lambda: a.reusableInputs(json.loads((root / name / 'authored.json').read_text())), 'PCA_INVALID_SOURCE')
    report['hostileExported'] = exported_hostile(root, exported['baseline']['api'], exported['variant']['api'])
    report['legacyReceipt'] = {}
    for label, run in legacy.items():
        copy_ = root / 'legacy' / label
        export_run(run, copy_)
        report['legacyReceipt'][label] = saved(lambda: registry.verify(copy_))
        assert report['legacyReceipt'][label].get('fault') == 'VERIFICATION_FAILED', report['legacyReceipt'][label]
    return report


def exported_hostile(root, baseline, variant):
    """Mutate independent exports, refresh every ordinary digest (recorded locations kept) and verify normally."""
    results = {}
    control = root / 'mutants' / 'controlExportOnly'
    export_run(baseline, control)
    results['controlExportOnly'] = verified(lambda: registry.verify(control), 'unmodified export')
    def capture(target):
        path = target / 'source.csv'; path.write_text(path.read_text().replace('103.75', '103.76', 1))
        atomic_json(target / 'capture.json', {**a.read(target, 'capture.json'), 'sha256': a.digest(target, 'source.csv')})
        inputs = a.read(target, 'compute-inputs.json'); inputs['source.csv'] = a.digest(target, 'source.csv')
        atomic_json(target / 'compute-inputs.json', inputs)
    def publication(target):
        lines = (target / 'reconstruction.csv').read_text().splitlines()
        cells = lines[1].split(','); cells[1] = repr(float(cells[1]) + 1e-6); lines[1] = ','.join(cells)
        (target / 'reconstruction.csv').write_text('\n'.join(lines) + '\n')
    def decision(target):
        value = a.read(target, 'pca-verification.json')
        value['assessment']['requirements']['status'].update({'reconstructionRMS.ch1': 'unmet'})
        atomic_json(target / 'pca-verification.json', value)
    def foreign(target):
        shutil.copy(Path(variant) / 'pca-verification.json', target / 'pca-verification.json')
    def binding(target):
        value = a.read(target, 'pca-verification.json')
        value['bindings']['runtime']['executablePathDigest'] = '0' * 64
        atomic_json(target / 'pca-verification.json', value)
    record = 'host verification record differs from recomputation (stale, foreign or altered)'
    mutants = {'sourceCaptureRehashed': (capture, True, 'independent verification failed: summary source digest equals captured bytes'),
               'publicationEditedRehashed': (publication, True, 'independent verification failed: reconstruction equals means + scale x retained projection'),
               'hostDecisionFlipped': (decision, False, record),
               'foreignHostDecision': (foreign, False, record),
               'interpreterPathDigestChanged': (binding, False, record)}
    expected = {'commandAbsoluteWorkerPath': 'native command or completion differs', 'commandWithoutIsolation': 'native command or completion differs',
                'commandForeignInterpreter': 'native command or completion differs', 'workerBytesChangedRehashed': 'trusted worker or native configuration differs'}
    mutants.update({label: (change, False, expected[label]) for label, change in command_mutants(baseline).items()})
    for label, (change, native, message) in mutants.items():
        target = root / 'mutants' / label
        export_run(baseline, target)
        change(target)
        refresh(target, native=native)
        outcome = saved(lambda: registry.verify(target))
        if outcome.get('fault') != 'VERIFICATION_FAILED' or outcome.get('message') != message:
            raise AssertionError(label + ': ' + json.dumps(outcome))
        results[label] = outcome
    return results


# ---------------------------------------------------------------- workflow, study and lifecycle

def producer(directory):
    result = json.loads((directory / 'result.json').read_text())
    return result, next(i for i, job in enumerate(result['jobs']) if job['operation'] == 'denoise')


def forge_input_hashes(directory, claimed):
    """Rewrite both scheduler records of the producer to claim other inputs; retained captures are untouched."""
    result, index = producer(directory)
    result['jobs'][index]['inputHashes'] = claimed
    atomic_json(directory / 'result.json', result)
    attempt = Path(result['jobs'][index]['directory'])
    job = json.loads((attempt / 'job.json').read_text()); job['inputHashes'] = claimed
    atomic_json(attempt / 'job.json', job)
    return attempt


def workflows(directory, locations):
    from schemaxis.parallel import reusable_inputs
    graph = json.loads((EXAMPLES / 'numpy-denoise-workflow.json').read_text())
    source = directory / 'sensors.csv'
    source.write_bytes((EXAMPLES / 'numpy-sensors.csv').read_bytes())
    graph['operations'][0]['document']['source'] = str(source)
    target = directory / 'workflow'
    first = workflow.execute(graph, target, locations=locations, timeout=60)
    assert workflow.verify(target)['verified']
    consumer = next(j for j in first['jobs'] if j['operation'] == 'reanalyse')
    spectrum = [line.split(',') for line in (Path(consumer['directory']) / 'spectrum.csv').read_text().splitlines()[1:]]
    lam = [float(r[1]) for r in spectrum]
    # The rank-2 reconstruction keeps the first two analytic eigenvalues and nothing else.
    assert abs(lam[0] - 1024 / 63) <= 1e-9 and abs(lam[1] - 256 / 63) <= 1e-9 and max(lam[2:]) <= 1e-12
    second = workflow.execute(graph, target, locations=locations, timeout=60, resume=True)
    assert all(j['reused'] for j in second['jobs'])
    # A real source change: saved verification still rests on the retained captures; reuse is invalidated.
    source.write_text(source.read_text().replace('103.75', '103.5', 1))
    after_change = verified(lambda: workflow.verify(target), 'saved workflow after its source changed')
    third = workflow.execute(graph, target, locations=locations, timeout=60, resume=True)
    assert not any(j['reused'] for j in third['jobs'])
    assert workflow.verify(target)['verified']
    # Forged scheduler provenance claims the next source bytes while the retained capture keeps the old bytes.
    source.write_text(source.read_text().replace('103.5', '103.25', 1))
    result, index = producer(target)
    stale = Path(result['jobs'][index]['directory'])
    forge_input_hashes(target, reusable_inputs(result['jobs'][index]['effective']))
    forged = saved(lambda: workflow.verify(target))
    assert forged == {'fault': 'VERIFICATION_FAILED', 'message': 'job input hashes differ from verified retained inputs'}, forged
    fourth = workflow.execute(graph, target, locations=locations, timeout=60, resume=True)
    assert not any(j['reused'] for j in fourth['jobs'])
    result, index = producer(target)
    fresh = Path(result['jobs'][index]['directory'])
    effective = result['jobs'][index]['effective']
    assert fresh != stale and a.retainedInputs(fresh, effective) == reusable_inputs(effective) == result['jobs'][index]['inputHashes']
    assert workflow.verify(target)['verified']
    blocked = copy.deepcopy(graph)
    blocked['operations'][0]['document']['requirements'] = {'reconstructionRMS': [{'channel': 'ch1', 'maximum': 0.1}]}
    outcome = refused(lambda: workflow.execute(blocked, directory / 'workflow-blocked', locations=locations, timeout=60), 'PCA_REQUIREMENT_NOT_MET')
    summaries = sorted(str(p.relative_to(directory)) for p in (directory / 'workflow-blocked').rglob('pca-summary.json'))
    assert len(summaries) <= 1, 'consumer ran after an unmet producer requirement: ' + repr(summaries)
    calc = json.loads((EXAMPLES / 'numpy-calc-workflow.json').read_text())
    calc['operations'][0]['document']['source'] = str(source)
    planned = workflow.validate(calc)
    study = json.loads((EXAMPLES / 'numpy-sensors.json').read_text())
    study['source'] = str(source)
    study.pop('requirements')
    study['axes'] = [{'name': 'k', 'values': [1, 2]}]
    study['retention'] = {'components': {'$axis': 'k'}}
    states = a.run(study, directory / 'study', executable=locations['numpy'], timeout=60)
    assert a.verify(directory / 'study')['verified'] and len(states['states']) == 2
    return {'nativeHandoffRank2': lam, 'unchangedReused': True, 'savedVerifyAfterSourceChange': after_change,
            'samePathChangedInvalidated': True, 'forgedInputHashes': {'verify': forged, 'resumeReusedForgedAttempt': False,
            'staleAttempt': stale.name, 'freshAttempt': fresh.name},
            'unmetProducerBlocksConsumer': outcome, 'calcHandoffHostPlanned': bool(planned), 'studyStates': 2}


def source_lifecycle(directory):
    """Export the workflow and study, remove their original source and verify every copy normally."""
    root = directory / 'export'
    copies = {'workflow': root / 'exported-workflow', 'study': root / 'exported-study'}
    export_run(directory / 'workflow', copies['workflow'])
    export_run(directory / 'study', copies['study'])
    cli_study = cli_backup(directory, 'study', root / 'cli-backup-study')
    (directory / 'sensors.csv').unlink()
    report = {'workflowOriginal': verified(lambda: workflow.verify(directory / 'workflow'), 'saved workflow without its source'),
              'workflowExported': verified(lambda: workflow.verify(copies['workflow']), 'exported workflow'),
              'workflowExportedCli': cli_verified(copies['workflow'], 'exported workflow'),
              'studyOriginal': verified(lambda: registry.verify(directory / 'study'), 'study without its source'),
              'studyExported': verified(lambda: registry.verify(copies['study']), 'exported study'),
              'studyCliBackup': cli_verified(cli_study, 'CLI backup of study')}
    report['handoffIntegrity'] = handoff_integrity(root, copies['workflow'])
    return report


def handoff_integrity(root, exported):
    """Tamper with independent copies of the exported workflow; each must fail normal workflow verification."""
    results = {}
    def attempt(target, operation):
        result = json.loads((target / 'result.json').read_text())
        index = next(i for i, job in enumerate(result['jobs']) if job['operation'] == operation)
        from schemaxis.run_paths import owned_path
        return result, index, owned_path(target, result['jobs'][index]['directory'], kind='directory')
    # The consumer's retained capture is exactly the producer's verified reconstruction publication.
    result, index, consumer = attempt(exported, 'reanalyse')
    handoff = result['jobs'][index]['handoffs'][0]
    consumed = a.read(consumer, 'capture.json')
    assert consumed['source'] == handoff['file'] and consumed['sha256'] == handoff['sha256'], (consumed, handoff)
    results['consumerCaptureEqualsHandoff'] = True
    def producer_publication(target):
        _, _, run = attempt(target, 'denoise')
        lines = (run / 'reconstruction.csv').read_text().splitlines()
        cells = lines[1].split(','); cells[1] = repr(float(cells[1]) + 1e-6); lines[1] = ','.join(cells)
        (run / 'reconstruction.csv').write_text('\n'.join(lines) + '\n')
        refresh(run)
    def consumer_capture(target):
        _, _, run = attempt(target, 'reanalyse')
        path = run / 'source.csv'; lines = path.read_text().splitlines()
        cells = lines[1].split(','); cells[1] = repr(float(cells[1]) + 1e-6); lines[1] = ','.join(cells)
        path.write_text('\n'.join(lines) + '\n')
        atomic_json(run / 'capture.json', {**a.read(run, 'capture.json'), 'bytes': path.stat().st_size, 'sha256': a.digest(run, 'source.csv')})
        inputs = a.read(run, 'compute-inputs.json'); inputs['source.csv'] = a.digest(run, 'source.csv')
        atomic_json(run / 'compute-inputs.json', inputs)
        refresh(run)
    def consumer_input_hashes(target):
        result, index, run = attempt(target, 'reanalyse')
        claimed = {key: '0' * 64 for key in result['jobs'][index]['inputHashes']}
        result['jobs'][index]['inputHashes'] = claimed
        atomic_json(target / 'result.json', result)
        job = json.loads((run / 'job.json').read_text()); job['inputHashes'] = claimed; atomic_json(run / 'job.json', job)
    def handoff_digest(target):
        result, index, _ = attempt(target, 'reanalyse')
        result['jobs'][index]['handoffs'][0]['sha256'] = '0' * 64
        atomic_json(target / 'result.json', result)
    mutants = {'producerPublicationEditedRehashed': (producer_publication, 'independent verification failed: reconstruction equals means + scale x retained projection'),
               'consumerCaptureEditedRehashed': (consumer_capture, 'independent verification failed: summary source digest equals captured bytes'),
               'consumerInputHashesForged': (consumer_input_hashes, 'job input hashes differ from verified retained inputs'),
               'handoffDigestForged': (handoff_digest, 'job handoff differs')}
    for label, (change, message) in mutants.items():
        target = root / 'workflow-mutants' / label
        export_run(exported, target)
        change(target)
        outcome = saved(lambda: workflow.verify(target))
        if outcome.get('fault') != 'VERIFICATION_FAILED' or outcome.get('message') != message:
            raise AssertionError(label + ': ' + json.dumps(outcome))
        results[label] = outcome
    return results


def lifecycle(directory, document_):
    wrapper, marker = directory / 'slow-runtime.py', directory / 'slow.pid'
    wrapper.write_text('#!' + sys.executable + '\nimport os,time\nfrom pathlib import Path\nPath(' + repr(str(marker)) + ').write_text(str(os.getpid()))\ntime.sleep(30)\n')
    wrapper.chmod(0o700)
    result = {}
    for action in ('timeout', 'cancel'):
        if marker.exists(): marker.unlink()
        event = threading.Event()
        def trigger():
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline: time.sleep(.01)
            if marker.exists(): event.set()
        thread = threading.Thread(target=trigger, daemon=True) if action == 'cancel' else None
        if thread: thread.start()
        try:
            with allocation({'threads': 1, 'ranks': 1}, event):
                result[action] = refused(lambda: a.run(document_, directory / ('inflight-' + action), executable=str(wrapper),
                                                       timeout=8 if thread else .6),
                                         'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')
        finally:
            if thread: thread.join(6)
        assert marker.exists(), 'owned child not launched'
        pid = int(marker.read_text())
        try: os.kill(pid, 0)
        except ProcessLookupError: pass
        else: raise AssertionError('child survived ' + action)
        result[action + 'ChildPid'] = pid
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--numpy', type=Path, required=True, help='Absolute isolated Python with NumPy 2.5.4 / OpenBLAS 0.3.34')
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--register', action='store_true')
    parser.add_argument('--legacy-run', type=Path, action='append', default=[],
                        help='Previously saved NumPy run to export read-only and require refusal under the current implementation')
    args = parser.parse_args()
    directory = args.output_directory.resolve(); directory.mkdir(parents=True, exist_ok=False)
    locations = {'numpy': str(args.numpy.absolute())}
    report = {'verified': False}
    try:
        receipt = qualify(a.VERSION, directory / 'kit', native=True, root=ROOT, locations=locations, timeout=60, wall_timeout=120)
        report['kit'] = {'verified': receipt['verified'], 'cases': [c['id'] for c in receipt['cases']], 'lifecycle': receipt['lifecycle']}
        report['cases'] = cases(directory, locations)
        report['faultInjection'] = fault_injection(directory, locations['numpy'])
        failed = directory / 'cases' / 'sensors-requirement-unmet'
        declared = directory / 'cases' / 'e1-cross-ratio-1e7'
        report['hostile'] = hostile(directory / 'kit/baseline', directory / 'kit/variant', declared, failed)
        report['workflow'] = workflows(directory, locations)
        report['portableExport'] = portable_export(directory, locations, {'legacy-' + str(i): run.resolve() for i, run in enumerate(args.legacy_run)})
        report['sourceLifecycle'] = source_lifecycle(directory)
        document_ = json.loads((EXAMPLES / 'numpy-sensors.json').read_text())
        document_['source'] = str(EXAMPLES / 'numpy-sensors.csv')
        report['inflightLifecycle'] = lifecycle(directory, document_)
        if args.register: register(directory / 'kit/qualification.json')
        report['verified'] = True
    finally:
        atomic_json(directory / 'acceptance.json', report)
    print(json.dumps({'verified': report['verified'], 'cases': len(report.get('cases', [])), 'hostile': len(report.get('hostile', {}))}, indent=2))


if __name__ == '__main__':
    main()
