"""Independent host expectations for HDF5 content, computed only from authored intent and captured bytes.

Nothing here imports h5py or NumPy. Element values use one canonical JSON form: integers and enum codes
as integers, floats as ``float.hex`` text (so -0.0, NaN and infinities stay exact), complex numbers as
``[real, imaginary]`` pairs of such text, strings as text, compound records and array/vlen elements as
lists, opaque bytes as lower-case hex and missing references as null. The native readback computes the
same form from what it actually reads, in a separate process, with its own code.
"""
import ast
import csv
import hashlib
import io
import json
import math
import re
import struct

from schemaxis.errors import fail

FORMATS = {16: '<e', 32: '<f', 64: '<d'}


def round_float(x, bits):
    if bits == 64 or not math.isfinite(x):
        return x
    try:
        return struct.unpack(FORMATS[bits], struct.pack(FORMATS[bits], x))[0]
    except OverflowError:
        return math.copysign(math.inf, x)


def canonical(value, t):
    """Canonical form of one host-checked element of resolved type ``t``."""
    cls = t['class']
    if t.get('dims'):
        inner = {k: v for k, v in t.items() if k != 'dims'}
        return [canonical(v, inner) for v in value]
    if cls == 'float':
        return float(value).hex()
    if cls == 'complex':
        return [float(value[0]).hex(), float(value[1]).hex()]
    if cls == 'compound':
        return [canonical(v, f['type']) for v, f in zip(value, t['fields'])]
    if cls == 'vlen':
        return [canonical(v, t['base']) for v in value]
    if cls == 'array':
        return canonical(value, t['base'])
    return value


def default_fill(t):
    cls = t['class']
    if t.get('dims'):
        n = 1
        for d in t['dims']:
            n *= d
        inner = {k: v for k, v in t.items() if k != 'dims'}
        return [default_fill(inner)] * n
    if cls in ('int', 'uint', 'enum'):
        return 0
    if cls == 'float':
        return 0.0
    if cls == 'complex':
        return [0.0, 0.0]
    if cls == 'bool':
        return False
    if cls == 'string':
        return ''
    if cls == 'compound':
        return [default_fill(f['type']) for f in t['fields']]
    if cls == 'vlen':
        return []
    if cls == 'array':
        return default_fill(t['base'])
    if cls == 'opaque':
        return '00' * t['size']
    return None


