"""Host tests of the E3 location models. Stored rationals, XMP literals and edition layouts are hand-written literals (the supplement's native
observations and the audit's cases R60a-j, L11'a-c, L20-L22); mutants are literal values fed to the proofs, never produced by a writer."""
from decimal import Decimal as D
from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from schemaxis.adaptors.exiftool import locations as loc  # noqa: E402


def code_of(call, *args):
    try:
        call(*args)
    except loc.LocationProblem as error:
        return error.code
    return None


class Authored(unittest.TestCase):
    def test_coordinates_signs_and_zero(self):
        p = loc.parse_coordinate('-33.8', 'lat')
        self.assertEqual((p['ref'], p['magnitude'], p['signedZeroNormalised']), ('S', '33.8', False))
        z = loc.parse_coordinate('-0.0', 'lon')
        self.assertEqual((z['ref'], z['magnitude'], z['signedZeroNormalised'], z['value']), ('E', '0', True, 0))
        self.assertEqual(loc.parse_coordinate(-70.6, 'lon')['ref'], 'W')
        self.assertEqual(loc.parse_coordinate('+180', 'lon')['ref'], 'E')
        self.assertEqual(loc.parse_coordinate('-180', 'lon')['ref'], 'W')
        self.assertEqual(loc.parse_coordinate('90', 'lat')['magnitude'], '90')
        self.assertEqual(loc.parse_coordinate('0.000000001', 'lat')['magnitude'], '0.000000001')
        for bad, axis in (('90.000000001', 'lat'), ('180.1', 'lon'), ('1e1', 'lat'), ('35.1234567891', 'lat'), ('', 'lat'), (True, 'lat'), (None, 'lat'), ('35,5', 'lat'), (' 1', 'lat')):
            self.assertEqual(code_of(loc.parse_coordinate, bad, axis), 'INVALID_ARGUMENT', bad)

    def test_altitude_grammar(self):
        self.assertEqual(loc.parse_altitude('-12.5'), (D('-12.5'), '12.5'))
        self.assertEqual(loc.parse_altitude('-0')[0], 0)
        self.assertEqual(loc.parse_altitude('40000')[1], '40000')
        for bad in ('40000.001', '123456', '1.2345', '1e3', '', '--1', '12.'):
            self.assertEqual(code_of(loc.parse_altitude, bad), 'INVALID_ARGUMENT', bad)
        self.assertEqual(loc.parse_error_meters('5')[1], '5')
        self.assertEqual(code_of(loc.parse_error_meters, '-5'), 'INVALID_ARGUMENT')
        self.assertEqual(loc.parse_datum('WGS-84'), 'WGS-84')
        self.assertEqual(code_of(loc.parse_datum, 'é'), 'INVALID_ARGUMENT')
        self.assertEqual(code_of(loc.parse_datum, 'x' * 33), 'INVALID_ARGUMENT')


