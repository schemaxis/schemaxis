"""Independent consumer: parse HDF Group ``h5dump -x -p -m %.17g`` XML with the standard library.

The XML is produced by the separately installed HDF5 command-line tools (a different C library build
from the one bundled with h5py), so agreement with host expectations does not depend on h5py code.
Recognised limits, recorded in every report: fill values of non-native byte order are mis-rendered by
h5dump XML and are therefore checked through the fresh-process readback instead; values of compound,
vlen, array, opaque and reference elements are compared structurally (token streams), not per field type;
h5dump XML prints Cset="unknown_cset" for some UTF-8 strings, so that encoding is unobservable here (wildcard)
and remains checked by the readback. h5dump decodes LZF and scale-offset chunks but omits those filters
from its XML filter list, so their presence is checked by the readback only. Region-reference datasets are rendered as
object references without data ("Region references not supported"), so their kind and targets are readback-only.
"""
import math
import re
import xml.etree.ElementTree as ElementTree

from schemaxis.errors import fail

NS = '{https://raw.githubusercontent.com/HDFGroup/hdf5/develop/tools/test/h5dump/testfiles/xml/HDF5-File.xsd}'
UNNAMED_FILTERS = ('lzf', 'scaleoffset', 'nbit')
FILTER_NAMES = {'Deflate': 'gzip', 'Shuffle': 'shuffle', 'Fletcher32': 'fletcher32', 'SZIP': 'szip', 'NBit': 'nbit', 'ScaleOffset': 'scaleoffset'}


def tag(element):
    return element.tag[len(NS):] if element.tag.startswith(NS) else element.tag


def child(element, name):
    for item in element:
        if tag(item) == name:
            return item
    return None


def children(element, name):
    return [item for item in element if tag(item) == name]


def type_of(element):
    """Descriptor from a DataType element, in the host vocabulary (complex appears as compound r/i)."""
    inner = element[0] if len(element) else None
    if inner is None:
        return {'class': 'unknown'}
    kind = tag(inner)
    if kind == 'AtomicType':
        atom = inner[0]
        a = tag(atom)
        if a == 'IntegerType':
            return {'class': 'int' if atom.get('Sign') == 'true' else 'uint', 'bits': 8 * int(atom.get('Size')),
                    'order': 'big' if atom.get('ByteOrder') == 'BE' else 'little'}
        if a == 'FloatType':
            return {'class': 'float', 'bits': 8 * int(atom.get('Size')), 'order': 'big' if atom.get('ByteOrder') == 'BE' else 'little'}
        if a == 'StringType':
            cset = atom.get('Cset')
            out = {'class': 'string', 'encoding': 'utf-8' if cset == 'H5T_CSET_UTF8' else 'ascii' if cset == 'H5T_CSET_ASCII' else '*'}
            if atom.get('StrSize') != 'H5T_VARIABLE':
                out['length'] = int(atom.get('StrSize'))
            return out
        if a == 'ReferenceType':
            ref = atom[0] if len(atom) else None
            return {'class': 'reference', 'reference': 'region' if ref is not None and 'Region' in tag(ref) else 'object'}
        if a == 'EnumType':
            return enum_of(atom)
        if a == 'BitfieldType':
            return {'class': 'bitfield', 'bits': 8 * int(atom.get('Size')), 'order': 'big' if atom.get('ByteOrder') == 'BE' else 'little'}
        if a == 'OpaqueType':
            return {'class': 'opaque', 'size': int(atom.get('Size', 0))}
        return {'class': 'unknown', 'xml': a}
    if kind == 'CompoundType':
        return {'class': 'compound', 'fields': [{'name': f.get('FieldName'), 'type': type_of(child(f, 'DataType'))} for f in children(inner, 'Field')]}
    if kind == 'EnumType':
        return enum_of(inner)
    if kind == 'VLType':
        return {'class': 'vlen', 'base': type_of(child(inner, 'DataType'))}
    if kind == 'ArrayType':
        dims = [int(d.get('DimSize')) for d in children(inner, 'ArrayDimension')]
        return {**type_of(child(inner, 'DataType')), 'dims': dims}
    return {'class': 'unknown', 'xml': kind}


