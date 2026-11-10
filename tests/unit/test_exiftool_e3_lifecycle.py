"""Live process lifecycle of the three E3 write operations (correctTime, setLocation, geotagFromTrack) against a genuine ExifTool 13.55.

For each operation a real WRITE-stage ExifTool Perl process is observed (system Perl, the ExifTool script, ``-config`` with its empty argument, ``-n``, the fixed
assignments, ``-o stage/ID.jpg captured/ID.jpg``) after the launcher bound the input digests, held with a test-owned SIGSTOP, and then ended by the operation's own timeout or
by its cancel. The process must have led its own process group (PID equals PGID), the dispatch leader must have exited by signal (-15 or -9), the process and its group must
be gone without the test's own safety-net kill, the run must have failed with a structured fault, and no success publication, plan, report or image may exist.

The hold proves that timeout and cancel reach a live write process and its group; it does not prove they fired at a particular point inside ExifTool. The ``/proc`` argv
is read as raw NUL-separated bytes so that the empty ``-config`` argument is preserved (an older reader dropped empty elements).
Skipped unless SCHEMAXIS_EXIFTOOL names an absolute ExifTool 13.55 script.
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
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests/unit'))

import exiftool_e3_fixtures as fx  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from schemaxis.dispatch import allocation  # noqa: E402
from test_exiftool_e3_gpx import doc as gpx  # noqa: E402
from test_exiftool_write_complete import descendants, group_alive, pid_alive  # noqa: E402

V = 'schemaxis.exiftool/1'
PUBLISHED = {'verification.json', 'manifest.json', 'photos', 'outcomes', 'rejected', 'runtime.json', 'after.stdout', 'write-report.json', 'residual.json', 'time-report.json',
             'time-correction-plan.json', 'location-plan.json', 'geotag-plan.json', 'track-report.json'}
TRACK = gpx([[('0', '10.000', '2026-03-01T10:59:00Z', '10'), ('0', '10.002', '2026-03-01T11:01:00Z', '20')]])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def cmdline(pid):
    """The argv of a process with every element preserved, including empty ones (the file ends with one NUL that terminates the last element)."""
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
        cls.tmp = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-e3-lifecycle-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)       # only the directory this class created
        cls.media = cls.tmp / 'media'
        cls.media.mkdir()
        cls.photo = fx.full_time()
        (cls.media / 'live.jpg').write_bytes(cls.photo)
        (cls.tmp / 'walk.gpx').write_bytes(TRACK)
        items = {'items': [{'id': 'live', 'path': str(cls.media / 'live.jpg')}]}
        cls.documents = {
            'correctTime': {'version': V, 'operation': 'correctTime', 'media': items, 'corrections': [{'group': 'dev1', 'shift': {'seconds': '60'}}]},
            'setLocation': {'version': V, 'operation': 'setLocation', 'media': items, 'positions': [{'item': 'live', 'latitude': '10.5', 'longitude': '20.25'}]},
            'geotagFromTrack': {'version': V, 'operation': 'geotagFromTrack', 'media': items, 'tracks': [{'id': 'walk', 'path': str(cls.tmp / 'walk.gpx')}]}}

    def hold(self, operation, kind):
        directory = self.tmp / ('live-%s-%s' % (operation, kind))
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
                        if len(command) > 4 and command[1] == str(self.exe) and '-o' in command and command[-1] == 'captured/live.jpg' and image == perl:
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
                    adaptor.run(self.documents[operation], directory, executable=self.exe, timeout=8 if kind == 'timeout' else 120)
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
        self.assertTrue(held.get('stopped'), 'the real write process was never observed before the hold')
        self.assertFalse(safety_net, 'the operation left the write process or its group alive')
        self.assertFalse(pid_alive(held['pid']) or group_alive(held['pgid']))
        self.assertEqual(held['pid'], held['pgid'])                                         # the write process leads its own process group
        self.assertNotEqual(held['pgid'], os.getpgid(0))
        command = held['command']
        at = command.index('-config')
        self.assertEqual(command[at + 1], '', 'the empty -config argument must be preserved in the observed argv')
        self.assertIn('-n', command)
        self.assertEqual(command[1], str(self.exe))
        self.assertEqual((command[-3], command[-1]), ('-o', 'captured/live.jpg'))
        self.assertTrue(command[-2].startswith('stage/') and command[-2].endswith('live.jpg'), command[-2])
        fault = caught.exception.fault
        self.assertIn(fault.observed['exitCode'], (-15, -9))
        self.assertEqual(held['boundInputs']['files']['captured/live.jpg'], sha(self.photo))
        names = {x.name for x in directory.iterdir()}
        self.assertFalse(names & PUBLISHED, sorted(names))
        result = json.loads((directory / 'result.json').read_text())
        self.assertEqual((result['status'], result['fault']['code']), ('failed', fault.code))
        self.assertEqual((directory / 'version.stdout').read_bytes(), b'13.55\n')
        self.assertTrue((directory / 'before.stdout').is_file())                            # the read stages completed; the hold is on the WRITE stage only
        Lifecycle.RESULTS['%s-%s' % (operation, kind)] = {
            'operation': operation, 'kind': kind, 'fault': fault.code, 'observedWritePid': held['pid'], 'observedProcessGroup': held['pgid'], 'pidEqualsPgid': True, 'procExe': held['exe'], 'argv': command,
            'emptyConfigArgumentPreserved': True, 'launcherBoundInputs': held['boundInputs'], 'dispatchLeaderExitCode': fault.observed['exitCode'], 'pidGone': True, 'processGroupGone': True,
            'safetyNetKillNeeded': False, 'resultStatus': 'failed', 'noSuccessPublication': True, 'elapsedSeconds': round(time.monotonic() - started, 2), 'container': 'jpeg',
            'stageHoldLimits': 'SIGSTOP applied after the launcher bound the inputs and a Perl write process was observed; no claim that the timeout or cancel fired inside ExifTool'}
        return fault

    def test_correct_time_timeout(self):
        self.assertEqual(self.hold('correctTime', 'timeout').code, 'RUNNER_TIMED_OUT')

    def test_correct_time_cancel(self):
        self.assertEqual(self.hold('correctTime', 'cancel').code, 'RUNNER_CANCELLED')

    def test_set_location_timeout(self):
        self.assertEqual(self.hold('setLocation', 'timeout').code, 'RUNNER_TIMED_OUT')

    def test_set_location_cancel(self):
        self.assertEqual(self.hold('setLocation', 'cancel').code, 'RUNNER_CANCELLED')

    def test_geotag_from_track_timeout(self):
        self.assertEqual(self.hold('geotagFromTrack', 'timeout').code, 'RUNNER_TIMED_OUT')

    def test_geotag_from_track_cancel(self):
        self.assertEqual(self.hold('geotagFromTrack', 'cancel').code, 'RUNNER_CANCELLED')


if __name__ == '__main__':
    unittest.main()
