"""Exact calendar and duration arithmetic of the time workflows (host-only, standard library, no binary floating point).

A *wall* value is a reading of a clock on the proleptic Gregorian calendar, held as an integer number of nanoseconds since 1970-01-01T00:00:00
counted as if the reading were UTC; an *offset* is an integer number of minutes east of UTC. A recorded instant is ``wall - offset``. Nothing here
knows a time zone, a daylight-saving rule or a leap second: second ``60`` is refused wherever it appears, and durations are counted on the
leap-second-free (POSIX) scale.
"""
from datetime import date
from fractions import Fraction
import re

NS = 10 ** 9
EPOCH = date(1970, 1, 1).toordinal()
MIN_YEAR, MAX_YEAR = 1900, 2100
MIN_NS = (date(MIN_YEAR, 1, 1).toordinal() - EPOCH) * 86400 * NS
MAX_NS = (date(MAX_YEAR, 12, 31).toordinal() - EPOCH + 1) * 86400 * NS - 1
OFFSET_MIN, OFFSET_MAX = -12 * 60, 14 * 60
MAX_SHIFT_SECONDS = 3155760000          # 100 Julian years
LOCAL = re.compile(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?', re.ASCII)
OFFSET = re.compile(r'([+-])(\d{2}):(\d{2})', re.ASCII)
DECIMAL_SECONDS = re.compile(r'([+-]?)(\d{1,10})(?:\.(\d{1,9}))?', re.ASCII)


class TimeProblem(ValueError):
    """A refused time value with a stable code from the E3 contract."""

    def __init__(self, code, message, **observed):
        super().__init__(message)
        self.code, self.message, self.observed = code, message, observed


def from_parts(year, month, day, hour, minute, second, fraction_ns=0):
    """Wall nanoseconds of validated calendar parts; second 60 is refused, years outside 1900-2100 are out of range."""
    if second == 60:
        raise TimeProblem('LEAP_SECOND_UNSUPPORTED', 'second 60 (a leap second) is not supported; no leap-second table is used')
    if not (MIN_YEAR <= year <= MAX_YEAR):
        raise TimeProblem('TIME_OUT_OF_RANGE', 'years %d to %d are supported' % (MIN_YEAR, MAX_YEAR), year=year)
    if not (1 <= month <= 12 and 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59 and 0 <= fraction_ns < NS):
        raise TimeProblem('INVALID_DATE_VALUE', 'month, hour, minute, second or fraction is out of range')
    try:
        ordinal = date(year, month, day).toordinal()
    except ValueError:
        raise TimeProblem('INVALID_DATE_VALUE', 'the calendar has no such day', year=year, month=month, day=day)
    return ((ordinal - EPOCH) * 86400 + hour * 3600 + minute * 60 + second) * NS + fraction_ns


def parts(wall):
    """``(year, month, day, hour, minute, second, fraction_ns)`` of wall nanoseconds."""
    if not isinstance(wall, int) or not MIN_NS <= wall <= MAX_NS:
        raise TimeProblem('TIME_OUT_OF_RANGE', 'the result is outside 1900-01-01T00:00:00 .. 2100-12-31T23:59:59.999999999')
    seconds, fraction = divmod(wall, NS)
    days, rest = divmod(seconds, 86400)
    d = date.fromordinal(days + EPOCH)
    return d.year, d.month, d.day, rest // 3600, rest % 3600 // 60, rest % 60, fraction


def unbounded_text(ns):
    """ISO text of a UTC instant that may lie outside the supported 1900-2100 range (a proposal is allowed to fall there; a written value is not)."""
    seconds, fraction = divmod(ns, NS)
    days, rest = divmod(seconds, 86400)
    try:
        d = date.fromordinal(days + EPOCH)
    except (ValueError, OverflowError):
        raise TimeProblem('TIME_OUT_OF_RANGE', 'the instant is outside the proleptic Gregorian years 1 to 9999')
    base = '%04d-%02d-%02dT%02d:%02d:%02d' % (d.year, d.month, d.day, rest // 3600, rest % 3600 // 60, rest % 60)
    digits = ('%09d' % fraction).rstrip('0')
    return base + ('.' + digits if digits else '')


def parse_local(text, field='value'):
    """``YYYY-MM-DDThh:mm:ss[.f{1,9}]`` to ``(wall_ns, fraction_digits)``; the digit string keeps its length (``05`` is not ``5``)."""
    match = LOCAL.fullmatch(text) if isinstance(text, str) else None
    if not match:
        raise TimeProblem('INVALID_ARGUMENT', 'use YYYY-MM-DDThh:mm:ss with an optional fraction of at most 9 digits', field=field)
    y, mo, d, h, mi, s = (int(match.group(i)) for i in range(1, 7))
    digits = match.group(7) or ''
    return from_parts(y, mo, d, h, mi, s, int(digits.ljust(9, '0')) if digits else 0), digits


def local_text(wall, digits=None):
    """The canonical text of a wall value. ``digits`` is the fraction digit count to print (``None``: the minimal exact count, at most 9)."""
    y, mo, d, h, mi, s, f = parts(wall)
    base = '%04d-%02d-%02dT%02d:%02d:%02d' % (y, mo, d, h, mi, s)
    if digits is None:
        digits = len(('%09d' % f).rstrip('0'))
    if digits == 0:
        if f:
            raise TimeProblem('INTERNAL', 'a fraction cannot be printed with zero digits')
        return base
    text = '%09d' % f
    if text[digits:].strip('0'):
        raise TimeProblem('INTERNAL', 'the fraction needs more digits than requested')
    return base + '.' + text[:digits]


def parse_offset(text, field='offset'):
    """``+hh:mm`` / ``-hh:mm`` to minutes (-12:00 .. +14:00). ``-00:00`` is refused: it is not an offset a device may record."""
    match = OFFSET.fullmatch(text) if isinstance(text, str) else None
    if not match:
        raise TimeProblem('INVALID_ARGUMENT', 'use +hh:mm or -hh:mm', field=field)
    sign, hours, minutes = match.group(1), int(match.group(2)), int(match.group(3))
    if minutes > 59:
        raise TimeProblem('INVALID_ARGUMENT', 'offset minutes must be 00 to 59', field=field)
    value = (hours * 60 + minutes) * (-1 if sign == '-' else 1)
    if text == '-00:00':
        raise TimeProblem('INVALID_ARGUMENT', '-00:00 is not an offset', field=field)
    if not OFFSET_MIN <= value <= OFFSET_MAX:
        raise TimeProblem('INVALID_ARGUMENT', 'offsets run from -12:00 to +14:00', field=field)
    return value


def offset_text(minutes):
    sign = '-' if minutes < 0 else '+'
    return '%s%02d:%02d' % (sign, abs(minutes) // 60, abs(minutes) % 60)


def parse_utc(text, field='trueUtc'):
    """``YYYY-MM-DDThh:mm:ss[.f]Z`` to UTC nanoseconds."""
    if not isinstance(text, str) or not text.endswith('Z'):
        raise TimeProblem('INVALID_ARGUMENT', 'a UTC instant must end in Z', field=field)
    return parse_local(text[:-1], field)[0]


def instant(wall, offset_minutes):
    """The UTC instant (nanoseconds, unbounded in range) of a wall value recorded with an offset."""
    return wall - offset_minutes * 60 * NS


def duration_ns(value, field='shift'):
    """A signed fixed-length duration to nanoseconds.

    ``{"seconds": "-3725.5"}`` or ``{"days": 1, "hours": -2, "minutes": 0, "seconds": "3.25"}``: integers except the seconds, a decimal string with at most
    9 fractional digits. There are no month or year shifts: those are calendar operations, not durations.
    """
    if not isinstance(value, dict) or not value or not set(value) <= {'days', 'hours', 'minutes', 'seconds'}:
        raise TimeProblem('INVALID_ARGUMENT', 'a shift has days, hours, minutes and/or seconds', field=field)
    total = 0
    for unit, scale in (('days', 86400), ('hours', 3600), ('minutes', 60)):
        if unit in value:
            if type(value[unit]) is not int:
                raise TimeProblem('INVALID_ARGUMENT', unit + ' must be an integer', field=field + '.' + unit)
            total += value[unit] * scale * NS
    if 'seconds' in value:
        total += seconds_ns(value['seconds'], field + '.seconds')
    if abs(total) > MAX_SHIFT_SECONDS * NS:
        raise TimeProblem('SHIFT_OUT_OF_RANGE', 'a shift is at most %d seconds (100 Julian years)' % MAX_SHIFT_SECONDS, field=field)
    return total


def seconds_ns(text, field='seconds'):
    """A decimal-string number of seconds (at most 9 fractional digits) to nanoseconds, exactly."""
    match = DECIMAL_SECONDS.fullmatch(text) if isinstance(text, str) else None
    if not match:
        raise TimeProblem('INVALID_ARGUMENT', 'use a decimal string with at most 9 fractional digits', field=field)
    magnitude = int(match.group(2)) * NS + int((match.group(3) or '').ljust(9, '0') or '0')
    return -magnitude if match.group(1) == '-' else magnitude


def seconds_text(ns):
    """Exact decimal text of a nanosecond count as seconds (``-330.38``): no float, minimal digits."""
    sign = '-' if ns < 0 else ''
    whole, frac = divmod(abs(ns), NS)
    text = ('%09d' % frac).rstrip('0')
    return sign + str(whole) + ('.' + text if text else '')


def shifted(wall, delta):
    """Wall nanoseconds moved by a duration; leaving the supported range is ``TIME_OUT_OF_RANGE``."""
    result = wall + delta
    if not MIN_NS <= result <= MAX_NS:
        raise TimeProblem('TIME_OUT_OF_RANGE', 'the corrected time leaves 1900-2100', before=local_text(wall))
    return result


def fraction_after(original_digits, new_fraction_ns):
    """The digit string of a shifted fraction: the original digit count when that is exact, else the minimal count (at most 9). Never rounded.

    Returns ``(digits, extended)``; ``digits`` is ``''`` when the value has no fraction and none was recorded.
    """
    minimal = len(('%09d' % new_fraction_ns).rstrip('0'))
    if not original_digits and not new_fraction_ns:
        return '', False
    if len(original_digits) >= minimal:
        return ('%09d' % new_fraction_ns)[:len(original_digits)], False
    return ('%09d' % new_fraction_ns)[:minimal], True


def median(values):
    """The exact median of Fractions (the mean of the two middle values for an even count)."""
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        raise ValueError('median of nothing')
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2


def seconds_fraction(ns):
    return Fraction(ns, NS)


def decimal_text(value, places=9):
    """Exact decimal text of a Fraction, cut at ``places`` decimals; ``(text, exact)``."""
    sign = '-' if value < 0 else ''
    value = abs(value)
    whole = value.numerator // value.denominator
    rest = value - whole
    digits, exact = [], True
    for _ in range(places):
        rest *= 10
        d = rest.numerator // rest.denominator
        digits.append(str(d))
        rest -= d
        if not rest:
            break
    else:
        exact = not rest
    text = ''.join(digits).rstrip('0')
    return sign + str(whole) + ('.' + text if text else ''), exact
