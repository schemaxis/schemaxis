"""appendSeries: single-writer/multiple-reader (SWMR) append of sample rows with concurrent fresh readers.

The writer creates one chunked unlimited dataset with libver latest, enters SWMR mode, then appends each
batch, flushes and waits (bounded) for every reader to acknowledge. Each reader is a separate process
opened with swmr=True that refreshes and records the rows and value digest it observed. The host checks
every observation against the digest of the independently computed prefix of the planned rows, then
checks the closed file through the readback and h5dump like any other publication.
"""
import json
import shutil
import threading

from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail
from . import expect, model, operations, state


def batch_values(p, captured):
    s = p['series']
    width = s['width']
    out = []
    parsed = {}
    inputs = {i['id']: i for i in p['inputs']}
    for i, b in enumerate(p['batches']):
        rec = b['record']
        at = f'$.batches[{i}]'
        if rec['source'] == 'input':
            item = inputs.get(rec.get('input'))
            if item is None or item['format'] != 'csv':
                fail('INVALID_HDF5_DATA', 'series batches read declared CSV inputs', at + '.input')
            header, rows = expect.parse_csv(captured[item['id']], item['delimiter'], '$.inputs.' + item['id'])
            n = len(rows)
            shape = [n] if width == 1 else [n, width]
        elif rec['source'] == 'values':
            n = len(rec['values']) // width
            shape = [n] if width == 1 else [n, width]
        else:
            fail('INVALID_HDF5_DATA', 'series batches take values or CSV input', at + '.source')
        values = operations.data_values(rec, s['type'], shape, at, captured, parsed, inputs)
        out.append((n, values))
    return out


def expected_state(p, batches):
    s = p['series']
    width = s['width']
    rows = sum(n for n, _ in batches)
    shape = [rows] if width == 1 else [rows, width]
    obj = {'path': s['dataset'], 'kind': 'dataset', 'type': s['type'], 'shape': shape,
           'maxshape': ['unlimited'] if width == 1 else ['unlimited', width],
           'storage': {'layout': 'chunked', 'chunks': [s['chunkRows']] if width == 1 else [s['chunkRows'], width],
                       'compression': s['compression'], 'shuffle': False, 'fletcher32': False, **({'level': 4} if s['compression'] == 'gzip' else {})},
           'data': {'source': 'values', 'values': [v for _, vs in batches for v in vs]},
           'attributes': [{'name': 'units', 'type': {'class': 'string', 'encoding': 'utf-8'}, 'shape': [], 'values': [s['units']]}] if 'units' in s else [],
           'dimensions': []}
    plan = {'file': {'attributes': []}, 'objects': [obj], 'links': []}
    return state.expected_create(plan, {s['dataset']: obj['data']['values']})


def prefix_digests(p, batches):
    s = p['series']
    rt = s['type']
    out, d, rows = [], expect.Digest(), 0
    for n, values in batches:
        for v in values:
            d.add(expect.canonical(v, rt))
        rows += n
        out.append({'rows': rows, **{k: v for k, v in d.result().items()}})
    return out


