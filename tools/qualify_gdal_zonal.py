#!/usr/bin/env python3
"""Qualify GDAL zonalSummary with independent literals, semantic mutants, live lifecycle and a real Calc handoff."""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import statistics
import struct
import subprocess
import threading
import time
from unittest.mock import patch

from schemaxis import publication_metadata, workflow
from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors.gdal import adaptor, reference
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis.publication_metadata import finalise
from qualify_gdal_fixtures import tiff

ROOT = Path(__file__).resolve().parents[1]
ELEVATION = ROOT/'examples/schemaxis/fixtures/gdal/elevation.tif'
Z = lambda i, x, y, w, h: {'id': i, 'x': x, 'y': y, 'width': w, 'height': h}
f32 = lambda v: struct.unpack('<f', struct.pack('<f', v))[0]
SPEC = importlib.util.spec_from_file_location('calc_cell_oracle', ROOT/'tools/qualify_calc_typed.py')
CALC = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(CALC)
COLUMNS = [{'name': 'zone', 'kind': 'text'}, {'name': 'valid', 'kind': 'number'}, {'name': 'missing', 'kind': 'number'}, {'name': 'coverage', 'kind': 'number'},
           {'name': 'minimum', 'kind': 'number', 'nullable': True}, {'name': 'maximum', 'kind': 'number', 'nullable': True}, {'name': 'sum', 'kind': 'number', 'nullable': True}, {'name': 'mean', 'kind': 'number', 'nullable': True}]


def document(source, **change):
    base = json.loads((ROOT/'examples/schemaxis/gdal-zonal.json').read_text())
    return {**base, 'source': source if isinstance(source, dict) else str(source), **change}


def refused(action, code, text=None):
    try: action()
    except SchemaxisError as error:
        fault = error.fault.to_dict()
        assert fault['code'] == code, fault
        if text is not None: assert text in fault['message'], (text, fault)
        return {'fault': code, 'message': fault['message']}
    raise AssertionError('invalid input/evidence accepted: ' + str(text))


def refused_exact(action, code, message, location):
    """The whole fault must equal the stated constants (code, full message, location); fragments are never accepted."""
    try: action()
    except SchemaxisError as error:
        fault = error.fault.to_dict()
        assert (fault['code'], fault['message'], fault['location']) == (code, message, location), (fault, (code, message, location))
        return {'fault': code, 'message': fault['message'], 'location': fault['location']}
    raise AssertionError('invalid input/evidence accepted: ' + message)


def tree(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.rglob('*')) if p.is_file()}


