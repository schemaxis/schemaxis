"""Capture and bind bounded workflow templates without launching applications.

This first contract supports scalar parameters and fixed-length numeric vectors.
It deliberately does not interpret assets, selectors, study policies or quantities
in alternative units. See docs/design/workflow-templates/template-contract.md.
"""
import copy
import math
from pathlib import Path, PurePosixPath
import re

from . import storage, workflow
from .adaptors import registry
from .errors import fail, keys


TEMPLATE_VERSION = 'schemaxis.workflow-template/1'
VALUES_VERSION = 'schemaxis.workflow-values/1'
_KINDS = ('number', 'integer', 'boolean', 'string', 'enum', 'vector')
_SCOPES = ('dimensions', 'definitions', 'settings')
_MAX_JSON_DEPTH = 64


def _json(value, location='$', *, depth=0, ancestors=None):
    """Bound nesting and reject cycles/Python-only data before recursive consumers."""
    if depth > _MAX_JSON_DEPTH:
        fail('INVALID_DOCUMENT', 'JSON nesting must not exceed 64 levels', location)
    if type(value) in (dict, list):
        ancestors = set() if ancestors is None else ancestors
        if id(value) in ancestors:
            fail('INVALID_DOCUMENT', 'JSON data must not contain reference cycles', location)
        ancestors.add(id(value))
        try:
            children = value.items() if type(value) is dict else enumerate(value)
            for key, child in children:
                if type(value) is dict and not isinstance(key, str):
                    fail('INVALID_DOCUMENT', 'JSON object keys must be strings', location)
                _json(child, location + '/' + str(key), depth=depth + 1, ancestors=ancestors)
        finally:
            ancestors.remove(id(value))
    elif type(value) is float:
        if not math.isfinite(value):
            fail('INVALID_DOCUMENT', 'values must be finite JSON data', location)
    elif value is not None and type(value) not in (str, int, bool):
        fail('INVALID_DOCUMENT', 'expected JSON data', location)


def _text(value, location):
    if not isinstance(value, str) or not value.strip():
        fail('INVALID_TEMPLATE', 'expected a nonempty string', location)


def _identity(value, location):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]*', value):
        fail('INVALID_TEMPLATE', 'identity must start with a letter and contain letters, digits, _, . or -', location)


def _pointer(value, location, *, binding=False):
    if not isinstance(value, str) or (value != '' and not value.startswith('/')):
        fail('INVALID_BINDING', 'use an RFC 6901 JSON pointer', location)
    if re.search(r'~(?![01])', value):
        fail('INVALID_BINDING', 'JSON pointer escapes must be ~0 or ~1', location)
    parts = tuple(part.replace('~1', '/').replace('~0', '~') for part in value.split('/')[1:])
    if binding and (len(parts) < 2 or parts[0] not in _SCOPES):
        fail('UNSUPPORTED_BINDING', 'bind an existing value under /dimensions, /definitions or /settings', location)
    return parts


def _member(value, part, location):
    if isinstance(value, dict) and part in value:
        return part
    if isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', part):
        # Compare digit counts before converting untrusted indices. This also
        # avoids Python's huge-integer string conversion limit leaking out.
        if len(part) <= len(str(len(value))):
            index = int(part)
            if index < len(value):
                return index
    fail('INVALID_BINDING', 'binding target is absent; repair the template target', location)


def _target(document, parts, location):
    parent = document
    for part in parts[:-1]:
        parent = parent[_member(parent, part, location)]
    key = _member(parent, parts[-1], location)
    return parent, key


def _numeric(value):
    return type(value) in (int, float) and (type(value) is int or math.isfinite(value))


