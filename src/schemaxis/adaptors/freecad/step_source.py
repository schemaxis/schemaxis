"""Bounded ISO 10303-21 admission for one external STEP solid; host-only.

This is a lexical scanner and entity-reference walk, not a geometry reader. It
tokenises strings, comments and lists, builds the instance table, and follows the
single SHAPE_DEFINITION_REPRESENTATION to the admitted B-rep and its assigned
length unit. Unreferenced B-reps, representations and unit contexts, product
structure, transformations, external references and entity types outside a
closed vocabulary are refused, so the native reader never chooses between them.
Geometry facts still come only from the native reader and the analyst's
expectations.
"""
import hashlib
import math
import os
import re
from pathlib import Path
from schemaxis.errors import fail

MAX_BYTES = 32*1024*1024
MAX_ENTITIES = 100000
MAX_LOOP_EDGES = 2000
MAX_STRING = 65536
MAX_TOKEN = 256
MAX_NESTING = 16
MAX_LIST = 100000
MAX_HEADER_BYTES = 65536
# Our own exports are verified with the same reference walk but larger caps;
# the import caps bound untrusted inputs, not this adaptor's publications.
EXPORT_LIMITS = {'bytes': 256*1024*1024, 'entities': 2000000, 'loopEdges': None}

SCHEMAS = {'CONFIG_CONTROL_DESIGN': 'AP203', 'AUTOMOTIVE_DESIGN': 'AP214',
           'AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF': 'AP242'}
UNITS = ('mm', 'cm', 'm', 'inch')
MILLIMETRES = {'mm': 1.0, 'cm': 10.0, 'm': 1000.0, 'inch': 25.4}

SOLIDS = {'MANIFOLD_SOLID_BREP', 'BREP_WITH_VOIDS'}
REPRESENTATIONS = {'SHAPE_REPRESENTATION', 'ADVANCED_BREP_SHAPE_REPRESENTATION', 'DEFINITIONAL_REPRESENTATION'}
CONTEXTS = {'GEOMETRIC_REPRESENTATION_CONTEXT', 'GLOBAL_UNIT_ASSIGNED_CONTEXT', 'REPRESENTATION_CONTEXT',
            'PARAMETRIC_REPRESENTATION_CONTEXT', 'GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT'}
