#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Qualify closed nullable Arrow interchange, independent evidence and SQLite handoff."""
import argparse
import calendar
import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import shutil
import struct
import subprocess
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


def refused(action, code='VERIFICATION_FAILED', reason=None):
    """Require the stable fault; `reason` pins the semantic cause so an incidental digest failure cannot pass."""
    try:
        action()
    except SchemaxisError as error:
        if error.fault.code != code or (reason is not None and reason not in error.fault.message + ' ' + str(error.fault.location)):
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


def subsecond(directory, executable):
    """Native acceptance of every accepted fractional width, with exact readback."""
    source = directory / 'subsecond.csv'
    rows = [('1', '2026-01-01T00:00:00.1Z', 1767225600100000), ('2', '2026-01-01T00:00:00.12Z', 1767225600120000),
            ('3', '2026-01-01T00:00:00.123Z', 1767225600123000), ('4', '2026-01-01T00:00:00.1234Z', 1767225600123400),
            ('5', '2026-01-01T00:00:00.12345Z', 1767225600123450), ('6', '2026-01-01T00:00:00.123456Z', 1767225600123456),
            ('7', '2026-01-01T00:00:00.5+00:00', 1767225600500000), ('8', '1969-12-31T23:59:59.5Z', -500000),
            ('9', '0001-01-01T00:00:00.1Z', -62135596799900000), ('10', '9999-12-31T23:59:59.99999+00:00', 253402300799999990),
            ('11', '2026-01-01T00:00:00Z', 1767225600000000)]
    source.write_text('id,observed\n' + ''.join(f'{i},{t}\n' for i, t, _ in rows))
    document = {'version': a.VERSION, 'operation': 'prepareTable', 'source': str(source),
                'columns': [{'name': 'id', 'type': 'int64', 'nullable': False},
                            {'name': 'observed', 'type': 'timestamp_us_utc', 'nullable': False}],
                'where': [], 'select': [{'column': 'id', 'name': 'id'}, {'column': 'observed', 'name': 'observed'}]}
    a.run(document, directory / 'subsecond', executable=executable, timeout=30)
    expected = [[i, str(micro)] for i, _, micro in rows]
    assert a.read(directory / 'subsecond', 'convert.stdout')['table']['rows'] == expected
    assert a.read(directory / 'subsecond', 'readback.stdout')['table']['rows'] == expected
    assert a.verify(directory / 'subsecond')['verified']
    # A literal with a five-digit fraction selects exactly the native microsecond value.
    chosen = {**document, 'where': [{'column': 'observed', 'test': 'eq', 'value': '2026-01-01T00:00:00.12345+00:00'}]}
    a.run(chosen, directory / 'subsecond-filter', executable=executable, timeout=30)
    report = a.read(directory / 'subsecond-filter', 'table-report.json')
    assert report['sourceRowIndices'] == [4] and report['rows'] == [['5', '2026-01-01T00:00:00.123450Z']]
    assert a.verify(directory / 'subsecond-filter')['verified']
    return {'nativeMicroseconds': [micro for _, _, micro in rows], 'filterSourceRowIndices': report['sourceRowIndices'], 'verified': True}


# --- Opt-in typed CSV publication -------------------------------------------------
# Everything below is a literal, hand-written oracle. Nothing is derived from the
# adaptor's encoder: expected bytes and typed rows are spelled out here.
CSV_SOURCE = ('id,small,reading,enabled,label,observed\n'
    '-9223372036854775808,-2147483648,-0,false,\\N,0001-01-01T00:00:00Z\n'
    '9223372036854775807,2147483647,5e-324,true,"",9999-12-31T23:59:59.999999Z\n'
    '9007199254740993,0,1.7976931348623157e308,\\N,"line one\nline two",1969-12-31T23:59:59.999999+00:00\n'
    '0,1,0.1000000000000000055511151231257827021181583404541015625,true,"a""b, c",2000-02-29T00:00:00.000001Z\n'
    '1,-1,2.2250738585072014e-308,false,"cr\rlf\r\nend",2026-01-01T00:00:00.5Z\n'
    '2,2,1e-7,true," lead and trail ",2026-01-01T00:00:00.12345+00:00\n'
    '3,3,12345678900,false,"=SUM(A1:A2)",\\N\n'
    '4,4,\\N,true,"café 雪 😀",1970-01-01T00:00:00Z\n'
    '5,5,-1.5e300,\\N,NA,1970-01-01T00:00:01Z\n'
    '6,6,1e10,true,"\\Nx",1970-01-01T00:00:00.000001Z\n'
    '7,7,0.000001,false,"x\\N",1970-01-01T00:00:00Z\n'
    '8,8,100,true,"",1970-01-01T00:00:00Z\n')
