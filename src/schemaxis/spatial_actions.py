# Copyright (C) 2026 David L. F. Gaden.
"""Host actions of the expression language: check, list, evaluate and load.

These four actions are the whole interface Studio, the command line and the
agent service use (docs/design/expression-language.md, appendix A). They are
stateless and accept an incomplete draft: only what an action needs is read.
"""
import copy
import math

from schemaxis.core.faults import Fault, SchemaxisError
from . import expr, expressions
from .errors import fail
from .expr.values import BOX, SCALAR, VECTOR
from .expressions import SECTIONS, Scope, State, pointer

ACTIONS = ('spatial_check', 'spatial_list', 'spatial_eval', 'spatial_load', 'spatial_rename')
SPATIAL = (SCALAR, VECTOR, BOX)
TYPED = (SCALAR, VECTOR, BOX, expr.values.BOOLEAN, expr.values.STRING)
WORKFLOW = 'schemaxis.workflow/'
UNRESOLVED = {'OBSERVATION_UNAVAILABLE': 'needs-data', 'EXPR_PHASE': 'needs-state'}


class Member:
    """One document of the input: the envelope, an operation or a plain document."""

    def __init__(self, document, base, scope, operation=None, analytic=(), authored=None):
        self.document = document
        self.authored = document if authored is None else authored
        self.base = base
        self.scope = scope
        self.operation = operation
        self.analytic = analytic

    def location(self, path=''):
        return '$' + self.base + path

    def identity(self, section, key):
        return {'scope': self.scope.kind, 'section': section, 'key': key}

    def entries(self):
        return [(section, key) for section in SECTIONS for key in self.scope.sections.get(section, {})]


def route_of(document):
    """Route of a document's adaptor, or None when its version is not known."""
    from .adaptors import registry
    version = document.get('version')
    route = registry.routes().get(version) if isinstance(version, str) else None
    return None if route is None else route[1]


def settled(document, workflow=None):
    """A document whose axes and times hold the values of their constant expressions, as a plan reads them.

    A draft whose axes or times cannot be resolved yet is left as written.
    """
    late = [key for key in ('sweeps', 'times') if expressions.has_expressions(document.get(key))]
    if not late:
        return document
    try:
        folder = expressions.Folder(document, workflow=workflow)
        return {**document, **{key: folder.fold(document[key], pointer('', key)) for key in late}}
    except (SchemaxisError, expr.ExprFault, TypeError, AttributeError, KeyError):
        return document


def planned(document):
    """A graph document with its member analytics named as a plan names them, and those names.

    A draft whose analytics cannot be compiled yet is left as written.
    """
    route = route_of(document)
    if route is None or not route.get('graph') or not isinstance(document.get('nodes'), list):
        return document, ()
    from .analytics import compile_analytics
    try:
        compiled, bindings = compile_analytics(document)
    except (SchemaxisError, expr.ExprFault, TypeError, AttributeError, KeyError):
        return document, ()
    return compiled, tuple(dict.fromkeys(binding['axis'] for binding in bindings))


