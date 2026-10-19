"""Public help/version discovery and host-only CLI behaviour."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.__main__ import project_version

ROOT = Path(__file__).resolve().parents[2]


class CLIDiscoveryTests(unittest.TestCase):
    def cli(self, *args, entry='module'):
        prefix = ([sys.executable, '-m', 'schemaxis'] if entry == 'module' else
                  [sys.executable, '-c', 'import sys; from schemaxis.__main__ import console_main; sys.exit(console_main())'])
        environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        environment.pop('DISPLAY', None)
        environment.pop('WAYLAND_DISPLAY', None)
        return subprocess.run([*prefix, *args], cwd=ROOT, env=environment,
                              capture_output=True, text=True, timeout=40)

    def test_version_uses_distribution_and_source_fallback(self):
        with patch('importlib.metadata.version', return_value='9.8.7'):
            self.assertEqual(project_version(), '9.8.7')
        from importlib.metadata import PackageNotFoundError
        with patch('importlib.metadata.version', side_effect=PackageNotFoundError):
            import re
            expected = re.search(r'^version = "([^"]+)"', (ROOT / 'pyproject.toml').read_text(), re.M)[1]
            self.assertEqual(project_version(), expected)
        for entry in ('module', 'console'):
            result = self.cli('--version', entry=entry)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'schemaxis ' + project_version() + '\n')
            self.assertEqual(result.stderr, '')

    def test_top_level_and_nested_command_help(self):
        for entry in ('module', 'console'):
            result = self.cli('--help', entry=entry)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--version', result.stdout)
            self.assertIn('help KEYWORDS', result.stdout)
            for path in ((), ('run',), ('capabilities', 'search'), ('schedule', 'preview')):
                actual = self.cli('help', *path, entry=entry)
                expected = self.cli(*path, '--help', entry=entry)
                self.assertEqual(actual.returncode, 0, actual.stderr)
                self.assertEqual(actual.stdout, expected.stdout)

    def test_discovery_does_not_require_version_metadata(self):
        import contextlib
        import io
        from schemaxis.__main__ import build_parser
        with patch('schemaxis.__main__.project_version', side_effect=ValueError('metadata unavailable')):
            parser = build_parser()
            self.assertEqual(parser.parse_args(['discover']).command, 'discover')
            self.assertIn('--version', parser.format_help())
            with contextlib.redirect_stderr(io.StringIO()) as diagnostic:
                with self.assertRaises(SystemExit) as caught:
                    parser.parse_args(['--version'])
            self.assertEqual(caught.exception.code, 2)
            self.assertIn('metadata unavailable', diagnostic.getvalue())

    def test_search_includes_commands_and_shared_capability_pages(self):
        commands = self.cli('help', 'retained')
        self.assertEqual(commands.returncode, 0, commands.stdout + commands.stderr)
        self.assertIn('verify', [item['command'] for item in json.loads(commands.stdout)['commands']])
        for entry in ('module', 'console'):
            search = self.cli('help', 'extrusion', '--scope', 'app/freecad', '--limit', '1', entry=entry)
            direct = self.cli('capabilities', 'search', 'extrusion', '--scope', 'app/freecad', '--limit', '1', entry=entry)
            self.assertEqual(search.returncode, 0, search.stdout + search.stderr)
            self.assertEqual(json.loads(search.stdout)['capabilities'], json.loads(direct.stdout))
            forced = self.cli('help', 'plan', '--search', entry=entry)
            self.assertIn('plan', [item['command'] for item in json.loads(forced.stdout)['commands']])
            empty = self.cli('help', 'xyzzy-no-such-topic', entry=entry)
            self.assertEqual(empty.returncode, 0)
            self.assertEqual(json.loads(empty.stdout)['capabilities']['page']['total'], 0)

    def test_usage_and_discovery_fault_statuses(self):
        for entry in ('module', 'console'):
            invalid = self.cli('nonexistent-command', entry=entry)
            self.assertEqual(invalid.returncode, 2)
            self.assertIn('usage:', invalid.stderr)
            missing = self.cli('help', '--search', entry=entry)
            self.assertEqual(missing.returncode, 2)
            broken = self.cli('help', 'extrusion', '--scope', 'app/no-such-app', entry=entry)
            self.assertEqual(broken.returncode, 1)
            self.assertIn('fault', json.loads(broken.stdout))

    def test_host_paths_never_import_gui_or_native_modules(self):
        fixture = tempfile.TemporaryDirectory(prefix='schemaxis-host-import-')
        self.addCleanup(fixture.cleanup)
        workspace = Path(fixture.name)
        configuration = workspace/'private.json'
        configuration.write_text('{"version":1,"locations":{}}')
        script = '''
import importlib.abc, json, sys
class RejectNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        roots = {'bpy', 'paraview', 'FreeCAD', 'PySide', 'PySide2', 'PySide6', 'PyQt5', 'PyQt6', 'tkinter', 'gmsh', 'cantera', 'qgis', 'matplotlib'}
        if fullname.split('.')[0] in roots or fullname in {'schemaxis.studio_server', 'schemaxis.console_server'}:
            raise AssertionError('GUI/native import attempted: ' + fullname)
sys.meta_path.insert(0, RejectNative())
from schemaxis.__main__ import console_main
sys.argv = ['schemaxis', *json.loads(sys.argv[1])]
sys.exit(console_main())
'''
        for args in (['--version'], ['--help'], ['discover'], ['help', 'extrusion'],
                     ['plan', str(ROOT / 'examples/schemaxis/gmsh-minimal.json')],
                     ['schedule', '--workspace', str(workspace/'scheduler'), 'list'],
                     ['console', '--provider', 'workflow', '--workspace', str(workspace/'console'), '--command', 'status']):
            result = subprocess.run([sys.executable, '-c', script, json.dumps(args)],
                cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'SCHEMAXIS_CONFIG': str(configuration)},
                capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_storage_cli_review_apply_and_restore(self):
        with tempfile.TemporaryDirectory(prefix='schemaxis-cli-storage-') as directory:
            root = Path(directory)
            run = root/'outputs/run-a'
            run.mkdir(parents=True)
            (run/'authored.json').write_text('{"version":"fixture/1"}')
            (run/'result.txt').write_text('retained fixture\n'*300)
            saved = root/'reviewed-plan.json'
            archive = root/'case.zip'
            args = ['storage', 'plan', '--action', 'compress', '--root', str(root/'outputs'),
                    '--run', 'run-a', '--destination', str(archive), '--save', str(saved)]
            plan = self.cli(*args)
            self.assertEqual(plan.returncode, 0, plan.stdout + plan.stderr)
            self.assertFalse(archive.exists())
            reviewed = json.loads(plan.stdout)
            applied = self.cli('storage', 'apply', str(saved), '--confirm', reviewed['confirmation'])
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            self.assertTrue(json.loads(applied.stdout)['sourcesRetained'])
            saved_restore = root/'restore.json'
            restored = root/'restored'
            restore = self.cli('storage', 'plan', '--action', 'restore', '--archive', str(archive),
                '--destination', str(restored), '--save', str(saved_restore))
            self.assertEqual(restore.returncode, 0, restore.stdout + restore.stderr)
            applied = self.cli('storage', 'apply', str(saved_restore), '--confirm', json.loads(restore.stdout)['confirmation'])
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            self.assertEqual((restored/'data/run-a/result.txt').read_text(), (run/'result.txt').read_text())


if __name__ == '__main__':
    unittest.main()
