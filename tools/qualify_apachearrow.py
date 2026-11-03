#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Qualify closed nullable Arrow interchange, independent evidence and SQLite handoff."""
import argparse
import copy
import csv
import io
import json
import os
from pathlib import Path
import sys
import threading
import time

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors.apachearrow import adaptor as a
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import workflow

ROOT = Path(__file__).resolve().parents[1]


def refused(action, code='VERIFICATION_FAILED'):
    try:
        action()
    except SchemaxisError as error:
        if error.fault.code != code:
            raise AssertionError(error.fault.to_dict()) from error
        return code
    raise AssertionError('invalid input/evidence was accepted')


def refresh(directory):
    receipt = a.read(directory, 'verification.json')
    receipt['artifacts'] = a.artifacts(directory)
    receipt['evidence'] = {name: a.digest(directory, name) for name in receipt['evidence']}
    atomic_json(directory / 'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def hostile(directory):
    saved = {path: path.read_bytes() for path in directory.rglob('*') if path.is_file()}
    results = {}
    def restore():
        for path, data in saved.items(): path.write_bytes(data)
    mutations = [('nativeCSVDisagreement', 'convert.stdout', lambda b: b.replace(b'9007199254740993', b'9007199254740994')),
        ('nativeFloatSign', 'convert.stdout', lambda b: b.replace(b'0000000000000080', b'0000000000000000')),
        ('nativeReadbackDisagreement', 'readback.stdout', lambda b: b.replace(b'9007199254740993', b'9007199254740994')),
        ('forgedReport', 'table-report.json', lambda b: b.replace(b'9007199254740993', b'9007199254740994')),
        ('workerSource', 'native-worker.py', lambda b: b + b'\n#changed\n')]
    for name, target, mutation in mutations:
        try:
            path = directory / target; changed = mutation(path.read_bytes())
            assert changed != path.read_bytes()
            path.write_bytes(changed)
            refresh(directory)
            results[name] = refused(lambda: a.verify(directory))
        finally: restore()
    try:
        # Change the first PLAIN id cell, repair both native snapshot and all raw
        # hashes, and require the independently parsed source to still reject it.
        from schemaxis.adaptors.apachearrow.parquet import Reader
        path = directory / 'table.parquet'; data = bytearray(path.read_bytes())
        reader = Reader(data[4:]);reader.value(12);data[4 + reader.pos] ^= 1;path.write_bytes(data)
        bindings = a.read(directory, 'readback-inputs.json');bindings['table.parquet'] = a.digest(directory, 'table.parquet')
        atomic_json(directory / 'readback-inputs.json', bindings)
        refresh(directory)
        results['changedParquetWithRehashedBinding'] = refused(lambda: a.verify(directory))
    finally: restore()
    try:
        path = directory / 'source.csv';path.write_bytes(path.read_bytes().replace(b'9007199254740993', b'9007199254740994'))
        cap = a.read(directory, 'capture.json');cap.update(sha256=a.digest(directory, 'source.csv'), bytes=path.stat().st_size)
        atomic_json(directory / 'capture.json', cap)
        bindings = a.read(directory, 'convert-inputs.json');bindings['source.csv'] = cap['sha256']
        atomic_json(directory / 'convert-inputs.json', bindings);refresh(directory)
        results['captureChangedWithRehashedBinding'] = refused(lambda: a.verify(directory))
    finally: restore()
    try:
        doc = a.read(directory, 'authored.json');doc['where'] = [{'column': 'id', 'test': 'eq', 'value': '4'}]
        atomic_json(directory / 'authored.json', doc);p = a.plan(doc)
        atomic_json(directory / 'plan.json', p);atomic_json(directory / 'native-config.json', a.config(p))
        for stage in ('convert', 'readback'):
            bindings = a.read(directory, stage + '-inputs.json');bindings['native-config.json'] = a.digest(directory, 'native-config.json')
            atomic_json(directory / (stage + '-inputs.json'), bindings)
        refresh(directory)
        results['authoredSelectionChangedWithRehashedPlan'] = refused(lambda: a.verify(directory))
    finally: restore()
    for name, change in [('missingEvidence', lambda x: x['evidence'].pop('convert.stdout')),
                         ('extraEvidence', lambda x: x['evidence'].update({'foreign': '0' * 64})),
                         ('missingPublication', lambda x: x['artifacts'].pop())]:
        try:
            receipt = a.read(directory, 'verification.json');change(receipt)
            atomic_json(directory / 'verification.json', receipt)
            results[name] = refused(lambda: a.verify(directory))
        finally: restore()
    assert a.verify(directory)['verified']
    return results


def lifecycle(directory, document):
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
                result[action] = refused(lambda: a.run(document, directory / ('inflight-' + action), executable=str(wrapper), timeout=8 if thread else .4),
                                         'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')
        finally:
            if thread: thread.join(6)
        assert marker.exists(), 'owned child not launched'
        try: os.kill(int(marker.read_text()), 0)
        except ProcessLookupError: pass
        else: raise AssertionError('child survived ' + action)
    return result


def boundaries(directory, document, executable):
    source = directory / 'lexical-boundaries.csv'
    text = 'id,small,reading,enabled,label,observed\n-9223372036854775808,-2147483648,-0,false,"\\N",0001-01-01T00:00:00Z\n9223372036854775807,2147483647,5e-324,true,"",9999-12-31T23:59:59.999999Z\n9007199254740993,0,1.7976931348623157e308,"\\N","line one\nline two",1969-12-31T23:59:59.999999+00:00\n0,1,0.1000000000000000055511151231257827021181583404541015625,true,"a""b",2000-02-29T00:00:00.000001Z\n'
    source.write_text(text)
    doc = copy.deepcopy(document);doc['source'] = str(source)
    result = a.run(doc, directory / 'lexical-boundaries', executable=executable, timeout=30)
    raw = a.read(directory / 'lexical-boundaries', 'convert.stdout')['table']['rows']
    assert raw == [['-9223372036854775808', -2147483648, '0000000000000080', False, None, '-62135596800000000'],
        ['9223372036854775807', 2147483647, '0100000000000000', True, '', '253402300799999999'],
        ['9007199254740993', 0, 'ffffffffffffef7f', None, 'line one\nline two', '-1'],
        ['0', 1, '9a9999999999b93f', True, 'a"b', '951782400000001']]
    source.rename(directory / 'retained-original.csv')
    assert a.verify(directory / 'lexical-boundaries')['verified']
    refused(lambda: a.reusableInputs(doc), 'INVALID_ARROW_SOURCE')
    # Exercise actual native null filling of every nullable scalar type.
    fill = copy.deepcopy(document)
    fill['select'] = [{'column': 'reading', 'name': 'reading', 'fillNull': '-0'},
        {'column': 'enabled', 'name': 'enabled', 'fillNull': 'false'},
        {'column': 'label', 'name': 'label', 'fillNull': ''},
        {'column': 'observed', 'name': 'observed', 'fillNull': '1970-01-01T00:00:00Z'}]
    a.run(fill, directory / 'fill-all-types', executable=executable, timeout=30)
    assert a.read(directory / 'fill-all-types', 'table-report.json')['nullCounts'] == [0, 0, 0, 0]
    # Fixed writer creates three row groups and many text pages.
    source = directory / 'multipage.csv'
    out = io.StringIO(newline='');writer = csv.writer(out, lineterminator='\n')
    writer.writerow([c['name'] for c in document['columns']])
    for i in range(2400):
        writer.writerow([i, i, '-0.0' if i % 2 else '0.1', '\\N' if i % 3 else 'true',
                         '\\N' if i % 3 else '雪' * 1000, '\\N'])
    source.write_text(out.getvalue())
    many = {**document, 'source': str(source)}
    a.run(many, directory / 'multipage', executable=executable, timeout=30)
    assert a.verify(directory / 'multipage')['rows'] == 2400
    report = a.read(directory / 'multipage', 'table-report.json')
    assert report['nullCounts'] == [0, 0, 0, 1600, 1600, 2400]
    return {'nativeLexicalBoundaryBits': raw, 'retainedCaptureAfterOriginalRemoved': True,
            'currentSourceUnavailableRefusesReuse': True, 'fillAllNullableTypes': True,
            'multipageRows': 2400, 'multipageNullCounts': report['nullCounts'], 'verified': result['verified']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apachearrow', type=Path, required=True)
    parser.add_argument('--sqlite', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--register', action='store_true')
    args = parser.parse_args()
    directory = args.output_directory.resolve();directory.mkdir(parents=True, exist_ok=False)
    locations = {'apachearrow': str(args.apachearrow.absolute()), 'sqlite': str(args.sqlite.absolute())}
    report = {'verified': False}
    try:
        receipt = qualify(a.VERSION, directory / 'kit', native=True, root=ROOT,
                          locations=locations, timeout=30, wall_timeout=45)
        report['native'] = {'verified': receipt['verified'], 'cases': [c['id'] for c in receipt['cases']], 'lifecycle': receipt['lifecycle']}
        document = json.loads((ROOT / 'examples/schemaxis/apachearrow-measurements.json').read_text())
        document['source'] = str(ROOT / 'examples/schemaxis/fixtures/apachearrow/measurements.csv')
        report['boundaries'] = boundaries(directory, document, locations['apachearrow'])
        report['hostile'] = hostile(directory / 'kit/baseline')
        graph = json.loads((ROOT / 'examples/schemaxis/apachearrow-sqlite-workflow.json').read_text())
        for table in graph['operations'][0]['document']['tables']:
            name = Path(table['source']).name
            source = directory / name
            source.write_bytes((ROOT / 'examples/schemaxis/fixtures/sqlite' / name).read_bytes())
            table['source'] = str(source)
        first = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=30)
        assert workflow.verify(directory / 'workflow')['verified']
        consumer = next(j for j in first['jobs'] if j['operation'] == 'parquet')
        literal = [[None, '1', None], ['', '1', '0'], ['North', '3', '300'], ['South', '1', '-30']]
        assert a.read(Path(consumer['directory']), 'table-report.json')['rows'] == literal
        second = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=30, resume=True)
        assert all(j['reused'] for j in second['jobs'])
        source = Path(graph['operations'][0]['document']['tables'][1]['source'])
        values = json.loads(source.read_text());values[0]['amount'] = 101;source.write_text(json.dumps(values))
        third = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=30, resume=True)
        assert not any(j['reused'] for j in third['jobs'])
        consumer = next(j for j in third['jobs'] if j['operation'] == 'parquet')
        assert a.read(Path(consumer['directory']), 'table-report.json')['rows'][2] == ['North', '3', '301']
        assert workflow.verify(directory / 'workflow')['verified']
        report['workflow'] = {'actualSQLiteCSVHandoff': True, 'literalRows': literal, 'unchangedReused': True, 'samePathChangedBytesReused': False}
        study = copy.deepcopy(document);study['axes'] = [{'name': 'id', 'values': ['0', '4']}]
        study['where'] = [{'column': 'id', 'test': 'eq', 'value': {'$axis': 'id'}}]
        result = a.run(study, directory / 'study', executable=locations['apachearrow'], timeout=30)
        assert a.verify(directory / 'study')['verified'] and len(result['states']) == 2
        report['composition'] = {'states': 2, 'verified': True}
        report['inflightLifecycle'] = lifecycle(directory, document)
        if args.register: register(directory / 'kit/qualification.json')
        report['verified'] = True
    finally:
        atomic_json(directory / 'acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
