"""Managed ownership, offline recovery and cleanup races with an engine double."""
from dataclasses import asdict
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.app_modules import ModuleManager, manifest
from schemaxis.container_executor import EngineResult, IsolationLimits
from schemaxis.core.faults import SchemaxisError
from schemaxis.storage import encoded

IMAGE = 'example.invalid/sympy@sha256:'+'a'*64
IMAGE_ID = 'sha256:'+'b'*64


def module(identity='sympy'):
    return {'version': 'schemaxis.app-module/1', 'id': identity, 'provider': 'sympy',
            'applicationVersion': '1.14.0', 'coreVersion': '0.4.0', 'image': IMAGE,
            'platform': 'linux/amd64', 'routes': ['schemaxis.sympy/1'],
            'qualification': 'explicit-engine-double', 'limits': asdict(IsolationLimits()),
            'inputFiles': {'schemaxis.sympy/1': []}}


class Engine:
    def __init__(self):
        self.present = False
        self.repo_digest = True
        self.containers = []
        self.calls = []
        self.unavailable = False
        self.identity = 'test-engine'

    def command(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == 'info':
            return EngineResult(int(self.unavailable), self.identity.encode(), b'unavailable')
        if args[:2] == ['image', 'inspect']:
            if not self.present or args[2] == IMAGE and not self.repo_digest:
                return EngineResult(1, b'', b'absent')
            return EngineResult(0, encoded([{'Id': IMAGE_ID, 'Size': 12345,
                'Os': 'linux', 'Architecture': 'amd64', 'RepoTags': [],
                'RepoDigests': [IMAGE] if self.repo_digest else []}]), b'')
        if args[:2] == ['image', 'pull']:
            self.present = True
            self.repo_digest = True
        elif args[:2] == ['image', 'save']:
            Path(args[args.index('--output')+1]).write_bytes(b'test-image-archive')
        elif args[:2] == ['image', 'load']:
            self.present = True
            self.repo_digest = False
        elif args[:2] == ['image', 'rm']:
            self.present = False
        elif args[:2] == ['container', 'ls']:
            return EngineResult(0, '\n'.join(self.containers).encode(), b'')
        else:
            raise AssertionError(args)
        return EngineResult(0, b'', b'')


class ModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = Engine()
        self.manager = ModuleManager(self.root/'modules', engine=self.engine)
        self.manager.register(module())

    def fault(self, code, action):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)

    def test_fetch_inventory_clear_preserves_settings_downloads_and_user_files(self):
        user = self.root/'project.txt'
        user.write_text('user work')
        self.manager.configure(backend='native', allow_downloads=False)
        self.manager.fetch(['sympy'], keep_download=True)
        row = self.manager.inventory()['modules'][0]
        self.assertTrue(row['owned'])
        self.assertGreater(row['downloadBytes'], 0)
        plan = self.manager.cleanup_plan(['sympy'])
        self.manager.clear(plan, plan['confirmation'])
        self.assertFalse(self.engine.present)
        self.assertTrue((self.manager.root/'downloads/sympy.tar').is_file())
        self.assertEqual(self.manager.settings(), {'backend': 'native', 'allowDownloads': False})
        self.assertEqual(user.read_text(), 'user work')
        self.assertTrue((self.manager.root/'catalogue/sympy.json').is_file())

    def test_offline_restore_keeps_original_content_identity_without_registry_metadata(self):
        self.manager.fetch(['sympy'], keep_download=True)
        plan = self.manager.cleanup_plan(['sympy'])
        self.manager.clear(plan, plan['confirmation'])
        self.manager.fetch(['sympy'], allow_download=False)
        row = self.manager.inventory()['modules'][0]
        self.assertTrue(row['installed'])
        self.assertTrue(row['owned'])
        self.assertEqual(row['imageId'], IMAGE_ID)
        self.assertEqual(sum(call[:2] == ['image', 'pull'] for call in self.engine.calls), 1)

    def test_external_image_is_usable_but_never_claimed_or_deleted(self):
        self.engine.present = True
        self.manager.fetch(['sympy'], keep_download=True)
        plan = self.manager.cleanup_plan(['sympy'], downloads=True)
        self.assertFalse(plan['modules'][0]['removeImage'])
        self.manager.clear(plan, plan['confirmation'])
        self.assertTrue(self.engine.present)
        self.assertFalse((self.manager.root/'downloads/sympy.tar').exists())
        self.assertFalse(any(call[:2] == ['image', 'rm'] for call in self.engine.calls))

    def test_stale_cleanup_plan_and_live_container_refuse_before_removal(self):
        self.manager.fetch(['sympy'])
        plan = self.manager.cleanup_plan(['sympy'])
        self.engine.containers = ['active-container']
        self.fault('STALE_MODULE_PLAN', lambda: self.manager.clear(plan, plan['confirmation']))
        plan = self.manager.cleanup_plan(['sympy'])
        self.fault('MODULES_BUSY', lambda: self.manager.clear(plan, plan['confirmation']))
        self.assertTrue(self.engine.present)

    def test_shared_execution_lease_blocks_cleanup_and_registration(self):
        self.manager.fetch(['sympy'])
        plan = self.manager.cleanup_plan(['sympy'])
        with self.manager.lock():
            self.fault('MODULES_BUSY', lambda: self.manager.clear(plan, plan['confirmation']))
            self.fault('MODULES_BUSY', lambda: self.manager.register(module()))

    def test_tampered_archives_symlinks_and_changed_manifests_are_not_removed(self):
        self.manager.fetch(['sympy'], keep_download=True)
        download = self.manager.root/'downloads/sympy.tar'
        download.write_bytes(b'changed')
        self.fault('MODULE_DOWNLOAD_CHANGED', lambda: self.manager.cleanup_plan(['sympy'], downloads=True))
        download.unlink()
        target = self.root/'user-file'
        target.write_text('retain')
        download.symlink_to(target)
        self.fault('MODULE_PATH_UNSAFE', lambda: self.manager.cleanup_plan(['sympy'], downloads=True))
        self.assertEqual(target.read_text(), 'retain')
        changed = module()
        changed['applicationVersion'] = 'next'
        self.fault('MODULE_CONFLICT', lambda: self.manager.register(changed))

    def test_unknown_unpinned_conflicting_modules_and_daemon_errors_refuse(self):
        self.fault('UNKNOWN_MODULE', lambda: self.manager.fetch(['missing']))
        self.fault('MODULE_CONFLICT', lambda: self.manager.register(module('other')))
        value = module()
        value['image'] = 'example.invalid/worker:latest'
        self.fault('INVALID_MODULE', lambda: manifest(value))
        self.engine.unavailable = True
        self.fault('MODULE_ENGINE_FAILED', lambda: self.manager.inventory())

    def test_offline_mode_never_pulls(self):
        self.fault('MODULE_NOT_CACHED', lambda: self.manager.fetch(['sympy'], allow_download=False))
        self.assertFalse(any(call[:2] == ['image', 'pull'] for call in self.engine.calls))

    def test_other_engine_cannot_inherit_image_ownership(self):
        self.manager.fetch(['sympy'])
        plan = self.manager.cleanup_plan(['sympy'])
        self.engine.identity = 'different-engine'
        self.fault('STALE_MODULE_PLAN', lambda: self.manager.clear(plan, plan['confirmation']))
        fresh = self.manager.cleanup_plan(['sympy'])
        self.assertFalse(fresh['modules'][0]['removeImage'])

    def test_shared_image_is_preserved_until_all_installed_modules_are_selected(self):
        other = module('numpy')
        other.update(provider='numpy', routes=['schemaxis.numpy/1'], inputFiles={'schemaxis.numpy/1': []})
        self.manager.register(other)
        self.manager.fetch(['sympy', 'numpy'])
        plan = self.manager.cleanup_plan(['sympy'])
        self.assertFalse(plan['modules'][0]['removeImage'])
        self.assertEqual(plan['modules'][0]['sharedWith'], ['numpy'])
        plan = self.manager.cleanup_plan(['sympy', 'numpy'])
        self.manager.clear(plan, plan['confirmation'])
        self.assertEqual(sum(call[:2] == ['image', 'rm'] for call in self.engine.calls), 1)

    def test_studio_mutations_require_admin_and_refuse_busy_jobs(self):
        import threading
        from types import SimpleNamespace
        from schemaxis.studio_setup import StudioSetup
        setup = StudioSetup.__new__(StudioSetup)
        setup.app = SimpleNamespace(busy=False, job_lock=threading.Lock())
        with patch('schemaxis.app_modules.ModuleManager', return_value=self.manager):
            self.assertEqual(len(setup.request({'action': 'modules'})['modules']), 1)
            self.fault('SETTING_SCOPE', lambda: setup.request({'action': 'moduleSettings', 'role': 'user',
                'backend': 'native', 'allowDownloads': False}))
            setup.app.busy = True
            self.fault('SESSION_BUSY', lambda: setup.request({'action': 'fetchModule', 'role': 'admin', 'module': 'sympy'}))

    def test_native_runtime_does_not_probe_container_engine_or_claim_system_apps(self):
        from schemaxis.module_runtime import runtime, current
        with runtime({'version': 'not-needed'}, backend='native', manager=self.manager):
            self.assertIsNone(current())
        self.assertEqual(self.engine.calls, [])

    def test_cli_cache_review_and_settings_work_in_private_module_home(self):
        from schemaxis.__main__ import main
        with patch.dict('os.environ', {'SCHEMAXIS_MODULE_HOME': str(self.manager.root)}):
            with patch('sys.argv', ['schemaxis', 'modules', 'settings', '--backend', 'native', '--offline']):
                self.assertEqual(main(), {'backend': 'native', 'allowDownloads': False})

    def test_cli_native_override_is_explicit_and_conflicting_container_selection_refuses(self):
        from types import SimpleNamespace
        from schemaxis.module_cli import execution_backend
        self.assertIsNone(execution_backend(SimpleNamespace(backend=None, executable=None), {}))
        self.assertEqual(execution_backend(SimpleNamespace(backend=None, executable='/native/app'), {}), 'native')
        self.fault('INVALID_CONFIGURATION', lambda: execution_backend(
            SimpleNamespace(backend='container', executable='/native/app'), {}))


if __name__ == '__main__':
    unittest.main()
