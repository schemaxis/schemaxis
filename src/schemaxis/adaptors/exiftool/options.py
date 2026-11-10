"""Authored option declarations of the metadata workbench operations (host-only, imports no native code)."""
from schemaxis.adaptors.exiftool import audit as auditing, catalogue, e4model, mediaset, naming, writes

PROFILES = list(catalogue.profiles())
FIELDS = list(catalogue.fields())
MAX_TEXT = 1024
PROFILE_LIST = {'type': 'array', 'minItems': 1, 'maxItems': len(PROFILES), 'uniqueItems': True, 'items': {'type': 'enum', 'values': PROFILES}}
FIELD_LIST = {'type': 'array', 'minItems': 1, 'maxItems': len(FIELDS), 'uniqueItems': True, 'items': {'type': 'enum', 'values': FIELDS}}
# How the EXIF Artist string is read into the creator list: literally (one string, the E1 behaviour and the default) or as a Metadata Working Group
# creator list (split on "; " outside quotes). It selects an internal catalogue; implementation version numbers are never authored.
CREATOR_INTERPRETATION = {'type': 'enum', 'values': ['literal', 'mwg']}
# ---- E3 time and location workflows: public options express domain intent (devices, true reference times, declared assumptions, tolerances); the internal
# expanded catalogue that reads every time and location source is chosen by the operation and is never an option.
ITEM_ID = {'type': 'string', 'minLength': 1, 'maxLength': 32}
GROUP_ID = {'type': 'string', 'minLength': 1, 'maxLength': 32}
DECIMAL_TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 24}
DEVICE_KEYS = ['cameraMake', 'cameraModel', 'bodySerialNumber']
CLOCK_GROUPS = {'type': 'object', 'properties': {
    'by': {'type': 'enum', 'values': ['recordedDevice', 'declared'], 'required': True},
    'keys': {'type': 'array', 'minItems': 1, 'maxItems': len(DEVICE_KEYS), 'uniqueItems': True, 'items': {'type': 'enum', 'values': DEVICE_KEYS}},
    'members': {'type': 'array', 'minItems': 1, 'maxItems': 64, 'items': {'type': 'object', 'properties': {'group': {**GROUP_ID, 'required': True},
                'items': {'type': 'array', 'required': True, 'minItems': 1, 'maxItems': mediaset.MAX_ITEMS, 'items': ITEM_ID}}}},
    'itemOverrides': {'type': 'array', 'minItems': 1, 'maxItems': 256, 'items': {'type': 'object', 'properties': {'item': {**ITEM_ID, 'required': True}, 'group': {**GROUP_ID, 'required': True}}}}}}
CLOCK_REFERENCES = {'type': 'array', 'minItems': 1, 'maxItems': 256, 'items': {'type': 'object', 'properties': {
    'item': {**ITEM_ID, 'required': True}, 'trueLocal': {'type': 'string', 'minLength': 1, 'maxLength': 32}, 'trueOffset': {'type': 'string', 'minLength': 1, 'maxLength': 8},
    'trueUtc': {'type': 'string', 'minLength': 1, 'maxLength': 32}, 'note': {'type': 'string', 'minLength': 1, 'maxLength': 200}}}}
CLOCK_SIMULTANEOUS = {'type': 'array', 'minItems': 1, 'maxItems': 256, 'items': {'type': 'object', 'properties': {
    'items': {'type': 'array', 'required': True, 'minItems': 2, 'maxItems': 16, 'items': ITEM_ID}, 'toleranceSeconds': DECIMAL_TEXT}}}
RECONCILE_OPTIONS = {'media': mediaset.MEDIA, 'groups': CLOCK_GROUPS, 'references': CLOCK_REFERENCES, 'simultaneous': CLOCK_SIMULTANEOUS,
                     'assumeCorrect': {'type': 'array', 'minItems': 1, 'maxItems': 64, 'uniqueItems': True, 'items': GROUP_ID},
                     'assumedOffsets': {'type': 'array', 'minItems': 1, 'maxItems': 64, 'items': {'type': 'object', 'properties': {'group': {**GROUP_ID, 'required': True}, 'offset': {'type': 'string', 'minLength': 1, 'maxLength': 8, 'required': True}}}},
                     'model': {'type': 'enum', 'values': ['constant', 'linearDrift']}, 'toleranceSeconds': DECIMAL_TEXT, 'maxDriftRate': DECIMAL_TEXT,
                     'maxDriftExtrapolationSeconds': {'type': 'integer', 'minimum': 0, 'maximum': 86400}, 'gpsToleranceSeconds': {'type': 'integer', 'minimum': 0, 'maximum': 86400}}
