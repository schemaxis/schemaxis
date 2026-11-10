#!/usr/bin/env python3
"""Bounded native acceptance of the Pandoc transcript timeFormat: literal HTML, DOCX and readback, mixed blocks, forged claims.

Runs the real Pandoc against the retained whisper.cpp fixture and a Unicode source; it never registers a qualification receipt
and never writes into a retained run passed with --genuine-run (those are only re-verified, then compared byte for byte).
"""
import argparse
import copy
import hashlib
import html
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qualify_pandoc import literal_docx_table, literal_html_table, literal_readback_table, refresh, refused, tree_digests, W  # noqa: E402
from schemaxis import workflow  # noqa: E402
from schemaxis.adaptors.pandoc import adaptor  # noqa: E402
from schemaxis.artifacts import atomic_json  # noqa: E402
from schemaxis.core import timed_text  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'examples/schemaxis/fixtures/pandoc/segments-jfk-short.json'
# Independent literals, written here and not derived from the adaptor: the retained whisper.cpp fixture's digests and cues.
SOURCE_SHA, AUDIO_SHA, MODEL_SHA = ('0fb466aec743b3a236655d7b29e4d3a1003bcd5230abcd4276af56b08cb4ba04',
                                    '59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e',
                                    'a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002')
TEXTS = ['And so my fellow Americans, ask not what', 'your country can do for you, ask what you', 'can do for your country.']
MS_HEADER = ['Start (ms)', 'End (ms)', 'Text']
MS_ROWS = [['0', '5410', TEXTS[0]], ['5410', '9040', TEXTS[1]], ['9040', '11000', TEXTS[2]]]
TC_HEADER = ['Start (HH:MM:SS.mmm)', 'End (HH:MM:SS.mmm)', 'Text']
TC_ROWS = [['00:00:00.000', '00:00:05.410', TEXTS[0]], ['00:00:05.410', '00:00:09.040', TEXTS[1]], ['00:00:09.040', '00:00:11.000', TEXTS[2]]]
# A Unicode source with hour and hundred-hour times; cue text is written here, times are the integers on the left.
UNICODE_CUES = [(0, 999, 'שלום עולם‏'), (999, 1000, 'می‌خواهم'), (1000, 59999, '你好，世界。'), (59999, 60000, 'Café déjà vu & grüße'),
                (3599999, 3600000, 'Ελληνικά — 日本語'), (3600000, 3600001, 'ภาษา​ไทย'), (359999999, 360000000, 'Hundred hours in')]
UNICODE_TC = [['00:00:00.000', '00:00:00.999'], ['00:00:00.999', '00:00:01.000'], ['00:00:01.000', '00:00:59.999'], ['00:00:59.999', '00:01:00.000'],
              ['00:59:59.999', '01:00:00.000'], ['01:00:00.000', '01:00:00.001'], ['99:59:59.999', '100:00:00.000']]
UNICODE_MS = [['0', '999'], ['999', '1000'], ['1000', '59999'], ['59999', '60000'], ['3599999', '3600000'], ['3600000', '3600001'], ['359999999', '360000000']]


