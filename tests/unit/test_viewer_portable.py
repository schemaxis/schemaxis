"""Portable distribution acceptance without site packages or the Schemaxis package.

Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
"""
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]


class PortableViewerTest(unittest.TestCase):
    def test_zip_runs_in_isolated_python_and_contains_only_viewer_modules(self):
        package = runpy.run_path(str(ROOT / 'tools/package_viewer.py'))['package']
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            sample = folder / 'input'
            sample.mkdir()
            (sample / 'sample.txt').write_text('synthetic test')
            archive = package(folder / 'viewer.zip', sample)
            with ZipFile(archive) as zipped:
                names = zipped.namelist()
                self.assertFalse(any('/schemaxis/' in name or '__pycache__' in name for name in names))
                self.assertIn('artifact-viewer/sample/sample.txt', names)
                zipped.extractall(folder / 'unpacked')
            isolated = folder / 'unpacked/artifact-viewer'
            result = subprocess.run([sys.executable, '-I', '-S', str(isolated / 'launch.py'), '--help'],
                                    capture_output=True, text=True, timeout=15, check=True)
            self.assertIn('--no-browser', result.stdout)
            script = '''import sys, threading
from urllib.request import urlopen
sys.path.insert(0, sys.argv[1])
from schemaxis_viewer.__main__ import make_server
server = make_server([sys.argv[1] + '/sample'])
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    for asset in ('', 'grouping.mjs', 'search-worker.mjs', 'search.mjs', 'text.mjs', 'filename-rules-worker.mjs', 'filename-rules-ui.mjs', 'automatic-sequences.mjs', 'file/0'):
        with urlopen(server.viewer_url + asset) as response:
            assert response.status == 200 and response.read()
    assert not any(name == 'schemaxis' or name.startswith('schemaxis.') for name in sys.modules)
finally:
    server.shutdown()
    server.server_close()
    thread.join(2)
'''
            subprocess.run([sys.executable, '-I', '-S', '-c', script, str(isolated)],
                           cwd=folder, env={key: value for key, value in os.environ.items() if key != 'PYTHONPATH'},
                           capture_output=True, text=True, timeout=15, check=True)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                package(archive)


if __name__ == '__main__':
    unittest.main()
