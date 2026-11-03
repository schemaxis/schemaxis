# Copyright (C) 2026 David L F Gaden
"""Expose unfinished runtime inputs through the existing template parameter contract."""
import copy
import re

from .errors import fail
from .unfilled import find_unfilled


def parameter_spec(marker, pointer):
    """Translate a Studio field into a supported, constrained case parameter."""
    field_type = marker.get('type', 'json')
    kinds = {'number': 'number', 'integer': 'integer', 'boolean': 'boolean', 'enum': 'enum',
             'string': 'string', 'path': 'string', 'field': 'string', 'nodeRef': 'string',
             'axisRef': 'string', 'id': 'string', 'vector3': 'vector', 'colour': 'vector', 'bounds': 'vector'}
    if field_type not in kinds or 'template' in marker:
        fail('UNSUPPORTED_PARAMETER_KIND', 'fill this value before exposing it; choose a scalar or numeric vector',
             pointer, type=field_type)
    spec = {'label': marker.get('label', str(marker['$fill'])), 'kind': kinds[field_type]}
    constraints = {}
    if spec['kind'] in ('number', 'integer', 'vector'):
        constraints.update({key: marker[key] for key in ('minimum', 'maximum') if key in marker})
    if spec['kind'] == 'string':
        constraints.update({key: marker[key] for key in ('minLength', 'maxLength') if key in marker})
    if spec['kind'] == 'enum':
        constraints['enum'] = copy.deepcopy(marker.get('values', []))
    if spec['kind'] == 'vector':
        constraints['length'] = 6 if field_type == 'bounds' else 3
    if constraints:
        spec['constraints'] = constraints
    for key in ('default', 'units', 'help'):
        if key in marker:
            spec[key] = copy.deepcopy(marker[key])
    return spec


def expose_unfilled(document):
    """Atomically move runtime markers to workflow settings and declare parameters.

    Structural fields (IDs, filters, ports and versions) cannot be case parameters.
    Repeated markers in the same operation share one parameter and one case value.
    """
    from . import workflow_design as design
    from .adaptor_runtime import workflow_inputs
    design._require_v2(document)
    effective = workflow_inputs(document['workflow'], defer_unfilled=True)
    result = copy.deepcopy(document)
    taken = set(result.get('parameters', {})) | set(result['workflow'].get('settings', {}))
    exposed = {spec['target']['pointer'] for spec in result.get('parameters', {}).values()}
    groups = {}
    for field in find_unfilled(document):
        pointer = field['pointer']
        parts = design._parts(pointer, pointer)
        if parts[:1] != ('workflow',):
            fail('INVALID_PARAMETER', 'only runtime inputs inside the workflow can be exposed', pointer)
        local = parts[1:]
        if '/' + '/'.join(design._escape(part) for part in local) in exposed:
            continue
        if local[:1] == ('operations',) and len(local) > 3 and local[2] == 'document':
            scope = local[3:]
            if not design._input_scope(scope):
                fail('INVALID_PARAMETER', 'fill structural fields before exposing runtime inputs', pointer)
            operation = effective['operations'][int(local[1])]['id']
            for connection in document['connections']:
                if connection['to']['operation'] != operation:
                    continue
                port = document['ports'][operation]['inputs'][connection['to']['port']]
                target = design._parts(port['target'], pointer)
                if target[:len(scope)] == scope or scope[:len(target)] == target:
                    fail('INVALID_PARAMETER', 'disconnect this input before exposing it', pointer)
        elif len(local) >= 2 and local[0] in ('settings', 'dimensions', 'definitions'):
            operation = 'workflow'
        else:
            fail('INVALID_PARAMETER', 'fill structural fields before exposing runtime inputs', pointer)
        marker = design._lookup(document, parts, pointer)
        spec = parameter_spec(marker, pointer)
        group = (operation, str(marker['$fill']))
        if group in groups:
            identity, previous = groups[group]
            if previous != spec:
                fail('INVALID_PARAMETER', 'repeated fields must agree on their type and constraints', pointer)
        else:
            base = re.sub(r'[^A-Za-z0-9_.-]', '-', operation + '-' + str(marker['$fill']))
            identity = design._fresh(taken, base)
            taken.add(identity)
            groups[group] = (identity, spec)
            target = '/settings/' + identity
            result['workflow'].setdefault('settings', {})[identity] = copy.deepcopy(marker)
            result.setdefault('parameters', {})[identity] = {
                **spec, 'target': {'scope': 'workflow', 'pointer': target}}
        design._replace(result, parts, {'$document': '/settings/' + identity, 'scope': 'workflow'}, pointer)
    design.validate(result)
    return result
