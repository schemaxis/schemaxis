#!/usr/bin/env python3
"""Bounded native acceptance of lossless WebP publication with libwebp 1.6 cwebp and dwebp.

Independent literal pixel rows, refreshed-hash hostile encodings (including a well-framed corrupt bitstream),
typed/duplicate-key/non-finite retained JSON with every ordinary hash rebound, missing/untrusted decoder faults,
the documented `schemaxis verify` decoder routes as real CLI processes, budget limits, workflow reuse and lifecycle. The tool decodes with dwebp itself and compares hand-written
rows; it does not reuse the adaptor's reader for those expectations.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import zlib

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors.webp import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import workflow

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/webp'
PROCESSES = []


def native(name, command, cwd, timeout=60, env=None, expect=0):
    """Run one probe process directly and keep its real PID, command and exit status."""
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    PROCESSES.append({'name': name, 'pid': process.pid, 'command': [Path(command[0]).name, *command[1:]], 'exitCode': process.returncode})
    assert process.returncode == expect, (name, process.returncode, err[-300:])
    return out if expect == 0 else out + err


class configuration_file:
    """Select a private SCHEMAXIS_CONFIG for a block, then restore the caller's environment."""
    def __init__(self, path, locations):
        self.path, self.locations = Path(path), locations

    def __enter__(self):
        atomic_json(self.path, {'version': 1, 'locations': self.locations})
        self.saved = {k: os.environ.get(k) for k in ('SCHEMAXIS_CONFIG', 'SCHEMAXIS_WEBP', 'SCHEMAXIS_DWEBP')}
        os.environ['SCHEMAXIS_CONFIG'] = str(self.path)
        os.environ.pop('SCHEMAXIS_WEBP', None)
        os.environ.pop('SCHEMAXIS_DWEBP', None)

    def __exit__(self, *error):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def refused(action, code='VERIFICATION_FAILED'):
    try:
        action()
    except SchemaxisError as error:
        assert error.fault.code == code, error.fault.to_dict()
        return error.fault.code
    raise AssertionError('invalid WebP evidence accepted')


def rebind(directory):
    """Rebind only the receipt's artifact and evidence digests and the shared manifest to the files as they now are."""
    directory = Path(directory)
    receipt = adaptor.read_json(directory, 'verification.json')
    receipt['evidence'] = {n: adaptor.digest(directory, n) for n in sorted(receipt['evidence'])}
    receipt['artifacts'] = adaptor.publications(directory)
    atomic_json(directory / 'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)    # the shared publication manifest is rebound too


def refresh(directory, forge_summary=True, forge_result=True):
    """Rebind every ordinary hash, and optionally rebuild the summary and result claims, as a fully consistent forging writer would.

    Returns whether the summary was rewritten: a forgery that cannot be parsed keeps the old summary.
    """
    directory = Path(directory)
    atomic_json(directory / 'decode-inputs.json', {'image.webp': adaptor.digest(directory, 'image.webp')})
    webp = (directory / 'image.webp').read_bytes()
    (directory / 'encode.stderr').write_text('Output:    %d bytes (0.00 bpp)\n' % len(webp))
    if forge_result:    # the result record's byte-count claim follows the forged file
        atomic_json(directory / 'result.json', {**adaptor.read_json(directory, 'result.json'), 'bytes': len(webp)})
    rewritten = False
    if forge_summary:
        try:
            capture = (directory / 'captured.png').read_bytes()
            summary = adaptor.summarize(adaptor.admit_png(capture), capture, webp, adaptor.webp_header(webp), adaptor.read_pam((directory / 'reopened.pam').read_bytes())[2])
            atomic_json(directory / 'webp-summary.json', summary)
            rewritten = True
        except SchemaxisError:
            pass    # unparseable forgeries keep the old summary; framing rejects them anyway
    rebind(directory)
    return rewritten


def rejection(directory, dwebp):
    try:
        adaptor.verify(directory, decoder=dwebp)
    except SchemaxisError as error:
        return error.fault
    raise AssertionError('accepted')


def rejection_reason(directory, dwebp):
    return rejection(directory, dwebp).message[:140]


def chunk(kind, value):
    return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value) & 0xffffffff)


def png(rows):
    raw = b''.join(b'\0' + bytes(v for px in row for v in px) for row in rows)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', len(rows[0]), len(rows), 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 1)) + chunk(b'IEND', b''))


