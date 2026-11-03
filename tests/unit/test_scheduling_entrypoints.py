# Copyright (C) 2026 David L F Gaden
"""Agent, CLI and Studio share durable scheduling with no native dispatch."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from schemaxis.agent_transport import dispatch
from schemaxis.execution_service import ExecutionService
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.studio_server import StudioApplication
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
BOX = {'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'body', 'filter': 'box'}], 'output': 'body'}


def spec():
    return {'document': BOX, 'objective': 'Future box', 'allowedProviders': ['freecad'],
            'trigger': {'kind': 'once', 'at': (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}}


class SchedulingEntrypoints(unittest.TestCase):
    def test_agent_registration_survives_disconnect_without_starting_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            with ExecutionService(directory) as service:
                created = dispatch(service, {'id': 1, 'method': 'schedule_create', 'params': {'spec': spec()}})
                methods = dispatch(service, {'id': 2, 'method': 'methods'})
                self.assertIn('schedule_create', methods['methods'])
            with ExecutionService(directory) as service:
                saved = service.schedule_get(created['id'])
                self.assertEqual(saved['status'], 'active')
                self.assertEqual(saved['occurrences'], [])
                paused = service.schedule_pause(saved['id'], saved['revision'])
                self.assertEqual(paused['status'], 'paused')
            self.assertFalse((Path(directory)/'schedules'/'scheduler-owner.lock').exists())

    def test_cli_preview_and_revision_checked_control(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory)/'schedule.json'
            filename.write_text(json.dumps(spec()))
            def cli(*args):
                return subprocess.run([sys.executable, '-m', 'schemaxis', 'schedule', '--workspace', directory, *args],
                                      capture_output=True, text=True, timeout=30,
                                      env={**os.environ, 'PYTHONPATH': str(ROOT/'src')}, cwd=ROOT)
            preview = cli('preview', str(filename))
            self.assertEqual(preview.returncode, 0, preview.stdout+preview.stderr)
            self.assertEqual(len(json.loads(preview.stdout)['upcoming']), 1)
            created = cli('create', str(filename))
            self.assertEqual(created.returncode, 0, created.stdout+created.stderr)
            record = json.loads(created.stdout)
            paused = cli('pause', record['id'], '--revision', str(record['revision']))
            self.assertEqual(paused.returncode, 0, paused.stdout+paused.stderr)
            stale = cli('resume', record['id'], '--revision', str(record['revision']))
            self.assertEqual(stale.returncode, 1)
            self.assertEqual(json.loads(stale.stdout)['fault']['code'], 'STALE_REVISION')

    def test_studio_captures_saved_revision_and_rejects_stale_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            session = AdaptorConsoleSession(directory, provider='freecad')
            app = StudioApplication(session)
            try:
                session.edit_source(json.dumps(BOX), session.active_document, session._record['revision'])
                revision = session._record['revision']
                declaration = spec()
                declaration.pop('document')
                declaration.pop('allowedProviders')
                created = app.schedule_request({'action': 'create', 'spec': declaration,
                    'document': session.active_document, 'documentRevision': revision})
                self.assertEqual(created['spec']['document'], BOX)
                self.assertEqual(created['spec']['allowedProviders'], ['freecad'])
                with self.assertRaises(SchemaxisError) as caught:
                    app.schedule_request({'action': 'create', 'spec': declaration,
                        'document': session.active_document, 'documentRevision': revision-1})
                self.assertEqual(caught.exception.fault.code, 'STALE_REVISION')
            finally:
                app.close()
                session.close()
