"""Bounded IFC4 wall schedule: IfcOpenShell extracts natively, an independent host STEP walk decides the meaning.

One local ASCII IFC4 file with 2 to 64 plain IfcWall occurrences yields a GUID-linked schedule of explicit property and
quantity columns, each cell carrying its origin (occurrence, type or missing). The native library runs in its own process
twice (extract and a fresh reopen); both raw tables must be identical and must agree with a standard-library STEP reader
that tokenizes the file and walks only the selected closed subgraph. Published files are rebuilt from the host-checked
values; native output, hashes and summaries never certify meaning. Geometry is never computed or validated.
"""
import hashlib
import json
import math
import os
from fractions import Fraction
from pathlib import Path
import re
import stat
import sys
import time

from schemaxis.adaptors.ifcopenshell import step
from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.ifcopenshell/1'
OPERATION = 'scheduleWalls'
RUNTIME = 'ifcopenshell 0.9.0.post1'
RUNTIME_VERSION = '0.9.0.post1'
# The pure-Python modules that implement the lookups and unit scales the worker calls; identical in every 0.9.0.post1 wheel of the qualified release.
NATIVE_MODULES = {'util/element.py': '7a561df026e8cf4e4deace4e7e7936675995401c30fce61118368f4f1f3eba95',
                  'util/unit.py': '35675f166b333ad3f5288bc2e285a9eed681b4c4894862d04eefdb93a77582ba'}
SOURCE_LIMIT = step.MAX_BYTES
JSON_LIMIT = 8 * 1024 * 1024
LOG_LIMIT = 4 * 1024 * 1024
RUNTIME_FILE_LIMIT = 1024 ** 3
HEX = re.compile(r'[0-9a-f]{64}')
SOURCE_FILE = 'source.ifc'
INTENT_FILE = 'intent.json'
WORKER_FILE = 'worker.py'
WORKER_SOURCE = Path(__file__).with_name('worker.py')
STAGES = ('version', 'extract', 'reopen')
NULL_TOKEN = '\\N'
CSV_FORMAT = 'schemaxis.calc.typed-csv/1'
FIXED = ('GUID', 'Name')
PATH = {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}
NAME = {'type': 'string', 'minLength': 1, 'maxLength': 128}
COLUMN = {'type': 'object', 'properties': {
    'name': {**NAME, 'required': True},
    'source': {'type': 'enum', 'values': ['property', 'quantity'], 'required': True},
    'set': {**NAME, 'required': True},
    'property': NAME, 'valueType': {'type': 'enum', 'values': ['text', 'number', 'boolean']},
    'quantityName': NAME, 'quantity': {'type': 'enum', 'values': ['length', 'area', 'volume']}}}
OPTIONS = {
    'source': {'type': 'object', 'required': True, 'properties': {'path': PATH, 'sha256': {'type': 'string', 'minLength': 64, 'maxLength': 64}}},
    'class': {'type': 'enum', 'values': ['IfcWall'], 'default': 'IfcWall'},
    'columns': {'type': 'array', 'items': COLUMN, 'minItems': 2, 'maxItems': 6, 'required': True},
    'missing': {'type': 'enum', 'values': ['refuse', 'null'], 'default': 'refuse'},
    'inheritance': {'type': 'enum', 'values': ['occurrence-only', 'occurrence-overrides-type'], 'default': 'occurrence-only'},
    'zeroQuantity': {'type': 'enum', 'values': ['accept', 'refuse'], 'default': 'accept'}}
