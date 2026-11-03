# Copyright (C) 2026 David L F Gaden
"""Exercise the public command, routed inputs and structured failures."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]


class SchemaxisCLITests(unittest.TestCase):
    def cli(self, module, *args, input=None):
        return subprocess.run(
            [sys.executable, '-m', module, *args], input=input, text=True,
            capture_output=True, cwd=ROOT,
            env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, timeout=30,
        )

    def test_discovery_uses_current_namespace(self):
        result = self.cli('schemaxis', 'discover')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        discovery = json.loads(result.stdout)
        self.assertIn('plan', discovery['commands'])
        self.assertIn('schemaxis', discovery['commands'])
        self.assertIn('schemaxis.gmsh/1', result.stdout)
        self.assertIn('schemaxis/1', result.stdout)

    def test_authored_input_plans_from_file_and_stdin(self):
        path = ROOT / 'examples/schemaxis/gmsh-minimal.json'
        stdin = self.cli('schemaxis', 'plan', '-', input=path.read_text())
        file = self.cli('schemaxis', 'plan', str(path))
        self.assertEqual(stdin.returncode, 0, stdin.stdout + stdin.stderr)
        self.assertEqual(file.returncode, 0, file.stdout + file.stderr)
        self.assertEqual(json.loads(stdin.stdout), json.loads(file.stdout))

    def test_new_command_preserves_structured_fault_and_failure_exit(self):
        result = self.cli('schemaxis', 'plan', '-', input='{"version":"invalid/1"}')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('fault', json.loads(result.stdout))


if __name__ == '__main__':
    unittest.main()
