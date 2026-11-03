# Copyright (C) 2026 David L F Gaden
"""Host-only commands avoid POSIX-only imports (no claim of Windows support)."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PortableHostImportTests(unittest.TestCase):
    def test_host_commands_do_not_require_fcntl(self):
        script = r'''
import importlib.abc, sys
class NoFcntl(importlib.abc.MetaPathFinder):
    def find_spec(self, name, *args):
        if name == 'fcntl': raise ModuleNotFoundError("No module named 'fcntl'", name=name)
sys.modules.pop('fcntl', None)
sys.meta_path.insert(0, NoFcntl())
from schemaxis.__main__ import main
source = sys.argv[1]
def cli(*args):
    sys.argv = ['schemaxis', *args]
    return main()
assert cli('discover')['providers']
assert cli('describe', '--provider', 'gmsh')
assert cli('schema', '--provider', 'gmsh')
assert cli('plan', source)
print('ok')
'''
        result = subprocess.run([sys.executable, '-c', script, str(ROOT/'examples/schemaxis/blender-lathe.json')],
                                env={**os.environ, 'PYTHONPATH': str(ROOT/'src')}, capture_output=True, text=True,
                                timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        self.assertEqual(result.stdout.strip().splitlines()[-1], 'ok')


if __name__ == '__main__':
    unittest.main()
