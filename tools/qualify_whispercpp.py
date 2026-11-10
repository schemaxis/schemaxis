#!/usr/bin/env python3
"""Qualify native whisper.cpp transcription: named public fixtures, hostile evidence and lifecycle.

Qualification covers structure, evidence binding and a literal known-sentence
result for one public sample with one model, plus one opt-in caption review case
whose editorial flags are recomputed independently, and two maxSegmentLength cases
(a native word-aware segmentation target, observed and never enforced). It does not certify recognition
accuracy for other audio, models, languages or runtimes, nor caption quality.

`--corrections-only` runs the separate HOST-ONLY acceptance of schemaxis.whispercpp.correct/1 instead: a retained real
native draft is corrected without any whisper.cpp launch (a sentinel executable proves it), published through a real Pandoc
HTML/DOCX report and read back independently. It never registers a receipt and never labels the route native-qualified.
"""
import argparse
import copy
import html.parser
import xml.etree.ElementTree as ElementTree
import zipfile
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import wave

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptor_delivery import case_document, route_materials
from schemaxis.adaptors.whispercpp import adaptor as a
from schemaxis.adaptors.whispercpp import corrections as corr
from schemaxis.core import timed_text
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import workflow

ROOT = Path(__file__).resolve().parents[1]
STAGING = Path('/tmp/schemaxis-whispercpp-acceptance')
_OWNED_STAGING = None
_OWNED_FILES = {}
# Public sample distributed in the whisper.cpp repository (samples/jfk.wav); never committed here.
SAMPLE_SHA256 = '59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e'
EXCERPT_SHA256 = '43e6a960b344dd5408628ca2f11ee444291790f0e52a5b44ea11e98fcc47f591'
EXCERPT_FRAMES = 128000
MODEL_SHA256 = 'a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002'
QUOTATION = 'and so my fellow americans ask not what your country can do for you ask what you can do for your country'
# What whisper.cpp 1.9.5 produced for the public sample with -ml 42 -sow: observed on this fixture, model and runtime only.
SHORT_CUES = [(0, 5410, 'And so my fellow Americans, ask not what'), (5410, 9040, 'your country can do for you, ask what you'), (9040, 11000, 'can do for your country.')]
SHORT_TARGET = 42


def words(text): return re.findall(r"[a-z0-9']+", text.lower())


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''): digest.update(block)
    return digest.hexdigest()


def refused(action, code=None):
    try: action()
    except SchemaxisError as error:
        assert code is None or error.fault.code == code, error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('invalid transcription input/evidence accepted')


def stage(sample, model):
    """Exclusively own the fixed example paths; never replace pre-existing data."""
    global _OWNED_STAGING, _OWNED_FILES
    if sha256(sample) != SAMPLE_SHA256: raise SystemExit('sample is not the expected public jfk.wav')
    if sha256(model) != MODEL_SHA256: raise SystemExit('model is not the pinned ggml-base.en.bin')
    try: STAGING.mkdir(mode=0o700)
    except FileExistsError: raise SystemExit(f'refusing pre-existing staging path {STAGING}; use the existing run or inspect and remove its own stale staging first')
    info=STAGING.lstat();_OWNED_STAGING=(info.st_dev,info.st_ino);_OWNED_FILES={}
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700: raise SystemExit('staging identity/mode differs')
    def remember(path):
        info=path.lstat();_OWNED_FILES[path]=(info.st_dev,info.st_ino)
    try:
        with (STAGING/'jfk.wav').open('xb') as target, open(sample,'rb') as source: shutil.copyfileobj(source,target)
        remember(STAGING/'jfk.wav')
        with wave.open(str(sample), 'rb') as source: raw = source.readframes(source.getnframes())
        with (STAGING/'jfk-first-8s.wav').open('xb') as handle:
            with wave.open(handle,'wb') as target:
                target.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'));target.writeframes(raw[:EXCERPT_FRAMES * 2])
        remember(STAGING/'jfk-first-8s.wav')
        assert sha256(STAGING / 'jfk-first-8s.wav') == EXCERPT_SHA256
        (STAGING / 'ggml-base.en.bin').symlink_to(Path(model).resolve())
        remember(STAGING/'ggml-base.en.bin')
    except BaseException:
        unstage();raise


def unstage():
    """Remove only the directory/files whose identities this process created."""
    global _OWNED_STAGING, _OWNED_FILES
    try: info=STAGING.lstat()
    except FileNotFoundError: return
    if not stat.S_ISDIR(info.st_mode) or (info.st_dev,info.st_ino)!=_OWNED_STAGING: return
    for path,identity in _OWNED_FILES.items():
        try: info=path.lstat()
        except FileNotFoundError: continue
        if (info.st_dev,info.st_ino)==identity: path.unlink()
    try: STAGING.rmdir()
    except OSError: pass
    _OWNED_STAGING=None;_OWNED_FILES={}


def source_identity(directory):
    if not directory: return {'checked': False, 'reason': 'no --source-directory supplied'}
    def git(*args): return subprocess.run(['git', '-C', str(directory), *args], capture_output=True, text=True, check=False).stdout.strip()
    return {'checked': True, 'commit': git('rev-parse', 'HEAD'), 'exactTag': git('describe', '--tags', '--exact-match'), 'dirty': bool(git('status', '--porcelain', '--untracked-files=no'))}


def wave_duration(path):
    with wave.open(str(path), 'rb') as stream: return stream.getnframes(), stream.getframerate(), stream.getnchannels(), stream.getsampwidth()