def decode_rows(dwebp, webp, work):
    """Independent dwebp -pam decode and a deliberately separate tiny PAM parser."""
    out = Path(work) / 'independent.pam'
    native('independent-decode', [dwebp, str(webp), '-pam', '-o', str(out)], work)
    head, _, body = out.read_bytes().partition(b'ENDHDR\n')
    fields = dict(line.split(b' ', 1) for line in head.split(b'\n')[1:] if b' ' in line)
    width, height = int(fields[b'WIDTH']), int(fields[b'HEIGHT'])
    assert int(fields[b'DEPTH']) == 4 and len(body) == 4 * width * height
    return width, height, [[tuple(body[4 * (y * width + x):4 * (y * width + x) + 4]) for x in range(width)] for y in range(height)]


def literal_rows(directory, dwebp):
    red, green, blue, white = (255, 0, 0, 255), (0, 200, 0, 255), (0, 0, 255, 255), (255, 255, 255, 255)
    yellow, cyan, hidden1, hidden2, clear = (255, 255, 0, 128), (0, 255, 255, 64), (17, 33, 65, 0), (250, 128, 3, 0), (0, 0, 0, 0)
    wanted = {'baseline': [[red, red, green, green, blue, blue, white], [red, yellow, yellow, green, cyan, blue, white],
                           [hidden1, hidden1, yellow, cyan, cyan, hidden2, hidden2], [clear, hidden1, clear, hidden2, clear, hidden1, clear],
                           [white, blue, green, red, red, green, blue]],
              'opaque': [[(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 255, 255), (0, 0, 0, 255)],
                         [(10, 20, 30, 255), (40, 50, 60, 255), (70, 80, 90, 255), (100, 110, 120, 255), (130, 140, 150, 255)],
                         [(1, 2, 3, 255), (250, 251, 252, 255), (128, 128, 128, 255), (64, 32, 16, 255), (8, 4, 2, 255)]]}
    report = {}
    for name, rows in wanted.items():
        width, height, actual = decode_rows(dwebp, directory / name / 'image.webp', directory / name)
        assert (width, height) == (len(rows[0]), len(rows)) and actual == rows, (name, actual)
        report[name] = {'dimensions': [width, height], 'everyRGBAChannelEqualsLiteralRows': True}
    return report


def hostile(directory, cwebp, dwebp, changed_png):
    """Replace image.webp with real libwebp outputs and refresh every ordinary hash; only decoding can decide."""
    report, run = {}, directory / 'baseline'
    saved = {p: p.read_bytes() for p in run.rglob('*') if p.is_file()}
    work = directory / 'hostile-work'
    work.mkdir()
    source = (run / 'source.pam')
    (work / 'changed.png').write_bytes(changed_png)
    # A PAM of different pixels, written with the canonical header, encoded with the real encoder.
    changed = adaptor.admit_png(changed_png)
    (work / 'changed.pam').write_bytes(adaptor.pam(changed['width'], changed['height'], changed['rgba']))
    exif = work / 'exif.bin'
    exif.write_bytes(b'Exif\0\0MM\0*\0\0\0\x08\0\0')
    variants = {}
    native('no-exact', [cwebp, '-lossless', '-z', '6', str(source), '-o', str(work / 'noexact.webp')], work)
    native('lossy', [cwebp, '-q', '75', str(source), '-o', str(work / 'lossy.webp')], work)
    native('different-pixels', [cwebp, '-lossless', '-exact', '-z', '6', str(work / 'changed.pam'), '-o', str(work / 'different.webp')], work)
    native('equivalent-effort-0', [cwebp, '-lossless', '-exact', '-z', '0', str(source), '-o', str(work / 'effort0.webp')], work)
    mux = Path(cwebp).with_name('webpmux')
    good = (run / 'image.webp').read_bytes()
    corrupt = good[:25] + bytes(len(good) - 25)    # the RIFF and VP8L headers and both sizes stay valid; the bitstream is zeroed
    assert len(corrupt) == len(good) and corrupt[:25] == good[:25] and adaptor.webp_header(corrupt)['width'] == adaptor.webp_header(good)['width']
    variants.update(noExactHiddenRgbZeroed=(work / 'noexact.webp').read_bytes(), lossyAlphaVP8X=(work / 'lossy.webp').read_bytes(),
                    differentPixelsSameSize=(work / 'different.webp').read_bytes(), truncated=good[:-3], trailingBytes=good + b'\0\0',
                    corruptBitstreamValidFraming=corrupt)
    if mux.exists():
        native('add-exif', [str(mux), '-set', 'exif', str(exif), str(run / 'image.webp'), '-o', str(work / 'exif.webp')], work)
        variants['exifChunkAdded'] = (work / 'exif.webp').read_bytes()
    try:
        for label, data in variants.items():
            assert data != good, label
            (run / 'image.webp').write_bytes(data)
            report[label + 'WithoutRefresh'] = refused(lambda: adaptor.verify(run, decoder=dwebp))
            report[label + 'SummaryRewritten'] = refresh(run)
            report[label + 'FullyRefreshed'] = refused(lambda: adaptor.verify(run, decoder=dwebp))
            fault = rejection(run, dwebp)
            report[label + 'FullyRefreshedReason'] = fault.message[:140]
            if label == 'corruptBitstreamValidFraming':    # the real dwebp exits non-zero; that is a verification failure with its cause
                cause = fault.observed['cause']
                assert cause['code'] == 'NATIVE_EXECUTION_FAILED' and 'BITSTREAM_ERROR' in cause['message'], cause
                report[label + 'OriginalCause'] = {'code': cause['code'], 'message': cause['message'][:160]}
            for path, content in saved.items():
                path.write_bytes(content)
        # A different valid lossless encoding of identical pixels is semantically equal and passes once receipts
        # agree. Without refreshing, the changed bytes alone are rejected by the receipt digest.
        (run / 'image.webp').write_bytes((work / 'effort0.webp').read_bytes())
        assert (work / 'effort0.webp').read_bytes() != good
        report['equivalentEncodingWithoutRefresh'] = refused(lambda: adaptor.verify(run, decoder=dwebp))
        refresh(run, forge_summary=False, forge_result=False)
        report['equivalentEncodingReceiptRefreshedSummaryStale'] = refused(lambda: adaptor.verify(run, decoder=dwebp))
        refresh(run, forge_result=False)
        report['equivalentEncodingSummaryRewrittenResultStale'] = rejection(run, dwebp).message[:100]
        refresh(run)
        report['equivalentEncodingAfterRefreshAccepted'] = adaptor.verify(run, decoder=dwebp)['verified']
    finally:
        for path, content in saved.items():
            path.write_bytes(content)
    assert adaptor.verify(run, decoder=dwebp)['verified']
    return report


