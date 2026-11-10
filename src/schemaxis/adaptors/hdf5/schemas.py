"""Literal JSON Schema for schemaxis.hdf5/1 with one $defs record per reusable HDF5 concept."""
from schemaxis.schema import DRAFT, argument_schema, object_schema
from . import model

DEFS = [('scalarType', model.SCALAR_TYPE), ('member', model.MEMBER), ('field', model.FIELD), ('type', model.TYPE),
        ('selectionSlice', model.SELECTION_SLICE), ('selection', model.SELECTION), ('target', model.TARGET), ('data', model.DATA),
        ('externalSegment', model.EXTERNAL), ('storage', model.STORAGE), ('virtualSource', model.VSOURCE), ('virtual', model.VIRTUAL),
        ('generated', model.GENERATED), ('attribute', model.ATTRIBUTE), ('dimension', model.DIMENSION), ('object', model.OBJECT), ('link', model.LINK),
        ('input', model.INPUT), ('dependency', model.DEPENDENCY), ('file', model.FILE), ('extract', model.EXTRACT),
        ('expectation', model.EXPECT), ('edit', model.EDIT), ('cells', model.CELLS), ('mesh', model.MESH),
        ('meshField', model.MESH_FIELD), ('series', model.SERIES), ('tolerance', model.COMPARE), ('access', model.ACCESS),
        ('parallelRead', model.PARALLEL_READ), ('condition', model.CONDITION)]


def strip(spec):
    return {k: v for k, v in spec.items() if k not in ('required', 'default')}


def lookup(spec):
    s = strip(spec)
    for name, d in DEFS:
        if s == strip(d) and spec.get('type') == 'object':
            return name
    return None


def project(spec, top=None):
    """Project a declaration, replacing known records with $ref (defaults kept as annotations)."""
    name = lookup(spec)
    if name is not None and name != top:
        out = {'$ref': '#/$defs/' + name}
        if 'default' in spec:
            out['default'] = spec['default']
        return out
    kind = spec['type']
    if kind == 'object':
        props = {k: project(v) for k, v in spec['properties'].items()}
        out = object_schema(props, [k for k, v in spec['properties'].items() if v.get('required')])
    elif kind == 'array':
        out = {'type': 'array', 'items': project(spec['items'])}
        for key in ('minItems', 'maxItems', 'uniqueItems'):
            if key in spec:
                out[key] = spec[key]
    elif kind == 'union':
        out = {'anyOf': [project(o) for o in spec['options']]}
    else:
        out = argument_schema(spec)
        out.pop('default', None)
    if 'default' in spec:
        out['default'] = spec['default']
    return out


def schema():
    defs = {name: project(spec, top=name) for name, spec in DEFS}
    branches = []
    properties = {'version': {'const': model.VERSION}, 'operation': {'enum': list(model.OPERATIONS)}}
    for op in model.OPERATIONS:
        options = model.OPTIONS[op]
        props = {'version': {'const': model.VERSION}, 'operation': {'const': op}, **{k: project(v) for k, v in options.items()}}
        branches.append(object_schema(props, ['version', 'operation', *[k for k, v in options.items() if v.get('required')]]))
        for key, value in props.items():
            if key in ('version', 'operation'):
                continue
            if key not in properties:
                properties[key] = value
            elif properties[key] != value:
                current = properties[key].get('anyOf', [properties[key]]) if 'anyOf' in properties[key] and '$ref' not in properties[key] else [properties[key]]
                if value not in current:
                    properties[key] = {'anyOf': [*current, value]}
    return {'$schema': DRAFT, **object_schema(properties, ['version', 'operation']), 'oneOf': branches, '$defs': defs}
