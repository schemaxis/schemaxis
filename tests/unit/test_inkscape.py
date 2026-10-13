"""Host intent, semantic evidence and independent native-measurement contracts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from schemaxis.adaptors.inkscape import adaptor as app
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]


def fixture():
    return json.loads((ROOT / 'examples/schemaxis/inkscape-diagram.json').read_text())


def native_query(prepared):
    rows = []
    def row(identity, values):
        rows.append(identity + ',' + ','.join(str(v * app.PX_MM) for v in values))
    for box in prepared['boxes']:
        row('box_' + box['id'], [box['x'] - .2, box['y'] - .2, box['width'] + .4, box['height'] + .4])
        row('label_' + box['id'], [box['x'] + prepared['padding'] + .2, box['y'] + 8, 8, 3])
    for link in prepared['routes']:
        xs, ys = zip(*link['points']); x, y = link['points'][-1]
        row('link_' + link['id'], [min(xs), min(ys) - .2, max(xs) - min(xs), max(ys) - min(ys) + .4])
        row('arrow_' + link['id'], [x - 2, y - 1, 2, 2])
    return '\n'.join(rows) + '\n'


class InkscapeTests(unittest.TestCase):
    def error(self, function, code):
        with self.assertRaises(SchemaxisError) as caught: function()
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def test_schema_matches_fixture_and_defaults(self):
        import jsonschema
        doc = fixture(); original = copy.deepcopy(doc)
        jsonschema.validate(doc, app.schema())
        planned = app.plan(doc)
        self.assertEqual(doc, original)
        self.assertEqual(planned, app.plan(doc))
        self.assertEqual(planned['minimumClearance'], 34.6)
        self.assertEqual(planned['routes'][0]['points'], [[40.2, 25.0], [57.5, 25.0], [57.5, 25.0], [74.8, 25.0]])
        self.assertEqual(app.reusableInputs(doc), {})

    def test_invalid_geometry_locations_and_recovery(self):
        for change in ('overlap', 'page', 'backward', 'duplicate', 'control'):
            doc = fixture()
            if change == 'overlap': doc['boxes'][1]['x'] = 35
            if change == 'page': doc['boxes'][0]['x'] = 5
            if change == 'backward': doc['links'][0].update(source='result', target='input')
            if change == 'duplicate': doc['boxes'][1]['id'] = 'input'
            if change == 'control': doc['boxes'][0]['label'] = 'two\nlines'
            error = self.error(lambda: app.plan(doc), 'INVALID_LAYOUT')
            self.assertTrue(error.location.startswith('$.'))
            self.assertIn('Move or resize', error.recovery)

    def test_connector_rejects_unrelated_box(self):
        doc = fixture(); doc['clearance'] = 1
        doc['boxes'].append({'id': 'obstacle', 'label': 'X', 'x': 50, 'y': 20, 'width': 10, 'height': 10})
        error = self.error(lambda: app.plan(doc), 'INVALID_LAYOUT')
        self.assertEqual(error.observed['box'], 'obstacle')

    def test_xml_forbidden_labels_fail_before_native(self):
        for text in ('x\ud800', 'x\ufffe', 'x\uffff'):
            doc = fixture(); doc['boxes'][0]['label'] = text
            self.error(lambda: app.plan(doc), 'INVALID_LAYOUT')

    def test_unknown_authored_options_and_nonfinite(self):
        doc = fixture(); doc['actions'] = 'arbitrary command'
        self.error(lambda: app.plan(doc), 'UNKNOWN_ARGUMENT')
        doc = fixture(); doc['width'] = float('nan')
        self.error(lambda: app.plan(doc), 'INVALID_ARGUMENT')

    def test_svg_is_editable_and_escapes_text(self):
        doc = fixture(); doc['boxes'][0]['label'] = '<script>&text'
        root = ET.fromstring(app.svg(app.plan(doc)))
        texts = root.findall('{http://www.w3.org/2000/svg}text')
        self.assertEqual(texts[0].text, '<script>&text')
        self.assertFalse(root.findall('{http://www.w3.org/2000/svg}script'))

    def test_native_measurements_reject_shape_and_label_faults(self):
        prepared = app.plan(fixture()); output = native_query(prepared)
        measured = app.bounds(prepared, output)
        self.assertEqual(measured['boxCount'], 2)
        self.assertEqual(measured['linkCount'], 1)
        self.error(lambda: app.bounds(prepared, output.replace('box_input,', 'missing,')), 'VERIFICATION_FAILED')
        lines = output.splitlines(); parts = lines[1].split(','); parts[3] = str(50 * app.PX_MM); lines[1] = ','.join(parts)
        error = self.error(lambda: app.bounds(prepared, '\n'.join(lines)), 'LABEL_OVERFLOW')
        self.assertIn('lower fontSize', error.recovery)
        lines = output.splitlines(); parts = lines[-2].split(','); parts[3] = '500'; lines[-2] = ','.join(parts)
        self.error(lambda: app.bounds(prepared, '\n'.join(lines)), 'VERIFICATION_FAILED')

    def test_verifier_reconstructs_svg_despite_updated_hash(self):
        # This synthetic fixture isolates semantic tamper rejection. Raster decoder
        # behaviour is separately exercised by native conformance with actual PNG.
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp); document = fixture(); prepared = app.plan(document)
            atomic_json(directory/'authored.json', document); atomic_json(directory/'plan.json', prepared)
            atomic_json(directory/'result.json', {'status': 'succeeded', 'verified': True})
            (directory/'diagram.svg').write_bytes(app.svg(prepared)); (directory/'diagram.png').write_bytes(b'fixture')
            (directory/'query.stdout').write_text(native_query(prepared)); (directory/'version.stdout').write_text('Inkscape 1.4.3 (fixture)\n')
            for stage in ('query', 'version', 'export'):
                atomic_json(directory/(stage+'-submission.json'), {'nativeCommand': ['/fixture/inkscape', '--app-id-tag='+app.instance_tag(directory, stage), *app.stage_arguments(prepared, directory, stage)]})
            native = app.bounds(prepared, native_query(prepared))
            atomic_json(directory/'diagram-measurements.json', {'version': 'schemaxis.inkscape.measurements/1', 'units': 'mm', **native})
            with patch.object(app, 'raster', return_value={'width': 454, 'height': 227}):
                receipt = app.receipt(directory, prepared); atomic_json(directory/'verification.json', receipt)
                self.assertTrue(app._native_verify(directory)['verified'])
                (directory/'diagram.svg').write_bytes(app.svg(prepared).replace(b'width="30"', b'width="31"', 1))
                receipt['artifacts'][0]['sha256'] = file_digest(directory/'diagram.svg')
                atomic_json(directory/'verification.json', receipt)
                self.error(lambda: app._native_verify(directory), 'VERIFICATION_FAILED')

    def test_native_visit_isolates_constructor_and_profile_before_launch(self):
        prepared = app.plan(fixture())
        with tempfile.TemporaryDirectory() as temp, patch.object(app, 'execute') as execute:
            directory = Path(temp)
            app.native_visit('/fixture/inkscape', prepared, directory, 'query', 20)
            arguments, keywords = execute.call_args
            tag = app.instance_tag(directory, 'query')
            self.assertEqual(arguments[0][1], '--app-id-tag=' + tag)
            self.assertEqual(keywords['environment']['INKSCAPE_APP_ID_TAG'], tag)
            self.assertEqual(keywords['environment']['INKSCAPE_PROFILE_DIR'], str(directory/'.native-profiles'/'query'))
            self.assertNotEqual(tag, app.instance_tag(directory, 'export'))
            self.assertNotEqual(tag, app.instance_tag(directory/'another-run', 'query'))

    def test_unavailable_executable_and_timeout_are_structured(self):
        self.error(lambda: app.run(fixture(), '/unused', executable='/does/not/exist'), 'INTERPRETER_NOT_FOUND')
        self.error(lambda: app.run(fixture(), '/unused', executable='/bin/true', timeout=float('nan')), 'INVALID_ARGUMENT')


class FlowDiagramTests(unittest.TestCase):
    error = InkscapeTests.error
    def flow(self):
        return json.loads((ROOT/'examples/schemaxis/inkscape-flow.json').read_text())

    def test_flow_derives_coordinates_with_literal_ranks_and_budgets(self):
        import jsonschema
        document = self.flow(); original = copy.deepcopy(document)
        self.assertFalse(any('x' in box or 'y' in box for box in document['boxes']))
        jsonschema.validate(document, app.schema())
        prepared = app.plan(document)
        self.assertEqual(document, original)
        self.assertEqual(prepared['layout']['ranks'], {'input': 0, 'model': 1, 'simulate': 1, 'result': 2})
        self.assertEqual(prepared['layout']['laneCounts'], [1, 2, 1])
        self.assertAlmostEqual(prepared['layout']['requiredSize'][0], 109.2)
        self.assertAlmostEqual(prepared['layout']['requiredSize'][1], 36.8)
        geometry = {box['id']: box for box in prepared['boxes']}
        self.assertAlmostEqual(geometry['input']['x'], 20.6)
        self.assertAlmostEqual(geometry['model']['x'], 62)
        self.assertAlmostEqual(geometry['model']['y'], 26.8)
        self.assertAlmostEqual(geometry['simulate']['y'], 49.2)
        self.assertAlmostEqual(geometry['result']['x'], 103.4)
        self.assertEqual(app.query(document)[0], ['flowDiagram'])

    def test_flow_permutation_invariant_and_names_choose_lexical_lanes(self):
        document = self.flow(); baseline = app.plan(document)
        document['boxes'].reverse(); document['links'].reverse()
        self.assertEqual(app.plan(document), baseline)
        self.assertEqual(app.svg(app.plan(document)), app.svg(baseline))
        doc = self.flow(); doc['boxes'][1]['id'] = 'zmodel'
        for link in doc['links']:
            for key in ('source', 'target'):
                if link[key] == 'model': link[key] = 'zmodel'
        geometry = {box['id']: box for box in app.plan(doc)['boxes']}
        self.assertLess(geometry['simulate']['y'], geometry['zmodel']['y'])

    def test_flow_native_measurements_include_replayed_domain_layout(self):
        prepared = app.plan(self.flow()); measured = app.bounds(prepared, native_query(prepared))
        self.assertEqual(measured['layout'], prepared['layout'])
        self.assertEqual(measured['boxCount'], 4)
        self.assertEqual(measured['linkCount'], 4)

    def test_flow_diagnostics_and_invalid_inputs_never_launch_native(self):
        from schemaxis.adaptors import registry
        for filename, code in [('inkscape-flow-cycle-invalid.json', 'FLOW_CYCLE'),
                               ('inkscape-flow-page-invalid.json', 'FLOW_PAGE_OVERFLOW'),
                               ('inkscape-flow-routing-invalid.json', 'FLOW_ROUTING_COLLISION')]:
            document = json.loads((ROOT/'examples/schemaxis'/filename).read_text())
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, '_native_run') as native:
                error = self.error(lambda: registry.run(document, Path(tmp)/'attempt'), code)
                native.assert_not_called(); self.assertFalse((Path(tmp)/'attempt').exists())
                self.assertTrue(error.recovery)
        document = self.flow(); document['links'].append({'id': 'duplicate', 'source': 'input', 'target': 'model'})
        self.error(lambda: app.plan(document), 'INVALID_LAYOUT')

    def test_flow_closed_schema_rejects_manual_coordinates_and_controls(self):
        import jsonschema
        document = self.flow(); document['boxes'][0]['x'] = 10
        with self.assertRaises(jsonschema.ValidationError): jsonschema.validate(document, app.schema())
        self.error(lambda: app.plan(document), 'UNKNOWN_ARGUMENT')
        document = fixture(); document['boxWidth'] = 26
        with self.assertRaises(jsonschema.ValidationError): jsonschema.validate(document, app.schema())
        self.error(lambda: app.plan(document), 'UNKNOWN_ARGUMENT')

    def test_exact_clearance_budget_absorbs_float_roundoff_only(self):
        document = self.flow(); document.update(rankGap=5, laneGap=5)
        self.assertAlmostEqual(app.plan(document)['minimumClearance'], 5)
        document['rankGap'] = 4.999999
        self.error(lambda: app.plan(document), 'INVALID_LAYOUT')
        document = self.flow(); document.update(width=119.2, height=46.8)
        self.assertEqual(app.plan(document)['layout']['rankCount'], 3)
        document['width'] = 119.199999
        self.error(lambda: app.plan(document), 'FLOW_PAGE_OVERFLOW')

    def test_flow_common_analytic_card_budget_and_early_invalid_visit(self):
        from schemaxis.adaptors import registry
        document = self.flow()
        document['dimensions'] = {'cardWidth': {'$analytic': {'type': 'values', 'values': [26, 28]}}}
        document['boxWidth'] = {'$document': '/dimensions/cardWidth'}
        document['fontSize'] = {'$expr': {'op': 'divide', 'args': [6, 2]}}
        prepared = app.plan(document)
        self.assertEqual(prepared['states'], 2)
        widths = [visit['plan']['layout']['requiredSize'][0] for visit in prepared['visits']]
        self.assertAlmostEqual(widths[0], 109.2); self.assertAlmostEqual(widths[1], 115.2)
        requirements = registry.query(document)
        self.assertTrue(requirements['supported'])
        self.assertEqual(requirements['adaptors'][0]['operations'], ['flowDiagram'])
        document['dimensions']['cardWidth']['$analytic']['values'][-1] = 100
        self.error(lambda: registry.query(document), 'FLOW_PAGE_OVERFLOW')
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, '_native_run') as native:
            self.error(lambda: registry.run(document, Path(tmp)/'attempt'), 'FLOW_PAGE_OVERFLOW')
            native.assert_not_called(); self.assertFalse((Path(tmp)/'attempt').exists())


if __name__ == '__main__': unittest.main()