RELATIONSHIPS = {'SHAPE_REPRESENTATION_RELATIONSHIP', 'REPRESENTATION_RELATIONSHIP'}
# Closed vocabulary: product/context/unit records, one representation chain,
# B-rep topology and the analytic and spline geometry OCCT writes for solids.
VOCABULARY = SOLIDS | REPRESENTATIONS | CONTEXTS | RELATIONSHIPS | {
    'APPLICATION_CONTEXT', 'APPLICATION_PROTOCOL_DEFINITION', 'PRODUCT_CONTEXT', 'MECHANICAL_CONTEXT', 'PRODUCT',
    'PRODUCT_DEFINITION_FORMATION', 'PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE', 'PRODUCT_DEFINITION_CONTEXT',
    'DESIGN_CONTEXT', 'PRODUCT_DEFINITION', 'PRODUCT_DEFINITION_SHAPE', 'PRODUCT_CATEGORY', 'PRODUCT_RELATED_PRODUCT_CATEGORY',
    'SHAPE_DEFINITION_REPRESENTATION', 'UNCERTAINTY_MEASURE_WITH_UNIT', 'LENGTH_MEASURE_WITH_UNIT',
    'PLANE_ANGLE_MEASURE_WITH_UNIT', 'NAMED_UNIT', 'SI_UNIT', 'LENGTH_UNIT', 'PLANE_ANGLE_UNIT', 'SOLID_ANGLE_UNIT',
    'CONVERSION_BASED_UNIT', 'DIMENSIONAL_EXPONENTS',
    'REPRESENTATION_ITEM', 'GEOMETRIC_REPRESENTATION_ITEM', 'TOPOLOGICAL_REPRESENTATION_ITEM',
    'VERTEX_POINT', 'EDGE_CURVE', 'ORIENTED_EDGE', 'EDGE_LOOP', 'VERTEX_LOOP', 'LOOP', 'PATH', 'FACE_BOUND',
    'FACE_OUTER_BOUND', 'ADVANCED_FACE', 'FACE_SURFACE', 'CLOSED_SHELL', 'ORIENTED_CLOSED_SHELL',
    'CARTESIAN_POINT', 'DIRECTION', 'VECTOR', 'AXIS1_PLACEMENT', 'AXIS2_PLACEMENT_2D', 'AXIS2_PLACEMENT_3D',
    'LINE', 'CIRCLE', 'ELLIPSE', 'PARABOLA', 'HYPERBOLA', 'POLYLINE', 'CURVE', 'BOUNDED_CURVE', 'B_SPLINE_CURVE',
    'B_SPLINE_CURVE_WITH_KNOTS', 'BEZIER_CURVE', 'UNIFORM_CURVE', 'QUASI_UNIFORM_CURVE', 'RATIONAL_B_SPLINE_CURVE',
    'TRIMMED_CURVE', 'COMPOSITE_CURVE', 'COMPOSITE_CURVE_SEGMENT', 'SURFACE_CURVE', 'SEAM_CURVE', 'PCURVE',
    'OFFSET_CURVE_3D', 'SURFACE', 'BOUNDED_SURFACE', 'PLANE', 'CYLINDRICAL_SURFACE', 'CONICAL_SURFACE',
    'SPHERICAL_SURFACE', 'TOROIDAL_SURFACE', 'DEGENERATE_TOROIDAL_SURFACE', 'SURFACE_OF_LINEAR_EXTRUSION',
    'SURFACE_OF_REVOLUTION', 'SWEPT_SURFACE', 'OFFSET_SURFACE', 'B_SPLINE_SURFACE', 'B_SPLINE_SURFACE_WITH_KNOTS',
    'BEZIER_SURFACE', 'UNIFORM_SURFACE', 'QUASI_UNIFORM_SURFACE', 'RATIONAL_B_SPLINE_SURFACE',
    'RECTANGULAR_TRIMMED_SURFACE', 'CONIC', 'ELEMENTARY_SURFACE', 'PLACEMENT', 'POINT'}
REFUSED = {'NEXT_ASSEMBLY_USAGE_OCCURRENCE': 'assembly structure', 'MAPPED_ITEM': 'instanced geometry',
           'REPRESENTATION_MAP': 'instanced geometry', 'CONTEXT_DEPENDENT_SHAPE_REPRESENTATION': 'assembly placement',
           'REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION': 'a transformed representation relationship',
           'ITEM_DEFINED_TRANSFORMATION': 'a transformed representation relationship'}

TOKEN = re.compile(r"""(?P<ws>[ \t\r\n]+)|(?P<comment>/\*.*?\*/)|(?P<string>'(?:[^']|'')*')|(?P<binary>"[0-9A-F]*")
|(?P<ref>\#[0-9]{1,9})|(?P<enum>\.[A-Z_][A-Z0-9_]*\.)|(?P<number>[+-]?[0-9]+(?:\.[0-9]*)?(?:E[+-]?[0-9]+)?)
|(?P<keyword>!?[A-Z_][A-Z0-9_]*(?:-[0-9A-Z_]+)*)|(?P<punct>[(),;=$*])""", re.X | re.S)


class _Refuse(Exception):
    def __init__(self, code, message, **detail):
        super().__init__(message); self.code, self.detail = code, detail


