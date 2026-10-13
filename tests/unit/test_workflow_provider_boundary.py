"""Unsupported standalone providers must never fall through to ParaView."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.core.faults import SchemaxisError
from schemaxis import parallel, workflow


class WorkflowProviderBoundaryTests(unittest.TestCase):
    def document(self, version):
        return {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'standalone', 'document': {'version': version, 'nodes': []}}]}

    def test_explicit_provider_fault_in_validation_and_planning(self):
        versions = ('schemaxis.unknown/1', None, [], {})
        for version in versions:
            for check in (workflow.validate, workflow.inspect_plan, parallel.work_items):
                with self.subTest(version=version, check=check.__name__):
                    document = self.document(version)
                    original = copy.deepcopy(document)
                    with self.assertRaises(SchemaxisError) as caught:
                        check(document)
                    self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_PROVIDER')
                    self.assertEqual(caught.exception.fault.location, 'standalone.document.version')
                    self.assertEqual(document, original)

    def test_execution_rejects_before_output_or_native_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'must-not-exist'
            with patch('schemaxis.workflow.run') as pv, patch('schemaxis.parallel.run_native') as native:
                for version in ('schemaxis.unknown/1',):
                    for mode in ('serial', 'scheduled', 'resume', 'mixed'):
                        with self.subTest(version=version, mode=mode):
                            document = self.document(version)
                            if mode == 'scheduled': document['execution'] = {'maxWorkers': 1}
                            if mode == 'mixed':
                                document['operations'].insert(0, {'id': 'cad', 'document': {
                                    'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'box', 'filter': 'box'}],
                                    'output': 'box'}})
                            with self.assertRaises(SchemaxisError) as caught:
                                workflow.execute(document, output, resume=mode == 'resume')
                            self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_PROVIDER')
                            self.assertFalse(output.exists())
                pv.assert_not_called()
                native.assert_not_called()

    def test_existing_workflow_versions_are_unchanged(self):
        for version in ('schemaxis/1', 'schemaxis.freecad/1', 'schemaxis.blender/1', 'schemaxis.blender.render/1', 'schemaxis.godot/1', 'schemaxis.aseprite/1'):
            document = self.document(version)
            self.assertEqual(workflow.validate(document), document['operations'])

    def test_missing_version_retains_legacy_validation_path(self):
        document = self.document('schemaxis/1')
        document['operations'][0]['document'] = {}
        self.assertEqual(workflow.validate(document), document['operations'])

    def test_dependency_errors_retain_precedence(self):
        document = self.document('schemaxis.godot/1')
        document['operations'][0]['document']['nodes'] = [{'options': {'file': {'$artifact': 'absent', 'index': 0}}}]
        with self.assertRaises(SchemaxisError) as caught:
            workflow.validate(document)
        self.assertEqual(caught.exception.fault.code, 'UNAVAILABLE_OPERATION')


if __name__ == '__main__':
    unittest.main()
