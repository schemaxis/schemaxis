#!/usr/bin/env python3
"""Bounded native acceptance of verifying a genuine earlier Pandoc transcript report whose provenance paragraph wrote "1 cues".

Runs the real Pandoc on a one-cue machine draft: the current writer must publish "1 cue", an earlier-grammar control written by the real
Pandoc must verify, and refreshed-hash forgeries of it must be refused. Genuine retained reports passed with --genuine-run are only
re-verified, then compared byte for byte and by modification time. Nothing is registered, and the whole run is bounded by --deadline.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qualify_pandoc import refresh  # noqa: E402
from qualify_pandoc_timecode import docx_edit, forgeries, html_edit, json_edit, native, provenance, report_of, tables, transcript  # noqa: E402
from schemaxis.adaptors.pandoc import adaptor  # noqa: E402
from schemaxis.artifacts import atomic_json  # noqa: E402
from schemaxis.core import timed_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'examples/schemaxis/fixtures/pandoc/segments-jfk-short.json'
# Independent literals, written here and not derived from the adaptor.
CUE = 'And so my fellow Americans, ask not what your country can do for you, ask what you can do for your country.'
AUDIO_SHA = '59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e'
MS_HEADER = ['Start (ms)', 'End (ms)', 'Text']
TC_HEADER = ['Start (HH:MM:SS.mmm)', 'End (HH:MM:SS.mmm)', 'Text']
CURRENT, EARLIER = b'Language en; 1 cue; audio', b'Language en; 1 cues; audio'


def one_cue_source(directory):
    """The retained whisper.cpp fixture reduced to one cue and no cue-length target: the shape of the genuine earlier report."""
    value = json.loads(FIXTURE.read_text()); value.pop('segmentation')
    value['segments'] = [{'index': 0, 'startMs': 0, 'endMs': 11000, 'text': CUE}]; value['segmentCount'] = 1
    path = directory / 'one-cue-segments.json'; path.write_bytes(timed_text.canonical_json(value)); return path


def snapshot(root):
    """Bytes and nanosecond modification times of every member: reading must change neither."""
    return {str(p.relative_to(root)): (p.lstat().st_mtime_ns, p.lstat().st_size, hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
            for p in sorted(Path(root).rglob('*'))}


def genuine(paths, report):
    out = {}
    for path in paths:
        path = Path(path).resolve(); before = snapshot(path)
        captured = adaptor.read(path, 'captures.json')['transcript-0-0.json']; tree = adaptor.read(path, 'report-input.json')
        text = ' '.join(''.join(' ' if i['t'] == 'Space' else i['c'] for i in b['c']) for b in tree['blocks'] if b['t'] == 'Para')
        result = adaptor.verify(path); assert result['verified'], result
        assert snapshot(path) == before, 'retained evidence or a modification time changed'
        out['/'.join(path.parts[-5:])] = {'verified': True, 'files': len(before), 'cues': captured['cues'], 'status': captured['status'], 'writesOneCues': 'Language en; 1 cues;' in text,
                                          'planLossWording': 'earlier' if adaptor.read(path, 'plan.json')['losses'][-1] == adaptor.LEGACY_TRANSCRIPT_LOSS else 'current',
                                          'treeSha256': hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(), 'evidenceAndMtimesUnchanged': True}
    report['genuineEarlierRuns'] = out


def inputs(run):
    """Re-bind the HTML and DOCX stage input records to the edited AST, as a forger recomputing every ordinary hash would."""
    for stage in ('html', 'docx'):
        record = adaptor.read(run, stage + '-inputs.json'); record[str(run / 'report-input.json')] = adaptor.digest(run, 'report-input.json'); atomic_json(run / (stage + '-inputs.json'), record)


def ast_text(run, change):
    def mutate(value):
        text = json.dumps(value); changed = change(text); assert changed != text; value.clear(); value.update(json.loads(changed))
    def apply():
        json_edit(run, 'report-input.json', mutate)(); inputs(run)
    return apply


def earlier_control(directory, source, locations):
    """A real-Pandoc run of the earlier grammar and earlier loss wording, structurally what the genuine report is; verified by the unpatched code."""
    document = report_of('Transcript (machine draft)', transcript(source))
    real = adaptor.transcript_content
    with patch.object(adaptor, 'transcript_content', lambda view, fmt=None, legacy=False: real(view, fmt, True)):
        result = adaptor.run(document, directory, executable=locations['pandoc'], timeout=60)
    assert result['verified'], result
    plan = adaptor.read(directory, 'plan.json'); plan['losses'][-1] = adaptor.LEGACY_TRANSCRIPT_LOSS; atomic_json(directory / 'plan.json', plan)
    summary = adaptor.read(directory, 'report-summary.json'); summary['losses'][-1] = adaptor.LEGACY_TRANSCRIPT_LOSS; atomic_json(directory / 'report-summary.json', summary)
    refresh(directory)
    return document


def acceptance(directory, locations, report):
    directory.mkdir(parents=True); source = one_cue_source(directory)
    current = directory / 'current'; result = native(report_of('One cue, current writer', transcript(source)), current, locations)
    assert result['transcripts'] == 1 and 'transcriptTimeFormats' not in result, result
    for place, found in provenance(current).items(): assert 'Language en; 1 cue; audio duration 11000 ms;' in found and '1 cues' not in found, place
    assert (current / 'report-input.json').read_bytes().count(b'"cues;"') == 0 and adaptor.read(current, 'plan.json')['losses'][-1] == adaptor.TRANSCRIPT_LOSS
    report['currentWriterOneCue'] = {'verified': True, 'htmlDocxReadback': 'Language en; 1 cue;', 'lossWording': 'current'}
    stamped = directory / 'timecode'; native(report_of('One cue, timecode', transcript(source, 'timecode')), stamped, locations)
    assert all('Language en; 1 cue; audio duration 00:00:11.000;' in t for t in provenance(stamped).values())
    report['currentWriterOneCueTimecode'] = {'verified': True}
    run = directory / 'earlier'; earlier_control(run, source, locations)
    for place, found in provenance(run).items(): assert 'Language en; 1 cues; audio duration 11000 ms;' in found, place
    found, word, back = tables(run)
    for got in (found, word, back): assert got == [(MS_HEADER, [['0', '11000', CUE]])], got
    before = snapshot(run); result = adaptor.verify(run); assert result['verified'] and result['transcripts'] == 1 and snapshot(run) == before, result
    report['earlierGrammarControl'] = {'verified': True, 'wroteOneCues': True, 'cueTable': 'literal in HTML, DOCX and readback', 'evidenceAndMtimesUnchanged': True}
    probes = [
        ('astClaimsCurrentGrammarButPublicationEarlier', ast_text(run, lambda t: t.replace('"cues;"', '"cue;"')), 'semantics differ'),
        ('astWrongCount', ast_text(run, lambda t: t.replace('"1"', '"2"', 1)), 'trusted AST differs'),
        ('astStatusChanged', ast_text(run, lambda t: t.replace('"machine-draft."', '"human-corrected."')), 'trusted AST differs'),
        ('astCueWordChanged', ast_text(run, lambda t: t.replace('"ask"', '"asks"', 1)), 'trusted AST differs'),
        ('astDigestChanged', ast_text(run, lambda t: t.replace(AUDIO_SHA, '1' * 64)), 'trusted AST differs'),
        ('htmlSingularGrammar', html_edit(run, EARLIER.decode(), CURRENT.decode()), 'semantics differ'),
        ('htmlCountChanged', html_edit(run, 'Language en; 1 cues;', 'Language en; 2 cues;'), 'semantics differ'),
        ('docxSingularGrammar', docx_edit(run, EARLIER, CURRENT), 'semantics differ'),
        ('docxCountChanged', docx_edit(run, EARLIER, b'Language en; 2 cues; audio'), 'semantics differ'),
        ('planLossBecomesCurrent', json_edit(run, 'plan.json', lambda v: v['losses'].__setitem__(-1, adaptor.TRANSCRIPT_LOSS)), 'trusted AST differs'),
        ('timeFormatClaimedEverywhere', lambda: (json_edit(run, 'authored.json', lambda v: v['sections'][0]['content'][0].update(timeFormat='timecode'))(),
                                                 json_edit(run, 'plan.json', lambda v: v.update(losses=[*v['losses'], adaptor.TIMECODE_LOSS]))(),
                                                 json_edit(run, 'captures.json', lambda v: v['transcript-0-0.json'].update(timeFormat='timecode'))()), 'effective report plan differs'),
        ('capturedWordsChanged', lambda: (run / 'transcript-0-0.json').write_bytes(timed_text.canonical_json({**json.loads((run / 'transcript-0-0.json').read_text()),
            'segments': [{'index': 0, 'startMs': 0, 'endMs': 11000, 'text': 'changed words'}]})), 'no longer satisfies the timed-text contract or its pin')]
    negative = {}; forgeries(run, 'earlier', probes, negative); report['negative'] = negative


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pandoc', required=True, type=Path)
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--genuine-run', action='append', default=[], type=Path, help='genuine earlier retained report directory, re-verified read-only')
    parser.add_argument('--deadline', type=float, default=170, help='seconds before the whole acceptance is stopped (default 170, below 180)')
    args = parser.parse_args(); assert 0 < args.deadline < 180, 'the acceptance is bounded below 180 seconds'
    import signal
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('acceptance deadline exceeded'))); signal.alarm(int(args.deadline))
    directory = args.output_directory.resolve(); pandoc = args.pandoc.resolve(); locations = {'pandoc': str(pandoc)}
    version = subprocess.run([str(pandoc), '--version'], capture_output=True, text=True, timeout=30, check=True).stdout.splitlines()[0]
    report = {'verified': False, 'pid': os.getpid(), 'runtime': version, 'pandocSha256': hashlib.sha256(pandoc.read_bytes()).hexdigest()}
    directory.mkdir(parents=True, exist_ok=False)
    try:
        genuine(args.genuine_run, report); acceptance(directory / "a", locations, report); report['verified'] = True
    finally: atomic_json(directory / 'acceptance.json', report)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
