"""The typed metadata field catalogue (``fields.json``): load once, validate strictly, expose read-only views.

The catalogue is the only place that says which semantic field lives in which EXIF IFD tag, XMP property or IPTC dataset, how it is
decoded and how it is anchored against the native ExifTool listing. Adding a field means adding catalogue data (and a fixture), not
a new operation. Names that ExifTool reports are observations, never declarations: authored input never carries a tag name.
"""
from fractions import Fraction
import hashlib
import json
import re
from importlib.resources import files

from schemaxis.adaptors.exiftool import codecs

VERSION = 'schemaxis.exiftool.fields/1'
VERSION_MWG = 'schemaxis.exiftool.fields/2'
VERSION_E3 = 'schemaxis.exiftool.fields/3'
VERSION_E4 = 'schemaxis.exiftool.fields/4'
# The only catalogues this code will ever load, by version: the package resource and the SHA-256 of its exact bytes. fields/1 is the
# catalogue of the accepted E1 read family and is byte-frozen; fields/2 is fields/1 with one data difference (the creator EXIF source reads
# an MWG creator list). A name or path never comes from a receipt, a plan or the environment, and a changed byte fails closed.
KNOWN = {VERSION: ('fields.json', '1785f956c2ad54c301eb7e9558790018d2b4ccd3adce2c91c3f7334b4d296c67'),
         VERSION_MWG: ('fields-2.json', 'bce7b860bab934e26cb5bdb9a03dbfa5e48617df86066429ad02e25d11237432')}
# The internal expanded view of the E3 time and location workflows: the E2 catalogue plus a pinned additions document. The only verb is ``addField``: a
# field that needs more sources than an existing one is a NEW id (capturedLocalE3, gpsLatitudeE3, ...), never an edited one, so restricting the view to the E2
# ids reproduces the E2 field specs byte for byte. No author ever selects this view; the operation does.
# The internal view of the E4 transfer, sidecar and naming operations is fields/3 plus a second pinned additions document, again only new ids (the exact-pair
# rational and XMP forms of the lens, serial and exposure fields), so restricting it to the E3 ids reproduces the E3 specs byte for byte.
ADDITIONS = {VERSION_E3: ('fields-3-additions.json', '04d5c0f6410b50fe23b5a65dba3ed50c58acfc27b6971413d834fb1d77bb143e', VERSION_MWG),
             VERSION_E4: ('fields-4-additions.json', '88a45459842aec0e65eb0c85330926e98be097f41311ac30ccb55101a960eae6', VERSION_E3)}
ADDITIONS_VERSION = 'schemaxis.exiftool.fields/3-additions'
TYPES = ('text', 'textList', 'localDateTime', 'offset', 'utcInstant', 'integer', 'rational', 'code', 'degrees', 'meters', 'enum', 'date', 'time', 'digits')
PRIVACY = ('none', 'capture-time', 'device-identity', 'personal-identity', 'descriptive-text', 'location')
FAMILIES = ('exif', 'xmp', 'iptc', 'container')
IFDS = ('IFD0', 'ExifIFD', 'GPS', 'IFD1')
RULES = ('utcFromLocalOffset', 'utcFromDateTime')
HEX_TAG = re.compile(r'0x[0-9A-F]{4}')
XMP_PROPERTY = re.compile(r'[A-Za-z][A-Za-z0-9]*:[A-Za-z][A-Za-z0-9]*')
NATIVE_KEY = re.compile(r'[A-Za-z0-9-]+(:[A-Za-z0-9-]+){1,2}')


class CatalogueError(ValueError):
    pass


def digest(version=VERSION):
    """SHA-256 of the exact bytes of one known catalogue; raises CatalogueError (CATALOGUE_DIGEST_DRIFT) when they differ from the pin.

    For an additions view this is the digest of the pinned additions bytes, after its base catalogue's own pin has been checked.
    """
    if version in ADDITIONS:
        name, pin, base = ADDITIONS[version]
        digest(base)
    else:
        need(version in KNOWN, 'unknown catalogue version ' + str(version)[:60])
        name, pin = KNOWN[version]
    found = hashlib.sha256(files(__package__).joinpath(name).read_bytes()).hexdigest()
    need(found == pin, 'CATALOGUE_DIGEST_DRIFT: %s no longer has its pinned bytes (%s)' % (name, found))
    return found


def load(version=VERSION):
    digest(version)
    if version in ADDITIONS:
        return load_additions(version)
    data = json.loads(files(__package__).joinpath(KNOWN[version][0]).read_text(encoding='utf-8'))
    validate(data, version)
    return data


def load_additions(version):
    """The base catalogue with the pinned ``addField`` additions applied, validated, and proved to leave every base field byte-identical."""
    name, _, base_version = ADDITIONS[version]
    base = load(base_version)
    extra = json.loads(files(__package__).joinpath(name).read_text(encoding='utf-8'))
    need(isinstance(extra, dict) and set(extra) == {'version', 'base', 'addField'} and extra['version'] == ADDITIONS_VERSION and extra['base'] == base_version, 'additions shape, version or base')
    need(isinstance(extra['addField'], dict) and extra['addField'] and not set(extra['addField']) & set(base['fields']), 'additions may only add field ids the base does not have')
    merged = {'version': version, 'profiles': dict(base['profiles']), 'fields': {**base['fields'], **extra['addField']}}
    validate(merged, version)
    need(all(merged['fields'][k] == v for k, v in base['fields'].items()) and list(merged['fields'])[:len(base['fields'])] == list(base['fields']), 'the additions changed a base field')
    return merged


