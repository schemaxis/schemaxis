#!/usr/bin/env python3
"""Native ImageJ measureRegions qualification: route kit, tamper probes and the typed Calc handoff.

Requires a Java 11+ runtime with jdk.compiler and ImageJ 1.54 ij.jar. The Calc handoff runs only
when a Calc location is supplied; otherwise it is reported as unavailable (unqualified), never as
a skipped success. Independent oracles here use no ImageJ and no Calc: exact pixel enumeration
for measurements and a dependency-free ODF/OOXML cell reader for the native workbook.
"""
import argparse
import copy
import csv
import hashlib
import json
import os
import signal
from fractions import Fraction
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from unittest import mock
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from schemaxis.adaptor_conformance import qualify
from schemaxis.adaptors import registry
from schemaxis.adaptor_delivery import case_document, route_materials
from schemaxis.adaptors.imagej import images, regions
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis import dispatch, workflow

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'schemaxis.imagej/1'
SERIES = ROOT/'examples/schemaxis/fixtures/imagej/series'
FRACTIONAL = SERIES
CASE = 'regions-baseline-8bit'


def rejected(action, message, location, code='VERIFICATION_FAILED'):
    """Run the action and require this exact fault code, message and location, so a probe cannot pass for another reason."""
    try: action()
    except SchemaxisError as error:
        found = error.fault
        assert (found.code, found.message, found.location) == (code, message, location), found.to_dict()
        return {'code': found.code, 'message': found.message, 'location': found.location}
    raise AssertionError('accepted invalid evidence or input')


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def refresh(target):
    """Recompute every ordinary evidence digest and every present publication digest, keeping receipt membership as it is."""
    prepared = regions.plan(json.loads((target/'authored.json').read_text()))
    receipt = json.loads((target/'verification.json').read_text())
    if isinstance(receipt.get('evidence'), dict):
        receipt['evidence'] = {name: sha(target/name) for name in regions.evidence_names(prepared) if name in receipt['evidence']}
    kinds = dict(regions.PUBLICATIONS)
    receipt['artifacts'] = [{'file': str(target/Path(entry['file']).name), 'kind': kinds[Path(entry['file']).name],
                             'sha256': sha(target/Path(entry['file']).name)} for entry in receipt['artifacts']]
    (target/'verification.json').write_text(json.dumps(receipt))


def edit_csv(path, row, field, value):
    lines = path.read_text().splitlines()
    parts = lines[row].split(','); parts[field] = value; lines[row] = ','.join(parts)
    path.write_text('\n'.join(lines)+'\n')


ROWS = 'native-measurements.csv/rows/%d'
SAME = 'native measurement differs from the independent enumeration'
MINMAX = 'native minimum/maximum differ from the exact enumeration'
IDENTITY = 'native row identity or order differs from frame-major declaration order'
SOURCE = 'native stage consumed different frame bytes'
SPEC = 'series specification differs from the authored frames and regions'
TABLE = 'published region table differs from verified native measurements'
RECEIPT_DIGEST = 'retained evidence digest differs from the verification receipt'


