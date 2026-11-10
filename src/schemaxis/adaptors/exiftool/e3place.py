"""Per-item plan of ``setLocation`` and ``geotagFromTrack`` (host-only, standard library): which GPS values are written, removed or kept, and what must read back.

Every decision is made from the independent read of the capture before any native call. Coordinates are assigned as decimal-degree strings under the fixed
``-n`` protocol (an exact decimal of at most 9 places; the native stores integer degrees and minutes plus a rationalised seconds value whose error stays
below the serialisation bound), every reference letter and the altitude reference byte are written explicitly and a zero never carries a south or west
reference. An altitude is written only with a reference the author declared and only where the file's metadata edition can express it; nothing is ever
converted between vertical references and no ExifVersion is written. The GPS values that describe the old fix (altitude, datum, time stamps, error,
dilution, speed, track, ...) are removed or kept as declared before the write; the camera direction is the camera's, not the fix's, and is kept.
"""
from schemaxis.adaptors.exiftool import e3read, e3writes, edits, locations, timecalc as tc, xmp as xmp_reader
from schemaxis.errors import fail

POLICY_DEFAULTS = {'staleCompanions': 'remove', 'xmp': 'ifPresent', 'createExif': 'allow', 'altitudeNotExpressible': 'refuse', 'removeDirection': False, 'uncorrectedItems': 'copyUnchanged',
                   'gpsStamp': 'photoInstant'}
POLICY_VALUES = {'staleCompanions': ('remove', 'keep'), 'xmp': ('ifPresent', 'always', 'remove'), 'createExif': ('allow', 'refuse'), 'altitudeNotExpressible': ('refuse', 'omitAltitude'),
                 'uncorrectedItems': ('copyUnchanged', 'refuseSlot'), 'gpsStamp': ('photoInstant', 'none')}
EXIF_GPS = 'GPS'
e3proofs_ifd0 = {'XResolution': 0x011A, 'YResolution': 0x011B, 'ResolutionUnit': 0x0128, 'YCbCrPositioning': 0x0213}


def refuse(code, message, at, **observed):
    raise edits.Refusal(code, message, at, **observed)


def tag_int(text): return int(text, 16)


def raw_literal(entry):
    """A short exact literal of one raw entry for the declared-loss lists (text, ``n/d`` rationals, byte values)."""
    if entry.raw is None:
        return None
    if entry.kind == 2:
        return entry.raw.rstrip(b'\0').decode('latin-1')[:80]
    values = entry.values()
    if entry.kind in (5, 10) and values:
        return ' '.join('%d/%d' % v for v in values[:3])
    if values is not None:
        return ' '.join(str(v) for v in values[:8])
    return entry.raw[:16].hex()


def gps_entries(payloads):
    """``{tag: [Entry]}`` of the GPS IFD (empty when there is none)."""
    state = payloads.exif
    if state[0] != 'ok':
        return {}
    group = state[1]['ifds'].get(EXIF_GPS)
    if not group or group[0] != 'ok':
        return {}
    found = {}
    for e in group[1]:
        found.setdefault(e.tag, []).append(e)
    return found


def xmp_properties(payloads):
    state = payloads.xmp
    return state[1] if state[0] == 'ok' else {}


def xmp_gps_present(payloads):
    return any(name.startswith('exif:GPS') or name.startswith('exifEX:GPS') for name in xmp_properties(payloads))


def jfif_density(walk):
    """``(units, x, y)`` of the capture's JFIF segment, or ``None``."""
    for s in (walk['pre'] if walk is not None else ()):
        if s['role'] == 'rendering' and s['marker'] == 0xE0 and s['body'].startswith(b'JFIF\0') and len(s['body']) >= 12:
            body = s['body']
            return body[7], int.from_bytes(body[8:10], 'big'), int.from_bytes(body[10:12], 'big')
    return None


