#!/usr/bin/env python3
"""Native acceptance of the Info-ZIP publication bundle with Info-ZIP Zip 3.0 `zip` and an independent `unzip`.

Every archive the adaptor makes is extracted member by member with a separate `unzip -p` process, one name at a time with a timeout, and
compared with bytes the tool wrote itself; the tool never reuses the adaptor's archive reader for those expectations. Cases: one, many
(sixteen), empty, binary and Unicode-content members, byte-for-byte deterministic archives, the largest accepted budget, refusals before any
native process, an `unzip` passed as the wrong runtime, in-flight timeout and cancellation, the documented CLI routes as real processes
(including bare `schemaxis verify` with no native program configured), workflow reuse and a narration -> FLAC -> bundle workflow when
eSpeak NG and FLAC executables are given. Commands run serially. Direct native subprocess PIDs, program basenames with their arguments (argv[0] is normalised to the basename, not the full executable path) and exit codes
are recorded for the tool's own probes; the PIDs of the adaptor's native zip stages come from each run's launcher record (the launcher process becomes
the native zip through execve), reported separately from the Python supervisor processes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import threading
import time

from schemaxis.adaptor_conformance import qualify
from schemaxis.adaptors.infozip import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import workflow

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/infozip'
PROCESSES = []
RUNS = []


def native(name, command, cwd, timeout=60, env=None, expect=0, limit=96 * 1024 * 1024):
    """Run one probe process directly and keep its real PID, normalised command (basename of argv[0] plus arguments) and exit status.

    The timeout is enforced; the output is read completely by communicate() and its length is checked afterwards, so ``limit`` is a post-read
    check on the captured output and not a streaming memory bound (the outer kernel guard and the probe choice are what bound memory here).
    """
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env or {'LANG': 'C', 'PATH': ''})
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    PROCESSES.append({'name': name, 'pid': process.pid, 'timeoutSeconds': timeout, 'command': [Path(command[0]).name, *map(str, command[1:])], 'exitCode': process.returncode})
    assert len(out) <= limit and process.returncode == expect, (name, process.returncode, err[-300:])
    return out if expect == 0 else out + err


def refused(action, code):
    try:
        action()
    except SchemaxisError as error:
        assert error.fault.code == code, error.fault.to_dict()
        return error.fault
    raise AssertionError('accepted where %s was required' % code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def document(files):
    return {'version': 'schemaxis.infozip/1', 'operation': 'bundle', 'files': [{'name': n, 'source': str(p)} for n, p in files]}


def make_sources(work, label, contents):
    folder = work / ('src-' + label)
    folder.mkdir()
    files = []
    for name, data in contents.items():
        (folder / name).write_bytes(data)
        files.append((name, folder / name))
    return files


def record_run(run):
    """Launcher records of one run: the native zip's process id, argument array and exit code (the launcher execs the native tool)."""
    for stage in adaptor.STAGES:
        process = json.loads((Path(run) / (stage + '-process.json')).read_text())
        submission = json.loads((Path(run) / (stage + '-submission.json')).read_text())
        RUNS.append({'run': Path(run).name, 'stage': stage, 'nativePid': process['pid'], 'argv': [Path(process['argv'][0]).name, *process['argv'][1:]], 'exitCode': submission['exitCode']})


def independent_extract(unzip, archive, contents, work):
    """`unzip -Z1`, `-tq`, `-Z` and one timeout-limited `unzip -p` per member; compare every byte with the tool's own expectations."""
    listing = native('unzip-list', [unzip, '-Z1', str(archive)], work).decode().split('\n')[:-1]
    assert listing == [*contents, 'manifest.json'], listing
    assert b'No errors detected' in native('unzip-test', [unzip, '-tq', str(archive)], work)
    detail = native('unzip-zipinfo', [unzip, '-Z', str(archive)], work).decode().splitlines()
    assert sum(' stor ' in line for line in detail) == len(listing), detail[:3]
    for index, name in enumerate(listing[:-1]):
        data = native('unzip-p-%d' % index, [unzip, '-p', str(archive), name], work, timeout=30)
        assert data == contents[name], 'member %s differs from the file the tool wrote' % name
    manifest = json.loads(native('unzip-p-manifest', [unzip, '-p', str(archive), 'manifest.json'], work, timeout=30))
    assert manifest['members'] == [{'bytes': len(contents[n]), 'name': n, 'sha256': sha(contents[n])} for n in contents], manifest['members']
    assert 'Unsigned inventory' in manifest['inventory']
    return {'members': len(listing), 'stored': True}