def _tokens(text):
    position, size = 0, len(text)
    while position < size:
        match = TOKEN.match(text, position)
        if match is None:
            raise _Refuse('UNSUPPORTED_SOURCE', 'STEP text contains an unterminated comment or unsupported character',
                          offset=position, near=text[position:position+20])
        kind = match.lastgroup
        value = match.group(kind)
        position = match.end()
        if kind in ('ws', 'comment'):
            continue
        if kind in ('string', 'binary'):
            if len(value) > MAX_STRING:
                raise _Refuse('RESOURCE_LIMIT', 'STEP string or binary literal exceeds the admission bound', limit=MAX_STRING)
        elif len(value) > MAX_TOKEN:
            raise _Refuse('RESOURCE_LIMIT', 'STEP token exceeds the admission bound', limit=MAX_TOKEN)
        if kind == 'keyword' and value.startswith('!'):
            raise _Refuse('UNSUPPORTED_SOURCE', 'User-defined STEP entities are not supported', entity=value)
        yield kind, value


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.current = next(tokens, None)

    def take(self, kind=None, value=None):
        token = self.current
        if token is None or (kind and token[0] != kind) or (value is not None and token[1] != value):
            raise _Refuse('UNSUPPORTED_SOURCE', 'STEP file structure is malformed',
                          expected=value or kind, found=None if token is None else token[1][:40])
        self.current = next(self.tokens, None)
        return token[1]

    def peek(self, value):
        return self.current is not None and self.current[1] == value

    def parameters(self, depth=0):
        if depth > MAX_NESTING:
            raise _Refuse('RESOURCE_LIMIT', 'STEP parameter nesting exceeds the admission bound', limit=MAX_NESTING)
        self.take('punct', '(')
        values = []
        if self.peek(')'):
            self.take(); return values
        while True:
            values.append(self.value(depth))
            if len(values) > MAX_LIST:
                raise _Refuse('RESOURCE_LIMIT', 'STEP list exceeds the admission bound', limit=MAX_LIST)
            if self.peek(','):
                self.take(); continue
            self.take('punct', ')')
            return values

    def value(self, depth):
        kind, token = self.current if self.current else (None, None)
        if token == '(':
            return self.parameters(depth+1)
        if kind == 'keyword':
            name = self.take()
            return ('typed', name, self.parameters(depth+1))
        if kind == 'ref':
            self.take(); return ('ref', int(token[1:]))
        if kind == 'string':
            self.take(); return ('string', token[1:-1].replace("''", "'"))
        if kind == 'enum':
            self.take(); return ('enum', token[1:-1])
        if kind == 'number':
            self.take()
            number = float(token)
            if not math.isfinite(number):
                raise _Refuse('UNSUPPORTED_SOURCE', 'STEP number is not finite')
            return number
        if kind == 'binary':
            self.take(); return ('binary', token)
        if token in ('$', '*'):
            self.take(); return token
        raise _Refuse('UNSUPPORTED_SOURCE', 'STEP parameter is malformed', found=(token or '')[:40])


def _instance(parser):
    """One `#n = ENTITY(...)` or complex `#n = (A(...) B(...))` record: {type: parameters}."""
    if parser.peek('('):
        parser.take()
        parts = {}
        while not parser.peek(')'):
            name = parser.take('keyword')
            if name in parts:
                raise _Refuse('UNSUPPORTED_SOURCE', 'STEP complex instance repeats a partial entity', entity=name)
            parts[name] = parser.parameters(1)
            if len(parts) > 32:
                raise _Refuse('RESOURCE_LIMIT', 'STEP complex instance has too many partial entities')
        parser.take()
        if not parts:
            raise _Refuse('UNSUPPORTED_SOURCE', 'STEP complex instance is empty')
        return parts
    name = parser.take('keyword')
    return {name: parser.parameters(0)}


def _refs(value, found):
    if isinstance(value, tuple):
        if value[0] == 'ref':
            found.append(value[1])
        elif value[0] == 'typed':
            _refs(value[2], found)
    elif isinstance(value, list):
        for item in value:
            _refs(item, found)
    return found


