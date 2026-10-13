import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from schemaxis.core.catalogue import Catalogue
from schemaxis.core.executor import Executor
from schemaxis.core.extensions import ExtensionRecord, ExtensionRegistry
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.planner import Planner
from schemaxis.adaptors.paraview.mvp.slice_export import SliceExport

PACKAGE = Path(__file__).resolve().parents[2] / 'src/schemaxis/adaptors/paraview/mvp'


class CapabilityDeclarationTests(unittest.TestCase):
    def test_export_equals_static_manifest_and_can_be_planned(self):
        catalogue = Catalogue.from_roots([PACKAGE])
        record = catalogue.describe('paraview.slice_export')
        self.assertEqual(record.document, SliceExport.describe())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'manifest.json'
            SliceExport.export_manifest(path)
            self.assertEqual(json.loads(path.read_text()), record.document)
        plan = Planner(catalogue).resolve({'documentVersion': 'schemaxis.workflow/0.1', 'steps': [
            {'id': 'slice', 'use': record.id, 'arguments': {'outputDirectory': 'new-output'}}]})
        self.assertEqual(plan.to_dict()['nodes'][0]['arguments']['normal'], [1, 0, 0])

    def test_discovery_does_not_import_provider_or_paraview(self):
        source = f'''import sys
from schemaxis.core.catalogue import Catalogue
catalogue = Catalogue.from_roots([{str(PACKAGE)!r}])
assert len(catalogue) == 1
assert not any(name == 'paraview' or name.startswith('paraview.') or name.startswith('schemaxis.adaptors.paraview.mvp') for name in sys.modules)
'''
        subprocess.run([sys.executable, '-c', source], check=True)

    def test_cli_and_document_share_dictionary_and_configuration_hook(self):
        registry = ExtensionRegistry([ExtensionRecord(
            'paraview.slice_export', 'schemaxis.adaptors.paraview.mvp.slice_export:SliceExport', PACKAGE / 'package.json')])
        document = registry.configure_document('paraview.slice_export', {
            'normal': [0, 3, 4], 'outputDirectory': 'result'})
        cli = registry.configure_cli('paraview.slice_export', [
            '--paraview.slice_export.normal', '[0,3,4]',
            '--paraview.slice_export.outputDirectory', 'result'])
        self.assertEqual(document.config, cli.config)
        self.assertEqual(cli.normal, [0, 0.6, 0.8])

    def test_drift_is_rejected(self):
        document = SliceExport.describe()
        document['arguments']['normal']['default'] = [0, 0, 1]
        with self.assertRaises(SchemaxisError) as caught:
            SliceExport.check_manifest(document)
        self.assertEqual(caught.exception.fault.code, 'DECLARATION_MISMATCH')

    def test_zero_normal_fails_before_application_or_writes(self):
        catalogue = Catalogue.from_roots([PACKAGE])
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'result'
            plan = Planner(catalogue).resolve({'documentVersion': 'schemaxis.workflow/0.1', 'steps': [
                {'id': 'slice', 'use': 'paraview.slice_export', 'arguments': {
                    'normal': [0, 0, 0], 'outputDirectory': str(directory)}}]})
            result = Executor(catalogue).execute(plan.to_dict())
            self.assertEqual(result.faults[0].code, 'INVALID_NORMAL')
            self.assertFalse(directory.exists())

    def test_invalid_sweep_fails_before_application_or_output_creation(self):
        catalogue = Catalogue.from_roots([PACKAGE])
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'result'
            for sweep, code in (({'start': 0, 'spacing': 1, 'count': 10**12}, 'EXPANSION_TOO_LARGE'),
                                ({'spacing': 1}, 'UNDER_SPECIFIED_SERIES')):
                with self.subTest(sweep=sweep):
                    plan = Planner(catalogue).resolve({'documentVersion': 'schemaxis.workflow/0.1', 'steps': [
                        {'id': 'slice', 'use': 'paraview.slice_export', 'arguments': {
                            'sweep': sweep, 'outputDirectory': str(directory)}}]})
                    result = Executor(catalogue).execute(plan.to_dict())
                    self.assertEqual(result.faults[0].code, code)
                    self.assertFalse(directory.exists())

    def test_existing_directory_is_never_overwritten(self):
        operation = SliceExport()
        with tempfile.TemporaryDirectory() as temporary:
            operation.configure({'normal': [1, 0, 0], 'outputDirectory': temporary})
            with self.assertRaises(SchemaxisError) as caught:
                operation.run()
            self.assertEqual(caught.exception.fault.code, 'OUTPUT_EXISTS')


if __name__ == '__main__':
    unittest.main()