CSV_EXPECTED_ALL = ('id,small,reading,enabled,label,observed\n'
    '-9223372036854775808,-2147483648,-0,false,\\N,"0001-01-01T00:00:00.000000Z"\n'
    '9223372036854775807,2147483647,5e-324,true,"","9999-12-31T23:59:59.999999Z"\n'
    '9007199254740993,0,1.7976931348623157e+308,\\N,"line one\nline two","1969-12-31T23:59:59.999999Z"\n'
    '0,1,0.1,true,"a""b, c","2000-02-29T00:00:00.000001Z"\n'
    '1,-1,2.2250738585072014e-308,false,"cr\rlf\r\nend","2026-01-01T00:00:00.500000Z"\n'
    '2,2,1e-7,true," lead and trail ","2026-01-01T00:00:00.123450Z"\n'
    '3,3,1.23456789e+10,false,"=SUM(A1:A2)",\\N\n'
    '4,4,\\N,true,"café 雪 😀","1970-01-01T00:00:00.000000Z"\n'
    '5,5,-1.5e+300,\\N,"NA","1970-01-01T00:00:01.000000Z"\n'
    '6,6,1e+10,true,"\\Nx","1970-01-01T00:00:00.000001Z"\n'
    '7,7,0.000001,false,"x\\N","1970-01-01T00:00:00.000000Z"\n'
    '8,8,100,true,"","1970-01-01T00:00:00.000000Z"\n').encode()
CSV_ROWS_ALL = [
    [-2**63, -2**31, -0.0, False, None, -62135596800000000],
    [2**63 - 1, 2**31 - 1, 5e-324, True, '', 253402300799999999],
    [9007199254740993, 0, 1.7976931348623157e308, None, 'line one\nline two', -1],
    [0, 1, 0.1, True, 'a"b, c', 951782400000001],
    [1, -1, 2.2250738585072014e-308, False, 'cr\rlf\r\nend', 1767225600500000],
    [2, 2, 1e-7, True, ' lead and trail ', 1767225600123450],
    [3, 3, 12345678900.0, False, '=SUM(A1:A2)', None],
    [4, 4, None, True, 'café 雪 😀', 0],
    [5, 5, -1.5e300, None, 'NA', 1000000],
    [6, 6, 1e10, True, '\\Nx', 1],
    [7, 7, 0.000001, False, 'x\\N', 0],
    [8, 8, 100.0, True, '', 0]]
CSV_SELECTED = {'where': [{'column': 'enabled', 'test': 'isValid'}],
    'select': [{'column': 'id', 'name': 'sample_id'}, {'column': 'small', 'name': 'batch', 'cast': 'int64'},
               {'column': 'reading', 'name': 'value', 'fillNull': '-0'}, {'column': 'enabled', 'name': 'active'},
               {'column': 'label', 'name': 'name', 'fillNull': 'unlabelled'},
               {'column': 'observed', 'name': 'seen_at', 'fillNull': '1970-01-01T00:00:00Z'}]}
CSV_EXPECTED_SELECTED = ('sample_id,batch,value,active,name,seen_at\n'
    '-9223372036854775808,-2147483648,-0,false,"unlabelled","0001-01-01T00:00:00.000000Z"\n'
    '9223372036854775807,2147483647,5e-324,true,"","9999-12-31T23:59:59.999999Z"\n'
    '0,1,0.1,true,"a""b, c","2000-02-29T00:00:00.000001Z"\n'
    '1,-1,2.2250738585072014e-308,false,"cr\rlf\r\nend","2026-01-01T00:00:00.500000Z"\n'
    '2,2,1e-7,true," lead and trail ","2026-01-01T00:00:00.123450Z"\n'
    '3,3,1.23456789e+10,false,"=SUM(A1:A2)","1970-01-01T00:00:00.000000Z"\n'
    '4,4,-0,true,"café 雪 😀","1970-01-01T00:00:00.000000Z"\n'
    '6,6,1e+10,true,"\\Nx","1970-01-01T00:00:00.000001Z"\n'
    '7,7,0.000001,false,"x\\N","1970-01-01T00:00:00.000000Z"\n'
    '8,8,100,true,"","1970-01-01T00:00:00.000000Z"\n').encode()
