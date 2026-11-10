"""Independent bounded ISO 10303-21 reader and IfcWall schedule oracle: standard library only, no native imports.

The reader tokenizes one small ASCII IFC4 file generically (every parameter form), refuses what it cannot represent
exactly, and walks only the selected closed subgraph: walls, their occurrence/type property and quantity sets and the
project units. Every other entity is counted and stays unassessed. The result is the expected schedule that the
native extraction is compared with; the native output is never used to build it.
"""
from fractions import Fraction
import re

from schemaxis.errors import fail

MAX_BYTES = 2 * 1024 * 1024
MAX_ENTITIES = 4096
MAX_STRING = 256
MAX_STRINGS = 8192
MAX_DEPTH = 8
MAX_LIST = 256
MAX_WALLS = 64
MIN_WALLS = 2
MAX_EXACT_INTEGER = 2 ** 53
MAX_NUMBER_DIGITS = 40  # mantissa digits (integer and fraction, leading zeros counted) of any numeric token, anywhere in the file
MAX_EXPONENT_DIGITS = 4
MAX_EXPONENT = 400  # decimal exponent magnitude; binary64 needs about 324, so every representable value is inside the budget
MAX_REFERENCE_DIGITS = 10  # digits of any #id, leading zeros counted
MAX_NAME_ECHO = 64  # longest keyword or type name a fault repeats in full; every IFC4 class name is shorter
NAME_PREFIX = 48
SCHEMA = 'IFC4'
GUID = re.compile(r'[0-3][0-9A-Za-z_$]{21}')
TOKEN = re.compile(r"""\s*(?:
    (?P<string>'(?:[^']|'')*')
  | (?P<ref>\#[0-9]+)
  | (?P<number>[+-]?[0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?)
  | (?P<enum>\.[A-Z][A-Z0-9_]*\.)
  | (?P<word>[A-Za-z][A-Za-z0-9_-]*)
  | (?P<punct>[(),;=$*])
  | (?P<comment>/\*)
  | (?P<backslash>\\)
)""", re.X)
PREFIX_EXPONENT = {None: 0, 'MILLI': -3, 'CENTI': -2, 'DECI': -1, 'KILO': 3}
QUANTITY = {'length': ('IFCQUANTITYLENGTH', 'LENGTHUNIT', 'METRE', 1, 'm'),
            'area': ('IFCQUANTITYAREA', 'AREAUNIT', 'SQUARE_METRE', 2, 'm2'),
            'volume': ('IFCQUANTITYVOLUME', 'VOLUMEUNIT', 'CUBIC_METRE', 3, 'm3')}
TEXT_TYPES = ('IFCLABEL', 'IFCTEXT', 'IFCIDENTIFIER')


def lexical_budget(lexeme, at, offset=None):
    """Refuse an over-budget numeric token from its text alone, before any int, Fraction or power is constructed.

    The budget is lexical, global (header, unselected and selected numbers alike) and independent of the value:
    at most MAX_NUMBER_DIGITS mantissa digits and an exponent of at most MAX_EXPONENT_DIGITS digits and magnitude MAX_EXPONENT.
    Nothing is truncated or coerced; the refusal carries bounded facts about the token, never the token itself.
    """
    mantissa, _, exponent = lexeme.lower().partition('e')
    digits = sum(1 for c in mantissa if c.isdigit())
    exponent_digits = len(exponent.lstrip('+-'))
    facts = {'lexemeCharacters': len(lexeme), 'prefix': lexeme[:16], 'mantissaDigits': digits, 'exponentDigits': exponent_digits}
    if offset is not None: facts['offset'] = offset
    if digits > MAX_NUMBER_DIGITS:
        refuse('STEP_RESOURCE_LIMIT', f'a numeric token has more than {MAX_NUMBER_DIGITS} mantissa digits', at, limit=MAX_NUMBER_DIGITS, **facts)
    if exponent_digits > MAX_EXPONENT_DIGITS or (exponent and abs(int(exponent)) > MAX_EXPONENT):
        refuse('STEP_RESOURCE_LIMIT', f'a numeric exponent is longer than {MAX_EXPONENT_DIGITS} digits or larger than {MAX_EXPONENT} in magnitude', at, limit=MAX_EXPONENT, **facts)