def refresh(directory):
    """Make every ordinary hash/receipt consistent with the mutated bytes, then require publication metadata to verify: only semantic verification may refuse."""
    prepared = adaptor._native_plan(adaptor.read(directory, 'authored.json'))
    capture = adaptor.read(directory, 'capture.json'); data = (directory/'source.tif').read_bytes()
    atomic_json(directory/'capture.json', {**capture, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    for stage, consumed in (('zonal', ('source.tif', 'zones.geojson')), ('zonal-readback', ('summary.geojson', 'zones.geojson'))):
        # Same serialisation as the trusted worker, so a refresh with nothing mutated rewrites identical bytes.
        (directory/(stage+'-inputs.json')).write_text(json.dumps({n: adaptor.digest(directory, n) for n in (*consumed, 'native-config.json', 'zonal_worker.py')}, sort_keys=True))
    receipt = adaptor.read(directory, 'verification.json')
    receipt['artifacts'] = adaptor.artifacts(directory, prepared)
    receipt['evidence'] = {n: adaptor.digest(directory, n) for n in receipt['evidence']}
    atomic_json(directory/'verification.json', receipt)
    finalise(directory)
    metadata = publication_metadata.verify(directory)
    assert metadata['verified'] and metadata['publications'] == 2, metadata
    return metadata


# Expected full fault of each semantic mutant after a consistent refresh, stated here as literals (code is always VERIFICATION_FAILED).
# Hand-copied from the retained independent review run, never derived from the mutant results inside this qualifier.
MUTANT_FAULTS = {
    'zone-geometry-selfconsistent-shifted': ('retained zone geometry differs from the authored pixel rectangles and source affine', 'zones.geojson'),
    'native-count-forged': ('zonal native evidence differs from the independent oracle: zone 007 identity/valid count differs', '$'),
    'native-fractional-count': ('zonal native evidence differs from the independent oracle: native count must be an exact nonnegative integer', '$'),
    'native-minimum-forged': ('zonal native evidence differs from the independent oracle: zone 007 minimum differs', '$'),
    'native-maximum-forged': ('zonal native evidence differs from the independent oracle: zone 007 maximum differs', '$'),
    'native-sum-forged': ('zonal native evidence differs from the independent oracle: zone 007 sum differs beyond the roundoff bound', '$'),
    'native-sum-tiny-forgery': ('zonal native evidence differs from the independent oracle: zone 007 sum differs beyond the roundoff bound', '$'),
    'native-sum-wrong-zero': ('zonal native evidence differs from the independent oracle: zone 007 sum differs beyond the roundoff bound', '$'),
    'native-mean-forged': ('zonal native evidence differs from the independent oracle: zone 007 mean differs beyond the roundoff bound', '$'),
    'native-all-missing-nonzero-sum': ('zonal native evidence differs from the independent oracle: native all-missing zone shape differs', '$'),
    'native-all-missing-invented-mean': ('zonal native evidence differs from the independent oracle: native all-missing zone shape differs', '$'),
    'native-zone-order-swapped': ('zonal native evidence differs from the independent oracle: native zone identity/order differs', '$'),
    'native-zone-id-renamed': ('zonal native evidence differs from the independent oracle: native zone identity/order differs', '$'),
    'native-boolean-count': ('zonal native evidence differs from the independent oracle: native count must be an exact nonnegative integer', '$'),
    'native-feature-dropped': ('zonal native evidence differs from the independent oracle: native zone feature count differs', '$'),
    'native-source-snapshot-units': ('zonal native evidence differs from the independent oracle: units differs', '$'),
    'fresh-reopen-count-forged': ('zonal native evidence differs from the independent oracle: fresh native reopening differs from the native summary', '$'),
    'fresh-reopen-zone-geometry-forged': ('zonal native evidence differs from the independent oracle: fresh native zone geometry differs from authored pixel rectangles', '$'),
    'source-pixel-changed': ('zonal native evidence differs from the independent oracle: pixels differs', '$'),
    'authored-units-changed': ('zone oracle refused: declared CRS/units/nodata do not match source', '$'),
    'authored-zone-rectangle-changed': ('retained zone geometry differs from the authored pixel rectangles and source affine', 'zones.geojson'),
    'authored-missing-policy-changed': ('zone oracle refused: zone 007 contains 1 nodata pixels and the missing policy is refuse', '$'),
    'summary-corners-changed': ('zonal summary differs', 'zones-summary.json'),
    'summary-units-changed': ('zonal summary differs', 'zones-summary.json'),
    'csv-value-forged': ('zonal CSV differs from the independent oracle', 'zones-summary.csv'),
    'csv-null-as-zero': ('zonal CSV differs from the independent oracle', 'zones-summary.csv'),
    'csv-id-formula-unquoted': ('zonal CSV differs from the independent oracle', 'zones-summary.csv'),
    'csv-id-leading-zeros-numeric': ('zonal CSV differs from the independent oracle', 'zones-summary.csv'),
    'csv-row-order': ('zonal CSV differs from the independent oracle', 'zones-summary.csv'),
    'extra-publication': ('unexpected zonal publication', '$'),
    'trusted-worker-changed': ('trusted native worker/configuration differs', '$'),
}
# Integrity controls (distinct from the semantic mutants): the same kinds of mutation WITHOUT refreshing bindings must be refused by the
# digest/binding checks with these exact faults, proving the refresh above is what the semantic mutants needed and that it does not hide integrity.
INTEGRITY_FAULTS = {
    'source-pixel-changed': ('captured source identity differs', '$'),
    'native-sum-forged': ('native consumed-input binding differs', 'zonal-readback'),
    'authored-zone-rectangle-changed': ('native consumed-input binding differs', 'zonal'),
}
# Metadata-only integrity control: a tampered publication metadata companion fails publication_metadata.verify (and, last, the full adaptor verification) with this exact fault.
METADATA_FAULT = ('missing or malformed output metadata: metadata content or artifact relationship differs', 'directory')


def edit_json(directory, name, change):
    value = adaptor.read(directory, name); change(value); atomic_json(directory/name, value)


def edit_summary(directory, change):
    path = directory/'summary.geojson'; value = json.loads(path.read_text()); change(value['features']); path.write_text(json.dumps(value))


def mutants(directory):
    saved = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}; report = {}
    def restore():
        for p in directory.rglob('*'):
            if p.is_file() and p not in saved: p.unlink()
        for p, data in saved.items(): p.write_bytes(data)
    def shift_zone():
        geo = json.loads((directory/'zones.geojson').read_text())
        for ring in geo['features'][0]['geometry']['coordinates']:
            for point in ring: point[0] += 10
        (directory/'zones.geojson').write_text(json.dumps(geo, sort_keys=True, allow_nan=False, separators=(',', ':')))
    def pixel():
        data = bytearray((directory/'source.tif').read_bytes()); data[-30*2+1*2] = 0x7f; (directory/'source.tif').write_bytes(bytes(data))
    def zones_authored(change):
        def action():
            for name in ('authored.json', 'plan.json'):
                edit_json(directory, name, lambda v: change(v))
            # Keep the trusted native configuration consistent so the independent oracle, not that binding, must refuse.
            atomic_json(directory/'native-config.json', adaptor.config(adaptor.read(directory, 'plan.json')))
        return action
    def csv_edit(old, new):
        return lambda: (directory/'zones-summary.csv').write_text((directory/'zones-summary.csv').read_text().replace(old, new, 1))
    def readback(change):
        return lambda: edit_json(directory, 'zonal-readback.stdout', change)
    cases = [
        ('zone-geometry-selfconsistent-shifted', shift_zone),
        ('native-count-forged', lambda: edit_summary(directory, lambda f: f[0]['properties'].update(count=6.0))),
        ('native-fractional-count', lambda: edit_summary(directory, lambda f: f[0]['properties'].update(count=5.5))),
        ('native-minimum-forged', lambda: edit_summary(directory, lambda f: f[0]['properties'].update(min=10.0))),
        ('native-maximum-forged', lambda: edit_summary(directory, lambda f: f[0]['properties'].update(max=24.0))),
        ('native-sum-forged', lambda: edit_summary(directory, lambda f: f[0]['properties'].update(sum=81.0))),
        ('native-sum-tiny-forgery', lambda: edit_summary(directory, lambda f: f[0]['properties'].update(sum=80.00000001))),
        ('native-sum-wrong-zero', lambda: edit_summary(directory, lambda f: f[0]['properties'].update(sum=0.0))),
        ('native-mean-forged', lambda: edit_summary(directory, lambda f: f[0]['properties'].update(mean=16.5))),
        ('native-all-missing-nonzero-sum', lambda: edit_summary(directory, lambda f: f[1]['properties'].update(sum=1.0))),
        ('native-all-missing-invented-mean', lambda: edit_summary(directory, lambda f: f[1]['properties'].update(min=0.0, max=0.0, sum=0.0, mean=0.0))),
        ('native-zone-order-swapped', lambda: edit_summary(directory, lambda f: f.reverse())),
        ('native-zone-id-renamed', lambda: edit_summary(directory, lambda f: f[0]['properties'].update(zone='700'))),
        ('native-boolean-count', lambda: edit_summary(directory, lambda f: f[2]['properties'].update(count=True))),
        ('native-feature-dropped', lambda: edit_summary(directory, lambda f: f.pop())),
        ('native-source-snapshot-units', lambda: edit_json(directory, 'zonal.stdout', lambda v: v['raster'].update(units='K'))),
        ('fresh-reopen-count-forged', readback(lambda v: v['summary']['features'][0]['properties'].update(count=6.0))),
        ('fresh-reopen-zone-geometry-forged', readback(lambda v: v['zones']['features'][0]['ring'][1].__setitem__(0, 500050.0))),
        ('source-pixel-changed', pixel),
        ('authored-units-changed', zones_authored(lambda v: v.update(units='K'))),
        ('authored-zone-rectangle-changed', zones_authored(lambda v: v['zones'][2].update(width=5))),
        ('authored-missing-policy-changed', zones_authored(lambda v: v.update(missing='refuse'))),
        ('summary-corners-changed', lambda: edit_json(directory, 'zones-summary.json', lambda v: v['zones'][0]['corners'][0].__setitem__(0, 500020))),
        ('summary-units-changed', lambda: edit_json(directory, 'zones-summary.json', lambda v: v.update(units='K'))),
        ('csv-value-forged', csv_edit(',80,16\n', ',81,16\n')),
        ('csv-null-as-zero', csv_edit('0,\\N,\\N,\\N,\\N', '0,0,0,0,0')),
        ('csv-id-formula-unquoted', csv_edit('"=1+2"', '=1+2')),
        ('csv-id-leading-zeros-numeric', csv_edit('"007"', '7')),
        ('csv-row-order', lambda: (directory/'zones-summary.csv').write_text('\n'.join([(directory/'zones-summary.csv').read_text().splitlines()[0], *reversed((directory/'zones-summary.csv').read_text().splitlines()[1:])])+'\n')),
        ('extra-publication', lambda: (directory/'zones-summary.extra').write_text('x')),
        ('trusted-worker-changed', lambda: (directory/'zonal_worker.py').write_text(adaptor.zonal_worker_source()+'\n#changed\n')),
    ]
    assert [name for name, _ in cases] == list(MUTANT_FAULTS) and len(cases) == 31, 'mutant list and explicit expected faults differ'
    before = tree(directory)
    control = refresh(directory)
    assert tree(directory) == before, 'a no-mutation refresh must not change any retained byte'
    assert adaptor.verify(directory)['verified'] and publication_metadata.verify(directory) == control
    report['control-no-mutation-refresh'] = {'adaptorVerified': True, 'metadataVerified': True, 'retainedBytesUnchanged': True, 'files': len(before)}
    for name, action in cases:
        message, location = MUTANT_FAULTS[name]
        try:
            action(); metadata = refresh(directory)  # publication metadata verifies first (asserted inside refresh); only the semantic check may refuse
            report[name] = {**refused_exact(lambda: adaptor.verify(directory), 'VERIFICATION_FAILED', message, location), 'metadataVerifiedBeforeRefusal': metadata['verified']}
        finally: restore()
    assert adaptor.verify(directory)['verified'] and publication_metadata.verify(directory)['verified']
    integrity = {}
    for name, (message, location) in INTEGRITY_FAULTS.items():
        try:
            dict(cases)[name]()  # no refresh: bindings now disagree with the mutated bytes
            integrity[name] = refused_exact(lambda: adaptor.verify(directory), 'VERIFICATION_FAILED', message, location)
        finally: restore()
    try:
        companion = directory/'zones-summary.csv.metadata.json'; companion.write_text(companion.read_text().replace('"', "'", 1))
        # adaptor.verify runs publication metadata verification last, after every native/semantic check; both entry points must refuse with the same exact fault.
        integrity['metadata-companion-tampered'] = refused_exact(lambda: publication_metadata.verify(directory), 'VERIFICATION_FAILED', METADATA_FAULT[0], str(directory.resolve()))
        integrity['metadata-companion-tampered-full-verify'] = refused_exact(lambda: adaptor.verify(directory), 'VERIFICATION_FAILED', METADATA_FAULT[0], str(directory.resolve()))
    finally: restore()
    assert adaptor.verify(directory)['verified'] and publication_metadata.verify(directory)['verified']
    report['integrity-controls'] = integrity
    report['metadata-first'] = {'mutants': len(cases), 'allMetadataVerifiedBeforeRefusal': all(report[name]['metadataVerifiedBeforeRefusal'] for name, _ in cases), 'exactFaults': len(cases)}
    return report


def literal_baseline(directory):
    summary = adaptor.read(directory, 'zones-summary.json'); rows = {z['zone']: z for z in summary['zones']}
    assert [z['zone'] for z in summary['zones']] == ['007', '=1+2', 'north', 'south'] and summary['units'] == 'm' and summary['epsg'] == 3857
    assert (rows['007']['valid'], rows['007']['minimum'], rows['007']['maximum'], rows['007']['sum'], rows['007']['mean']) == (5, 11, 23, 80, 16)
    assert (rows['=1+2']['valid'], rows['=1+2']['missing'], rows['=1+2']['minimum'], rows['=1+2']['sum'], rows['=1+2']['mean']) == (0, 1, None, None, None)
    assert (rows['north']['sum'], rows['north']['mean'], rows['south']['valid'], rows['south']['sum']) == (75, 12.5, 11, 526)
    assert rows['007']['corners'] == [[500010, 5500000], [500040, 5499960]]
    expected = ('"zone","valid","missing","coverage","minimum","maximum","sum","mean"\n"007",5,1,0.8333333333333334,11,23,80,16\n"=1+2",0,1,0,\\N,\\N,\\N,\\N\n'
                '"north",6,0,1,10,15,75,12.5\n"south",11,1,0.9166666666666666,40,55,526,47.81818181818182\n')
    assert (directory/'zones-summary.csv').read_text() == expected
    return {'zones': 4, 'csvBytes': len(expected)}


def inputs(directory, executable):
    report = {}
    run = lambda name, doc: adaptor.run(doc, directory/name, executable=executable, timeout=60)
    source = directory/'elevation.tif'; source.write_bytes(ELEVATION.read_bytes())
    for name, change, code in [('wrong-crs', {'epsg': 4326}, 'INVALID_RASTER_CONTENT'), ('wrong-units', {'units': 'K'}, 'INVALID_RASTER_CONTENT'), ('wrong-nodata', {'nodata': 0}, 'INVALID_RASTER_CONTENT'),
                               ('outside-zone', {'zones': [Z('a', 4, 3, 3, 2)]}, 'INVALID_ZONE'), ('outside-row', {'zones': [Z('a', 0, 4, 1, 2)]}, 'INVALID_ZONE'),
                               ('refuse-missing', {'missing': 'refuse'}, 'ZONE_MISSING_VALUES')]:
        report[name] = refused(lambda: run(name+'-run', document(source, **change)), code)
    for name, data in {'cancellation': tiff([1.0, -1.0]+[5.0]*28, dtype='Float32', units='1'), 'mislabelled-latitude': tiff([1.0]*30, dtype='Float32', epsg=4326, units='1', origin=(1e6, 5500000), spacing=(10000, 20000))}.items():
        path = directory/(name+'.tif'); path.write_bytes(data)
        if name == 'cancellation':
            report[name] = refused(lambda: run(name+'-run', document(path, units='1', zones=[Z('a', 0, 0, 2, 1)], missing='refuse')), 'ZONE_SUM_UNRESOLVABLE')
        else:
            report[name] = refused(lambda: run(name+'-run', document(path, epsg=4326, units='1', zones=[Z('a', 0, 0, 2, 1)])), 'RASTER_EXTENT_INVALID')
    # Real native numerics: subnormal Float32, huge Float32, mixed sign without cancellation, UInt16 maximum, all-missing zone.
    cases = {
        'subnormal': (tiff([2.0**-149, 2.0**-148, 3*2.0**-149]+[0.0]*27, dtype='Float32', units='1'), 'Float32', [Z('s', 0, 0, 3, 1)], None, None),
        'huge': (tiff([3.4e38, 3.4e38, -1e38]+[1.0]*27, dtype='Float32', units='1'), 'Float32', [Z('h', 0, 0, 3, 1)], None, None),
        'mixed': (tiff([-7.25, 4.0, 10.5]+[1.0]*27, dtype='Float32', units='1'), 'Float32', [Z('m', 0, 0, 3, 1)], 7.25, 7.25),
        'uint16-max': (tiff([65535, 65534, 0]+[1]*27, dtype='UInt16', nodata=65533, units='1'), 'UInt16', [Z('u', 0, 0, 3, 1)], 131069, 131069),
        # Ordinary mixed-sign zone near (inside) the 2**-26 resolution ceiling: hand sum 16777216-16777215+0.5 = 1.5, derived allowance about 5e-9 of the sum.
        'near-boundary': (tiff([16777216.0, -16777215.0, 0.5]+[1.0]*27, dtype='Float32', units='1'), 'Float32', [Z('b', 0, 0, 3, 1)], None, None),
    }
    for name, (data, dtype, zones, _, _) in cases.items():
        path = directory/(name+'.tif'); path.write_bytes(data)
        nodata = 65533 if dtype == 'UInt16' else -9999
        out = directory/(name+'-run'); result = run(name+'-run', document(path, units='1', nodata=nodata, zones=zones))
        row = adaptor.read(out, 'zones-summary.json')['zones'][0]; assert result['verified'] and row['valid'] == 3, row
        report[name] = {'sum': row['sum'], 'mean': row['mean'], 'minimum': row['minimum'], 'maximum': row['maximum']}
    assert report['subnormal']['sum'] == 6*2.0**-149 and report['subnormal']['minimum'] == 2.0**-149 and report['subnormal']['maximum'] == 3*2.0**-149
    assert report['huge']['sum'] == f32(3.4e38)*2+f32(-1e38) and report['huge']['maximum'] == f32(3.4e38) and report['huge']['minimum'] == f32(-1e38)
    assert (report['near-boundary']['sum'], report['near-boundary']['mean'], report['near-boundary']['minimum'], report['near-boundary']['maximum']) == (1.5, 0.5, -16777215.0, 16777216.0)
    assert report['mixed']['sum'] == 7.25 and report['mixed']['minimum'] == -7.25 and report['uint16-max']['sum'] == 131069 and report['uint16-max']['mean'] == 131069/3
    # Partial cancellation the old bound accepted (bound/|sum| = 0.444): refused with the stable code before any native process starts.
    path = directory/'partial-cancellation.tif'; path.write_bytes(tiff([f32(1e19), -f32(1e19), 1e4]+[1.0]*27, dtype='Float32', units='1'))
    report['partial-cancellation'] = refused(lambda: run('partial-cancellation-run', document(path, units='1', zones=[Z('p', 0, 0, 3, 1)])), 'ZONE_SUM_UNRESOLVABLE')
    refused_run = directory/'partial-cancellation-run'
    assert adaptor.read(refused_run, 'result.json')['status'] == 'failed' and not (refused_run/'zonal.stdout').exists() and not (refused_run/'.dispatch').exists() and not (refused_run/'zonal-submission.json').exists()
    report['partial-cancellation']['nativeProcessStarted'] = False
    # Signed zero: native [-0.0, 0.0] publishes canonical numeric zero in both public files.
    path = directory/'signed-zero.tif'; path.write_bytes(tiff([-0.0, 0.0]+[1.0]*28, dtype='Float32', units='1'))
    run('signed-zero-run', document(path, units='1', zones=[Z('z', 0, 0, 2, 1)]))
    zero_run = directory/'signed-zero-run'; zero_row = adaptor.read(zero_run, 'zones-summary.json')['zones'][0]
    assert [zero_row[k] for k in ('minimum', 'maximum', 'sum', 'mean')] == [0, 0, 0, 0] and all(math.copysign(1, zero_row[k]) == 1 for k in ('minimum', 'maximum', 'sum', 'mean'))
    assert (zero_run/'zones-summary.csv').read_text().splitlines()[1] == '"z",2,0,1,0,0,0,0' and '-0' not in (zero_run/'zones-summary.json').read_text()
    report['signed-zero'] = 'native [-0.0, 0.0] published as numeric 0 (CSV and JSON), never -0'
    path = directory/'all-missing.tif'; path.write_bytes(tiff([-9999]*30, dtype='Float32', units='1'))
    run('all-missing-run', document(path, units='1', zones=[Z('a', 0, 0, 6, 5), Z('b', 1, 1, 1, 1)]))
    rows = adaptor.read(directory/'all-missing-run', 'zones-summary.json')['zones']
    assert all(r['valid'] == 0 and r['sum'] is None and r['mean'] is None and r['coverage'] == 0 for r in rows); report['all-missing'] = 'verified null statistics'
    return report


def active(directory, executable, mode):
    """Hold the real native zonal process after it hashes consumed inputs, then cancel or exceed the deadline."""
    source = directory/(mode+'-source.tif'); source.write_bytes(tiff([i*.1 for i in range(262144)], width=512, height=512, dtype='Float32', units='1'))
    doc = document(source, units='1', zones=[Z('z%d' % i, i*32, 0, 32, 512) for i in range(16)])
    cancel = threading.Event(); out = directory/(mode+'-run'); observed = []; processes = []; errors = []
    launch = subprocess.Popen
    def capture(*args, **kwargs):
        process = launch(*args, **kwargs); processes.append(process); return process
    def watch():
        try:
            deadline = time.monotonic()+15
            while time.monotonic() < deadline:
                if (out/'zonal-inputs.json').is_file():
                    for process in processes:
                        try: command = Path('/proc', str(process.pid), 'cmdline').read_bytes()
                        except FileNotFoundError: continue
                        if process.poll() is None and str(out/'zonal_worker.py').encode() in command:
                            group = os.getpgid(process.pid)  # exact owned identity, recorded while the victim is live and before it is paused
                            os.kill(process.pid, signal.SIGSTOP)
                            for _ in range(1000):
                                if Path('/proc', str(process.pid), 'stat').read_text().rsplit(')', 1)[1].split()[0] == 'T': break
                                time.sleep(.001)
                            observed.append({'pid': process.pid, 'pgid': group, 'marker': 'zonal-inputs.json', 'pauseInjected': 'SIGSTOP at the zonal-inputs.json marker (after the worker hashed its inputs, before it finishes); not a claim of a stop inside the GDAL library'})
                            if mode == 'cancel': cancel.set()
                            return
                time.sleep(.001)
            cancel.set()
        except Exception as error: errors.append(str(error)); cancel.set()
    thread = threading.Thread(target=watch); thread.start()
    safety_net = []
    try:
        with patch('schemaxis.dispatch.subprocess.Popen', side_effect=capture):
            with allocation({'threads': 1, 'ranks': 1}, cancel):
                fault = refused(lambda: adaptor.run(doc, out, executable=executable, timeout=20 if mode == 'cancel' else 4), 'RUNNER_CANCELLED' if mode == 'cancel' else 'RUNNER_TIMED_OUT')
        # The runner itself must have terminated the victim and its whole process group; asserted BEFORE any safety-net cleanup below.
        thread.join(timeout=16); assert not thread.is_alive() and observed and not errors, errors
        victim = next(p for p in processes if p.pid == observed[0]['pid']); group = observed[0]['pgid']
        assert group == victim.pid, (group, victim.pid)  # start_new_session: the owned group is led by the victim
        assert victim.returncode == -signal.SIGKILL and not Path('/proc', str(victim.pid)).exists(), victim.returncode
        deadline = time.monotonic()+5; gone = False
        while time.monotonic() < deadline and not gone:
            try: os.killpg(group, 0)  # signal 0 probes the exact owned group only; no process-table search
            except ProcessLookupError: gone = True
            else: time.sleep(.01)
        assert gone, 'owned process group %d survived runner termination' % group
    finally:
        thread.join(timeout=16)
        for process in processes:  # safety net only; reaching it successfully is a failure of the assertions above
            if process.poll() is None:
                safety_net.append(process.pid)
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait(timeout=5)
    assert not safety_net, safety_net
    assert not (out/'verification.json').exists() and adaptor.read(out, 'result.json')['status'] == 'failed'
    assert not list(out.glob('zones-summary*'))
    return {**fault, **observed[0], 'returnCode': victim.returncode, 'ownedProcessGone': True, 'ownedProcessGroupGone': True, 'groupGoneBeforeSafetyNet': True, 'safetyNetKills': 0, 'failedResult': True, 'noSuccessfulPublication': True}


def calc_rows(zones):
    """Data rows and Summary lines derived from the producer's zones-summary.json zones.

    That summary is itself checked by the adaptor against the independent stdlib oracle, and the callers assert hand-stated literals for it;
    this function is not a hand-written literal oracle of the whole workbook.
    """
    rows = [[c['name'] for c in COLUMNS]]
    for z in zones: rows.append([z['zone'], float(z['valid']), float(z['missing']), float(z['coverage']), *[None if z[k] is None else float(z[k]) for k in ('minimum', 'maximum', 'sum', 'mean')]])
    summary = []
    for index, name in enumerate(c['name'] for c in COLUMNS[1:]):
        values = [r[index+1] for r in rows[1:] if r[index+1] is not None]
        mean = sum(values)/len(values)
        summary.append([name, len(values), sum(values), mean, min(values), max(values), statistics.stdev(values), len(rows)-1-len(values), 'BCDEFGH'[index]])
    return rows, summary


# Hand-counted, not computed from any output: Data = 8 header cells + 8 per zone - 4 null statistics per all-missing zone; Summary = 8 rows x 8 columns = 64.
# baseline: 4 zones, one all-missing (8+32-4+64 = 100); after the nodata pixel is valid or the zone grows no zone is all-missing (8+32+64 = 104);
# threeNode: 3 zones, one all-missing (8+24-4+64 = 92); windowChanged: 3 zones, none all-missing (8+24+64 = 96).
# Per format 100+104+104+92+96 = 496; both formats 992.
LITERAL_CELLS = {'baseline': 100, 'nodataPixelChanged': 104, 'zoneChanged': 104, 'threeNode': 92, 'windowChanged': 96}


def expected_cells(zones):
    """Independent workbook cell count: Data holds every non-null literal cell, Summary a fixed 8 x 8 block (header plus seven metrics)."""
    rows, summary = calc_rows(zones)
    return {'data': sum(v is not None for row in rows for v in row), 'summary': 8*(len(COLUMNS)), 'zones': len(zones),
            'nullCells': sum(v is None for row in rows[1:] for v in row)}


def check_calc(consumer, zones):
    """Check every cell of both workbook formats; return exact per-format and combined totals, compared with the literal expectation."""
    rows, summary = calc_rows(zones); wanted = expected_cells(zones); per_format = {}
    for extension, odf in (('xlsx', False), ('ods', True)):
        per_format[extension] = CALC.check_workbook(consumer/('analysis.'+extension), rows, summary, odf=odf)
        assert per_format[extension] == wanted['data']+wanted['summary'], (extension, per_format[extension], wanted)
    return {'perFormat': per_format, 'combined': sum(per_format.values()), 'expectedPerFormat': wanted['data']+wanted['summary'], 'zones': wanted['zones'], 'nullCells': wanted['nullCells']}


def chain(directory, locations, executable):
    source = directory/'chain-elevation.tif'; source.write_bytes(ELEVATION.read_bytes()); report = {'workbooks': []}
    reader = lambda ref, nullable=True: {'id': 'zones', 'filter': 'readTypedCSV', 'options': {'file': ref, 'nullToken': '\\N', 'columns': COLUMNS}}
    graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'zonal', 'document': document(source)}, {'id': 'workbook', 'document': {'version': 'schemaxis.calc/1', 'nodes': [reader({'$artifact': 'zonal', 'index': 0})]}}]}
    def jobs(result): return [Path(next(j['directory'] for j in result['jobs'] if j['operation'] == name)) for name in ('zonal', 'workbook')]
    def check(result, label):
        producer, consumer = jobs(result)
        assert (producer/'zones-summary.csv').read_bytes() == (consumer/'source.csv').read_bytes(), 'consumer did not capture the exact producer CSV'
        zones = adaptor.read(producer, 'zones-summary.json')['zones']
        report['workbooks'].append({'label': label, **check_calc(consumer, zones)})
        assert report['workbooks'][-1]['perFormat'] == {'xlsx': LITERAL_CELLS[label], 'ods': LITERAL_CELLS[label]}, report['workbooks'][-1]
        report[label] = {'csvSha256': hashlib.sha256((producer/'zones-summary.csv').read_bytes()).hexdigest(), 'zones': [z['zone'] for z in zones], 'consumerRuntime': json.loads((consumer/'runtime.json').read_text())['runtime']}
    first = workflow.execute(graph, directory/'workflow', locations=locations, timeout=240); assert workflow.verify(directory/'workflow')['verified']; check(first, 'baseline')
    resumed = workflow.execute(graph, directory/'workflow', locations=locations, timeout=240, resume=True); assert all(j['reused'] for j in resumed['jobs'])
    data = bytearray(source.read_bytes()); data[-30*2+8*2:-30*2+8*2+2] = (50).to_bytes(2, 'little', signed=True); source.write_bytes(bytes(data))  # nodata pixel (col 2,row 1) becomes 50
    pixel = workflow.execute(graph, directory/'workflow', locations=locations, timeout=240, resume=True); assert not any(j['reused'] for j in pixel['jobs']); assert workflow.verify(directory/'workflow')['verified']; check(pixel, 'nodataPixelChanged')
    assert report['nodataPixelChanged']['csvSha256'] != report['baseline']['csvSha256']
    assert [z for z in adaptor.read(jobs(pixel)[0], 'zones-summary.json')['zones'] if z['zone'] == '=1+2'][0]['valid'] == 1
    again = workflow.execute(graph, directory/'workflow', locations=locations, timeout=240, resume=True); assert all(j['reused'] for j in again['jobs'])
    # A changed authored zone is a different workflow graph: resume refuses it, so it is run as a fresh workflow whose nodes all compute (no same-directory reuse claim).
    changed = copy.deepcopy(graph); changed['operations'][0]['document']['zones'][2]['height'] = 2
    refused(lambda: workflow.execute(changed, directory/'workflow', locations=locations, timeout=240, resume=True), 'RESUME_MISMATCH')
    zone_changed = workflow.execute(changed, directory/'workflow-zone', locations=locations, timeout=240); assert not any(j['reused'] for j in zone_changed['jobs']); assert workflow.verify(directory/'workflow-zone')['verified']; check(zone_changed, 'zoneChanged')
    north = {z['zone']: z for z in adaptor.read(jobs(zone_changed)[0], 'zones-summary.json')['zones']}['north']
    assert (north['valid'], north['sum']) == (12, 238) and report['zoneChanged']['csvSha256'] not in (report['baseline']['csvSha256'], report['nodataPixelChanged']['csvSha256'])
    report['reuse'] = {'unchangedReusedBothJobs': True, 'nodataPixelSamePathRerunBoth': True, 'changedZoneResumeRefused': True, 'changedZoneFreshWorkflowComputedAllNodes': True}
    negatives = {}
    def attempt(name, mutate, code, text=None):
        bad = copy.deepcopy(graph); mutate(bad)
        negatives[name] = refused(lambda: workflow.execute(bad, directory/('neg-'+name), locations=locations, timeout=240), code, text)
    attempt('wrong-artifact-index', lambda g: g['operations'][1]['document']['nodes'][0]['options']['file'].update(index=1), 'TYPE_MISMATCH')
    attempt('header-mismatch', lambda g: g['operations'][1]['document']['nodes'][0]['options']['columns'][1].update(name='count'), 'INVALID_TABLE')
    attempt('null-not-allowed', lambda g: (g['operations'][0]['document']['zones'][1].update(x=4, y=3), g['operations'][1]['document']['nodes'][0]['options']['columns'][4].update(nullable=False)), 'INVALID_TABLE')  # zone 2 is now the all-missing nodata pixel
    attempt('text-declared-number', lambda g: g['operations'][1]['document']['nodes'][0]['options']['columns'][0].update(kind='number'), 'INVALID_TABLE')
    attempt('wrong-crs-units', lambda g: g['operations'][0]['document'].update(units='K'), 'INVALID_RASTER_CONTENT')
    attempt('outside-zone', lambda g: g['operations'][0]['document']['zones'].append(Z('out', 5, 4, 2, 1)), 'INVALID_ZONE')
    attempt('missing-policy-refuse', lambda g: g['operations'][0]['document'].update(missing='refuse'), 'ZONE_MISSING_VALUES')
    for name in negatives:
        assert not any(path for extension in ('xlsx', 'ods') for path in (directory/('neg-'+name)).glob('**/analysis.'+extension)), name  # no workbook for any of the seven, consumer-side included
    report['negativeControls'] = negatives
    # Three nodes: verified GeoTIFF window artifact 0 -> zonal summary on the cropped grid -> typed Calc workbook.
    three = directory/'three-source.tif'; three.write_bytes(ELEVATION.read_bytes())
    crop = json.loads((ROOT/'examples/schemaxis/gdal-window.json').read_text()); crop.update(source=str(three), x=0, y=0, width=6, height=4, outputWidth=6, outputHeight=4)
    zones = [Z('a', 0, 0, 3, 2), Z('b', 2, 1, 1, 1), Z('c', 3, 2, 3, 2)]
    graph3 = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'crop', 'document': crop}, {'id': 'zonal', 'document': document({'$artifact': 'crop', 'index': 0}, zones=zones)},
                                                               {'id': 'workbook', 'document': {'version': 'schemaxis.calc/1', 'nodes': [reader({'$artifact': 'zonal', 'index': 0})]}}]}
    result = workflow.execute(graph3, directory/'three', locations=locations, timeout=300); assert workflow.verify(directory/'three')['verified']
    producer = Path(next(j['directory'] for j in result['jobs'] if j['operation'] == 'zonal')); consumer = Path(next(j['directory'] for j in result['jobs'] if j['operation'] == 'workbook'))
    cropped = Path(next(j['directory'] for j in result['jobs'] if j['operation'] == 'crop'))
    assert (producer/'source.tif').read_bytes() == (cropped/'raster.tif').read_bytes() and (producer/'zones-summary.csv').read_bytes() == (consumer/'source.csv').read_bytes()
    rows = {z['zone']: z for z in adaptor.read(producer, 'zones-summary.json')['zones']}
    assert (rows['a']['valid'], rows['a']['sum'], rows['b']['valid'], rows['c']['valid'], rows['c']['sum']) == (5, 74, 0, 5, 33+34+35+43+45)
    report['workbooks'].append({'label': 'threeNode', **check_calc(consumer, list(rows.values()))})
    assert report['workbooks'][-1]['perFormat'] == {'xlsx': LITERAL_CELLS['threeNode'], 'ods': LITERAL_CELLS['threeNode']}, report['workbooks'][-1]
    resumed = workflow.execute(graph3, directory/'three', locations=locations, timeout=300, resume=True); assert all(j['reused'] for j in resumed['jobs'])
    report['threeNode'] = {'nodes': ['gdal window image artifact 0', 'gdal zonalSummary on cropped grid', 'calc readTypedCSV'], 'unchangedReused': True}
    # A changed crop window (and the zones that fit its grid) is a different graph: resume refuses it, and a fresh workflow computes every node.
    # Hand-stated literals: crop columns 1-4, rows 1-3 of the 6 x 5 fixture = 21 -- 23 24 / 31 32 33 34 / 41 42 43 -- (-- is nodata).
    moved = copy.deepcopy(graph3); moved['operations'][0]['document'].update(x=1, y=1, width=4, height=3, outputWidth=4, outputHeight=3)
    moved['operations'][1]['document']['zones'] = [Z('a', 0, 0, 2, 2), Z('b', 2, 1, 2, 2), Z('c', 1, 0, 3, 1)]
    refused(lambda: workflow.execute(moved, directory/'three', locations=locations, timeout=300, resume=True), 'RESUME_MISMATCH')
    window_changed = workflow.execute(moved, directory/'three-window', locations=locations, timeout=300); assert not any(j['reused'] for j in window_changed['jobs']); assert workflow.verify(directory/'three-window')['verified']
    jobs3 = {j['operation']: Path(j['directory']) for j in window_changed['jobs']}
    pixels = reference.parse((jobs3['crop']/'raster.tif').read_bytes())
    assert pixels['width'] == 4 and pixels['height'] == 3 and pixels['pixels'] == [21, -9999, 23, 24, 31, 32, 33, 34, 41, 42, 43, -9999], pixels['pixels']
    assert (jobs3['zonal']/'source.tif').read_bytes() == (jobs3['crop']/'raster.tif').read_bytes() and (jobs3['zonal']/'zones-summary.csv').read_bytes() == (jobs3['workbook']/'source.csv').read_bytes()
    moved_rows = {z['zone']: z for z in adaptor.read(jobs3['zonal'], 'zones-summary.json')['zones']}
    assert [(moved_rows[k]['valid'], moved_rows[k]['missing'], moved_rows[k]['minimum'], moved_rows[k]['maximum'], moved_rows[k]['sum']) for k in 'abc'] == [(3, 1, 21, 32, 84), (3, 1, 33, 43, 110), (2, 1, 23, 24, 47)]
    assert moved_rows['a']['mean'] == 28 and moved_rows['c']['mean'] == 23.5 and moved_rows['b']['mean'] == 110/3
    report['workbooks'].append({'label': 'windowChanged', **check_calc(jobs3['workbook'], list(moved_rows.values()))})
    assert report['workbooks'][-1]['perFormat'] == {'xlsx': LITERAL_CELLS['windowChanged'], 'ods': LITERAL_CELLS['windowChanged']}, report['workbooks'][-1]
    assert (jobs3['zonal']/'zones-summary.csv').read_bytes() != (producer/'zones-summary.csv').read_bytes()
    report['reuse'].update(changedWindowResumeRefused=True, changedWindowFreshWorkflowComputedAllNodes=True)
    report['cellTotals'] = {'perFormat': {f: sum(w['perFormat'][f] for w in report['workbooks']) for f in ('xlsx', 'ods')}, 'combined': sum(w['combined'] for w in report['workbooks'])}
    assert report['cellTotals'] == {'perFormat': {'xlsx': 496, 'ods': 496}, 'combined': 992}, report['cellTotals']
    report['verified'] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--gdal', type=Path, required=True); parser.add_argument('--calc', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True); parser.add_argument('--register', action='store_true'); args = parser.parse_args()
    directory = args.output_directory.resolve(); directory.mkdir(parents=True, exist_ok=False)
    executable = str(args.gdal.absolute()); locations = {'gdal': executable, 'calc': str(args.calc.absolute())}; report = {'verified': False}
    try:
        source = directory/'elevation.tif'; source.write_bytes(ELEVATION.read_bytes())
        adaptor.run(document(source), directory/'baseline', executable=executable, timeout=60)
        report['baseline'] = literal_baseline(directory/'baseline')
        temperature = json.loads((ROOT/'examples/schemaxis/gdal-zonal-temperature.json').read_text()); temperature['source'] = str(ROOT/'examples/schemaxis/fixtures/gdal/temperature.tif')
        adaptor.run(temperature, directory/'temperature', executable=executable, timeout=60)
        rows = {z['zone']: z for z in adaptor.read(directory/'temperature', 'zones-summary.json')['zones']}
        assert (rows['cold']['sum'], rows['cold']['mean'], rows['warm']['maximum'], rows['row']['mean']) == (1096.5, 274.125, 280.5, 279.875) and adaptor.read(directory/'temperature', 'zones-summary.json')['units'] == 'K'
        report['temperature'] = 'EPSG:4326 K Float32 big-endian zones verified; angular pixels, no area claim'
        report['mutants'] = mutants(directory/'baseline')
        report['inputs'] = inputs(directory, executable)
        report['cancel'] = active(directory, executable, 'cancel')
        report['timeout'] = active(directory, executable, 'timeout')
        receipt = qualify(adaptor.VERSION, directory/'kit', native=True, root=ROOT, locations={'gdal': executable}, timeout=60, wall_timeout=120)
        assert receipt['verified'], receipt
        report['kit'] = {'verified': True, 'cases': [c['id'] for c in receipt['cases']], 'lifecycle': receipt['lifecycle']}
        report['chain'] = chain(directory, locations, executable)
        if args.register: register(directory/'kit/qualification.json')
        report['verified'] = True
    finally: atomic_json(directory/'acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
