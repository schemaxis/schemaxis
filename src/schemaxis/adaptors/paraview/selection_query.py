"""ParaView selection queries as a closed authored grammar; host-safe.

ParaView 5.13.3 evaluates a selection ``QueryString`` with Python ``eval`` when
a query selection is extracted: vtkPVExtractSelection::NewSelectionOperator
returns vtkPythonSelector, which calls paraview/detail/python_selector.py
``execute`` and then paraview/detail/calculator.py ``compute``. Authors therefore
never supply query text. They describe the query with the JSON grammar below,
and Schemaxis writes the text itself using only the operators and functions of
ParaView's own Find Data panel (pqSelectionQueryPropertyWidget.cxx). The
generated text is then checked again by an independent allow-list over Python's
syntax tree, here and immediately before native assignment.

Nothing here imports ParaView or evaluates code.
"""
import ast
import math
import re
import string
from schemaxis.core.declarations import validate_value
from schemaxis.errors import fail

COMPILER = 'paraview.selectionQuery'
INVALID = 'INVALID_SELECTION_QUERY'
UNSAFE = 'UNSAFE_NATIVE_QUERY'

MAX_NAME = 256
MAX_GROUPS = 16
MAX_CLAUSES = 16
MAX_VALUES = 256
MAX_TEXT = 16384
MAX_NESTING = 32
MAX_DEPTH = 48
MAX_NODES = 4096
MAX_INTEGER = 2 ** 53

# Native property commands whose values ParaView 5.13.3 evaluates as Python.
# A compiler name means Schemaxis generates the value from a closed grammar;
# None means no value may be assigned at all. Python-backed classes that reuse
# a generic command (vtkPythonCalculator.SetExpression) are refused by class.
PYTHON_EVALUATED = {
    'SetQueryString': COMPILER,          # vtkSelectionSource -> vtkPythonSelector
    'SetPythonExpression': None,         # vtkExplicitStructuredGridPythonExtractor
    'SetMultilineExpression': None,      # vtkPythonCalculator
    'SetScript': None,                   # programmable filters, Python view and cue
    'SetInformationScript': None,
    'SetUpdateExtentScript': None,
    'SetCheckNeedsUpdateScript': None,
    'SetPythonPath': None,
}

# Find Data operators, keyed by the authored test name. Values are the extra
# clause members each test requires; every test except the two location tests
# also needs one term (array or ids).
COMPARISONS = ('==', '!=', '<', '<=', '>', '>=')
STATISTICS = {'isMinimum': 'min', 'isMaximum': 'max', 'isMinimumPerBlock': 'min_per_block',
              'isMaximumPerBlock': 'max_per_block'}
MEANS = {'atMostMean': '<=', 'atLeastMean': '>='}
MEMBERS = {**{test: ('value',) for test in COMPARISONS}, 'between': ('minimum', 'maximum'),
           'oneOf': ('values',), **{test: () for test in STATISTICS}, 'isNaN': (),
           **{test: () for test in MEANS}, 'nearMean': ('tolerance',),
           'pointNear': ('point', 'tolerance'), 'cellContaining': ('point',)}
LOCATIONS = ('pointNear', 'cellContaining')
TERM = ('array', 'ids', 'component', 'magnitude')

NUMBER = {'type': 'number'}
CLAUSE = {'type': 'object', 'properties': {
    'array': {'type': 'string', 'minLength': 1, 'maxLength': MAX_NAME},
    'ids': {'type': 'boolean'},
    'component': {'type': 'integer', 'minimum': 0, 'maximum': 255},
    'magnitude': {'type': 'boolean'},
    'test': {'type': 'enum', 'values': list(MEMBERS), 'required': True},
    'value': NUMBER,
    'values': {'type': 'array', 'items': NUMBER, 'minItems': 1, 'maxItems': MAX_VALUES},
    'minimum': NUMBER,
    'maximum': NUMBER,
    'point': {'type': 'array', 'items': NUMBER, 'minItems': 3, 'maxItems': 3},
    'tolerance': {'type': 'number', 'minimum': 0},
    'negate': {'type': 'boolean'}}}