def _constraints(spec, location):
    kind = spec['kind']
    constraints = spec.get('constraints', {})
    allowed = {'number': ('minimum', 'maximum'), 'integer': ('minimum', 'maximum'),
               'boolean': (), 'string': ('minLength', 'maxLength'),
               'enum': ('enum',), 'vector': ('length', 'minimum', 'maximum')}[kind]
    keys(constraints, allowed, location + '.constraints')
    for bound in ('minimum', 'maximum'):
        if bound in constraints and not _numeric(constraints[bound]):
            fail('INVALID_TEMPLATE', 'numeric limits must be finite numbers', location + '.constraints.' + bound)
    if 'minimum' in constraints and 'maximum' in constraints and constraints['minimum'] > constraints['maximum']:
        fail('INVALID_TEMPLATE', 'minimum exceeds maximum', location + '.constraints')
    for bound in ('minLength', 'maxLength', 'length'):
        if bound in constraints and (type(constraints[bound]) is not int or constraints[bound] < 0):
            fail('INVALID_TEMPLATE', 'length limits must be nonnegative integers', location + '.constraints.' + bound)
    if constraints.get('minLength', 0) > constraints.get('maxLength', float('inf')):
        fail('INVALID_TEMPLATE', 'minLength exceeds maxLength', location + '.constraints')
    if kind == 'vector' and not 1 <= constraints.get('length', 0) <= 1024:
        fail('INVALID_TEMPLATE', 'vector requires a fixed length from 1 to 1024', location + '.constraints.length')
    if kind == 'enum':
        choices = constraints.get('enum')
        if not isinstance(choices, list) or not choices:
            fail('INVALID_TEMPLATE', 'enum requires a nonempty constraints.enum list', location + '.constraints.enum')
        if any(type(v) not in (str, bool, int, float) for v in choices):
            fail('INVALID_TEMPLATE', 'enum choices must be scalar strings, booleans or numbers', location + '.constraints.enum')
        categories = {_category(v) for v in choices}
        if len(categories) != 1 or any(_equal(value, previous) for i, value in enumerate(choices) for previous in choices[:i]):
            fail('INVALID_TEMPLATE', 'enum choices must be unique and have one scalar type', location + '.constraints.enum')
    return constraints


def _category(value):
    return 'number' if type(value) in (int, float) else type(value).__name__


def _equal(left, right):
    return _category(left) == _category(right) and left == right


def _value(value, spec, location):
    kind = spec['kind']
    constraints = spec.get('constraints', {})
    valid = {'number': lambda: _numeric(value),
             'integer': lambda: type(value) is int,
             'boolean': lambda: type(value) is bool,
             'string': lambda: isinstance(value, str),
             'enum': lambda: any(_equal(value, choice) for choice in constraints['enum']),
             'vector': lambda: isinstance(value, list) and len(value) == constraints['length'] and all(_numeric(v) for v in value)}[kind]()
    if not valid:
        fail('INVALID_PARAMETER', 'supply a ' + kind + ' value in the declared units; expressions and quantity objects are unsupported', location)
    if kind in ('number', 'integer', 'vector'):
        for component in value if kind == 'vector' else [value]:
            if ('minimum' in constraints and component < constraints['minimum']) or ('maximum' in constraints and component > constraints['maximum']):
                fail('INVALID_PARAMETER', 'value is outside the declared inclusive limits', location)
    if kind == 'string' and not constraints.get('minLength', 0) <= len(value) <= constraints.get('maxLength', float('inf')):
        fail('INVALID_PARAMETER', 'string length is outside the declared limits', location)


