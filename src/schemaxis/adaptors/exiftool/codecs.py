"""Value codecs and native anchors named by the field catalogue (standard library only).

A codec turns one located payload value into a canonical Python value or raises ``ValueProblem`` (present but malformed),
``Unsupported`` (well-formed but outside this codec) or ``Ambiguous``. Canonical values: str, int, Fraction, tuple of str. Each codec
also has an anchor: the comparison of its value with what the pinned native ExifTool reported for the same bytes under fixed ``-n``
options. Text and integer anchors are exact. A native RATIONAL64 is ExifTool's own ``sprintf("%.10g", n/d)`` of the stored fraction, and a
native GPS degree value is the sum of three such rounded parts printed with 15 digits, so numeric anchors accept exactly that rounding
and nothing wider: no absolute floor, and a zero must be an exact zero. Digit patterns are ASCII-only (``re.ASCII``): a bare digit class also
matches other Unicode decimal digits, which ``int()`` would then accept.
"""
import datetime
from fractions import Fraction
import re

DATE_TIME = re.compile(r'(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})', re.ASCII)
OFFSET = re.compile(r'([+-])(\d{2}):(\d{2})', re.ASCII)
XMP_DATE = re.compile(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})?', re.ASCII)
NATIVE_DATE = re.compile(r'(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?', re.ASCII)
IPTC_DATE = re.compile(r'(\d{4})(\d{2})(\d{2})', re.ASCII)
IPTC_TIME = re.compile(r'(\d{2})(\d{2})(\d{2})(?:([+-])(\d{2})(\d{2}))?', re.ASCII)
GPS_DATE = re.compile(r'(\d{4}):(\d{2}):(\d{2})', re.ASCII)
XMP_INTEGER = re.compile(r'-?\d{1,18}', re.ASCII)
XMP_REDUCED_DATE = re.compile(r'\d{4}(-\d{2}(-\d{2}(T\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})?)?)?)?', re.ASCII)
SUBSECOND = re.compile(r'\d{1,9}', re.ASCII)
NATIVE_NUMBER = re.compile(r'-?(?:0|[1-9][0-9]{0,29})(?:\.[0-9]{1,30})?(?:[eE][+-]?[0-9]{1,3})?', re.ASCII)
SIGNIFICANT = 10            # ExifTool 13.55 GetRational64u/s: RoundFloat(n/d, 10) = sprintf("%.10g")
BINARY_SLACK = Fraction(1, 2 ** 50)     # a few binary64 ulps: the Perl division of two integers and a 10-digit print of it
DEGREES_SLACK = Fraction(1, 10 ** 14)   # the binary64 sum of three parts and the 15-digit print of the result (5e-15 at worst)
ORIENTATIONS = {1: 'top-left', 2: 'top-right', 3: 'bottom-right', 4: 'bottom-left', 5: 'left-top', 6: 'right-top', 7: 'right-bottom', 8: 'left-bottom'}


