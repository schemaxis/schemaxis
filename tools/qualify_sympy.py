#!/usr/bin/env python3
"""Qualify SymPy real-root isolation through the public Schemaxis path.

Runs the shared conformance kit, constructed-root cases whose outcomes are fixed in advance from the roots
used to build each polynomial, native refusal, hostile saved-evidence mutants (including self-consistent forged
tables with every ordinary hash refreshed, so that only the independent Yun/Sturm certification can reject
them), the normal command-line plan/run/verify path with tamper rejection, a scheduled workflow with resume
reuse and invalidation, and in-flight timeout and cancellation. Host code is standard-library only; the native
runtime is the configured isolated Python (exactly SymPy 1.14.0).
"""
import argparse
import copy
from fractions import Fraction as F
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors import registry
from schemaxis.adaptors.sympy import adaptor as a, oracle as o
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import workflow

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'examples/schemaxis'


def expand(roots, scale=1, complex_factors=()):
    """Descending exact coefficients of scale * prod (x - r)^m * complex factors, built here from the chosen roots."""
    p = [F(scale)]
    for r, m in roots:
        for _ in range(m):
            p = o.mul(p, [F(1), -F(r)])
    for factor in complex_factors:
        p = o.mul(p, [F(c) for c in factor])
    return [o.text(c) for c in p]


def document(coefficients, width='1/1000'):
    return {'version': a.VERSION, 'operation': a.OPERATION, 'coefficients': list(coefficients), 'maximumIntervalWidth': width}


def table(directory):
    return [tuple(line.split(',')) for line in (Path(directory) / 'real-roots.csv').read_text().splitlines()[1:]]


def run_case(directory, name, doc, locations, *, points=None, irrational=None, count=None, with_multiplicity=None):
    """Run through registry.run and saved verification, then compare the table with roots known from construction."""
    target = directory / name
    result = registry.run(doc, target, locations=locations, timeout=60)
    assert result['verified'] is True and a.verify(target)['verified'] is True, name
    rows = table(target)
    record = {'case': name, 'rows': len(rows), 'distinctRealRoots': result['distinctRealRoots'],
              'realRootsWithMultiplicity': result['realRootsWithMultiplicity']}
    if points is not None:                       # exact rational roots: each must be a point interval at that root
        expected = [(o.text(r), o.text(r), str(m), 'true') for r, m in sorted(points)]
        assert [r[1:] for r in rows] == expected, (name, rows, expected)
    if irrational is not None:                   # irrational roots: the interval must bracket the known root (squares compared exactly)
        for (lo, hi, _m, flag), (n, _width) in zip([r[1:] for r in rows], irrational):
            low, high = o.published(lo, name), o.published(hi, name)
            assert flag == 'false' and low * low <= n <= high * high if low >= 0 else high * high <= n <= low * low, (name, rows)
    if count is not None:
        assert len(rows) == count == result['distinctRealRoots'], (name, rows)
    if with_multiplicity is not None:
        assert result['realRootsWithMultiplicity'] == with_multiplicity, name
    widest = max((o.published(r[2], name) - o.published(r[1], name) for r in rows), default=F(0))
    assert widest <= o.literal(doc['maximumIntervalWidth'], name, 'X'), name
    record['widest'] = o.text(widest)
    record['host'] = json.loads((target / 'roots-verification.json').read_text())['assessment']['squareFreeFactors']
    return record