def _validate(manifest, body, *, allow_unfilled=False):
    keys(manifest, ('version', 'id', 'revision', 'title', 'workflow', 'parameters', 'outputs', 'requirements'), '$.template')
    if manifest.get('version') != TEMPLATE_VERSION:
        fail('UNSUPPORTED_VERSION', 'expected ' + TEMPLATE_VERSION, '$.template.version')
    _identity(manifest.get('id'), '$.template.id')
    if type(manifest.get('revision')) is not int or manifest['revision'] < 1:
        fail('INVALID_TEMPLATE', 'revision must be a positive integer', '$.template.revision')
    _text(manifest.get('title'), '$.template.title')
    _relative(manifest.get('workflow'))
    parameters = manifest.get('parameters')
    keys(parameters, parameters if isinstance(parameters, dict) else (), '$.template.parameters')
    targets = []
    for identity, spec in parameters.items():
        location = '$.template.parameters.' + identity
        _identity(identity, location)
        keys(spec, ('label', 'help', 'kind', 'constraints', 'default', 'units', 'target'), location)
        _text(spec.get('label'), location + '.label')
        if 'help' in spec:
            _text(spec['help'], location + '.help')
        if spec.get('kind') not in _KINDS:
            fail('UNSUPPORTED_PARAMETER_KIND', 'supported parameter kinds: ' + ', '.join(_KINDS), location + '.kind')
        if 'units' in spec:
            _text(spec['units'], location + '.units')
            if spec['kind'] not in ('number', 'integer', 'vector'):
                fail('INVALID_TEMPLATE', 'units apply only to numeric parameters', location + '.units')
        _constraints(spec, location)
        target = spec.get('target')
        keys(target, ('scope', 'pointer'), location + '.target')
        if target.get('scope') != 'workflow':
            fail('UNSUPPORTED_BINDING', 'only workflow-scoped targets are supported', location + '.target.scope')
        parts = _pointer(target.get('pointer'), location + '.target.pointer', binding=True)
        if any(parts[:len(other)] == other or other[:len(parts)] == parts for other in targets):
            fail('OVERLAPPING_BINDINGS', 'parameter targets must not overlap', location + '.target.pointer')
        targets.append(parts)
        parent, key = _target(body, parts, location + '.target.pointer')
        from .unfilled import find_unfilled
        if not find_unfilled(parent[key]):
            _value(parent[key], spec, location + '.target')
        if 'default' in spec:
            _value(spec['default'], spec, location + '.default')
    from .unfilled import reject_unfilled
    if not allow_unfilled:
        reject_unfilled(body, allowed=[spec['target']['pointer'] for spec in parameters.values()])
    operations = workflow.validate(body, allow_unfilled=True)
    providers = sorted({registry.resolve(operation['document'], legacy=True)[0] for operation in operations})
    outputs = manifest.get('outputs')
    keys(outputs, outputs if isinstance(outputs, dict) else (), '$.template.outputs')
    operation_ids = {operation['id'] for operation in operations}
    for identity, output in outputs.items():
        location = '$.template.outputs.' + identity
        _identity(identity, location)
        keys(output, ('operation', 'artifact', 'pointer', 'kind', 'units'), location)
        if not isinstance(output.get('operation'), str) or output['operation'] not in operation_ids:
            fail('INVALID_OUTPUT_ALIAS', 'output must name an existing operation', location + '.operation')
        if type(output.get('artifact')) is not int or output['artifact'] < 0:
            fail('INVALID_OUTPUT_ALIAS', 'artifact index must be nonnegative', location + '.artifact')
        _text(output.get('kind'), location + '.kind')
        if 'pointer' in output:
            _pointer(output['pointer'], location + '.pointer')
        if 'units' in output:
            _text(output['units'], location + '.units')
    if 'requirements' in manifest:
        requirements = manifest['requirements']
        keys(requirements, ('providers', 'qualification'), '$.template.requirements')
        if 'providers' in requirements:
            declared = requirements['providers']
            if not isinstance(declared, list) or any(not isinstance(p, str) for p in declared) or sorted(declared) != providers:
                fail('INVALID_REQUIREMENTS', 'providers must match those derived from the workflow', '$.template.requirements.providers', providers=providers)
        if 'qualification' in requirements:
            _text(requirements['qualification'], '$.template.requirements.qualification')


def _relative(value):
    _text(value, '$.template.workflow')
    parts = value.split('/')
    if PurePosixPath(value).is_absolute() or any(part in ('', '.', '..') for part in parts) or '\\' in value or ':' in value or '\x00' in value:
        fail('INVALID_TEMPLATE_PATH', 'workflow must be a confined relative file path without traversal', '$.template.workflow')
    return parts


def _read(path):
    try:
        if path.is_symlink() or not path.is_file():
            fail('INVALID_TEMPLATE_PATH', 'template inputs must be regular files, not symlinks', str(path))
        from .core.documents import load_document_file, document_format
        value = load_document_file(path) if document_format(path) == 'yaml' else storage.load(path.read_text(encoding='utf-8'))
        _json(value, str(path))
        return value
    except RecursionError:
        fail('INVALID_DOCUMENT', 'JSON nesting must not exceed 64 levels', str(path))
    except (OSError, UnicodeError) as error:
        fail('INVALID_TEMPLATE_PATH', 'cannot read template input: ' + str(error), str(path))


def _manifest_path(path):
    """Inspect caller spelling before normalization can erase a symlink/.. alias."""
    try:
        path = Path(path).expanduser()
        if '..' in path.parts or '\x00' in str(path):
            fail('INVALID_TEMPLATE_PATH', 'manifest path must not contain parent traversal or NUL', str(path))
        if not path.is_absolute():
            path = Path.cwd() / path
        for component in (*reversed(path.parents), path):
            if component.is_symlink():
                fail('INVALID_TEMPLATE_PATH', 'manifest path must not pass through a symlink', str(component))
        return path
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        fail('INVALID_TEMPLATE_PATH', 'cannot locate template input: ' + str(error))