LOCATE_OPTIONS = {'media': mediaset.MEDIA, 'compareTo': {'type': 'object', 'properties': {'latitude': {**DECIMAL_TEXT, 'required': True}, 'longitude': {**DECIMAL_TEXT, 'required': True}, 'datum': {'type': 'string', 'minLength': 1, 'maxLength': 32}}}}
OPTIONS = {
    'inspectMetadata': {'media': mediaset.MEDIA, 'profiles': {**PROFILE_LIST, 'required': True}, 'nativeListing': {'type': 'boolean'}, 'creatorInterpretation': CREATOR_INTERPRETATION},
    'auditMetadata': {'media': mediaset.MEDIA, 'profiles': PROFILE_LIST, 'require': FIELD_LIST,
                      'rules': {'type': 'array', 'minItems': 1, 'maxItems': len(auditing.RULES), 'uniqueItems': True, 'items': {'type': 'enum', 'values': list(auditing.RULES)}},
                      'gpsToleranceSeconds': {'type': 'integer', 'minimum': 0, 'maximum': 86400}, 'creatorInterpretation': CREATOR_INTERPRETATION},
    'compareMetadata': {'media': mediaset.MEDIA, 'profiles': PROFILE_LIST, 'baseline': {'type': 'string', 'minLength': 1, 'maxLength': 32, 'required': True}, 'fields': FIELD_LIST,
                        'creatorInterpretation': CREATOR_INTERPRETATION}}
OPTIONS.update({'reconcileTime': RECONCILE_OPTIONS, 'locate': LOCATE_OPTIONS})     # appended: the order of the E1 operations (and so every E1 message and enum) is unchanged


def text_spec(limits, item=False):
    return {'type': 'string', 'minLength': 1, 'maxLength': limits.get('itemMaxChars' if item else 'maxChars', 1024)}


def value_spec(spec):
    """The declared value type of one writable field (the exact value domain is enforced when the document is planned)."""
    shape, limits = spec['shape'], spec['limits']
    if shape == 'langText':
        text = text_spec(limits)
        return {'type': 'union', 'options': [text, {'type': 'object', 'properties': {'text': {**text, 'required': True}, 'languages': {'type': 'array', 'minItems': 1, 'maxItems': 16, 'items': {
            'type': 'object', 'properties': {'language': {'type': 'string', 'minLength': 1, 'maxLength': 35, 'required': True}, 'text': {**text, 'required': True}}}}}}]}
    if shape in ('orderedList', 'unorderedList'):
        return {'type': 'array', 'minItems': 1, 'maxItems': limits['maxItems'], 'items': text_spec(limits, True)}
    if shape == 'integer':
        return {'type': 'integer', 'minimum': limits['minimum'], 'maximum': limits['maximum']}
    return text_spec(limits)


def field_edit(spec):
    properties = {'set': value_spec(spec), 'clear': {'type': 'boolean'}}
    if spec['shape'] == 'unorderedList':
        properties.update(add=value_spec(spec), remove=value_spec(spec))
    return {'type': 'object', 'properties': properties}


EDITS = {'type': 'object', 'properties': {name: field_edit(spec) for name, spec in writes.fields().items()}}
POLICIES = {'type': 'object', 'properties': {'iptc': {'type': 'enum', 'values': ['ifPresent', 'always']}, 'otherLanguages': {'type': 'enum', 'values': ['keep', 'remove', 'refuse']},
                                             'exifEncoding': {'type': 'enum', 'values': ['utf8', 'ascii']}, 'companionLoss': {'type': 'enum', 'values': ['removeCompanion', 'refuse']}}}