class Number:
    """A numeric token that keeps its exact source lexeme; the exact rational is built only when a selected value needs it."""
    def __init__(self, lexeme, at='$.source.path', offset=None):
        lexical_budget(lexeme, at, offset)
        self.lexeme = lexeme
        self.integer = '.' not in lexeme and 'e' not in lexeme.lower()
        if not self.integer and not (re.fullmatch(r'[+-]?[0-9]+\.[0-9]*(?:E[+-]?[0-9]+)?', lexeme)):
            refuse('STEP_SYNTAX', 'a number must be a Part 21 INTEGER or REAL: a REAL needs a decimal point and an upper-case E exponent', at, lexemeCharacters=len(lexeme), prefix=lexeme[:16], **({'offset': offset} if offset is not None else {}))
        self._exact = None

    @property
    def exact(self):
        if self._exact is None: self._exact = Fraction(self.lexeme)
        return self._exact

    @property
    def real(self): return not self.integer


def reference(text, at, offset=None):
    """The positive-or-zero id of one #n token, bounded before int conversion."""
    if len(text) - 1 > MAX_REFERENCE_DIGITS:
        refuse('STEP_RESOURCE_LIMIT', f'an entity reference has more than {MAX_REFERENCE_DIGITS} digits', at, limit=MAX_REFERENCE_DIGITS, referenceCharacters=len(text), prefix=text[:16], **({'offset': offset} if offset is not None else {}))
    return int(text[1:])


def refuse(code, message, location, **extra):
    fail(code, message, location, **extra)


def named(name):
    """A keyword or type name for a fault: whole when short, otherwise a prefix and its true length, never the whole token."""
    return name if len(name) <= MAX_NAME_ECHO else f'{name[:NAME_PREFIX]}... ({len(name)} characters)'


def scan(text, position, at):
    match = TOKEN.match(text, position)
    if not match:
        if text[position:].strip() == '': return None, len(text)
        refuse('STEP_SYNTAX', 'unrecognised STEP token', at, offset=position)
    kind = match.lastgroup
    if kind == 'comment': refuse('UNSUPPORTED_STEP_COMMENT', 'STEP comments are not supported; remove them', at, offset=position)
    if kind == 'backslash': refuse('UNSUPPORTED_STEP_ESCAPE', 'backslash text and Unicode escape sequences are unsupported; use plain ASCII', at, offset=position)
    return (kind, match.group(kind)), match.end()


class Reader:
    def __init__(self, text, at):
        self.text, self.position, self.at, self.strings, self.peeked, self.keyword_offset = text, 0, at, 0, None, 0

    def peek(self):
        if self.peeked is None:
            token, end = scan(self.text, self.position, self.at)
            self.peeked = (token, end)
        return self.peeked[0]

    def take(self):
        token = self.peek()
        if token is None: refuse('STEP_SYNTAX', 'unexpected end of file', self.at)
        self.position, self.peeked = self.peeked[1], None
        return token

    def expect(self, value):
        token = self.take()
        if token[1] != value: refuse('STEP_SYNTAX', f'expected {value!r}', self.at, found=token[1][:32], offset=self.position)

    def string(self, raw):
        body = raw[1:-1].replace("''", "'")
        if '\\' in body: refuse('UNSUPPORTED_STEP_ESCAPE', 'backslash text and Unicode escape sequences (\\X\\, \\X2\\, \\S\\) are unsupported; use plain ASCII', self.at, offset=self.position)
        if len(body) > MAX_STRING: refuse('STEP_RESOURCE_LIMIT', f'a string is longer than {MAX_STRING} characters', self.at, offset=self.position)
        for character in body:
            if not 32 <= ord(character) < 127: refuse('UNSUPPORTED_STEP_ESCAPE', 'only printable ASCII text is supported', self.at, offset=self.position)
        self.strings += 1
        if self.strings > MAX_STRINGS: refuse('STEP_RESOURCE_LIMIT', f'more than {MAX_STRINGS} strings', self.at)
        return body

    def value(self, depth=0):
        if depth > MAX_DEPTH: refuse('STEP_RESOURCE_LIMIT', f'parameters nest deeper than {MAX_DEPTH}', self.at, offset=self.position)
        kind, text = self.take()
        if kind == 'string': return self.string(text)
        if kind == 'ref': return ('ref', reference(text, self.at, self.position))
        if kind == 'number': return Number(text, self.at, self.position)
        if kind == 'enum': return ('enum', text[1:-1])
        if kind == 'punct' and text == '$': return None
        if kind == 'punct' and text == '*': return ('derived',)
        if kind == 'punct' and text == '(': return self.items(depth + 1)
        if kind == 'word' and self.peek() == ('punct', '('):
            self.take()
            return ('typed', text.upper(), self.items(depth + 1))
        refuse('STEP_SYNTAX', 'unexpected parameter token', self.at, found=text[:32], offset=self.position)

    def items(self, depth):
        result = []
        if self.peek() == ('punct', ')'): self.take(); return result
        while True:
            result.append(self.value(depth))
            if len(result) > MAX_LIST: refuse('STEP_RESOURCE_LIMIT', f'a list has more than {MAX_LIST} members', self.at, offset=self.position)
            token = self.take()
            if token == ('punct', ')'): return result
            if token != ('punct', ','): refuse('STEP_SYNTAX', 'expected a comma or closing parenthesis', self.at, offset=self.position)

    def keyword_instance(self):
        kind, name = self.take()
        if kind != 'word': refuse('STEP_SYNTAX', 'expected a keyword', self.at, offset=self.position)
        self.keyword_offset = self.position - len(name)
        self.expect('(')
        args = self.items(1)
        self.expect(';')
        return name.upper(), args