class ExifCoordinateReader(unittest.TestCase):
    def read(self, components, ref='N', axis='lat'):
        return loc.decode_exif_coordinate(components, ref, axis)

    def test_R60a_seconds_sixty_is_an_exact_sum(self):
        a = self.read([(33, 1), (47, 1), (60, 1)])
        self.assertEqual((a['degrees'], a['flags']), (F(169, 5), ['nonCanonicalSeconds60']))        # 33.8
        b = self.read([(33, 1), (48, 1), (0, 1)])
        self.assertEqual((b['degrees'], b['flags']), (F(169, 5), []))                              # R60b: same meaning, different stored literals
        self.assertEqual(a['stored'], [[33, 1], [47, 1], [60, 1]])
        self.assertNotEqual(a['stored'], b['stored'])

    def test_R60c_R60d_extremes(self):
        self.assertEqual(self.read([(89, 1), (59, 1), (60, 1)])['degrees'], 90)
        self.assertEqual(self.read([(179, 1), (59, 1), (60, 1)], 'W', 'lon')['degrees'], -180)
        self.assertEqual(self.read([(0, 1), (0, 1), (0, 1)], 'S')['degrees'], 0)

    def test_R60e_to_R60h_never_carry(self):
        self.assertEqual(code_of(self.read, [(33, 1), (47, 1), (61, 1)]), 'GPS_COORDINATE_COMPONENT_RANGE')
        self.assertEqual(code_of(self.read, [(33, 1), (60, 1), (0, 1)]), 'GPS_COORDINATE_COMPONENT_RANGE')
        self.assertEqual(code_of(self.read, [(33, 1), (47, 1), (60, 0)]), 'GPS_COORDINATE_MALFORMED')
        self.assertEqual(code_of(self.read, [(90, 1), (0, 1), (1, 1)]), 'GPS_COORDINATE_RANGE')
        self.assertEqual(code_of(self.read, [(181, 1), (0, 1), (0, 1)], 'E', 'lon'), 'GPS_COORDINATE_RANGE')
        self.assertEqual(code_of(self.read, [(1, 1), (0, 1)]), 'GPS_COORDINATE_MALFORMED')
        self.assertEqual(code_of(self.read, [(1, 1), (0, 1), (-1, 1)]), 'GPS_COORDINATE_MALFORMED')
        self.assertEqual(code_of(self.read, [(1, 1), (0, 1), (0, 1)], 'E'), 'GPS_COORDINATE_REF')
        self.assertEqual(code_of(self.read, [(1, 1), (0, 1), (0, 1)], ''), 'GPS_COORDINATE_REF')

    def test_R60i_fractional_forms_read_only_with_zero_tails(self):
        self.assertEqual(self.read([(35, 1), (15, 2), (0, 1)])['degrees'], F(35) + F(15, 2) / 60)            # 35.125
        self.assertEqual(self.read([(35, 1), (15, 2), (0, 1)])['degrees'], F(281, 8))
        self.assertEqual(self.read([(71, 2), (0, 1), (0, 1)])['degrees'], F(71, 2))
        self.assertEqual(code_of(self.read, [(71, 2), (1, 1), (0, 1)]), 'GPS_COORDINATE_MALFORMED')
        self.assertEqual(code_of(self.read, [(35, 1), (15, 2), (1, 1)]), 'GPS_COORDINATE_MALFORMED')

    def test_R60i_fails_a_target_proof(self):
        problems = loc.exif_target_problems([(35, 1), (15, 2), (0, 1)], 'N', D('35.125'), 'lat', '$.at')
        self.assertTrue(any('integral' in p[1] for p in problems))