def retained_json(directory, dwebp):
    """Type-only, duplicate-key and non-finite edits of retained JSON, each with every ordinary hash and the manifest rebound."""
    run = directory / 'baseline'
    saved = {p: p.read_bytes() for p in run.rglob('*') if p.is_file()}

    def first(old, new):
        def edit(text):
            assert text.count(old) == 1, old
            return text.replace(old, new)
        return edit

    def leading(entry):
        return lambda text: '{' + entry + ', ' + text.lstrip()[1:]

    def integer_to_float(pattern, count=0):
        return lambda text: re.sub(pattern, lambda m: m.group(1) + m.group(2) + '.0', text, count=count, flags=re.S)
    cases = [
        ('summaryBooleanAsInteger', 'webp-summary.json', first('"exactRgba": true', '"exactRgba": 1'), True),
        ('summaryImageBytesAsFloat', 'webp-summary.json', integer_to_float(r'("image": \{[^}]*?"bytes": )(\d+)', 1), True),
        ('summaryDuplicateKey', 'webp-summary.json', first('"exactRgba": true', '"exactRgba": false, "exactRgba": true'), False),
        ('summaryNaN', 'webp-summary.json', first('"exactRgba": true', '"exactRgba": NaN'), False),
        ('summaryOverflow1e400', 'webp-summary.json', first('"exactRgba": true', '"exactRgba": 1e400'), False),
        ('planNumberType', 'plan.json', first('"maxPixels": 1048576', '"maxPixels": 1048576.0'), True),
        ('capturesBytesAsFloat', 'captures.json', integer_to_float(r'("bytes": )(\d+)'), True),
        ('decodeInputsDuplicateKey', 'decode-inputs.json', leading('"image.webp": "0"'), False),
        ('resultBooleanAsInteger', 'result.json', first('"verified": true', '"verified": 1'), True),
        ('resultCountAsFloat', 'result.json', first('"artifacts": 2', '"artifacts": 2.0'), True),
        ('resultDuplicateStatus', 'result.json', leading('"status": "failed"'), False),
        ('receiptDuplicateExecutables', 'verification.json', leading('"executables": {"encoder": "/x", "decoder": "/y"}'), False),
        ('receiptNaN', 'verification.json', leading('"extra": NaN'), False),
        ('receiptOverflow1e400', 'verification.json', leading('"extra": 1e400'), False),
    ]
    report = {}
    try:
        for label, name, edit, collapses in cases:
            path = run / name
            if name == 'verification.json':
                rebind(run)    # rebound first, then textually forged
            before = path.read_text()
            path.write_text(edit(before))
            assert path.read_text() != before, label
            if collapses:    # Python equality would have accepted the edit
                assert json.loads(before) == json.loads(path.read_text()), label
            if name != 'verification.json':
                rebind(run)
            fault = rejection(run, dwebp)
            assert fault.code == 'VERIFICATION_FAILED', fault.to_dict()
            report[label] = {'pythonEqualityWouldCollapse': collapses, 'fault': fault.code, 'reason': fault.message[:100]}
            for item, data in saved.items():
                item.write_bytes(data)
    finally:
        for item, data in saved.items():
            item.write_bytes(data)
    assert adaptor.verify(run, decoder=dwebp)['verified']
    return report


