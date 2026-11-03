# Copyright (C) 2026 David L F Gaden
"""The CLI and local service bind the same captured template revision."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.agent_transport import dispatch
from schemaxis.core.faults import SchemaxisError
from schemaxis.execution_service import ExecutionService
from schemaxis.storage import load
from schemaxis.workflow import inspect_plan
from schemaxis.workflow_templates import load_template, prepare_template


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / 'docs/design/workflow-templates/examples/reentrant'


class TemplateEntrypointTests(unittest.TestCase):
    def cli(self, *args, input=None):
        result = subprocess.run([sys.executable, '-m', 'schemaxis', *map(str, args)],
                                input=input, text=True, capture_output=True, cwd=ROOT,
                                env={**os.environ, 'PYTHONPATH': str(ROOT/'src')}, timeout=30)
        return result, json.loads(result.stdout)

    def test_cli_service_and_transport_agree_for_both_cases(self):
        with tempfile.TemporaryDirectory() as temporary, ExecutionService(temporary) as service:
            for name in ('small', 'tall'):
                filename = EXAMPLE / ('values-' + name + '.json')
                values = load(filename.read_text())
                result, bound = self.cli('template', 'bind', EXAMPLE/'template.json', '--values', filename)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                native_calls = ('schemaxis.execution_service.registry.run', 'schemaxis.workflow.execute')
                with patch(native_calls[0], side_effect=AssertionError('native execution')), \
                        patch(native_calls[1], side_effect=AssertionError('native execution')):
                    response = dispatch(service, {'id': 1, 'method': 'prepare_template', 'params': {
                        'filename': str(EXAMPLE/'template.json'), 'values': values}})
                self.assertEqual(bound, response)
                self.assertEqual(bound['values']['height'], 5 if name == 'small' else 7)

    def test_plan_agrees_with_ordinary_workflow_and_service(self):
        values = load((EXAMPLE/'values-small.json').read_text())
        result, prepared = self.cli('template', 'plan', EXAMPLE/'template.json', '--values', '-',
                                    input=json.dumps(values))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(prepared['plan'], inspect_plan(prepared['document']))
        with tempfile.TemporaryDirectory() as temporary, ExecutionService(temporary) as service:
            self.assertEqual(prepared, service.prepare_template(str(EXAMPLE/'template.json'), values, True))
            self.assertEqual(service.state['plans'], {})
            self.assertEqual(service.state['jobs'], {})

    def test_inspect_and_document_only_are_useful_cli_documents(self):
        result, bundle = self.cli('template', 'inspect', EXAMPLE/'template.json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(bundle, load_template(EXAMPLE/'template.json'))
        values = load((EXAMPLE/'values-small.json').read_text())
        result, body = self.cli('template', 'bind', EXAMPLE/'template.json', '--values', '-',
                                '--document-only', input=json.dumps(values))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(body, prepare_template(EXAMPLE/'template.json', values)['document'])
        self.assertEqual(body['version'], 'schemaxis.workflow/1')

    def test_invalid_values_fail_without_creating_service_plans(self):
        values = load((EXAMPLE/'values-small.json').read_text())
        values['template']['revision'] += 1
        result, response = self.cli('template', 'bind', EXAMPLE/'template.json', '--values', '-',
                                    input=json.dumps(values))
        self.assertEqual(result.returncode, 1)
        self.assertIn('fault', response)
        with tempfile.TemporaryDirectory() as temporary, ExecutionService(temporary) as service:
            before = copy.deepcopy(service.state)
            with self.assertRaises(SchemaxisError):
                service.prepare_template(str(EXAMPLE/'template.json'), values)
            self.assertEqual(before, service.state)

    def test_duplicate_case_keys_produce_a_structured_fault(self):
        result, response = self.cli('template', 'bind', EXAMPLE/'template.json', '--values', '-',
                                    input='{"values":{},"values":{}}')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(response['fault']['code'], 'INVALID_DOCUMENT')

    def test_deep_case_json_produces_a_structured_fault(self):
        result, response = self.cli('template', 'bind', EXAMPLE/'template.json', '--values', '-',
                                    input='[' * 2000 + '0' + ']' * 2000)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(response['fault']['code'], 'INVALID_DOCUMENT')
        self.assertNotIn('Traceback', result.stderr)

    def test_closed_service_and_invalid_planning_flag_are_rejected(self):
        values = load((EXAMPLE/'values-small.json').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            service = ExecutionService(temporary)
            try:
                with self.assertRaises(SchemaxisError):
                    service.prepare_template(str(EXAMPLE/'template.json'), values, 'true')
            finally:
                service.close()
            with self.assertRaises(SchemaxisError):
                service.prepare_template(str(EXAMPLE/'template.json'), values)


if __name__ == '__main__':
    unittest.main()