class ExifTargetProof(unittest.TestCase):
    """Native-observed stored values (supplement L7') proved against the requested decimals."""
    OBSERVED = [('35.123456789', [(35, 1), (7, 1), (671611, 27475)], 'N', 'lat'), ('179.999999', [(179, 1), (59, 1), (83335, 1389)], 'E', 'lon'),
                ('9.87654321', [(9, 1), (52, 1), (8888889, 250000)], 'N', 'lat'), ('0.000000001', [(0, 1), (0, 1), (9, 2500000)], 'N', 'lat'),
                ('33.8', [(33, 1), (47, 1), (60, 1)], 'N', 'lat'), ('0', [(0, 1), (0, 1), (0, 1)], 'N', 'lat')]

    def test_observed_values_pass(self):
        for text, stored, ref, axis in self.OBSERVED:
            self.assertEqual(loc.exif_target_problems(stored, ref, D(text), axis, '$.at'), [], text)

    def test_M_L1_one_input_unit_is_detected(self):
        # stored seconds altered to represent requested +/- 1e-9 degrees: separation >= 8e-10 > 2e-10
        plus = [(35, 1), (7, 1), (671611, 27475)]
        delta_seconds = F(1, 10 ** 9) * 3600                    # 1e-9 degree in arc-seconds
        shifted = F(671611, 27475) + delta_seconds
        mutant = [(35, 1), (7, 1), (shifted.numerator, shifted.denominator)]
        self.assertEqual(loc.exif_target_problems(plus, 'N', D('35.123456789'), 'lat', 'x'), [])
        self.assertEqual([p[0] for p in loc.exif_target_problems(mutant, 'N', D('35.123456789'), 'lat', 'x')], ['READBACK_MISMATCH'])
        lower = F(671611, 27475) - delta_seconds
        self.assertTrue(loc.exif_target_problems([(35, 1), (7, 1), (lower.numerator, lower.denominator)], 'N', D('35.123456789'), 'lat', 'x'))

    def test_M_L0_exact_zero(self):
        # requested latitude 0, stored 9/50000000 seconds (= 5e-11 degrees, inside the bound) -> R-zero mismatch
        problems = loc.exif_target_problems([(0, 1), (0, 1), (9, 50000000)], 'N', D('0'), 'lat', 'x')
        self.assertEqual(len(problems), 1)
        self.assertIn('R-zero', problems[0][1])
        # M-L0b: requested 1e-9 stored as zero
        problems = loc.exif_target_problems([(0, 1), (0, 1), (0, 1)], 'N', D('0.000000001'), 'lat', 'x')
        self.assertIn('R-zero', ' '.join(p[1] for p in problems))

    def test_M_L6_silent_native_misparse_of_a_ratio_is_caught_without_any_warning(self):
        # audit probe p2: '35/1 7/1 6111111/250000' with print conversion on was stored as 35 1 7 (about 0.1 degree away) with no warning
        problems = loc.exif_target_problems([(35, 1), (1, 1), (7, 1)], 'N', D('35.123456789'), 'lat', 'x')
        self.assertEqual(problems[0][0], 'READBACK_MISMATCH')
        self.assertTrue(any('2e-10' in p[1] for p in problems))

    def test_reference_letter_and_sign(self):
        self.assertTrue(loc.exif_target_problems([(33, 1), (47, 1), (60, 1)], 'S', D('33.8'), 'lat', 'x'))           # request was north
        self.assertEqual(loc.exif_target_problems([(33, 1), (47, 1), (60, 1)], 'S', D('-33.8'), 'lat', 'x'), [])
        self.assertTrue(loc.exif_target_problems([(0, 1), (0, 1), (0, 1)], 'S', D('0'), 'lat', 'x'))                 # zero is never S/W

    def test_quantisation_object(self):
        q = loc.quantisation([(35, 1), (7, 1), (671611, 27475)], D('35.123456789'))
        self.assertEqual((q['requested'], q['stored'], q['bound'], q['storedDegreesExact']), ('35.123456789', [[35, 1], [7, 1], [671611, 27475]], '2e-10', False))
        self.assertTrue(q['storedDegrees'].startswith('35.12345678'))
        self.assertEqual(loc.quantisation([(33, 1), (48, 1), (0, 1)], D('33.8'))['storedDegreesExact'], True)


class XmpCoordinates(unittest.TestCase):
    LITERALS = [('35.123456789', 'lat', '35,7.40740734N'), ('-179.999999999', 'lon', '179,59.99999994W'), ('0.000000001', 'lat', '0,0.00000006N'),
                ('-0.000000005', 'lat', '0,0.0000003S'), ('33.8', 'lat', '33,48.0N'), ('35.5', 'lat', '35,30.0N'), ('-120.125', 'lon', '120,7.5W')]

    def test_native_literals_are_predicted_and_decode_exactly(self):
        for text, axis, literal in self.LITERALS:
            self.assertEqual(loc.xmp_literal(D(text), axis), literal, text)
            self.assertEqual(loc.decode_xmp_coordinate(literal, axis), F(D(text)), text)
            self.assertEqual(loc.xmp_target_problems(literal, D(text), axis, 'x'), [], text)

    def test_M_L2_last_minute_digit_is_detected(self):
        self.assertTrue(loc.xmp_target_problems('35,7.40740735N', D('35.123456789'), 'lat', 'x'))     # +1e-8 minutes
        self.assertTrue(loc.xmp_target_problems('35,7.40740734S', D('35.123456789'), 'lat', 'x'))

    def test_forms_and_ranges(self):
        self.assertEqual(loc.decode_xmp_coordinate('35,7,24.5N', 'lat'), F(35) + F(7, 60) + F(49, 2) / 3600)
        self.assertEqual(loc.decode_xmp_coordinate('90,0.0N', 'lat'), 90)
        for bad, axis, code in (('35,7,24.4444404', 'lat', 'GPS_COORDINATE_MALFORMED'), ('35,60.0N', 'lat', 'GPS_COORDINATE_COMPONENT_RANGE'), ('35,7,60N', 'lat', 'GPS_COORDINATE_COMPONENT_RANGE'),
                                ('91,0N', 'lat', 'GPS_COORDINATE_RANGE'), ('35,7E', 'lat', 'GPS_COORDINATE_REF'), ('', 'lat', 'GPS_COORDINATE_MALFORMED'), ('-35,7N', 'lat', 'GPS_COORDINATE_MALFORMED'),
                                ('35,7.5,3N', 'lat', 'GPS_COORDINATE_MALFORMED')):
            self.assertEqual(code_of(loc.decode_xmp_coordinate, bad, axis), code, bad)