def parse_entry(spec, default, at, allow_altitude=True):
    """The normalised position request of one item from a ``positions`` entry (or the ``default``), with every value domain checked."""
    try:
        lat = locations.parse_coordinate(spec['latitude'], 'lat', at + '.latitude')
        lon = locations.parse_coordinate(spec['longitude'], 'lon', at + '.longitude')
        out = {'latitude': lat, 'longitude': lon, 'altitude': None, 'datum': None, 'horizontalError': None, 'gpsUtc': None}
        if spec.get('altitude') is not None:
            altitude = spec['altitude']
            if altitude.get('reference') not in ('seaLevel', 'ellipsoidal'):
                raise locations.LocationProblem('INVALID_ARGUMENT', 'the altitude reference is required: seaLevel or ellipsoidal (no default reference exists)', field=at + '.altitude.reference')
            value, magnitude = locations.parse_altitude(altitude['meters'], at + '.altitude.meters')
            out['altitude'] = {'value': value, 'meters': magnitude if value >= 0 else '-' + magnitude, 'magnitude': magnitude, 'reference': altitude['reference']}
        if spec.get('datum') is not None:
            out['datum'] = locations.parse_datum(spec['datum'], at + '.datum')
        if spec.get('horizontalErrorMeters') is not None:
            value, magnitude = locations.parse_error_meters(spec['horizontalErrorMeters'], at + '.horizontalErrorMeters')
            out['horizontalError'] = {'value': value, 'magnitude': magnitude}
        if spec.get('gpsUtc') is not None:
            out['gpsUtc'] = parse_gps_utc(spec['gpsUtc'], at + '.gpsUtc')
    except locations.LocationProblem as error:
        fail(error.code, error.message, error.observed.get('field', at), **{k: v for k, v in error.observed.items() if k != 'field'})
    except tc.TimeProblem as error:
        fail(error.code, error.message, at + '.gpsUtc', **error.observed)
    return out


def parse_gps_utc(text, at):
    """``YYYY-MM-DDThh:mm:ss[.f{1,9}]Z`` to the GPS stamp forms ``(YYYY:MM:DD, hh:mm:ss[.f])`` and the exact UTC nanoseconds."""
    ns = tc.parse_utc(text, at)
    local = tc.local_text(ns - ns % tc.NS, 0)
    digits = text[19:-1].lstrip('.') if len(text) > 20 else ''
    return {'date': local[:10].replace('-', ':'), 'time': local[11:] + ('.' + digits if digits else ''), 'ns': ns, 'text': text}


