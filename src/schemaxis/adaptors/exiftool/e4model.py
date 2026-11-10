"""Typed snapshots of one media item and the closed transfer vocabulary of the E4 operations (host-only, standard library, no native import).

A snapshot is the independently decoded value of each requested field with its state kept distinct: present, absent (the family was understood and has no
value), ambiguous (sources disagree; no source is preferred), unreadable (malformed) or unsupported (outside the reader). It is the only input of a transfer or
a sidecar export. Values are the raw decoded literals (exact text, exact language set, list order, exact numerator/denominator pairs); nothing is
normalised, trimmed or rounded here, so a reader that normalises cannot make a changed value look equal.
"""
from schemaxis.adaptors.exiftool import catalogue, e3read, records, xmpwrite

VIEW = catalogue.VERSION_E4
GROUPS = {'descriptive': ('title', 'description', 'keywords'), 'rights': ('creator', 'copyright', 'rightsUrl'), 'rating': ('rating',), 'place': ('locationCity', 'locationCountry'),
          'captureTime': ('captureTime',), 'location': ('location',), 'camera': ('cameraMake', 'cameraModel', 'lensMake', 'lensModel'),
          'exposure': ('exposureTime', 'fNumber', 'isoSpeed', 'focalLength', 'focalLength35mm', 'exposureBias'), 'deviceSerials': ('bodySerialNumber', 'lensSerialNumber')}
FIELDS = tuple(f for group in GROUPS.values() for f in group)
GROUP_OF = {f: g for g, fs in GROUPS.items() for f in fs}
SHAPES = {'title': 'langText', 'description': 'langText', 'copyright': 'langText', 'keywords': 'bag', 'creator': 'seq', 'rating': 'integer', 'rightsUrl': 'text', 'locationCity': 'text',
          'locationCountry': 'text', 'cameraMake': 'text', 'cameraModel': 'text', 'lensMake': 'text', 'lensModel': 'text', 'bodySerialNumber': 'text', 'lensSerialNumber': 'text',
          'exposureTime': 'rational', 'fNumber': 'rational', 'focalLength': 'rational', 'exposureBias': 'rational', 'isoSpeed': 'integer', 'focalLength35mm': 'integer',
          'captureTime': 'time', 'location': 'location'}
# the field of the internal fields/4 view that reads each transferable field (a new id where the older field has fewer sources)
VIEW_FIELD = {'lensMake': 'lensMakeE4', 'lensModel': 'lensModelE4', 'bodySerialNumber': 'bodySerialNumberE4', 'lensSerialNumber': 'lensSerialNumberE4', 'exposureTime': 'exposureTimeE4',
              'fNumber': 'fNumberE4', 'focalLength': 'focalLengthE4', 'exposureBias': 'exposureBiasE4', 'focalLength35mm': 'focalLength35mmE4', 'isoSpeed': 'isoSpeedE4'}
XMP_ALT = {'title': 'dc:title', 'description': 'dc:description', 'copyright': 'dc:rights'}
PRIVACY = {'deviceSerials': 'device-identity', 'camera': 'device-identity', 'rights': 'personal-identity', 'location': 'location', 'place': 'location', 'captureTime': 'capture-time',
           'descriptive': 'descriptive-text', 'exposure': 'none', 'rating': 'none'}
NOT_TRANSFERABLE = {'orientation': 'a rendering fact of the destination pixels, not a carried fact', 'imageWidth': 'a rendering fact of the destination pixels, not a carried fact',
                    'imageHeight': 'a rendering fact of the destination pixels, not a carried fact', 'software': 'describes the process that produced the destination, not a carried fact',
                    'modifiedLocal': 'describes the process that produced the destination, not a carried fact', 'digitizedLocal': 'describes the process that produced the destination, not a carried fact'}
TIME_FIELDS = ('capturedLocalE3', 'capturedOffsetE3', 'capturedSubSecondE3', 'gpsUtcExact')
LOCATION_FIELDS = ('gpsLatitudeE3', 'gpsLongitudeE3', 'gpsDatumE3', 'gpsUtcExact')
STATES = ('present', 'absent', 'ambiguous', 'unreadable', 'unsupported')
WORST = ('unreadable', 'unsupported', 'ambiguous')


class SelectionError(ValueError):
    def __init__(self, message, location, **observed):
        super().__init__(message)
        self.message, self.location, self.observed = message, location, observed