CATEGORIES = list(writes.categories()) + ['minimise']
WRITE_OPTIONS = {
    'editMetadata': {'media': mediaset.MEDIA, 'edits': {**EDITS, 'required': True},
                     'itemEdits': {'type': 'array', 'minItems': 1, 'maxItems': mediaset.MAX_ITEMS, 'items': {'type': 'object', 'properties': {'item': {'type': 'string', 'minLength': 1, 'maxLength': 32, 'required': True}, 'edits': {**EDITS, 'required': True}}}},
                     'policies': POLICIES},
    'removeMetadata': {'media': mediaset.MEDIA, 'categories': {'type': 'array', 'required': True, 'minItems': 1, 'maxItems': len(CATEGORIES), 'uniqueItems': True, 'items': {'type': 'enum', 'values': CATEGORIES}}}}
# ---- E3 write operations: declared domain intent only (devices, reference times, positions, tracks); native assignments, flags and the internal expanded
# catalogue are never authored. A plan published with apply: plan can be applied later through plan; a plan carries every other input of its operation.
APPLY = {'type': 'enum', 'values': ['write', 'plan']}
PLAN_FILE = {'type': 'string', 'minLength': 1, 'maxLength': 4096}
SHIFT = {'type': 'object', 'properties': {'days': {'type': 'integer', 'minimum': -40000, 'maximum': 40000}, 'hours': {'type': 'integer', 'minimum': -1000000, 'maximum': 1000000},
                                          'minutes': {'type': 'integer', 'minimum': -100000000, 'maximum': 100000000}, 'seconds': DECIMAL_TEXT}}
COORDINATE = {'type': 'union', 'options': [{'type': 'string', 'minLength': 1, 'maxLength': 24}, {'type': 'number'}]}
POSITION = {'latitude': {**COORDINATE, 'required': True}, 'longitude': {**COORDINATE, 'required': True},
            'altitude': {'type': 'object', 'properties': {'meters': {**DECIMAL_TEXT, 'required': True}, 'reference': {'type': 'enum', 'values': ['seaLevel', 'ellipsoidal'], 'required': True}}},
            'datum': {'type': 'string', 'minLength': 1, 'maxLength': 32}, 'horizontalErrorMeters': DECIMAL_TEXT, 'gpsUtc': {'type': 'string', 'minLength': 1, 'maxLength': 32}}
LOCATION_POLICIES = {'type': 'object', 'properties': {'staleCompanions': {'type': 'enum', 'values': ['remove', 'keep']}, 'xmp': {'type': 'enum', 'values': ['ifPresent', 'always', 'remove']},
                                                      'createExif': {'type': 'enum', 'values': ['allow', 'refuse']}, 'altitudeNotExpressible': {'type': 'enum', 'values': ['refuse', 'omitAltitude']},
                                                      'removeDirection': {'type': 'boolean'}, 'uncorrectedItems': {'type': 'enum', 'values': ['copyUnchanged', 'refuseSlot']}}}
GEOTAG_POLICIES = {'type': 'object', 'properties': {**LOCATION_POLICIES['properties'], 'gpsStamp': {'type': 'enum', 'values': ['photoInstant', 'none']}, 'maxSpeedMetersPerSecond': DECIMAL_TEXT}}
TIME_POLICIES = {'type': 'object', 'properties': {'sourceConflicts': {'type': 'enum', 'values': ['refuse', 'preferFamily']}, 'preferFamily': {'type': 'enum', 'values': ['exif', 'xmp', 'iptc']},
                                                  'subSecond': {'type': 'enum', 'values': ['addIfNeeded', 'refuse']}, 'uncorrectedItems': {'type': 'enum', 'values': ['copyUnchanged', 'refuseSlot']}}}
CORRECTIONS = {'type': 'array', 'minItems': 1, 'maxItems': 64, 'items': {'type': 'object', 'properties': {
    'group': {**GROUP_ID, 'required': True}, 'from': {'type': 'enum', 'values': ['references']}, 'shift': SHIFT,
    'setOffset': {'type': 'object', 'properties': {'offset': {'type': 'string', 'minLength': 1, 'maxLength': 8, 'required': True}, 'keep': {'type': 'enum', 'values': ['instant', 'wallClock'], 'required': True}}}}}}
CLOCK_CORRECTION = {'type': 'union', 'options': [{'type': 'enum', 'values': ['none']}, {'type': 'object', 'properties': {
    'shifts': {'type': 'array', 'minItems': 1, 'maxItems': 64, 'items': {'type': 'object', 'properties': {'group': {**GROUP_ID, 'required': True}, 'shift': {**SHIFT, 'required': True}}}}, 'plan': PLAN_FILE}}]}
