# Copyright (C) 2026 David L F Gaden
"""Optional grouped export preserves the exact standalone schema contract."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.paraview.schema_bundle import ENTRY, GROUPS, _closure, read, schemas, write
from schemaxis.core.faults import SchemaxisError
from schemaxis.schema import expand_input, export_schema

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None
try:
    from referencing import Registry, Resource
except ImportError:
    Registry = None

ROOT = Path(__file__).resolve().parents[2]
BASE = 'https://offline.invalid/paraview/'


def unbundle(documents):
    """Undo only the storage layout, proving every original constraint is retained."""
    root = copy.deepcopy(documents[ENTRY])
    def restore(value):
        if not isinstance(value, dict):
            return value
        reference = value.get('$ref', '')
        member, _, fragment = reference.partition('#')
        if member:
            key = fragment[len('/$defs/'):]
            if key.startswith(('node-', 'inline-', 'export-')) or key == 'scene':
                return restore(documents[member]['$defs'][key])
        result = copy.deepcopy(value)
        if '.schema.json#' in reference:
            result['$ref'] = '#' + reference.split('#', 1)[1]
        for key in ('properties', '$defs', 'patternProperties'):
            if key in result:
                result[key] = {name: restore(child) for name, child in result[key].items()}
        for key in ('items', 'additionalProperties', 'not', 'if', 'then', 'else', 'contains'):
            if isinstance(result.get(key), dict):
                result[key] = restore(result[key])
        for key in ('oneOf', 'anyOf', 'allOf', 'prefixItems'):
            if key in result:
                result[key] = [restore(child) for child in result[key]]
        return result
    root['$defs'] = {key: value for group in GROUPS
                     for key, value in documents[group + '.schema.json']['$defs'].items()
                     if key not in ('nodes', 'exports', 'scene') and not key.startswith(('node-', 'inline-', 'export-'))
                     and not (set(value) == {'$ref'} and '.schema.json#' in value['$ref'])}
    return restore(root)


class ParaViewSchemaBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundles = {authored: schemas(authored=authored) for authored in (False, True)}

    def test_reassembled_bundles_equal_every_original_constraint(self):
        for authored, documents in self.bundles.items():
            with self.subTest(authored=authored):
                _closure(documents)
                self.assertEqual(unbundle(documents), export_schema('paraview', authored=authored))

    def test_literal_reference_keys_in_annotations_are_preserved(self):
        original = export_schema('paraview', authored=True)
        original['$defs']['json']['default'] = {'$ref': 'literal'}
        original['$defs']['json']['x-example'] = {'$ref': 'filters.schema.json#/$defs/example'}
        original['properties']['maxStates'] = {'$ref': '#/$defs/json/anyOf/0'}
        with patch('schemaxis.adaptors.paraview.schema_bundle.export_schema', return_value=original):
            documents = schemas(authored=True)
        _closure(documents)
        self.assertEqual(unbundle(documents), original)

    def test_malformed_reference_and_schema_children_are_structured_faults(self):
        for node in ({'$ref': 42}, {'properties': []}):
            documents = copy.deepcopy(self.bundles[False])
            documents[ENTRY]['properties']['nodes'] = node
            with self.subTest(node=node), self.assertRaises(SchemaxisError) as caught:
                _closure(documents)
            self.assertEqual(caught.exception.fault.code, 'INVALID_SCHEMA_BUNDLE')

    def test_atomic_hash_manifest_relocation_missing_tampered_and_broken_references(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('schemaxis.adaptors.paraview.schema_bundle.schemas', return_value=self.bundles[True]):
                write(root/'first')
            shutil.copytree(root/'first', root/'moved')
            shutil.rmtree(root/'first')
            self.assertEqual(read(root/'moved'), self.bundles[True])
            common = root/'moved/common.schema.json'
            payload = common.read_bytes()
            common.unlink()
            with self.assertRaises(SchemaxisError):
                read(root/'moved')
            common.write_bytes(payload + b' ')
            with self.assertRaises(SchemaxisError):
                read(root/'moved')
            common.write_bytes(payload)
            entry = root/'moved'/ENTRY
            document = json.loads(entry.read_bytes())
            document['properties']['nodes'] = {'$ref': 'common.schema.json#/$defs/does-not-exist'}
            changed = json.dumps(document).encode('utf-8')
            entry.write_bytes(changed)
            manifest_path = root/'moved/bundle.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['files'][ENTRY] = {'sha256': hashlib.sha256(changed).hexdigest(), 'bytes': len(changed)}
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaises(SchemaxisError):
                read(root/'moved')  # Closure checked even when bytes match manifest.

    @unittest.skipIf(Draft202012Validator is None, 'optional jsonschema developer package unavailable')
    def test_full_document_and_category_entry_points_validate_offline(self):
        def never_fetch(uri):
            raise AssertionError('network resolution is prohibited: ' + uri)
        for authored, documents in self.bundles.items():
            resources = {name: {**document, '$id': BASE + name} for name, document in documents.items()}
            if Registry is not None:
                registry = Registry(retrieve=never_fetch).with_resources(
                    (BASE + name, Resource.from_contents(document)) for name, document in resources.items())
                validators = {name: Draft202012Validator(document, registry=registry) for name, document in resources.items()}
            else:
                from jsonschema import RefResolver
                validators = {name: Draft202012Validator(document, resolver=RefResolver(
                    base_uri=BASE + name, referrer=document,
                    store={BASE + member: value for member, value in resources.items()},
                    handlers={'http': never_fetch, 'https': never_fetch, 'file': never_fetch}))
                    for name, document in resources.items()}
            standalone = Draft202012Validator(export_schema('paraview', authored=authored))
            paths = sorted((ROOT/'examples/schemaxis').glob('paraview-*.json'))
            paths += [ROOT/'examples/schemaxis/showcase.json']
            checked = 0
            for path in paths:
                document = json.loads(path.read_text())
                if document.get('version') != 'schemaxis/1':
                    continue
                document = document if authored else expand_input(document)
                with self.subTest(authored=authored, example=path.name):
                    self.assertEqual(validators[ENTRY].is_valid(document), standalone.is_valid(document))
                checked += 1
            self.assertGreater(checked, 10)
            valid = {'version': 'schemaxis/1', 'nodes': [{'id': 's', 'filter': 'sphere'}], 'scenes': [{'id': 'out'}]}
            for change in ({'extra': 1}, {'nodes': [{'id': 's', 'filter': 'unregistered'}]},
                           {'nodes': [{'id': 's', 'filter': 'sphere', 'options': {'radius': 0}}]}):
                document = {**valid, **change}
                self.assertFalse(standalone.is_valid(document))
                self.assertFalse(validators[ENTRY].is_valid(document))
            self.assertTrue(validators['filters.schema.json'].is_valid(valid['nodes'][0]))
            self.assertFalse(validators['readers.schema.json'].is_valid(valid['nodes'][0]))
            self.assertTrue(validators['readers.schema.json'].is_valid({'id': 'foam', 'filter': 'foam', 'options': {'file': 'case.foam'}}))
            self.assertTrue(validators['rendering.schema.json'].is_valid(valid['scenes'][0]))
            self.assertFalse(validators['rendering.schema.json'].is_valid({'id': 'out', 'unknown': True}))
            self.assertTrue(validators['writers.schema.json'].is_valid({'id': 'out', 'node': 's', 'writer': 'pvWriteCSVWriter'}))
            self.assertFalse(validators['writers.schema.json'].is_valid(valid['nodes'][0]))