def selection(spec):
    """The ordered transfer field ids of ``{'groups': [...], 'fields': [...]}`` (the union, in catalogue order); an empty or unknown selection is refused."""
    spec = spec or {}
    unknown_group = sorted(set(spec.get('groups', [])) - set(GROUPS))
    if unknown_group:
        raise SelectionError('unknown transfer group', '$.transfer.groups', value=unknown_group[:5], groups=sorted(GROUPS))
    chosen = set()
    for group in spec.get('groups', []):
        chosen |= set(GROUPS[group])
    for field in spec.get('fields', []):
        if field in NOT_TRANSFERABLE:
            raise SelectionError('this field is not transferable: ' + NOT_TRANSFERABLE[field], '$.transfer.fields', value=field)
        if field not in FIELDS:
            raise SelectionError('unknown transfer field', '$.transfer.fields', value=str(field)[:40], fields=list(FIELDS))
        chosen.add(field)
    if not chosen:
        raise SelectionError('select at least one group or field to transfer', '$.transfer')
    return [f for f in FIELDS if f in chosen]


def view_names(selected):
    """The internal view fields a selection reads (internal: authors never name them)."""
    names = []
    for f in selected:
        if f == 'captureTime':
            names += list(TIME_FIELDS)
        elif f == 'location':
            names += list(LOCATION_FIELDS)
        else:
            names.append(VIEW_FIELD.get(f, f))
    ordered = list(catalogue.fields(VIEW))
    return [n for n in ordered if n in set(names)]


# ---------------------------------------------------------------- one field of a snapshot
def source_rows(record):
    return [{'family': s['family'], 'location': s['location'], 'state': s['state'], **({'value': jsonable(s['canonical'])} if 'canonical' in s else {}), **({'code': s['code']} if s.get('code') else {})}
            for s in record['sources']]


def jsonable(value):
    if isinstance(value, tuple):
        return list(value)
    return value


def lang_value(payloads, prop, text):
    """``{'text', 'languages'}`` of a language-alternative field: the other languages come from the XMP alternative in its source order."""
    state = payloads.xmp
    languages = []
    if state[0] == 'ok':
        found = state[1].get(prop) or []
        if len(found) == 1 and found[0].get('kind') == 'langAlt' and found[0].get('value'):
            languages = [{'language': k, 'text': v} for k, v in found[0]['value'].items() if k != 'x-default']
    return {'text': text, 'languages': languages}


def plain_field(view_record, field, payloads):
    state = view_record['state']
    row = {'field': field, 'state': state, 'sources': source_rows(view_record), 'reconciliation': view_record['reconciliation']}
    if state == 'present':
        value = view_record['canonical']
        shape = SHAPES[field]
        if shape == 'langText':
            row['value'] = lang_value(payloads, XMP_ALT[field], value)
        elif shape in ('bag', 'seq'):
            row['value'] = list(value)
        elif shape == 'rational':
            row['value'] = tuple(value)
        else:
            row['value'] = value
    return row


def combine(states):
    """The state of a group of inputs: the strongest problem, else present if any is present, else absent."""
    for state in WORST:
        if state in states:
            return state
    return 'present' if 'present' in states else 'absent'


# The carrier that states the local time of each offset or fraction carrier: an XMP date states its own local time, Exif OffsetTimeOriginal and SubSecTimeOriginal belong to Exif
# DateTimeOriginal, and the IPTC time 2:60 belongs to the IPTC date 2:55.
LOCAL_OF = {'ExifIFD:0x9011': 'ExifIFD:0x9003', 'ExifIFD:0x9291': 'ExifIFD:0x9003', '2:60': '2:55'}
UNANCHORED_CODE = 'TIME_COMPONENT_UNANCHORED'
COMPONENT_LABEL = {'offset': 'UTC offset', 'sub': 'fraction of a second'}


def unanchored(local, offset, sub):
    """The orphan carriers of the capture time's offset and fraction, ``[{component, family, location, value}]``.

    A carrier is anchored when it also states the local time itself (the same Exif or XMP date, or the IPTC time with its IPTC date). A component that only carriers without their own local time
    state would be attached to a local time that another carrier states, an association no carrier made, so it is listed here. A component that an anchored carrier states too is not listed:
    that carrier makes the association, the orphan merely repeats it, and a disagreement is the ordinary ambiguity of the reader, not an orphan.
    """
    stated = {(s['family'], s['location']) for s in local['sources'] if s['state'] == 'present'}
    found = []
    for component, record in (('offset', offset), ('sub', sub)):
        anchored, orphans = False, []
        for s in record['sources']:
            if s['state'] != 'present':
                continue
            if (s['family'], LOCAL_OF.get(s['location'], s['location'])) in stated:
                anchored = True
            else:
                orphans.append({'component': component, 'family': s['family'], 'location': s['location'], 'value': s['canonical']})
        if not anchored:
            found += orphans
    return found