def _parse(data, limits):
    if data[:2] == b'\x1f\x8b' or data[:4] == b'PK\x03\x04':
        raise _Refuse('UNSUPPORTED_SOURCE', 'Compressed STEP (.stpZ or zip) is not supported; supply plain ISO 10303-21 text')
    try:
        text = data.decode('ascii')
    except UnicodeDecodeError:
        raise _Refuse('UNSUPPORTED_SOURCE', 'STEP text must be ASCII; non-ASCII characters must use Part 21 escapes') from None
    parser = _Parser(_tokens(text))
    parser.take('keyword', 'ISO-10303-21'); parser.take('punct', ';')
    parser.take('keyword', 'HEADER'); parser.take('punct', ';')
    header = {}
    while not parser.peek('ENDSEC'):
        name = parser.take('keyword')
        if name in header:
            raise _Refuse('UNSUPPORTED_SOURCE', 'STEP header repeats an entity', entity=name)
        header[name] = parser.parameters(0)
        parser.take('punct', ';')
        if len(header) > 16:
            raise _Refuse('UNSUPPORTED_SOURCE', 'STEP header has unsupported entries')
    parser.take(); parser.take('punct', ';')
    if not {'FILE_DESCRIPTION', 'FILE_NAME', 'FILE_SCHEMA'} <= set(header):
        raise _Refuse('UNSUPPORTED_SOURCE', 'STEP header lacks FILE_DESCRIPTION, FILE_NAME or FILE_SCHEMA')
    schemas = header['FILE_SCHEMA'][0] if header['FILE_SCHEMA'] and isinstance(header['FILE_SCHEMA'][0], list) else None
    if not schemas or len(schemas) != 1 or not isinstance(schemas[0], tuple) or schemas[0][0] != 'string':
        raise _Refuse('UNSUPPORTED_SOURCE', 'STEP FILE_SCHEMA must name exactly one schema')
    schema_name = re.split(r'[ {]', schemas[0][1].strip(), maxsplit=1)[0].upper()
    if schema_name not in SCHEMAS:
        raise _Refuse('UNSUPPORTED_SOURCE', 'STEP schema is not AP203, AP214 or AP242', schema=schemas[0][1][:120])
    if not parser.peek('DATA'):
        raise _Refuse('UNSUPPORTED_SOURCE', 'STEP file must have one DATA section after its header (no anchor or reference sections)')
    parser.take(); parser.take('punct', ';')
    table = {}
    while not parser.peek('ENDSEC'):
        identifier = int(parser.take('ref')[1:])
        parser.take('punct', '=')
        if identifier in table:
            raise _Refuse('UNSUPPORTED_SOURCE', 'STEP instance identifier is duplicated', instance=identifier)
        table[identifier] = _instance(parser)
        parser.take('punct', ';')
        if len(table) > limits['entities']:
            raise _Refuse('RESOURCE_LIMIT', 'STEP file exceeds the admitted entity count', limit=limits['entities'])
    parser.take(); parser.take('punct', ';')
    parser.take('keyword', 'END-ISO-10303-21'); parser.take('punct', ';')
    if parser.current is not None:
        raise _Refuse('UNSUPPORTED_SOURCE', 'STEP file has content after END-ISO-10303-21 (one DATA section only)')
    return SCHEMAS[schema_name], table


def _types(table, identifier):
    return set(table[identifier])


def _params(table, identifier, name):
    return table[identifier].get(name)


def _length_unit(table, identifier, depth=0):
    """mm/cm/m from SI_UNIT, inch from a conversion-based unit of exactly 25.4 mm."""
    record = table[identifier]
    if 'LENGTH_UNIT' not in record:
        return None
    if 'SI_UNIT' in record:
        prefix, name = (record['SI_UNIT'] + [None, None])[:2]
        if name != ('enum', 'METRE'):
            raise _Refuse('UNSUPPORTED_UNITS', 'STEP length unit is not based on the metre')
        unit = {'$': 'm', ('enum', 'MILLI'): 'mm', ('enum', 'CENTI'): 'cm'}.get(prefix) if isinstance(prefix, (str, tuple)) else None
        if unit is None:
            raise _Refuse('UNSUPPORTED_UNITS', 'STEP length unit prefix is outside mm, cm and m', prefix=str(prefix))
        return unit
    if 'CONVERSION_BASED_UNIT' in record and depth == 0:
        parameters = record['CONVERSION_BASED_UNIT']
        if len(parameters) != 2 or not isinstance(parameters[1], tuple) or parameters[1][0] != 'ref':
            raise _Refuse('UNSUPPORTED_UNITS', 'STEP conversion-based length unit is malformed')
        measure = table[parameters[1][1]]
        values = measure.get('LENGTH_MEASURE_WITH_UNIT')
        if not values or len(values) != 2 or not isinstance(values[0], tuple) or values[0][0] != 'typed' \
                or values[0][1] != 'LENGTH_MEASURE' or len(values[0][2]) != 1 or not isinstance(values[0][2][0], float) \
                or not isinstance(values[1], tuple) or values[1][0] != 'ref':
            raise _Refuse('UNSUPPORTED_UNITS', 'STEP conversion-based length unit is malformed')
        factor, base = values[0][2][0], _length_unit(table, values[1][1], depth+1)
        millimetres = factor*MILLIMETRES.get(base, math.nan)
        if math.isclose(millimetres, 25.4, rel_tol=1e-12):
            return 'inch'
        raise _Refuse('UNSUPPORTED_UNITS', 'STEP conversion-based length unit is not the inch', millimetres=millimetres)
    raise _Refuse('UNSUPPORTED_UNITS', 'STEP length unit form is not supported')


