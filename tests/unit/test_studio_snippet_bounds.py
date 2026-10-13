"""Snippet field limits must lie inside the limits of the schema option they fill.

The snippet field grammar has inclusive minimum and maximum only, so a field filling a
strictly positive option needs a positive minimum; otherwise the form accepts a value
that planning then rejects.
"""
import json
import math
from pathlib import Path
import unittest

from schemaxis.adaptors import registry

ROOT = Path(__file__).resolve().parents[2]
INF = math.inf


def snippets(app):
    return json.loads((ROOT / 'src/schemaxis/adaptors' / app / 'studio.json').read_text())['snippets']


def fills(value, found=None):
    """Yield (filter, option, field) for every option that is exactly a $fill marker."""
    if isinstance(value, dict):
        options = value.get('options')
        if 'filter' in value and isinstance(options, dict):
            for option, content in options.items():
                if isinstance(content, dict) and set(content) == {'$fill'}:
                    yield value['filter'], option, content['$fill']
        for item in value.values():
            yield from fills(item)
    elif isinstance(value, list):
        for item in value:
            yield from fills(item)


def lower_within(field, schema):
    """True when the field's minimum never admits a value below the schema's (exclusive-aware)."""
    low, smin = field.get('minimum', -INF), schema.get('minimum', -INF)
    return low > smin if schema.get('exclusiveMinimum') is True else low >= smin


def upper_within(field, schema):
    return field.get('maximum', INF) <= schema.get('maximum', INF)


class SnippetBoundsTests(unittest.TestCase):
    def test_freecad_snippet_fields_lie_within_the_option_they_fill(self):
        declarations = registry.declarations('freecad')
        checked = 0
        for snippet in snippets('freecad'):
            for filter_, option, name in fills(snippet['inserts']):
                field = snippet['fields'][name]
                schema = declarations[filter_]['options'][option]['value']
                if field['type'] != 'number' or not any(k in schema for k in ('minimum', 'maximum')):
                    continue
                checked += 1
                with self.subTest(snippet=snippet['id'], option=option):
                    self.assertTrue(lower_within(field, schema) and upper_within(field, schema), (field, schema))
        self.assertGreaterEqual(checked, 17)

    def test_ngspice_divider_field_matches_resistance_limits(self):
        divider = next(s for s in snippets('ngspice') if s['id'] == 'divider')
        field = divider['fields']['value']
        circuit = registry.declarations('ngspice')['dcSweep']['options']['circuit']['value']
        resistance = circuit['properties']['resistors']['items']['properties']['resistance']
        self.assertTrue(lower_within(field, resistance) and upper_within(field, resistance), (field, resistance))
        self.assertEqual(field['maximum'], resistance['maximum'])