def unanchored_problem(carriers, side):
    """``(message, observed)`` of the refusal of a capture time (``side`` is ``source`` or ``destination``) whose component only a carrier without its own local time states."""
    components = []
    for c in carriers:
        if c['component'] not in components:
            components.append(c['component'])
    message = 'the %s capture time cannot be used: its %s %s stated only by a carrier that does not state the local time itself, so no association with that time is invented' % (
        side, ' and '.join(COMPONENT_LABEL[c] for c in components), 'is' if len(components) == 1 else 'are')
    return message, {'field': 'captureTime', 'side': side, 'carriers': [dict(c) for c in carriers]}


def time_value(rec):
    local, offset, sub = rec.field('capturedLocalE3'), rec.field('capturedOffsetE3'), rec.field('capturedSubSecondE3')
    row = {'field': 'captureTime', 'sources': {'local': source_rows(local), 'offset': source_rows(offset), 'sub': source_rows(sub)}}
    states = {local['state'], offset['state'], sub['state']}
    if local['state'] == 'absent':
        state = combine(states - {'present'}) if states - {'present', 'absent'} else 'absent'
    else:
        state = combine(states - {'absent'}) if states - {'present', 'absent'} else 'present'
    orphans = unanchored(local, offset, sub)
    if orphans:
        row['unanchored'] = orphans
        if state == 'present':
            state = 'unsupported'
            row['code'] = UNANCHORED_CODE
    row['state'] = state
    if state == 'present':
        row['value'] = {'local': local['canonical'], 'offset': offset['canonical'] if offset['state'] == 'present' else None, 'sub': sub['canonical'] if sub['state'] == 'present' else None}
    return row


def location_value(rec, payloads):
    fields = {name: rec.field(name) for name in ('gpsLatitudeE3', 'gpsLongitudeE3', 'gpsDatumE3', 'gpsUtcExact')}
    pos = e3read.position(fields, payloads)
    height = e3read.height(payloads)
    row = {'field': 'location', 'state': pos['state'], 'position': {k: v for k, v in pos.items() if k != 'concordance'}, 'height': height, 'datum': {'state': fields['gpsDatumE3']['state'], 'value': fields['gpsDatumE3']['canonical']},
           'gpsUtc': {'state': fields['gpsUtcExact']['state'], 'value': fields['gpsUtcExact']['canonical']}}
    if pos['state'] == 'present':
        row['exactDegrees'] = {'latitude': fields['gpsLatitudeE3']['canonical'], 'longitude': fields['gpsLongitudeE3']['canonical']}
        rationals = [pos['stored'][a]['rationals'] for a in ('latitude', 'longitude')]
        if any(r is None for r in rationals):
            row['state'] = 'unreadable'
            row['code'] = 'GPS_COORDINATE_UNREADABLE'
    return row


def snapshot(payloads, selected):
    """``{field: row}`` for every selected transfer field of one located item (or sidecar); every row has a ``state`` of ``STATES``."""
    rec = records.Record(payloads, VIEW)
    out = {}
    for field in selected:
        if field == 'captureTime':
            out[field] = time_value(rec)
        elif field == 'location':
            out[field] = location_value(rec, payloads)
        else:
            out[field] = plain_field(rec.field(VIEW_FIELD.get(field, field)), field, payloads)
    return out


# ---------------------------------------------------------------- the sidecar model
ALTITUDE_CODE = {('ellipsoidal', False): 0, ('ellipsoidal', True): 1, ('seaLevel', False): 2, ('seaLevel', True): 3}


