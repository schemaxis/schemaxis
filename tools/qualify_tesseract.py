#!/usr/bin/env python3
"""Native Tesseract qualification with independent literal expectations, controls, hostile evidence and a producer handoff.

Scope: one synthetic page fixture (DejaVu Sans Bold, committed), the pinned English fast model and Tesseract 5.5.3. Literal words
come from fixture authoring and their ink boxes from pixel measurement (tools/qualify_tesseract_fixtures.py), never from OCR. A
second native pass shows deterministic readback only. Nothing here certifies recognition accuracy, other fonts, languages or layouts.
A MuPDF page handoff runs only when a MuPDF runtime is configured (--mupdf); otherwise it is reported unavailable, never skipped as success.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import time

from schemaxis import workflow
from schemaxis.adaptor_conformance import qualify
from schemaxis.adaptors.tesseract import adaptor as a
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from qualify_tesseract_fixtures import blank, interlaced_flag, measure, rgba_from

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/tesseract'
STAGING = Path('/tmp/schemaxis-tesseract-acceptance')
MODEL_SHA256 = '7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2'
HORIZONTAL_TOLERANCE = 3
VERTICAL_TOLERANCE = 5
OWNED = {}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''): digest.update(block)
    return digest.hexdigest()


def remember(path):
    info = path.lstat();OWNED[path] = (info.st_dev, info.st_ino)


def stage(model, extra):
    """Exclusively own the fixed example paths; never replace pre-existing data."""
    try: STAGING.mkdir(mode=0o700)
    except FileExistsError: raise SystemExit(f'refusing pre-existing staging path {STAGING}; inspect and remove its stale contents yourself')
    info = STAGING.lstat();OWNED[STAGING] = (info.st_dev, info.st_ino)
    try:
        for name in ('baseline.png', 'changed.png', 'single-line.png'):
            with (STAGING / name).open('xb') as target, (FIXTURES / name).open('rb') as source: shutil.copyfileobj(source, target)
            remember(STAGING / name)
        (STAGING / 'eng.traineddata').symlink_to(Path(model).resolve());remember(STAGING / 'eng.traineddata')
        for name, data in extra.items():
            (STAGING / name).write_bytes(data);remember(STAGING / name)
    except BaseException:
        unstage();raise


def unstage():
    for path, identity in list(OWNED.items()):
        if path == STAGING: continue
        try:
            info = path.lstat()
            if (info.st_dev, info.st_ino) == identity: path.unlink()
        except FileNotFoundError: pass
    try: STAGING.rmdir()
    except OSError: pass


def refused(action, code):
    try: action()
    except SchemaxisError as error:
        assert error.fault.code == code, error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('invalid OCR input/evidence accepted: ' + code)


def document(image, model, **kw):
    return {'version': 'schemaxis.tesseract/1', 'operation': 'recognizePage', 'image': {'path': str(image)}, 'model': {'path': str(model), 'sha256': MODEL_SHA256}, **kw}


def independent_tsv(path, width, height):
    """A second, deliberately simple TSV reader (no code shared with the adaptor): returns word tuples and checks hierarchy by counting."""
    rows = [line.split('\t') for line in Path(path).read_text(encoding='utf-8').split('\n')[:-1]]
    assert rows[0] == 'level page_num block_num par_num line_num word_num left top width height conf text'.split()
    assert all(len(r) == 12 for r in rows) and [int(c) for c in rows[1][:6]] == [1, 1, 0, 0, 0, 0] and [int(c) for c in rows[1][6:10]] == [0, 0, width, height]
    levels = [int(r[0]) for r in rows[1:]]
    assert levels[0] == 1 and set(levels) <= {1, 2, 3, 4, 5} and levels.count(1) == 1
    words = []
    for r in rows[2:]:
        level, box, conf, text = int(r[0]), tuple(int(c) for c in r[6:10]), r[10], r[11]
        assert box[2] > 0 and box[3] > 0 and box[0] + box[2] <= width and box[1] + box[3] <= height
        if level == 5:
            assert 0 <= float(conf) <= 100 and text == text.strip() and text
            words.append((text, box, float(conf)))
        else: assert conf == '-1' and text == ''
    return words


def check_page(directory, fixture, expected_lines, report, name):
    """Literal words/lines plus ink-measured geometry for a fixture page, reading published and native files directly."""
    directory = Path(directory);ink = measure((FIXTURES / fixture).read_bytes())
    words = json.loads((directory / 'words.json').read_text())
    text = (directory / 'page.txt').read_text()
    assert text == ''.join(line + '\n' for line in expected_lines), (name, text)
    literal = [w for line in expected_lines for w in line.split(' ')]
    assert [w['text'] for w in words['words']] == literal, (name, [w['text'] for w in words['words']])
    native = independent_tsv(directory / 'native.tsv', ink['width'], ink['height'])
    assert [(w[0]) for w in native] == literal and [w[2] for w in native] == [w['confidence'] for w in words['words']]
    assert words['page'] == {'width': ink['width'], 'height': ink['height']}
    index = 0;worst = 0
    for (top, bottom, spans), line in zip(ink['lines'], expected_lines):
        assert len(spans) == len(line.split(' ')), (name, spans)
        for left, right in spans:
            box = words['words'][index]['box']
            horizontal = (abs(box['left'] - left), abs(box['left'] + box['width'] - 1 - right))
            vertical = (abs(box['top'] - top), abs(box['top'] + box['height'] - 1 - bottom))
            assert max(horizontal) <= HORIZONTAL_TOLERANCE and max(vertical) <= VERTICAL_TOLERANCE, (name, index, box, left, right, top, bottom)
            worst = max(worst, *horizontal, *vertical)
            index += 1
    report['cases'][name] = {'literalWords': literal, 'inkBoxToleranceHorizontalPx': HORIZONTAL_TOLERANCE, 'inkBoxToleranceVerticalPx': VERTICAL_TOLERANCE, 'inkBoxMaxObservedErrorPx': worst, 'confidences': [w['confidence'] for w in words['words']]}


def hostile(directory, report):
    """Tamper every evidence class on a real native run; each mutation must fail verification and be restored."""
    directory = Path(directory);saved = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()};done = []
    def restore():
        for path in list(directory.rglob('*')):
            if path.is_symlink() or (path.is_file() and path not in saved): path.unlink()
        for path, data in saved.items(): path.write_bytes(data)
    def json_edit(name, change):
        def apply():
            data = json.loads((directory / name).read_text());change(data);atomic_json(directory / name, data)
        return apply
    def refresh():
        receipt = json.loads((directory / 'verification.json').read_text())
        receipt['evidence'] = {n: a.digest(directory, n, a.evidence_limit(n)) for n in receipt['evidence']};receipt['artifacts'] = a.artifacts(directory)
        atomic_json(directory / 'verification.json', receipt)
    tsv = directory / 'native.tsv';text = tsv.read_text()
    mutations = {
        'forged-box': json_edit('words.json', lambda d: d['words'][0]['box'].update(left=47)),
        'forged-confidence': json_edit('words.json', lambda d: d['words'][0].update(confidence=100.0)),
        'forged-word': json_edit('words.json', lambda d: d['words'][1].update(text='4097')),
        'forged-text': lambda: (directory / 'page.txt').write_text('NORTH 4097\nRIVER 1357\n'),
        'native-header': lambda: tsv.write_text(text.replace('level', 'lvl', 1)),
        'native-extra-row': lambda: tsv.write_text(text + '5\t1\t1\t1\t2\t3\t300\t150\t10\t10\t90\tEXTRA\n'),
        'native-box-outside': lambda: tsv.write_text(text.replace('\t210\t43\t', '\t9999\t43\t')),
        'native-confidence-range': lambda: tsv.write_text(text.replace('96.', '196.', 1)),
        'native-word': lambda: tsv.write_text(text.replace('NORTH', 'SOUTH')),
        'native-text-drift': lambda: (directory / 'native.txt').write_text('NORTH 4097\nRIVER 1357\n'),
        'stale-source': lambda: shutil.copy(FIXTURES / 'changed.png', directory / 'captured-page.png'),
        'stale-model': lambda: (directory / 'tessdata/eng.traineddata').write_bytes(b'stale model'),
        'forged-runtime-claim': json_edit('verification.json', lambda d: d.update(runtime='tesseract 6.0.0')),
        'forged-executable': json_edit('runtime.json', lambda d: d.update(executable='/forged/tesseract')),
        'forged-filename': lambda: (directory / 'page.txt').rename(directory / 'page.txt.bak'),
        'extra-file': lambda: (directory / 'extra.tsv').write_text('x'),
        'missing-output': lambda: (directory / 'native.tsv').unlink(),
    }
    refreshed = {'forged-box', 'forged-confidence', 'forged-word', 'forged-text', 'native-header', 'native-extra-row', 'native-box-outside', 'native-confidence-range', 'native-word', 'native-text-drift'}
    for name, mutate in mutations.items():
        mutate()
        if name in refreshed:
            try: refresh()
            except SchemaxisError: pass
        refused(lambda: a.verify(directory), 'VERIFICATION_FAILED');restore();done.append(name)
    assert a.verify(directory)['verified']
    report['hostile'] = done
    report['hostileDigestRefreshed'] = [n for n in done if n in refreshed]
    report['hostileNotRefreshed'] = [n for n in done if n not in refreshed]


def count_launches(action):
    """Run an action while any attempt to start a process raises, proving offline verification launches no native code."""
    import subprocess
    original = subprocess.Popen
    def forbidden(*args, **kwargs): raise AssertionError('native process launched during offline verification')
    subprocess.Popen = forbidden
    try: return action()
    finally: subprocess.Popen = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tesseract', type=Path, required=True);parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--gnuplot', type=Path, help='real chart producer for the handoff');parser.add_argument('--mupdf', type=Path, help='qualified MuPDF 1.28.5 mutool for the page handoff')
    parser.add_argument('--conform', action='store_true', help='also run shared native conformance')
    args = parser.parse_args()
    out = args.output_directory.resolve()
    if out.exists(): raise SystemExit('select a fresh output directory')
    out.mkdir(parents=True)
    exe = args.tesseract.resolve()
    assert sha256(args.model) == MODEL_SHA256, 'model is not the pinned eng fast model'
    baseline = FIXTURES / 'baseline.png'
    image = a.admit_image(baseline.read_bytes());other = a.admit_image((FIXTURES / 'changed.png').read_bytes())
    def summary_for(info, page, pdf_sha):
        return json.dumps({'sourceSha256': pdf_sha, 'pageCount': 2, 'dpi': 72, 'rotation': 0, 'pages': [{'page': page, 'width': info['width'], 'height': info['height'], 'rgbSha256': info['rgbSha256']}]}).encode()
    extra = {'baseline-summary.json': summary_for(image, 1, 'c' * 64), 'changed-summary.json': summary_for(other, 1, 'c' * 64)}
    report = {'scope': __doc__.split('\n\n')[0], 'cases': {}, 'controls': {}, 'verified': False, 'startedAt': time.time()}
    stage(args.model, extra)
    try:
        model = STAGING / 'eng.traineddata'
        def run(name, doc, **kw): return a.run(doc, out / name, executable=str(exe), timeout=kw.pop('timeout', 120), **kw)
        report['runtime'] = {'executable': str(exe.name), 'executableSha256': sha256(exe), 'modelSha256': MODEL_SHA256}
        run('baseline', document(STAGING / 'baseline.png', model, dpi=200))
        check_page(out / 'baseline', 'baseline.png', ['NORTH 4096', 'RIVER 1357'], report, 'baseline')
        run('changed', document(STAGING / 'changed.png', model, dpi=200))
        check_page(out / 'changed', 'changed.png', ['NORTH 4096', 'RIVER 2468'], report, 'changed-word')
        assert (out / 'baseline/page.txt').read_text() != (out / 'changed/page.txt').read_text()
        run('single-line', document(STAGING / 'single-line.png', model, dpi=200, pageSegmentation='single-line'))
        check_page(out / 'single-line', 'single-line.png', ['NORTH 4096'], report, 'single-line-segmentation')
        assert json.loads((out / 'single-line/ocr-summary.json').read_text())['settings']['psm'] == 7
        # controls: explicit segmentation, blank, density and unsupported-image refusals; every failed attempt is retained unmodified
        controls = report['controls']
        controls['single-line-on-two-line-page'] = refused(lambda: run('two-line-single-line', document(STAGING / 'baseline.png', model, dpi=200, pageSegmentation='single-line')), 'OCR_NO_TEXT')
        (STAGING / 'blank.png').write_bytes(blank());remember(STAGING / 'blank.png')
        controls['blank-page'] = refused(lambda: run('blank', document(STAGING / 'blank.png', model, dpi=200)), 'OCR_NO_TEXT')
        run('dpi-300', document(STAGING / 'baseline.png', model, dpi=300))
        dpi_plan = json.loads((out / 'dpi-300/plan.json').read_text())
        assert dpi_plan['dpi'] == 300 and json.loads((out / 'baseline/plan.json').read_text())['dpi'] == 200
        assert '300' in json.loads((out / 'dpi-300/recognize-submission.json').read_text())['nativeCommand'][1] or "'--dpi', '300'" in (out / 'dpi-300/recognize-launcher.py').read_text()
        controls['dpi-300'] = {'planRecordsDpi': 300, 'recognizedText': (out / 'dpi-300/page.txt').read_text(), 'note': 'text is observed, not asserted: density is a hint, not an accuracy guarantee'}
        (STAGING / 'alpha.png').write_bytes(rgba_from((FIXTURES / 'baseline.png').read_bytes()));remember(STAGING / 'alpha.png')
        (STAGING / 'interlaced.png').write_bytes(interlaced_flag((FIXTURES / 'baseline.png').read_bytes()));remember(STAGING / 'interlaced.png')
        controls['alpha-png'] = refused(lambda: run('alpha', document(STAGING / 'alpha.png', model)), 'UNSUPPORTED_IMAGE')
        controls['interlaced-png'] = refused(lambda: run('interlaced', document(STAGING / 'interlaced.png', model)), 'UNSUPPORTED_IMAGE')
        controls['wrong-model-pin'] = refused(lambda: run('wrong-pin', {**document(STAGING / 'baseline.png', model), 'model': {'path': str(model), 'sha256': '0' * 64}}), 'MODEL_HASH_MISMATCH')
        controls['missing-source'] = refused(lambda: run('missing-source', document(STAGING / 'none.png', model)), 'INVALID_IMAGE_SOURCE')
        controls['missing-model'] = refused(lambda: run('missing-model', document(STAGING / 'baseline.png', STAGING / 'none.traineddata')), 'INVALID_MODEL')
        controls['missing-runtime'] = refused(lambda: a.run(document(STAGING / 'baseline.png', model), out / 'missing-runtime', executable='/nonexistent/tesseract'), 'INTERPRETER_NOT_FOUND')
        # origin: hand-built summaries (not MuPDF output) exercise the pixel binding natively; a summary for different pixels is refused
        run('origin', document(STAGING / 'baseline.png', model, dpi=200, origin={'kind': 'mupdf-review', 'summary': str(STAGING / 'baseline-summary.json'), 'page': 1}))
        origin = json.loads((out / 'origin/ocr-summary.json').read_text())['origin']
        assert origin['state'] == 'declared-bound-to-pixels' and origin['pdfSha256'] == 'c' * 64 and origin['page'] == 1
        controls['origin-wrong-pixels'] = refused(lambda: run('origin-mismatch', document(STAGING / 'baseline.png', model, dpi=200, origin={'kind': 'mupdf-review', 'summary': str(STAGING / 'changed-summary.json'), 'page': 1})), 'ORIGIN_MISMATCH')
        report['origin'] = {'note': 'summaries are hand-built fixtures, not MuPDF output', 'state': origin['state']}
        # deterministic readback: a fresh second native pass; this shows repeatability, not independent OCR truth
        run('baseline-second', document(STAGING / 'baseline.png', model, dpi=200))
        for name in ('page.txt', 'words.json', 'native.tsv'):
            assert (out / 'baseline' / name).read_bytes() == (out / 'baseline-second' / name).read_bytes(), name
        report['determinism'] = {'secondNativePassIdentical': ['page.txt', 'words.json', 'native.tsv'], 'scope': 'repeatability on this host, not independent OCR truth'}
        count_launches(lambda: a.verify(out / 'baseline'));report['offlineVerificationLaunchedNothing'] = True
        hostile(out / 'baseline', report)
        # lifecycle with the real process-tree runner
        cancel = {'requested': False}
        controls['timeout'] = refused(lambda: run('timeout', document(STAGING / 'baseline.png', model), timeout=0.2), 'RUNNER_TIMED_OUT')
        from unittest.mock import patch
        with patch.object(a, 'cancellation_requested', return_value=True):
            controls['cancelled-before-launch'] = refused(lambda: run('cancelled', document(STAGING / 'baseline.png', model)), 'RUNNER_CANCELLED')
        # workflow reuse and invalidation with the real scheduler
        graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'ocr', 'document': document(STAGING / 'baseline.png', model, dpi=200)}]}
        locations = {'tesseract': str(exe)}
        first = workflow.execute(graph, out / 'workflow', locations=locations, timeout=120);assert workflow.verify(out / 'workflow')['verified']
        resumed = workflow.execute(graph, out / 'workflow', locations=locations, timeout=120, resume=True);assert resumed['jobs'][0]['reused']
        (STAGING / 'baseline.png').write_bytes((FIXTURES / 'changed.png').read_bytes())
        changed = workflow.execute(graph, out / 'workflow', locations=locations, timeout=120, resume=True);assert not changed['jobs'][0]['reused'] and workflow.verify(out / 'workflow')['verified']
        (STAGING / 'baseline.png').write_bytes((FIXTURES / 'baseline.png').read_bytes())
        report['workflow'] = {'reuse': 'image digest unchanged: reused', 'invalidation': 'same-path image bytes changed: re-executed'}
        # true producer handoff
        report['handoff'] = {}
        if args.gnuplot:
            handoff_gnuplot(out, exe, model, args.gnuplot, report)
        else: report['handoff']['gnuplot'] = {'status': 'unavailable', 'reason': 'no --gnuplot executable supplied'}
        if args.mupdf:
            handoff_mupdf(out, exe, model, args.mupdf, report)
        else: report['handoff']['mupdf'] = {'status': 'unavailable', 'reason': 'no qualified MuPDF 1.28.5 mutool supplied (--mupdf); not run, not qualified'}
        if args.conform:
            qualify(a.VERSION, out / 'kit', native=True, root=ROOT, locations=locations, timeout=120, wall_timeout=240)
            receipt = json.loads((out / 'kit/qualification.json').read_text())
            assert receipt['verified'] is True and receipt['mode'] == 'native', 'shared native conformance receipt did not verify'
            report['conformance'] = {'verified': receipt['verified'], 'mode': receipt['mode'], 'receipt': 'kit/qualification.json (written by the shared conformance kit; not recorded)',
                                     'cases': [c.get('id') or c.get('name') for c in receipt['cases']] if all(isinstance(c, dict) for c in receipt['cases']) else receipt['cases']}
        report['verified'] = True
    finally:
        report['finishedAt'] = time.time();atomic_json(out / 'acceptance.json', report);unstage()
    print(json.dumps(report, ensure_ascii=False, indent=2))


def handoff_gnuplot(out, exe, model, gnuplot, report):
    """A real verified chart producer feeds OCR: the title is authored text, its position measured from the chart pixels."""
    csv = out / 'handoff-calibration.csv';csv.write_text('time,reading,uncertainty\n0,1,0.1\n1,2,0.1\n2,3,0.2\n')
    chart = json.loads((ROOT / 'examples/schemaxis/gnuplot-calibration.json').read_text());chart.update(source=str(csv), title='NORTH 4096')
    ocr = document('/unused', model, dpi=150);ocr['image'] = {'path': {'$artifact': 'chart', 'index': 1}}
    graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'chart', 'document': chart}, {'id': 'ocr', 'document': ocr}]}
    result = workflow.execute(graph, out / 'handoff-gnuplot', locations={'tesseract': str(exe), 'gnuplot': str(gnuplot.resolve())}, timeout=180)
    assert workflow.verify(out / 'handoff-gnuplot')['verified']
    producer = next(p for p in (out / 'handoff-gnuplot').rglob('plot.png'))
    consumer = producer.parents[1] / 'ocr' if (producer.parents[1] / 'ocr').is_dir() else next(p.parent for p in (out / 'handoff-gnuplot').rglob('ocr-summary.json'))
    words = json.loads((consumer / 'words.json').read_text());summary = json.loads((consumer / 'ocr-summary.json').read_text())
    captured = a.admit_image((consumer / 'captured-page.png').read_bytes())
    assert captured['sha256'] == hashlib.sha256(producer.read_bytes()).hexdigest(), 'consumer did not receive the producer PNG bytes'
    assert [w['text'] for w in words['words'][:2]] == ['NORTH', '4096']
    ink = measure(producer.read_bytes());top, bottom, spans = ink['lines'][0]
    title = words['words'][0]['box']
    assert abs(title['top'] - top) <= 6 and title['top'] + title['height'] <= ink['height'] * 0.15 and abs((words['words'][0]['box']['left'] + words['words'][1]['box']['left'] + words['words'][1]['box']['width']) / 2 - ink['width'] / 2) <= 40
    assert summary['origin']['state'] == 'unknown' and not summary['review']['ocrTruthCertified']
    report['handoff']['gnuplot'] = {'status': 'verified', 'producer': 'gnuplot adaptor plot.png (artifact index 1)', 'workflowStatus': result.get('status'), 'titleWords': ['NORTH', '4096'],
        'note': 'other chart text (ticks, labels) is recognized noisily and is not asserted; origin is unknown for a non-MuPDF producer'}


def handoff_mupdf(out, exe, model, mutool, report):
    graph = json.loads((ROOT / 'examples/schemaxis/tesseract-mupdf-workflow.json').read_text())
    shutil.copy(FIXTURES / 'scanned.pdf', out / 'scanned.pdf')
    graph['operations'][0]['document']['source'] = str(out / 'scanned.pdf')
    graph['operations'][1]['document']['model'] = {'path': str(model), 'sha256': MODEL_SHA256}
    result = workflow.execute(graph, out / 'handoff-mupdf', locations={'tesseract': str(exe), 'mupdf': str(mutool.resolve())}, timeout=180)
    assert workflow.verify(out / 'handoff-mupdf')['verified']
    consumer = next(p.parent for p in (out / 'handoff-mupdf').rglob('ocr-summary.json'))
    assert (consumer / 'page.txt').read_text() == 'NORTH 4096\nRIVER 2468\n'
    origin = json.loads((consumer / 'ocr-summary.json').read_text())['origin']
    assert origin['state'] == 'declared-bound-to-pixels' and origin['page'] == 2 and origin['pdfSha256'] == hashlib.sha256((FIXTURES / 'scanned.pdf').read_bytes()).hexdigest()
    report['handoff']['mupdf'] = {'status': 'verified', 'workflowStatus': result.get('status'), 'page': 2, 'originState': origin['state']}


if __name__ == '__main__':
    main()
