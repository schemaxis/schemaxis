"""Host contract checks only; no Docker, native decoders or image qualification."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.core.faults import SchemaxisError
from schemaxis.execution_inputs import (CapturedInput, InputBindings, CapturePolicy,
    validate_bindings, bind_document, check_bound_document, bindings_record, bindings_from_record)


class CapturedInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)/'captures'
        self.root.mkdir(mode=0o700)
        self.data = b'time,ch1,ch2\n0,1,2\n1,2,4\n'
        self.path = self.root/'source.csv'
        self.path.write_bytes(self.data); self.path.chmod(0o444)
        details = self.path.stat()
        self.capture = CapturedInput('input-one', self.path,
            'sha256:'+hashlib.sha256(self.data).hexdigest(), len(self.data), details.st_dev, details.st_ino)
        self.inputs = InputBindings('task-one', (self.capture,), (('/source', 'input-one'),))
        self.policy = CapturePolicy(self.root, 'task-one', 1024, 2)

    def tearDown(self): self.temporary.cleanup()

    def refused(self, function, code='INVALID_INPUT_BINDINGS'):
        with self.assertRaises(SchemaxisError) as caught: function()
        self.assertEqual(caught.exception.fault.code, code)

    def test_pure_binding_is_nonmutating_and_never_reads_capture(self):
        document = {'version': 'test/1', 'source': 'input-one'}
        with patch.object(Path, 'open', side_effect=AssertionError('file read')), \
             patch.object(Path, 'stat', side_effect=AssertionError('stat')), \
             patch('os.open', side_effect=AssertionError('filesystem open')):
            bound = bind_document(document, self.inputs)
            self.assertEqual(bound['source'], str(self.path))
            self.assertEqual(document['source'], 'input-one')
            self.assertIs(check_bound_document(bound, self.inputs), self.inputs)
            self.refused(lambda: bind_document(bound, self.inputs))
            self.refused(lambda: check_bound_document(document, self.inputs), 'INPUT_CAPTURE_CHANGED')

    def test_closure_requires_unique_metadata_and_all_captures_used(self):
        invalid = [replace(self.inputs, namespace=''), replace(self.inputs, captures=()),
            replace(self.inputs, slots=()), replace(self.inputs, captures=[self.capture]),
            replace(self.inputs, captures=(self.capture, self.capture)),
            replace(self.inputs, slots=(('/source','other'),)),
            replace(self.inputs, slots=(('/source','input-one'),('/source','input-one'))),
            replace(self.inputs, slots=(('/source','input-one'),('/source/child','input-one'))),
            replace(self.inputs, slots=(('', 'input-one'),)),
            replace(self.inputs, slots=(('/bad~2escape', 'input-one'),))]
        for item in invalid:
            with self.subTest(item=item): self.refused(lambda: validate_bindings(item))
        other = replace(self.capture, identity='input-two', path=self.root/'other.csv', inode=self.capture.inode+1)
        self.refused(lambda: validate_bindings(replace(self.inputs, captures=(self.capture, other))))
        for fields in ({'bytes': True}, {'inode': 0}, {'device': True}, {'sha256': '0'*64},
                       {'path': Path('relative.csv')}, {'path': self.root/'..'/'elsewhere.csv'}):
            self.refused(lambda: validate_bindings(replace(self.inputs, captures=(replace(self.capture, **fields),))))

    def test_persistence_codec_is_exact_bounded_and_pure(self):
        record = bindings_record(self.inputs)
        with patch('os.open', side_effect=AssertionError('filesystem open')):
            self.assertEqual(bindings_from_record(record), self.inputs)
        for changes in ({'version': True}, {'version': 2}, {'extra': 1}, {'captures': []},
                        {'slots': record['slots']*257}, {'namespace': 'invalid/name'}):
            self.refused(lambda: bindings_from_record({**record, **changes}))
        item = record['captures'][0]
        for changes in ({'path': str(self.root)+'//source.csv'}, {'path': '\0'},
                        {'path': 12}, {'extra': 1}, {'bytes': True}):
            self.refused(lambda: bindings_from_record({**record, 'captures': [{**item, **changes}]}))
        self.assertEqual(bindings_record(bindings_from_record(record)), record)

    def test_pointer_escapes_arrays_and_same_capture_reuse(self):
        document = {'items': [{'a/b~c':'input-one'}, {'source':'input-one'}]}
        inputs = replace(self.inputs, slots=(('/items/0/a~1b~0c','input-one'),('/items/1/source','input-one')))
        bound = bind_document(document, inputs)
        self.assertEqual(bound['items'][0]['a/b~c'], str(self.path))
        self.assertEqual(bound['items'][1]['source'], str(self.path))
        for pointer in ('/items/00/source', '/items/-/source', '/items/2/source'):
            self.refused(lambda: bind_document(document, replace(self.inputs, slots=((pointer,'input-one'),))))

    def test_lease_validates_readonly_identity_and_blocks_mutation(self):
        with self.policy.lease(self.inputs) as reader:
            self.assertEqual(reader.captures, (self.capture,))
            with self.policy.lease(self.inputs): pass
            self.refused(lambda: self.policy.lease(exclusive=True), 'INPUTS_BUSY')
            self.assertEqual(reader.recheck(), (self.capture,))
        with self.policy.lease(exclusive=True):
            self.refused(lambda: self.policy.lease(self.inputs), 'INPUTS_BUSY')
        with self.policy.lease(self.inputs): pass

    def test_namespace_count_bytes_and_outside_root_refuse_before_open(self):
        policies = [replace(self.policy, namespace='task-two'), replace(self.policy, max_bytes=1)]
        for policy in policies:
            with patch('os.open', side_effect=AssertionError('must reject before filesystem')):
                self.refused(lambda: policy.lease(self.inputs), 'INPUT_SCOPE_EXCEEDED')
        outside = replace(self.capture, path=self.root.parent/'elsewhere.csv')
        self.refused(lambda: self.policy.lease(replace(self.inputs, captures=(outside,))), 'INPUT_SCOPE_EXCEEDED')
        with self.assertRaises(ValueError): self.policy.lease()

    def test_symlinks_hardlinks_permissions_and_fifo_are_refused(self):
        self.path.chmod(0o644)
        self.refused(lambda: self.policy.lease(self.inputs), 'INPUT_CAPTURE_CHANGED')
        self.path.chmod(0o444)
        link = self.root/'hardlink.csv'; os.link(self.path, link)
        self.refused(lambda: self.policy.lease(self.inputs), 'INPUT_CAPTURE_CHANGED')
        link.unlink()
        self.path.unlink(); self.path.symlink_to(self.root.parent/'outside')
        self.refused(lambda: self.policy.lease(self.inputs), 'INPUT_CAPTURE_CHANGED')
        self.path.unlink(); os.mkfifo(self.path, mode=0o444)
        # O_NONBLOCK ensures corrupted capture metadata cannot hang on a FIFO.
        self.refused(lambda: self.policy.lease(self.inputs), 'INPUT_CAPTURE_CHANGED')

    def test_replacement_same_bytes_and_content_mutation_are_detected(self):
        with self.policy.lease(self.inputs) as lease:
            replacement = self.root/'replacement.csv'
            replacement.write_bytes(self.data); replacement.chmod(0o444)
            replacement.replace(self.path)
            self.refused(lease.recheck, 'INPUT_CAPTURE_CHANGED')
        self.refused(lambda: self.policy.lease(self.inputs), 'INPUT_CAPTURE_CHANGED')
        details = self.path.stat()
        current = replace(self.inputs, captures=(replace(self.capture, inode=details.st_ino),))
        with self.policy.lease(current) as lease:
            self.path.chmod(0o644); self.path.write_bytes(b'x'*len(self.data)); self.path.chmod(0o444)
            self.refused(lease.recheck, 'INPUT_CAPTURE_CHANGED')

    def test_root_and_lock_replacement_cannot_preserve_a_lease(self):
        with self.policy.lease(self.inputs) as lease:
            (self.root/'.capture.lock').unlink()
            (self.root/'.capture.lock').touch(mode=0o600)
            self.refused(lease.recheck, 'INPUT_CAPTURE_CHANGED')
        self.root.chmod(0o755)
        self.refused(lambda: self.policy.lease(self.inputs), 'INPUT_CAPTURE_CHANGED')
        self.root.chmod(0o700)
        renamed = self.root.with_name('moved')
        self.root.rename(renamed); self.root.symlink_to(renamed, target_is_directory=True)
        self.refused(lambda: self.policy.lease(self.inputs), 'INPUT_CAPTURE_CHANGED')


if __name__ == '__main__': unittest.main()
