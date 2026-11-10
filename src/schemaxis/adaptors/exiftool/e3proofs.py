"""Independent proofs of one rewritten time or location item: readback of every target (R), non-target preservation of XMP and IPTC, and the native-diff rules.

R reads each written value back out of the output bytes with the standard-library readers, never through ExifTool: a time component must read back as exactly the
planned canonical text in every source (and untouched sources unchanged), a coordinate within the 2e-10 degree serialisation bound with the exact zero rule,
an XMP coordinate exactly, an altitude with its reference byte and typed meaning, and the GPS version, creation values and removals as declared. The Exif,
XMP and IPTC content the plan does not name must be unchanged; the native diff of the E2 writer then classifies every remaining native key change.
"""
from fractions import Fraction

from schemaxis.adaptors.exiftool import codecs, e3place, e3read, e3writes, locations, proofs, records, catalogue, timecalc as tc

VIEW = catalogue.VERSION_E3
UNREQUESTED = 'UNREQUESTED_METADATA_CHANGED'
IFD0_CREATED = {'XResolution': 0x011A, 'YResolution': 0x011B, 'ResolutionUnit': 0x0128, 'YCbCrPositioning': 0x0213}


def problem(code, message, location, **observed):
    return proofs.problem(code, message, location, **observed)


def snapshot(source):
    return (source['state'], source.get('canonical'), source.get('code'))


# ---------------------------------------------------------------- time
def time_field_names():
    return [spec[k] for spec in e3writes.time_groups().values() for k in ('local', 'offset', 'subSecond', 'utc')]


def time_readback(plan, item, payloads_out, at):
    """R of a correctTime item: planned components exact, every other source of every time field unchanged, touched fields concordant, derived UTC as planned."""
    problems = []
    reader = records.Record(payloads_out, VIEW)
    expect = plan['expect']
    touched = {gp['group'] for gp in plan['groups'] if gp['changed']}
    for group, spec in e3writes.time_groups().items():
        for key in ('local', 'offset', 'subSecond'):
            name = spec[key]
            after = reader.field(name)
            before = item['e3fields'][name]
            sources_before = {(s['family'], s['location']): s for s in before['sources']}
            for s in after['sources']:
                wanted = expect.get((name, s['family'], s['location']), None)
                here = '%s.fields.%s.%s' % (at, name, s['family'])
                if (name, s['family'], s['location']) in expect:
                    if s['state'] != 'present' or s['canonical'] != wanted:
                        problems.append(problem('READBACK_MISMATCH', 'a written time component does not read back as planned', here, source=s['location'], expected=wanted, found=s.get('canonical') if s['state'] == 'present' else s['state']))
                elif snapshot(s) != snapshot(sources_before[(s['family'], s['location'])]):
                    problems.append(problem('READBACK_MISMATCH', 'a time source the plan leaves alone changed', here, source=s['location']))
        if group in touched:
            local, offset = reader.field(spec['local']), reader.field(spec['offset'])
            for name in (spec['local'], spec['offset'], spec['subSecond']):
                rec = reader.field(name)
                if rec['state'] == 'present' and rec['reconciliation'] not in ('consistent', 'single-source'):
                    problems.append(problem('READBACK_NOT_CONCORDANT', 'the sources of a corrected time field do not agree after the write', '%s.fields.%s' % (at, name), reconciliation=rec['reconciliation']))
                elif rec['state'] == 'ambiguous':
                    problems.append(problem('READBACK_NOT_CONCORDANT', 'the sources of a corrected time field disagree after the write', '%s.fields.%s' % (at, name), reconciliation=rec['reconciliation']))
            planned = next(gp for gp in plan['groups'] if gp['group'] == group)['after']
            utc = reader.field(spec['utc'])
            if planned['offset'] is not None and any(t['family'] for gp in plan['groups'] if gp['group'] == group for t in gp['targets']):
                want = codecs.to_utc(planned['local'], planned['offset'])
                if utc['state'] == 'present' and utc['canonical'] != want:
                    problems.append(problem('READBACK_MISMATCH', 'the derived UTC instant of a corrected field is not the planned one', '%s.fields.%s' % (at, spec['utc']), expected=want, found=utc['canonical']))
    return problems