class Digest:
    """Streaming SHA-256 of the canonical JSON list of elements."""

    def __init__(self):
        self.hash = hashlib.sha256(b'[')
        self.count = 0

    def add(self, element):
        if self.count:
            self.hash.update(b',')
        self.hash.update(json.dumps(element, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode())
        self.count += 1

    def result(self):
        h = self.hash.copy()
        h.update(b']')
        return {'count': self.count, 'sha256': h.hexdigest()}


PREVIEW = 64


def summary(elements):
    d = Digest()
    head = []
    for e in elements:
        if len(head) < PREVIEW:
            head.append(e)
        d.add(e)
    return {**d.result(), 'head': head}


def generated(data, t, n):
    """Yield host-checked element values of a generator source (documented formulas, not library calls)."""
    src = data['source']
    cls = t['class']
    if src == 'range':
        start, step = data['start'], data['step']
        if cls == 'float':
            for i in range(n):
                v = round_float(float(start) + float(i) * float(step), t['bits'])
                yield v if math.isfinite(v) else repr(v)
        else:
            for i in range(n):
                yield int(start) + i * int(step)
        return
    start, stop = float(data['start']), float(data['stop'])
    step = (stop - start) / (n - 1)
    for i in range(n):
        v = round_float(stop if i == n - 1 else start + float(i) * step, t['bits'])
        yield v if math.isfinite(v) else repr(v)


# ---------------------------------------------------------------- captured inputs
def parse_csv(data, delimiter, at):
    try:
        text = data.decode('utf-8-sig')
    except UnicodeError:
        fail('INVALID_HDF5_INPUT', 'CSV inputs are UTF-8 text', at)
    rows = list(csv.reader(io.StringIO(text, newline=''), delimiter='\t' if delimiter == 'tab' else delimiter, strict=True))
    if not rows or not rows[0]:
        fail('INVALID_HDF5_INPUT', 'CSV inputs start with a header row', at)
    header = rows[0]
    if len(set(header)) != len(header) or any(not h.strip() for h in header):
        fail('INVALID_HDF5_INPUT', 'CSV header names are unique and nonblank', at)
    body = [r for r in rows[1:] if r != []]
    for i, r in enumerate(body):
        if len(r) != len(header):
            fail('INVALID_HDF5_INPUT', 'every CSV row has one cell per header column', at, row=i + 2)
    return header, body


def csv_cell(text, t, at):
    cls = t['class']
    if cls in ('int', 'uint', 'enum'):
        if not re.fullmatch(r'[+-]?[0-9]+', text.strip()):
            if cls == 'enum' and text.strip() in {m['name'] for m in t['members']}:
                return text.strip()
            fail('INVALID_HDF5_INPUT', 'integer cell is not a decimal integer', at, cell=text[:40])
        return int(text)
    if cls == 'float':
        s = text.strip().lower()
        if s in ('nan', 'inf', '+inf', '-inf', 'infinity', '-infinity'):
            return float(s.replace('infinity', 'inf'))
        if not re.fullmatch(r'[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?', s):
            fail('INVALID_HDF5_INPUT', 'float cell is not a decimal number', at, cell=text[:40])
        return float(s)
    if cls == 'bool':
        s = text.strip().lower()
        if s not in ('true', 'false', '1', '0'):
            fail('INVALID_HDF5_INPUT', 'bool cells are true/false or 1/0', at, cell=text[:40])
        return s in ('true', '1')
    if cls == 'string':
        return text
    fail('INVALID_HDF5_INPUT', 'CSV cells feed numeric, bool, enum or string elements', at)


NPY_TYPES = {'b1': ('bool', 8), 'i1': ('int', 8), 'i2': ('int', 16), 'i4': ('int', 32), 'i8': ('int', 64),
             'u1': ('uint', 8), 'u2': ('uint', 16), 'u4': ('uint', 32), 'u8': ('uint', 64),
             'f2': ('float', 16), 'f4': ('float', 32), 'f8': ('float', 64)}
STRUCT = {('int', 8): 'b', ('int', 16): 'h', ('int', 32): 'i', ('int', 64): 'q', ('uint', 8): 'B', ('uint', 16): 'H',
          ('uint', 32): 'I', ('uint', 64): 'Q', ('float', 16): 'e', ('float', 32): 'f', ('float', 64): 'd', ('bool', 8): '?'}


def parse_npy(data, at):
    """Independent reader for simple C-order NumPy .npy files of bool/int/uint/float elements."""
    if data[:6] != b'\x93NUMPY' or len(data) < 10:
        fail('INVALID_HDF5_INPUT', 'not a .npy file', at)
    major = data[6]
    if major == 1:
        hlen, offset = struct.unpack('<H', data[8:10])[0], 10
    elif major in (2, 3):
        hlen, offset = struct.unpack('<I', data[8:12])[0], 12
    else:
        fail('INVALID_HDF5_INPUT', 'unsupported .npy format version', at)
    try:
        header = ast.literal_eval(data[offset:offset + hlen].decode('latin-1'))
        descr, fortran, shape = header['descr'], header['fortran_order'], tuple(header['shape'])
    except (ValueError, SyntaxError, KeyError, TypeError, UnicodeError):
        fail('INVALID_HDF5_INPUT', 'malformed .npy header', at)
    if fortran:
        fail('INVALID_HDF5_INPUT', 'Fortran-ordered .npy arrays are refused; save C-ordered data', at)
    if not isinstance(descr, str) or descr[1:] not in NPY_TYPES or descr[0] not in '<>|=':
        fail('INVALID_HDF5_INPUT', '.npy inputs hold bool, integer or float elements', at, descr=str(descr)[:40])
    if descr[0] == '=':
        descr = '<' + descr[1:]
    cls, bits = NPY_TYPES[descr[1:]]
    order = '>' if descr[0] == '>' else '<'
    n = 1
    for d in shape:
        n *= d
    body = data[offset + hlen:]
    size = bits // 8
    if len(body) != n * size:
        fail('INVALID_HDF5_INPUT', '.npy payload length does not match its shape', at)
    values = list(struct.unpack(order + STRUCT[(cls, bits)] * n, body)) if n else []
    return {'class': cls, 'bits': bits, 'order': 'big' if order == '>' else 'little'}, list(shape), values


def parse_raw(data, item, at):
    t = item['type']
    n = 1
    for d in item['shape']:
        n *= d
    size = t['bits'] // 8
    start = item['offset']
    if start + n * size > len(data):
        fail('INVALID_HDF5_INPUT', 'raw input is shorter than offset plus shape times element size', at)
    order = '>' if t['order'] == 'big' else '<'
    return list(struct.unpack(order + STRUCT[(t['class'], t['bits'])] * n, data[start:start + n * size]))


def natural(value, t):
    """Canonical element -> natural JSON (finite floats as numbers, non-finite as text)."""
    cls = t['class']
    if t.get('dims'):
        inner = {k: v for k, v in t.items() if k != 'dims'}
        return [natural(v, inner) for v in value]
    if cls == 'float':
        x = float.fromhex(value)
        return x if math.isfinite(x) else repr(x)
    if cls == 'complex':
        return [natural(v, {'class': 'float'}) for v in value]
    if cls == 'compound':
        return [natural(v, f['type']) for v, f in zip(value, t['fields'])]
    if cls == 'vlen':
        return [natural(v, t['base']) for v in value]
    return value
