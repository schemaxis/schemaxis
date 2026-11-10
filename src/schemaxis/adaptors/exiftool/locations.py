"""Typed location models of the E3 workflows (host-only, standard library): coordinates, altitude references, metadata edition evidence, target proofs.

Everything here works on independently decoded raw values (rational numerators and denominators, XMP literals, ExifVersion text) and never on
ExifTool's own interpretation. Exact arithmetic uses ``Fraction``; there is no binary floating point.

Stored precision is a *serialisation* bound, not physical GPS accuracy: ExifTool stores integer degrees and minutes plus a rationalised seconds value
whose total error is below ``B_EXIF`` (derived and sampled, see the contract), which says nothing about where a camera really was.
"""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import re

B_EXIF = Fraction(2, 10 ** 10)               # degrees: stored EXIF coordinate versus the requested decimal
ALTITUDE_RELATIVE = Fraction(1, 10 ** 8)     # metres: relative bound of a rationalised altitude or error value
LIMITS = {'lat': 90, 'lon': 180}
REFS = {'lat': ('N', 'S'), 'lon': ('E', 'W')}
COORDINATE = re.compile(r'([+-]?)(\d{1,3})(?:\.(\d{1,9}))?', re.ASCII)
ALTITUDE = re.compile(r'([+-]?)(\d{1,5})(?:\.(\d{1,3}))?', re.ASCII)
ERROR_METERS = re.compile(r'(\d{1,5})(?:\.(\d{1,3}))?', re.ASCII)
XMP_COORDINATE = re.compile(r'(\d{1,3}),(\d{1,2})(?:\.(\d{1,12})|,(\d{1,2})(?:\.(\d{1,12}))?)?([NSEW])', re.ASCII)
ALTITUDE_MAX = 40000
HISTORICAL_LABEL = 'sea level (Exif <= 2.32 definition)'
GPS_IFD_BEFORE = {'absent': False, 'present': True}


class LocationProblem(ValueError):
    """A refused or unreadable location value with a stable code."""

    def __init__(self, code, message, **observed):
        super().__init__(message)
        self.code, self.message, self.observed = code, message, observed


