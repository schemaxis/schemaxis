# Copyright (C) 2026 David L. F. Gaden.
"""Scene GUI annotations preserve the existing authored publication contract."""
import unittest
from unittest.mock import patch
from schemaxis.studio_catalogue import catalogue
from schemaxis.adaptors.paraview.schema import document_schema
from schemaxis.adaptors.paraview.job import plan
from schemaxis.colours import palette


class SceneControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = document_schema()
        with patch('subprocess.Popen', side_effect=AssertionError('Authoring must not load native data')):
            cls.catalogue = catalogue('paraview')
        cls.scene = next(i['schema'] for i in cls.catalogue['items'] if i['id'] == 'document:scenes')

    def test_guided_scene_fields_and_authoritative_palette(self):
        props = self.scene['properties']
        self.assertEqual(props['visible']['x-studio-control']['kind'], 'pipeline-map')
        self.assertEqual(props['appearances']['items']['x-studio-control']['kind'], 'pipeline-map')
        self.assertEqual(props['geometry']['x-studio-reference'], {'kind': 'data', 'multiple': True})
        camera = props['images']['items']['properties']['cameras']['items']
        self.assertEqual(camera['properties']['bounds']['x-studio-control']['kind'], 'frame')
        self.assertEqual(self.catalogue['definitions']['studio-colours']['x-studio-palette'], palette())
        self.assertEqual(document_schema(), self.before)
        appearance = next(i for i in self.catalogue['items'] if i['id'] == 'scene:appearance')
        self.assertTrue(appearance['editTarget'])
        self.assertNotIn('lighting', appearance['description'])

    def test_gui_authored_values_plan_with_existing_schema(self):
        body = {'version': 'schemaxis/1', 'definitions': {'focus': {'min': [-2,-2,-2], 'max': [2,2,2]}},
                'nodes': [{'id': 'body', 'filter': 'sphere'}],
                'scenes': [{'id': 'view', 'visible': {'body': {'colour': 'xkcd:sky blue', 'opacity': 0.7}},
                            'appearances': [{}, {'body': {'colour': [0.2,0.4,0.6]}}],
                            'images': [{'id': 'image', 'size': [640,480], 'background': 'white',
                                        'cameras': [{'bounds': {'$expr': 'definitions.focus'}, 'direction': [1,1,1]}]}]}]}
        _, scenes, _ = plan(body)
        self.assertEqual(scenes[0]['publications'], 2)
        self.assertEqual(scenes[0]['visible']['body']['colour'], palette()['colours']['xkcd:sky blue'][:3])

if __name__ == '__main__':
    unittest.main()
