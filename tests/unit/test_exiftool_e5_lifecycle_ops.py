"""Live process lifecycle of the E5 time, location, transfer and minimise writes over the containers, against a genuine ExifTool 13.55.

The mechanics are those of ``test_exiftool_e5_lifecycle`` (a real WRITE-stage Perl process is observed after the launcher bound its inputs, held with a test-owned SIGSTOP, and ended by the
operation's own timeout or by its cancel; PID equals PGID, the leader exits by signal, the process and its group are gone without the safety net, the run fails structured, nothing is
published). Each operation below plans its arguments differently, so each is held for its own container pair; the hold proves that timeout and cancel reach the live native process of that
write, not that they fired at a particular point inside ExifTool.
"""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/unit')]

import exiftool_e4_fixtures as f4  # noqa: E402
import exiftool_e5_time_fixtures as t  # noqa: E402
import test_exiftool_e5_lifecycle as base  # noqa: E402

V = 'schemaxis.exiftool/1'
ITEM = lambda path: {'id': 'live', 'path': str(path)}                                                       # noqa: E731
OPERATIONS = {
    'correctTime': (('tiff', 'webp'), lambda m, p: {'operation': 'correctTime', 'media': {'items': [ITEM(p)]}, 'corrections': [{'group': 'dev1', 'shift': {'seconds': '3600'}}]}),
    'setLocation': (('png', 'heif'), lambda m, p: {'operation': 'setLocation', 'media': {'items': [ITEM(p)]}, 'default': {'latitude': '35.658581', 'longitude': '139.745433'}}),
    'copyMetadata': (('dng', 'png'), lambda m, p: {'operation': 'copyMetadata', 'media': {'items': [{'id': 'src', 'path': str(m / 'src.jpg')}, ITEM(p)]}, 'source': {'item': 'src'},
                                                  'transfer': {'groups': ['descriptive', 'camera']}, 'policies': {'existing': 'replace'}}),
    'minimise': (('png', 'webp'), lambda m, p: {'operation': 'removeMetadata', 'media': {'items': [ITEM(p)]}, 'categories': ['minimise']}),
}


class LifecycleOps(base.Lifecycle):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        (cls.media / 'src.jpg').write_bytes(f4.master())
        for name, (containers, build) in OPERATIONS.items():
            for container in containers:
                suffix = t.EXTENSIONS[container]
                path = cls.media / ('live-%s%s' % (name, suffix))
                path.write_bytes(t.png_g6() if name == 'minimise' and container == 'png' else t.full_time(container) if name != 'minimise' else t.container('webp', xmp=None))
                # the stage input is named captured/live<suffix> whatever the source name is, so each document points at its own source file
                cls.documents['%s-%s' % (name, container)] = {'version': V, **build(cls.media, path)}


def _case(name, container, kind, code):
    def test(self):
        self.assertEqual(self.hold(container, kind, '%s-%s' % (name, container)).code, code)
    return test


for _name, (_containers, _build) in OPERATIONS.items():
    for _container in _containers:
        setattr(LifecycleOps, 'test_%s_%s_timeout' % (_name, _container), _case(_name, _container, 'timeout', 'RUNNER_TIMED_OUT'))
        setattr(LifecycleOps, 'test_%s_%s_cancel' % (_name, _container), _case(_name, _container, 'cancel', 'RUNNER_CANCELLED'))

for _inherited in [n for n in dir(base.Lifecycle) if n.startswith('test_')]:
    setattr(LifecycleOps, _inherited, None)       # the editMetadata cases belong to the base module; they are not run twice


if __name__ == '__main__':
    unittest.main()