# ---------------------------------------------------------------- location
def raw_entry(payloads, tag):
    found = e3read.entries(payloads, 'GPS', tag)
    if found[0] != 'ok' or len(found[1]) != 1:
        return None
    return found[1][0]


def time_fraction(text):
    h, m, s = text.split(':')
    return int(h) * 3600 + int(m) * 60 + Fraction(s)


def location_readback(plan, payloads_out, at):
    """R of a setLocation/geotagFromTrack item (see the module docstring)."""
    problems = []
    data = e3writes.location()
    exp, request = plan['exifExpect'], plan['request']
    here = at + '.location'
    if plan['exifActive']:
        for axis, short in (('latitude', 'lat'), ('longitude', 'lon')):
            triple, ref = e3read.raw_position(payloads_out, short)
            want = exp[axis]
            if triple is None or ref is None:
                problems.append(problem('READBACK_MISMATCH', 'the written %s is absent or not three rationals with a reference letter' % axis, here + '.' + axis))
                continue
            for code, message, loc, detail in locations.exif_target_problems(triple, ref, want['value'], short, here + '.' + axis):
                problems.append(problem(code, message, loc, **detail))
        altitude = plan['exifExpect']['altitude']
        if altitude is not None:
            value, ref = raw_entry(payloads_out, 0x0006), raw_entry(payloads_out, 0x0005)
            if value is None or ref is None or value.kind != 5 or value.count != 1 or ref.kind != 1 or ref.count != 1 or value.values()[0][1] == 0:
                problems.append(problem('READBACK_MISMATCH', 'the written altitude or its reference byte is absent or malformed', here + '.altitude'))
            else:
                for code, message, loc, detail in locations.altitude_target_problems(value.values()[0], ref.values()[0], (altitude['value'], altitude['reference']), here + '.altitude'):
                    problems.append(problem(code, message, loc, **detail))
                typed = e3read.height(payloads_out)
                if typed['state'] != 'present' or typed['reference'] != altitude['reference']:
                    problems.append(problem('READBACK_MISMATCH', 'the typed height of the output does not carry the requested reference', here + '.altitude', found=typed.get('reference'), state=typed['state']))
        if exp['datum'] is not None:
            entry = raw_entry(payloads_out, 0x0012)
            try:
                found = None if entry is None else codecs.exif_text(entry)
            except codecs.ValueProblem:
                found = None
            if found != exp['datum']:
                problems.append(problem('READBACK_MISMATCH', 'the written GPSMapDatum does not read back exactly', here + '.datum', expected=exp['datum'], found=found))
        if exp['horizontalError'] is not None:
            entry = raw_entry(payloads_out, 0x001F)
            want = exp['horizontalError']
            if entry is None or entry.kind != 5 or entry.count != 1 or entry.values()[0][1] == 0:
                problems.append(problem('READBACK_MISMATCH', 'the written horizontal error is absent or malformed', here + '.horizontalError'))
            else:
                n, d = entry.values()[0]
                wanted, stored = Fraction(want), Fraction(n, d)
                if (wanted == 0 and n != 0) or abs(stored - wanted) > locations.ALTITUDE_RELATIVE * wanted:
                    problems.append(problem('READBACK_MISMATCH', 'the stored horizontal error differs from the request beyond the serialisation bound', here + '.horizontalError', stored=[n, d]))
        if exp['gpsUtc'] is not None:
            date_entry, time_entry = raw_entry(payloads_out, 0x001D), raw_entry(payloads_out, 0x0007)
            try:
                date = None if date_entry is None else codecs.exif_text(date_entry)
                stamp = None if time_entry is None else codecs.gps_time_exact(time_entry)
            except codecs.ValueProblem:
                date = stamp = None
            if date != exp['gpsUtc']['date'] or stamp is None or time_fraction(stamp) != time_fraction(exp['gpsUtc']['time']):
                problems.append(problem('READBACK_MISMATCH', 'the written GPS date or time stamp does not read back exactly', here + '.gpsUtc', date=date, time=stamp))
        version = exp['version']
        entry = raw_entry(payloads_out, 0x0000)
        found = None if entry is None or entry.kind != 1 else entry.values()
        if version is not None and (version['created'] or version['target'] is not None):
            wanted = version['target'] if version['target'] is not None else [2, 3, 0, 0]
            if found != wanted:
                problems.append(problem('SIDE_EFFECT_VALUE_INVALID', 'GPSVersionID is not the declared value (a created GPS IFD is 2.3.0.0 by the native default or the declared 2.4.0.0 target)', here + '.gpsVersionId', expected=wanted, found=found))
        for tag in plan['deletedExif']:
            if e3read.entries(payloads_out, 'GPS', tag)[0] == 'ok' and e3read.entries(payloads_out, 'GPS', tag)[1]:
                problems.append(problem('READBACK_MISMATCH', 'a GPS tag the plan removes is still present', here + '.gps', tag='0x%04X' % tag))
    props = e3place.xmp_properties(payloads_out)
    xexp = plan['xmpExpect']
    for axis, short in (('latitude', 'lat'), ('longitude', 'lon')):
        if xexp[axis] is not None:
            found = props.get('exif:GPS' + axis.capitalize())
            if not found or len(found) != 1 or found[0].get('kind') != 'text':
                problems.append(problem('READBACK_MISMATCH', 'the XMP %s is absent or malformed' % axis, here + '.xmp.' + axis))
            else:
                for code, message, loc, detail in locations.xmp_target_problems(found[0]['value'], xexp[axis], short, here + '.xmp.' + axis):
                    problems.append(problem(code, message, loc, **detail))
    if xexp['datum'] is not None:
        found = props.get('exif:GPSMapDatum')
        if not found or len(found) != 1 or found[0].get('value') != xexp['datum']:
            problems.append(problem('READBACK_MISMATCH', 'the XMP GPSMapDatum does not read back exactly', here + '.xmp.datum'))
    for prop in xexp['removed']:
        if prop in props:
            problems.append(problem('READBACK_MISMATCH', 'an XMP property the plan removes is still present', here + '.xmp', property=prop))
    if plan['exifActive'] or plan['xmpActive']:
        reader = records.Record(payloads_out, VIEW)
        for name in ('gpsLatitudeE3', 'gpsLongitudeE3'):
            rec = reader.field(name)
            if rec['state'] != 'present' or rec['reconciliation'] not in ('consistent', 'single-source'):
                problems.append(problem('READBACK_NOT_CONCORDANT', 'the written position is not concordant across its sources', '%s.fields.%s' % (at, name), state=rec['state'], reconciliation=rec['reconciliation']))
    if plan['creation'] is not None:
        problems += creation_readback(plan['creation'], payloads_out, here + '.creation')
    return problems


