#!/usr/bin/env python3
"""Folder-set reuse and invalidation through the real workflow scheduler: ExifTool inspectMetadata over a folder -> Calc readTypedCSV.

Every scenario runs ``workflow.execute(..., resume=True)`` on one workflow directory over one unique private photo folder (created under
``--output-directory``; no shared staging path, so the shared fixture lock is not needed) and states, per job, whether it was reused or re-run, with
the workbook cells of both formats read back independently from literal hand-written rows. Distinguished outcomes:
- unchanged folder: both jobs reused;
- input content changes under the unchanged authored document (same-path bytes, added or removed matching file, rename that changes the item ID and
  order, unrelated file): resume re-runs the producer and, observed here, the consumer too (an unrelated file leaves the CSV bytes identical but still re-runs both);
- a change to the authored document itself (the folder selection limit): resume is refused (RESUME_MISMATCH) and a fresh workflow directory is needed.
Expected cells are written by hand from the fixture specification in tools/author_exiftool_fixtures.py, never read from ExifTool or the adaptor.
Nothing here certifies photo provenance, and no application other than ExifTool and Calc is qualified.
"""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schemaxis import workflow  # noqa: E402
from schemaxis.artifacts import atomic_json  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
import author_exiftool_fixtures as author  # noqa: E402
import qualify_exiftool_workbench as wb  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/exiftool'
COLUMNS = wb.EXPOSURE_COLUMNS
ROW = {'ridge_line': wb.EXPOSURE_ROWS[1], 'harbour_light': wb.EXPOSURE_ROWS[2], 'orchard_gate': wb.EXPOSURE_ROWS[3]}
ABSENT = [None, 'absent'] * 6


def row_for(identifier, source):
    """The literal row for an item ID whose bytes are those of fixture ``source`` (hand-written table above, exposure of conflict-desk is absent)."""
    if source == 'conflict_desk':
        return [identifier, *ABSENT]
    return [identifier, *ROW[source][1:]]


def summary_for(rows):
    count = len(rows)
    lines = []
    for label, column in wb.NUMBER_COLUMNS.items():
        index = COLUMNS.index(label)
        values = [r[index] for r in rows if r[index] is not None]
        lines.append([label, len(values), math.fsum(values), statistics.fmean(values), min(values), max(values), statistics.stdev(values), count - len(values), column])
    return lines


def attempt_of(result, operation):
    job = next(j for j in result['jobs'] if j['operation'] == operation)
    return Path(job['directory']), bool(job.get('reused'))


def check(result, rows, report, label):
    """Producer bytes handed to Calc exactly, and every Data and Summary cell of both workbooks against the hand-written rows."""
    producer, _ = attempt_of(result, 'exposure')
    consumer, _ = attempt_of(result, 'workbook')
    csv_bytes = (producer / 'profile-exposure.csv').read_bytes()
    assert (consumer / 'source.csv').read_bytes() == csv_bytes, label + ': consumer captured bytes differ from the producer artifact'
    table = [COLUMNS] + rows
    checked = wb.check_both_formats(consumer, table, summary_for(rows))
    cells = checked['cells']
    manifest = json.loads((producer / 'manifest.json').read_text())
    report['scenarios'][label].update(cellsCheckedIndependently=cells, cellsPerFormat=checked['perFormat'], rows=[r[0] for r in rows], manifest={'status': manifest['status'], 'items': manifest['counts']['items'], 'excluded': manifest['counts']['excluded']})
    return csv_bytes