def cli_verify(directory, run, dwebp, work):
    """The documented routes for bare `schemaxis verify`: SCHEMAXIS_DWEBP or a stored dwebp location; there is no --dwebp flag."""
    base = {k: v for k, v in os.environ.items() if not k.startswith('SCHEMAXIS_')}
    base['PYTHONPATH'] = str(ROOT / 'src')
    atomic_json(work / 'cli-empty.json', {'version': 1, 'locations': {}})
    atomic_json(work / 'cli-stored.json', {'version': 1, 'locations': {'dwebp': dwebp}})
    command = [sys.executable, '-m', 'schemaxis', 'verify', str(run)]
    report = {}
    report['environmentVariable'] = json.loads(native('cli-verify-environment', command, work, env={**base, 'SCHEMAXIS_CONFIG': str(work / 'cli-empty.json'), 'SCHEMAXIS_DWEBP': dwebp}))['verified']
    report['storedLocation'] = json.loads(native('cli-verify-stored-location', command, work, env={**base, 'SCHEMAXIS_CONFIG': str(work / 'cli-stored.json')}))['verified']
    missing = native('cli-verify-without-decoder', command, work, env={**base, 'SCHEMAXIS_CONFIG': str(work / 'cli-empty.json')}, expect=1).decode()
    assert 'INTERPRETER_NOT_FOUND' in missing, missing[-300:]
    report['withoutDecoder'] = 'INTERPRETER_NOT_FOUND'
    flag = native('cli-verify-with-dwebp-flag', [*command, '--dwebp', dwebp], work, env={**base, 'SCHEMAXIS_CONFIG': str(work / 'cli-empty.json')}, expect=2).decode()
    assert 'unrecognized arguments' in flag and '--dwebp' in flag, flag[-300:]
    report['dwebpFlagOnBareVerify'] = 'rejected by the argument parser (exit 2): the flag belongs to run and inspect'
    return report