def creation_readback(creation, payloads_out, here):
    """S9: the IFD0 values ExifTool creates when it writes the first Exif block of a file (resolution from JFIF, YCbCrPositioning 1; nothing else)."""
    problems = []
    state = payloads_out.exif
    group = state[1]['ifds'].get('IFD0') if state[0] == 'ok' else None
    entries = {e.tag: e for e in group[1]} if group and group[0] == 'ok' else {}
    wanted = creation['ifd0']
    expected_tags = {IFD0_CREATED[k] for k in wanted}
    extra = sorted(t for t in entries if t not in expected_tags and t != 0x8825)
    if extra:
        problems.append(problem('SIDE_EFFECT_VALUE_INVALID', 'the created IFD0 holds entries beyond the declared creation values', here, tags=['0x%04X' % t for t in extra]))
    for key, value in wanted.items():
        entry = entries.get(IFD0_CREATED[key])
        values = None if entry is None else entry.values()
        found = None
        if values:
            found = values[0] if key == 'YCbCrPositioning' or key == 'ResolutionUnit' else (Fraction(*values[0]) if entry.kind == 5 else None)
        if found != value:
            problems.append(problem('SIDE_EFFECT_VALUE_INVALID', 'the created IFD0 value %s is not the declared one' % key, here, expected=value, found=None if found is None else str(found)))
    return problems