def transcript(path, fmt=None, pin=True):
    segments = {'path': str(path), **({'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()} if pin else {})}
    return {'kind': 'transcript', 'segments': segments, **({'timeFormat': fmt} if fmt else {})}


def report_of(title, *blocks):
    return {'version': adaptor.VERSION, 'operation': 'report', 'title': title,
            'sections': [{'heading': f'Part {i + 1}', 'level': 1, 'content': [b]} for i, b in enumerate(blocks)]}


def unicode_source(directory):
    value = {'version': 'schemaxis.whispercpp.segments/1', 'language': 'en', 'timeUnit': 'millisecond',
             'audio': {'sha256': 'a' * 64, 'bytes': 1, 'frames': 16000 * 360000, 'rate': 16000, 'channels': 1, 'durationMs': 360000000, 'durationRemainderFrames': 0},
             'model': {'sha256': 'b' * 64, 'bytes': 1}, 'nativeJsonSha256': 'c' * 64, 'segmentCount': len(UNICODE_CUES),
             'segments': [{'index': i, 'startMs': s, 'endMs': e, 'text': t} for i, (s, e, t) in enumerate(UNICODE_CUES)],
             'review': {'accuracyCertified': False, 'humanReviewRequired': True, 'statement': 'Review before use.',
                        'policy': {'timing': 'integral milliseconds', 'text': 'UTF-8 plain text'}}}
    path = directory / 'unicode-segments.json'; path.write_bytes(timed_text.canonical_json(value)); return path


def tables(run):
    """(html, docx, readback) tables of a retained run as (header, rows) lists, each in document order, from independent readers."""
    page = (run / 'report.html').read_text(encoding='utf-8')
    found = []
    import re
    for head, body in re.findall(r'<thead>(.*?)</thead>\s*<tbody>(.*?)</tbody>', page, re.S):
        cells = lambda text, tag: [[html.unescape(c) for c in re.findall('<%s>(.*?)</%s>' % (tag, tag), row, re.S)] for row in re.findall('<tr>(.*?)</tr>', text, re.S)]
        found.append((cells(head, 'th')[0], cells(body, 'td')))
    with zipfile.ZipFile(run / 'report.docx') as archive: document = ET.fromstring(archive.read('word/document.xml'))
    word = []
    for table in document.findall('.//' + W + 'tbl'):
        rows = [[''.join(t.text or '' for t in cell.iter(W + 't')) for cell in row.findall(W + 'tc')] for row in table.findall(W + 'tr')]
        flags = [row.find(W + 'trPr/' + W + 'tblHeader') is not None for row in table.findall(W + 'tr')]
        assert flags == [True] + [False] * (len(rows) - 1), flags
        word.append((rows[0], rows[1:]))
    def text(items): return ''.join(i['c'] if i['t'] == 'Str' else ' ' for i in items if i['t'] in ('Str', 'Space'))
    back = []
    for block in json.loads((run / 'reopened.json').read_text())['blocks']:
        if block['t'] == 'Table':
            row = lambda r: [text(c[4][0]['c']) for c in r[1]]
            back.append((row(block['c'][3][1][0]), [row(r) for b in block['c'][4] for r in b[3]]))
    return found, word, back


def provenance(run):
    page = html.unescape((run / 'report.html').read_text(encoding='utf-8'))
    with zipfile.ZipFile(run / 'report.docx') as archive: word = ''.join(t.text or '' for t in ET.fromstring(archive.read('word/document.xml')).iter(W + 't'))
    def text(items): return ''.join(i['c'] if i['t'] == 'Str' else ' ' for i in items if i['t'] in ('Str', 'Space'))
    back = ' '.join(text(b['c']) for b in json.loads((run / 'reopened.json').read_text())['blocks'] if b['t'] == 'Para')
    return {'html': page, 'docx': word, 'readback': back}


def native(document, directory, locations):
    result = adaptor.run(document, directory, executable=locations['pandoc'], timeout=60)
    assert result['verified'] and adaptor.verify(directory)['verified'], result
    return result


def check_tables(run, expected, label, report):
    found, word, back = tables(run)
    for name, got in (('html', found), ('docx', word), ('readback', back)):
        assert [(h, r) for h, r in got] == expected, (label, name, got)
    report[label] = {'tables': len(expected), 'html': True, 'docx': True, 'readback': True}


def forgeries(run, label, probes, report):
    """Refreshed-hash forgeries; each must be refused as VERIFICATION_FAILED for its intended reason."""
    saved = {p: p.read_bytes() for p in run.rglob('*') if p.is_file()}
    def restore():
        for p in sorted((p for p in run.rglob('*') if p not in saved and not p.is_dir()), key=str, reverse=True): p.unlink()
        for p, data in saved.items(): p.write_bytes(data)
    for name, change, reason in probes:
        try:
            change(); refresh(run)
            report[f'{label}:{name}'] = refused(lambda: adaptor.verify(run), reason=reason)['code']
        finally: restore()
    assert adaptor.verify(run)['verified']


def html_edit(run, old, new, count=1):
    def change():
        target = run / 'report.html'; text = target.read_text(encoding='utf-8'); assert old in text, old; target.write_text(text.replace(old, new, count), encoding='utf-8')
    return change


def docx_edit(run, old, new):
    def change():
        target = run / 'report.docx'; buffer = io.BytesIO()
        with zipfile.ZipFile(target) as source, zipfile.ZipFile(buffer, 'w') as out:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == 'word/document.xml': assert old in data, old; data = data.replace(old, new, 1)
                out.writestr(item, data)
        target.write_bytes(buffer.getvalue())
        inputs = adaptor.read(run, 'reopen-inputs.json'); inputs[str(target)] = adaptor.digest(run, 'report.docx'); atomic_json(run / 'reopen-inputs.json', inputs)
    return change


def json_edit(run, name, mutate):
    def change(): value = adaptor.read(run, name); mutate(value); atomic_json(run / name, value)
    return change


def claim_flip(run, mapping):
    """Rewrite the claimed format everywhere a forger who refreshes receipt hashes could (authored, plan, captures), leaving the publication."""
    def change():
        authored = adaptor.read(run, 'authored.json')
        for i, section in enumerate(authored['sections']):
            for j, block in enumerate(section['content']):
                if block['kind'] != 'transcript': continue
                if mapping[(i, j)] is None: block.pop('timeFormat', None)
                else: block['timeFormat'] = mapping[(i, j)]
        atomic_json(run / 'authored.json', authored); atomic_json(run / 'plan.json', adaptor.plan(authored, retained=True))
        captures = adaptor.read(run, 'captures.json')
        for (i, j), fmt in mapping.items():
            entry = captures[f'transcript-{i}-{j}.json']
            if fmt is None: entry.pop('timeFormat', None)
            else: entry['timeFormat'] = fmt
        atomic_json(run / 'captures.json', captures)
    return change


def timecode_acceptance(directory, locations, report):
    directory.mkdir(parents=True)
    doc = report_of('Interview transcript, timecodes', transcript(FIXTURE, 'timecode'))
    run = directory / 'timecode'; result = native(doc, run, locations)
    assert result['transcriptTimeFormats'] == ['timecode'] and result['transcripts'] == 1, result
    check_tables(run, [(TC_HEADER, TC_ROWS)], 'literalTimecode', report)
    text = provenance(run)
    for place, found in text.items():
        for literal in ('Status: machine-draft.', 'a person has not reviewed it', 'accuracy is not certified', 'Language en; 3 cues; audio duration 00:00:11.000;',
                        'HH:MM:SS.mmm (hours, minutes, seconds, milliseconds)', SOURCE_SHA, AUDIO_SHA, MODEL_SHA):
            assert literal in found, (place, literal)
        assert 'audio duration 11000 ms' not in found and 'elapsed milliseconds' not in found, place
    summary = adaptor.read(run, 'report-summary.json'); assert summary['transcriptTimeFormats'] == ['timecode'] and summary['losses'][-1] == adaptor.TIMECODE_LOSS
    captured = adaptor.read(run, 'captures.json')['transcript-0-0.json']
    assert captured['timeFormat'] == 'timecode' and captured['sha256'] == SOURCE_SHA and captured['cues'] == 3, captured
    assert json.loads((run / 'result.json').read_text())['transcriptTimeFormats'] == ['timecode']
    probes = [
        ('htmlHeaderLabelMilliseconds', html_edit(run, 'Start (HH:MM:SS.mmm)', 'Start (ms)'), 'semantics differ'),
        ('htmlHeaderLabelSeconds', html_edit(run, 'End (HH:MM:SS.mmm)', 'End (s)'), 'semantics differ'),
        ('htmlTimeValue', html_edit(run, '<td>00:00:05.410</td>', '<td>00:00:05.411</td>'), 'semantics differ'),
        ('htmlTimeAsIntegerMilliseconds', html_edit(run, '<td>00:00:09.040</td>', '<td>9040</td>'), 'semantics differ'),
        ('htmlTimeCommaSeparator', html_edit(run, '<td>00:00:11.000</td>', '<td>00:00:11,000</td>'), 'semantics differ'),
        ('htmlDuration', html_edit(run, 'audio duration 00:00:11.000', 'audio duration 11000 ms'), 'semantics differ'),
        ('htmlUnitSentence', html_edit(run, 'written as HH:MM:SS.mmm (hours, minutes, seconds, milliseconds)', 'in milliseconds'), 'semantics differ'),
        ('docxHeaderLabel', docx_edit(run, b'>Start (HH:MM:SS.mmm)<', b'>Start (ms)<'), 'semantics differ'),
        ('docxTimeValue', docx_edit(run, b'>00:00:05.410<', b'>00:00:05.411<'), 'semantics differ'),
        ('docxTimeAsIntegerMilliseconds', docx_edit(run, b'>00:00:09.040<', b'>9040<'), 'semantics differ'),
        ('docxDuration', docx_edit(run, b'audio duration 00:00:11.000', b'audio duration 11000 ms'), 'semantics differ'),
        ('astTimeValue', json_edit(run, 'report-input.json', lambda v: v.update(blocks=json.loads(json.dumps(v['blocks']).replace('"00:00:05.410"', '"00:00:05.411"')))), 'trusted AST differs'),
        ('claimFlippedAuthoredOnly', json_edit(run, 'authored.json', lambda v: v['sections'][0]['content'][0].update(timeFormat='milliseconds')), 'effective report plan differs'),
        ('claimFlippedAuthoredAndPlanAndCapture', claim_flip(run, {(0, 0): 'milliseconds'}), 'trusted AST differs'),
        ('claimRemovedEverywhere', claim_flip(run, {(0, 0): None}), 'trusted AST differs'),
        ('captureFormatForged', json_edit(run, 'captures.json', lambda v: v['transcript-0-0.json'].update(timeFormat='milliseconds')), 'captured transcript/source binding differs'),
        ('captureFormatRemoved', json_edit(run, 'captures.json', lambda v: v['transcript-0-0.json'].pop('timeFormat')), 'captured transcript/source binding differs'),
        ('summaryFormatsForged', json_edit(run, 'report-summary.json', lambda v: v.update(transcriptTimeFormats=['milliseconds'])), 'report summary differs'),
        ('summaryFormatsRemoved', json_edit(run, 'report-summary.json', lambda v: v.pop('transcriptTimeFormats')), 'report summary differs'),
        ('planCaveatRemoved', json_edit(run, 'plan.json', lambda v: v.update(losses=v['losses'][:-1])), 'effective report plan differs'),
        ('capturedTextChanged', lambda: (run / 'transcript-0-0.json').write_bytes(timed_text.canonical_json({**json.loads((run / 'transcript-0-0.json').read_text()),
            'segments': [{**c, 'text': 'changed words'} if c['index'] == 1 else c for c in json.loads((run / 'transcript-0-0.json').read_text())['segments']]})), 'no longer satisfies the timed-text contract or its pin')]
    forgeries(run, 'timecode', probes, report)


def mixed_acceptance(directory, locations, report):
    doc = report_of('Interview transcript in two time formats', transcript(FIXTURE, 'timecode'), transcript(FIXTURE, 'milliseconds'))
    run = directory / 'mixed'; result = native(doc, run, locations)
    assert result['transcriptTimeFormats'] == ['timecode', 'milliseconds'] and result['transcripts'] == 2 and result['tables'] == 2, result
    check_tables(run, [(TC_HEADER, TC_ROWS), (MS_HEADER, MS_ROWS)], 'literalMixed', report)
    assert adaptor.read(run, 'report-summary.json')['losses'].count(adaptor.TIMECODE_LOSS) == 1
    swapped = {(0, 0): 'milliseconds', (1, 0): 'timecode'}
    forgeries(run, 'mixed', [
        ('claimsSwappedBetweenBlocks', claim_flip(run, swapped), 'trusted AST differs'),
        ('secondBlockClaimedTimecode', claim_flip(run, {(0, 0): 'timecode', (1, 0): 'timecode'}), 'trusted AST differs'),
        ('htmlSecondTableTimecode', html_edit(run, '<td>5410</td>', '<td>00:00:05.410</td>'), 'semantics differ'),
        ('htmlFirstTableMilliseconds', html_edit(run, '<td>00:00:05.410</td>', '<td>5410</td>'), 'semantics differ'),
        ('summaryFormatsSwapped', json_edit(run, 'report-summary.json', lambda v: v.update(transcriptTimeFormats=['milliseconds', 'timecode'])), 'report summary differs')], report)
    mixed_absent = report_of('Absent and timecode', transcript(FIXTURE, None), transcript(FIXTURE, 'timecode'))
    other = directory / 'absent-and-timecode'; result = native(mixed_absent, other, locations)
    assert result['transcriptTimeFormats'] == ['milliseconds', 'timecode'], result
    check_tables(other, [(MS_HEADER, MS_ROWS), (TC_HEADER, TC_ROWS)], 'literalAbsentAndTimecode', report)
    assert 'timeFormat' not in adaptor.read(other, 'captures.json')['transcript-0-0.json'] and 'timeFormat' in adaptor.read(other, 'captures.json')['transcript-1-0.json']


def absent_acceptance(directory, locations, report):
    doc = report_of('Interview transcript, milliseconds as before', transcript(FIXTURE))
    run = directory / 'absent'; result = native(doc, run, locations)
    assert 'transcriptTimeFormats' not in result and result['transcripts'] == 1, result
    check_tables(run, [(MS_HEADER, MS_ROWS)], 'literalAbsentField', report)
    assert 'transcriptTimeFormats' not in adaptor.read(run, 'report-summary.json') and 'timeFormat' not in adaptor.read(run, 'captures.json')['transcript-0-0.json']
    assert 'timeFormat' not in json.dumps(adaptor.read(run, 'plan.json')) and adaptor.read(run, 'plan.json')['losses'][-1] == adaptor.TRANSCRIPT_LOSS
    assert 'audio duration 11000 ms; times are elapsed milliseconds from the start of the recording.' in provenance(run)['html']
    explicit = report_of('Interview transcript, milliseconds explicit', transcript(FIXTURE, 'milliseconds'))
    other = directory / 'explicit-milliseconds'; result = native(explicit, other, locations)
    assert result['transcriptTimeFormats'] == ['milliseconds'], result
    check_tables(other, [(MS_HEADER, MS_ROWS)], 'literalExplicitMilliseconds', report)
    assert (run / 'report.html').read_text().replace('Interview transcript, milliseconds as before', 'T') == (other / 'report.html').read_text().replace('Interview transcript, milliseconds explicit', 'T')
    forgeries(run, 'absent', [
        ('timecodeClaimedForAbsentField', claim_flip(run, {(0, 0): 'timecode'}), 'trusted AST differs'),
        ('explicitMillisecondsRecordAdded', json_edit(run, 'captures.json', lambda v: v['transcript-0-0.json'].update(timeFormat='milliseconds')), 'captured transcript/source binding differs'),
        ('summaryFormatsAdded', json_edit(run, 'report-summary.json', lambda v: v.update(transcriptTimeFormats=['milliseconds'])), 'report summary differs'),
        ('htmlTimeRewrittenAsTimecode', html_edit(run, '<td>5410</td>', '<td>00:00:05.410</td>'), 'semantics differ')], report)


def unicode_acceptance(directory, locations, report):
    path = unicode_source(directory)
    for fmt, header, times, name in (('timecode', TC_HEADER, UNICODE_TC, 'unicode-timecode'), ('milliseconds', MS_HEADER, UNICODE_MS, 'unicode-milliseconds')):
        run = directory / name; native(report_of('Unicode transcript', transcript(path, fmt)), run, locations)
        expected = [(header, [[a, b, c[2]] for (a, b), c in zip(times, UNICODE_CUES)])]
        check_tables(run, expected, 'literal-' + name, report)
        found = tables(run)[0][0][1]; assert [row[2] for row in found] == [c[2] for c in UNICODE_CUES], 'cue text must be the source text exactly'
    # The retained DOCX package is reopened here from its ZIP and XML with the standard library, not Word.
    with zipfile.ZipFile(directory / 'unicode-timecode/report.docx') as archive:
        assert archive.testzip() is None
        body = ''.join(t.text or '' for t in ET.fromstring(archive.read('word/document.xml')).iter(W + 't'))
    for literal in ('99:59:59.999', '100:00:00.000', '01:00:00.001', 'audio duration 100:00:00.000'): assert literal in body, literal


def lifecycle(directory, locations, report):
    for value in (True, 'clock', 1, None):
        block = transcript(FIXTURE); block['timeFormat'] = value; target = directory / f'refused-{type(value).__name__}'
        out = refused(lambda: adaptor.run(report_of('T', block), target, executable=locations['pandoc'], timeout=60), 'INVALID_ARGUMENT')
        assert not target.exists() and out['location'] == '$.sections[0].content[0].timeFormat', out
    source = directory / 'workflow-segments.json'; shutil.copyfile(FIXTURE, source)
    document = report_of('Workflow timecode', transcript(source, 'timecode')); graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'report', 'document': document}]}
    first = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=60); assert workflow.verify(directory / 'workflow')['verified']
    assert workflow.execute(graph, directory / 'workflow', locations=locations, timeout=60, resume=True)['jobs'][0]['reused']
    changed = copy.deepcopy(graph); changed['operations'][0]['document']['sections'][0]['content'][0]['timeFormat'] = 'milliseconds'
    # A changed authored format is a changed workflow: resuming the retained one is refused, and a fresh run publishes the other format.
    try: workflow.execute(changed, directory / 'workflow', locations=locations, timeout=60, resume=True)
    except SchemaxisError as error: resume_fault = error.fault.code; assert 'unchanged authored workflow' in error.fault.message, error.fault.to_dict()
    else: raise AssertionError('a changed timeFormat resumed the retained workflow')
    fresh = workflow.execute(changed, directory / 'workflow-milliseconds', locations=locations, timeout=60); assert workflow.verify(directory / 'workflow-milliseconds')['verified']
    assert workflow.verify(directory / 'workflow')['verified']
    report['lifecycle'] = {'baseline': first['status'], 'unchangedReused': True, 'changedFormatResumeRefused': resume_fault, 'changedFormatFreshRun': fresh['status'],
                           'refusedBeforeNative': ['boolean', 'unknown name', 'integer', 'null']}