class Altitude(unittest.TestCase):
    def test_native_observed_altitudes_pass(self):
        for text, stored in (('1234.567', (119753, 97)), ('12345.678', (728395, 59)), ('8848.86', (442443, 50)), ('0.001', (1, 1000)), ('0', (0, 1)), ('39999.999', (39999999, 1000))):
            self.assertEqual(loc.altitude_target_problems(stored, 2, (D(text), 'seaLevel'), 'x'), [], text)

    def test_M_L3_one_millimetre_at_the_top_of_the_range(self):
        self.assertTrue(loc.altitude_target_problems((39999998, 1000), 2, (D('39999.999'), 'seaLevel'), 'x'))
        self.assertTrue(loc.altitude_target_problems((40000000, 1000), 2, (D('39999.999'), 'seaLevel'), 'x'))
        self.assertTrue(loc.altitude_target_problems((1, 1000), 2, (D('0'), 'seaLevel'), 'x'))                # exact zero
        self.assertTrue(loc.altitude_target_problems((1234, 1), 3, (D('1234'), 'seaLevel'), 'x'))             # sign byte: positive request, ref 3

    def test_reference_bytes(self):
        self.assertEqual([loc.reference_byte('ellipsoidal', False), loc.reference_byte('ellipsoidal', True), loc.reference_byte('seaLevel', False), loc.reference_byte('seaLevel', True)], [0, 1, 2, 3])
        self.assertTrue(loc.altitude_target_problems((1, 1), 0, (D('1'), 'seaLevel'), 'x'))        # M-L4 on a legacy file: ref byte 2 -> 0