def enum_of(inner):
    base = type_of(child(inner, 'DataType'))
    names = [e.text.strip() for e in children(inner, 'EnumElement')]
    values = [int(e.text.strip()) for e in children(inner, 'EnumValue')]
    if sorted(names) == ['FALSE', 'TRUE'] and base.get('bits') == 8 and dict(zip(names, values)) == {'FALSE': 0, 'TRUE': 1}:
        return {'class': 'bool'}
    return {'class': 'enum', 'bits': base.get('bits'), 'signed': base.get('class') == 'int', 'order': base.get('order'),
            'members': sorted(({'name': n, 'value': v} for n, v in zip(names, values)), key=lambda m: m['value'])}


def shape_of(element):
    if element is None or not len(element):
        return None, None
    space = element[0]
    if tag(space) == 'ScalarDataspace':
        return [], []
    if tag(space) == 'SimpleDataspace':
        dims = children(space, 'Dimension')
        return ([int(d.get('DimSize')) for d in dims],
                ['unlimited' if d.get('MaxDimSize') == 'UNLIMITED' else int(d.get('MaxDimSize')) for d in dims])
    return None, None


def tokens(text):
    """Split DataFromFile text into tokens; quoted strings keep h5dump's escapes resolved."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == '"':
            j, buf = i + 1, []
            while j < n and text[j] != '"':
                if text[j] == '\\' and j + 1 < n:
                    nxt = text[j + 1]
                    if nxt in '01234567' and j + 3 < n and re.fullmatch(r'[0-7]{3}', text[j + 1:j + 4]):
                        buf.append(chr(int(text[j + 1:j + 4], 8)))
                        j += 4
                        continue
                    buf.append({'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}.get(nxt, nxt))
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            out.append(('s', ''.join(buf)))
            i = j + 1
            continue
        j = i
        while j < n and not text[j].isspace():
            j += 1
        out.append(('w', text[i:j]))
        i = j
    return out


def number(token, d):
    kind, text = token
    if kind != 'w':
        raise ValueError('expected a number')
    if d['class'] in ('int', 'uint'):
        return int(text)
    low = text.lower()
    if low in ('nan', '-nan'):
        return float('nan').hex()
    if low in ('inf', 'infinity'):
        return float('inf').hex()
    if low in ('-inf', '-infinity'):
        return float('-inf').hex()
    return float(text).hex()


def scalar(token, d):
    cls = d['class']
    if cls in ('int', 'uint', 'float'):
        return number(token, d)
    if cls == 'bitfield':
        text = token[1]
        return int(text.replace(':', ''), 16) if text.startswith('0x') or ':' in text else int(text)
    if cls == 'bool':
        return token[1] == 'TRUE'
    if cls == 'enum':
        names = {m['name']: m['value'] for m in d['members']}
        return names[token[1]]
    if cls == 'string':
        if token[0] != 's':
            if token[1] == 'NULL':
                return ''
            raise ValueError('expected a quoted string')
        return token[1].rstrip('\x00') if 'length' in d else token[1]
    if cls == 'opaque':
        return token[1].replace(':', '')
    raise ValueError('scalar class ' + cls)


def width(d):
    if d.get('dims'):
        n = 1
        for x in d['dims']:
            n *= x
        return n * width({k: v for k, v in d.items() if k != 'dims'})
    if d['class'] == 'compound':
        return sum(width(f['type']) for f in d['fields'])
    return 1


def element(stream, d):
    if d.get('dims'):
        n = 1
        for x in d['dims']:
            n *= x
        inner = {k: v for k, v in d.items() if k != 'dims'}
        return [element(stream, inner) for _ in range(n)]
    if d['class'] == 'compound':
        return [element(stream, f['type']) for f in d['fields']]
    return scalar(next(stream), d)


def plain(d):
    if d['class'] in ('reference', 'unknown'):
        return False
    if d['class'] == 'compound':
        return all(plain(f['type']) and f['type']['class'] != 'vlen' for f in d['fields'])
    if d['class'] == 'vlen':
        return plain(d['base'])
    return True


def values_of(data, d, count):
    """Canonical elements from a Data element, or None when outside the independent value scope."""
    if data is None:
        return None
    source = child(data, 'DataFromFile')
    if source is None:
        return None
    text = source.text or ''
    cls = d['class']
    if not plain(d):
        return None
    if cls == 'vlen' and d['base']['class'] in ('reference', 'unknown'):
        return None
    if cls == 'vlen':
        lines = [line for line in text.split('\n') if line.strip()]
        if len(lines) != count:
            return None
        return [[scalar(t, d['base']) for t in tokens(line)] for line in lines]
    stream = iter(tokens(text))
    out = [element(stream, d) for _ in range(count)]
    if next(stream, None) is not None:
        raise ValueError('extra tokens after the last element')
    return out


def complex_as_compound(d):
    if d.get('class') == 'compound' and [f['name'] for f in d['fields']] == ['r', 'i'] and all(f['type']['class'] == 'float' for f in d['fields']) \
            and d['fields'][0]['type'] == d['fields'][1]['type']:
        return {'class': 'complex', 'bits': 2 * d['fields'][0]['type']['bits'], 'order': d['fields'][0]['type']['order']}
    return d


def dimension_list(element):
    """Paths per axis from a DIMENSION_LIST attribute (vlen of object references)."""
    data = child(element, 'Data')
    source = child(data, 'DataFromFile') if data is not None else None
    if source is None:
        return None
    lines = (source.text or '').split('\n')[1:-1]
    return [[t[1] for t in tokens(line) if t[0] == 's'] for line in lines]


def attribute(element):
    if element.get('Name') == 'DIMENSION_LIST':
        rec = {'type': {'class': 'vlen', 'base': {'class': 'reference', 'reference': 'object'}}, 'scales': dimension_list(element)}
        shape, _ = shape_of(child(element, 'Dataspace'))
        rec['shape'] = shape
        return rec
    d = type_of(child(element, 'DataType'))
    shape, _ = shape_of(child(element, 'Dataspace'))
    data = child(element, 'Data')
    if shape is None or data is not None and child(data, 'NoData') is not None:
        return {'type': d, 'empty': True}
    n = 1
    for s in shape:
        n *= s
    return {'type': d, 'shape': shape, 'values': values_of(data, d, n)}


def layout_of(dataset):
    storage = child(dataset, 'StorageLayout')
    if storage is None or not len(storage):
        return {'layout': 'unknown'}
    item = storage[0]
    kind = tag(item)
    if kind == 'ChunkedLayout':
        filters = []
        required = child(item, 'RequiredFilter')
        for f in (required if required is not None else []):
            filters.append(FILTER_NAMES.get(tag(f), tag(f)))
        return {'layout': 'chunked', 'chunks': [int(c.get('DimSize')) for c in children(item, 'ChunkDimension')], 'filters': filters}
    if kind == 'ContiguousLayout':
        return {'layout': 'contiguous', 'filters': []}
    if kind == 'CompactLayout':
        return {'layout': 'compact', 'filters': []}
    if kind == 'ExternalLayout':
        return {'layout': 'external', 'filters': []}
    return {'layout': kind, 'filters': []}


def parse(data, limit=256 * 1024 * 1024):
    if len(data) > limit:
        fail('VERIFICATION_FAILED', 'h5dump XML exceeds its byte budget')
    if b'<!DOCTYPE' in data[:4096] or b'<!ENTITY' in data:
        fail('VERIFICATION_FAILED', 'h5dump XML contains declarations that are refused')
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        fail('VERIFICATION_FAILED', 'h5dump XML is not well formed: ' + str(error))
    group = child(root, 'RootGroup')
    if group is None:
        fail('VERIFICATION_FAILED', 'h5dump XML has no root group')
    objects, links, xids = {}, {}, {}
    named = {}
    for item in root.iter(NS + 'NamedDataType'):
        dt = child(item, 'DataType')
        named[item.get('H5Path')] = type_of(dt) if dt is not None else {'class': 'unknown'}

    def walk(element, path):
        rec_kind = tag(element)
        xid = element.get('OBJ-XID')
        rec = {'kind': 'group' if rec_kind in ('RootGroup', 'Group') else 'dataset', 'xid': xid,
               'attributes': {a.get('Name'): attribute(a) for a in children(element, 'Attribute')}}
        if rec_kind == 'Dataset':
            pointer = child(element, 'DatasetPtr')
            if pointer is not None:
                objects[path] = {'kind': 'alias', 'of': pointer.get('H5Path'), 'xid': pointer.get('OBJ-XID')}
                return
            dt = child(element, 'DataType')
            if dt is None and child(element, 'NamedDataTypePtr') is not None:
                pointer = child(element, 'NamedDataTypePtr').get('H5Path')
                d = named.get(pointer, {'class': 'unknown'})
                rec['committedType'] = pointer
            else:
                d = type_of(dt)
            shape, maxshape = shape_of(child(element, 'Dataspace'))
            rec.update({'type': d, 'shape': shape, 'maxshape': maxshape, **layout_of(element)})
            n = 1
            for s in shape or []:
                n *= s
            try:
                rec['values'] = [] if shape is not None and n == 0 else values_of(child(element, 'Data'), d, n)
            except (ValueError, KeyError, StopIteration, TypeError) as error:
                fail('VERIFICATION_FAILED', 'h5dump values cannot be read under the declared type: ' + str(error), path)
            data_element = child(element, 'Data')
            if d['class'] == 'reference' and data_element is not None and child(data_element, 'NoData') is not None:
                d = {'class': 'reference', 'reference': '*'}
            rec['type'] = complex_as_compound(d)
            if rec['type']['class'] == 'complex' and rec['values'] is not None:
                rec['values'] = [[v[0], v[1]] for v in rec['values']]
        objects[path] = rec
        if xid:
            xids[xid] = path
        for item in element:
            kind = tag(item)
            name = item.get('Name') or item.get('LinkName')
            if name is None:
                continue
            sub = (path.rstrip('/') + '/' + name)
            if kind in ('Group', 'Dataset'):
                pointer = child(item, 'GroupPtr') if kind == 'Group' else None
                if pointer is not None:
                    objects[sub] = {'kind': 'alias', 'of': pointer.get('H5Path'), 'xid': pointer.get('OBJ-XID')}
                    continue
                walk(item, sub)
            elif kind == 'NamedDataType':
                objects[sub] = {'kind': 'datatype', 'type': named.get(item.get('H5Path'), {'class': 'unknown'}),
                                'attributes': {a.get('Name'): attribute(a) for a in children(item, 'Attribute')}}
            elif kind == 'SoftLink':
                links[sub] = {'kind': 'soft', 'target': item.get('TargetPath')}
            elif kind == 'ExternalLink':
                links[sub] = {'kind': 'external', 'file': item.get('TargetFilename'), 'target': item.get('TargetPath')}
    walk(group, '/')
    return {'objects': objects, 'links': links}


def same_float(a, b):
    return a == b or a in ('nan', float('nan').hex()) and b in ('nan', float('nan').hex())


def same_type(observed, expected):
    """Type equality where h5dump could not observe a string encoding."""
    if isinstance(observed, dict) and isinstance(expected, dict):
        if set(observed) != set(expected):
            return False
        return all(observed[k] == '*' or same_type(observed[k], expected[k]) for k in observed)
    if isinstance(observed, list) and isinstance(expected, list):
        return len(observed) == len(expected) and all(same_type(a, b) for a, b in zip(observed, expected))
    return observed == expected


def ddl_values(text, d, path):
    """Numeric values of one dataset from ``h5dump -d PATH -y -w 0`` DDL output."""
    match = re.search(r'^[ \t]*DATA \{[ \t]*$', text, re.M)
    end = text.find('}', match.end()) if match else -1
    if end < 0:
        fail('VERIFICATION_FAILED', 'h5dump DDL has no data block', path)
    body = text[match.end():end].replace(',', ' ')
    try:
        return [number(('w', token), d) for token in body.split()]
    except ValueError as error:
        fail('VERIFICATION_FAILED', 'h5dump DDL values are not numbers: ' + str(error), path)
