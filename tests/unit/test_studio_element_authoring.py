# Copyright (C) 2026 David L. F. Gaden.
"""Host-only authoring declarations remain separate from runtime schemas."""
import unittest
from unittest.mock import patch
from schemaxis.studio_catalogue import catalogue, validate_authoring, validate_authoring_schema
from schemaxis.studio_guidance import annotate, validate_record
from schemaxis.core.faults import SchemaxisError


class ElementAuthoring(unittest.TestCase):
    def test_reference_declaration_projects_without_native_processes(self):
        with patch('subprocess.Popen', side_effect=AssertionError('host only')):
            items = catalogue('paraview')['items']
        item = next(item for item in items if item.get('operation') == 'extractBlock')
        self.assertEqual(item['authoring']['instanceFields'], [
            {'path': '/options/selectors', 'label': 'Blocks', 'style': 'lastSegment'}])
        self.assertEqual(item['authoring']['naming'], {})
        self.assertEqual(item['authoring']['multiMode']['batchPath'], '/options/selectors')
        self.assertNotIn('authoring', item['schema'].get('properties', {}))
        threshold = next(item for item in items if item.get('operation') == 'threshold')
        self.assertEqual([field['path'] for field in threshold['authoring']['instanceFields']],
                         ['/options/lower', '/options/upper'])
        self.assertNotIn('batchPath', threshold['authoring']['multiMode'])

    def test_generated_filter_inputs_project_only_typed_pipeline_operations(self):
        result = catalogue('paraview')
        items = {item['operation']: item for item in result['items'] if item.get('operation')}
        self.assertEqual(items['pvAppendArcLength']['authoring']['instanceFields'],
                         [{'path': '/inputs/Input', 'label': 'Input'}])
        self.assertEqual([field['path'] for field in items['pvCellGridProbe']['authoring']['instanceFields']],
                         ['/inputs/Input', '/inputs/Source'])
        self.assertNotIn('authoringBasis', items['pvAnnotateTimeFilter'])
        self.assertNotIn('authoring', items['pvConduit'])

    def test_schema_nesting_failures_are_structured(self):
        from schemaxis.studio_catalogue import literal_schema
        from schemaxis.studio_guidance import enrich, fields
        deep = {'type': 'integer'}
        for _ in range(1000):
            deep = {'type': 'array', 'items': deep}
        for project in (lambda: literal_schema(deep), lambda: list(fields(deep)),
                        lambda: enrich(deep, 'paraview', 'schemaxis/1')):
            with self.assertRaises(SchemaxisError) as caught:
                project()
            self.assertEqual(caught.exception.fault.code, 'INVALID_STUDIO_SCHEMA')

    def test_invalid_policies_are_refused(self):
        for policy in ({'unknown': {}}, {'naming': {'path': '/id', 'style': 'literal'}},
                       {'multiMode': {'path': '/options/selectors', 'grouping': 'magic'}}):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                validate_authoring(policy)
        validate_record({'status': 'reviewed', 'explanation': 'Useful description.',
                         'authoring': {'naming': {'path': '/options/field', 'style': 'literal'}}})

    def test_ordered_instance_fields_and_optional_batch_selection(self):
        fields = [{'path': '/options/blocks', 'label': 'Blocks'}, {'path': '/options/assembly', 'label': 'Assembly'}]
        policy = {'instanceFields': fields, 'naming': {}, 'multiMode': {'rationale': 'Independent blocks'}}
        validate_authoring(policy)
        for invalid in ({**policy, 'instanceFields': fields * 2},
                        {**policy, 'multiMode': {'rationale': 'Independent blocks', 'batchPath': '/options/other'}}):
            with self.assertRaises(ValueError):
                validate_authoring(invalid)
        item = {'id': 'operation:example', 'at': '/nodes/-', 'authoring': policy,
                'schema': {'properties': {'id': {'type': 'string'}, 'options': {'properties': {
                    'blocks': {'type': 'array'}, 'assembly': {'type': 'string'}}}}}}
        validate_authoring_schema(item, {})
        policy['multiMode']['batchPath'] = '/options/assembly'
        validate_authoring(policy)
        with self.assertRaises(SchemaxisError):
            validate_authoring_schema(item, {})

    def test_unique_string_enumerations_project_a_subset_without_adaptor_rules(self):
        base = {'type': 'array', 'items': {'enum': ['front', 'top']}}
        for keys in ({'uniqueItems': True}, {}, {'uniqueItems': False}):
            schema = {**base, **keys}
            annotate(schema, {'status': 'pending'}, '/properties/views', 'freecad', 'schemaxis.freecad.drawing/1')
            if keys.get('uniqueItems'):
                self.assertEqual(schema['x-studio-control'], {'kind': 'enum-subset'})
            else:
                self.assertNotIn('x-studio-control', schema)

    def test_static_subset_projects_through_referenced_definitions(self):
        projection = catalogue('oracle')
        item = next(item for item in projection['items'] if item['id'] == 'document:inspection')
        definition = item['schema']['$ref'].rsplit('/', 1)[-1]
        kinds = projection['definitions'][definition]['properties']['kinds']
        self.assertEqual(kinds['x-studio-control'], {'kind': 'enum-subset'})

    def test_generated_file_reader_family_projects_one_instance_field(self):
        result = catalogue('paraview')
        items = {item['operation']: item for item in result['items'] if item.get('operation')}
        reader = items['pvXMLUnstructuredGridReader']
        self.assertEqual(reader['authoring']['instanceFields'], [
            {'path': '/options/FileName', 'label': 'Source files', 'style': 'lastSegment'}])
        self.assertEqual(reader['authoringBasis'], 'adaptor Studio catalogue')
        self.assertNotIn('batchPath', reader['authoring']['multiMode'])
        self.assertNotIn('authoring', items['pvWriteCSVWriter'])
        self.assertNotIn('authoringBasis', items['foam'])
        options = result['definitions']['options-pvXMLUnstructuredGridReader']['properties']
        self.assertEqual(options['PointArrayStatus']['x-studio-control'],
                         {'kind': 'reader-array-domain', 'field': 'PointArrayStatus'})

    def test_multi_mode_cannot_be_declared_for_singleton_nodes(self):
        item = next(item for item in catalogue('shotcut')['items'] if item['id'] == 'operation:editTimeline')
        item['authoring'] = {'multiMode': {'rationale': 'test'}, 'instanceFields': [
            {'path': '/options/clips', 'label': 'Clips'}]}
        with self.assertRaisesRegex(SchemaxisError, 'singleton'):
            validate_authoring_schema(item, {})

    def test_schema_policy_paths_are_checked_before_rendering(self):
        item = {'id': 'operation:example', 'at': '/nodes/-',
                'schema': {'properties': {'id': {'type': 'string'}, 'options': {'$ref': '#/$defs/options'}}},
                'authoring': {'multiMode': {'path': '/options/missing'}}}
        definitions = {'options': {'type': 'object', 'properties': {'items': {'anyOf': [
            {'type': 'array', 'items': {'anyOf': [{'type': 'string'}, {'type': 'object'}]}},
            {'type': 'object'}]}, 'number': {'type': 'number'}}}}
        for path in ('/options/missing', '/options/number'):
            item['authoring']['multiMode']['path'] = path
            with self.assertRaises(SchemaxisError) as caught:
                validate_authoring_schema(item, definitions)
            self.assertEqual(caught.exception.fault.code, 'INVALID_STUDIO_GUIDANCE')
        item['authoring']['multiMode']['path'] = '/options/items'
        validate_authoring_schema(item, definitions)
