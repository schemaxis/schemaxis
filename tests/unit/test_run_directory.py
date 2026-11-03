# Copyright (C) 2026 David L F Gaden
"""Run output convenience must preserve evidence and exclusive ownership."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import unittest

from schemaxis.core.faults import SchemaxisError
from schemaxis.storage import prepare_run_directory


class RunDirectoryTests(unittest.TestCase):
    def test_existing_content_is_never_modified(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            for name in ('authored.json', '.hidden', 'other.txt'):
                with self.subTest(name=name):
                    retained = target / name
                    retained.write_bytes(b'original evidence')
                    with self.assertRaises(SchemaxisError) as caught:
                        prepare_run_directory(target, {'new': True})
                    self.assertEqual(caught.exception.fault.code, 'OUTPUT_EXISTS')
                    self.assertEqual(retained.read_bytes(), b'original evidence')
                    self.assertEqual(list(target.iterdir()), [retained])
                    retained.unlink()

    def test_files_and_symlinks_are_not_output_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'file').write_text('keep')
            (root / 'empty').mkdir()
            (root / 'link').symlink_to(root / 'empty', target_is_directory=True)
            (root / 'dangling').symlink_to(root / 'missing')
            for name in ('file', 'link', 'dangling'):
                with self.subTest(name=name), self.assertRaises(SchemaxisError) as caught:
                    prepare_run_directory(root / name, {})
                self.assertEqual(caught.exception.fault.code, 'OUTPUT_EXISTS')
            self.assertEqual((root / 'file').read_text(), 'keep')
            self.assertEqual(list((root / 'empty').iterdir()), [])
            self.assertFalse((root / 'missing').exists())

    def test_parent_file_has_actionable_path_fault(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp) / 'file'
            parent.write_text('keep')
            with self.assertRaises(SchemaxisError) as caught:
                prepare_run_directory(parent / 'run', {})
            self.assertEqual(caught.exception.fault.code, 'INVALID_OUTPUT_PATH')
            self.assertEqual(parent.read_text(), 'keep')

    def test_concurrent_starts_have_exactly_one_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'nested' / 'run'
            barrier = threading.Barrier(2)
            def start(identity):
                barrier.wait(timeout=5)
                try:
                    prepare_run_directory(target, {'owner': identity})
                    return identity
                except SchemaxisError as error:
                    self.assertEqual(error.fault.code, 'OUTPUT_EXISTS')
                    return None
            with ThreadPoolExecutor(max_workers=2) as workers:
                outcomes = list(workers.map(start, (1, 2)))
            winners = [value for value in outcomes if value is not None]
            self.assertEqual(len(winners), 1)
            self.assertEqual(json.loads((target / 'authored.json').read_text()), {'owner': winners[0]})
