"""Compact bounded reader and writer for classic NetCDF (CDF-1), original code written from the public
"NetCDF Classic Format" specification (Unidata NetCDF-C file format specifications).

Standard library only; it never imports xarray, NumPy, SciPy or another adaptor. Every count, length and
offset is checked against the remaining bytes and the declared limits before anything is allocated or
decoded. Only the fixed-dimension, non-record, uncompressed subset is read: a record (unlimited) dimension,
other format versions, unsupported types, overlapping, gapped or trailing data and non-zero padding are
refused with stable located faults rather than skipped.
"""
import math
import re
import struct

LIMITS = {'maxBytes': 4 * 1024 * 1024, 'maxDims': 4, 'maxVars': 5, 'maxAttrs': 8, 'maxName': 40, 'maxAttrName': 32,
          'maxText': 128, 'maxAxis': 4096, 'maxCells': 262144}
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,39}')
ATTRIBUTE_NAME = re.compile(r'_?[A-Za-z][A-Za-z0-9_]{0,31}')
TEXT = re.compile(r'[ -~]{0,128}')
DIMENSION, VARIABLE, ATTRIBUTE = 10, 11, 12
CHAR, INT, DOUBLE = 2, 4, 6
SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 4, 6: 8}
KINDS = {'char': CHAR, 'int': INT, 'double': DOUBLE}


class CdfError(Exception):
    def __init__(self, code, message, location='$'):
        super().__init__(message)
        self.code, self.message, self.location = code, message, location


def pad(n):
    return -n % 4


class Cursor:
    def __init__(self, data, limit):
        self.data, self.at, self.limit = data, 0, limit

    def take(self, n, where):
        if n < 0 or self.at + n > self.limit:
            raise CdfError('XR_CDF_MALFORMED', 'header is truncated or a count exceeds the file', where)
        chunk = self.data[self.at:self.at + n]
        self.at += n
        return chunk

    def word(self, where):
        return struct.unpack('>I', self.take(4, where))[0]

    def padding(self, n, where):
        if any(self.take(pad(n), where)):
            raise CdfError('XR_CDF_MALFORMED', 'padding bytes are not zero', where)

    def name(self, where, maximum, pattern):
        n = self.word(where)
        if n == 0 or n > maximum:
            raise CdfError('XR_RESOURCE_LIMIT', 'name length is outside 1..%d' % maximum, where)
        raw = self.take(n, where)
        self.padding(n, where)
        try:
            text = raw.decode('ascii')
        except UnicodeDecodeError:
            raise CdfError('XR_CDF_NAME', 'names are plain ASCII', where)
        if not pattern.fullmatch(text):
            raise CdfError('XR_CDF_NAME', 'names are identifiers: a letter then letters, digits or _ (attributes may start with _)', where)
        return text


def attributes(cursor, where, limits):
    tag, count = cursor.word(where), cursor.word(where)
    if (tag, count) == (0, 0):
        return {}
    if tag != ATTRIBUTE or not 0 < count <= limits['maxAttrs']:
        raise CdfError('XR_RESOURCE_LIMIT' if tag == ATTRIBUTE else 'XR_CDF_MALFORMED',
                       'attribute list is malformed or exceeds %d attributes' % limits['maxAttrs'], where)
    result = {}
    for _ in range(count):
        name = cursor.name(where, limits['maxAttrName'], ATTRIBUTE_NAME)
        at = where + '.' + name
        if name in result:
            raise CdfError('XR_CDF_DUPLICATE', 'duplicate attribute', at)
        kind, n = cursor.word(at), cursor.word(at)
        if kind not in (CHAR, DOUBLE):
            raise CdfError('XR_TYPE_UNSUPPORTED', 'only text and double attributes are supported', at)
        if n == 0 or n > limits['maxText'] or (kind == DOUBLE and n != 1):
            raise CdfError('XR_RESOURCE_LIMIT', 'attribute length is outside its bound', at)
        raw = cursor.take(n * SIZES[kind], at)
        cursor.padding(n * SIZES[kind], at)
        if kind == CHAR:
            text = raw.decode('latin-1')
            if not TEXT.fullmatch(text):
                raise CdfError('XR_ATTRIBUTE_VALUE', 'text attributes are printable ASCII of at most 128 characters', at)
            result[name] = ('char', text)
        else:
            value = struct.unpack('>d', raw)[0]
            if not math.isfinite(value):
                raise CdfError('XR_ATTRIBUTE_VALUE', 'numeric attributes are finite', at)
            result[name] = ('double', value)
    return result