def plan_item(request, payloads, walk, policies, at, entry_fields=None, instant_ns=None):
    """The location plan of one item, or a ``Refusal``. ``request`` comes from ``parse_entry``; ``instant_ns`` marks a GPS stamp taken from a track photo instant."""
    data = e3writes.location()
    exif_data, xmp_data = data['exif'], data['xmp']
    if payloads.exif[0] not in ('ok', 'absent'):
        refuse('EDIT_DESTINATION_UNREADABLE', 'the Exif block cannot be read, so it is not rewritten', at, cause=payloads.exif[2] if payloads.exif[0] == 'error' else payloads.exif[1])
    if payloads.xmp[0] not in ('ok', 'absent'):
        refuse('EDIT_DESTINATION_UNREADABLE', 'the XMP packet cannot be read, so it is not rewritten', at, cause=payloads.xmp[2] if payloads.xmp[0] == 'error' else payloads.xmp[1])
    gps_group = payloads.exif[1]['ifds'].get(EXIF_GPS) if payloads.exif[0] == 'ok' else None
    for name, group in (payloads.exif[1]['ifds'].items() if payloads.exif[0] == 'ok' else ()):
        if group[0] == 'error':
            refuse('EDIT_DESTINATION_UNREADABLE', 'the %s IFD cannot be read, so the Exif block is not rewritten around it' % name, at, ifd=name, cause=group[1])
    before = gps_entries(payloads)
    gps_before = bool(gps_group)
    xmp_props = xmp_properties(payloads)
    evidence, edition_infos, exif_version, gps_version = e3read.edition(payloads)
    exif_absent = payloads.exif[0] == 'absent'
    xmp_policy = policies['xmp']
    xmp_active = xmp_policy == 'always' or (xmp_policy == 'ifPresent' and xmp_gps_present(payloads))
    xmp_remove = xmp_policy == 'remove'
    exif_active = True
    infos = list(edition_infos)
    if exif_absent and exif_active:
        if policies['createExif'] == 'refuse':
            if xmp_policy != 'always':
                refuse('EXIF_CREATION_REFUSED', 'the capture has no Exif block and the policy refuses to create one (use xmp: always to write XMP only)', at)
            exif_active = False
            infos.append('exifNotCreated')
    losses, args, exif_targets, xmp_targets, deletes_exif = [], [], set(), set(), []
    lat, lon = request['latitude'], request['longitude']
    altitude = request['altitude']
    # ---- altitude (A1): the reference is the author's statement; the edition decides whether it can be expressed
    alt_plan = None
    gps_version_target = None
    if altitude is not None and exif_active:
        alt_plan = locations.plan_altitude(altitude['reference'], altitude['value'], evidence, gps_before, policies['altitudeNotExpressible'])
        if alt_plan['action'] == 'refuse':
            refuse(alt_plan['code'], alt_plan['message'] + ' (exifVersion %s)' % (exif_version or 'absent'), at + '.altitude', edition=evidence, exifVersion=exif_version, gpsVersionId=gps_version,
                   requested=altitude['reference'], remedy='use reference seaLevel for a sea-level height, omit the altitude, or set altitudeNotExpressible to omitAltitude')
        infos += alt_plan['infos']
        gps_version_target = alt_plan['gpsVersionTarget']
    elif altitude is None and exif_active and not gps_before and evidence == 'exif3':
        gps_version_target = (2, 4, 0, 0)       # a GPS IFD created inside an Exif 3.x file is the 2.4 edition (A1)
    losses_early = []
    if altitude is not None and not exif_active:
        infos.append('altitudeNotWritten')
        losses_early.append({'key': 'GPS:GPSAltitude', 'before': None, 'reason': 'xmpAltitudeNotExpressible', 'treatment': 'notWritten'})
    # ---- EXIF writes
    written_tags = set()
    exif_expect = {'latitude': None, 'longitude': None, 'altitude': None, 'datum': None, 'horizontalError': None, 'gpsUtc': None, 'version': None}
    if exif_active:
        if gps_version_target is not None:
            args.append('-%s=%s' % (exif_data['version']['write'], ' '.join(str(x) for x in gps_version_target)))
        if gps_version_target is not None or not gps_before:
            exif_targets.add((EXIF_GPS, tag_int(exif_data['version']['tag'])))       # created with the GPS IFD (native default 2.3.0.0, or the declared 2.4.0.0 target)
        exif_expect['version'] = {'target': None if gps_version_target is None else list(gps_version_target), 'created': not gps_before}
        for axis, spec_axis, req in (('latitude', exif_data['latitude'], lat), ('longitude', exif_data['longitude'], lon)):
            args.append('-%s=%s' % (spec_axis['write'], req['magnitude']))
            args.append('-%s=%s' % (spec_axis['ref']['write'], req['ref']))
            exif_targets |= {(EXIF_GPS, tag_int(spec_axis['tag'])), (EXIF_GPS, tag_int(spec_axis['ref']['tag']))}
            exif_expect[axis] = {'value': req['value'], 'ref': req['ref'], 'magnitude': req['magnitude']}
            if req['signedZeroNormalised']:
                infos.append('signedZeroNormalised')
        if alt_plan is not None and alt_plan['action'] == 'write':
            args.append('-%s=%s' % (exif_data['altitude']['write'], altitude['magnitude']))
            args.append('-%s=%d' % (exif_data['altitude']['ref']['write'], alt_plan['refByte']))
            exif_targets |= {(EXIF_GPS, tag_int(exif_data['altitude']['tag'])), (EXIF_GPS, tag_int(exif_data['altitude']['ref']['tag']))}
            exif_expect['altitude'] = {'value': altitude['value'], 'reference': altitude['reference'], 'refByte': alt_plan['refByte']}
        if request['datum'] is not None:
            args.append('-%s=%s' % (exif_data['datum']['write'], request['datum']))
            exif_targets.add((EXIF_GPS, tag_int(exif_data['datum']['tag'])))
            exif_expect['datum'] = request['datum']
        if request['horizontalError'] is not None:
            args.append('-%s=%s' % (exif_data['horizontalError']['write'], request['horizontalError']['magnitude']))
            exif_targets.add((EXIF_GPS, tag_int(exif_data['horizontalError']['tag'])))
            exif_expect['horizontalError'] = request['horizontalError']['value']
        if request['gpsUtc'] is not None:
            args.append('-%s=%s' % (exif_data['date']['write'], request['gpsUtc']['date']))
            args.append('-%s=%s' % (exif_data['time']['write'], request['gpsUtc']['time']))
            exif_targets |= {(EXIF_GPS, tag_int(exif_data['date']['tag'])), (EXIF_GPS, tag_int(exif_data['time']['tag']))}
            exif_expect['gpsUtc'] = {'date': request['gpsUtc']['date'], 'time': request['gpsUtc']['time']}
        written_tags = {t for _, t in exif_targets}
        # ---- stale companions and the camera direction (EXIF)
        stale = [(tag_int(e['tag']), e['write']) for e in exif_data_stale(data)]
        stale += [(tag_int(exif_data[k]['tag']), exif_data[k]['write']) for k in ('datum', 'horizontalError', 'date', 'time')]
        stale += [(tag_int(exif_data['altitude']['tag']), exif_data['altitude']['write']), (tag_int(exif_data['altitude']['ref']['tag']), exif_data['altitude']['ref']['write'])]
        direction = [(tag_int(e['tag']), e['write']) for e in data['direction']['exif']]
        omit_altitude = alt_plan is not None and alt_plan['action'] == 'omit'
        for tag, write in sorted(stale):
            if tag in written_tags or tag not in before:
                continue
            is_altitude = write in (exif_data['altitude']['write'], exif_data['altitude']['ref']['write'])
            if len(before[tag]) > 1:
                refuse('EDIT_DESTINATION_UNREADABLE', 'a GPS tag this write replaces or removes is repeated in the GPS IFD', at, tag='0x%04X' % tag, cause='EXIF_TAG_REPEATED')
            literal = raw_literal(before[tag][0])
            if policies['staleCompanions'] == 'remove' or omit_altitude and is_altitude:
                args.append('-%s=' % write)
                exif_targets.add((EXIF_GPS, tag))
                deletes_exif.append(tag)
                losses.append({'key': write, 'before': literal, 'reason': 'altitudeOmitted' if omit_altitude and is_altitude else 'staleCompanionRemoved', 'treatment': 'removed'})
            else:
                infos.append('staleKept')
                losses.append({'key': write, 'before': literal, 'reason': 'staleCompanionKept', 'treatment': 'kept'})
        if policies['removeDirection']:
            for tag, write in direction:
                if tag in before:
                    args.append('-%s=' % write)
                    exif_targets.add((EXIF_GPS, tag))
                    deletes_exif.append(tag)
                    losses.append({'key': write, 'before': raw_literal(before[tag][0]), 'reason': 'directionRemoved', 'treatment': 'removed'})
        for tag in (tag_int(exif_data[k]['tag']) for k in ('latitude', 'longitude')):
            if len(before.get(tag, ())) > 1:
                refuse('EDIT_DESTINATION_UNREADABLE', 'a GPS coordinate tag is repeated in the GPS IFD', at, tag='0x%04X' % tag, cause='EXIF_TAG_REPEATED')
    # ---- XMP writes
    xmp_expect = {'latitude': None, 'longitude': None, 'datum': None, 'removed': []}
    if xmp_active and not xmp_remove:
        for axis, spec_axis, req in (('latitude', xmp_data['latitude'], lat), ('longitude', xmp_data['longitude'], lon)):
            text = format(req['value'], 'f') if req['value'] != 0 else '0'
            args.append('-%s=%s' % (spec_axis['write'], text))
            xmp_targets.add(spec_axis['property'])
            xmp_expect[axis] = req['value']
        if request['datum'] is not None and (xmp_data['datum']['property'] in xmp_props or xmp_policy == 'always'):
            args.append('-%s=%s' % (xmp_data['datum']['write'], request['datum']))
            xmp_targets.add(xmp_data['datum']['property'])
            xmp_expect['datum'] = request['datum']
    altitude_changes = alt_plan is not None and alt_plan['action'] in ('write', 'omit')
    if xmp_active or xmp_remove:
        removable = [xmp_data['altitude'], xmp_data['altitudeRef']]
        if xmp_data['altitudeRefCurrent']['property'] in xmp_props and (altitude_changes or xmp_remove):
            refuse('ALTITUDE_REFERENCE_NOT_EXPRESSIBLE', 'the XMP packet records exifEX:GPSAltitudeRef, which the pinned ExifTool cannot rewrite or remove, so an altitude change would leave it contradicting the new value', at,
                   property=xmp_data['altitudeRefCurrent']['property'])
        stale_xmp = [e for e in data['stale']['xmp']]
        for entry in [xmp_data['datum']] + stale_xmp + removable + ([] if not policies['removeDirection'] else list(data['direction']['xmp'])):
            prop = entry['property']
            if prop not in xmp_props or prop in xmp_targets:
                continue
            is_altitude = prop in (xmp_data['altitude']['property'], xmp_data['altitudeRef']['property'])
            if len(xmp_props[prop]) > 1:
                refuse('EDIT_DESTINATION_UNREADABLE', 'an XMP property this write replaces or removes is repeated', at, property=prop, cause='XMP_PROPERTY_REPEATED')
            if xmp_remove or policies['staleCompanions'] == 'remove' or (is_altitude and altitude_changes):
                args.append('-%s=' % entry['write'])
                xmp_targets.add(prop)
                xmp_expect['removed'].append(prop)
                losses.append({'key': entry['write'], 'before': xmp_literal(xmp_props[prop][0]), 'reason': 'xmpAltitudeNotExpressible' if is_altitude else 'staleCompanionRemoved', 'treatment': 'removed'})
                if is_altitude:
                    infos.append('xmpAltitudeNotExpressible')
            else:
                infos.append('staleKept')
                losses.append({'key': entry['write'], 'before': xmp_literal(xmp_props[prop][0]), 'reason': 'staleCompanionKept', 'treatment': 'kept'})
    if xmp_remove:
        for entry in (xmp_data['latitude'], xmp_data['longitude']):
            if entry['property'] in xmp_props:
                if len(xmp_props[entry['property']]) > 1:
                    refuse('EDIT_DESTINATION_UNREADABLE', 'an XMP property this write removes is repeated', at, property=entry['property'], cause='XMP_PROPERTY_REPEATED')
                args.append('-%s=' % entry['write'])
                xmp_targets.add(entry['property'])
                xmp_expect['removed'].append(entry['property'])
                losses.append({'key': entry['write'], 'before': xmp_literal(xmp_props[entry['property']][0]), 'reason': 'xmpRemoved', 'treatment': 'removed'})
    for prop in xmp_targets:
        if prop in xmp_props and len(xmp_props[prop]) > 1:
            refuse('EDIT_DESTINATION_UNREADABLE', 'an XMP property this write rewrites is repeated', at, property=prop, cause='XMP_PROPERTY_REPEATED')
    # ---- creation of the Exif block (S9)
    creation = None
    if exif_absent and exif_active:
        density = jfif_density(walk)
        creation = {'jfif': None if density is None else {'units': density[0], 'x': density[1], 'y': density[2]},
                    'ifd0': ({'XResolution': density[1], 'YResolution': density[2], 'ResolutionUnit': density[0] + 1, 'YCbCrPositioning': 1} if density is not None else {'YCbCrPositioning': 1})}
        infos.append('exifCreated')
        exif_targets |= {('IFD0', e3proofs_ifd0[k]) for k in creation['ifd0']}
    losses = losses_early + losses
    changed = bool(args)
    return {'kind': 'location', 'args': ['-n'] + args if args else [], 'request': request, 'edition': {'evidence': evidence, 'exifVersion': exif_version, 'gpsVersionId': gps_version},
            'altitude': None if alt_plan is None else {k: v for k, v in alt_plan.items() if k in ('action', 'refByte', 'gpsVersionTarget', 'infos')},
            'exifTargets': exif_targets, 'xmpTargets': xmp_targets, 'exifExpect': exif_expect, 'xmpExpect': xmp_expect, 'deletedExif': sorted(deletes_exif), 'gpsIfdBefore': gps_before,
            'exifActive': exif_active, 'xmpActive': xmp_active and not xmp_remove, 'xmpRemove': xmp_remove, 'creation': creation, 'losses': losses, 'infos': sorted(set(infos)),
            'declared': {'exif': exif_active and bool(exif_targets) or bool(creation), 'xmp': bool(xmp_targets), 'iptc': False, 'exifCreate': creation is not None},
            'changed': changed, 'xmpWritten': bool(xmp_targets), 'instant': instant_ns}


def exif_data_stale(data):
    return data['stale']['exif']


def xmp_literal(occurrence):
    if occurrence.get('kind') == 'text':
        return occurrence['value'][:80]
    return '<%s>' % occurrence.get('kind')


def xmp_qualifier_problem(located, props):
    """The first XMP property of ``props`` whose capture carries qualifiers that a rewrite would drop, or ``None``."""
    xmp = located['xmp']
    if not xmp or not props:
        return None
    found = xmp_reader.qualifiers(xmp[0], set(props))
    for prop in sorted(found):
        return {'property': prop, 'count': found[prop]}
    return None