def _context_unit(table, identifier):
    record = table.get(identifier)
    if record is None or 'GLOBAL_UNIT_ASSIGNED_CONTEXT' not in record or 'GEOMETRIC_REPRESENTATION_CONTEXT' not in record:
        raise _Refuse('UNDECLARED_UNIT', 'The admitted representation context assigns no units')
    dimension = record['GEOMETRIC_REPRESENTATION_CONTEXT']
    if dimension != [3.0]:
        raise _Refuse('UNSUPPORTED_SOURCE', 'The admitted representation context is not three-dimensional')
    units = record['GLOBAL_UNIT_ASSIGNED_CONTEXT']
    if len(units) != 1 or not isinstance(units[0], list) or any(not (isinstance(u, tuple) and u[0] == 'ref') for u in units[0]):
        raise _Refuse('UNSUPPORTED_SOURCE', 'STEP unit assignment is malformed')
    lengths = [unit for unit in (_length_unit(table, ref[1]) for ref in units[0]) if unit]
    if not lengths:
        raise _Refuse('UNDECLARED_UNIT', 'The admitted representation context assigns no length unit; units are never assumed')
    if len(set(lengths)) != 1 or len(lengths) != 1:
        raise _Refuse('UNDECLARED_UNIT', 'The admitted representation context assigns more than one length unit', units=lengths)
    return lengths[0]


def _representation(table, identifier, kinds):
    record = table.get(identifier)
    names = set(record or ()) & REPRESENTATIONS
    if record is None or len(names) != 1 or next(iter(names)) not in kinds:
        raise _Refuse('UNSUPPORTED_SOURCE', 'STEP shape definition does not reference a supported representation')
    parameters = record[next(iter(names))]
    if len(parameters) != 3 or not isinstance(parameters[1], list) or not isinstance(parameters[2], tuple) or parameters[2][0] != 'ref':
        raise _Refuse('UNSUPPORTED_SOURCE', 'STEP representation is malformed')
    return next(iter(names)), parameters[1], parameters[2][1]


