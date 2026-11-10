"""Bounded native acceptance for the HDF5 adaptor.

  PYTHONPATH=src python3 tools/qualify_hdf5.py --python /abs/venv/bin/python --h5dump /abs/h5dump \
      --output-directory evidence/hdf5-native

Runs every readiness case from fresh directories with repository fixtures, checks the reviewed literal
expectations, then attacks retained publications with semantic edits whose recorded digests are
refreshed (each must fail the intended guard while an unchanged copy still verifies), and exercises
lifecycle faults. Writes qualification-summary.json; retains failures. Native results only describe
the exact cases, source commit and runtimes recorded in the summary.
"""
import argparse
import hashlib
import inspect
import json
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from schemaxis.adaptor_conformance import assertions  # noqa: E402
from schemaxis.adaptors.hdf5 import adaptor, chunks  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

READINESS = ROOT / 'src/schemaxis/adaptors/hdf5/readiness.json'


def case_document(case, examples):
    document = json.loads((ROOT / examples[case['example']]).read_text())
    if case['edits']:
        raise ValueError('cases with JSON patches are run by schemaxis adaptor conform')
    for pointer, relative in case.get('resources', {}).items():
        target = document
        parts = [p.replace('~1', '/').replace('~0', '~') for p in pointer.strip('/').split('/')]
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        key = parts[-1]
        if isinstance(target, list):
            target[int(key)] = str(ROOT / relative)
        else:
            target[key] = str(ROOT / relative)
    return document


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def refresh(directory):
    """Adversary with write access: recompute every recorded digest after an edit."""
    capture = directory / 'capture.json'
    if capture.is_file():
        record = json.loads(capture.read_text())
        for item in record['captured']:
            data = (directory / item['file']).read_bytes()
            item['bytes'], item['sha256'] = len(data), hashlib.sha256(data).hexdigest()
        capture.write_text(json.dumps(record, indent=2))
    receipt = json.loads((directory / 'verification.json').read_text())
    for item in receipt['artifacts']:
        item['file'] = str(directory / Path(item['file']).name)
        item['sha256'] = digest(item['file'])
    for name in receipt['evidence']:
        receipt['evidence'][name] = digest(directory / name)
    (directory / 'verification.json').write_text(json.dumps(receipt, indent=2))


def native(paths, code, cwd):
    subprocess.run([paths['python'], '-I', '-c', code], cwd=cwd, check=True, timeout=60)


