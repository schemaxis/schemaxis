"""Immutable portable schema evidence, byte identity and failure handling."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.core.faults import SchemaxisError
from schemaxis.schema_snapshots import capture, read, store

VERSION = 'schemaxis/1'
# Keep whitespace and non-ASCII bytes: importing evidence must be lossless.
PAYLOAD = ('{ "properties": {"version": {"const": "schemaxis/1"}}, '
           '"description": "Métadonnées", "$defs": {"item": {"type": "number"}}, '
           '"items": {"$ref": "#/$defs/item"} }\n').encode('utf-8')


def save(directory, name, payload=PAYLOAD):
    return store(directory, name, payload, provider='paraview', document_version=VERSION, authored=True)


class SchemaSnapshotTests(unittest.TestCase):
    def test_repeated_captures_share_exact_bytes_and_survive_relocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = save(root/'original', 'first')
            second = save(root/'original', 'second')
            self.assertEqual(read(first), PAYLOAD)
            self.assertEqual(read(second), PAYLOAD)
            self.assertEqual(len(list((root/'original/schemas').glob('*.json'))), 1)
            shutil.copytree(root/'original', root/'moved')
            shutil.rmtree(root/'original')
            self.assertEqual(read(root/'moved/first.snapshot.json'), PAYLOAD)
            manifest = json.loads((root/'moved/second.snapshot.json').read_text())
            self.assertEqual(manifest['documentVersion'], VERSION)
            self.assertEqual(manifest['bytes'], len(PAYLOAD))
            self.assertFalse(Path(manifest['schema']).is_absolute())

    def test_changed_content_is_new_identity_and_capture_names_are_immutable(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = save(temporary, 'first')
            changed = PAYLOAD.replace(b'number', b'string')
            second = save(temporary, 'second', changed)
            self.assertNotEqual(json.loads(first.read_text())['sha256'], json.loads(second.read_text())['sha256'])
            self.assertEqual(save(temporary, 'first'), first)  # Retry is idempotent.
            with self.assertRaises(SchemaxisError) as caught:
                save(temporary, 'first', changed)
            self.assertEqual(caught.exception.fault.code, 'SCHEMA_SNAPSHOT_EXISTS')
            self.assertEqual(read(first), PAYLOAD)

    def test_missing_tampered_and_escaping_references_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = save(temporary, 'first')
            original = json.loads(path.read_text())
            target = Path(temporary)/original['schema']
            target.write_bytes(PAYLOAD + b' ')
            with self.assertRaises(SchemaxisError):
                read(path)
            with self.assertRaises(SchemaxisError):
                save(temporary, 'new')  # Never silently repair corrupted evidence.
            target.unlink()
            with self.assertRaises(SchemaxisError):
                read(path)
            target.write_bytes(PAYLOAD)
            for edits in ({'schema': '../outside.json'}, {'documentVersion': 'different/1'}, {'authored': 'yes'}, {'bytes': True}):
                path.write_text(json.dumps({**original, **edits}))
                with self.subTest(edits=edits), self.assertRaises(SchemaxisError):
                    read(path)

    def test_concurrent_captures_publish_one_complete_object(self):
        with tempfile.TemporaryDirectory() as temporary:
            with ThreadPoolExecutor(max_workers=6) as pool:
                paths = list(pool.map(lambda index: save(temporary, 'capture-' + str(index % 3)), range(18)))
            self.assertTrue(all(read(path) == PAYLOAD for path in paths))
            self.assertEqual(len(list((Path(temporary)/'schemas').iterdir())), 1)
            self.assertEqual(len(list(Path(temporary).glob('*.snapshot.json'))), 3)
            self.assertFalse(list(Path(temporary).rglob('*.tmp')))

    def test_interrupted_publication_leaves_no_partial_file_or_temporary(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch('schemaxis.schema_snapshots.os.link', side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):
                    save(temporary, 'interrupted')
            self.assertFalse(list(Path(temporary).rglob('*.json')))
            self.assertFalse(list(Path(temporary).rglob('*.tmp')))

    def test_capture_regenerates_after_registry_changes_and_read_needs_no_registry(self):
        schema = json.loads(PAYLOAD)
        with tempfile.TemporaryDirectory() as temporary:
            with patch('schemaxis.schema.export_schema', return_value=schema) as export:
                first = capture(temporary, 'before', version=VERSION)
                schema['description'] = 'Changed declaration'
                second = capture(temporary, 'after', version=VERSION)
                self.assertEqual(export.call_count, 2)
            with patch('schemaxis.adaptors.registry.resolve', side_effect=AssertionError('must read retained evidence')):
                self.assertNotEqual(read(first), read(second))

    def test_invalid_schema_and_capture_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            for payload in (b'[]', b'{"properties": []}', b'{"properties":{"version":{"const":"other"}}}', PAYLOAD.replace(b'"M', b'NaN, "M')):
                with self.subTest(payload=payload), self.assertRaises(SchemaxisError):
                    save(temporary, 'invalid', payload)
            for name in ('../outside', '/absolute', '', '..'):
                with self.subTest(name=name), self.assertRaises(SchemaxisError):
                    save(temporary, name)