def parse(data):
    """Return ({'schema': ..., 'entities': {id: (NAME, args)}, 'counts': {NAME: n}}) or refuse before any native step."""
    if not isinstance(data, bytes) or not data: refuse('STEP_SYNTAX', 'the source is empty', '$.source.path')
    if len(data) > MAX_BYTES: refuse('STEP_RESOURCE_LIMIT', f'the file is larger than {MAX_BYTES} bytes', '$.source.path', bytes=len(data))
    if any(b > 126 or (b < 32 and b not in (9, 10, 13)) for b in data): refuse('UNSUPPORTED_STEP_ESCAPE', 'only ASCII STEP files are supported; encode text with plain ASCII (Unicode escapes are not supported)', '$.source.path')
    reader = Reader(data.decode('ascii'), '$.source.path')
    for word in ('ISO-10303-21',):
        if reader.take()[1].upper() != word: refuse('STEP_SYNTAX', 'missing ISO-10303-21 start', '$.source.path')
    reader.expect(';');reader.expect('HEADER');reader.expect(';')
    header = {}
    while reader.peek() != ('word', 'ENDSEC'):
        name, args = reader.keyword_instance()
        if name in header: refuse('STEP_HEADER', 'duplicate header entity ' + named(name), 'header', entity=named(name), nameCharacters=len(name), offset=reader.keyword_offset)
        header[name] = args
    reader.take();reader.expect(';')
    if list(header) != ['FILE_DESCRIPTION', 'FILE_NAME', 'FILE_SCHEMA']: refuse('STEP_HEADER', 'the header must be exactly FILE_DESCRIPTION, FILE_NAME and FILE_SCHEMA', 'header')
    schema = header['FILE_SCHEMA']
    if schema != [[SCHEMA]]: refuse('UNSUPPORTED_SCHEMA', 'only FILE_SCHEMA((\'IFC4\')) is supported; IFC2X3, IFC4X3 and multiple schemas are refused', 'header.FILE_SCHEMA', observed=str(schema)[:80])
    reader.expect('DATA');reader.expect(';')
    entities, counts = {}, {}
    while reader.peek() != ('word', 'ENDSEC'):
        kind, ref = reader.take()
        if kind != 'ref': refuse('STEP_SYNTAX', 'expected an entity instance name', 'data', offset=reader.position)
        number = reference(ref, 'data', reader.position)
        reader.expect('=')
        if reader.peek() == ('punct', '('): refuse('UNSUPPORTED_COMPLEX_ENTITY', 'complex (multiple-leaf) entity instances are unsupported', f'#{number}')
        name, args = reader.keyword_instance()
        if number in entities: refuse('DUPLICATE_ENTITY_ID', f'entity #{number} is defined more than once', f'#{number}')
        if number == 0 or len(entities) >= MAX_ENTITIES: refuse('STEP_RESOURCE_LIMIT', f'at most {MAX_ENTITIES} entities with positive ids are supported', f'#{number}')
        entities[number] = (name, args)
        counts[name] = counts.get(name, 0) + 1
    reader.take();reader.expect(';');reader.expect('END-ISO-10303-21');reader.expect(';')
    if reader.peek() is not None: refuse('STEP_SYNTAX', 'content after END-ISO-10303-21', 'data')
    return {'schema': SCHEMA, 'entities': entities, 'counts': counts}


