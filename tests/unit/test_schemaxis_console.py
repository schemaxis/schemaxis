# Copyright (C) 2026 David L F Gaden
import tempfile
import unittest
import copy
import hashlib
import json
import sys
import zipfile
from unittest.mock import patch
from pathlib import Path

from schemaxis.core.faults import SchemaxisError
from schemaxis.console import ConsoleSession
from schemaxis.console import AdaptorConsoleSession


def setUpModule():
    # These are host-only console tests. A developer's private installations must
    # not turn a dry preview assertion into an unintended native application run.
    local_configuration = patch('schemaxis.configuration.load',
                                return_value={'version': 1, 'locations': {}})
    local_configuration.start()
    unittest.addModuleCleanup(local_configuration.stop)


class ConsoleSessionTests(unittest.TestCase):
    def test_bounded_modelling_loop_and_dry_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            session = ConsoleSession(directory)
            self.addCleanup(session.close)
            session.execute('new Housing')
            session.execute('draw a rectangle 80 x 50 mm centred on the origin')
            session.execute('extrude housing 6 mm')
            result = session.execute('preview')
            self.assertEqual(result['status'], 'planned')
            self.assertTrue((Path(result['preview']) / 'authored.json').is_file())
            self.assertEqual(session.status()['selected'], 'housing')

    def test_undo_and_selection_are_authored_only(self):
        session = ConsoleSession(tempfile.mkdtemp())
        self.addCleanup(session.close)
        session.execute('box block 10 20 30')
        session.execute('select block')
        session.execute('undo')
        self.assertEqual(session.status()['nodes'], 0)
        with self.assertRaises(SchemaxisError):
            session.execute('run arbitrary python')

    def test_native_connection_is_explicit_and_validated(self):
        with self.assertRaises(SchemaxisError):
            ConsoleSession(tempfile.mkdtemp(), executable='/not/a/freecad')

    def test_common_console_opens_and_plans_all_adaptors(self):
        root = Path(__file__).resolve().parents[2] / 'examples' / 'schemaxis'
        examples = {'freecad': root / 'freecad-bracket.json',
                    'blender': root / 'blender-primitives.json',
                    'paraview': root / 'branching.json'}
        for provider, path in examples.items():
            with self.subTest(provider=provider):
                session = AdaptorConsoleSession(tempfile.mkdtemp(), provider=provider)
                self.addCleanup(session.close)
                result = session.open(path)
                self.assertEqual(result['provider'], provider)
                self.assertGreater(result['nodes'], 0)
                preview = session.preview()
                self.assertEqual(preview['status'], 'planned')


