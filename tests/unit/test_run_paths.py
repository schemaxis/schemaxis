# Copyright (C) 2026 David L F Gaden
"""Exported evidence reads its selected copy, without rewriting native receipts."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise, publish_artifacts, verify
from schemaxis.run_paths import MANIFEST, owned_path
from schemaxis.schema_snapshots import export_run


class PortablePublicationTests(unittest.TestCase):
    def test_ancestor_alias_publishes_without_rewriting_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); real = base/'real'; real.mkdir()
            alias = base/'alias'; alias.symlink_to(real, target_is_directory=True)
            for name, recorded_root in [('alias-recorded', alias), ('real-recorded', real)]:
                run = real/name; run.mkdir(); (run/'data.txt').write_text('retained')
                artifact = {'file': str(recorded_root/name/'data.txt'), 'kind': 'text'}
                atomic_json(run/'verification.json', {'artifacts': [artifact]})
                receipt = (run/'verification.json').read_bytes()
                publish_artifacts(alias/name, [artifact])
                self.assertTrue(verify(run)['verified'])
                self.assertTrue(verify(alias/name)['verified'])
                self.assertEqual(owned_path(run, artifact['file']), run/'data.txt')
                self.assertEqual(receipt, (run/'verification.json').read_bytes())
                self.assertNotIn('recordedDirectory', json.loads((run/MANIFEST).read_text()))

    def test_alias_cannot_hide_internal_links_even_when_they_reenter_the_run(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); real = base/'real'; real.mkdir()
            alias = base/'alias'; alias.symlink_to(real, target_is_directory=True)
            run = real/'run'; run.mkdir(); (run/'inner').mkdir()
            (run/'inner/data.txt').write_text('retained')
            (run/'inner-link').symlink_to(run/'inner', target_is_directory=True)
            (run/'file-link').symlink_to(run/'inner/data.txt')
            (run/'selfloop').symlink_to(run, target_is_directory=True)
            (run/'uplink').symlink_to(real, target_is_directory=True)
            foreign = base/'foreign-leaf'; foreign.symlink_to(run/'inner/data.txt')
            for prefix in (real, alias):
                for tail in ('inner-link/data.txt', 'file-link',
                             'selfloop/inner/data.txt', 'uplink/run/inner/data.txt'):
                    with self.subTest(prefix=prefix, tail=tail), self.assertRaises(SchemaxisError) as caught:
                        owned_path(run, prefix/'run'/tail)
                    self.assertIn('traverses a link', caught.exception.fault.message)
            with self.assertRaises(SchemaxisError):
                owned_path(run, foreign)

    def test_origin_hint_never_uses_alias_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); real = base/'real'; real.mkdir()
            alias = base/'alias'; alias.symlink_to(real, target_is_directory=True)
            run = real/'run'; run.mkdir(); (run/'data.txt').write_text('retained')
            atomic_json(run/MANIFEST, {'version': 'schemaxis.artifact-metadata/1',
                                      'recordedDirectory': str(base/'old-run'), 'publications': []})
            with self.assertRaises(SchemaxisError):
                owned_path(run, alias/'run/data.txt')

    def test_deep_missing_foreign_path_does_not_repeatedly_resolve_ancestors(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp); calls = []
            original = Path.resolve
            def counted(path, *args, **kwargs):
                calls.append(path)
                return original(path, *args, **kwargs)
            foreign = run.parent/('absent-' + run.name)/Path(*(['x'] * 1500))/'data.txt'
            with patch.object(Path, 'resolve', counted), self.assertRaises(SchemaxisError) as caught:
                owned_path(run, foreign)
            self.assertIn('outside its owned directory', caught.exception.fault.message)
            # No wall-clock threshold: absent tails must not multiply filesystem resolution work.
            self.assertLess(len(calls), 20)

    def test_malformed_paths_and_manifest_have_structured_actionable_faults(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for value in ('', ' ', '\t'):
                with self.subTest(path=value), self.assertRaises(SchemaxisError) as caught:
                    owned_path(root, value, kind='directory')
                self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
                self.assertEqual(caught.exception.fault.location, '$')
            (root/'data.txt').write_text('retained')
            for payload in ('unrelated native data', '{"version":"foreign"}'):
                (root/MANIFEST).write_text(payload)
                with self.subTest(manifest=payload), self.assertRaises(SchemaxisError) as caught:
                    owned_path(root, 'data.txt')
                self.assertIn(str(root/MANIFEST), caught.exception.fault.message)

    def fixture(self, root):
        root.mkdir()
        artifacts = []
        for name in ('first', 'second'):
            child = root/name
            child.mkdir()
            (child/'data.txt').write_text(name)
            item = {'file': str(child/'data.txt'), 'kind': 'text'}
            atomic_json(child/'verification.json', {'artifacts': [item]})
            publish_artifacts(child, [item])
            artifacts.append(item)
        atomic_json(root/'verification.json', {'artifacts': artifacts})
        publish_artifacts(root, artifacts)

    def test_nested_export_move_reexport_preserves_receipts_and_source(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); source = base/'source'; self.fixture(source)
            before = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            exported = base/'exported'
            export_run(source, exported)
            self.assertEqual(before, {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()})
            for name in (Path('.'), Path('first'), Path('second')):
                self.assertEqual((exported/name/'verification.json').read_bytes(), before[name/'verification.json'])
                self.assertTrue(verify(exported/name)['verified'])
            source.rename(base/'unavailable-original')
            moved = base/'moved'; exported.rename(moved)
            self.assertTrue(verify(moved)['verified'])
            final = base/'again'; export_run(moved, final)
            moved.rename(base/'unavailable-export')
            self.assertTrue(verify(final)['verified'])
            self.assertTrue(verify(final/'first')['verified'])
            self.assertEqual(json.loads((final/MANIFEST).read_text())['recordedDirectory'], str(source))

    def test_present_originals_never_replace_changed_or_missing_export_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); source = base/'source'; self.fixture(source)
            exported = base/'exported'; export_run(source, exported)
            (source/'first/data.txt').write_text('foreign modified original')
            self.assertTrue(verify(exported)['verified'])
            (exported/'first/data.txt').write_text('wrong local bytes')
            with self.assertRaises(SchemaxisError): verify(exported)
            (exported/'first/data.txt').unlink()
            with self.assertRaises(SchemaxisError): verify(exported)

    def test_finalisation_preserves_export_origin_and_original_receipt_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); source = base/'source'; self.fixture(source)
            exported = base/'exported'; export_run(source, exported)
            source.rename(base/'unavailable')
            for name in (Path('.'), Path('first'), Path('second')):
                directory = exported/name
                receipt = (directory/'verification.json').read_bytes()
                manifest = finalise(directory)
                self.assertEqual(manifest['recordedDirectory'], str(source/name))
                self.assertEqual((directory/'verification.json').read_bytes(), receipt)
                self.assertTrue(verify(directory)['verified'])
            again = base/'again'; export_run(exported, again)
            exported.rename(base/'unavailable-export')
            self.assertTrue(verify(again)['verified'])
            self.assertTrue(verify(again/'first')['verified'])
            # A malformed hint is refused before any companion or manifest is rewritten.
            atomic_json(again/MANIFEST, {'version': 'schemaxis.artifact-metadata/1',
                                       'recordedDirectory': '../outside', 'publications': []})
            before = {p: p.read_bytes() for p in again.rglob('*') if p.is_file()}
            with self.assertRaises(SchemaxisError): finalise(again)
            self.assertEqual(before, {p: p.read_bytes() for p in again.rglob('*') if p.is_file()})

    def test_origin_traversal_foreign_paths_and_linked_components_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); source = base/'source'; self.fixture(source)
            exported = base/'exported'; export_run(source, exported)
            manifest = json.loads((exported/MANIFEST).read_text())
            for value in ('relative', str(base/'other'), str(source/'..'), 12):
                with self.subTest(origin=value):
                    atomic_json(exported/MANIFEST, {**manifest, 'recordedDirectory': value})
                    with self.assertRaises(SchemaxisError): verify(exported)
            atomic_json(exported/MANIFEST, manifest)
            for name in ('../source/first/data.txt', str(base/'outside.txt')):
                with self.assertRaises(SchemaxisError): owned_path(exported, name)
            (exported/'first').rename(exported/'retained-first')
            (exported/'first').symlink_to(source/'first', target_is_directory=True)
            with self.assertRaises(SchemaxisError): verify(exported)

    def test_run_relative_bundle_members_keep_distinct_subdirectories(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); source = base/'source'; source.mkdir()
            for name in ('a', 'b'):
                (source/name).mkdir(); (source/name/'piece.txt').write_text(name)
            (source/'index.txt').write_text('bundle')
            artifact = {'file': 'index.txt', 'files': ['index.txt', 'a/piece.txt', 'b/piece.txt']}
            atomic_json(source/'verification.json', {'artifacts': [artifact]})
            publish_artifacts(source, [artifact])
            exported = base/'exported'; export_run(source, exported)
            source.rename(base/'unavailable')
            self.assertEqual(verify(exported)['publications'], 3)
            (exported/'b/piece.txt').write_text('a')
            with self.assertRaises(SchemaxisError): verify(exported)