# ---------------------------------------------------------------- selected subgraph
def entity(model, token, at, names=None):
    if not (isinstance(token, tuple) and token and token[0] == 'ref'): refuse('DANGLING_REFERENCE', 'expected an entity reference', at)
    found = model['entities'].get(token[1])
    if found is None: refuse('DANGLING_REFERENCE', f'#{token[1]} is not defined', at, reference=token[1])
    if names and found[0] not in names: refuse('UNSUPPORTED_ENTITY_CLASS', f'#{token[1]} is {named(found[0])}, expected one of {sorted(names)}', at, reference=token[1], entity=named(found[0]), nameCharacters=len(found[0]))
    return token[1], found


def arguments(found, count, at):
    if not isinstance(found[1], list) or len(found[1]) != count: refuse('UNSUPPORTED_ENTITY_SHAPE', f'{named(found[0])} must have {count} arguments in IFC4', at)
    return found[1]


def text_of(value, at, optional=False):
    if value is None and optional: return None
    if not isinstance(value, str): refuse('UNSUPPORTED_ENTITY_SHAPE', 'expected a string', at)
    return value


def guid_of(value, at):
    if not isinstance(value, str) or not GUID.fullmatch(value): refuse('INVALID_GLOBAL_ID', 'GlobalId must be a 22-character compressed IFC GUID', at, observed=str(value)[:32])
    return value


def refs_of(value, at):
    if not isinstance(value, list): refuse('UNSUPPORTED_ENTITY_SHAPE', 'expected a list of references', at)
    return value


def units(model, project_id, needed):
    """Exact SI scale exponent for each needed unit type; every context-dependent or ambiguous unit is refused."""
    _, project = entity(model, ('ref', project_id), '$.source.path', {'IFCPROJECT'})
    args = arguments(project, 9, f'#{project_id}')
    if args[8] is None: return {}, 0  # IFC4 allows no project units; a selected quantity then refuses as UNIT_MISSING, a property-only schedule never needs them
    assignment_id, assignment = entity(model, args[8], f'#{project_id}.UnitsInContext', {'IFCUNITASSIGNMENT'})
    members = refs_of(arguments(assignment, 1, f'#{assignment_id}')[0], f'#{assignment_id}.Units')
    found, others = {}, 0
    for index, ref in enumerate(members):
        at = f'#{assignment_id}.Units[{index}]'
        number, unit = entity(model, ref, at)
        name = unit[0]
        if name == 'IFCSIUNIT':
            a = arguments(unit, 4, at)
            kind = a[1][1] if isinstance(a[1], tuple) and a[1][0] == 'enum' else None
            prefix = a[2][1] if isinstance(a[2], tuple) and a[2][0] == 'enum' else None
            unit_name = a[3][1] if isinstance(a[3], tuple) and a[3][0] == 'enum' else None
            if kind in needed:
                if kind in found: refuse('UNIT_AMBIGUOUS', f'the project declares more than one {kind}', at, unit=kind)
                found[kind] = (number, prefix, unit_name)
        elif name in ('IFCCONVERSIONBASEDUNIT', 'IFCCONTEXTDEPENDENTUNIT', 'IFCDERIVEDUNIT', 'IFCCONVERSIONBASEDUNITWITHOFFSET'):
            kind = None
            for item in unit[1]:
                if isinstance(item, tuple) and item[0] == 'enum' and item[1].endswith('UNIT'): kind = item[1]
            if kind in needed: refuse('UNSUPPORTED_UNIT', f'{kind} is declared by {name}; only plain SI units are supported', at, unit=kind)
            others += 1
        else: others += 1
    return found, others


def quantity_scale(unit_types, kind, found, location):
    entity_name, unit_type, unit_name, power, canonical = QUANTITY[kind]
    if unit_type not in found: refuse('UNIT_MISSING', f'the project declares no {unit_type}; the {kind} quantity cannot be converted', location, unit=unit_type)
    _, prefix, name = found[unit_type]
    if name != unit_name or prefix not in PREFIX_EXPONENT: refuse('UNSUPPORTED_UNIT', f'{unit_type} must be {unit_name} with no prefix or MILLI, CENTI, DECI or KILO', location, unit=unit_type, prefix=None if prefix is None else named(prefix), name=None if name is None else named(name), prefixCharacters=None if prefix is None else len(prefix), nameCharacters=None if name is None else len(name))
    return PREFIX_EXPONENT[prefix] * power