def bundle_case(work, zip_, unzip, label, contents):
    files = make_sources(work, label, contents)
    result = adaptor.run(document(files), work / label, executable=zip_, timeout=120)
    assert result['status'] == 'succeeded' and result['verified'] and result['members'] == len(contents) + 1
    record_run(work / label)
    archive = work / label / 'bundle.zip'
    report = {**independent_extract(unzip, archive, contents, work), 'archiveBytes': archive.stat().st_size, 'archiveSha256': sha(archive.read_bytes())}
    assert adaptor.verify(work / label)['verified']
    again = adaptor.run(document(files), work / (label + '-again'), executable=zip_, timeout=120)
    assert again['archiveSha256'] == report['archiveSha256'], 'two runs of the same files must give byte-identical archives (fixed time, mode and order)'
    record_run(work / (label + '-again'))
    report['deterministic'] = True
    return report


def literal_cases(work, zip_, unzip):
    rng = random.Random(60)
    blob = bytes(range(256)) * 4 + rng.randbytes(100 * 1024)
    many = {('f%02d-%s.%s' % (i, 'x' * (i % 5), ('txt', 'json', 'srt', 'vtt', 'html')[i % 5])): ('member %d\n' % i).encode() * (i + 1) for i in range(16)}
    return {'one': bundle_case(work, zip_, unzip, 'one', {'note.txt': b'one member\n'}),
            'sixteenMembers': bundle_case(work, zip_, unzip, 'many', many),
            'emptyFile': bundle_case(work, zip_, unzip, 'empty', {'empty.txt': b'', 'after.txt': b'after the empty member\n', 'empty2.json': b''}),
            'binary': bundle_case(work, zip_, unzip, 'binary', {'blob.png': blob, 'allbytes.wav': bytes(range(256))}),
            'unicodeContent': bundle_case(work, zip_, unzip, 'unicode', {
                'utf8.txt': 'Caf\u00e9 \u2014 \u65e5\u672c\u8a9e \u2014 \u0645\u0631\u062d\u0628\u0627 \U0001f600\n'.encode('utf-8'),
                'utf16.txt': '\u2603 snow\n'.encode('utf-16'), 'nul-bytes.json': b'{"a":"\\u0000"}\x00\x00'}),
            'fixtures': bundle_case(work, zip_, unzip, 'fixtures', {n: (FIXTURES / n).read_bytes() for n in ('report.txt', 'captions.srt', 'notes.json', 'tone.wav', 'empty.txt', 'page.html')})}


def refusals(work, zip_, unzip):
    report = {}
    files = make_sources(work, 'refusals', {'a.txt': b'a'})
    base = document(files)
    report['unzipAsRuntime'] = refused(lambda: adaptor.run(base, work / 'wrong-runtime', executable=unzip, timeout=60), 'UNSUPPORTED_RUNTIME').message[:80]
    report['missingRuntime'] = refused(lambda: adaptor.run(base, work / 'no-runtime', executable=str(work / 'absent-zip'), timeout=60), 'INTERPRETER_NOT_FOUND').code
    report['relativeRuntime'] = refused(lambda: adaptor.run(base, work / 'rel-runtime', executable='zip', timeout=60), 'INTERPRETER_NOT_FOUND').code
    assert not (work / 'no-runtime').exists() and not (work / 'rel-runtime').exists()
    report['outputCollision'] = refused(lambda: adaptor.run(base, work / 'one', executable=zip_, timeout=60), 'OUTPUT_EXISTS').code
    (work / 'src-refusals/link.txt').symlink_to(work / 'src-refusals/a.txt')
    os.mkdir(work / 'src-refusals/dir')
    os.mkfifo(work / 'src-refusals/fifo')
    for name in ('link.txt', 'dir', 'fifo', 'missing.txt'):
        bad = document([('b.txt', work / 'src-refusals' / name)])
        refused(lambda: adaptor.run(bad, work / ('bad-' + name), executable=zip_, timeout=60), 'INVALID_INFOZIP_SOURCE')
        assert not (work / ('bad-' + name) / 'pack').exists(), 'native staging began for a refused source'
    report['unsafeSources'] = 'symlink, directory, FIFO and missing source refused before any staging'
    big = work / 'src-refusals/big.bin'
    with big.open('wb') as stream:
        stream.truncate(adaptor.MAX_MEMBER_BYTES + 1)
    refused(lambda: adaptor.run(document([('big.pdf', big)]), work / 'over-member', executable=zip_, timeout=60), 'INFOZIP_BUDGET')
    parts = []
    for index in range(3):
        part = work / ('src-refusals/part%d.bin' % index)
        with part.open('wb') as stream:
            stream.truncate(22 * 1024 * 1024)
        parts.append(('part%d.pdf' % index, part))
    refused(lambda: adaptor.run(document(parts), work / 'over-total', executable=zip_, timeout=60), 'INFOZIP_BUDGET')
    report['budgetRefusals'] = {'memberBytes': adaptor.MAX_MEMBER_BYTES + 1, 'totalBytes': 3 * 22 * 1024 * 1024}
    return report