ELEVATION = {'type': 'union', 'options': [{'type': 'enum', 'values': ['ignore']}, {'type': 'object', 'properties': {'reference': {'type': 'enum', 'values': ['seaLevel', 'ellipsoidal'], 'required': True}}}]}
E3_WRITE_OPTIONS = {
    'correctTime': {**{k: v for k, v in RECONCILE_OPTIONS.items()}, 'apply': APPLY, 'corrections': CORRECTIONS, 'timeFields': {'type': 'array', 'minItems': 1, 'maxItems': 3, 'uniqueItems': True,
                    'items': {'type': 'enum', 'values': ['captured', 'digitized', 'modified']}}, 'policies': TIME_POLICIES, 'plan': PLAN_FILE},
    'setLocation': {'media': mediaset.MEDIA, 'apply': APPLY, 'positions': {'type': 'array', 'minItems': 1, 'maxItems': mediaset.MAX_ITEMS, 'items': {'type': 'object', 'properties': {**POSITION, 'item': {**ITEM_ID, 'required': True}}}},
                    'default': {'type': 'object', 'properties': POSITION}, 'policies': LOCATION_POLICIES, 'plan': PLAN_FILE},
    'geotagFromTrack': {'media': mediaset.MEDIA, 'apply': APPLY, 'tracks': {'type': 'array', 'minItems': 1, 'maxItems': 8, 'items': {'type': 'object', 'properties': {
                            'id': {**ITEM_ID, 'required': True}, 'path': {**PLAN_FILE, 'required': True}, 'sha256': mediaset.SHA}}},
                        'photoTime': {'type': 'object', 'properties': {'source': {'type': 'enum', 'values': ['captured']}, 'assumedOffsets': RECONCILE_OPTIONS['assumedOffsets'], 'clockCorrection': CLOCK_CORRECTION}},
                        'groups': CLOCK_GROUPS, 'interpolation': {'type': 'object', 'properties': {'maxGapSeconds': {'type': 'integer', 'minimum': 1, 'maximum': 3600}, 'endpointSnapSeconds': {'type': 'integer', 'minimum': 0, 'maximum': 60},
                                                                                                    'overlapAgreementMeters': DECIMAL_TEXT}},
                        'track': {'type': 'object', 'properties': {'invalidPoints': {'type': 'enum', 'values': ['refuse', 'exclude']}, 'zonelessTimes': {'type': 'enum', 'values': ['asSchema', 'refuse', 'utc']},
                                                                    'elevation': ELEVATION, 'datum1_0': {'type': 'string', 'minLength': 1, 'maxLength': 32}}},
                        'policies': GEOTAG_POLICIES, 'plan': PLAN_FILE}}
E3_WRITE_OPTIONS['correctTime']['media'] = mediaset.MEDIA
WRITE_OPTIONS.update(E3_WRITE_OPTIONS)       # appended: the order of the E2 operations (and so every E2 message and enum) is unchanged
WRITE_NATIVE = {'editMetadata': 'one perl exiftool -config "" process per item: -GROUP:TAG=value assignments chosen by the planner from catalogue write data (XMP, IPTC and EXIF forms of the requested fields; never authored) -o stage/ID.jpg captured/ID.jpg',
                'correctTime': 'one perl exiftool -config "" -n process per item: -GROUP:TAG=value assignments of every present time source (EXIF, XMP, IPTC), values computed by exact host arithmetic from declared corrections (never authored); -o stage/ID.jpg captured/ID.jpg. The clock model is host logic; no native time shifting, AllDates or expression is used',
                'setLocation': 'one perl exiftool -config "" -n process per item: -GPS:TAG=value and -XMP-exif:TAG=value assignments of decimal-degree coordinates, explicit references and the declared companions, stale GPS values removed as declared (never authored as tags); -o stage/ID.jpg captured/ID.jpg',
                'geotagFromTrack': 'one perl exiftool -config "" -n process per item: the same fixed coordinate assignments as setLocation, from positions Schemaxis interpolated on captured GPX tracks (no native -geotag, -geosync or expression is used); -o stage/ID.jpg captured/ID.jpg',
                'removeMetadata': 'one perl exiftool -config "" process per item: whole-group deletes (-GPS:all= -IFD1:all= -MakerNotes:all=) and -GROUP:TAG= deletes of keys the trusted listing of the capture reports; minimise: whole-block deletes (-EXIF:all= -XMP:all= -IPTC:all= -Photoshop:all= -File:Comment=), -ExifByteOrder= of the capture and numeric re-assignment of the independently read rendering values (never a bare -all=); -o stage/ID.jpg captured/ID.jpg'}
