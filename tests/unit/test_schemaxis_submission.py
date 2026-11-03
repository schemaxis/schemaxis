# Copyright (C) 2026 David L F Gaden
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.job import run


class SubmissionTests(unittest.TestCase):
    def test_timeout_records_failed_host_result_and_preserves_authored_references(self):
        document = {'version': 'schemaxis/1', 'definitions': {'radius': 2},
                    'nodes': [{'id': 's', 'filter': 'sphere', 'options': {'radius': {'$document': '/definitions/radius'}}}],
                    'scenes': [{'id': 's', 'geometry': ['s']}]}
        failure = SchemaxisError(Fault('RUNNER_TIMED_OUT', 'test timeout', '$', 'submission'))
        with tempfile.TemporaryDirectory() as parent:
            directory = Path(parent) / 'run'
            with patch('schemaxis.job.require_paraview', return_value=object()), patch('schemaxis.job.SubprocessRunner') as runner:
                runner.return_value.side_effect = failure
                with self.assertRaises(SchemaxisError):
                    run(document, directory)
            result = json.loads((directory / 'result.json').read_text())
            self.assertFalse(result['verified'])
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(json.loads((directory / 'authored.json').read_text()), document)
            self.assertEqual(json.loads((directory / 'input.json').read_text())['nodes'][0]['options']['radius'], 2)
            self.assertTrue(json.loads((directory / 'document-resolution.json').read_text()))
