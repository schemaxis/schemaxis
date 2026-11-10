"""Info-ZIP native boundary with a fake ``zip`` executable: lifecycle, launch discipline, native-free verification and forgeries.

The fake is a small Python program that writes the canonical archive with test_infozip_fakes (or a defective one, selected by a
mode file next to it). It records its own environment, working directory and process id so the tests can prove what the real
launcher passes. Real Info-ZIP acceptance is tools/qualify_infozip.py; nothing here claims native behaviour.
"""
import contextlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from schemaxis.adaptors.infozip import adaptor
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_infozip_fakes import build_zip   # noqa: E402

TESTS = str(Path(__file__).resolve().parent)
BANNER = "Copyright (c) 1990-2008 Info-ZIP - Type 'zip \"-L\"' for software license.\\nThis is Zip 3.0 (July 5th 2008), by Info-ZIP.\\n"
FAKE = '''#!%(python)s
import json, os, sys, time, zipfile, io
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, %(tests)r)
from test_infozip_fakes import build_zip
mode, *rest = open(os.path.join(here, 'mode.txt')).read().split('\\n')
open(os.path.join(here, 'ran-' + str(len(os.listdir(here)))), 'w').close()
if sys.argv[1:] == ['-v']:
    sys.stdout.write('This is Zip 2.32 (June 19th 2006), by Info-ZIP.\\n' if mode == 'old' else 'bsdtar 3.7\\n' if mode == 'notzip' else %(banner)r)
    sys.exit(0)
json.dump({'env': dict(os.environ), 'cwd': os.getcwd(), 'pid': os.getpid(), 'argv': sys.argv}, open(os.path.join(here, 'observed.json'), 'w'))
args = sys.argv[1:]
assert args[:4] == ['-X', '-0', '-q', 'bundle.zip'], args
members = [(name, open(name, 'rb').read()) for name in args[4:]]
if mode == 'fail':
    sys.stderr.write('zip error: Interrupted (aborting)'); sys.exit(2)
if mode == 'sleep':
    time.sleep(60)
if mode == 'noisy':
    print('adding: x')
if mode == 'drop':
    members = members[:-1]
if mode == 'reorder':
    members[0], members[1] = members[1], members[0]
if mode == 'recrc':
    members[0] = (members[0][0], members[0][1][:-1] + bytes([members[0][1][-1] ^ 1]))
data = build_zip(members)
if mode == 'flip':
    data = bytearray(data); data[30 + len(members[0][0])] ^= 1; data = bytes(data)
if mode == 'suffix':
    data += b'\\0'
if mode == 'deflate':
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)
    data = buffer.getvalue()
open('bundle.zip', 'wb').write(data)
if mode == 'leftover':
    open('zipAB12cd', 'wb').write(b'temp')
if mode == 'mutate-source':
    open(rest[0], 'ab').write(b'!')
'''


