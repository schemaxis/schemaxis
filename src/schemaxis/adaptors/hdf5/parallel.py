"""parallelWrite: MPI ranks write axis-0 row blocks through the mpio driver; serial consumers verify the result.

The parallel h5py build and mpiexec come only from trusted configuration (never from authored input). Ranks
are launched on localhost only (shared-memory transport), so an inherited scheduler allocation cannot place
them on other nodes.
Every rank writes a receipt (rank, size, pid, rows, driver); the host requires exactly the planned ranks,
distinct processes, the mpio driver and partitions covering every row once. The closed file is then read
by the serial wheel runtime and by h5dump against the host's expectations, and an optional parallel read
reduces count/min/max/sum across ranks for comparison with host statistics.
"""
import math
import time

from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail
from schemaxis.native_command import execute
from . import operations, state

MPI_ENVIRONMENT = {'OMPI_MCA_btl': 'self,vader', 'OMPI_MCA_rmaps_base_oversubscribe': '1', 'OMPI_MCA_mpi_yield_when_idle': '1'}


def mpi_stage(paths, directory, name, deadline, ranks):
    from . import adaptor
    access = adaptor.inject_access(directory)
    command = [paths['mpiexec'], '--host', 'localhost:%d' % ranks, '-n', str(ranks), paths['mpiPython'], '-I', '-B', str(directory / 'native-worker.py'), name]
    try:
        execute(command, directory, name, deadline - time.monotonic(), {**adaptor.environment(directory), **MPI_ENVIRONMENT})
    except SchemaxisError as error:
        if error.fault.code != 'RUNNER_FAILED':
            raise
        for rank in range(ranks):
            path = directory / ('%s-fault-%d.json' % (name, rank))
            if path.is_file():
                record = adaptor.read(directory, path.name)
                fail(record.get('code', 'HDF5_NATIVE_FAILED') if str(record.get('code', '')).startswith('HDF5_') else 'HDF5_NATIVE_FAILED',
                     'parallel h5py refused the operation: ' + str(record.get('message'))[:300], str(record.get('location', '$')), rank=rank)
        fail('HDF5_NATIVE_FAILED', 'the MPI job failed without a structured refusal; see ' + name + '.stderr', name)
    result = adaptor.read(directory, name + '-result.json')
    adaptor.check_access(access, result.get('access'), name)
    return result


def check_ranks(directory, p, stage):
    from . import adaptor
    receipts = [adaptor.read(directory, '%s-rank-%d.json' % (stage, r)) for r in range(p['ranks'])]
    pids = set()
    for r, rec in enumerate(receipts):
        if rec.get('rank') != r or rec.get('size') != p['ranks']:
            fail('VERIFICATION_FAILED', 'an MPI rank receipt does not match the planned communicator', stage, rank=r, observed=[rec.get('rank'), rec.get('size')])
        pids.add(rec.get('pid'))
        if stage == 'mpi-write':
            if rec.get('driver') != 'mpio' or rec.get('io') != p['io']:
                fail('VERIFICATION_FAILED', 'a rank did not write through the mpio driver with the planned I/O mode', stage, rank=r)
            if rec.get('rows') != {path: rows[r] for path, rows in p['partitions'].items()}:
                fail('VERIFICATION_FAILED', 'a rank wrote rows outside its planned partition', stage, rank=r)
    if len(pids) != p['ranks']:
        fail('VERIFICATION_FAILED', 'MPI ranks were not distinct processes', stage)
    for path, rows in p['partitions'].items():
        covered = []
        for lo, hi in rows:
            covered.extend(range(lo, hi))
        shape0 = next(o['shape'][0] for o in p['objects'] if o['path'] == path)
        if covered != list(range(shape0)):
            fail('VERIFICATION_FAILED', 'partitions do not cover every row exactly once', path)
    return {'ranks': p['ranks'], 'pids': sorted(pids), 'mpi': receipts[0].get('mpi'), 'mpi4py': receipts[0].get('mpi4py')}


def reductions(expected, p):
    out = {}
    for o in p['objects']:
        if o['kind'] != 'dataset':
            continue
        values = expected['objects'][o['path']]['values']
        is_float = expected['objects'][o['path']]['type']['class'] == 'float'
        numbers = [float.fromhex(v) for v in values] if is_float else list(values)
        finite = [x for x in numbers if not is_float or math.isfinite(x)]
        out[o['path']] = {'count': len(numbers), 'sum': math.fsum(finite) if is_float else sum(finite),
                          'minimum': min(finite) if finite else None, 'maximum': max(finite) if finite else None, 'float': is_float}
    return out


