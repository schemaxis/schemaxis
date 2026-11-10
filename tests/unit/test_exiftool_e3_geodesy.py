"""Host tests of the E3 great-circle interpolation. Expectations are hand-derived literals (symmetry, meridian/equator arcs, R*pi/180)."""
from decimal import Decimal as D
from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from schemaxis.adaptors.exiftool import geodesy as g  # noqa: E402


class Interpolation(unittest.TestCase):
    def test_meridian_midpoint(self):
        # contract G1: on a meridian a great circle is linear in latitude: halfway from 0 to 10 N is exactly 5 N
        r = g.interpolate((D(0), D(0)), (D(10), D(0)), F(1, 2))
        self.assertEqual((g.text9(r['latitude']), g.text9(r['longitude'])), ('5.000000000', '0.000000000'))
        self.assertEqual(r['flags'], [])

    def test_equator_quarter(self):
        # contract G1: on the equator the great circle is linear in longitude: a quarter of the way from 0 to 8 E is 2 E
        r = g.interpolate((D(0), D(0)), (D(0), D(8)), F(1, 4))
        self.assertEqual((g.text9(r['latitude']), g.text9(r['longitude'])), ('0.000000000', '2.000000000'))

    def test_antimeridian_goes_the_short_way_and_is_normalised(self):
        # contract G8: 179.9999 E to 179.9999 W on the equator, f = 0.5: the midpoint is on the antimeridian, published as -180 (never 0)
        r = g.interpolate((D(0), D('179.9999')), (D(0), D('-179.9999')), F(1, 2))
        self.assertEqual((g.text9(r['latitude']), g.text9(r['longitude'])), ('0.000000000', '-180.000000000'))
        self.assertIn('antimeridian', r['flags'])

    def test_three_quarters_across_the_antimeridian(self):
        # 0.0002 degrees of longitude in total, so 3/4 of the way from 179.9999 E is 179.9999 + 0.00015 = 180.00005 = -179.99995
        r = g.interpolate((D(0), D('179.9999')), (D(0), D('-179.9999')), F(3, 4))
        self.assertEqual(g.text9(r['longitude']), '-179.999950000')

    def test_symmetry(self):
        a, b = (D('35.1'), D('139.2')), (D('35.2'), D('139.4'))
        fwd = g.interpolate(a, b, F(1, 3))
        back = g.interpolate(b, a, F(2, 3))
        self.assertLess(abs(fwd['latitude'] - back['latitude']), D('2e-9'))
        self.assertLess(abs(fwd['longitude'] - back['longitude']), D('2e-9'))

    def test_polar_span_is_flagged(self):
        r = g.interpolate((D('89.99999995'), D(10)), (D('89.99999995'), D(-170)), F(1, 2))
        self.assertIn('nearPole', r['flags'])
        self.assertGreater(abs(r['latitude']), D('89.9999999'))

    def test_near_antipodal_is_refused(self):
        with self.assertRaises(g.Antipodal):
            g.interpolate((D(0), D(0)), (D(0), D(179.5)), F(1, 2))
        r = g.interpolate((D(0), D(0)), (D(0), D(178)), F(1, 2))        # 178 degrees is still a defined great circle
        self.assertEqual(g.text9(r['longitude']), '89.000000000')

    def test_identical_points(self):
        r = g.interpolate((D('12.5'), D('45.25')), (D('12.5'), D('45.25')), F(1, 2))
        self.assertEqual((g.text9(r['latitude']), g.text9(r['longitude'])), ('12.500000000', '45.250000000'))

    def test_open_interval_only(self):
        for bad in (F(0), F(1), F(-1, 2)):
            with self.assertRaises(ValueError):
                g.interpolate((D(0), D(0)), (D(1), D(1)), bad)


class Distance(unittest.TestCase):
    def test_one_degree_of_latitude(self):
        # R * pi / 180 with R = 6371008.8 m is 111195.0802 m (hand arithmetic: 63710.088 + 44597.0616 + 2548.40352 + 318.55044 + 20.97668)
        self.assertAlmostEqual(g.haversine_m((D(0), D(0)), (D(1), D(0))), 111195.0802, places=3)
        self.assertEqual(g.haversine_m((D(5), D(5)), (D(5), D(5))), 0.0)

    def test_quarter_circumference(self):
        self.assertAlmostEqual(g.haversine_m((D(0), D(0)), (D(0), D(90))), 6371008.8 * 3.141592653589793 / 2, places=3)


class Rounding(unittest.TestCase):
    def test_half_even_degrees_and_signed_zero(self):
        self.assertEqual(g.text9(g.round_degrees(-0.0000000001)[0]), '0.000000000')
        self.assertEqual(g.text9(g.round_degrees(35.1234567891)[0]), '35.123456789')
        self.assertTrue(g.round_degrees(0.0000000005)[1])           # a tie region: the verifier treats +/-1 last place as indeterminate
        self.assertFalse(g.round_degrees(0.1234567891)[1])

    def test_altitude_is_exact_and_half_even(self):
        self.assertEqual(g.interpolate_altitude(D('10'), D('11'), F(1, 2)), D('10.500'))
        self.assertEqual(g.interpolate_altitude(D('0'), D('0.001'), F(1, 2)), D('0.000'))   # 0.0005 -> tie -> even (0)
        self.assertEqual(g.interpolate_altitude(D('0'), D('0.003'), F(1, 2)), D('0.002'))   # 0.0015 -> tie -> even (2)
        self.assertEqual(g.interpolate_altitude(D('-5'), D('5'), F(1, 3)), D('-1.667'))
        self.assertEqual(g.interpolate_altitude(D('7'), D('7'), F(1, 3)), D('7.000'))


if __name__ == '__main__':
    unittest.main()