def objects_sets(model, owner, wanted_class):
    """Property definitions attached to one occurrence by IfcRelDefinesByProperties."""
    result = []
    for number, (name, args) in model['entities'].items():
        if name != 'IFCRELDEFINESBYPROPERTIES': continue
        a = arguments((name, args), 6, f'#{number}')
        related = refs_of(a[4], f'#{number}.RelatedObjects')
        if any(isinstance(r, tuple) and r == ('ref', owner) for r in related): result.append((number, a[5]))
    return result


def set_members(model, number, found):
    """name -> (set entity, class) with duplicate property and set names refused."""
    name = found[0]
    if name == 'IFCPROPERTYSET':
        a = arguments(found, 5, f'#{number}');members = refs_of(a[4], f'#{number}.HasProperties')
    else:
        a = arguments(found, 6, f'#{number}');members = refs_of(a[5], f'#{number}.Quantities')
    return text_of(a[2], f'#{number}.Name'), members


def collect(model, owner, location, sets, set_class):
    """All sets on one object, keyed by name; duplicate set names (even across set classes) are ambiguous."""
    keyed = {}
    for number, found in sets:
        set_name, members = set_members(model, number, found)
        if set_name in keyed: refuse('DUPLICATE_SET_NAME', f'{location} has more than one property or quantity set named {set_name!r}', f'#{number}.Name', owner=owner, set=set_name)
        keyed[set_name] = (number, found[0], members)
    return keyed


def member_index(model, number, members, property_class, at):
    index = {}
    for position, ref in enumerate(members):
        item_id, item = entity(model, ref, f'#{number}.members[{position}]')
        if not item[1] or not isinstance(item[1][0], str): continue
        item_name = item[1][0]
        if item_name in index: refuse('DUPLICATE_PROPERTY_NAME', f'{at} lists {item_name!r} more than once', f'#{item_id}', set=at, name=item_name)
        index[item_name] = (item_id, item)
    return index


def attached_sets(model, owner, owner_label, relation_sets):
    sets = []
    for rel, ref in relation_sets:
        number, found = entity(model, ref, f'#{rel}.RelatingPropertyDefinition', {'IFCPROPERTYSET', 'IFCELEMENTQUANTITY'})
        sets.append((number, found))
    return collect(model, owner, owner_label, sets, None)


def wall_type_of(model, wall_id):
    found = []
    for number, (name, args) in model['entities'].items():
        if name != 'IFCRELDEFINESBYTYPE': continue
        a = arguments((name, args), 6, f'#{number}')
        if any(r == ('ref', wall_id) for r in refs_of(a[4], f'#{number}.RelatedObjects')): found.append((number, a[5]))
    if len(found) > 1: refuse('AMBIGUOUS_TYPE', 'a wall has more than one IfcRelDefinesByType', f'#{wall_id}', relations=[n for n, _ in found])
    if not found: return None
    type_id, type_entity = entity(model, found[0][1], f'#{found[0][0]}.RelatingType', {'IFCWALLTYPE'})
    return type_id, type_entity


def type_sets(model, type_id, type_entity):
    a = arguments(type_entity, 10, f'#{type_id}')
    sets = []
    for position, ref in enumerate(refs_of(a[5], f'#{type_id}.HasPropertySets') if a[5] is not None else []):
        number, found = entity(model, ref, f'#{type_id}.HasPropertySets[{position}]', {'IFCPROPERTYSET'})
        sets.append((number, found))
    return collect(model, type_id, f'wall type #{type_id}', sets, None)


