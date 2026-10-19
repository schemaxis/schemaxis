"""Private location configuration is validated and honoured at execution boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import venv
from unittest.mock import patch, Mock

from schemaxis import configuration
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors import registry


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'.schemaxis.local.json'
        self.patch = patch('schemaxis.configuration.config_path', return_value=self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write(self, value):
        self.path.write_text(json.dumps(value))

    def test_configure_merges_locations_without_launching_apps(self):
        with patch('subprocess.run', side_effect=AssertionError('configure must not launch native apps')):
            configuration.configure('blender', sys.executable)
            configuration.configure('freecad', sys.executable)
            configuration.configure('paraview', self.tmp.name)
        self.assertEqual(configuration.locations(), {'blender': str(Path(sys.executable).absolute()),
                         'freecad': str(Path(sys.executable).absolute()), 'roots': [self.tmp.name]})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(configuration.executable('paraview'), self.tmp.name)

    def test_none_does_not_mask_configured_locations(self):
        self.write({'version': 1, 'locations': {'blender': '/configured', 'roots': ['/configured-root']}})
        self.assertEqual(configuration.locations({'blender': None})['blender'], '/configured')
        self.assertEqual(configuration.locations({'blender': '/explicit'})['blender'], '/explicit')
        self.assertEqual(configuration.locations({'roots': ['/explicit-root']})['roots'], ['/explicit-root'])
        self.assertEqual(configuration.locations({'paraview': '/generic-root'})['roots'], ['/generic-root'])

    @unittest.skipUnless(os.name == 'posix', 'POSIX virtual-environment executable layout')
    def test_configured_symlink_keeps_virtual_environment_after_session_recovery(self):
        from schemaxis.console_session import AdaptorConsoleSession
        environment = Path(self.tmp.name)/'native-env'
        venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
        executable = environment/'bin/python'
        self.assertTrue(executable.is_symlink())
        configuration.configure('blender', executable)
        workspace = Path(self.tmp.name)/'session'
        for _ in range(2):
            session = AdaptorConsoleSession(workspace, provider='blender')
            try:
                self.assertEqual(session.executable, str(executable))
                observed = subprocess.run(
                    [session.executable, '-I', '-c', 'import sys; print(sys.prefix)'],
                    check=True, text=True, capture_output=True, timeout=10)
                self.assertEqual(Path(observed.stdout.strip()), environment)
            finally:
                session.close()

    def test_invalid_configuration_is_a_structured_fault(self):
        for value in ({}, {'version': 2, 'locations': {}}, {'version': 1, 'locations': []},
                      {'version': 1, 'locations': {'roots': '/not-a-list'}},
                      {'version': 1, 'locations': {'blender': ['not-a-string']}}):
            with self.subTest(value=value):
                self.write(value)
                with self.assertRaises(SchemaxisError) as caught: configuration.load()
                self.assertEqual(caught.exception.fault.code, 'INVALID_CONFIGURATION')

    def test_missing_explicit_config_fails_and_absent_default_is_optional(self):
        with patch.dict(os.environ, {}, clear=True): self.assertEqual(configuration.load()['locations'], {})
        with patch.dict(os.environ, {'SCHEMAXIS_CONFIG': str(self.path)}):
            with self.assertRaises(SchemaxisError): configuration.load()

    def test_missing_application_does_not_write_configuration(self):
        with self.assertRaises(SchemaxisError): configuration.configure('blender', self.path/'missing')
        self.assertFalse(self.path.exists())

    def test_registry_run_applies_defaults_and_explicit_override(self):
        self.write({'version': 1, 'locations': {'freecad': '/cad', 'freecad_gui': '/gui', 'roots': ['/pv']}})
        runner = Mock()
        with patch.object(registry, 'import_module', return_value=runner), \
                patch.object(registry, '_verify_native'), \
                patch('schemaxis.schema_snapshots.capture_run'), \
                patch('schemaxis.publication_metadata.finalise'), \
                patch('schemaxis.publication_metadata.verify'):
            registry.run({'version': 'schemaxis.freecad.assembly/1'}, 'out')
            self.assertEqual(runner.run.call_args.kwargs['executable'], '/cad')
            self.assertEqual(runner.run.call_args.kwargs['gui_executable'], '/gui')
            registry.run({'version': 'schemaxis/1'}, 'out', roots=None)
            self.assertEqual(runner.run.call_args.kwargs['roots'], ['/pv'])
            registry.run({'version': 'schemaxis/1'}, 'out', roots=['/explicit'])
            self.assertEqual(runner.run.call_args.kwargs['roots'], ['/explicit'])

    def test_new_console_uses_private_configuration_saved_session_wins(self):
        from schemaxis.console_session import AdaptorConsoleSession
        self.write({'version': 1, 'locations': {'blender': sys.executable}})
        workspace = Path(self.tmp.name)/'console'
        with AdaptorConsoleSession(workspace, provider='blender') as session:
            self.assertEqual(session.executable, str(Path(sys.executable).absolute()))
        self.write({'version': 1, 'locations': {'blender': '/not-installed'}})
        with AdaptorConsoleSession(workspace, provider='blender') as session:
            self.assertEqual(session.executable, str(Path(sys.executable).absolute()))