def tamper(target, report):
    """Classify every probe: refreshed-semantic (all ordinary digests and bindings recomputed), digest-only and contract controls.

    Each probe must fail with its exact intended message and location. Refreshed probes prove the semantic check, because the
    digest comparison cannot be the reason; digest-only probes prove the digest comparison itself; contract controls prove a
    structural contract and are labelled so, not as digest checks.
    """
    names = ['verification.json', 'authored.json', 'plan.json', 'series.spec', 'frame-02.pgm', 'native-measurements.csv', 'reopen-measurements.csv',
             'measure-readback.txt', 'reopen-readback.txt', 'region-measurements.csv', 'region-measurements.json', 'result.json', 'runtime.json',
             regions.NAME, 'java-version.stderr', 'measure.stdout', 'measure-submission.json']
    saved = {name: (target/name).read_bytes() for name in names}
    def restore():
        for name, data in saved.items(): (target/name).write_bytes(data)
    def swap(name):
        lines = (target/name).read_text().splitlines(); lines[1], lines[2] = lines[2], lines[1]
        (target/name).write_text('\n'.join(lines)+'\n')
    def replace(name, old, new):
        text = (target/name).read_text(); assert old in text, (name, old); (target/name).write_text(text.replace(old, new, 1))
    def append(name, text): (target/name).write_bytes((target/name).read_bytes()+text)
    def frame_pixel():
        data = bytearray((target/'frame-02.pgm').read_bytes()); data[-1] ^= 1; (target/'frame-02.pgm').write_bytes(bytes(data))
    def authored_time():
        authored = json.loads((target/'authored.json').read_text()); authored['frames'][1]['timeSeconds'] = 31.0
        atomic_json(target/'authored.json', authored); atomic_json(target/'plan.json', json.loads(json.dumps(regions.plan(authored))))
    def receipt(change):
        def action():
            value = json.loads((target/'verification.json').read_text()); change(value); (target/'verification.json').write_text(json.dumps(value))
        return action
    def membership(value): value['artifacts'].pop()
    def evidence_membership(value): value['evidence'].pop('measure.stdout')
    def exit_code(): replace('measure-submission.json', '"exitCode": 0', '"exitCode": 1')
    def jar_hash():
        value = json.loads((target/'runtime.json').read_text()); value['jarSha256'] = '0'*64; (target/'runtime.json').write_text(json.dumps(value))
    def result_failed(): (target/'result.json').write_text(json.dumps({'status': 'failed', 'verified': False}))
    old_java = lambda: (target/'java-version.stderr').write_text('openjdk version "8.0.1" 2020-01-01\n')
    # (name, class, mutation, expected message, expected location, code)
    probes = [
        ('nativeCount', 'refreshed', lambda: edit_csv(target/'native-measurements.csv', 1, 6, '13'), 'native pixel count differs from the exact rectangle enumeration', ROWS % 0+'/Count'),
        ('nativeMean', 'refreshed', lambda: edit_csv(target/'native-measurements.csv', 5, 8, '63.0'), SAME, ROWS % 4+'/Mean'),
        ('nativeMinimum', 'refreshed', lambda: edit_csv(target/'native-measurements.csv', 7, 9, '134.5'), MINMAX, ROWS % 6),
        ('nativeMaximum', 'refreshed', lambda: edit_csv(target/'native-measurements.csv', 12, 10, '243.0'), MINMAX, ROWS % 11),
        ('nativeArea', 'refreshed', lambda: edit_csv(target/'native-measurements.csv', 2, 7, '12.5'), SAME, ROWS % 1+'/Area'),
        ('nativeBounds', 'refreshed', lambda: edit_csv(target/'native-measurements.csv', 3, 4, '3.0'), SAME, ROWS % 2+'/Width'),
        ('reopenMean', 'refreshed', lambda: edit_csv(target/'reopen-measurements.csv', 4, 8, '178.5'), SAME, 'reopen-measurements.csv/rows/3/Mean'),
        ('nativeRowOrder', 'refreshed', lambda: swap('native-measurements.csv'), IDENTITY, ROWS % 0),
        ('nativeRowIdentity', 'refreshed', lambda: edit_csv(target/'native-measurements.csv', 2, 1, '0'), IDENTITY, ROWS % 1),
        ('nativeCalibrationReadback', 'refreshed', lambda: replace('measure-readback.txt', 'pixelWidth=0.5', 'pixelWidth=0.6'),
         'native calibration readback differs from the declared calibration', 'measure-readback.txt'),
        ('nativeRectangleReadback', 'refreshed', lambda: replace('reopen-readback.txt', 'region.0=core,2,1,4,3', 'region.0=core,2,1,4,4'),
         'native rectangle readback differs from the declared region in the reopen stage', 'reopen-readback.txt/region.0'),
        ('nativeFrameLabelReadback', 'refreshed', lambda: replace('measure-readback.txt', 'label.1=T1', 'label.1=T9'),
         'native frame label differs from the declared frame identifier in the measure stage', 'measure-readback.txt/label.1'),
        ('nativeSourceHashReadback', 'refreshed', lambda: replace('measure-readback.txt', 'frame.0.sha256=', 'frame.0.sha256=0'), SOURCE, 'measure-readback.txt/frame.0.sha256'),
        ('configuration', 'refreshed', lambda: replace('series.spec', 'region core 2 1 4 3', 'region core 2 1 4 2'), SPEC, 'series.spec'),
        ('retainedSourceFrame', 'refreshed', frame_pixel, SOURCE, 'measure-readback.txt/frame.1.sha256'),
        ('authoredTime', 'refreshed', authored_time, SPEC, 'series.spec'),
        ('publishedCsvCell', 'refreshed', lambda: replace('region-measurements.csv', 'T1,core,30.0,12,12,82,', 'T1,core,30.0,12,12,83,'), TABLE, 'region-measurements.csv'),
        ('publishedCsvIdentity', 'refreshed', lambda: replace('region-measurements.csv', 'T2,edge', 'T2,core'), TABLE, 'region-measurements.csv'),
        ('publishedJsonRecord', 'refreshed', lambda: replace('region-measurements.json', '"meanIntensity": 82', '"meanIntensity": 83'),
         'summary differs from independently checked measurements', 'region-measurements.json'),
        ('jarSha256Record', 'refreshed', jar_hash, 'the ImageJ jar the native process loaded differs from the jarSha256 recorded in runtime.json', 'measure-readback.txt/jarSha256'),
        ('storedFileCalibrationReadback', 'refreshed', lambda: replace('measure-readback.txt', 'frame.2.fileCalibration=1.0,1.0,', 'frame.2.fileCalibration=2.0,1.0,'),
         'ImageJ reports a calibration stored in a file that carries none', 'measure-readback.txt/frame.2.fileCalibration'),
        ('nativeSubmissionExitCode', 'refreshed', exit_code, 'native command or completion differs', 'measure-submission.json'),
        ('trustedProgram', 'refreshed', lambda: append(regions.NAME, b'// edited\n'), 'trusted fixed ImageJ program differs', regions.NAME),
        ('javaVersionRecord', 'refreshed', old_java, 'the fixed ImageJ program needs a Java 11 or newer runtime with the jdk.compiler module', 'java-version.stderr', 'UNSUPPORTED_RUNTIME'),
        ('publicationMembership', 'refreshed', receipt(membership), 'verification receipt publication membership or digests differ from the retained publications', 'verification.json/artifacts'),
        ('evidenceMembership', 'refreshed', receipt(evidence_membership), 'verification receipt evidence membership differs', 'verification.json/evidence'),
        ('ordinaryLogDigestOnly', 'digest', lambda: append('measure.stdout', b'#'), RECEIPT_DIGEST, 'verification.json/evidence/measure.stdout'),
        ('javaVersionLogDigestOnly', 'digest', lambda: append('java-version.stderr', b'#'), RECEIPT_DIGEST, 'verification.json/evidence/java-version.stderr'),
        ('readbackFieldContractOnly', 'contract', lambda: append('reopen-readback.txt', b'#'), 'native readback fields differ from the fixed program contract', 'reopen-readback.txt'),
        ('incompleteResult', 'contract', result_failed, 'region measurement did not complete', 'result.json', 'INCOMPLETE_EXECUTION')]
    counts = {'refreshed': 0, 'digest': 0, 'contract': 0}
    for name, kind, action, message, location, *code in probes:
        try:
            restore(); action()
            if kind == 'refreshed': refresh(target)
            found = rejected(lambda: registry.verify(target), message, location, *code)
            report['negative'].append({name: {**found, 'class': {'refreshed': 'refreshed-semantic', 'digest': 'digest-only', 'contract': 'contract-control'}[kind]}})
            counts[kind] += 1
        finally:
            restore()
    # Honest limit: an edit to an ordinary native log that is refreshed into the receipt is accepted. Logs are bound by digest only;
    # no measurement, calibration or identity is read from them.
    try:
        restore(); append('measure.stdout', b'#'); refresh(target)
        assert registry.verify(target)['verified']
        report['digestOnlyLimit'] = 'native stdout/stderr logs are retained under a receipt digest only; a refreshed receipt hides an edit to them, and no result is read from them'
    finally:
        restore()
    report['tamperClasses'] = {'refreshedSemantic': counts['refreshed'], 'digestOnly': counts['digest'], 'contractControl': counts['contract']}
    assert registry.verify(target)['verified']