def independent_result(directory, expect_words, duration_ms):
    """Literal public-sentence check; reads published files without the adaptor's parsers."""
    segments = json.loads((directory / 'segments.json').read_text(encoding='utf-8'))
    frames, rate, channels, width = wave_duration(directory / 'captured-audio.wav')
    assert (rate, channels, width) == (16000, 1, 2) and frames * 1000 // rate == duration_ms == segments['audio']['durationMs']
    text = ' '.join(s['text'] for s in segments['segments'])
    assert words(text) == expect_words, (words(text), expect_words)
    srt = (directory / 'captions.srt').read_text(encoding='utf-8').split('\n\n')[:-1]
    assert len(srt) == len(segments['segments'])
    for block, segment in zip(srt, segments['segments']):
        index, timing, *lines = block.split('\n')
        start, end = [sum(int(x) * m for x, m in zip(re.split('[:,]', t), (3600000, 60000, 1000, 1))) for t in timing.split(' --> ')]
        assert (int(index), start, end, '\n'.join(lines)) == (segment['index'] + 1, segment['startMs'], segment['endMs'], segment['text'])
    assert (directory / 'captions.vtt').read_text(encoding='utf-8').startswith('WEBVTT\n\n')
    assert (directory / 'transcript.txt').read_text(encoding='utf-8') == ''.join(s['text'] + '\n' for s in segments['segments'])
    assert segments['review']['accuracyCertified'] is False and segments['review']['humanReviewRequired'] is True
    return {'segments': [(s['startMs'], s['endMs'], s['text']) for s in segments['segments']], 'wordsMatchPublicQuotation': True, 'durationMs': duration_ms}


def independent_review(directory, reference):
    """Recompute the optional caption review from published files with the qualifier's own arithmetic.

    Fractions and literal thresholds stand in for the adaptor's integer formulas, so a shared mistake would
    have to be made twice. The expected flags are editorial defaults, not a claim about caption quality.
    """
    segments = json.loads((directory / 'segments.json').read_text(encoding='utf-8'))
    report = json.loads((directory / 'caption-review.json').read_text(encoding='utf-8'))
    assert report['segmentsSha256'] == sha256(directory / 'segments.json') and report['cueCount'] == len(segments['segments']) == len(report['cues'])
    flagged = 0
    for cue, segment in zip(report['cues'], segments['segments']):
        duration = segment['endMs'] - segment['startMs'];points = len(segment['text'])
        rate = Fraction(points * 1000, duration)
        expected = [name for name, hit in (('short-duration', duration < 1000), ('long-duration', duration > 7000), ('dense-text', rate > 20)) if hit]
        assert (cue['index'], cue['startMs'], cue['endMs'], cue['durationMs'], cue['codePoints'], cue['codePointsPerSecondMilli'], cue['flags']) == \
            (segment['index'], segment['startMs'], segment['endMs'], duration, points, math.floor(rate * 1000), expected), (cue, segment)
        flagged += bool(expected)
    assert report['flaggedCueCount'] == flagged
    review = report['review']
    assert [review[k] for k in ('accuracyCertified', 'accessibilityCertified', 'readabilityCertified', 'passCertified')] == [False] * 4 and review['humanReviewRequired'] is True
    assert [p['file'].rsplit('/', 1)[1] for p in a.read(directory, 'verification.json')['artifacts']] == ['segments.json', 'transcript.txt', 'captions.srt', 'captions.vtt', 'caption-review.json']
    reference_segments = json.loads((reference / 'segments.json').read_text(encoding='utf-8'))['segments']
    assert [(s['startMs'], s['endMs'], s['text']) for s in segments['segments']] == [(s['startMs'], s['endMs'], s['text']) for s in reference_segments]
    for name in ('transcript.txt', 'captions.srt', 'captions.vtt'): assert (directory / name).read_bytes() == (reference / name).read_bytes(), name
    return {'cues': [(c['durationMs'], c['codePoints'], c['codePointsPerSecondMilli'], c['flags']) for c in report['cues']], 'flaggedCues': flagged, 'passCertified': False, 'sameWordsAndTimingAsPlainRun': True}


def independent_segmentation(directory, reference, review=False):
    """Literal cue boundaries and the host-counted target observation, recomputed from published files only.

    The target is a native target: this check records that the three observed cues happen to fit 42 code
    points. It does not assert that any cue always fits, and it asserts no readability or accuracy.
    """
    segments = json.loads((directory / 'segments.json').read_text(encoding='utf-8'))
    assert [(s['startMs'], s['endMs'], s['text']) for s in segments['segments']] == SHORT_CUES, segments['segments']
    assert words(' '.join(s['text'] for s in segments['segments'])) == QUOTATION.split()
    reference_text = json.loads((reference / 'segments.json').read_text(encoding='utf-8'))['segments']
    assert len(reference_text) == 1 and (reference_text[0]['startMs'], reference_text[0]['endMs']) == (0, 11000)
    assert segments['segments'][0]['startMs'] == reference_text[0]['startMs'] and segments['segments'][-1]['endMs'] == reference_text[0]['endMs']
    member = segments['segmentation']
    assert (member['maxSegmentLength'], member['nativeOptions'], member['enforced'], member['cueCount']) == (SHORT_TARGET, ['-ml', '42', '-sow'], False, 3)
    over = sum(1 for s in segments['segments'] if len(s['text']) > SHORT_TARGET)
    assert member['cuesOverTarget'] == over == 0
    srt = (directory / 'captions.srt').read_text(encoding='utf-8')
    assert srt == ''.join(f'{i + 1}\n{clock(s)} --> {clock(e)}\n{t}\n\n' for i, (s, e, t) in enumerate(SHORT_CUES))
    plan = a.read(directory, 'plan.json')
    assert plan['maxSegmentLength'] == SHORT_TARGET and plan['losses'][-1] == a.segmentation.LOSS
    launcher = (directory / 'transcribe-launcher.py').read_text(encoding='utf-8')
    assert "'-osrt', '-ml', '42', '-sow', '-of', 'native'" in launcher
    assert '-ml' not in (directory / 'version-launcher.py').read_text(encoding='utf-8')
    native = json.loads((directory / 'native.json').read_text(encoding='utf-8'))['transcription']
    assert [(n['offsets']['from'], n['offsets']['to']) for n in native] == [(s, e) for s, e, _ in SHORT_CUES]
    out = {'cues': [(s, e, len(t)) for s, e, t in SHORT_CUES], 'cuesOverTarget': over, 'enforced': False, 'sameWordsAsBaseline': True, 'timingCertified': False}
    if review:
        report = json.loads((directory / 'caption-review.json').read_text(encoding='utf-8'))
        for cue, (start, end, text) in zip(report['cues'], SHORT_CUES):
            duration = end - start;rate = Fraction(len(text) * 1000, duration)
            assert (cue['durationMs'], cue['codePoints'], cue['codePointsPerSecondMilli'], cue['flags']) == (duration, len(text), math.floor(rate * 1000), [n for n, hit in (('short-duration', duration < 1000), ('long-duration', duration > 7000), ('dense-text', rate > 20)) if hit]), cue
        assert report['flaggedCueCount'] == 0 and report['flagCounts']['long-duration'] == 0 and report['review']['passCertified'] is False
        out['captionReviewFlaggedCues'] = report['flaggedCueCount']
    return out