QUERY = {'type': 'object', 'required': True, 'properties': {
    'any': {'type': 'array', 'required': True, 'minItems': 1, 'maxItems': MAX_GROUPS, 'items': {
        'type': 'object', 'properties': {
            'all': {'type': 'array', 'required': True, 'minItems': 1, 'maxItems': MAX_CLAUSES,
                    'items': CLAUSE}}}}}}

# Functions the generated text may call. ParaView resolves them in the globals
# of paraview.detail.calculator: the VTK numpy algorithms module (imported with
# *) and the module's own pointIsNear and cellContainsPoint.
FUNCTIONS = frozenset({'abs', 'in1d', 'isnan', 'logical_not', 'mag', 'mean', 'min', 'max',
                       'min_per_block', 'max_per_block', 'pointIsNear', 'cellContainsPoint'})
# Names an array reference may not use: keywords, built-in functions and
# constants, the query functions, and the names compute() itself binds.
RESERVED = frozenset('''
    False None True and as assert async await break class continue def del elif else except
    finally for from global if import in is lambda nonlocal not or pass raise return try while
    with yield Ellipsis NotImplemented abs aiter all anext any ascii bin bool breakpoint
    bytearray bytes callable chr classmethod compile complex copyright credits delattr dict
    dir divmod enumerate eval exec exit filter float format frozenset getattr globals hasattr
    hash help hex id input int isinstance issubclass iter len license list locals map max
    memoryview min next object oct open ord pow print property quit range repr reversed round
    set setattr slice sorted staticmethod str sum super tuple type vars zip inputs points
    '''.split()) | FUNCTIONS
IDENTIFIER = re.compile('[A-Za-z][A-Za-z0-9_]{0,%d}' % (MAX_NAME - 1))
CHARACTERS = re.compile(r'[A-Za-z0-9_ .,:()\[\]&|<>=!+-]*')
VALID = frozenset(string.ascii_letters + string.digits + '_')


def sanitise(name):
    """ParaView's array-variable name: vtkSMCoreUtilities::SanitizeName."""
    result = ''.join(character for character in name if character in VALID)
    return result if not result or result[0].isalpha() else 'a' + result


def compile_query(value, location='QueryString'):
    """Return ParaView query text for one structured query, or fail."""
    value = validate_value(value, QUERY, location)
    groups = []
    for g, group in enumerate(value['any']):
        clauses = [_clause(clause, f'{location}.any[{g}].all[{c}]')
                   for c, clause in enumerate(group['all'])]
        groups.append(' & '.join('(' + text + ')' for text in clauses))
    text = groups[0] if len(groups) == 1 else ' | '.join('(' + text + ')' for text in groups)
    check_text(text, location)
    return text


def _clause(clause, location):
    test = clause['test']
    members = set(MEMBERS[test]) | ({'negate'} if 'negate' in clause else set())
    if test not in LOCATIONS:
        members |= {key for key in TERM if key in clause}
    for key in sorted(set(clause) - members - {'test'}):
        fail(INVALID, f'{key!r} does not apply to the {test!r} test', location + '.' + key,
             test=test, accepted=sorted(members))
    for key in MEMBERS[test]:
        if key not in clause:
            fail(INVALID, f'the {test!r} test requires {key!r}', location + '.' + key, test=test)
    if test in LOCATIONS:
        point = '[(' + ', '.join(_number(v, f'{location}.point[{i}]')
                                 for i, v in enumerate(clause['point'])) + ')]'
        text = (f"pointIsNear({point}, {_number(clause['tolerance'], location + '.tolerance')}, inputs)"
                if test == 'pointNear' else f'cellContainsPoint(inputs, {point})')
    else:
        term = _term(clause, location)
        if test in COMPARISONS:
            text = f"{term} {test} {_number(clause['value'], location + '.value')}"
        elif test == 'between':
            low = _number(clause['minimum'], location + '.minimum')
            high = _number(clause['maximum'], location + '.maximum')
            if not clause['minimum'] < clause['maximum']:
                fail(INVALID, 'minimum must be less than maximum', location + '.maximum',
                     minimum=clause['minimum'], maximum=clause['maximum'])
            text = f'({term} > {low}) & ({term} < {high})'
        elif test == 'oneOf':
            text = f"in1d({term}, [{', '.join(_number(v, f'{location}.values[{i}]') for i, v in enumerate(clause['values']))}])"
        elif test in STATISTICS:
            text = f'{term} == {STATISTICS[test]}({term})'
        elif test == 'isNaN':
            text = f'isnan({term})'
        elif test in MEANS:
            text = f'{term} {MEANS[test]} mean({term})'
        else:
            text = f"abs({term} - mean({term})) <= {_number(clause['tolerance'], location + '.tolerance')}"
    return f'logical_not({text})' if clause.get('negate') else text


