"""Chunk indexes (extract format ``chunks``): every allocated chunk's position, file offset, size and filter mask.

The native worker lists chunks with h5py's direct chunk API. The host then reads each chunk's raw bytes
from the published file itself, checks the Fletcher-32 checksum, inflates and unshuffles them in pure
Python in the pipeline order the index states (only the filter set is known independently; a wrong order
cannot decode to the independent values) and compares every in-bounds element with the independent h5dump
values, so the index is checked against the stored bytes rather than trusted. Allocated chunk bytes must also add up to the
allocated size reported by HDF Group h5ls. Because equal chunks can hold identical bytes, decoded values alone cannot
bind a listed file position to its logical chunk: a fresh h5py process lists the current file's chunks again (HDF5's own
chunk records) and the published index must equal that listing exactly.
"""
import hashlib
import itertools
import json
import math
import struct
import zlib

from schemaxis.errors import fail
from . import expect, model

DECODABLE = ('shuffle', 'gzip', 'fletcher32')
FILTER_CODES = {'gzip': 1, 'shuffle': 2, 'fletcher32': 3}
MAX_CHUNK_BYTES = 64 * 1024 * 1024
MAX_CHUNKS = 1000000
FORMATS = {('int', 8): 'b', ('int', 16): 'h', ('int', 32): 'i', ('int', 64): 'q', ('uint', 8): 'B', ('uint', 16): 'H',
           ('uint', 32): 'I', ('uint', 64): 'Q', ('float', 16): 'e', ('float', 32): 'f', ('float', 64): 'd'}


def check_indexable(obj, at):
    """Chunk indexes are offered for chunked integer and float datasets whose filters the host can decode itself."""
    t = model.resolved(obj['type'])
    if obj.get('layout') != 'chunked':
        fail('INVALID_HDF5_EXTRACT', 'a chunk index needs a chunked dataset', at + '.format', layout=obj.get('layout'))
    if t['class'] not in ('int', 'uint', 'float') or t.get('dims'):
        fail('INVALID_HDF5_EXTRACT', 'chunk indexes are offered for integer and float datasets', at + '.format', type=t)
    names = [f['name'] if isinstance(f, dict) else f for f in obj.get('filters', [])]
    unknown = [n for n in names if n not in DECODABLE]
    if unknown:
        fail('INVALID_HDF5_EXTRACT', 'chunk indexes are offered for gzip, shuffle and fletcher32 pipelines, which the host decodes '
             'independently', at + '.format', filters=names)
    return t, names


def fletcher32(data):
    """HDF5's Fletcher-32 over 16-bit big-endian words (an odd trailing byte is the high byte)."""
    sum1 = sum2 = 0
    words = len(data) // 2
    i = 0
    while words:
        block = min(words, 360)
        words -= block
        for _ in range(block):
            sum1 += (data[i] << 8) | data[i + 1]
            sum2 += sum1
            i += 2
        sum1 = (sum1 & 0xffff) + (sum1 >> 16)
        sum2 = (sum2 & 0xffff) + (sum2 >> 16)
    if len(data) % 2:
        sum1 += data[i] << 8
        sum2 += sum1
        sum1 = (sum1 & 0xffff) + (sum1 >> 16)
        sum2 = (sum2 & 0xffff) + (sum2 >> 16)
    sum1 = (sum1 & 0xffff) + (sum1 >> 16)
    sum2 = (sum2 & 0xffff) + (sum2 >> 16)
    return (sum2 << 16) | sum1


def unshuffle(data, size):
    n = len(data) // size
    out = bytearray(len(data))
    for b in range(size):
        out[b:n * size:size] = data[b * n:(b + 1) * n]
    out[n * size:] = data[n * size:]
    return bytes(out)


def decode(raw, filters, mask, size, expected_bytes, at):
    """Undo the pipeline in reverse order; a set mask bit means that filter was skipped for this chunk."""
    data = raw
    for k in reversed(range(len(filters))):
        if mask >> k & 1:
            continue
        name = filters[k]
        if name == 'fletcher32':
            if len(data) < 4 or fletcher32(data[:-4]) != struct.unpack('<I', data[-4:])[0]:
                fail('VERIFICATION_FAILED', 'a chunk fails its Fletcher-32 checksum', at)
            data = data[:-4]
        elif name == 'gzip':
            inflater = zlib.decompressobj()
            try:
                data = inflater.decompress(data, expected_bytes + 1)
            except zlib.error:
                fail('VERIFICATION_FAILED', 'a chunk does not inflate', at)
            if len(data) > expected_bytes or inflater.unconsumed_tail:
                fail('VERIFICATION_FAILED', 'a chunk inflates beyond its declared size', at)
        else:
            data = unshuffle(data, size)
    if len(data) != expected_bytes:
        fail('VERIFICATION_FAILED', 'a decoded chunk has the wrong size', at, expected=expected_bytes, observed=len(data))
    return data


def elements(data, t):
    code = ('>' if t.get('order') == 'big' else '<') + FORMATS[(t['class'], t['bits'])]
    values = [v[0] for v in struct.iter_unpack(code, data)]
    return [float(v).hex() for v in values] if t['class'] == 'float' else values


