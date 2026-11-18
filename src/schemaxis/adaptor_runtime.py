# Copyright (C) 2026 David L. F. Gaden.
"""Common authored inputs and stateful execution around native black boxes.

Native graph routes retain their specialised incremental engine. Other routes use
verified isolated visits through the same finite study contract. No app identities,
reflection or native handles occur in this module.
"""
import copy
import json
import math
from pathlib import Path
import re
import time

from .analytics import values as analytic_values
from .artifacts import atomic_json
from .documents import resolve_document
from .errors import fail, keys
from .storage import digest, encoded, prepare_run_directory

PROTOCOL = 'schemaxis.adaptor-execution/1'
META = ('dimensions', 'definitions', 'settings')
OPERATION = re.compile(r'(/operations/[0-9]+/document)(/.*)?')
STEPPED = '%%studyGroup%%'


def walk(value, path=''):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from walk(child, path + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, path + '/' + str(index))


def output_reference(value):
    return isinstance(value, dict) and '$value' in value and 'path' in value


def pending(value):
    return any(output_reference(v) for _, v in walk(value))


def select(value, pointer, location='$'):
    if not isinstance(pointer, str) or (pointer and not pointer.startswith('/')):
        fail('INVALID_SELECTION', 'use an RFC 6901 pointer', location)
    for part in pointer[1:].split('/') if pointer else []:
        if re.search(r'~(?![01])', part):
            fail('INVALID_SELECTION', 'invalid pointer escape', location)
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', part) and int(part) < len(value):
            value = value[int(part)]
        else:
            fail('UNKNOWN_REFERENCE', 'selected value does not exist', location, pointer=pointer)
    return copy.deepcopy(value)


def workflow_document_pointer(value, path, sources):
    """Address a workflow $document marker without expanding authored values."""
    keys(value, ('$document', 'operation', 'scope'), path)
    pointer = value['$document']
    if not isinstance(pointer, str):
        fail('INVALID_DOCUMENT_REFERENCE', 'document reference needs a pointer', path)
    if 'operation' in value:
        if 'scope' in value or not isinstance(value['operation'], str) or value['operation'] not in sources or not pointer.startswith('/'):
            fail('UNKNOWN_DOCUMENT_REFERENCE', 'use a known operation and absolute document pointer', path)
        return sources[value['operation']] + pointer
    if value.get('scope') == 'workflow':
        return pointer
    if 'scope' in value:
        fail('INVALID_DOCUMENT_REFERENCE', 'scope must be workflow', path)
    if pointer.startswith('/'):
        match = re.match(r'^(/operations/[0-9]+/document)(?:/|$)', path)
        return (match.group(1) if match else '') + pointer
    return None


def workflow_inputs(document, *, evaluate_analytics=None, defer_unfilled=False, axes=None):
    """Resolve document references at their definition site, across local scopes.

    Result references stay deferred until their producer has been verified.
    A workflow-wide study supplies evaluate_analytics to bind each source once.
    """
    operations = document.get('operations', [])
    sources = {op['id']: '/operations/'+str(i)+'/document'
               for i, op in enumerate(operations) if isinstance(op, dict) and isinstance(op.get('id'), str)} if isinstance(operations, list) else {}

    def marker(value, path, visit):
        if output_reference(value):
            keys(value, ('$value', 'path', 'visit', 'artifact'), path)
            if not isinstance(value['$value'], str) or not isinstance(value['path'], str):
                fail('INVALID_REFERENCE', 'value reference needs an operation and pointer', path)
            if 'visit' in value and (type(value['visit']) is not int or value['visit'] < 0):
                fail('INVALID_SELECTION', 'visit must be nonnegative', path)
            return True, copy.deepcopy(value)
        if '$document' in value:
            target = workflow_document_pointer(value, path, sources)
            if target is None:
                return False, None
            return True, visit(select(document, target, path), target)
        if '$analytic' in value or ('$sweep' in value and evaluate_analytics):
            if evaluate_analytics:
                return evaluate_analytics(value, path, visit)
            return True, {'$analytic': visit(value['$analytic'], path+'/$analytic')}
        return False, None

    def deferred(value):
        return pending(value) or any('$analytic' in item or defer_unfilled and '$fill' in item
                                     for _, item in walk(value))

    return resolve_document(document, marker_resolver=marker, defer=deferred, axes=axes)[0]


def member_group(prefix, axis):
    """Study group of an analytic that an expression reads by name: the group its own marker steps."""
    if axis.startswith('sweep:') and axis.endswith('/$analytic#0'):
        return 'member:' + prefix + axis[len('sweep:'):-len('/$analytic#0')]
    return None