def reused(result):
    return {j['operation']: bool(j.get('reused')) for j in result['jobs']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exiftool', type=Path, required=True)
    parser.add_argument('--calc', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    out = args.output_directory.resolve()
    out.mkdir(parents=True, exist_ok=False)
    locations = {'exiftool': str(args.exiftool.resolve()), 'calc': str(args.calc.resolve())}
    photos = out / 'private' / 'exposure-folder'
    photos.mkdir(parents=True)
    for name in ('ridge-line.jpg', 'harbour-light.jpg', 'orchard-gate.jpg'):
        shutil.copyfile(FIXTURES / name, photos / name)
    graph = json.loads((ROOT / 'examples/schemaxis/exiftool-exposure-folder-calc-workflow.json').read_text())
    graph['operations'][0]['document']['media']['folder']['path'] = str(photos)
    report = {'scope': __doc__.split('\n\n')[0], 'scenarios': {}, 'verified': False, 'startedAt': time.time()}
    target = out / 'workflow'

    def scenario(label, resume=True, note=None):
        report['scenarios'][label] = {'note': note} if note else {}
        result = workflow.execute(graph, target, locations=locations, timeout=300, resume=resume) if resume else workflow.execute(graph, target, locations=locations, timeout=300)
        assert workflow.verify(target)['verified'], label
        report['scenarios'][label]['reused'] = reused(result)
        return result
    try:
        # fresh workflow: three photos, byte-order of the file names is harbour-light, orchard-gate, ridge-line
        rows = [row_for('harbour_light', 'harbour_light'), row_for('orchard_gate', 'orchard_gate'), row_for('ridge_line', 'ridge_line')]
        result = scenario('fresh', resume=False)
        first = check(result, rows, report, 'fresh')
        assert reused(result) == {'exposure': False, 'workbook': False}
        # unchanged folder: resume reuses both
        result = scenario('resume-unchanged')
        assert reused(result) == {'exposure': True, 'workbook': True}, reused(result)
        assert check(result, rows, report, 'resume-unchanged') == first
        # same-path bytes change: harbour-light.jpg now holds the orchard-gate photograph
        shutil.copyfile(FIXTURES / 'orchard-gate.jpg', photos / 'harbour-light.jpg')
        rows = [row_for('harbour_light', 'orchard_gate'), row_for('orchard_gate', 'orchard_gate'), row_for('ridge_line', 'ridge_line')]
        result = scenario('same-path-bytes-changed')
        assert reused(result) == {'exposure': False, 'workbook': False}, reused(result)
        assert check(result, rows, report, 'same-path-bytes-changed') != first
        again = scenario('resume-after-change')
        assert reused(again) == {'exposure': True, 'workbook': True}, reused(again)
        # a matching file is added (exposure fields absent in conflict-desk.jpg; it sorts first)
        shutil.copyfile(FIXTURES / 'conflict-desk.jpg', photos / 'conflict-desk.jpg')
        rows = [row_for('conflict_desk', 'conflict_desk')] + rows
        result = scenario('matching-file-added')
        assert reused(result) == {'exposure': False, 'workbook': False}, reused(result)
        check(result, rows, report, 'matching-file-added')
        # an unrelated file is added: the folder manifest changed, so the producer re-runs and publishes identical bytes; the consumer is handed the new attempt's
        # artifact and re-runs too (conservative: no reuse is claimed beyond what is observed)
        before = (attempt_of(result, 'exposure')[0] / 'profile-exposure.csv').read_bytes()
        (photos / 'notes.txt').write_bytes(b'not metadata')
        result = scenario('unrelated-file-added', note='manifest digest changes; published CSV bytes do not; the consumer still re-runs because its handed artifact is a new attempt')
        assert reused(result) == {'exposure': False, 'workbook': False}, reused(result)
        assert check(result, rows, report, 'unrelated-file-added') == before
        # a matching file is removed
        (photos / 'conflict-desk.jpg').unlink()
        rows = rows[1:]
        result = scenario('matching-file-removed')
        assert reused(result) == {'exposure': False, 'workbook': False}, reused(result)
        check(result, rows, report, 'matching-file-removed')
        # rename that changes the item ID and the byte order: same bytes, different table
        os.rename(photos / 'orchard-gate.jpg', photos / 'aa-orchard.jpg')
        rows = [row_for('aa_orchard', 'orchard_gate'), rows[0], rows[2]]
        result = scenario('renamed-changes-id-and-order')
        assert reused(result) == {'exposure': False, 'workbook': False}, reused(result)
        check(result, rows, report, 'renamed-changes-id-and-order')
        # the authored document changes (a selection limit): resume is refused with the framework's exact fault, and a fresh workflow directory runs it
        changed = copy.deepcopy(graph)
        changed['operations'][0]['document']['media']['folder']['maxItems'] = 2
        try:
            workflow.execute(changed, target, locations=locations, timeout=300, resume=True)
            raise AssertionError('resume with a changed authored workflow must be refused')
        except SchemaxisError as error:
            assert error.fault.code == 'RESUME_MISMATCH' and error.fault.location == str(target), error.fault.to_dict()
            report['scenarios']['document-changed-resume-refused'] = {'fault': error.fault.code, 'location': 'the workflow directory'}
        fresh = out / 'workflow-limited'
        result = workflow.execute(changed, fresh, locations=locations, timeout=300)
        assert workflow.verify(fresh)['verified'] and reused(result) == {'exposure': False, 'workbook': False}
        limited = [rows[0], rows[1]]  # byte order: aa-orchard.jpg, harbour-light.jpg; ridge-line.jpg exceeds maxItems 2
        producer, _ = attempt_of(result, 'exposure')
        manifest = json.loads((producer / 'manifest.json').read_text())
        assert manifest['status'] == 'partial' and [(e['path'], e.get('reason')) for e in manifest['entries'] if not e['included'] and e['reason'] != 'extension'] == [('ridge-line.jpg', 'count-limit')], manifest['entries']
        checked = wb.check_both_formats(attempt_of(result, 'workbook')[0], [COLUMNS] + limited, summary_for(limited))
        report['scenarios']['fresh-after-document-change'] = {'rows': [r[0] for r in limited], 'cellsCheckedIndependently': checked['cells'], 'cellsPerFormat': checked['perFormat'], 'manifestStatus': 'partial', 'excluded': 'ridge-line.jpg count-limit'}
        report['verified'] = True
    finally:
        report['finishedAt'] = time.time()
        atomic_json(out / 'acceptance.json', report)
    print(json.dumps({k: v for k, v in report['scenarios'].items()}, indent=1)[:3500])


if __name__ == '__main__':
    main()