def _term(clause, location):
    if clause.get('ids') and 'array' in clause:
        fail(INVALID, 'choose either array or ids, not both', location + '.ids')
    if clause.get('ids'):
        for key in ('component', 'magnitude'):
            if key in clause:
                fail(INVALID, f'{key!r} applies only to an array', location + '.' + key)
        return 'id'
    if 'array' not in clause:
        fail(INVALID, 'name the array to test, or set ids to true for element indices',
             location + '.array')
    name = sanitise(clause['array'])
    if not name:
        fail(INVALID, 'array name has no ASCII letters, digits or underscores', location + '.array',
             array=clause['array'])
    if name == 'id':
        fail(INVALID, 'ParaView reserves id for element indices; use "ids": true', location + '.array')
    if '__' in name:
        fail(INVALID, 'array variable names may not contain a double underscore', location + '.array',
             array=clause['array'], variable=name)
    if name in RESERVED:
        fail(INVALID, 'array name collides with a Python name the query cannot shadow safely',
             location + '.array', array=clause['array'], variable=name,
             recovery='rename the array upstream, for example with pvPassArrays or a calculator')
    if 'component' in clause and clause.get('magnitude'):
        fail(INVALID, 'choose either component or magnitude, not both', location + '.magnitude')
    if 'component' in clause:
        return f"{name}[:, {clause['component']}]"
    return f'mag({name})' if clause.get('magnitude') else name


def _number(value, location):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        fail(INVALID, 'expected a finite number', location)
    if isinstance(value, int):
        if abs(value) > MAX_INTEGER:
            fail(INVALID, 'integer exceeds the exactly representable range', location, limit=MAX_INTEGER)
        return str(value)
    return repr(value)