CSV_SELECTED_INDICES = [0, 1, 3, 4, 5, 6, 7, 9, 10, 11]
CSV_ROWS_SELECTED = [[CSV_ROWS_ALL[i][0], CSV_ROWS_ALL[i][1], -0.0 if CSV_ROWS_ALL[i][2] is None else CSV_ROWS_ALL[i][2],
                      CSV_ROWS_ALL[i][3], 'unlabelled' if CSV_ROWS_ALL[i][4] is None else CSV_ROWS_ALL[i][4],
                      0 if CSV_ROWS_ALL[i][5] is None else CSV_ROWS_ALL[i][5]] for i in CSV_SELECTED_INDICES]
TIMESTAMP = re.compile(r'(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)\.(\d{6})Z\Z')


def decoded_csv(data, types):
    """Independent consumer: csv.reader plus the type declaration; every cell is parsed, nothing is inferred."""
    records = list(csv.reader(io.StringIO(data.decode('utf-8'), newline=''), strict=True))
    header, rows = records[0], []
    for record in records[1:]:
        assert len(record) == len(types), record
        row = []
        for cell, kind in zip(record, types):
            if cell == '\\N':
                row.append(None)
            elif kind == 'bool':
                row.append({'true': True, 'false': False}[cell])
            elif kind in ('int32', 'int64'):
                assert str(int(cell)) == cell
                row.append(int(cell))
            elif kind == 'float64':
                row.append(float(cell))
            elif kind == 'timestamp_us_utc':
                m = TIMESTAMP.fullmatch(cell)
                row.append(calendar.timegm(tuple(map(int, m.groups()[:6]))) * 1000000 + int(m.group(7)))
            else:
                row.append(cell)
        rows.append(row)
    return header, rows


def same_rows(left, right):
    """Exact comparison; doubles by IEEE bits so -0 and 0 differ, bool is not int."""
    def one(a, b):
        if type(a) is not type(b):
            return False
        return struct.pack('<d', a) == struct.pack('<d', b) if isinstance(a, float) else a == b
    return len(left) == len(right) and all(len(x) == len(y) and all(one(a, b) for a, b in zip(x, y)) for x, y in zip(left, right))