class FakeLive:
    def __init__(self):
        self.revision = 0
        self.closed = False
        self.fail = False
        self.divergent = False

    def request(self, command, **args):
        if self.fail: raise RuntimeError('native apply failed')
        assert command == 'apply'
        self.revision += 1
        self.document = copy.deepcopy(args['document'])
        return {'revision': self.revision}

    def geometry(self):
        if self.divergent:
            from schemaxis.errors import fail
            fail('NATIVE_DIVERGENCE', 'native GUI was edited')
        return {'revision': self.revision, 'objects': [{'id': self.document['output'], 'faces': []}]}

    def save(self, path):
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('Document.xml', '<Document SchemaVersion="4"><Objects/></Document>')
    def image(self, path): Path(path).write_bytes(b'\x89PNG\r\n\x1a\nimage')
    def close(self): self.closed = True


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.session = ConsoleSession(self.root / 'workspace')
        self.addCleanup(self.session.close)

    def box(self): self.session.execute('box block 10 20 30')

    def live(self):
        self.box()
        client = FakeLive()
        self.session.live = client
        self.session.preview()
        return client

    def test_lock_recovery_history_and_monotonic_revision(self):
        self.box()
        first = self.session.status()['revision']
        self.session.execute('set block width 40')
        second = self.session.status()['revision']
        self.session.undo()
        third = self.session.status()['revision']
        identity = self.session.active_document
        with self.assertRaises(SchemaxisError): ConsoleSession(self.session.workspace)
        self.session.close()
        with ConsoleSession(self.root / 'workspace') as recovered:
            self.assertEqual(recovered.active_document, identity)
            self.assertEqual(recovered.document['nodes'][0]['options']['width'], 20)
            recovered.redo()
            self.assertEqual(recovered.document['nodes'][0]['options']['width'], 40)
            self.assertTrue(first < second < third < recovered.status()['revision'])
            self.assertFalse(recovered.status()['resident'])

    def test_full_document_metadata_open_undo_redo(self):
        self.box()
        document = self.session.document
        document.update(linearDeflection=0.05, definitions={}, dimensions={})
        source = self.root / 'authored with spaces.json'
        source.write_text(json.dumps(document))
        self.session.execute('open ' + json.dumps(str(source)))
        self.session.execute('set block height 50')
        self.session.undo()
        self.assertEqual(self.session.document, document)
        self.session.redo()
        self.assertEqual(self.session.document['linearDeflection'], .05)
        self.assertIn('definitions', self.session.document)
        destination = self.root / 'saved with spaces.json'
        self.session.execute('save ' + json.dumps(str(destination)))
        self.assertEqual(json.loads(destination.read_text()), self.session.document)

    def test_rejected_commands_do_not_change_state_or_history(self):
        self.box()
        for line in ('box invalid nan 1 1', 'box invalid inf 1 1', 'box invalid -1 1 1',
                     'box block 1 1 1', 'set block width true', 'set block width NaN',
                     'set block bogus 3', 'add invalid box \'{"length": "10"}\'',
                     'add invalid box []', 'status ignored', 'preview a b', 'open "unfinished'):
            with self.subTest(line=line):
                before = self.session.status()
                history = self.session.history
                with self.assertRaises(SchemaxisError): self.session.execute(line)
                self.assertEqual(self.session.status(), before)
                self.assertEqual(self.session.history, history)

    def test_multi_document_provider_configs_and_disconnect(self):
        self.box()
        original = self.session.active_document
        self.session.configure('freecad', sys.executable)
        self.session.configure('blender', sys.executable)
        self.session.new('Other', 'blender')
        self.assertEqual(self.session.provider, 'blender')
        self.assertEqual(len(self.session.status()['documents']), 2)
        self.assertEqual(len(self.session.status()['connections']), 2)
        self.session.activate(original)
        self.assertEqual(self.session.output, 'block')
        self.session.unload()
        self.assertTrue(self.session.status()['configured'])
        self.session.disconnect()
        self.assertIsNone(self.session.executable)
        self.assertEqual(self.session.preview()['status'], 'planned')

    def test_live_stale_geometry_image_and_save(self):
        client = self.live()
        self.assertEqual(self.session.geometry()['revision'], self.session.status()['revision'])
        self.assertTrue(Path(self.session.image()).is_file())
        self.session.save(self.root / 'valid.FCStd')
        self.session.execute('set block width 40')
        for operation in (self.session.geometry, self.session.image, lambda: self.session.save(self.root / 'stale.FCStd')):
            with self.assertRaises(SchemaxisError): operation()
        self.session.undo()
        with self.assertRaises(SchemaxisError): self.session.save(self.root / 'undo.FCStd')
        self.session.preview()
        self.assertEqual(self.session.geometry()['revision'], self.session.status()['revision'])
        client.divergent = True
        with self.assertRaises(SchemaxisError): self.session.geometry()
        self.assertFalse(self.session.status()['resident'])

    def test_live_client_bound_to_document_and_provider(self):
        client = self.live()
        original = self.session.active_document
        self.session.new('Second')
        self.box()
        self.assertIsNone(self.session.live)
        self.assertEqual(self.session.preview()['status'], 'planned')
        with self.assertRaises(SchemaxisError): self.session.live = client
        self.session.switch_provider('blender')
        self.session.execute('add mat material')
        self.session.execute('add cube cube \'{}\' \'{"material":{"$object":"mat"}}\'')
        self.assertEqual(self.session.preview()['status'], 'planned')
        self.session.activate(original)
        self.assertIs(self.session.live, client)
        self.assertEqual(self.session.geometry()['revision'], self.session.status()['revision'])

    def test_retained_clients_switch_edit_unload_and_close(self):
        first = self.live()
        first_id = self.session.active_document
        first_document = self.session.document
        first_revision = self.session.status()['revision']
        self.session.new('Other', 'blender')
        second_id = self.session.active_document
        self.session.execute('add paint material')
        self.session.execute('add cube cube \'{}\' \'{"material":{"$object":"paint"}}\'')
        class BlenderLive(FakeLive):
            provider = 'blender'
            def geometry(client):
                return {'revision': client.revision, 'objects': [{'id': 'cube', 'faces': []}]}
        second = BlenderLive()
        self.session.live = second
        self.session.preview()
        self.assertEqual(len([c for c in self.session.status()['connections'] if c['mode'] == 'live']), 2)
        self.session.activate(first_id)
        self.assertIs(self.session.live, first)
        self.assertEqual(self.session.document, first_document)
        self.assertEqual(self.session.geometry()['revision'], first_revision)
        self.assertEqual(first.revision, 1)  # Switch/query did not replay apply.
        self.session.execute('set block width 40')
        with self.assertRaises(SchemaxisError): self.session.geometry()
        self.assertIs(self.session.live, first)
        self.session.activate(second_id)
        self.assertIs(self.session.live, second)
        self.assertEqual(self.session.geometry()['objects'][0]['id'], 'cube')
        self.session.unload()
        self.assertTrue(second.closed)
        self.assertFalse(first.closed)
        self.session.activate(first_id)
        self.assertIs(self.session.live, first)
        with self.assertRaises(SchemaxisError): self.session.geometry()
        self.session.preview()
        self.session.new('Third')
        self.box()
        third = FakeLive()
        self.session.live = third
        self.session.preview()
        self.session.close()
        self.assertTrue(first.closed)
        self.assertTrue(third.closed)

    def test_inactive_native_divergence_and_failure_are_document_local(self):
        first = self.live()
        first_id = self.session.active_document
        self.session.new('Second')
        second = self.live()
        second_id = self.session.active_document
        first.divergent = True
        self.session.activate(first_id)
        with self.assertRaises(SchemaxisError): self.session.geometry()
        self.assertTrue(first.closed)
        self.assertIsNone(self.session.live)
        self.session.activate(second_id)
        self.assertIs(self.session.live, second)
        self.assertFalse(second.closed)
        self.assertEqual(self.session.geometry()['revision'], self.session.status()['revision'])
        state = self.session.status()
        self.assertEqual(state['documents'][first_id]['nativeState'], 'unavailable')
        self.assertTrue(state['documents'][second_id]['resident'])

    def test_close_attempts_all_clients_when_one_close_fails(self):
        first = self.live()
        self.session.new('Second')
        second = self.live()
        with patch.object(first, 'close', side_effect=RuntimeError('close failed')):
            with self.assertRaises(RuntimeError): self.session.close()
        self.assertTrue(second.closed)
        with ConsoleSession(self.session.workspace) as recovered:
            self.assertIsNone(recovered.live)
            self.assertFalse(any(record['resident'] for record in recovered.status()['documents'].values()))

    def test_failed_preview_record_retry_and_retained_snapshot(self):
        client = self.live()
        previous = self.session.last_preview
        client.fail = True
        with self.assertRaises(RuntimeError): self.session.preview()
        record = self.session.status()['documents'][self.session.active_document]
        self.assertEqual(record['attempts'][-1]['status'], 'failed')
        self.assertFalse(self.session.status()['resident'])
        self.assertEqual(self.session.last_preview, previous)
        self.session.save(self.root / 'retained.FCStd')
        client.fail = False
        self.session.preview()
        self.assertNotEqual(self.session.last_preview, previous)
        self.assertEqual(len(self.session.checkpoints), 2)

    def test_artifact_and_receipt_tampering_wrong_extension_overwrite(self):
        self.live()
        with self.assertRaises(SchemaxisError): self.session.save(self.root / 'wrong.step')
        destination = self.root / 'saved.FCStd'
        self.session.save(destination)
        with self.assertRaises(SchemaxisError): self.session.save(destination)
        source = Path(self.session.artifacts()[0]['file'])
        original = source.read_bytes()
        source.write_bytes(b'tampered')
        with self.assertRaises(SchemaxisError): self.session.save(self.root / 'tampered.FCStd')
        source.write_bytes(original)
        receipt = Path(self.session.last_preview) / 'console-receipt.json'
        receipt.write_text('{}')
        with self.assertRaises(SchemaxisError): self.session.save(self.root / 'receipt.FCStd')

    def test_blender_incremental_material_cube_and_actual_artifact_name(self):
        self.session.switch_provider('blender')
        self.session.execute('add mat material')
        self.assertEqual(self.session.document['scenes'], [])
        with self.assertRaises(SchemaxisError): self.session.preview()
        self.session.execute('add cube cube \'{}\' \'{"material":{"$object":"mat"}}\'')
        self.assertEqual(self.session.preview()['status'], 'planned')
        self.session.execute('add bevel bevel \'{}\' \'{"input":"cube"}\'')
        self.session.execute('show bevel')
        self.assertEqual(self.session.document['scenes'][0]['visible'], ['bevel'])
        with self.assertRaises(SchemaxisError): self.session.remove('mat')
        self.session.configure('blender', sys.executable)
        def run(document, directory):
            directory.mkdir()
            path = directory / 'state-0001.blend'
            path.write_bytes(b'blender')
            receipt = {'artifacts': [{'file': str(path), 'sha256': hashlib.sha256(b'blender').hexdigest()}]}
            (directory / 'verification.json').write_text(json.dumps(receipt))
            return {'verified': True}
        with patch.object(self.session, '_run', side_effect=run): self.session.preview()
        self.session.save(self.root / 'scene.blend')
        self.assertEqual((self.root / 'scene.blend').read_bytes(), b'blender')

    def test_atomic_persistence_failure_leaves_state_unchanged(self):
        self.box()
        before = self.session.status()
        with patch('schemaxis.console_session.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.session.execute('set block width 80')
        self.assertEqual(self.session.status(), before)
        self.session.close()
        with ConsoleSession(self.root / 'workspace') as recovered:
            self.assertEqual(recovered.document['nodes'][0]['options']['width'], 20)

    def test_directory_fsync_failure_reconciles_published_revision(self):
        from schemaxis.console_session import AtomicPublicationError
        self.live()
        previous = self.session.status()['revision']
        with patch('schemaxis.console_session.os.fsync', side_effect=[None, OSError('directory fsync failed')]):
            with self.assertRaises(AtomicPublicationError) as caught:
                self.session.execute('set block width 80')
        self.assertTrue(caught.exception.published)
        self.assertFalse(caught.exception.durable)
        disk = json.loads((self.session.workspace / 'session.json').read_text())['state']
        self.assertEqual(self.session._state, disk)
        self.assertEqual(self.session.document['nodes'][0]['options']['width'], 80)
        self.assertGreater(self.session.status()['revision'], previous)
        with self.assertRaises(SchemaxisError): self.session.geometry()
        committed = self.session.status()['revision']
        self.session.execute('set block height 90')
        self.assertGreater(self.session.status()['revision'], committed)
        self.session.undo()
        self.assertEqual(self.session.document['nodes'][0]['options']['width'], 80)

    def test_atomic_exclusive_reports_published_bytes_on_fsync_failure(self):
        from schemaxis.console_session import AtomicPublicationError, atomic
        path = self.root / 'publication.json'
        with patch('schemaxis.console_session.os.fsync', side_effect=[None, OSError('directory fsync failed')]):
            with self.assertRaises(AtomicPublicationError): atomic(path, b'{}', True)
        self.assertEqual(path.read_bytes(), b'{}')

    def test_start_live_closes_new_client_if_old_close_fails(self):
        previous = self.live()
        replacement = FakeLive()
        with patch('schemaxis.adaptors.freecad.live.LiveSession', return_value=replacement), patch.object(previous, 'close', side_effect=RuntimeError('old close failed')):
            with self.assertRaises(RuntimeError): self.session.start_live('/fake/FreeCAD')
        self.assertTrue(replacement.closed)
        self.assertIs(self.session.live, previous)
        self.assertFalse(self.session.status()['resident'])

    def test_freecad_snapshot_rejects_non_zip_and_discloses_scope(self):
        self.box()
        client = FakeLive()
        self.session.live = client
        with patch.object(client, 'save', side_effect=lambda path: Path(path).write_bytes(b'not an FCStd')):
            with self.assertRaises(SchemaxisError): self.session.preview()
        self.assertIsNone(self.session.last_preview)
        self.session.preview()
        result = self.session.save(self.root / 'snapshot.FCStd')
        self.assertEqual(result['nativeSave']['verificationScope'], 'nativeLiveSnapshot')
        self.assertFalse(result['nativeSave']['independentReopen'])
        self.assertNotIn('verified', result['nativeSave'])

    def test_corrupt_recovery_rejected_and_lock_released(self):
        self.session.close()
        path = self.root / 'workspace' / 'session.json'
        original = path.read_bytes()
        path.write_text('{"version":1,"state":{},"sha256":"wrong"}')
        with self.assertRaises(SchemaxisError): ConsoleSession(self.root / 'workspace')
        path.write_bytes(original)
        with ConsoleSession(self.root / 'workspace'): pass

    def test_constrained_profiles_and_remove_last(self):
        self.session.execute('rectangle sketch 10 20')
        self.assertEqual(self.session.nodes[0]['filter'], 'rectangle')
        self.assertEqual(self.session.preview()['status'], 'planned')
        self.session.remove('sketch')
        self.assertEqual(self.session.nodes, [])
        self.session.execute('circle round 5')
        self.session.execute('extrude cylinder 12')
        self.assertEqual(self.session.preview()['status'], 'planned')

    def test_draft_unknown_header_and_types_are_rejected(self):
        self.session.switch_provider('blender')
        self.session.execute('add mat material')
        before = self.session.status()
        with self.assertRaises(SchemaxisError): self.session.set('document', 'unknownHeader', 1)
        with self.assertRaises(SchemaxisError): self.session.add('invalid', ['cube'])
        self.assertEqual(self.session.status(), before)

    def test_dynamic_registry_provider_and_recovered_interrupted_attempt(self):
        from schemaxis.console_session import ADAPTORS
        module = type(sys)('console_test_provider')
        module.plan = lambda document: {'planned': document}
        with patch.dict(ADAPTORS, {'testprovider': {'version': 'schemaxis.testprovider/1', 'adaptor': module.__name__}}), patch.dict(sys.modules, {module.__name__: module}):
            self.session.new('Dynamic', 'testprovider')
            self.session.add('item', 'declared')
            self.assertEqual(self.session.preview()['status'], 'planned')
            state = copy.deepcopy(self.session._state)
            state['documents'][self.session.active_document]['attempts'].append({'id': 'interrupted-test', 'revision': self.session.status()['revision'], 'status': 'running'})
            self.session._commit(state)
            self.session.close()
            with ConsoleSession(self.root / 'workspace') as recovered:
                self.assertEqual(recovered.provider, 'testprovider')
                attempts = recovered.status()['documents'][recovered.active_document]['attempts']
                self.assertEqual(attempts[-1]['status'], 'interrupted')

    def test_godot_and_aseprite_incremental_plans(self):
        self.session.new('Game', 'godot')
        self.session.execute('add paint material')
        with self.assertRaises(SchemaxisError): self.session.preview()
        self.session.execute('add cube box \'{}\' \'{"material":"paint"}\'')
        self.session.execute('add camera camera')
        self.session.execute('set document preview true')
        self.assertTrue(self.session.document['preview'])
        self.assertEqual(self.session.preview()['status'], 'planned')
        self.session.new('Sprite', 'aseprite')
        self.session.execute('add sprite sprite \'{"width":16,"height":16}\'')
        self.assertEqual(self.session.output, 'sprite')
        self.assertEqual(self.session.preview()['status'], 'planned')
        self.session.execute('add frame frame \'{}\' \'{"sprite":"sprite"}\'')
        self.assertEqual(self.session.output, 'frame')
        self.session.undo()
        self.assertEqual(self.session.output, 'sprite')

    def test_batch_png_fallback_checks_receipts_and_revision(self):
        self.session.new('Sprite', 'aseprite')
        self.session.execute('add sprite sprite \'{"width":16,"height":16}\'')
        self.session.configure('aseprite', sys.executable)
        def run(document, directory):
            directory.mkdir()
            hashes = {}
            for name, payload in [('sprite.aseprite', b'native'), ('preview.png', b'\x89PNG\r\n\x1a\npreview'), ('sheet.png', b'\x89PNG\r\n\x1a\nsheet')]:
                (directory / name).write_bytes(payload)
                hashes[name] = hashlib.sha256(payload).hexdigest()
            return {'verified': True, 'sha256': hashes}
        with patch.object(self.session, '_run', side_effect=run): self.session.preview()
        path = Path(self.session.image())
        self.assertEqual(path.name, 'preview.png')
        self.session.save(self.root / 'saved.aseprite')
        copied = self.root / 'copied.png'
        self.assertEqual(self.session.image(copied), str(copied))
        path.write_bytes(b'tampered')
        with self.assertRaises(SchemaxisError): self.session.image()
        self.session.execute('set sprite width 24')
        with self.assertRaises(SchemaxisError): self.session.image()

    def test_blender_live_uses_only_supported_commands(self):
        self.session.new('Scene', 'blender')
        self.session.execute('add paint material')
        self.session.execute('add cube cube \'{}\' \'{"material":{"$object":"paint"}}\'')
        class Headless:
            def request(self, command, **args):
                if command == 'apply': return {'revision': 1}
                if command == 'geometry': return {'revision': 1, 'objects': []}
                raise AssertionError(command)
            def close(self): pass
        self.session.live = Headless()
        self.session.preview()
        self.assertEqual(self.session.artifacts()[0]['kind'], 'liveGeometry')
        self.assertEqual(self.session.geometry()['revision'], self.session.status()['revision'])
        with self.assertRaises(SchemaxisError): self.session.save(self.root / 'unsupported.blend')

    def test_readline_history_and_completion_are_workspace_scoped(self):
        import readline
        from schemaxis.console import completions, terminal_editor
        self.box()
        self.assertIn('block', completions(self.session, 'blo'))
        self.assertIn('preview', completions(self.session, 'pre'))
        previous = readline.get_completer()
        with terminal_editor(self.session, True):
            readline.add_history('inspect block')
            self.assertEqual(readline.get_completer()('blo', 0), 'block')
        self.assertIs(readline.get_completer(), previous)
        with terminal_editor(self.session, True):
            self.assertEqual(readline.get_history_item(readline.get_current_history_length()), 'inspect block')

    def test_live_native_save_preserves_scoped_receipt_and_dependencies(self):
        from schemaxis.console_session import digest
        self.session.new('View', 'paraview')
        self.session.add('sphere', 'sphere')
        class NativeSave:
            def request(client, command, **args):
                if command == 'apply':
                    client.document = args['document']
                    return {'revision': 1, 'geometryDigest': 'geometry', 'capabilities': ['save']}
                if command == 'geometry': return {'revision': 1, 'objects': []}
                raise AssertionError(command)
            def save(client, path):
                Path(path).write_bytes(b'native state')
                result = {'file': path, 'receipt': path + '.receipt.json', 'verified': True,
                    'revision': 1, 'documentDigest': digest(client.document), 'geometryDigest': 'geometry',
                    'kind': 'state', 'sha256': hashlib.sha256(b'native state').hexdigest(),
                    'externalDependencies': [{'file': '/external/dataset', 'copied': False}],
                    'datasetsCopied': False, 'verificationScope': 'state XML membership only'}
                Path(result['receipt']).write_text(json.dumps({**result, 'document': client.document, 'provider': 'paraview'}))
                return result
            def close(client): pass
        self.session.live = NativeSave()
        self.session.preview()
        result = self.session.save(self.root / 'state.pvsm')
        self.assertFalse(result['nativeSave']['datasetsCopied'])
        self.assertEqual(result['nativeSave']['verificationScope'], 'state XML membership only')
        receipt = next(a for a in self.session.artifacts() if a['kind'] == 'nativeSaveReceipt')
        Path(receipt['file']).write_text('{}')
        with self.assertRaises(SchemaxisError): self.session.save(self.root / 'tampered.pvsm')

    def test_freecad_assembly_open_full_edits_batch_receipt_and_recovery(self):
        source = Path(__file__).resolve().parents[2] / 'examples/schemaxis/freecad-assembly.json'
        self.session.open(source)
        authored = self.session.document
        self.assertEqual(self.session.status()['components'], 4)
        self.assertEqual(len(self.session.list_features()), 4)
        self.session.execute('set document dimensions \'{"plateThickness":6,"postHeight":25}\'')
        self.session.undo()
        self.assertEqual(self.session.document, authored)
        self.assertEqual(self.session.preview()['status'], 'planned')
        for command in ('box bad 1 1 1', 'add bad box', 'remove base', 'live /missing'):
            with self.assertRaises(SchemaxisError): self.session.execute(command)
        self.session.configure('freecad', sys.executable)
        def run(document, directory, **kwargs):
            self.assertEqual(document, authored)
            directory.mkdir()
            path = directory / 'model.FCStd'
            path.write_bytes(b'assembly')
            (directory / 'verification.json').write_text(json.dumps({'artifact': {'file': str(path), 'kind': 'cadScene', 'sha256': hashlib.sha256(b'assembly').hexdigest()}}))
            return {'verified': True}
        with patch('schemaxis.adaptors.registry.run', side_effect=run): self.session.preview()
        self.session.save(self.root / 'assembly.FCStd')
        self.session.close()
        with ConsoleSession(self.root / 'workspace') as recovered:
            self.assertEqual(recovered.document, authored)
            recovered.save(self.root / 'recovered.FCStd')

    def test_cancelled_live_discards_worker_preserves_authored_state(self):
        self.box()
        before = self.session.document
        class Cancelled(FakeLive):
            def request(client, command, **args):
                from schemaxis.errors import fail
                fail('RUNNER_CANCELLED', 'native operation cancelled')
        client = Cancelled()
        self.session.live = client
        with self.assertRaises(SchemaxisError): self.session.preview()
        self.assertEqual(self.session.document, before)
        self.assertIsNone(self.session.live)
        self.assertTrue(client.closed)
        self.assertEqual(self.session.status()['nativeState'], 'unavailable')