def unsettled(document):
    """Whether a resolved document still holds a string expression or an analytic for its graph to evaluate."""
    from .expressions import has_expressions
    return has_expressions(document) or any('$analytic' in item for _, item in walk(document))


def planned(document):
    """Whether a document is one visit of a study, which has already chosen where it stands on every sweep."""
    from .expressions import POSITIONS, VISITS
    return VISITS in document or POSITIONS in document


def requires_common(document, route):
    if not route.get('graph'):
        return True
    if planned(document):
        return False
    # Keep the established native graph state/update semantics. Use the common
    # study for newly supported analytic scopes or expressions over analytics.
    analytic = any('$analytic' in v or '$sweep' in v for _, v in walk(document))
    if not analytic:
        return False
    for path, value in walk(document):
        if ('$analytic' in value or '$sweep' in value) and path.startswith(tuple('/'+k+'/' for k in META)):
            return True
        if '$sweep' in value and not path.startswith('/nodes/'):
            # Existing presentation axes remain governed by the graph's active
            # geometry-axis checks; camera-only sampling has its own loops.
            continue
        if '$analytic' in value or '$sweep' in value:
            if re.fullmatch(r'/scenes/[0-9]+/(?:appearances|images/[0-9]+/cameras)', path):
                continue
            match = re.match(r'^/nodes/([0-9]+)/options/([^/]+)', path)
            if match:
                from .adaptors import registry
                node = document['nodes'][int(match.group(1))]
                declaration = registry.declarations(registry.resolve(document, legacy=True)[0]).get(node.get('filter'), {})
                if declaration.get('options', {}).get(match.group(2), {}).get('constructor'):
                    return True
            elif '/$create/' not in path:
                return True
    try:
        resolve_document(document)
    except Exception as error:
        from .core.faults import SchemaxisError
        if not isinstance(error, SchemaxisError): raise
        return True
    return False