class Draft:
    """The input of one request and the documents an action may read."""

    def __init__(self, request):
        if not isinstance(request, dict) or not isinstance(request.get('input'), dict):
            fail('INVALID_REQUEST', 'a spatial action needs the whole authored input as an object', '$.input')
        self.request = request
        self.input = request['input']
        self.operation = request.get('operation')
        from .pipeline import digest
        try:
            self.digest = digest(self.input)
        except (TypeError, ValueError):
            fail('INVALID_REQUEST', 'the input is not finite JSON', '$.input')
        version = self.input.get('version')
        design = version in ('schemaxis.workflow-design/1', 'schemaxis.workflow-design/2')
        body = self.input.get('workflow') if design else self.input
        base = '/workflow' if design else ''
        if design and (not isinstance(body, dict) or body.get('version') != WORKFLOW + '1'):
            fail('INVALID_REQUEST', 'A design needs an ordinary workflow', '$.input.workflow')
        self.workflow = design or isinstance(version, str) and version.startswith(WORKFLOW)
        self.envelope = None
        self.operations = []
        if not self.workflow:
            if self.operation is not None:
                fail('INVALID_REQUEST', 'only a workflow has operations to select', '$.operation')
            document, analytic = planned(settled(self.input))
            self.selected = Member(document, '', Scope(document, adaptor=expressions.adaptor_of(document)),
                                   analytic=analytic, authored=self.input)
            return
        scope = Scope(body, kind='workflow', adaptor=expressions.Adaptor(False, None, 'workflow'))
        scope.workflow = scope
        self.envelope = Member(body, base, scope)
        operations = body.get('operations')
        for index, operation in enumerate(operations if isinstance(operations, list) else []):
            if (isinstance(operation, dict) and isinstance(operation.get('id'), str)
                    and isinstance(operation.get('document'), dict)):
                document, analytic = planned(settled(operation['document'], scope))
                self.operations.append(Member(
                    document, base + f'/operations/{index}/document',
                    Scope(document, workflow=scope, adaptor=expressions.adaptor_of(document)), operation['id'],
                    analytic, operation['document']))
        if self.operation is None:
            self.selected = self.envelope
        else:
            found = [member for member in self.operations if member.operation == self.operation]
            if not found:
                fail('UNKNOWN_OPERATION', 'the workflow has no such operation', '$.operation',
                     operation=self.operation, available=[member.operation for member in self.operations])
            self.selected = found[0]

    def listed(self):
        """Documents whose entries are reported when none are named."""
        if self.workflow and self.operation is None:
            return [self.envelope] + self.operations
        return [self.selected]

    def response(self, **fields):
        result = {'inputDigest': self.digest, 'capabilities': {'extents': self.selected.scope.adaptor.extents is True}}
        if 'draft' in self.request:
            result['draft'] = copy.deepcopy(self.request['draft'])
        result.update(fields)
        return result

    def find(self, identity):
        """Member and entry named by an identity, or a fault record's reason."""
        if not isinstance(identity, dict) or identity.get('section') not in SECTIONS \
                or not isinstance(identity.get('key'), str):
            fail('INVALID_REQUEST', 'an entry is identified by scope, section and key', '$.entries')
        if 'operation' in identity:
            members = [member for member in self.operations if member.operation == identity['operation']]
        elif identity.get('scope') == 'workflow':
            members = [self.envelope] if self.envelope else []
        else:
            members = [self.selected] if self.selected is not self.envelope else []
        for member in members:
            if identity['key'] in member.scope.sections.get(identity['section'], {}):
                return member
        return None


def fault_of(error):
    return error.fault.to_dict()


def located(fault, location, phase='input'):
    """Fault record of an expression fault at a document location."""
    try:
        expressions.raise_fault(fault, location, phase)
    except SchemaxisError as error:
        return fault_of(error)


def depends_on(profile):
    ports, complete = {}, set()
    for item in profile.dependencies:
        if item[0] == 'port':
            ports.setdefault(item[1], set()).add(item[2])
        elif item[0] == 'ports':
            complete.add(item[1])
    nodes = []
    for node in sorted(profile.nodes):
        if node in complete:
            nodes.append({'node': node, 'allPorts': True})
        nodes.extend({'node': node, 'port': port} for port in sorted(ports.get(node, ())))
        if node not in complete and node not in ports:
            nodes.append({'node': node, 'port': 0})
    result = {'entries': [{'scope': scope, 'section': section, 'key': key}
                          for scope, section, key in sorted(profile.entries)],
              'nodes': nodes, 'sweeps': sorted(axis for axis in profile.axes if axis != expressions.ANALYTIC),
              'awaits': sorted(profile.awaits)}
    if profile.time:
        result['time'] = True
    return result


def canonical(value, kind):
    """Value of a spatial type in its canonical JSON form."""
    return expr.to_json(expr.coerce(value, kind))


