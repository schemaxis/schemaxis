"""Workflow provenance for embedded geometry and image inputs."""
from schemaxis.artifacts import file_digest
from schemaxis.errors import fail

def reusableInputs(document):
    from .adaptor import plan
    try:
        return {n['options']['file']: file_digest(n['options']['file'])
                for n in plan(document)['nodes'] if n['filter'] in ('readGLTF', 'sprite3D')}
    except OSError as error:
        fail('RESOURCE_NOT_FOUND', str(error), str(error.filename))
