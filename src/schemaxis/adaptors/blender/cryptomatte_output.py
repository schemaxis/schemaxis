"""Bounded embedded Cryptomatte metadata and independent standard ID hashing.

The interchange contract is defined by https://github.com/Psyop/Cryptomatte.
Names are hashed as UTF-8 bytes with MurmurHash3 x86/32, seed zero. Manifest
hexadecimal values retain the original integer; pixel IDs use exponent repair.
"""
import json
import re

from schemaxis.errors import fail


MASK = (1 << 32) - 1


def _require(condition, message):
    if not condition:
        fail('INVALID_RENDER_OUTPUT', message)


def name_hash(name):
    _require(isinstance(name, str), 'Cryptomatte name must be text')
    data = name.encode('utf-8')
    _require(len(data) <= 4096, 'Cryptomatte name exceeds 4096 UTF-8 bytes')
    def rotate(value, bits):
        return ((value << bits) | (value >> (32 - bits))) & MASK
    result = 0
    for offset in range(0, len(data) - len(data) % 4, 4):
        block = int.from_bytes(data[offset:offset + 4], 'little')
        block = rotate(block * 0xcc9e2d51 & MASK, 15) * 0x1b873593 & MASK
        result = rotate(result ^ block, 13)
        result = (result * 5 + 0xe6546b64) & MASK
    tail = data[len(data) - len(data) % 4:]
    if tail:
        block = int.from_bytes(tail, 'little')
        block = rotate(block * 0xcc9e2d51 & MASK, 15) * 0x1b873593 & MASK
        result ^= block
    result ^= len(data)
    result ^= result >> 16
    result = result * 0x85ebca6b & MASK
    result ^= result >> 13
    result = result * 0xc2b2ae35 & MASK
    return (result ^ (result >> 16)) & MASK


def pixel_bits(integer):
    _require(type(integer) is int and 0 <= integer <= MASK, 'Cryptomatte hash is not a uint32')
    return integer ^ (1 << 23) if (integer >> 23) & 255 in (0, 255) else integer


def layer_identifier(name):
    return format(name_hash(name), '08x')[:7]


def metadata(attributes):
    """Read embedded manifests only; metadata cannot request filesystem reads."""
    groups = {}
    for key, (kind, value) in attributes.items():
        if not key.startswith('cryptomatte/'):
            continue
        match = re.fullmatch(r'cryptomatte/([0-9a-f]{7})/(name|hash|conversion|manifest)', key)
        _require(match is not None and kind == 'string', 'Cryptomatte metadata needs reviewed embedded string fields')
        identifier, field = match.groups()
        group = groups.setdefault(identifier, {})
        _require(field not in group, 'Cryptomatte metadata repeats a field')
        group[field] = value.decode('utf-8')
    _require(len(groups) <= 48, 'Cryptomatte exceeds 48 embedded layer groups')
    total = 0
    def pairs(items):
        nonlocal total
        total += len(items)
        _require(total <= 16384, 'Cryptomatte manifests exceed 16384 entries')
        result = {}
        for name, value in items:
            _require(name not in result and isinstance(value, str)
                     and re.fullmatch(r'[0-9a-fA-F]{8}', value) is not None,
                     'Cryptomatte manifest has duplicate names or invalid hexadecimal IDs')
            _require(name_hash(name) == int(value, 16), 'Cryptomatte manifest ID differs from its UTF-8 name hash')
            result[name] = value.lower()
        encoded = [pixel_bits(int(value, 16)) for value in result.values()]
        _require(len(set(encoded)) == len(encoded), 'Cryptomatte names collide after pixel-ID conversion; rename the conflicting source identities')
        return dict(sorted(result.items()))
    result = {}
    for identifier, group in groups.items():
        _require(set(group) == {'name', 'hash', 'conversion', 'manifest'}, 'Cryptomatte metadata is incomplete')
        name = group['name']
        _require(name and '\0' not in name and len(name.encode('utf-8')) <= 256
                 and identifier == layer_identifier(name), 'Cryptomatte layer name and metadata identifier differ')
        _require(name not in result and group['hash'] == 'MurmurHash3_32'
                 and group['conversion'] == 'uint32_to_float32', 'Cryptomatte layer repeats or uses an unsupported ID encoding')
        try:
            manifest = json.loads(group['manifest'], object_pairs_hook=pairs)
        except (ValueError, RecursionError, UnicodeError) as error:
            fail('INVALID_RENDER_OUTPUT', 'Malformed embedded Cryptomatte manifest: ' + str(error))
        _require(isinstance(manifest, dict), 'Cryptomatte embedded manifest must be an object')
        result[name] = {'identifier': identifier, 'hash': group['hash'],
                        'conversion': group['conversion'], 'manifest': manifest}
    return dict(sorted(result.items()))