class Visit:
    """The state a request selects and the observations that belong to it."""

    def __init__(self, draft, evaluate):
        request = draft.request
        self.draft = draft
        self.evaluate = evaluate
        state = request.get('state', {})
        if not isinstance(state, dict) or not isinstance(state.get('indices', {}), dict):
            fail('INVALID_REQUEST', 'state holds timeIndex and indices', '$.state')
        self.time_index = state.get('timeIndex', 0)
        self.indices = dict(state.get('indices', {}))
        if type(self.time_index) is not int or self.time_index < 0 or any(
                type(index) is not int or index < 0 for index in self.indices.values()):
            fail('INVALID_SELECTION', 'state positions are nonnegative whole numbers', '$.state')
        self.state = {'timeIndex': self.time_index, 'indices': self.indices}
        self.observations = request.get('observations')
        self.reason = 'needs-data'
        self.observed = {}
        self.loaded = False
        if self.observations is not None:
            self.read_observations()

    def read_observations(self):
        given = self.observations
        if not isinstance(given, dict) or not isinstance(given.get('extents'), list):
            fail('INVALID_REQUEST', 'observations are passed back as spatial_load returned them', '$.observations')
        if (given.get('inputDigest') != self.draft.digest or given.get('operation') != self.draft.operation
                or given.get('state') != self.state):
            self.reason = 'stale-data'
            return
        self.loaded = True
        for item in given['extents']:
            if not isinstance(item, dict) or not isinstance(item.get('node'), str) or type(item.get('port')) is not int:
                fail('INVALID_REQUEST', 'an observed extent names a node and port', '$.observations.extents')
            record = self.observed.setdefault(item['node'], {'extents': []})
            status = item.get('status')
            if status == 'fault':
                record['extentsFault'] = item.get('fault') if isinstance(item.get('fault'), dict) else {}
                continue
            ports = record['extents']
            ports.extend([None] * (item['port'] + 1 - len(ports)))
            ports[item['port']] = (list(item['bounds']) if status == 'ok'
                                   else list(expressions.INVALID_SIX) if status == 'empty' else None)

    def source(self, kind):
        return {'kind': kind, 'inputDigest': self.draft.digest, 'state': copy.deepcopy(self.state)}

    def axes(self, member):
        """Value of every axis of a member at the selected state."""
        scope, values = member.scope, {}
        for name, items in scope.axes.items():
            index = self.indices.get(name, 0)
            if isinstance(items, list) and index < len(items):
                values[name] = items[index]
        for axis, declared in scope.sweeps.items():
            index = self.indices.get(axis, 0)
            if index < declared['count']:
                values[axis] = index
        return values

    def time(self, member):
        times = member.document.get('times', [0.0])
        if isinstance(times, list) and self.time_index < len(times) and type(times[self.time_index]) in (int, float):
            return times[self.time_index]
        return None

    def context(self, member, location):
        return State(self.axes(member), self.observed, self.time(member), None, location)


def unresolved(record, reason):
    record.update(state='unresolved', reason=reason)
    return record


def faulted(record, fault):
    record.update(state='fault', fault=fault)
    return record


def resolve(record, kind, profile, visit, literal, compute):
    """Fill in the state of a record: resolved with a value, unresolved or a fault."""
    if profile.pending:
        return unresolved(record, 'awaits-producer')
    if profile.phase != expr.CONSTANT and not visit.evaluate:
        return unresolved(record, 'needs-data' if profile.observed else 'needs-state')
    if profile.observed and not visit.loaded:
        return unresolved(record, visit.reason)
    try:
        value = canonical(compute(), kind) if kind in SPATIAL else compute()
    except SchemaxisError as error:
        if error.fault.code in UNRESOLVED:
            return unresolved(record, UNRESOLVED[error.fault.code])
        return faulted(record, fault_of(error))
    except expr.ExprFault as fault:
        return faulted(record, located(fault, '$', 'pipeline'))
    record.update(state='resolved', value=value)
    if kind == BOX:
        record['valid'] = not expressions.is_invalid_box(value)
    record['source'] = visit.source('literal' if literal else 'live' if profile.observed else 'constant')
    return record


def entry_record(draft, member, section, key, visit, explain=False, named=False):
    """Record of one entry; None when it is not a scalar, vector or box and was not named."""
    scope, raw = member.scope, member.scope.sections[section][key]
    path = pointer(pointer('', section), key)
    record = {'entry': member.identity(section, key)}
    if member.operation is not None:
        record['operation'] = member.operation
    if expressions.is_expression(raw):
        record['expression'] = raw['$expr']
    try:
        binding = scope.entry(section, key)
    except expr.ExprFault as fault:
        return faulted(record, located(fault, member.location(path)))
    if binding.type not in SPATIAL and not named:
        return None
    profile = binding.profile
    record.update(type=binding.type, phase=expr.PHASES[profile.phase], dependsOn=depends_on(profile))
    if explain:
        record['chains'] = [cause.chain for cause in scope.causes(raw, path)]
    location = member.location(path)
    return resolve(record, binding.type, profile, visit, not expressions.has_markers(raw),
                   Reader(scope, section, key, visit, member, location).value)