def wire(rows, types):
    return [[None if v is None else struct.pack('<d', v).hex() if t == 'float64' else str(v) if t in ('int64', 'timestamp_us_utc') else v
             for v, t in zip(row, types)] for row in rows]


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def csv_publication(directory, document, executable):
    """Fresh native opted-in runs against literal bytes and an independent typed row oracle."""
    source = directory / 'csv-boundaries.csv'
    source.write_text(CSV_SOURCE, encoding='utf-8', newline='')
    base = {**copy.deepcopy(document), 'source': str(source), 'where': [], 'publishCSV': True}
    cases = {'all': (base, CSV_EXPECTED_ALL, CSV_ROWS_ALL, list(range(12)), ['id', 'small', 'reading', 'enabled', 'label', 'observed']),
             'selected': ({**base, **copy.deepcopy(CSV_SELECTED)}, CSV_EXPECTED_SELECTED, CSV_ROWS_SELECTED, CSV_SELECTED_INDICES,
                          ['sample_id', 'batch', 'value', 'active', 'name', 'seen_at'])}
    types = ['int64', 'int32', 'float64', 'bool', 'utf8', 'timestamp_us_utc']
    selected_types = ['int64', 'int64', 'float64', 'bool', 'utf8', 'timestamp_us_utc']
    result = {}
    for name, (doc, expected, rows, indices, header) in cases.items():
        run = directory / ('csv-' + name)
        a.run(doc, run, executable=executable, timeout=30)
        kinds = types if name == 'all' else selected_types
        data = (run / 'table.csv').read_bytes()
        assert data == expected, (name, data)
        head, parsed = decoded_csv(data, kinds)
        assert head == header and same_rows(parsed, rows), name
        report = a.read(run, 'table-report.json')
        assert report['sourceRowIndices'] == indices and report['outputRows'] == len(rows)
        assert report['csv'] == {'file': 'table.csv', 'format': 'schemaxis.apachearrow.table-csv/1', 'bytes': len(expected),
                                 'sha256': hashlib.sha256(expected).hexdigest(), 'nullToken': '\\N'}
        assert [c['name'] for c in report['columns']] == header
        # Parquet, native source/readback/CSV-reopen snapshots and the CSV all describe the same rows.
        for stage in ('readback', 'csvreadback'):
            snapshot = a.read(run, stage + '.stdout')['table']
            assert snapshot['rows'] == wire(rows, kinds), (name, stage)
            assert [c['name'] for c in snapshot['columns']] == header
        receipt = a.read(run, 'verification.json')
        assert [Path(x['file']).name for x in receipt['artifacts']] == ['table.parquet', 'table-report.json', 'table.csv']
        assert [x['kind'] for x in receipt['artifacts']] == ['file', 'text', 'file']
        assert receipt['artifacts'][2]['sha256'] == hashlib.sha256(expected).hexdigest()
        assert (run / 'table.csv.metadata.json').is_file()
        # Standalone verification uses the captured source and still checks every CSV cell.
        original = directory / ('csv-original-' + name + '.csv')
        shutil.move(str(source), str(original))
        try:
            verified = a.verify(run)
        finally:
            shutil.move(str(original), str(source))
        assert verified['verified'] and verified['artifacts'] == 3 and verified['rows'] == len(rows)
        result[name] = {'bytes': len(expected), 'sha256': hashlib.sha256(expected).hexdigest(), 'rows': len(rows)}
    # Header-only output for an empty result, and a row that is null in every nullable column.
    empty = {**base, 'where': [{'column': 'id', 'test': 'eq', 'value': '1000'}]}
    a.run(empty, directory / 'csv-empty', executable=executable, timeout=30)
    assert (directory / 'csv-empty/table.csv').read_bytes() == b'id,small,reading,enabled,label,observed\n'
    assert a.read(directory / 'csv-empty', 'csvreadback.stdout')['table']['rows'] == []
    assert a.read(directory / 'csv-empty', 'table-report.json')['outputRows'] == 0 and a.verify(directory / 'csv-empty')['rows'] == 0
    nulls = directory / 'csv-all-null.csv'
    nulls.write_text('id,small,reading,enabled,label,observed\n5,5,\\N,\\N,\\N,\\N\n')
    a.run({**base, 'source': str(nulls)}, directory / 'csv-all-null', executable=executable, timeout=30)
    assert (directory / 'csv-all-null/table.csv').read_bytes() == b'id,small,reading,enabled,label,observed\n5,5,\\N,\\N,\\N,\\N\n'
    assert a.read(directory / 'csv-all-null', 'csvreadback.stdout')['table']['rows'] == [['5', 5, None, None, None, None]]
    assert a.read(directory / 'csv-all-null', 'table-report.json')['nullCounts'] == [0, 0, 1, 1, 1, 1]
    assert a.verify(directory / 'csv-all-null')['verified']
    result['emptyAndAllNull'] = True
    # Same document and source with the option absent publishes exactly the same Parquet and report rows.
    for label, extra in (('absent', {}), ('false', {'publishCSV': False})):
        doc = {k: v for k, v in cases['selected'][0].items() if k != 'publishCSV'} | extra
        run = directory / ('csv-' + label)
        a.run(doc, run, executable=executable, timeout=30)
        assert digest_file(run / 'table.parquet') == digest_file(directory / 'csv-selected/table.parquet')
        report = a.read(run, 'table-report.json')
        assert 'csv' not in report and report['rows'] == a.read(directory / 'csv-selected', 'table-report.json')['rows']
        assert not (run / 'table.csv').exists() and not (run / 'csvreadback.stdout').exists()
        assert [Path(x['file']).name for x in a.read(run, 'verification.json')['artifacts']] == ['table.parquet', 'table-report.json']
        assert a.verify(run)['artifacts'] == 2
    result['optionAbsentAndFalseOmitCSV'] = True
    return result


def csv_option_compatibility(directory, executable, retained):
    """Absent, false and true runs agree with an older retained numeric/nullable run, which is only read."""
    if retained is None:
        return {'skipped': 'no --retained-run supplied'}
    retained = Path(retained).resolve()
    def snapshot():
        return {str(p.relative_to(retained)): digest_file(p) for p in sorted(retained.rglob('*')) if p.is_file()}
    before = snapshot()
    authored = json.loads((retained / 'authored.json').read_text())
    assert 'publishCSV' not in authored
    source = directory / 'retained-source.csv'
    source.write_bytes((retained / 'source.csv').read_bytes())
    document = {**authored, 'source': str(source)}
    outcome = {}
    for label, extra in (('absent', {}), ('false', {'publishCSV': False}), ('true', {'publishCSV': True})):
        run = directory / ('retained-compat-' + label)
        a.run({**document, **extra}, run, executable=executable, timeout=30)
        assert digest_file(run / 'table.parquet') == digest_file(retained / 'table.parquet'), label
        legacy_report = a.read(retained, 'table-report.json')
        report = a.read(run, 'table-report.json')
        csv_block = report.pop('csv', None)
        assert report == legacy_report, label
        assert (csv_block is not None) == (label == 'true')
        if label != 'true':
            assert digest_file(run / 'table-report.json') == digest_file(retained / 'table-report.json')
            assert a.read(run, 'plan.json') == {k: v for k, v in a.read(retained, 'plan.json').items() if k != 'source'} | {'source': str(source)}
        outcome[label] = {'parquetSha256': digest_file(run / 'table.parquet'), 'csv': csv_block is not None}
    assert snapshot() == before, 'retained run was modified'
    outcome['retainedFiles'] = len(before)
    outcome['retainedUnmodified'] = True
    return outcome