def budget(work, zip_, unzip):
    """The largest accepted shape (two 32 MiB members, 64 MiB total) with wall time, extracted independently."""
    rng = random.Random(61)
    folder = work / 'src-largest'
    folder.mkdir()
    contents = {}
    for name in ('first.pdf', 'second.pdf'):
        data = rng.randbytes(1024 * 1024) * 32
        (folder / name).write_bytes(data)
        contents[name] = data
    start = time.monotonic()
    result = adaptor.run(document([(n, folder / n) for n in contents]), work / 'largest', executable=zip_, timeout=300)
    seconds = round(time.monotonic() - start, 2)
    record_run(work / 'largest')
    archive = work / 'largest/bundle.zip'
    assert result['verified'] and archive.stat().st_size <= adaptor.MAX_ARCHIVE_BYTES
    for index, name in enumerate(contents):
        data = native('unzip-largest-%d' % index, [unzip, '-p', str(archive), name], work, timeout=120)
        assert data == contents[name]
    shutil.rmtree(folder)
    return {'totalMemberBytes': 2 * 32 * 1024 * 1024, 'archiveBytes': archive.stat().st_size, 'wallSeconds': seconds, 'extractedIndependently': True}


def lifecycle(work, zip_):
    wrapper = work / 'slow-zip.py'
    marker = work / 'slow.pid'
    wrapper.write_text('#!%s\nimport os, sys, time\nfrom pathlib import Path\nif sys.argv[1:] == ["-v"]:\n    print("This is Zip 3.0 (July 5th 2008), by Info-ZIP."); sys.exit(0)\nPath(%r).write_text(str(os.getpid()))\ntime.sleep(30)\n' % (sys.executable, str(marker)))
    wrapper.chmod(0o700)
    base = document(make_sources(work, 'lifecycle', {'a.txt': b'a'}))
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
                results[action] = refused(lambda: adaptor.run(base, work / ('inflight-' + action), executable=str(wrapper), timeout=10 if thread else 2),
                                          'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT').code
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
        for published in ('bundle.zip', 'bundle-summary.json', 'verification.json'):
            assert not (work / ('inflight-' + action) / published).exists()
        results[action + 'Published'] = 'none'
    results['wrapperNote'] = 'the timeout and cancellation probes use a fake zip that prints a Zip 3.0 banner and sleeps; they test lifecycle ownership, not Info-ZIP behaviour'
    return results


