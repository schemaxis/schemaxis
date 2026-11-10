"""Closed inline-ASCII VTK XML captures, checked before any native parser.

This intentionally supports three self-contained leaf formats only. It is not
a general VTK XML reader, companion-file resolver or native data verifier.
"""
import math
import os
from pathlib import Path
import re
import stat
import xml.etree.ElementTree as ET

from schemaxis.observations import fail

MAX_BYTES = 32 * 1024 * 1024
MAX_ELEMENTS = 65536
MAX_DEPTH = 32
MAX_VALUES = 1000000
MAX_DIMENSION = 4096
TYPES = {'.vtr': 'RectilinearGrid', '.vts': 'StructuredGrid', '.vtt': 'Table'}
NUMERIC_TYPES = {'Float32', 'Float64', 'Int8', 'UInt8', 'Int16', 'UInt16',
                 'Int32', 'UInt32', 'Int64', 'UInt64'}
ACTIVE = {'Scalars', 'Vectors', 'Normals', 'Tensors', 'TCoords', 'GlobalIds', 'PedigreeIds'}
ATTRIBUTES = {'VTKFile': {'type', 'version', 'byte_order', 'header_type'},
              'RectilinearGrid': {'WholeExtent'}, 'StructuredGrid': {'WholeExtent'},
              'Table': set(), 'Piece': {'Extent', 'NumberOfRows'},
              'PointData': ACTIVE, 'CellData': ACTIVE, 'RowData': ACTIVE,
              'FieldData': set(), 'Points': set(), 'Coordinates': set(),
              'DataArray': {'type', 'Name', 'NumberOfComponents', 'NumberOfTuples',
                            'format', 'RangeMin', 'RangeMax'}}
CHILDREN = {'VTKFile': set(TYPES.values()), 'RectilinearGrid': {'Piece', 'FieldData'},
            'StructuredGrid': {'Piece', 'FieldData'}, 'Table': {'Piece', 'FieldData'},
            'Piece': {'PointData', 'CellData', 'RowData', 'Points', 'Coordinates'},
            **{name: {'DataArray'} for name in ('PointData', 'CellData', 'RowData', 'FieldData', 'Points', 'Coordinates')},
            'DataArray': set()}
NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z')
INTEGER = re.compile(r'[+-]?[0-9]+\Z')


def _refuse(message):
    fail('INPUT_CONTENT_UNSUPPORTED', message, '$.inputs')


