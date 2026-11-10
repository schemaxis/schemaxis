"""The write data of the time and location workflows (``writes-3.json``): load once, pin by digest, validate statically against the E3 catalogue view.

Like ``writes.json`` for the E2 edit family this is data, not per-field code: which catalogued time source is rewritten with which native assignment,
which GPS tags describe a fix (and so go stale when a position is replaced) and which are kept. Every time and position destination must be a source that
the E3 catalogue view's independent readers already understand, so a written value can be read back without ExifTool, and no destination may collide
with an E2 edit destination. Native names are group-qualified tag names that the planner turns into assignments; authored input never carries one.
"""
import hashlib
import json
from importlib.resources import files

from schemaxis.adaptors.exiftool import catalogue, writes

VERSION = 'schemaxis.exiftool.writes/3'
FILE = 'writes-3.json'
PIN = '51c2d45caa70498759f2281875629d521fbef369a55dd0d0b11ed4cd39203773'
TIME_GROUPS = ('captured', 'digitized', 'modified')


class E3WritesError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise E3WritesError(message)


def digest():
    found = hashlib.sha256(files(__package__).joinpath(FILE).read_bytes()).hexdigest()
    need(found == PIN, 'CATALOGUE_DIGEST_DRIFT: %s no longer has its pinned bytes (%s)' % (FILE, found))
    return found


def source_match(field, family, **where):
    """The catalogue sources of ``field`` at one location (exactly one is required)."""
    out = []
    for s in catalogue.fields(catalogue.VERSION_E3)[field]['sources']:
        if s['family'] != family:
            continue
        if family == 'exif' and (s['ifd'], s['tag']) == (where['ifd'], where['tag']):
            out.append(s)
        elif family == 'xmp' and s['property'] == where['property']:
            out.append(s)
        elif family == 'iptc' and (s['record'], s['dataset']) == (where['record'], where['dataset']):
            out.append(s)
    return out


def validate(data):
    need(isinstance(data, dict) and data.get('version') == VERSION and data.get('catalogue') == catalogue.VERSION_E3 and set(data) == {'version', 'catalogue', 'time', 'location', 'creation'}, 'e3 writes shape or version')
    known = catalogue.fields(catalogue.VERSION_E3)
    reserved = {d['write'] for f in writes.fields().values() for d in f['destinations']}
    seen = set()

    def claim(name, at):
        need(isinstance(name, str) and name and name not in reserved and name not in seen, '%s native name %r collides or is invalid' % (at, name))
        seen.add(name)
    need(tuple(data['time']) == TIME_GROUPS, 'time groups')
    for group, spec in data['time'].items():
        at = 'time ' + group
        for key in ('local', 'offset', 'subSecond', 'utc'):
            need(spec[key] in known, '%s %s is not a catalogue field' % (at, key))
        exif = spec['exif']
        for key in ('local', 'offset', 'subSecond'):
            claim(exif[key]['write'], at)
            ifd = exif['ifd'] if key == 'local' else 'ExifIFD'
            need(len(source_match(spec[key], 'exif', ifd=ifd, tag=exif[key]['tag'])) == 1, '%s exif %s has no independent reader' % (at, key))
        for entry in spec['xmp']:
            claim(entry['write'], at)
            for key in ('local', 'offset', 'subSecond'):
                need(len(source_match(spec[key], 'xmp', property=entry['property'])) == 1, '%s xmp %s has no independent %s reader' % (at, entry['property'], key))
        if 'iptc' in spec:
            for key, field in (('date', 'local'), ('time', 'offset')):
                entry = spec['iptc'][key]
                claim(entry['write'], at)
                need(len(source_match(spec[field], 'iptc', record=entry['record'], dataset=entry['dataset'])) == 1, '%s iptc %s has no independent reader' % (at, key))
    exif, xmp = data['location']['exif'], data['location']['xmp']
    for key, field, ifd in (('latitude', 'gpsLatitudeE3', 'GPS'), ('longitude', 'gpsLongitudeE3', 'GPS'), ('datum', 'gpsDatumE3', 'GPS'), ('horizontalError', 'gpsHorizontalError', 'GPS'), ('time', 'gpsUtcTimeExact', 'GPS')):
        claim(exif[key]['write'], 'location ' + key)
        need(len(source_match(field, 'exif', ifd=ifd, tag=exif[key]['tag'])) == 1, 'location exif %s has no independent reader' % key)
    for key in ('altitude', 'date', 'version'):
        claim(exif[key]['write'], 'location ' + key)
    for key in ('latitude', 'longitude', 'altitude'):
        claim(exif[key]['ref']['write'], 'location %s reference' % key)
    for key, field in (('latitude', 'gpsLatitudeE3'), ('longitude', 'gpsLongitudeE3'), ('datum', 'gpsDatumE3')):
        claim(xmp[key]['write'], 'location xmp ' + key)
        need(len(source_match(field, 'xmp', property=xmp[key]['property'])) == 1, 'location xmp %s has no independent reader' % key)
    for key in ('altitude', 'altitudeRef'):
        claim(xmp[key]['write'], 'location xmp ' + key)
    for group in ('stale', 'direction'):
        for family in ('exif', 'xmp'):
            for entry in data['location'][group][family]:
                claim(entry['write'], 'location %s %s' % (group, family))
    return data


_CACHE = []


def load():
    if not _CACHE:
        digest()
        data = json.loads(files(__package__).joinpath(FILE).read_text(encoding='utf-8'))
        validate(data)
        _CACHE.append(data)
    return _CACHE[0]


def time_groups(): return load()['time']
def location(): return load()['location']
def creation(): return load()['creation']
