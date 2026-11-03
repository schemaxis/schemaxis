# Copyright (C) 2026 David L F Gaden
"""Application-owned scene and settings schemas; host-safe."""
from schemaxis.schema import NAME, DRAFT, object_schema, arguments_schema, argument_schema, option_schema, graph_document_schema
from schemaxis.camera import CAMERA
from .publication import STYLE


def scene_schema(catalogue, definitions):
    image = object_schema({'id': NAME, 'size': {'type': 'array', 'items': {'type': 'integer',
        'minimum': 32, 'maximum': 8192}, 'minItems': 2, 'maxItems': 2,
        'default': [640, 480]},
        'cameras': {'type': 'array', 'minItems': 1, 'items': arguments_schema(CAMERA, dynamic=True)}}, ['id', 'cameras'])
    images = {'type': 'array', 'items': image}
    styles = {'type': 'object', 'additionalProperties': arguments_schema(STYLE, dynamic=True)}
    readbacks = []
    for reader, declaration in catalogue.items():
        filenames = [k for k, v in declaration['options'].items() if v.get('constructor') and 'vtkSMFileListDomain' in v.get('nativeDomains', [])]
        if declaration.get('role') == 'writer' or declaration['inputs'] or len(filenames) != 1: continue
        # Every file-list option is managed: a secondary one (for example Exodus FilePattern/FilePrefix)
        # could point the readback at a different file than the written artefact.
        options = option_schema({**declaration, 'options': {k: v for k, v in declaration['options'].items()
                                                            if 'vtkSMFileListDomain' not in v.get('nativeDomains', [])}})
        readbacks.append(object_schema({'operation': {'const': reader}, 'options': options},
            ['operation'] + (['options'] if options.get('required') else [])))
    definitions['readback'] = {'anyOf': [{'type': 'null'}, {'oneOf': readbacks}]}
    export_variants = []
    for name, declaration in catalogue.items():
        if declaration.get('role') != 'writer': continue
        export_variants.append(object_schema({
            'id': NAME, 'node': NAME, 'writer': {'const': name},
            'options': {'$ref': '#/$defs/options-' + name},
            'resources': object_schema({key:NAME for key,spec in declaration['inputs'].items()
                                        if spec.get('kind','data')!='data'}),
            'extension': {'enum': declaration['publication']['extensions']},
            'comparison': {'enum': ['exact', 'geometry', 'pixels', 'table', 'semantic']},
            'tolerance': {'type': 'number', 'minimum': 0},
            'acceptLosses': {'type': 'array', 'items': {'type': 'string'}},
            'readback': {'$ref': '#/$defs/readback'}
        }, ['id', 'node', 'writer']))
    scene = object_schema({'id': NAME, 'visible': styles, 'images': images,
        'exports': {'type': 'array', 'items': {'oneOf': export_variants}},
        'geometry': {'type': 'array', 'items': NAME}, 'gltf': {'type': 'boolean', 'default': False},
        'appearances': {'type': 'array', 'minItems': 1, 'items': styles, 'default': [{}]},
        'measurements': {'type': 'array', 'items': object_schema({'node': NAME,
            'association': {'enum': ['POINTS', 'CELLS', 'ROWS'], 'default': 'POINTS'}}, ['node'])}}, ['id'])
    return scene


def document_schema():
    reference = {'oneOf': [NAME, object_schema({'node': NAME, 'port': {'type': 'integer', 'minimum': 0}}, ['node', 'port'])]}
    return graph_document_schema('paraview', scene_schema, reference=reference, source_times=True)


def style_schema():
    return arguments_schema(STYLE)


def time_schema():
    from schemaxis.core.times import TIMES_ARGUMENT
    return argument_schema(TIMES_ARGUMENT)


def runtime_variants():
    return [object_schema({'$sample': NAME, 'association': {'enum': ['POINTS', 'CELLS', 'ROWS']},
        'field': {'type': 'string', 'minLength': 1},
        'index': {'anyOf': [{'type': 'integer', 'minimum': 0}, {'$ref': '#/$defs/runtime'}]},
        'component': {'type': 'integer', 'minimum': 0},
        'block': {'type': 'array', 'items': {'type': 'integer', 'minimum': 0}}},
        ['$sample', 'association', 'field', 'index'])]