def _admit(table, limits, *, export=False):
    counts = {}
    for identifier, record in table.items():
        for name, parameters in record.items():
            if name in REFUSED:
                raise _Refuse('UNSUPPORTED_SOURCE', f'STEP {REFUSED[name]} is not supported; supply one part as one solid',
                              entity=name, instance=identifier)
            if 'EXTERNAL' in name:
                raise _Refuse('UNSUPPORTED_SOURCE', 'STEP external references are not supported', entity=name, instance=identifier)
            if name not in VOCABULARY and not export:
                raise _Refuse('UNSUPPORTED_SOURCE', 'STEP entity type is outside the supported solid subset',
                              entity=name, instance=identifier)
            counts[name] = counts.get(name, 0)+1
        references = _refs(list(record.values()), [])
        for reference in references:
            if reference not in table:
                raise _Refuse('UNSUPPORTED_SOURCE', 'STEP reference is unresolved', instance=identifier, reference=reference)
        if 'EDGE_LOOP' in record and limits['loopEdges'] is not None:
            loop = record['EDGE_LOOP']
            edges = len(_refs(loop[1:], [])) if len(loop) == 2 else 0
            if edges > limits['loopEdges']:
                raise _Refuse('RESOURCE_LIMIT', 'STEP edge loop exceeds the admitted oriented-edge count',
                              instance=identifier, edges=edges, limit=limits['loopEdges'])
    definitions = [k for k, v in table.items() if 'SHAPE_DEFINITION_REPRESENTATION' in v]
    if len(definitions) != 1:
        raise _Refuse('UNSUPPORTED_SOURCE', 'STEP file must contain exactly one shape definition', found=len(definitions))
    sdr = table[definitions[0]]['SHAPE_DEFINITION_REPRESENTATION']
    if len(sdr) != 2 or not isinstance(sdr[1], tuple) or sdr[1][0] != 'ref':
        raise _Refuse('UNSUPPORTED_SOURCE', 'STEP shape definition is malformed')
    top = sdr[1][1]
    kind, items, context = _representation(table, top, {'SHAPE_REPRESENTATION', 'ADVANCED_BREP_SHAPE_REPRESENTATION'})
    roots = [definitions[0]]
    relationships = [k for k, v in table.items() if set(v) & RELATIONSHIPS]
    if kind == 'ADVANCED_BREP_SHAPE_REPRESENTATION':
        brep, brep_items, brep_context, structure = top, items, context, 'direct'
        if relationships:
            raise _Refuse('UNSUPPORTED_SOURCE', 'STEP representation relationship does not link the admitted representations')
    else:
        if len(relationships) != 1:
            raise _Refuse('UNSUPPORTED_SOURCE', 'STEP shape representation must link exactly one B-rep representation',
                          relationships=len(relationships))
        record = table[relationships[0]]
        if set(record) - RELATIONSHIPS:
            raise _Refuse('UNSUPPORTED_SOURCE', 'STEP representation relationship has unsupported partial entities')
        parameters = record.get('REPRESENTATION_RELATIONSHIP') or record.get('SHAPE_REPRESENTATION_RELATIONSHIP')
        if not parameters or len(parameters) != 4 or not all(isinstance(p, tuple) and p[0] == 'ref' for p in parameters[2:]):
            raise _Refuse('UNSUPPORTED_SOURCE', 'STEP representation relationship is malformed')
        linked = {parameters[2][1], parameters[3][1]}
        if top not in linked or len(linked) != 2:
            raise _Refuse('UNSUPPORTED_SOURCE', 'STEP representation relationship does not link the admitted representations')
        brep = (linked - {top}).pop()
        _, brep_items, brep_context = _representation(table, brep, {'ADVANCED_BREP_SHAPE_REPRESENTATION'})
        if any(table[ref[1]].keys() & SOLIDS for ref in items if isinstance(ref, tuple) and ref[0] == 'ref'):
            raise _Refuse('UNSUPPORTED_SOURCE', 'STEP outer shape representation must not carry geometry itself')
        roots.append(relationships[0])
        structure = 'relationship'
    solids = [ref[1] for ref in brep_items if isinstance(ref, tuple) and ref[0] == 'ref' and table[ref[1]].keys() & SOLIDS]
    others = [ref for ref in brep_items if not (isinstance(ref, tuple) and ref[0] == 'ref'
                                                 and table[ref[1]].keys() & (SOLIDS | {'AXIS2_PLACEMENT_3D'}))]
    if len(solids) != 1 or others:
        raise _Refuse('INVALID_GEOMETRY', 'STEP B-rep representation must hold exactly one solid (and only placements)',
                      solids=len(solids))
    unit = _context_unit(table, brep_context)
    if structure == 'relationship' and _context_unit(table, context) != unit:
        raise _Refuse('UNDECLARED_UNIT', 'Linked STEP representations assign conflicting length units')
    # Reachability closure from the admitted shape definition (and its sole relationship).
    reached, stack = set(), list(roots)
    while stack:
        identifier = stack.pop()
        if identifier in reached:
            continue
        reached.add(identifier)
        stack.extend(_refs(list(table[identifier].values()), []))
    for identifier, record in table.items():
        if identifier in reached:
            continue
        stray = set(record) & (SOLIDS | REPRESENTATIONS | {'GEOMETRIC_REPRESENTATION_CONTEXT', 'GLOBAL_UNIT_ASSIGNED_CONTEXT',
                                                            'CLOSED_SHELL', 'ADVANCED_FACE', 'SHAPE_DEFINITION_REPRESENTATION'})
        if stray:
            raise _Refuse('UNSUPPORTED_SOURCE', 'STEP file contains an unreferenced representation, unit context or B-rep',
                          instance=identifier, entity=sorted(stray)[0])
    loops = [len(_refs(v['EDGE_LOOP'][1:], [])) for v in table.values() if 'EDGE_LOOP' in v and len(v['EDGE_LOOP']) == 2]
    return {'unit': unit, 'structure': structure, 'solid': sorted(table[solids[0]].keys() & SOLIDS)[0],
            'entities': len(table), 'maxLoopEdges': max(loops, default=0)}