def parse(data, limits=LIMITS):
    """Decode a CDF-1 file into {'dims': [(name, length)], 'attrs': {...}, 'vars': [...]} with values as lists."""
    if len(data) > limits['maxBytes']:
        raise CdfError('XR_RESOURCE_LIMIT', 'file exceeds %d bytes' % limits['maxBytes'], '$.source')
    if data[:3] != b'CDF' or len(data) < 8:
        raise CdfError('XR_UNSUPPORTED_FORMAT', 'only classic NetCDF files beginning CDF\\x01 are supported', '$.source')
    if data[3] != 1:
        raise CdfError('XR_UNSUPPORTED_FORMAT', 'CDF version byte %d is not classic CDF-1 (64-bit offset and CDF-5 are refused)'
                       % data[3], '$.source')
    cursor = Cursor(data, len(data))
    cursor.at = 4
    if cursor.word('numrecs') != 0:
        raise CdfError('XR_UNLIMITED_DIMENSION', 'record data (non-zero record count) is not supported', 'numrecs')
    tag, count = cursor.word('dims'), cursor.word('dims')
    dims = []
    if (tag, count) != (0, 0):
        if tag != DIMENSION or not 0 < count <= limits['maxDims']:
            raise CdfError('XR_RESOURCE_LIMIT' if tag == DIMENSION else 'XR_CDF_MALFORMED',
                           'dimension list is malformed or exceeds %d dimensions' % limits['maxDims'], 'dims')
        for i in range(count):
            name = cursor.name('dims', limits['maxName'], NAME)
            length = cursor.word('dims.' + name)
            if length == 0:
                raise CdfError('XR_UNLIMITED_DIMENSION', 'unlimited (record) dimensions are not supported', 'dims.' + name)
            if length > limits['maxAxis']:
                raise CdfError('XR_RESOURCE_LIMIT', 'axis length exceeds %d' % limits['maxAxis'], 'dims.' + name)
            if any(name == existing for existing, _ in dims):
                raise CdfError('XR_CDF_DUPLICATE', 'duplicate dimension name', 'dims.' + name)
            dims.append((name, length))
    attrs = attributes(cursor, 'attrs', limits)
    tag, count = cursor.word('vars'), cursor.word('vars')
    variables = []
    if (tag, count) != (0, 0):
        if tag != VARIABLE or not 0 < count <= limits['maxVars']:
            raise CdfError('XR_RESOURCE_LIMIT' if tag == VARIABLE else 'XR_CDF_MALFORMED',
                           'variable list is malformed or exceeds %d variables' % limits['maxVars'], 'vars')
        for _ in range(count):
            name = cursor.name('vars', limits['maxName'], NAME)
            at = 'vars.' + name
            if any(name == v['name'] for v in variables):
                raise CdfError('XR_CDF_DUPLICATE', 'duplicate variable name', at)
            rank = cursor.word(at)
            if not 0 < rank <= limits['maxDims']:
                raise CdfError('XR_RESOURCE_LIMIT', 'variable rank is outside 1..%d' % limits['maxDims'], at)
            ids = [cursor.word(at) for _ in range(rank)]
            if any(i >= len(dims) for i in ids) or len(set(ids)) != rank:
                raise CdfError('XR_CDF_MALFORMED', 'variable dimension ids are out of range or repeated', at)
            vattrs = attributes(cursor, at, limits)
            kind, vsize, begin = cursor.word(at), cursor.word(at), cursor.word(at)
            if kind not in (INT, DOUBLE):
                raise CdfError('XR_TYPE_UNSUPPORTED', 'only int and double variables are supported (type code %d)' % kind, at)
            cells = 1
            for i in ids:
                cells *= dims[i][1]
            if cells > limits['maxCells']:
                raise CdfError('XR_RESOURCE_LIMIT', 'variable exceeds %d cells' % limits['maxCells'], at)
            if vsize != cells * SIZES[kind] + pad(cells * SIZES[kind]):
                raise CdfError('XR_CDF_MALFORMED', 'variable size does not equal its dimensions', at)
            variables.append({'name': name, 'dims': [dims[i][0] for i in ids], 'attrs': vattrs,
                              'type': 'int' if kind == INT else 'double', 'size': vsize, 'begin': begin, 'cells': cells})
    # Data layout: regions must tile the bytes after the header exactly (no overlap, gap or trailing data).
    expected = cursor.at
    for v in sorted(variables, key=lambda v: v['begin']):
        if v['begin'] < expected:
            raise CdfError('XR_CDF_LAYOUT', 'variable data overlaps the header or another variable', 'vars.' + v['name'])
        if v['begin'] > expected:
            raise CdfError('XR_CDF_LAYOUT', 'unaccounted bytes before variable data', 'vars.' + v['name'])
        expected += v['size']
    if expected > len(data):
        raise CdfError('XR_CDF_MALFORMED', 'variable data extends beyond the file', 'vars')
    if expected < len(data):
        raise CdfError('XR_CDF_LAYOUT', 'trailing bytes after the last variable', 'vars')
    total = sum(v['cells'] for v in variables)
    if total > limits['maxCells'] * 2:
        raise CdfError('XR_RESOURCE_LIMIT', 'total cells exceed the bound', 'vars')
    for v in variables:
        fmt = '>%d%s' % (v['cells'], 'i' if v['type'] == 'int' else 'd')
        width = SIZES[INT if v['type'] == 'int' else DOUBLE] * v['cells']
        values = list(struct.unpack(fmt, data[v['begin']:v['begin'] + width]))
        if any(data[v['begin'] + width:v['begin'] + v['size']]):
            raise CdfError('XR_CDF_MALFORMED', 'padding bytes are not zero', 'vars.' + v['name'])
        v['values'] = values
    return {'dims': dims, 'attrs': attrs, 'vars': variables}