# ----------------------------------------------------------------------- independent workbook cell readers
def column_letters(index):
    text = ''
    while True:
        text = chr(65+index % 26)+text; index = index//26-1
        if index < 0: return text


def xlsx_cells(path):
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(path) as archive:
        strings = [''.join(t.text or '' for t in si.iter('{%s}t' % ns['m'])) for si in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('m:si', ns)]
        sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
    cells = {}
    for cell in sheet.iter('{%s}c' % ns['m']):
        value = cell.find('m:v', ns)
        if value is None: continue
        cells[cell.get('r')] = strings[int(value.text)] if cell.get('t') == 's' else float(value.text)
    return cells


def ods_cells(path):
    office, table, text = ('{urn:oasis:names:tc:opendocument:xmlns:%s:1.0}' % n for n in ('office', 'table', 'text'))
    with ZipFile(path) as archive: root = ET.fromstring(archive.read('content.xml'))
    sheet = next(root.iter(table+'table')); cells = {}; row_number = 0
    for row in sheet.findall(table+'table-row'):
        repeat = int(row.get(table+'number-rows-repeated', '1')); column = 0; found = {}
        for cell in row:
            span = int(cell.get(table+'number-columns-repeated', '1')); kind = cell.get(office+'value-type')
            if kind == 'float': value = float(cell.get(office+'value'))
            elif kind == 'string': value = '\n'.join(''.join(p.itertext()) for p in cell.findall(text+'p'))
            else: value = None
            if value is not None:
                for offset in range(span): found[column+offset] = value
            column += span
        if found and repeat < 100:
            for extra in range(repeat):
                for key, value in found.items(): cells['%s%d' % (column_letters(key), row_number+extra+1)] = value
        row_number += repeat
    return cells


