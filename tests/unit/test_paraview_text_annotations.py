import copy
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.job import plan
from schemaxis.adaptors.paraview import publication
from schemaxis.adaptors.paraview.publication import Renderer, style, TEXT_STYLE, GEOMETRY_ONLY


def document(label=None, **scene):
    return {'version': 'schemaxis/1', 'times': [1, 2],
            'nodes': [{'id': 'clock', 'filter': 'pvTimeSource'},
                      {'id': 's', 'filter': 'sphere'},
                      {'id': 'label', 'filter': 'pvAnnotateTimeFilter', 'inputs': {'Input': 'clock'},
                       'options': {'Format': 't = {time:.1f}'}}],
            'scenes': [{'id': 'one', 'visible': {'s': {}, 'label': {} if label is None else label},
                        'images': [{'id': 'view', 'cameras': [{}]}], **scene}]}


class Display:
    """Text-representation fake: only text properties exist."""
    def __init__(self, xml, calls):
        object.__setattr__(self, 'xml', xml)
        object.__setattr__(self, 'calls', calls)
        object.__setattr__(self, 'values', {})
        object.__setattr__(self, 'SMProxy', type('SM', (), {'GetXMLName': lambda _: xml})())

    def GetProperty(self, name):
        value = self.values[name]
        return type('Enumeration', (), {'GetElement': lambda _, index: value})()

    def __getattr__(self, name):
        if name in self.values:
            return self.values[name]
        self.calls.append(name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        allowed = {'TextSourceRepresentation': {'Visibility', 'Color', 'Opacity', 'FontSize', 'WindowLocation',
                                                'Justification', 'Bold', 'Italic'}}.get(self.xml)
        if allowed is not None and name not in allowed:
            self.calls.append(name)
            raise AttributeError(name)
        self.values[name] = value


class PV:
    def __init__(self):
        self.calls, self.deleted = [], []

    def _DisableFirstRenderCameraReset(self):
        pass

    def CreateView(self, kind):
        return type('View', (), {})()

    def Show(self, proxy, view):
        return Display('TextSourceRepresentation', self.calls)

    def Delete(self, item):
        self.deleted.append(item)


class TextAnnotationTests(unittest.TestCase):
    def fault(self, code, action):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def test_declared_text_styles_are_validated_with_text_defaults(self):
        label = {'fontSize': 24, 'colour': 'red', 'position': 'Upper Center', 'justification': 'Center',
                 'bold': True, 'italic': True, 'opacity': 0.5}
        _, scenes, _ = plan(document(label))
        self.assertEqual(scenes[0]['text'], ['label'])
        resolved = style(label, 'label', text=True)
        self.assertEqual(resolved['fontSize'], 24)
        self.assertEqual(resolved['position'], 'Upper Center')
        self.assertEqual(resolved['colour'], [1, 0, 0])
        defaults = style({}, 'label', text=True)
        self.assertEqual(defaults, {'colour': [0, 0, 0], 'opacity': 1, 'fontSize': 18, 'position': 'Upper Left Corner',
                                    'justification': 'Left', 'bold': False, 'italic': False})
        for bad in ({'fontSize': 2}, {'position': 'Any Location'}, {'justification': 'Middle'}, {'bold': 1}):
            with self.subTest(bad=bad):
                self.fault('INVALID_ARGUMENT' if 'fontSize' in bad else self.code(bad), lambda: plan(document(bad)))

    def code(self, bad):
        try:
            plan(document(bad))
        except SchemaxisError as error:
            return error.fault.code
        self.fail('invalid text style accepted')

    def test_geometry_styles_on_text_fail_with_location_and_recovery(self):
        for key, value in (('field', ['POINTS', 'x']), ('representation', 'Wireframe'), ('legend', True),
                           ('preset', 'Jet'), ('range', [0, 1]), ('logScale', True)):
            with self.subTest(key=key):
                fault = self.fault('UNSUPPORTED_TEXT_STYLE', lambda: plan(document({key: value})))
                self.assertEqual(fault.location, '$.scenes[0].visible.label')
                self.assertEqual(fault.observed['keys'], [key])
                self.assertIn('fontSize', fault.recovery)
        value = document(appearances=[{}, {'label': {'representation': 'Points'}}])
        fault = self.fault('UNSUPPORTED_TEXT_STYLE', lambda: plan(value))
        self.assertEqual(fault.location, '$.scenes[0].appearances[1].label')
        value = document()
        value['scenes'][0]['visible']['s'] = {'fontSize': 12}
        fault = self.fault('UNSUPPORTED_GEOMETRY_STYLE', lambda: plan(value))
        self.assertIn('pvAnnotateTimeFilter', fault.recovery)

    def test_text_cannot_frame_or_export_gltf(self):
        value = document()
        del value['scenes'][0]['visible']['s']
        self.fault('EMPTY_SCENE', lambda: plan(value))
        self.fault('UNSUPPORTED_TEXT_ANNOTATION', lambda: plan(document(gltf=True)))

    def test_geometry_scenes_are_unchanged(self):
        value = document()
        del value['scenes'][0]['visible']['label']
        _, scenes, _ = plan(value)
        self.assertNotIn('text', scenes[0])
        self.assertEqual(style({}, 's')['representation'], 'Surface')

    def test_schema_and_guidance_expose_text_keys(self):
        from schemaxis.adaptors.paraview.schema import document_schema
        import json
        from pathlib import Path
        schema = document_schema()
        text = json.dumps(schema)
        for key in ('fontSize', 'position', 'justification', 'bold', 'italic'):
            self.assertIn(f'"{key}"', text)
        guidance = json.loads((Path(publication.__file__).parent / 'guidance.json').read_text())
        routes = json.dumps(guidance)
        for route in ('visible', 'appearances/items'):
            for key in ('fontSize', 'position', 'justification', 'bold', 'italic'):
                self.assertIn(f'/properties/scenes/items/properties/{route}/additionalProperties/properties/{key}"',
                              routes)

    def test_shipped_example_plans_one_text_scene_and_one_plain_scene(self):
        import json
        from pathlib import Path
        path = Path(__file__).parents[2] / 'examples' / 'schemaxis' / 'paraview-time-annotation.json'
        value = json.loads(path.read_text())
        self.fault('TIME_INSPECTION_REQUIRED', lambda: plan(copy.deepcopy(value)))
        value['times'] = [0, 1]  # The source selection is resolved by native inspection.
        _, scenes, _ = plan(value)
        self.assertEqual([s.get('text') for s in scenes], [['label'], None])
        self.assertEqual([s['publications'] for s in scenes], [4, 2])
        self.assertTrue(scenes[1]['appearances'][0]['ball']['representation'])

    def test_live_preview_rejects_text_before_native_mutation(self):
        from schemaxis.adaptors.paraview.live_native import Worker
        value = document()
        value['scenes'][0].pop('images')
        value['scenes'][0]['geometry'] = ['s']
        value['times'] = [1]
        fault = self.fault('UNSUPPORTED_LIVE_INPUT', lambda: Worker().prepare(value))
        self.assertEqual(fault.observed['nodes'], ['label'])
        self.assertIsNone(Worker().prepared)
        del value['scenes'][0]['visible']['label']
        self.assertEqual(Worker().prepare(value)[3], ['s'])

    def test_text_rendering_uses_only_text_properties_and_cleans_up(self):
        pv = PV()
        renderer = Renderer(type('Backend', (), {'pv': pv})())
        renderer.view.ViewTime = 0
        settings = style({'fontSize': 22, 'position': 'Lower Right Corner', 'justification': 'Right',
                          'colour': [0, 0, 1], 'italic': True}, 'label', text=True)
        observed = renderer.prepare({'label': object()}, {'label': settings}, time=2.5, text={'label'})
        self.assertEqual(renderer.view.ViewTime, 2.5)
        self.assertEqual(observed['label'], {'kind': 'text', 'colour': [0, 0, 1], 'opacity': 1.0, 'fontSize': 22,
                                             'position': 'Lower Right Corner', 'justification': 'Right',
                                             'bold': False, 'italic': True})
        self.assertEqual(pv.calls, [])
        renderer.clear()
        self.assertEqual(pv.calls, [])
        self.assertEqual(len(pv.deleted), 1)
        self.assertEqual(renderer.text, set())

    def test_undeclared_text_display_fails_structurally(self):
        pv = PV()
        renderer = Renderer(type('Backend', (), {'pv': pv})())
        fault = self.fault('UNSUPPORTED_TEXT_ANNOTATION',
                           lambda: renderer.prepare({'t': object()}, {'t': style({}, 't')}, time=0))
        self.assertEqual(fault.observed['representation'], 'TextSourceRepresentation')
        self.assertIn('pvAnnotateTimeFilter', fault.recovery)
        self.assertEqual(pv.calls, [])

    def test_text_scene_switch_uses_fresh_displays(self):
        pv = PV()
        renderer = Renderer(type('Backend', (), {'pv': pv})())
        settings = {'label': style({}, 'label', text=True)}
        first = renderer.prepare({'label': object()}, settings, time=1, text={'label'})
        display = renderer.displays['label']
        renderer.clear()
        second = renderer.prepare({'label': object()}, copy.deepcopy(settings), time=2, text={'label'})
        self.assertIsNot(renderer.displays['label'], display)
        self.assertEqual(first, second)
        self.assertEqual(sorted(GEOMETRY_ONLY), sorted(set(publication.STYLE) - set(TEXT_STYLE)))


if __name__ == '__main__':
    unittest.main()