def tolerance(text):
    """The declared concordance bound of a field as an exact Fraction (``within`` is a rational such as ``1/5000000000``), or 0 when malformed."""
    try:
        return Fraction(text) if isinstance(text, str) and len(text) <= 64 else Fraction(0)
    except (ValueError, ZeroDivisionError):
        return Fraction(0)


def need(condition, message):
    if not condition:
        raise CatalogueError(message)


def validate(data, version=VERSION):
    need(isinstance(data, dict) and data.get('version') == version and set(data) == {'version', 'profiles', 'fields'}, 'catalogue shape or version')
    profiles, fields = data['profiles'], data['fields']
    need(isinstance(profiles, dict) and profiles and all(isinstance(k, str) and isinstance(v, str) and v for k, v in profiles.items()), 'profiles')
    need(isinstance(fields, dict) and fields, 'fields')
    seen = set()
    for name, spec in fields.items():
        at = 'field ' + name
        need(re.fullmatch(r'[a-z][A-Za-z0-9]{1,39}', name), at + ' id')
        need(set(spec) >= {'label', 'description', 'profile', 'type', 'unit', 'privacy', 'sources'} and set(spec) <= {'label', 'description', 'profile', 'type', 'unit', 'privacy', 'sources', 'derive', 'labels', 'concordance'}, at + ' keys')
        if 'concordance' in spec:
            need(spec['type'] in ('degrees', 'meters', 'rational') and set(spec['concordance']) == {'within'} and tolerance(spec['concordance']['within']) > 0, at + ' concordance')
        need(spec['profile'] in profiles and spec['type'] in TYPES and spec['privacy'] in PRIVACY, at + ' profile, type or privacy')
        need(isinstance(spec['description'], str) and len(spec['description']) >= 40 and isinstance(spec['label'], str) and spec['label'] and (spec['unit'] is None or isinstance(spec['unit'], str)), at + ' label or unit')
        derived = 'derive' in spec
        need(derived != bool(spec['sources']), at + ' must have sources or a derive rule, not both')
        if derived:
            rule = spec['derive']
            need(set(rule) == {'rule', 'from'} and rule['rule'] in RULES and all(f in fields and f != name for f in rule['from']), at + ' derive')
        for source in spec['sources']:
            validate_source(at, source, fields)
            key = (name, source['family'], source.get('ifd'), source.get('tag'), source.get('property'), source.get('record'), source.get('dataset'), source['codec'])
            need(key not in seen, at + ' repeats a source')
            seen.add(key)
        need(spec['type'] != 'code' or 'labels' in spec, at + ' needs labels')


def validate_source(at, source, fields):
    need(source.get('family') in FAMILIES, at + ' source family')
    need(source.get('codec') in codecs.CODECS and codecs.CODECS[source['codec']][0] == source['family'], at + ' codec does not belong to the family')
    need(isinstance(source.get('native'), str) and NATIVE_KEY.fullmatch(source['native']), at + ' native anchor key')
    allowed = {'family', 'codec', 'native'}
    if source['family'] == 'exif':
        allowed |= {'ifd', 'tag', 'companion', 'companionNative', 'values', 'anchorAbsolute'}
        need(source.get('ifd') in IFDS and HEX_TAG.fullmatch(str(source.get('tag'))), at + ' exif location')
        need(all(HEX_TAG.fullmatch(v) for v in source.get('companion', {}).values()), at + ' exif companion')
        need(set(source.get('companionNative', {})) <= set(source.get('companion', {})) and all(isinstance(v, str) and NATIVE_KEY.fullmatch(v) for v in source.get('companionNative', {}).values()), at + ' exif companion anchors')
        need(source['codec'] not in ('gpsLatitude', 'gpsLongitude', 'gpsAltitude', 'exifDmsSumE3Latitude', 'exifDmsSumE3Longitude') or set(source.get('companionNative', {})) == {'ref'} == set(source.get('companion', {})), at + ' a GPS reference must be anchored against its native companion tag')
    elif source['family'] == 'xmp':
        allowed |= {'property'}
        need(XMP_PROPERTY.fullmatch(str(source.get('property'))), at + ' xmp property')
    elif source['family'] == 'iptc':
        allowed |= {'record', 'dataset', 'companion', 'companionNative'}
        need(isinstance(source.get('record'), int) and isinstance(source.get('dataset'), int) and 1 <= source['record'] <= 9 and 0 <= source['dataset'] <= 255, at + ' iptc location')
        need(set(source.get('companion', {})) == set(source.get('companionNative', {})), at + ' iptc companion anchors')
    else:
        allowed |= {'property'}
        need(source.get('property') in ('width', 'height'), at + ' container property')
    need(set(source) <= allowed, at + ' source keys')


_CACHE = {}


def catalogue(version=VERSION):
    if version not in _CACHE:
        _CACHE[version] = load(version)
    return _CACHE[version]


def fields(version=VERSION): return catalogue(version)['fields']
def profiles(version=VERSION): return catalogue(version)['profiles']


def profile_fields(selected, version=VERSION):
    """Field ids of the selected profiles, in catalogue order (derived inputs are computed internally, not added here)."""
    chosen = set(selected)
    return [name for name, spec in fields(version).items() if spec['profile'] in chosen]
