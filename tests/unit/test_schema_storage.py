# Copyright (C) 2026 David L F Gaden
"""Workspace sharing, offline retention, recovery and conservative ownership."""
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.core.faults import SchemaxisError
from schemaxis.schema_snapshots import capture_run, export_run, inspect, read, rebuild_index, store, store_shared, verify_run
from schemaxis.schema_store import canonical

VERSION = 'schemaxis.calc/1'
SCHEMA = {'properties': {'version': {'const': VERSION}}, 'description': 'Métadonnées', 'items': {'type': 'number'}}


def save(root, name, schema=None, **kwargs):
    return store_shared(root, Path(root)/name/'schema.snapshot.json', json.dumps(schema or SCHEMA).encode(),
                        provider='calc', document_version=VERSION, **kwargs)


def process_capture(arguments):
    root, index = arguments
    return str(save(root, 'run-' + str(index), provenance={'generator': 'test-' + str(index % 2)}))


class SharedSchemaTests(unittest.TestCase):
    def test_failed_schema_capture_invalidates_native_success(self):
        from schemaxis.adaptor_runtime import execute, AdaptorSession
        def native(document, directory, **kwargs):
            directory = Path(directory)
            directory.mkdir(parents=True, exist_ok=True)
            (directory/'result.json').write_text(json.dumps({
                'status': 'succeeded', 'verified': True, 'nativeEvidence': 'retained'}))
        for study in (False, True):
            with self.subTest(study=study), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with patch('schemaxis.schema_snapshots.capture_run', side_effect=OSError('schema store unavailable')):
                    with self.assertRaisesRegex(OSError, 'schema store unavailable'):
                        if study:
                            session = AdaptorSession(root, native, lambda *a: None, timeout=10, options={})
                            session.apply({'index': 0, 'document': {'version': VERSION}})
                        else:
                            execute({'version': VERSION}, root, {}, native, lambda *a: None, lambda d: {})
                path = root/'state-00000/result.json' if study else root/'result.json'
                status = json.loads(path.read_text())
                self.assertEqual(status['status'], 'failed')
                self.assertFalse(status['verified'])
                self.assertEqual(status['nativeEvidence'], 'retained')
                self.assertIn('schema store unavailable', status['verificationFault'])

    def test_canonical_identity_and_provenance_are_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = save(root, 'one', provenance={'application': 'A'})
            schema = dict(reversed(list(SCHEMA.items())))
            second = save(root, 'two', schema, provenance={'application': 'B'})
            self.assertEqual(read(first), read(second))
            self.assertEqual(read(first), canonical(SCHEMA))
            index = json.loads((root/'schemas/index.json').read_text())
            self.assertEqual(len(index['objects']), 1)
            self.assertEqual(len(next(iter(index['objects'].values()))['provenance']), 2)
            for label, changed in [('type', {**SCHEMA, 'items': {'type': 'string'}}),
                                   ('annotation', {**SCHEMA, 'description': 'Changed'}),
                                   ('array', {**SCHEMA, 'enum': [2, 1]})]:
                self.assertNotEqual(read(save(root, label, changed)), read(first))
            self.assertEqual(len(json.loads((root/'schemas/index.json').read_text())['objects']), 4)

    def test_names_are_immutable_and_corruption_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = save(root, 'one')
            self.assertEqual(save(root, 'one'), path)
            with self.assertRaises(SchemaxisError):
                save(root, 'one', {**SCHEMA, 'description': 'changed'})
            manifest = json.loads(path.read_text())
            blob = root/manifest['schema']
            blob.write_bytes(b'broken')
            for action in (lambda: read(path), lambda: save(root, 'two'), lambda: rebuild_index(root)):
                with self.assertRaises(SchemaxisError):
                    action()
            self.assertEqual(blob.read_bytes(), b'broken')
            self.assertTrue(inspect(root)['faults'])

    def test_missing_object_is_predictable_and_offline_read_does_not_regenerate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = save(root, 'one')
            manifest = json.loads(path.read_text())
            with patch('schemaxis.schema.export_schema', side_effect=AssertionError('must not regenerate')):
                self.assertEqual(read(path), canonical(SCHEMA))
                (root/manifest['schema']).unlink()
                with self.assertRaises(SchemaxisError) as caught:
                    read(path)
                self.assertEqual(caught.exception.fault.code, 'INVALID_SCHEMA_SNAPSHOT')
                self.assertTrue(inspect(root)['faults'])

    def test_concurrent_processes_do_not_lose_index_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            with ProcessPoolExecutor(max_workers=3) as pool:
                paths = list(pool.map(process_capture, [(temporary, n) for n in range(9)]))
            self.assertTrue(all(read(path) == canonical(SCHEMA) for path in paths))
            index = json.loads((Path(temporary)/'schemas/index.json').read_text())
            self.assertEqual(len(index['objects']), 1)
            self.assertEqual(len(next(iter(index['objects'].values()))['provenance']), 2)
            self.assertFalse(list(Path(temporary).rglob('*.tmp')))

    def test_interrupted_index_and_manifest_publication_recover(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('schemaxis.schema_store.atomic', side_effect=OSError('interruption')):
                with self.assertRaises(SchemaxisError):
                    save(root, 'interrupted')
            self.assertFalse((root/'interrupted/schema.snapshot.json').exists())
            self.assertEqual(len(list((root/'schemas').glob('*.json'))), 1)
            self.assertTrue(inspect(root)['faults'])
            rebuilt = rebuild_index(root)
            self.assertEqual(next(iter(rebuilt['objects'].values()))['provenance'], [])
            path = save(root, 'retry')
            (root/'schemas/index.json').write_bytes(b'{incomplete')
            self.assertEqual(read(path), canonical(SCHEMA))
            with self.assertRaises(SchemaxisError):
                save(root, 'blocked')
            self.assertEqual(len(next(iter(rebuild_index(root)['objects'].values()))['provenance']), 1)
            self.assertEqual(read(save(root, 'recovered')), canonical(SCHEMA))
            (root/'schemas/index.json').unlink()
            with self.assertRaises(SchemaxisError): save(root, 'missing-index')
            self.assertEqual(read(path), canonical(SCHEMA))
            rebuild_index(root)

    def test_interrupted_manifest_publish_is_retryable_and_lock_wait_is_bounded(self):
        import fcntl
        from schemaxis.schema_snapshots import _publish
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def interrupted(path, payload):
                if str(path).endswith('.snapshot.json'):
                    raise OSError('manifest interrupted')
                return _publish(path, payload)
            with patch('schemaxis.schema_store._publish', side_effect=interrupted):
                with self.assertRaises(SchemaxisError): save(root, 'run')
            self.assertFalse((root/'run/schema.snapshot.json').exists())
            self.assertEqual(len(json.loads((root/'schemas/index.json').read_text())['objects']), 1)
            self.assertEqual(read(save(root, 'run')), canonical(SCHEMA))
            with (root/'schemas/.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch('schemaxis.schema_store.time.monotonic', side_effect=[0, 11]):
                    with self.assertRaises(SchemaxisError) as caught: save(root, 'blocked')
                self.assertEqual(caught.exception.fault.code, 'SCHEMA_STORAGE_BUSY')

    def test_failed_export_keeps_source_and_marks_destination_incomplete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = save(root/'workspace', 'run').parent
            (source/'artifact.txt').write_text('evidence')
            with patch('schemaxis.schema_store.shutil.copy2', side_effect=OSError('disk full')):
                with self.assertRaises(SchemaxisError): export_run(source, root/'export')
            self.assertEqual((source/'artifact.txt').read_text(), 'evidence')
            self.assertTrue((root/'export/.schema-export-incomplete').is_file())
            with self.assertRaises(SchemaxisError): export_run(source, root/'export')
            with self.assertRaises(SchemaxisError): export_run(root/'export', root/'retry')
            self.assertFalse((root/'retry').exists())

    def test_portable_export_nested_runs_survives_source_and_store_removal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root/'workspace'
            first = save(workspace, 'workflow/a')
            second = save(workspace, 'workflow/attempts/b')
            legacy = store(workspace/'workflow/legacy', 'old', json.dumps(SCHEMA, indent=2).encode(),
                           provider='calc', document_version=VERSION, authored=True)
            expected_legacy = read(legacy)
            (workspace/'workflow/artifact.txt').write_text('retained native fixture')
            result = export_run(workspace/'workflow', root/'portable')
            self.assertEqual(result['manifests'], 3)
            shutil.rmtree(workspace)
            shutil.move(root/'portable', root/'relocated')
            for relative in ('a/schema.snapshot.json', 'attempts/b/schema.snapshot.json'):
                self.assertEqual(read(root/'relocated'/relative), canonical(SCHEMA))
            self.assertEqual(read(root/'relocated/legacy/old.snapshot.json'), expected_legacy)
            self.assertEqual((root/'relocated/artifact.txt').read_text(), 'retained native fixture')
            self.assertFalse((root/'relocated/.schema-export-incomplete').exists())

    def test_copy_entire_workspace_and_remove_one_run_preserves_other(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save(root/'original', 'a'); save(root/'original', 'b')
            shutil.copytree(root/'original', root/'moved')
            shutil.rmtree(root/'original')
            shutil.rmtree(root/'moved/a')
            self.assertEqual(read(root/'moved/b/schema.snapshot.json'), canonical(SCHEMA))
            state = inspect(root/'moved')
            self.assertEqual(len(state['references']), 1)
            self.assertFalse(state['usageComplete'])
            self.assertEqual(state['protectedPaths'], [str(root/'moved/schemas')])

    def test_symlinks_escape_and_malformed_reference_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = save(root/'workspace', 'a')
            original = path.read_bytes()
            for edit in ({'root': '/etc'}, {'root': '../sibling'}, {'schema': '../../outside'},
                         {'bytes': True}, {'provenance': []}, {'canonicalisation': 'unknown'}):
                path.write_text(json.dumps({**json.loads(original), **edit}))
                with self.subTest(edit=edit), self.assertRaises(SchemaxisError):
                    read(path)
            path.write_bytes(original)
            (root/'linked').symlink_to(root/'workspace', target_is_directory=True)
            for action in (lambda: read(root/'linked/a/schema.snapshot.json'),
                           lambda: save(root/'linked', 'b'),
                           lambda: store_shared(root/'workspace', root/'workspace/../outside/schema.snapshot.json',
                                                canonical(SCHEMA), provider='calc', document_version=VERSION)):
                with self.assertRaises(SchemaxisError): action()
            (root/'workspace/a/link').symlink_to(root/'workspace/schemas', target_is_directory=True)
            with self.assertRaises(SchemaxisError): export_run(root/'workspace/a', root/'exported')
            self.assertFalse((root/'exported').exists())
            self.assertTrue(inspect(root/'workspace')['faults'])

    def test_json_duplicates_nonfinite_and_wrong_version_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            for payload in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e309}', b'[]',
                            canonical({**SCHEMA, 'properties': {'version': {'const': 'other/1'}}})):
                with self.subTest(payload=payload), self.assertRaises(SchemaxisError):
                    store_shared(temporary, Path(temporary)/'run/schema.snapshot.json', payload,
                                 provider='calc', document_version=VERSION)

    def test_external_schema_dependencies_are_not_silently_lost(self):
        with tempfile.TemporaryDirectory() as temporary:
            for keyword in ('$ref', '$dynamicRef'):
                with self.assertRaises(SchemaxisError):
                    save(temporary, keyword, {**SCHEMA, 'items': {keyword: 'external.json#/$defs/item'}})
            path = save(temporary, 'literal', {**SCHEMA, 'const': {'$ref': 'literal data.json'}})
            self.assertIn(b'literal data.json', read(path))
            legacy = store(Path(temporary)/'legacy', 'external',
                           canonical({**SCHEMA, 'items': {'$ref': 'missing.json'}}),
                           provider='calc', document_version=VERSION, authored=True)
            self.assertIn(b'missing.json', read(legacy))  # old exact-byte reads remain compatible
            with self.assertRaises(SchemaxisError):
                export_run(legacy.parent, Path(temporary)/'portable')
            self.assertFalse((Path(temporary)/'portable').exists())

    def test_capture_two_non_cfd_adaptors_and_nested_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for provider in ('calc', 'ffmpeg'):
                document = {'version': 'schemaxis.' + provider + '/1'}
                paths = [capture_run(root/(provider + str(n)), document) for n in range(2)]
                self.assertEqual(read(paths[0]), read(paths[1]))
                self.assertEqual(json.loads(paths[0].read_text())['root'], '..')
                (paths[0].parent/'authored.json').write_text(json.dumps(document))
                verify_run(paths[0].parent)
                (paths[0].parent/'authored.json').write_text('{"version":"mismatch/1"}')
                with self.assertRaises(SchemaxisError): verify_run(paths[0].parent)
            workflow = root/'workflow'
            workflow.mkdir(); (workflow/'authored.json').write_text('{"version":"schemaxis.workflow/1"}')
            child = capture_run(workflow/'steps/child', {'version': VERSION})
            self.assertEqual(json.loads(child.read_text())['root'], '../../..')
            self.assertEqual(len(json.loads((root/'schemas/index.json').read_text())['objects']), 2)
            unrelated = root/'unrelated'
            unrelated.mkdir(); (unrelated/'authored.json').write_text(json.dumps({'version': VERSION}))
            local = capture_run(unrelated/'independent', {'version': VERSION})
            self.assertEqual(json.loads(local.read_text())['root'], '..')
            study = root/'study'
            study.mkdir(); (study/'authored.json').write_text(json.dumps({'version': VERSION}))
            (study/'result.json').write_text(json.dumps({'protocol': 'schemaxis.adaptor-execution/1'}))
            nested = capture_run(study/'state-00000', {'version': VERSION})
            self.assertEqual(json.loads(nested.read_text())['root'], '../..')
            self.assertIsNone(capture_run(root/'legacy', {'nodes': []}))
            verify_run(root/'old-evidence')

    def test_plan_only_dynamic_provider_needs_no_manufactured_schema(self):
        from schemaxis.adaptors import registry
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(registry.ADAPTORS, {'planonly': {'version': 'schemaxis.planonly/1', 'adaptor': 'planonly'}}):
                self.assertIsNone(capture_run(Path(temporary)/'run', {'version': 'schemaxis.planonly/1'}))
            with patch('schemaxis.schema.export_schema', side_effect=RuntimeError('broken declared schema')):
                with self.assertRaisesRegex(RuntimeError, 'broken declared schema'):
                    capture_run(Path(temporary)/'run', {'version': VERSION})
            self.assertFalse((Path(temporary)/'run').exists())

    def test_all_registered_schema_routes_are_capturable_without_native_imports(self):
        from schemaxis.adaptors import registry
        blocked = {'paraview', 'bpy', 'FreeCAD', 'gmsh', 'qgis', 'cantera', 'pcbnew', 'ij'}
        class NativeImportBlocker:
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split('.')[0] in blocked:
                    raise AssertionError('native import: ' + fullname)
        blocker = NativeImportBlocker()
        with tempfile.TemporaryDirectory() as temporary:
            sys.meta_path.insert(0, blocker)
            try:
                for index, (version, (provider, route)) in enumerate(registry.routes().items()):
                    with self.subTest(provider=provider, version=version):
                        path = capture_run(Path(temporary)/str(index), {'version': version})
                        manifest = json.loads(path.read_text())
                        self.assertEqual(manifest['provider'], provider)
                        self.assertEqual(json.loads(read(path))['properties']['version']['const'], version)
                workflow = capture_run(Path(temporary)/'workflow', {'version': 'schemaxis.workflow/1'})
                self.assertEqual(json.loads(read(workflow))['properties']['version']['const'], 'schemaxis.workflow/1')
            finally:
                sys.meta_path.remove(blocker)