class InputProgram:
    """Finite synchronized inputs; expressions are re-evaluated on every visit.

    The study owns every step. A declared sweep, an analytic and a sweep written
    in an expression are each a group of the study, whether the study can
    compute the value or a graph must wait for its data to do so. A graph is
    told where the study stands and steps nothing but time, so everything that
    shares a sync name advances together across the operations of a workflow.
    """
    def __init__(self, document, route=None, *, workflow=False):
        if not isinstance(document, dict): fail('INVALID_DOCUMENT', 'document must be an object')
        self.authored = copy.deepcopy(document)
        self.route = route or {}
        self.workflow = workflow
        self.limit = document.get('maxStates', 10000)
        if type(self.limit) is not int or not 1 <= self.limit <= 10000:
            fail('INVALID_LIMIT', 'maxStates must be between 1 and 10000')
        self.groups = {}
        self.bindings = {}
        self.positions = {}
        self.frozen = False
        authored_features = any(key in document for key in (*META, 'sweeps', 'maxStates')) or any(
            any(key in value for key in ('$document', '$expr', '$value', '$analytic', '$sweep')) for _, value in walk(document))
        self.common = workflow or (authored_features and requires_common(document, self.route))
        self.explicit = {}
        self.axis_scopes = {}
        self.sweep_groups = {}
        self.scopes = {}
        self.late = set()
        if self.common:
            staged, _ = resolve_document(document,
                marker_resolver=lambda value, path, visit: (True, copy.deepcopy(value)) if output_reference(value) else (False, None),
                defer=lambda value: pending(value) or any('$analytic' in item for _, item in walk(value))) if not workflow else (workflow_inputs(document), [])
            scopes = [('', staged)]
            if workflow:
                scopes.extend(('/operations/'+str(i)+'/document', op['document'])
                              for i, op in enumerate(staged.get('operations', []))
                              if isinstance(op, dict) and isinstance(op.get('document'), dict))
            for scope, owner in scopes:
                self._axes(owner, scope)
            self._sweeps(scopes)
            self.first = self._resolve()
            self._first_use(scopes)
            self.frozen = True
        else:
            self.first = copy.deepcopy(document)
        self.count = math.prod(self.groups.values())
        if self.count > self.limit:
            fail('EXPANSION_TOO_LARGE', 'analytic Cartesian product exceeds maxStates', states=self.count,
                 limit=self.limit)

    def _axes(self, owner, scope):
        raw_axes = owner.get('sweeps', [])
        if not isinstance(raw_axes, list): fail('INVALID_SWEEP', 'sweeps must be a list', scope)
        self.axis_scopes[scope] = {}
        for index, raw in enumerate(raw_axes):
            keys(raw, ('name', 'values', 'series'), '$.sweeps')
            name = raw.get('name')
            if not isinstance(name, str) or not name or name in self.axis_scopes[scope]:
                fail('INVALID_SWEEP', 'sweep names must be distinct nonempty strings')
            if ('values' in raw) == ('series' in raw):
                fail('INVALID_SWEEP', 'choose values or series')
            if 'series' in raw:
                from .core.series import resolve_series
                items = list(resolve_series(raw['series'], limit=self.limit).positions)
            else:
                items = raw['values']
            if not isinstance(items, list) or not items or len(items) > self.limit:
                fail('EMPTY_SWEEP', 'a sweep needs a bounded nonempty values list', name)
            group = scope+'/declared:'+name
            self.axis_scopes[scope][name] = group
            self.explicit[group] = (copy.deepcopy(items), scope+'/sweeps/'+str(index)+'/values')
            self.groups[group] = len(items)

    def _sweeps(self, scopes):
        """Every sweep an expression uses is a group of the study, whether or not the study can compute its ends."""
        from . import expressions
        envelope = None
        for prefix, owner in scopes:
            top = self.workflow and not prefix
            binding = expressions.Scope(owner, workflow=envelope, kind='workflow' if top else 'document',
                                        adaptor=expressions.Adaptor(expressions.extents_capability(owner)))
            if top:
                binding.workflow = envelope = binding
            self.scopes[prefix] = binding
            if not top and self._route(prefix).get('graph'):
                self._refuse_misplaced(prefix, owner, binding)
            self.sweep_groups[prefix] = {}
            skipped = (*META, 'sweeps', 'operations') if top else (*META, 'sweeps', expressions.CARRIED)
            for key, value in owner.items():
                if key in skipped:
                    continue
                for path, marker in expressions.expression_markers(value, expressions.pointer('', key)):
                    try:
                        profile = binding.profile(marker, path)
                        uses = binding.axis_uses(marker, path)
                    except expressions.expr.ExprFault as fault:
                        expressions.raise_fault(fault, '$' + prefix + path, 'input')
                    for axis in uses:
                        if axis in profile.sweeps:
                            self._sweep_group(prefix, axis, binding.sweeps[axis], path)

    def _route(self, prefix):
        """Route of the document at a prefix: the document itself, or one operation of a workflow."""
        match = re.fullmatch(r'/operations/([0-9]+)/document', prefix) if self.workflow else None
        if match is None:
            return self.route
        from .adaptors import registry
        return registry.resolve(self.authored['operations'][int(match.group(1))]['document'], legacy=True)[1]

    def _refuse_misplaced(self, prefix, owner, binding):
        """A study gives each visit its own document, so what a graph fixes at planning is checked before it.

        Without this an expression that reads an axis would reach the graph as a
        constant of each visit, in a place that accepts constants only.
        """
        from . import expressions
        from .adaptors import registry
        expressions.check_static(owner, prefix)
        nodes = owner.get('nodes')
        declarations = registry.declarations(registry.resolve(owner, legacy=True)[0])
        for index, node in enumerate(nodes if isinstance(nodes, list) else []):
            options = node.get('options') if isinstance(node, dict) else None
            declared = declarations.get(node.get('filter'), {}).get('options', {}) if isinstance(node, dict) else {}
            for key, value in options.items() if isinstance(options, dict) else []:
                if not declared.get(key, {}).get('constructor') or not expressions.has_expressions(value):
                    continue
                location = str(node.get('id', index)) + '.' + key
                try:
                    expressions.misuse(binding, value, f'/nodes/{index}/options/' + key.replace('~', '~0')
                                       .replace('/', '~1'), expressions.CONSTRUCTOR, location,
                                       'constructor option ' + location)
                except expressions.expr.ExprFault as fault:
                    expressions.raise_fault(fault, location, 'input')

    def _first_use(self, scopes):
        """With a sweep in the study, generated groups step in the order the documents first use them.

        Declared axes stay first as authored. A study without sweeps keeps its order.
        """
        from . import expressions
        if not any(self.sweep_groups.values()):
            return
        ranked = []
        for prefix, owner in scopes:
            binding = self.scopes[prefix]
            skipped = ((*META, 'sweeps', 'operations') if self.workflow and not prefix
                       else (*META, 'sweeps', expressions.CARRIED))
            for key, value in owner.items():
                if key in skipped:
                    continue
                try:
                    uses = binding.axis_uses(value, expressions.pointer('', key))
                except (expressions.expr.ExprFault, expressions.SchemaxisError):
                    continue
                for axis in uses:
                    group = self.sweep_groups[prefix].get(axis) or member_group(prefix, axis) or axis
                    if group in self.groups and group not in self.explicit and group not in ranked:
                        ranked.append(group)
        ordered = [group for group in self.groups if group in self.explicit] + ranked
        ordered.extend(group for group in self.groups if group not in ordered)
        self.groups = {group: self.groups[group] for group in ordered}

    def _sweep_group(self, prefix, axis, declared, path):
        group = 'sync:' + declared['sync'] if declared['sync'] else member_group(prefix, axis) or prefix + '/' + axis
        if self.groups.get(group, declared['count']) != declared['count']:
            fail('ANALYTIC_LENGTH_MISMATCH', 'synchronized or changing sweeps must retain equal lengths', path)
        self.groups[group] = declared['count']
        self.sweep_groups[prefix][axis] = group

    def _visit_axes(self):
        """Value of every axis of each document at the current position of the study."""
        result = {}
        for scope, names in self.axis_scopes.items():
            values = {name: self.explicit[group][0][self.positions.get(group, 0)] for name, group in names.items()}
            values.update(self._generated(scope))
            result[scope] = values
        return result

    def _generated(self, scope):
        """Position of the study on every sweep the expressions of one document use."""
        return {axis: self.positions.get(group, 0) for axis, group in self.sweep_groups.get(scope, {}).items()}

    def _split(self, path):
        """Document a path lies in, and the path within it: the document itself, or one operation of a workflow."""
        match = OPERATION.fullmatch(path) if self.workflow else None
        return (match.group(1), match.group(2) or '') if match else ('', path)

    def _member(self, spec, path, count):
        """Group an analytic steps with: its sync name, else its own."""
        sync = spec.get('sync')
        if sync is not None and (not isinstance(sync, str) or not sync):
            fail('INVALID_SYNC', 'sync must be a nonempty string', path)
        group = 'sync:'+sync if sync else 'member:'+path
        if self.frozen and (path not in self.bindings or self.bindings[path] != group):
            fail('DYNAMIC_ANALYTIC_STRUCTURE', 'analytic bindings must remain fixed across a finite study', path)
        if group in self.groups and self.groups[group] != count:
            fail('ANALYTIC_LENGTH_MISMATCH', 'synchronized or changing sweeps must retain equal lengths', path)
        self.groups[group] = count
        self.bindings[path] = group
        return group

    def _count(self, spec, prefix, path):
        """Count of an analytic a graph evaluates, which is fixed when the study is planned."""
        from . import expressions
        count = spec.get('count')
        if expressions.is_expression(count) and prefix in self.scopes:
            count = self.scopes[prefix].evaluate(count['$expr'], expressions.State(location='$'+path+'/$analytic/count'))
        if type(count) is not int or not 1 <= count <= self.limit:
            fail('INVALID_ANALYTIC_COUNT', 'count must be positive and within the state limit', path)
        return count

    def _marker(self, value, path, visit):
        if output_reference(value):
            return True, copy.deepcopy(value)
        if '$sweep' in value:
            keys(value, ('$sweep', 'path'), path)
            axis = value['$sweep']
            match = re.match(r'^(/operations/[0-9]+/document)(?:/|$)', path) if self.workflow else None
            scope = match.group(1) if match else ''
            if not isinstance(axis, str) or axis not in self.axis_scopes.get(scope, {}):
                fail('UNKNOWN_SWEEP', 'sweep is not declared', path)
            group = self.axis_scopes[scope][axis]
            items, source = self.explicit[group]
            index = self.positions.get(group, 0)
            result = items[index]
            source += '/'+str(index)
            parts = value.get('path', [])
            if not isinstance(parts, list): fail('INVALID_SELECTION', 'sweep path needs a list', path)
            for part in parts:
                if isinstance(result, dict) and isinstance(part, str) and part in result: result = result[part]
                elif isinstance(result, list) and type(part) is int and 0 <= part < len(result): result = result[part]
                else: fail('UNKNOWN_REFERENCE', 'sweep member is absent', path)
                source += '/'+str(part).replace('~', '~0').replace('/', '~1')
            return True, visit(result, source)
        if '$analytic' not in value:
            return False, None
        keys(value, ('$analytic',), path)
        spec = visit(value['$analytic'], path+'/$analytic')
        if self.workflow and pending(spec):
            # A producer-derived sequence belongs to the consumer's later
            # execution boundary. Its bounds cannot be invented during planning.
            return True, {'$analytic': spec}
        prefix, member_path = self._split(path)
        route = self._route(prefix)
        sequence = isinstance(spec, dict) and (spec.get('type') == 'orbit' or (route.get('graph') and re.fullmatch(
            r'/scenes/[0-9]+/(?:appearances|images/[0-9]+/cameras)', member_path)))
        from .expressions import late_analytic
        if route.get('graph') and not sequence and late_analytic(spec, ()):
            # Ends a graph must wait for are interpolated there, at the position the study gives it.
            return True, {'$analytic': spec, STEPPED: self._member(spec, path, self._count(spec, prefix, path))}
        items = analytic_values(spec, path, self.limit)
        if sequence:
            if 'sync' in spec: fail('INVALID_SYNC', 'publication sequences have their own iteration scope', path)
            return True, items
        group = self._member(spec, path, len(items))
        return True, visit(items[self.positions.get(group, 0)], path+'/$selected')

    def _place(self, value, path, placed):
        """Take the study's mark off each analytic it left in a visit.

        An analytic whose ends are known by now becomes its value. One a graph
        must still wait for stays, and its position is recorded under the name
        that graph gives its sweep.
        """
        if isinstance(value, list):
            return [self._place(item, path+'/'+str(index), placed) for index, item in enumerate(value)]
        if not isinstance(value, dict):
            return value
        if STEPPED not in value:
            return {key: self._place(item, path+'/'+key.replace('~', '~0').replace('/', '~1'), placed)
                    for key, item in value.items()}
        from .expressions import late_analytic
        spec, group = value['$analytic'], value[STEPPED]
        position = self.positions.get(group, 0)
        if not late_analytic(spec, ()):
            return analytic_values(spec, path, self.limit)[position]
        prefix, site = self._split(path)
        axis = group if group.startswith('sync:') else 'sweep:'+site+'/$analytic#0'
        placed.setdefault(prefix, {})[axis] = position
        return {'$analytic': spec}

    def _hand(self, document, prefix, placed):
        """Leave one document of a visit as its adaptor takes it.

        A graph that still evaluates something at its own visits keeps its named
        sections and is told where the study stands: the chosen value of each
        declared sweep under its name, and its position on every other sweep.
        That record also marks the document as planned. Any other document
        keeps values only.
        """
        from .expressions import CARRIED, POSITIONS, refuse_late
        route = self._route(prefix)
        if not (route.get('graph') and unsettled(document)):
            if not route.get('graph'):
                refuse_late(document, prefix)
            for key in (*META, 'sweeps', 'maxStates', CARRIED):
                document.pop(key, None)
            return
        self.late.add(prefix)
        document.pop('sweeps', None)
        names = self.axis_scopes.get(prefix, {})
        if names:
            document['sweeps'] = [{'name': name, 'values': [copy.deepcopy(
                self.explicit[group][0][self.positions.get(group, 0)])]} for name, group in names.items()]
        document[POSITIONS] = {**self._generated(prefix), **placed.get(prefix, {})}
        if 'maxStates' in self.authored:
            # The times a graph steps at each visit share the study's limit with the visits of the study.
            document.setdefault('maxStates', self.limit)

    def _resolve(self):
        from .expressions import CARRIED
        if self.workflow:
            result = workflow_inputs(self.authored, evaluate_analytics=self._marker, axes=self._visit_axes())
        else:
            result, _ = resolve_document(self.authored, marker_resolver=self._marker, defer=pending,
                                         axes=self._visit_axes())
        placed = {}
        result = self._place(result, '', placed)
        self.late = set()
        if not self.workflow:
            self._hand(result, '', placed)
            return result
        for index, operation in enumerate(result.get('operations', [])):
            if isinstance(operation, dict) and isinstance(operation.get('document'), dict):
                self._hand(operation['document'], '/operations/'+str(index)+'/document', placed)
        # Metadata is authoring context, not a native API argument. An operation that waits for its
        # own data still reads the envelope's entries, which by now are their values at this visit.
        for key in ('sweeps', 'maxStates', CARRIED) if self.late else (*META, 'sweeps', 'maxStates', CARRIED):
            result.pop(key, None)
        for key in META:
            if isinstance(result.get(key), dict):
                result[key] = {name: entry for name, entry in result[key].items()
                               if not any('$analytic' in item for _, item in walk(entry))}
        return result

    def _document(self, visit, prefix):
        """One document of a visit: the visit itself, or the document of one operation of a workflow."""
        return visit['operations'][int(prefix.split('/')[2])]['document'] if prefix else visit

    def visits(self):
        if not self.common:
            yield {'index': 0, 'indices': {}, 'document': copy.deepcopy(self.first)}
            return
        from .expressions import VISITS
        total_bytes = 0
        for index in range(self.count):
            remainder = index
            self.positions = {}
            for name, length in self.groups.items():
                self.positions[name] = remainder % length
                remainder //= length
            document = self._resolve()
            if self.count > 1:
                # The times a graph steps at each visit share the authored limit with the visits of the study.
                for prefix in self.late:
                    self._document(document, prefix)[VISITS] = self.count
            total_bytes += len(encoded(document))
            if total_bytes > 64*1024*1024:
                fail('EXPANSION_TOO_LARGE', 'expanded documents exceed 64 MiB')
            yield {'index': index, 'indices': dict(self.positions), 'document': document}


