import copy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from schemaxis import storage, workflow_resources as resources
from schemaxis.core.faults import SchemaxisError


class WorkflowResourcesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'inputs'
        self.source.mkdir()
        (self.source / 'model.step').write_bytes(b'geometry\x00\x01')
        self.destination = self.root / 'capture'

    def fault(self, code, function, *args, **kwargs):
        with self.assertRaises(SchemaxisError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.fault.code, code)
        self.assertTrue(caught.exception.fault.location)
        return caught.exception.fault

    def capture_file(self):
        return resources.capture(self.source / 'model.step', self.destination)

    def write_manifest(self, value):
        value = copy.deepcopy(value)
        value.pop('digest', None)
        value['digest'] = storage.digest(value)
        (self.destination / 'resource.json').write_bytes(storage.encoded(value))

    def test_file_capture_is_portable_and_preserves_source(self):
        source = self.source / 'model.step'
        before = source.stat()
        manifest = self.capture_file()
        self.assertEqual(manifest, resources.verify(self.destination))
        self.assertEqual(manifest['files'], [{'path': 'model.step', 'size': 10,
            'sha256': hashlib.sha256(b'geometry\x00\x01').hexdigest()}])
        self.assertNotIn(str(self.source), storage.encoded(manifest).decode())
        self.assertEqual(source.stat().st_mode, before.st_mode)
        self.assertEqual(source.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(source.read_bytes(), b'geometry\x00\x01')
        source.unlink()
        self.assertEqual(resources.verify(self.destination), manifest)

    def test_directory_captures_nested_files_and_empty_directories(self):
        (self.source / 'empty').mkdir()
        (self.source / 'time' / '0').mkdir(parents=True)
        (self.source / 'time' / '0' / 'velocity').write_bytes(b'1 2 3')
        manifest = resources.capture(self.source, self.destination, kind='directory')
        self.assertEqual(manifest['directories'], ['empty', 'time', 'time/0'])
        self.assertEqual([entry['path'] for entry in manifest['files']],
                         ['model.step', 'time/0/velocity'])
        self.assertEqual(resources.verify(self.destination), manifest)

    def test_empty_directory_capture(self):
        (self.source / 'model.step').unlink()
        manifest = resources.capture(self.source, self.destination, kind='directory', max_bytes=0)
        self.assertEqual(manifest['totalBytes'], 0)
        self.assertEqual(resources.verify(self.destination), manifest)

    def test_file_set_captures_only_declared_members_and_parents(self):
        (self.source / 'case').mkdir()
        (self.source / 'case' / 'mesh').write_bytes(b'mesh')
        (self.source / 'unselected.txt').write_bytes(b'not captured')
        manifest = resources.capture(self.source, self.destination, kind='file-set',
                                     members=['case/mesh', 'model.step'])
        self.assertEqual(manifest['directories'], ['case'])
        self.assertEqual([record['path'] for record in manifest['files']], ['case/mesh', 'model.step'])
        self.assertEqual(resources.verify(self.destination), manifest)

    def test_manifests_deterministic_across_input_and_output_locations(self):
        first = self.capture_file()
        second = resources.capture(self.source / 'model.step', self.root / 'second')
        self.assertEqual(first, second)
        self.assertEqual((self.destination / 'resource.json').read_bytes(),
                         (self.root / 'second' / 'resource.json').read_bytes())

    def test_existing_empty_destination_not_reused(self):
        self.destination.mkdir()
        self.fault('OUTPUT_EXISTS', self.capture_file)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_existing_evidence_not_overwritten(self):
        manifest = self.capture_file()
        self.fault('OUTPUT_EXISTS', self.capture_file)
        self.assertEqual(resources.verify(self.destination), manifest)

    def test_destination_inside_source_rejected_including_dot_alias(self):
        self.fault('INVALID_RESOURCE', resources.capture, self.source,
                   self.source / 'case' / '..' / 'capture', kind='directory')
        self.assertFalse((self.source / 'capture').exists())

    def test_symlinks_rejected_as_source_member_ancestor_and_destination(self):
        link = self.root / 'link'
        link.symlink_to(self.source, target_is_directory=True)
        self.fault('INVALID_RESOURCE', resources.capture, link / 'model.step', self.destination)
        self.fault('INVALID_RESOURCE', resources.capture, self.source / 'model.step', link / 'out')
        link.unlink()
        (self.source / 'bad').symlink_to(self.source / 'model.step')
        self.fault('INVALID_RESOURCE', resources.capture, self.source, self.destination, kind='directory')
        (self.source / 'bad').unlink()
        self.destination.symlink_to(self.source, target_is_directory=True)
        self.fault('INVALID_RESOURCE', self.capture_file)

    def test_file_set_paths_must_be_explicit_normalised_and_unique(self):
        for members in ([], ['../outside'], ['/absolute'], ['case/../model.step'],
                        ['./model.step'], ['case//mesh'], ['C:outside'],
                        ['case\\mesh'], ['model.step', 'model.step'], [None]):
            with self.subTest(members=members):
                self.fault('INVALID_RESOURCE', resources.capture, self.source,
                           self.destination, kind='file-set', members=members)
        self.assertFalse(self.destination.exists())

    def test_unknown_kind_and_invalid_limits_rejected(self):
        self.fault('UNSUPPORTED_RESOURCE', resources.capture, self.source, self.destination, kind='project')
        for kwargs in ({'max_files': 0}, {'max_files': True}, {'max_bytes': -1}, {'max_bytes': False}):
            self.fault('INVALID_RESOURCE', resources.capture, self.source, self.destination, **kwargs)
        self.fault('INVALID_RESOURCE', resources.capture, self.source / 'model.step',
                   self.destination, members=['model.step'])

    def test_byte_and_file_limits_apply_before_destination_claim(self):
        self.fault('RESOURCE_LIMIT', resources.capture, self.source / 'model.step',
                   self.destination, max_bytes=9)
        (self.source / 'second').write_bytes(b'2')
        self.fault('RESOURCE_LIMIT', resources.capture, self.source, self.destination,
                   kind='directory', max_files=1)
        self.assertFalse(self.destination.exists())

    def test_empty_directory_count_is_bounded(self):
        (self.source / 'one').mkdir()
        (self.source / 'two').mkdir()
        self.fault('RESOURCE_LIMIT', resources.capture, self.source, self.destination,
                   kind='directory', max_files=1)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'requires POSIX FIFO')
    def test_special_files_rejected_without_blocking(self):
        os.mkfifo(self.source / 'pipe')
        self.fault('INVALID_RESOURCE', resources.capture, self.source, self.destination, kind='directory')

    def test_modified_missing_and_unexpected_file_detected(self):
        self.capture_file()
        captured = self.destination / 'data' / 'model.step'
        captured.write_bytes(b'different!')
        self.fault('RESOURCE_MISMATCH', resources.verify, self.destination)
        captured.write_bytes(b'geometry\x00\x01')
        captured.unlink()
        self.fault('RESOURCE_MISMATCH', resources.verify, self.destination)
        captured.write_bytes(b'geometry\x00\x01')
        (self.destination / 'data' / 'extra').write_bytes(b'')
        self.fault('RESOURCE_MISMATCH', resources.verify, self.destination)

    def test_unexpected_directory_and_capture_root_members_detected(self):
        self.capture_file()
        (self.destination / 'data' / 'extra').mkdir()
        self.fault('RESOURCE_MISMATCH', resources.verify, self.destination)
        (self.destination / 'data' / 'extra').rmdir()
        (self.destination / 'unlisted').write_bytes(b'')
        self.fault('RESOURCE_MISMATCH', resources.verify, self.destination)

    def test_verify_rejects_links_and_escaped_manifest_paths(self):
        manifest = self.capture_file()
        captured = self.destination / 'data' / 'model.step'
        captured.unlink()
        captured.symlink_to(self.source / 'model.step')
        self.fault('INVALID_RESOURCE', resources.verify, self.destination)
        captured.unlink()
        captured.write_bytes(b'geometry\x00\x01')
        manifest['files'][0]['path'] = '../model.step'
        self.write_manifest(manifest)
        self.fault('INVALID_RESOURCE', resources.verify, self.destination)

    def test_manifest_tamper_and_incomplete_capture_detected(self):
        manifest = self.capture_file()
        manifest['totalBytes'] = 11
        (self.destination / 'resource.json').write_bytes(storage.encoded(manifest))
        self.fault('RESOURCE_MISMATCH', resources.verify, self.destination)
        (self.destination / 'resource.json').unlink()
        self.fault('RESOURCE_MISMATCH', resources.verify, self.destination)

    def test_manifest_types_fail_with_structured_faults(self):
        manifest = self.capture_file()
        mutations = ({'kind': []}, {'files': {}}, {'directories': {}},
                     {'totalBytes': True}, {'status': 'partial'}, {'version': 'unknown'})
        for change in mutations:
            with self.subTest(change=change):
                self.write_manifest(dict(manifest, **change))
                self.fault('RESOURCE_MISMATCH', resources.verify, self.destination)

    def test_verify_obeys_caller_limits(self):
        self.capture_file()
        self.fault('RESOURCE_LIMIT', resources.verify, self.destination, max_bytes=9)

    def test_source_mutation_during_copy_leaves_partial_evidence_without_manifest(self):
        original_reader = resources._read_file

        def modify_after_read(source, expected, destination=None):
            result = original_reader(source, expected, destination)
            if destination is not None:
                source.write_bytes(b'changed bytes')
            return result

        with mock.patch.object(resources, '_read_file', side_effect=modify_after_read):
            self.fault('RESOURCE_CHANGED', self.capture_file)
        self.assertTrue((self.destination / 'data' / 'model.step').is_file())
        self.assertFalse((self.destination / 'resource.json').exists())
        self.fault('OUTPUT_EXISTS', self.capture_file)

    def test_new_directory_member_during_copy_prevents_publication(self):
        original_reader = resources._read_file

        def add_after_read(source, expected, destination=None):
            result = original_reader(source, expected, destination)
            if destination is not None:
                (self.source / 'late').write_bytes(b'late')
            return result

        with mock.patch.object(resources, '_read_file', side_effect=add_after_read):
            self.fault('RESOURCE_CHANGED', resources.capture, self.source, self.destination, kind='directory')
        self.assertFalse((self.destination / 'resource.json').exists())

    def test_growing_or_shorter_input_rejected_at_read_boundary(self):
        source = self.source / 'model.step'
        signature = resources._regular(source)
        source.write_bytes(b'grown source data')
        self.fault('RESOURCE_CHANGED', resources._read_file, source, signature)

    def test_source_modified_mid_read_prevents_completion(self):
        original_open = resources._open_read
        source = self.source / 'model.step'

        class MutatingReader:
            def __init__(self, stream):
                self.stream = stream
                self.first = True

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def fileno(self):
                return self.stream.fileno()

            def read(self, count):
                result = self.stream.read(count)
                if self.first:
                    self.first = False
                    source.write_bytes(b'new geometry')
                return result

        def open_mutating(path):
            opened = original_open(path)
            return MutatingReader(opened) if path == source else opened

        with mock.patch.object(resources, '_open_read', side_effect=open_mutating):
            self.fault('RESOURCE_CHANGED', self.capture_file)
        self.assertFalse((self.destination / 'resource.json').exists())

    def test_uncertain_manifest_publication_removes_completion_marker(self):
        def uncertain(path, payload, exclusive=False):
            path.write_bytes(payload)
            raise storage.AtomicPublicationError(path, OSError('injected durability failure'))

        with mock.patch.object(storage, 'atomic', side_effect=uncertain):
            self.fault('RESOURCE_IO', self.capture_file)
        self.assertTrue((self.destination / 'data' / 'model.step').exists())
        self.assertFalse((self.destination / 'resource.json').exists())

    def test_directory_durability_precedes_completion_marker(self):
        (self.source / 'case' / '0').mkdir(parents=True)
        (self.source / 'case' / '0' / 'U').write_bytes(b'velocity')
        destination = self.root / 'new-parent' / 'capture'
        events = []
        real_sync = resources._sync_directory
        real_atomic = storage.atomic

        def sync(path):
            events.append(path)
            real_sync(path)

        def publish(path, payload, exclusive=False):
            events.append('publish')
            return real_atomic(path, payload, exclusive=exclusive)

        with mock.patch.object(resources, '_sync_directory', side_effect=sync), \
                mock.patch.object(storage, 'atomic', side_effect=publish):
            resources.capture(self.source, destination, kind='directory')
        self.assertEqual(events, [destination / 'data' / 'case' / '0',
                                  destination / 'data' / 'case', destination / 'data',
                                  destination, destination.parent, self.root, 'publish'])

    def test_directory_sync_failure_prevents_completion_marker(self):
        with mock.patch.object(resources, '_sync_directory', side_effect=OSError('injected fsync failure')):
            self.fault('RESOURCE_IO', self.capture_file)
        self.assertFalse((self.destination / 'resource.json').exists())

    def test_excessive_json_nesting_yields_structured_fault(self):
        self.capture_file()
        (self.destination / 'resource.json').write_text('[' * 20000 + '0' + ']' * 20000)
        self.fault('RESOURCE_MISMATCH', resources.verify, self.destination)

    def test_symlink_before_parent_traversal_is_rejected_before_normalising(self):
        elsewhere = self.root / 'elsewhere'
        (elsewhere / 'child').mkdir(parents=True)
        (elsewhere / 'sample').write_bytes(b'intended target')
        (self.root / 'sample').write_bytes(b'lexically collapsed target')
        (self.root / 'link').symlink_to(elsewhere / 'child', target_is_directory=True)
        supplied = self.root / 'link' / '..' / 'sample'
        self.assertEqual(supplied.read_bytes(), b'intended target')
        self.fault('INVALID_RESOURCE', resources.capture, supplied, self.destination)
        self.fault('INVALID_RESOURCE', resources.capture, self.source / 'model.step',
                   self.root / 'link' / '..' / 'capture')
        self.assertFalse(self.destination.exists())
        self.assertFalse((elsewhere / 'capture').exists())

    def test_missing_component_before_parent_traversal_cannot_select_existing_input(self):
        supplied = self.source / 'nonexistent' / '..' / 'model.step'
        self.assertFalse(supplied.exists())
        self.fault('INVALID_RESOURCE', resources.capture, supplied, self.destination)
        self.fault('INVALID_RESOURCE', resources.capture, self.source / 'model.step',
                   self.root / 'nonexistent' / '..' / 'capture')
        self.assertFalse(self.destination.exists())


if __name__ == '__main__':
    unittest.main()