class Editions(unittest.TestCase):
    def test_classification_A1(self):
        c = loc.classify_edition
        self.assertEqual(c('0310', [2, 4, 0, 0], True), ('exif3', []))
        self.assertEqual(c('0300', [2, 3, 0, 0], True), ('exif3', ['gpsVersionIdNotUpdated']))       # the CIPA annex layout (L11'a)
        self.assertEqual(c(None, [2, 4, 0, 0], True), ('gpsIfd24', []))                              # L11'b
        self.assertEqual(c('0232', [2, 4, 0, 0], True), ('legacy', ['editionConflict']))             # L11'c
        self.assertEqual(c('0232', [2, 3, 0, 0], True), ('legacy', []))
        self.assertEqual(c(None, [2, 3, 0, 0], True), ('none', []))
        self.assertEqual(c(None, None, False), ('none', []))
        self.assertEqual(c(None, None, True), ('none', []))
        self.assertEqual(c('02x2', None, False), ('legacy', []))                                    # a malformed ExifVersion is never promoted to Exif 3

    def read(self, ref, edition, altitude=F(5), **kw):
        return loc.read_height(ref, altitude, edition, **kw)

    def test_read_matrix(self):
        h = self.read(0, 'exif3')
        self.assertEqual((h['reference'], h['basis'], h['sign']), ('ellipsoidal', 'exif3EllipsoidalRef', 1))
        h = self.read(1, 'gpsIfd24')
        self.assertEqual((h['reference'], h['basis'], h['sign'], h['flags']), ('ellipsoidal', 'gpsVersionIdOnly', -1, ['editionByGpsVersionOnly']))
        h = self.read(0, 'legacy')
        self.assertEqual((h['reference'], h['basis'], h['historicalLabel']), ('unspecified', 'legacyEditionRef', loc.HISTORICAL_LABEL))
        h = self.read(0, 'none')
        self.assertEqual((h['reference'], h['basis']), ('unspecified', 'noEditionRef'))
        h = self.read(2, 'legacy')
        self.assertEqual((h['reference'], h['basis'], h['sign'], h['flags']), ('seaLevel', 'exifSeaLevelRef', 1, ['legacyReadersMayNotRecognise']))
        h = self.read(3, 'exif3')
        self.assertEqual((h['reference'], h['sign'], h['flags']), ('seaLevel', -1, []))
        h = self.read(None, 'exif3')
        self.assertEqual((h['reference'], h['basis'], h['signKnown'], h['sign']), ('unspecified', 'refAbsent', False, None))
        self.assertEqual(code_of(self.read, 4, 'exif3'), 'GPS_ALTITUDE_REF_RESERVED')
        self.assertIsNone(loc.read_height(None, None, 'exif3'))
        h = loc.read_height(0, F(5), 'exif3', xmp='exif')
        self.assertEqual((h['reference'], h['basis']), ('unspecified', 'xmpLegacyRef'))
        h = loc.read_height(2, F(5), 'exif3', xmp='exif')
        self.assertEqual((h['reference'], h['basis']), ('unspecified', 'xmpNonStandardRef'))

    def test_write_matrix_A1(self):
        plan = loc.plan_altitude
        w = plan('ellipsoidal', D('52.317'), 'exif3', False)
        self.assertEqual((w['action'], w['refByte'], w['gpsVersionTarget']), ('write', 0, (2, 4, 0, 0)))          # L14
        w = plan('ellipsoidal', D('-3'), 'exif3', True)
        self.assertEqual((w['action'], w['refByte'], w['gpsVersionTarget']), ('write', 1, None))                   # L22: an existing GPSVersionID stays
        w = plan('ellipsoidal', D('1'), 'gpsIfd24', True)
        self.assertEqual((w['action'], w['gpsVersionTarget']), ('write', None))
        w = plan('ellipsoidal', D('52.317'), 'none', False)                                                        # L20: no ExifVersion, no GPS IFD
        self.assertEqual((w['action'], w['refByte'], w['gpsVersionTarget'], w['infos']), ('write', 0, (2, 4, 0, 0), ['editionByGpsVersionOnly', 'legacyReadersMayNotRecognise']))
        w = plan('ellipsoidal', D('1'), 'none', True)                                                              # L21: GPS IFD present but unedited
        self.assertEqual((w['action'], w['code']), ('refuse', 'ALTITUDE_REFERENCE_NOT_EXPRESSIBLE'))
        w = plan('ellipsoidal', D('1'), 'legacy', False)                                                           # L15
        self.assertEqual((w['action'], w['code']), ('refuse', 'ALTITUDE_REFERENCE_NOT_EXPRESSIBLE'))
        self.assertIn('without converting', w['message'])
        w = plan('ellipsoidal', D('1'), 'legacy', False, 'omitAltitude')
        self.assertEqual((w['action'], w['infos'], w['refByte']), ('omit', ['altitudeOmitted'], None))
        w = plan('seaLevel', D('-430.5'), 'legacy', True)                                                          # L16
        self.assertEqual((w['action'], w['refByte'], w['gpsVersionTarget'], w['infos']), ('write', 3, None, ['legacyReadersMayNotRecognise']))
        w = plan('seaLevel', D('12.5'), 'none', False)                                                             # L1': native default 2.3 stands
        self.assertEqual((w['refByte'], w['gpsVersionTarget']), (2, None))
        w = plan('seaLevel', D('12.5'), 'exif3', False)
        self.assertEqual((w['refByte'], w['gpsVersionTarget'], w['infos']), (2, (2, 4, 0, 0), []))


if __name__ == '__main__':
    unittest.main()