DECLARATIONS = {OPERATION: {
    'native': 'python -I worker.py source.ifc intent.json native.json (ifcopenshell.open, by_type, util.element.get_pset(should_inherit=False), get_type, util.unit.calculate_unit_scale)',
    'kinds': ['table', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
REVIEW = ('Property and quantity values are read as stored in the file: a person must decide whether the declared quantities are the intended ones. '
          'This schedule does not compute or validate geometry, does not check the model against the building, regulations, cost or safety, and does not '
          'validate the whole IFC file. Agreement between IfcOpenShell and the independent STEP reader proves only that both read the same stated values.')
LOSSES = [
    'One local ASCII STEP IFC4 file, at most 2MiB, 4096 entities, 256 characters per string and 64 walls; FILE_SCHEMA must be exactly IFC4. IFC2X3, IFC4X3, IFC4 ADD2 variants declared as other schemas, Unicode or backslash escapes, comments and complex entities are refused before any native process runs. Every numeric token anywhere in the file, header and unselected entities included, is held to a lexical budget checked before any conversion: at most 40 mantissa digits, an exponent of at most 4 digits and magnitude 400, and #ids of at most 10 digits (STEP_RESOURCE_LIMIT, never truncated or coerced). A number must be a Part 21 INTEGER or a REAL with a decimal point and an upper-case E exponent (STEP_SYNTAX otherwise); quantities and IfcReal need the REAL form.',
    'Selected class is plain IfcWall. IfcWallStandardCase and IfcWallElementedCase are refused rather than silently included; every other entity is counted and left unassessed, as are geometry, representations, placement, materials, layers, classifications, relationships to spaces and all properties and quantities not selected.',
    'Properties are IfcPropertySingleValue with a typed NominalValue: IfcLabel, IfcText or IfcIdentifier as text, IfcReal or IfcInteger as unitless numbers (published as binary64 shortest decimals: IfcInteger 7 appears as 7.0, exact up to 2^53, and 1e16 as 1e+16; values beyond +/-1e100 are valid here but refused by Calc readTypedCSV, so a consumer must check them before the Calc step), IfcBoolean as the text true or false. Lists, enumerations, bounded, table and complex properties and properties with an explicit Unit are refused when selected.',
    'Quantities come from the occurrence IfcElementQuantity only and are IfcQuantityLength, IfcQuantityArea or IfcQuantityVolume with the project SI unit (metre, square metre, cubic metre with no prefix or MILLI, CENTI, DECI or KILO). Conversion-based, context-dependent and derived units, a missing unit and a per-quantity Unit override are refused; a property-only schedule does not need project units, and a selected quantity without them is refused as UNIT_MISSING. Values are converted to m, m2 and m3 from the exact source text and rounded once to the nearest binary64.',
    'Type inheritance is explicit: occurrence-only never reads the type; occurrence-overrides-type reads the wall type property set only when the occurrence has no such property. Each cell records its origin. The type must be one IfcWallType; more than one type relation is ambiguous and refused. Quantities are never inherited.',
    'Missing values are null with origin missing under missing=null and refused under missing=refuse; they are never zero. Zero quantities are accepted or refused by zeroQuantity; negative quantities and empty text are refused.',
    'Rows are sorted by GlobalId. The wall Name is nullable literal text and never an identity. Nothing here measures accuracy, certifies the model or substitutes for review; the first-slice schedule is a hypothesis for BIM coordination, not demonstrated customer demand.']


# ---------------------------------------------------------------- planning
def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION', 'expected ' + VERSION, '$.version')
    if document.get('operation') != OPERATION: fail('UNKNOWN_OPERATION', 'select ' + OPERATION, '$.operation')
    p = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS})
    path = p['source']['path']
    if '\0' in path or not path.startswith('/') or '..' in Path(path).parts or Path(path).suffix.lower() != '.ifc':
        fail('INVALID_SOURCE', 'select an absolute local .ifc path without parent references', '$.source.path')
    if 'sha256' in p['source'] and not HEX.fullmatch(p['source']['sha256']): fail('INVALID_SHA256', 'use 64 lowercase hexadecimal digits', '$.source.sha256')
    names, seen = set(FIXED), set()
    for i, c in enumerate(p['columns']):
        at = f'$.columns[{i}]'
        if c['name'] in names or c['name'] == NULL_TOKEN: fail('INVALID_COLUMN', 'column names must be distinct and differ from GUID, Name and the null token', at + '.name', column=c['name'])
        if any(ord(ch) < 32 or ord(ch) > 126 for ch in c['name']): fail('INVALID_COLUMN', 'use printable ASCII column names', at + '.name')
        names.add(c['name'])
        if c['source'] == 'property':
            if 'property' not in c or 'valueType' not in c: fail('INVALID_COLUMN', 'a property column needs property and valueType', at)
            for extra in ('quantity', 'quantityName'):
                if extra in c: fail('INVALID_COLUMN', extra + ' belongs to quantity columns', at + '.' + extra)
            if c['property'] == 'id': fail('INVALID_COLUMN', 'a property named id collides with the native identifier key', at + '.property')
            key = ('property', c['set'], c['property'])
        else:
            if 'quantity' not in c or 'quantityName' not in c: fail('INVALID_COLUMN', 'a quantity column needs quantity and quantityName', at)
            for extra in ('property', 'valueType'):
                if extra in c: fail('INVALID_COLUMN', extra + ' belongs to property columns', at + '.' + extra)
            key = ('quantity', c['set'], c['quantityName'])
        if key in seen: fail('INVALID_COLUMN', 'two columns select the same property or quantity', at)
        seen.add(key)
    if p['inheritance'] == 'occurrence-overrides-type' and all(c['source'] == 'quantity' for c in p['columns']):
        fail('INVALID_COLUMN', 'type inheritance applies to properties; every selected column is a quantity', '$.inheritance')
    return {'version': 'schemaxis.ifcopenshell.plan/1', 'operation': OPERATION, **p,
            'budget': {'maxSourceBytes': SOURCE_LIMIT, 'maxEntities': step.MAX_ENTITIES, 'maxStringCharacters': step.MAX_STRING, 'maxWalls': step.MAX_WALLS, 'minWalls': step.MIN_WALLS},
            'losses': LOSSES}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION}, 'operation': {'const': OPERATION},
        **{k: argument_schema(v) for k, v in OPTIONS.items()}}, ['version', 'operation', 'source', 'columns'])}


