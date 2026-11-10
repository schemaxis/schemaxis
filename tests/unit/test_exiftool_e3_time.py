"""Host tests of the E3 time arithmetic. Every expectation is a literal written here by hand (calendar facts and exact decimals)."""
from fractions import Fraction
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from schemaxis.adaptors.exiftool import timecalc as tc  # noqa: E402


def code_of(call, *args):
    try:
        call(*args)
    except tc.TimeProblem as error:
        return error.code
    return None


class Calendar(unittest.TestCase):
    def test_leap_day_and_year_rollover_are_exact(self):
        # contract T2: 2024-02-28T23:59:59 + 1 s is a leap day; 2023-12-31T23:59:59.9 + 0.2 s rolls the year with one retained digit
        wall, _ = tc.parse_local('2024-02-28T23:59:59')
        self.assertEqual(tc.local_text(tc.shifted(wall, tc.NS)), '2024-02-29T00:00:00')
        wall, digits = tc.parse_local('2023-12-31T23:59:59.9')
        moved = tc.shifted(wall, tc.duration_ns({'seconds': '0.2'}))
        self.assertEqual(tc.local_text(moved, 1), '2024-01-01T00:00:00.1')
        self.assertEqual(tc.fraction_after(digits, tc.parts(moved)[6]), ('1', False))

    def test_non_leap_february_has_no_29th(self):
        # contract T3: 2023-02-28T12:00:00 + 1 day is 03-01, and 2023-02-29 is an invalid date
        wall, _ = tc.parse_local('2023-02-28T12:00:00')
        self.assertEqual(tc.local_text(tc.shifted(wall, tc.duration_ns({'days': 1}))), '2023-03-01T12:00:00')
        self.assertEqual(code_of(tc.parse_local, '2023-02-29T00:00:00'), 'INVALID_DATE_VALUE')
        self.assertEqual(code_of(tc.parse_local, '1900-02-29T00:00:00'), 'INVALID_DATE_VALUE')   # 1900 is not a leap year
        self.assertEqual(tc.local_text(tc.parse_local('2000-02-29T00:00:00')[0]), '2000-02-29T00:00:00')  # 2000 is

    def test_range_and_leap_seconds(self):
        wall, _ = tc.parse_local('2100-12-31T23:59:59')
        self.assertEqual(code_of(tc.shifted, wall, tc.NS), 'TIME_OUT_OF_RANGE')          # contract T15
        self.assertEqual(tc.local_text(tc.shifted(wall, tc.NS - 1), 9), '2100-12-31T23:59:59.999999999')
        self.assertEqual(code_of(tc.parse_local, '1899-12-31T23:59:59'), 'TIME_OUT_OF_RANGE')
        self.assertEqual(code_of(tc.parse_local, '2016-12-31T23:59:60'), 'LEAP_SECOND_UNSUPPORTED')
        self.assertEqual(code_of(tc.parse_local, '2026-03-01T12:00'), 'INVALID_ARGUMENT')
        self.assertEqual(code_of(tc.parse_local, '2026-03-01T12:00:00.1234567890'), 'INVALID_ARGUMENT')

    def test_digit_strings_keep_leading_zeros(self):
        wall, digits = tc.parse_local('2026-03-01T12:00:00.05')
        self.assertEqual(digits, '05')
        self.assertEqual(tc.local_text(wall, 2), '2026-03-01T12:00:00.05')
        self.assertEqual(tc.local_text(wall), '2026-03-01T12:00:00.05')


class Offsets(unittest.TestCase):
    def test_offsets(self):
        self.assertEqual(tc.parse_offset('+09:00'), 540)
        self.assertEqual(tc.parse_offset('-12:00'), -720)
        self.assertEqual(tc.parse_offset('+14:00'), 840)
        self.assertEqual(tc.parse_offset('+05:30'), 330)
        self.assertEqual(tc.parse_offset('+00:00'), 0)
        for bad in ('-00:00', '+14:01', '-12:01', '+9:00', '+09:60', '09:00', 'Z'):
            self.assertEqual(code_of(tc.parse_offset, bad), 'INVALID_ARGUMENT', bad)
        self.assertEqual(tc.offset_text(-210), '-03:30')

    def test_instant_is_wall_minus_offset(self):
        wall, _ = tc.parse_local('2026-03-01T12:00:00')
        self.assertEqual(tc.local_text(tc.instant(wall, 60)), '2026-03-01T11:00:00')
        self.assertEqual(tc.local_text(tc.instant(wall, -330)), '2026-03-01T17:30:00')


class Shifts(unittest.TestCase):
    def test_duration_forms_normalise_to_one_exact_value(self):
        self.assertEqual(tc.duration_ns({'seconds': '-3725.5'}), -3725500000000)
        self.assertEqual(tc.duration_ns({'days': 1, 'hours': -2, 'minutes': 0, 'seconds': '3.25'}), (86400 - 7200) * tc.NS + 3250000000)
        self.assertEqual(tc.seconds_text(tc.duration_ns({'hours': -1, 'seconds': '-0.001'})), '-3600.001')
        self.assertEqual(code_of(tc.duration_ns, {'months': 1}), 'INVALID_ARGUMENT')
        self.assertEqual(code_of(tc.duration_ns, {'hours': 1.5}), 'INVALID_ARGUMENT')
        self.assertEqual(code_of(tc.duration_ns, {'seconds': '1e3'}), 'INVALID_ARGUMENT')
        self.assertEqual(code_of(tc.duration_ns, {'days': 36525 + 1}), 'SHIFT_OUT_OF_RANGE')
        self.assertEqual(code_of(tc.duration_ns, {}), 'INVALID_ARGUMENT')

    def test_fraction_extension_and_retention(self):
        # contract 2.4: "12" + 0.5 s -> "62" (two digits kept); "5" + 0.25 s -> "75" (extended, never rounded)
        self.assertEqual(tc.fraction_after('12', 620000000), ('62', False))
        self.assertEqual(tc.fraction_after('5', 750000000), ('75', True))
        self.assertEqual(tc.fraction_after('', 0), ('', False))
        self.assertEqual(tc.fraction_after('', 250000000), ('25', True))
        self.assertEqual(tc.fraction_after('12', 0), ('00', False))

    def test_contract_T1_skew_literal(self):
        # recorded 12:00:00.12 at +01:00 vs true 12:05:30.5 at +01:00 : instantSkew = -330.38 s (the camera is behind)
        recorded = tc.parse_local('2026-03-01T12:00:00.12')[0]
        truth = tc.parse_local('2026-03-01T12:05:30.5')[0]
        skew = tc.instant(recorded, 60) - tc.instant(truth, 60)
        self.assertEqual(tc.seconds_text(skew), '-330.38')


class Statistics(unittest.TestCase):
    def test_exact_median(self):
        self.assertEqual(tc.median([Fraction(3), Fraction(1), Fraction(2)]), 2)
        self.assertEqual(tc.median([Fraction(1), Fraction(4)]), Fraction(5, 2))
        self.assertEqual(tc.median([Fraction(1, 3), Fraction(2, 3)]), Fraction(1, 2))

    def test_decimal_text_is_exact_or_marked_inexact(self):
        self.assertEqual(tc.decimal_text(Fraction(25, 2)), ('12.5', True))
        self.assertEqual(tc.decimal_text(Fraction(-1, 3), 12), ('-0.333333333333', False))
        self.assertEqual(tc.decimal_text(Fraction(0)), ('0', True))


if __name__ == '__main__':
    unittest.main()