class ValueProblem(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


class Unsupported(ValueProblem):
    pass


class Ambiguous(ValueProblem):
    pass


class Repeated(Ambiguous):
    """A companion tag (a GPS reference) that the file repeats: the reader cannot say which copy applies, and native lists every copy."""

    def __init__(self, code, message, companion, instances, values):
        super().__init__(code, message)
        self.companion, self.instances, self.values = companion, instances, values


class Missing(ValueProblem):
    """A well-formed value that simply does not record this component (reported as absent, with the reason)."""


# ---------------------------------------------------------------- calendar helpers (shared with derivation and audit)
def valid_calendar(year, month, day, hour, minute, second, field):
    try:
        datetime.datetime(year, month, day, hour, minute, second)
    except ValueError:
        raise ValueProblem('INVALID_DATE_VALUE', field + ' is not a valid calendar date and time')
    if not 1900 <= year <= 2100:
        raise ValueProblem('INVALID_DATE_VALUE', field + ' is outside the years 1900 to 2100')
    return '%04d-%02d-%02dT%02d:%02d:%02d' % (year, month, day, hour, minute, second)


def check_offset(sign, hours, minutes, field):
    total = int(hours) * 60 + int(minutes)
    if int(minutes) > 59 or total > 14 * 60 or (sign == '-' and total > 12 * 60):
        raise ValueProblem('INVALID_OFFSET_VALUE', field + ' is outside -12:00 to +14:00 or has minutes above 59')
    if sign == '-' and total == 0:
        raise ValueProblem('INVALID_OFFSET_VALUE', field + ' is -00:00, which means an unknown offset, and is not published as UTC')
    return '%s%02d:%02d' % (sign, int(hours), int(minutes))


def offset_minutes(text):
    return (-1 if text[0] == '-' else 1) * (int(text[1:3]) * 60 + int(text[4:6]))


def to_utc(local, offset):
    """Exact UTC instant text from a canonical local time and offset: 'YYYY-MM-DDTHH:MM:SSZ'."""
    naive = datetime.datetime.strptime(local, '%Y-%m-%dT%H:%M:%S') - datetime.timedelta(minutes=offset_minutes(offset))
    return naive.strftime('%Y-%m-%dT%H:%M:%SZ')


def exact_text(value):
    return str(value.numerator) if value.denominator == 1 else '%d/%d' % (value.numerator, value.denominator)


def number(value):
    """JSON-friendly number for a Fraction: int when whole, otherwise a float."""
    return value.numerator if value.denominator == 1 else float(value)


# ---------------------------------------------------------------- EXIF codecs: (entry, companion) -> canonical value
def exif_text(entry, multi=False):
    if entry.kind != 2 or entry.raw is None:
        raise ValueProblem('EXIF_TYPE_MISMATCH', 'the value is not an ASCII entry' if entry.raw is not None else 'the value is beyond the byte budget')
    raw = entry.raw
    parts = raw.split(b'\0')
    if parts and parts[-1] == b'':
        parts = parts[:-1]
    if not multi:
        if len(parts) > 1:
            raise ValueProblem('EXIF_TEXT_MULTIPLE', 'the ASCII value holds more than one string')
        parts = parts[:1]
    decoded = []
    for part in parts or [b'']:
        try:
            decoded.append(part.decode('ascii'))
        except UnicodeDecodeError:
            try:
                decoded.append(part.decode('utf-8'))
            except UnicodeDecodeError:
                raise ValueProblem('EXIF_TEXT_ENCODING', 'the ASCII value is neither ASCII nor UTF-8')
    return '\n'.join(decoded)


SEPARATOR = '; '


def artist_quote(item):
    """MWG 5.7: an item is quoted when it contains the separator or starts with a quote, and inner quotes are doubled."""
    return '"' + item.replace('"', '""') + '"' if SEPARATOR in item or item.startswith('"') else item


def artist_join(items): return SEPARATOR.join(artist_quote(i) for i in items)


def artist_split(raw):
    """Split an EXIF Artist string into creator items (MWG 5.7). The result must re-join to exactly ``raw`` or the string is not canonical."""
    items, position, size = [], 0, len(raw)
    while True:
        if raw.startswith('"', position):
            position += 1
            chunk = []
            while True:
                end = raw.find('"', position)
                if end < 0:
                    raise ValueProblem('EXIF_ARTIST_NONCANONICAL', 'the Artist string has an unterminated quoted item')
                chunk.append(raw[position:end])
                if raw.startswith('""', end):
                    chunk.append('"')
                    position = end + 2
                    continue
                position = end + 1
                break
            items.append(''.join(chunk))
            if position == size:
                break
            if not raw.startswith(SEPARATOR, position):
                raise ValueProblem('EXIF_ARTIST_NONCANONICAL', 'a quoted Artist item is not followed by the separator')
            position += len(SEPARATOR)
        else:
            end = raw.find(SEPARATOR, position)
            if end < 0:
                items.append(raw[position:])
                break
            items.append(raw[position:end])
            position = end + len(SEPARATOR)
        if position == size:
            raise ValueProblem('EXIF_ARTIST_NONCANONICAL', 'the Artist string ends with a separator (an empty item)')
    if any(item == '' for item in items) and len(items) > 1:
        raise ValueProblem('EXIF_ARTIST_NONCANONICAL', 'the Artist string holds an empty item')
    if artist_join(items) != raw:
        raise ValueProblem('EXIF_ARTIST_NONCANONICAL', 'the Artist string does not re-join from its items, so its split is not unambiguous')
    return tuple(items)


def exif_artist_list(entry, companion=None):
    return artist_split(exif_text(entry))


def exif_integer(entry, companion=None):
    values = entry.values()
    if values is None or len(values) != 1 or entry.kind not in (1, 3, 4):
        raise ValueProblem('EXIF_TYPE_MISMATCH', 'expected one BYTE, SHORT or LONG value')
    return values[0]


def exif_rational(entry, companion=None, signed=False):
    values = entry.values()
    if values is None or len(values) != 1 or entry.kind != (10 if signed else 5):
        raise ValueProblem('EXIF_TYPE_MISMATCH', 'expected one %sRATIONAL value' % ('S' if signed else ''))
    n, d = values[0]
    if d == 0:
        raise ValueProblem('EXIF_RATIONAL_UNDEFINED', 'the rational has a zero denominator')
    return Fraction(n, d)


def exif_srational(entry, companion=None):
    return exif_rational(entry, companion, True)


def exif_datetime(entry, companion=None):
    text = exif_text(entry)
    match = DATE_TIME.fullmatch(text)
    if not match:
        raise ValueProblem('INVALID_DATE_VALUE', 'the date must be exactly YYYY:MM:DD HH:MM:SS')
    return valid_calendar(*map(int, match.groups()), 'the date')


def exif_offset(entry, companion=None):
    text = exif_text(entry)
    match = OFFSET.fullmatch(text)
    if not match:
        raise ValueProblem('INVALID_OFFSET_VALUE', 'the offset must be exactly +HH:MM or -HH:MM')
    return check_offset(*match.groups(), 'the offset')


def exif_subsecond(entry, companion=None):
    text = exif_text(entry)
    if not SUBSECOND.fullmatch(text):
        raise ValueProblem('INVALID_SUBSECOND_VALUE', 'the sub-second digits must be 1 to 9 ASCII digits')
    return text


def exif_orientation(entry, companion=None):
    value = exif_integer(entry)
    if entry.kind != 3 or not 1 <= value <= 8:
        raise ValueProblem('INVALID_ORIENTATION', 'the orientation must be one SHORT code from 1 to 8')
    return value


def gps_triple(entry):
    values = entry.values()
    if values is None or entry.kind != 5 or len(values) != 3:
        raise ValueProblem('EXIF_TYPE_MISMATCH', 'expected three RATIONAL values')
    if any(d == 0 for _, d in values):
        raise ValueProblem('EXIF_RATIONAL_UNDEFINED', 'a rational has a zero denominator')
    return [Fraction(n, d) for n, d in values]


def gps_coordinate(entry, companion, axis):
    degrees, minutes, seconds = gps_triple(entry)
    ref_entry = companion('ref')
    if ref_entry is None:
        raise ValueProblem('GPS_REF_MISSING', 'the latitude or longitude has no N/S or E/W reference tag')
    ref = exif_text(ref_entry)
    allowed = ('N', 'S') if axis == 'lat' else ('E', 'W')
    if ref not in allowed:
        raise ValueProblem('GPS_REF_INVALID', 'the reference must be ' + ' or '.join(allowed))
    limit = 90 if axis == 'lat' else 180
    if degrees < 0 or minutes < 0 or seconds < 0 or minutes >= 60 or seconds >= 60 or degrees + minutes / 60 + seconds / 3600 > limit:
        raise ValueProblem('GPS_RANGE', 'degrees, minutes or seconds are outside the valid range')
    total = degrees + minutes / 60 + seconds / 3600
    return -total if ref in ('S', 'W') else total


def gps_latitude(entry, companion): return gps_coordinate(entry, companion, 'lat')
def gps_longitude(entry, companion): return gps_coordinate(entry, companion, 'lon')


def gps_altitude(entry, companion):
    value = exif_rational(entry)
    ref_entry = companion('ref')
    ref = 0 if ref_entry is None else exif_integer(ref_entry)
    if ref not in (0, 1) or value < 0:
        raise ValueProblem('GPS_ALTITUDE_REF', 'the altitude reference must be 0 (above sea level) or 1 (below), with an absolute altitude')
    return -value if ref else value


def gps_bearing(entry, companion):
    value = exif_rational(entry)
    if not 0 <= value < 360:
        raise ValueProblem('GPS_RANGE', 'the direction must be from 0 up to but not including 360 degrees')
    return value


def gps_time(entry, companion=None):
    h, m, s = gps_triple(entry)
    if h < 0 or m < 0 or s < 0 or h >= 24 or m >= 60 or s >= 60:
        raise ValueProblem('GPS_RANGE', 'the UTC time is outside 00:00:00 to 23:59:59')
    if h.denominator != 1 or m.denominator != 1 or s.denominator != 1:
        raise Unsupported('GPS_FRACTIONAL_TIME', 'fractional UTC time components are not published')
    return '%02d:%02d:%02d' % (h, m, s)


def gps_date(entry, companion=None):
    text = exif_text(entry)
    match = GPS_DATE.fullmatch(text)
    if not match:
        raise ValueProblem('INVALID_DATE_VALUE', 'the GPS date must be YYYY:MM:DD')
    return valid_calendar(*map(int, match.groups()), 0, 0, 0, 'the GPS date')[:10]


def exif_enum(entry, companion=None, values=None):
    text = exif_text(entry)
    if text not in values:
        raise ValueProblem('ENUM_INVALID', 'the value is not one of ' + ', '.join(sorted(values)))
    return values[text]


# ---------------------------------------------------------------- XMP codecs: (occurrence) -> canonical value
def xmp_simple(occurrence):
    if occurrence['kind'] == 'struct':
        raise Unsupported('XMP_STRUCTURE', 'a structured value is not read for this field')
    if occurrence['kind'] == 'list':
        raise Unsupported('XMP_SHAPE', 'an array was found where one value is expected')
    return occurrence


def xmp_text(occurrence):
    occurrence = xmp_simple(occurrence)
    if occurrence['kind'] == 'langAlt':
        raise Unsupported('XMP_SHAPE', 'a language alternative was found where one value is expected')
    return occurrence['value']


def xmp_lang_default(occurrence):
    occurrence = xmp_simple(occurrence)
    if occurrence['kind'] == 'text':
        return occurrence['value']
    if occurrence['value'] is None:
        raise ValueProblem('XMP_LANG_DUPLICATE', 'a language alternative repeats a language')
    if 'x-default' not in occurrence['value']:
        raise Unsupported('XMP_NO_DEFAULT_LANGUAGE', 'no x-default alternative (only other languages are present)')
    return occurrence['value']['x-default']


def xmp_list(occurrence):
    if occurrence['kind'] == 'struct':
        raise Unsupported('XMP_STRUCTURE', 'a structured value is not read for this field')
    if occurrence['kind'] != 'list':
        raise Unsupported('XMP_SHAPE', 'a single value was found where an array is expected')
    return tuple(occurrence['value'])


def xmp_integer(occurrence):
    text = xmp_text(occurrence)
    if not XMP_INTEGER.fullmatch(text):
        raise ValueProblem('XMP_INTEGER_INVALID', 'the value is not an integer')
    return int(text)


def xmp_date_parts(occurrence):
    text = xmp_text(occurrence)
    match = XMP_DATE.fullmatch(text)
    if not match:
        if XMP_REDUCED_DATE.fullmatch(text):
            raise Unsupported('XMP_DATE_REDUCED_PRECISION', 'the date lacks seconds, so it cannot be compared with a full capture time')
        raise ValueProblem('XMP_DATE_INVALID', 'the value is not an ISO 8601 date and time')
    y, mo, d, h, mi, s, fraction, zone = match.groups()
    local = valid_calendar(int(y), int(mo), int(d), int(h), int(mi), int(s), 'the date')
    offset = None
    if zone == 'Z':
        offset = '+00:00'
    elif zone:
        offset = check_offset(zone[0], zone[1:3], zone[4:6], 'the offset')
    return local, offset, fraction


def xmp_date_local(occurrence): return xmp_date_parts(occurrence)[0]


def xmp_date_offset(occurrence):
    offset = xmp_date_parts(occurrence)[1]
    if offset is None:
        raise Missing('XMP_NO_OFFSET', 'the date records no offset')
    return offset


def xmp_date_fraction(occurrence):
    fraction = xmp_date_parts(occurrence)[2]
    if fraction is None:
        raise Missing('XMP_NO_FRACTION', 'the date records no fraction of a second')
    return fraction


# ---------------------------------------------------------------- IPTC codecs: (values, charset, companion) -> canonical value
def iptc_text_of(raw, charset):
    if charset == 'utf-8':
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError:
            raise ValueProblem('IPTC_TEXT_ENCODING', 'the text is not valid UTF-8 although 1:90 declares UTF-8')
    if charset == 'unsupported':
        raise Unsupported('IPTC_CHARSET_UNSUPPORTED', 'the coded character set (1:90) is not UTF-8')
    try:
        return raw.decode('ascii')
    except UnicodeDecodeError:
        raise ValueProblem('IPTC_CHARSET_UNSPECIFIED', 'the text has non-ASCII bytes and no 1:90 coded character set, so its encoding is unknown')


def iptc_text(values, charset, companion=None):
    if len(values) > 1:
        raise Ambiguous('IPTC_REPEATED', 'a single-value dataset is repeated')
    return iptc_text_of(values[0], charset)


def iptc_text_list(values, charset, companion=None):
    return tuple(iptc_text_of(raw, charset) for raw in values)


def iptc_date(raw):
    text = raw.decode('ascii', 'replace')
    match = IPTC_DATE.fullmatch(text)
    if not match:
        raise ValueProblem('INVALID_DATE_VALUE', 'the IPTC date must be CCYYMMDD')
    return valid_calendar(*map(int, match.groups()), 0, 0, 0, 'the IPTC date')[:10]


def iptc_time(raw):
    text = raw.decode('ascii', 'replace')
    match = IPTC_TIME.fullmatch(text)
    if not match:
        raise ValueProblem('INVALID_TIME_VALUE', 'the IPTC time must be HHMMSS or HHMMSS+HHMM')
    h, m, s, sign, oh, om = match.groups()
    if int(h) > 23 or int(m) > 59 or int(s) > 59:
        raise ValueProblem('INVALID_TIME_VALUE', 'the IPTC time is outside 00:00:00 to 23:59:59')
    return '%s:%s:%s' % (h, m, s), (check_offset(sign, oh, om, 'the offset') if sign else None)


def iptc_date_local(values, charset, companion):
    if len(values) > 1:
        raise Ambiguous('IPTC_REPEATED', 'a single-value dataset is repeated')
    date = iptc_date(values[0])
    times = companion('time')
    if times is None:
        raise Unsupported('IPTC_TIME_MISSING', 'the IPTC date has no time-created dataset, so it is not a full capture time')
    if len(times) > 1:
        raise Ambiguous('IPTC_REPEATED', 'a single-value dataset is repeated')
    return date + 'T' + iptc_time(times[0])[0]


def iptc_time_offset(values, charset, companion=None):
    if len(values) > 1:
        raise Ambiguous('IPTC_REPEATED', 'a single-value dataset is repeated')
    offset = iptc_time(values[0])[1]
    if offset is None:
        raise Missing('IPTC_NO_OFFSET', 'the IPTC time records no offset')
    return offset


# ---------------------------------------------------------------- container codecs
def frame_width(frame): return frame['width']
def frame_height(frame): return frame['height']


# ---------------------------------------------------------------- native anchors: (value, native tokens, get, source) -> mismatch text or None
def as_text(token): return str(token)


def anchor_text(value, tokens, get, source):
    if len(tokens) != 1 or as_text(tokens[0]) != value:
        return 'native reports %s, the independent reader decoded %r' % ([as_text(t)[:60] for t in tokens][:3], value[:60])


def anchor_list(value, tokens, get, source):
    flat = []
    for token in tokens:
        flat.extend(token if isinstance(token, list) else [token])
    if len(tokens) != 1 or [as_text(t) for t in flat] != list(value):
        return 'native reports %s, the independent reader decoded %s' % ([as_text(t)[:40] for t in flat][:5], list(value)[:5])


def native_exact(token):
    """Exact value of a native JSON number token, or ``None`` for ``inf``/``undef``, other text and over-long tokens."""
    text = as_text(token)
    return Fraction(text) if len(text) <= 64 and NATIVE_NUMBER.fullmatch(text) else None


def significant_digits(token):
    return len(as_text(token).lower().partition('e')[0].replace('-', '').replace('.', '').strip('0'))


def decimal_exponent(value):
    """floor(log10(value)) of a positive Fraction, by exact integer arithmetic."""
    exponent = len(str(value.numerator)) - len(str(value.denominator))
    return exponent - 1 if value < Fraction(10) ** exponent else exponent


def rounding_bound(value):
    """Largest distance between an exact positive quotient and what ExifTool prints for it: half a unit of the tenth significant digit, plus binary64 slack."""
    return Fraction(1, 2) * Fraction(10) ** (decimal_exponent(value) - SIGNIFICANT + 1) + value * BINARY_SLACK


def mismatch_numeric(value, tokens, wanted):
    return 'native reports %s, the independent reader decoded %s' % ([as_text(t)[:40] for t in tokens][:3], exact_text(wanted) if not isinstance(wanted, str) else wanted)


def anchor_rational(value, tokens, get, source):
    """A native RATIONAL64 is the stored fraction rounded to 10 significant digits. ``anchorAbsolute`` sources (the unsigned GPS magnitude) must also be non-negative."""
    wanted = abs(value) if source.get('anchorAbsolute') else value
    native = native_exact(tokens[0]) if len(tokens) == 1 else None
    ok = native is not None and significant_digits(tokens[0]) <= SIGNIFICANT and (native >= 0 or not source.get('anchorAbsolute'))
    if ok:
        ok = native == 0 if wanted == 0 else abs(native - wanted) <= rounding_bound(abs(wanted))
    if not ok:
        return mismatch_numeric(value, tokens, value)


def anchor_degrees(value, tokens, get, source):
    """A native GPS coordinate is the unsigned sum d + m/60 + s/3600 of three parts rounded to 10 digits, so it is within 5e-10 relative of the exact value."""
    wanted = abs(value)
    native = native_exact(tokens[0]) if len(tokens) == 1 else None
    ok = native is not None and native >= 0 and (native == 0 if wanted == 0 else abs(native - wanted) <= wanted * (Fraction(5, 10 ** 10) + DEGREES_SLACK))
    if not ok:
        return mismatch_numeric(value, tokens, value)


def native_date(token):
    match = NATIVE_DATE.fullmatch(as_text(token))
    if not match:
        return None
    y, mo, d, h, mi, s, fraction, zone = match.groups()
    return '%s-%s-%sT%s:%s:%s' % (y, mo, d, h, mi, s), ('+00:00' if zone == 'Z' else zone), fraction


def anchor_date_part(index):
    def anchor(value, tokens, get, source):
        parsed = native_date(tokens[0]) if len(tokens) == 1 else None
        if parsed is None or parsed[index] != value:
            return 'native reports %s, the independent reader decoded %r' % ([as_text(t)[:40] for t in tokens][:3], value)
    return anchor


def anchor_iptc_date_local(value, tokens, get, source):
    dates, times = tokens, get(source['companionNative']['time'])
    if len(dates) != 1 or len(times) != 1:
        return 'native does not report exactly one IPTC date and time'
    text = '%sT%s' % (as_text(dates[0]).replace(':', '-'), as_text(times[0])[:8])
    if text != value:
        return 'native reports %s, the independent reader decoded %r' % (text, value)


def anchor_iptc_time_offset(value, tokens, get, source):
    text = as_text(tokens[0]) if len(tokens) == 1 else ''
    if len(text) < 14 or text[8:] != value:
        return 'native reports %s, the independent reader decoded %r' % (text[:20], value)


def anchor_gps_date(value, tokens, get, source):
    if len(tokens) != 1 or as_text(tokens[0]).replace(':', '-') != value:
        return 'native reports %s, the independent reader decoded %r' % ([as_text(t)[:20] for t in tokens][:3], value)


def anchor_enum(value, tokens, get, source):
    mapping = source.get('values', {})
    native = as_text(tokens[0]) if len(tokens) == 1 else None
    if native is None or mapping.get(native) != value:
        return 'native reports %s, the independent reader decoded %r' % ([as_text(t)[:20] for t in tokens][:3], value)


def anchor_artist(value, tokens, get, source):
    joined = artist_join(value)
    if len(tokens) != 1 or as_text(tokens[0]) != joined:
        return 'native reports %s, the independent reader joined %r' % ([as_text(t)[:60] for t in tokens][:3], joined[:60])


def anchor_integer(value, tokens, get, source):
    if len(tokens) != 1 or as_text(tokens[0]) != str(value):
        return 'native reports %s, the independent reader decoded %d' % ([as_text(t)[:20] for t in tokens][:3], value)


# codec name -> (family, decoder, anchor). EXIF decoders take (entry, companion); XMP (occurrence); IPTC (values, charset, companion).
CODECS = {
    'exifText': ('exif', exif_text, anchor_text), 'exifTextMulti': ('exif', lambda e, c=None: exif_text(e, True), anchor_text),
    'exifArtistList': ('exif', exif_artist_list, anchor_artist),
    'exifInteger': ('exif', exif_integer, anchor_integer), 'exifRational': ('exif', exif_rational, anchor_rational),
    'exifSignedRational': ('exif', exif_srational, anchor_rational), 'exifDateTime': ('exif', exif_datetime, anchor_date_part(0)),
    'exifOffset': ('exif', exif_offset, anchor_text), 'exifSubSecond': ('exif', exif_subsecond, anchor_text),
    'exifOrientation': ('exif', exif_orientation, anchor_integer),
    'gpsLatitude': ('exif', gps_latitude, anchor_degrees), 'gpsLongitude': ('exif', gps_longitude, anchor_degrees),
    'gpsAltitude': ('exif', gps_altitude, anchor_rational), 'gpsBearing': ('exif', gps_bearing, anchor_rational),
    'gpsTime': ('exif', gps_time, anchor_text), 'gpsDate': ('exif', gps_date, anchor_gps_date),
    'exifEnum': ('exif', exif_enum, anchor_enum),
    'xmpText': ('xmp', xmp_text, anchor_text), 'xmpLangDefault': ('xmp', xmp_lang_default, anchor_text), 'xmpList': ('xmp', xmp_list, anchor_list),
    'xmpInteger': ('xmp', xmp_integer, anchor_integer),
    'xmpDateLocal': ('xmp', xmp_date_local, anchor_date_part(0)), 'xmpDateOffset': ('xmp', xmp_date_offset, anchor_date_part(1)),
    'xmpDateFraction': ('xmp', xmp_date_fraction, anchor_date_part(2)),
    'iptcText': ('iptc', iptc_text, anchor_text), 'iptcTextList': ('iptc', iptc_text_list, anchor_list),
    'iptcDateLocal': ('iptc', iptc_date_local, anchor_iptc_date_local), 'iptcTimeOffset': ('iptc', iptc_time_offset, anchor_iptc_time_offset),
    'frameWidth': ('container', frame_width, anchor_integer), 'frameHeight': ('container', frame_height, anchor_integer)}


# ---------------------------------------------------------------- E3 codecs (added with the E3 catalogue view; every codec above is unchanged)
# Coordinates: the stored degree/minute/second rationals are summed exactly, seconds of exactly 60 are an accepted non-canonical form (ExifTool stores 33.8 as
# 33/1 47/1 60/1) and minutes of 60 or more are never carried. The frozen gpsLatitude/gpsLongitude codecs keep refusing seconds >= 60 for the E1/E2 fields.
def e3_coordinate(axis):
    def decode(entry, companion):
        from schemaxis.adaptors.exiftool import locations
        components = gps_triple_raw(entry)
        ref_entry = companion('ref')
        if ref_entry is None:
            raise ValueProblem('GPS_REF_MISSING', 'the latitude or longitude has no N/S or E/W reference tag')
        try:
            return locations.decode_exif_coordinate(components, exif_text(ref_entry), axis)['degrees']
        except locations.LocationProblem as problem:
            raise ValueProblem(problem.code, problem.message)
    return decode


def gps_triple_raw(entry):
    values = entry.values()
    if values is None or entry.kind != 5 or len(values) != 3:
        raise ValueProblem('EXIF_TYPE_MISMATCH', 'expected three RATIONAL values')
    return [(int(n), int(d)) for n, d in values]


def xmp_gps_coordinate(axis):
    def decode(occurrence):
        from schemaxis.adaptors.exiftool import locations
        try:
            return locations.decode_xmp_coordinate(xmp_text(occurrence), axis)
        except locations.LocationProblem as problem:
            raise ValueProblem(problem.code, problem.message)
    return decode


def gps_time_exact(entry, companion=None):
    """The GPS UTC time of day with an exact decimal fraction (denominators that divide 10**9); other denominators are unsupported, never rounded."""
    components = gps_triple_raw(entry)
    if any(d == 0 for _, d in components):
        raise ValueProblem('EXIF_RATIONAL_UNDEFINED', 'a rational has a zero denominator')
    h, m, s = (Fraction(n, d) for n, d in components)
    if h < 0 or m < 0 or s < 0 or h >= 24 or m >= 60 or s >= 60:
        raise ValueProblem('GPS_RANGE', 'the UTC time is outside 00:00:00 to 23:59:59.999999999')
    if h.denominator != 1 or m.denominator != 1:
        raise Unsupported('GPS_FRACTIONAL_TIME', 'fractional hours or minutes are not published')
    scaled = s * 10 ** 9
    if scaled.denominator != 1:
        raise Unsupported('GPS_FRACTIONAL_TIME', 'the seconds are not an exact decimal of at most 9 digits')
    whole, fraction = divmod(int(scaled), 10 ** 9)
    digits = ('%09d' % fraction).rstrip('0')
    return '%02d:%02d:%02d' % (h, m, whole) + ('.' + digits if digits else '')


def anchor_xmp_degrees(value, tokens, get, source):
    """Native lists an XMP GPS coordinate as a signed decimal; the exactly decoded literal must agree to 1e-12 degrees."""
    native = native_exact(tokens[0]) if len(tokens) == 1 else None
    if native is None or abs(native - value) > Fraction(1, 10 ** 12):
        return mismatch_numeric(value, tokens, value)


CODECS.update({
    'exifDmsSumE3Latitude': ('exif', e3_coordinate('lat'), anchor_degrees), 'exifDmsSumE3Longitude': ('exif', e3_coordinate('lon'), anchor_degrees),
    'xmpGpsCoordinateLatitude': ('xmp', xmp_gps_coordinate('lat'), anchor_xmp_degrees), 'xmpGpsCoordinateLongitude': ('xmp', xmp_gps_coordinate('lon'), anchor_xmp_degrees),
    'gpsTimeExact': ('exif', gps_time_exact, anchor_text)})


# ---------------------------------------------------------------- E4 codecs (added with the E4 catalogue view; every codec above is unchanged)
# Exact numerator/denominator pairs: a transfer must reproduce the pair, not only its value, so (10, 30) and (1, 3) are different canonical values.
def exif_rational_pair(entry, companion=None, signed=False):
    values = entry.values()
    if values is None or len(values) != 1 or entry.kind != (10 if signed else 5):
        raise ValueProblem('EXIF_TYPE_MISMATCH', 'expected one %sRATIONAL value' % ('S' if signed else ''))
    n, d = values[0]
    if d == 0:
        raise ValueProblem('EXIF_RATIONAL_UNDEFINED', 'the rational has a zero denominator')
    return (int(n), int(d))


def exif_signed_rational_pair(entry, companion=None):
    return exif_rational_pair(entry, companion, True)


XMP_RATIONAL = re.compile(r'(-?\d{1,10})/(\d{1,10})', re.ASCII)


def xmp_rational_pair(occurrence):
    match = XMP_RATIONAL.fullmatch(xmp_text(occurrence))
    if not match:
        raise ValueProblem('XMP_RATIONAL_INVALID', 'the value is not an n/d rational')
    n, d = int(match.group(1)), int(match.group(2))
    if d == 0:
        raise ValueProblem('XMP_RATIONAL_UNDEFINED', 'the rational has a zero denominator')
    return (n, d)


def anchor_exif_rational_pair(value, tokens, get, source):
    return anchor_rational(Fraction(*value), tokens, get, source)


def native_float_text(pair):
    """What Perl prints for a quotient (``%.15g``): the 15-significant-digit agreement that anchors a rational XMP value."""
    return '%.15g' % (pair[0] / pair[1])


def anchor_xmp_rational_pair(value, tokens, get, source):
    if len(tokens) != 1 or as_text(tokens[0]) != native_float_text(value):
        return 'native reports %s, the independent reader decoded %d/%d' % ([as_text(t)[:40] for t in tokens][:3], value[0], value[1])


CODECS.update({
    'exifRationalPair': ('exif', exif_rational_pair, anchor_exif_rational_pair), 'exifSignedRationalPair': ('exif', exif_signed_rational_pair, anchor_exif_rational_pair),
    'xmpRationalPair': ('xmp', xmp_rational_pair, anchor_xmp_rational_pair)})