def load_template(path):
    """Read a strict manifest and its confined workflow into a captured bundle."""
    path = _manifest_path(path)
    manifest = _read(path)
    keys(manifest, ('version', 'id', 'revision', 'title', 'workflow', 'parameters', 'outputs', 'requirements'), '$.template')
    parts = _relative(manifest.get('workflow'))
    body_path = path.parent
    for part in parts:
        body_path /= part
        if body_path.is_symlink():
            fail('INVALID_TEMPLATE_PATH', 'workflow path must not pass through a symlink', str(body_path))
    body = _read(body_path)
    _validate(manifest, body)
    captured = {'template': manifest, 'workflow': body}
    return {**captured, 'digest': storage.digest(captured)}


def _run_options(run, location='$.case.run'):
    """Case-level run preferences; they never enter the template digest."""
    keys(run, ('outputDirectory', 'workers', 'naming'), location)
    if 'outputDirectory' in run:
        directory = run['outputDirectory']
        if not isinstance(directory, str) or not directory.strip() or '\x00' in directory or len(directory) > 4096:
            fail('INVALID_RUN_OPTIONS', 'outputDirectory must be a nonempty path string', location + '.outputDirectory')
    if 'workers' in run and (type(run['workers']) is not int or not 1 <= run['workers'] <= 64):
        fail('INVALID_RUN_OPTIONS', 'workers must be an integer from 1 to 64', location + '.workers')
    if 'naming' in run:
        from . import output_naming
        naming = run['naming']
        keys(naming, ('pattern', 'indexWidth'), location + '.naming')
        if 'pattern' in naming:
            output_naming.validate_pattern(naming['pattern'], location + '.naming.pattern')
        if 'indexWidth' in naming:
            output_naming.validate_width(naming['indexWidth'], location + '.naming.indexWidth')
    return copy.deepcopy(run)


def bind_values(bundle, values):
    """Atomically produce an ordinary workflow and source map from captured JSON.

    This validates the effective host plan. Producer-dependent native contracts
    stay deferred until execution verifies their actual artifacts and values.
    Neither argument is mutated, including when validation fails.
    """
    _json(bundle, '$.bundle')
    _json(values, '$.case')
    from .unfilled import reject_unfilled
    reject_unfilled(values)
    bundle, values = copy.deepcopy(bundle), copy.deepcopy(values)
    keys(bundle, ('template', 'workflow', 'digest'), '$.bundle')
    manifest, body = bundle.get('template'), bundle.get('workflow')
    _validate(manifest, body)
    actual_digest = storage.digest({'template': manifest, 'workflow': body})
    if bundle.get('digest') != actual_digest:
        fail('STALE_TEMPLATE', 'bundle changed after capture; reload the template', '$.bundle.digest')
    keys(values, ('version', 'template', 'values', 'run'), '$.case')
    if values.get('version') != VALUES_VERSION:
        fail('UNSUPPORTED_VERSION', 'expected ' + VALUES_VERSION, '$.case.version')
    run = _run_options(values.get('run', {}))
    identity = {'id': manifest['id'], 'revision': manifest['revision'], 'digest': actual_digest}
    supplied_identity = values.get('template')
    keys(supplied_identity, ('id', 'revision', 'digest'), '$.case.template')
    if (type(supplied_identity.get('revision')) is not int or supplied_identity != identity):
        fail('STALE_TEMPLATE', 'case identity, revision and digest must match the captured template; migrate explicitly', '$.case.template')
    supplied = values.get('values')
    keys(supplied, manifest['parameters'], '$.case.values')
    document, resolved, bindings = copy.deepcopy(body), {}, []
    for parameter, spec in manifest['parameters'].items():
        location = '$.case.values.' + parameter
        if parameter not in supplied and 'default' not in spec:
            fail('MISSING_PARAMETER', 'supply this required parameter', location)
        value = supplied[parameter] if parameter in supplied else spec['default']
        _value(value, spec, location)
        parts = _pointer(spec['target']['pointer'], location, binding=True)
        parent, key = _target(document, parts, location)
        bindings.append({'parameter': parameter, 'target': copy.deepcopy(spec['target']),
                         'source': 'case' if parameter in supplied else 'default',
                         'previous': copy.deepcopy(parent[key]), 'value': copy.deepcopy(value)})
        resolved[parameter] = copy.deepcopy(value)
        parent[key] = copy.deepcopy(value)
    from .unfilled import reject_unfilled
    reject_unfilled(document)
    workflow.inspect_plan(document)
    return {'document': document, 'template': identity, 'values': resolved,
            'bindings': bindings, 'digest': storage.digest(document), 'run': run}


def prepare_template(path, values, *, planning=False):
    """Shared CLI/service preparation; values is the parsed case JSON object."""
    result = bind_values(load_template(path), values)
    if planning:
        result['plan'] = workflow.inspect_plan(result['document'])
    return result