def expected_records(document, directory=None):
    """Independent oracle rows: [frame, region, time, count, area, mean, min, max] from the source frames."""
    prepared = regions.plan(document); rows = []
    decoded = [images.decode(Path(f['image']).read_bytes(), f['extension']) for f in prepared['frames']]
    for frame, image in zip(prepared['frames'], decoded):
        for region in prepared['regions']:
            facts = regions.enumerate_region(image, region)
            rows.append([frame['id'], region['id'], float(frame['timeSeconds']), facts['pixelCount'], facts['pixelCount']*prepared['pixelArea'],
                         facts['sum']/facts['pixelCount'], facts['minimum'], facts['maximum']])
    return prepared, rows


def check_cells(cells, prepared, rows):
    header = prepared['columns']
    for index, name in enumerate(header): assert cells['%s1' % column_letters(index)] == name, (index, name)
    for number, row in enumerate(rows, start=2):
        for index, value in enumerate(row):
            actual = cells['%s%d' % (column_letters(index), number)]
            ok = actual == value if isinstance(value, str) else isinstance(actual, float) and abs(actual-value) <= 1e-9*max(1, abs(value))
            assert ok, (number, index, actual, value)
    assert not any(re.fullmatch(r'[A-Z]+%d' % (len(rows)+2), key) for key in cells), 'extra record'
    return len(rows)*len(header)+len(header)


def formula_records(document, formula, overrides=None):
    """Independent rows from a closed-form plane formula and exact Fractions; no Schemaxis decoder or ImageJ output is used."""
    overrides, rows = overrides or {}, []
    pixel_area = Fraction(document['calibration']['pixelWidth'])*Fraction(document['calibration']['pixelHeight'])
    for t, frame in enumerate(document['frames']):
        for region in document['regions']:
            values = [overrides.get((t, i, j), formula(i, j, t)) for j in range(region['y'], region['y']+region['height'])
                      for i in range(region['x'], region['x']+region['width'])]
            rows.append([frame['id'], region['id'], float(frame['timeSeconds']), len(values), float(len(values)*pixel_area),
                         float(Fraction(sum(values), len(values))), min(values), max(values)])
    return rows


def fractional8(x, y, t): return (29*x+53*y+17*t+11*x*y) % 256


def check_area(cells, rows, pixel_area):
    """Every workbook area cell must be count x declared pixel area, and differ from the bare count when the pixel area is not 1."""
    for number, row in enumerate(rows, start=2):
        count, area = cells['D%d' % number], cells['E%d' % number]
        assert abs(area-count*pixel_area) <= 1e-9*max(1, area), (number, count, area, pixel_area)
        assert pixel_area == 1 or area != count, (number, 'area equals the pixel count although the pixel area is not 1')