def check_text(text, location='QueryString'):
    """Accept only query text inside the generated language; never evaluate it."""
    def reject(reason, **observed):
        fail(UNSAFE, 'query text is outside the Schemaxis selection-query language', location,
             reason=reason, **observed)

    if not isinstance(text, str):
        reject('query text must be a string')
    if not text or len(text) > MAX_TEXT:
        reject('query text must be nonempty and bounded', length=len(text), limit=MAX_TEXT)
    if not CHARACTERS.fullmatch(text):
        reject('query text contains a character the language never uses')
    if ' and ' in text:
        # calculator.compute splits on this substring before each eval.
        reject('query text contains the word and')
    nesting = deepest = 0
    for character in text:
        nesting += character in '(['
        nesting -= character in ')]'
        deepest = max(deepest, nesting)
    if deepest > MAX_NESTING:
        reject('query text nests too deeply', nesting=deepest, limit=MAX_NESTING)
    try:
        tree = ast.parse(text, mode='eval')
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        reject('query text is not a valid expression')
    counter = [0]

    def visit(node, depth):
        counter[0] += 1
        if depth > MAX_DEPTH or counter[0] > MAX_NODES:
            reject('query expression is too large')

    def call(node, depth, names, count):
        visit(node, depth)
        if (not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name)
                or node.func.id not in names or node.keywords or len(node.args) != count):
            return False
        visit(node.func, depth + 1)
        return True

    def mask(node, depth):
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.BitAnd, ast.BitOr)):
            visit(node, depth); mask(node.left, depth + 1); mask(node.right, depth + 1)
        elif call(node, depth, {'logical_not'}, 1):
            mask(node.args[0], depth + 1)
        elif call(node, depth, {'isnan'}, 1):
            term(node.args[0], depth + 1)
        elif call(node, depth, {'in1d'}, 2):
            term(node.args[0], depth + 1); numbers(node.args[1], depth + 1, MAX_VALUES)
        elif call(node, depth, {'pointIsNear'}, 3):
            points(node.args[0], depth + 1); number(node.args[1], depth + 1); inputs(node.args[2], depth + 1)
        elif call(node, depth, {'cellContainsPoint'}, 2):
            inputs(node.args[0], depth + 1); points(node.args[1], depth + 1)
        elif (isinstance(node, ast.Compare) and len(node.ops) == 1
              and isinstance(node.ops[0], (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE))):
            visit(node, depth); value(node.left, depth + 1); value(node.comparators[0], depth + 1)
        else:
            reject('unsupported selection construct', node=type(node).__name__)

    def value(node, depth):
        if call(node, depth, {'abs'}, 1):
            value(node.args[0], depth + 1)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
            visit(node, depth); value(node.left, depth + 1); value(node.right, depth + 1)
        elif call(node, depth, set(STATISTICS.values()) | {'mean'}, 1):
            term(node.args[0], depth + 1)
        elif isinstance(node, (ast.Constant, ast.UnaryOp)):
            number(node, depth)
        else:
            term(node, depth)

    def term(node, depth):
        visit(node, depth)
        if isinstance(node, ast.Name) and node.id == 'id':
            return name(node, depth, allow_id=True)
        if isinstance(node, ast.Name):
            return name(node, depth)
        if call(node, depth, {'mag'}, 1):
            return name(node.args[0], depth + 1)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Tuple) and len(node.slice.elts) == 2:
            whole, index = node.slice.elts
            if (isinstance(whole, ast.Slice) and whole.lower is None and whole.upper is None
                    and whole.step is None and isinstance(index, ast.Constant)
                    and type(index.value) is int and 0 <= index.value <= 255):
                visit(node.slice, depth + 1); visit(whole, depth + 2); visit(index, depth + 2)
                return name(node.value, depth + 1)
        reject('unsupported array reference', node=type(node).__name__)

    def name(node, depth, allow_id=False):
        visit(node, depth)
        if (not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load)
                or not IDENTIFIER.fullmatch(node.id) or '__' in node.id
                or (node.id in RESERVED and not allow_id)):
            reject('unsupported or reserved name', name=getattr(node, 'id', None))

    def number(node, depth):
        visit(node, depth)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            node = node.operand
            visit(node, depth + 1)
        if (not isinstance(node, ast.Constant) or type(node.value) not in (int, float)
                or not math.isfinite(node.value)):
            reject('unsupported literal', node=type(node).__name__)

    def numbers(node, depth, limit):
        visit(node, depth)
        if not isinstance(node, ast.List) or not 1 <= len(node.elts) <= limit:
            reject('expected a bounded list of numbers')
        for item in node.elts:
            number(item, depth + 1)

    def points(node, depth):
        visit(node, depth)
        if not isinstance(node, ast.List) or len(node.elts) != 1:
            reject('expected one location')
        location_node = node.elts[0]
        visit(location_node, depth + 1)
        if not isinstance(location_node, ast.Tuple) or len(location_node.elts) != 3:
            reject('a location has three coordinates')
        for item in location_node.elts:
            number(item, depth + 2)

    def inputs(node, depth):
        visit(node, depth)
        if not isinstance(node, ast.Name) or node.id != 'inputs' or not isinstance(node.ctx, ast.Load):
            reject('location tests take the native inputs list only')

    mask(tree.body, 0)
    return text


# Native commands whose argument is an in-process memory address that the native
# reader dereferences. Authored input must never reach them (compile-time gap in
# catalogue_import, and refused again at assignment).
UNSAFE_COMMANDS = {'SetDataSourceIO': 'in-process memory address that the native reader dereferences; '
                                      'unsafe for authored input'}


def guard_native_value(command, value, location):
    """Final check at native assignment, after runtime values are resolved."""
    if command in UNSAFE_COMMANDS:
        fail('UNSAFE_NATIVE_PROPERTY', 'this native property takes ' + UNSAFE_COMMANDS[command]
             + '; Schemaxis never assigns it', location, command=command)
    if command not in PYTHON_EVALUATED:
        return value
    if PYTHON_EVALUATED[command] is None:
        fail('UNSAFE_NATIVE_PROPERTY', 'ParaView evaluates this property as Python; Schemaxis never assigns it',
             location, command=command)
    return check_text(value, location)


from schemaxis.bindings import register_compiler
register_compiler(COMPILER, compile_query)
