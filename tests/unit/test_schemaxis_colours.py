import sys
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.colours import palette, rgba
from schemaxis.publication import style


class ColourTests(unittest.TestCase):
    def test_named_colours_without_runtime_dependencies(self):
        self.assertGreater(len(palette()['colours']), 1100)
        self.assertEqual(rgba('red'), [1, 0, 0, 1])
        self.assertEqual(rgba('GOLDENROD'), rgba('#daa520'))
        self.assertEqual(rgba('xkcd:sky blue'), rgba('#75bbfd'))
        self.assertEqual(rgba('tab:blue'), rgba('#1f77b4'))

    def test_hex_byte_alpha_and_grey(self):
        self.assertEqual(rgba('#f008'), [1, 0, 0, 136/255])
        self.assertEqual(rgba([255, 0, 0]), [1, 0, 0, 1])
        self.assertEqual(rgba('0.5'), [.5, .5, .5, 1])
        value = style({'colour': '#ff000080', 'opacity': .5}, '$')
        self.assertEqual(value['colour'], [1, 0, 0])
        self.assertAlmostEqual(value['opacity'], 64/255)

    def test_every_exported_colour_is_valid(self):
        for name, expected in palette()['colours'].items():
            self.assertEqual(rgba(name), expected)

    def test_invalid_colours_fail(self):
        for value in ('not a colour', '#gg00ff', [-1, 0, 0], [2.0, 0, 0], [True, 0, 0], 'nan'):
            with self.assertRaises(SchemaxisError):
                rgba(value)