def run_handoff(directory, locations, label, source, frames, formula, overrides, report):
    """ImageJ series CSV -> Calc readTypedCSV for one example; independently checks every native ODF/OOXML cell, area against count,
    unchanged reuse, a changed pixel at the same path, and (as a fresh workflow) a changed calibration and time."""
    original = json.loads((ROOT/source).read_text())
    folder = directory/(label+'-frames'); folder.mkdir()
    for path in frames: shutil.copyfile(path, folder/path.name)
    document = copy.deepcopy(original)
    series_document = document['operations'][0]['document']
    for frame in series_document['frames']: frame['image'] = str(folder/Path(frame['image']).name)
    target = directory/label
    result = workflow.execute(document, target, locations=locations, timeout=240)
    assert workflow.verify(target)['verified']
    jobs = {job['operation']: job for job in result['jobs']}
    series, book = Path(jobs['series']['directory']), Path(jobs['workbook']['directory'])
    rows = formula_records(series_document, formula)
    calibration = series_document['calibration']
    pixel_area = float(Fraction(calibration['pixelWidth'])*Fraction(calibration['pixelHeight']))
    csv_rows = list(csv.reader((series/'region-measurements.csv').read_text().splitlines()))
    prepared = regions.plan(series_document)
    assert csv_rows[0] == prepared['columns'] and len(csv_rows) == len(rows)+1
    for record, row in zip(csv_rows[1:], rows):
        assert record[:2] == row[:2] and all(abs(float(a)-b) <= 1e-9*max(1, abs(b)) for a, b in zip(record[2:], row[2:])), (record, row)
    assert any(sha(path) == sha(series/'region-measurements.csv') for path in book.rglob('*.csv') if path.is_file()), 'captured CSV bytes not preserved'
    for index, path in enumerate(frames): assert sha(series/('frame-%02d%s' % (index+1, path.suffix))) == sha(folder/path.name)
    cells = {'ods': ods_cells(book/'analysis.ods'), 'xlsx': xlsx_cells(book/'analysis.xlsx')}
    checked = {kind: check_cells(value, prepared, rows) for kind, value in cells.items()}
    for value in cells.values(): check_area(value, rows, pixel_area)
    nonintegral = sum(1 for row in rows if row[5] != int(row[5]))
    entry = {'handoff': 'ImageJ series CSV -> Calc readTypedCSV', 'example': source, 'records': len(rows), 'nativeCellsChecked': checked,
             'pixelArea': pixel_area, 'areaDiffersFromCount': pixel_area != 1, 'nonIntegralMeans': nonintegral,
             'textColumns': ['frame', 'region'], 'repeatedFrames': len(frames), 'repeatedRegions': len(series_document['regions'])}
    resumed = workflow.execute(document, target, locations=locations, timeout=240, resume=True)
    assert all(job['reused'] for job in resumed['jobs']); entry['unchangedReuse'] = True
    # Changing one pixel inside overlapping rectangles at the same path must invalidate the series and reach the workbook.
    if overrides:
        (t, x, y), value = next(iter(overrides.items()))
        path = folder/frames[t].name; data = bytearray(path.read_bytes())
        data[-(prepared_height(series_document)-y)*prepared_width(series_document)+x] = value
        path.write_bytes(bytes(data))
        changed = workflow.execute(document, target, locations=locations, timeout=240, resume=True)
        assert {j['operation']: j['reused'] for j in changed['jobs']} == {'series': False, 'workbook': False}
        jobs = {job['operation']: job for job in changed['jobs']}
        rows2 = formula_records(series_document, formula, overrides)
        assert rows2 != rows and any(a[5] != b[5] for a, b in zip(rows, rows2)), 'the changed pixel is inside a declared rectangle'
        book2 = Path(jobs['workbook']['directory'])
        entry['changedPixelCells'] = {kind: check_cells(read(book2/('analysis.'+kind)), prepared, rows2) for kind, read in (('ods', ods_cells), ('xlsx', xlsx_cells))}
        for kind, read in (('ods', ods_cells), ('xlsx', xlsx_cells)): check_area(read(book2/('analysis.'+kind)), rows2, pixel_area)
        entry['changedPixelReuse'] = {'series': False, 'workbook': False}
        rows = rows2
    # A changed calibration and a changed time are a different authored workflow (resume refuses it), so run it fresh:
    # both must reach the table and the workbook with the new area and time.
    series_document['calibration']['pixelWidth'] = calibration['pixelWidth']/2
    series_document['frames'][-1]['timeSeconds'] = series_document['frames'][-1]['timeSeconds']+5
    changed = workflow.execute(document, directory/(label+'-changed-calibration-time'), locations=locations, timeout=240)
    assert workflow.verify(directory/(label+'-changed-calibration-time'))['verified']
    jobs = {job['operation']: job for job in changed['jobs']}
    rows3 = formula_records(series_document, formula, overrides)
    assert rows3[-1][2] == rows[-1][2]+5 and rows3[0][4] == rows[0][4]/2
    prepared = regions.plan(series_document); book3 = Path(jobs['workbook']['directory'])
    half = pixel_area/2
    entry['changedCalibrationAndTimeCells'] = {kind: check_cells(read(book3/('analysis.'+kind)), prepared, rows3) for kind, read in (('ods', ods_cells), ('xlsx', xlsx_cells))}
    for read, kind in ((ods_cells, 'ods'), (xlsx_cells, 'xlsx')): check_area(read(book3/('analysis.'+kind)), rows3, half)
    entry['changedCalibrationAndTime'] = {'pixelWidth': series_document['calibration']['pixelWidth'], 'pixelArea': half, 'lastFrameSeconds': rows3[-1][2]}
    report['workflows'].append(entry)
    return document, folder