def plan(document, route, native_plan):
    program = InputProgram(document, route)
    prepared = []
    for visit in program.visits():
        if pending(visit['document']):
            fail('VALUE_INSPECTION_REQUIRED', 'producer values must be verified before consumer planning')
        prepared.append({**visit, 'plan': native_plan(visit['document'])})
    if not program.groups:
        return prepared[0]['plan']
    if 'planIndex' in route:
        for item in prepared:
            if isinstance(item['plan'], tuple): item['plan'] = item['plan'][route['planIndex']]
    return {'version': 'schemaxis.study.plan/1', 'states': program.count,
            'bindings': program.bindings, 'visits': prepared}


class AdaptorSession:
    """A logical live black box with atomic, independently verified transitions.

    The default backend uses isolated native executions. Native graph executors
    continue to own persistent objects within their own visits. A failed transition
    poisons this session; completed evidence remains available for inspection.
    """
    def __init__(self, directory, native_run, native_verify, *, timeout, options):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            fail('INVALID_TIMEOUT', 'timeout must be positive and finite')
        self.directory = Path(directory)
        self.run = native_run
        self.verify = native_verify
        self.deadline = time.monotonic()+timeout
        self.options = options
        self.closed = False
        self.failed = False
        self.previous = None

    def apply(self, visit):
        if self.closed or self.failed:
            fail('CLOSED_SESSION', 'open a fresh session after closure or a failed transition')
        target = self.directory / ('state-'+str(visit['index']).zfill(5))
        try:
            from .dispatch import cancellation_requested
            if cancellation_requested(): fail('RUNNER_CANCELLED', 'study cancelled between visits')
            remaining = self.deadline-time.monotonic()
            if remaining <= 0: fail('RUNNER_TIMED_OUT', 'study exhausted its total timeout')
            self.run(visit['document'], target, timeout=remaining, **self.options)
            from .schema_snapshots import capture_run
            capture_run(target, visit['document'])
            if time.monotonic() > self.deadline: fail('RUNNER_TIMED_OUT', 'study exhausted its total timeout')
            self.verify(target, visit['document'])
            from .publication_metadata import finalise, verify as verify_metadata
            finalise(target)
            verify_metadata(target)
            receipt = json.loads((target/'verification.json').read_text())
            record = {**visit, 'directory': target.name,
                      'inputDigest': digest(visit['document']), 'artifacts': receipt['artifacts'],
                      'changed': self.previous != visit['document']}
            self.previous = copy.deepcopy(visit['document'])
            return record
        except Exception as error:
            self.failed = True
            _mark_verification_failed(target, error)
            raise

    def close(self):
        self.closed = True