def property_value(model, member, column, at):
    """The exact typed value of one IfcPropertySingleValue under the declared column type."""
    item_id, item = member
    if item[0] != 'IFCPROPERTYSINGLEVALUE': refuse('UNSUPPORTED_PROPERTY', f'{named(item[0])} is unsupported; only IfcPropertySingleValue is read', at, property=column['property'], entity=named(item[0]), nameCharacters=len(item[0]))
    a = arguments(item, 4, at)
    if a[3] is not None: refuse('UNSUPPORTED_PROPERTY_UNIT', 'a property with an explicit Unit is unsupported', at, property=column['property'])
    nominal = a[2]
    if nominal is None: refuse('UNSUPPORTED_NULL_VALUE', 'a property with no NominalValue is unsupported', at, property=column['property'])
    if not (isinstance(nominal, tuple) and nominal[0] == 'typed' and len(nominal[2]) == 1): refuse('UNSUPPORTED_PROPERTY', 'NominalValue must be one typed IFC value', at, property=column['property'])
    kind, wrapped = nominal[1], nominal[2][0]
    wanted = column['valueType']
    if wanted == 'text':
        if kind not in TEXT_TYPES or not isinstance(wrapped, str): refuse('TYPE_MISMATCH', f'{named(kind)} is not text (IfcLabel, IfcText or IfcIdentifier)', at, property=column['property'], observed=named(kind), nameCharacters=len(kind))
        if wrapped == '': refuse('UNREPRESENTABLE_EMPTY_TEXT', 'empty text cannot be told from a missing cell in the workbook', at, property=column['property'])
        if len(wrapped) > 256: refuse('STEP_RESOURCE_LIMIT', 'text longer than 256 characters', at)
        return wrapped
    if wanted == 'boolean':
        if kind != 'IFCBOOLEAN' or not (isinstance(wrapped, tuple) and wrapped[0] == 'enum' and wrapped[1] in ('T', 'F')): refuse('TYPE_MISMATCH', f'{named(kind)} is not IfcBoolean with .T. or .F.', at, property=column['property'], observed=named(kind), nameCharacters=len(kind))
        return 'true' if wrapped[1] == 'T' else 'false'
    if kind not in ('IFCREAL', 'IFCINTEGER') or not isinstance(wrapped, Number) or wrapped.integer != (kind == 'IFCINTEGER'): refuse('TYPE_MISMATCH', f'{named(kind)} is not an IfcReal or IfcInteger number', at, property=column['property'], observed=named(kind), nameCharacters=len(kind))
    if abs(wrapped.exact) > MAX_EXACT_INTEGER and wrapped.integer: refuse('NUMBER_RANGE', 'integer exceeds 2^53', at, property=column['property'])
    return exact_float(wrapped.exact, at), wrapped.lexeme


def exact_float(value, at):
    """Correctly rounded binary64 of an exact rational; refuses overflow, and a nonzero value that underflows to zero."""
    try: result = float(value)
    except OverflowError: refuse('NUMBER_RANGE', 'value overflows binary64', at)
    if result != result or result in (float('inf'), float('-inf')) or (result == 0.0 and value != 0): refuse('NUMBER_RANGE', 'value is not finite and nonzero-preserving in binary64', at)
    return result + 0.0


def quantity_value(member, column, exponent, zero, at):
    item_id, item = member
    entity_name = QUANTITY[column['quantity']][0]
    if item[0] != entity_name: refuse('TYPE_MISMATCH', f'{named(item[0])} is not {entity_name}', at, quantity=column['name'], entity=named(item[0]), nameCharacters=len(item[0]))
    a = arguments(item, 5, at)
    if a[2] is not None: refuse('UNSUPPORTED_QUANTITY_UNIT', 'an explicit quantity Unit override is unsupported', at, quantity=column['quantity'])
    if not isinstance(a[3], Number): refuse('UNSUPPORTED_ENTITY_SHAPE', 'the quantity value must be a number', at)
    if not a[3].real: refuse('TYPE_MISMATCH', 'a quantity value must be a STEP REAL with a decimal point (2500. rather than 2500)', at, quantity=column['name'])
    exact = a[3].exact
    if exact < 0: refuse('QUANTITY_NEGATIVE', 'a physical quantity cannot be negative', at, lexeme=a[3].lexeme)
    if exact == 0 and zero == 'refuse': refuse('QUANTITY_ZERO', 'zero quantities are refused by the zeroQuantity policy', at)
    return exact_float(exact * Fraction(10) ** exponent, at), a[3].lexeme


