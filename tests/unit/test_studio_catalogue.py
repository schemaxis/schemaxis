# Copyright (C) 2026 David L F Gaden
"""One generated contract test covers every packaged Studio library entry."""
from pathlib import Path
import unittest
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis import workflow
from schemaxis.core.faults import SchemaxisError
from schemaxis.studio_library import instantiate_item, load_library, plan_item
from schemaxis.unfilled import find_unfilled


class StudioCatalogueTests(unittest.TestCase):
    def test_workflow_validation_requires_explicit_draft_mode_for_markers(self):
        body = {'version': 'schemaxis.workflow/1', 'settings': {'start': {'$fill': 'start'}},
                'operations': [{'id': 'series', 'document': {'version': 'schemaxis.octave/1',
                    'nodes': [{'id': 'data', 'filter': 'sequence', 'options': {
                        'start': {'$document': '/settings/start', 'scope': 'workflow'},
                        'stop': {'$fill': 'stop', 'label': 'Upper bound', 'type': 'number'}, 'count': 5}}],
                    'outputs': ['data']}}]}
        with self.assertRaises(SchemaxisError) as caught:
            workflow.validate(body)
        self.assertEqual(caught.exception.fault.code, 'UNFILLED_VALUES')
        self.assertEqual(caught.exception.fault.observed['pointers'],
                         ['/settings/start', '/operations/0/document/nodes/0/options/stop'])
        operations = workflow.validate(body, allow_unfilled=True)
        self.assertEqual(operations[0]['document']['nodes'][0]['options']['start'], {'$fill': 'start'})

    def test_every_packaged_entry_plans_and_reports_all_unfilled_pointers(self):
        root = Path(registry.__file__).parent
        providers = [p.name for p in root.iterdir() if (p / 'studio.json').is_file()]
        self.assertTrue(providers)
        with patch('subprocess.Popen', side_effect=AssertionError('catalogue must be host-only')):
            for provider in sorted(providers):
                library = load_library(provider)
                for group in ('templates', 'snippets'):
                    for item in library.get(group, []):
                        with self.subTest(provider=provider, kind=group, item=item['id']):
                            plan_item(instantiate_item(library, item, provider=provider))
                            draft = instantiate_item(library, item, provider=provider, filled=False)
                            expected = find_unfilled(draft)
                            if not expected:
                                continue
                            with self.assertRaises(SchemaxisError) as caught:
                                plan_item(draft)
                            self.assertEqual(caught.exception.fault.code, 'UNFILLED_VALUES')
                            observed = caught.exception.fault.to_dict()['observed']
                            self.assertEqual(observed['values'], expected)
                            self.assertEqual(observed['pointers'], [v['pointer'] for v in expected])