NATIVE = {'inspectMetadata': 'perl exiftool -config "" -json -a -G0:1:4 -n -e -u -q --System:all captured/ID.EXT... (fixed; every authored value is a catalogue ID, never a tag name or option)',
          'auditMetadata': 'the same fixed native listing, used to anchor the independent reader; the audit itself is host logic over typed records',
          'compareMetadata': 'the same fixed native listing, used to anchor the independent reader; the comparison itself is host logic over typed records',
          'reconcileTime': 'the same fixed native listing, used to anchor the independent reader of every time source; the clock model (device groups, reference skew, drift, simultaneity) is exact host arithmetic over typed records, with no native time arithmetic',
          'locate': 'the same fixed native listing, used to anchor the independent reader of every location source; the typed position, height reference and edition evidence are host logic over typed records'}
DECLARATIONS = {op: {'native': NATIVE[op], 'kinds': ['text', 'table'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS[op].items()}} for op in OPTIONS}
DECLARATIONS.update({op: {'native': WRITE_NATIVE[op], 'kinds': ['image', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in WRITE_OPTIONS[op].items()}} for op in WRITE_OPTIONS})


# ---- E4 copy, sidecar and naming operations: public options express domain intent (which kinds of information, which conflict and loss policies, which name and folder
# vocabulary); native assignments, catalogue versions, property names and the sidecar mapping are internal and automatic.
TRANSFER = {'type': 'object', 'required': True, 'properties': {
    'groups': {'type': 'array', 'minItems': 1, 'maxItems': len(e4model.GROUPS), 'uniqueItems': True, 'items': {'type': 'enum', 'values': list(e4model.GROUPS)}},
    'fields': {'type': 'array', 'minItems': 1, 'maxItems': len(e4model.FIELDS), 'uniqueItems': True, 'items': {'type': 'enum', 'values': list(e4model.FIELDS)}}}}
TRANSFER_POLICIES = {'type': 'object', 'properties': {
    'existing': {'type': 'enum', 'values': ['replace', 'keepDestination', 'refuseConflict']}, 'absent': {'type': 'enum', 'values': ['leaveDestination', 'clearDestination']},
    'ambiguous': {'type': 'enum', 'values': ['refuseItem', 'skipField']}, 'loss': POLICIES}}
COPY_SOURCE = {'type': 'union', 'required': True, 'options': [
    {'type': 'object', 'properties': {'item': {**ITEM_ID, 'required': True}}},
    {'type': 'object', 'properties': {'file': {'type': 'object', 'required': True, 'properties': {'path': {**PLAN_FILE, 'required': True}, 'sha256': mediaset.SHA}}}},
    {'type': 'object', 'properties': {'pairs': {'type': 'array', 'required': True, 'minItems': 1, 'maxItems': mediaset.MAX_ITEMS, 'items': {'type': 'object', 'properties': {'from': {**ITEM_ID, 'required': True}, 'to': {**ITEM_ID, 'required': True}}}}}}]}
SIDECAR_SOURCE = {'type': 'object', 'required': True, 'properties': {'sidecar': {'type': 'enum', 'values': ['adjacent', 'declared'], 'required': True}}}
EXPORT_POLICIES = {'type': 'object', 'properties': {'ambiguous': {'type': 'enum', 'values': ['refuseItem', 'skipField']}, 'altitude': {'type': 'enum', 'values': ['omitUnlessReferenceKnown', 'refuseUnlessReferenceKnown']},
                                                    'existingSidecar': {'type': 'enum', 'values': ['ignore', 'refuse']}}}
NAME_PART = {'type': 'object', 'properties': {'token': {'type': 'enum', 'values': sorted(set(naming.NAME_TOKENS) | set(naming.FOLDER_TOKENS))}, 'literal': {'type': 'string', 'minLength': 1, 'maxLength': naming.MAX_LITERAL},
                                              'format': {'type': 'string', 'minLength': 1, 'maxLength': 12}, 'width': {'type': 'integer', 'minimum': 1, 'maximum': 6}, 'start': {'type': 'integer', 'minimum': 0, 'maximum': 999999},
                                              'scope': {'type': 'enum', 'values': list(naming.SCOPES)}}}