def attack(paths, run, label, mutate, expect_code='VERIFICATION_FAILED'):
    target = run.parent / (run.name + '-attack-' + label)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(run, target)
    try:
        if mutate is not None:
            mutate(target)
        refresh(target)
        try:
            result = adaptor.verify_directory(target, paths)
            outcome = {'attack': label, 'accepted': True, 'freshlyChecked': result['freshlyChecked']}
        except SchemaxisError as error:
            outcome = {'attack': label, 'accepted': False, 'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message}
        outcome['ok'] = outcome['accepted'] if mutate is None else (not outcome['accepted'] and outcome['code'] == expect_code)
        return outcome
    finally:
        shutil.rmtree(target, ignore_errors=True)


H5_HELPERS = '''
import h5py, numpy as np, struct, zlib


%s

def zlib_chunk(ds):
    """The second chunk's values re-encoded with a different gzip level: same values, different stored bytes."""
    a = np.ascontiguousarray(ds[3:6]).view(np.uint8).reshape(-1, 2)
    body = zlib.compress(np.ascontiguousarray(a.T).tobytes(), 1)
    return body + struct.pack('<I', fletcher32(body))
''' % inspect.getsource(chunks.fletcher32)


def h5(paths, name, code):
    return lambda d: native(paths, H5_HELPERS + 'f = h5py.File(%r, "r+")\n%s\nf.close()' % (name, code), d)


def text_edit(name, old, new):
    def mutate(d):
        p = d / name
        data = p.read_text()
        if old not in data:
            raise AssertionError('attack precondition missing in ' + name)
        p.write_text(data.replace(old, new, 1))
    return mutate


def chunk_index_rewrite(d, change):
    index = json.loads((d / 'counts.chunks.json').read_text())
    change(index)
    (d / 'counts.chunks.json').write_text(json.dumps(index, indent=1, sort_keys=True) + '\n')


def chunk_index_edit(change):
    return lambda d: chunk_index_rewrite(d, lambda index: change(index['chunks'][1]))


def flip_chunk_byte(d):
    """Adversary flips one stored byte of the second chunk in the captured source and refreshes its digests."""
    chunk = json.loads((d / 'counts.chunks.json').read_text())['chunks'][1]
    data = bytearray((d / 'source.h5').read_bytes())
    data[chunk['byteOffset'] + 2] ^= 0x40
    (d / 'source.h5').write_bytes(bytes(data))


def where_rows_bump(d):
    """Adversary edits the native where-row receipt of the first extract."""
    record = json.loads((d / 'extract-result.json').read_text())
    record['result']['extracts'][0]['whereRows']['count'] += 1
    (d / 'extract-result.json').write_text(json.dumps(record, indent=2))


def report_bump(d):
    """Change the first numeric claim in the published report (semantic report tampering)."""
    path = d / 'hdf5-report.json'
    report = json.loads(path.read_text())

    def bump(value):
        if isinstance(value, dict):
            for key in sorted(value):
                if key != 'runtime' and bump(value[key]) is not None:
                    return True
                if isinstance(value[key], (int, float)) and not isinstance(value[key], bool):
                    value[key] = value[key] + 1
                    return True
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    value[i] = item + 1
                    return True
                if bump(item):
                    return True
        return None
    if not bump(report):
        raise AssertionError('no numeric claim to tamper')
    path.write_text(json.dumps(report, indent=2))


ATTACKS = {
    'sensor-run': lambda p: [
        ('unchanged', None),
        ('value', h5(p, 'sensor-run.h5', 'f["/run/raw/counts"][2, 1] = 99')),
        ('unit', h5(p, 'sensor-run.h5', 'f["/run/calibrated/pressure"].attrs["units"] = "Pa"')),
        ('link-retarget', h5(p, 'sensor-run.h5', 'del f["/latest"]\nf["/latest"] = h5py.SoftLink("/run/raw/time")')),
        ('dtype', h5(p, 'sensor-run.h5', 'v = f["/run/flag"][()]\ndel f["/run/flag"]\nf["/run/flag"] = np.float32(v)')),
        ('scale-detach', h5(p, 'sensor-run.h5', 'f["/run/calibrated/pressure"].dims[0].detach_scale(f["/run/raw/time"])')),
        ('extra-object', h5(p, 'sensor-run.h5', 'f["/run/injected"] = np.arange(3)')),
        ('csv-cell', text_edit('counts_window.csv', '7,10', '7,11')),
        ('lzf-removed', h5(p, 'sensor-run.h5', 'v = f["/run/calibrated/pressure"][()]\na = dict(f["/run/calibrated/pressure"].attrs)\n'
                                              'f["/run/calibrated/pressure"].dims[0].detach_scale(f["/run/raw/time"])\ndel f["/run/calibrated/pressure"]\n'
                                              'd = f.create_dataset("/run/calibrated/pressure", data=v, chunks=(3,))\nd.attrs["units"] = "kPa"\n'
                                              'd.dims[0].attach_scale(f["/run/raw/time"])\nd.dims[0].label = "time"')),
        ('utf8-to-ascii', h5(p, 'sensor-run.h5', 'del f["/run/raw"].attrs["instrument"]\n'
                                                'f["/run/raw"].attrs.create("instrument", "PX-4 transducer array", dtype=h5py.string_dtype("ascii"))')),
        ('region-retarget', h5(p, 'sensor-run.h5', 'f["/run/peak"][0] = f["/run/raw/counts"].regionref[0:2, 0:2]')),
        ('committed-type-dropped', h5(p, 'sensor-run.h5', 'v = f["/run/readings"][()]\ndel f["/run/readings"]\nf["/run/readings"] = v')),
    ],
    'campaign': lambda p: [
        ('unchanged', None),
        ('dependency-source', h5(p, 'run-b.h5', 'f["/signal"][2] = 0.0')),
        ('raw-bytes', lambda d: (d / 'probe-counts.bin').write_bytes((d / 'probe-counts.bin').read_bytes()[:6] + b'\x7f\x7f' + (d / 'probe-counts.bin').read_bytes()[8:])),
        ('stitched-json', text_edit('stitched.json', '-999.0', '-998.0')),
    ],
    'edit-vendor': lambda p: [
        ('unchanged', None),
        ('edited-value', h5(p, 'vendor-export-annotated.h5', 'f["/acquisition/frames"][2, 1, 0] = 7')),
        ('source-copy', h5(p, 'source.h5', 'f.attrs["format_version"] = np.int32(4)')),
        ('calibration', h5(p, 'vendor-export-annotated.h5', 'f["/acquisition/frames"].attrs["calibration"] = [0.5, 2.0]')),
        ('extract-cell', text_edit('mean_counts.csv', ',85', ',86')),
    ],
    'inspect-vendor': lambda p: [
        ('unchanged', None),
        ('decision', text_edit('expectations.json', '"unmet": 2', '"unmet": 1')),
        ('inventory-storage', text_edit('inventory.json', '"allocatedBytes": 80', '"allocatedBytes": 48')),
        ('source-copy', h5(p, 'source.h5', 'f["/acquisition/time"].attrs["units"] = "K"')),
    ],
    'mesh-fields': lambda p: [
        ('unchanged', None),
        ('connectivity', h5(p, 'cooling-block.h5', 'f["/mesh/solid/connectivity"][1, 3] = 0')),
        ('xdmf', text_edit('cooling-block.xdmf', 'Time Value="30.0"', 'Time Value="31.0"')),
    ],
    'swmr-monitor': lambda p: [
        ('unchanged', None),
        ('sample', h5(p, 'monitor.h5', 'f["/monitor/probe"][0, 0] = 0')),
        ('observation', text_edit('swmr-reader-1-result.json', '"rows": 3', '"rows": 4')),
    ],
    'parallel-write': lambda p: [
        ('unchanged', None),
        ('value', h5(p, 'parallel-field.h5', 'f["/field/cell_id"][5] = 0')),
        ('rank-rows', text_edit('mpi-write-rank-1.json', '"/field/temperature": [\n   3,', '"/field/temperature": [\n   2,')),
        ('reduction', text_edit('mpi-reduce-result.json', '"count": 18', '"count": 17')),
    ],
    'streamed-grid': lambda p: [
        ('unchanged', None),
        ('grid-value', h5(p, 'grid.h5', 'f["/grid"][2999, 0] = -1.0')),
        ('npy-bytes', lambda d: (d / 'grid.npy').write_bytes((d / 'grid.npy').read_bytes()[:-8] + b'\x00' * 8)),
    ],
    'parallel-extract': lambda p: [
        ('unchanged', None),
        ('frames-json', text_edit('frames.json', '230', '231')),
        ('rank-rows', text_edit('mpi-extract-rank-1.json', '"frames": 2', '"frames": 3')),
    ],
    'compare-runs': lambda p: [
        ('unchanged', None),
        ('verdict', text_edit('comparison.json', '"equal": false', '"equal": true')),
    ],
    'edit-fields': lambda p: [
        ('unchanged', None),
        ('sibling-member', h5(p, 'events-corrected.h5', 'r = f["/run/events"][0]; r["level"] = 101.0; f["/run/events"][0] = r')),
        ('written-member', h5(p, 'events-corrected.h5', 'f["/run/events"][1, "sample"] = 41')),
        ('null-to-scalar', h5(p, 'events-corrected.h5', 'del f["/run/pending"]; f["/run/pending"] = 0.0; f["/run/pending"].attrs["units"] = "kPa"')),
    ],
    'large-attributes': lambda p: [
        ('unchanged', None),
        ('large-attribute-value', h5(p, 'calibrated.h5', 'a = f["/detector/counts"].attrs["lookup table"]; a[8999] = 0; f["/detector/counts"].attrs.modify("lookup table", a)')),
        ('creation-order', h5(p, 'calibrated.h5', 'v = f["/detector/counts"].attrs["zeta"]; del f["/detector/counts"].attrs["zeta"]; f["/detector/counts"].attrs["zeta"] = v')),
        ('root-large-attribute', h5(p, 'calibrated.h5', 'a = f.attrs["pixel gains"]; a[0, 0] = 9; f.attrs.modify("pixel gains", a)')),
    ],
    'sieve-columns': lambda p: [
        ('unchanged', None),
        ('grid-value', h5(p, 'profiles.h5', 'f["/grid"][1500, 5] = 0')),
        ('sieve-readback', text_edit('extract-result.json', '"sieveBufferBytes": 1048576', '"sieveBufferBytes": 65536')),
    ],
    'copy-chunks': lambda p: [
        ('unchanged', None),
        ('archived-value', h5(p, 'sensor-mirrored.h5', 'f["/archive/counts"][4, 1] = 0')),
        ('archived-rechunked', h5(p, 'sensor-mirrored.h5', 'f["/archive/counts"].id.write_direct_chunk((3, 0), zlib_chunk(f["/archive/counts"]), 0)')),
    ],
    'chunk-index': lambda p: [
        ('unchanged', None),
        ('byte-offset', chunk_index_edit(lambda c: c.__setitem__('byteOffset', c['byteOffset'] + 1))),
        ('chunk-digest', chunk_index_edit(lambda c: c.__setitem__('sha256', '0' * 64))),
        ('dropped-chunk', lambda d: chunk_index_rewrite(d, lambda index: index['chunks'].pop())),
        ('stored-chunk-byte', flip_chunk_byte, 'HDF5_UNREADABLE_OBJECT'),
    ],
    'filter-rows': lambda p: [
        ('unchanged', None),
        ('source-state', h5(p, 'source.h5', 'f["/run/state"][4] = 1')),
        ('native-rows', where_rows_bump),
        ('csv-row', text_edit('acquiring.csv', '1.5,13,16', '2.0,19,22')),
    ],
    'human-names': lambda p: [
        ('unchanged', None),
        ('unicode-value', h5(p, 'lab-notebook.h5', 'f["/Experiment 1/Temperature (°C)"][3, 1] = 28.0')),
        ('punctuated-scalar', h5(p, 'lab-notebook.h5', 'f["/Run #2, \\"warm\\" & <dry>/peak ratio"][()] = 0.5')),
        ('object-ref-retarget', h5(p, 'lab-notebook.h5', 'f["/Index"][1] = f["/.calibration"].ref')),
        ('dot-name-renamed', h5(p, 'lab-notebook.h5', 'f.move("/.calibration", "/calibration")')),
    ],
}


def lifecycle(paths, examples, out):
    results = []
    base = json.loads((ROOT / examples['sensor-run']).read_text())

    def expect_fault(label, code, action):
        try:
            action()
            results.append({'check': label, 'ok': False, 'observed': 'accepted'})
        except SchemaxisError as error:
            results.append({'check': label, 'ok': error.fault.code == code, 'code': error.fault.code, 'location': error.fault.location})
        except Exception as error:
            results.append({'check': label, 'ok': False, 'observed': 'unstructured ' + repr(error)[:200]})

    expect_fault('timeout', 'RUNNER_TIMED_OUT', lambda: adaptor.run(base, out / 'life-timeout', executable=paths['python'], h5dump=paths['h5dump'], timeout=1e-6))
    from schemaxis.dispatch import allocation
    cancel = threading.Event()
    cancel.set()

    def cancelled():
        with allocation({'threads': 1, 'ranks': 1}, cancel):
            adaptor.run(base, out / 'life-cancel', executable=paths['python'], h5dump=paths['h5dump'])
    expect_fault('pre-launch cancellation', 'RUNNER_CANCELLED', cancelled)
    (out / 'life-exists').mkdir(exist_ok=True)
    expect_fault('existing output', 'OUTPUT_EXISTS', lambda: adaptor.run(base, out / 'life-exists', executable=paths['python'], h5dump=paths['h5dump']))
    expect_fault('wrong runtime', 'HDF5_UNSUPPORTED_RUNTIME',
                 lambda: adaptor.run(base, out / 'life-runtime', executable='/usr/bin/python3', h5dump=paths['h5dump']))
    campaign = case_document({'example': 'campaign', 'edits': [], 'resources': next(c for c in cases() if c['id'] == 'campaign')['resources']}, examples)
    campaign['inputs'][0]['sha256'] = '0' * 64
    expect_fault('changed input', 'HDF5_INPUT_CHANGED', lambda: adaptor.run(campaign, out / 'life-sha', executable=paths['python'], h5dump=paths['h5dump']))
    truncated = out / 'truncated.h5'
    truncated.write_bytes((ROOT / 'examples/schemaxis/hdf5-fixtures/vendor-export.h5').read_bytes()[:3000])
    inspect = json.loads((ROOT / examples['inspect']).read_text())
    inspect['source'] = str(truncated)
    expect_fault('truncated source', 'HDF5_NATIVE_FAILED', lambda: adaptor.run(inspect, out / 'life-truncated', executable=paths['python'], h5dump=paths['h5dump']))
    edit = json.loads((ROOT / examples['edit']).read_text())
    edit['source'] = str(ROOT / 'examples/schemaxis/hdf5-fixtures/vendor-export.h5')
    edit['edits'] = [{'action': 'delete', 'path': '/acquisition/missing'}]
    expect_fault('edit of a missing path', 'INVALID_HDF5_EDIT', lambda: adaptor.run(edit, out / 'life-edit', executable=paths['python'], h5dump=paths['h5dump']))
    return results


def workflows(paths, numpy, out):
    """Scheduled handoffs: HDF5 chain (artifact-bound dependencies, edit, inspect, extract, resume) and HDF5 -> NumPy PCA."""
    config = out / 'workflow-config.json'
    locations = {'hdf5': paths['python'], 'hdf5H5dump': paths['h5dump'], **({'numpy': numpy} if numpy else {})}
    config.write_text(json.dumps({'version': 1, 'locations': locations}))
    env = {'SCHEMAXIS_CONFIG': str(config), 'PYTHONPATH': str(ROOT / 'src'), 'PATH': '/usr/bin:/bin'}
    results = []

    def run(document, directory, resume=False):
        command = [sys.executable, '-m', 'schemaxis', 'run', str(document), '--output-directory', str(directory), '--timeout', '600'] + (['--resume'] if resume else [])
        done = subprocess.run(command, capture_output=True, text=True, env=env, timeout=1200)
        text = done.stdout
        return json.loads(text[text.index('{'):]) if '{' in text else {'status': 'failed', 'stderr': done.stderr[-800:]}

    chain = ROOT / 'examples/schemaxis/hdf5-chain-workflow.json'
    first = run(chain, out / 'wf-chain')
    again = run(chain, out / 'wf-chain', resume=True)
    signal = json.loads(next((out / 'wf-chain').glob('extract/*/*/signal.json')).read_text())['values'] if first.get('status') == 'succeeded' else None
    results.append({'check': 'chain workflow', 'ok': first.get('status') == 'succeeded' and signal == [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5], 'signal': signal})
    results.append({'check': 'chain resume reuses every verified step', 'ok': again.get('status') == 'succeeded' and all(j.get('reused') for j in again.get('jobs', [])),
                    'reused': [j.get('reused') for j in again.get('jobs', [])]})
    changed = out / 'wf-chain-changed.json'
    changed.write_text(chain.read_text().replace('"start": 4.5', '"start": 5.5'))
    third = run(changed, out / 'wf-chain-changed')
    if third.get('status') == 'succeeded':
        signal = json.loads(next((out / 'wf-chain-changed').glob('extract/*/*/signal.json')).read_text())['values']
        decisions = json.loads(next((out / 'wf-chain-changed').glob('inspect/*/*/expectations.json')).read_text())
    results.append({'check': 'changed upstream propagates', 'ok': third.get('status') == 'succeeded' and signal == [0.5, 1.5, 2.5, 3.5, 5.5, 6.5, 7.5, 8.5]
                    and decisions['unmet'] == 1})
    if numpy:
        wf = json.loads((ROOT / 'examples/schemaxis/hdf5-numpy-workflow.json').read_text().replace('/replace/with/numpy-sensors.csv', str(ROOT / 'examples/schemaxis/numpy-sensors.csv')))
        document = out / 'wf-numpy.json'
        document.write_text(json.dumps(wf))
        result = run(document, out / 'wf-numpy')
        ok = result.get('status') == 'succeeded'
        if ok:
            from schemaxis.tabular import read_csv
            rows = read_csv(next((out / 'wf-numpy').glob('pca/*/*/spectrum.csv')))['rows']
            want = [16.253968253968253, 4.063492063492063, 1.0158730158730158, 0.25396825396825395]
            ok = all(abs(r[1] - w) <= 1e-12 * w for r, w in zip(rows, want))
        results.append({'check': 'HDF5 extract feeds NumPy PCA (64 d^2/63 eigenvalues)', 'ok': ok})
    campaign = out / 'campaign' / 'campaign.h5'
    if campaign.is_file():
        inspect = json.loads((ROOT / 'examples/schemaxis/hdf5-inspect.json').read_text())
        inspect.update(source=str(campaign), expectations=[])
        try:
            adaptor.run(inspect, out / 'life-missing-dependency', executable=paths['python'], h5dump=paths['h5dump'])
            results.append({'check': 'virtual sources without dependencies are refused', 'ok': False})
        except SchemaxisError as error:
            results.append({'check': 'virtual sources without dependencies are refused', 'ok': error.fault.code == 'HDF5_MISSING_DEPENDENCY',
                            'code': error.fault.code, 'files': error.fault.observed.get('files')})
        fx = ROOT / 'examples/schemaxis/hdf5-fixtures'
        inspect['dependencies'] = [{'id': 'runA', 'path': str(fx / 'run-a.h5'), 'role': 'virtualSource'},
                                   {'id': 'runB', 'path': str(fx / 'run-b.h5'), 'role': 'virtualSource'},
                                   {'id': 'probe', 'path': str(fx / 'probe-counts.bin'), 'role': 'rawStorage'}]
        try:
            adaptor.run(inspect, out / 'life-declared-dependency', executable=paths['python'], h5dump=paths['h5dump'])
            inventory = json.loads((out / 'life-declared-dependency' / 'inventory.json').read_text())
            preview = inventory['objects']['/campaign/signal']['values']['preview']
            results.append({'check': 'declared dependencies resolve virtual and raw data', 'ok': [float.fromhex(v) for v in preview] ==
                            [0.5, 1.5, 2.5, 3.5, -999.0, 5.5, 6.5, 7.5][:len(preview)] and len(preview) == 6})
        except SchemaxisError as error:
            results.append({'check': 'declared dependencies resolve virtual and raw data', 'ok': False, 'code': error.fault.code})
    return results


SENTINEL = [19031903, 22042204, 65026502, 88018801]
ADMISSION_FIXTURES = r'''
import h5py, numpy as np, struct, sys, os
d = sys.argv[1]
s = os.path.join(d, 'sentinel.raw')
open(s, 'wb').write(struct.pack('<4i', *SENTINEL))
with h5py.File(os.path.join(d, 'sentinel.h5'), 'w') as f:
    f['secret'] = np.array(SENTINEL, dtype='<i4')
def make(name, build):
    with h5py.File(os.path.join(d, name), 'w') as f:
        build(f)
make('abs-raw.h5', lambda f: f.create_dataset('x', shape=(4,), dtype='<i4', external=[(s, 0, 16)]))
make('rel-raw.h5', lambda f: f.create_dataset('x', shape=(4,), dtype='<i4', external=[('../admission/sentinel.raw', 0, 16)]))
def vds(target):
    def build(f):
        layout = h5py.VirtualLayout(shape=(4,), dtype='<i4')
        layout[:] = h5py.VirtualSource(target, 'secret', shape=(4,))
        f.create_virtual_dataset('v', layout)
    return build
make('abs-vds.h5', vds(os.path.join(d, 'sentinel.h5')))
make('bare-vds.h5', vds('sentinel.h5'))
make('nested-raw.h5', lambda f: f.create_dataset('x', shape=(4,), dtype='<i4', external=[(s, 0, 16)]))
make('nested-vds.h5', vds('nested-raw.h5'))
def plugin(f):
    dcpl = h5py.h5p.create(h5py.h5p.DATASET_CREATE)
    dcpl.set_chunk((4,))
    dcpl.set_filter(307, h5py.h5z.FLAG_OPTIONAL)
    sid = h5py.h5s.create_simple((4,))
    h5py.h5d.create(f.id, b'p', h5py.h5t.STD_I32LE, sid, dcpl=dcpl)
make('plugin.h5', plugin)
def links(f):
    f['local'] = np.arange(3)
    f['ext'] = h5py.ExternalLink(os.path.join(d, 'sentinel.h5'), '/secret')
    f['alias'] = h5py.SoftLink('/ext')
make('links.h5', links)
fifo = os.path.join(d, 'owned.fifo')
os.mkfifo(fifo)
def fifo_links(f):
    f['external'] = h5py.ExternalLink(fifo, '/target')
    f['alias'] = h5py.SoftLink('/external/target')
make('fifo-link.h5', fifo_links)
make('bundle-link.h5', lambda f: f.__setitem__('evidence', h5py.ExternalLink('plan.json', '/x')))
make('declared-link.h5', lambda f: f.__setitem__('secret', h5py.ExternalLink('sentinel.h5', '/secret')))
'''.replace('SENTINEL', repr(SENTINEL))


def admission(paths, out):
    """Metadata-first closure: unsafe or undeclared referenced files and unknown filters are refused before any value read."""
    import struct
    fixtures = out / 'admission'
    fixtures.mkdir()
    subprocess.run([paths['python'], '-I', '-c', ADMISSION_FIXTURES, str(fixtures)], check=True, timeout=60, env={'HDF5_PLUGIN_PRELOAD': '::'})
    needle = struct.pack('<i', SENTINEL[0])
    results = []

    def leaked(run, declared=()):
        hits = []
        for path in run.rglob('*'):
            if path.is_file() and not path.is_fifo() and path.name not in ('authored.json', 'plan.json', *declared) and needle in path.read_bytes():
                hits.append(path.name)
        return hits

    def probe(label, name, code, deps=(), operation='inspectFile'):
        document = {'version': 'schemaxis.hdf5/1', 'operation': operation, 'source': str(fixtures / name),
                    'dependencies': [{'id': 'd%d' % i, 'path': str(fixtures / dep), 'role': role} for i, (dep, role) in enumerate(deps)]}
        if operation == 'extractData':
            document['extracts'] = [{'id': 'x', 'dataset': '/x', 'format': 'json'}]
        if operation == 'editFile':
            document['edits'] = [{'action': 'setAttribute', 'path': '/', 'attribute': {'name': 'note', 'value': 'edited'}}]
        run = out / ('admission-' + label)
        try:
            adaptor.run(document, run, executable=paths['python'], h5dump=paths['h5dump'])
            got = None
        except SchemaxisError as error:
            got = error.fault.code
        hits = leaked(run, [dep for dep, _ in deps])
        results.append({'check': 'admission ' + label, 'ok': got == code and not hits, 'code': got, 'sentinelBytesIn': hits})

    probe('absolute raw', 'abs-raw.h5', 'HDF5_UNSAFE_DEPENDENCY_PATH')
    probe('traversing raw', 'rel-raw.h5', 'HDF5_UNSAFE_DEPENDENCY_PATH', operation='extractData')
    probe('absolute virtual', 'abs-vds.h5', 'HDF5_UNSAFE_DEPENDENCY_PATH', operation='editFile')
    probe('undeclared virtual', 'bare-vds.h5', 'HDF5_MISSING_DEPENDENCY')
    probe('wrong-role virtual', 'bare-vds.h5', 'HDF5_MISSING_DEPENDENCY', deps=[('sentinel.h5', 'rawStorage')])
    probe('nested absolute raw', 'nested-vds.h5', 'HDF5_UNSAFE_DEPENDENCY_PATH', deps=[('nested-raw.h5', 'virtualSource')])
    probe('unknown filter', 'plugin.h5', 'HDF5_UNSUPPORTED_FILTER')
    probe('absolute external link', 'links.h5', 'HDF5_UNSAFE_DEPENDENCY_PATH')
    started = time.monotonic()
    probe('absolute external link to a FIFO with soft alias', 'fifo-link.h5', 'HDF5_UNSAFE_DEPENDENCY_PATH')
    results[-1]['seconds'] = round(time.monotonic() - started, 2)
    results[-1]['ok'] = results[-1]['ok'] and results[-1]['seconds'] < 30
    probe('external link to an undeclared bundle file', 'bundle-link.h5', 'HDF5_MISSING_DEPENDENCY')
    probe('declared external link target', 'declared-link.h5', None, deps=[('sentinel.h5', 'externalLink')])
    run = out / 'admission-declared-virtual'
    document = {'version': 'schemaxis.hdf5/1', 'operation': 'extractData', 'source': str(fixtures / 'bare-vds.h5'),
                'dependencies': [{'id': 'sentinel', 'path': str(fixtures / 'sentinel.h5'), 'role': 'virtualSource'}],
                'extracts': [{'id': 'v', 'dataset': '/v', 'format': 'json'}]}
    try:
        adaptor.run(document, run, executable=paths['python'], h5dump=paths['h5dump'])
        values = json.loads((run / 'v.json').read_text())['values']
        results.append({'check': 'admission declared virtual source is read', 'ok': values == SENTINEL})
    except SchemaxisError as error:
        results.append({'check': 'admission declared virtual source is read', 'ok': False, 'code': error.fault.code})
    if (fixtures / 'owned.fifo').is_fifo():
        (fixtures / 'owned.fifo').unlink()
    return results


MESHIO_READ = r'''
import json, meshio
with meshio.xdmf.TimeSeriesReader('cooling-block.xdmf') as r:
    points, cells = r.read_points_cells()
    steps = []
    for k in range(r.num_steps):
        t, pd, cd = r.read_data(k)
        steps.append([t, pd['temperature'].tolist(), cd['heat_flux'][0].tolist()])
print(json.dumps({'points': points.tolist(), 'cells': [[c.type, c.data.tolist()] for c in cells], 'steps': steps}))
'''


def meshio_consumer(meshio_python, out):
    """Downstream XDMF consumer: meshio's own XDMF parser must recover the authored mesh and fields."""
    run = out / 'mesh-fields'
    done = subprocess.run([meshio_python, '-I', '-c', MESHIO_READ], cwd=run, capture_output=True, text=True, timeout=120,
                          env={'HDF5_PLUGIN_PRELOAD': '::', 'PATH': '/usr/bin:/bin'})
    try:
        got = json.loads(done.stdout)
    except ValueError:
        return [{'check': 'meshio reads the XDMF series', 'ok': False, 'stderr': done.stderr[-600:]}]
    want = {'points': [[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0], [0, 0, 0.1], [0.1, 0.1, 0.1]], 'cells': [['tetra', [[0, 1, 2, 3], [1, 2, 3, 4]]]],
            'steps': [[0.0, [350] * 5, [[0, 0, 0], [0, 0, 0]]], [30.0, [340, 345, 345, 345, 348], [[-120, 0, 15], [-80, 5, 10]]],
                      [60.0, [330.5, 339, 339, 339, 346], [[-95, 0, 12], [-61, 4, 8]]]]}
    return [{'check': 'meshio reads the XDMF series (independent XDMF consumer)', 'ok': got == json.loads(json.dumps(want))}]


XARRAY_READ = r'''
import json, sys, xarray as xr
ds = xr.open_dataset(sys.argv[1], engine='h5netcdf', group='/array')
v = ds['voltage']
print(json.dumps({'dims': list(v.dims), 'units': v.attrs.get('units'), 'timeUnits': ds['time'].attrs.get('units'),
                  'channel': ds['channel'].values.tolist(), 'atHalfSecond': v.sel(time=0.5).values.tolist()}))
'''


def netcdf_consumer(python, out):
    """NetCDF-4 view: xarray (h5netcdf engine) must present the scaled HDF5 array with named dimensions and units."""
    found = sorted((out / 'wf-numpy').glob('store/*/*/sensor-array.h5'))
    if not found:
        return [{'check': 'xarray reads HDF5 dimension scales as NetCDF-4 dimensions', 'ok': False, 'observed': 'no workflow output'}]
    done = subprocess.run([python, '-I', '-c', XARRAY_READ, str(found[0])], capture_output=True, text=True, timeout=120,
                          env={'HDF5_PLUGIN_PRELOAD': '::', 'PATH': '/usr/bin:/bin'})
    want = {'dims': ['time', 'channel'], 'units': 'mV', 'timeUnits': 's', 'channel': [1, 2, 3, 4], 'atHalfSecond': [98.75, -53.75, 19.25, 2.75]}
    try:
        got = json.loads(done.stdout)
    except ValueError:
        got = {'stderr': done.stderr[-400:]}
    return [{'check': 'xarray reads HDF5 dimension scales as NetCDF-4 dimensions', 'ok': got == want, 'observed': got}]


LARGE_FIXTURE = r'''
import h5py, numpy as np, sys
with h5py.File(sys.argv[1], 'w') as f:
    t = f.create_dataset('time', data=np.arange(1200) * 0.5)
    t.attrs['units'] = 's'
    t.make_scale('time')
    grid = np.arange(1200)[:, None] * 1000.0 + np.arange(1000)[None, :]
    d = f.create_dataset('grid', data=grid, chunks=(100, 100), compression='gzip', compression_opts=1)
    d.attrs['units'] = 'K'
    d.dims[0].attach_scale(t)
'''


def large_extraction(paths, out):
    """Beyond the full-reading budget, extracted selections are still checked by an independent h5dump hyperslab read."""
    source = out / 'large-grid.h5'
    subprocess.run([paths['python'], '-I', '-c', LARGE_FIXTURE, str(source)], check=True, timeout=120, env={'HDF5_PLUGIN_PRELOAD': '::'})
    document = {'version': 'schemaxis.hdf5/1', 'operation': 'extractData', 'source': str(source), 'extracts': [
        {'id': 'window', 'dataset': '/grid', 'selection': {'kind': 'hyperslab', 'start': [600, 10], 'count': [3, 4], 'stride': [100, 2]}},
        {'id': 'probe', 'dataset': '/grid', 'selection': {'kind': 'points', 'points': [[1199, 999], [0, 0]]}, 'format': 'json'}]}
    run = out / 'large-extract'
    try:
        adaptor.run(document, run, executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
        from schemaxis.tabular import read_csv
        rows = read_csv(run / 'window.csv')['rows']
        want = [[0.5 * i] + [1000.0 * i + j for j in (10, 12, 14, 16)] for i in (600, 700, 800)]
        probe = json.loads((run / 'probe.json').read_text())['values']
        verified = adaptor.verify_directory(run, paths)
        ok = rows == want and probe == [1199999.0, 0.0] and verified['verified']
        return [{'check': 'large adopted file: independent hyperslab and point reads', 'ok': ok, 'rows': rows, 'probe': probe}]
    except SchemaxisError as error:
        return [{'check': 'large adopted file: independent hyperslab and point reads', 'ok': False, 'code': error.fault.code, 'message': error.fault.message}]


MEMORY_FIXTURE = r'''
import h5py, numpy as np, sys
with h5py.File(sys.argv[1], 'w') as f:
    wide = np.dtype([('f%d' % k, '<f8') for k in range(64)])
    rows = np.zeros(8000, dtype=wide)
    for k in range(64):
        rows['f%d' % k] = np.arange(8000) * 64 + k
    f['/wide'] = rows
    padded = np.dtype({'names': ['t', 'v'], 'formats': ['<f8', '<f8'], 'offsets': [0, 32], 'itemsize': 64})
    p = np.zeros(1000, dtype=padded)
    p['t'] = np.arange(1000) * 0.5
    p['v'] = np.arange(1000) * 2.0
    f['/padded'] = p
    inner = np.dtype({'names': ['a'], 'formats': ['<f8'], 'offsets': [0], 'itemsize': 4096})
    f['/nested'] = np.zeros(64, dtype=np.dtype([('id', '<i4'), ('blob', inner)]))
    mixed = np.dtype([('t', '<f8'), ('note', h5py.string_dtype())])
    f['/mixed'] = np.array([(0.5 * i, 'n%d' % i) for i in range(1000)], dtype=mixed)
    f['/notes'] = np.array(['x' * (i % 50) for i in range(100)], dtype=h5py.string_dtype())
    one = np.zeros(1000, dtype=[('x', '<f8')])
    one['x'] = np.arange(1000) * 0.25
    f['/single'] = one
    pad1 = np.zeros(1000, dtype=np.dtype({'names': ['x'], 'formats': ['<f8'], 'offsets': [8], 'itemsize': 32}))
    pad1['x'] = np.arange(1000) * 4.0
    f['/padded-single'] = pad1
'''


def memory_variants(paths, out):
    """memoryBytes over wide, padded, nested and variable-length records: direct field reads, packed records, located refusals."""
    source = out / 'memory-records.h5'
    subprocess.run([paths['python'], '-I', '-c', MEMORY_FIXTURE, str(source)], check=True, timeout=120, env={'HDF5_PLUGIN_PRELOAD': '::'})

    def doc(extracts, memory):
        return {'version': 'schemaxis.hdf5/1', 'operation': 'extractData', 'source': str(source), 'access': {'memoryBytes': memory}, 'extracts': extracts}
    results = []
    accepted = (('wide-fields', doc([{'id': 'pair', 'dataset': '/wide', 'fields': ['f0', 'f63'], 'format': 'csv'}], 32768)),
                ('padded-records', doc([{'id': 'padded', 'dataset': '/padded', 'format': 'csv'}], 4096)),
                ('fixed-fields-of-mixed', doc([{'id': 'times', 'dataset': '/mixed', 'fields': ['t'], 'format': 'json'}], 4096)),
                ('one-member-records', doc([{'id': 'single', 'dataset': '/single', 'format': 'json'}], 4096)),
                ('padded-one-member', doc([{'id': 'padded_single', 'dataset': '/padded-single', 'format': 'csv'}], 4096)),
                ('reordered-fields', doc([{'id': 'reordered', 'dataset': '/wide', 'fields': ['f63', 'f0'], 'format': 'csv'}], 32768)))
    for label, document in accepted:
        run = out / ('memory-' + label)
        try:
            adaptor.run(document, run, executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
            streamed = json.loads((run / 'extract-result.json').read_text())['result']['extracts'][0]['streaming']
            ok = streamed['largestBlockBytes'] <= document['access']['memoryBytes'] and streamed['blocks'] > 1
            from schemaxis.tabular import read_csv
            if label == 'wide-fields':
                table = read_csv(run / 'pair.csv')
                ok = ok and table['columns'] == ['f0', 'f63'] and table['rows'][-1] == [7999 * 64.0, 7999 * 64 + 63.0] and streamed['blocks'] == 4
            if label == 'one-member-records':
                values = json.loads((run / 'single.json').read_text())['values']
                ok = ok and values[:2] == [[0.0], [0.25]] and values[-1] == [249.75]
            if label == 'padded-one-member':
                table = read_csv(run / 'padded_single.csv')
                ok = ok and table['columns'] == ['x'] and table['rows'][-1] == [3996.0]
            if label == 'reordered-fields':
                table = read_csv(run / 'reordered.csv')
                ok = ok and table['columns'] == ['f63', 'f0'] and table['rows'][-1] == [7999 * 64 + 63.0, 7999 * 64.0]
            results.append({'check': 'memoryBytes ' + label, 'ok': ok, 'streaming': streamed})
            results.append({'check': 'memoryBytes unchanged verify: ' + label, **attack(paths, run, 'unchanged', None)})
        except SchemaxisError as error:
            results.append({'check': 'memoryBytes ' + label, 'ok': False, 'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message})
    refused = (('variable-length strings', doc([{'id': 'notes', 'dataset': '/notes', 'format': 'json'}], 4096), 'INVALID_HDF5_ACCESS', '$.extracts.notes'),
               ('record with a variable-length field', doc([{'id': 'mixed', 'dataset': '/mixed', 'format': 'json'}], 4096), 'INVALID_HDF5_ACCESS', '$.extracts.mixed'),
               ('nested padded record', doc([{'id': 'nested', 'dataset': '/nested', 'format': 'json'}], 8192), 'HDF5_RESOURCE_LIMIT', '$.extracts.nested'))
    for label, document, code, location in refused:
        try:
            adaptor.run(document, out / ('memory-refused-' + label.replace(' ', '-')), executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
            results.append({'check': 'memoryBytes refuses ' + label, 'ok': False})
        except SchemaxisError as error:
            results.append({'check': 'memoryBytes refuses ' + label, 'ok': error.fault.code == code and error.fault.location == location,
                            'code': error.fault.code, 'location': error.fault.location})
    return results


WHERE_FIXTURE = r'''
import h5py, numpy as np, sys
n = 1500000
with h5py.File(sys.argv[1], 'w') as f:
    f.create_dataset('/flag[0]', data=(np.arange(n) % 1000 == 7).astype('u1'), chunks=(65536,), compression='gzip', compression_opts=1)
    f.create_dataset('/signal [V]', data=np.stack([np.arange(n) * 0.5, -np.arange(n) * 1.0], axis=1), chunks=(65536, 2))
'''


def where_variants(paths, out):
    """where over a file beyond the full-reading budget, streamed under memoryBytes, and on an edited copy."""
    source = out / 'where-large.h5'
    subprocess.run([paths['python'], '-I', '-c', WHERE_FIXTURE, str(source)], check=True, timeout=120, env={'HDF5_PLUGIN_PRELOAD': '::'})
    results = []
    document = {'version': 'schemaxis.hdf5/1', 'operation': 'extractData', 'source': str(source), 'access': {'memoryBytes': 8192},
                'extracts': [{'id': 'flagged', 'dataset': '/signal [V]', 'format': 'csv', 'where': [{'dataset': '/flag[0]', 'op': 'eq', 'value': 1}]}]}
    run = out / 'where-large'
    try:
        adaptor.run(document, run, executable=paths['python'], h5dump=paths['h5dump'], timeout=900)
        from schemaxis.tabular import read_csv
        rows = read_csv(run / 'flagged.csv')['rows']
        streamed = json.loads((run / 'extract-result.json').read_text())['result']['extracts'][0]['streaming']
        ok = len(rows) == 1500 and rows[0] == [3.5, -7.0] and rows[-1] == [749503.5, -1499007.0] and streamed['blocks'] == 3
        results.append({'check': 'where over 1.5M rows streamed under memoryBytes', 'ok': ok, 'streaming': streamed})
        results.append({'check': 'where large unchanged verify', **attack(paths, run, 'unchanged', None)})
        results.append({'check': 'where large flag tamper refused', **attack(paths, run, 'flag', h5(paths, 'source.h5', 'f["/flag[0]"][17] = 1'))})
    except SchemaxisError as error:
        results.append({'check': 'where over 1.5M rows streamed under memoryBytes', 'ok': False, 'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message})
    edit = {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': str(ROOT / 'examples/schemaxis/hdf5-fixtures/sensor-run.h5'),
            'file': {'name': 'faulted.h5'}, 'edits': [{'action': 'write', 'path': '/run/state', 'selection': {'kind': 'points', 'points': [[1]]},
                                                       'data': {'source': 'values', 'values': ['FAULT']}}],
            'extracts': [{'id': 'faults', 'dataset': '/run/raw/counts', 'format': 'json', 'where': [{'dataset': '/run/state', 'op': 'eq', 'value': 'FAULT'}]}]}
    run = out / 'where-edit'
    try:
        adaptor.run(edit, run, executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
        values = json.loads((run / 'faults.json').read_text())['values']
        results.append({'check': 'where on an edited copy sees the edit', 'ok': values == [1, 4, 19, 22], 'values': values})
        results.append({'check': 'where edit unchanged verify', **attack(paths, run, 'unchanged', None)})
    except SchemaxisError as error:
        results.append({'check': 'where on an edited copy sees the edit', 'ok': False, 'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message})
    return results


def chunk_variants(paths, out):
    """Chunk indexes on a created file (edge chunks, little-endian floats, gzip only), on an edited copy with unallocated
    chunks read as the fill value, and refusals for undecodable filters, contiguous layout and multi-file drivers."""
    results = []
    sensor = str(ROOT / 'examples/schemaxis/hdf5-fixtures/sensor-run.h5')
    created = {'version': 'schemaxis.hdf5/1', 'operation': 'createFile', 'file': {'name': 'tiles.h5'},
               'objects': [{'path': '/tile', 'type': {'class': 'float', 'bits': 32}, 'shape': [5, 7], 'data': {'source': 'range', 'start': 0, 'step': 0.5},
                            'storage': {'chunks': [2, 3], 'compression': 'gzip', 'level': 9}}],
               'extracts': [{'id': 'tile', 'dataset': '/tile', 'format': 'chunks'}]}
    resized = {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': sensor, 'file': {'name': 'grown.h5'},
               'edits': [{'action': 'resize', 'path': '/run/raw/counts', 'shape': [9, 2]}],
               'extracts': [{'id': 'grown', 'dataset': '/run/raw/counts', 'format': 'chunks'}]}
    repeated = {'version': 'schemaxis.hdf5/1', 'operation': 'createFile', 'file': {'name': 'repeat.h5'},
                'objects': [{'path': '/repeat', 'type': {'class': 'uint', 'bits': 32}, 'shape': [8], 'data': {'source': 'values', 'values': [1, 2, 3, 4, 1, 2, 3, 4]},
                             'storage': {'chunks': [4], 'compression': 'gzip', 'level': 4, 'shuffle': True, 'fletcher32': True}}],
                'extracts': [{'id': 'repeat', 'dataset': '/repeat', 'format': 'chunks'}]}
    run = out / 'chunks-repeated-identical-chunks'
    try:
        adaptor.run(repeated, run, executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
        listed = json.loads((run / 'repeat.chunks.json').read_text())['chunks']
        results.append({'check': 'chunk index: identical chunks at distinct offsets', 'ok': listed[0]['sha256'] == listed[1]['sha256'] and listed[0]['byteOffset'] != listed[1]['byteOffset']})

        def swap(d):
            index = json.loads((d / 'repeat.chunks.json').read_text())
            index['chunks'][1]['byteOffset'] = index['chunks'][0]['byteOffset']
            (d / 'repeat.chunks.json').write_text(json.dumps(index, indent=1, sort_keys=True) + '\n')

        def boolean_mask(d):
            index = json.loads((d / 'repeat.chunks.json').read_text())
            index['chunks'][0]['filterMask'] = False
            (d / 'repeat.chunks.json').write_text(json.dumps(index, indent=1, sort_keys=True) + '\n')
        for label, mutate in (('unchanged', None), ('identical-chunk-offset-swap', swap), ('boolean-filter-mask', boolean_mask)):
            results.append({'check': 'chunk index identity attack ' + label, **attack(paths, run, label, mutate)})
    except SchemaxisError as error:
        results.append({'check': 'chunk index: identical chunks at distinct offsets', 'ok': False, 'code': error.fault.code, 'message': error.fault.message})
    for label, document, expected in (('created file edge chunks', created, 9), ('edited copy with unallocated chunks', resized, 2)):
        run = out / ('chunks-' + label.replace(' ', '-'))
        try:
            adaptor.run(document, run, executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
            report = json.loads((run / 'hdf5-report.json').read_text())['extracts'][0]['chunks']
            results.append({'check': 'chunk index: ' + label, 'ok': report['count'] == expected, 'chunks': report})
            results.append({'check': 'chunk index unchanged verify: ' + label, **attack(paths, run, 'unchanged', None)})
        except SchemaxisError as error:
            results.append({'check': 'chunk index: ' + label, 'ok': False, 'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message})
    refusals = (('lzf filter', {'version': 'schemaxis.hdf5/1', 'operation': 'extractData', 'source': sensor,
                                'extracts': [{'id': 'p', 'dataset': '/run/calibrated/pressure', 'format': 'chunks'}]}, '$.extracts.p.format'),
                ('contiguous layout', {'version': 'schemaxis.hdf5/1', 'operation': 'extractData', 'source': sensor,
                                       'extracts': [{'id': 't', 'dataset': '/run/raw/time', 'format': 'chunks'}]}, '$.extracts.t.format'),
                ('family driver', {**created, 'file': {'name': 'tiles.h5', 'driver': 'family', 'memberBytes': 4096}}, '$.extracts[0].format'))
    for label, document, location in refusals:
        try:
            adaptor.run(document, out / ('chunks-refused-' + label.replace(' ', '-')), executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
            results.append({'check': 'chunk index refuses ' + label, 'ok': False})
        except SchemaxisError as error:
            results.append({'check': 'chunk index refuses ' + label, 'ok': error.fault.code == 'INVALID_HDF5_EXTRACT' and error.fault.location == location,
                            'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message})
    return results


UNSIGNED = [0, 1, 2 ** 53 - 1, 2 ** 53, 2 ** 53 + 1, 2 ** 63 - 2, 2 ** 63 - 1, 2 ** 63, 2 ** 63 + 1, 2 ** 64 - 2, 2 ** 64 - 1]
SIGNED = [-2 ** 63, -2 ** 63 + 1, -2 ** 53 - 1, -2 ** 53, -1, 0, 1, 2 ** 53, 2 ** 53 + 1, 2 ** 63 - 2, 2 ** 63 - 1]
INTEGER_FIXTURE = r'''
import h5py, numpy as np, sys
with h5py.File(sys.argv[1], 'w') as f:
    f['/u64'] = np.array(%r, dtype='<u8')
    f['/i64'] = np.array(%r, dtype='>i8')
''' % (UNSIGNED, SIGNED)
INTEGER_CONDITIONS = (
    ('u64', {'op': 'in', 'values': [0, 2 ** 63]}), ('u64', {'op': 'in', 'values': [2 ** 53, 2 ** 64 - 1, 2 ** 63 - 1]}),
    ('u64', {'op': 'eq', 'value': 2 ** 53 + 1}), ('u64', {'op': 'ne', 'value': 2 ** 63}), ('u64', {'op': 'gt', 'value': 2 ** 64 - 2}),
    ('u64', {'op': 'between', 'value': 2 ** 63 - 1, 'upper': 2 ** 63 + 1}), ('u64', {'op': 'lt', 'value': 2 ** 53 + 1}),
    ('i64', {'op': 'in', 'values': [-2 ** 63, -1, 2 ** 53]}), ('i64', {'op': 'between', 'value': -2 ** 53 - 1, 'upper': -2 ** 53}),
    ('i64', {'op': 'ge', 'value': 2 ** 63 - 1}), ('i64', {'op': 'le', 'value': -2 ** 63 + 1}), ('i64', {'op': 'eq', 'value': 2 ** 53 + 1}))


def integer_membership(paths, out):
    """where on 64-bit integers near 2**53, 2**63 and 2**64 selects exactly the rows exact integer arithmetic selects."""
    source = out / 'integer-where.h5'
    subprocess.run([paths['python'], '-I', '-c', INTEGER_FIXTURE, str(source)], check=True, timeout=60, env={'HDF5_PLUGIN_PRELOAD': '::'})
    holds = {'in': lambda x, c: x in c['values'], 'eq': lambda x, c: x == c['value'], 'ne': lambda x, c: x != c['value'],
             'gt': lambda x, c: x > c['value'], 'ge': lambda x, c: x >= c['value'], 'lt': lambda x, c: x < c['value'],
             'le': lambda x, c: x <= c['value'], 'between': lambda x, c: c['value'] <= x <= c['upper']}
    extracts = [{'id': 'c%d' % k, 'dataset': '/' + name, 'format': 'json', 'where': [condition]} for k, (name, condition) in enumerate(INTEGER_CONDITIONS)]
    run = out / 'integer-where'
    try:
        adaptor.run({'version': 'schemaxis.hdf5/1', 'operation': 'extractData', 'source': str(source), 'extracts': extracts}, run,
                    executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
        results = []
        for k, (name, condition) in enumerate(INTEGER_CONDITIONS):
            data = UNSIGNED if name == 'u64' else SIGNED
            want = [x for x in data if holds[condition['op']](x, condition)]
            got = json.loads((run / ('c%d.json' % k)).read_text())['values']
            results.append({'check': 'exact integer where %s %s' % (name, json.dumps(condition)), 'ok': got == want, 'expected': want, 'observed': got})
        return results + [{'check': 'exact integer where unchanged verify', **attack(paths, run, 'unchanged', None)}]
    except SchemaxisError as error:
        return [{'check': 'exact integer where', 'ok': False, 'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message}]


COPY_FIXTURE = r'''
import h5py, numpy as np, sys
n = 1200000
with h5py.File(sys.argv[1], 'w') as f:
    kw = dict(shape=(n,), dtype='<f4', chunks=(65536,), compression='gzip', compression_opts=4, shuffle=True)
    f.create_dataset('/a', data=np.arange(n, dtype='<f4') * 0.25, **{k: v for k, v in kw.items() if k not in ('shape', 'dtype')})
    f.create_dataset('/b', **kw)
    f.create_dataset('/c', shape=(n,), dtype='<f4', chunks=(65536,), compression='gzip', compression_opts=1, shuffle=True)
    f.create_dataset('/d', shape=(n,), dtype='<f4', chunks=(65536,), compression='lzf')
    p = f.create_dataset('/partial', **kw)
    p[:65536] = 1.0
    f['/small'] = np.arange(8, dtype='<i4')
'''


def copy_chunk_variants(paths, out):
    """copyChunks over 1.2M elements beyond the full-reading budget, and located refusals for mismatched layouts and touched sources."""
    source = out / 'copy-chunks.h5'
    subprocess.run([paths['python'], '-I', '-c', COPY_FIXTURE, str(source)], check=True, timeout=120, env={'HDF5_PLUGIN_PRELOAD': '::'})

    def doc(edits, name='copied.h5'):
        return {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': str(source), 'file': {'name': name}, 'edits': edits}
    results = []
    run = out / 'copy-chunks-large'
    try:
        adaptor.run(doc([{'action': 'copyChunks', 'path': '/a', 'to': '/b'}]), run, executable=paths['python'], h5dump=paths['h5dump'], timeout=900)
        results.append({'check': 'copyChunks 1.2M floats beyond the reading budget', 'ok': True})
        results.append({'check': 'copyChunks large unchanged verify', **attack(paths, run, 'unchanged', None)})
        results.append({'check': 'copyChunks large target tamper refused', **attack(paths, run, 'target', h5(paths, 'copied.h5', 'f["/b"][1199999] = 0'))})
    except SchemaxisError as error:
        results.append({'check': 'copyChunks 1.2M floats beyond the reading budget', 'ok': False, 'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message})
    refusals = (('different gzip level', [{'action': 'copyChunks', 'path': '/a', 'to': '/c'}], 'HDF5_CHUNK_LAYOUT_MISMATCH', '$.edits[0]'),
                ('different filters', [{'action': 'copyChunks', 'path': '/a', 'to': '/d'}], 'INVALID_HDF5_EDIT', '$.edits[0].to'),
                ('partially allocated source', [{'action': 'copyChunks', 'path': '/partial', 'to': '/b'}], 'HDF5_CHUNK_LAYOUT_MISMATCH', '$.edits[0]'),
                ('contiguous source', [{'action': 'copyChunks', 'path': '/small', 'to': '/a'}], 'INVALID_HDF5_EDIT', '$.edits[0].to'),
                ('source changed earlier', [{'action': 'setAttribute', 'path': '/a', 'attribute': {'name': 'note', 'value': 'x'}},
                                            {'action': 'copyChunks', 'path': '/a', 'to': '/b'}], 'INVALID_HDF5_EDIT', '$.edits[1].path'))
    for label, edits, code, location in refusals:
        try:
            adaptor.run(doc(edits), out / ('copy-chunks-refused-' + label.replace(' ', '-')), executable=paths['python'], h5dump=paths['h5dump'], timeout=900)
            results.append({'check': 'copyChunks refuses ' + label, 'ok': False})
        except SchemaxisError as error:
            results.append({'check': 'copyChunks refuses ' + label, 'ok': error.fault.code == code and error.fault.location == location,
                            'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message})
    return results


def sieve_variants(paths, out, mpi=None):
    """access.sieveBufferBytes on every operation family: each native stage's file access property list reports the declared size."""
    examples = {e['id']: e['reference'] for e in json.loads(READINESS.read_text())['routes']['schemaxis.hdf5/1']['examples']}
    results = []
    names = ['extract', 'edit', 'compare', 'inspect', 'swmr-monitor', 'campaign', 'mesh-fields', 'sensor-run', 'raw-export', 'import-group']
    if mpi and mpi.get('mpiPython'):
        names += ['parallel-write', 'parallel-extract']
    for name in names:
        case = next(c for c in cases() if c['example'] == name)
        document = case_document(case, examples)
        document['access'] = {**document.get('access', {}), 'sieveBufferBytes': 262144}
        run = out / ('sieve-' + name)
        try:
            adaptor.run(document, run, executable=paths['python'], h5dump=paths['h5dump'], timeout=900, **(mpi or {}))
            seen = {r.name: json.loads(r.read_text()).get('access') for r in run.glob('*-result.json')}
            applied = {k: v['sieveBufferBytes'] for k, v in seen.items() if v is not None}
            ok = bool(applied) and set(applied.values()) == {262144}
            results.append({'check': 'sieve buffer applied: ' + name, 'ok': ok, 'stages': applied})
            results.append({'check': 'sieve buffer unchanged verify: ' + name, **attack(paths, run, 'unchanged', None)})
        except SchemaxisError as error:
            results.append({'check': 'sieve buffer applied: ' + name, 'ok': False, 'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message})
    try:
        adaptor.plan({'version': 'schemaxis.hdf5/1', 'operation': 'inspectFile', 'source': '/tmp/x.h5', 'access': {'sieveBufferBytes': 100}})
        results.append({'check': 'sieve buffer below 512 bytes refused', 'ok': False})
    except SchemaxisError as error:
        results.append({'check': 'sieve buffer below 512 bytes refused', 'ok': error.fault.location == '$.access.sieveBufferBytes', 'code': error.fault.code})
    return results


ATTRIBUTE_FIXTURE = r'''
import h5py, numpy as np, sys
with h5py.File(sys.argv[1], 'w') as f:
    d = f.create_dataset('/tracked', data=np.arange(6, dtype='<i4'), track_order=True)
    d.attrs['zeta'] = 1
    d.attrs['table'] = np.arange(10000, dtype='<f8')
    d.attrs['alpha'] = 'two'
    g = f.create_group('/meta', track_order=True)
    g.attrs['b'] = 1
    g.attrs['a'] = 2
    f['/plain'] = np.arange(3, dtype='<i4')
'''


def attribute_variants(paths, out):
    """Large attributes and creation order on an adopted file through inspect, edits, copy and repack; located refusals."""
    source = out / 'attributes-source.h5'
    subprocess.run([paths['python'], '-I', '-c', ATTRIBUTE_FIXTURE, str(source)], check=True, timeout=60, env={'HDF5_PLUGIN_PRELOAD': '::'})
    big = {'name': 'second table', 'type': {'class': 'float', 'bits': 32}, 'shape': [20000], 'data': {'source': 'range', 'start': 0, 'step': 0.5}}
    edits = [{'action': 'setAttribute', 'path': '/tracked', 'attribute': {'name': 'zeta', 'value': 3}},
             {'action': 'renameAttribute', 'path': '/tracked', 'name': 'alpha', 'newName': 'Alpha'},
             {'action': 'setAttribute', 'path': '/tracked', 'attribute': big},
             {'action': 'deleteAttribute', 'path': '/meta', 'name': 'b'},
             {'action': 'copy', 'path': '/tracked', 'to': '/copied'}]
    want = ['table', 'zeta', 'Alpha', 'second table']
    results = []
    for repack in (False, True):
        label = 'repacked' if repack else 'edited'
        run = out / ('attributes-' + label)
        try:
            adaptor.run({'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': str(source), 'file': {'name': 'attrs-%s.h5' % label},
                         'repack': repack, 'edits': edits}, run, executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
            objects = json.loads((run / 'readback-result.json').read_text())['result']['objects']
            ok = objects['/tracked']['attributeOrder'] == want and objects['/copied']['attributeOrder'] == want and objects['/meta']['attributeOrder'] == ['a']
            results.append({'check': 'attribute creation order after edits (%s)' % label, 'ok': ok,
                            'observed': [objects['/tracked'].get('attributeOrder'), objects['/copied'].get('attributeOrder'), objects['/meta'].get('attributeOrder')]})
            results.append({'check': 'attribute edits unchanged verify (%s)' % label, **attack(paths, run, 'unchanged', None)})
            results.append({'check': 'attribute order tamper (%s)' % label, **attack(paths, run, 'order', h5(paths, 'attrs-%s.h5' % label,
                            'v = f["/copied"].attrs["table"]; del f["/copied"].attrs["table"]; f["/copied"].attrs["table"] = v'))})
        except SchemaxisError as error:
            results.append({'check': 'attribute creation order after edits (%s)' % label, 'ok': False, 'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message})
    run = out / 'attributes-inspect'
    try:
        adaptor.run({'version': 'schemaxis.hdf5/1', 'operation': 'inspectFile', 'source': str(source),
                     'expectations': [{'id': 'table', 'path': '/tracked', 'attribute': 'table', 'value': list(range(10000))}]},
                    run, executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
        decisions = json.loads((run / 'expectations.json').read_text())
        results.append({'check': 'inspect decides a 10000-element attribute expectation', 'ok': decisions['met'] == 1, 'decisions': decisions['decisions']})
    except SchemaxisError as error:
        results.append({'check': 'inspect decides a 10000-element attribute expectation', 'ok': False, 'code': error.fault.code, 'message': error.fault.message})
    refusals = (('large attribute on an untracked earliest-format dataset',
                 {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': str(source), 'file': {'name': 'big-plain.h5'},
                  'edits': [{'action': 'setAttribute', 'path': '/plain', 'attribute': big}]}, 'HDF5_ATTRIBUTE_TOO_LARGE', '$.edits[0]'),
                ('large attribute without dense storage at planning',
                 {'version': 'schemaxis.hdf5/1', 'operation': 'createFile', 'file': {'name': 'x.h5'},
                  'objects': [{'path': '/d', 'type': {'class': 'int', 'bits': 8}, 'shape': [1], 'data': {'source': 'values', 'values': [1]}, 'attributes': [big]}]},
                 'INVALID_HDF5_ATTRIBUTE', '$.objects[0].attributes[0]'))
    for label, document, code, location in refusals:
        try:
            adaptor.run(document, out / ('attributes-refused-%d' % len(results)), executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
            results.append({'check': 'refuses ' + label, 'ok': False})
        except SchemaxisError as error:
            results.append({'check': 'refuses ' + label, 'ok': error.fault.code == code and error.fault.location == location,
                            'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message})
    run = out / 'attributes-libver'
    try:
        adaptor.run({'version': 'schemaxis.hdf5/1', 'operation': 'createFile', 'file': {'name': 'v110.h5', 'libver': 'v110'},
                     'objects': [{'path': '/d', 'type': {'class': 'int', 'bits': 8}, 'shape': [1], 'data': {'source': 'values', 'values': [1]}, 'attributes': [big]}]},
                    run, executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
        results.append({'check': 'large attribute in a libver v110 file without trackOrder', **attack(paths, run, 'unchanged', None)})
    except SchemaxisError as error:
        results.append({'check': 'large attribute in a libver v110 file without trackOrder', 'ok': False, 'code': error.fault.code, 'message': error.fault.message})
    return results


NULL_FIXTURE = r'''
import h5py, numpy as np, sys
rec = np.dtype({'names': ['id', 'temperature', 'flags'], 'formats': ['<u8', '<f4', 'u1'], 'offsets': [0, 16, 24], 'itemsize': 32})
with h5py.File(sys.argv[1], 'w') as f:
    p = f.create_dataset('/pending', dtype='f8')
    p.attrs['units'] = 'K'
    p.attrs['note'] = 'awaiting calibration'
    f['/pending_count'] = h5py.Empty('<i4')
    f['/signal'] = np.array([1.5, 2.5, 3.5])
    f['/scalar'] = np.float64(4.25)
    f.create_dataset('/zero', shape=(0,), maxshape=(None,), dtype='<f4', chunks=(4,))
    grid = np.zeros((3, 4), dtype=rec)
    grid['id'] = np.arange(12, dtype='u8').reshape(3, 4) + np.uint64(2 ** 63)
    grid['temperature'] = np.arange(12, dtype='f4').reshape(3, 4) * 0.5
    grid['flags'] = 7
    f['/grid'] = grid
'''
NULL_IDS = [2 ** 63 + k for k in range(12)]


def null_and_field_variants(paths, out):
    """A vendor file with null datasets beside ordinary, scalar, zero-extent and padded uint64 records: inspection, unrelated
    extraction, field writes (selections, padded/uint64 siblings protected), null edits, repack, compare, refusals and tampers."""
    source = out / 'null-vendor.h5'
    subprocess.run([paths['python'], '-I', '-c', NULL_FIXTURE, str(source)], check=True, timeout=60, env={'HDF5_PLUGIN_PRELOAD': '::'})
    results = []

    def run(label, document, check=None, attacks=()):
        target = out / ('null-' + label)
        try:
            adaptor.run(document, target, executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
            ok = check(target) if check else True
            results.append({'check': label, 'ok': bool(ok)})
            for name, mutate in (('unchanged', None), *attacks):
                results.append({'check': '%s attack %s' % (label, name), **attack(paths, target, name, mutate)})
        except SchemaxisError as error:
            results.append({'check': label, 'ok': False, 'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message})

    def inventory(target):
        objects = json.loads((target / 'inventory.json').read_text())['objects']
        return (objects['/pending'].get('null') and objects['/pending']['shape'] is None and objects['/scalar']['shape'] == []
                and objects['/zero']['shape'] == [0] and json.loads((target / 'expectations.json').read_text())['met'] == 2)
    run('inspect', {'version': 'schemaxis.hdf5/1', 'operation': 'inspectFile', 'source': str(source), 'expectations': [
        {'id': 'pending', 'path': '/pending', 'kind': 'dataset', 'class': 'float', 'units': 'K'},
        {'id': 'grid', 'path': '/grid', 'kind': 'dataset', 'shape': [3, 4]}]}, inventory)

    def extracted(target):
        data = json.loads((target / 'temps.json').read_text())['values']
        return data == [k * 0.5 for k in range(12)] and json.loads((target / 'ids.json').read_text())['values'] == NULL_IDS
    run('unrelated-extract', {'version': 'schemaxis.hdf5/1', 'operation': 'extractData', 'source': str(source), 'extracts': [
        {'id': 'temps', 'dataset': '/grid', 'fields': ['temperature'], 'format': 'json'},
        {'id': 'ids', 'dataset': '/grid', 'fields': ['id'], 'format': 'json'},
        {'id': 'signal', 'dataset': '/signal'}]}, extracted)
    edits = [{'action': 'write', 'path': '/grid', 'fields': ['temperature'], 'selection': {'kind': 'hyperslab', 'start': [0, 1], 'count': [2, 2], 'stride': [2, 2]},
              'data': {'source': 'values', 'values': [-1, -2, -3, -4]}},
             {'action': 'write', 'path': '/grid', 'fields': ['flags', 'temperature'], 'selection': {'kind': 'points', 'points': [[1, 3], [0, 0]]},
              'data': {'source': 'values', 'values': [[1, 9.5], [2, 8.5]]}},
             {'action': 'setAttribute', 'path': '/pending', 'attribute': {'name': 'status', 'value': 'still pending'}},
             {'action': 'renameAttribute', 'path': '/pending', 'name': 'note', 'newName': 'comment'},
             {'action': 'copy', 'path': '/pending', 'to': '/archive/pending'},
             {'action': 'move', 'path': '/pending_count', 'to': '/archive/pending_count'}]

    def edited(name):
        def check(target):
            temps = [k * 0.5 for k in range(12)]
            flags = [7] * 12
            for (r, c), v in zip([(0, 1), (0, 3), (2, 1), (2, 3)], [-1, -2, -3, -4]):
                temps[r * 4 + c] = v
            flags[7], temps[7], flags[0], temps[0] = 1, 9.5, 2, 8.5
            data = json.loads((target / 'grid.json').read_text())['values']
            return data == [[i, t, g] for i, t, g in zip(NULL_IDS, temps, flags)]
        return check
    for repack in (False, True):
        label = 'edit-repacked' if repack else 'edit'
        name = 'null-%s.h5' % label
        run(label, {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': str(source), 'file': {'name': name}, 'repack': repack,
                    'edits': edits, 'extracts': [{'id': 'grid', 'dataset': '/grid', 'format': 'json'}]}, edited(name),
            (('null-replaced-by-scalar', h5(paths, name, 'a = dict(f["/archive/pending"].attrs); del f["/archive/pending"]; f["/archive/pending"] = 0.0\nfor k, v in a.items(): f["/archive/pending"].attrs[k] = v')),
             ('protected-uint64-id', h5(paths, name, 'f["/grid"][2, 2, "id"] = 5')),
             ('protected-padding-flag', h5(paths, name, 'f["/grid"][1, 1, "flags"] = 0'))))
    run('compare', {'version': 'schemaxis.hdf5/1', 'operation': 'compareFiles', 'source': str(source), 'reference': str(source)},
        lambda target: json.loads((target / 'comparison.json').read_text())['equal'])

    def created(target):
        objects = json.loads((target / 'readback-result.json').read_text())['result']['objects']
        return objects['/n']['null'] and objects['/n']['shape'] is None and objects['/s']['shape'] == [] and objects['/z']['shape'] == [0]
    run('create-null-scalar-zero', {'version': 'schemaxis.hdf5/1', 'operation': 'createFile', 'file': {'name': 'shapes.h5'}, 'objects': [
        {'path': '/n', 'type': {'class': 'int', 'bits': 16}, 'empty': True, 'trackOrder': True, 'attributes': [{'name': 'b', 'value': 1}, {'name': 'a', 'value': 2}]},
        {'path': '/s', 'type': {'class': 'int', 'bits': 16}, 'shape': [], 'data': {'source': 'values', 'values': [3]}},
        {'path': '/z', 'type': {'class': 'int', 'bits': 16}, 'shape': [0], 'maxshape': ['unlimited'], 'storage': {'chunks': [8]}}]}, created,
        (('null-gains-shape', h5(paths, 'shapes.h5', 'del f["/n"]; f.create_dataset("/n", shape=(0,), dtype="<i2", track_order=True); f["/n"].attrs["b"] = 1; f["/n"].attrs["a"] = 2')),))
    refusals = (('extract a null dataset', {'version': 'schemaxis.hdf5/1', 'operation': 'extractData', 'source': str(source),
                                            'extracts': [{'id': 'p', 'dataset': '/pending'}]}, 'INVALID_HDF5_EXTRACT', '$.extracts.p.dataset'),
                ('where on a null dataset', {'version': 'schemaxis.hdf5/1', 'operation': 'extractData', 'source': str(source),
                                             'extracts': [{'id': 's', 'dataset': '/signal', 'where': [{'dataset': '/pending', 'op': 'finite'}]}]},
                 'INVALID_HDF5_EXTRACT', '$.extracts.s.where[0].dataset'),
                ('write to a null dataset', {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': str(source), 'file': {'name': 'w.h5'},
                                             'edits': [{'action': 'write', 'path': '/pending', 'data': {'source': 'values', 'values': [1.0]}}]},
                 'INVALID_HDF5_EDIT', '$.edits[0].path'),
                ('resize a null dataset', {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': str(source), 'file': {'name': 'w.h5'},
                                           'edits': [{'action': 'resize', 'path': '/pending', 'shape': [2]}]}, 'INVALID_HDF5_EDIT', '$.edits[0].path'),
                ('unknown field', {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': str(source), 'file': {'name': 'w.h5'},
                                   'edits': [{'action': 'write', 'path': '/grid', 'fields': ['pressure'], 'data': {'source': 'values', 'values': [0] * 12}}]},
                 'INVALID_HDF5_EDIT', '$.edits[0].fields[0]'),
                ('fields on a non-compound dataset', {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': str(source), 'file': {'name': 'w.h5'},
                                                      'edits': [{'action': 'write', 'path': '/signal', 'fields': ['x'], 'data': {'source': 'values', 'values': [0, 0, 0]}}]},
                 'INVALID_HDF5_EDIT', '$.edits[0].fields[0]'),
                ('uint64 field out of range', {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': str(source), 'file': {'name': 'w.h5'},
                                               'edits': [{'action': 'write', 'path': '/grid', 'fields': ['id'], 'selection': {'kind': 'points', 'points': [[0, 0]]},
                                                          'data': {'source': 'values', 'values': [2 ** 64]}}]}, 'INVALID_HDF5_VALUE', '$.edits[0].data.values[0]'))
    for label, document, code, location in refusals:
        try:
            adaptor.run(document, out / ('null-refused-%d' % len(results)), executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
            results.append({'check': 'refuses ' + label, 'ok': False})
        except SchemaxisError as error:
            results.append({'check': 'refuses ' + label, 'ok': error.fault.code == code and error.fault.location == location,
                            'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message})
    return results


NULL_TYPES_FIXTURE = r'''
import sys
import h5py
import numpy as np


def null(f, name, tid, layout=None):
    dcpl = h5py.h5p.create(h5py.h5p.DATASET_CREATE)
    if layout is not None:
        dcpl.set_layout(layout)
    h5py.h5d.create(f.id, name.encode(), tid, h5py.h5s.create(h5py.h5s.NULL), dcpl=dcpl)


with h5py.File(sys.argv[1], 'w') as f:
    f['/data'] = np.arange(6, dtype='<i4')
    bits = h5py.h5d.create(f.id, b'bits', h5py.h5t.STD_B8LE, h5py.h5s.create_simple((3,)))
    bits.write(h5py.h5s.ALL, h5py.h5s.ALL, np.array([1, 2, 255], dtype='u1'))
    null(f, 'null_bitfield', h5py.h5t.STD_B8LE)
    null(f, 'null_bitfield_be16', h5py.h5t.STD_B16BE)
    null(f, 'null_enum', h5py.h5t.py_create(h5py.enum_dtype({'OFF': 0, 'ON': 1}, basetype='u1'), logical=True))
    rec = np.dtype({'names': ['id', 'value'], 'formats': ['<u8', '<f4'], 'offsets': [0, 16], 'itemsize': 24})
    null(f, 'null_compound', h5py.h5t.py_create(rec, logical=True))
    null(f, 'null_opaque', h5py.h5t.py_create(h5py.opaque_dtype(np.dtype('V4'))))
    null(f, 'null_reference', h5py.h5t.STD_REF_OBJ)
    null(f, 'null_array', h5py.h5t.py_create(np.dtype(('<f4', (3,))), logical=True))
    f['/types/reading'] = np.dtype([('t', '<f8'), ('p', '<f4')])
    null(f, 'null_named', f['/types/reading'].id)
    null(f, 'null_string', h5py.h5t.py_create(h5py.string_dtype('ascii', 8), logical=True))
    null(f, 'null_vlen_string', h5py.h5t.py_create(h5py.string_dtype('utf-8'), logical=True))
    null(f, 'null_compact', h5py.h5t.IEEE_F64LE, h5py.h5d.COMPACT)
    for name in list(f):
        if name.startswith('null_'):
            f[name].attrs['note'] = 'placeholder ' + name
'''
NULL_TYPES = ('bitfield', 'bitfield_be16', 'enum', 'compound', 'opaque', 'reference', 'array', 'named', 'string', 'vlen_string', 'compact')


def null_type_variants(paths, out):
    """Null datasets of every supported stored type and layout (bitfield, enum, padded compound, opaque, reference, array, committed,
    fixed/variable strings, compact) beside non-null controls: inspect, unrelated extraction, edits, repack, compare and tampers."""
    source = out / 'null-types.h5'
    subprocess.run([paths['python'], '-I', '-c', NULL_TYPES_FIXTURE, str(source)], check=True, timeout=60, env={'HDF5_PLUGIN_PRELOAD': '::'})
    results = []

    def run(label, document, check, attacks=()):
        target = out / ('null-types-' + label)
        try:
            adaptor.run(document, target, executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
            results.append({'check': label, 'ok': bool(check(target))})
            for name, mutate, *code in (('unchanged', None), *attacks):
                results.append({'check': '%s attack %s' % (label, name), **attack(paths, target, name, mutate, *code)})
        except SchemaxisError as error:
            results.append({'check': label, 'ok': False, 'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message})

    def inventory(target):
        objects = json.loads((target / 'inventory.json').read_text())['objects']
        kinds = {name: objects['/null_' + name] for name in NULL_TYPES}
        return (all(o.get('null') and o['shape'] is None for o in kinds.values()) and kinds['bitfield']['type'] == {'class': 'bitfield', 'bits': 8, 'order': 'little'}
                and kinds['bitfield_be16']['type'] == {'class': 'bitfield', 'bits': 16, 'order': 'big'} and kinds['compact']['layout'] == 'compact'
                and objects['/bits']['type']['class'] == 'bitfield' and json.loads((target / 'expectations.json').read_text())['met'] == 3)
    run('inspect', {'version': 'schemaxis.hdf5/1', 'operation': 'inspectFile', 'source': str(source), 'expectations': [
        {'id': 'bitfield', 'path': '/null_bitfield', 'kind': 'dataset', 'attribute': 'note', 'value': 'placeholder null_bitfield'},
        {'id': 'named', 'path': '/null_named', 'kind': 'dataset'},
        {'id': 'data', 'path': '/data', 'shape': [6], 'minimum': 0, 'maximum': 5}]}, inventory)
    run('unrelated-extract', {'version': 'schemaxis.hdf5/1', 'operation': 'extractData', 'source': str(source), 'extracts': [
        {'id': 'data', 'dataset': '/data', 'format': 'json'}]},
        lambda target: json.loads((target / 'data.json').read_text())['values'] == [0, 1, 2, 3, 4, 5])
    edits = [{'action': 'setAttribute', 'path': '/null_bitfield', 'attribute': {'name': 'status', 'value': 'reviewed'}},
             {'action': 'copy', 'path': '/null_compound', 'to': '/archive/null_compound'},
             {'action': 'move', 'path': '/null_compact', 'to': '/archive/null_compact'},
             {'action': 'write', 'path': '/data', 'selection': {'kind': 'points', 'points': [[0]]}, 'data': {'source': 'values', 'values': [42]}}]
    for repack in (False, True):
        label = 'edit-repacked' if repack else 'edit'
        name = 'null-types-%s.h5' % label
        run(label, {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': str(source), 'file': {'name': name}, 'repack': repack, 'edits': edits},
            lambda target: True,
            (('bitfield-to-uint', h5(paths, name, 'del f["/null_bitfield"]; f.create_dataset("/null_bitfield", dtype="u1"); f["/null_bitfield"].attrs["note"] = "placeholder null_bitfield"; f["/null_bitfield"].attrs["status"] = "reviewed"')),
             ('compact-to-contiguous', h5(paths, name, 'a = dict(f["/archive/null_compact"].attrs); del f["/archive/null_compact"]; f.create_dataset("/archive/null_compact", dtype="<f8")\nfor k, v in a.items(): f["/archive/null_compact"].attrs[k] = v')),
             ('committed-type-dropped', h5(paths, name, 'a = dict(f["/null_named"].attrs); del f["/null_named"]; f.create_dataset("/null_named", dtype=np.dtype([("t", "<f8"), ("p", "<f4")]))\nfor k, v in a.items(): f["/null_named"].attrs[k] = v'))))
    run('compare', {'version': 'schemaxis.hdf5/1', 'operation': 'compareFiles', 'source': str(source), 'reference': str(source)},
        lambda target: json.loads((target / 'comparison.json').read_text())['equal'])
    return results


LARGE_LOG = r'''
import h5py, numpy as np, sys
with h5py.File(sys.argv[1], 'w') as f:
    d = f.create_dataset('log', data=np.arange(1100000) * 0.25, maxshape=(None,), chunks=(10000,), compression='gzip', compression_opts=1)
    d.attrs['units'] = 'V'
'''


def large_source_tamper(paths, out):
    """Inspect a large source, then change one stored value of the captured copy beyond the XML budget (all hashes refreshed)."""
    source = out / 'large-inspect.h5'
    subprocess.run([paths['python'], '-I', '-c', LARGE_LOG, str(source)], check=True, timeout=120, env={'HDF5_PLUGIN_PRELOAD': '::'})
    run = out / 'large-inspect'
    adaptor.run({'version': 'schemaxis.hdf5/1', 'operation': 'inspectFile', 'source': str(source),
                 'expectations': [{'id': 'range', 'path': '/log', 'minimum': 0, 'maximum': 274999.75}]}, run,
                executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
    return [{'check': 'large source attack ' + label, **attack(paths, run, label, mutate)}
            for label, mutate in (('unchanged', None), ('stored-value', h5(paths, 'source.h5', 'f["/log"][700000] = 5.0')))]


def large_append(paths, out):
    """Append to a dataset beyond the full-reading budget: old rows by digest, new rows by independent h5dump read."""
    source = out / 'big-log.h5'
    subprocess.run([paths['python'], '-I', '-c', LARGE_LOG, str(source)], check=True, timeout=120, env={'HDF5_PLUGIN_PRELOAD': '::'})
    document = {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': str(source), 'file': {'name': 'big-log-appended.h5'},
                'edits': [{'action': 'append', 'path': '/log', 'axis': 0, 'shape': [3], 'data': {'source': 'values', 'values': [1.5, -2.25, 3.0]}}],
                'extracts': [{'id': 'tail', 'dataset': '/log', 'selection': {'kind': 'slices', 'slices': [{'start': 1099998}]}, 'format': 'json'}]}
    run = out / 'large-append'
    results = []
    try:
        adaptor.run(document, run, executable=paths['python'], h5dump=paths['h5dump'], timeout=600)
        tail = json.loads((run / 'tail.json').read_text())['values']
        results.append({'check': 'large append: tail = last originals + authored block', 'ok': tail == [274999.5, 274999.75, 1.5, -2.25, 3.0]})
        for label, mutate in (('unchanged', None), ('old-row', h5(paths, 'big-log-appended.h5', 'f["/log"][500000] = -1.0')),
                              ('new-row', h5(paths, 'big-log-appended.h5', 'f["/log"][1100001] = 0.0'))):
            outcome = attack(paths, run, label, mutate)
            results.append({'check': 'large append attack ' + label, **outcome})
    except SchemaxisError as error:
        results.append({'check': 'large append', 'ok': False, 'code': error.fault.code, 'message': error.fault.message})
    return results


ODD_TYPES = r'''
import h5py, numpy as np, sys
with h5py.File(sys.argv[1], 'w') as f:
    h5py.h5d.create(f.id, b'bits', h5py.h5t.STD_B8LE, h5py.h5s.create_simple((3,)))
    f['tags'] = np.array([('alpha', 1.0), ('beta', 2.0)], dtype=np.dtype([('name', h5py.string_dtype()), ('v', '<f8')]))
    inner = np.dtype([('x', '<f4'), ('y', '<f4')])
    f['nested'] = np.array([(1, (0.5, 1.5))], dtype=np.dtype([('id', '<i4'), ('pos', inner)]))
'''


def odd_types(paths, out):
    """Third-party types outside the authoring vocabulary (bitfield, vlen strings in records, nested records) still inventory."""
    source = out / 'odd-types.h5'
    subprocess.run([paths['python'], '-I', '-c', ODD_TYPES, str(source)], check=True, timeout=60, env={'HDF5_PLUGIN_PRELOAD': '::'})
    run = out / 'odd-types-inspect'
    try:
        adaptor.run({'version': 'schemaxis.hdf5/1', 'operation': 'inspectFile', 'source': str(source)}, run,
                    executable=paths['python'], h5dump=paths['h5dump'])
        objects = json.loads((run / 'inventory.json').read_text())['objects']
        ok = (objects['/bits']['type']['class'] == 'bitfield' and objects['/tags']['values']['preview'][0][0] == 'alpha'
              and objects['/nested']['type']['fields'][1]['type']['class'] == 'compound')
        return [{'check': 'adoption of bitfield, vlen-string record and nested record types', 'ok': ok}]
    except SchemaxisError as error:
        return [{'check': 'adoption of bitfield, vlen-string record and nested record types', 'ok': False, 'code': error.fault.code}]


def adopted_references(paths, out):
    """Adopted object/region references keep their exact targets through moves and repack; dangling deletes are refused."""
    source = str(ROOT / 'examples/schemaxis/hdf5-fixtures/sensor-run.h5')
    results = []

    def doc(name, edits, repack):
        return {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': source, 'file': {'name': name}, 'repack': repack, 'edits': edits}
    move = {'action': 'move', 'path': '/run/raw/counts', 'to': '/data/counts'}
    try:
        adaptor.run(doc('dangling.h5', [move, {'action': 'delete', 'path': '/run/calibrated/pressure'}], False), out / 'refs-dangling',
                    executable=paths['python'], h5dump=paths['h5dump'])
        results.append({'check': 'delete leaving a dangling reference is refused', 'ok': False})
    except SchemaxisError as error:
        results.append({'check': 'delete leaving a dangling reference is refused', 'ok': error.fault.code == 'INVALID_HDF5_EDIT'
                        and error.fault.location == '$.edits[1].path' and error.fault.observed.get('reference') == '/run/index[1]'})
    for repack in (False, True):
        label = 'repacked' if repack else 'edited'
        run = out / ('refs-' + label)
        try:
            adaptor.run(doc('refs-%s.h5' % label, [move, {'action': 'delete', 'path': '/run/index'}, {'action': 'delete', 'path': '/run/calibrated/pressure'}], repack),
                        run, executable=paths['python'], h5dump=paths['h5dump'])
            peak = json.loads((run / 'expected-state.json').read_text())['objects']['/run/peak']['references']
            ok = peak == [{'path': '/data/counts', 'points': [[2, 0], [2, 1], [3, 0], [3, 1]]}]
            results.append({'check': 'adopted region reference follows a moved target (%s)' % label, 'ok': ok, 'references': peak})
            name = 'refs-%s.h5' % label
            for attack_label, mutate in (('unchanged', None), ('region-retarget', h5(paths, name, 'f["/run/peak"][0] = f["/data/counts"].regionref[0:1, 0:2]'))):
                results.append({'check': 'adopted reference attack %s (%s)' % (attack_label, label), **attack(paths, run, attack_label, mutate)})
        except SchemaxisError as error:
            results.append({'check': 'adopted region reference follows a moved target (%s)' % label, 'ok': False, 'code': error.fault.code, 'message': error.fault.message})
    document = json.loads((ROOT / 'examples/schemaxis/hdf5-raw-export.json').read_text())
    document['file']['name'] = 'detector.he5'
    for o in document['objects']:
        for seg in o.get('storage', {}).get('external', []):
            seg['file'] = 'adc-frames.raw'
    try:
        adaptor.run(document, out / 'he5-raw', executable=paths['python'], h5dump=paths['h5dump'])
        results.append({'check': '.he5 output with .raw external storage verifies freshly', **attack(paths, out / 'he5-raw', 'unchanged', None)})
    except SchemaxisError as error:
        results.append({'check': '.he5 output with .raw external storage verifies freshly', 'ok': False, 'code': error.fault.code})
    return results


HUMAN_SOURCE = '''
import sys, h5py, numpy as np
with h5py.File(sys.argv[1], "w") as f:
    f["/signal"] = np.array([1, 2, 3], dtype="<i4")
    t = f.create_dataset("/Experiment 1/Temperature (°C)", data=np.array([[20.5, 21.0], [22.5, 23.0], [24.5, 25.0]]))
    t.attrs["units"] = "°C"
    s = f.create_dataset("/Experiment 1/Zeit (s)", data=np.array([0.0, 0.5, 1.0]))
    s.make_scale("Zeit")
    t.dims[0].attach_scale(s)
    f["/μm"] = np.array([1, 2, 3], dtype="<i4")
    f["/.calibration"] = np.array([0.5, -1.25])
    f["/Run #2, \\"warm\\" & <dry>/peak ratio"] = 0.875
    f["/Kanal[2] = Druck"] = np.array([1.5, 2.5, 3.5])
'''


def human_names(paths, out):
    """Ordinary Unicode/space/punctuation/leading-dot names through adopt, extract, expect, edit, repack and compare, with fresh verification."""
    source = out / 'human-source.h5'
    subprocess.run([paths['python'], '-I', '-c', HUMAN_SOURCE, str(source)], check=True, timeout=60, env={'HDF5_PLUGIN_PRELOAD': '::'})
    temp, scale, micro, dot, run2 = '/Experiment 1/Temperature (°C)', '/Experiment 1/Zeit (s)', '/μm', '/.calibration', '/Run #2, "warm" & <dry>'
    documents = {
        'human-extract': {'version': 'schemaxis.hdf5/1', 'operation': 'extractData', 'source': str(source), 'extracts': [
            {'id': 'temperature', 'dataset': temp, 'coordinates': True},
            {'id': 'micro', 'dataset': micro, 'selection': {'kind': 'points', 'points': [[2], [0]]}, 'format': 'json'},
            {'id': 'calibration', 'dataset': dot, 'format': 'npy'},
            {'id': 'bracket', 'dataset': '/Kanal[2] = Druck', 'selection': {'kind': 'points', 'points': [[2], [0]]}, 'format': 'json'}]},
        'human-inspect': {'version': 'schemaxis.hdf5/1', 'operation': 'inspectFile', 'source': str(source), 'expectations': [
            {'id': 'temperature', 'path': temp, 'kind': 'dataset', 'shape': [3, 2], 'units': '°C', 'minimum': 20.5, 'maximum': 25, 'finite': True},
            {'id': 'ratio', 'path': run2 + '/peak ratio', 'minimum': 0.875, 'maximum': 0.875},
            {'id': 'dot', 'path': dot, 'kind': 'dataset'}]},
        'human-edit': {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': str(source), 'file': {'name': 'renamed-names.h5'}, 'repack': True, 'edits': [
            {'action': 'move', 'path': micro, 'to': '/Längen/μm'},
            {'action': 'copy', 'path': '/Experiment 1', 'to': '/Experiment 2 (copy)'},
            {'action': 'setAttribute', 'path': dot, 'attribute': {'name': 'Gültig ab', 'value': '2026-11-05'}},
            {'action': 'renameAttribute', 'path': temp, 'name': 'units', 'newName': 'Einheit'},
            {'action': 'link', 'link': {'path': '/Längen/→ calibration', 'kind': 'soft', 'target': dot}},
            {'action': 'write', 'path': run2 + '/peak ratio', 'data': {'source': 'values', 'values': [0.75]}},
            {'action': 'delete', 'path': '/signal'}]},
        'human-compare': {'version': 'schemaxis.hdf5/1', 'operation': 'compareFiles', 'source': str(source), 'reference': str(source)}}
    results = []
    for name, document in documents.items():
        run = out / name
        try:
            adaptor.run(document, run, executable=paths['python'], h5dump=paths['h5dump'])
            ok = True
            if name == 'human-extract':
                header = (run / 'temperature.csv').read_text(encoding='utf-8').splitlines()[0]
                ok = header == 'Zeit (s),Temperature (°C)_0,Temperature (°C)_1'
            if name == 'human-inspect':
                ok = json.loads((run / 'expectations.json').read_text())['met'] == 3
            if name == 'human-edit':
                objects = json.loads((run / 'expected-state.json').read_text())['objects']
                ok = ('/Längen/μm' in objects and '/Experiment 2 (copy)/Temperature (°C)' in objects and '/signal' not in objects
                      and objects['/Experiment 2 (copy)/Temperature (°C)']['dims'][0]['scales'] == ['/Experiment 2 (copy)/Zeit (s)'])
            results.append({'check': 'human names: ' + name, 'ok': ok})
            results.append({'check': 'human names unchanged verify: ' + name, **attack(paths, run, 'unchanged', None)})
        except SchemaxisError as error:
            results.append({'check': 'human names: ' + name, 'ok': False, 'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message})
    tamper = h5(paths, 'renamed-names.h5', 'f["/Experiment 2 (copy)/Temperature (°C)"][0, 0] = 99.0')
    if (out / 'human-edit' / 'renamed-names.h5').is_file():
        results.append({'check': 'human names value tamper refused', **attack(paths, out / 'human-edit', 'value', tamper)})
    for bad, label in (('/tab\there', 'control character'), ('/x/../y', 'dot-dot segment'), ('/' + 'é' * 128, 'over 255 UTF-8 bytes')):
        try:
            adaptor.plan({'version': 'schemaxis.hdf5/1', 'operation': 'extractData', 'source': str(source), 'extracts': [{'id': 'x', 'dataset': bad}]})
            results.append({'check': 'malformed name refused: ' + label, 'ok': False})
        except SchemaxisError as error:
            results.append({'check': 'malformed name refused: ' + label, 'ok': error.fault.code == 'INVALID_HDF5_PATH'})
    return results


LIFECYCLE = {'admission': 'admission', 'large-extraction': 'large_extraction', 'large-append': 'large_append', 'odd-types': 'odd_types',
             'adopted-references': 'adopted_references', 'human-names': 'human_names',
             'memory-variants': 'memory_variants', 'where-variants': 'where_variants',
             'chunk-variants': 'chunk_variants', 'integer-membership': 'integer_membership',
             'copy-chunk-variants': 'copy_chunk_variants',
             'sieve-variants': 'sieve_variants', 'attribute-variants': 'attribute_variants',
             'null-and-field-variants': 'null_and_field_variants', 'null-type-variants': 'null_type_variants'}


def cases():
    return json.loads(READINESS.read_text())['routes']['schemaxis.hdf5/1']['development']['cases']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', required=True)
    parser.add_argument('--h5dump', required=True)
    parser.add_argument('--output-directory', required=True)
    parser.add_argument('--case', action='append')
    parser.add_argument('--admission-only', action='store_true')
    parser.add_argument('--lifecycle', action='append', choices=sorted(LIFECYCLE), help='Run only these serial lifecycle checks')
    parser.add_argument('--mpi-python', help='Parallel h5py interpreter for parallelWrite')
    parser.add_argument('--mpiexec', help='Open MPI mpiexec for parallelWrite')
    parser.add_argument('--meshio', help='Optional Python with meshio 5.3.5, xarray and h5netcdf used as independent XDMF and NetCDF-4 consumers')
    parser.add_argument('--numpy', help='Optional qualified NumPy adaptor interpreter for the HDF5 -> NumPy handoff')
    args = parser.parse_args()
    out = Path(args.output_directory).absolute()
    out.mkdir(parents=True, exist_ok=False)
    paths = {'python': args.python, 'h5dump': args.h5dump}
    mpi = {'mpiPython': args.mpi_python, 'mpiexec': args.mpiexec}
    route = json.loads(READINESS.read_text())['routes']['schemaxis.hdf5/1']
    examples = {e['id']: e['reference'] for e in route['examples']}
    fixtures = {p.name: digest(p) for p in sorted((ROOT / 'examples/schemaxis/hdf5-fixtures').iterdir())}
    commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain', '--', 'src', 'tools', 'examples'], capture_output=True, text=True).stdout.strip()
    summary = {'commit': commit, 'sourceClean': not dirty, 'implementation': adaptor.implementation(), 'cases': [], 'attacks': [], 'lifecycle': [],
               'startedUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    if args.lifecycle:
        summary['lifecycle'] = [x for name in args.lifecycle for x in (globals()[LIFECYCLE[name]](paths, out, mpi) if name == 'sieve-variants'
                                                                         else globals()[LIFECYCLE[name]](paths, out))]
        summary['passed'] = all(x['ok'] for x in summary['lifecycle'])
        (out / 'qualification-summary.json').write_text(json.dumps(summary, indent=1, default=str))
        print(json.dumps(summary['lifecycle'], indent=1, default=str))
        return 0 if summary['passed'] else 1
    if args.admission_only:
        summary['lifecycle'] = admission(paths, out)
        summary['passed'] = all(x['ok'] for x in summary['lifecycle'])
        (out / 'qualification-summary.json').write_text(json.dumps(summary, indent=1, default=str))
        print(json.dumps(summary['lifecycle'], indent=1))
        return 0 if summary['passed'] else 1
    for case in cases():
        if args.case and case['id'] not in args.case:
            continue
        run = out / case['id']
        record = {'id': case['id'], 'scope': case['scope']}
        try:
            started = time.monotonic()
            if case['id'] in ('parallel-write', 'parallel-extract') and not args.mpi_python:
                record.update(ok=False, error='parallel runtime not configured (unqualified, not a skip)')
                summary['cases'].append(record)
                continue
            result = adaptor.run(case_document(case, examples), run, executable=args.python, h5dump=args.h5dump, timeout=600, **mpi)
            record.update(ok=True, seconds=round(time.monotonic() - started, 2), result=result,
                          checks=assertions(run, case['checks']), runtime=json.loads((run / 'build-result.json').read_text())['runtime']
                          if (run / 'build-result.json').is_file() else None)
            for label, mutate, *code in [*ATTACKS.get(case['id'], lambda p: [])(paths), ('report-number', report_bump)]:
                summary['attacks'].append({'case': case['id'], **attack(paths, run, label, mutate, *code)})
        except Exception as error:
            record.update(ok=False, error=getattr(error, 'fault', None) and error.fault.to_dict() or repr(error), trace=traceback.format_exc()[-2000:])
        summary['cases'].append(record)
        (out / 'qualification-summary.json').write_text(json.dumps(summary, indent=1, default=str))
    if not args.case:
        summary['lifecycle'] = admission(paths, out) + large_extraction(paths, out) + large_append(paths, out) + large_source_tamper(paths, out) + odd_types(paths, out) + adopted_references(paths, out) + human_names(paths, out) + memory_variants(paths, out) + where_variants(paths, out) + integer_membership(paths, out) + chunk_variants(paths, out) + copy_chunk_variants(paths, out) + sieve_variants(paths, out, mpi) + attribute_variants(paths, out) + null_and_field_variants(paths, out) + null_type_variants(paths, out) + lifecycle(paths, examples, out) + workflows(paths, args.numpy, out)
        if args.meshio and (out / 'mesh-fields' / 'cooling-block.xdmf').is_file():
            summary['lifecycle'] += meshio_consumer(args.meshio, out) + netcdf_consumer(args.meshio, out)
    after = {p.name: digest(p) for p in sorted((ROOT / 'examples/schemaxis/hdf5-fixtures').iterdir())}
    summary['fixturesUnmodified'] = after == fixtures
    summary['finishedUtc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    summary['passed'] = (all(c['ok'] for c in summary['cases']) and all(a['ok'] for a in summary['attacks'])
                         and all(x['ok'] for x in summary['lifecycle']) and summary['fixturesUnmodified'])
    (out / 'qualification-summary.json').write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps({'passed': summary['passed'], 'cases': [(c['id'], c['ok']) for c in summary['cases']],
                      'attacks': [(a['case'], a['attack'], a['ok'], a.get('code')) for a in summary['attacks']],
                      'lifecycle': [(x['check'], x['ok'], x.get('code')) for x in summary['lifecycle']]}, indent=1))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