# ---------------------------------------------------------------- authored coordinate input
def parse_coordinate(value, axis, field='latitude'):
    """A coordinate as authored: a decimal string with at most 9 fractional digits (or a JSON number, taken through its shortest representation).

    Returns ``{'value': Decimal, 'magnitude': str, 'ref': 'N'|'S'|'E'|'W', 'signedZeroNormalised': bool}``. A zero magnitude is always ``N``/``E``.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise LocationProblem('INVALID_ARGUMENT', 'a coordinate is a decimal string', field=field)
    text = value if isinstance(value, str) else repr(value)
    match = COORDINATE.fullmatch(text)
    if not match:
        raise LocationProblem('INVALID_ARGUMENT', 'use a decimal string with at most 9 fractional digits, such as "35.658581"', field=field)
    number = Decimal(match.group(2) + ('.' + match.group(3) if match.group(3) else ''))
    if number > LIMITS[axis]:
        raise LocationProblem('INVALID_ARGUMENT', 'the %s must be between -%d and %d' % ('latitude' if axis == 'lat' else 'longitude', LIMITS[axis], LIMITS[axis]), field=field)
    negative = match.group(1) == '-' and number != 0
    ref = REFS[axis][1 if negative else 0]
    return {'value': -number if negative else number, 'magnitude': format(number.normalize() if number else Decimal(0), 'f'), 'ref': ref,
            'signedZeroNormalised': match.group(1) == '-' and number == 0}


def parse_altitude(meters, field='altitude.meters'):
    """An altitude in metres: ``[+-]ddddd[.ddd]``, at most 40000 in magnitude; ``-0`` is 0. Returns ``(Decimal, magnitude text)``."""
    match = ALTITUDE.fullmatch(meters) if isinstance(meters, str) else None
    if not match:
        raise LocationProblem('INVALID_ARGUMENT', 'use a decimal string with at most 3 fractional digits, such as "-12.5"', field=field)
    number = Decimal(match.group(2) + ('.' + match.group(3) if match.group(3) else ''))
    if number > ALTITUDE_MAX:
        raise LocationProblem('INVALID_ARGUMENT', 'an altitude is at most %d metres in magnitude' % ALTITUDE_MAX, field=field)
    negative = match.group(1) == '-' and number != 0
    return (-number if negative else number), format(number.normalize() if number else Decimal(0), 'f')


def parse_error_meters(text, field='horizontalErrorMeters'):
    match = ERROR_METERS.fullmatch(text) if isinstance(text, str) else None
    if not match:
        raise LocationProblem('INVALID_ARGUMENT', 'use a non-negative decimal string with at most 3 fractional digits', field=field)
    number = Decimal(match.group(1) + ('.' + match.group(2) if match.group(2) else ''))
    if number > ALTITUDE_MAX:
        raise LocationProblem('INVALID_ARGUMENT', 'a horizontal error is at most %d metres' % ALTITUDE_MAX, field=field)
    return number, format(number.normalize() if number else Decimal(0), 'f')


def parse_datum(text, field='datum'):
    if not isinstance(text, str) or not 1 <= len(text) <= 32 or not all(32 <= ord(c) < 127 for c in text):
        raise LocationProblem('INVALID_ARGUMENT', 'a datum is 1 to 32 printable ASCII characters', field=field)
    return text


# ---------------------------------------------------------------- independent EXIF coordinate reader (field codec exifDmsSumE3)
def decode_exif_coordinate(components, ref, axis):
    """Read stored EXIF coordinate rationals ``[(n, d)] * 3`` and a reference text as signed exact degrees.

    Seconds equal to 60 are accepted as an exact sum (ExifTool stores 33.8 as ``33/1 47/1 60/1``) and flagged ``nonCanonicalSeconds60``;
    minutes of 60 or more and seconds above 60 are never carried. Fractional degrees or minutes are read only when every later component is
    zero (camera forms such as ``D M.mmmm 0``). Returns ``{'degrees': Fraction, 'flags': [...], 'stored': [[n, d], ...]}``.
    """
    if len(components) != 3 or any(d == 0 or d < 0 or n < 0 for n, d in components):
        raise LocationProblem('GPS_COORDINATE_MALFORMED', 'each component needs a positive denominator and a non-negative numerator')
    deg, minutes, seconds = (Fraction(n, d) for n, d in components)
    if minutes >= 60 or seconds > 60:
        raise LocationProblem('GPS_COORDINATE_COMPONENT_RANGE', 'minutes must be below 60 and seconds at most 60; a component is never carried')
    if (deg.denominator != 1 and (minutes or seconds)) or (minutes.denominator != 1 and seconds):
        raise LocationProblem('GPS_COORDINATE_MALFORMED', 'fractional degrees or minutes are read only when every later component is zero')
    if ref not in REFS[axis]:
        raise LocationProblem('GPS_COORDINATE_REF', 'the reference must be ' + ' or '.join(REFS[axis]))
    total = deg + minutes / 60 + seconds / 3600
    if total > LIMITS[axis]:
        raise LocationProblem('GPS_COORDINATE_RANGE', 'the coordinate is beyond %d degrees' % LIMITS[axis])
    return {'degrees': -total if ref in ('S', 'W') else total, 'flags': ['nonCanonicalSeconds60'] if seconds == 60 else [], 'stored': [[n, d] for n, d in components]}


def decode_xmp_coordinate(text, axis):
    """Read an XMP ``DDD,MM.mmk`` or ``DDD,MM,SS.sssk`` literal as signed exact degrees (``Fraction``)."""
    match = XMP_COORDINATE.fullmatch(text) if isinstance(text, str) else None
    if not match:
        raise LocationProblem('GPS_COORDINATE_MALFORMED', 'an XMP coordinate is DDD,MM.mmk or DDD,MM,SS.sssk with k one of N, S, E, W')
    degrees, minutes, minute_fraction, seconds, second_fraction, ref = match.groups()
    if ref not in REFS[axis]:
        raise LocationProblem('GPS_COORDINATE_REF', 'the reference must be ' + ' or '.join(REFS[axis]))
    m = Fraction(int(minutes)) + (Fraction(int(minute_fraction), 10 ** len(minute_fraction)) if minute_fraction else 0)
    s = Fraction(int(seconds)) + (Fraction(int(second_fraction), 10 ** len(second_fraction)) if second_fraction else 0) if seconds is not None else Fraction(0)
    if m >= 60 or s >= 60 or (minute_fraction and seconds is not None):
        raise LocationProblem('GPS_COORDINATE_COMPONENT_RANGE', 'minutes and seconds must be below 60')
    total = int(degrees) + m / 60 + s / 3600
    if total > LIMITS[axis]:
        raise LocationProblem('GPS_COORDINATE_RANGE', 'the coordinate is beyond %d degrees' % LIMITS[axis])
    return -total if ref in ('S', 'W') else total


def xmp_literal(requested, axis):
    """The ``DDD,MM.mmk`` literal ExifTool 13.55 stores for a decimal of at most 9 places: ``%d,%.8f`` decimal minutes, zeros trimmed to one decimal."""
    value = Fraction(requested)
    magnitude = abs(value)
    degrees = magnitude.numerator // magnitude.denominator
    minutes = (magnitude - degrees) * 60
    scaled = minutes * 10 ** 8
    rounded = scaled.numerator // scaled.denominator
    if (scaled - rounded) * 2 > 1 or ((scaled - rounded) * 2 == 1 and rounded % 2):
        rounded += 1
    whole, part = divmod(rounded, 10 ** 8)
    text = ('%08d' % part).rstrip('0') or '0'
    return '%d,%d.%s%s' % (degrees, whole, text, REFS[axis][1 if value < 0 else 0])


# ---------------------------------------------------------------- target proofs of a written location
def exif_target_problems(stored, ref, requested, axis, at):
    """Proof R for one coordinate the plan wrote: integral D and M, 0 <= M <= 59, 0 <= S <= 60, R-zero, bound, and the reference.

    ``stored`` is ``[(n, d)] * 3``; ``requested`` a ``Decimal``. Returns a list of ``(code, message, location, detail)``.
    """
    problems = []
    try:
        read = decode_exif_coordinate(stored, ref, axis)
    except LocationProblem as error:
        return [('READBACK_MISMATCH', 'the stored coordinate is not readable: ' + error.message, at, {'code': error.code})]
    deg, minutes, seconds = (Fraction(n, d) for n, d in stored)
    if deg.denominator != 1 or minutes.denominator != 1 or not 0 <= minutes <= 59:
        problems.append(('READBACK_MISMATCH', 'degrees and minutes of a written coordinate are integral, with minutes 0 to 59', at, {'stored': read['stored']}))
    want = Fraction(requested)
    expected_ref = REFS[axis][1 if want < 0 else 0]
    if ref != expected_ref:
        problems.append(('READBACK_MISMATCH', 'the reference letter differs from the requested sign (zero is always %s)' % REFS[axis][0], at, {'expected': expected_ref, 'stored': ref}))
    stored_sum = deg + minutes / 60 + seconds / 3600
    if want == 0 and any(n for n, _ in stored):
        problems.append(('READBACK_MISMATCH', 'a requested zero must store exactly zero in every component (R-zero)', at, {'stored': read['stored']}))
    elif want != 0 and stored_sum == 0:
        problems.append(('READBACK_MISMATCH', 'a requested non-zero value was stored as zero (R-zero)', at, {'stored': read['stored']}))
    if abs(stored_sum - abs(want)) > B_EXIF:
        problems.append(('READBACK_MISMATCH', 'the stored coordinate differs from the request by more than the 2e-10 degree serialisation bound', at,
                         {'differenceDegrees': float(stored_sum - abs(want)), 'bound': '2e-10'}))
    return problems


def quantisation(stored, requested):
    """The published after-value of a written EXIF coordinate: literal rationals, exact sum and difference (never a physical-accuracy claim)."""
    from schemaxis.adaptors.exiftool.timecalc import decimal_text
    deg, minutes, seconds = (Fraction(n, d) for n, d in stored)
    total = deg + minutes / 60 + seconds / 3600
    want = abs(Fraction(requested))
    text, exact = decimal_text(total, 12)
    return {'requested': format(Decimal(requested), 'f'), 'stored': [[n, d] for n, d in stored], 'storedDegrees': text, 'storedDegreesExact': exact,
            'differenceDegrees': format(Decimal(float(total - want)), '.3e') if total != want else '0', 'bound': '2e-10',
            'meaning': 'serialisation bound of the stored rationals; not the accuracy of any GPS fix'}


def xmp_target_problems(literal, requested, axis, at):
    """Proof R for an XMP coordinate: the decoded literal must equal the request exactly."""
    try:
        read = decode_xmp_coordinate(literal, axis)
    except LocationProblem as error:
        return [('READBACK_MISMATCH', 'the XMP coordinate is not readable: ' + error.message, at, {'code': error.code})]
    if read != Fraction(requested):
        return [('READBACK_MISMATCH', 'the XMP coordinate is not exactly the requested decimal', at, {'literal': literal})]
    return []


def altitude_target_problems(stored, ref_byte, request, at):
    """Proof R for a written altitude: reference byte exact, magnitude within 1e-8 relative, exact zero stays zero. ``request`` is ``(Decimal, reference)``."""
    value, reference = request
    n, d = stored
    problems = []
    want_byte = reference_byte(reference, value < 0)
    if ref_byte != want_byte:
        problems.append(('READBACK_MISMATCH', 'GPSAltitudeRef is not the requested reference byte', at, {'expected': want_byte, 'stored': ref_byte}))
    magnitude, wanted = Fraction(n, d), abs(Fraction(value))
    if wanted == 0 and n != 0:
        problems.append(('READBACK_MISMATCH', 'a requested altitude of zero must store a zero numerator', at, {'stored': [n, d]}))
    elif abs(magnitude - wanted) > ALTITUDE_RELATIVE * wanted:
        problems.append(('READBACK_MISMATCH', 'the stored altitude differs from the request by more than the 1e-8 relative serialisation bound', at, {'stored': [n, d]}))
    return problems


# ---------------------------------------------------------------- altitude reference and edition evidence (contract amendment A1)
def reference_byte(reference, negative):
    """EXIF GPSAltitudeRef for a declared reference: ellipsoidal 0/1, sea level 2/3 (negative means below)."""
    return {'ellipsoidal': 0, 'seaLevel': 2}[reference] + (1 if negative else 0)


def version_tuple(gps_version):
    """``(major, minor)`` of a stored GPSVersionID byte list, or ``None`` when absent."""
    return None if gps_version is None else (gps_version[0], gps_version[1]) if len(gps_version) >= 2 else None


def classify_edition(exif_version, gps_version, gps_ifd_present, unresolved=()):
    """Edition evidence from the BEFORE file; E3 never writes ExifVersion. ``exif_version`` is the 4-character text or ``None`` (absent).

    ``exif3`` (>= 0300), ``legacy`` (present and below 0300), ``gpsIfd24`` (no ExifVersion, GPSVersionID >= 2.4), ``none`` (neither), and ``unresolved``: a version
    tag that exists but cannot be resolved (repeated, malformed, wrong type, or inside a damaged IFD) is not absent, and evidence that is not established is
    never read as a declaration. ``unresolved`` names which of ``exif`` and ``gps`` could not be resolved. Returns ``(evidence, infos)``.
    """
    infos = []
    gps = version_tuple(gps_version)
    if 'exif' in unresolved or ('gps' in unresolved and exif_version is None):
        return 'unresolved', ['editionUnresolved']
    if exif_version is not None:
        if re.fullmatch(r'\d{4}', exif_version) and exif_version >= '0300':
            if gps is not None and gps < (2, 4):
                infos.append('gpsVersionIdNotUpdated')
            return 'exif3', infos
        if gps is not None and gps >= (2, 4):
            infos.append('editionConflict')
        return 'legacy', infos
    if gps is not None and gps >= (2, 4):
        return 'gpsIfd24', infos
    return 'none', infos


def read_height(ref, altitude, edition, infos=(), xmp=None):
    """The typed height of a stored altitude: reference, basis, sign knowledge and flags (E3 view; the frozen ``gpsAltitude`` field is unchanged).

    ``ref`` is the EXIF GPSAltitudeRef byte or ``None``; ``altitude`` a ``Fraction`` magnitude or ``None``. For XMP sources pass ``xmp='exif'|'exifEX'``.
    """
    flags = list(infos)
    if altitude is None:
        return None
    result = {'magnitude': altitude, 'signKnown': True, 'rawRef': ref, 'edition': edition, 'historicalLabel': None}
    if xmp == 'exif':
        result.update(reference='unspecified', basis='xmpLegacyRef' if ref in (0, 1, None) else 'xmpNonStandardRef', sign=-1 if ref in (1, 3) else 1, flags=flags)
        return result
    if ref is None:
        result.update(reference='unspecified', basis='refAbsent', signKnown=False, sign=None, flags=flags + ['altitudeRefAbsent'])
        return result
    if ref >= 4:
        raise LocationProblem('GPS_ALTITUDE_REF_RESERVED', 'GPSAltitudeRef values above 3 are reserved')
    sign = -1 if ref in (1, 3) else 1
    if ref >= 2:
        result.update(reference='seaLevel', basis='exifSeaLevelRef', sign=sign, flags=flags + (['legacyReadersMayNotRecognise'] if edition != 'exif3' else []))
    elif edition == 'exif3':
        result.update(reference='ellipsoidal', basis='exif3EllipsoidalRef', sign=sign, flags=flags)
    elif edition == 'gpsIfd24':
        result.update(reference='ellipsoidal', basis='gpsVersionIdOnly', sign=sign, flags=flags + ['editionByGpsVersionOnly'])
    elif edition == 'unresolved':
        result.update(reference='unspecified', basis='editionUnresolved', sign=sign, flags=flags)
    else:
        result.update(reference='unspecified', basis='legacyEditionRef' if edition == 'legacy' else 'noEditionRef', sign=sign, historicalLabel=HISTORICAL_LABEL, flags=flags)
    return result


def plan_altitude(reference, value, edition, gps_ifd_present, policy='refuse'):
    """What an altitude request may write (A1). ``reference`` is ``seaLevel`` or ``ellipsoidal``; ``value`` a Decimal in metres.

    Returns ``{'action': 'write' | 'omit' | 'refuse', 'refByte', 'gpsVersionTarget', 'infos', 'code'?, 'message'?}``. ``gpsVersionTarget`` is ``(2, 4, 0, 0)``
    when E3 creates the GPS IFD as an exif3 file or as a GPS-only ellipsoidal declaration, otherwise ``None`` (an existing GPSVersionID is never changed and a
    created one keeps the native default).
    """
    infos = []
    creating = not gps_ifd_present
    target = (2, 4, 0, 0) if creating and edition == 'exif3' else None
    if reference == 'ellipsoidal':
        if edition in ('exif3', 'gpsIfd24'):
            pass
        elif edition == 'none' and creating:
            target = (2, 4, 0, 0)
            infos += ['editionByGpsVersionOnly', 'legacyReadersMayNotRecognise']
        else:
            refusal = {'code': 'ALTITUDE_REFERENCE_NOT_EXPRESSIBLE',
                       'message': ('an ellipsoidal height cannot be expressed in this file without converting it or promoting its ExifVersion, and neither is performed'
                                   if edition == 'legacy' else 'the metadata edition of this file cannot be resolved (a repeated, malformed or unreadable ExifVersion or GPSVersionID); an ellipsoidal height is not written on unestablished evidence'
                                   if edition == 'unresolved' else 'the file has a GPS IFD without an Exif 3.x or GPS 2.4 edition declaration; no conversion and no promotion is performed')}
            if policy == 'omitAltitude':
                return {'action': 'omit', 'refByte': None, 'gpsVersionTarget': None, 'infos': ['altitudeOmitted'], **refusal}
            return {'action': 'refuse', 'refByte': None, 'gpsVersionTarget': None, 'infos': [], **refusal}
    elif edition != 'exif3':
        infos.append('legacyReadersMayNotRecognise')
    return {'action': 'write', 'refByte': reference_byte(reference, value < 0), 'gpsVersionTarget': target, 'infos': infos}
