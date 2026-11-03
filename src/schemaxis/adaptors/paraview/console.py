# Copyright (C) 2026 David L F Gaden
"""Application-specific console policy; session persistence stays in the framework."""
import copy
from schemaxis.errors import fail
from .job import plan
from schemaxis.adaptors.registry import declarations


def validate(document, draft=True):
    if draft and document.get('scenes') == []:
        from schemaxis.pipeline import DefinitionGraph
        candidate = copy.deepcopy(document)
        candidate['version'] = 'schemaxis/1'
        graph = DefinitionGraph(candidate, declarations('paraview'))
        return {'status': 'draft', 'pipeline': graph.to_dict()}
    return plan(document)


def add(document, identity, operation, renderable):
    if not document['scenes'] and renderable:
        document['scenes'] = [{'id': 'view', 'visible': {identity: {}}, 'geometry': [identity]}]


def show(document, identity, renderable):
    if not document.get('scenes'): fail('UNSUPPORTED_COMMAND', 'declare a scene before choosing visible output')
    if not renderable: fail('TYPE_MISMATCH', 'visible output must be renderable')
    document['scenes'][0]['visible'] = {identity: {}}
    document['scenes'][0]['geometry'] = [identity]