# ---------------------------------------------------------------- typed semantic preservation (E3R-5)
HEIGHT_KEYS = ('state', 'reference', 'basis', 'meters', 'rawRef', 'stored', 'signKnown', 'historicalLabel')


def height_problems(plan, before, after, at):
    """An altitude the plan does not target keeps its *typed meaning*, not only its raw bytes: the native writer can add an ExifVersion when it creates an ExifIFD,
    which leaves the GPS bytes identical and changes the meaning of a GPS-only 2.4 height from ellipsoidal to unspecified. The edition is read again after the write."""
    if plan['kind'] == 'location' and any(ifd == 'GPS' and tag in (0x0005, 0x0006) for ifd, tag in plan['exifTargets']):
        return []
    one, two = e3read.height(before), e3read.height(after)
    if any(one.get(k) != two.get(k) for k in HEIGHT_KEYS):
        return [problem('ALTITUDE_MEANING_CHANGED', 'the typed meaning of an altitude this write does not target changed (the metadata edition it is read under differs after the write)', at + '.height',
                        before={k: one.get(k) for k in ('state', 'reference', 'basis')}, after={k: two.get(k) for k in ('state', 'reference', 'basis')},
                        editionBefore=one['edition']['evidence'], editionAfter=two['edition']['evidence'])]
    return []


# ---------------------------------------------------------------- non-target content and the native diff
def exif_problems(found):
    """The E2 independent non-target Exif problems, with an unrequested change reported under the E3 code."""
    out = []
    for p in found:
        if p['code'] == 'EXIF_NONTARGET_CHANGED':
            p = dict(p, code=UNREQUESTED)
        out.append(p)
    return out


def xmp_nontarget(before, after, targets, at):
    """Every XMP property the plan does not name has the same occurrences (kind, value, container) before and after."""
    one, two = e3place.xmp_properties(before), e3place.xmp_properties(after)
    problems = []
    for prop in sorted(set(one) | set(two)):
        if prop in targets or one.get(prop) == two.get(prop):
            continue
        problems.append(problem(UNREQUESTED, 'an XMP property the plan does not name differs from the capture (%s)' % ('absent' if prop not in two else 'appeared' if prop not in one else 'value differs'), at + '.xmp', property=prop))
    return problems[:12]


def iptc_nontarget(before, after, touched, at):
    """Every IPTC dataset the plan does not name keeps its bytes (the structural datasets ExifTool maintains are compared by the native diff)."""
    old, new = proofs.datasets_of(before), proofs.datasets_of(after)
    ignore = {(1, 90), (1, 0), (2, 0)}
    problems = []
    for key in sorted(set(old) | set(new)):
        if key in touched or key in ignore:
            continue
        if old.get(key) != new.get(key):
            problems.append(problem(UNREQUESTED, 'an IPTC dataset the plan does not name differs from the capture', at + '.iptc', dataset='%d:%d' % key))
    return problems[:12]


def native_targets(plan):
    """Group-qualified native names the plan writes or deletes (from its arguments), plus the keys that appear with a created GPS IFD or Exif block."""
    names = set()
    for arg in plan['args']:
        if arg.startswith('-') and '=' in arg and arg != '-n':
            names.add(arg[1:].split('=', 1)[0])
    names.discard('Photoshop:IPTCDigest')
    if plan['kind'] == 'location':
        if plan['exifExpect']['version'] is not None and plan['exifExpect']['version']['created']:
            names.add(e3writes.location()['exif']['version']['write'])
        if plan['creation'] is not None:
            names |= {'IFD0:' + k for k in plan['creation']['ifd0']}
    return names


def extra_side_effect(plan):
    """The declared side effects of the E3 write that the E2 rules do not know: the byte-order header of a newly created Exif block."""
    def rule(key, before, after):
        if key == ('File', 'File', 'ExifByteOrder') and plan['kind'] == 'location' and plan['creation'] is not None and not before and after and [str(x) for x in after] in (['II'], ['MM']):
            return 'S9-exifByteOrder'
        return None
    return rule