def cases(directory, locations):
    out = directory / 'cases'
    out.mkdir()
    add = lambda *args, **kw: results.append(run_case(out, *args, locations=locations, **kw))
    results = []
    add('linear', document(['2', '-3']), points=[(F(3, 2), 1)])
    add('x7-multiple-zero', document(['1'] + ['0'] * 7), points=[(0, 7)], with_multiplicity=7)
    add('sqrt2', document(['1', '0', '-2']), irrational=[(2, 0)] * 2, count=2)
    add('irrational-neighbours-of-zero-default-width', document(['1', '0', '-1/50000000', '0']), count=3, with_multiplicity=3)
    add('irrational-neighbours-of-zero-wide', document(['50', '0', '-1', '0'], '1'), count=3, with_multiplicity=3)
    add('irrational-neighbours-of-one-wide', document(['50', '-150', '149', '-49'], '1'), count=3, with_multiplicity=3)
    add('sqrt2-1e-30', document(['1', '0', '-2'], '1/' + '1' + '0' * 30), irrational=[(2, 0)] * 2, count=2)
    add('no-real-roots', document(['1/2', '0', '0', '0', '3']), count=0, with_multiplicity=0)
    add('no-real-roots-x2-plus-1-scaled', document(['-7/3', '0', '-7/3']), count=0)
    add('mixed-repeated', document(expand([(1, 3), (-2, 2)], complex_factors=[(1, 0, 1)])), points=[(1, 3), (-2, 2)], with_multiplicity=5)
    add('rational-fractions', document(expand([(F(3, 2), 1), (F(-1, 3), 1), (-4, 1)], scale=6)), points=[(F(3, 2), 1), (F(-1, 3), 1), (-4, 1)])
    add('wilkinson-12', document(expand([(k, 1) for k in range(1, 13)])), points=[(k, 1) for k in range(1, 13)], count=12)
    add('close-roots-1e-20', document(expand([(1, 1), (1 + F(1, 10 ** 20), 1)]), '1/1000000000000000000000'),
        points=[(1, 1), (1 + F(1, 10 ** 20), 1)])
    add('close-roots-resolved-by-width', document(expand([(1, 1), (1 + F(1, 10 ** 6), 1)], complex_factors=[(1, 0, 3)]) , '1/10000000'),
        points=[(1, 1), (1 + F(1, 10 ** 6), 1)])
    big = 10 ** 39
    add('forty-digit-coefficients', document([str(big - 1), '0', str(-(big - 1) * 2 // 1)]), irrational=[(2, 0)] * 2, count=2)
    add('negative-leading-large-denominator', document(['-1/' + '9' * 38, '0', '2/' + '9' * 38]), irrational=[(2, 0)] * 2, count=2)
    add('x12-minus-2', document(['1'] + ['0'] * 11 + ['-2']), count=2)
    add('degree-12-three-quadruple-roots', document(expand([(-1, 4), (0, 4), (2, 4)])), points=[(-1, 4), (0, 4), (2, 4)], with_multiplicity=12)
    add('cubic-three-irrational', document(['1', '0', '-3', '1']), count=3)    # 2cos(2 pi k/9)-type roots
    add('double-root-needs-square-free', document(['1', '-2', '1']), points=[(1, 2)])
    return results


def refused(action, *codes):
    try:
        action()
    except SchemaxisError as error:
        if codes and error.fault.code not in codes:
            raise AssertionError(error.fault.to_dict()) from error
        return error.fault.code
    raise AssertionError('invalid evidence was accepted')


def refuse_input(locations):
    result = {}
    for label, doc, code in (
            ('expression', document(['x**2', '0', '-2']), 'SYMPY_INVALID_COEFFICIENT'),
            ('code', document(['__import__("os").system("true")', '1']), 'SYMPY_INVALID_COEFFICIENT'),
            ('decimal', document(['1', '0.5']), 'SYMPY_INVALID_COEFFICIENT'),
            ('zero-leading', document(['0', '1', '-2']), 'SYMPY_ZERO_LEADING_COEFFICIENT'),
            ('width-decimal', document(['1', '-2'], '0.001'), 'SYMPY_INVALID_WIDTH'),
            ('width-too-fine', document(['1', '-2'], '1/10' + '0' * 30), 'SYMPY_INVALID_WIDTH')):
        result[label] = refused(lambda doc=doc: registry.run(doc, ROOT / 'tmp-never-created', locations=locations), code)
        assert not (ROOT / 'tmp-never-created').exists()
    return result


STUB = ('import runpy, sys\nsys.path.insert(0, {stub!r})\nsys.argv = ["native-worker.py", *sys.argv[4:]] if sys.argv[1:4] == ["-I", "-B", "native-worker.py"] else sys.argv\n'
        'runpy.run_path("native-worker.py", run_name="__main__")\n')


def unsupported_runtime(directory, locations):
    """A launcher whose `sympy` reports 1.13.3: the worker must refuse before any computation."""
    stub = directory / 'stub'
    (stub / 'sympy').mkdir(parents=True)
    (stub / 'sympy/__init__.py').write_text('__version__ = "1.13.3"\n')
    launcher = directory / 'old-sympy-runtime.py'
    launcher.write_text('#!' + sys.executable + '\n' + STUB.format(stub=str(stub)))
    launcher.chmod(0o700)
    try:
        registry.run(document(['1', '0', '-2']), directory / 'old-runtime', locations={'sympy': str(launcher)}, timeout=30)
    except SchemaxisError as error:
        assert error.fault.code == 'SYMPY_UNSUPPORTED_RUNTIME', error.fault.to_dict()
        assert (directory / 'old-runtime/compute-fault.json').is_file()
        return {'fault': error.fault.code, 'observed': dict(error.fault.observed)}
    raise AssertionError('an unsupported SymPy release was accepted')


def unavailable_runtime(directory):
    """A launcher whose Python cannot import SymPy (`-S`): a structured unavailable fault, distinct from unsupported."""
    launcher = directory / 'no-sympy-runtime.sh'
    launcher.write_text('#!/bin/sh\nexec "%s" -S "$@"\n' % sys.executable)
    launcher.chmod(0o700)
    try:
        registry.run(document(['1', '0', '-2']), directory / 'absent-runtime', locations={'sympy': str(launcher)}, timeout=30)
    except SchemaxisError as error:
        assert error.fault.code == 'SYMPY_RUNTIME_UNAVAILABLE' and error.fault.recovery, error.fault.to_dict()
        assert (directory / 'absent-runtime/compute-fault.json').is_file()
        return {'fault': error.fault.code, 'location': error.fault.location}
    raise AssertionError('a Python without SymPy was accepted')


def refresh(directory, *, rewrite_record=True):
    """Refresh every ordinary hash so only independent certification can reject a forged table."""
    directory = Path(directory)
    plan = a.read(directory, 'plan.json')
    summary = a.read(directory, 'roots-summary.json')
    summary['files'] = {'real-roots.csv': a.digest(directory, 'real-roots.csv')}
    atomic_json(directory / 'roots-summary.json', summary)
    inputs = a.read(directory, 'readback-inputs.json')
    atomic_json(directory / 'readback-inputs.json', {name: a.digest(directory, name) for name in inputs})
    if rewrite_record:
        try:
            atomic_json(directory / 'roots-verification.json', a.host_record(directory, plan))
        except SchemaxisError:
            pass                                            # the host certifier refuses; the stale record stays
    receipt = a.read(directory, 'verification.json')
    receipt['artifacts'] = [{**item, 'sha256': a.digest(directory, Path(item['file']).name)} for item in receipt['artifacts']]
    receipt['evidence'] = {name: a.digest(directory, name) for name in receipt['evidence']}
    atomic_json(directory / 'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    manifest = directory / 'publication-metadata.json'
    origin = json.loads(manifest.read_text()).get('recordedDirectory') if manifest.is_file() else None
    finalise(directory)
    if origin is not None:
        atomic_json(manifest, {**json.loads(manifest.read_text()), 'recordedDirectory': origin})


def forge(target, rows):
    """Self-consistent wrong table: CSV, native summary and every digest agree; only the mathematics is wrong."""
    intervals = [(F(lo), F(hi), m) for lo, hi, m in rows]
    (target / 'real-roots.csv').write_bytes(o.render(intervals))
    summary = a.read(target, 'roots-summary.json')
    summary['intervals'] = [{'lower': o.text(lo), 'upper': o.text(hi), 'multiplicity': m} for lo, hi, m in intervals]
    atomic_json(target / 'roots-summary.json', summary)
    refresh(target)


def hostile(directory, kit):
    repeated = kit / 'variant'                              # (x-1)^3 (x+2)^2 (x^2+1): exact roots -2 (2), 1 (3)
    sqrt2 = kit / 'baseline'
    for source in (repeated, sqrt2):
        assert a.verify(source)['verified']
    results = {}

    def mutate(label, source, change, *, expect=None):
        # Mutate the original run in place and restore every byte, so shared publication metadata stays owned by this directory.
        saved = {path: path.read_bytes() for path in source.rglob('*') if path.is_file()}
        try:
            change(source)
            try:
                a.verify(source)
            except SchemaxisError as error:
                if expect and error.fault.code not in expect:
                    raise AssertionError(label + ': ' + json.dumps(error.fault.to_dict())) from error
                results[label] = {'fault': error.fault.code, 'location': error.fault.location}
            else:
                raise AssertionError(label + ': mutant accepted')
        finally:
            for path in [p for p in source.rglob('*') if p.is_file() and p not in saved]:
                path.unlink()
            for path, data in saved.items():
                path.write_bytes(data)
        assert a.verify(source)['verified'], label + ': restoration failed'

    cert = ('SYMPY_CERTIFICATION_FAILED',)
    forged = {
        'drop-a-root': (repeated, [(-2, -2, 2)]),
        'phantom-root': (repeated, [(-2, -2, 2), (1, 1, 3), (5, 5, 1)]),
        'wrong-multiplicity': (repeated, [(-2, -2, 3), (1, 1, 2)]),
        'swapped-multiplicity-labels': (repeated, [(-2, -2, 3), (1, 1, 3)]),
        'point-off-the-root': (repeated, [(-2, -2, 2), (2, 2, 3)]),
        'interval-misses-root': (repeated, [(-2, -2, 2), (F(1, 2), F(3, 4), 3)]),
        'two-roots-in-one-interval': (repeated, [(-3, 2, 2)]),
        'too-wide-for-declared-width': (sqrt2, [(F(-2), F(-1), 1), (F(1), F(2), 1)]),
        'touching-intervals': (repeated, [(-2, 0, 2), (0, 1, 3)]),
        'reversed-order': (repeated, [(1, 1, 3), (-2, -2, 2)]),
        'one-of-two-irrational-roots': (sqrt2, [(F(41, 29), F(58, 41), 1)]),
        'sqrt2-as-exact-point': (sqrt2, [(F(-3, 2), F(-3, 2), 1), (F(3, 2), F(3, 2), 1)]),
    }
    for label, (source, rows) in forged.items():
        mutate(label, source, lambda t, rows=rows: forge(t, rows), expect=cert)

    def edit_json(name, change, refreshed=False):
        def apply(target):
            value = a.read(target, name)
            change(value)
            atomic_json(target / name, value)
            if refreshed:
                refresh(target, rewrite_record=False)
        return apply
    raw = {
        'csv-byte-flip': lambda t: (t / 'real-roots.csv').write_bytes((t / 'real-roots.csv').read_bytes().replace(b'-2,-2', b'-2,-1', 1)),
        'summary-deleted': lambda t: (t / 'roots-summary.json').unlink(),
        'verification-record-deleted': lambda t: (t / 'roots-verification.json').unlink(),
        'receipt-deleted': lambda t: (t / 'verification.json').unlink(),
        'authored-edited': edit_json('authored.json', lambda d: d['coefficients'].__setitem__(-1, '-5')),
        'plan-edited': edit_json('plan.json', lambda d: d.__setitem__('maximumIntervalWidth', '1')),
        'host-record-count-edited': edit_json('roots-verification.json', lambda d: d['assessment'].__setitem__('distinctRealRoots', 3), True),
        'host-record-binding-edited': edit_json('roots-verification.json', lambda d: d['bindings']['runtime'].__setitem__('identity', 'SymPy 9'), True),
        'native-summary-decision-added': edit_json('roots-summary.json', lambda d: d.__setitem__('verified', True), True),
        'native-runtime-edited': edit_json('roots-summary.json', lambda d: d['runtime'].__setitem__('sympy', '1.13.3'), True),
        'readback-flipped': edit_json('readback.json', lambda d: d.__setitem__('ok', False), True),
        'submission-command-edited': edit_json('compute-submission.json', lambda d: d['nativeCommand'].__setitem__(0, '/usr/bin/true'), True),
        'submission-exit-edited': edit_json('readback-submission.json', lambda d: d.__setitem__('exitCode', 1), True),
        'implementation-edited': edit_json('implementation.json', lambda d: d.__setitem__('oracle.py', '0' * 64), True),
        'worker-edited': lambda t: ((t / 'native-worker.py').write_text((t / 'native-worker.py').read_text() + '\n# altered\n'), refresh(t, rewrite_record=False)),
        'receipt-evidence-dropped': edit_json('verification.json', lambda d: d['evidence'].pop('readback.json')),
        'receipt-artifact-dropped': edit_json('verification.json', lambda d: d['artifacts'].pop()),
        'result-failed': edit_json('result.json', lambda d: d.update(status='failed', verified=False)),
        'extra-duplicate-json-key': lambda t: ((t / 'authored.json').write_text((t / 'authored.json').read_text().replace('"operation"', '"operation": "isolateRealRoots", "operation"', 1))),
    }
    for label, change in raw.items():
        mutate(label, repeated, change)
    # A verification record and table from a different polynomial copied in place: foreign but internally consistent.
    def foreign(target):
        for name in ('real-roots.csv', 'roots-summary.json', 'roots-verification.json'):
            shutil.copy(sqrt2 / name, target / name)
        refresh(target, rewrite_record=False)
    mutate('foreign-polynomial-publications', repeated, foreign)
    return results


def cli(*args):
    done = subprocess.run([sys.executable, '-B', '-m', 'schemaxis', *map(str, args)], capture_output=True, text=True, timeout=300,
                          env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')})
    try:
        value = json.loads(done.stdout)
    except ValueError:
        value = None
    return {'exitCode': done.returncode, 'result': value, 'stderr': done.stderr[-1500:]}


def command_line(directory, executable):
    out = directory / 'cli'
    out.mkdir()
    result = {}
    planned = cli('plan', EXAMPLES / 'sympy-repeated-roots.json')
    assert planned['exitCode'] == 0 and planned['result']['publications'][-1] == 'roots-verification.json', planned
    result['plan'] = 'ok'
    for name in ('sympy-sqrt2', 'sympy-repeated-roots', 'sympy-no-real-roots', 'sympy-rational-roots'):
        run = cli('run', EXAMPLES / (name + '.json'), '--output-directory', out / name, '--sympy', executable)
        assert run['exitCode'] == 0 and run['result']['verified'] is True and run['result']['status'] == 'succeeded', run
        again = cli('verify', out / name)
        assert again['exitCode'] == 0 and again['result']['verified'] is True, again
        result[name] = {'run': 'verified', 'distinctRealRoots': run['result']['distinctRealRoots']}
    for name, code in (('sympy-expression-invalid', 'SYMPY_INVALID_COEFFICIENT'), ('sympy-zero-leading-invalid', 'SYMPY_ZERO_LEADING_COEFFICIENT')):
        for verb in ('plan', 'run'):
            args = ['run', EXAMPLES / (name + '.json'), '--output-directory', out / ('x-' + name), '--sympy', executable] if verb == 'run' else ['plan', EXAMPLES / (name + '.json')]
            bad = cli(*args)
            assert bad['exitCode'] != 0 and bad['result']['fault']['code'] == code, bad
        assert not (out / ('x-' + name)).exists()
        result[name] = code
    # Tamper in place and restore every byte: copied runs would no longer own their recorded publication paths.
    run = out / 'sympy-repeated-roots'
    saved = {path: path.read_bytes() for path in run.rglob('*') if path.is_file()}

    def restore():
        for path in [p for p in run.rglob('*') if p.is_file() and p not in saved]:
            path.unlink()
        for path, data in saved.items():
            path.write_bytes(data)
    try:
        (run / 'real-roots.csv').write_bytes(saved[run / 'real-roots.csv'].replace(b'1,1,3', b'1,1,2', 1))
        bad = cli('verify', run)
        assert bad['exitCode'] != 0 and bad['result'].get('fault', {}).get('code') == 'VERIFICATION_FAILED', bad
        result['tamperedVerify'] = bad['result']['fault']['code']
        restore()
        forge(run, [(-2, -2, 2), (1, 1, 2)])
        bad = cli('verify', run)
        assert bad['exitCode'] != 0 and bad['result']['fault']['code'] == 'SYMPY_CERTIFICATION_FAILED', bad
        result['forgedVerify'] = bad['result']['fault']['code']
    finally:
        restore()
    again = cli('verify', run)
    assert again['exitCode'] == 0 and again['result']['verified'] is True, again
    result['restoredVerify'] = 'verified'
    return result


def workflows(directory, locations):
    graph = json.loads((EXAMPLES / 'sympy-two-polynomials-workflow.json').read_text())
    target = directory / 'workflow'
    first = workflow.execute(graph, target, locations=locations, timeout=60)
    assert first['verified'] and workflow.verify(target)['verified']
    second = workflow.execute(graph, target, locations=locations, timeout=60, resume=True)
    assert all(j['reused'] for j in second['jobs']), 'identical resume must reuse'
    changed = copy.deepcopy(graph)
    changed['operations'][0]['document']['coefficients'] = ['1', '0', '-3']
    refusal = refused(lambda: workflow.execute(changed, target, locations=locations, timeout=60, resume=True), 'RESUME_MISMATCH')
    assert workflow.verify(target)['verified']
    fresh = workflow.execute(changed, directory / 'workflow-edited', locations=locations, timeout=60)
    assert fresh['verified'] and not any(j.get('reused') for j in fresh['jobs'])
    return {'firstRun': 'verified', 'identicalResume': 'all reused', 'editedWorkflowResume': refusal, 'editedWorkflowFreshRun': 'verified'}


def lifecycle(directory):
    wrapper, marker = directory / 'slow-runtime.py', directory / 'slow.pid'
    wrapper.write_text('#!' + sys.executable + '\nimport os,time\nfrom pathlib import Path\nPath(' + repr(str(marker)) + ').write_text(str(os.getpid()))\ntime.sleep(30)\n')
    wrapper.chmod(0o700)
    result = {}
    for action in ('timeout', 'cancel'):
        if marker.exists():
            marker.unlink()
        event = threading.Event()

        def trigger():
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            if marker.exists():
                event.set()
        thread = threading.Thread(target=trigger, daemon=True) if action == 'cancel' else None
        if thread:
            thread.start()
        try:
            with allocation({'threads': 1, 'ranks': 1}, event):
                result[action] = refused(lambda: a.run(document(['1', '0', '-2']), directory / ('inflight-' + action), executable=str(wrapper),
                                                       timeout=8 if thread else .6), 'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')
        finally:
            if thread:
                thread.join(6)
        assert marker.exists(), 'owned child not launched'
        pid = int(marker.read_text())
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError('child survived ' + action)
        result[action + 'ChildPid'] = pid
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sympy', type=Path, required=True, help='Absolute isolated Python with SymPy 1.14.0')
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--register', action='store_true')
    args = parser.parse_args()
    directory = args.output_directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    locations = {'sympy': str(args.sympy.absolute())}
    report = {'verified': False}
    try:
        receipt = qualify(a.VERSION, directory / 'kit', native=True, root=ROOT, locations=locations, timeout=60, wall_timeout=120)
        report['kit'] = {'verified': receipt['verified'], 'cases': [c['id'] for c in receipt['cases']], 'lifecycle': receipt['lifecycle']}
        report['cases'] = cases(directory, locations)
        report['inputRefusals'] = refuse_input(locations)
        report['unsupportedRuntime'] = unsupported_runtime(directory, locations)
        report['unavailableRuntime'] = unavailable_runtime(directory)
        report['hostile'] = hostile(directory, directory / 'kit')
        report['commandLine'] = command_line(directory, locations['sympy'])
        report['workflow'] = workflows(directory, locations)
        report['inflightLifecycle'] = lifecycle(directory)
        if args.register:
            register(directory / 'kit/qualification.json')
        report['verified'] = True
    finally:
        atomic_json(directory / 'acceptance.json', report)
    print(json.dumps({'verified': report['verified'], 'cases': len(report.get('cases', [])), 'hostile': len(report.get('hostile', {}))}, indent=2))


if __name__ == '__main__':
    main()