def scan(data, *, export=False):
    """Admission facts of STEP bytes, or a refusal as (code, message, detail)."""
    limits = EXPORT_LIMITS if export else {'bytes': MAX_BYTES, 'entities': MAX_ENTITIES, 'loopEdges': MAX_LOOP_EDGES}
    if len(data) > limits['bytes']:
        raise _Refuse('RESOURCE_LIMIT', 'STEP file exceeds the admitted size', bytes=len(data), limit=limits['bytes'])
    schema, table = _parse(data, limits)
    return {'schema': schema, **_admit(table, limits, export=export), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest()}


def admit(data, location, *, export=False):
    try:
        return scan(data, export=export)
    except _Refuse as refusal:
        fail(refusal.code, refusal.args[0], location, **refusal.detail)
    except RecursionError:
        fail('RESOURCE_LIMIT', 'STEP structure is too deeply nested', location)


def read_bounded(path, location, *, limit=MAX_BYTES, code='RESOURCE_NOT_FOUND'):
    path = Path(path)
    if path.is_symlink():
        fail('UNSUPPORTED_SOURCE', 'STEP source must be a regular file, not a symbolic link', location, path=str(path))
    if not path.is_file():
        fail(code, 'STEP source file is absent', location, path=str(path))
    with path.open('rb') as handle:
        if os.fstat(handle.fileno()).st_size > limit:
            fail('RESOURCE_LIMIT', 'STEP file exceeds the admitted size', location, limit=limit)
        data = handle.read(limit+1)
    if len(data) > limit:
        fail('RESOURCE_LIMIT', 'STEP file exceeds the admitted size', location, limit=limit)
    return data


class AuthoredSources:
    """Default provider: new planning and reuse read the authored path now."""
    replay = False

    def read(self, value, identity, location):
        path = Path(value).absolute()
        return str(path), read_bounded(path, location)


def consistent(authored, recorded):
    """A recorded absolute path is the authored path, resolved against the planning directory if relative."""
    if not isinstance(recorded, str) or not Path(recorded).is_absolute():
        return False
    authored_path = Path(authored)
    if authored_path.is_absolute():
        return str(authored_path.absolute()) == recorded
    parts = authored_path.parts
    return len(Path(recorded).parts) > len(parts) and Path(recorded).parts[-len(parts):] == parts


class CapturedSources:
    """Saved-verification provider: the retained copy, bound to its capture record.

    It never opens the original path. The record's path is provenance only and
    must agree with the authored value; the bytes must hash to the recorded digest.
    The caller still compares the replayed plan with the saved plan.
    """
    replay = True

    def __init__(self, directory, records):
        self.directory, self.records = Path(directory), records

    def record(self, identity, location):
        record = self.records.get(identity) if isinstance(self.records, dict) else None
        if not isinstance(record, dict) or not isinstance(record.get('sha256'), str) or not isinstance(record.get('retained'), str):
            fail('VERIFICATION_FAILED', 'Captured STEP source record is missing or malformed', location)
        return record

    def read(self, value, identity, location):
        from schemaxis.run_paths import owned_path
        record = self.record(identity, location)
        if not consistent(value, record.get('file')):
            fail('VERIFICATION_FAILED', 'Captured STEP source path does not match the authored file', location)
        retained = owned_path(self.directory, record['retained'])
        data = read_bounded(retained, location, code='VERIFICATION_FAILED')
        if hashlib.sha256(data).hexdigest() != record['sha256']:
            fail('VERIFICATION_FAILED', 'Retained STEP copy differs from its capture record', location)
        return record['file'], data