def resolve(model, intent):
    """The independent expected schedule: one row per wall, explicit origin per column."""
    for name in model['counts']:
        if name.startswith('IFCWALL') and name not in ('IFCWALL', 'IFCWALLTYPE'):
            first = min(n for n, (found, _) in model['entities'].items() if found == name)
            refuse('UNSUPPORTED_ENTITY_CLASS', f'{named(name)} is a wall subtype or variant that the IfcWall schedule does not select; remove it or use a plain IfcWall', 'data', entity=named(name), nameCharacters=len(name), reference=first)
    if model['counts'].get('IFCPROJECT') != 1: refuse('PROJECT_AMBIGUOUS', 'the file needs exactly one IfcProject', 'data', projects=model['counts'].get('IFCPROJECT', 0))
    project_id = next(n for n, (name, _) in model['entities'].items() if name == 'IFCPROJECT')
    wall_ids = sorted(n for n, (name, _) in model['entities'].items() if name == 'IFCWALL')
    if not MIN_WALLS <= len(wall_ids) <= MAX_WALLS: refuse('WALL_COUNT', f'the file needs {MIN_WALLS} to {MAX_WALLS} IfcWall entities', 'data', walls=len(wall_ids))
    needed = {QUANTITY[c['quantity']][1] for c in intent['columns'] if c['source'] == 'quantity'}
    found, others = units(model, project_id, needed)
    exponents = {c['name']: quantity_scale(needed, c['quantity'], found, f'$.columns[{i}]') for i, c in enumerate(intent['columns']) if c['source'] == 'quantity'}
    guids, rows = {}, []
    for wall_id in wall_ids:
        wall = model['entities'][wall_id]
        a = arguments(wall, 9, f'#{wall_id}')
        guid = guid_of(a[0], f'#{wall_id}.GlobalId')
        if guid in guids: refuse('DUPLICATE_GLOBAL_ID', 'two walls share one GlobalId', f'#{wall_id}.GlobalId', guid=guid, entities=[guids[guid], wall_id])
        guids[guid] = wall_id
        label = text_of(a[2], f'#{wall_id}.Name', optional=True)
        if label == '': refuse('UNREPRESENTABLE_EMPTY_TEXT', 'an empty wall Name is unsupported; use $ for a missing name', f'#{wall_id}.Name')
        occurrence = attached_sets(model, wall_id, f'wall #{wall_id}', objects_sets(model, wall_id, None))
        related_type = wall_type_of(model, wall_id)
        typed = type_sets(model, *related_type) if related_type else {}
        cells = []
        for index, column in enumerate(intent['columns']):
            at = f'#{wall_id}.columns[{index}]'
            found_value, origin = None, 'missing'
            for scope, sets in (('occurrence', occurrence), ('type', typed)):
                if scope == 'type' and (column['source'] != 'property' or intent['inheritance'] != 'occurrence-overrides-type'): continue
                entry = sets.get(column['set'])
                if entry is None: continue
                number, set_class, members = entry
                wanted_class = 'IFCPROPERTYSET' if column['source'] == 'property' else 'IFCELEMENTQUANTITY'
                if set_class != wanted_class: refuse('TYPE_MISMATCH', f'set {column["set"]!r} is {set_class}, expected {wanted_class}', f'#{number}', set=column['set'])
                index_members = member_index(model, number, members, None, column['set'])
                if column['source'] == 'property' and 'id' in index_members: refuse('UNSUPPORTED_PROPERTY', 'a property named id collides with the native identifier key', f'#{number}')
                member = index_members.get(column['property'] if column['source'] == 'property' else column['quantityName'])
                if member is None: continue
                if column['source'] == 'property': found_value = property_value(model, member, column, f'#{member[0]}')
                else: found_value = quantity_value(member, column, exponents[column['name']], intent['zeroQuantity'], f'#{member[0]}')
                origin = scope
                break
            if found_value is None and intent['missing'] == 'refuse':
                refuse('MISSING_VALUE', 'the wall has no value for the column under the declared inheritance policy', at, guid=guid, column=column['name'])
            cells.append({'column': column['name'], 'origin': origin, 'value': found_value[0] if isinstance(found_value, tuple) else found_value,
                          **({'sourceLexeme': found_value[1]} if isinstance(found_value, tuple) else {})})
        type_guid = guid_of(arguments(related_type[1], 10, f'#{related_type[0]}')[0], f'#{related_type[0]}.GlobalId') if related_type else None
        rows.append({'guid': guid, 'name': label, 'entity': wall_id, 'type': related_type[0] if related_type else None, 'typeGuid': type_guid, 'cells': cells})
    rows.sort(key=lambda r: r['guid'])
    return {'schema': model['schema'], 'units': {k: {'prefix': v[1], 'name': v[2]} for k, v in sorted(found.items())}, 'unitsUnassessed': others,
            'scaleExponents': {QUANTITY[c['quantity']][1]: exponents[c['name']] for c in intent['columns'] if c['source'] == 'quantity'},
            'rows': rows, 'counts': {'entities': len(model['entities']), 'walls': len(rows), 'byClass': dict(sorted(model['counts'].items()))}}