def _mark_verification_failed(directory, error, key='verificationFault'):
    """Retain native evidence but invalidate a run whose final checks failed."""
    path = Path(directory)/'result.json'
    if not path.is_file():
        return
    try:
        status = json.loads(path.read_text())
        if not isinstance(status, dict):
            status = {}
    except (ValueError, OSError):
        status = {}
    status.update(status='failed', verified=False, **{key: str(error)})
    from .storage import atomic
    atomic(path, encoded(status))


def execute(document, directory, route, native_run, native_verify, native_plan, *, timeout=300,
            workflow=False, resume=False, **options):
    from .configuration import location_context
    from .artifact_names import run_scope
    from .core.faults import SchemaxisError
    from .dispatch import execution_deadline
    locations = {}
    if not workflow:
        from .adaptors import registry
        try:
            provider, _ = registry.resolve(document, legacy=True)
        except SchemaxisError:
            # Location scoping is derived, not validation: an unregistered
            # direct entrypoint keeps its existing document checks below.
            provider = None
        if 'roots' in options:
            locations['roots'] = options['roots']
        elif provider is not None:
            locations[provider] = options.get('executable')
        locations.update({provider: options.get(option)
                          for option, provider in route.get('runOptions', {}).items()})
    # An invalid budget is reported by the adaptor's own validation, preserving
    # its established fault code; only a valid budget opens a deadline scope.
    valid = type(timeout) in (int, float) and math.isfinite(timeout) and timeout > 0
    with location_context(locations), run_scope(directory):
        if not valid:
            return _execute(document, directory, route, native_run, native_verify, native_plan,
                            timeout=timeout, workflow=workflow, resume=resume, **options)
        with execution_deadline(timeout):
            return _execute(document, directory, route, native_run, native_verify, native_plan,
                            timeout=timeout, workflow=workflow, resume=resume, **options)


