"""Live process lifecycle of editMetadata over each E5 container against a genuine ExifTool 13.55.

A real WRITE-stage ExifTool Perl process (system Perl, the ExifTool script, ``-config`` with its empty argument, the fixed assignments, ``-o stage/live.<ext> captured/live.<ext>``) writes a
TIFF, DNG, PNG, WebP or HEIF capture. The process is observed after the launcher bound the input digests, held with a test-owned SIGSTOP, and ended by the operation's own timeout or by
its cancel. It must have led its own process group (PID equals PGID), the dispatch leader must have exited by signal (-15 or -9), the process and its group must be gone without the
test's own safety-net kill, the run must have failed with a structured fault, and no success publication, plan, report or photo may exist.

The hold proves that timeout and cancel reach a live native process and its group for each container; it does not prove they fired at a particular point inside ExifTool. The ``/proc`` argv is
read as raw NUL-separated bytes so that the empty ``-config`` argument is preserved. Skipped unless SCHEMAXIS_EXIFTOOL names an absolute ExifTool 13.55 script.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/unit')]

import exiftool_e5_fixtures as f  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from schemaxis.dispatch import allocation  # noqa: E402
from test_exiftool_write_complete import descendants, group_alive, pid_alive  # noqa: E402

V = 'schemaxis.exiftool/1'
PUBLISHED = {'verification.json', 'manifest.json', 'photos', 'runtime.json', 'after.stdout', 'edit-plan.json', 'edit-report.json'}
CONTAINERS = {'tiff': ('.tif', lambda: f.plain_tiff('<')), 'dng': ('.dng', lambda: f.dng()[0]), 'png': ('.png', f.basic_png), 'webp': ('.webp', lambda: f.riff(f.vp8x(0x0C), f.ck(b'VP8 ', f.vp8()), f.webp_exif(), f.webp_xmp())),
              'heif': ('.heic', lambda: f.heic_basic(with_metadata=True))}


def cmdline(pid):
    raw = Path('/proc/%d/cmdline' % pid).read_bytes()
    return [part.decode() for part in raw.split(b'\0')[:-1]] if raw.endswith(b'\0') else [part.decode() for part in raw.split(b'\0')]


class Lifecycle(unittest.TestCase):
    RESULTS = {}

    @classmethod
    def setUpClass(cls):
        path = os.environ.get('SCHEMAXIS_EXIFTOOL')
        if not path or not os.path.isabs(path) or not Path(path).is_file() or not Path(adaptor.PERL).is_file():
            raise unittest.SkipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL')
        cls.exe = path
        cls.tmp = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-e5-lifecycle-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.media = cls.tmp / 'media'
        cls.media.mkdir()
        cls.documents = {}
        for container, (suffix, make) in CONTAINERS.items():
            (cls.media / ('live' + suffix)).write_bytes(make())
            cls.documents[container] = {'version': V, 'operation': 'editMetadata', 'media': {'items': [{'id': 'live', 'path': str(cls.media / ('live' + suffix))}]},
                                        'edits': {'title': {'set': 'Quarry gate north'}, 'creator': {'set': ['B. Mason']}}}

    def hold(self, container, kind, key=None):
        key = key or container
        suffix = CONTAINERS[container][0]
        directory = self.tmp / ('live-%s-%s' % (key, kind))
        last = 'captured/live' + suffix
        held, event = {}, threading.Event()
        perl = os.path.realpath(adaptor.PERL)

        def watch():
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline and not held:
                inputs = directory / 'write-live-inputs.json'
                if inputs.is_file() and inputs.stat().st_size:
                    for pid in descendants(os.getpid()):
                        try:
                            command = cmdline(pid)
                            image = os.path.realpath('/proc/%d/exe' % pid)
                            group = os.getpgid(pid)
                        except OSError:
                            continue
                        if len(command) > 4 and command[1] == str(self.exe) and '-o' in command and command[-1] == last and image == perl:
                            held.update(pid=pid, pgid=group, command=command, exe=image, boundInputs=json.loads(inputs.read_text()))
                            os.kill(pid, signal.SIGSTOP)
                            held['stopped'] = True
                            if kind == 'cancel':
                                time.sleep(0.5)
                                event.set()
                            return
                time.sleep(0.02)
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        started, safety_net = time.monotonic(), False
        try:
            with allocation({'threads': 1}, cancel=event):
                with self.assertRaises(SchemaxisError) as caught:
                    adaptor.run(self.documents[key], directory, executable=self.exe, timeout=8 if kind == 'timeout' else 120)
        finally:
            watcher.join(5)
            pid, pgid = held.get('pid'), held.get('pgid')
            if pid:
                end = time.monotonic() + 10
                while time.monotonic() < end and (pid_alive(pid) or group_alive(pgid)):
                    time.sleep(0.1)
                if pid_alive(pid) or group_alive(pgid):
                    safety_net = True
                    for sig in (signal.SIGCONT, signal.SIGKILL):
                        try:
                            os.kill(pid, sig)
                        except ProcessLookupError:
                            pass
        self.assertTrue(held.get('stopped'), 'the real native process was never observed before the hold')
        self.assertFalse(safety_net, 'the operation left the native process or its group alive')
        self.assertFalse(pid_alive(held['pid']) or group_alive(held['pgid']))
        self.assertEqual(held['pid'], held['pgid'])
        self.assertNotEqual(held['pgid'], os.getpgid(0))
        command = held['command']
        self.assertEqual(command[command.index('-config') + 1], '', 'the empty -config argument must be preserved in the observed argv')
        self.assertEqual(command[1], str(self.exe))
        fault = caught.exception.fault
        self.assertIn(fault.observed['exitCode'], (-15, -9))
        self.assertIn(last, held['boundInputs']['files'])
        names = {x.name for x in directory.iterdir()}
        self.assertFalse(names & PUBLISHED, sorted(names))
        result = json.loads((directory / 'result.json').read_text())
        self.assertEqual((result['status'], result['fault']['code']), ('failed', fault.code))
        Lifecycle.RESULTS['%s-%s' % (key, kind)] = {
            'operation': self.documents[key]['operation'], 'container': container, 'kind': kind, 'stage': 'write', 'fault': fault.code, 'observedPid': held['pid'], 'observedProcessGroup': held['pgid'], 'pidEqualsPgid': True,
            'procExe': held['exe'], 'argv': command, 'emptyConfigArgumentPreserved': True, 'launcherBoundInputs': held['boundInputs'], 'dispatchLeaderExitCode': fault.observed['exitCode'], 'pidGone': True,
            'processGroupGone': True, 'safetyNetKillNeeded': False, 'resultStatus': 'failed', 'noSuccessPublication': True, 'elapsedSeconds': round(time.monotonic() - started, 2),
            'stageHoldLimits': 'SIGSTOP applied after the launcher bound the inputs and a Perl process was observed; no claim that the timeout or cancel fired inside ExifTool'}
        return fault


def _case(container, kind, code):
    def test(self):
        self.assertEqual(self.hold(container, kind).code, code)
    return test


for _container in CONTAINERS:
    setattr(Lifecycle, 'test_%s_timeout' % _container, _case(_container, 'timeout', 'RUNNER_TIMED_OUT'))
    setattr(Lifecycle, 'test_%s_cancel' % _container, _case(_container, 'cancel', 'RUNNER_CANCELLED'))


if __name__ == '__main__':
    unittest.main()