def genuine(paths, report):
    """Genuine earlier retained runs: verify in place and require every byte unchanged; never a rewrite."""
    out = {}
    for path in paths:
        path = Path(path).resolve(); before = tree_digests(path)
        result = adaptor.verify(path); assert result['verified'], result
        assert tree_digests(path) == before, 'retained evidence was modified'
        summary = adaptor.read(path, 'report-summary.json'); plan = adaptor.read(path, 'plan.json')
        assert 'transcriptTimeFormats' not in result and 'transcriptTimeFormats' not in summary and 'timeFormat' not in json.dumps(adaptor.read(path, 'captures.json')), path
        out['/'.join(path.parts[-5:])] = {
            'verified': True, 'runtime': result['runtime'], 'transcripts': result.get('transcripts', 0), 'lossWording': 'earlier' if plan['losses'][-1] == adaptor.LEGACY_TRANSCRIPT_LOSS else 'current', 'evidenceUnchanged': True}
    report['genuineEarlierRuns'] = out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pandoc', required=True, type=Path)
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--genuine-run', action='append', default=[], type=Path, help='retained earlier run directory re-verified read-only (never modified)')
    args = parser.parse_args(); directory = args.output_directory.resolve(); directory.mkdir(parents=True, exist_ok=False)
    pandoc = args.pandoc.resolve(); locations = {'pandoc': str(pandoc)}
    version = subprocess.run([str(pandoc), '--version'], capture_output=True, text=True, timeout=30, check=True).stdout.splitlines()[0]
    report = {'verified': False, 'runtime': version, 'pandocSha256': hashlib.sha256(pandoc.read_bytes()).hexdigest(), 'negative': {}}
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == SOURCE_SHA, 'fixture changed'
    try:
        genuine(args.genuine_run, report)
        timecode_acceptance(directory / 'a', locations, report['negative'])
        mixed_acceptance(directory / 'a', locations, report['negative'])
        absent_acceptance(directory / 'a', locations, report['negative'])
        unicode_acceptance(directory / 'a', locations, report['negative'])
        lifecycle(directory / 'a', locations, report)
        report['verified'] = True
    finally: atomic_json(directory / 'acceptance.json', report)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__': main()