class Fixture(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='infozip-test-'))
        self.addCleanup(shutil.rmtree, self.scratch, True)
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        config = self.scratch / 'config.json'
        config.write_text(json.dumps({'version': 1, 'locations': {}}))
        os.environ['SCHEMAXIS_CONFIG'] = str(config)
        os.environ.pop('SCHEMAXIS_INFOZIP', None)
        self.sources = self.scratch / 'sources'
        self.sources.mkdir()
        self.contents = {'report.txt': 'Café 日本語 report\n'.encode('utf-8'), 'tone.wav': bytes(range(256)) * 4, 'empty.txt': b''}
        for name, data in self.contents.items():
            (self.sources / name).write_bytes(data)
        self.zip_directory = self.scratch / 'fake'
        self.zip_directory.mkdir()
        self.zip = self.zip_directory / 'zip'
        self.zip.write_text(FAKE % {'python': sys.executable, 'tests': TESTS, 'banner': BANNER.replace('\\n', '\n')})
        self.zip.chmod(0o755)
        self.mode('good')

    def mode(self, name, *rest):
        (self.zip_directory / 'mode.txt').write_text('\n'.join([name, *rest]))

    def launches(self):
        return sorted(p.name for p in self.zip_directory.iterdir() if p.name.startswith('ran-'))

    def document(self, *names):
        return {'version': 'schemaxis.infozip/1', 'operation': 'bundle',
                'files': [{'name': {'report.txt': 'report.txt', 'tone.wav': 'tone.wav', 'empty.txt': 'empty.txt'}[n], 'source': str(self.sources / n)} for n in names or tuple(self.contents)]}

    def run_bundle(self, name='run', document=None, **keywords):
        return adaptor.run(document or self.document(), self.scratch / name, executable=str(self.zip), timeout=keywords.pop('timeout', 60), **keywords)

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def failed_run(self, code, name='failed', document=None):
        fault = self.fault(lambda: self.run_bundle(name, document), code)
        directory = self.scratch / name
        result = json.loads((directory / 'result.json').read_text())
        self.assertEqual((result['status'], result['verified'], result['fault']['code']), ('failed', False, code))
        for published in ('bundle.zip', 'bundle-summary.json', 'verification.json'):
            self.assertFalse((directory / published).exists(), published + ' survived a failed run')
        return fault