def _name(text):
    raw = text.encode('ascii')
    return struct.pack('>I', len(raw)) + raw + b'\0' * pad(len(raw))


def _attributes(items):
    if not items:
        return struct.pack('>II', 0, 0)
    out = struct.pack('>II', ATTRIBUTE, len(items))
    for name, kind, value in items:
        out += _name(name)
        if kind == 'char':
            raw = value.encode('ascii')
            out += struct.pack('>II', CHAR, len(raw)) + raw + b'\0' * pad(len(raw))
        else:
            out += struct.pack('>IId', DOUBLE, 1, value)
    return out


def write(dims, attrs, variables):
    """Encode a CDF-1 file. dims [(name, length)], attrs [(name, 'char'|'double', value)], variables
    [{'name', 'dims': [names], 'type': 'int'|'double', 'attrs': [...], 'values': flat list}]."""
    index = {name: i for i, (name, _) in enumerate(dims)}
    head = b'CDF\x01' + struct.pack('>I', 0)
    if dims:
        head += struct.pack('>II', DIMENSION, len(dims)) + b''.join(_name(n) + struct.pack('>I', k) for n, k in dims)
    else:
        head += struct.pack('>II', 0, 0)
    head += _attributes(attrs)
    body = b''
    rows = []
    for v in variables:
        code = INT if v['type'] == 'int' else DOUBLE
        cells = 1
        for d in v['dims']:
            cells *= dims[index[d]][1]
        if cells != len(v['values']):
            raise ValueError('value count does not match dimensions of ' + v['name'])
        raw = struct.pack('>%d%s' % (cells, 'i' if code == INT else 'd'), *v['values'])
        raw += b'\0' * pad(len(raw))
        rows.append((v, code, raw))
    entries = []
    for v, code, raw in rows:
        entry = _name(v['name']) + struct.pack('>I', len(v['dims'])) + b''.join(struct.pack('>I', index[d]) for d in v['dims'])
        entry += _attributes(v.get('attrs', []))
        entries.append((entry + struct.pack('>II', code, len(raw)), raw))
    listing = struct.pack('>II', VARIABLE, len(entries)) if entries else struct.pack('>II', 0, 0)
    begin = len(head) + len(listing) + sum(len(e) + 4 for e, _ in entries)
    out = head + listing
    for entry, raw in entries:
        out += entry + struct.pack('>I', begin)
        body += raw
        begin += len(raw)
    return out + body