def prepared_width(document): return 9


def prepared_height(document): return 6


def handoff(directory, locations, report):
    """Fractional, non-unit-pixel-area handoff first, then the preserved original unit-area integer-mean handoff."""
    document, folder = run_handoff(directory, locations, 'handoff-fractional', 'examples/schemaxis/imagej-regions-fractional-to-calc.json',
                                   sorted(FRACTIONAL.glob('frac8-t*.pgm')), fractional8, {(1, 2, 2): 255}, report)
    legacy_handoff(directory, locations, report)
    # Incompatible consumer control: the numeric-only Calc readCSV cannot hold text identifiers.
    original = json.loads((ROOT/'examples/schemaxis/imagej-regions-fractional-to-calc.json').read_text())
    control = copy.deepcopy(original)
    for frame in control['operations'][0]['document']['frames']: frame['image'] = str(folder/Path(frame['image']).name)
    control['operations'][1]['document']['nodes'][0]['filter'] = 'readCSV'
    control['operations'][1]['document']['nodes'][0]['options'] = {'file': {'$artifact': 'series', 'index': 0}}
    try:
        outcome = workflow.execute(control, directory/'control', locations=locations, timeout=240)
        refused = outcome.get('status') != 'succeeded'
        report['incompatibleConsumer'] = {'consumer': 'Calc readCSV (numeric-only)', 'status': outcome.get('status')}
    except Exception as error:
        refused = True
        report['incompatibleConsumer'] = {'consumer': 'Calc readCSV (numeric-only)', 'refused': type(error).__name__,
                                          'fault': getattr(getattr(error, 'fault', None), 'code', None)}
    assert refused, 'numeric-only consumer accepted a table with text identifiers'


def legacy_handoff(directory, locations, report):
    """The original integer-mean, unit-pixel-area handoff, kept so its record stays comparable."""
    original = json.loads((ROOT/'examples/schemaxis/imagej-regions-to-calc.json').read_text())
    folder = directory/'handoff-frames'; folder.mkdir()
    for path in SERIES.glob('ramp8-t*.pgm'): shutil.copyfile(path, folder/path.name)
    document = copy.deepcopy(original)
    for frame in document['operations'][0]['document']['frames']: frame['image'] = str(folder/Path(frame['image']).name)
    target = directory/'handoff'
    result = workflow.execute(document, target, locations=locations, timeout=240)
    assert workflow.verify(target)['verified']
    jobs = {job['operation']: job for job in result['jobs']}
    series, book = Path(jobs['series']['directory']), Path(jobs['workbook']['directory'])
    prepared, rows = expected_records(document['operations'][0]['document'])
    csv_rows = list(csv.reader((series/'region-measurements.csv').read_text().splitlines()))
    assert csv_rows[0] == prepared['columns'] and len(csv_rows) == 13
    assert any(sha(path) == sha(series/'region-measurements.csv') for path in book.rglob('*.csv') if path.is_file()), 'captured CSV bytes not preserved'
    cells = {'ods': check_cells(ods_cells(book/'analysis.ods'), prepared, rows), 'xlsx': check_cells(xlsx_cells(book/'analysis.xlsx'), prepared, rows)}
    report['workflows'].append({'handoff': 'ImageJ series CSV -> Calc readTypedCSV', 'example': 'examples/schemaxis/imagej-regions-to-calc.json',
                                'records': len(rows), 'nativeCellsChecked': cells, 'pixelArea': prepared['pixelArea'],
                                'note': 'original integer-mean unit-pixel-area control; area equals the pixel count here by construction'})


# ----------------------------------------------------------------------- measureRegions timeout and cancellation lifecycle
class Recorder(subprocess.Popen):
    """Remember every child the shared runner starts, so the test can name the owned native PID and prove it gone."""
    started = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs); Recorder.started.append(self)


def command_line(pid):
    try: return Path('/proc/%d/cmdline' % pid).read_bytes().replace(b'\0', b' ').decode('utf-8', 'replace')
    except OSError: return ''


