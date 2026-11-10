"""The write data of the metadata edit family (``writes.json``): load once, pin by digest, validate statically against the MWG catalogue.

Which semantic field is written where, with which shape and limits, and which concrete removal categories exist are data, not per-field code:
the planner, the independent readback and the native comparison all consume this one table. It is keyed by the field ids of the MWG-capable
read catalogue (``fields/2``), and every destination must be a source that catalogue's independent readers already understand, so a value
that can be written can also be read back without ExifTool. Nothing here names an ExifTool option; ``write`` names are group-qualified tag
names that the planner turns into assignments, and authored input never carries one.
"""
import hashlib
import json
import re
from importlib.resources import files

from schemaxis.adaptors.exiftool import catalogue

VERSION = 'schemaxis.exiftool.writes/1'
FILE = 'writes.json'
PIN = '4878f3af1568797b702e63fc6fe3e5aa93d0335bcd191b0dbb359709a4596477'
SHAPES = ('text', 'langText', 'orderedList', 'unorderedList', 'integer', 'url')
ROLES = ('primary', 'companion')
WRITE_NAME = re.compile(r'[A-Za-z0-9]+(-[A-Za-z0-9]+)?:[A-Za-z0-9-]+')
XMP_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9]*:([A-Za-z][A-Za-z0-9]*\*?|\*)')
# Rendering metadata that no operation may touch: removal selectors must never match these.
RENDERING_EXIF = {('IFD0', 0x0112), ('IFD0', 0x0213), ('ExifIFD', 0xA001), ('ExifIFD', 0xA500), ('ExifIFD', 0xA002), ('ExifIFD', 0xA003), ('ExifIFD', 0xA005)}
RENDERING_XMP = {'tiff:Orientation', 'exif:ColorSpace', 'exif:PixelXDimension', 'exif:PixelYDimension'}
RENDERING_NATIVE = {('IFD0', 'Orientation'), ('IFD0', 'YCbCrPositioning'), ('ExifIFD', 'ColorSpace'), ('ExifIFD', 'Gamma'), ('InteropIFD', 'InteropIndex'), ('ExifIFD', 'ExifImageWidth'), ('ExifIFD', 'ExifImageHeight'),
                    ('XMP-tiff', 'Orientation'), ('XMP-exif', 'ColorSpace'), ('XMP-exif', 'PixelXDimension'), ('XMP-exif', 'PixelYDimension'), ('ICC_Profile', '*'), ('APP14', '*'), ('JFIF', '*'), ('File', 'ExifByteOrder')}


class WritesError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise WritesError(message)


def digest():
    found = hashlib.sha256(files(__package__).joinpath(FILE).read_bytes()).hexdigest()
    need(found == PIN, 'CATALOGUE_DIGEST_DRIFT: %s no longer has its pinned bytes (%s)' % (FILE, found))
    return found


def xmp_match(pattern, name):
    """A selector pattern is an exact ``prefix:Name`` or ``prefix:Prefix*``."""
    return name.startswith(pattern[:-1]) if pattern.endswith('*') else name == pattern


def native_match(pattern, name):
    return name.startswith(pattern[:-1]) if pattern.endswith('*') else name == pattern


def validate(data, version=catalogue.VERSION_MWG):
    need(isinstance(data, dict) and data.get('version') == VERSION and set(data) == {'version', 'fields', 'removalCategories', 'minimise'}, 'writes shape or version')
    known = catalogue.fields(version)
    seen = {}
    for name, spec in data['fields'].items():
        at = 'field ' + name
        need(name in known, at + ' is not a catalogue field')
        need(set(spec) == {'shape', 'limits', 'destinations'} and spec['shape'] in SHAPES, at + ' keys or shape')
        sources = known[name]['sources']
        roles = [d.get('role') for d in spec['destinations']]
        need(roles.count('primary') == 1 and set(roles) <= set(ROLES) and roles[0] == 'primary', at + ' needs exactly one leading primary destination')
        for d in spec['destinations']:
            need(d['family'] in ('xmp', 'iptc', 'exif'), at + ' destination family')
            need(isinstance(d.get('write'), str) and WRITE_NAME.fullmatch(d['write']) and WRITE_NAME.fullmatch(d.get('listing', '')), at + ' native names')
            need(d['write'] not in seen, '%s destination %s collides with field %s' % (at, d['write'], seen.get(d['write'])))
            seen[d['write']] = name
            if d['family'] == 'xmp':
                match = [s for s in sources if s['family'] == 'xmp' and s['property'] == d['property']]
            elif d['family'] == 'iptc':
                match = [s for s in sources if s['family'] == 'iptc' and (s['record'], s['dataset']) == (d['record'], d['dataset'])]
            else:
                match = [s for s in sources if s['family'] == 'exif' and (s['ifd'], s['tag']) == (d['ifd'], d['tag'])]
            need(len(match) == 1, '%s destination %s has no independent reader in the catalogue' % (at, d['write']))
    for name, cat in data['removalCategories'].items():
        at = 'category ' + name
        need(set(cat) >= {'label', 'description', 'exifIfds', 'exif', 'xmp', 'xmpNamespaces', 'iptc', 'psir', 'comment', 'native'}, at + ' keys')
        for e in cat['exif']:
            need((e['ifd'], int(e['tag'], 16)) not in RENDERING_EXIF, at + ' selects rendering metadata ' + e['name'])
        for pattern in cat['xmp']:
            need(XMP_PATTERN.fullmatch(pattern) and not any(xmp_match(pattern, r) for r in RENDERING_XMP), at + ' xmp selector ' + pattern)
        for group in cat['native']['observed']:
            need(not any(group['group1'] == g and (native_match(n, r) or native_match(r, n)) for n in group['names'] for g, r in RENDERING_NATIVE), at + ' native selector touches rendering metadata')
        for i in cat['iptc']:
            need(i['record'] == 2, at + ' iptc selector record')
    mini = data['minimise']
    need(set(mini) == {'label', 'description', 'deletes', 'comment', 'preserve', 'refuseIfPresent', 'xmpRendering'}, 'minimise keys')
    need(all(WRITE_NAME.fullmatch(d.replace(':all', ':x')) for d in mini['deletes']), 'minimise deletes are whole-group names')
    for e in mini['preserve']:
        need(e['ifd'] == 'InteropIFD' or (e['ifd'], int(e['tag'], 16)) in RENDERING_EXIF, 'minimise preserves only rendering metadata: ' + e['name'])
        need(WRITE_NAME.fullmatch(e['write']) and e['values'] and (e['numeric'] is False or all(type(v) is int for v in e['values'])), 'minimise preserve entry ' + e['name'])
    need(all((e['ifd'], int(e['tag'], 16)) in RENDERING_EXIF for e in mini['refuseIfPresent']), 'minimise refusals name rendering metadata')
    return data


_CACHE = []


def load():
    if not _CACHE:
        digest()
        data = json.loads(files(__package__).joinpath(FILE).read_text(encoding='utf-8'))
        validate(data)
        _CACHE.append(data)
    return _CACHE[0]


def fields(): return load()['fields']
def categories(): return load()['removalCategories']
def minimise(): return load()['minimise']