class Reader:
    """Evaluates one entry at the visit of a request."""

    def __init__(self, scope, section, key, visit, member, location):
        self.scope, self.section, self.key = scope, section, key
        self.visit, self.member, self.location = visit, member, location

    def value(self):
        return self.scope.entry_value(self.section, self.key, self.visit.context(self.member, self.location))


class Expression:
    """One ad-hoc expression checked, and optionally evaluated, in a member."""

    def __init__(self, member, text, destination):
        if not isinstance(text, str):
            fail('INVALID_REQUEST', 'expression is a string', '$.expression')
        if destination is not None and (not isinstance(destination, str) or
                                        (destination and not destination.startswith('/'))):
            fail('INVALID_REQUEST', 'destination is a JSON pointer within the selected document', '$.destination')
        self.member, self.text, self.destination = member, text, destination
        self.site = pointer(destination, '$expr') if destination is not None else ''
        self.location = member.location(destination or '')
        self.marker = {'$expr': text}
        self.checked = None
        self.fault = None
        try:
            self.checked = member.scope.check(text, self.site)
            self.profile = expressions.Profile(self.checked.dependencies)
            self.place()
        except expr.ExprFault as fault:
            self.fault = located(fault, self.location)
        except SchemaxisError as error:
            self.fault = fault_of(error)

    def place(self):
        """Check the expression against what its destination declares and accepts."""
        if self.destination is None:
            return
        kind, specification, label = destination_of(self.member, self.destination)
        route = route_of(self.member.document)
        if (kind == expressions.OPTION and route is not None and not route.get('graph')
                and self.member.scope.kind != 'workflow'
                and not self.profile.pending and not expressions.study_evaluable(self.profile)):
            kind, label = expressions.STATIC, 'a document of this adaptor, whose values are fixed before it runs'
        expressions.misuse(self.member.scope, self.marker, self.destination, kind, self.location, label)
        expected = expressions.declared_type(specification) if isinstance(specification, dict) else None
        if expected in TYPED and self.checked.type in TYPED and self.checked.type != expected:
            raise SchemaxisError(Fault(
                'EXPR_TYPE', f'{label} takes {expected}; `{self.text}` is {self.checked.type}', self.location,
                'input', observed={'expression': self.text, 'expected': [expected], 'actual': self.checked.type}))

    def describe(self, record):
        if self.checked is not None:
            record.update(type=self.checked.type, phase=expr.PHASES[self.profile.phase],
                          dependsOn=depends_on(self.profile))
        return record

    def value(self):
        scope, visit = self.member.scope, self.visit
        return scope.evaluate(self.text, visit.context(self.member, self.location), self.site)

    def record(self, visit):
        self.visit = visit
        record = self.describe({'expression': self.text})
        if self.member.operation is not None:
            record['operation'] = self.member.operation
        if self.fault is not None:
            return faulted(record, self.fault)
        return resolve(record, self.checked.type, self.profile, visit, False, self.value)


def descend(specification, parts):
    """Declared shape of a value inside an option, following its pointer."""
    for part in parts:
        if not isinstance(specification, dict):
            return None
        if part.isdigit() and isinstance(specification.get('items'), dict):
            specification = specification['items']
        elif part in specification.get('properties', {}):
            specification = specification['properties'][part]
        else:
            return None
    return specification


def destination_of(member, destination):
    """Kind of destination, its declared shape and how to name it in a fault."""
    parts = [part.replace('~1', '/').replace('~0', '~') for part in destination.split('/')[1:]]
    if not parts:
        return expressions.OPTION, None, 'this document'
    head = parts[0]
    if expressions.ANALYTIC in parts[:-1]:
        inside = parts.index(expressions.ANALYTIC)
        specification = authored_value(member.authored, parts[:inside + 1])
        linear = not isinstance(specification, dict) or specification.get('type', 'linear') == 'linear'
        if not (linear and parts[inside + 1] in ('start', 'end')):
            return expressions.STATIC, None, f'`{destination}`, which is fixed when the document is planned'
    if head in SECTIONS:
        return expressions.ENTRY, None, 'entry ' + '.'.join(parts[:2])
    if head in ('sweeps', 'times', 'maxStates', 'maxPublications'):
        return expressions.STATIC, None, f'`{destination}`, which is fixed when the document is planned'
    if head == 'scenes':
        return expressions.SCENE, None, f'scene value `{destination}`'
    nodes = member.document.get('nodes')
    if head == 'nodes' and len(parts) >= 4 and parts[1].isdigit() and parts[2] == 'options' \
            and isinstance(nodes, list) and int(parts[1]) < len(nodes) and isinstance(nodes[int(parts[1])], dict):
        node = nodes[int(parts[1])]
        declarations = member.scope.adaptor.declarations or {}
        option = declarations.get(node.get('filter'), {}).get('options', {}).get(parts[3])
        name = f'{node.get("id", parts[1])}.{parts[3]}'
        if isinstance(option, dict):
            kind = expressions.CONSTRUCTOR if option.get('constructor') else expressions.OPTION
            label = ('constructor option ' if option.get('constructor') else 'option ') + name
            return kind, descend(option.get('value'), parts[4:]), label
        return expressions.OPTION, None, 'option ' + name
    return expressions.OPTION, None, f'`{destination}`'