def alive_group(pid):
    """True while any process of the runner's own session/process group still exists."""
    try: os.killpg(pid, 0)
    except ProcessLookupError: return False
    except PermissionError: return True
    return True


def scenario(directory, locations, document, name, expected, submissions, *, timeout=60, skew_after=None, remaining=0.25,
             cancel_after=None, live=None, cancel_first=False):
    """Drive regions.run for real and require its own precise fault, a retained failed result and no surviving native process.

    skew_after names the stage after which the run's own clock is moved so only `remaining` seconds of the total deadline are
    left (negative: exhausted), so the genuine deadline arithmetic and the shared runner's kill path decide the outcome.
    cancel_after sets cancellation after that stage completes and the run's own checks decide; live names the stage during
    which cancellation is set while its java process is running, so the shared runner has to terminate the owned process tree.
    expected is (code, message, location); a location starting with '~' only needs to be contained in the actual location.
    """
    run = directory/name
    skew, cancel, stop, observed = [0.0], threading.Event(), threading.Event(), {}
    real_clock, real_execute = time.monotonic, regions.execute
    started = real_clock()
    class Clock:
        monotonic = staticmethod(lambda: real_clock()+skew[0])
    def spy(command, folder, stage, seconds, environment=None):
        result = real_execute(command, folder, stage, seconds, environment)
        if skew_after == stage: skew[0] = (started+timeout-remaining)-real_clock()
        if cancel_after == stage: cancel.set()
        return result
    def watch():
        while not stop.is_set():
            for process in list(Recorder.started):
                tokens = command_line(process.pid).split()
                named = [i for i, token in enumerate(tokens) if token.endswith('/'+regions.NAME)]
                if named and len(tokens) > named[0]+1 and tokens[named[0]+1] not in observed:
                    stage = tokens[named[0]+1]
                    observed[stage] = {'pid': process.pid, 'stage': stage, 'argv': tokens[:1]+['...', regions.NAME, stage]}
                    if live == stage: cancel.set()
            time.sleep(0.005)
    Recorder.started = []
    if cancel_first: cancel.set()
    watcher = threading.Thread(target=watch, daemon=True); watcher.start()
    fault = None
    try:
        with mock.patch.object(regions, 'time', Clock), mock.patch.object(regions, 'execute', spy), \
                mock.patch.object(dispatch.subprocess, 'Popen', Recorder), dispatch.allocation({'threads': 1, 'ranks': 1}, cancel):
            try: registry.run(copy.deepcopy(document), run, locations=locations, timeout=timeout)
            except SchemaxisError as error: fault = error.fault
    finally:
        stop.set(); watcher.join(10)
    assert fault is not None, name+' completed instead of being refused'
    code, message, location = expected
    assert fault.code == code and fault.message == message, fault.to_dict()
    assert (location[1:] in fault.location if location.startswith('~') else fault.location == location), fault.to_dict()
    result = json.loads((run/'result.json').read_text())
    assert result['status'] == 'failed' and result['verified'] is False and result['fault']['code'] == code, result
    assert not (run/'publication-metadata.json').exists(), name+' retained successful publication metadata'
    incomplete = rejected(lambda: regions.verify(run), 'region measurement did not complete', 'result.json', 'INCOMPLETE_EXECUTION')
    assert sorted(p.name for p in run.glob('*-submission.json')) == submissions, sorted(p.name for p in run.glob('*-submission.json'))
    owned = [{'pid': p.pid, 'returncode': p.returncode, 'groupAlive': alive_group(p.pid), 'procPresent': Path('/proc/%d' % p.pid).exists()}
             for p in Recorder.started]
    assert not any(item['groupAlive'] or item['procPresent'] or item['returncode'] is None for item in owned), owned
    if live or name.startswith('deadline-during'):
        stage = live or name.rsplit('-', 1)[1]
        assert stage in observed and observed[stage]['pid'] in [p.pid for p in Recorder.started], (observed, owned)
        killed = next(item for item in owned if item['pid'] == observed[stage]['pid'])
        assert killed['returncode'] in (-signal.SIGTERM, 128+signal.SIGTERM), killed
    return {'scenario': name, 'fault': fault.code, 'message': fault.message, 'location': fault.location, 'liveNative': list(observed.values()),
            'ownedProcesses': owned, 'nativeProcessesGone': True, 'publicationMetadataAbsent': True, 'failedResultRetained': True, 'verifyRefusesIt': incomplete['code'],
            'submissions': submissions}