def float_layout(directory, executable):
    """Native shortest-layout comparison, both Arrow's cast and the full adaptor publication path."""
    generator = random.Random(65)
    values = [0.0, -0.0, 5e-324, -5e-324, 2.2250738585072014e-308, 2.225073858507201e-308, 1.7976931348623157e308, -1.7976931348623157e308,
              0.1, 1e-6, 9.999999999999999e-7, 1e-7, 1e9, 9999999999.999998, 1e10, 1e15, 1e16, 1e21, 1e22, 123456789.0, 12345678900.0]
    for exponent in range(-323, 309):
        base = float('1e%d' % exponent)
        for multiplier in (1, 2, 3, 5, 7, 9.5, 9.999999):
            value = base * multiplier
            if value == value and abs(value) != float('inf'):
                values += [value, -value, struct.unpack('<d', struct.pack('<Q', struct.unpack('<Q', struct.pack('<d', value))[0] + 1))[0]]
    while len(values) < 400000:
        value = struct.unpack('<d', struct.pack('<Q', generator.getrandbits(64)))[0]
        if value == value and abs(value) != float('inf'):
            values.append(value)
    folder = directory / 'float-layout'
    folder.mkdir()
    (folder / 'bits.txt').write_text('\n'.join(struct.pack('<d', v).hex() for v in values))
    (folder / 'layout.py').write_text(
        'import struct, sys\nimport pyarrow as pa\nimport pyarrow.compute as pc\nimport pyarrow.csv as csv\n'
        'values = [struct.unpack("<d", bytes.fromhex(line))[0] for line in open("bits.txt").read().split()]\n'
        'array = pa.array(values, pa.float64())\n'
        'open("cast.txt", "w").write("\\n".join(pc.cast(array, pa.string()).to_pylist()))\n'
        'csv.write_csv(pa.table({"v": array}), "written.csv", csv.WriteOptions(include_header=False, null_string="\\\\N", quoting_style="needed"))\n')
    subprocess.run([executable, '-I', 'layout.py'], cwd=folder, check=True, timeout=120, capture_output=True)
    from schemaxis.adaptors.apachearrow import reference
    cast = (folder / 'cast.txt').read_text().split('\n')
    written = (folder / 'written.csv').read_text().split('\n')[:-1]
    assert len(cast) == len(written) == len(values)
    wrong = [(v, c, w) for v, c, w in zip(values, cast, written) if not (reference.float_text(v) == c == w)]
    assert not wrong, wrong[:5]
    assert all(struct.pack('<d', float(c)) == struct.pack('<d', v) for v, c in zip(values, cast))
    # And through the actual adaptor: 10,000 rows of binary64 cells, compared byte for byte by verification.
    chosen = [values[i] for i in sorted(generator.sample(range(len(values)), 20000))]
    source = directory / 'float-layout-rows.csv'
    source.write_text('a,b\n' + ''.join(f'{repr(x)},{repr(y)}\n' for x, y in zip(chosen[:10000], chosen[10000:])))
    document = {'version': a.VERSION, 'operation': 'prepareTable', 'source': str(source), 'publishCSV': True,
                'columns': [{'name': 'a', 'type': 'float64', 'nullable': False}, {'name': 'b', 'type': 'float64', 'nullable': False}],
                'select': [{'column': 'a', 'name': 'a'}, {'column': 'b', 'name': 'b'}]}
    a.run(document, directory / 'float-layout-run', executable=executable, timeout=60)
    assert a.verify(directory / 'float-layout-run')['rows'] == 10000
    return {'nativeDoublesCompared': len(values), 'castEqualsWriterEqualsHost': True, 'adaptorRows': 10000,
            'includes': 'random bit patterns, subnormals, maximum finite, signed zero, powers of ten and neighbours'}