def cli(work, zip_, unzip):
    """The documented routes as real processes: run with --infozip, then bare verify with no native program configured and a ZIPOPT that would change stored bytes."""
    files = make_sources(work, 'cli', {'cli.txt': b'cli run\n'})
    atomic_json(work / 'cli.json', document(files))
    atomic_json(work / 'cli-empty.json', {'version': 1, 'locations': {}})
    base = {k: v for k, v in os.environ.items() if not k.startswith('SCHEMAXIS_')}
    base.update(PYTHONPATH=str(ROOT / 'src'), SCHEMAXIS_CONFIG=str(work / 'cli-empty.json'), ZIPOPT='-l', UNZIPOPT='-o')   # -l would rewrite LF as CRLF in stored bytes
    run = native('cli-run', [sys.executable, '-m', 'schemaxis', 'run', str(work / 'cli.json'), '--output-directory', str(work / 'cli-run'), '--infozip', zip_], work, timeout=120, env=base)
    assert json.loads(run)['verified'] is True
    record_run(work / 'cli-run')
    assert [e for e in json.loads((work / 'cli-run/bundle-process.json').read_text())['argv']][:4] == [zip_, '-X', '-0', '-q']
    verified = json.loads(native('cli-verify', [sys.executable, '-m', 'schemaxis', 'verify', str(work / 'cli-run')], work, timeout=60, env=base))
    assert verified['verified'] is True
    plan = native('cli-plan', [sys.executable, '-m', 'schemaxis', 'plan', str(work / 'cli.json')], work, timeout=60, env=base)
    assert b'schemaxis.infozip.plan/1' in plan
    contents = {'cli.txt': b'cli run\n'}
    independent_extract(unzip, work / 'cli-run/bundle.zip', contents, work)
    return {'run': True, 'bareVerifyWithoutNativeProgram': True,
            'zipoptInference': 'ZIPOPT=-l was set in the CLI process environment and the bytes read back by unzip -p equal the source bytes; zip -l would have written CRLF, '
                               'so this is an inference from a byte comparison, not a readback of the native environment',
            'environmentPolicy': 'the product minimal environment (LANG, LC_ALL, TZ through the launcher execve) is shown by the launcher text that verification checks and by the fake-native '
                                 'unit test that records the environment; this tool does not observe the real zip environment. The outer kernel memory, swap, CPU and task guard is separate '
                                 'from that product policy'}


def reuse(work, zip_):
    locations = {'infozip': zip_}
    files = make_sources(work, 'reuse', {'keep.txt': b'first\n', 'other.json': b'{}\n'})
    graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'package', 'document': document(files)}]}
    first = workflow.execute(graph, work / 'reuse-workflow', locations=locations, timeout=240)
    assert first['status'] == 'succeeded'
    with location_context(locations):
        assert workflow.verify(work / 'reuse-workflow')['verified']
    second = workflow.execute(graph, work / 'reuse-workflow', locations=locations, timeout=240, resume=True)
    assert all(job['reused'] for job in second['jobs'])
    files[0][1].write_bytes(b'second, same path\n')
    third = workflow.execute(graph, work / 'reuse-workflow', locations=locations, timeout=240, resume=True)
    assert all(not job['reused'] for job in third['jobs'])
    archive = next((work / 'reuse-workflow').rglob('bundle.zip'))
    with location_context(locations):
        assert workflow.verify(work / 'reuse-workflow')['verified']
    return {'unchangedReused': True, 'changedSamePathSourceBytesReused': False, 'rerunArchiveContainsNewBytes': b'second, same path\n' in archive.read_bytes()}


