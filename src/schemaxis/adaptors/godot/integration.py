# Copyright (C) 2026 David L F Gaden
"""Workflow provenance for embedded geometry and image inputs."""
from schemaxis.artifacts import file_digest
from schemaxis.errors import fail

def reusableInputs(document):
    from .adaptor import plan
    try:
        inputs = {}
        for node in plan(document)['nodes']:
            if node['filter'] in ('readGLTF', 'sprite3D', 'animatedSprite3D'):
                for field in ('file', 'metadata'):
                    if field in node['options']:
                        inputs[node['options'][field]] = file_digest(node['options'][field])
        return inputs
    except OSError as error:
        fail('RESOURCE_NOT_FOUND', str(error), str(error.filename))