def check(directory, target, item, obj, values, allocated):
    """Check a published chunk index against the stored bytes, the independent values and h5ls's allocated size; return its summary."""
    at = '$.extracts.' + item['id']
    t, filters = check_indexable(obj, at)
    raw_index = (directory / item['output']).read_bytes()
    try:
        index = json.loads(raw_index)
    except ValueError:
        fail('VERIFICATION_FAILED', 'the chunk index is not JSON', item['output'])
    shape, chunk_shape = obj['shape'], obj['chunks']
    if index.get('dataset') != item['dataset'] or index.get('shape') != shape or index.get('chunkShape') != chunk_shape \
            or not isinstance(index.get('filters'), list) or sorted(index['filters']) != sorted(filters) or index.get('type') != t:
        fail('VERIFICATION_FAILED', 'the chunk index header differs from the independent reading', item['output'])
    filters = index['filters']
    chunks = index.get('chunks')
    if not isinstance(chunks, list) or len(chunks) > MAX_CHUNKS:
        fail('VERIFICATION_FAILED', 'the chunk index lists no chunks array', item['output'])
    size = t['bits'] // 8
    per_chunk = math.prod(chunk_shape)
    strides = [math.prod(shape[k + 1:]) for k in range(len(shape))]
    covered = {}
    total = 0
    with open(directory / target, 'rb') as stream:
        for n, c in enumerate(chunks):
            where = '%s.chunks[%d]' % (item['output'], n)
            offset = c.get('offset')
            if not isinstance(offset, list) or len(offset) != len(shape) or any(type(o) is not int or o < 0 or o % k or o >= s
                                                                                  for o, k, s in zip(offset, chunk_shape, shape)):
                fail('VERIFICATION_FAILED', 'a chunk offset is not a chunk boundary inside the dataset', where)
            if tuple(offset) in covered:
                fail('VERIFICATION_FAILED', 'a chunk is listed twice', where)
            if type(c.get('size')) is not int or not 0 < c['size'] <= MAX_CHUNK_BYTES or type(c.get('byteOffset')) is not int or c['byteOffset'] < 0:
                fail('VERIFICATION_FAILED', 'a chunk has an invalid file position', where)
            stream.seek(c['byteOffset'])
            raw = stream.read(c['size'])
            if len(raw) != c['size'] or hashlib.sha256(raw).hexdigest() != c.get('sha256'):
                fail('VERIFICATION_FAILED', 'the chunk bytes at the listed offset differ from the index', where)
            mask = c.get('filterMask')
            if type(mask) is not int or not 0 <= mask < 2 ** len(filters):
                fail('VERIFICATION_FAILED', 'a chunk has an invalid filter mask', where)
            decoded = elements(decode(raw, filters, mask, size, per_chunk * size, where), t)
            for local, value in enumerate(decoded):
                position, rest = [], local
                for k in range(len(shape)):
                    inner = math.prod(chunk_shape[k + 1:])
                    position.append(offset[k] + rest // inner)
                    rest %= inner
                if all(p < s for p, s in zip(position, shape)):
                    flat = sum(p * s for p, s in zip(position, strides))
                    if value != values[flat]:
                        fail('VERIFICATION_FAILED', 'a decoded chunk element differs from the independent value', where, element=position,
                             expected=values[flat], observed=value)
            covered[tuple(offset)] = True
            total += c['size']
    check_unallocated(obj, t, values, covered, item['output'])
    if allocated is not None and total != allocated:
        fail('VERIFICATION_FAILED', 'chunk sizes do not add up to the allocated bytes reported by h5ls', item['output'], index=total, h5ls=allocated)
    return {'count': len(chunks), 'bytes': total, 'decoded': len(chunks), 'filters': filters}


def check_listing(index, listing, at):
    """The published chunk list must be exactly HDF5's own record for the current bytes (position, file offset, size, mask, digest)."""
    if index.get('chunkShape') != listing['chunkShape'] or index.get('filters') != listing['filters']:
        fail('VERIFICATION_FAILED', 'the chunk index layout differs from a fresh HDF5 chunk listing', at)
    if index.get('chunks') != listing['chunks']:
        published = index.get('chunks') or []
        first = next((n for n, (a, b) in enumerate(zip(published, listing['chunks'])) if a != b), min(len(published), len(listing['chunks'])))
        fail('VERIFICATION_FAILED', 'the chunk index differs from a fresh HDF5 chunk listing of the current file', '%s.chunks[%d]' % (at, first),
             published=published[first] if first < len(published) else None, fresh=listing['chunks'][first] if first < len(listing['chunks']) else None)


def check_unallocated(obj, t, values, covered, at):
    """Elements outside every allocated chunk read back as the dataset fill value."""
    shape, chunk_shape = obj['shape'], obj['chunks']
    fill = obj.get('fill', 0)
    fill = fill if isinstance(fill, str) else expect.canonical(fill, t)
    strides = [math.prod(shape[k + 1:]) for k in range(len(shape))]
    grid = [range(0, s, k) for s, k in zip(shape, chunk_shape)]
    for offset in itertools.product(*grid):
        if offset in covered:
            continue
        for position in itertools.product(*[range(o, min(o + k, s)) for o, k, s in zip(offset, chunk_shape, shape)]):
            flat = sum(p * s for p, s in zip(position, strides))
            if values[flat] != fill:
                fail('VERIFICATION_FAILED', 'an element outside every allocated chunk is not the fill value', at, element=list(position))