def _execute(document, directory, route, native_run, native_verify, native_plan, *, timeout,
             workflow, resume, **options):
    program = InputProgram(document, route, workflow=workflow)
    visits = list(program.visits())
    # Validate every statically known state before starting the application.
    for visit in visits:
        try:
            native_plan(visit['document'])
        except Exception as error:
            # A source-dependent time selection is resolved by the native run
            # after inspecting that source; the run validates it before launch.
            from .core.faults import SchemaxisError
            if not isinstance(error, SchemaxisError) or error.fault.code != 'TIME_INSPECTION_REQUIRED':
                raise
    if not program.groups and visits[0]['document'] == document:
        result = native_run(document, directory, timeout=timeout, **options)
        from .schema_snapshots import capture_run
        from .publication_metadata import finalise, verify as verify_metadata
        phase = 'verificationFault'
        try:
            capture_run(directory, document)
            native_verify(directory, document)
            phase = 'publicationMetadataFault'
            finalise(directory)
            verify_metadata(directory)
        except Exception as error:
            _mark_verification_failed(directory, error, phase)
            raise
        return result
    if resume:
        directory = Path(directory).absolute()
        if not is_common(directory) or json.loads((directory/'authored.json').read_text()) != document:
            fail('RESUME_MISMATCH', 'resume needs the unchanged authored study')
    else:
        directory = prepare_run_directory(directory, document)
    from .schema_snapshots import capture_run, verify_run
    if resume:
        verify_run(directory)
    else:
        capture_run(directory, document)
    # The outer study owns its aggregate receipt while child workflows retain
    # their own attempt locks. In particular, two resumes cannot publish at once.
    import fcntl
    with (directory/'.coordinator.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail('WORKFLOW_BUSY', 'another coordinator owns this output directory', str(directory))
        return _execute_visits(document, directory, route, native_run, native_verify, visits,
                               program, timeout, options, workflow)


def _execute_visits(document, directory, route, native_run, native_verify, visits,
                    program, timeout, options, workflow):
    session = AdaptorSession(directory, native_run, native_verify, timeout=timeout, options=options)
    status = {'protocol': PROTOCOL, 'status': 'incomplete', 'verified': False, 'states': []}
    atomic_json(directory/'result.json', status)
    try:
        for visit in visits:
            status['states'].append(session.apply(visit))
            atomic_json(directory/'result.json', status)
        artifacts = [a for state in status['states'] for a in state['artifacts']]
        receipt = {'protocol': PROTOCOL, 'authoredDigest': digest(document),
                   'executionMode': 'isolated-visits', 'bindings': program.bindings,
                   'states': status['states'], 'artifacts': artifacts}
        atomic_json(directory/'verification.json', receipt)
        from .publication_metadata import finalise
        finalise(directory)
        status.update(status='succeeded', verified=True, artifacts=len(artifacts))
        atomic_json(directory/'result.json', status)
        verify(directory, document, route, native_verify, workflow=workflow)
        return status
    except Exception as error:
        status.update(status='failed', verified=False, fault=str(error))
        atomic_json(directory/'result.json', status)
        raise
    finally:
        session.close()


def is_common(directory):
    path = Path(directory)/'result.json'
    if not path.is_file(): return False
    try:
        result = json.loads(path.read_text())
        return isinstance(result, dict) and result.get('protocol') == PROTOCOL
    except RecursionError:
        fail('VERIFICATION_FAILED', 'retained result JSON nesting exceeds the host reader limit', str(path))
    except (OSError, ValueError):
        return False


def verify(directory, document, route, native_verify, *, workflow=False):
    directory = Path(directory)
    from .schema_snapshots import verify_run
    verify_run(directory)
    try:
        saved = json.loads((directory/'result.json').read_text())
        receipt = json.loads((directory/'verification.json').read_text())
        if not isinstance(saved, dict) or not isinstance(receipt, dict):
            fail('VERIFICATION_FAILED', 'study evidence must be objects')
        if (saved.get('protocol') != PROTOCOL or receipt.get('protocol') != PROTOCOL
                or receipt.get('executionMode') != 'isolated-visits'):
            fail('VERIFICATION_FAILED', 'study execution contract differs')
        if saved.get('status') != 'succeeded' or saved.get('verified') is not True:
            fail('INCOMPLETE_EXECUTION', 'study is incomplete')
        if json.loads((directory/'authored.json').read_text()) != document or receipt.get('authoredDigest') != digest(document):
            fail('VERIFICATION_FAILED', 'study authored input differs')
        program = InputProgram(document, route, workflow=workflow)
        visits = list(program.visits())
        states = saved.get('states', [])
        if len(states) != len(visits) or receipt.get('states') != states or receipt.get('bindings') != program.bindings:
            fail('VERIFICATION_FAILED', 'study state membership differs')
        artifacts = []
        previous = None
        for visit, state in zip(visits, states):
            if not isinstance(state, dict): fail('VERIFICATION_FAILED', 'study state must be an object')
            target = directory/('state-'+str(visit['index']).zfill(5))
            if target.is_symlink() or state.get('directory') != target.name:
                fail('VERIFICATION_FAILED', 'study state directory differs')
            if any(state.get(k) != v for k, v in visit.items()) or state.get('inputDigest') != digest(visit['document']):
                fail('VERIFICATION_FAILED', 'study inputs or indices differ')
            if state.get('changed') != (previous != visit['document']):
                fail('VERIFICATION_FAILED', 'study transition evidence differs')
            native_verify(target, visit['document'])
            from .publication_metadata import verify as verify_metadata
            verify_metadata(target)
            child = json.loads((target/'verification.json').read_text())
            if state.get('artifacts') != child['artifacts']:
                fail('VERIFICATION_FAILED', 'study publication membership differs')
            artifacts.extend(child['artifacts'])
            previous = visit['document']
        if receipt.get('artifacts') != artifacts or saved.get('artifacts') != len(artifacts):
            fail('VERIFICATION_FAILED', 'study publications differ')
        from .publication_metadata import verify as verify_metadata
        verify_metadata(directory)
        return {'verified': True, 'states': len(states), 'artifacts': len(artifacts)}
    except (OSError, ValueError, KeyError, TypeError) as error:
        fail('VERIFICATION_FAILED', 'missing or malformed study evidence: '+str(error))


def bind(namespace):
    """Give direct adaptor entry points the same boundary as CLI and registry.

    Kernels retain their signatures and native semantics. New plugins need not
    call this helper to gain the registry contract; it also covers direct imports.
    """
    from functools import wraps
    native_plan, native_run = (namespace[key] for key in ('plan', 'run'))
    native_verify = namespace.get('verify')
    if native_verify is None:
        def native_verify(directory, *args, **kwargs):
            from .adaptors import registry
            document = json.loads((Path(directory)/'authored.json').read_text())
            return registry.route_hook(document, 'verify', required=True)(directory, *args, **kwargs)
    namespace.update(_native_plan=native_plan, _native_run=native_run, _native_verify=native_verify)

    @wraps(native_plan)
    def prepared(document, *args, **kwargs):
        if not isinstance(document, dict): return native_plan(document, *args, **kwargs)
        from .adaptors import registry
        route = registry.resolve(document, legacy=True)[1]
        return plan(document, route, lambda value: native_plan(value, *args, **kwargs))

    @wraps(native_run)
    def execute_prepared(document, directory, *args, **kwargs):
        if not isinstance(document, dict): return native_run(document, directory, *args, **kwargs)
        from .adaptors import registry
        route = registry.resolve(document, legacy=True)[1]
        from inspect import signature
        sig = signature(native_run)
        bound = sig.bind(document, directory, *args, **kwargs)
        bound.apply_defaults()
        options = dict(bound.arguments)
        for key in list(sig.parameters)[:2]: options.pop(key)
        timeout = options.pop('timeout')
        return execute(document, directory, route,
                       native_run, registry._verify_native, native_plan, timeout=timeout, **options)

    @wraps(native_verify)
    def verify_prepared(directory, *args, **kwargs):
        from .schema_snapshots import verify_run
        verify_run(directory)
        if not is_common(directory):
            result = native_verify(directory, *args, **kwargs)
            from inspect import signature
            bound = signature(native_verify).bind(directory, *args, **kwargs)
            bound.apply_defaults()
            if bound.arguments.get('require_result', True):
                from .publication_metadata import verify as verify_metadata
                verify_metadata(directory)
            return result
        from .adaptors import registry
        document = json.loads((Path(directory)/'authored.json').read_text())
        return verify(directory, document, registry.resolve(document, legacy=True)[1], registry._verify_native)

    namespace.update(plan=prepared, run=execute_prepared, verify=verify_prepared)
