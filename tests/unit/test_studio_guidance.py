"""Conceptual-help inventory, projection and admission remain host-only."""
import copy
import json
import unittest
from unittest.mock import patch
import importlib.util
import tempfile
from pathlib import Path
from schemaxis.adaptors import registry
from schemaxis.studio_guidance import fields, audit, enrich, load, validate_record
from schemaxis.studio_catalogue import catalogue
from schemaxis.schema_authoring import version_schema


def plain(value):
    if isinstance(value, list):
        return [plain(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {key: plain(item) for key, item in value.items()
            if not key.startswith('x-studio-') and key not in ('description', 'title')}


class StudioGuidanceTests(unittest.TestCase):
    def test_shared_schema_objects_keep_independent_help_addresses(self):
        shared = {'type': 'string'}
        schema = {'type': 'object', 'properties': {'id': shared, 'file': shared}}
        guidance = {'routes': {'schemaxis/1': {'fields': {
            '/properties/id': {'status': 'reviewed', 'explanation': 'A unique name.'},
            '/properties/file': {'status': 'reviewed', 'explanation': 'An input file.'}}}}}
        result = enrich(schema, 'paraview', 'schemaxis/1', guidance)
        self.assertEqual(result['properties']['id']['description'], 'A unique name.')
        self.assertEqual(result['properties']['id']['x-studio-guide']['address'], '/properties/id')
        self.assertEqual(result['properties']['file']['description'], 'An input file.')
        self.assertNotIn('description', shared)

    def test_native_bindings_and_spatial_controls_survive_schema_projection(self):
        result = catalogue('paraview')
        options = result['definitions']['options-calculator']['properties']
        self.assertEqual(options['expression']['title'], 'Function (equation)')
        self.assertEqual(options['result']['x-studio-guide']['binding']['property'], 'ResultArrayName')
        self.assertIn('sqrt(U_X', options['expression']['description'])
        self.assertEqual(result['definitions']['options-line']['x-studio-control'],
                         {'kind': 'line', 'start': 'start', 'end': 'end'})
        step = result['definitions']['options-pvStreamTracer']['properties']['InitialStepLength']
        self.assertEqual(step['x-studio-guide']['status'], 'reference')
        self.assertIn('initial integration step', step['description'])
        self.assertTrue(any('InitialIntegrationStep' in source for source in step['x-studio-guide']['sources']))

    def test_native_property_import_uses_python_names_and_preserves_reviewed_prose(self):
        path = Path(__file__).resolve().parents[2] / 'tools/import_paraview_guidance.py'
        spec = importlib.util.spec_from_file_location('native_guidance_import', path)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        address = '/$defs/options-stream/properties/initialStep'
        guide = {'routes': {'schemaxis/1': {'fields': {address: {'status': 'pending'}}}}}
        declarations = {'stream': {'native': 'StreamTracer', 'nativeIdentity': 'filters/StreamTracer',
            'options': {'initialStep': {'path': ['InitialStepLength']}}}}
        context = {'operations': {'filters/StreamTracer': {'properties': {
            'InitialIntegrationStep': {'pythonName': 'InitialStepLength', 'description': 'Initial integration step.', 'label': 'Initial Step Length'}}}}}
        result, changes = tool.project(context, guide, declarations)
        self.assertEqual(changes, [address])
        record = result['routes']['schemaxis/1']['fields'][address]
        self.assertEqual(record['status'], 'reference')
        record.update(status='reviewed', explanation='Reviewed local meaning.')
        retained, changes = tool.project(context, result, declarations)
        self.assertFalse(changes)
        self.assertEqual(retained, result)

    def test_every_registered_adaptor_route_and_operation_has_a_preserved_record(self):
        with patch('subprocess.Popen', side_effect=AssertionError('host-only')):
            for provider, manifest in registry.ADAPTORS.items():
                with self.subTest(provider=provider):
                    guide = load(provider)
                    self.assertEqual(set(guide['operations']), set(registry.declarations(provider)))
                    report = audit(provider)
                    self.assertFalse(report['stale'])
                    self.assertEqual(set(report['routes']), set(manifest['routes']))
                    for version, route in manifest['routes'].items():
                        schema = registry.binding(route['schema'])()
                        self.assertEqual(set(guide['routes'][version]['fields']), {path for path, _ in fields(schema)})
                    expected_records = len(guide['operations']) + sum(
                        len(route['fields']) for route in guide['routes'].values())
                    self.assertEqual(sum(report['counts'].values()), expected_records)
                    self.assertEqual(report['complete'], report['counts']['pending'] == 0 and not report['linkIssues'])

    def test_completion_requires_every_declared_record_and_no_stale_records(self):
        guide = load('calc')
        records = list(guide['operations'].values())
        for route in guide['routes'].values():
            records.extend(route['fields'].values())
        for record in records:
            record.update(status='reviewed', explanation='Reviewed conceptual explanation.')
        with patch('schemaxis.studio_guidance.load', return_value=guide):
            self.assertTrue(audit('calc')['complete'])
            records[0]['status'] = 'pending'
            self.assertFalse(audit('calc')['complete'])
            records[0]['status'] = 'reviewed'
            guide['operations']['retired'] = {'status': 'reviewed', 'explanation': 'Obsolete.'}
            self.assertFalse(audit('calc')['complete'])

    def test_annotations_preserve_validation_and_reach_authored_schema(self):
        version = 'schemaxis/1'
        native = version_schema(version, authored=True)
        enriched = version_schema(version, authored=True, annotate=lambda schema: enrich(schema, 'paraview', version))
        self.assertEqual(plain(native), plain(enriched))
        descriptions = [node.get('description', '') for _, node in fields(enriched)]
        self.assertTrue(any('marker can be empty' in text for text in descriptions))
        guide = load('paraview')
        changed = copy.deepcopy(guide)
        changed['routes'][version]['fields']['/$defs/options-foam/properties/file']['explanation'] = 'Human contributed explanation.'
        raw = registry.binding(registry.metadata('paraview')['routes'][version]['schema'])()
        result = enrich(raw, 'paraview', version, changed)
        self.assertEqual(result['$defs']['options-foam']['properties']['file']['description'], 'Human contributed explanation.')
        self.assertNotIn('x-studio-guide', raw)

    def test_non_graph_catalogues_and_operation_semantics_are_projected(self):
        for provider in registry.ADAPTORS:
            with self.subTest(provider=provider):
                additions = catalogue(provider)
                self.assertTrue(additions['items'])
                for item in additions['items']:
                    self.assertIn('guidance', item)
                schema = registry.binding(registry.metadata(provider)['routes'][registry.metadata(provider)['version']]['schema'])()
                if schema.get('properties', {}).get('nodes'):
                    projected = {item['operation'] for item in additions['items'] if item.get('operation')}
                    self.assertEqual(projected, set(registry.declarations(provider)))
        render = catalogue('blender', 'schemaxis.blender.render/1')
        self.assertIn('document:sceneFile', {item['id'] for item in render['items']})
        self.assertFalse(any(item.get('operation') for item in render['items']))
        assembly = catalogue('freecad', 'schemaxis.freecad.assembly/1')
        self.assertIn('document:components', {item['id'] for item in assembly['items']})
        integral = next(item for item in catalogue('octave')['items'] if item.get('operation') == 'integral')
        self.assertTrue(integral['guidance']['pitfalls'])
        self.assertTrue(integral['guidance']['examples'])

    def test_review_import_merges_only_valid_known_addresses(self):
        path = Path(__file__).resolve().parents[2] / 'tools/studio_guidance.py'
        spec = importlib.util.spec_from_file_location('guidance_tool', path)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'src/schemaxis/adaptors/calc'
            folder.mkdir(parents=True)
            contribution = {'calc': {'operations': {'formula': {'status': 'reviewed', 'explanation': 'Evaluate a declared formula.'}}}}
            name = next(iter(load('calc')['operations']))
            contribution['calc']['operations'][name] = contribution['calc']['operations'].pop('formula')
            request = root / 'review.json'
            request.write_text(json.dumps(contribution))
            with patch.object(tool, 'ROOT', root):
                tool.apply_review(request)
            retained = json.loads((folder / 'guidance.json').read_text())
            self.assertEqual(retained['operations'][name]['status'], 'reviewed')
            before = (folder / 'guidance.json').read_bytes()
            contribution['calc']['operations']['retired'] = {'status': 'reviewed', 'explanation': 'Stale operation.'}
            request.write_text(json.dumps(contribution))
            with patch.object(tool, 'ROOT', root), self.assertRaises(ValueError):
                tool.apply_review(request)
            self.assertEqual((folder / 'guidance.json').read_bytes(), before)

    def test_available_guidance_requires_prose_and_reference_provenance(self):
        for record in ({'status': 'reviewed'}, {'status': 'reference', 'explanation': 'Useful explanation.'},
                       {'status': 'invented', 'explanation': 'Useful explanation.'}):
            with self.subTest(record=record), self.assertRaises(ValueError):
                validate_record(record)
        validate_record({'status': 'pending'})

    def test_stale_records_are_not_claimed_complete(self):
        guide = load('calc')
        guide['operations']['retired'] = {'status': 'pending'}
        guide['routes']['schemaxis.calc/1']['fields']['/removed'] = {'status': 'pending'}
        with patch('schemaxis.studio_guidance.load', return_value=guide):
            result = audit('calc')
        self.assertIn('operation:retired', result['stale'])
        self.assertIn('schemaxis.calc/1:/removed', result['stale'])
        self.assertFalse(result['complete'])


class GuidanceToolTests(unittest.TestCase):
    def tool(self):
        path = Path(__file__).resolve().parents[2] / 'tools/studio_guidance.py'
        spec = importlib.util.spec_from_file_location('guidance_tool_derive', path)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        return tool

    def test_review_merge_preserves_optional_metadata_and_null_removes(self):
        tool = self.tool()
        current = {'status': 'pending', 'fileExtensions': ['.foam'], 'question': 'Which case?'}
        merged = tool.merge(current, {'status': 'reviewed', 'explanation': 'Choose the case marker.', 'question': None})
        self.assertEqual(merged, {'status': 'reviewed', 'fileExtensions': ['.foam'], 'explanation': 'Choose the case marker.'})

    def test_value_wrappers_and_references_share_their_origin_record(self):
        tool = self.tool()
        schema = {'$defs': {'runtime': {'type': 'object'}}, 'type': 'object', 'properties': {
            'scale': {'anyOf': [{'type': 'number'}, {'$ref': '#/$defs/runtime'}]},
            'mode': {'anyOf': [{'enum': ['a']}, {'enum': ['b']}]}}}
        links = tool.origins(schema)
        self.assertEqual(links['/properties/scale/anyOf/0'], ('/properties/scale', False))
        self.assertEqual(links['/properties/scale/anyOf/1'], ('/$defs/runtime', True))
        self.assertNotIn('/properties/mode/anyOf/0', links)

    def test_derive_fills_and_refreshes_only_derived_records(self):
        tool = self.tool()
        schema = {'$defs': {'runtime': {'type': 'object'}}, 'type': 'object', 'properties': {
            'scale': {'anyOf': [{'type': 'number'}, {'$ref': '#/$defs/runtime'}]},
            'size': {'anyOf': [{'type': 'number'}, {'$ref': '#/$defs/runtime'}]}}}
        guide = {'version': 'schemaxis.studio-guidance/1', 'operations': {}, 'routes': {'r/1': {'fields': {
            '/$defs/runtime': {'status': 'reviewed', 'explanation': 'Computed while the visit runs.',
                               'label': 'Runtime value', 'sources': ['docs/dollar-reference.md']},
            '/properties/scale': {'status': 'reviewed', 'explanation': 'Multiplies glyph size.', 'label': 'Scale',
                                  'units': 'Dimensionless.', 'sources': ['a.xml']},
            '/properties/size/anyOf/0': {'status': 'reviewed', 'explanation': 'Hand-written literal help.'}}}}}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(tool, 'ROOT', Path(directory)), \
                patch.object(tool, 'load', side_effect=lambda provider: copy.deepcopy(guide)), \
                patch.object(tool, 'routes', return_value=[('r/1', schema, {p for p, _ in fields(schema)})]):
            (Path(directory) / 'src/schemaxis/adaptors/demo').mkdir(parents=True)
            tool.derive('demo')
            result = json.loads((Path(directory) / 'src/schemaxis/adaptors/demo/guidance.json').read_text())
        records = result['routes']['r/1']['fields']
        literal = records['/properties/scale/anyOf/0']
        self.assertEqual((literal['explanation'], literal['units']), ('Multiplies glyph size.', 'Dimensionless.'))
        self.assertNotIn('label', literal)
        self.assertEqual(literal['sources'], ['a.xml', 'guidance:/properties/scale'])
        runtime = records['/properties/scale/anyOf/1']
        self.assertEqual((runtime['label'], runtime['sources'][-1]), ('Runtime value', 'guidance:/$defs/runtime'))
        self.assertEqual(records['/properties/size/anyOf/0']['explanation'], 'Hand-written literal help.')
        self.assertNotIn('/properties/size', records)

    def test_derive_refreshes_node_variants_from_their_operation_record(self):
        tool = self.tool()
        schema = {'type': 'object', 'properties': {'nodes': {'type': 'array', 'items': {'oneOf': [{'type': 'object'}]}}}}
        guide = {'version': 'schemaxis.studio-guidance/1',
                 'operations': {'cut': {'status': 'reviewed', 'explanation': 'Corrected text.', 'sources': ['b.xml']}},
                 'routes': {'r/1': {'fields': {'/properties/nodes/items/oneOf/0': {
                     'status': 'reviewed', 'explanation': 'Stale text.', 'pitfalls': ['Stale pitfall.'],
                     'label': 'Cut', 'sources': ['a.xml', 'guidance:operation cut']}}}}}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(tool, 'ROOT', Path(directory)), \
                patch.object(tool, 'load', side_effect=lambda provider: copy.deepcopy(guide)), \
                patch.object(tool, 'routes', return_value=[('r/1', schema, {p for p, _ in fields(schema)})]):
            (Path(directory) / 'src/schemaxis/adaptors/demo').mkdir(parents=True)
            tool.derive('demo')
            result = json.loads((Path(directory) / 'src/schemaxis/adaptors/demo/guidance.json').read_text())
        variant = result['routes']['r/1']['fields']['/properties/nodes/items/oneOf/0']
        self.assertEqual(variant, {'status': 'reviewed', 'explanation': 'Corrected text.', 'label': 'Cut',
                                   'sources': ['b.xml', 'guidance:operation cut']})


class SharedDocumentGuidanceTests(unittest.TestCase):
    def test_workflow_choice_guidance_matches_route_after_provider_insertion(self):
        from schemaxis.schema_authoring import WORKFLOW_VERSIONS
        from schemaxis.studio_guidance import load
        records = load('workflow')['routes']['schemaxis.workflow/1']['fields']
        for index, version in enumerate(WORKFLOW_VERSIONS):
            address = '/properties/operations/items/properties/document/oneOf/' + str(index)
            with self.subTest(version=version):
                self.assertIn('(route ' + version + ')', records[address]['explanation'])

    def test_shared_documents_inventory_their_own_envelope_only(self):
        from schemaxis.studio_guidance import SHARED, shared_fields, audit_shared
        for version in SHARED:
            with self.subTest(version=version):
                owned = [path for path, _ in shared_fields(version)]
                self.assertTrue(owned)
                self.assertFalse([path for path in owned if path.startswith('/$defs/pipeline')])
                if version != 'schemaxis.workflow/1':
                    self.assertFalse([path for path in owned if path.startswith('/properties/workflow/')])
        for provider in set(SHARED.values()):
            report = audit_shared(provider)
            self.assertFalse(report['stale'])
            self.assertEqual(report['complete'], report['counts']['pending'] == 0)

    def test_embedded_documents_and_markers_carry_adaptor_and_shared_guidance(self):
        from schemaxis.studio_guidance import enrich_shared, enrich_markers, document_annotator
        from schemaxis.schema_authoring import version_schema
        design = enrich_shared('schemaxis.workflow-design/2')
        providers = {node['x-studio-guide']['provider'] for _, node in fields(design) if 'x-studio-guide' in node}
        self.assertTrue({'paraview', 'gmsh', 'workflow', 'workflow-design'} <= providers)
        envelope = design['properties']['workflow']['properties']['operations']['x-studio-guide']
        self.assertEqual((envelope['provider'], envelope['address']), ('workflow', '/properties/operations'))
        authored = enrich_markers(version_schema('schemaxis.gmsh/1', authored=True,
                                                 annotate=document_annotator('schemaxis.gmsh/1')))
        marker = authored['$defs']['documentReference']['x-studio-guide']
        self.assertEqual((marker['provider'], marker['version']), ('workflow', 'schemaxis.workflow/1'))

    def test_shared_projection_never_mutates_reusable_schema_objects(self):
        from schemaxis.studio_guidance import enrich_shared, enrich_markers
        from schemaxis.schema_authoring import version_schema, workflow_schema
        before = json.dumps(version_schema('schemaxis.gmsh/1', authored=True), sort_keys=True)
        enrich_markers(version_schema('schemaxis.gmsh/1', authored=True))
        enrich_shared('schemaxis.workflow-design/2')
        self.assertEqual(json.dumps(version_schema('schemaxis.gmsh/1', authored=True), sort_keys=True), before)
        self.assertNotIn('x-studio-guide', json.dumps(workflow_schema(authored=True)))

    def test_cited_repository_sources_exist(self):
        tool = GuidanceToolTests.tool(self)
        for provider in tool.PROVIDERS:
            with self.subTest(provider=provider):
                self.assertEqual(tool.missing_sources(provider), [])
        guide = {'version': 'schemaxis.studio-guidance/1', 'operations': {'x': {'status': 'reviewed',
                 'explanation': 'Example.', 'sources': ['src/schemaxis/no_such_module.py:1-3', 'https://example.org']}}, 'routes': {}}
        with patch.object(tool, 'load', return_value=guide):
            self.assertEqual(tool.missing_sources('demo'), ['src/schemaxis/no_such_module.py:1-3'])

    def test_add_catalogue_leads_with_operation_guidance_and_keeps_native_summary(self):
        items = {item.get('operation'): item for item in catalogue('paraview')['items'] if item.get('operation')}
        contour = items['pvContour']
        self.assertEqual(contour['description'], load('paraview')['operations']['pvContour']['explanation'])
        self.assertIn('isolines', contour['nativeDescription'])
        for item in items.values():
            self.assertNotEqual(item['guidance']['status'], 'pending')