class InfozipLifecycle(Fixture):
    def test_good_run_publishes_two_artifacts_and_verifies_without_any_native_program(self):
        result = self.run_bundle()
        self.assertEqual((result['status'], result['verified'], result['members'], result['artifacts']), ('succeeded', True, 4, 2))
        directory = self.scratch / 'run'
        receipt = json.loads((directory / 'verification.json').read_text())
        self.assertEqual([(Path(a['file']).name, a['kind']) for a in receipt['artifacts']], [('bundle.zip', 'file'), ('bundle-summary.json', 'text')])
        names = ['report.txt', 'tone.wav', 'empty.txt', 'manifest.json']
        self.assertEqual([m['name'] for m in adaptor.parse_archive((directory / 'bundle.zip').read_bytes())], names)
        manifest = json.loads((directory / 'pack/manifest.json').read_text())
        self.assertEqual([(m['name'], m['bytes'], m['sha256']) for m in manifest['members']], [(n, len(self.contents[n]), adaptor.sha(self.contents[n])) for n in names[:3]])
        summary = json.loads((directory / 'bundle-summary.json').read_text())
        self.assertNotIn(str(self.sources), json.dumps(summary))
        self.assertEqual((summary['archive']['compression'], summary['archive']['members']), ('stored', 4))
        self.zip.unlink()                                        # the recorded executable is provenance only: verification never launches it
        self.assertEqual(adaptor.verify(directory)['members'], 4)
        self.assertEqual(adaptor.verify(directory)['runtime'], {'infozip': 'This is Zip 3.0 (July 5th 2008), by Info-ZIP.'})

    def test_native_launch_uses_the_fixed_argument_array_minimal_environment_and_recorded_pid(self):
        os.environ.update(ZIPOPT='-9 -r', UNZIPOPT='-o', HOME='/nonexistent-home', TMPDIR='/nonexistent-tmp', ZIP_TMP='1')
        self.run_bundle()
        observed = json.loads((self.zip_directory / 'observed.json').read_text())
        self.assertEqual(observed['env'], {'LANG': 'C', 'LC_ALL': 'C', 'TZ': 'UTC'})
        self.assertEqual(observed['argv'], [str(self.zip), '-X', '-0', '-q', 'bundle.zip', 'report.txt', 'tone.wav', 'empty.txt', 'manifest.json'])
        self.assertEqual(Path(observed['cwd']).name, 'pack')
        record = json.loads((self.scratch / 'run/bundle-process.json').read_text())
        self.assertEqual((record['pid'], record['argv']), (observed['pid'], observed['argv']))       # execve keeps the launcher's process id
        self.assertEqual(json.loads((self.scratch / 'run/version-process.json').read_text())['argv'], [str(self.zip), '-v'])
        for name in self.contents:                                # sources are untouched and the staged captures carry the fixed time and mode
            self.assertEqual((self.sources / name).read_bytes(), self.contents[name])
        staged = (self.scratch / 'run/pack/report.txt').stat()
        self.assertEqual((staged.st_mtime, stat.S_IMODE(staged.st_mode)), (adaptor.EPOCH, 0o600))

    def test_invalid_plan_creates_nothing_and_never_launches(self):
        bad = self.document()
        bad['files'][0]['name'] = 'Report.TXT'
        self.fault(lambda: self.run_bundle('never', bad), 'INVALID_INFOZIP_NAME')
        self.assertFalse((self.scratch / 'never').exists())
        self.assertEqual(self.launches(), [])

    def test_unavailable_runtime_creates_nothing(self):
        for value in (None, 'zip', str(self.scratch / 'absent' / 'zip')):
            self.fault(lambda: adaptor.run(self.document(), self.scratch / 'none', executable=value, timeout=60), 'INTERPRETER_NOT_FOUND')
        self.assertFalse((self.scratch / 'none').exists())
        self.zip.chmod(0o644)
        self.fault(lambda: self.run_bundle('none'), 'INTERPRETER_NOT_FOUND')

    def test_existing_output_directory_is_refused_untouched(self):
        (self.scratch / 'taken').mkdir()
        (self.scratch / 'taken/keep.txt').write_text('keep')
        self.fault(lambda: self.run_bundle('taken'), 'OUTPUT_EXISTS')
        self.assertEqual(sorted(p.name for p in (self.scratch / 'taken').iterdir()), ['keep.txt'])
        self.assertEqual(self.launches(), [])

    def test_unsupported_and_foreign_executables_are_distinct_faults(self):
        for mode in ('old', 'notzip'):
            self.mode(mode)
            self.failed_run('UNSUPPORTED_RUNTIME', 'foreign-' + mode)

    def test_source_defects_are_refused_before_any_native_process(self):
        os.symlink(self.sources / 'report.txt', self.sources / 'link.txt')
        os.mkdir(self.sources / 'dir')
        os.mkfifo(self.sources / 'fifo')
        for index, target in enumerate(('absent.txt', 'link.txt', 'dir', 'fifo')):
            bad = self.document('report.txt')
            bad['files'].append({'name': 'other.txt', 'source': str(self.sources / target)})
            fault = self.failed_run('INVALID_INFOZIP_SOURCE', 'bad-%d' % index, bad)
            self.assertEqual(fault.location, '$.files[1].source')
            self.assertFalse((self.scratch / ('bad-%d' % index) / 'pack').exists())
        with mock.patch.object(adaptor, 'MAX_MEMBER_BYTES', 100):
            self.failed_run('INFOZIP_BUDGET', 'big', self.document('tone.wav'))
        with mock.patch.object(adaptor, 'MAX_TOTAL_BYTES', 1030):
            self.failed_run('INFOZIP_BUDGET', 'total')
        self.assertEqual(self.launches(), [])

    def test_native_failures_keep_their_distinct_codes_and_publish_nothing(self):
        self.mode('fail')
        fault = self.failed_run('NATIVE_EXECUTION_FAILED', 'native-fail')
        self.assertIn('exit 2', fault.message)
        self.mode('noisy')
        self.failed_run('NATIVE_EXECUTION_FAILED', 'noisy')
        for mode in ('flip', 'suffix', 'deflate', 'drop', 'reorder', 'recrc'):
            self.mode(mode)
            self.failed_run('INVALID_INFOZIP_ARCHIVE', 'archive-' + mode)

    def test_leftover_native_temporary_file_fails_the_run_closed(self):
        self.mode('leftover')
        self.failed_run('VERIFICATION_FAILED', 'leftover')

    def test_source_changing_during_the_bundle_is_detected(self):
        self.mode('mutate-source', str(self.sources / 'report.txt'))
        fault = self.failed_run('INVALID_INFOZIP_SOURCE', 'changed')
        self.assertEqual(fault.location, '$.files[0].source')

    def test_timeout_is_bounded_and_leaves_no_published_artifact(self):
        self.mode('sleep')
        start = time.monotonic()
        fault = self.fault(lambda: adaptor.run(self.document(), self.scratch / 'slow', executable=str(self.zip), timeout=3), 'RUNNER_TIMED_OUT')
        self.assertLess(time.monotonic() - start, 30)
        self.assertEqual(json.loads((self.scratch / 'slow/result.json').read_text())['status'], 'failed')
        self.assertFalse((self.scratch / 'slow/bundle.zip').exists())
        probe = subprocess.run(['pgrep', '-f', str(self.zip_directory / '[z]ip')], capture_output=True, timeout=10)
        self.assertEqual(probe.returncode, 1, 'a fake native process survived the timeout')

    def test_invalid_timeouts_are_refused_before_creation(self):
        for value in (0, -1, float('nan'), float('inf'), True, '3', 3601):
            self.fault(lambda: adaptor.run(self.document(), self.scratch / 'badtime', executable=str(self.zip), timeout=value), 'INVALID_ARGUMENT')
        self.assertFalse((self.scratch / 'badtime').exists())