def check_reduction(observed, want):
    for path, w in want.items():
        g = observed.get(path)
        if g is None:
            fail('VERIFICATION_FAILED', 'the parallel reduction omitted a dataset', path)
        decode = (lambda v: None if v is None else float.fromhex(v)) if w['float'] else (lambda v: v)
        if g['count'] != w['count'] or decode(g['minimum']) != w['minimum'] or decode(g['maximum']) != w['maximum']:
            fail('VERIFICATION_FAILED', 'parallel count/min/max differ from the independent values', path, expected=w, observed=g)
        total = decode(g['sum'])
        limit = 1e-12 * math.fsum(abs(x) for x in [w['sum']]) + 1e-300 if w['float'] else 0
        if abs(total - w['sum']) > limit:
            fail('VERIFICATION_FAILED', 'parallel sum differs from the independent sum', path, expected=w['sum'], observed=total)


def run(p, directory, paths, deadline, captured):
    from . import adaptor
    values = adaptor.host_values(p, captured)
    expected = state.expected_create(p, values)
    atomic_json(directory / 'expected-state.json', expected)
    objects = adaptor.native_objects(p, values)
    adaptor.write_payloads(directory, p, values, objects)
    config = {'file': p['file'], 'objects': objects, 'partitions': p['partitions'], 'io': p['io'],
              'manifests': {'readback': {'file': p['file']['name'], 'fileSettings': p['file']}}}
    atomic_json(directory / 'native-config.json', config)
    mpi_stage(paths, directory, 'mpi-write', deadline, p['ranks'])
    ranks = check_ranks(directory, p, 'mpi-write')
    report = adaptor.check_output(p, directory, paths, deadline, expected)
    report['parallel'] = {**ranks, 'io': p['io'], 'partitions': p['partitions']}
    if p['reduce']:
        observed = mpi_stage(paths, directory, 'mpi-reduce', deadline, p['ranks'])['result']['reduced']
        check_ranks(directory, p, 'mpi-reduce')
        want = reductions(expected, p)
        check_reduction(observed, want)
        report['parallel']['reduction'] = {path: {k: v for k, v in w.items() if k != 'float'} for path, w in want.items()}
    return report


def fresh_check(directory, p):
    """Recheck rank receipts and the parallel reduction; return the report section rebuilt from them."""
    from . import adaptor
    section = {**check_ranks(directory, p, 'mpi-write'), 'io': p['io'], 'partitions': p['partitions']}
    if p['reduce']:
        check_ranks(directory, p, 'mpi-reduce')
        observed = adaptor.read(directory, 'mpi-reduce-result.json')['result']['reduced']
        want = reductions(adaptor.read(directory, 'expected-state.json'), p)
        check_reduction(observed, want)
        section['reduction'] = {path: {k: v for k, v in w.items() if k != 'float'} for path, w in want.items()}
    return section


def check_extract_ranks(directory, p, items):
    """Every rank read exactly its planned axis-0 block of every extract through the mpio driver."""
    from . import adaptor, model, state
    ranks = p['parallel']['ranks']
    pids = set()
    for r in range(ranks):
        rec = adaptor.read(directory, 'mpi-extract-rank-%d.json' % r)
        if rec.get('rank') != r or rec.get('size') != ranks or rec.get('driver') != 'mpio' or rec.get('io') != p['parallel']['io']:
            fail('VERIFICATION_FAILED', 'an MPI extraction rank receipt does not match the plan', 'mpi-extract', rank=r)
        pids.add(rec.get('pid'))
        for item in items:
            shape = item['selectedShape']
            width = model.element_count(shape[1:]) if len(shape) > 1 else 1
            want = len(state.indices(item['parallelBlocks'][r], item['datasetShape'])) // max(1, width)
            if rec['rows'].get(item['id']) != want:
                fail('VERIFICATION_FAILED', 'a rank read a different number of rows than its planned block', 'mpi-extract', rank=r, extract=item['id'])
    if len(pids) != ranks:
        fail('VERIFICATION_FAILED', 'MPI extraction ranks were not distinct processes', 'mpi-extract')
