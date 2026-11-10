#!/usr/bin/env python3
"""Host-only acceptance of schemaxis.whispercpp.correct/2 (explicit cue deletion) with real Pandoc HTML and DOCX publication.

Two retained genuine native whisper.cpp drafts are corrected without any whisper.cpp launch (a sentinel executable proves
it): a two second silent recording whose one cue "You" is a recognition artefact (every cue deleted), and the three-cue public
sample (one cue replaced and one deleted). Each reviewed/2 document is handed through a verified workflow to the Pandoc
transcript block and the HTML and DOCX are read back with html.parser and zipfile/ElementTree, with no schemaxis reader.

The declarations are automated illustrative declarations; no person reviewed anything. This never registers a receipt and
never labels the route native-qualified. Every subprocess this tool launches is bounded by a deadline and records its PID,
command and exit status; processes the workflow executor launches are observed by polling /proc and by their retained
submission records, so a very short-lived process can be missing from the observed PID list.
"""
import argparse
import copy
import hashlib
import html.parser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ElementTree
import zipfile

from schemaxis import workflow
from schemaxis.adaptors.pandoc import adaptor as pandoc_report
from schemaxis.adaptors.whispercpp import corrections as first
from schemaxis.adaptors.whispercpp import corrections_deletion as corr
from schemaxis.artifacts import atomic_json
from schemaxis.core import timed_text
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[1]
SILENCE_SHA = 'ce623bde74e436a134230ba80cee7613fd61358acac8e1094ff35d5293ca27be'
CHAIN_SHA = 'fb5a1eab941f7b97be2a4607b037c6d2a141eccb491b8daaf276211bdd71d118'
NOTE = 'Illustrative automated declaration; no person reviewed this recording for it.'
REPLACED = 'And so, my fellow Americans: ask not what'
PROCESSES = []


def sha256(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bounded(label, argv, *, timeout, env=None, cwd=None):
    """Launch one subprocess with a deadline; record its PID, command, exit status and wall time."""
    started = time.monotonic()
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=cwd, stdin=subprocess.DEVNULL)
    record = {'label': label, 'pid': process.pid, 'argv': [str(a) for a in argv], 'deadlineSeconds': timeout}
    PROCESSES.append(record)
    try: out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill(); process.communicate(); record.update(exitCode=None, timedOut=True); raise AssertionError(f'{label} exceeded its {timeout} s deadline (killed pid {process.pid})')
    record.update(exitCode=process.returncode, timedOut=False, seconds=round(time.monotonic() - started, 3))
    return process.returncode, out, err


