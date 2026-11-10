"""The fixed native ExifTool listing: command, bounded strict parsing, instance-preserving observations and independent anchors.

Nothing authored reaches the command line: the argument list is a constant plus captured file names that the host chose. ExifTool's tag
names and values are observations, never declarations. Volatile filesystem/system observations are excluded by the fixed command
(``--System:all``); real native warnings and errors are kept, and unknown tags are listed, not dropped. Instance copies (a duplicate tag,
or the same tag name in two groups) keep their instance number, so nothing is lost to a duplicate JSON key.
"""
import json
import re

from schemaxis.adaptors.exiftool import catalogue, codecs

FIXED = ['-config', '', '-json', '-a', '-G0:1:4', '-n', '-e', '-u', '-q', '--System:all']
MAX_STDOUT = 64 * 1024 * 1024
MAX_TAGS = 4096
MAX_VALUE_CHARS = 65536
MAX_LIST = 4096
COPY = re.compile(r'Copy(\d+)', re.ASCII)
ANCHOR_REPORT = 8


class Number(str):
    """JSON number token kept as text so 1.50 and 007-like values compare exactly."""


class Bound(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def strict_loads(data):
    def pairs(items):
        if len({k for k, _ in items}) != len(items):
            raise ValueError('duplicate JSON key')
        return dict(items)

    def constant(name):
        raise ValueError('non-finite JSON number ' + name)
    text = data.decode('utf-8')
    if text.startswith('﻿'):
        raise ValueError('byte-order mark')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_int=Number, parse_float=Number)


def split_key(key):
    """``(group0, group1, instance, name)`` of one native key; the instance is 0 for the main copy."""
    parts = key.split(':')
    name = parts[-1]
    instance = 0
    if len(parts) >= 3 and COPY.fullmatch(parts[-2]):
        instance = int(COPY.fullmatch(parts[-2]).group(1))
        parts = parts[:-2] + [name]
    groups = parts[:-1]
    if not groups:
        return None
    return groups[0], groups[1] if len(groups) > 1 else groups[0], instance, name


def scalar(value, depth=0):
    if isinstance(value, (str, Number)):
        if len(value) > MAX_VALUE_CHARS:
            raise Bound('a native value exceeds %d characters' % MAX_VALUE_CHARS)
        return str(value) if not isinstance(value, Number) else value
    if isinstance(value, list) and depth == 0:
        if len(value) > MAX_LIST:
            raise Bound('a native list exceeds %d elements' % MAX_LIST)
        return [scalar(v, 1) for v in value]
    if value is None or isinstance(value, (bool, dict, list)):
        raise Bound('a native value has an unsupported nested or null shape')
    return value


def parse(stdout, names):
    """Per-file normalised native records in command order; raises ValueError for whole-listing problems."""
    if len(stdout) > MAX_STDOUT:
        raise ValueError('native listing exceeds %d bytes' % MAX_STDOUT)
    rows = strict_loads(stdout)
    if not isinstance(rows, list) or len(rows) != len(names):
        raise ValueError('ExifTool did not report exactly one record per captured file')
    out = []
    for row, name in zip(rows, names):
        if not isinstance(row, dict) or row.get('SourceFile') != name:
            raise ValueError('ExifTool record order or source differs from the captured file order')
        out.append(normalise(row))
    return out


def normalise(row):
    """``{'observations': [...], 'warnings': [...], 'errors': [...], 'fault': None | {...}}`` for one file record."""
    record = {'observations': [], 'warnings': [], 'errors': [], 'fault': None}
    if len(row) - 1 > MAX_TAGS:
        record['fault'] = {'code': 'NATIVE_LISTING_BOUND', 'message': 'ExifTool listed more than %d tags for one file' % MAX_TAGS}
        return record
    identities = {}
    try:
        for key, value in row.items():
            if key == 'SourceFile':
                continue
            parts = split_key(key)
            if parts is None:
                raise Bound('a native key has no group: ' + key[:60])
            group0, group1, instance, name = parts
            value = scalar(value)
            if (group0, name) in (('ExifTool', 'Warning'), ('ExifTool', 'Error')):
                record['warnings' if name == 'Warning' else 'errors'].append(value if isinstance(value, str) else str(value))
                continue
            record['observations'].append({'group0': group0, 'group1': group1, 'name': name, 'instance': instance, 'value': value})
            identities.setdefault((group0, group1, name), []).append(len(record['observations']) - 1)
    except Bound as error:
        record['fault'] = {'code': 'NATIVE_LISTING_BOUND', 'message': error.message}
        return record
    for indexes in identities.values():
        if len(indexes) > 1:
            for index in indexes:
                record['observations'][index]['ambiguous'] = True
    record['observations'].sort(key=lambda o: (o['group0'], o['group1'], o['name'], o['instance']))
    return record


def index(record):
    """Native values by ``group0:group1:name`` in instance order."""
    found = {}
    for o in record['observations']:
        found.setdefault('%s:%s:%s' % (o['group0'], alias_group(o), o['name']), []).append(o['value'])
    return found