def lifecycle(directory, locations, report):
    """Operation-specific timeout and cancellation for measureRegions itself, not the particle kit.

    Covers the run's own total deadline before launch, before the measure stage, during the measure and reopen processes and after
    verification, and cancellation before launch, before the measure stage, while the measure and reopen processes are live and
    before publication. Each needs its precise fault, a failed retained result.json and no surviving native process.
    """
    _, _, entry = route_materials(VERSION)
    case = next(c for c in entry['development']['cases'] if c['id'] == CASE)
    document = case_document(entry, case, ROOT)
    assert document['operation'] == 'measureRegions'
    folder = directory/'lifecycle'; folder.mkdir()
    exhausted, killed = 'native job exhausted its total timeout', 'native execution did not complete'
    timed, cancelled = 'RUNNER_TIMED_OUT', 'RUNNER_CANCELLED'
    java, measure = ['java-version-submission.json'], ['java-version-submission.json', 'measure-submission.json']
    everything = ['java-version-submission.json', 'measure-submission.json', 'reopen-submission.json']
    plan = [
        ('deadline-before-launch', (timed, exhausted, 'java-version'), [], dict(timeout=1e-9)),
        ('deadline-before-measure', (timed, exhausted, 'measure'), java, dict(skew_after='java-version', remaining=-1.0)),
        ('deadline-during-measure', (timed, killed, '~/.dispatch/measure/'), java, dict(skew_after='java-version')),
        ('deadline-during-reopen', (timed, killed, '~/.dispatch/reopen/'), measure, dict(skew_after='measure')),
        ('deadline-after-verification', (timed, 'region verification exhausted the total timeout', 'verification.json'), everything,
         dict(skew_after='reopen', remaining=-1.0)),
        ('cancel-before-launch', (cancelled, 'execution cancelled before dispatch', '$'), [], dict(cancel_first=True)),
        ('cancel-before-measure', (cancelled, 'region measurement cancelled before the measure stage', 'measure'), java, dict(cancel_after='java-version')),
        ('cancel-live-measure', (cancelled, killed, '~/.dispatch/measure/'), java, dict(live='measure')),
        ('cancel-live-reopen', (cancelled, killed, '~/.dispatch/reopen/'), measure, dict(live='reopen')),
        ('cancel-before-publication', (cancelled, 'region publication cancelled', 'verification.json'), everything, dict(cancel_after='reopen'))]
    report['regionsLifecycle'] = [scenario(folder, locations, document, name, expected, submissions, **options)
                                  for name, expected, submissions, options in plan]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--java', type=Path); parser.add_argument('--jar', type=Path)
    parser.add_argument('--calc', type=Path, help='absolute Calc soffice for the typed handoff')
    parser.add_argument('--config', type=Path); parser.add_argument('--wall-timeout', type=float, default=600)
    args = parser.parse_args()
    directory = args.output_directory.resolve(); directory.mkdir(parents=True, exist_ok=False)
    if args.config: config = args.config.resolve()
    else:
        locations = {'imagej': str(args.java), 'imagejJar': str(args.jar)}
        if args.calc: locations['calc'] = str(args.calc)
        config = directory/'locations.json'
        config.write_text(json.dumps({'version': 1, 'locations': locations}, indent=2)+'\n'); config.chmod(0o600)
    os.environ['SCHEMAXIS_CONFIG'] = str(config); os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    from schemaxis.configuration import locations as configured
    locations = configured()
    report = {'verified': False, 'workflows': [], 'negative': [], 'calc': 'unavailable'}
    try:
        fixtures = subprocess.run([sys.executable, str(ROOT/'tools/qualify_imagej_series_fixtures.py'), '--check'], capture_output=True, text=True, timeout=60)
        assert fixtures.returncode == 0, fixtures.stderr
        receipt = qualify(VERSION, directory/'native', native=True, locations=locations, timeout=120, wall_timeout=args.wall_timeout)
        assert receipt['verified'], receipt
        report['receipt'] = str(directory/'native/qualification.json')
        report['cases'] = [{'id': c['id'], 'runtime': c['runtime'], 'checks': len(c['checks']), 'integrityProbes': len(c['integrity'])} for c in receipt['cases']]
        report['lifecycle'] = receipt['lifecycle']
        lifecycle(directory, locations, report)
        tamper(directory/'native'/CASE, report)
        if locations.get('calc'):
            handoff(directory, locations, report); report['calc'] = 'qualified'
        report['verified'] = True
    finally:
        (directory/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
