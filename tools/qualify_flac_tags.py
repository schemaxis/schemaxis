#!/usr/bin/env python3
"""Bounded native acceptance of the optional FLAC recording labels (title, artist, description) with FLAC 1.5 `flac` and `metaflac`.

Labels are read back from the real published FLAC by independent means that do not use the adaptor: `metaflac --no-utf8-convert
--show-tag` and a literal little-endian binary reader of the VORBIS_COMMENT block, both compared with hand-written literal byte
strings. Every PCM byte of each archive is decoded again by this tool's own `flac -d` and compared with the independently parsed
fixture WAV. The tool also compares absent-label behaviour byte for byte with the pre-change adaptor, verifies genuine old untagged
receipts read-only, forges comments with real `flac` output while refreshing every receipt hash, checks inclusive limits and
refusals before any native process, drives the real CLI, and runs SoX conform -> labelled archive -> PCM16 reuse when SoX is given.

Direct native children (flac, metaflac, sox) are recorded with their PIDs in `probeProcesses`; the Python tool, the CLI processes
it supervises and the processes the adaptor starts through its fixed launcher are reported separately and never mistaken for them.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import time

from schemaxis.adaptor_conformance import qualify
from schemaxis.adaptors.flac import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis import workflow

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/flac'
PROCESSES = []
ENCODE = ['-8', '-V', '-s', '-w', '--no-padding', '--no-seektable', '--no-preserve-modtime', '--force-raw-format', '--endian=little', '--sign=signed']
DEADLINE_SECONDS = 1500
NATIVE_ENV = {'LC_ALL': 'C', 'LANG': 'C'}

# hand-written literal labels and their UTF-8 bytes (not derived from the adaptor or the example files)
ASCII = {'title': 'Plain title', 'artist': 'Ann Artist', 'description': 'A note'}
ASCII_LINES = [b'TITLE=Plain title', b'ARTIST=Ann Artist', b'DESCRIPTION=A note']
UNICODE = {'title': 'Café du Müller – 日本語メモ', 'artist': 'Zoë Núñez', 'description': 'k=v; x==y'}
UNICODE_LINES = [b'TITLE=Caf\xc3\xa9 du M\xc3\xbcller \xe2\x80\x93 \xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\xe3\x83\xa1\xe3\x83\xa2', b'ARTIST=Zo\xc3\xab N\xc3\xba\xc3\xb1ez', b'DESCRIPTION=k=v; x==y']


def native(name, command, cwd, timeout=60, env=None, expect=0, kind='native'):
    """Run one probe process directly and keep its real PID, argv, deadline and exit status."""
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        PROCESSES.append({'name': name, 'kind': kind, 'pid': process.pid, 'timeoutSeconds': timeout, 'command': [Path(command[0]).name, *map(str, command[1:])], 'exitCode': 'timeout'})
        raise
    PROCESSES.append({'name': name, 'kind': kind, 'pid': process.pid, 'timeoutSeconds': timeout, 'command': [Path(command[0]).name, *map(str, command[1:])], 'exitCode': process.returncode})
    assert process.returncode == expect, (name, process.returncode, err[-300:])
    return out if expect == 0 else out + err


def refused(action, code='VERIFICATION_FAILED'):
    try:
        action()
    except SchemaxisError as error:
        assert error.fault.code == code, error.fault.to_dict()
        return error.fault
    raise AssertionError('invalid evidence accepted (expected %s)' % code)


def tree_hash(directory):
    digest = hashlib.sha256()
    for path in sorted(p for p in Path(directory).rglob('*') if p.is_file()):
        digest.update(str(path.relative_to(directory)).encode() + b'\0' + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


# ---------------------------------------------------------------- independent readers (no adaptor code)
def wav_data(data):
    assert data[:4] == b'RIFF' and data[8:12] == b'WAVE'
    offset, fmt = 12, None
    while offset + 8 <= len(data):
        kind, size = data[offset:offset + 4], struct.unpack_from('<I', data, offset + 4)[0]
        if kind == b'fmt ':
            fmt = struct.unpack_from('<HHIIHH', data, offset + 8)
        if kind == b'data':
            return fmt, data[offset + 8:offset + 8 + size]
        offset += 8 + size + (size & 1)
    raise AssertionError('no data chunk')


def metadata_blocks(data):
    assert data[:4] == b'fLaC'
    offset, blocks = 4, []
    while True:
        last, kind, size = data[offset] >> 7, data[offset] & 0x7f, int.from_bytes(data[offset + 1:offset + 4], 'big')
        blocks.append((kind, data[offset + 4:offset + 4 + size]))
        offset += 4 + size
        if last:
            return blocks


def literal_comments(data):
    """(vendor, [raw entries]) of the single VORBIS_COMMENT block, read with plain struct arithmetic."""
    blocks = metadata_blocks(data)
    assert [kind for kind, _ in blocks] == [0, 4], [kind for kind, _ in blocks]
    body = blocks[1][1]
    length = struct.unpack_from('<I', body, 0)[0]
    count = struct.unpack_from('<I', body, 4 + length)[0]
    offset, lines = 8 + length, []
    for _ in range(count):
        size = struct.unpack_from('<I', body, offset)[0]
        lines.append(body[offset + 4:offset + 4 + size])
        offset += 4 + size
    assert offset == len(body)
    return body[4:4 + length], lines


def streaminfo_md5(data):
    return data[26:42].hex()


def metaflac_tag(metaflac, path, field, work):
    return native('metaflac-show-tag-' + field.lower(), [metaflac, '--no-utf8-convert', '--show-tag=' + field, str(path)], work, timeout=30, env=NATIVE_ENV)


def independent_decode(flac, flac_path, work, name):
    target = Path(work) / (name + '-independent.raw')
    target.unlink(missing_ok=True)
    native('independent-decode-' + name, [flac, '-d', '-s', '-w', '--no-preserve-modtime', '--force-raw-format', '--endian=little', '--sign=signed', '-o', str(target), str(flac_path)], work, timeout=60)
    return target.read_bytes()


def flac_encode(flac, work, name, pcm, rate, channels, tags=(), convert_off=True, level='-8'):
    source = Path(work) / (name + '.raw')
    source.write_bytes(pcm)
    target = Path(work) / (name + '.flac')
    target.unlink(missing_ok=True)
    native('encode-' + name, [flac, level, *ENCODE[1:], *(['--no-utf8-convert'] if convert_off and tags else []), *['--tag=' + t for t in tags],
                              '--bps=16', '--channels=%d' % channels, '--sample-rate=%d' % rate, '-o', str(target), str(source)], work, env=NATIVE_ENV)
    return target.read_bytes()


# ---------------------------------------------------------------- forging helpers (the dishonest writer the verifier must survive)
def refresh(run, rewrite=True):
    """Rebind every ordinary hash and, optionally, rebuild the summary and result claims from the verifier's own observation."""
    run = Path(run)
    atomic_json(run / 'encode-inputs.json', {'source.pcm': adaptor.digest(run, 'source.pcm')})
    atomic_json(run / 'decode-inputs.json', {'audio.flac': adaptor.digest(run, 'audio.flac')})
    rewritten = False
    if rewrite:
        try:
            prepared = adaptor.plan(json.loads((run / 'authored.json').read_text()))
            observation = adaptor.observe(run, prepared, adaptor.runtime(), {})
            atomic_json(run / 'flac-summary.json', observation['summary'])
            rewritten = True
        except SchemaxisError:
            pass     # a forgery the verifier's own observation already refuses keeps the stale summary
    rebind(run)
    return rewritten


