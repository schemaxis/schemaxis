# Copyright (C) 2026 David L F Gaden
"""The library contract is strict, confined and backward compatible."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis.core.faults import SchemaxisError
from schemaxis.studio_library import (VERSION, apply_inserts, fill_fields, instantiate_item,
                                     load_library, validate_library)


class StudioLibraryTests(unittest.TestCase):
    def library(self):
        return {'version': VERSION, 'categories': [{'id': 'nodes', 'title': 'Nodes'}], 'snippets': [{
            'id': 'box', 'title': 'Box', 'category': 'nodes', 'fields': {
                'size': {'label': 'Size', 'type': 'number', 'minimum': 1},
                'prefix': {'label': 'Prefix', 'type': 'id', 'default': 'box'}},
            'testValues': {'size': 3}, 'baseDocument': {'nodes': []}, 'inserts': [
                {'at': '/nodes/-', 'values': [{'id': '${prefix}A', 'size': {'$fill': 'size'}}]}]}]}

    def test_fields_and_interpolation(self):
        library = validate_library(self.library())
        item = library['snippets'][0]
        result = instantiate_item(library, item)
        self.assertEqual(result, {'nodes': [{'id': 'boxA', 'size': 3}]})
        draft = instantiate_item(library, item, filled=False)
        self.assertEqual(draft['nodes'][0]['id']['template'], '${prefix}A')
        self.assertEqual(draft['nodes'][0]['size']['label'], 'Size')
        self.assertEqual(item['inserts'][0]['values'][0]['size'], {'$fill': 'size'})

    def test_reject_invalid_contract(self):
        mutations = [lambda d: d.update(unknown=True),
                     lambda d: d['snippets'][0].update(category='missing'),
                     lambda d: d['snippets'][0]['fields']['prefix'].update(type='string'),
                     lambda d: d['snippets'][0]['testValues'].update(size=0),
                     lambda d: d['snippets'][0]['inserts'][0].update(merge={}),
                     lambda d: d['snippets'][0]['inserts'][0].update(at='/bad~2'),
                     lambda d: d['snippets'][0]['inserts'][0]['values'][0].update(size={'$fill': 'missing'}),
                     lambda d: d['snippets'].append(copy.deepcopy(d['snippets'][0]))]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                data = self.library()
                mutate(data)
                with self.assertRaises(SchemaxisError) as caught:
                    validate_library(data)
                self.assertEqual(caught.exception.fault.code, 'INVALID_STUDIO_LIBRARY')

    def test_typed_constraints_and_cursor_fixture(self):
        for kind, default in [('enum', True), ('number', float('inf')), ('colour', [1, 0, 0, 1]),
                              ('colour', [2, 0, 0]), ('bounds', [1, 0, 0, 1, 0, 1])]:
            data = self.library()
            data['snippets'][0]['fields']['size'] = {'type': kind, 'label': 'Value', 'default': default}
            if kind == 'enum':
                data['snippets'][0]['fields']['size']['values'] = [1]
            with self.subTest(kind=kind, default=default), self.assertRaises(SchemaxisError):
                validate_library(data)
        data = self.library()
        item = data['snippets'][0]
        item.update(testCursor='/height', baseDocument={'height': 0},
                    inserts=[{'at': '@cursor', 'values': [{'$fill': 'size'}]}])
        self.assertEqual(instantiate_item(validate_library(data), item), {'height': 3})
        item.pop('testCursor')
        with self.assertRaises(SchemaxisError):
            validate_library(data)

    def test_legacy_migration_and_confined_template_path(self):
        library = load_library('paraview')
        self.assertEqual(library['version'], VERSION)
        self.assertIn('inserts', library['snippets'][0])
        self.assertIn('fields', library['snippets'][0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in ('../outside.json', '/tmp/outside.json', 'sub/../../outside.json'):
                (root / 'studio.json').write_text(json.dumps({'version': VERSION, 'templates': [
                    {'id': 'bad', 'title': 'Bad', 'file': filename}]}))
                with self.assertRaises(SchemaxisError):
                    load_library('ignored', root)

    def test_cursor_replaces_array_value_without_shifting_siblings(self):
        source = {'nodes': [{'id': 'source'}, {'id': 'target'}], 'values': [1, 2, 3]}
        changed = apply_inserts(source, [{'at': '@cursor', 'values': [42]}], cursor='/values/1')
        self.assertEqual(changed['values'], [1, 42, 3])
        self.assertEqual(source['values'], [1, 2, 3])
        node = apply_inserts(source, [{'at': '@cursor', 'values': [{'id': 'replacement'}]}], cursor='/nodes/1')
        self.assertEqual(node['nodes'], [{'id': 'source'}, {'id': 'replacement'}])
        inserted = apply_inserts(source, [{'at': '/values/1', 'values': [42]}])
        self.assertEqual(inserted['values'], [1, 42, 2, 3])

    def test_identifier_defaults_follow_fill_controller_contract(self):
        for value in ('_hidden', 'dotted.name'):
            data = self.library()
            data['snippets'][0]['fields']['prefix']['default'] = value
            with self.subTest(value=value), self.assertRaises(SchemaxisError):
                validate_library(data)

    def test_ordered_inserts_create_containers_and_merge(self):
        before = {'scenes': [{'visible': {'source': {'colour': 'red', 'opacity': 1}}}]}
        result = apply_inserts(before, [
            {'at': '/axes/-', 'values': [{'name': 'x', 'values': [1]}]},
            {'at': '/scenes/0/visible', 'merge': {'source': {'opacity': 0.5}, 'cut': {}}}])
        self.assertEqual(result['scenes'][0]['visible']['source'], {'colour': 'red', 'opacity': 0.5})
        self.assertEqual(result['axes'][0]['name'], 'x')
        self.assertNotIn('axes', before)
        self.assertEqual(fill_fields({'$fill': 'x'}, {'x': {'label': 'X', 'type': 'json'}}, {'x': None}), None)
