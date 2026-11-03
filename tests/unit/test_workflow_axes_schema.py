# Copyright (C) 2026 David L F Gaden
"""The workflow/1 authored schema gives study axes the same structured shape as adaptor documents."""
import json
import unittest
from pathlib import Path

from schemaxis.schema_authoring import version_schema

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None

ROOT = Path(__file__).resolve().parents[2]
BOX = json.loads((ROOT / 'examples/schemaxis/gmsh-minimal.json').read_text())
BASE = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'one', 'document': BOX}]}


class WorkflowAxesSchemaTests(unittest.TestCase):
    def test_axes_items_are_structured_like_adaptor_documents(self):
        schema = version_schema('schemaxis.workflow/1', authored=True)
        item = schema['properties']['axes']['items']
        self.assertEqual(item['required'], ['name'])
        self.assertEqual(set(item['properties']), {'name', 'values', 'series'})
        self.assertFalse(item['additionalProperties'])
        self.assertEqual(item['properties']['values']['minItems'], 1)
        adaptor = version_schema(BOX['version'], authored=True)['properties']['axes']['items']
        self.assertEqual(item, adaptor)

    @unittest.skipIf(Draft202012Validator is None, 'jsonschema is not installed')
    def test_accepts_runtime_forms_and_rejects_malformed_axes(self):
        validator = Draft202012Validator(version_schema('schemaxis.workflow/1', authored=True))
        for axis in ({'name': 'h', 'values': [1, 2]},
                     {'name': 'h', 'values': [[0, 0, 0], {'a': {'$axis': 'x'}}]},
                     {'name': 'h', 'series': {'start': 0, 'end': 1, 'count': 3}},
                     {'name': 'h', 'series': {'start': {'$document': '/dimensions/a', 'scope': 'workflow'},
                                              'end': 1, 'count': 3}}):
            self.assertTrue(validator.is_valid({**BASE, 'axes': [axis]}), axis)
        for axis in ({'values': [1]}, {'name': 'h', 'values': []}, {'name': 'h', 'extra': 1},
                     {'name': 'h', 'values': 3}, 'h', {'$expr': 1},
                     {'name': 'h', 'values': [1], 'series': {'count': 1}}, {'name': 'h'}):
            self.assertFalse(validator.is_valid({**BASE, 'axes': [axis]}), axis)