def csv_refresh(directory):
    """Repair every ordinary digest a careful forger would; only semantic checks can catch the edit."""
    data = (directory / 'table.csv').read_bytes()
    report = a.read(directory, 'table-report.json')
    report['csv'].update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    atomic_json(directory / 'table-report.json', report)
    bindings = a.read(directory, 'csvreadback-inputs.json')
    bindings['table.csv'] = hashlib.sha256(data).hexdigest()
    atomic_json(directory / 'csvreadback-inputs.json', bindings)
    refresh(directory)


def hostile_csv(directory):
    saved = {path: path.read_bytes() for path in directory.rglob('*') if path.is_file()}
    results = {}
    def restore():
        for path in directory.rglob('*'):
            if path.is_file() and path not in saved:
                path.unlink()
        for path, data in saved.items():
            path.write_bytes(data)
    original = saved[directory / 'table.csv']
    edits = {
        'wideIntegerChanged': (b'9007199254740993', b'9007199254740994'),
        'signedZeroErased': (b',-0,false,', b',0,false,'),
        'equalNumberOtherLayout': (b',0.1,true,', b',0.10,true,'),
        'subnormalChanged': (b'5e-324', b'1e-323'),
        'maxFiniteChanged': (b'1.7976931348623157e+308', b'1.7976931348623155e+308'),
        'nullBecomesEmptyText': (b',false,\\N,"0001', b',false,"","0001'),
        'emptyTextBecomesNull': (b',true,"","9999', b',true,\\N,"9999'),
        'nullTokenQuoted': (b',false,\\N,"0001', b',false,"\\N","0001'),
        'textUnquoted': (b',"NA",', b',NA,'),
        'embeddedNewlineChanged': (b'line one\nline two', b'line one\r\nline two'),
        'unicodeChanged': ('雪'.encode(), '雲'.encode()),
        'formulaGuarded': (b'"=SUM(A1:A2)"', b'"\'=SUM(A1:A2)"'),
        'timestampPrecisionChanged': (b'"1969-12-31T23:59:59.999999Z"', b'"1969-12-31T23:59:59.99999Z"'),
        'timestampUnquoted': (b'"1970-01-01T00:00:01.000000Z"', b'1970-01-01T00:00:01.000000Z'),
        'boolSpelling': (b',true,"",', b',True,"",'),
        'headerRenamed': (b'id,small,', b'ID,small,'),
        'headerQuoted': (b'id,small,', b'"id",small,'),
        'headerReordered': (b'id,small,reading', b'small,id,reading'),
        'crlfRecords': (b'\n8,8,', b'\r\n8,8,'),
        'bom': (b'id,small', b'\xef\xbb\xbfid,small'),
        'finalNewlineRemoved': lambda data: data[:-1],
        'rowDropped': (b'8,8,100,true,"","1970-01-01T00:00:00.000000Z"\n', b''),
        'rowDuplicated': (b'8,8,100,true,"","1970-01-01T00:00:00.000000Z"\n', b'8,8,100,true,"","1970-01-01T00:00:00.000000Z"\n' * 2)}
    for name, edit in edits.items():
        try:
            if callable(edit):
                changed = edit(original)
            else:
                assert edit[0] in original, name
                changed = original.replace(edit[0], edit[1], 1)
            assert changed != original, name
            (directory / 'table.csv').write_bytes(changed)
            csv_refresh(directory)
            results[name] = refused(lambda: a.verify(directory), reason='table.csv differs from the canonical encoding')
        finally: restore()
    try:
        data = a.read(directory, 'csvreadback.stdout')
        data['table']['rows'][0][0] = '-9223372036854775807'
        atomic_json(directory / 'csvreadback.stdout', data);csv_refresh(directory)
        results['nativeCSVReopenDisagreement'] = refused(lambda: a.verify(directory), reason='csvreadback')
    finally: restore()
    try:
        report = a.read(directory, 'table-report.json');report['csv']['sha256'] = '0' * 64
        atomic_json(directory / 'table-report.json', report);refresh(directory)
        results['reportCSVDigestForged'] = refused(lambda: a.verify(directory), reason='published report differs')
    finally: restore()
    try:
        for suffix in ('', '.metadata.json'):
            (directory / ('table.csv' + suffix)).unlink()
        results['csvRemovedWithRefresh'] = refused(lambda: (refresh_missing(directory), a.verify(directory)), reason='table.csv')
    finally: restore()
    try:
        receipt = a.read(directory, 'verification.json');receipt['artifacts'].pop()
        atomic_json(directory / 'verification.json', receipt)
        results['csvDroppedFromReceipt'] = refused(lambda: a.verify(directory), reason='publication membership')
    finally: restore()
    try:
        authored = a.read(directory, 'authored.json');authored['publishCSV'] = False
        atomic_json(directory / 'authored.json', authored);p = a.plan(authored)
        atomic_json(directory / 'plan.json', p);atomic_json(directory / 'native-config.json', a.config(p))
        report = a.read(directory, 'table-report.json');del report['csv']
        atomic_json(directory / 'table-report.json', report)
        for stage in ('convert', 'readback', 'csvreadback'):
            bindings = a.read(directory, stage + '-inputs.json');bindings['native-config.json'] = a.digest(directory, 'native-config.json')
            atomic_json(directory / (stage + '-inputs.json'), bindings)
        refresh(directory)
        results['optionFalsifiedToFalseWithRehashedPlan'] = refused(lambda: a.verify(directory), reason='publication membership')
    finally: restore()
    try:
        (directory / 'table-extra.csv').write_bytes(original)
        results['strayTablePublication'] = refused(lambda: a.verify(directory), reason='publication membership')
    finally: restore()
    try:
        path = directory / 'native-worker.py';path.write_bytes(path.read_bytes() + b'\n#changed\n');csv_refresh(directory)
        results['workerChanged'] = refused(lambda: a.verify(directory), reason='trusted worker')
    finally: restore()
    assert a.verify(directory)['verified']
    return results


