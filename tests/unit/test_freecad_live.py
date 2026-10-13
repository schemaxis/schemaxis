"""Host contract/transport checks; native acceptance is tools/qualify_freecad_live.py."""
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.freecad.live import LiveSession, owner_alive, owner_record, prepare, validate


def box():
    return {'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'b', 'filter': 'box'}], 'output': 'b'}


class LiveContractTests(unittest.TestCase):
    def test_image_uses_owned_gui_document_even_when_another_is_active(self):
        from schemaxis.adaptors.freecad.live_native import Worker
        worker = Worker.__new__(Worker)
        worker.doc = Mock(Name='OwnedDocument')
        worker.gui = Mock()
        worker.gui.activeDocument.side_effect = AssertionError('Must not capture the unrelated active document')
        worker.prepared = {'output': 'box'}
        worker.revision = 7
        worker.ensure_synchronised = Mock()
        view = worker.gui.getDocument.return_value.activeView.return_value
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'owned.png'
            view.saveImage.side_effect = lambda *args: path.write_bytes(b'owned-image')
            result = worker.dispatch('image', {'path': str(path)})
            self.assertEqual(result['revision'], 7)
            worker.gui.getDocument.assert_called_once_with('OwnedDocument')
            view.saveImage.assert_called_once_with(str(path), 960, 720, 'White')
            worker.gui.activeDocument.assert_not_called()

    def test_owner_watchdog_identity(self):
        owner = owner_record()
        self.assertTrue(owner_alive(owner))
        if 'startTime' in owner:
            self.assertFalse(owner_alive({**owner, 'startTime': 'not-the-recorded-process'}))
        self.assertFalse(owner_alive({'pid': -1}))
        self.assertFalse(owner_alive({'pid': True}))
        with patch('schemaxis.adaptors.freecad.live.os.kill', side_effect=ProcessLookupError):
            self.assertFalse(owner_alive(owner))

    def test_cancelled_request_closes_transport(self):
        from schemaxis.dispatch import allocation
        event = threading.Event()
        event.set()
        with tempfile.TemporaryDirectory() as tmp:
            session = LiveSession.__new__(LiveSession)
            session.directory = Path(tmp)
            session.timeout = 2
            session._closed = False
            session._lock = threading.RLock()
            session.process = None
            session._log = None
            with allocation({}, event), self.assertRaises(SchemaxisError) as error:
                session.request('status')
            self.assertEqual(error.exception.fault.code, 'RUNNER_CANCELLED')
            self.assertTrue(session._closed)

    def test_native_modules_are_lazy(self):
        subprocess.run([sys.executable, '-c', 'import sys; from schemaxis.adaptors.freecad import live, live_native; '
                        'assert not any(x in sys.modules for x in ("FreeCAD", "FreeCADGui", "Part", "PySide"))'], check=True)

    def test_prepare_does_not_mutate_and_supports_profile(self):
        document = {'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'p', 'filter': 'polygon',
                    'options': {'points': [[0, 0], [2, 0], [0, 2]]}}], 'output': 'p'}
        original = copy.deepcopy(document)
        result = prepare(document)
        self.assertEqual(result['output'], 'p')
        self.assertEqual(len(result['nodes']), 1)
        self.assertEqual(document, original)

    def test_rejects_unbounded_or_executable_declarations(self):
        for change in ({'nodes': []}, {'nodes': box()['nodes']*101},
                       {'nodes': [{'id': 'b', 'filter': 'readSTEP', 'options': {'file': '/tmp/a.step'}}]},
                       {'nodes': [{'id': 'b', 'filter': 'box', 'options': {'length': {'$eval': '1'}}}]},
                       {'nodes': [{'id': 'b', 'filter': 'box', 'options': {'origin': [1e100, 0, 0]}}]},
                       {'nodes': [{'id': 'b', 'filter': 'box', 'options': {'length': float('nan')}}]},
                       {'script': 'print(1)'}):
            with self.subTest(change=change), self.assertRaises(SchemaxisError):
                prepare({**box(), **change})

    def test_resolves_authoring_containers_before_literal_validation(self):
        doc = box()
        doc.update(dimensions={'length': 12}, definitions={'origin': [1, 2, 3]}, settings={'width': 4})
        doc['nodes'][0]['options'] = {'length': {'$document': '/dimensions/length'},
            'origin': {'$document': '/definitions/origin'}, 'width': {'$document': '/settings/width'}}
        prepared = prepare(doc)
        self.assertEqual(prepared['nodes'][0]['options']['length'], 12)
        self.assertEqual(prepared['nodes'][0]['options']['origin'], [1, 2, 3])
        self.assertEqual(prepared['nodes'][0]['options']['width'], 4)
        self.assertIn('dimensions', doc)
        self.assertNotIn('dimensions', prepared)

    def test_all_declared_profile_kinds_support_preview(self):
        from schemaxis.adaptors.freecad.adaptor import DECLARATIONS
        for kind, declaration in DECLARATIONS.items():
            if declaration['kinds'] != ['profile']:
                continue
            options = {'points': [[0, 0], [4, 0], [0, 4]]} if kind == 'polygon' else {}
            doc = {'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'p', 'filter': kind, 'options': options}], 'output': 'p'}
            with self.subTest(kind=kind):
                self.assertEqual(prepare(doc)['output'], 'p')

    def test_command_allowlist_and_exact_arguments(self):
        for command, args in [('exec', {'code': 'pass'}), ('status', {'x': 1}), ('apply', {}),
                              ('select', {'object': 'b', 'subelement': 1}), ('save', {'path': 'relative.FCStd'})]:
            with self.subTest(command=command), self.assertRaises(SchemaxisError):
                validate(command, args)

    def test_outputs_cannot_overwrite_or_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'old.FCStd'
            path.write_text('preserve')
            with self.assertRaises(SchemaxisError):
                validate('save', {'path': str(path)})
            link = Path(tmp)/'link.FCStd'
            link.symlink_to(Path(tmp)/'missing')
            with self.assertRaises(SchemaxisError):
                validate('save', {'path': str(link)})
            self.assertEqual(path.read_text(), 'preserve')

    def test_existing_session_directory_preserved(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SchemaxisError):
            LiveSession(sys.executable, tmp)

    def test_startup_exit_is_bounded_and_directory_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'session'
            with self.assertRaises(SchemaxisError) as error:
                LiveSession('/bin/true', target, startup_timeout=1)
            self.assertEqual(error.exception.fault.code, 'NATIVE_EXIT')
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)

    def test_startup_timeout_terminates_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('schemaxis.adaptors.freecad.live.subprocess.Popen') as popen:
                from unittest.mock import Mock
                process = Mock(pid=987654321)
                process.poll.return_value = None
                popen.return_value = process
                with patch('schemaxis.adaptors.freecad.live.os.killpg') as kill:
                    with self.assertRaises(SchemaxisError) as error:
                        LiveSession('/bin/true', Path(tmp)/'session', startup_timeout=0.05)
                    self.assertEqual(error.exception.fault.code, 'LIVE_TIMEOUT')
                    self.assertTrue(kill.called)
                    self.assertTrue(process.wait.called)