def speech_workflow(work, zip_, unzip, espeak, flac):
    """Narration (eSpeak NG) -> lossless FLAC -> bundle of the FLAC, both summaries and a caption file; every member compared with the producers' files."""
    locations = {'infozip': zip_, 'espeakng': espeak, 'flac': flac}
    caption = work / 'captions.srt'
    shutil.copyfile(FIXTURES / 'captions.srt', caption)
    graph = json.loads((ROOT / 'examples/schemaxis/infozip-speech-workflow.json').read_text())
    graph['operations'][2]['document']['files'][3]['source'] = str(caption)
    result = workflow.execute(graph, work / 'speech-bundle', locations=locations, timeout=300)
    assert result['status'] == 'succeeded'
    with location_context(locations):
        assert workflow.verify(work / 'speech-bundle')['verified']
    jobs = {job['operation']: Path(job['directory']) for job in result['jobs']}
    expected = {'narration.flac': (jobs['archive'] / 'audio.flac').read_bytes(), 'narration-summary.json': (jobs['narration'] / 'espeakng-summary.json').read_bytes(),
                'archive-summary.json': (jobs['archive'] / 'flac-summary.json').read_bytes(), 'captions.srt': caption.read_bytes()}
    record_run(jobs['package'])
    report = independent_extract(unzip, jobs['package'] / 'bundle.zip', expected, work)
    return {**report, 'assets': list(expected), 'narrationFlacBytes': len(expected['narration.flac']),
            'status': 'illustrative synthetic narration and machine draft text; no human review, listening or accessibility check',
            'runtimes': {'espeakng': native('espeak-version', [espeak, '--version'], work, timeout=20).decode().strip(), 'flac': native('flac-version', [flac, '--version'], work, timeout=20).decode().strip()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--infozip', type=Path, required=True, help='absolute Info-ZIP Zip 3.0 zip')
    parser.add_argument('--unzip', type=Path, required=True, help='absolute unzip used only as the independent extractor')
    parser.add_argument('--espeakng', type=Path, help='absolute eSpeak NG for the narration workflow (reported unavailable when absent)')
    parser.add_argument('--flac', type=Path, help='absolute FLAC for the narration workflow')
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--skip-budget', action='store_true')
    args = parser.parse_args()
    directory = args.output_directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    zip_, unzip = str(args.infozip.absolute()), str(args.unzip.absolute())
    locations = {'infozip': zip_}
    report = {'verified': False, 'acceptancePid': os.getpid(), 'sourceSha256': sha(Path(adaptor.__file__).read_bytes())}
    try:
        report['runtime'] = {'zip': native('zip-version', [zip_, '-v'], directory).decode().splitlines()[1], 'unzip': native('unzip-version', [unzip, '-v'], directory).decode().splitlines()[0]}
        atomic_json(directory / 'config.json', {'version': 1, 'locations': locations})
        saved = {k: os.environ.get(k) for k in ('SCHEMAXIS_CONFIG', 'SCHEMAXIS_INFOZIP')}
        os.environ['SCHEMAXIS_CONFIG'] = str(directory / 'config.json')
        os.environ.pop('SCHEMAXIS_INFOZIP', None)
        try:
            receipt = qualify(adaptor.VERSION, directory / 'kit', native=True, root=ROOT, locations=locations, timeout=60, wall_timeout=240)
            report['native'] = {'verified': receipt['verified'], 'cases': [c['id'] for c in receipt['cases']], 'runtimes': [c['runtime'] for c in receipt['cases']], 'lifecycle': receipt['lifecycle']}
            kit = directory / 'kit'
            work = directory / 'work'
            work.mkdir()
            for case in receipt['cases']:
                run = kit / case['id']
                record_run(run)
                names = [f['name'] for f in json.loads((run / 'plan.json').read_text())['files']]
                sources = {n: (run / 'pack' / n).read_bytes() for n in names}
                report.setdefault('kitIndependentExtraction', {})[case['id']] = independent_extract(unzip, run / 'bundle.zip', sources, work)
            with location_context(locations):
                report['literal'] = literal_cases(work, zip_, unzip)
                report['refusals'] = refusals(work, zip_, unzip)
                report['lifecycle'] = lifecycle(work, zip_)
                report['cli'] = cli(work, zip_, unzip)
                report['reuse'] = reuse(work, zip_)
                if not args.skip_budget:
                    report['budget'] = budget(work, zip_, unzip)
                if args.espeakng and args.flac:
                    report['speechWorkflow'] = speech_workflow(work, zip_, unzip, str(args.espeakng.absolute()), str(args.flac.absolute()))
                else:
                    report['speechWorkflow'] = 'unavailable: --espeakng and --flac were not both given; the narration workflow was not run'
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        report['verified'] = True
    finally:
        report['probeProcesses'] = PROCESSES
        report['adaptorNativeStages'] = RUNS
        report['processNote'] = ('probeProcesses are direct native subprocesses started by this tool. adaptorNativeStages come from each run\'s launcher record: the launcher wrote its pid and the argument array '
                                 'immediately before execve, so that pid is the native zip; exitCode is the supervisor-recorded status of that same process. The Python acceptance process, the shared '
                                 'runner and the replay supervisors are other processes and are not listed.')
        atomic_json(directory / 'acceptance.json', report)
    print(json.dumps({k: report[k] for k in report if k not in ('probeProcesses', 'adaptorNativeStages')}, indent=2))


if __name__ == '__main__':
    main()