def validate_leaf(path, *, vtk_type, max_bytes=MAX_BYTES):
    """Read one already-owned immutable file; no referenced path is ever opened."""
    path = Path(path)
    if (TYPES.get(path.suffix.lower()) != vtk_type or type(max_bytes) is not int
            or not 1 <= max_bytes <= MAX_BYTES):
        _refuse('capture format or byte limit differs from the declared VTK leaf contract')
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= max_bytes:
                _refuse('VTK XML capture must be a bounded regular file')
            raw = stream.read(max_bytes+1)
            after = os.fstat(stream.fileno())
            if (len(raw) != info.st_size or len(raw) > max_bytes
                    or (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    != (info.st_size, info.st_mtime_ns, info.st_ctime_ns)):
                _refuse('VTK XML capture changed while being validated')
    except OSError:
        _refuse('VTK XML capture cannot be safely read')
    # Reject before the XML parser: DTD/entity expansion and processing
    # instructions can never acquire their own file/network authority.
    if (b'\0' in raw or re.search(br'<!\s*(?:DOCTYPE|ENTITY)', raw, re.I)
            or re.search(br'<\?(?!xml(?:\s|\?>))', raw, re.I)):
        _refuse('VTK XML captures exclude DTDs, entities and processing instructions')
    try:
        raw.decode('utf-8')
        root = ET.fromstring(raw)
    except (UnicodeError, ET.ParseError):
        _refuse('VTK XML capture must be one well-formed UTF-8 document')
    if (root.tag != 'VTKFile' or root.get('type') != vtk_type
            or len(root) != 1 or root[0].tag != vtk_type):
        _refuse('VTK XML root type differs from its declared self-contained leaf format')
    leaf = root[0]
    pieces = [child for child in leaf if child.tag == 'Piece']
    if len(pieces) != 1:
        _refuse('VTK XML leaf captures require exactly one bounded piece')
    piece = pieces[0]
    def integer(value, lower, upper):
        if (type(value) is not str or len(value) > 16 or INTEGER.fullmatch(value) is None
                or not lower <= int(value) <= upper):
            _refuse('VTK XML structural integers exceed their declared bounds')
        return int(value)
    def extent(value):
        tokens = (value or '').split()
        if len(tokens) != 6:
            _refuse('VTK XML structured extents require six bounded integers')
        result = [integer(token, -MAX_VALUES, MAX_VALUES) for token in tokens]
        dims = [result[index+1]-result[index]+1 for index in (0, 2, 4)]
        if any(not 1 <= size <= MAX_DIMENSION for size in dims) or math.prod(dims) > MAX_VALUES:
            _refuse('VTK XML structured dimensions exceed their point budget')
        return result, dims
    expected = {}
    if vtk_type == 'Table':
        if set(piece.attrib) != {'NumberOfRows'}:
            _refuse('VTK XML table piece requires a bounded row count only')
        expected['RowData'] = integer(piece.get('NumberOfRows'), 0, MAX_VALUES)
        allowed_piece = {'RowData'}
    else:
        if set(piece.attrib) != {'Extent'}:
            _refuse('VTK XML grid piece requires a bounded extent only')
        whole, _ = extent(leaf.get('WholeExtent'))
        local, dims = extent(piece.get('Extent'))
        if any(local[index] < whole[index] or local[index+1] > whole[index+1] for index in (0, 2, 4)):
            _refuse('VTK XML piece extent escapes its whole extent')
        expected.update(PointData=math.prod(dims), CellData=math.prod(max(1, size-1) for size in dims))
        allowed_piece = {'PointData', 'CellData', 'Coordinates' if vtk_type == 'RectilinearGrid' else 'Points'}
    if any(child.tag not in allowed_piece for child in piece):
        _refuse('VTK XML piece elements differ from its declared data type')
    for tag in allowed_piece:
        if sum(child.tag == tag for child in piece) > 1:
            _refuse('VTK XML leaf contains repeated array containers')
    if vtk_type != 'Table':
        geometry_tag = 'Coordinates' if vtk_type == 'RectilinearGrid' else 'Points'
        geometry = [child for child in piece if child.tag == geometry_tag]
        if len(geometry) != 1 or len(geometry[0]) != (3 if vtk_type == 'RectilinearGrid' else 1):
            _refuse('VTK XML structured geometry requires exact coordinate arrays')
    count = values = 0
    pending = [(root, 0, None)]
    while pending:
        element, depth, parent = pending.pop()
        count += 1
        if count > MAX_ELEMENTS or depth > MAX_DEPTH:
            _refuse('VTK XML capture exceeds its element or depth limit')
        if (element.tag not in ATTRIBUTES or set(element.attrib)-ATTRIBUTES[element.tag]
                or any(child.tag not in CHILDREN[element.tag] for child in element)):
            _refuse('VTK XML capture contains an undeclared element, attribute or file reference')
        if element.tag == 'DataArray':
            dtype = element.get('type')
            if element.get('format') != 'ascii' or dtype not in NUMERIC_TYPES:
                _refuse('VTK XML capture supports only inline ASCII numeric arrays')
            components = integer(element.get('NumberOfComponents', '1'), 1, 16)
            tuples = integer(element.get('NumberOfTuples', '0'), 0, MAX_VALUES)
            array_values = 0
            for match in re.finditer(r'\S+', element.text or ''):
                values += 1
                array_values += 1
                token = match.group()
                grammar = NUMBER if dtype.startswith('Float') else INTEGER
                if (values > MAX_VALUES or len(token) > 64 or grammar.fullmatch(token) is None
                        or not math.isfinite(float(token))):
                    _refuse('VTK XML numeric arrays exceed their finite literal value budget')
                if dtype.startswith(('Int', 'UInt')):
                    bits = int(dtype.removeprefix('UInt').removeprefix('Int'))
                    lower = 0 if dtype.startswith('U') else -(2**(bits-1))
                    upper = 2**bits-1 if dtype.startswith('U') else 2**(bits-1)-1
                    if not lower <= int(token) <= upper:
                        _refuse('VTK XML integer literal exceeds its declared numeric type')
                elif dtype == 'Float32' and abs(float(token)) > 3.4028234663852886e38:
                    _refuse('VTK XML float literal exceeds its declared numeric type')
            if array_values % components or ('NumberOfTuples' in element.attrib and array_values != tuples*components):
                _refuse('VTK XML array values disagree with its tuple/component counts')
            if parent.tag in expected and array_values != expected[parent.tag]*components:
                _refuse('VTK XML array tuples disagree with its declared structural dimensions')
            if parent.tag == 'Points' and (components != 3 or array_values != expected['PointData']*3):
                _refuse('VTK XML point coordinates disagree with its declared dimensions')
            if parent.tag == 'Coordinates':
                index = list(parent).index(element)
                if components != 1 or array_values != dims[index]:
                    _refuse('VTK XML rectilinear coordinates disagree with its declared dimensions')
            for name in ('RangeMin', 'RangeMax'):
                if name in element.attrib:
                    token = element.attrib[name]
                    if len(token) > 64 or NUMBER.fullmatch(token) is None or not math.isfinite(float(token)):
                        _refuse('VTK XML array range must be a finite bounded literal')
        elif element.text and element.text.strip():
            _refuse('VTK XML leaf structure contains unexpected character data')
        if element.tail and element.tail.strip():
            _refuse('VTK XML leaf structure contains unexpected trailing character data')
        pending.extend((child, depth+1, element) for child in element)
    return {'format': vtk_type, 'bytes': len(raw), 'elements': count, 'numericValues': values,
            'scope': 'Closed inline ASCII input grammar; native readback verifies actual data separately.'}