def authored_value(value, parts):
    """Value at a pointer of an authored document, or None when the draft does not hold it."""
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def axes_of(member):
    """Axes of a member, fastest first, and the number of visits they give.

    Declared axes come first as authored. With a sweep in the document, generated
    axes follow in the order they are first used, as the visits step through them.
    """
    scope, declared, used = member.scope, [], []
    for name, values in scope.axes.items():
        declared.append({'id': name, 'kind': 'analytic' if name in member.analytic else 'declared',
                         'count': len(values) if isinstance(values, list) else None})
    for key, value in member.document.items():
        if key in SECTIONS or key in ('sweeps', expressions.CARRIED):
            continue
        try:
            uses = scope.axis_uses(value, pointer('', key))
        except (expr.ExprFault, SchemaxisError):
            continue
        used.extend(axis for axis in uses if axis not in used)
    swept = []
    for axis in used:
        generated = scope.sweeps.get(axis)
        if generated is not None and axis not in scope.axes:
            item = {'id': axis, 'kind': generated['kind'], 'count': generated['count']}
            if generated['sync']:
                item['sync'] = generated['sync']
            swept.append(item)
    if swept:
        authored = [item for item in declared if item['kind'] == 'declared']
        compiled = {item['id']: item for item in declared if item['kind'] == 'analytic'}
        late = {item['id']: item for item in swept}
        ordered = [compiled.get(axis, late.get(axis)) for axis in used if axis in compiled or axis in late]
        result = authored + ordered + [item for item in compiled.values() if item not in ordered]
    else:
        result = declared
    states = math.prod(item['count'] or 1 for item in result if item['id'] in used) * time_count(member.document)
    if member.operation is not None:
        result = [{**item, 'operation': member.operation} for item in result]
    return result, states


def time_count(document):
    times = document.get('times')
    return len(times) if isinstance(times, list) and times else 1


def functions():
    """Every function an expression may call, for completion."""
    from .expr.functions import BUILTINS, CASTS, CONDITIONAL
    from .functions import FUNCTIONS
    result = [{'name': name, 'kind': 'builtin',
               'parameters': [signature.describe() for signature in builtin.signatures],
               'result': sorted({signature.result for signature in builtin.signatures}), 'method': builtin.method}
              for name, builtin in BUILTINS.items()]
    result.extend({'name': name, 'kind': 'builtin', 'parameters': [['value']], 'result': [name], 'method': False}
                  for name in CASTS)
    result.append({'name': CONDITIONAL, 'kind': 'builtin', 'parameters': [['boolean', 'value', 'value']],
                   'result': ['value'], 'method': False})
    result.append({'name': 'extents', 'kind': 'builtin', 'parameters': [['node'], ['node', 'port']],
                   'result': [BOX], 'method': False})
    result.append({'name': 'sweep', 'kind': 'builtin', 'method': False, 'result': [SCALAR, VECTOR],
                   'parameters': [['value', 'value', 'count'], ['value', 'value', 'count', 'sync']]})
    scope = Scope({})
    result.extend({'name': name, 'kind': 'catalogue', 'parameters': copy.deepcopy(FUNCTIONS.entries[name][0]),
                   'result': copy.deepcopy(FUNCTIONS.entries[name][1])}
                  for name in sorted(FUNCTIONS.entries) if scope.function(name) is not None)
    return sorted(result, key=by_name)


def by_name(item):
    return item['name']