def query(document): plan(document);return [OPERATION], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1: fail('INVALID_EXECUTION', 'extraction runs one serial native thread', identity)
    return {'threads': 1}


def sha(data): return hashlib.sha256(data).hexdigest()
def plan_hash(p): return sha(json.dumps(p, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
def whole(value): return type(value) is int


def reusableInputs(document):
    p = plan(document)
    return {'source': sha(source_bytes(p['source']['path']))}


def intent_of(p):
    """The only authored content the native worker receives: no expected values."""
    return {'class': p['class'], 'columns': p['columns'], 'inheritance': p['inheritance']}


# ---------------------------------------------------------------- bounded host inputs
def bounded(path, code='VERIFICATION_FAILED', limit=JSON_LIMIT, location=None):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit: raise ValueError('not a bounded regular file')
            data = stream.read(limit + 1)
        if len(data) > limit: raise ValueError('file byte budget exceeded')
        return data
    except (OSError, ValueError) as error: fail(code, 'select an intact regular file within the byte budget: ' + str(error), location or str(path))


def source_bytes(path, location='$.source.path'):
    """Follow a symlinked source once, through one descriptor, and require a stable regular file."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > SOURCE_LIMIT: raise ValueError('not a bounded regular file')
            data = stream.read(SOURCE_LIMIT + 1)
            after = os.fstat(stream.fileno())
        if len(data) != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino): raise ValueError('file changed while it was read')
        return data
    except (OSError, ValueError) as error: fail('INVALID_SOURCE', 'select an intact regular IFC file within 2MiB: ' + str(error), location)


def strict_json(data, at, code='VERIFICATION_FAILED'):
    def pairs(items):
        if len({k for k, _ in items}) != len(items): raise ValueError('duplicate JSON key')
        return dict(items)
    def constant(name): raise ValueError('non-finite JSON number ' + name)
    try:
        text = data.decode('utf-8')
        if text.startswith('﻿'): raise ValueError('byte-order mark')
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as error: fail(code, 'evidence is not strict UTF-8 JSON: ' + str(error), at)


def same_json(actual, expected):
    try: return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError): return False


def encode_json(value): return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
def read(directory, name): return strict_json(bounded(directory / name), name)
def digest(directory, name, limit=JSON_LIMIT): return sha(bounded(directory / name, limit=limit))


# ---------------------------------------------------------------- native command and launcher
def commands(executable, p):
    extract = lambda name: [executable, '-I', WORKER_FILE, SOURCE_FILE, INTENT_FILE, name]
    return {'version': [executable, '-I', WORKER_FILE, '--identity'], 'extract': extract('native-extract.json'), 'reopen': extract('native-reopen.json')}


def stage_inputs(stage): return [WORKER_FILE] if stage == 'version' else [SOURCE_FILE, INTENT_FILE, WORKER_FILE]


def launcher(directory, stage, command, p):
    """Trusted launcher: binds inputs by hash, fixes the environment and resource caps, never trusts ambient configuration."""
    environment = {'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'}
    return ('import hashlib,json,os,resource,stat\nfrom pathlib import Path\n'
        + f'command={command!r}\nnames={stage_inputs(stage)!r}\nenvironment={environment!r}\nbindings={{"files":{{}}}}\n'
        + 'resource.setrlimit(resource.RLIMIT_CPU,(600,600))\nresource.setrlimit(resource.RLIMIT_FSIZE,(16777216,16777216))\nresource.setrlimit(resource.RLIMIT_AS,(8589934592,8589934592))\nresource.setrlimit(resource.RLIMIT_CORE,(0,0))\n'
        + 'for name in names:\n    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|getattr(os,"O_NONBLOCK",0))\n'
        + '    with os.fdopen(fd,"rb") as stream:\n        info=os.fstat(stream.fileno())\n'
        + f'        if not stat.S_ISREG(info.st_mode) or info.st_size>{SOURCE_LIMIT}: raise ValueError("invalid native input")\n'
        + '        h=hashlib.sha256();count=0\n        for block in iter(lambda:stream.read(1<<20),b""):\n            count+=len(block);h.update(block)\n'
        + '        if count!=info.st_size: raise ValueError("native input changed while read")\n    bindings["files"][name]=h.hexdigest()\n'
        + f'Path({stage + "-inputs.json"!r}).write_text(json.dumps(bindings,sort_keys=True))\n'
        + 'os.execve(command[0],command,dict(environment))\n')


def identity_of(directory, code='UNSUPPORTED_NATIVE_VERSION'):
    found = strict_json(bounded(directory / 'version.stdout', code, 4096), 'version', code)
    if not isinstance(found, dict) or set(found) != {'ifcopenshell', 'python', 'wrapper', 'wrapperBytes', 'wrapperSha256', 'modules'}: fail(code, 'native identity is malformed', 'version')
    if found['ifcopenshell'] != RUNTIME_VERSION: fail(code, 'configure the qualified IfcOpenShell 0.9.0.post1 interpreter', 'version', observed=str(found['ifcopenshell'])[:64])
    if not isinstance(found['wrapperSha256'], str) or not HEX.fullmatch(found['wrapperSha256']) or not whole(found['wrapperBytes']) or found['wrapperBytes'] <= 0: fail(code, 'native library identity is malformed', 'version')
    if found['modules'] != NATIVE_MODULES: fail(code, 'the native util.element or util.unit module differs from the qualified release', 'version.modules', observed=str(found['modules'])[:200])
    return found


# ---------------------------------------------------------------- comparison and publications
def ulps(a, b): return abs(a - b) <= 2 * math.ulp(max(abs(a), abs(b)))


def exact_scale(exponent): return float(Fraction(10) ** exponent)


def check_native(native, expected, p, name):
    """Compare the raw native table with the independent host oracle; raise the exact semantic fault.

    Every field the worker returns is bound: GUIDs, names, type GUIDs, the unit scales (membership and the SI prefix power,
    within the declared two-ulp binary64 bound), each cell origin, raw source value (with its strict type) and converted value.
    """
    if not isinstance(native, dict) or set(native) != {'version', 'identity', 'schema', 'scales', 'rows'} or native['version'] != 'schemaxis.ifcopenshell.native/1':
        fail('NATIVE_DISAGREES', 'native output has a different member set', name)
    if native['schema'] != expected['schema']: fail('NATIVE_DISAGREES', 'native schema differs from the independent header', name + '.schema', native=native['schema'], host=expected['schema'])
    scales = native['scales']
    if not isinstance(scales, dict) or set(scales) != set(expected['scaleExponents']): fail('NATIVE_DISAGREES', 'native unit scales cover different unit types than the independent walk', name + '.scales', native=sorted(scales) if isinstance(scales, dict) else None, host=sorted(expected['scaleExponents']))
    for unit_type, exponent in sorted(expected['scaleExponents'].items()):
        scale = scales[unit_type]
        if type(scale) not in (int, float) or not math.isfinite(scale) or not ulps(float(scale), exact_scale(exponent)): fail('NATIVE_DISAGREES', 'native unit scale differs from the SI prefix power of the independent walk', f'{name}.scales.{unit_type}', native=scale, host=exact_scale(exponent))
    rows = native['rows']
    if not isinstance(rows, list) or len(rows) != len(expected['rows']): fail('NATIVE_DISAGREES', 'native wall count differs from the independent walk', name + '.rows', native=len(rows) if isinstance(rows, list) else None, host=len(expected['rows']))
    for index, (n, e) in enumerate(zip(rows, expected['rows'])):
        at = f'{name}.rows[{index}]'
        if not isinstance(n, dict) or set(n) != {'guid', 'name', 'typeGuid', 'cells'}: fail('NATIVE_DISAGREES', 'native row has a different member set', at)
        if n['guid'] != e['guid']: fail('NATIVE_DISAGREES', 'native GlobalId differs from the independent walk', at + '.guid', native=n['guid'], host=e['guid'])
        if n['name'] != e['name']: fail('NATIVE_DISAGREES', 'native wall Name differs', at + '.name', guid=e['guid'], native=n['name'], host=e['name'])
        if n['typeGuid'] != e['typeGuid']: fail('NATIVE_DISAGREES', 'native wall type GlobalId differs from the independent walk', at + '.typeGuid', guid=e['guid'], native=n['typeGuid'], host=e['typeGuid'])
        if not isinstance(n['cells'], list) or len(n['cells']) != len(p['columns']): fail('NATIVE_DISAGREES', 'native cell count differs', at + '.cells', guid=e['guid'])
        for position, (cn, ce, column) in enumerate(zip(n['cells'], e['cells'], p['columns'])):
            cell = f'{at}.cells[{position}]'
            context = {'guid': e['guid'], 'column': column['name']}
            if not isinstance(cn, dict) or set(cn) != {'origin', 'raw', 'value'}: fail('NATIVE_DISAGREES', 'native cell has a different member set', cell, **context)
            if cn['origin'] != ce['origin']: fail('NATIVE_DISAGREES', 'native value origin differs from the independent walk', cell + '.origin', native=cn['origin'], host=ce['origin'], **context)
            if ce['origin'] == 'missing':
                if cn['raw'] is not None or cn['value'] is not None: fail('NATIVE_DISAGREES', 'native reports a value where the independent walk found none', cell, **context)
                continue
            if column['source'] == 'quantity':
                lexeme = float(ce['sourceLexeme'])
                if type(cn['raw']) is not float or cn['raw'] != lexeme or type(cn['value']) is not float or not ulps(cn['value'], ce['value']): fail('NATIVE_DISAGREES', 'native quantity or unit conversion differs from the exact independent conversion', cell + '.value', native=cn['value'], host=ce['value'], **context)
            elif column['valueType'] == 'boolean':
                if type(cn['value']) is not bool or ('true' if cn['value'] else 'false') != ce['value']: fail('NATIVE_DISAGREES', 'native boolean differs', cell + '.value', native=cn['value'], host=ce['value'], **context)
                if type(cn['raw']) is not bool or cn['raw'] is not cn['value']: fail('NATIVE_DISAGREES', 'native raw boolean differs from the declared value', cell + '.raw', native=cn['raw'], host=ce['value'], **context)
            elif column['valueType'] == 'number':
                whole_number = '.' not in ce['sourceLexeme']
                wanted = int(ce['sourceLexeme']) if whole_number else ce['value']
                if type(cn['value']) is not type(wanted) or cn['value'] != wanted: fail('NATIVE_DISAGREES', 'native number differs', cell + '.value', native=cn['value'], host=ce['value'], **context)
                if type(cn['raw']) is not type(wanted) or cn['raw'] != wanted: fail('NATIVE_DISAGREES', 'native raw number differs from the declared value or its integer/real type', cell + '.raw', native=cn['raw'], host=ce['value'], **context)
            else:
                if type(cn['value']) is not str or cn['value'] != ce['value']: fail('NATIVE_DISAGREES', 'native text differs', cell + '.value', native=cn['value'], host=ce['value'], **context)
                if type(cn['raw']) is not str or cn['raw'] != ce['value']: fail('NATIVE_DISAGREES', 'native raw text differs from the declared value', cell + '.raw', native=cn['raw'], host=ce['value'], **context)


def column_kind(column): return 'number' if column['source'] == 'quantity' or column['valueType'] == 'number' else 'text'
def canonical_unit(column): return {'length': 'm', 'area': 'm2', 'volume': 'm3'}[column['quantity']] if column['source'] == 'quantity' else None


def quote(text): return '"' + text.replace('"', '""') + '"'


def csv_document(p, expected):
    """Typed CSV: quoted labels and text, shortest round-trip numbers, bare null token."""
    header = [*FIXED, *[c['name'] for c in p['columns']]]
    lines = [','.join(quote(h) for h in header)]
    for row in expected['rows']:
        cells = [quote(row['guid']), NULL_TOKEN if row['name'] is None else quote(row['name'])]
        for cell, column in zip(row['cells'], p['columns']):
            value = cell['value']
            cells.append(NULL_TOKEN if value is None else quote(value) if column_kind(column) == 'text' else repr(value))
        lines.append(','.join(cells))
    return ('\n'.join(lines) + '\n').encode('utf-8')


def documents(p, source_info, expected, identity):
    columns = [{'header': 'GUID', 'kind': 'text', 'nullable': False}, {'header': 'Name', 'kind': 'text', 'nullable': True}]
    for column in p['columns']:
        columns.append({'header': column['name'], 'kind': column_kind(column), 'nullable': p['missing'] == 'null', 'source': column['source'], 'set': column['set'],
                        **({'property': column['property'], 'valueType': column['valueType']} if column['source'] == 'property' else {'quantity': column['quantity'], 'quantityName': column['quantityName'], 'unit': canonical_unit(column)})})
    rows = [{'guid': r['guid'], 'name': r['name'], 'cells': [{'value': c['value'], 'origin': c['origin']} for c in r['cells']]} for r in expected['rows']]
    numeric = {c['name']: sum(1 for r in expected['rows'] for cell, col in zip(r['cells'], p['columns']) if col is c and cell['value'] is not None) for c in p['columns'] if column_kind(c) == 'number'}
    schedule = {'version': 'schemaxis.ifcopenshell.schedule/1', 'status': 'host-checked-schedule', 'runtime': RUNTIME,
                'source': {'sha256': source_info['sha256'], 'bytes': source_info['bytes'], 'schema': expected['schema'], 'entities': expected['counts']['entities']},
                'selection': {'class': p['class'], 'walls': expected['counts']['walls'], 'order': 'GlobalId ascending', 'inheritance': p['inheritance'], 'missing': p['missing'], 'zeroQuantity': p['zeroQuantity']},
                'units': {'projectUnits': expected['units'], 'canonical': {'length': 'm', 'area': 'm2', 'volume': 'm3'}, 'conversion': 'exact source decimal times a power of ten, rounded once to binary64'},
                'columns': columns, 'rows': rows, 'numericPresent': numeric, 'nullToken': NULL_TOKEN,
                'unassessed': {'entityClasses': {k: v for k, v in expected['counts']['byClass'].items() if k not in ('IFCWALL', 'IFCWALLTYPE', 'IFCPROJECT', 'IFCUNITASSIGNMENT', 'IFCSIUNIT', 'IFCRELDEFINESBYTYPE', 'IFCRELDEFINESBYPROPERTIES', 'IFCPROPERTYSET', 'IFCPROPERTYSINGLEVALUE', 'IFCELEMENTQUANTITY', 'IFCQUANTITYLENGTH', 'IFCQUANTITYAREA', 'IFCQUANTITYVOLUME')},
                               'geometry': 'unassessed', 'unitsOtherThanSelected': expected['unitsUnassessed']},
                'identity': {'ifcopenshell': identity['ifcopenshell'], 'python': identity['python'], 'wrapperSha256': identity['wrapperSha256']},
                'review': {'geometryAssessed': False, 'modelCertified': False, 'quantityAccuracyCertified': False, 'statement': REVIEW}, 'losses': LOSSES}
    return {'ifc-schedule.csv': csv_document(p, expected), 'ifc-schedule.json': encode_json(schedule)}, schedule


PUBLISHED = (('ifc-schedule.csv', 'table'), ('ifc-schedule.json', 'text'))


def artifacts(directory, p):
    records = [{'file': str(directory / n), 'kind': kind, 'sha256': digest(directory, n)} for n, kind in PUBLISHED]
    records[0].update(identity={'kind': 'table', 'format': CSV_FORMAT, 'nullToken': NULL_TOKEN}, losses=LOSSES,
                      verificationScope='Header, text/number/null cells and exact values regenerated from the independently walked source; geometry and the whole IFC file are not assessed.')
    return records


def evidence_names():
    return {'authored.json', 'plan.json', 'captures.json', SOURCE_FILE, INTENT_FILE, WORKER_FILE, 'host-expected.json', 'runtime.json', 'native-extract.json', 'native-reopen.json',
            *[s + x for s in STAGES for x in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr')]}


def membership(directory):
    from schemaxis.run_paths import MANIFEST
    published = [n for n, _ in PUBLISHED]
    expected = {*evidence_names(), *published, 'verification.json', 'result.json', 'schema.snapshot.json', MANIFEST, 'job.json', *[n + '.metadata.json' for n in published]}
    for path in directory.iterdir():
        if path.name == '.dispatch':
            if path.is_symlink() or not path.is_dir(): fail('VERIFICATION_FAILED', 'owned member is not a directory', path.name)
        elif path.name not in expected or path.is_symlink() or not path.is_file(): fail('VERIFICATION_FAILED', 'unexpected or nonregular retained schedule member', path.name)


def run(document, directory, *, executable=None, timeout=300):
    p = plan(document)
    executable = executable or os.environ.get('SCHEMAXIS_IFCOPENSHELL')
    if not executable or not os.path.isabs(executable) or not os.access(executable, os.X_OK): fail('INTERPRETER_NOT_FOUND', 'configure an absolute IfcOpenShell 0.9.0.post1 Python interpreter')
    executable = os.path.abspath(executable)  # never resolve: a venv interpreter is a symlink whose identity is the venv
    if os.name != 'posix': fail('UNSUPPORTED_PLATFORM', 'native resource caps require POSIX')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600: fail('INVALID_ARGUMENT', 'timeout must be finite in (0,3600]')
    deadline = time.monotonic() + timeout;directory = Path(directory).absolute();launched = False
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS', 'select a fresh output directory', str(directory))
    directory.mkdir(parents=True);atomic_json(directory / 'authored.json', document);atomic_json(directory / 'plan.json', p)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    def checkpoint():
        if cancellation_requested(): fail('RUNNER_CANCELLED', 'extraction cancelled')
        if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'extraction exhausted its total deadline')
    try:
        checkpoint()
        data = source_bytes(p['source']['path'])
        info = {'sha256': sha(data), 'bytes': len(data)}
        if 'sha256' in p['source'] and p['source']['sha256'] != info['sha256']: fail('SOURCE_HASH_MISMATCH', 'source bytes differ from the pinned sha256', '$.source.sha256', observed=info['sha256'])
        (directory / SOURCE_FILE).write_bytes(data)
        atomic_json(directory / 'captures.json', {'source': p['source']['path'], **info})
        expected = step.resolve(step.parse(data), p)  # every supported-contract refusal happens here, before any native process
        atomic_json(directory / 'host-expected.json', expected)
        (directory / WORKER_FILE).write_bytes(WORKER_SOURCE.read_bytes())
        (directory / INTENT_FILE).write_bytes(encode_json(intent_of(p)))
        checkpoint()
        for stage, command in commands(executable, p).items():
            path = directory / (stage + '-launcher.py');path.write_text(launcher(directory, stage, command, p));launched = True
            execute([sys.executable, str(path)], directory, stage, deadline - time.monotonic(), {'LANG': 'C.UTF-8'})
            if stage == 'version': atomic_json(directory / 'runtime.json', {'executable': executable, **identity_of(directory)})
        checkpoint()
        extract, reopen = (bounded(directory / n) for n in ('native-extract.json', 'native-reopen.json'))
        if extract != reopen: fail('NATIVE_REOPEN_DIFFERS', 'a fresh native reopen produced a different raw table', 'native-reopen.json')
        check_native(strict_json(extract, 'native-extract.json'), expected, p, 'native-extract.json')
        files, _ = documents(p, info, expected, identity_of(directory))
        for name, content in files.items(): (directory / name).write_bytes(content)
        atomic_json(directory / 'verification.json', {'executable': executable, 'runtime': RUNTIME, 'planSha256': plan_hash(p), 'artifacts': artifacts(directory, p),
            'evidence': {n: digest(directory, n, SOURCE_LIMIT) for n in sorted(evidence_names())}})
        result = verify(directory, require_result=False)
        checkpoint()
        result['status'] = 'succeeded';atomic_json(directory / 'result.json', result);return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try:
                if launched: fail('NATIVE_EXECUTION_FAILED', str(error))
                fail('HOST_EXECUTION_FAILED', 'an unexpected host failure occurred before any native process was launched: ' + type(error).__name__ + ': ' + str(error)[:200])
            except SchemaxisError as wrapped: error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()});raise error


def verify(directory, require_result=True):
    """Offline: rebuilds the expected schedule from retained source and rechecks every retained native file. Receipt values are not trusted."""
    directory = Path(directory).absolute()
    try:
        p = plan(read(directory, 'authored.json'));receipt = read(directory, 'verification.json')
        if not isinstance(receipt, dict) or set(receipt) != {'executable', 'runtime', 'planSha256', 'artifacts', 'evidence'} or not isinstance(receipt['evidence'], dict): fail('VERIFICATION_FAILED', 'native receipt member set differs')
        if not same_json(read(directory, 'plan.json'), p) or receipt['planSha256'] != plan_hash(p): fail('VERIFICATION_FAILED', 'effective schedule plan differs from the authored input or receipt')
        if require_result and read(directory, 'result.json').get('status') != 'succeeded': fail('INCOMPLETE_EXECUTION', 'extraction did not complete')
        membership(directory)
        data = bounded(directory / SOURCE_FILE, limit=SOURCE_LIMIT);info = {'sha256': sha(data), 'bytes': len(data)}
        if 'sha256' in p['source'] and p['source']['sha256'] != info['sha256']: fail('VERIFICATION_FAILED', 'captured source differs from the pinned sha256')
        if not same_json(read(directory, 'captures.json'), {'source': p['source']['path'], **info}): fail('VERIFICATION_FAILED', 'source capture binding differs')
        expected = step.resolve(step.parse(data), p)
        if not same_json(read(directory, 'host-expected.json'), expected): fail('VERIFICATION_FAILED', 'retained host expectation differs from the independent walk of the captured source', 'host-expected.json')
        if bounded(directory / WORKER_FILE) != WORKER_SOURCE.read_bytes(): fail('VERIFICATION_FAILED', 'retained native worker differs from the packaged worker', WORKER_FILE)
        if bounded(directory / INTENT_FILE) != encode_json(intent_of(p)): fail('VERIFICATION_FAILED', 'retained native intent differs from the plan', INTENT_FILE)
        executable = receipt['executable']
        if not isinstance(executable, str) or not os.path.isabs(executable): fail('VERIFICATION_FAILED', 'native executable identity must be absolute')
        for stage, command in commands(executable, p).items():
            submission = read(directory, stage + '-submission.json');path = directory / (stage + '-launcher.py')
            interpreter = submission.get('interpreter', {}).get('executable') if isinstance(submission, dict) and isinstance(submission.get('interpreter'), dict) else None
            if not isinstance(interpreter, str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand') != [interpreter, str(path)] or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0: fail('VERIFICATION_FAILED', 'native command/completion differs', stage)
            if bounded(path).decode() != launcher(directory, stage, command, p): fail('VERIFICATION_FAILED', 'trusted native launcher differs', stage)
            bindings = read(directory, stage + '-inputs.json');wanted = {'files': {n: digest(directory, n, SOURCE_LIMIT) for n in stage_inputs(stage)}}
            if not same_json(bindings, wanted): fail('VERIFICATION_FAILED', 'native input binding differs', stage)
        identity = identity_of(directory, 'VERIFICATION_FAILED')
        if receipt['runtime'] != RUNTIME or not same_json(read(directory, 'runtime.json'), {'executable': executable, **identity}): fail('VERIFICATION_FAILED', 'runtime identity differs from the native version stage')
        extract, reopen = (bounded(directory / n) for n in ('native-extract.json', 'native-reopen.json'))
        if extract != reopen: fail('NATIVE_REOPEN_DIFFERS', 'a fresh native reopen produced a different raw table', 'native-reopen.json')
        native = strict_json(extract, 'native-extract.json')
        check_native(native, expected, p, 'native-extract.json')
        if not same_json(native['identity'], identity): fail('VERIFICATION_FAILED', 'native extraction ran under a different library identity than the version stage', 'native-extract.json.identity')
        files, schedule = documents(p, info, expected, identity)
        for name, content in files.items():
            if bounded(directory / name, limit=JSON_LIMIT) != content: fail('VERIFICATION_FAILED', 'published schedule file differs from independently checked evidence', name)
        if not same_json(receipt['artifacts'], artifacts(directory, p)): fail('VERIFICATION_FAILED', 'schedule publication membership/digest differs')
        if set(receipt['evidence']) != evidence_names(): fail('VERIFICATION_FAILED', 'native evidence membership differs')
        for n in evidence_names():
            if digest(directory, n, SOURCE_LIMIT) != receipt['evidence'][n]: fail('VERIFICATION_FAILED', 'retained native evidence differs', n)
        fresh = {'verified': True, 'artifacts': len(PUBLISHED), 'runtime': RUNTIME, 'walls': schedule['selection']['walls'], 'columns': len(schedule['columns']),
                 'sourceSha256': info['sha256'], 'geometryAssessed': False, 'modelCertified': False}
        if require_result and not same_json(read(directory, 'result.json'), {**fresh, 'status': 'succeeded'}): fail('VERIFICATION_FAILED', 'retained result differs from independent reopening')
        return fresh
    except SchemaxisError as error:
        if error.fault.code in ('VERIFICATION_FAILED', 'INCOMPLETE_EXECUTION', 'NATIVE_DISAGREES', 'NATIVE_REOPEN_DIFFERS'): raise
        fail('VERIFICATION_FAILED', 'retained schedule evidence violates its contract (' + error.fault.code + ')', error.fault.location, cause=error.fault.to_dict())
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeDecodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained schedule evidence: ' + str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
