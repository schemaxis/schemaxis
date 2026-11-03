# Copyright (C) 2026 David L F Gaden
"""Disposable preservation, schema dependencies and untrusted archive safety."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from schemaxis import storage_management as management
from schemaxis.core.faults import SchemaxisError
from schemaxis.schema_snapshots import read, store_shared
from schemaxis.storage import encoded, load


class StorageManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='schemaxis-storage-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.outputs = self.root/'outputs'
        self.case = self.outputs/'run-a'
        self.case.mkdir(parents=True)
        (self.case/'authored.json').write_text('{"version":"schemaxis.fixture/1"}')
        (self.case/'result.txt').write_text('independent retained result\n'*500)
        (self.case/'result.txt').chmod(0o750)
        (self.case/'empty').mkdir()
        schema = b'{"properties":{"version":{"const":"schemaxis.fixture/1"}}}'
        self.snapshot = self.case/'evidence/input.snapshot.json'
        store_shared(self.outputs, self.snapshot, schema, provider='fixture',
                     document_version='schemaxis.fixture/1')

    def assertFault(self, code, callback):
        with self.assertRaises(SchemaxisError) as caught:
            callback()
        self.assertEqual(caught.exception.fault.code, code, caught.exception)

    def make(self, action='compress', destination=None):
        plan = management.plan(self.outputs, ['run-a'], action=action,
                               destination=destination or self.root/('preserved-'+action))
        return plan, management.apply_plan(plan, plan['confirmation'])

    def test_backup_compress_and_restore_preserve_contents_modes_and_schemas(self):
        for action in ('backup', 'archive', 'compress'):
            with self.subTest(action=action):
                plan, receipt = self.make(action)
                self.assertEqual(receipt['status'], 'verified')
                self.assertTrue(receipt['sourcesRetained'])
                self.assertEqual(receipt['sourceDeletionBytes'], 0)
                destination = self.root/('restored-'+action)
                restore = management.plan(action='restore', archive=receipt['destination'], destination=destination)
                management.apply_plan(restore, restore['confirmation'])
                case = destination/'data/run-a'
                self.assertEqual((case/'result.txt').read_bytes(), (self.case/'result.txt').read_bytes())
                self.assertEqual(stat.S_IMODE((case/'result.txt').stat().st_mode), 0o750)
                self.assertTrue((case/'empty').is_dir())
                self.assertEqual(read(case/'evidence/input.snapshot.json'), read(self.snapshot))
                if action == 'compress':
                    self.assertLess(receipt['storedBytes'], receipt['contentBytes'])
                self.assertTrue(self.case.is_dir())

    def test_restored_schemas_survive_original_run_and_store_loss(self):
        _, receipt = self.make()
        import shutil
        shutil.rmtree(self.outputs)
        restored = self.root/'detached'
        plan = management.plan(action='restore', archive=receipt['destination'], destination=restored)
        management.apply_plan(plan, plan['confirmation'])
        self.assertIn(b'schemaxis.fixture/1', read(restored/'data/run-a/evidence/input.snapshot.json'))

    def test_explicit_plan_confirmation_and_source_staleness(self):
        destination = self.root/'new.zip'
        plan = management.plan(self.outputs, ['run-a'], action='compress', destination=destination)
        self.assertFalse(destination.exists())
        self.assertFault('STORAGE_CONFIRMATION_REQUIRED', lambda: management.apply_plan(plan, 'no'))
        (self.case/'result.txt').write_text('changed after review')
        self.assertFault('STALE_STORAGE_PLAN', lambda: management.apply_plan(plan, plan['confirmation']))
        self.assertFalse(destination.exists())

    def test_duplicate_overlap_escape_shared_store_and_destination_collision(self):
        (self.case/'nested').mkdir()
        (self.case/'nested/authored.json').write_text('{}')
        for runs in (['run-a','run-a'], ['run-a','run-a/nested'], ['../'], ['schemas']):
            self.assertFault('INVALID_STORAGE_SELECTION', lambda runs=runs:
                management.plan(self.outputs, runs, destination=self.root/'new'))
        self.assertFault('INVALID_STORAGE_SELECTION', lambda:
            management.plan(self.outputs, ['run-a'], destination=self.case/'copy'))
        existing = self.root/'occupied'
        existing.mkdir()
        self.assertFault('OUTPUT_EXISTS', lambda: management.plan(self.outputs, ['run-a'], destination=existing))

    def test_links_and_active_workspace_are_refused(self):
        link = self.case/'outside'
        link.symlink_to(self.root/'elsewhere')
        self.assertFault('UNSAFE_STORAGE_PATH', lambda:
            management.plan(self.outputs, ['run-a'], destination=self.root/'new'))
        link.unlink()
        import fcntl
        for name in ('agent.lock', '.coordinator.lock'):
            with (self.outputs/name).open('w') as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertFault('STORAGE_ACTIVE_OR_UNKNOWN', lambda:
                    management.plan(self.outputs, ['run-a'], destination=self.root/'new'))
        fifo = self.root/'not-an-archive'
        os.mkfifo(fifo)
        self.assertFault('INVALID_STORAGE_ARCHIVE', lambda:
            management.plan(action='restore', archive=fifo, destination=self.root/'restored'))

    def tamper(self, mutate):
        _, receipt = self.make(destination=self.root/'original.zip')
        altered = self.root/'altered.zip'
        with zipfile.ZipFile(receipt['destination']) as source:
            members = {n: source.read(n) for n in source.namelist()}
        mutate(members)
        with zipfile.ZipFile(altered, 'w') as output:
            for name, data in members.items():
                output.writestr(name, data)
        return altered

    def test_archive_checksum_membership_path_traversal_and_limits(self):
        tamperers = (
            lambda members: members.update({'data/run-a/result.txt': b'altered'}),
            lambda members: members.update({'unlisted': b'extra'}),
            lambda members: members.pop('data/run-a/authored.json'),
            lambda members: members.update({'../../escape': b'bad'}),
        )
        for i, mutate in enumerate(tamperers):
            with self.subTest(i=i):
                archive = self.tamper(mutate)
                self.assertFault('INVALID_STORAGE_ARCHIVE', lambda: management.verify_archive(archive))
                (self.root/'original.zip').unlink()
                archive.unlink()
        _, receipt = self.make()
        self.assertFault('INVALID_STORAGE_ARCHIVE', lambda:
            management.plan(action='restore', archive=receipt['destination'], destination=self.root/'large', max_bytes=1))

    def test_duplicate_archive_members_and_manifest_traversal(self):
        _, receipt = self.make()
        with zipfile.ZipFile(receipt['destination'], 'a') as archive:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                archive.writestr(management.MANIFEST, b'{}')
        self.assertFault('INVALID_STORAGE_ARCHIVE', lambda: management.verify_archive(receipt['destination']))
        for name in ('../escape', '/absolute', 'data/../escape', 'data//alias', 'data/evil\\escape', 'C:/evil', ''):
            self.assertFault('INVALID_STORAGE_ARCHIVE', lambda name=name: management._member(name))

    def test_self_consistent_traversal_manifest_and_symlink_members_are_refused(self):
        _, receipt = self.make()
        with zipfile.ZipFile(receipt['destination']) as source:
            members = {n: source.read(n) for n in source.namelist()}
        manifest = load(members[management.MANIFEST].decode())
        old_name = 'data/run-a/result.txt'
        manifest['files']['data/../../escape'] = manifest['files'].pop(old_name)
        members['data/../../escape'] = members.pop(old_name)
        members[management.MANIFEST] = encoded(manifest)
        evil = self.root/'traversal.zip'
        with zipfile.ZipFile(evil, 'w') as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        self.assertFault('INVALID_STORAGE_ARCHIVE', lambda:
            management.plan(action='restore', archive=evil, destination=self.root/'escaped'))
        self.assertFalse((self.root/'escape').exists())
        linked = self.root/'linked.zip'
        with zipfile.ZipFile(receipt['destination']) as source, zipfile.ZipFile(linked, 'w') as archive:
            for name in source.namelist():
                info = zipfile.ZipInfo(name)
                if name == old_name:
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, source.read(name))
        self.assertFault('INVALID_STORAGE_ARCHIVE', lambda: management.verify_archive(linked))

    def test_directory_backup_tamper_and_unfinished_publication_are_refused(self):
        _, receipt = self.make('backup')
        backup = Path(receipt['destination'])
        (backup/'.storage-incomplete').write_text('interrupted')
        self.assertFault('STORAGE_INCOMPLETE', lambda:
            management.plan(action='restore', archive=backup, destination=self.root/'restore'))
        (backup/'.storage-incomplete').unlink()
        (backup/'data/run-a/result.txt').write_text('changed')
        self.assertFault('INVALID_STORAGE_ARCHIVE', lambda:
            management.plan(action='restore', archive=backup, destination=self.root/'restore'))

    def test_inspect_unknown_installation_usage_and_declared_sizes(self):
        config = self.root/'private.json'
        config.write_text(json.dumps({'version':1,'locations':{'blender':str(self.case/'result.txt')}}))
        from unittest.mock import patch
        with patch.dict(os.environ, {'SCHEMAXIS_CONFIG':str(config)}):
            report = management.inspect(self.outputs)
        self.assertEqual(len(report['runs']), 1)
        record = report['installations'][0]
        self.assertEqual(record['measuredPathBytes'], (self.case/'result.txt').stat().st_size)
        self.assertIsNone(record['installationBytes'])
        self.assertIsNone(record['lastUsedAt'])
        self.assertIsNone(record['recordedUseCount'])
        self.assertFalse(record['managedRemovalSupported'])
        self.assertTrue(report['schemas']['references'])

    def test_policy_is_opt_in_plan_only_and_age_gated(self):
        policy = self.root/'policy.json'
        management.create_policy(policy, name='monthly', root=self.outputs, runs=['run-a'],
            destination=self.root/'archives', every_days=30, first_due='2020-01-01T00:00:00Z', older_than_days=7)
        before = management.due_policy(policy, now='2019-12-31T00:00:00Z')
        self.assertIsNone(before['plan'])
        due = management.due_policy(policy, now='2030-01-01T00:00:00Z')
        self.assertEqual(due['mode'], 'plan-only')
        self.assertFalse(due['workerInstalled'])
        self.assertIsNotNone(due['plan'])
        self.assertFalse((self.root/'archives').exists())
        now = management.datetime.now(management.timezone.utc).isoformat()
        young = management.due_policy(policy, now=now)
        self.assertIsNone(young['plan'])
        self.assertEqual(len(young['skipped']), 1)

    def test_extraction_enforces_actual_bytes_and_manifest_bounds(self):
        import io
        from unittest.mock import patch
        output = io.BytesIO()
        self.assertFault('INVALID_STORAGE_ARCHIVE', lambda:
            management._copy_bounded(io.BytesIO(b'x'*4096), output, 16, 16))
        self.assertLessEqual(len(output.getvalue()), 16)
        self.assertFault('INVALID_STORAGE_ARCHIVE', lambda:
            management._copy_bounded(io.BytesIO(b'x'*16), io.BytesIO(), 16, 8))
        _, backup = self.make('backup')
        _, archive = self.make('archive')
        with patch.object(management, 'MAX_MANIFEST', 64):
            self.assertFault('INVALID_STORAGE_ARCHIVE', lambda:
                management.plan(action='restore', archive=backup['destination'], destination=self.root/'new'))
            self.assertFault('INVALID_STORAGE_ARCHIVE', lambda: management.verify_archive(archive['destination']))

    def test_replaced_archive_path_uses_verified_descriptor_and_refuses_publication(self):
        from unittest.mock import patch
        _, receipt = self.make()
        archive = Path(receipt['destination'])
        destination = self.root/'restored'
        reviewed = management.plan(action='restore', archive=archive, destination=destination)
        verify = management.verify_archive
        descriptor_checked = []
        def replace_after_verification(source, **options):
            verified = verify(source, **options)
            if hasattr(source, 'fileno'):
                descriptor_checked.append(source.fileno())
                replacement = self.root/'replacement'
                replacement.write_bytes(b'changed path after descriptor verification')
                os.replace(replacement, archive)
            return verified
        with patch.object(management, 'verify_archive', side_effect=replace_after_verification):
            self.assertFault('STALE_STORAGE_PLAN', lambda:
                management.apply_plan(reviewed, reviewed['confirmation']))
        self.assertTrue(descriptor_checked)
        self.assertFalse(destination.exists())

    def test_malformed_plans_and_policies_fail_with_structured_faults(self):
        for saved in ({'version':management.PROTOCOL},
                      {'version':management.PROTOCOL,'action':'restore','destination':'new',
                       'sourceDeletionBytes':0,'archive':[], 'maxBytes':8}):
            self.assertFault('INVALID_STORAGE_PLAN', lambda saved=saved: management.apply_plan(saved, 'unused'))
        policy = self.root/'invalid-policy.json'
        for value in ({}, {'version':'schemaxis.storage-policy/1','mode':'plan-only'}, []):
            policy.write_bytes(encoded(value))
            self.assertFault('INVALID_STORAGE_POLICY', lambda: management.due_policy(policy))
