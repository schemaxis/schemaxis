# Copyright (C) 2026 David L F Gaden
"""Application-specific console policy; session persistence stays in the framework."""
import copy
from schemaxis.errors import fail
from .job import plan, inspection_plan
from schemaxis.adaptors.registry import declarations


def validate(document, draft=True):
    from schemaxis.adaptors import registry
    from schemaxis.adaptor_runtime import plan as prepare
    _, route = registry.resolve(document)
    checked = prepare(document, route, lambda value: validate_visit(value, draft))
    if isinstance(checked, dict) and checked.get('version') == 'schemaxis.study.plan/1':
        for visit in checked['visits']:
            if isinstance(visit['plan'], dict) and visit['plan'].get('deferred'):
                return visit['plan']
    return checked


def validate_visit(document, draft):
    if isinstance(document.get('times'), dict):
        inspection_plan(document, draft=draft)
        # This is validation, not a plan with guessed source times.
        return {'status': 'deferred', 'deferred': True, 'code': 'TIME_INSPECTION_REQUIRED',
                'message': 'Input checked; Run will inspect the source to select stored times.'}
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