NAME_FALLBACK = {'type': 'union', 'options': [{'type': 'enum', 'values': ['refuseItem']}, {'type': 'object', 'properties': {'fallback': {'type': 'string', 'minLength': 1, 'maxLength': 60, 'required': True}}}]}
NAME_RULE = {'name': {'type': 'array', 'minItems': 1, 'maxItems': naming.MAX_PARTS, 'items': NAME_PART},
             'folders': {'type': 'union', 'options': [{'type': 'enum', 'values': ['flat']}, {'type': 'array', 'minItems': 1, 'maxItems': naming.MAX_LEVELS, 'items': NAME_PART}]},
             'time': {'type': 'object', 'properties': {'basis': {'type': 'union', 'options': [{'type': 'enum', 'values': list(naming.BASES)}, {'type': 'object', 'properties': {'fixedOffset': {'type': 'string', 'minLength': 1, 'maxLength': 8, 'required': True}}}]},
                                                         'source': {'type': 'enum', 'values': list(naming.SOURCES)}, 'missing': NAME_FALLBACK, 'missingOffset': {'type': 'enum', 'values': ['refuseItem', 'useRecordedLocal']}}},
             'text': {'type': 'object', 'properties': {'missing': NAME_FALLBACK}}, 'collisions': {'type': 'enum', 'values': ['refuse', 'sequence']}, 'extension': {'type': 'enum', 'values': ['canonical', 'keepOriginal']}}
E4_WRITE_OPTIONS = {'copyMetadata': {'media': mediaset.MEDIA, 'source': COPY_SOURCE, 'transfer': TRANSFER, 'policies': TRANSFER_POLICIES},
                    'applySidecar': {'media': mediaset.MEDIA, 'source': SIDECAR_SOURCE, 'transfer': TRANSFER, 'policies': TRANSFER_POLICIES}}
E4_HOST_OPTIONS = {'exportSidecar': {'media': mediaset.MEDIA, 'transfer': TRANSFER, 'policies': EXPORT_POLICIES},
                   'planNames': {'media': mediaset.MEDIA, **NAME_RULE},
                   'organiseCopies': {'media': mediaset.MEDIA, 'names': {'type': 'union', 'required': True, 'options': [PLAN_FILE, {'type': 'object', 'properties': NAME_RULE}]}, 'sidecars': {'type': 'enum', 'values': ['carry', 'omit']}}}
WRITE_OPTIONS.update(E4_WRITE_OPTIONS)       # appended: the order of the E2 and E3 operations (and so every E2 and E3 message and enum) is unchanged
E4_NATIVE = {'copyMetadata': 'one perl exiftool -config "" process per item (the E2 copy writer): -GROUP:TAG=value assignments planned from typed values of an independent snapshot of the source (never -tagsFromFile, never a block or MakerNote copy, never authored as tags); -o stage/ID.jpg captured/ID.jpg',
             'applySidecar': 'the same copy writer with the typed values of the item\'s XMP sidecar as source: one perl exiftool -config "" process per item, -GROUP:TAG=value assignments planned from the sidecar snapshot (never -tagsFromFile); -o stage/ID.jpg captured/ID.jpg',
             'exportSidecar': 'no native write: the host serializes each XMP sidecar from the typed snapshot of the item; one fixed perl exiftool listing of the produced sidecars anchors every property',
             'planNames': 'no native write: names are host logic over typed capture facts; the same fixed listing used by inspectMetadata anchors the reads the names come from',
             'organiseCopies': 'no native write: exact byte copies of the captures are created by the host under organised/; the fixed listing anchors the reads the names came from'}
DECLARATIONS.update({op: {'native': E4_NATIVE[op], 'kinds': ['image', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in WRITE_OPTIONS[op].items()}} for op in E4_WRITE_OPTIONS})
DECLARATIONS.update({op: {'native': E4_NATIVE[op], 'kinds': ['text', 'image'] if op == 'organiseCopies' else ['text', 'table'] if op == 'planNames' else ['text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in E4_HOST_OPTIONS[op].items()}} for op in E4_HOST_OPTIONS})