def refresh_missing(directory):
    """A forger who deletes the CSV also repairs what can be repaired without it."""
    receipt = a.read(directory, 'verification.json')
    receipt['artifacts'] = [x for x in receipt['artifacts'] if not x['file'].endswith('table.csv')]
    receipt['evidence'] = {name: a.digest(directory, name) for name in receipt['evidence']}
    atomic_json(directory / 'verification.json', receipt)


def csv_budget_before_native(directory, executable):
    source = directory / 'budget-source.csv'
    source.write_bytes(b'label\n' + b'\\N\n' * 1100)
    document = {'version': a.VERSION, 'operation': 'prepareTable', 'source': str(source), 'publishCSV': True,
                'columns': [{'name': 'label', 'type': 'utf8', 'nullable': True}],
                'select': [{'column': 'label', 'name': 'label', 'fillNull': '"' * 4096}]}
    refused(lambda: a.run(document, directory / 'budget-refused', executable=executable, timeout=30), 'INVALID_ARROW_CSV_BUDGET')
    run = directory / 'budget-refused'
    assert not any((run / name).exists() for name in ('convert.stdout', 'convert-submission.json', 'table.csv', 'table.parquet', 'verification.json'))
    assert a.read(run, 'result.json')['fault']['code'] == 'INVALID_ARROW_CSV_BUDGET'
    # Opt-out of the same table is accepted by the same executable.
    a.run({**document, 'publishCSV': False}, directory / 'budget-opted-out', executable=executable, timeout=30)
    assert a.verify(directory / 'budget-opted-out')['artifacts'] == 2
    refused(lambda: a.run({**document, 'publishCSV': 'yes'}, directory / 'option-refused', executable=executable, timeout=30), 'INVALID_ARGUMENT')
    assert not (directory / 'option-refused').exists()
    return {'budgetFault': 'INVALID_ARROW_CSV_BUDGET', 'nativeLaunched': False, 'optedOutAccepted': True, 'invalidOptionBeforeRunDirectory': True}