def alias_group(o):
    """Family-1 group of an observation; native 13.55 names the IPTC of a Photoshop image-resource block (TIFF tag 0x8649) ``IPTC2``, the same IPTC fields as ``IPTC``."""
    return 'IPTC' if (o['group0'], o['group1']) == ('IPTC', 'IPTC2') else o['group1']


# E5: the native frame size of a non-JPEG container is reported under the container's own group, not under File: (the catalogue, which is pinned, keeps File:)
FRAME_NATIVE = {'File:ImageWidth': {'tiff': 'EXIF:IFD0:ImageWidth', 'dng': 'EXIF:IFD0:ImageWidth', 'png': 'PNG:ImageWidth', 'webp': 'RIFF:ImageWidth'},
                'File:ImageHeight': {'tiff': 'EXIF:IFD0:ImageHeight', 'dng': 'EXIF:IFD0:ImageHeight', 'png': 'PNG:ImageHeight', 'webp': 'RIFF:ImageHeight'}}


def native_key(spec, container):
    return FRAME_NATIVE.get(spec['native'], {}).get(container, spec['native'])


def lookup(found, key):
    parts = key.split(':')
    if len(parts) == 2:
        parts = [parts[0], parts[0], parts[1]]
    return found.get(':'.join(parts), [])


def anchors(record, fields, natives):
    """Mismatches between independent source decodes and native values: ``natives`` maps a source family to its native index (or None)."""
    problems, checked = [], 0
    for name, item in fields.items():
        for source in item['sources']:
            spec = source['_spec']
            found = natives.get('sidecar' if source['family'] == 'xmp-sidecar' else 'image')
            if found is None:
                continue
            tokens = lookup(found, native_key(spec, record.get('container')) if spec['family'] == 'container' else spec['native'])
            if spec['family'] == 'container' and len(tokens) > 1 and len(set(map(str, tokens))) == 1:
                tokens = tokens[:1]            # a WebP VP8X canvas and its bitstream both report the size; identical reports are one fact
            state = source['state']
            if state == 'absent' and not source.get('code'):
                checked += 1
                if tokens:
                    problems.append({'field': name, 'source': source['family'] + ':' + source['location'], 'message': 'native reports a value where the independent reader found none'})
                continue
            if state == 'ambiguous' and source.get('code') == 'EXIF_TAG_REPEATED':
                checked += 1
                if len(tokens) != source['instances']:
                    problems.append({'field': name, 'source': source['family'] + ':' + source['location'], 'message': 'native reports %d instances, the independent reader found %d' % (len(tokens), source['instances'])})
                continue
            if state == 'ambiguous' and source.get('code') == 'EXIF_COMPANION_REPEATED':
                checked += 1
                message = repeated_companion_mismatch(source, tokens, lookup(found, spec['companionNative'][source['companion']]))
                if message:
                    problems.append({'field': name, 'source': source['family'] + ':' + source['location'], 'message': message[:300]})
                continue
            if state != 'present':
                continue
            anchor = codecs.CODECS[spec['codec']][2]
            if isinstance(source['canonical'], tuple) and anchor is codecs.anchor_text:
                anchor = codecs.anchor_list
            if anchor is None:
                continue
            checked += 1
            message = anchor(source['canonical'], tokens, lambda key: lookup(found, key), spec)
            if message:
                problems.append({'field': name, 'source': source['family'] + ':' + source['location'], 'message': message[:300]})
            for companion, key in sorted(spec.get('companionNative', {}).items()) if spec['family'] == 'exif' else ():
                checked += 1
                message = companion_mismatch(companion, source['_companions'].get(companion), lookup(found, key))
                if message:
                    problems.append({'field': name, 'source': source['family'] + ':' + source['location'], 'message': message[:300]})
    return checked, problems


def repeated_companion_mismatch(source, tokens, companions):
    """A repeated reference tag leaves the main tag single, and native must list exactly the copies the independent reader found (as listed copies, in any order)."""
    if len(tokens) != 1:
        return 'native reports %d instances of the tag, the independent reader found 1 beside a repeated reference tag' % len(tokens)
    if len(companions) != source['instances']:
        return 'native reports %d instances of the reference tag, the independent reader found %d' % (len(companions), source['instances'])
    expected = source['_repeatedValues']
    if None not in expected and sorted(str(v) for v in expected) != sorted(codecs.as_text(t) for t in companions):
        return 'native reports %s for the repeated reference tag, the independent reader decoded %s' % ([codecs.as_text(t)[:20] for t in companions][:4], [str(v)[:20] for v in expected][:4])


def companion_mismatch(companion, expected, tokens):
    """A companion tag (a hemisphere or altitude reference) must match exactly what the independent reader read, and absent must stay absent."""
    if expected is None:
        if tokens:
            return 'native reports %s for the %s reference, the independent reader found none' % ([codecs.as_text(t)[:20] for t in tokens][:3], companion)
    elif len(tokens) != 1 or codecs.as_text(tokens[0]) != str(expected):
        return 'native reports %s for the %s reference, the independent reader decoded %r' % ([codecs.as_text(t)[:20] for t in tokens][:3], companion, expected)