def clock(ms): return '%02d:%02d:%02d,%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def refresh(directory):
    receipt = a.read(directory, 'verification.json');receipt['artifacts'] = a.artifacts(directory, a.read(directory, 'plan.json').get('captionReview') is True)
    receipt['evidence'] = {n: a.digest(directory, n) for n in receipt['evidence']};atomic_json(directory / 'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def negative(directory):
    """Rehashed forgeries on a real native run must fail semantic verification."""
    report = {};saved = {p: p.read_bytes() for p in directory.iterdir() if p.is_file()}
    def restore():
        for path in [p for p in directory.iterdir() if p.is_file() and p not in saved]: path.unlink()
        for path, data in saved.items(): path.write_bytes(data)
    cases = [('captionTextWithRefreshedHashes', 'captions.srt', lambda b: b.replace(b'country', b'county', 1)),
        ('webvttTimingWithRefreshedHashes', 'captions.vtt', lambda b: b.replace(b'00:00:11.000', b'00:00:10.000')),
        ('transcriptTextWithRefreshedHashes', 'transcript.txt', lambda b: b.replace(b'fellow', b'fellows')),
        ('segmentEvidenceWithRefreshedHashes', 'segments.json', lambda b: b.replace(b'"endMs": 11000', b'"endMs": 10999')),
        ('reviewWarningRemovedWithRefreshedHashes', 'segments.json', lambda b: b.replace(b'"humanReviewRequired": true', b'"humanReviewRequired": false')),
        ('nativeJsonTimingWithRefreshedHashes', 'native.json', lambda b: b.replace(b'"to": 11000', b'"to": 12000')),
        ('nativeJsonTextWithRefreshedHashes', 'native.json', lambda b: b.replace(b'country', b'county', 1)),
        ('nativeSrtDisagreesWithRefreshedHashes', 'native.srt', lambda b: b.replace(b'country', b'county', 1)),
        ('capturedAudioWithRefreshedHashes', 'captured-audio.wav', lambda b: b[:2000] + bytes([b[2000] ^ 1]) + b[2001:]),
        ('modelIdentityWithRefreshedHashes', 'model.json', lambda b: b.replace(MODEL_SHA256.encode(), b'0' * 64)),
        ('runtimeVersionWithRefreshedHashes', 'version.stdout', lambda b: b'whisper.cpp version: 1.9.4-dev\n'),
        ('forgedLauncherWithRefreshedHashes', 'transcribe-launcher.py', lambda b: b.replace(b'-ng', b'-nf'))]
    for name, target, mutate in cases:
        try:
            path = directory / target;before = path.read_bytes();after = mutate(before);assert after != before, name;path.write_bytes(after);refresh(directory)
            report[name] = refused(lambda: a.verify(directory))['code']
        finally: restore()
    for name, mutation in [('extraClaim',lambda r:r.update(accuracyCertified=True)), ('missingEvidence', lambda r: r['evidence'].pop('native.json')), ('extraEvidence', lambda r: r['evidence'].update({'extra.json': '0' * 64})),
            ('publicationMembership', lambda r: r['artifacts'].pop()), ('runtimeIdentity', lambda r: r.update(runtime='whisper.cpp 1.9.4-dev'))]:
        try:
            receipt = a.read(directory, 'verification.json');mutation(receipt);atomic_json(directory / 'verification.json', receipt)
            report[name] = refused(lambda: a.verify(directory))['code']
        finally: restore()
    try:
        (directory / 'stray.txt').write_text('x');report['strayFile'] = refused(lambda: a.verify(directory))['code']
    finally: restore()
    try:
        (directory / 'caption-review.json').write_text('{}');report['strayCaptionReviewWithoutOption'] = refused(lambda: a.verify(directory))['code']
        refresh(directory);report['strayCaptionReviewWithRefreshedHashes'] = refused(lambda: a.verify(directory))['code']
    finally: restore()
    for key,value in [('accuracyCertified',True),('humanReviewRequired',False),('verified',1),('segments',1.0),('extra','claim')]:
        try:
            result=a.read(directory,'result.json');result[key]=value;atomic_json(directory/'result.json',result)
            report['result-'+key]=refused(lambda:a.verify(directory),'VERIFICATION_FAILED')['code']
        finally:restore()
    try:
        (directory/'orphan.metadata.json').write_text('{}')
        report['orphanMetadata']=refused(lambda:a.verify(directory),'VERIFICATION_FAILED')['code']
    finally:restore()
    assert a.verify(directory)['verified'];return report


def negative_review(directory):
    """Rehashed forgeries of the optional caption review on a real native run must fail semantic verification."""
    report = {};saved = {p: p.read_bytes() for p in directory.iterdir() if p.is_file()}
    def restore():
        for path in [p for p in directory.iterdir() if p.is_file() and p not in saved]: path.unlink()
        for path, data in saved.items(): path.write_bytes(data)
    def edited(change):
        def mutate(b):
            value = json.loads(b);change(value);return a.encode_json(value)
        return mutate
    cases = [('metricDuration', edited(lambda r: r['cues'][0].update(durationMs=10999))), ('metricCodePoints', edited(lambda r: r['cues'][0].update(codePoints=106))),
        ('metricRate', edited(lambda r: r['cues'][0].update(codePointsPerSecondMilli=9728))), ('flagRemoved', edited(lambda r: r['cues'][0].update(flags=[]))),
        ('flagAdded', edited(lambda r: r['cues'][0].update(flags=['long-duration', 'dense-text']))), ('flagCounts', edited(lambda r: r['flagCounts'].update(**{'long-duration': 0}))),
        ('flaggedCueCount', edited(lambda r: r.update(flaggedCueCount=0))), ('cueRemoved', edited(lambda r: r['cues'].pop())), ('segmentsHash', edited(lambda r: r.update(segmentsSha256='0' * 64))),
        ('threshold', edited(lambda r: r['policy'].update(longDurationAboveMs=12000))), ('passClaim', edited(lambda r: r['review'].update(passCertified=True))),
        ('humanReviewDropped', edited(lambda r: r['review'].update(humanReviewRequired=False))), ('unknownRootKey', edited(lambda r: r.update(verdict='good'))),
        ('unknownCueKey', edited(lambda r: r['cues'][0].update(severity=1))), ('missingMember', edited(lambda r: r.pop('policy'))),
        ('boolAsInteger', edited(lambda r: r['review'].update(accuracyCertified=0))), ('integerAsFloat', edited(lambda r: r['cues'][0].update(endMs=11000.0))),
        ('integerAsString', edited(lambda r: r['cues'][0].update(codePoints='107'))), ('nonCanonicalBytes', lambda b: json.dumps(json.loads(b)).encode()), ('emptyReport', lambda b: b'')]
    for name, mutate in cases:
        try:
            path = directory / 'caption-review.json';before = path.read_bytes();after = mutate(before);assert after != before, name;path.write_bytes(after);refresh(directory)
            report[name] = refused(lambda: a.verify(directory), 'VERIFICATION_FAILED')['code']
        except SchemaxisError as error:
            assert error.fault.code == 'VERIFICATION_FAILED', error.fault.to_dict();report[name] = error.fault.code   # a malformed file may fail while refreshing
        finally: restore()
    for name, mutation in [('summaryForged', lambda r: r['captionReview'].update(flaggedCues=0)), ('summaryDropped', lambda r: r.pop('captionReview')), ('artifactCountReduced', lambda r: r.update(artifacts=4)),
            ('verdictAdded', lambda r: r['captionReview'].update(passed=True))]:
        try:
            result = a.read(directory, 'result.json');mutation(result);atomic_json(directory / 'result.json', result)
            report['result-' + name] = refused(lambda: a.verify(directory), 'VERIFICATION_FAILED')['code']
        finally: restore()
    try:
        (directory / 'caption-review.json').unlink()
        receipt = a.read(directory, 'verification.json');receipt['artifacts'] = a.artifacts(directory)   # the four standard publications, refreshed
        atomic_json(directory / 'verification.json', receipt)
        from schemaxis.publication_metadata import finalise
        finalise(directory)
        report['reportMissingWithRefreshedHashes'] = refused(lambda: a.verify(directory), 'VERIFICATION_FAILED')['code']
    finally: restore()
    try:
        receipt = a.read(directory, 'verification.json');receipt['artifacts'].pop();atomic_json(directory / 'verification.json', receipt)
        report['reportOmittedFromReceipt'] = refused(lambda: a.verify(directory), 'VERIFICATION_FAILED')['code']
    finally: restore()
    try:
        authored = a.read(directory, 'authored.json');authored['captionReview'] = False;atomic_json(directory / 'authored.json', authored);atomic_json(directory / 'plan.json', a.plan(authored));refresh(directory)
        report['optionDroppedWithRefreshedHashes'] = refused(lambda: a.verify(directory), 'VERIFICATION_FAILED')['code']
    finally: restore()
    assert a.verify(directory)['verified'];return report


def negative_segmentation(directory):
    """Rehashed forgeries of the segmentation evidence on a real native run must fail semantic verification."""
    report = {};saved = {p: p.read_bytes() for p in directory.iterdir() if p.is_file()}
    def restore():
        for path in [p for p in directory.iterdir() if p.is_file() and p not in saved]: path.unlink()
        for path, data in saved.items(): path.write_bytes(data)
    def edited(change):
        def mutate(b):
            value = json.loads(b);change(value);return a.encode_json(value)
        return mutate
    cases = [('enforcedClaimed', 'segments.json', edited(lambda r: r['segmentation'].update(enforced=True))),
        ('overTargetCountForged', 'segments.json', edited(lambda r: r['segmentation'].update(cuesOverTarget=1))),
        ('targetRewritten', 'segments.json', edited(lambda r: r['segmentation'].update(maxSegmentLength=200))),
        ('memberRemoved', 'segments.json', edited(lambda r: r.pop('segmentation'))),
        ('cueBoundaryMoved', 'segments.json', lambda b: b.replace(b'"endMs": 5410', b'"endMs": 5400')),
        ('nativeCueBoundaryMoved', 'native.json', lambda b: b.replace(b'"to": 5410', b'"to": 5400', 1)),
        ('launcherWithoutOption', 'transcribe-launcher.py', lambda b: b.replace(b"'-ml', '42', '-sow', ", b'')),
        ('launcherWithOtherTarget', 'transcribe-launcher.py', lambda b: b.replace(b"'-ml', '42'", b"'-ml', '43'")),
        ('authoredTargetDropped', 'authored.json', edited(lambda r: r.pop('maxSegmentLength'))),
        ('planTargetAsBoolean', 'plan.json', edited(lambda r: r.update(maxSegmentLength=True))),
        ('resultSummaryForged', 'result.json', edited(lambda r: r['segmentation'].update(cuesOverTarget=2))),
        ('resultSummaryDropped', 'result.json', edited(lambda r: r.pop('segmentation')))]
    for name, target, mutate in cases:
        try:
            path = directory / target;before = path.read_bytes();after = mutate(before);assert after != before, name;path.write_bytes(after);refresh(directory)
            report[name] = refused(lambda: a.verify(directory), 'VERIFICATION_FAILED')['code']
        finally: restore()
    assert a.verify(directory)['verified'];return report


def pre_native(directory, executable, document):
    results = {}
    def run(name, **change):
        bad = copy.deepcopy(document)
        for path, value in change.items():
            target = bad
            *parents, leaf = path.split('/')
            for part in parents: target = target[part]
            target[leaf] = value
        return lambda: a.run(bad, directory / name, executable=executable, timeout=60)
    results['audioPinMismatch'] = refused(run('audio-pin', **{'audio/sha256': '0' * 64}), 'AUDIO_HASH_MISMATCH')['code']
    results['modelPinMismatch'] = refused(run('model-pin', **{'model/sha256': '0' * 64}), 'MODEL_HASH_MISMATCH')['code']
    results['absentModel'] = refused(run('absent-model', **{'model/path': str(STAGING / 'absent.bin')}), 'INVALID_MODEL')['code']
    for name in ('audio-pin', 'model-pin', 'absent-model'): assert not (directory / name / 'version-launcher.py').exists()
    results['relativeAudio'] = refused(run('relative', **{'audio/path': 'jfk.wav'}), 'INVALID_AUDIO_SOURCE')['code']
    results['languageCode'] = refused(run('language', language='English'), None)['code']
    wrong = STAGING / 'wrong-rate.wav'
    try:
        with wave.open(str(wrong), 'wb') as stream:
            stream.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'));stream.writeframes(bytes(16000))
        results['wrongSampleRate'] = refused(run('rate', **{'audio/path': str(wrong), 'audio/sha256': sha256(wrong)}), 'INVALID_AUDIO_DATA')['code']
    finally: wrong.unlink(missing_ok=True)
    return results


def native_probes(directory, executable, document):
    """Observed native behaviour on non-speech and non-model input; outcomes are recorded, not asserted as accuracy."""
    report = {}
    silence = STAGING / 'silence.wav';bad_model = STAGING / 'not-a-model.bin'
    try:
        with wave.open(str(silence), 'wb') as stream:
            stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'));stream.writeframes(bytes(64000))
        bad_model.write_bytes(b'not a ggml model\n' * 64)
        silent = copy.deepcopy(document);silent['audio'] = {'path': str(silence), 'sha256': sha256(silence)}
        try:
            result = a.run(silent, directory / 'silence', executable=executable, timeout=120)
            segments = json.loads((directory / 'silence' / 'segments.json').read_text())
            report['fourSecondSilence'] = {'outcome': 'verified', 'segments': [s['text'] for s in segments['segments']], 'note': 'structurally valid; whisper.cpp still emitted text for silence, so content needs human review'}
        except SchemaxisError as error: report['fourSecondSilence'] = {'outcome': 'refused', 'code': error.fault.code}
        invalid = copy.deepcopy(document);invalid['model'] = {'path': str(bad_model), 'sha256': sha256(bad_model)}
        fault = refused(lambda: a.run(invalid, directory / 'bad-model', executable=executable, timeout=60))
        assert not (directory / 'bad-model' / 'segments.json').exists() and not (directory / 'bad-model' / 'captions.srt').exists()
        report['nonModelBytesWithMatchingPin'] = {'outcome': 'refused', 'code': fault['code']}
    finally:
        silence.unlink(missing_ok=True);bad_model.unlink(missing_ok=True)
    unaligned=directory/'eight-plus-five-ms.wav'
    with wave.open(str(STAGING/'jfk.wav'),'rb') as source:raw=source.readframes(128080)
    with wave.open(str(unaligned),'wb') as target:
        target.setparams((1,2,16000,0,'NONE','not compressed'));target.writeframes(raw)
    cut=copy.deepcopy(document);cut['audio']={'path':str(unaligned),'sha256':sha256(unaligned)}
    try:
        result=a.run(cut,directory/'unaligned',executable=executable,timeout=120)
        cues=json.loads((directory/'unaligned/segments.json').read_text())['segments']
        report['unaligned8005ms']={'outcome':'verified','endMs':cues[-1]['endMs'],'accuracyCertified':False}
    except SchemaxisError as error:report['unaligned8005ms']={'outcome':'refused','code':error.fault.code}
    return report


def interrupted(directory, document):
    """Deterministic process-control wrappers; never counted as native transcription."""
    wrapper = directory / 'slow-runtime.py';marker = directory / 'slow.pid'
    wrapper.write_text('#!' + sys.executable + '\nimport os,time\nfrom pathlib import Path\nPath(' + repr(str(marker)) + ').write_text(str(os.getpid()))\ntime.sleep(30)\n');wrapper.chmod(0o700)
    outcomes = {}
    for action in ('timeout', 'cancel'):
        if marker.exists(): marker.unlink()
        cancel = threading.Event()
        def trigger():
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline: time.sleep(.01)
            if marker.exists(): cancel.set()
        thread = threading.Thread(target=trigger, daemon=True) if action == 'cancel' else None
        if thread: thread.start()
        try:
            with allocation({'threads': 1, 'ranks': 1}, cancel):
                outcomes[action] = refused(lambda: a.run(document, directory / ('inflight-' + action), executable=str(wrapper), timeout=8 if thread else 1.0), 'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')['code']
        finally:
            if thread: thread.join(6)
        assert marker.exists(), 'lifecycle probe did not launch an owned child'
        try: os.kill(int(marker.read_text()), 0)
        except ProcessLookupError: pass
        else: raise AssertionError('owned process survived ' + action)
    return outcomes


CORRECTION_STAGING = Path('/tmp/schemaxis-whispercpp-corrections')
CORRECTION_BASIS = '0fb466aec743b3a236655d7b29e4d3a1003bcd5230abcd4276af56b08cb4ba04'
CORRECTION_EXPECTED = ['And so, my fellow Americans: ask not what', 'your country can do for you; ask what you', 'can do for your country.']
CORRECTION_TIMES = [(0, 5410), (5410, 9040), (9040, 11000)]


class Collector(html.parser.HTMLParser):
    """Independent HTML readback: paragraph texts and table rows, no schemaxis code."""
    def __init__(self):
        super().__init__(); self.paragraphs = []; self.rows = []; self.cell = None; self.row = None; self.para = None
    def handle_starttag(self, tag, attrs):
        if tag == 'p': self.para = ''
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
    paragraphs = [text(p) for p in body.findall(namespace + 'p')]
    rows = [[text(cell) for cell in row.findall(namespace + 'tc')] for table in body.findall(namespace + 'tbl') for row in table.findall(namespace + 'tr')]
    return paragraphs, rows


def parse_srt(text):
    cues = []
    for block in text.strip('\n').split('\n\n'):
        number, clock, words = block.split('\n', 2)
        start, end = (sum(int(x) * m for x, m in zip(re.split('[:,]', part), (3600000, 60000, 1000, 1))) for part in clock.split(' --> '))
        cues.append((int(number), start, end, words))
    return cues


def correction_documents():
    stem = ROOT / 'examples/schemaxis'
    return {name: json.loads((stem / f'whispercpp-corrections{suffix}.json').read_text()) for name, suffix in
            (('corrected', ''), ('unchanged', '-unchanged'), ('workflow', '-workflow'), ('blank', '-blank-invalid'), ('stale', '-stale-invalid'))}


def stage_corrections():
    fixture = ROOT / 'examples/schemaxis/whispercpp-corrections-fixtures/jfk-short-cues-segments.json'
    assert sha256(fixture) == CORRECTION_BASIS, 'the committed real native draft changed'
    CORRECTION_STAGING.mkdir(mode=0o700)       # exclusive: a pre-existing path is another run's and is never replaced
    shutil.copyfile(fixture, CORRECTION_STAGING / fixture.name)
    return CORRECTION_STAGING / fixture.name


def readback_publications(directory, corrected=True):
    """Independent text, timing and status readback of the published files; no corrections.py code is used."""
    reviewed = json.loads((directory / 'reviewed-segments.json').read_text()); ledger = json.loads((directory / 'corrections.json').read_text())
    srt = parse_srt((directory / 'captions.srt').read_text())
    expected = CORRECTION_EXPECTED if corrected else ['And so my fellow Americans, ask not what', 'your country can do for you, ask what you', 'can do for your country.']
    assert reviewed['version'] == 'schemaxis.timedtext.reviewed/1'
    assert [(s['startMs'], s['endMs']) for s in reviewed['segments']] == CORRECTION_TIMES, 'timings must be the native draft timings'
    assert [s['text'] for s in reviewed['segments']] == expected
    assert [(n, st, en, w) for n, st, en, w in srt] == [(i + 1, CORRECTION_TIMES[i][0], CORRECTION_TIMES[i][1], expected[i]) for i in range(3)]
    assert (directory / 'transcript.txt').read_text() == ''.join(t + '\n' for t in expected)
    vtt = (directory / 'captions.vtt').read_text(); assert vtt.startswith('WEBVTT\n\n') and all(t in vtt for t in expected)
    status = 'human-corrected' if corrected else 'human-reviewed-unchanged'
    assert (reviewed['review']['status'], ledger['status']) == (status, status)
    assert reviewed['review']['basis']['sha256'] == ledger['basis']['sha256'] == CORRECTION_BASIS
    assert (reviewed['review']['accuracyCertified'], reviewed['review']['identityVerified'], ledger['identityVerified']) == (False, False, False)
    assert ledger['reviewedSha256'] == sha256(directory / 'reviewed-segments.json')
    assert [e['index'] for e in ledger['entries']] == ([0, 1] if corrected else [])
    return {'status': status, 'texts': expected, 'times': CORRECTION_TIMES, 'ledgerEntries': len(ledger['entries'])}


def refresh_hashes(directory):
    receipt = corr.read_json(directory, 'verification.json'); plan = corr.read_json(directory, 'plan.json')
    receipt['artifacts'] = corr.artifacts(directory, corr.wants_review(plan)); receipt['evidence'] = {n: corr.digest(directory, n) for n in receipt['evidence']}
    atomic_json(directory / 'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def correction_negatives(directory, documents, draft):
    outcomes = {}
    def attempt(label, mutate, code):
        document = copy.deepcopy(documents['corrected']); document['draft']['path'] = str(draft); mutate(document)
        fault = refused(lambda: corr.run(document, directory / label, timeout=30), code); outcomes[label] = {'code': fault['code'], 'location': fault['location'], 'recovery': bool(fault.get('recovery'))}
        assert fault.get('recovery'), label
        assert not [n for n in ('reviewed-segments.json', 'captions.srt') if (directory / label / n).exists()], 'nothing may be published after a refusal'
    attempt('stale', lambda d: d.update(basisSha256='1' * 64), 'CORRECTIONS_STALE')
    attempt('index', lambda d: d['corrections'][1].update(index=3), 'CORRECTION_INDEX_INVALID')
    attempt('noop', lambda d: d['corrections'][1].update(text='your country can do for you, ask what you'), 'CORRECTION_NOOP')
    attempt('duplicate', lambda d: d['corrections'].append({'index': 0, 'text': 'x'}), 'CORRECTION_DUPLICATE')
    attempt('blank', lambda d: d['corrections'][0].update(text='   '), 'CORRECTION_TEXT_INVALID')
    attempt('markup', lambda d: d['corrections'][0].update(text='a <b> c'), 'CORRECTION_TEXT_INVALID')
    attempt('status', lambda d: d['review'].update(status='human-reviewed-unchanged'), 'CORRECTIONS_STATUS_CONFLICT')
    attempt('unknown-key', lambda d: d['corrections'][0].update(startMs=1), 'UNKNOWN_ARGUMENT')
    attempt('note', lambda d: d['review'].update(note='two  spaces'), 'CORRECTIONS_NOTE_INVALID')
    return outcomes


def correction_tampering(directory, documents, draft):
    """Every probe refreshes all ordinary hashes, so only independent replay can notice the change."""
    document = copy.deepcopy(documents['corrected']); document['draft']['path'] = str(draft)
    corr.run(document, directory, timeout=30)
    saved = {p: p.read_bytes() for p in directory.iterdir() if p.is_file()}; probes = {}
    def restore():
        for path in [p for p in directory.iterdir() if p.is_file() and p not in saved]: path.unlink()
        for path, data in saved.items(): path.write_bytes(data)
    def probe(name, mutate):
        try:
            path = directory / name; original = path.read_bytes(); changed = mutate(original); assert changed != original, 'vacuous probe ' + name + ':' + mutate.__name__
            path.write_bytes(changed); refresh_hashes(directory)
            fault = refused(lambda: corr._native_verify(directory), 'VERIFICATION_FAILED'); probes[name + ':' + mutate.__name__] = fault['code']
        finally: restore()
    def text(b): return b.replace(b'ask not what', b'ask all what', 1)
    def time_(b): return b.replace(b'5410', b'5411', 1) if b'5410' in b else b.replace(b'05,410', b'05,411').replace(b'05.410', b'05.411')
    def status(b): return b.replace(b'human-corrected', b'human-reviewed-unchanged')
    def identity(b): return b.replace(b'"identityVerified": false', b'"identityVerified": true')
    def ledger_text(b): return b.replace(b'ask not what"', b'ask all what"', 1)
    def basis(b): return b.replace(CORRECTION_BASIS.encode(), b'2' * 64)
    def note(b): return json.dumps({**json.loads(b), 'review': {**json.loads(b)['review'], 'note': 'An altered author declaration.'}}, indent=2).encode()
    for name, mutate in (('reviewed-segments.json', text), ('reviewed-segments.json', time_), ('reviewed-segments.json', status), ('reviewed-segments.json', identity), ('transcript.txt', text),
                         ('captions.srt', time_), ('captions.vtt', text), ('corrections.json', ledger_text), ('corrections.json', basis), ('captured-draft.json', text), ('captures.json', basis),
                         ('authored.json', note), ('result.json', status)):
        probe(name, mutate)
    try:
        (directory / 'transcribe-launcher.py').write_text('native evidence has no place here'); refused(lambda: corr._native_verify(directory), 'VERIFICATION_FAILED'); probes['launcher-membership'] = 'VERIFICATION_FAILED'
    finally: restore()
    try:
        planted = directory / '.dispatch' / 'transcribe'; planted.mkdir(parents=True); marker = directory.parent / 'planted-dispatch-ran.marker'
        (planted / 'replay-x.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("ran")\n')
        refused(lambda: corr._native_verify(directory), 'VERIFICATION_FAILED'); probes['plantedDispatchMember'] = 'VERIFICATION_FAILED'; assert not marker.exists(), 'verification executed a planted script'
    finally: shutil.rmtree(directory / '.dispatch', ignore_errors=True); restore()
    corr._native_verify(directory); probes['restored'] = 'verified'
    return probes


def run_pandoc_workflow(directory, documents, draft, pandoc, sentinel, name, document):
    graph = copy.deepcopy(documents['workflow']); graph['operations'][0]['document'] = document
    locations = {'whispercpp': str(sentinel), 'pandoc': str(pandoc)}
    result = workflow.execute(graph, directory / name, locations=locations, timeout=120)
    assert result['status'] == 'succeeded', result['status']; assert workflow.verify(directory / name)['verified']
    html_path = next((directory / name / 'report').rglob('report.html')); docx_path = next((directory / name / 'report').rglob('report.docx'))
    return html_path, docx_path


def corrections_acceptance(directory, pandoc):
    started = time.monotonic(); documents = correction_documents(); report = {'verified': False, 'route': corr.VERSION, 'nativeQualified': False, 'hostOnly': True, 'pid': os.getpid()}
    qualification = ROOT / 'src/schemaxis/adaptors/whispercpp/qualification.json'; before = sha256(qualification)
    version = subprocess.run([str(pandoc), '--version'], capture_output=True, text=True, timeout=30).stdout.splitlines()[0]
    assert version == 'pandoc 3.12.1', version
    report['pandoc'] = {'version': version, 'sha256': sha256(pandoc)}
    sentinel = directory / 'whisper-cli-sentinel'; marker = directory / 'whisper-launched.log'
    sentinel.write_text('#!/bin/sh\necho "launched $$ $@" >> ' + str(marker) + '\nexit 99\n'); sentinel.chmod(0o700)
    draft = stage_corrections()
    try:
        report['draft'] = {'sha256': sha256(draft), 'bytes': draft.stat().st_size, 'provenance': 'real native whisper.cpp 1.9.5-dev output (public jfk.wav, ggml-base.en, maxSegmentLength 42); retained fixture, no recognition run here'}
        os.environ['SCHEMAXIS_WHISPERCPP'] = str(sentinel); os.environ['PATH'] = '/nonexistent'
        corrected = corr.run(documents['corrected'], directory / 'corrected', timeout=30)
        assert corrected['verified'] and corrected['nativeProcesses'] == 0 and corrected['reviewStatus'] == 'human-corrected'
        report['corrected'] = {'result': corrected, 'readback': readback_publications(directory / 'corrected')}
        unchanged = corr.run(documents['unchanged'], directory / 'unchanged', timeout=30)
        report['unchanged'] = {'result': unchanged, 'readback': readback_publications(directory / 'unchanged', corrected=False)}
        names = {p.name for p in (directory / 'corrected').iterdir()}
        assert not [n for n in names if any(x in n for x in ('launcher', 'submission', 'native', 'runtime', 'model', '.stdout', '.stderr'))], names
        report['negatives'] = correction_negatives(directory / 'negatives', documents, draft)
        report['tampering'] = correction_tampering(directory / 'tamper', documents, draft)
        for variant, document in (('corrected', documents['corrected']), ('unchanged', documents['unchanged'])):
            html_path, docx_path = run_pandoc_workflow(directory, documents, draft, pandoc, sentinel, 'pandoc-' + variant, document)
            collector = Collector(); collector.feed(html_path.read_text()); docx_paragraphs, docx_rows = docx_text(docx_path)
            status = 'human-corrected' if variant == 'corrected' else 'human-reviewed-unchanged'
            expected = CORRECTION_EXPECTED if variant == 'corrected' else readback_publications(directory / 'unchanged', corrected=False)['texts']
            rows = [[str(a), str(b), t] for (a, b), t in zip(CORRECTION_TIMES, expected)]
            for label, paragraphs, table in (('html', collector.paragraphs, collector.rows), ('docx', docx_paragraphs, docx_rows)):
                provenance = next(p for p in paragraphs if p.startswith('Status: '))
                assert provenance.startswith(f'Status: {status}, declared by the author of the corrections.'), provenance[:120]
                assert 'not verified or certified' in provenance and CORRECTION_BASIS in provenance and 'a person has not reviewed it' not in provenance
                assert table == [['Start (ms)', 'End (ms)', 'Text'], *rows], (label, table)
            report['pandoc-' + variant] = {'html': str(html_path.relative_to(directory)), 'docx': str(docx_path.relative_to(directory)), 'status': status, 'rows': rows,
                                         'readback': 'html and docx paragraphs and tables read with html.parser and zipfile/ElementTree'}
        stale = copy.deepcopy(documents['stale']); assert stale['draft']['path'] == str(draft)
        report['staleExample'] = refused(lambda: corr.run(stale, directory / 'stale-example', timeout=30), 'CORRECTIONS_STALE')['code']
        refused(lambda: corr.plan(documents['blank']), 'CORRECTION_TEXT_INVALID')
        assert not marker.exists(), 'whisper-cli was launched: ' + marker.read_text()
        assert sha256(draft) == CORRECTION_BASIS, 'the machine draft was modified'
        assert sha256(qualification) == before and corr.VERSION not in json.loads(qualification.read_text())['routes'], 'no qualification receipt may exist for the host-only route'
        report['noNativeLaunch'] = {'sentinel': str(sentinel.name), 'launchLogExists': False, 'nativeProcessesInResults': 0}
        report['verified'] = True
    finally:
        report['elapsedSeconds'] = round(time.monotonic() - started, 1)
        shutil.rmtree(CORRECTION_STAGING, ignore_errors=True)
        atomic_json(directory / 'corrections-acceptance.json', report)
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--whisper-cli', type=Path, help='absolute whisper.cpp 1.9.5 whisper-cli')
    parser.add_argument('--model', type=Path, help='local ggml-base.en.bin pinned by SHA-256')
    parser.add_argument('--sample', type=Path, help='public whisper.cpp samples/jfk.wav')
    parser.add_argument('--corrections-only', action='store_true', help='run only the host-only corrections acceptance (needs --pandoc, no whisper.cpp)')
    parser.add_argument('--pandoc', type=Path, help='absolute official Pandoc 3.12.1 binary for the corrections acceptance')
    parser.add_argument('--source-directory', type=Path, help='optional release checkout to record commit/tag identity')
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--register', action='store_true', help='retain a successful receipt in the adaptor package')
    args = parser.parse_args()
    if args.corrections_only:
        if not args.pandoc: parser.error('--corrections-only requires --pandoc')
        directory = args.output_directory.resolve();directory.mkdir(parents=True, exist_ok=False)
        return corrections_acceptance(directory, args.pandoc.resolve())
    if not (args.whisper_cli and args.model and args.sample): parser.error('--whisper-cli, --model and --sample are required for native transcription qualification')
    directory = args.output_directory.resolve();directory.mkdir(parents=True, exist_ok=False)
    executable = str(args.whisper_cli.resolve());locations = {'whispercpp': executable};report = {'verified': False}
    started = time.monotonic()
    stage(args.sample, args.model)
    try:
        report['executable'] = {'sha256': sha256(executable), 'bytes': Path(executable).stat().st_size}
        report['source'] = source_identity(args.source_directory)
        report['fixtures'] = {'sampleSha256': SAMPLE_SHA256, 'excerptSha256': EXCERPT_SHA256, 'modelSha256': MODEL_SHA256,
            'provenance': 'jfk.wav is the public sample in the whisper.cpp repository; the excerpt is its first 128000 frames; neither is committed here'}
        receipt = qualify(a.VERSION, directory / 'kit', native=True, root=ROOT, locations=locations, timeout=120, wall_timeout=300)
        report['native'] = {'verified': receipt['verified'], 'cases': [c['id'] for c in receipt['cases']], 'runtimes': [c['runtime'] for c in receipt['cases']], 'lifecycle': receipt['lifecycle']}
        _, _, entry = route_materials(a.VERSION)
        report['independent'] = {}
        for case, expect, ms in zip(entry['development']['cases'], (QUOTATION, ' '.join(QUOTATION.split()[:14]), QUOTATION), (11000, 8000, 11000)):
            report['independent'][case['id']] = independent_result(directory / 'kit' / case['id'], expect.split(), ms)
        review_case = entry['development']['cases'][2];assert review_case['id'] == 'jfk-caption-review'
        report['captionReview'] = independent_review(directory / 'kit' / review_case['id'], directory / 'kit' / entry['development']['cases'][0]['id'])
        baseline = directory / 'kit' / entry['development']['cases'][0]['id']
        short_case, short_review_case = entry['development']['cases'][3:5];assert (short_case['id'], short_review_case['id']) == ('jfk-short-cues', 'jfk-short-cues-review')
        report['segmentation'] = {'plain': independent_segmentation(directory / 'kit' / short_case['id'], baseline),
            'withCaptionReview': independent_segmentation(directory / 'kit' / short_review_case['id'], baseline, review=True)}
        document = case_document(entry, entry['development']['cases'][0], ROOT)
        report['negative'] = negative(baseline)
        report['negativeCaptionReview'] = negative_review(directory / 'kit' / review_case['id'])
        report['negativeSegmentation'] = negative_segmentation(directory / 'kit' / short_case['id'])
        report['preNative'] = pre_native(directory / 'pre', executable, document)
        report['nativeProbes'] = native_probes(directory / 'probes', executable, document)
        mutable = STAGING / 'mutable.wav'
        try:
            shutil.copyfile(STAGING / 'jfk-first-8s.wav', mutable)
            study = copy.deepcopy(document);study['audio'] = {'path': str(mutable)}
            graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'transcript', 'document': study}]}
            first = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=120);assert workflow.verify(directory / 'workflow')['verified']
            second = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=120, resume=True);assert second['jobs'][0]['reused']
            raw = bytearray(mutable.read_bytes());raw[-2] ^= 1;mutable.write_bytes(raw)
            third = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=120, resume=True)
            assert not third['jobs'][0]['reused'];assert workflow.verify(directory / 'workflow')['verified']
            report['workflow'] = {'status': first['status'], 'unchangedReused': True, 'changedSamePathAudioReused': False}
        finally: mutable.unlink(missing_ok=True)
        report['inflightLifecycle'] = interrupted(directory, document)
        if args.register: register(directory / 'kit/qualification.json')
        report['registered'] = bool(args.register)
        report['verified'] = True
    finally:
        report['elapsedSeconds'] = round(time.monotonic() - started, 1)
        unstage()
        atomic_json(directory / 'acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