def csv_handoff(directory, locations, document):
    """Native producer table.csv -> existing Arrow prepareTable as a real $artifact workflow."""
    graph = json.loads((ROOT / 'examples/schemaxis/apachearrow-csv-handoff.json').read_text())
    source = directory / 'handoff-measurements.csv'
    source.write_bytes((ROOT / 'examples/schemaxis/fixtures/apachearrow/measurements.csv').read_bytes())
    graph['operations'][0]['document']['source'] = str(source)
    first = workflow.execute(graph, directory / 'csv-workflow', locations=locations, timeout=60)
    assert workflow.verify(directory / 'csv-workflow')['verified']
    producer = next(j for j in first['jobs'] if j['operation'] == 'prepare')
    consumer = next(j for j in first['jobs'] if j['operation'] == 'consume')
    produced = Path(producer['directory']) / 'table.csv'
    kinds = ['int64', 'int64', 'float64', 'bool', 'utf8', 'timestamp_us_utc']
    literal = [[9007199254740993, -2147483648, -0.0, True, '', -1],
               [9223372036854775807, 2147483647, 1.5, False, 'NA', 951782400000001],
               [-9223372036854775808, 0, None, None, 'unlabelled', None]]
    assert same_rows(decoded_csv(produced.read_bytes(), kinds)[1], literal)
    # The consumer declares the schema; native parsing of every typed cell, signed zero included.
    held = Path(consumer['directory'])
    assert (held / 'source.csv').read_bytes() == produced.read_bytes()
    assert a.read(held, 'convert.stdout')['table']['rows'] == wire(literal, kinds)
    assert a.read(held, 'table-report.json')['rows'] == [
        ['9007199254740993', '', -0.0, '1969-12-31T23:59:59.999999Z'],
        ['9223372036854775807', 'NA', 1.5, '2000-02-29T00:00:00.000001Z']]
    assert a.read(held, 'table-report.json')['sourceRowIndices'] == [0, 1]
    assert a.verify(held)['rows'] == 2
    second = workflow.execute(graph, directory / 'csv-workflow', locations=locations, timeout=60, resume=True)
    assert all(j['reused'] for j in second['jobs'])
    # Same path, changed bytes: the producer reruns, the CSV changes and the consumer sees the new value.
    source.write_bytes(source.read_bytes().replace(b'2000-02-29T00:00:00.000001+00:00', b'2000-02-29T00:00:00.000002+00:00').replace(b',1.5,', b',2.5,'))
    third = workflow.execute(graph, directory / 'csv-workflow', locations=locations, timeout=60, resume=True)
    assert not any(j['reused'] for j in third['jobs'])
    consumer = next(j for j in third['jobs'] if j['operation'] == 'consume')
    rows = a.read(Path(consumer['directory']), 'table-report.json')['rows']
    assert rows[1] == ['9223372036854775807', 'NA', 2.5, '2000-02-29T00:00:00.000002Z'], rows
    assert workflow.verify(directory / 'csv-workflow')['verified']
    changed = decoded_csv((Path(next(j for j in third['jobs'] if j['operation'] == 'prepare')['directory']) / 'table.csv').read_bytes(), kinds)[1]
    assert changed[1][2] == 2.5 and changed[1][5] == 951782400000002
    # An unopted producer has no artifact 2: the consumer is refused rather than silently reading something else.
    bare = copy.deepcopy(graph);bare['operations'][0]['document']['publishCSV'] = False
    try:
        workflow.execute(bare, directory / 'csv-workflow-unopted', locations=locations, timeout=60)
    except SchemaxisError as error:
        refusal = error.fault.code
    else:
        raise AssertionError('consumer accepted a producer without table.csv')
    return {'actualArrowCSVHandoff': True, 'literalRows': literal, 'unchangedReused': True, 'samePathChangedBytesReused': False,
            'changedValuePropagated': 2.5, 'unoptedProducerRefusal': refusal}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apachearrow', type=Path, required=True)
    parser.add_argument('--sqlite', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--retained-run', type=Path, help='older retained Arrow run directory, read only, for option compatibility')
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
        report['subsecond'] = subsecond(directory, locations['apachearrow'])
        report['hostile'] = hostile(directory / 'kit/baseline')
        report['csvPublication'] = csv_publication(directory, document, locations['apachearrow'])
        report['csvOptionCompatibility'] = csv_option_compatibility(directory, locations['apachearrow'], args.retained_run)
        report['csvFloatLayout'] = float_layout(directory, locations['apachearrow'])
        report['csvHostile'] = hostile_csv(directory / 'csv-all')
        report['csvHostileBaselineControls'] = hostile(directory / 'csv-all')
        report['csvBudget'] = csv_budget_before_native(directory, locations['apachearrow'])
        report['csvHandoff'] = csv_handoff(directory, locations, document)
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
        (directory / 'csv-lifecycle').mkdir()
        report['csvInflightLifecycle'] = lifecycle(directory / 'csv-lifecycle', {**document, 'publishCSV': True})
        for action in ('timeout', 'cancel'):
            refused(lambda: a.verify(directory / 'csv-lifecycle' / ('inflight-' + action)))
            assert not (directory / 'csv-lifecycle' / ('inflight-' + action) / 'verification.json').exists()
        if args.register: register(directory / 'kit/qualification.json')
        report['verified'] = True
    finally:
        atomic_json(directory / 'acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
