# Copyright (C) 2026 David L. F. Gaden.
"""Source-time validation reaches execution without hiding authoring faults (host)."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.core.faults import SchemaxisError
from schemaxis.studio_server import StudioApplication
from schemaxis.adaptors import registry


CAR = Path(__file__).resolve().parents[2] / 'examples/paraview-car/input.json'


class SourceTimes(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.session = AdaptorConsoleSession(folder.name, provider='paraview')
        self.addCleanup(self.session.close)
        self.app = StudioApplication(self.session)
        self.addCleanup(self.app.close)
        self.car = json.loads(CAR.read_text())

    def validate(self, document):
        with patch('subprocess.Popen', side_effect=AssertionError('host validation cannot launch applications')):
            return self.app.validate_source({'provider': 'paraview', 'source': json.dumps(document)})

    def test_car_is_checked_and_deferred_but_cli_plan_still_requires_inspection(self):
        before = copy.deepcopy(self.car)
        checked = self.validate(self.car)
        self.assertTrue(checked['valid'], checked)
        self.assertEqual(checked['diagnostics'], [])
        self.assertEqual(checked['validation']['code'], 'TIME_INSPECTION_REQUIRED')
        self.assertTrue(checked['validation']['deferred'])
        self.assertEqual(self.car, before)
        with self.assertRaises(SchemaxisError) as caught:
            registry.plan(self.car)
        self.assertEqual(caught.exception.fault.code, 'TIME_INSPECTION_REQUIRED')

    def test_publish_and_both_console_preflights_reach_run_with_authored_times(self):
        self.session._edit(self.car)
        self.session.configure('paraview', Path(CAR).parent)
        class ReachedRun(Exception):
            pass
        with patch.object(self.session, '_run', side_effect=ReachedRun) as run:
            with self.assertRaises(ReachedRun):
                self.session.preview()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], self.car)

    def test_reader_only_draft_can_be_edited_but_cannot_run_without_publications(self):
        document = {'version': 'schemaxis/1', 'nodes': [{'id': 'case', 'filter': 'foam',
                    'options': {'file': 'case.foam'}}], 'scenes': [],
                    'times': {'source': 'case', 'select': 'latest'}}
        self.assertTrue((checked := self.validate(document))['valid'], checked)
        self.session._edit(document)
        with self.assertRaises(SchemaxisError) as caught:
            self.session.preview()
        self.assertEqual(caught.exception.fault.code, 'EMPTY_PUBLICATION')

    def test_structural_expression_and_time_request_faults_still_block(self):
        variants = []
        for field, value in [('filter', 'missingFilter'), ('inputs', {'unexpected': 'case'})]:
            doc = copy.deepcopy(self.car)
            doc['nodes'][-1][field] = value
            variants.append(doc)
        for value in ['missingName + 1', 'vector(']:
            doc = copy.deepcopy(self.car)
            doc['definitions']['wake'] = {'$expr': value}
            variants.append(doc)
        for times in [{'source': 'missing', 'select': 'latest'},
                      {'source': 'case', 'select': {}},
                      {'source': 'case', 'select': {'latest': 1, 'first': 1}},
                      {'source': 'case', 'select': {'latest': 0}}]:
            doc = copy.deepcopy(self.car)
            doc['times'] = times
            variants.append(doc)
        for doc in variants:
            with self.subTest(document=doc):
                checked = self.validate(doc)
                self.assertFalse(checked['valid'], checked)
                self.assertNotEqual(checked['diagnostics'][0]['code'], 'TIME_INSPECTION_REQUIRED')

    def test_explicit_time_is_a_complete_plan_and_study_checks_every_combination(self):
        self.car['times'] = [1]
        self.assertTrue((checked := self.validate(self.car))['valid'], checked)
        self.car['times'] = {'source': 'case', 'select': 'latest'}
        self.car['settings']['unusedStudyValue'] = {'$analytic': {'type': 'values', 'values': [1, 2]}}
        self.assertTrue((checked := self.validate(self.car))['valid'], checked)
        self.car['settings']['case'] = {'$analytic': {'type': 'values', 'values': ['case.foam', '']}}
        self.assertFalse(self.validate(self.car)['valid'])


if __name__ == '__main__':
    unittest.main()