def run(p, directory, paths, deadline, captured):
    from . import adaptor
    batches = batch_values(p, captured)
    for i, (n, values) in enumerate(batches):
        atomic_json(directory / ('payload-b%d.json' % i), [operations.payload_value(v, p['series']['type']) for v in values])
    config = {'file': p['file'], 'series': p['series'], 'swmr': p['swmr'], 'readers': p['readers'],
              'batches': [{'payload': 'b%d' % i} for i in range(len(batches))], 'readerWait': 10.0, 'readerTimeout': 60.0,
              'manifests': {'readback': {'file': p['file']['name'], 'fileSettings': p['file']}}}
    atomic_json(directory / 'native-config.json', config)
    adaptor.inject_access(directory)
    errors = []

    def reader(index):
        try:
            adaptor.stage(paths, directory, 'swmr-reader-%d' % index, deadline)
        except Exception as error:
            errors.append(error)
    threads = [threading.Thread(target=reader, args=(i,), daemon=True) for i in range(p['readers'])]
    for t in threads:
        t.start()
    try:
        writer = adaptor.stage(paths, directory, 'swmr-writer', deadline)
    finally:
        for t in threads:
            t.join(timeout=max(1.0, deadline - __import__('time').monotonic()))
    if errors:
        if isinstance(errors[0], SchemaxisError):
            raise errors[0]
        fail('HDF5_NATIVE_FAILED', 'a SWMR reader stage failed: ' + repr(errors[0])[:300], 'swmr-reader')
    if any(t.is_alive() for t in threads):
        fail('RUNNER_TIMED_OUT', 'a SWMR reader did not finish before the deadline')
    prefixes = prefix_digests(p, batches)
    observations = check_observations(directory, p, prefixes)
    expected = expected_state(p, batches)
    readback = adaptor.stage(paths, directory, 'readback', deadline)
    state.compare_readback(expected, readback)
    if readback['file']['superblock'] != 3:
        fail('VERIFICATION_FAILED', 'SWMR files use superblock version 3', '$.file', observed=readback['file']['superblock'])
    xml = adaptor.dump(paths, directory, 'h5dump-output', p['file']['name'], deadline, values=True)
    state.compare_xml(expected, xml)
    atomic_json(directory / 'expected-state.json', expected)
    return series_report(p, batches, prefixes, observations, writer)


def series_report(p, batches, prefixes, observations, writer):
    timeline = [{'batch': t['batch'], 'rows': t['rows']} for t in writer['timeline']]
    if timeline != [{'batch': i, 'rows': want['rows']} for i, want in enumerate(prefixes)]:
        fail('VERIFICATION_FAILED', 'the SWMR writer timeline differs from the planned cumulative rows', '$.batches')
    return {'operation': 'appendSeries', 'file': p['file']['name'], 'dataset': p['series']['dataset'], 'rows': prefixes[-1]['rows'] if prefixes else 0,
            'batches': len(batches), 'swmr': p['swmr'], 'readers': p['readers'], 'observations': observations, 'writerTimeline': timeline}


def check_observations(directory, p, prefixes):
    from . import adaptor
    out = []
    for r in range(p['readers']):
        observed = adaptor.read(directory, 'swmr-reader-%d-result.json' % r)['result']['observed']
        if len(observed) != len(prefixes):
            fail('VERIFICATION_FAILED', 'a SWMR reader did not observe every flushed batch', '$.readers', reader=r, observed=len(observed))
        for obs, want in zip(observed, prefixes):
            if obs['rows'] != want['rows'] or obs['values']['count'] != want['count'] or obs['values']['sha256'] != want['sha256']:
                fail('VERIFICATION_FAILED', 'a concurrent SWMR reader observed rows that differ from the flushed prefix', '$.batches[%d]' % obs['batch'],
                     reader=r, expectedRows=want['rows'], observedRows=obs['rows'])
        out.append({'reader': r, 'batchesObserved': len(observed)})
    return out


def fresh_check(directory, scratch, p, paths, deadline):
    from . import adaptor
    batches = batch_values(p, adaptor.captured_bytes(directory, p))
    expected = expected_state(p, batches)
    if json.loads(json.dumps(expected)) != adaptor.read(directory, 'expected-state.json'):
        fail('VERIFICATION_FAILED', 'the retained expected series differs from a fresh computation')
    prefixes = prefix_digests(p, batches)
    observations = check_observations(directory, p, prefixes)
    adaptor.same_report(directory, series_report(p, batches, prefixes, observations, adaptor.read(directory, 'swmr-writer-result.json')['result']))
    shutil.copyfile(directory / p['file']['name'], scratch / p['file']['name'])
    xml = adaptor.dump(paths, scratch, 'h5dump-fresh', p['file']['name'], deadline, values=True)
    state.compare_xml(expected, xml)
    rb = adaptor.fresh_manifest(paths, scratch, 'readback', p['file']['name'], deadline, p['file'])
    state.compare_readback(expected, rb)
    if rb['file']['superblock'] != 3:
        fail('VERIFICATION_FAILED', 'SWMR files use superblock version 3', '$.file')
    return ['h5dump-output', 'readback-output', 'swmr-observations']
