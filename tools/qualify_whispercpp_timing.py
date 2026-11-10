#!/usr/bin/env python3
"""Acceptance of the Pandoc publishing handoff of schemaxis.whispercpp.correct/3 (author-edited cue times) with real Pandoc.

This is a PUBLISHING handoff check, not speech-recognition requalification and not native qualification of the correction route.
The retained, genuine native whisper.cpp 1.9.5-dev draft of the public sample (pinned bytes, three cues 0/5410/9040/11000 ms) is
corrected without any whisper.cpp launch (a sentinel executable proves it), then handed through a verified workflow to the Pandoc
transcript block as artifact index 0, in integer milliseconds and in timecode, and once with the optional EPUB. The published
HTML, DOCX and EPUB tables are read back with html.parser and zipfile/ElementTree, with no schemaxis reader, against HAND-WRITTEN
expected intervals; nothing here uses Word, a device or an accessibility checker.

The declarations are automated illustrative declarations; no person listened to or reviewed anything. Every subprocess this tool
launches is bounded by a deadline and records its PID, command and exit status; processes the workflow executor launches are
observed by polling /proc and by their retained submission records, so a very short-lived process can be missing from the observed
PID list. Only the selected Pandoc binary is fingerprinted (size, mtime, SHA-256, symlinks resolved) before and after; its installation directory
is not hashed. The tool refuses to start under python -O or PYTHONOPTIMIZE because its checks are assert statements.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

if not __debug__:
    sys.exit('refused: this qualifier uses assert statements; run without python -O / PYTHONOPTIMIZE. No acceptance work, native process or output was started.')

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify_whispercpp_deletions as base  # noqa: E402

from schemaxis import workflow  # noqa: E402
from schemaxis.adaptors.pandoc import adaptor as pandoc_report  # noqa: E402
from schemaxis.adaptors.whispercpp import corrections_timing as corr  # noqa: E402
from schemaxis.artifacts import atomic_json  # noqa: E402
from schemaxis.core import timed_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JFK_SHA = '0fb466aec743b3a236655d7b29e4d3a1003bcd5230abcd4276af56b08cb4ba04'
NOTE = 'Illustrative automated declaration; no person listened to or reviewed this recording.'
REPLACED = 'And so, my fellow Americans: ask not what'
TEXTS = ['And so my fellow Americans, ask not what', 'your country can do for you, ask what you', 'can do for your country.']
EDIT = [{'index': 0, 'startMs': 120, 'endMs': 5300}, {'index': 2, 'startMs': 9100, 'endMs': 10950}]
# Cue 0 is both reworded and retimed, so every ledger section must show its original and published times side by side.
COMBINED = {'corrections': [{'index': 0, 'text': REPLACED}], 'deletions': [1], 'timings': [{'index': 0, 'startMs': 100, 'endMs': 5400}, {'index': 2, 'startMs': 8000, 'endMs': 10000}]}
TEXTONLY = {'corrections': [{'index': 0, 'text': REPLACED}]}
# Hand-written expected intervals (start, end, text); they are not derived from any schemaxis code.
EXPECTED = {'edit': [(120, 5300, TEXTS[0]), (5410, 9040, TEXTS[1]), (9100, 10950, TEXTS[2])],
            'combined': [(100, 5400, REPLACED), (8000, 10000, TEXTS[2])],
            'textonly': [(0, 5410, REPLACED), (5410, 9040, TEXTS[1]), (9040, 11000, TEXTS[2])]}
CLOCK = {'edit': [('00:00:00.120', '00:00:05.300'), ('00:00:05.410', '00:00:09.040'), ('00:00:09.100', '00:00:10.950')],
         'combined': [('00:00:00.100', '00:00:05.400'), ('00:00:08.000', '00:00:10.000')],
         'textonly': [('00:00:00.000', '00:00:05.410'), ('00:00:05.410', '00:00:09.040'), ('00:00:09.040', '00:00:11.000')]}
EDITED_SOURCES = {'edit': [0, 2], 'combined': [0, 2], 'textonly': []}
# Hand-written ledger rows. Times are (originalStartMs, originalEndMs, startMs, endMs): the pinned draft's times, then the published ones.
LEDGER = {'edit': {'replacements': [], 'timingEdits': [(0, 0, 5410, 120, 5300), (2, 9040, 11000, 9100, 10950)], 'deletions': [],
                   'retained': [(0, 0, 5410, 120, 5300, False, True), (1, 5410, 9040, 5410, 9040, False, False), (2, 9040, 11000, 9100, 10950, False, True)]},
          'combined': {'replacements': [(0, 0, 5410, 100, 5400)], 'timingEdits': [(0, 0, 5410, 100, 5400), (2, 9040, 11000, 8000, 10000)], 'deletions': [(1, 5410, 9040)],
                       'retained': [(0, 0, 5410, 100, 5400, True, True), (2, 9040, 11000, 8000, 10000, False, True)]},
          'textonly': {'replacements': [(0, 0, 5410, 0, 5410)], 'timingEdits': [], 'deletions': [],
                       'retained': [(0, 0, 5410, 0, 5410, True, False), (1, 5410, 9040, 5410, 9040, False, False), (2, 9040, 11000, 9040, 11000, False, False)]}}


def sha256(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(binary):
    """Read-only fingerprint of the one selected Pandoc binary (symlinks resolved): size, mtime and SHA-256. The installation directory is not hashed."""
    resolved = Path(binary).resolve(strict=True); status = resolved.stat()
    return {'path': str(resolved), 'bytes': status.st_size, 'mtimeNs': status.st_mtime_ns, 'sha256': sha256(resolved)}


def documents(jfk):
    base_document = {'version': corr.VERSION, 'draft': {'path': str(jfk)}, 'basisSha256': JFK_SHA}
    return {'edit': {**base_document, 'review': {'status': 'human-corrected', 'note': NOTE}, 'timings': EDIT},
            'combined': {**base_document, 'review': {'status': 'human-corrected', 'note': NOTE}, **COMBINED},
            'textonly': {**base_document, 'review': {'status': 'human-corrected', 'note': NOTE}, **TEXTONLY}}


def readback(directory, kind, source):
    """Independent readback of the published files from JSON and text, without corrections code."""
    reviewed = json.loads((directory / 'reviewed-segments.json').read_text()); ledger = json.loads((directory / 'corrections.json').read_text())
    original = json.loads(Path(source).read_text())['segments']
    assert reviewed['version'] == 'schemaxis.timedtext.reviewed/3' and ledger['version'] == 'schemaxis.whispercpp.corrections/3'
    assert [(s['index'], s['startMs'], s['endMs'], s['text']) for s in reviewed['segments']] == [(n, *row) for n, row in enumerate(EXPECTED[kind])]
    assert reviewed['review']['timingEditedIndices'] == EDITED_SOURCES[kind] and ledger['timingEditCount'] == len(EDITED_SOURCES[kind])
    retained = reviewed['review']['retainedSourceIndices']
    assert reviewed['review']['originalTimings'] == [{'sourceIndex': i, 'startMs': original[i]['startMs'], 'endMs': original[i]['endMs']} for i in retained], 'originals must be the native draft times'
    assert (reviewed['review']['synchronizationCertified'], reviewed['review']['accuracyCertified'], reviewed['review']['identityVerified'], ledger['synchronizationCertified']) == (False,) * 4
    srt, vtt = (directory / 'captions.srt').read_text(), (directory / 'captions.vtt').read_text()
    for (start, end), (_, _, text) in zip(CLOCK[kind], EXPECTED[kind]):
        assert f'{start.replace(".", ",")} --> {end.replace(".", ",")}\n{text}\n' in srt and f'{start} --> {end}\n{text}\n' in vtt
    assert ledger['reviewedSha256'] == sha256(directory / 'reviewed-segments.json')
    for section, rows in LEDGER[kind].items():
        found = ledger[section]; assert len(found) == len(rows), (section, found)
        for entry, row in zip(found, rows):
            if section == 'deletions':
                assert set(entry) == {'sourceIndex', 'originalStartMs', 'originalEndMs', 'original'}, entry
                assert (entry['sourceIndex'], entry['originalStartMs'], entry['originalEndMs']) == row and entry['original'] == TEXTS[row[0]], entry
                continue
            assert (entry['sourceIndex'], entry['originalStartMs'], entry['originalEndMs'], entry['startMs'], entry['endMs']) == row[:5], (section, entry)
            assert (entry['originalStartMs'], entry['originalEndMs']) == (original[entry['sourceIndex']]['startMs'], original[entry['sourceIndex']]['endMs']), 'originals must be the native draft times'
            if section == 'retained': assert (entry['edited'], entry['retimed']) == row[5:], entry
    published = {c['sourceIndex']: (c['startMs'], c['endMs']) for c in ledger['retained']}
    for section in ('replacements', 'timingEdits'):
        for entry in ledger[section]: assert (entry['startMs'], entry['endMs']) == published[entry['sourceIndex']], 'every section must show the same published time'
    return {'cues': len(retained), 'ledgerSections': {section: len(rows) for section, rows in LEDGER[kind].items()}}


def refresh(directory):
    from schemaxis.adaptors.whispercpp import corrections as first
    receipt = first.read_json(directory, 'verification.json'); plan = first.read_json(directory, 'plan.json')
    receipt['artifacts'] = first.artifacts(directory, first.wants_review(plan)); receipt['evidence'] = {n: first.digest(directory, n) for n in receipt['evidence']}
    atomic_json(directory / 'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def tampering(directory):
    """Every probe refreshes all ordinary hashes, so only independent replay can notice the change."""
    saved = {p: p.read_bytes() for p in directory.iterdir() if p.is_file()}; probes = {}
    def restore():
        for path in [p for p in directory.iterdir() if p.is_file() and p not in saved]: path.unlink()
        for path, data in saved.items(): path.write_bytes(data)
    def probe(name, mutate, label):
        try:
            path = directory / name; original = path.read_bytes(); changed = mutate(original); assert changed != original, 'vacuous probe ' + label
            path.write_bytes(changed); refresh(directory)
            probes[f'{name}:{label}'] = base.refused(lambda: corr.verify(directory), 'VERIFICATION_FAILED')['code']
        finally: restore()
    def original_times(b):
        value = json.loads(b)
        for cue, original in zip(value['segments'], value['review']['originalTimings']): cue['startMs'], cue['endMs'] = original['startMs'], original['endMs']
        value['review'].update(timingEditCount=0, timingEditedIndices=[], status='human-reviewed-unchanged'); timed_text.validate(value); return timed_text.canonical_json(value)
    for name, mutate, label in (('reviewed-segments.json', original_times, 'coherent-restored-original-times'),
                                ('reviewed-segments.json', lambda b: b.replace(b'"endMs": 5300', b'"endMs": 5301', 1), 'published-end'),
                                ('captions.srt', lambda b: b.replace(b'00:00:09,100', b'00:00:09,040'), 'srt-time'),
                                ('corrections.json', lambda b: b.replace(b'"originalEndMs": 5410', b'"originalEndMs": 5300', 1), 'ledger-original'),
                                ('authored.json', lambda b: json.dumps({**json.loads(b), 'timings': EDIT[:1]}).encode(), 'authored-dropped-edit')):
        probe(name, mutate, label)
    corr.verify(directory); probes['restored'] = 'verified'
    return probes


def negatives(directory, docs):
    outcomes = {}
    def attempt(label, timings, code):
        document = {**docs['edit'], 'timings': timings}
        fault = base.refused(lambda: corr.run(document, directory / label, timeout=30), code)
        assert fault.get('recovery') and not (directory / label / 'reviewed-segments.json').exists(), label
        outcomes[label] = {'code': fault['code'], 'location': fault['location']}
    attempt('overlap', [{'index': 1, 'startMs': 5000, 'endMs': 9040}], 'TIMING_OVERLAP')
    attempt('after-audio', [{'index': 2, 'startMs': 9040, 'endMs': 11001}], 'TIMING_AFTER_AUDIO')
    attempt('noop', [{'index': 1, 'startMs': 5410, 'endMs': 9040}], 'TIMING_NOOP')
    attempt('index', [{'index': 3, 'startMs': 1, 'endMs': 2}], 'TIMING_INDEX_INVALID')
    return outcomes


def run_workflow(directory, docs, pandoc, sentinel, kind, name, time_format, epub):
    graph = json.loads((ROOT / 'examples/schemaxis/whispercpp-timing-workflow.json').read_text())
    graph['operations'][0]['document'] = docs[kind]
    block = graph['operations'][1]['document']['sections'][0]['content'][0]
    if time_format == 'milliseconds': block.pop('timeFormat')
    if epub: graph['operations'][1]['document']['epub'] = {'language': 'en'}
    result = workflow.execute(graph, directory / name, locations={'whispercpp': str(sentinel), 'pandoc': str(pandoc)}, timeout=180)
    assert result['status'] == 'succeeded', result['status']; assert workflow.verify(directory / name)['verified']
    published = directory / name / 'report'
    submissions = sorted((p.parent.name + '/' + p.name, json.loads(p.read_text())['exitCode']) for p in published.rglob('*-submission.json'))
    return published, submissions


def epub_pages(path):
    """Every XHTML page of the EPUB with its paragraphs and table rows, read with html.parser from the zip."""
    import zipfile
    pages = []
    with zipfile.ZipFile(path) as archive:
        for entry in archive.namelist():
            if entry.endswith('.xhtml'):
                collected = base.Collector(); collected.feed(archive.read(entry).decode('utf-8')); pages.append((entry, collected))
    return pages


def check_publication(label, paragraphs, rows, tables, kind, time_format):
    provenance = next(p for p in paragraphs if p.startswith('Status: '))
    assert provenance.startswith('Status: human-corrected, declared by the author of the corrections.'), provenance[:120]
    sources = ', '.join(map(str, EDITED_SOURCES[kind])); n = len(EDITED_SOURCES[kind]); kept = len(EXPECTED[kind])
    if n:
        assert f'{n} cue{"" if n == 1 else "s"} given author-edited start and end times (source cue indexes {sources})' in provenance, provenance
        assert (f"The times shown for the {n} cue{'' if n == 1 else 's'} listed above are edited times recorded in this document as the author's, "
                "not the machine draft's; the original machine times are not shown here.") in provenance, provenance
        assert ('The other' in provenance) == (kept > n), provenance
    else:
        assert "The author edited no cue times; the times shown are the machine draft's original times as recorded in this document, and Pandoc did not check them against the draft file." in provenance, provenance
        assert 'author-edited' not in provenance and 'edited times' not in provenance, provenance
    assert 'is not verified or certified' in provenance and 'preserved' not in provenance and 'a person has not reviewed it' not in provenance
    header = ['Start (HH:MM:SS.mmm)', 'End (HH:MM:SS.mmm)', 'Text'] if time_format == 'timecode' else ['Start (ms)', 'End (ms)', 'Text']
    body = [[*CLOCK[kind][i], text] if time_format == 'timecode' else [str(start), str(end), text] for i, (start, end, text) in enumerate(EXPECTED[kind])]
    assert tables == 1 and rows == [header, *body], (label, rows)
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pandoc', required=True, type=Path, help='absolute official Pandoc 3.12.1 binary')
    parser.add_argument('--jfk-draft', required=True, type=Path, help='retained genuine three-cue segments.json of the public sample')
    parser.add_argument('--output-directory', required=True, type=Path)
    args = parser.parse_args()
    directory = args.output_directory.resolve(); directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic(); report = {'verified': False, 'route': corr.VERSION, 'nativeQualified': False, 'hostOnly': True, 'pid': os.getpid(), 'scope': 'Pandoc publishing handoff, not ASR requalification',
                                          'declarations': 'automated illustrative declarations; no person listened to or reviewed any recording'}
    qualification = ROOT / 'src/schemaxis/adaptors/whispercpp/qualification.json'; before = sha256(qualification)
    binary_before = fingerprint(args.pandoc); report['pandocBinaryBefore'] = binary_before
    staged = directory / 'drafts'; staged.mkdir(mode=0o700); jfk = staged / 'jfk-segments.json'; shutil.copyfile(args.jfk_draft, jfk)
    assert sha256(jfk) == JFK_SHA, 'the retained genuine draft changed'
    sampler = base.Sampler()
    try:
        code, out, _ = base.bounded('pandoc-version', [args.pandoc, '--version'], timeout=30)
        assert code == 0 and out.splitlines()[0] == 'pandoc 3.12.1', out[:80]
        report['pandoc'] = {'version': out.splitlines()[0], 'sha256': binary_before['sha256']}
        report['draft'] = {'sha256': JFK_SHA, 'provenance': 'genuine native whisper.cpp 1.9.5-dev output of the public sample, -ml 42 -sow, retained from the accepted allocation 45 fixtures', 'recognitionRunHere': False}
        sentinel = directory / 'whisper-cli-sentinel'; marker = directory / 'whisper-launched.log'
        sentinel.write_text('#!/bin/sh\necho "launched $$ $@" >> ' + str(marker) + '\nexit 99\n'); sentinel.chmod(0o700)
        docs = documents(jfk); os.environ['SCHEMAXIS_WHISPERCPP'] = str(sentinel)
        for kind in ('edit', 'combined', 'textonly'):
            result = corr.run(docs[kind], directory / kind, timeout=30)
            assert result['verified'] and result['nativeProcesses'] == 0 and result['synchronizationCertified'] is False, result
            report[kind] = {'result': result, 'readback': readback(directory / kind, kind, jfk)}
        report['negatives'] = negatives(directory / 'negatives', docs)
        report['tampering'] = tampering(directory / 'edit')
        sampler.start()
        for kind, name, time_format, epub in (('edit', 'pandoc-edit-ms', 'milliseconds', True), ('edit', 'pandoc-edit-timecode', 'timecode', False),
                                              ('combined', 'pandoc-combined-ms', 'milliseconds', False), ('combined', 'pandoc-combined-timecode', 'timecode', False),
                                              ('textonly', 'pandoc-textonly-ms', 'milliseconds', False)):
            published, submissions = run_workflow(directory, docs, args.pandoc, sentinel, kind, name, time_format, epub)
            html_path, docx_path = next(published.rglob('report.html')), next(published.rglob('report.docx'))
            collected = base.Collector(); collected.feed(html_path.read_text()); docx_paragraphs, docx_rows, docx_tables = base.docx_text(docx_path)
            body = check_publication('html', collected.paragraphs, collected.rows, collected.tables, kind, time_format)
            assert check_publication('docx', docx_paragraphs, docx_rows, docx_tables, kind, time_format) == body
            entry = {'html': str(html_path.relative_to(directory)), 'docx': str(docx_path.relative_to(directory)), 'rows': body, 'pandocSubmissionExitCodes': submissions,
                     'readback': 'html.parser and zipfile/ElementTree over the published files'}
            if epub:
                epub_path = next(published.rglob('report.epub'))
                pages = [(n, c) for n, c in epub_pages(epub_path) if c.tables]
                assert len(pages) == 1, [n for n, _ in pages]
                check_publication('epub', pages[0][1].paragraphs, pages[0][1].rows, pages[0][1].tables, kind, time_format)
                entry['epub'] = {'path': str(epub_path.relative_to(directory)), 'page': pages[0][0], 'scope': 'bounded structural readback only; not EPUBCheck, a reading system or an accessibility claim'}
            report_directory = html_path.parent
            summary = json.loads((report_directory / 'report-summary.json').read_text())
            observations = summary['transcriptObservations']; assert len(observations) == 1 and 'reviewed/3' in observations[0], observations
            if EDITED_SOURCES[kind]:
                assert 'author-edited times' in observations[0] and f'(source cue indexes {", ".join(map(str, EDITED_SOURCES[kind]))})' in observations[0], observations
                assert "recorded in this document as the author's times" in observations[0], observations
            else:
                assert 'no cue times edited by the author' in observations[0] and 'author-edited times' not in observations[0], observations
            assert pandoc_report.TRANSCRIPT_LOSS in summary['losses'], 'the plan transcript-loss sentence is the unchanged literal'
            pandoc_report.verify(report_directory); entry['reportSummary'] = {'transcripts': summary['transcripts'], 'observation': observations[0]}
            report[name] = entry
        sampler.stop(); report['observedChildPids'] = sampler.seen
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'PATH': '/nonexistent', 'SCHEMAXIS_WHISPERCPP': '/nonexistent/whisper-cli'}
        (directory / 'cli-document.json').write_text(json.dumps(docs['edit']))
        for label, argv in (('cli-plan', [sys.executable, '-m', 'schemaxis', 'plan', str(directory / 'cli-document.json')]),
                            ('cli-run', [sys.executable, '-m', 'schemaxis', 'run', str(directory / 'cli-document.json'), '--output-directory', str(directory / 'cli-run')]),
                            ('cli-verify', [sys.executable, '-m', 'schemaxis', 'verify', str(directory / 'cli-run')])):
            code, out, err = base.bounded(label, argv, timeout=120, env=env, cwd=str(directory)); assert code == 0, (label, out[-300:], err[-300:])
        assert json.loads(out)['verified'] is True
        assert not marker.exists(), 'whisper-cli was launched: ' + marker.read_text()
        assert sha256(jfk) == JFK_SHA, 'the machine draft was modified'
        assert sha256(qualification) == before and corr.VERSION not in json.loads(qualification.read_text())['routes'], 'no qualification receipt may exist for the host-only route'
        assert fingerprint(args.pandoc) == binary_before, 'the selected Pandoc binary changed'
        report['noNativeLaunch'] = {'sentinel': sentinel.name, 'launchLogExists': False}; report['pandocBinaryUnchanged'] = True
        report['verified'] = True
    finally:
        if sampler.is_alive(): sampler.stop()
        base.PROCESSES.sort(key=lambda r: r['pid'])
        report['processes'] = base.PROCESSES; report['elapsedSeconds'] = round(time.monotonic() - started, 1)
        atomic_json(directory / 'timing-acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