def lifecycle(directory, document, dwebp):
    wrapper = directory / 'slow-cwebp.py'
    marker = directory / 'slow.pid'
    wrapper.write_text('#!' + sys.executable + '\nimport os,time\nfrom pathlib import Path\nPath(' + repr(str(marker)) + ').write_text(str(os.getpid()))\ntime.sleep(30)\n')
    wrapper.chmod(0o700)
    results = {}
    for action in ('timeout', 'cancel'):
        marker.unlink(missing_ok=True)
        cancel = threading.Event()
        thread = None
        if action == 'cancel':
            def trigger():
                end = time.monotonic() + 8
                while not marker.exists() and time.monotonic() < end:
                    time.sleep(.01)
                if marker.exists():
                    cancel.set()
            thread = threading.Thread(target=trigger, daemon=True)
            thread.start()
        try:
            with allocation({'threads': 1, 'ranks': 1}, cancel):
                results[action] = refused(lambda: adaptor.run(document, directory / ('inflight-' + action), executable=str(wrapper), decoder=dwebp,
                                                              timeout=10 if thread else .5), 'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')
        finally:
            if thread:
                thread.join(10)
        assert marker.exists()
        try:
            os.kill(int(marker.read_text()), 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError('owned process survived ' + action)
    return results


def budget(directory, cwebp, dwebp):
    """Largest accepted shapes and the first refused ones, with observed wall time."""
    report = {}
    state = 12345

    def noise(width, height):
        nonlocal state
        rows = []
        for _ in range(height):
            row = []
            for _ in range(width):
                state = (state * 1103515245 + 12345) & 0x7fffffff
                row.append(((state >> 4) & 255, (state >> 12) & 255, (state >> 20) & 255, 255 if state & 4 else (state >> 8) & 255))
            rows.append(row)
        return rows
    for label, shape in (('1024x1024', (1024, 1024)), ('2048x512', (2048, 512))):
        source = directory / ('budget-%s.png' % label)
        source.write_bytes(png(noise(*shape)))
        document = {'version': 'schemaxis.webp/1', 'operation': 'encodeLossless', 'source': str(source)}
        start = time.monotonic()
        result = adaptor.run(document, directory / ('budget-' + label), executable=cwebp, decoder=dwebp, timeout=240)
        run_seconds = time.monotonic() - start
        start = time.monotonic()
        assert adaptor.verify(directory / ('budget-' + label), decoder=dwebp)['verified']
        report[label] = {'verified': result['verified'], 'sourceBytes': source.stat().st_size, 'webpBytes': result['bytes'], 'runSeconds': round(run_seconds, 1),
                         'verifySeconds': round(time.monotonic() - start, 1), 'content': 'pseudo-random RGBA noise (worst case for compression)'}
    for label, shape in (('1025x1025', (1025, 1025)), ('2049x16', (2049, 16))):
        source = directory / ('over-%s.png' % label)
        source.write_bytes(png([[(0, 0, 0, 255)] * shape[0]] * shape[1]))
        document = {'version': 'schemaxis.webp/1', 'operation': 'encodeLossless', 'source': str(source)}
        report[label + 'Refused'] = refused(lambda: adaptor.run(document, directory / ('over-' + label), executable=cwebp, decoder=dwebp, timeout=30), 'WEBP_PIXEL_BUDGET')
        assert not (directory / ('over-' + label) / 'encoder-version-submission.json').exists()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--webp', type=Path, required=True, help='absolute libwebp 1.6 cwebp')
    parser.add_argument('--dwebp', type=Path, required=True, help='absolute libwebp 1.6 dwebp')
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--register', action='store_true')
    args = parser.parse_args()
    directory = args.output_directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    cwebp, dwebp = str(args.webp.absolute()), str(args.dwebp.absolute())
    locations = {'webp': cwebp, 'dwebp': dwebp}
    report = {'verified': False, 'acceptancePid': os.getpid()}
    try:
        report['runtime'] = {'cwebp': native('cwebp-version', [cwebp, '-version'], directory).decode().strip().replace('\n', ' / '),
                             'dwebp': native('dwebp-version', [dwebp, '-version'], directory).decode().strip()}
        with configuration_file(directory / 'config.json', locations):
            receipt = qualify(adaptor.VERSION, directory / 'kit', native=True, root=ROOT, locations=locations, timeout=30, wall_timeout=90)
        report['native'] = {'verified': receipt['verified'], 'cases': [c['id'] for c in receipt['cases']],
                            'runtimes': [c['runtime'] for c in receipt['cases']], 'lifecycle': receipt['lifecycle']}
        with configuration_file(directory / 'config-without-dwebp.json', {'webp': cwebp}):
            report['verifyWithoutConfiguredDwebp'] = refused(lambda: adaptor.verify(directory / 'kit/baseline'), 'INTERPRETER_NOT_FOUND')
        with configuration_file(directory / 'config-with-dwebp.json', locations):
            report['verifyWithStoredDwebp'] = adaptor.verify(directory / 'kit/baseline')['verified']
        with location_context(locations):
            report['literalPixels'] = literal_rows(directory / 'kit', dwebp)
            report['hostile'] = hostile(directory / 'kit', cwebp, dwebp, (FIXTURES / 'swatch-rgba-changed.png').read_bytes())
            report['retainedJson'] = retained_json(directory / 'kit', dwebp)
            report['cliVerifyRoutes'] = cli_verify(directory, directory / 'kit/baseline', dwebp, directory)
            document = {'version': 'schemaxis.webp/1', 'operation': 'encodeLossless', 'source': str(FIXTURES / 'swatch-rgba.png')}
            source = directory / 'reuse.png'
            shutil.copyfile(FIXTURES / 'swatch-rgba.png', source)
            document['source'] = str(source)
            graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'publish', 'document': document}]}
            first = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=60)
            assert first['status'] == 'succeeded' and workflow.verify(directory / 'workflow')['verified']
            second = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=60, resume=True)
            assert all(j['reused'] for j in second['jobs'])
            shutil.copyfile(FIXTURES / 'swatch-rgba-changed.png', source)
            third = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=60, resume=True)
            assert all(not j['reused'] for j in third['jobs']) and workflow.verify(directory / 'workflow')['verified']
            report['workflow'] = {'baseline': first['status'], 'unchangedReused': True, 'changedSamePathSourceBytesReused': False}
            report['inflightLifecycle'] = lifecycle(directory, document, dwebp)
            report['budget'] = budget(directory, cwebp, dwebp)
        if args.register:
            register(directory / 'kit/qualification.json')
        report['verified'] = True
    finally:
        report['probeProcesses'] = PROCESSES
        atomic_json(directory / 'acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