def altitude_model(height, policy):
    """``(model entries, losses, infos)`` of the typed height: written only for a reference known to be ellipsoidal or sea level with a known sign."""
    if height['state'] == 'absent':
        return {}, [], []
    if height['state'] != 'present':
        return None, [{'code': 'TRANSFER_SOURCE_UNREADABLE', 'field': 'location.height', 'state': height['state'], 'cause': height.get('code')}], []
    if height['reference'] not in ('ellipsoidal', 'seaLevel') or not height['signKnown']:
        if policy == 'refuseUnlessReferenceKnown':
            return None, [{'code': 'ALTITUDE_REFERENCE_UNSPECIFIED', 'field': 'location.height', 'reference': height['reference']}], []
        return {}, [{'code': 'altitudeReferenceUnspecified', 'field': 'location.height', 'treatment': 'altitudeOmitted'}], []
    negative = height['meters'].startswith('-')
    code = ALTITUDE_CODE[(height['reference'], negative)]
    entries = {'gpsAltitude': tuple(height['stored']), 'gpsAltitudeRef': code}
    infos, losses = [], []
    if code == 2:
        losses.append({'code': 'altitudeRefMisreadByExifTool13_55Composite', 'field': 'location.height', 'treatment': 'written', 'detail': 'ExifTool 13.55 lists the literal and its Composite GPSAltitude reads it with legacy 0/1 semantics, inverting the sign for code 2'})
    elif code in (1, 3):
        infos.append({'code': 'exifToolCompositeLabelsSeaLevel', 'field': 'location.height', 'referenceCode': code})
    return entries, losses, infos


def sidecar_model(snapshot_, selected, policies):
    """``(model, losses, infos, faults, skipped)`` of one item: only present selected fields; ambiguity follows the policy, unreadable and unsupported are never absent."""
    model, losses, infos, faults, skipped = {}, [], [], [], []
    for field in selected:
        row = snapshot_[field]
        state = row['state']
        if state == 'absent':
            continue
        if state != 'present':
            code = 'TRANSFER_SOURCE_AMBIGUOUS' if state == 'ambiguous' else 'TRANSFER_SOURCE_UNREADABLE'
            if state == 'ambiguous' and policies['ambiguous'] == 'skipField':
                skipped.append({'field': field, 'reason': 'ambiguous', 'sources': row.get('sources')})
                continue
            if row.get('code') == UNANCHORED_CODE:
                message, observed = unanchored_problem(row['unanchored'], 'source')
                if policies['ambiguous'] == 'skipField':
                    skipped.append({'field': field, 'reason': 'unanchored', 'sources': row.get('sources')})
                    continue
                faults.append({'code': 'TRANSFER_TIME_COMPONENT_UNANCHORED', 'field': field, 'state': state, 'sources': row.get('sources'), 'message': message, 'carriers': observed['carriers']})
                continue
            faults.append({'code': code, 'field': field, 'state': state, 'sources': row.get('sources'), 'message': 'the source values of this field %s' % ('disagree, so no single value is chosen' if state == 'ambiguous' else 'cannot be read, so they are never treated as absent')})
            continue
        value = row.get('value')
        if field == 'captureTime':
            model['captureTime'] = model['captureTimeExif'] = value
        elif field == 'location':
            pos = row['position']
            for axis, key in (('latitude', 'gpsLatitude'), ('longitude', 'gpsLongitude')):
                stored = pos['stored'][axis]
                model[key] = {'components': [tuple(x) for x in stored['rationals']], 'ref': stored['ref']}
            if row['datum']['state'] == 'present':
                model['gpsDatum'] = row['datum']['value']
            entries, alt_losses, alt_infos = altitude_model(row['height'], policies.get('altitude', 'omitUnlessReferenceKnown'))
            if entries is None:
                faults.append({**alt_losses[0], 'message': 'the altitude has no reference that makes its meaning known'})
            else:
                model.update(entries)
                losses += alt_losses
                infos += alt_infos
            gps = row['gpsUtc']
            if gps['state'] == 'present':
                model['gpsDateTime'] = gps['value']
            elif gps['state'] != 'absent':
                losses.append({'code': 'gpsDateTimeIncomplete', 'field': 'location', 'state': gps['state']})
            for axis in ('latitude', 'longitude'):
                for flag in pos['stored'][axis].get('flags', []):
                    infos.append({'code': flag, 'field': 'location.' + axis})
        else:
            model[field] = value
    return model, losses, infos, faults, skipped


def quantisation(model):
    """The published ``{axis: {stored, written, differenceArcSeconds}}`` of every coordinate written in the decimal-minutes form."""
    out = {}
    for key in ('gpsLatitude', 'gpsLongitude'):
        if key in model:
            _, q = xmpwrite.coordinate_literal([tuple(c) for c in model[key]['components']], model[key]['ref'])
            if q is not None:
                out[key] = q
    return out
