# Copyright (C) 2026 David L F Gaden
"""Application-specific console policy; session persistence stays in the framework."""
import copy
from schemaxis.errors import fail
from .adaptor import plan
from schemaxis.adaptors.registry import declarations


def validate(document, draft=True):
    if draft and document.get('scenes') == []:
        from schemaxis.pipeline import DefinitionGraph
        candidate = copy.deepcopy(document)
        candidate['version'] = 'schemaxis/1'
        graph = DefinitionGraph(candidate, declarations('blender'))
        return {'status': 'draft', 'pipeline': graph.to_dict()}
    return plan(document)


def add(document, identity, operation, renderable):
    if not document['scenes'] and renderable:
        document['scenes'] = [{'id': 'view', 'visible': [identity], 'images': [{'id': 'image', 'size': [640, 480], 'cameras': [{'direction': [1, -1, 1]}]}]}]


def show(document, identity, renderable):
    if not document.get('scenes'): fail('UNSUPPORTED_COMMAND', 'declare a scene before choosing visible output')
    if not renderable: fail('TYPE_MISMATCH', 'visible output must be renderable')
    document['scenes'][0]['visible'] = [identity]