def refresh(directory):
    """Rewrite the receipt's artifact paths, digests and evidence digests from the files now on disk, so only semantics can object."""
    directory = Path(directory)
    receipt = json.loads((directory / 'verification.json').read_text())
    names = [f['name'] for f in json.loads((directory / 'plan.json').read_text())['files']]
    receipt['artifacts'] = [{'file': str(directory / n), 'kind': k, 'sha256': adaptor.sha((directory / n).read_bytes())}
                            for n, k in (('bundle.zip', 'file'), ('bundle-summary.json', 'text')) if (directory / n).is_file()]
    receipt['evidence'] = {n: adaptor.sha((directory / n).read_bytes()) for n in sorted(adaptor.evidence_names(names)) if (directory / n).is_file()}
    (directory / 'verification.json').write_text(json.dumps(receipt))


class InfozipForgeries(Fixture):
    def setUp(self):
        super().setUp()
        self.run_bundle('original')
        self.names = ['report.txt', 'tone.wav', 'empty.txt']

    @contextlib.contextmanager
    def copy(self):
        target = self.scratch / ('copy-%d' % time.monotonic_ns())
        shutil.copytree(self.scratch / 'original', target, symlinks=True)
        yield target

    def judged(self, mutate, code='VERIFICATION_FAILED', reread=True):
        with self.copy() as target:
            if reread:
                mutate(target)
                refresh(target)
            else:                                            # receipt edits happen after the hashes are made consistent
                refresh(target)
                mutate(target)
            return self.fault(lambda: adaptor.verify_semantic(target), code)

    def edit_json(self, name, change):
        def mutate(target):
            path = target / name
            document = json.loads(path.read_text())
            change(document)
            path.write_text(json.dumps(document))
        return mutate

    def test_pristine_copy_verifies_after_refresh_only(self):
        with self.copy() as target:
            refresh(target)
            self.assertTrue(adaptor.verify_semantic(target)['verified'])

    def test_archive_forgeries_with_refreshed_hashes_are_refused(self):
        members = [(n, self.contents[n]) for n in self.names]
        manifest = (self.scratch / 'original/pack/manifest.json').read_bytes()
        good = build_zip(members + [('manifest.json', manifest)])
        for label, data in {'member byte, consistent CRC': build_zip([(members[0][0], members[0][1] + b'!')] + members[1:] + [('manifest.json', manifest)]),
                            'different manifest': build_zip(members + [('manifest.json', manifest.replace(b'report', b'rep0rt'))]),
                            'member dropped': build_zip(members[:2] + [('manifest.json', manifest)]),
                            'order changed': build_zip([members[1], members[0], members[2], ('manifest.json', manifest)]),
                            'trailing byte': good + b'\0', 'prefix': b'\0' + good, 'extra member': build_zip(members + [('x.txt', b''), ('manifest.json', manifest)]),
                            'compressed': build_zip(members + [('manifest.json', manifest)], method=8), 'flag bits': build_zip(members + [('manifest.json', manifest)], flags=1),
                            'empty': b''}.items():
            with self.subTest(label):
                self.judged(lambda target, d=data: (target / 'bundle.zip').write_bytes(d))

    def test_capture_summary_and_manifest_forgeries_are_refused(self):
        self.judged(lambda t: (t / 'pack/report.txt').write_bytes(b'tampered'))
        self.judged(lambda t: (t / 'pack/manifest.json').write_bytes((t / 'pack/manifest.json').read_bytes() + b' '))
        self.judged(lambda t: (t / 'pack/empty.txt').write_bytes(b'x'))
        self.judged(self.edit_json('bundle-summary.json', lambda d: d['archive'].update(bytes=d['archive']['bytes'] + 1)))
        self.judged(self.edit_json('bundle-summary.json', lambda d: d['members'][0].update(sha256='0' * 64)))
        self.judged(self.edit_json('bundle-summary.json', lambda d: d['readback'].update(everyByteCompared=1)))
        self.judged(self.edit_json('bundle-summary.json', lambda d: d.update(extra=1)))
        self.judged(self.edit_json('captures.json', lambda d: d['files'][0].update(sha256='1' * 64)))
        self.judged(self.edit_json('captures.json', lambda d: d['files'].pop()))
        self.judged(self.edit_json('plan.json', lambda d: d['files'].pop()))
        self.judged(self.edit_json('authored.json', lambda d: d['files'].pop()))
        self.judged(self.edit_json('authored.json', lambda d: d['files'][0].update(name='manifest.json')))

    def test_result_receipt_and_claim_forgeries_are_refused(self):
        self.judged(self.edit_json('result.json', lambda d: d['bytes'].update(archive=True)))
        self.judged(self.edit_json('result.json', lambda d: d['bytes'].update(members=d['bytes']['members'] + 0.0)))
        self.judged(self.edit_json('result.json', lambda d: d.update(promoted=True)))
        self.judged(self.edit_json('result.json', lambda d: d.update(archiveSha256='2' * 64)))
        self.judged(self.edit_json('result.json', lambda d: d.update(members=3)))
        self.judged(self.edit_json('result.json', lambda d: d.pop('operation')))
        self.judged(self.edit_json('result.json', lambda d: d['runtime'].update(infozip='This is Zip 3.0 (July 5th 2008), by Info-ZIP')))
        self.judged(self.edit_json('result.json', lambda d: d.update(status='failed')), 'INCOMPLETE_EXECUTION')
        self.judged(self.edit_json('verification.json', lambda d: d['artifacts'].pop()), reread=False)
        self.judged(self.edit_json('verification.json', lambda d: d['artifacts'][0].update(kind='text')), reread=False)
        self.judged(self.edit_json('verification.json', lambda d: d['evidence'].pop('captures.json')), reread=False)
        self.judged(self.edit_json('verification.json', lambda d: d['executables'].update(infozip='zip')), reread=False)
        self.judged(self.edit_json('verification.json', lambda d: d['executables'].update(extra='/bin/true')), reread=False)
        self.judged(self.edit_json('verification.json', lambda d: d['runtime'].update(infozip='This is Zip 3.0 (July 5th 2008), by Info-ZIP')), reread=False)
        for claim in ({'signed': True}, {'verified': True}, {'signature': 'x'}):          # the receipt is closed: no extra signed or verified claim
            self.judged(self.edit_json('verification.json', lambda d, claim=claim: d.update(claim)), reread=False)
        self.judged(self.edit_json('verification.json', lambda d: d.pop('runtime')), reread=False)
        self.judged(lambda t: (t / 'verification.json').write_text(json.dumps([])), reread=False)

    def test_native_recipe_forgeries_are_refused(self):
        self.judged(self.edit_json('bundle-submission.json', lambda d: d.update(exitCode=1)))
        self.judged(self.edit_json('bundle-submission.json', lambda d: d.update(exitCode=False)))
        self.judged(self.edit_json('bundle-submission.json', lambda d: d.update(nativeCommand=['/bin/sh', '-c', 'true'])))
        self.judged(self.edit_json('bundle-process.json', lambda d: d.update(pid='1')))
        self.judged(self.edit_json('bundle-process.json', lambda d: d.update(pid=0)))
        self.judged(self.edit_json('bundle-process.json', lambda d: d['argv'].insert(1, '-r')))
        self.judged(self.edit_json('bundle-inputs.json', lambda d: d.update(**{'report.txt': '3' * 64})))
        self.judged(self.edit_json('version-inputs.json', lambda d: d.update(extra='4' * 64)))
        self.judged(lambda t: (t / 'bundle-launcher.py').write_text((t / 'bundle-launcher.py').read_text() + '\nprint(1)\n'))
        self.judged(lambda t: (t / 'bundle-launcher.py').write_text((t / 'bundle-launcher.py').read_text().replace('"TZ": "UTC"', '"TZ": "UTC", "ZIPOPT": "-9"').replace("'TZ': 'UTC'", "'TZ': 'UTC', 'ZIPOPT': '-9'")))
        self.judged(lambda t: (t / 'bundle.stdout').write_text('adding: x'))
        self.judged(lambda t: (t / 'version.stdout').write_text('This is Zip 2.32 (June 19th 2006), by Info-ZIP.\n'), 'UNSUPPORTED_RUNTIME')
        self.judged(lambda t: (t / 'bundle-submission.json').unlink(), reread=True)

    def test_membership_symlink_and_json_hygiene_forgeries_are_refused(self):
        self.judged(lambda t: (t / 'notes.txt').write_text('extra'))
        self.judged(lambda t: (t / 'pack/extra.txt').write_text('extra'))
        self.judged(lambda t: (t / 'pack/bundle.zip').write_bytes(b'leftover'))
        self.judged(lambda t: (t / 'pack/report.txt').unlink() or os.symlink(self.sources / 'report.txt', t / 'pack/report.txt'))
        self.judged(lambda t: (t / 'bundle.zip').unlink() or os.symlink(self.scratch / 'original/bundle.zip', t / 'bundle.zip'))
        self.judged(lambda t: (t / 'pack').rename(t / 'moved') or os.symlink(t / 'moved', t / 'pack'))
        self.judged(lambda t: (t / 'result.json').write_text('{"status": "succeeded", "status": "succeeded"}'))
        self.judged(lambda t: (t / 'result.json').write_text('{"status": "succeeded", "n": NaN}'))
        self.judged(lambda t: (t / 'bundle-summary.json').write_bytes(b'\xef\xbb\xbf' + (t / 'bundle-summary.json').read_bytes()))
        self.judged(lambda t: (t / 'captures.json').write_text('{"files": 1e400}'))
        self.judged(lambda t: (t / 'plan.json').write_text('[' * 50000), reread=False)

    def test_the_originals_may_move_without_affecting_verification(self):
        for name in self.contents:
            (self.sources / name).write_bytes(b'moved and different')
        self.assertTrue(adaptor.verify(self.scratch / 'original')['verified'])

    def test_a_failed_attempt_directory_does_not_verify(self):
        self.mode('fail')
        self.fault(lambda: self.run_bundle('attempt'), 'NATIVE_EXECUTION_FAILED')
        self.fault(lambda: adaptor.verify_semantic(self.scratch / 'attempt'), 'INCOMPLETE_EXECUTION')


if __name__ == '__main__':
    unittest.main()