class Sampler(threading.Thread):
    """Poll /proc for direct children of this process while a workflow runs; best effort, bounded by stop()."""
    def __init__(self):
        super().__init__(daemon=True); self.seen = {}; self.stopped = threading.Event()
    def run(self):
        while not self.stopped.is_set():
            try:
                for task in Path('/proc/self/task').iterdir():
                    for pid in (task / 'children').read_text().split():
                        if pid not in self.seen:
                            try: self.seen[pid] = (Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace').strip())[:200]
                            except OSError: self.seen[pid] = '(exited before it could be read)'
            except OSError: pass
            self.stopped.wait(0.01)
    def stop(self): self.stopped.set(); self.join(timeout=5)


class Collector(html.parser.HTMLParser):
    """Independent HTML readback: paragraph texts and table rows, no schemaxis code."""
    def __init__(self):
        super().__init__(); self.paragraphs = []; self.rows = []; self.tables = 0; self.cell = None; self.row = None; self.para = None
    def handle_starttag(self, tag, attrs):
        if tag == 'p': self.para = ''
        if tag == 'table': self.tables += 1
        if tag == 'tr': self.row = []
        if tag in ('td', 'th'): self.cell = ''
    def handle_endtag(self, tag):
        if tag == 'p' and self.para is not None: self.paragraphs.append(self.para); self.para = None
        if tag in ('td', 'th') and self.cell is not None: self.row.append(self.cell); self.cell = None
        if tag == 'tr' and self.row is not None: self.rows.append(self.row); self.row = None
    def handle_data(self, data):
        if self.cell is not None: self.cell += data
        elif self.para is not None: self.para += data


def docx_text(path):
    namespace = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    with zipfile.ZipFile(path) as archive: root = ElementTree.fromstring(archive.read('word/document.xml'))
    text = lambda node: ''.join(t.text or '' for t in node.iter(namespace + 't'))
    body = root.find(namespace + 'body')
    return ([text(p) for p in body.findall(namespace + 'p')], [[text(c) for c in row.findall(namespace + 'tc')] for table in body.findall(namespace + 'tbl') for row in table.findall(namespace + 'tr')],
            len(body.findall(namespace + 'tbl')))


def refused(action, code):
    try: action()
    except SchemaxisError as error:
        assert error.fault.code == code, (code, error.fault.to_dict()); return error.fault.to_dict()
    raise AssertionError('expected ' + code)


def documents(directory, silence, jfk):
    base = {'version': corr.VERSION, 'review': {'status': 'human-corrected', 'note': NOTE}}
    return {'all': {**base, 'draft': {'path': str(silence)}, 'basisSha256': SILENCE_SHA, 'deletions': [0]},
            'partial': {**base, 'draft': {'path': str(jfk)}, 'basisSha256': CHAIN_SHA, 'corrections': [{'index': 0, 'text': REPLACED}], 'deletions': [1]},
            'unchanged': {'version': corr.VERSION, 'draft': {'path': str(jfk)}, 'basisSha256': CHAIN_SHA, 'review': {'status': 'human-reviewed-unchanged', 'note': NOTE}}}


def readback(directory, kind, source):
    """Independent readback of the published files from JSON and text, without corrections code."""
    reviewed = json.loads((directory / 'reviewed-segments.json').read_text()); ledger = json.loads((directory / 'corrections.json').read_text())
    original = json.loads(Path(source).read_text())['segments']
    assert reviewed['version'] == 'schemaxis.timedtext.reviewed/2' and ledger['version'] == 'schemaxis.whispercpp.corrections/2'
    deleted = {'all': [0], 'partial': [1], 'unchanged': []}[kind]
    retained = [i for i in range(len(original)) if i not in deleted]
    texts = [REPLACED if (kind == 'partial' and i == 0) else original[i]['text'] for i in retained]
    assert [s['text'] for s in reviewed['segments']] == texts and [s['index'] for s in reviewed['segments']] == list(range(len(retained)))
    assert [(s['startMs'], s['endMs']) for s in reviewed['segments']] == [(original[i]['startMs'], original[i]['endMs']) for i in retained], 'retained timings must be the native draft timings'
    assert reviewed['review']['deletedSourceIndices'] == deleted and reviewed['review']['retainedSourceIndices'] == retained
    assert [(e['sourceIndex'], e['original']) for e in ledger['deletions']] == [(i, original[i]['text']) for i in deleted]
    assert [(e['publishedIndex'], e['sourceIndex']) for e in ledger['retained']] == list(enumerate(retained))
    assert (directory / 'transcript.txt').read_text() == ''.join(t + '\n' for t in texts)
    srt = (directory / 'captions.srt').read_text(); vtt = (directory / 'captions.vtt').read_text()
    if not retained: assert (directory / 'transcript.txt').read_bytes() == b'' and srt == '' and vtt == 'WEBVTT\n\n'
    else: assert all(t in srt and t in vtt for t in texts) and vtt.startswith('WEBVTT\n\n')
    assert (reviewed['review']['accuracyCertified'], reviewed['review']['identityVerified'], ledger['identityVerified'], ledger['accuracyCertified']) == (False,) * 4
    assert ledger['reviewedSha256'] == sha256(directory / 'reviewed-segments.json')
    return {'cues': len(texts), 'texts': texts, 'deleted': deleted, 'retained': retained}


def refresh(directory):
    receipt = first.read_json(directory, 'verification.json'); plan = first.read_json(directory, 'plan.json')
    receipt['artifacts'] = first.artifacts(directory, first.wants_review(plan)); receipt['evidence'] = {n: first.digest(directory, n) for n in receipt['evidence']}
    atomic_json(directory / 'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def tampering(directory, kind):
    """Every probe refreshes all ordinary hashes, so only independent replay can notice the change."""
    saved = {p: p.read_bytes() for p in directory.iterdir() if p.is_file()}; probes = {}
    def restore():
        for path in [p for p in directory.iterdir() if p.is_file() and p not in saved]: path.unlink()
        for path, data in saved.items(): path.write_bytes(data)
    def probe(name, mutate, label):
        try:
            path = directory / name; original = path.read_bytes(); changed = mutate(original); assert changed != original, 'vacuous probe ' + label
            path.write_bytes(changed); refresh(directory)
            probes[f'{name}:{label}'] = refused(lambda: corr._native_verify(directory), 'VERIFICATION_FAILED')['code']
        finally: restore()
    def forged_empty(b):
        value = json.loads(b); source = value['review']['basis']['cueCount']
        value.update(segments=[], segmentCount=0); value.pop('segmentation', None)
        value['review'].update(correctionCount=0, correctedIndices=[], deletionCount=source, deletedSourceIndices=list(range(source)), retainedSourceIndices=[])
        timed_text.validate(value); return timed_text.canonical_json(value)
    def restored_cue(b):
        value = json.loads(b); source = value['review']['basis']['cueCount']
        value['segments'] = [{'index': i, 'startMs': i * 1000, 'endMs': i * 1000 + 900, 'text': 'Restored'} for i in range(source)]; value['segmentCount'] = source
        value['review'].update(deletionCount=0, deletedSourceIndices=[], retainedSourceIndices=list(range(source)), correctionCount=0, correctedIndices=[], status='human-reviewed-unchanged')
        value.pop('segmentation', None); return timed_text.canonical_json(value)
    if kind == 'all':
        for name, mutate, label in (('transcript.txt', lambda b: b'You\n', 'restored-cue-text'), ('captions.srt', lambda b: b'1\n00:00:00,000 --> 00:00:02,000\nYou\n\n', 'restored-cue-srt'),
                                    ('captions.vtt', lambda b: b + b'00:00:00.000 --> 00:00:02.000\nYou\n\n', 'restored-cue-vtt'), ('reviewed-segments.json', restored_cue, 'restored-cue-reviewed'),
                                    ('reviewed-segments.json', lambda b: b.replace(b'"deletionCount": 1', b'"deletionCount": 0'), 'deletion-count'),
                                    ('corrections.json', lambda b: b.replace(b'"original": "You"', b'"original": "Yo"'), 'ledger-original'),
                                    ('authored.json', lambda b: json.dumps({**json.loads(b), 'deletions': []}).encode(), 'authored-no-deletions')):
            probe(name, mutate, label)
    else:
        for name, mutate, label in (('reviewed-segments.json', forged_empty, 'forged-empty-state'), ('transcript.txt', lambda b: b + b'your country can do for you, ask what you\n', 'deleted-cue-returned'),
                                    ('reviewed-segments.json', lambda b: b.replace(b'"deletedSourceIndices": [\n      1\n    ]', b'"deletedSourceIndices": [\n      2\n    ]'), 'deleted-index-moved'),
                                    ('reviewed-segments.json', lambda b: b.replace(b'"endMs": 5410', b'"endMs": 5411', 1), 'timing'), ('captions.srt', lambda b: b.replace(b'2\n00:00:09,040', b'3\n00:00:09,040'), 'renumbering'),
                                    ('corrections.json', lambda b: b.replace(b'"sourceIndex": 2', b'"sourceIndex": 1', 1), 'mapping'), ('captured-draft.json', lambda b: b.replace(b'And so my', b'And so, my'), 'captured-draft'),
                                    ('authored.json', lambda b: json.dumps({**json.loads(b), 'deletions': [2]}).encode(), 'authored-deletion'), ('result.json', lambda b: b.replace(b'"deletions": 1', b'"deletions": 0'), 'result')):
            probe(name, mutate, label)
    try:
        (directory / 'transcribe-launcher.py').write_text('native evidence has no place here'); probes['launcher-membership'] = refused(lambda: corr._native_verify(directory), 'VERIFICATION_FAILED')['code']
    finally: restore()
    corr._native_verify(directory); probes['restored'] = 'verified'
    return probes


def negatives(directory, docs, jfk, silence):
    outcomes = {}
    def attempt(label, mutate, code, base='partial'):
        document = copy.deepcopy(docs[base]); mutate(document)
        fault = refused(lambda: corr.run(document, directory / label, timeout=30), code)
        assert fault.get('recovery') and not (directory / label / 'reviewed-segments.json').exists(), label
        outcomes[label] = {'code': fault['code'], 'location': fault['location']}
    attempt('stale', lambda d: d.update(basisSha256='1' * 64), 'CORRECTIONS_STALE')
    attempt('deletion-range', lambda d: d.update(deletions=[1, 3]), 'DELETION_INDEX_INVALID')
    attempt('replacement-range', lambda d: d.update(corrections=[{'index': 3, 'text': 'x'}]), 'CORRECTION_INDEX_INVALID')
    attempt('duplicate-deletion', lambda d: d.update(deletions=[1, 1]), 'DELETION_DUPLICATE')
    attempt('replace-and-delete', lambda d: d.update(deletions=[0]), 'CORRECTION_DELETION_CONFLICT')
    attempt('noop', lambda d: d.update(corrections=[{'index': 2, 'text': 'can do for your country.'}]), 'CORRECTION_NOOP')
    attempt('status', lambda d: d.update(corrections=[], deletions=[]), 'CORRECTIONS_STATUS_CONFLICT')
    attempt('unknown-key', lambda d: d.update(removals=[1]), 'UNKNOWN_ARGUMENT')
    attempt('object-deletion', lambda d: d.update(deletions=[{'index': 1}]), 'INVALID_ARGUMENT')
    attempt('caption-review-of-nothing', lambda d: d.update(captionReview=True), 'CAPTION_REVIEW_EMPTY', base='all')
    # An original machine draft with zero cues stays refused, and a reviewed document (any version) is never a draft.
    zero = json.loads(Path(silence).read_text()); zero['segments'] = []; zero['segmentCount'] = 0
    path = directory / 'zero-cue-draft.json'; path.write_bytes(timed_text.canonical_json(zero))
    document = {**docs['all'], 'draft': {'path': str(path)}, 'basisSha256': sha256(path)}
    fault = refused(lambda: corr.run(document, directory / 'zero-cue-original', timeout=30), 'TIMED_TEXT_INVALID'); outcomes['zero-cue-original'] = {'code': fault['code'], 'location': fault['location']}
    for label, reviewed in (('reviewed-2-as-draft', directory.parent / 'partial' / 'reviewed-segments.json'), ('empty-reviewed-2-as-draft', directory.parent / 'all' / 'reviewed-segments.json')):
        document = {**docs['partial'], 'draft': {'path': str(reviewed)}, 'basisSha256': sha256(reviewed)}
        fault = refused(lambda: corr.run(document, directory / label, timeout=30), 'DRAFT_NOT_MACHINE_DRAFT'); outcomes[label] = {'code': fault['code'], 'location': fault['location']}
    return outcomes


def pandoc_workflow(directory, docs, pandoc, sentinel, kind, sampler):
    graph = json.loads((ROOT / 'examples/schemaxis/whispercpp-deletions-workflow.json').read_text())
    graph['operations'][0]['document'] = docs[kind]
    name = 'pandoc-' + kind
    result = workflow.execute(graph, directory / name, locations={'whispercpp': str(sentinel), 'pandoc': str(pandoc)}, timeout=120)
    assert result['status'] == 'succeeded', result['status']; assert workflow.verify(directory / name)['verified']
    html_path = next((directory / name / 'report').rglob('report.html')); docx_path = next((directory / name / 'report').rglob('report.docx'))
    submissions = sorted((p.parent.name + '/' + p.name, json.loads(p.read_text())['exitCode']) for p in (directory / name / 'report').rglob('*-submission.json'))
    return html_path, docx_path, submissions


def summary_observations(report_directory, kind, tables, deleted, retained, source):
    """Read the published report-summary.json as plain JSON and check the actual-shape observation, then refuse a refreshed-hash forgery of it."""
    summary = json.loads((report_directory / 'report-summary.json').read_text())
    assert summary['tables'] == tables and summary['transcripts'] == 1, summary
    observations = summary['transcriptObservations']; assert len(observations) == 1, observations
    text = observations[0]
    assert text.startswith('$.sections[0].content[0]: schemaxis.timedtext.reviewed/2; ') and f'{deleted} of {source} source cues deleted by the author' in text, text
    assert f'{retained} cue{"" if retained == 1 else "s"} retained' in text, text
    if retained: assert 'one three-column table of the retained cues follows the provenance paragraph' in text and 'no table is published' not in text, text
    else: assert 'no table is published, only the provenance paragraph' in text and 'one three-column table of the retained cues' not in text, text
    assert summary['losses'][-1] == pandoc_report.TRANSCRIPT_LOSS, 'the plan loss sentence is the unchanged literal'
    saved = {p: p.read_bytes() for p in report_directory.iterdir() if p.is_file()}
    def refresh_pandoc():
        receipt = json.loads((report_directory / 'verification.json').read_text()); receipt['artifacts'] = pandoc_report.artifacts(report_directory)
        atomic_json(report_directory / 'verification.json', receipt)
        from schemaxis.publication_metadata import finalise
        finalise(report_directory)
    try:
        pandoc_report.verify(report_directory); probes = {'before': 'verified'}
        flipped = dict(summary, transcriptObservations=[text.replace('no table is published', 'one table is published') if not retained else text.replace('one three-column table', 'no table is published')])
        assert flipped != summary
        for label, changed in (('observation-text', flipped), ('observation-removed', {k: v for k, v in summary.items() if k != 'transcriptObservations'}),
                               ('observation-count', dict(summary, transcriptObservations=[text.replace(f'{retained} cue', f'{retained + 1} cue', 1)]))):
            try:
                atomic_json(report_directory / 'report-summary.json', changed); refresh_pandoc()
                probes[label] = refused(lambda: pandoc_report.verify(report_directory), 'VERIFICATION_FAILED')['code']
            finally:
                for path in [p for p in report_directory.iterdir() if p.is_file() and p not in saved]: path.unlink()
                for path, data in saved.items(): path.write_bytes(data)
        pandoc_report.verify(report_directory); probes['restored'] = 'verified'
    finally:
        for path, data in saved.items(): path.write_bytes(data)
    return {'tables': summary['tables'], 'observation': text, 'refreshedHashProbes': probes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pandoc', required=True, type=Path, help='absolute official Pandoc 3.12.1 binary')
    parser.add_argument('--silence-draft', required=True, type=Path, help='retained genuine segments.json of the silent recording')
    parser.add_argument('--jfk-draft', required=True, type=Path, help='retained genuine three-cue segments.json of the public sample')
    parser.add_argument('--output-directory', required=True, type=Path)
    args = parser.parse_args()
    directory = args.output_directory.resolve(); directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic(); report = {'verified': False, 'route': corr.VERSION, 'nativeQualified': False, 'hostOnly': True, 'pid': os.getpid(),
                                          'declarations': 'automated illustrative declarations; no person reviewed any recording'}
    qualification = ROOT / 'src/schemaxis/adaptors/whispercpp/qualification.json'; before = sha256(qualification)
    staged = directory / 'drafts'; staged.mkdir(mode=0o700)
    silence, jfk = staged / 'silence-segments.json', staged / 'jfk-segments.json'
    shutil.copyfile(args.silence_draft, silence); shutil.copyfile(args.jfk_draft, jfk)
    assert (sha256(silence), sha256(jfk)) == (SILENCE_SHA, CHAIN_SHA), 'the retained genuine drafts changed'
    sampler = Sampler()
    try:
        code, out, _ = bounded('pandoc-version', [args.pandoc, '--version'], timeout=30)
        assert code == 0 and out.splitlines()[0] == 'pandoc 3.12.1', out[:80]
        report['pandoc'] = {'version': out.splitlines()[0], 'sha256': sha256(args.pandoc)}
        report['drafts'] = {'silence': {'sha256': SILENCE_SHA, 'cues': ['You (0-2000 ms)'], 'provenance': 'genuine native whisper.cpp 1.9.5-dev output of a two second silent recording'},
                            'jfk': {'sha256': CHAIN_SHA, 'provenance': 'genuine native whisper.cpp 1.9.5-dev output of the public sample, -ml 42 -sow'}, 'recognitionRunHere': False}
        sentinel = directory / 'whisper-cli-sentinel'; marker = directory / 'whisper-launched.log'
        sentinel.write_text('#!/bin/sh\necho "launched $$ $@" >> ' + str(marker) + '\nexit 99\n'); sentinel.chmod(0o700)
        docs = documents(directory, silence, jfk)
        os.environ['SCHEMAXIS_WHISPERCPP'] = str(sentinel)
        for kind in ('all', 'partial', 'unchanged'):
            result = corr.run(docs[kind], directory / kind, timeout=30)
            assert result['verified'] and result['nativeProcesses'] == 0, result
            report[kind] = {'result': result, 'readback': readback(directory / kind, kind, {'all': silence}.get(kind, jfk))}
        report['negatives'] = negatives(directory / 'negatives', docs, jfk, silence)
        report['tampering'] = {kind: tampering(directory / kind, kind) for kind in ('all', 'partial')}
        sampler.start()
        for kind in ('all', 'partial'):
            html_path, docx_path, submissions = pandoc_workflow(directory, docs, args.pandoc, sentinel, kind, sampler)
            collected = Collector(); collected.feed(html_path.read_text()); docx_paragraphs, docx_rows, docx_tables = docx_text(docx_path)
            data = report[kind]['readback']; basis = SILENCE_SHA if kind == 'all' else CHAIN_SHA
            times = [(x['startMs'], x['endMs']) for x in json.loads((directory / kind / 'reviewed-segments.json').read_text())['segments']]
            expected_rows = [[str(start), str(end), text] for (start, end), text in zip(times, data['texts'])]
            for label, paragraphs, rows, tables in (('html', collected.paragraphs, collected.rows, collected.tables), ('docx', docx_paragraphs, docx_rows, docx_tables)):
                provenance = next(p for p in paragraphs if p.startswith('Status: '))
                assert provenance.startswith('Status: human-corrected, declared by the author of the corrections.'), provenance[:120]
                assert 'not verified or certified' in provenance and basis in provenance and 'a person has not reviewed it' not in provenance
                assert 'deleted by the author (source cue indexes ' + ', '.join(map(str, data['deleted'])) + ')' in provenance, provenance
                if kind == 'all':
                    assert tables == 0 and rows == [], (label, tables, rows)
                    assert 'no cues are retained and no spoken words are published here' in provenance
                    assert not re.search(r'\bYou\b', ' '.join(paragraphs)), 'the deleted cue text must not appear'
                else:
                    assert tables == 1 and rows == [['Start (ms)', 'End (ms)', 'Text'], *expected_rows], (label, rows)
                    assert 'the remaining 2 cues are numbered from zero as published' in provenance
                    assert 'your country can do for you' not in ' '.join(sum(rows, []) + paragraphs), 'the deleted cue text must not appear'
            observed = summary_observations(html_path.parent, kind, 0 if kind == 'all' else 1, len(data['deleted']), data['cues'], data['cues'] + len(data['deleted']))
            report['pandoc-' + kind] = {'html': str(html_path.relative_to(directory)), 'docx': str(docx_path.relative_to(directory)), 'rows': expected_rows, 'tables': {'html': collected.tables, 'docx': docx_tables},
                                       'pandocSubmissionExitCodes': submissions, 'readback': 'html.parser and zipfile/ElementTree over the published files', 'reportSummary': observed}
        sampler.stop()
        report['observedChildPids'] = sampler.seen
        # The command line is the other interface: plan, run and verify with no whisper executable on PATH.
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'PATH': '/nonexistent', 'SCHEMAXIS_WHISPERCPP': '/nonexistent/whisper-cli'}
        (directory / 'cli-document.json').write_text(json.dumps(docs['all']))
        for label, argv in (('cli-plan', [sys.executable, '-m', 'schemaxis', 'plan', str(directory / 'cli-document.json')]),
                            ('cli-run', [sys.executable, '-m', 'schemaxis', 'run', str(directory / 'cli-document.json'), '--output-directory', str(directory / 'cli-run')]),
                            ('cli-verify', [sys.executable, '-m', 'schemaxis', 'verify', str(directory / 'cli-run')])):
            code, out, err = bounded(label, argv, timeout=120, env=env, cwd=str(directory)); assert code == 0, (label, out[-300:], err[-300:])
        assert json.loads(out)['verified'] is True
        assert not marker.exists(), 'whisper-cli was launched: ' + marker.read_text()
        assert (sha256(silence), sha256(jfk)) == (SILENCE_SHA, CHAIN_SHA), 'a machine draft was modified'
        assert sha256(qualification) == before and corr.VERSION not in json.loads(qualification.read_text())['routes'], 'no qualification receipt may exist for the host-only route'
        report['noNativeLaunch'] = {'sentinel': sentinel.name, 'launchLogExists': False, 'nativeProcessesInResults': 0}
        report['verified'] = True
    finally:
        sampler.stop()
        report['processes'] = PROCESSES; report['elapsedSeconds'] = round(time.monotonic() - started, 1)
        atomic_json(directory / 'deletions-acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