def spatial_check(request):
    draft = Draft(request)
    checked = Expression(draft.selected, request.get('expression'), request.get('destination'))
    result = checked.describe({'ok': checked.fault is None})
    if checked.fault is not None:
        result['fault'] = checked.fault
    return draft.response(**result)


def records(draft, visit, identities=None, explain=False):
    result = []
    if identities is None:
        for member in draft.listed():
            for section, key in member.entries():
                record = entry_record(draft, member, section, key, visit, explain)
                if record is not None:
                    result.append(record)
        return result
    if not isinstance(identities, list):
        fail('INVALID_REQUEST', 'entries is a list of entry identities', '$.entries')
    for identity in identities:
        member = draft.find(identity)
        if member is None:
            result.append(faulted({'entry': copy.deepcopy(identity)}, {
                'code': 'UNKNOWN_ENTRY', 'message': 'the input has no such entry', 'location': '$', 'phase': 'input',
                'observed': {'entry': copy.deepcopy(identity)}}))
            continue
        result.append(entry_record(draft, member, identity['section'], identity['key'], visit, explain, True))
    return result


def spatial_list(request, explain=False):
    draft = Draft(request)
    visit = Visit(draft, False)
    entries = records(draft, visit, None, explain)
    axes, states = [], 1
    for member in draft.listed():
        found, count = axes_of(member)
        axes.extend(found)
        if member is draft.selected:
            states = count
    return draft.response(entries=entries, sweeps=axes, states=states, functions=functions())


def spatial_eval(request):
    draft = Draft(request)
    visit = Visit(draft, True)
    if 'expression' in request:
        checked = Expression(draft.selected, request.get('expression'), request.get('destination'))
        return draft.response(records=[checked.record(visit)])
    return draft.response(records=records(draft, visit, request.get('entries')))


def run(action, request, **native):
    """Dispatch one host action by name."""
    if action == 'spatial_rename':
        from .spatial_rename import rename
        return rename(request)
    if action == 'spatial_check':
        return spatial_check(request)
    if action == 'spatial_list':
        return spatial_list(request)
    if action == 'spatial_eval':
        return spatial_eval(request)
    if action == 'spatial_load':
        from .spatial_load import spatial_load
        return spatial_load(request, **native)
    fail('UNKNOWN_ACTION', 'choose one of the spatial actions', '$.action', available=list(ACTIONS))


def named_entries(names):
    """Entry identities from the command line's [workflow:]SECTION.KEY spellings."""
    result = []
    for name in names or []:
        scope, _, rest = name.rpartition(':') if name.startswith('workflow:') else ('document', '', name)
        section, _, key = rest.partition('.')
        if section not in SECTIONS or not key:
            fail('INVALID_REQUEST', 'name an entry as SECTION.KEY, for example definitions.model', '--entry',
                 entry=name, sections=list(SECTIONS))
        result.append({'scope': scope or 'document', 'section': section, 'key': key})
    return result or None


def command(args, document):
    """The spatial command line: list, eval and explain over one authored input."""
    request = {'input': document}
    if args.operation is not None:
        request['operation'] = args.operation
    if args.spatial_action == 'rename':
        from .spatial_rename import rename
        return rename({**request, 'section': args.section, 'name': args.name, 'newName': args.new_name})['input']
    if args.spatial_action == 'list':
        result = spatial_list(request)
        if not args.functions:
            del result['functions']
        return result
    identities = named_entries(args.entry)
    if args.spatial_action == 'explain':
        draft = Draft(request)
        return draft.response(entries=[
            {key: record[key] for key in ('entry', 'operation', 'expression', 'type', 'phase', 'dependsOn',
                                          'chains', 'state', 'reason', 'fault') if key in record}
            for record in records(draft, Visit(draft, False), identities, True)])
    indices = {}
    for item in args.index:
        axis, separator, position = item.rpartition('=')
        if not separator or not position.isdigit():
            fail('INVALID_REQUEST', 'give a position as SWEEP=N', '--index', index=item)
        indices[axis] = int(position)
    request['state'] = {'timeIndex': args.time_index, 'indices': indices}
    if args.observations is not None:
        import json
        loaded = json.loads(args.observations.read_text())
        request['observations'] = loaded.get('observations', loaded) if isinstance(loaded, dict) else loaded
    if args.expression is not None:
        request['expression'] = args.expression
        if args.destination is not None:
            request['destination'] = args.destination
    elif identities is not None:
        request['entries'] = identities
    return spatial_eval(request)