def rebind(run):
    run = Path(run)
    receipt = adaptor.read_json(run, 'verification.json')
    receipt['evidence'] = {n: adaptor.digest(run, n) for n in sorted(receipt['evidence'])}
    receipt['artifacts'] = adaptor.publications(run, 'encodeLossless')
    atomic_json(run / 'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    finalise(run)


def snapshot(run):
    return {p: p.read_bytes() for p in Path(run).rglob('*') if p.is_file()}


def restore(saved):
    for path, content in saved.items():
        path.write_bytes(content)


def labelled(flac, work, name, source, labels):
    document = {'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(source), 'metadata': labels}
    return adaptor.run(document, Path(work) / name, executable=flac, timeout=120)


# ---------------------------------------------------------------- acceptance sections
def identity(flac, metaflac, work):
    out = native('flac-version', [flac, '--version'], work, timeout=20).decode().strip()
    meta = native('metaflac-version', [metaflac, '--version'], work, timeout=20).decode().strip()
    assert re.fullmatch(r'flac 1\.5\.\d+', out) and re.fullmatch(r'metaflac 1\.5\.\d+', meta), (out, meta)
    return {'flac': out, 'metaflac': meta, 'flacSha256': hashlib.sha256(Path(flac).read_bytes()).hexdigest()}


def label_cases(flac, metaflac, work):
    """Labelled archives from real flac, read back by metaflac and a literal reader, with every PCM byte decoded again independently."""
    report = {}
    cases = (('ascii-all-three', 'stereo-16000', ASCII, ASCII_LINES), ('unicode-all-three', 'stereo-16000', UNICODE, UNICODE_LINES),
             ('ascii-mono-subset', 'mono-8000', {'artist': 'Ann Artist'}, [b'ARTIST=Ann Artist']),
             ('unicode-title-only', 'mono-8000', {'title': UNICODE['title']}, [UNICODE_LINES[0]]),
             ('equals-values', 'stereo-16000', {'title': '=', 'description': 'a=b=c==d'}, [b'TITLE==', b'DESCRIPTION=a=b=c==d']),
             ('leading-dash-and-flag-like', 'mono-8000', {'title': '--tag=EVIL=1', 'artist': '-w --force'}, [b'TITLE=--tag=EVIL=1', b'ARTIST=-w --force']),
             ('spaces-preserved', 'mono-8000', {'description': '  padded \u00a0 text  '}, [b'DESCRIPTION=  padded \xc2\xa0 text  ']),
             ('nfd-not-normalised', 'mono-8000', {'title': 'Cafe\u0301'}, [b'TITLE=Cafe\xcc\x81']))
    for name, fixture, labels, expected in cases:
        source = FIXTURES / (fixture + '.wav')
        fmt, pcm = wav_data(source.read_bytes())
        result = labelled(flac, work, 'label-' + name, source, labels)
        assert result['verified']
        run = Path(work) / ('label-' + name)
        data = (run / 'audio.flac').read_bytes()
        vendor, lines = literal_comments(data)
        assert re.fullmatch(rb'reference libFLAC 1\.5\.\d+ \d{8}', vendor), vendor
        assert lines == expected, (name, lines, expected)
        shown = {}
        for key in labels:
            field = key.upper()
            value = metaflac_tag(metaflac, run / 'audio.flac', field, work)
            line = next(l for l in expected if l.startswith(field.encode() + b'='))
            assert value == line + b'\n', (name, field, value, line)
            shown[field] = value.decode('utf-8').rstrip('\n')
        assert independent_decode(flac, run / 'audio.flac', work, name) == pcm, name
        assert streaminfo_md5(data) == hashlib.md5(pcm).hexdigest()
        assert adaptor.verify(run, executable=flac)['verified']
        flags = adaptor.read_json(run, 'plan.json')['native']['arguments']
        assert '--no-utf8-convert' in flags and flags.index('--no-utf8-convert') < min(i for i, a in enumerate(flags) if a.startswith('--tag='))
        report[name] = {'fixture': fixture, 'comments': [l.decode('utf-8') for l in lines], 'metaflacExact': True, 'literalReaderExact': True, 'pcmBytesCompared': len(pcm),
                        'everyPcmByteEqualsFixture': True, 'summaryComments': [c['value'] for c in adaptor.read_json(run, 'flac-summary.json')['metadata']['comments']]}
    # the flag is load bearing in the C locale the adaptor uses: without it flac replaces non-ASCII bytes
    fmt, pcm = wav_data((FIXTURES / 'mono-8000.wav').read_bytes())
    plain = literal_comments(flac_encode(flac, work, 'convert-on', pcm, 8000, 1, ['TITLE=Café'], convert_off=False))[1]
    flagged = literal_comments(flac_encode(flac, work, 'convert-off', pcm, 8000, 1, ['TITLE=Café'], convert_off=True))[1]
    assert plain == [b'TITLE=Caf##'] and flagged == [b'TITLE=Caf\xc3\xa9'], (plain, flagged)
    report['noUtf8ConvertIsNeededInLocaleC'] = {'withoutFlag': plain[0].decode(), 'withFlag': flagged[0].decode('utf-8')}
    return report


def limits(flac, metaflac, work):
    maximal = {'title': 'x' * 200, 'artist': 'あ' * 170, 'description': '\U0001f600' * 750}      # 200 cp/200 B, 170 cp/510 B, 750 cp/3000 B
    source = FIXTURES / 'mono-8000.wav'
    result = labelled(flac, work, 'limits-maximal', source, maximal)
    run = Path(work) / 'limits-maximal'
    lines = literal_comments((run / 'audio.flac').read_bytes())[1]
    assert lines == [b'TITLE=' + b'x' * 200, b'ARTIST=' + 'あ'.encode() * 170, b'DESCRIPTION=' + '\U0001f600'.encode() * 750], 'maximal labels differ'
    for field, expected in (('TITLE', lines[0]), ('ARTIST', lines[1]), ('DESCRIPTION', lines[2])):
        assert metaflac_tag(metaflac, run / 'audio.flac', field, work) == expected + b'\n'
    assert result['verified'] and adaptor.verify(run, executable=flac)['verified']
    before = len(PROCESSES)
    over = {'title 201 code points': {'title': 'x' * 201}, 'artist 171 CJK (513 bytes)': {'artist': 'あ' * 171}, 'description 751 emoji (3004 bytes)': {'description': '\U0001f600' * 751},
            'description 1001 code points': {'description': 'z' * 1001}}
    refusals = {}
    for label, labels in over.items():
        target = Path(work) / ('limits-over-' + re.sub(r'\W+', '-', label))
        fault = refused(lambda: adaptor.run({'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(source), 'metadata': labels}, target, executable=flac, timeout=60), 'INVALID_FLAC_METADATA')
        assert not target.exists()
        refusals[label] = {'fault': fault.code, 'location': fault.location, 'outputDirectoryCreated': False}
    assert len(PROCESSES) == before
    return {'maximalAccepted': {'titleCodePoints': 200, 'artistBytes': 510, 'descriptionBytes': 3000, 'metaflacExact': True, 'verified': True}, 'overLimitRefusedBeforeAnyNativeProcess': refusals}


def refusals(flac, work):
    source = FIXTURES / 'mono-8000.wav'
    bad = {'empty object': ({}, 'INVALID_FLAC_METADATA'), 'null': (None, 'INVALID_FLAC_METADATA'), 'array': ([], 'INVALID_FLAC_METADATA'), 'empty title': ({'title': ''}, 'INVALID_FLAC_METADATA'),
           'whitespace only': ({'title': ' \u00a0 '}, 'INVALID_FLAC_METADATA'), 'newline': ({'description': 'a\nb'}, 'INVALID_FLAC_METADATA'), 'nul': ({'title': 'a\0b'}, 'INVALID_FLAC_METADATA'),
           'lone surrogate': ({'title': 'a\ud800'}, 'INVALID_FLAC_METADATA'), 'bidi override': ({'title': 'a\u202eb'}, 'INVALID_FLAC_METADATA'), 'bidi isolate': ({'artist': '\u2066x\u2069'}, 'INVALID_FLAC_METADATA'),
           'number': ({'title': 7}, 'INVALID_FLAC_METADATA'), 'array value': ({'title': ['x']}, 'INVALID_FLAC_METADATA'), 'private use': ({'title': '\ue000'}, 'INVALID_FLAC_METADATA'),
           'zero width space': ({'title': 'a\u200bb'}, 'INVALID_FLAC_METADATA'), 'unknown field': ({'title': 'x', 'album': 'y'}, 'UNKNOWN_ARGUMENT'), 'tag name': ({'tagName': 'x'}, 'UNKNOWN_ARGUMENT'),
           'tag from file': ({'tag-from-file': 'TITLE=/etc/passwd'}, 'UNKNOWN_ARGUMENT'), 'upper-case key': ({'TITLE': 'x'}, 'UNKNOWN_ARGUMENT')}
    before, report = len(PROCESSES), {}
    for label, (value, code) in bad.items():
        target = Path(work) / ('refused-' + re.sub(r'\W+', '-', label))
        fault = refused(lambda: adaptor.run({'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(source), 'metadata': value}, target, executable=flac, timeout=60), code)
        assert not target.exists()
        report[label] = fault.code
    target = Path(work) / 'refused-decode-metadata'
    decode = {'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': str(FIXTURES / 'stereo-16000.flac'), 'metadata': {'title': 'x'}}
    report['metadata on decodePCM16'] = refused(lambda: adaptor.run(decode, target, executable=flac, timeout=60), 'UNKNOWN_ARGUMENT').code
    assert not target.exists() and len(PROCESSES) == before
    return {'refusedBeforeAnyNativeProcessOrOutputDirectory': report, 'directNativeProcessesStartedDuringRefusals': 0}


def forgeries(flac, metaflac, work):
    """Real flac builds files whose comments differ from the request; every receipt hash is refreshed, and the summary rebuilt where possible."""
    source = FIXTURES / 'stereo-16000.wav'
    fmt, pcm = wav_data(source.read_bytes())
    rate, channels = 16000, 2
    run = Path(work) / 'forge-base'
    labelled(flac, work, 'forge-base', source, UNICODE)
    saved = snapshot(run)
    good_tags = [line.decode('utf-8') for line in UNICODE_LINES]
    other = bytearray(pcm)
    other[300] ^= 1
    variants = {
        'titleValueChanged': (flac_encode(flac, work, 'f-title', pcm, rate, channels, ['TITLE=Other', *good_tags[1:]]), None),
        'orderReversed': (flac_encode(flac, work, 'f-order', pcm, rate, channels, good_tags[::-1]), None),
        'extraTagAdded': (flac_encode(flac, work, 'f-extra', pcm, rate, channels, [*good_tags, 'COMMENT=injected']), None),
        'artistMissing': (flac_encode(flac, work, 'f-missing', pcm, rate, channels, [good_tags[0], good_tags[2]]), None),
        'duplicateTitle': (flac_encode(flac, work, 'f-dup', pcm, rate, channels, [good_tags[0], *good_tags]), None),
        'untagged': (flac_encode(flac, work, 'f-untagged', pcm, rate, channels), None),
        'normalisedTitle': (flac_encode(flac, work, 'f-nfd', pcm, rate, channels, ['TITLE=Cafe\u0301 du Müller – 日本語メモ', *good_tags[1:]]), None),
        'localeConvertedBytes': (flac_encode(flac, work, 'f-convert', pcm, rate, channels, good_tags, convert_off=False), None),
        'differentPcmCorrectLabels': (flac_encode(flac, work, 'f-pcm', bytes(other), rate, channels, good_tags), None),
        'emptyValueTitle': (flac_encode(flac, work, 'f-empty', pcm, rate, channels, ['TITLE=', *good_tags[1:]]), None),
    }
    report = {}
    try:
        for label, (data, _) in variants.items():
            (run / 'audio.flac').write_bytes(data)
            report[label + 'WithoutRefresh'] = refused(lambda: adaptor.verify(run, executable=flac)).message[:110]
            rewritten = refresh(run)
            fault = refused(lambda: adaptor.verify(run, executable=flac))
            report[label] = {'summaryRewritten': rewritten, 'fault': fault.code, 'reason': fault.message[:150]}
            restore(saved)
        assert adaptor.verify(run, executable=flac)['verified']
        # request-side forgery: the request and plan are rewritten to claim labels the real flac never wrote (and the reverse)
        plain = Path(work) / 'forge-plain'
        adaptor.run({'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(source)}, plain, executable=flac, timeout=120)
        claimed = {'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(source), 'metadata': {'title': 'Smuggled'}}
        before = snapshot(plain)
        for name, value in (('authored.json', claimed), ('plan.json', adaptor.plan(claimed)),
                            ('captures.json', {**adaptor.read_json(plain, 'captures.json'), 'metadata': claimed['metadata']})):
            atomic_json(plain / name, value)
        rebind(plain)
        report['labelsClaimedForUntaggedFlac'] = refused(lambda: adaptor.verify(plain, executable=flac)).message[:140]
        restore(before)
        stripped = {k: v for k, v in json.loads((run / 'authored.json').read_text()).items() if k != 'metadata'}
        captures = {k: v for k, v in adaptor.read_json(run, 'captures.json').items() if k != 'metadata'}
        for name, value in (('authored.json', stripped), ('plan.json', adaptor.plan(stripped)), ('captures.json', captures)):
            atomic_json(run / name, value)
        rebind(run)
        report['labelsRemovedFromRequestOfTaggedFlac'] = refused(lambda: adaptor.verify(run, executable=flac)).message[:140]
        restore(saved)
        # documented limit: a coherent rewrite of every record around a different but valid labelled FLAC is semantic consistency, not authenticity
        replacement = {'title': 'Rewritten title', 'artist': 'Someone else'}
        data = flac_encode(flac, work, 'f-coherent', pcm, rate, channels, ['TITLE=Rewritten title', 'ARTIST=Someone else'], level='-0')
        (run / 'audio.flac').write_bytes(data)
        document = {**json.loads((run / 'authored.json').read_text()), 'metadata': replacement}
        atomic_json(run / 'authored.json', document)
        atomic_json(run / 'plan.json', adaptor.plan(document))
        captures = adaptor.read_json(run, 'captures.json')
        atomic_json(run / 'captures.json', {**captures, 'metadata': replacement})
        prepared = adaptor.plan(document)
        paths = adaptor.read_json(run, 'verification.json')['executables']
        command, names, limit = adaptor.stage_commands(prepared, paths['flac'], rate, channels, len(pcm))['encode']
        (run / 'encode-launcher.py').write_text(adaptor.launcher('encode', names, command, limit), encoding='utf-8')
        refresh(run, rewrite=False)
        observation = adaptor.observe(run, prepared, adaptor.runtime(flac), {})
        atomic_json(run / 'flac-summary.json', observation['summary'])
        rebind(run)
        verified = adaptor.verify_semantic(run, adaptor.runtime(flac), require_result=False)
        result = {'status': 'succeeded', **verified}
        atomic_json(run / 'result.json', result)
        rebind(run)
        report['coherentRewriteAcceptedAsSemanticConsistency'] = {'verified': adaptor.verify(run, executable=flac)['verified'], 'note': 'every record rewritten around a valid FLAC with different labels and effort -0; not authenticity'}
    finally:
        restore(saved)
    return report


def differential(flac, baseline, work):
    """Absent-label behaviour against the pre-change adaptor: identical bytes, plans, summaries, results and cross-verification."""
    spec = importlib.util.spec_from_file_location('schemaxis.adaptors.flac.baseline_adaptor', baseline)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    report = {}
    for name, operation, source in (('encode-stereo', 'encodeLossless', FIXTURES / 'stereo-16000.wav'), ('encode-mono-list', 'encodeLossless', FIXTURES / 'mono-8000.wav'),
                                    ('decode-stereo', 'decodePCM16', FIXTURES / 'stereo-16000.flac'), ('decode-tagged', 'decodePCM16', FIXTURES / 'tagged-stereo-16000.flac')):
        document = {'version': 'schemaxis.flac/1', 'operation': operation, 'source': str(source)}
        old_run, new_run = Path(work) / ('old-' + name), Path(work) / ('new-' + name)
        old.run(document, old_run, executable=flac, timeout=120)
        adaptor.run(document, new_run, executable=flac, timeout=120)
        identical, different = [], []
        for path in sorted(p for p in old_run.rglob('*') if p.is_file()):
            relative = path.relative_to(old_run)
            if relative.parts[0] == '.dispatch' or relative.name in ('verification.json', 'publication-metadata.json') or relative.name.endswith(('-submission.json', '.metadata.json', 'job.json')):
                continue
            other = new_run / relative
            (identical if other.is_file() and other.read_bytes() == path.read_bytes() else different).append(str(relative))
        assert not different, (name, different)
        old_names = sorted(str(p.relative_to(old_run)) for p in old_run.rglob('*') if p.is_file() and '.dispatch' not in p.parts)
        new_names = sorted(str(p.relative_to(new_run)) for p in new_run.rglob('*') if p.is_file() and '.dispatch' not in p.parts)
        assert old_names == new_names, (name, set(old_names) ^ set(new_names))
        old_receipt = json.loads((old_run / 'verification.json').read_text().replace(str(old_run), '<run>'))
        new_receipt = json.loads((new_run / 'verification.json').read_text().replace(str(new_run), '<run>'))
        for receipt in (old_receipt, new_receipt):      # the per-run submission records carry run-specific script paths and timings
            for key in [k for k in receipt['evidence'] if k.endswith('-submission.json')]:
                del receipt['evidence'][key]
        assert old_receipt == new_receipt, name
        assert adaptor.verify(old_run, executable=flac)['verified'] and old.verify(new_run, executable=flac)['verified']
        report[name] = {'filesComparedByteForByte': len(identical), 'membershipIdentical': True, 'receiptIdenticalModuloRunPathAndSubmissionRecords': True, 'oldRunVerifiesWithNewCode': True, 'newRunVerifiesWithOldCode': True}
    labelled_old = refused(lambda: old.plan({'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': '/data/a.wav', 'metadata': {'title': 'x'}}), 'UNKNOWN_ARGUMENT')
    report['preChangeAdaptorRejectsMetadata'] = labelled_old.code
    # the pre-change verifier refuses a labelled run (its comment guard demands an empty comment): labels cannot sneak through old code
    labelled_run = Path(work) / 'label-ascii-all-three'
    if labelled_run.exists():
        report['preChangeVerifierOnLabelledRun'] = refused(lambda: old.verify(labelled_run, executable=flac), 'VERIFICATION_FAILED').code
    return report


def old_receipts(directories, flac, work):
    """Genuine native untagged receipts from earlier runs verify with the new code, read only, and are unchanged."""
    report = {}
    for directory in directories:
        directory = Path(directory)
        before = tree_hash(directory)
        result = adaptor.verify(directory, executable=flac)
        cli = native('cli-verify-old-' + directory.name, [sys.executable, '-m', 'schemaxis', 'verify', str(directory)], ROOT, timeout=120, kind='schemaxis-cli-supervisor',
                     env={**os.environ, 'SCHEMAXIS_FLAC': flac, 'PYTHONPATH': str(ROOT / 'src')})
        after = tree_hash(directory)
        assert result['verified'] and after == before and b'verified' in cli, (directory, after == before, cli[-200:])
        summary = json.loads((directory / 'flac-summary.json').read_text())
        assert 'metadata' not in summary and 'metadata' not in json.loads((directory / 'result.json').read_text())
        report['/'.join(directory.parts[-5:])] = {
            'operation': result['operation'], 'verifiedWithNewCode': True, 'cliVerified': True, 'treeSha256': before, 'unchangedAfterVerification': True}
    return report


def cli_route(flac, metaflac, work):
    """The documented CLI as real processes: plan, run and verify a labelled example, and a refused invalid-label example."""
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'SCHEMAXIS_FLAC': flac}
    example = json.loads((ROOT / 'examples/schemaxis/flac-tag-archive.json').read_text(encoding='utf-8'))
    example['source'] = str(FIXTURES / 'mono-8000.wav')
    document = Path(work) / 'cli-tag-archive.json'
    document.write_text(json.dumps(example, ensure_ascii=False), encoding='utf-8')
    native('cli-plan', [sys.executable, '-m', 'schemaxis', 'plan', str(document)], ROOT, 60, env, kind='schemaxis-cli-supervisor')
    output = Path(work) / 'cli-run'
    native('cli-run', [sys.executable, '-m', 'schemaxis', 'run', str(document), '--output-directory', str(output), '--flac', flac], ROOT, 180, env, kind='schemaxis-cli-supervisor')
    native('cli-verify', [sys.executable, '-m', 'schemaxis', 'verify', str(output)], ROOT, 180, env, kind='schemaxis-cli-supervisor')
    published = next(output.rglob('audio.flac'))
    lines = literal_comments(published.read_bytes())[1]
    assert lines == [b'TITLE=Site visit, north bank', b'ARTIST=A. Reviewer', b'DESCRIPTION=Field note A=B; recorded before the repair']
    assert metaflac_tag(metaflac, published, 'DESCRIPTION', work) == lines[2] + b'\n'
    invalid = json.loads((ROOT / 'examples/schemaxis/flac-tag-invalid-label.json').read_text())
    invalid['source'] = str(FIXTURES / 'mono-8000.wav')
    bad = Path(work) / 'cli-invalid.json'
    bad.write_text(json.dumps(invalid))
    text = native('cli-plan-invalid', [sys.executable, '-m', 'schemaxis', 'plan', str(bad)], ROOT, 60, env, expect=1, kind='schemaxis-cli-supervisor')
    assert b'INVALID_FLAC_METADATA' in text, text[-300:]
    return {'planRunVerify': True, 'commentsExact': True, 'invalidLabelFault': 'INVALID_FLAC_METADATA', 'cliProcessesAreSupervisorKind': True}


def sox_workflow(flac, metaflac, sox, work):
    """SoX conform -> labelled FLAC archive -> PCM16 decode reuse, with scheduler reuse and label-edit invalidation."""
    locations = {'flac': flac, 'sox': sox}
    graph = json.loads((ROOT / 'examples/schemaxis/flac-tag-workflow.json').read_text())
    graph['operations'][0]['document']['source'] = str(FIXTURES / 'stereo-48000.wav')
    root = Path(work) / 'tag-workflow'
    first = workflow.execute(graph, root, locations=locations, timeout=300)
    assert first['status'] == 'succeeded'
    with location_context(locations):
        assert workflow.verify(root)['verified']
    wavs = {p.relative_to(root).parts[0]: p for p in root.rglob('audio.wav')}
    archive = next(p for p in root.rglob('audio.flac'))
    lines = literal_comments(archive.read_bytes())[1]
    assert lines == [b'TITLE=Conformed speech take', b'ARTIST=A. Reviewer'], lines
    assert metaflac_tag(metaflac, archive, 'TITLE', work) == b'TITLE=Conformed speech take\n'
    speech_fmt, speech_pcm = wav_data(wavs['speech'].read_bytes())
    reuse_fmt, reuse_pcm = wav_data(wavs['reuse'].read_bytes())
    assert wavs['reuse'].read_bytes() == wavs['speech'].read_bytes() and reuse_pcm == speech_pcm
    assert independent_decode(flac, archive, work, 'tag-workflow') == speech_pcm
    assert b'Conformed' not in wavs['reuse'].read_bytes()
    summary = json.loads(next(p for p in root.rglob('flac-summary.json') if 'reuse' in p.relative_to(root).parts[0]).read_text())
    assert summary['source']['droppedMetadataBlocks'] == ['VORBIS_COMMENT'] and 'metadata' not in summary
    second = workflow.execute(graph, root, locations=locations, timeout=300, resume=True)
    assert all(job['reused'] for job in second['jobs'])
    graph['operations'][1]['document']['metadata']['title'] = 'Edited label'
    mismatch = refused(lambda: workflow.execute(graph, root, locations=locations, timeout=300, resume=True), 'RESUME_MISMATCH')
    return {'status': first['status'], 'archiveComments': [l.decode() for l in lines], 'decodedWavEqualsConformedWav': True, 'decodeDropsLabels': True, 'unchangedReused': True,
            'editedLabelResumeRefused': mismatch.code, 'soxRuntime': native('sox-version', [sox, '--version'], work, timeout=20).decode().strip(),
            'noHumanReviewOrQualityClaim': True}


def shared_acceptance(flac, directory):
    locations = {'flac': flac}
    config = directory / 'config.json'
    atomic_json(config, {'version': 1, 'locations': locations})
    saved = {k: os.environ.get(k) for k in ('SCHEMAXIS_CONFIG', 'SCHEMAXIS_FLAC')}
    os.environ['SCHEMAXIS_CONFIG'] = str(config)
    os.environ.pop('SCHEMAXIS_FLAC', None)
    try:
        receipt = qualify(adaptor.VERSION, directory / 'kit', native=True, root=ROOT, locations=locations, timeout=60, wall_timeout=240)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    cases = [c['id'] for c in receipt['cases']]
    assert receipt['verified'] and 'tag-archive' in cases and 'tag-unicode' in cases, cases
    kit = directory / 'kit'
    for case, expected in (('tag-archive', [b'TITLE=Site visit, north bank', b'ARTIST=A. Reviewer', b'DESCRIPTION=Field note A=B; recorded before the repair']),):
        assert literal_comments((kit / case / 'audio.flac').read_bytes())[1] == expected
    return {'verified': receipt['verified'], 'cases': cases, 'runtimes': sorted({json.dumps(c['runtime'], sort_keys=True) for c in receipt['cases']}), 'lifecycle': receipt['lifecycle'],
            'registered': False, 'note': 'shared readiness acceptance incl. tag-archive and tag-unicode; the receipt was not registered in the source package'}


def launched_stages(work):
    """Exit codes of the native stages the adaptor started through its fixed launcher (their OS PIDs are not captured by this tool)."""
    stages = []
    for path in sorted(Path(work).rglob('*-submission.json')):
        value = json.loads(path.read_text())
        stages.append(value.get('exitCode'))
    return {'count': len(stages), 'nonZeroExitCodes': [c for c in stages if c != 0], 'note': 'flac stages started by the adaptor launcher inside run directories; direct probe processes are in probeProcesses'}


def on_alarm(signum, frame):
    raise TimeoutError('qualification exceeded %d seconds' % DEADLINE_SECONDS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--flac', type=Path, required=True, help='absolute FLAC 1.5 flac')
    parser.add_argument('--metaflac', type=Path, help='absolute metaflac (default: sibling of --flac)')
    parser.add_argument('--sox', type=Path, help='absolute SoX sox for the conform -> labelled archive -> reuse workflow (reported unavailable when absent)')
    parser.add_argument('--baseline-adaptor', type=Path, help='the pre-change flac adaptor.py for the byte-for-byte absent-label comparison (reported unavailable when absent)')
    parser.add_argument('--old-receipt', type=Path, action='append', default=[], help='genuine untagged run directory to verify read only (repeatable)')
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--skip-shared', action='store_true', help='skip the shared readiness acceptance of every case')
    args = parser.parse_args()
    directory = args.output_directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    flac = str(args.flac.absolute())
    metaflac = str((args.metaflac or args.flac.with_name('metaflac')).absolute())
    signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(DEADLINE_SECONDS)
    report = {'verified': False, 'acceptancePid': os.getpid(), 'deadlineSeconds': DEADLINE_SECONDS, 'startedUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    try:
        work = directory / 'work'
        work.mkdir()
        report['runtime'] = identity(flac, metaflac, work)
        with location_context({'flac': flac}):
            report['labelCases'] = label_cases(flac, metaflac, work)
            report['limits'] = limits(flac, metaflac, work)
            report['refusals'] = refusals(flac, work)
            report['forgeries'] = forgeries(flac, metaflac, work)
            if args.baseline_adaptor:
                report['absentLabelsDifferential'] = differential(flac, str(args.baseline_adaptor.absolute()), work)
            else:
                report['absentLabelsDifferential'] = 'unavailable: no --baseline-adaptor given'
            report['oldReceipts'] = old_receipts(args.old_receipt, flac, work) if args.old_receipt else 'unavailable: no --old-receipt given'
            report['cliRoute'] = cli_route(flac, metaflac, work)
            report['workflow'] = sox_workflow(flac, metaflac, str(args.sox.absolute()), work) if args.sox else 'unavailable: no --sox executable given'
        if not args.skip_shared:
            report['sharedAcceptance'] = shared_acceptance(flac, directory)
        report['adaptorLaunchedStages'] = launched_stages(directory)
        report['verified'] = True
    finally:
        signal.alarm(0)
        report['probeProcesses'] = PROCESSES
        report['finishedUtc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        atomic_json(directory / 'acceptance.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'probeProcesses'}, indent=2, ensure_ascii=False))
    print('probe processes:', len(PROCESSES))


if __name__ == '__main__':
    main()
