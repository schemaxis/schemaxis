"""Malformed retained schema/input depth is a located fault through public verification."""
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis.adaptors import registry
from schemaxis.core.faults import SchemaxisError
from schemaxis.schema_snapshots import capture_run, read, store_shared, verify_run


class SchemaEvidenceDepthTests(unittest.TestCase):
    def test_deep_authored_input_is_structured_before_adaptor_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / 'run'
            version = 'schemaxis.pandoc/1'
            store_shared(root, run / 'schema.snapshot.json',
                         json.dumps({'properties': {'version': {'const': version}}}).encode(),
                         provider='pandoc', document_version=version)
            (run / 'authored.json').write_text('[' * 2000 + '0' + ']' * 2000)
            for action in (lambda: verify_run(run), lambda: registry.verify(run, {'version': version})):
                with self.subTest(action=action), self.assertRaises(SchemaxisError) as error:
                    action()
                self.assertEqual(error.exception.fault.code, 'INVALID_SCHEMA_SNAPSHOT')
                self.assertTrue(error.exception.fault.location)

    def test_deep_schema_and_manifest_are_structured(self):
        version = 'schemaxis.pandoc/1'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = ('[' * 2000 + '0' + ']' * 2000).encode()
            with self.assertRaises(SchemaxisError) as error:
                store_shared(root, root / 'bad/schema.snapshot.json', payload,
                             provider='pandoc', document_version=version)
            self.assertEqual(error.exception.fault.code, 'INVALID_SCHEMA_SNAPSHOT')
            path = root / 'manifest.json'
            path.write_bytes(payload)
            with self.assertRaises(SchemaxisError) as error:
                read(path)
            self.assertEqual(error.exception.fault.code, 'INVALID_SCHEMA_SNAPSHOT')

    def test_deep_schema_that_parses_still_refuses_with_a_located_fault(self):
        version = 'schemaxis.pandoc/1'
        # Python 3.14 parses this; the recursive schema-keyword walk used to leak.
        payload = ('{"properties":{"version":{"const":"' + version + '"}},"not":' +
                   '{"not":' * 2400 + '{}' + '}' * 2400 + '}').encode()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(SchemaxisError) as error:
                store_shared(root, root / 'run/schema.snapshot.json', payload,
                             provider='pandoc', document_version=version)
            self.assertEqual(error.exception.fault.code, 'INVALID_SCHEMA_SNAPSHOT')
            self.assertIn('schema.snapshot.json', error.exception.fault.location)

    def test_unreadable_deep_parent_metadata_does_not_abort_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / 'parent'
            parent.mkdir()
            (parent / 'authored.json').write_text('[' * 2400 + '0' + ']' * 2400)
            run = parent / 'child'
            run.mkdir()
            manifest = capture_run(run, {'version': 'schemaxis.pandoc/1'})
            self.assertTrue(manifest.is_file())
